"""Backfill course_prerequisites edges from catalog-scraped prereq codes.

The catalog scraper already extracts prerequisites as CLEAN course codes
(anchor tags, not free text) into Course.prereqs — for the whole catalog.
But only scripts/seed_program.py ever wrote course_prerequisites edges, so
the detail panel's prereq graph and the "what to take first" answers only
covered the 4 hand-seeded programs. This script converts the scraped codes
into edges for every indexed course: zero LLM, zero scraping, one pass.

Caveats encoded in the rows themselves:
  - The scraper flattens AND/OR prerequisite groups, so every edge is
    written as requirement='required' with a note flagging the flattening.
    A future parser can upgrade OR-groups to 'recommended' alternatives.
  - Codes whose course isn't in the catalog (retired/not-scraped) are
    skipped — the FK would reject them and the UI tolerates absence.
  - Hand-seeded program edges are preserved: the upsert only INSERTs
    missing pairs (ON CONFLICT DO NOTHING), never overwriting curated
    requirement tiers/notes.

Usage:
  uv run python scripts/backfill_prereq_edges.py                  # dry-run
  uv run python scripts/backfill_prereq_edges.py --commit
  docker exec neu-compass-api python scripts/backfill_prereq_edges.py \
      --db-path /data/courses.db --commit
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKFILL_NOTE = "parsed from catalog; AND/OR groups flattened"


def backfill(conn: sqlite3.Connection, *, commit: bool) -> dict[str, int]:
    """Insert missing prereq edges. Returns counters for the report."""
    code_to_id: dict[str, str] = {
        row["primary_code"]: row["course_id"]
        for row in conn.execute(
            "SELECT course_id, primary_code FROM courses"
        )
    }

    stats = {"courses_with_prereqs": 0, "edges_new": 0,
             "edges_existing": 0, "dangling_codes": 0, "self_refs": 0}

    rows = conn.execute(
        "SELECT course_id, generated_json FROM courses "
        "WHERE status = 'indexed'"
    ).fetchall()
    for row in rows:
        prereq_codes = json.loads(row["generated_json"]).get("prereqs") or []
        if not prereq_codes:
            continue
        stats["courses_with_prereqs"] += 1
        for code in prereq_codes:
            prereq_id = code_to_id.get(str(code).strip().upper())
            if prereq_id is None:
                stats["dangling_codes"] += 1
                continue
            if prereq_id == row["course_id"]:
                stats["self_refs"] += 1  # schema CHECK forbids; skip
                continue
            cur = conn.execute(
                """
                INSERT INTO course_prerequisites
                    (course_id, prereq_course_id, requirement, notes)
                VALUES (?, ?, 'required', ?)
                ON CONFLICT(course_id, prereq_course_id) DO NOTHING
                """,
                (row["course_id"], prereq_id, BACKFILL_NOTE),
            )
            if cur.rowcount:
                stats["edges_new"] += 1
            else:
                stats["edges_existing"] += 1

    if commit:
        conn.commit()
    else:
        conn.rollback()
    return stats


def cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db-path", default=None)
    ap.add_argument(
        "--commit", action="store_true",
        help="Apply changes. Default is dry-run (counts only, rolled back).",
    )
    args = ap.parse_args()

    from config import settings  # noqa: PLC0415

    db_path = args.db_path or settings.sqlite_path
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        total_before = conn.execute(
            "SELECT COUNT(*) FROM course_prerequisites"
        ).fetchone()[0]
        stats = backfill(conn, commit=args.commit)
        print(f"=> target DB: {db_path}")
        print(f"=> edges before: {total_before}")
        for k, v in stats.items():
            print(f"   {k}: {v}")
        print("=> committed." if args.commit
              else "=> dry-run; pass --commit to apply.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(cli())
