"""Rebuild the FAISS index from SQLite. ADR-0013 disaster-recovery script.

When to run:
  - FAISS index file lost / corrupted
  - Schema migration changed embedding semantics
  - Switching embedding model (bge-m3 -> something else)
  - Periodic sanity check (FAISS contains every status='indexed' row)
  - Incremental sync of newly indexed or deleted courses

The script:
  1. Reads all courses with status='indexed' from SQLite.
  2. In full mode:
     - Embeds raw_text via Embedder (bge-m3 by default).
     - Builds a fresh FAISS index, writes to disk with atomic replace & manifest.
  3. In incremental mode:
     - Loads existing index (falling back to full rebuild if corrupted/absent).
     - Computes diff (to_add = target - existing, to_remove = existing - target).
     - Removes stale courses, encodes only new courses, saves updated index & manifest.

Usage:
    python scripts/rebuild_faiss.py
    python scripts/rebuild_faiss.py --incremental
    python scripts/rebuild_faiss.py --db-path /tmp/x.db --index-path /tmp/idx
    python scripts/rebuild_faiss.py --status pending  # also embed pending
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

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
    model_name: str = "BAAI/bge-m3",
    incremental: bool = False,
) -> dict[str, Any]:
    """Rebuild or incrementally update FAISS index from SQLite.

    Returns dict with counts: embedded, removed, retained, skipped_no_text, fallback_full.
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
    target_map: dict[str, str] = {}
    skipped_no_text = 0
    for row in rows:
        cid = row["course_id"]
        raw = row["raw_text"]
        if not raw:
            skipped_no_text += 1
            continue
        course_ids.append(cid)
        target_map[cid] = raw

    if embedder is None:
        embedder = BGEM3Embedder()

    target_index_path = Path(index_path)

    if incremental:
        existing_index: FaissIndex | None = None
        if (target_index_path / FaissIndex.INDEX_FILE).exists():
            try:
                existing_index = FaissIndex.load(target_index_path, verify_checksums=False)
            except Exception:
                existing_index = None

        if existing_index is not None:
            existing_ids = set(existing_index._course_to_id.keys())
            target_ids = set(target_map.keys())

            to_remove = sorted(list(existing_ids - target_ids))
            to_add = sorted(list(target_ids - existing_ids))

            if to_remove:
                existing_index.remove(to_remove)

            if to_add:
                add_texts = [target_map[cid] for cid in to_add]
                vectors = embedder.encode(add_texts, normalize=True)
                existing_index.add(vectors, to_add)

            existing_index.save(target_index_path, model_name=model_name, atomic=True)
            retained = len(existing_ids & target_ids)
            return {
                "embedded": len(to_add),
                "removed": len(to_remove),
                "retained": retained,
                "skipped_no_text": skipped_no_text,
                "fallback_full": False,
            }

    # Full rebuild (or fallback from failed incremental load)
    index = FaissIndex()
    if course_ids:
        texts = [target_map[cid] for cid in course_ids]
        vectors = embedder.encode(texts, normalize=True)
        index.add(vectors, course_ids)

    index.save(target_index_path, model_name=model_name, atomic=True)

    if incremental:
        return {
            "embedded": len(course_ids),
            "removed": 0,
            "retained": 0,
            "skipped_no_text": skipped_no_text,
            "fallback_full": True,
        }

    return {
        "embedded": len(course_ids),
        "skipped_no_text": skipped_no_text,
    }


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
    parser.add_argument("--incremental", action="store_true",
                        help="Incremental update against existing index if valid")
    parser.add_argument("--model-name", default="BAAI/bge-m3",
                        help="Embedding model identifier for metadata manifest")
    args = parser.parse_args()

    if args.db_path is None or args.index_path is None:
        from config import settings  # noqa: PLC0415
        db_path = args.db_path or settings.sqlite_path
        index_path = args.index_path or settings.faiss_index_path
    else:
        db_path = args.db_path
        index_path = args.index_path

    status = None if args.all else args.status

    mode_str = "INCREMENTAL" if args.incremental else "FULL"
    print(f"=> rebuilding FAISS index (mode={mode_str})")
    print(f"   db:    {db_path}")
    print(f"   index: {index_path}")
    print(f"   filter: status={status if status else 'ANY'}")
    print(f"   model:  {args.model_name}")

    counts = rebuild(
        db_path=db_path,
        index_path=index_path,
        status_filter=status,
        model_name=args.model_name,
        incremental=args.incremental,
    )
    print(f"=> embedded     : {counts['embedded']}")
    if args.incremental:
        print(f"   removed      : {counts['removed']}")
        print(f"   retained     : {counts['retained']}")
        if counts["fallback_full"]:
            print("   note         : fallback to full rebuild occurred")
    print(f"   skipped (no raw_text): {counts['skipped_no_text']}")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
