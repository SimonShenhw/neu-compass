"""Add the private Co-op queue and credit ledger; dry-run unless --commit.

Usage: python scripts/migrate_coop_submissions.py --db-path COPY.db [--commit]
Back up the existing runtime DB first. This never imports or overwrites UGC.
中文：显式指定已有数据库；默认只读检查，--commit 才执行加表迁移。
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TABLES = {"coop_submissions", "coop_contribution_credits"}


def migration_sql() -> str:
    sql = (PROJECT_ROOT / "db" / "init.sql").read_text(encoding="utf-8")
    return sql.split("-- BEGIN COOP_MODERATION_V1_3", 1)[1].split("-- END COOP_MODERATION_V1_3", 1)[0]


def migrate(db_path: str | Path, *, commit: bool = False) -> list[str]:
    path = Path(db_path).resolve(strict=True)
    mode = "rw" if commit else "ro"
    conn = sqlite3.connect(f"{path.as_uri()}?mode={mode}", uri=True)
    try:
        existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"users", "coop_experiences", "schema_versions"}.issubset(existing):
            raise ValueError("Apply the existing runtime schema before this additive migration")
        missing = sorted(TABLES - existing)
        if commit:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            try:
                conn.executescript("BEGIN IMMEDIATE;\n" + migration_sql() + "\nCOMMIT;")
            except Exception:
                conn.rollback()
                raise
        return missing
    finally:
        conn.close()


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    try:
        missing = migrate(args.db_path, commit=args.commit)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"Migration failed ({type(exc).__name__}); runtime DB not replaced.")
        return 1
    print(f"{'Applied additive migration' if args.commit else 'Read-only dry-run'}; missing tables: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
