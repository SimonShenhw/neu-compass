"""Bring an older runtime DB up to schema_version 1.1.

The runtime DB at `~/neu-compass-data/courses.db` was first init'd from an
older `db/init.sql` that lacked several `coop_experiences` columns and the
`user_courses` table entirely. `init.sql` itself uses `CREATE TABLE IF NOT
EXISTS` so re-running it adds NEW tables but doesn't ALTER existing ones —
hence this one-shot DDL migration.

Idempotent: safe to re-run. Each step checks current state before mutating.

Adds (if missing):
  - `coop_experiences.industry` (TEXT)
  - `coop_experiences.coop_term` (TEXT)
  - `coop_experiences.duration_months` (INTEGER; range check enforced at app layer)
  - `coop_experiences.technical_questions` (TEXT)
  - `coop_experiences.salary_range_usd` (TEXT)
  - `coop_experiences.redaction_audit` (TEXT)
  - `idx_coop_industry`, `idx_coop_term` indexes
  - `user_courses` table + indexes + trigger (via init.sql replay)
  - schema_versions row for '1.1'

NOT touched: existing rows, courses table, aliases, users.

Usage:
  uv run python scripts/migrate_db_to_v1_1.py            # dry-run report
  uv run python scripts/migrate_db_to_v1_1.py --commit
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import settings  # noqa: E402

# (column_name, ALTER TABLE column-spec). SQLite ALTER TABLE ADD COLUMN
# accepts type + DEFAULT but is finicky with CHECK constraints on existing
# tables — we keep these unconstrained at DDL level; Pydantic enforces.
COOP_COLUMNS = [
    ("industry", "TEXT"),
    ("coop_term", "TEXT"),
    ("duration_months", "INTEGER"),
    ("technical_questions", "TEXT"),
    ("salary_range_usd", "TEXT"),
    ("redaction_audit", "TEXT"),
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_coop_industry ON coop_experiences(industry)",
    "CREATE INDEX IF NOT EXISTS idx_coop_term ON coop_experiences(coop_term)",
]


def cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db-path", default=None)
    ap.add_argument(
        "--commit", action="store_true",
        help="Apply changes. Default is dry-run (report what would change).",
    )
    args = ap.parse_args()

    db_path = args.db_path or settings.sqlite_path
    init_sql_path = PROJECT_ROOT / "db" / "init.sql"

    print(f"=> target DB:  {db_path}")
    print(f"=> init.sql:   {init_sql_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # 1) State snapshot before changes.
        existing_coop_cols = {
            r["name"] for r in conn.execute("PRAGMA table_info(coop_experiences)")
        }
        has_user_courses = bool(conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_courses'"
        ).fetchone())
        existing_versions = {
            r["version"] for r in conn.execute("SELECT version FROM schema_versions")
        }

        missing_coop_cols = [
            name for name, _ in COOP_COLUMNS if name not in existing_coop_cols
        ]

        print("\n=> coop_experiences missing columns:", missing_coop_cols or "(none)")
        print(f"=> user_courses table exists:        {has_user_courses}")
        print(f"=> schema_versions present:          {sorted(existing_versions)}")

        if not args.commit:
            print("\n=> dry-run only; nothing applied. Add --commit to migrate.")
            return 0

        # 2) Apply ALTER TABLE for missing coop columns.
        added = []
        for name, type_def in COOP_COLUMNS:
            if name in existing_coop_cols:
                continue
            conn.execute(
                f"ALTER TABLE coop_experiences ADD COLUMN {name} {type_def}"
            )
            added.append(name)
        if added:
            print(f"\n=> added coop_experiences columns: {added}")

        # 3) Replay init.sql — adds user_courses + trigger + indexes.
        #    Existing tables are no-ops thanks to IF NOT EXISTS.
        conn.executescript(init_sql_path.read_text(encoding="utf-8"))
        print("=> replayed init.sql (idempotent CREATE IF NOT EXISTS)")

        # 4) Indexes that depend on the new columns.
        for sql in INDEXES:
            conn.execute(sql)

        conn.commit()
        print("\n=> committed.")

        # 5) Re-snapshot for confirmation.
        cur_versions = sorted(
            r["version"] for r in conn.execute("SELECT version FROM schema_versions")
        )
        print(f"=> schema_versions now:              {cur_versions}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(cli())
