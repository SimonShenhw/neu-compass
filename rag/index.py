"""FAISS IndexIDMap wrapper with course_id <-> int64 mapping.

Schema uses string course_ids (UUID-like). FAISS IDs are int64. The
mapping is maintained in this class and persisted alongside the index
file. add() refuses to insert a course already present — caller must
remove + re-add to update embeddings.

Schema 里用的是字符串形式的 course_id(类 UUID)。FAISS 的 ID 是 int64。
这个映射关系由本类维护,并与索引文件一起持久化。add() 拒绝插入已经
存在的课程 —— 调用方要更新 embedding 必须先 remove 再重新 add。

Persistence layout under <dir>/:
  index.faiss      — FAISS binary (IndexIDMap wrapping IndexFlatIP)
  id_map.json      — int_id -> course_id map (and reverse)

<dir>/ 下的持久化布局:
  index.faiss —— FAISS 二进制文件(IndexIDMap 包裹 IndexFlatIP)
  id_map.json —— int_id -> course_id 的映射(以及反向映射)

Empty path is fine for tests; in production we'd point at
~/neu-compass-data/faiss_index/.

测试时用空路径就行;生产环境会指向 ~/neu-compass-data/faiss_index/。
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

import faiss
import numpy as np

from rag.embedder import EMBEDDING_DIM


_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def text_fingerprint(text: str) -> str:
    """SHA-256 of the exact text a vector is computed from (UTF-8).
    中文:生成向量所用原文的 SHA-256(UTF-8)。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class FaissIndex:
    """IndexIDMap(IndexFlatIP) with stable int64 IDs assigned per course_id.

    中文:IndexIDMap(IndexFlatIP),为每个 course_id 分配稳定的 int64 ID。
    """

    INDEX_FILE = "index.faiss"
    ID_MAP_FILE = "id_map.json"
    MANIFEST_FILE = "index_manifest.json"
    DEFAULT_MODEL_NAME = "BAAI/bge-m3"
    MANIFEST_VERSION = "1.0"

    def __init__(self, *, dim: int = EMBEDDING_DIM) -> None:
        self._dim = dim
        base = faiss.IndexFlatIP(dim)
        self._index = faiss.IndexIDMap(base)
        self._id_to_course: dict[int, str] = {}
        self._course_to_id: dict[str, int] = {}
        # course_id -> SHA-256 of the text its vector was computed from.
        # Lets an incremental rebuild tell an unchanged course from one whose
        # raw_text changed (same id, stale vector). Empty for legacy builds.
        # 中文:course_id -> 生成该向量所用文本的 SHA-256。增量重建靠它区分
        # "没变的课程"和"raw_text 改过、向量已过期的课程"。旧构建为空。
        self._fingerprints: dict[str, str] = {}
        self._next_int_id = 0
        self._manifest: dict[str, Any] | None = None

    @property
    def manifest(self) -> dict[str, Any] | None:
        return self._manifest

    @property
    def course_ids(self) -> frozenset[str]:
        return frozenset(self._course_to_id)

    def fingerprint(self, course_id: str) -> str | None:
        """Text fingerprint recorded when this course's vector was added;
        None when the build that added it did not record one.
        中文:添加该课程向量时记录的文本指纹;添加它的那次构建没记录时为 None。"""
        return self._fingerprints.get(course_id)

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def count(self) -> int:
        return self._index.ntotal

    def __contains__(self, course_id: str) -> bool:
        return course_id in self._course_to_id

    # === Mutation ===
    # 中文:=== 写操作 ===

    def add(
        self,
        vectors: np.ndarray,
        course_ids: list[str],
        *,
        fingerprints: list[str] | None = None,
    ) -> None:
        """Add vectors. Caller must ensure vectors are L2-normalized for IP.

        `fingerprints` (optional, one SHA-256 hex per course) records which
        text each vector came from, for incremental staleness detection.

        中文:添加向量。调用方必须确保向量已经 L2 归一化,这样内积(IP)
        才等价于余弦相似度。`fingerprints`(可选,每门课一个 SHA-256 十六进制
        串)记录每个向量来自哪段文本,供增量重建判断向量是否过期。
        """
        if len(vectors) != len(course_ids):
            raise ValueError(
                f"Vector count {len(vectors)} != course_id count {len(course_ids)}"
            )
        if fingerprints is not None and (
            len(fingerprints) != len(course_ids)
            or not all(isinstance(f, str) and _SHA256_RE.fullmatch(f) for f in fingerprints)
        ):
            raise ValueError("fingerprints must be one SHA-256 hex string per course_id")
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
        if fingerprints is not None:
            self._fingerprints.update(zip(course_ids, fingerprints, strict=True))

    def remove(self, course_ids: list[str]) -> int:
        """Remove course_ids from index. Returns count actually removed.

        中文:从索引里移除 course_id。返回实际移除的数量。
        """
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
            self._fingerprints.pop(cid, None)

        return int(removed)

    def clear(self) -> None:
        base = faiss.IndexFlatIP(self._dim)
        self._index = faiss.IndexIDMap(base)
        self._id_to_course.clear()
        self._course_to_id.clear()
        self._fingerprints.clear()
        self._next_int_id = 0
        self._manifest = None

    # === Query ===
    # 中文:=== 查询 ===

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

        中文:Top-K 搜索。若提供了 candidate_course_ids,则只在其中检索。
        返回 [(course_id, similarity), ...],按相似度降序排列。索引为空
        或候选集为空时返回空列表。
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
            # IDSelectorBatch + SearchParameters restricts FAISS's own search
            # to this id subset — cheaper than searching everything and
            # filtering the result, and still returns true top-k WITHIN the
            # subset (a post-filter could return < k after dropping misses).
            # 中文:IDSelectorBatch + SearchParameters 把 FAISS 自身的搜索
            # 限定在这个 id 子集内 —— 比先搜索全部再过滤结果更省,而且能
            # 保证在子集内返回真正的 top-k(事后过滤可能在剔除不匹配项后
            # 剩下不足 k 个)。
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
                # FAISS's sentinel for "fewer than k results were found".
                # 中文:FAISS 用 -1 表示"结果数量不足 k 个"的哨兵值。
                continue
            cid = self._id_to_course.get(int(int_id))
            if cid is None:  # shouldn't happen unless map is corrupt
                # 中文:正常不会发生,除非映射已经损坏。
                continue
            results.append((cid, float(dist)))
        return results



    # === Persistence ===
    # 中文:=== 持久化 ===

    def save(
        self,
        dir_path: str | Path,
        *,
        model_name: str = DEFAULT_MODEL_NAME,
        atomic: bool = True,
    ) -> dict[str, Any]:
        """Persist index binary, id_map (+fingerprints), and the manifest.

        atomic=True stages all three files in a sibling temp dir, then
        publishes them with one os.replace EACH — data files first, manifest
        LAST. That is per-file atomic, NOT a transactional swap of the set: a
        crash between replaces leaves e.g. new index + old id_map/manifest.
        Such a torn set is DETECTABLE, because the manifest pins both data
        checksums — load(verify_checksums=True) refuses it (the API lifespan
        loads that way). Returns the manifest.

        中文:atomic=True 时先把三个文件写到同级临时目录,再逐个 os.replace
        发布 —— 数据文件在前、清单最后。这是"单文件原子",不是整组事务替换:
        两次 replace 之间崩溃会留下"新索引 + 旧 id_map/旧清单"之类的撕裂状态。
        但这种撕裂可以被发现:清单钉住了两个数据文件的校验和,
        load(verify_checksums=True) 会拒绝它(API 启动时就是这样加载的)。
        """
        target_dir = Path(dir_path)
        target_dir.mkdir(parents=True, exist_ok=True)

        meta: dict[str, Any] = {
            "dim": self._dim,
            "next_int_id": self._next_int_id,
            # JSON object keys must be strings; int_id becomes a string here
            # and is cast back to int in load().
            # 中文:JSON 对象的键必须是字符串;这里把 int_id 转成字符串,
            # 加载时(见 load())再转回 int。
            "id_map": {str(k): v for k, v in self._id_to_course.items()},
        }
        if self._fingerprints:
            meta["fingerprints"] = dict(sorted(self._fingerprints.items()))
        id_map_str = json.dumps(meta, indent=2, ensure_ascii=False)

        if not atomic:
            manifest = self._write_set(target_dir, id_map_str, model_name)
        else:
            staging_dir = Path(tempfile.mkdtemp(prefix=".tmp_faiss_", dir=str(target_dir.parent)))
            try:
                manifest = self._write_set(staging_dir, id_map_str, model_name)
                for fn in (self.INDEX_FILE, self.ID_MAP_FILE, self.MANIFEST_FILE):
                    os.replace(staging_dir / fn, target_dir / fn)
            finally:
                shutil.rmtree(staging_dir, ignore_errors=True)

        self._manifest = manifest
        return manifest

    def _write_set(self, directory: Path, id_map_str: str, model_name: str) -> dict[str, Any]:
        """Write index + id_map into `directory`, then the manifest pinning both.
        中文:把索引和 id_map 写进 `directory`,再写出钉住两者校验和的清单。"""
        index_path = directory / self.INDEX_FILE
        id_map_path = directory / self.ID_MAP_FILE
        faiss.write_index(self._index, str(index_path))
        id_map_path.write_text(id_map_str, encoding="utf-8")
        manifest = {
            "manifest_version": self.MANIFEST_VERSION,
            "embedding_model": str(model_name),
            "dimension": self._dim,
            "count": self.count,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "index_file": self.INDEX_FILE,
            "index_sha256": _sha256_file(index_path),
            "id_map_file": self.ID_MAP_FILE,
            "id_map_sha256": _sha256_file(id_map_path),
        }
        (directory / self.MANIFEST_FILE).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return manifest

    @classmethod
    def load(
        cls,
        dir_path: str | Path,
        *,
        expected_model: str | None = None,
        verify_checksums: bool = False,
    ) -> "FaissIndex":
        path = Path(dir_path)
        index_path = path / cls.INDEX_FILE
        meta_path = path / cls.ID_MAP_FILE
        if not index_path.exists() or not meta_path.exists():
            raise FileNotFoundError(
                f"Missing FAISS index files in {path}. Run rebuild_faiss.py."
            )

        manifest_path = path / cls.MANIFEST_FILE
        manifest: dict[str, Any] | None = None
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ValueError(f"Invalid FAISS index manifest in {path}: {exc}") from exc
            if not isinstance(manifest, dict):
                raise ValueError(f"Invalid FAISS index manifest in {path}: not a JSON object")

            if expected_model is not None and manifest.get("embedding_model") != expected_model:
                raise ValueError(
                    f"Embedding model mismatch: expected {expected_model!r}, index has {manifest.get('embedding_model')!r}"
                )

            if verify_checksums:
                # Strict: a manifest that cannot pin BOTH data files is not
                # evidence of integrity (and could hide a torn publish).
                # 中文:严格模式 —— 清单若不能同时钉住两个数据文件,就不能
                # 作为完整性证据(还可能掩盖一次撕裂的发布)。
                for file_path, key, name in (
                    (index_path, "index_sha256", cls.INDEX_FILE),
                    (meta_path, "id_map_sha256", cls.ID_MAP_FILE),
                ):
                    expected_hash = manifest.get(key)
                    actual_hash = _sha256_file(file_path)
                    if not expected_hash or actual_hash != expected_hash:
                        raise ValueError(
                            f"Checksum mismatch for {name}: expected {expected_hash}, got {actual_hash}"
                        )

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        instance = cls(dim=meta["dim"])
        instance._index = faiss.read_index(str(index_path))
        instance._next_int_id = int(meta["next_int_id"])
        # Rebuild BOTH directions of the id map from the persisted one-way
        # (int_id -> course_id) dict.
        # 中文:从持久化的单向字典(int_id -> course_id)重建双向映射。
        for str_int, course_id in meta["id_map"].items():
            int_id = int(str_int)
            instance._id_to_course[int_id] = course_id
            instance._course_to_id[course_id] = int_id
        # Fingerprints only for ids actually in the map; malformed entries are
        # dropped (the course then just looks "unfingerprinted").
        # 中文:只保留映射里确实存在的 id 的指纹;格式不对的条目直接丢弃
        # (该课程只会被视为"没有指纹")。
        for course_id, digest in (meta.get("fingerprints") or {}).items():
            if course_id in instance._course_to_id and isinstance(digest, str) and _SHA256_RE.fullmatch(digest):
                instance._fingerprints[course_id] = digest

        if manifest is not None:
            if manifest.get("dimension") != instance.dim:
                raise ValueError(
                    f"Manifest dimension mismatch: manifest={manifest.get('dimension')}, index={instance.dim}"
                )
            if manifest.get("count") != instance.count:
                raise ValueError(
                    f"Manifest count mismatch: manifest={manifest.get('count')}, index={instance.count}"
                )

        instance._manifest = manifest
        return instance

    @classmethod
    def get_manifest(cls, dir_path: str | Path) -> dict[str, Any] | None:
        """Inspect and return the index manifest without loading binary vectors into memory."""
        path = Path(dir_path) / cls.MANIFEST_FILE
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @classmethod
    def verify_integrity(cls, dir_path: str | Path) -> dict[str, Any]:
        """Check presence of index files and checksum integrity against manifest."""
        path = Path(dir_path)
        index_file = path / cls.INDEX_FILE
        id_map_file = path / cls.ID_MAP_FILE
        manifest_file = path / cls.MANIFEST_FILE

        if not index_file.exists() or not id_map_file.exists():
            return {
                "valid": False,
                "error": "missing_required_files",
                "missing": [f.name for f in (index_file, id_map_file) if not f.exists()],
            }

        if not manifest_file.exists():
            return {
                "valid": True,
                "has_manifest": False,
                "warning": "legacy_index_without_manifest",
            }

        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"valid": False, "error": f"corrupted_manifest: {exc}"}
        if not isinstance(manifest, dict):
            return {"valid": False, "error": "corrupted_manifest: not a JSON object"}

        idx_hash = _sha256_file(index_file)
        id_hash = _sha256_file(id_map_file)

        idx_ok = idx_hash == manifest.get("index_sha256")
        id_ok = id_hash == manifest.get("id_map_sha256")

        return {
            "valid": bool(idx_ok and id_ok),
            "has_manifest": True,
            "manifest": manifest,
            "checksums_match": bool(idx_ok and id_ok),
            "index_sha256_match": idx_ok,
            "id_map_sha256_match": id_ok,
        }



__all__ = ["FaissIndex", "text_fingerprint"]
