"""Rebuild the FAISS index from SQLite. ADR-0013 disaster-recovery script.

When to run:
  - FAISS index file lost / corrupted
  - Schema migration changed embedding semantics
  - Switching embedding model (bge-m3 -> something else)
  - Periodic sanity check (FAISS contains every status='indexed' row)

The script:
  1. Reads all courses with status='indexed' from SQLite.
  2. Embeds raw_text via Embedder (bge-m3 by default).
  3. Builds a fresh FAISS index, writes to disk.
  4. Optionally reconciles status: if a row is status='indexed' but has
     never been embedded (status set manually for testing), still runs.

Caller responsibility:
  - SQLite is the source of truth; this script never modifies it.
  - You probably want to stop the API before running (we hold no locks).

Usage:
    python scripts/rebuild_faiss.py
    python scripts/rebuild_faiss.py --db-path /tmp/x.db --index-path /tmp/idx
    python scripts/rebuild_faiss.py --status pending  # also embed pending
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from db.connection import connect  # noqa: E402
from rag.embedder import BGEM3Embedder, EmbedderProtocol  # noqa: E402
from rag.index import FaissIndex  # noqa: E402


def rebuild(
    *,
    db_path: str | Path,
    index_path: str | Path,
    embedder: EmbedderProtocol | None = None,
    status_filter: str | None = "indexed",
    batch_size: int = 32,
) -> dict[str, int]:
    """Rebuild FAISS index from SQLite. Returns {'embedded': N, 'skipped_no_text': N}.

    `embedder` is injectable so tests pass a fake. Default builds BGEM3Embedder
    on demand (lazy ~2.3GB model download on first encode call).
    """
    conn = connect(db_path)
    try:
        sql = "SELECT course_id, raw_text FROM courses"
        params: list = []
        if status_filter:
            sql += " WHERE status = ?"
            params.append(status_filter)
        sql += " ORDER BY course_id"

        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    course_ids: list[str] = []
    texts: list[str] = []
    skipped_no_text = 0
    for row in rows:
        if not row["raw_text"]:
            skipped_no_text += 1
            continue
        course_ids.append(row["course_id"])
        texts.append(row["raw_text"])

    if embedder is None:
        embedder = BGEM3Embedder()

    index = FaissIndex()
    if texts:
        # Encode in batches via embedder's own batch_size knob (BGEM3) or
        # all-at-once for smaller fakes. Either way, single .encode() call.
        vectors = embedder.encode(texts, normalize=True)
        index.add(vectors, course_ids)

    index.save(index_path)

    return {"embedded": len(course_ids), "skipped_no_text": skipped_no_text}


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=None, help="Override settings.sqlite_path")
    parser.add_argument("--index-path", default=None, help="Override settings.faiss_index_path")
    parser.add_argument(
        "--status", default="indexed",
        help="Embed only rows with this status (default: indexed)",
    )
    parser.add_argument("--all", action="store_true",
                        help="Ignore status filter (embed every row with raw_text)")
    args = parser.parse_args()

    if args.db_path is None or args.index_path is None:
        from config import settings  # noqa: PLC0415
        db_path = args.db_path or settings.sqlite_path
        index_path = args.index_path or settings.faiss_index_path
    else:
        db_path = args.db_path
        index_path = args.index_path

    status = None if args.all else args.status

    print(f"=> rebuilding FAISS index")
    print(f"   db:    {db_path}")
    print(f"   index: {index_path}")
    print(f"   filter: status={status if status else 'ANY'}")

    counts = rebuild(db_path=db_path, index_path=index_path, status_filter=status)
    print(f"=> embedded     : {counts['embedded']}")
    print(f"   skipped (no raw_text): {counts['skipped_no_text']}")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
