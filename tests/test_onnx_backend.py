"""Tests for rag.onnx_backend — uses fake ORT sessions + fake tokenizers.

No onnxruntime / transformers / disk dependency — these tests run in
CI even on machines without optimum / ORT installed. Production
correctness (real bge-m3 / real ORT session) is verified by the
post-export smoke step in docs/tensorrt_runbook.md §4.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from rag.onnx_backend import EMBEDDING_DIM, OnnxEmbedder, OnnxReranker, warm_up

# === Test doubles ===


class _FakeSession:
    """Mimics ort.InferenceSession.run() — captures calls + returns canned output."""

    def __init__(self, output: np.ndarray | list[np.ndarray]):
        self._output = output if isinstance(output, list) else [output]
        self.calls: list[dict[str, np.ndarray]] = []

    def run(
        self,
        output_names: list[str] | None,
        inputs: dict[str, np.ndarray],
    ) -> list[np.ndarray]:
        self.calls.append(inputs)
        return self._output


class _FakeTokenizer:
    """Mimics a transformers tokenizer with __call__(texts, ...) signature.

    Returns a dict shaped like the real tokenizer output (input_ids +
    attention_mask) so OnnxEmbedder / OnnxReranker .run() input matches
    what the production session would expect.
    """

    def __init__(self, *, fixed_seq_len: int = 5):
        self._seq_len = fixed_seq_len
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        texts: list[str] | str,
        text_pair: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, np.ndarray]:
        self.calls.append({"texts": texts, "text_pair": text_pair, "kwargs": kwargs})
        n = len(texts) if isinstance(texts, list) else 1
        return {
            "input_ids": np.array([[101, 102, 103, 104, 102]] * n, dtype=np.int64),
            "attention_mask": np.ones((n, self._seq_len), dtype=np.int64),
        }


# === OnnxEmbedder ===


def test_embedder_empty_input_returns_empty() -> None:
    emb = OnnxEmbedder(
        session=_FakeSession(np.zeros((0, 5, EMBEDDING_DIM), dtype=np.float32)),
        tokenizer=_FakeTokenizer(),
    )
    out = emb.encode([])
    assert out.shape == (0, EMBEDDING_DIM)


def test_embedder_cls_pools_then_l2_normalizes() -> None:
    """Output last_hidden_state[:, 0, :] should be L2-normalized to unit length."""
    # 2 texts, seq_len=5, hidden=1024. Use fixed values so we can verify
    # normalization behavior deterministically.
    fake_hidden = np.zeros((2, 5, EMBEDDING_DIM), dtype=np.float32)
    fake_hidden[0, 0, 0] = 3.0  # CLS for text 0: [3, 0, 0, ...]
    fake_hidden[0, 0, 1] = 4.0  # → norm 5, normalized [0.6, 0.8, 0, ...]
    fake_hidden[1, 0, :3] = [1.0, 2.0, 2.0]  # CLS for text 1: norm 3

    emb = OnnxEmbedder(session=_FakeSession(fake_hidden), tokenizer=_FakeTokenizer())
    out = emb.encode(["hello", "world"])

    assert out.shape == (2, EMBEDDING_DIM)
    np.testing.assert_allclose(out[0, 0], 0.6, atol=1e-5)
    np.testing.assert_allclose(out[0, 1], 0.8, atol=1e-5)
    # All rows should have unit L2 norm
    norms = np.linalg.norm(out, axis=1)
    np.testing.assert_allclose(norms, [1.0, 1.0], atol=1e-5)


def test_embedder_normalize_false_skips_l2() -> None:
    fake_hidden = np.zeros((1, 5, EMBEDDING_DIM), dtype=np.float32)
    fake_hidden[0, 0, 0] = 3.0
    fake_hidden[0, 0, 1] = 4.0

    emb = OnnxEmbedder(session=_FakeSession(fake_hidden), tokenizer=_FakeTokenizer())
    out = emb.encode(["x"], normalize=False)

    # Raw CLS values, no normalization
    assert out[0, 0] == 3.0
    assert out[0, 1] == 4.0


def test_embedder_passes_input_ids_int64() -> None:
    """ORT-TRT EP rejects int32 input_ids; the backend must cast to int64."""
    fake_hidden = np.zeros((1, 5, EMBEDDING_DIM), dtype=np.float32)
    fake_session = _FakeSession(fake_hidden)
    emb = OnnxEmbedder(session=fake_session, tokenizer=_FakeTokenizer())
    emb.encode(["q"])

    inputs = fake_session.calls[0]
    assert inputs["input_ids"].dtype == np.int64
    assert inputs["attention_mask"].dtype == np.int64


def test_embedder_zero_vector_normalize_safe() -> None:
    """All-zero CLS shouldn't divide-by-zero out — should stay all-zero."""
    fake_hidden = np.zeros((1, 5, EMBEDDING_DIM), dtype=np.float32)
    emb = OnnxEmbedder(session=_FakeSession(fake_hidden), tokenizer=_FakeTokenizer())
    out = emb.encode(["q"])
    assert np.allclose(out, 0.0)
    assert not np.isnan(out).any()


# === OnnxReranker ===


def test_reranker_empty_candidates_returns_empty() -> None:
    rer = OnnxReranker(
        session=_FakeSession(np.zeros((0, 1), dtype=np.float32)),
        tokenizer=_FakeTokenizer(),
    )
    assert rer.score("q", []) == []


def test_reranker_logit_to_sigmoid() -> None:
    """logit 0 → sigmoid 0.5; logit +∞-ish → sigmoid ~1; logit -∞-ish → ~0."""
    fake_logits = np.array([[0.0], [10.0], [-10.0]], dtype=np.float32)
    rer = OnnxReranker(
        session=_FakeSession(fake_logits),
        tokenizer=_FakeTokenizer(),
    )
    scores = rer.score("q", ["a", "b", "c"])
    assert len(scores) == 3
    np.testing.assert_allclose(scores[0], 0.5, atol=1e-5)
    assert scores[1] > 0.999
    assert scores[2] < 0.001


def test_reranker_passes_query_and_candidates_paired() -> None:
    """Cross-encoder format: tokenizer is called with [query]*N + candidates."""
    fake_logits = np.array([[1.0], [2.0]], dtype=np.float32)
    fake_tokenizer = _FakeTokenizer()
    rer = OnnxReranker(session=_FakeSession(fake_logits), tokenizer=fake_tokenizer)
    rer.score("query text", ["candidate A", "candidate B"])

    call = fake_tokenizer.calls[0]
    assert call["texts"] == ["query text", "query text"]
    assert call["text_pair"] == ["candidate A", "candidate B"]


def test_reranker_returns_python_floats_not_numpy() -> None:
    """Downstream zscore_blend/JSON serialization expects Python float."""
    fake_logits = np.array([[0.0], [1.0]], dtype=np.float32)
    rer = OnnxReranker(
        session=_FakeSession(fake_logits),
        tokenizer=_FakeTokenizer(),
    )
    scores = rer.score("q", ["a", "b"])
    assert all(isinstance(s, float) for s in scores)


# === warm_up helper ===


def test_warm_up_calls_encode_on_embedders() -> None:
    """warm_up should dispatch by attribute presence, hitting .encode for
    embedders and .score for rerankers."""
    fake_hidden = np.zeros((1, 5, EMBEDDING_DIM), dtype=np.float32)
    fake_logits = np.array([[0.5]], dtype=np.float32)

    e_session = _FakeSession(fake_hidden)
    r_session = _FakeSession(fake_logits)
    emb = OnnxEmbedder(session=e_session, tokenizer=_FakeTokenizer())
    rer = OnnxReranker(session=r_session, tokenizer=_FakeTokenizer())

    warm_up([emb, rer])

    assert len(e_session.calls) == 1, "embedder should have been called once"
    assert len(r_session.calls) == 1, "reranker should have been called once"


# === default_providers ===


def test_default_providers_falls_back_to_cpu_when_others_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If only CPU EP is available, that's what we get."""
    import rag.onnx_backend as backend

    fake_ort = type("FakeOrt", (), {
        "get_available_providers": staticmethod(lambda: ["CPUExecutionProvider"]),
    })()
    # Inject the fake ort module — the function imports it lazily.
    import sys
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)

    assert backend.default_providers() == ["CPUExecutionProvider"]


def test_default_providers_prefers_tensorrt_over_cuda(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TRT EP is fastest; should be picked when both TRT and CUDA available."""
    import rag.onnx_backend as backend

    fake_ort = type("FakeOrt", (), {
        "get_available_providers": staticmethod(lambda: [
            "TensorrtExecutionProvider",
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ]),
    })()
    import sys
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)

    assert backend.default_providers() == ["TensorrtExecutionProvider"]


def test_default_providers_picks_openvino_for_intel_igpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Intel NAS path: OpenVINO EP available, no NVIDIA → use OpenVINO."""
    import rag.onnx_backend as backend

    fake_ort = type("FakeOrt", (), {
        "get_available_providers": staticmethod(lambda: [
            "OpenVINOExecutionProvider",
            "CPUExecutionProvider",
        ]),
    })()
    import sys
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)

    assert backend.default_providers() == ["OpenVINOExecutionProvider"]
