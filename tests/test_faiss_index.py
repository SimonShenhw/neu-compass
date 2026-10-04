"""Tests for rag.index — real FAISS, no embedder dependency."""

from __future__ import annotations

from pathlib import Path
import json

import numpy as np
import pytest

from rag.embedder import EMBEDDING_DIM, _l2_normalize
from rag.index import FaissIndex


def _vec(seed: int, dim: int = EMBEDDING_DIM) -> np.ndarray:
    """Deterministic L2-normalized vector for a given seed."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim, dtype=np.float32).reshape(1, -1)
    return _l2_normalize(v)


# === Empty index ===

def test_new_index_count_zero() -> None:
    idx = FaissIndex()
    assert idx.count == 0
    assert idx.dim == EMBEDDING_DIM


def test_search_empty_index_returns_empty() -> None:
    idx = FaissIndex()
    assert idx.search(_vec(1), k=5) == []


def test_contains_membership() -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["a"])
    assert "a" in idx
    assert "b" not in idx


# === add ===

def test_add_single() -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["course-1"])
    assert idx.count == 1


def test_add_many() -> None:
    idx = FaissIndex()
    vecs = np.vstack([_vec(i) for i in range(5)])
    idx.add(vecs, [f"course-{i}" for i in range(5)])
    assert idx.count == 5


def test_add_mismatched_lengths_raises() -> None:
    idx = FaissIndex()
    with pytest.raises(ValueError, match="!="):
        idx.add(_vec(1), ["a", "b"])


def test_add_wrong_dim_raises() -> None:
    idx = FaissIndex()
    bad = np.zeros((1, 64), dtype=np.float32)
    with pytest.raises(ValueError, match="dim"):
        idx.add(bad, ["x"])


def test_add_duplicate_course_id_raises() -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["x"])
    with pytest.raises(ValueError, match="already in index"):
        idx.add(_vec(2), ["x"])


def test_add_empty_no_op() -> None:
    idx = FaissIndex()
    empty = np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    idx.add(empty, [])
    assert idx.count == 0


# === search ===

def test_search_returns_self_as_top_hit() -> None:
    idx = FaissIndex()
    v = _vec(42)
    idx.add(v, ["self"])
    results = idx.search(v, k=1)
    assert len(results) == 1
    assert results[0][0] == "self"
    assert results[0][1] == pytest.approx(1.0, abs=1e-4)


def test_search_orders_by_similarity() -> None:
    idx = FaissIndex()
    target = _vec(1)
    idx.add(target, ["near"])
    far = _vec(99999)  # a different seed -> far direction
    idx.add(far, ["far"])

    results = idx.search(target, k=2)
    assert results[0][0] == "near"
    assert results[1][0] == "far"
    assert results[0][1] > results[1][1]


def test_search_handles_1d_query() -> None:
    """search() should accept either (D,) or (1, D) query vectors."""
    idx = FaissIndex()
    v = _vec(1)
    idx.add(v, ["x"])
    flat = v[0]
    assert idx.search(flat, k=1)[0][0] == "x"


def test_search_wrong_query_dim_raises() -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["x"])
    with pytest.raises(ValueError, match="dim"):
        idx.search(np.zeros((1, 64), dtype=np.float32))


def test_search_with_candidate_filter() -> None:
    idx = FaissIndex()
    target = _vec(1)
    idx.add(target, ["target"])
    idx.add(_vec(2), ["distractor"])

    # Ask for top 2 but restrict to ["distractor"] only — target excluded
    results = idx.search(target, k=2, candidate_course_ids=["distractor"])
    assert [c for c, _ in results] == ["distractor"]


def test_search_with_unknown_candidates_returns_empty() -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["x"])
    results = idx.search(_vec(1), k=5, candidate_course_ids=["does-not-exist"])
    assert results == []


def test_search_k_larger_than_index_returns_what_exists() -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["only"])
    results = idx.search(_vec(1), k=100)
    assert len(results) == 1


# === remove ===

def test_remove_single() -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["x"])
    idx.add(_vec(2), ["y"])
    removed = idx.remove(["x"])
    assert removed == 1
    assert idx.count == 1
    assert "x" not in idx
    assert "y" in idx


def test_remove_unknown_no_op() -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["x"])
    assert idx.remove(["unknown"]) == 0
    assert idx.count == 1


def test_clear_empties_index() -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["x"])
    idx.clear()
    assert idx.count == 0
    assert "x" not in idx


# === persistence ===

def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    idx = FaissIndex()
    vecs = np.vstack([_vec(i) for i in range(3)])
    course_ids = ["a", "b", "c"]
    idx.add(vecs, course_ids)
    idx.save(tmp_path)

    assert (tmp_path / FaissIndex.INDEX_FILE).exists()
    assert (tmp_path / FaissIndex.ID_MAP_FILE).exists()

    loaded = FaissIndex.load(tmp_path)
    assert loaded.count == 3
    assert "a" in loaded
    assert "c" in loaded

    # Search behavior identical
    results = loaded.search(vecs[0], k=1)
    assert results[0][0] == "a"


def test_load_missing_files_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="rebuild_faiss"):
        FaissIndex.load(tmp_path)


def test_save_load_preserves_next_int_id(tmp_path: Path) -> None:
    """After load, adding a new course should not collide with old int ids."""
    idx = FaissIndex()
    idx.add(_vec(1), ["a"])
    idx.add(_vec(2), ["b"])
    idx.save(tmp_path)

    loaded = FaissIndex.load(tmp_path)
    loaded.add(_vec(3), ["c"])
    assert loaded.count == 3
    assert "a" in loaded and "b" in loaded and "c" in loaded

# === Manifest and 08A tests ===

def test_save_creates_manifest_metadata(tmp_path: Path) -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["course-1"])
    idx.add(_vec(2), ["course-2"])
    manifest = idx.save(tmp_path, model_name="BAAI/bge-m3", atomic=True)

    manifest_file = tmp_path / FaissIndex.MANIFEST_FILE
    assert manifest_file.exists()
    assert idx.manifest == manifest

    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert data["manifest_version"] == FaissIndex.MANIFEST_VERSION
    assert data["embedding_model"] == "BAAI/bge-m3"
    assert data["dimension"] == EMBEDDING_DIM
    assert data["count"] == 2
    assert "created_at" in data
    assert data["index_file"] == FaissIndex.INDEX_FILE
    assert data["id_map_file"] == FaissIndex.ID_MAP_FILE
    assert len(data["index_sha256"]) == 64
    assert len(data["id_map_sha256"]) == 64


def test_save_atomic_false(tmp_path: Path) -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["course-1"])
    idx.save(tmp_path, atomic=False)

    manifest_file = tmp_path / FaissIndex.MANIFEST_FILE
    assert manifest_file.exists()
    loaded = FaissIndex.load(tmp_path)
    assert loaded.count == 1
    assert "course-1" in loaded


def test_load_with_expected_model_matching_and_mismatch(tmp_path: Path) -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["c1"])
    idx.save(tmp_path, model_name="custom/bge-v2")

    # Matching model passes
    loaded = FaissIndex.load(tmp_path, expected_model="custom/bge-v2")
    assert loaded.count == 1
    assert loaded.manifest is not None
    assert loaded.manifest["embedding_model"] == "custom/bge-v2"

    # Mismatched model raises ValueError
    with pytest.raises(ValueError, match="Embedding model mismatch"):
        FaissIndex.load(tmp_path, expected_model="other/model")


def test_load_manifest_dimension_or_count_mismatch(tmp_path: Path) -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["c1"])
    idx.save(tmp_path)

    manifest_file = tmp_path / FaissIndex.MANIFEST_FILE
    data = json.loads(manifest_file.read_text(encoding="utf-8"))

    # Dimension mismatch
    bad_dim_data = dict(data, dimension=128)
    manifest_file.write_text(json.dumps(bad_dim_data), encoding="utf-8")
    with pytest.raises(ValueError, match="Manifest dimension mismatch"):
        FaissIndex.load(tmp_path)

    # Count mismatch
    bad_count_data = dict(data, count=999)
    manifest_file.write_text(json.dumps(bad_count_data), encoding="utf-8")
    with pytest.raises(ValueError, match="Manifest count mismatch"):
        FaissIndex.load(tmp_path)


def test_load_corrupted_manifest_json_raises(tmp_path: Path) -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["c1"])
    idx.save(tmp_path)

    (tmp_path / FaissIndex.MANIFEST_FILE).write_text("{broken json", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid FAISS index manifest"):
        FaissIndex.load(tmp_path)


def test_load_verify_checksums_pass_and_tampered(tmp_path: Path) -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["c1"])
    idx.save(tmp_path)

    # Clean verification passes
    loaded = FaissIndex.load(tmp_path, verify_checksums=True)
    assert loaded.count == 1

    # Tampering index.faiss raises
    (tmp_path / FaissIndex.INDEX_FILE).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Checksum mismatch for index.faiss"):
        FaissIndex.load(tmp_path, verify_checksums=True)


def test_load_verify_checksums_tampered_id_map(tmp_path: Path) -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["c1"])
    idx.save(tmp_path)

    # Re-write id_map with different formatting/content
    (tmp_path / FaissIndex.ID_MAP_FILE).write_text(
        json.dumps({"dim": EMBEDDING_DIM, "next_int_id": 1, "id_map": {"0": "c1"}, "extra": True}),
        encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Checksum mismatch for id_map.json"):
        FaissIndex.load(tmp_path, verify_checksums=True)


def test_load_legacy_without_manifest(tmp_path: Path) -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["c1"])
    idx.save(tmp_path)

    (tmp_path / FaissIndex.MANIFEST_FILE).unlink()
    loaded = FaissIndex.load(tmp_path)
    assert loaded.count == 1
    assert loaded.manifest is None


def test_get_manifest(tmp_path: Path) -> None:
    assert FaissIndex.get_manifest(tmp_path) is None

    idx = FaissIndex()
    idx.add(_vec(1), ["c1"])
    idx.save(tmp_path, model_name="test-model")

    manifest = FaissIndex.get_manifest(tmp_path)
    assert manifest is not None
    assert manifest["embedding_model"] == "test-model"


def test_verify_integrity(tmp_path: Path) -> None:
    # Directory with missing files
    status = FaissIndex.verify_integrity(tmp_path)
    assert status["valid"] is False
    assert status["error"] == "missing_required_files"

    # Save cleanly
    idx = FaissIndex()
    idx.add(_vec(1), ["c1"])
    idx.save(tmp_path)

    status = FaissIndex.verify_integrity(tmp_path)
    assert status["valid"] is True
    assert status["has_manifest"] is True
    assert status["checksums_match"] is True

    # Legacy (no manifest)
    (tmp_path / FaissIndex.MANIFEST_FILE).unlink()
    status = FaissIndex.verify_integrity(tmp_path)
    assert status["valid"] is True
    assert status["has_manifest"] is False
    assert status["warning"] == "legacy_index_without_manifest"

    # Corrupt manifest
    (tmp_path / FaissIndex.MANIFEST_FILE).write_text("invalid json", encoding="utf-8")
    status = FaissIndex.verify_integrity(tmp_path)
    assert status["valid"] is False
    assert "corrupted_manifest" in status["error"]


# === Fingerprints, torn publishes, strict verification (review 2026-10-03) ===

_FP_A, _FP_B = "a" * 64, "b" * 64


def test_fingerprints_persist_through_save_load_and_drop_on_remove(tmp_path: Path) -> None:
    idx = FaissIndex()
    idx.add(np.vstack([_vec(1), _vec(2)]), ["c1", "c2"], fingerprints=[_FP_A, _FP_B])
    idx.save(tmp_path)
    loaded = FaissIndex.load(tmp_path, verify_checksums=True)
    assert loaded.fingerprint("c1") == _FP_A and loaded.fingerprint("c2") == _FP_B
    assert loaded.course_ids == frozenset({"c1", "c2"})
    loaded.remove(["c1"])
    assert loaded.fingerprint("c1") is None
    loaded.save(tmp_path)
    assert FaissIndex.load(tmp_path).fingerprint("c1") is None


@pytest.mark.parametrize("bad", [["short"], [_FP_A, _FP_B], ["A" * 64], [7]])
def test_add_rejects_malformed_fingerprints(bad) -> None:
    with pytest.raises(ValueError):
        FaissIndex().add(_vec(1), ["c1"], fingerprints=bad)


def test_unfingerprinted_legacy_vectors_report_none(tmp_path: Path) -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["c1"])
    idx.save(tmp_path)
    assert FaissIndex.load(tmp_path).fingerprint("c1") is None


def test_torn_publish_is_refused_by_verified_load(tmp_path: Path) -> None:
    """Crash after the FIRST os.replace: new index.faiss next to the OLD id_map
    and manifest, same vector count. An unverified load would silently map
    vectors to the wrong courses; the verified load (what the API uses) must
    refuse the set."""
    old, new = tmp_path / "old", tmp_path / "new"
    a = FaissIndex()
    a.add(np.vstack([_vec(1), _vec(2)]), ["c1", "c2"])
    a.save(old)
    b = FaissIndex()
    b.add(np.vstack([_vec(3), _vec(4)]), ["c2", "c1"])  # same count, different mapping
    b.save(new)
    (old / FaissIndex.INDEX_FILE).write_bytes((new / FaissIndex.INDEX_FILE).read_bytes())
    with pytest.raises(ValueError, match="Checksum mismatch for index.faiss"):
        FaissIndex.load(old, verify_checksums=True)


def test_verified_load_requires_both_checksums_in_manifest(tmp_path: Path) -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["c1"])
    idx.save(tmp_path)
    manifest_file = tmp_path / FaissIndex.MANIFEST_FILE
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    del data["id_map_sha256"]
    manifest_file.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Checksum mismatch for id_map.json"):
        FaissIndex.load(tmp_path, verify_checksums=True)


def test_non_object_manifest_is_invalid_not_a_crash(tmp_path: Path) -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["c1"])
    idx.save(tmp_path)
    (tmp_path / FaissIndex.MANIFEST_FILE).write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="not a JSON object"):
        FaissIndex.load(tmp_path)
    assert FaissIndex.verify_integrity(tmp_path)["valid"] is False


def test_atomic_and_plain_save_emit_identical_manifest_fields(tmp_path: Path) -> None:
    """Both branches share one writer now; the manifests must not drift."""
    idx = FaissIndex()
    idx.add(_vec(1), ["c1"], fingerprints=[_FP_A])
    m1 = idx.save(tmp_path / "a", atomic=True)
    m2 = idx.save(tmp_path / "b", atomic=False)
    assert {k: v for k, v in m1.items() if k != "created_at"} == {k: v for k, v in m2.items() if k != "created_at"}
    assert not list(tmp_path.glob(".tmp_faiss_*"))  # staging always cleaned up


def test_api_lifespan_enforces_model_and_checksums(monkeypatch) -> None:
    """The manifest only protects production if the startup load uses it."""
    import asyncio  # noqa: PLC0415
    from types import SimpleNamespace  # noqa: PLC0415

    from fastapi import FastAPI  # noqa: PLC0415

    import api.main as main  # noqa: PLC0415
    from config import settings  # noqa: PLC0415

    seen: dict = {}

    def fake_load(path, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(count=1, manifest={"embedding_model": settings.embedding_model})

    monkeypatch.setattr(main.FaissIndex, "load", staticmethod(fake_load))
    monkeypatch.setattr(main, "connect", lambda path: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(main.BM25Corpus, "from_db", classmethod(lambda cls, conn: SimpleNamespace(count=1)))
    monkeypatch.setattr(main, "_build_inference_stack", lambda log: (object(), None))

    async def run() -> None:
        async with main.lifespan(FastAPI()):
            pass

    asyncio.run(run())
    assert seen == {"expected_model": settings.embedding_model, "verify_checksums": True}

