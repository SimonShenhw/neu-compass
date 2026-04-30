"""FAISS IndexIDMap wrapper with course_id <-> int64 mapping.

Schema uses string course_ids (UUID-like). FAISS IDs are int64. The
mapping is maintained in this class and persisted alongside the index
file. add() refuses to insert a course already present — caller must
remove + re-add to update embeddings.

Persistence layout under <dir>/:
  index.faiss      — FAISS binary (IndexIDMap wrapping IndexFlatIP)
  id_map.json      — int_id -> course_id map (and reverse)

Empty path is fine for tests; in production we'd point at
~/neu-compass-data/faiss_index/.
"""

from __future__ import annotations

import json
from pathlib import Path

import faiss
import numpy as np

from rag.embedder import EMBEDDING_DIM


class FaissIndex:
    """IndexIDMap(IndexFlatIP) with stable int64 IDs assigned per course_id."""

    INDEX_FILE = "index.faiss"
    ID_MAP_FILE = "id_map.json"

    def __init__(self, *, dim: int = EMBEDDING_DIM) -> None:
        self._dim = dim
        base = faiss.IndexFlatIP(dim)
        self._index = faiss.IndexIDMap(base)
        self._id_to_course: dict[int, str] = {}
        self._course_to_id: dict[str, int] = {}
        self._next_int_id = 0

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def count(self) -> int:
        return self._index.ntotal

    def __contains__(self, course_id: str) -> bool:
        return course_id in self._course_to_id

    # === Mutation ===

    def add(self, vectors: np.ndarray, course_ids: list[str]) -> None:
        """Add vectors. Caller must ensure vectors are L2-normalized for IP."""
        if len(vectors) != len(course_ids):
            raise ValueError(
                f"Vector count {len(vectors)} != course_id count {len(course_ids)}"
            )
        if vectors.size == 0:
            return
        if vectors.shape[1] != self._dim:
            raise ValueError(f"Expected dim {self._dim}, got {vectors.shape[1]}")

        for cid in course_ids:
            if cid in self._course_to_id:
                raise ValueError(
                    f"course_id {cid!r} already in index. "
                    "Remove first if updating."
                )

        int_ids: list[int] = []
        for cid in course_ids:
            int_id = self._next_int_id
            self._next_int_id += 1
            self._id_to_course[int_id] = cid
            self._course_to_id[cid] = int_id
            int_ids.append(int_id)

        self._index.add_with_ids(
            np.ascontiguousarray(vectors.astype(np.float32)),
            np.asarray(int_ids, dtype=np.int64),
        )

    def remove(self, course_ids: list[str]) -> int:
        """Remove course_ids from index. Returns count actually removed."""
        int_ids = [
            self._course_to_id[c] for c in course_ids if c in self._course_to_id
        ]
        if not int_ids:
            return 0

        selector = faiss.IDSelectorBatch(np.asarray(int_ids, dtype=np.int64))
        removed = self._index.remove_ids(selector)

        for cid in course_ids:
            int_id = self._course_to_id.pop(cid, None)
            if int_id is not None:
                self._id_to_course.pop(int_id, None)

        return int(removed)

    def clear(self) -> None:
        base = faiss.IndexFlatIP(self._dim)
        self._index = faiss.IndexIDMap(base)
        self._id_to_course.clear()
        self._course_to_id.clear()
        self._next_int_id = 0

    # === Query ===

    def search(
        self,
        query_vec: np.ndarray,
        *,
        k: int = 10,
        candidate_course_ids: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Top-K search. If candidate_course_ids is given, restrict to those.

        Returns [(course_id, similarity), ...] sorted by similarity desc.
        Empty list if index is empty or candidate set is empty.
        """
        if self._index.ntotal == 0:
            return []

        if query_vec.ndim == 1:
            query_vec = query_vec.reshape(1, -1)
        if query_vec.shape[1] != self._dim:
            raise ValueError(f"Query dim {query_vec.shape[1]} != index dim {self._dim}")

        params = None
        if candidate_course_ids is not None:
            int_ids = [
                self._course_to_id[c] for c in candidate_course_ids
                if c in self._course_to_id
            ]
            if not int_ids:
                return []
            selector = faiss.IDSelectorBatch(np.asarray(int_ids, dtype=np.int64))
            params = faiss.SearchParameters(sel=selector)

        q = np.ascontiguousarray(query_vec.astype(np.float32))
        if params is not None:
            distances, ids = self._index.search(q, k, params=params)
        else:
            distances, ids = self._index.search(q, k)

        results: list[tuple[str, float]] = []
        for dist, int_id in zip(distances[0], ids[0]):
            if int_id == -1:
                continue
            cid = self._id_to_course.get(int(int_id))
            if cid is None:  # shouldn't happen unless map is corrupt
                continue
            results.append((cid, float(dist)))
        return results

    # === Persistence ===

    def save(self, dir_path: str | Path) -> None:
        path = Path(dir_path)
        path.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(path / self.INDEX_FILE))
        meta = {
            "dim": self._dim,
            "next_int_id": self._next_int_id,
            "id_map": {str(k): v for k, v in self._id_to_course.items()},
        }
        (path / self.ID_MAP_FILE).write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @classmethod
    def load(cls, dir_path: str | Path) -> "FaissIndex":
        path = Path(dir_path)
        index_path = path / cls.INDEX_FILE
        meta_path = path / cls.ID_MAP_FILE
        if not index_path.exists() or not meta_path.exists():
            raise FileNotFoundError(
                f"Missing FAISS index files in {path}. Run rebuild_faiss.py."
            )

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        instance = cls(dim=meta["dim"])
        instance._index = faiss.read_index(str(index_path))
        instance._next_int_id = int(meta["next_int_id"])
        for str_int, course_id in meta["id_map"].items():
            int_id = int(str_int)
            instance._id_to_course[int_id] = course_id
            instance._course_to_id[course_id] = int_id
        return instance


__all__ = ["FaissIndex"]
