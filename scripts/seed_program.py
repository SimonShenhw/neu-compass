"""Seed a program (with required courses + prerequisites) into the runtime DB.

Loads `data/program_seed/<program_id>.json` and upserts via ProgramRepository.
Idempotent — safe to re-run; updates existing rows in place.

Usage:
  uv run python scripts/seed_program.py --file data/program_seed/aai_ms.json
  uv run python scripts/seed_program.py --file data/program_seed/aai_ms.json --commit
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

from config import settings  # noqa: E402
from db.program_repository import ProgramRepository  # noqa: E402
from schemas.program import (  # noqa: E402
    CoursePrerequisite,
    Program,
    ProgramRequiredCourse,
)


def _validate_courses_exist(conn: sqlite3.Connection, course_ids: set[str]) -> set[str]:
    """Return the set of course_ids in `course_ids` that don't exist in
    courses table — caller decides whether to abort or continue."""
    placeholders = ",".join("?" * len(course_ids))
    rows = conn.execute(
        f"SELECT course_id FROM courses WHERE course_id IN ({placeholders})",
        list(course_ids),
    ).fetchall()
    found = {r["course_id"] for r in rows}
    return course_ids - found


def cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True, help="Path to a program seed JSON.")
    ap.add_argument("--db-path", default=None)
    ap.add_argument(
        "--commit", action="store_true",
        help="Apply changes. Default is dry-run.",
    )
    args = ap.parse_args()

    seed_path = Path(args.file).resolve()
    if not seed_path.exists():
        print(f"!! seed file not found: {seed_path}", file=sys.stderr)
        return 1
    payload = json.loads(seed_path.read_text(encoding="utf-8"))

    program = Program(**payload["program"])
    required = [ProgramRequiredCourse(program_id=program.program_id, **r)
                for r in payload.get("required_courses", [])]
    prereqs = [CoursePrerequisite(**r) for r in payload.get("prerequisites", [])]

    db_path = args.db_path or settings.sqlite_path
    print(f"=> seed file:  {seed_path.name}")
    print(f"=> target DB:  {db_path}")
    print(f"=> program:    {program.program_id} ({program.full_name})")
    print(f"=> courses:    {len(required)} required edges")
    print(f"=> prereqs:    {len(prereqs)} prerequisite edges")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row

    try:
        # Validate referenced courses exist before writing FK rows.
        referenced = (
            {r.course_id for r in required}
            | {p.course_id for p in prereqs}
            | {p.prereq_course_id for p in prereqs}
        )
        missing = _validate_courses_exist(conn, referenced)
        if missing:
            print(f"!! {len(missing)} referenced course_ids not in courses table:")
            for cid in sorted(missing)[:10]:
                print(f"   - {cid}")
            print(f"   abort — fix the seed file or ingest these courses first.")
            return 2

        if not args.commit:
            print("=> dry-run; pass --commit to apply.")
            return 0

        repo = ProgramRepository(conn)
        repo.upsert_program(program)
        for edge in required:
            repo.upsert_required_course(edge)
        for prereq in prereqs:
            repo.upsert_prerequisite(prereq)
        conn.commit()

        print(f"=> committed.")
        # Sanity recap
        for sem in (1, 2, 3, 4):
            n = len(repo.list_required_courses(program.program_id, semester=sem))
            print(f"   semester {sem}: {n} courses")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(cli())
