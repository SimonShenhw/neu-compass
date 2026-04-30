"""Tests for rag.embedder. BGEM3Embedder is NOT instantiated (would download
2.3GB model); we test the lazy-load contract + the L2 normalization helper.
"""

from __future__ import annotations

import numpy as np

from rag.embedder import EMBEDDING_DIM, BGEM3Embedder, _l2_normalize


def test_embedding_dim_is_1024() -> None:
    assert EMBEDDING_DIM == 1024


def test_bgem3_embedder_init_does_not_load_model() -> None:
    """Construction must NOT trigger the 2.3GB download."""
    e = BGEM3Embedder()
    assert e._model is None
    assert e.model_name == "BAAI/bge-m3"


def test_bgem3_embedder_init_overrides() -> None:
    e = BGEM3Embedder(model_name="custom/model", device="cpu",
                      use_fp16=False, batch_size=8, max_length=512)
    assert e.device == "cpu"
    assert e.use_fp16 is False
    assert e.batch_size == 8
    assert e.max_length == 512


def test_encode_empty_returns_empty_array() -> None:
    """Edge case: empty input must not trigger model load."""
    e = BGEM3Embedder()
    out = e.encode([])
    assert out.shape == (0, EMBEDDING_DIM)
    assert out.dtype == np.float32
    assert e._model is None  # still not loaded


# === L2 normalization ===

def test_l2_normalize_unit_vectors() -> None:
    v = np.array([[3.0, 4.0, 0.0]])
    out = _l2_normalize(v)
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0)


def test_l2_normalize_preserves_direction() -> None:
    v = np.array([[1.0, 2.0, 3.0]])
    out = _l2_normalize(v)
    expected = v / np.linalg.norm(v)
    assert np.allclose(out, expected)


def test_l2_normalize_zero_vector_stays_zero() -> None:
    """Zero rows should not divide-by-zero. Stay zero."""
    v = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    out = _l2_normalize(v)
    assert np.allclose(out[0], 0.0)
    assert np.allclose(np.linalg.norm(out[1]), 1.0)


def test_l2_normalize_returns_float32() -> None:
    v = np.array([[1.0, 1.0]], dtype=np.float64)
    out = _l2_normalize(v)
    assert out.dtype == np.float32


def test_l2_normalize_batch() -> None:
    v = np.random.randn(10, EMBEDDING_DIM).astype(np.float32)
    out = _l2_normalize(v)
    norms = np.linalg.norm(out, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)
