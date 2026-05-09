"""Bring an existing runtime DB up to schema_version 1.2 (PLAN v3.0 Layer 3).

Adds three tables (and their indexes) to support the program-aware chat path:

  - `programs`                    — NEU programs (AAI / CS / DS / ...)
  - `program_required_courses`    — program -> course curriculum mapping
  - `course_prerequisites`        — course -> course "must take first"

Idempotent: the underlying DDL uses `CREATE TABLE IF NOT EXISTS`, so re-running
this script is a no-op once tables already exist. Seeding (e.g. AAI program
data) is a separate step — see `scripts/seed_aai_program.py`.

Usage:
  uv run python scripts/migrate_db_to_v1_2.py            # dry-run report
  uv run python scripts/migrate_db_to_v1_2.py --commit
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

NEW_TABLES = ("programs", "program_required_courses", "course_prerequisites")


def _existing_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {r["name"] for r in rows}


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
        before = _existing_tables(conn)
        missing = [t for t in NEW_TABLES if t not in before]

        if not missing:
            current_versions = [
                r["version"] for r in conn.execute(
                    "SELECT version FROM schema_versions ORDER BY version"
                ).fetchall()
            ]
            print(f"=> All v1.2 tables already present.  schema_versions={current_versions}")
            return 0

        print(f"=> tables missing: {missing}")

        if not args.commit:
            print("=> dry-run; pass --commit to apply.")
            return 0

        # Apply by replaying init.sql. The IF NOT EXISTS clauses make this
        # safe — only the new v1.2 tables / indexes get created; everything
        # else is a no-op. Same trick as migrate_db_to_v1_1.py.
        conn.executescript(init_sql_path.read_text(encoding="utf-8"))
        conn.commit()

        after = _existing_tables(conn)
        added = sorted(after - before)
        print(f"=> added: {added}")

        # Pin schema_versions row even if it was already added by the script
        # (INSERT OR IGNORE is idempotent at the DDL level).
        applied = [
            r["version"] for r in conn.execute(
                "SELECT version FROM schema_versions ORDER BY version"
            ).fetchall()
        ]
        print(f"=> schema_versions: {applied}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(cli())
