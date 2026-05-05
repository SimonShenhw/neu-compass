"""Bulk-load Co-op seed records from a curated JSON file.

PLAN v2.2 §3.7 / PLAN v1.3 §6.5 — feed `coop_experiences` table with the
30-record team-curated set (12 quant_fintech / 8 big_tech / 5 biotech_health
/ 5 startup).

Idempotent: repeated runs upsert by `coop_id`. Exiting half-way is safe.

Behavior:
  - Validates each record via `CoopExperience` Pydantic model.
  - Server-side derives `visibility_level` from content presence (mirrors
    api/routes/coop.py:_derive_visibility) so seed entries follow the same
    rule as user uploads. Authors don't pick the tier.
  - Sets `is_seed_data=True` and `contributor_user_id=None` (no real user
    behind seed rows).
  - Writes a curation audit line to `redaction_audit` if the input lacks one.
  - Skips k=2 anonymity gate — seed data is curator-controlled and may
    legitimately be unique-by-design (e.g. one rare biotech role). Real-user
    uploads still go through the gate via `POST /coop`.

Usage:
  uv run python scripts/ingest_coop_seed.py \\
      --file data/coop_seed/curated.json --commit

  # dry-run (default): prints what would happen, no writes
  uv run python scripts/ingest_coop_seed.py \\
      --file data/coop_seed/curated.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import settings  # noqa: E402
from db.connection import connect  # noqa: E402
from db.coop_repository import CoopRepository  # noqa: E402
from schemas.coop import CoopExperience, Industry  # noqa: E402

EXPECTED_DISTRIBUTION = {
    Industry.QUANT_FINTECH.value: 12,
    Industry.BIG_TECH.value: 8,
    Industry.BIOTECH_HEALTH.value: 5,
    Industry.STARTUP.value: 5,
}

# Curated-v1 (the team's actual seed format) → CoopExperience field mapping.
# v1 ships richer per-row metadata (location, offer_status, f1_sponsor,
# interview_rounds_n, interview_duration_weeks) that the v0.1 schema can't
# store as first-class fields. We fold them into a structured prefix at the
# top of `interview_summary` so no information is lost; v0.2 schema can lift
# them into proper columns and a one-shot migration parses the prefix back.
_CURATED_V1_INDUSTRY_MAP = {
    "Quant": Industry.QUANT_FINTECH.value,
    "BigTech": Industry.BIG_TECH.value,
    "Biotech": Industry.BIOTECH_HEALTH.value,
    "Startup": Industry.STARTUP.value,
    "Consulting": Industry.CONSULTING.value,
}


def _bucket_hourly_usd(amount: int | float | None) -> str | None:
    """Round int hourly rate to a 10-wide bucket per PLAN §6.3 redaction
    policy (no exact figures). 100+ collapses to a single ceiling bucket."""
    if amount is None:
        return None
    n = int(amount)
    if n >= 100:
        return "$100+/hr"
    floor = (n // 10) * 10
    return f"${floor}-{floor + 10}/hr"


def _is_curated_v1(rec: dict) -> bool:
    """Detect the team's ad-hoc curated format by signature fields. The
    canonical CoopExperience-shaped records have `coop_id` + Industry-enum
    `industry`; v1 has integer `id` + free-text `category`."""
    return (
        "id" in rec
        and "category" in rec
        and "salary_hourly_usd" in rec
        and "coop_id" not in rec
    )


def _normalize_curated_v1(rec: dict) -> dict:
    """Map a curated-v1 record into a CoopExperience-shaped dict."""
    cat = rec.get("category", "Other")
    industry = _CURATED_V1_INDUSTRY_MAP.get(cat, Industry.OTHER.value)
    coop_id = f"seed-{cat.lower()}-{int(rec['id']):02d}"

    f1_str = "yes" if rec.get("f1_sponsor") else "no/case-by-case"
    location = rec.get("location", "?")
    rounds = rec.get("interview_rounds", "?")
    weeks = rec.get("interview_duration_weeks", "?")
    outcome = rec.get("offer_status", "?")

    summary_prefix = (
        f"[Location] {location}\n"
        f"[Outcome] {outcome} ({rounds} rounds over {weeks} weeks)\n"
        f"[F1 Sponsor] {f1_str}\n\n"
    )
    review = rec.get("review_content", "")

    return {
        "coop_id": coop_id,
        "company": rec["company"],
        "role": rec["role"],
        "industry": industry,
        "coop_term": rec.get("coop_term"),
        "related_courses": [],
        "interview_summary": summary_prefix + review,
        "salary_range_usd": _bucket_hourly_usd(rec.get("salary_hourly_usd")),
    }


def derive_visibility_level(rec: dict) -> int:
    """Mirror api/routes/coop.py:_derive_visibility — content drives the tier."""
    if rec.get("salary_range_usd"):
        return 2
    if rec.get("interview_summary") or rec.get("technical_questions"):
        return 1
    return 0


def cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--file", required=True,
        help="Path to curated JSON. Schema: see data/coop_seed/template.example.json",
    )
    ap.add_argument(
        "--commit", action="store_true",
        help="Actually write to SQLite. Default is dry-run (validate + report only).",
    )
    ap.add_argument("--db-path", default=None)
    args = ap.parse_args()

    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        raw_records = payload
    else:
        raw_records = payload.get("records", [])

    if not raw_records:
        print(f"=> {args.file} contains no records (looked under .records and root).")
        return 1

    db_path = args.db_path or settings.sqlite_path
    print(f"=> validating {len(raw_records)} record(s) from {args.file}")

    validated: list[CoopExperience] = []
    errors: list[tuple[str, str]] = []
    industry_counter: Counter[str] = Counter()

    n_v1_normalized = 0
    for idx, raw in enumerate(raw_records):
        # Strip non-schema metadata from template (_comment etc).
        record = {k: v for k, v in raw.items() if not k.startswith("_")}

        # Curated-v1 (team's actual format) → CoopExperience shape.
        if _is_curated_v1(record):
            record = _normalize_curated_v1(record)
            n_v1_normalized += 1

        coop_id = record.get("coop_id", f"<index {idx}>")

        # Server-side derivations override any author setting.
        record["is_seed_data"] = True
        record["contributor_user_id"] = None
        record["visibility_level"] = derive_visibility_level(record)
        record.setdefault(
            "redaction_audit",
            "[seed; curator did not record an audit line — fill in before ship]",
        )

        try:
            coop = CoopExperience.model_validate(record)
        except Exception as e:  # noqa: BLE001
            errors.append((coop_id, f"{type(e).__name__}: {e}"))
            continue

        validated.append(coop)
        if coop.industry:
            industry_counter[coop.industry.value] += 1

    if n_v1_normalized:
        print(f"   ({n_v1_normalized} record(s) normalized from curated-v1 format)")

    print(f"   ok: {len(validated)}   errors: {len(errors)}")
    for cid, msg in errors:
        print(f"     ✗ {cid}: {msg[:120]}")

    print("\n=> industry distribution vs target:")
    for industry, target in EXPECTED_DISTRIBUTION.items():
        actual = industry_counter.get(industry, 0)
        marker = "✓" if actual >= target else "⚠"
        print(f"   {marker} {industry:18s} {actual:3d} / {target}")
    extra = set(industry_counter) - set(EXPECTED_DISTRIBUTION)
    for industry in extra:
        print(f"   ?  {industry:18s} {industry_counter[industry]:3d} / 0 (off-target bucket)")

    if errors:
        print("\n=> validation errors above; fix before --commit")
        return 1

    if not args.commit:
        print("\n=> dry-run only; nothing written. Add --commit to ingest.")
        return 0

    conn = connect(db_path)
    try:
        repo = CoopRepository(conn)
        existing = {c.coop_id for c in repo.list_all()}
        added = 0
        upserted = 0
        for coop in validated:
            if coop.coop_id in existing:
                upserted += 1
            else:
                added += 1
            repo.add(coop)
        conn.commit()
        print(f"\n=> committed: {added} new + {upserted} upserted "
              f"({len(validated)} total)")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(cli())
