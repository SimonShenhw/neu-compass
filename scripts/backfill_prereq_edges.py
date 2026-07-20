"""Backfill course_prerequisites edges from catalog-scraped prereq codes.

The catalog scraper already extracts prerequisites as CLEAN course codes
(anchor tags, not free text) into Course.prereqs — for the whole catalog.
But only scripts/seed_program.py ever wrote course_prerequisites edges, so
the detail panel's prereq graph and the "what to take first" answers only
covered the 4 hand-seeded programs. This script converts the scraped codes
into edges for every indexed course: zero LLM, zero scraping, one pass.

目录爬虫早就已经把先修课提取成了干净的课程代码(anchor 标签,不是自由
文本)存进了 Course.prereqs —— 覆盖整个目录。但过去只有
scripts/seed_program.py 会写 course_prerequisites 边,所以详情面板的
先修课关系图和"该先修什么"这类回答,只覆盖了手工 seed 过的 4 个专业。
这个脚本把已抓取到的代码转换成边,覆盖每一门已建索引的课程:零 LLM、
零爬取,一次跑完。

Caveats encoded in the rows themselves:
  - The scraper flattens AND/OR prerequisite groups, so every edge is
    written as requirement='required' with a note flagging the flattening.
    A future parser can upgrade OR-groups to 'recommended' alternatives.
  - Codes whose course isn't in the catalog (retired/not-scraped) are
    skipped — the FK would reject them and the UI tolerates absence.
  - Hand-seeded program edges are preserved: the upsert only INSERTs
    missing pairs (ON CONFLICT DO NOTHING), never overwriting curated
    requirement tiers/notes.

写入行本身所携带的注意事项:
  - 爬虫会把 AND/OR 先修分组拍平(flatten),所以每条边都写成
    requirement='required',并在 notes 里标注"已拍平"。未来的解析器
    可以把 OR 分组升级为 'recommended' 的替代选项。
  - 课程不在目录里(已下架 / 未爬到)的代码会被跳过 —— 外键会拒绝
    它们,UI 也能容忍缺失。
  - 手工 seed 的专业边会被保留:这里的 upsert 只 INSERT 缺失的
    pair(ON CONFLICT DO NOTHING),绝不会覆盖人工整理过的
    requirement 分级 / notes。

Usage:
  uv run python scripts/backfill_prereq_edges.py                  # dry-run
  uv run python scripts/backfill_prereq_edges.py --commit
  docker exec neu-compass-api python scripts/backfill_prereq_edges.py \
      --db-path /data/courses.db --commit

用法:
  uv run python scripts/backfill_prereq_edges.py                  # 试运行(dry-run)
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

# 中文:写入 course_prerequisites.notes 的固定文案,标记这条边是本脚本
# 自动生成、AND/OR 分组已被拍平(flatten)处理过。
BACKFILL_NOTE = "parsed from catalog; AND/OR groups flattened"


def backfill(conn: sqlite3.Connection, *, commit: bool) -> dict[str, int]:
    """Insert missing prereq edges. Returns counters for the report.

    中文:插入缺失的先修课边。返回供报告使用的计数字典。
    """
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
                # 中文:schema 的 CHECK 约束禁止自引用;跳过
                continue
            # ON CONFLICT strategy: DO NOTHING — this is a pure backfill, so
            # an edge that already exists (e.g. hand-seeded by
            # scripts/seed_program.py) is left completely untouched; only a
            # missing pair gets inserted. This is what "Hand-seeded program
            # edges are preserved" in the module docstring means concretely.
            # 中文:ON CONFLICT 策略 —— DO NOTHING。这只是一次补全性质的
            # backfill,已经存在的边(比如由 scripts/seed_program.py 手工
            # seed 的)会被完全保留、不做任何改动;只有缺失的 pair 才会被
            # 插入。这正是模块级 docstring 里"手工 seed 的专业边会被保留"
            # 这句话的具体实现。
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

    # Deferred import: local packages only become importable after
    # PROJECT_ROOT was inserted into sys.path above, so this can't be a
    # top-of-file import.
    # 中文:延迟导入 —— 本地包要等到上面把 PROJECT_ROOT 插入 sys.path
    # 之后才能被导入,所以不能写成文件顶部的 import。
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
