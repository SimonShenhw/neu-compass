"""Apply doc-expansion JSONL to a DB + build the acronym glossary (ADR-0020).

Three subcommands in one script (all idempotent):

  filter   Doc2Query-- style relevance filtering: score every generated
           query against its source course's raw_text with the production
           reranker and drop pairs below --min-sigmoid. Run this INSIDE the
           NAS container (the PC venv's torch is broken; the int8 OpenVINO
           reranker is the production scorer anyway). Writes a filtered
           JSONL next to the input.
  apply    ALTER courses ADD search_expansion (if missing) + UPDATE each
           course's expansion text from the JSONL. Dry-run unless --commit.
  glossary Aggregate mined acronyms into data/acronym_glossary.json
           ({ACRO: [senses...]}, max 3 senses, junk filtered).

Typical sequence:
  PC : uv run python scripts/generate_doc_expansion.py --db-path ...
  NAS: docker run ... python scripts/apply_doc_expansion.py filter \
         --jsonl /data/doc_expansion/expansions.jsonl
  NAS: docker run ... python scripts/apply_doc_expansion.py apply \
         --jsonl /data/doc_expansion/expansions.filtered.jsonl \
         --db-path /data/courses.db --commit
  PC : same apply against ~/neu-compass-data/courses.db (dev parity)
  PC : uv run python scripts/apply_doc_expansion.py glossary \
         --jsonl data/doc_expansion/expansions.filtered.jsonl --commit
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ACRO_OK_RE = re.compile(r"^[A-Za-z]{2,6}$")


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:  # noqa: BLE001 — tolerate a torn tail line
            continue
    return rows


def cmd_filter(args) -> int:
    """Reranker-score (query, course raw_text) pairs; drop weak queries.

    Doc2Query-- (ECIR'23): pruning hallucinated/irrelevant generated
    queries beats indexing everything (+16% effectiveness in their runs).
    zh_keywords / keywords are kept as-is — they're terms, not queries,
    and the cross-encoder isn't calibrated for bare keyword inputs.
    """
    import structlog  # noqa: PLC0415

    from api.main import _build_inference_stack  # noqa: PLC0415
    from db.connection import connect  # noqa: PLC0415

    src = Path(args.jsonl)
    out = src.with_suffix(".filtered.jsonl")
    rows = _load_jsonl(src)
    print(f"=> {len(rows)} expansion rows from {src}")

    _, reranker = _build_inference_stack(structlog.get_logger("docexp_filter"))
    if reranker is None:
        print("ERROR: reranker unavailable; cannot filter")
        return 1

    conn = connect(args.db_path)
    kept = dropped = 0
    try:
        with out.open("w", encoding="utf-8") as fh:
            for i, row in enumerate(rows):
                r = conn.execute(
                    "SELECT COALESCE(raw_text,'') AS t FROM courses "
                    "WHERE course_id = ?",
                    (row["course_id"],),
                ).fetchone()
                if r is None or not r["t"]:
                    continue
                queries = row.get("student_queries", [])
                if queries:
                    # One reranker pass per course: query-vs-own-doc.
                    scores = [
                        reranker.score(q, [r["t"]])[0] for q in queries
                    ]
                    keep = [
                        q for q, s in zip(queries, scores)
                        if s >= args.min_sigmoid
                    ]
                    dropped += len(queries) - len(keep)
                    kept += len(keep)
                    row["student_queries"] = keep
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                if (i + 1) % 500 == 0:
                    print(f"   {i + 1}/{len(rows)} (kept={kept} dropped={dropped})")
    finally:
        conn.close()
    print(f"=> queries kept={kept} dropped={dropped} -> {out}")
    return 0


def cmd_apply(args) -> int:
    from db.connection import connect  # noqa: PLC0415

    rows = _load_jsonl(Path(args.jsonl))
    conn = connect(args.db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(courses)")}
        if "search_expansion" not in cols:
            print("=> ALTER TABLE courses ADD COLUMN search_expansion TEXT")
            if args.commit:
                conn.execute(
                    "ALTER TABLE courses ADD COLUMN search_expansion TEXT"
                )

        updated = 0
        for row in rows:
            parts = (
                row.get("student_queries", [])
                + row.get("keywords", [])
                + row.get("zh_keywords", [])
            )
            text = "\n".join(p.strip() for p in parts if p and p.strip())
            if not text:
                continue
            if args.commit:
                cur = conn.execute(
                    "UPDATE courses SET search_expansion = ? WHERE course_id = ?",
                    (text, row["course_id"]),
                )
                updated += cur.rowcount
            else:
                updated += 1
        if args.commit:
            conn.commit()
        print(f"=> {'updated' if args.commit else 'would update'} {updated} "
              f"courses ({'committed' if args.commit else 'DRY RUN'})")
    finally:
        conn.close()
    return 0


def cmd_glossary(args) -> int:
    from rag.hybrid import STOPWORDS  # noqa: PLC0415

    rows = _load_jsonl(Path(args.jsonl))
    senses: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        for a in row.get("acronyms", []):
            acro = (a.get("acronym") or "").strip().upper()
            exp = (a.get("expansion") or "").strip()
            if not _ACRO_OK_RE.match(acro) or not exp:
                continue
            if acro.lower() in STOPWORDS:
                continue
            # Junk guard: an "expansion" that's just the acronym again, or
            # implausibly short, carries no retrieval signal.
            if len(exp) < 6 or exp.upper() == acro:
                continue
            senses[acro][exp.lower()] += 1

    glossary = {
        acro: [s for s, _ in counter.most_common(3)]
        for acro, counter in sorted(senses.items())
        if counter
    }
    out = Path(args.out)
    print(f"=> {len(glossary)} acronyms mined "
          f"(multi-sense: {sum(1 for v in glossary.values() if len(v) > 1)})")
    if args.commit:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(glossary, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        print(f"=> wrote {out}")
    else:
        sample = dict(list(glossary.items())[:8])
        print(json.dumps(sample, indent=2, ensure_ascii=False))
        print("   (DRY RUN — pass --commit to write)")
    return 0


def cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_filter = sub.add_parser("filter")
    p_filter.add_argument("--jsonl", required=True)
    p_filter.add_argument("--db-path", default="/data/courses.db")
    p_filter.add_argument(
        "--min-sigmoid", type=float, default=0.2,
        help="Drop generated queries scoring below this against their own "
        "course text (Doc2Query-- pruning).",
    )

    p_apply = sub.add_parser("apply")
    p_apply.add_argument("--jsonl", required=True)
    p_apply.add_argument("--db-path", required=True)
    p_apply.add_argument("--commit", action="store_true")

    p_gl = sub.add_parser("glossary")
    p_gl.add_argument("--jsonl", required=True)
    p_gl.add_argument(
        "--out", default=str(PROJECT_ROOT / "data" / "acronym_glossary.json")
    )
    p_gl.add_argument("--commit", action="store_true")

    args = ap.parse_args()
    return {"filter": cmd_filter, "apply": cmd_apply, "glossary": cmd_glossary}[
        args.cmd
    ](args)


if __name__ == "__main__":
    sys.exit(cli())
