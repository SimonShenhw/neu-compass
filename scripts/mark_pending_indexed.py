"""Flip status='pending' → 'indexed' for courses that have raw_text.

Companion to scripts/rebuild_faiss.py: rebuild_faiss reads from SQLite
and writes the FAISS index but never touches courses.status (per its
docstring — SQLite is the source of truth, the script is non-mutating).

After a fresh ingest where everything is 'pending', call this to complete
the canonical ADR-0013 transition: pending → embed → indexed.

Run:
    uv run python scripts/rebuild_faiss.py --status pending
    uv run python scripts/mark_pending_indexed.py

Idempotent: rows without raw_text stay 'pending' (they weren't embeddable).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import settings  # noqa: E402
from db.connection import connect  # noqa: E402


def main() -> int:
    conn = connect(settings.sqlite_path)
    try:
        cur = conn.execute(
            """
            UPDATE courses
               SET status = 'indexed', indexed_at = CURRENT_TIMESTAMP
             WHERE status = 'pending'
               AND raw_text IS NOT NULL
               AND raw_text != ''
            """
        )
        conn.commit()
        print(f"flipped pending -> indexed: {cur.rowcount} rows")

        counts = conn.execute(
            "SELECT status, COUNT(*) AS n FROM courses GROUP BY status"
        ).fetchall()
        for row in counts:
            print(f"  status={row['status']:>8}: {row['n']}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
