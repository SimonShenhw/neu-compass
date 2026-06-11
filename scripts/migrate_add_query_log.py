"""Add the query_log table to an EXISTING database (fresh DBs get it from
db/init.sql). Idempotent; dry-run by default.

Usage:
  PC : uv run python scripts/migrate_add_query_log.py \
         --db-path ~/neu-compass-data/courses.db --commit
  NAS: docker exec neu-compass-api python scripts/migrate_add_query_log.py \
         --db-path /data/courses.db --commit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DDL = """
CREATE TABLE IF NOT EXISTS query_log (
    log_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    route             TEXT NOT NULL CHECK (route IN ('search', 'chat')),
    query             TEXT NOT NULL,
    matched_via       TEXT,
    k                 INTEGER,
    latency_ms        REAL,
    result_course_ids TEXT,
    rejection_reason  TEXT,
    user_id           TEXT
);
CREATE INDEX IF NOT EXISTS idx_query_log_created ON query_log(created_at);
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db-path", required=True)
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    from db.connection import connect  # noqa: PLC0415

    conn = connect(str(Path(args.db_path).expanduser()))
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='query_log'"
        ).fetchone()
        if exists:
            print("=> query_log already present — nothing to do")
            return 0
        print("=> would create query_log table + index")
        if args.commit:
            conn.executescript(DDL)
            conn.commit()
            print("=> created (committed)")
        else:
            print("   (DRY RUN — pass --commit to apply)")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
