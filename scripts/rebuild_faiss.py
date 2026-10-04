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
     - Loads the existing index WITH checksum verification.
     - Diffs by id AND by text fingerprint: new ids are embedded, gone ids are
       removed, and ids whose raw_text changed are re-embedded (a vector is
       only "retained" when it was computed from the exact current text).
     - Falls back to a full rebuild — and says why (`fallback_reason`) — when
       it cannot be sure: index missing/corrupt/torn, no manifest (unknown
       model), a different --model-name than the index was built with, or a
       retained course without a recorded fingerprint (legacy build).
     中文：增量模式按 id 和文本指纹双重比对：新增的嵌入、消失的删除、
     raw_text 变过的重新嵌入；无法确定时（索引缺失/损坏/撕裂、无清单、
     模型名不同、旧构建缺指纹）退回全量重建并给出 fallback_reason。

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
from rag.index import FaissIndex, text_fingerprint  # noqa: E402


def _load_for_incremental(index_path: Path, model_name: str) -> tuple[FaissIndex | None, str | None]:
    """The existing index if it is safe to extend, else (None, reason).
    中文：现有索引可以安全地在其上增量更新时返回它，否则返回 (None, 原因)。"""
    if not (index_path / FaissIndex.INDEX_FILE).exists():
        return None, "missing_index"
    try:
        existing = FaissIndex.load(index_path, verify_checksums=True)
    except Exception:  # noqa: BLE001 — any unreadable/torn/corrupt set => full rebuild
        return None, "unreadable_or_corrupt_index"
    if existing.manifest is None:
        return None, "no_manifest_unknown_model"
    if existing.manifest.get("embedding_model") != model_name:
        return None, "model_changed"
    return existing, None


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

    Full mode returns {embedded, skipped_no_text}. Incremental mode adds
    removed / retained / reembedded_changed / fallback_full / fallback_reason;
    `embedded` counts every vector computed this run (new + changed).
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
    target_fp = {cid: text_fingerprint(raw) for cid, raw in target_map.items()}

    fallback_reason: str | None = None
    if incremental:
        existing_index, fallback_reason = _load_for_incremental(target_index_path, model_name)
        if existing_index is not None:
            existing_ids = set(existing_index.course_ids)
            target_ids = set(target_map)
            kept = existing_ids & target_ids
            if any(existing_index.fingerprint(cid) is None for cid in kept):
                # Built before fingerprints existed: "unchanged" can't be told
                # from "raw_text changed", so nothing may be trusted as retained.
                # 中文：指纹出现之前的旧构建 —— 分不清"没变"和"raw_text 改过"，
                # 因此任何向量都不能被当作可保留。
                existing_index, fallback_reason = None, "missing_fingerprints"
        if existing_index is not None:
            changed = sorted(cid for cid in kept if existing_index.fingerprint(cid) != target_fp[cid])
            to_remove = sorted(existing_ids - target_ids)
            to_add = sorted(target_ids - existing_ids)

            if to_remove or changed:
                existing_index.remove(to_remove + changed)

            reembed = sorted(to_add + changed)
            if reembed:
                vectors = embedder.encode([target_map[cid] for cid in reembed], normalize=True)
                existing_index.add(vectors, reembed, fingerprints=[target_fp[cid] for cid in reembed])

            existing_index.save(target_index_path, model_name=model_name, atomic=True)
            return {
                "embedded": len(reembed),
                "reembedded_changed": len(changed),
                "removed": len(to_remove),
                "retained": len(kept) - len(changed),
                "skipped_no_text": skipped_no_text,
                "fallback_full": False,
                "fallback_reason": None,
            }

    # Full rebuild (or fallback from an incremental run that could not be trusted)
    index = FaissIndex()
    if course_ids:
        texts = [target_map[cid] for cid in course_ids]
        vectors = embedder.encode(texts, normalize=True)
        index.add(vectors, course_ids, fingerprints=[target_fp[cid] for cid in course_ids])

    index.save(target_index_path, model_name=model_name, atomic=True)

    if incremental:
        return {
            "embedded": len(course_ids),
            "reembedded_changed": 0,
            "removed": 0,
            "retained": 0,
            "skipped_no_text": skipped_no_text,
            "fallback_full": True,
            "fallback_reason": fallback_reason,
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
    parser.add_argument("--model-name", default=None,
                        help="Embedding model identifier for the manifest "
                             "(default: settings.embedding_model — the value the API checks at startup)")
    args = parser.parse_args()

    if args.db_path is None or args.index_path is None or args.model_name is None:
        from config import settings  # noqa: PLC0415
        db_path = args.db_path or settings.sqlite_path
        index_path = args.index_path or settings.faiss_index_path
        args.model_name = args.model_name or settings.embedding_model
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
        print(f"   re-embedded (raw_text changed): {counts['reembedded_changed']}")
        print(f"   removed      : {counts['removed']}")
        print(f"   retained     : {counts['retained']}")
        if counts["fallback_full"]:
            print(f"   note         : full rebuild ({counts['fallback_reason']})")
    print(f"   skipped (no raw_text): {counts['skipped_no_text']}")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
