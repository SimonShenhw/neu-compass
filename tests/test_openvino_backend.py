"""Tests for rag.openvino_backend — OvEmbedder / OvReranker / warm_up.

This backend is what production actually runs on the NAS (Iris Xe via
optimum-intel), so the pooling / sigmoid / shape logic gets pinned here
with fake model+tokenizer objects — exactly the injection seam the
constructors were designed for (no optimum-intel / torch install needed).

The fakes speak the same dialect as the real stack: the backend calls
`outputs.last_hidden_state[:, 0, :].numpy()` (embedder) and
`outputs.logits.squeeze(-1).numpy()` (reranker), so the fakes return a
minimal tensor wrapper exposing exactly that surface — backed by numpy,
keeping the test independent of torch (which the real tokenizer returns
but the backend only touches through these three methods).
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from rag.openvino_backend import (
    EMBEDDING_DIM,
    OvEmbedder,
    OvReranker,
    _build_ov_config,
    warm_up,
)


# === fakes ===


class _NpTensor:
    """Duck-typed stand-in for the torch tensors the backend slices: supports
    __getitem__ / squeeze / numpy — the only three ops the backend uses."""

    def __init__(self, arr: np.ndarray) -> None:
        self._arr = arr

    def __getitem__(self, key) -> _NpTensor:
        return _NpTensor(self._arr[key])

    def squeeze(self, axis: int) -> _NpTensor:
        return _NpTensor(self._arr.squeeze(axis))

    def numpy(self) -> np.ndarray:
        return self._arr


class _FakeTokenizer:
    """Captures call kwargs; emits deterministic (batch, seq) id arrays.

    input_ids row i is filled with (total character length of input i) so
    the fake models can derive per-row outputs from the encoding alone.
    """

    def __init__(self) -> None:
        self.last_kwargs: dict | None = None

    def __call__(self, texts, pair=None, **kwargs):
        self.last_kwargs = kwargs
        batch = len(texts)
        seq = 8
        ids = np.zeros((batch, seq), dtype=np.int64)
        for i in range(batch):
            ids[i, :] = len(texts[i]) + (len(pair[i]) if pair is not None else 0)
        return {
            "input_ids": ids,
            "attention_mask": np.ones((batch, seq), dtype=np.int64),
        }


class _FakeFeatureModel:
    """last_hidden_state[b, t, d] = input_ids[b, 0] / (d + 1) — CLS pooling
    then sees a distinct, deterministic vector per distinct input."""

    def __call__(self, *, input_ids, attention_mask):
        batch, seq = input_ids.shape
        base = input_ids[:, 0].astype(np.float32)  # (batch,)
        dims = 1.0 / (np.arange(EMBEDDING_DIM, dtype=np.float32) + 1.0)
        hidden = base[:, None, None] * dims[None, None, :]  # (batch, 1, dim)
        hidden = np.broadcast_to(hidden, (batch, seq, EMBEDDING_DIM)).copy()
        return SimpleNamespace(last_hidden_state=_NpTensor(hidden))


class _FakeClassifierModel:
    """logits[b] = input_ids[b, 0] / 100 - 1 → varies with pair length."""

    def __call__(self, *, input_ids, attention_mask):
        logits = (input_ids[:, 0].astype(np.float32) / 100.0 - 1.0).reshape(-1, 1)
        return SimpleNamespace(logits=_NpTensor(logits))


# === _build_ov_config ===


def test_ov_config_latency_hint_always_set() -> None:
    assert _build_ov_config(cache_dir=None) == {"PERFORMANCE_HINT": "LATENCY"}


def test_ov_config_cache_dir_included_when_given() -> None:
    cfg = _build_ov_config(cache_dir="/data/openvino_cache")
    assert cfg["CACHE_DIR"] == "/data/openvino_cache"


# === OvEmbedder ===


def test_embedder_empty_input_returns_zero_rows() -> None:
    emb = OvEmbedder(model=_FakeFeatureModel(), tokenizer=_FakeTokenizer())
    out = emb.encode([])
    assert out.shape == (0, EMBEDDING_DIM)
    assert out.dtype == np.float32


def test_embedder_output_shape_and_dtype() -> None:
    emb = OvEmbedder(model=_FakeFeatureModel(), tokenizer=_FakeTokenizer())
    out = emb.encode(["graph algorithms", "neural nets"])
    assert out.shape == (2, EMBEDDING_DIM)
    assert out.dtype == np.float32


def test_embedder_l2_normalizes_by_default() -> None:
    emb = OvEmbedder(model=_FakeFeatureModel(), tokenizer=_FakeTokenizer())
    out = emb.encode(["graph algorithms", "x"])
    norms = np.linalg.norm(out, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_embedder_normalize_false_keeps_raw_scale() -> None:
    emb = OvEmbedder(model=_FakeFeatureModel(), tokenizer=_FakeTokenizer())
    out = emb.encode(["a long input string here"], normalize=False)
    assert not np.allclose(np.linalg.norm(out, axis=1), 1.0)


def test_embedder_passes_max_length_to_tokenizer() -> None:
    tok = _FakeTokenizer()
    emb = OvEmbedder(model=_FakeFeatureModel(), tokenizer=tok, max_length=128)
    emb.encode(["hello"])
    assert tok.last_kwargs is not None
    assert tok.last_kwargs["max_length"] == 128
    assert tok.last_kwargs["truncation"] is True


# === OvReranker ===


def test_reranker_empty_candidates_returns_empty() -> None:
    rr = OvReranker(model=_FakeClassifierModel(), tokenizer=_FakeTokenizer())
    assert rr.score("query", []) == []


def test_reranker_scores_are_sigmoid_bounded() -> None:
    rr = OvReranker(model=_FakeClassifierModel(), tokenizer=_FakeTokenizer())
    scores = rr.score("q", ["short", "a much longer candidate text body"])
    assert len(scores) == 2
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_reranker_monotonic_in_fake_logit() -> None:
    """Fake logit grows with pair length — score order must follow."""
    rr = OvReranker(model=_FakeClassifierModel(), tokenizer=_FakeTokenizer())
    scores = rr.score("q", ["aa", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"])
    assert scores[1] > scores[0]


def test_reranker_single_candidate_no_squeeze_collapse() -> None:
    """batch=1 logits (1, 1) must squeeze to one score, not a scalar crash."""
    rr = OvReranker(model=_FakeClassifierModel(), tokenizer=_FakeTokenizer())
    scores = rr.score("q", ["only one"])
    assert len(scores) == 1


# === warm_up ===


def test_warm_up_dispatches_encode_and_score() -> None:
    calls: list[str] = []

    class _Enc:
        def encode(self, texts):
            calls.append("encode")

    class _Scr:
        def score(self, q, cands):
            calls.append("score")

    warm_up([_Enc(), _Scr()])
    assert calls == ["encode", "score"]
