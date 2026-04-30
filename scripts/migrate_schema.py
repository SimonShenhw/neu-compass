"""Apply schema migration to all rows in courses table.

Reads each row's stored schema_version, runs schemas.course.migrate() to
bring it up to current SCHEMA_VERSION, writes the migrated generated_json
back. Idempotent: rows already at current version are skipped.

Usage:
    python scripts/migrate_schema.py
    python scripts/migrate_schema.py --db-path /tmp/test.db
    python scripts/migrate_schema.py --dry-run     # report only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from db.connection import connect  # noqa: E402
from schemas.course import SCHEMA_VERSION, migrate  # noqa: E402


def migrate_all(db_path: str | Path, *, dry_run: bool = False) -> dict[str, int]:
    """Walk the courses table, apply migrate() to non-current rows.

    Returns {"already_current": N, "migrated": N, "errors": N}.
    """
    counts = {"already_current": 0, "migrated": 0, "errors": 0}

    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT course_id, schema_version, generated_json FROM courses"
        ).fetchall()

        for row in rows:
            current = row["schema_version"]
            if current == SCHEMA_VERSION:
                counts["already_current"] += 1
                continue

            try:
                old_data = json.loads(row["generated_json"])
                new_data = migrate(old_data, from_version=current)
            except Exception as e:
                counts["errors"] += 1
                print(f"  ERROR migrating {row['course_id']!r} ({current} -> {SCHEMA_VERSION}): {e}")
                continue

            if not dry_run:
                conn.execute(
                    """
                    UPDATE courses SET
                        generated_json = ?,
                        schema_version = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE course_id = ?
                    """,
                    (json.dumps(new_data), SCHEMA_VERSION, row["course_id"]),
                )
            counts["migrated"] += 1

        if not dry_run:
            conn.commit()
    finally:
        conn.close()

    return counts


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=None, help="Override settings.sqlite_path")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be migrated; no writes")
    args = parser.parse_args()

    if args.db_path:
        db_path: str | Path = args.db_path
    else:
        from config import settings  # noqa: PLC0415
        db_path = settings.sqlite_path

    mode = "DRY RUN" if args.dry_run else "APPLYING"
    print(f"=> {mode}: schema migration -> {SCHEMA_VERSION}")
    print(f"   db: {db_path}")
    counts = migrate_all(db_path, dry_run=args.dry_run)
    print(f"=> already current : {counts['already_current']}")
    print(f"   migrated        : {counts['migrated']}")
    print(f"   errors          : {counts['errors']}")

    return 1 if counts["errors"] else 0


if __name__ == "__main__":
    sys.exit(cli())
