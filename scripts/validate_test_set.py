"""Sanity check eval/test_set.json: count by category + verify each
expected_course_id actually exists in the live SQLite catalog.

Run:
    uv run python scripts/validate_test_set.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import settings  # noqa: E402
from db.connection import connect  # noqa: E402

TEST_SET_PATH = PROJECT_ROOT / "eval" / "test_set.json"


def main() -> int:
    data = json.loads(TEST_SET_PATH.read_text(encoding="utf-8"))
    queries = data["queries"]
    print(f"version: {data.get('version')}")
    print(f"total queries: {len(queries)}")

    cats = Counter(q["category"] for q in queries)
    for c, n in cats.most_common():
        print(f"  {c}: {n}")

    conn = connect(settings.sqlite_path)
    try:
        missing: list[tuple[str, str]] = []
        for q in queries:
            for cid in q["expected_course_ids"]:
                row = conn.execute(
                    "SELECT 1 FROM courses WHERE course_id = ?", (cid,)
                ).fetchone()
                if not row:
                    missing.append((q["query_id"], cid))
    finally:
        conn.close()

    print(f"\nmissing course_id references: {len(missing)}")
    for qid, cid in missing:
        print(f"  {qid}: {cid!r}")

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
