"""Run db/init.sql against the configured SQLite path. Idempotent.

Usage:
    python scripts/init_db.py                   # uses settings.sqlite_path
    python scripts/init_db.py --path tmp.db     # custom path
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INIT_SQL_PATH = PROJECT_ROOT / "db" / "init.sql"


def init_database(db_path: str | Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    sql = INIT_SQL_PATH.read_text(encoding="utf-8")

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(sql)
        conn.commit()

        version_row = conn.execute(
            "SELECT version FROM schema_versions ORDER BY applied_at DESC LIMIT 1"
        ).fetchone()
        table_count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
    finally:
        conn.close()

    print(f"OK Initialized SQLite at {db_path}")
    print(f"   Schema version: {version_row[0] if version_row else 'unknown'}")
    print(f"   Tables: {table_count}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path", default=None,
        help="Override sqlite_path from .env settings",
    )
    args = parser.parse_args()

    if args.path:
        db_path: str | Path = args.path
    else:
        sys.path.insert(0, str(PROJECT_ROOT))
        from config import settings  # noqa: PLC0415 (lazy import: only load .env when needed)
        db_path = settings.sqlite_path

    init_database(db_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
