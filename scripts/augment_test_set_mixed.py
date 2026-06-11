"""Add a code_switched category to the eval set → test_set v0.3.1.

Why: the user base's dominant register is 中英混合 ("有没有 workload 轻一点
的 ML 课"), but v0.3 only measures pure-English (medium/complex) and
mostly-Chinese (boundary) — code-switching sits between and is unmeasured.
Measure first, adapt second.

Ground truth: weak-label (source course), same convention as v0.3.
Output: eval/test_set_v031.json (v0.3 queries verbatim + N new).

Usage (PC WSL):
  uv run python scripts/augment_test_set_mixed.py \
      --db-path ~/neu-compass-data/courses.db
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_CJK_RE = re.compile(r"[一-鿿]")
_ASCII_RE = re.compile(r"[A-Za-z]{2,}")

PROMPT = (
    "你在模拟一个习惯中英混合表达的东北大学(Northeastern)中国研究生在选课"
    "系统里搜索。根据下面的课程描述,写一条**中英混合**的搜索 query:中文"
    "句架 + 英文专业术语,风格如 \"有没有 workload 轻一点的 ML 课\" 或 "
    "\"讲 distributed systems 容错的课推荐\"。8-25 个字,必须同时包含中文和"
    "英文,不要出现课程编号和完整课程名。只输出 query 本身。\n\n"
    "课程名: {name}\n描述: {text}"
)


def cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db-path", required=True)
    ap.add_argument("--base", default=str(PROJECT_ROOT / "eval" / "test_set_v03.json"))
    ap.add_argument("--out", default=str(PROJECT_ROOT / "eval" / "test_set_v031.json"))
    ap.add_argument("--count", type=int, default=12)
    args = ap.parse_args()

    from db.connection import connect  # noqa: PLC0415
    from llm.gemini_client import GeminiError, generate_text  # noqa: PLC0415

    base = json.loads(Path(args.base).read_text(encoding="utf-8"))
    queries = list(base["queries"])
    next_id = max(int(q["query_id"][1:]) for q in queries) + 1

    conn = connect(str(Path(args.db_path).expanduser()))
    try:
        rows = conn.execute(
            "SELECT course_id, primary_name, raw_text FROM courses "
            "WHERE status='indexed' AND length(COALESCE(raw_text,'')) > 200 "
            "ORDER BY course_id"
        ).fetchall()
    finally:
        conn.close()

    # Seed offset 7: disjoint from the v0.3 generation strides.
    stride = max(1, len(rows) // (args.count * 2))
    made = 0
    for r in rows[7::stride]:
        if made >= args.count:
            break
        try:
            out = generate_text(
                PROMPT.format(name=r["primary_name"], text=r["raw_text"][:500]),
                temperature=0.8, max_output_tokens=2048,
            )
        except GeminiError as e:
            print(f"   ! LLM failed: {e}")
            continue
        q = out.strip().splitlines()[0].strip().strip('"').strip()
        # Hard contract: genuinely code-switched, no truncation tail.
        if not (_CJK_RE.search(q) and _ASCII_RE.search(q) and 6 <= len(q) <= 60):
            print(f"   ! dropped: {q[:50]!r}")
            continue
        queries.append({
            "query_id": f"q{next_id:03d}",
            "category": "code_switched",
            "query": q,
            "expected_course_ids": [r["course_id"]],
            "rationale": f"v0.3.1 generated: Gemini code-switched query for "
                         f"{r['primary_name'][:40]}",
        })
        next_id += 1
        made += 1
        print(f"   + {q}")

    from collections import Counter
    out_doc = {
        "_comment": base["_comment"] + " | v0.3.1: +code_switched category "
        "(中英混合 register, the user base's dominant style).",
        "version": "0.3.1",
        "category_distribution": dict(Counter(q["category"] for q in queries)),
        "queries": queries,
    }
    Path(args.out).write_text(
        json.dumps(out_doc, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print(f"\n=> wrote {args.out}: {len(queries)} queries")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
