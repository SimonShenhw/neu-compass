"""Tests for rag.index — real FAISS, no embedder dependency."""

from __future__ import annotations

from pathlib import Path

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
