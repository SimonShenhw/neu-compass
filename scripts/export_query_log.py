"""Dump query_log to JSONL for eval-set mining (test_set v0.4 pipeline).

Usage:
  uv run python scripts/export_query_log.py --db-path ~/neu-compass-data/courses.db
  docker exec neu-compass-api python scripts/export_query_log.py \
      --db-path /data/courses.db --since 2026-06-01 --out /data/query_log.jsonl
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db-path", required=True)
    ap.add_argument("--since", default=None, help="ISO date floor, e.g. 2026-06-01")
    ap.add_argument(
        "--out", default=str(PROJECT_ROOT / "eval" / "query_log_export.jsonl")
    )
    args = ap.parse_args()

    from db.connection import connect  # noqa: PLC0415

    conn = connect(str(Path(args.db_path).expanduser()))
    try:
        sql = "SELECT * FROM query_log"
        params: list[str] = []
        if args.since:
            sql += " WHERE created_at >= ?"
            params.append(args.since)
        sql += " ORDER BY log_id"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
    print(f"=> exported {len(rows)} rows -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
