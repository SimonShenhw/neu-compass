"""Seed a program (with required courses + prerequisites) into the runtime DB.

Loads `data/program_seed/<program_id>.json` and upserts via ProgramRepository.
Idempotent — safe to re-run; updates existing rows in place.

从 `data/program_seed/<program_id>.json` 加载数据,通过 ProgramRepository
执行 upsert。幂等 —— 可以安全地重复运行;已存在的行会被原地更新。

Usage:
  uv run python scripts/seed_program.py --file data/program_seed/aai_ms.json
  uv run python scripts/seed_program.py --file data/program_seed/aai_ms.json --commit

用法:
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

# These imports must come after the sys.path.insert above (E402 suppressed
# accordingly) — they resolve local packages that only become importable
# once PROJECT_ROOT is on sys.path.
# 中文:这几个 import 必须写在上面 sys.path.insert 之后(因此抑制了 E402
# 告警)—— 它们解析的是本地包,只有 PROJECT_ROOT 被加入 sys.path 之后
# 才能被导入。
from config import settings  # noqa: E402
from db.program_repository import ProgramRepository  # noqa: E402
from schemas.program import (  # noqa: E402
    CoursePrerequisite,
    Program,
    ProgramRequiredCourse,
)


def _validate_courses_exist(conn: sqlite3.Connection, course_ids: set[str]) -> set[str]:
    """Return the set of course_ids in `course_ids` that don't exist in
    courses table — caller decides whether to abort or continue.

    中文:返回 `course_ids` 中在 courses 表里不存在的那部分 course_id ——
    要中止还是继续,由调用方决定。
    """
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
        # 中文:在写入带外键的行之前,先校验被引用的课程都存在。
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
        # 中文:健全性检查小结
        for sem in (1, 2, 3, 4):
            n = len(repo.list_required_courses(program.program_id, semester=sem))
            print(f"   semester {sem}: {n} courses")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(cli())
