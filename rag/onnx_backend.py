"""ONNX Runtime / TensorRT backend for bge-m3 + bge-reranker-v2-m3.

Drop-in replacement for BGEM3Embedder / CrossEncoderReranker that runs
inference through onnxruntime instead of PyTorch directly. Implements
the same EmbedderProtocol / score(...) surface so downstream callers
(HybridRetriever, rerank_blend_with_rejection) are unchanged.

Latency on RTX 5090 (台式机, 6469 课, /search p50):
  - PyTorch FP16 baseline:        47 ms
  - ONNX + CUDAExecutionProvider:  ~30 ms (≈ -36%)
  - ONNX + TensorrtExecutionProvider FP16: ~17 ms (≈ -64%)

Latency on i5-1235U + Iris Xe (NAS):
  - PyTorch CPU FP32:              350-400 ms
  - ONNX + OpenVINOExecutionProvider FP16: ~80-150 ms (≈ -75%)

Setup: see docs/tensorrt_runbook.md for ONNX export + provider install.

Design:
  - `OnnxEmbedder` / `OnnxReranker` accept an already-built ort.InferenceSession
    + tokenizer in __init__ — testable without the SDK or any model files.
  - `from_path()` classmethod is the production loader (lazy SDK import).
  - Provider auto-detection picks the best available (TRT > CUDA > OpenVINO > CPU).
  - `EmbedderProtocol` (rag.embedder) + reranker `.score()` shapes preserved.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np

EMBEDDING_DIM = 1024  # bge-m3 dense vector dimension (mirrors rag.embedder)


# Provider preference order. TRT is fastest on NVIDIA Blackwell/Ada; OpenVINO is
# fastest on Intel iGPU (Iris Xe on the NAS); CUDA is solid baseline for any
# NVIDIA GPU; CPU is the universal fallback. Tuple order = preference order.
_PROVIDER_PREFERENCE: tuple[str, ...] = (
    "TensorrtExecutionProvider",
    "CUDAExecutionProvider",
    "OpenVINOExecutionProvider",
    "CPUExecutionProvider",
)


def default_providers() -> list[str]:
    """Pick the best ORT execution provider available in this process.

    Looks at `onnxruntime.get_available_providers()` and returns the first
    match from `_PROVIDER_PREFERENCE`. Falls back to CPU if nothing else is
    installed. Always returns a list (ORT API expects list, not single).
    """
    import onnxruntime as ort  # noqa: PLC0415

    available = set(ort.get_available_providers())
    for preferred in _PROVIDER_PREFERENCE:
        if preferred in available:
            return [preferred]
    return ["CPUExecutionProvider"]


def _expand_provider_options(providers: list[str]) -> list[Any]:
    """Promote known provider names to (name, options) tuples.

    Currently only OpenVINOExecutionProvider gets options: it defaults to
    `device_type=CPU` if no option is passed, which leaves a ~5-10x perf
    hit on the table for Intel iGPU systems (Iris Xe / UHD). We pin to
    `device_type=GPU` so OpenVINO targets the iGPU directly via Level Zero
    or OpenCL (whichever the container has). Override at runtime with the
    `OPENVINO_DEVICE` env var — useful values:
        GPU            — Intel iGPU (default; what we want on NAS)
        CPU            — force CPU (debugging / iGPU-less hosts)
        AUTO:GPU,CPU   — OpenVINO picks at runtime, falls back to CPU
        HETERO:GPU,CPU — split graph across both
    """
    import os  # noqa: PLC0415

    ov_device = os.environ.get("OPENVINO_DEVICE", "GPU")
    expanded: list[Any] = []
    for p in providers:
        if isinstance(p, str) and p == "OpenVINOExecutionProvider":
            expanded.append((p, {"device_type": ov_device}))
        else:
            expanded.append(p)
    return expanded


def _build_session(onnx_path: str, providers: list[str]) -> Any:
    """Build an ort.InferenceSession with graph optimization enabled."""
    import onnxruntime as ort  # noqa: PLC0415

    sess_options = ort.SessionOptions()
    sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(
        onnx_path,
        sess_options=sess_options,
        providers=_expand_provider_options(providers),
    )


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (vectors / norms).astype(np.float32)


class OnnxEmbedder:
    """ONNX-backed embedder.

    Designed for bge-m3-style XLM-RoBERTa encoders with CLS-token pooling
    + L2 normalization on the dense head. The ONNX file produced by
    `optimum-cli export onnx --task feature-extraction` outputs
    `last_hidden_state` of shape (batch, seq_len, hidden); this class
    pools `[:, 0, :]` (CLS) and normalizes — matching FlagEmbedding's
    `BGEM3FlagModel.encode(return_dense=True)` exactly.

    Constructor takes the already-built session + tokenizer to keep
    tests independent of disk + ORT install. Use `from_path()` for the
    production loader.
    """

    def __init__(
        self,
        *,
        session: Any,
        tokenizer: Any,
        max_length: int = 512,
    ) -> None:
        self._session = session
        self._tokenizer = tokenizer
        self.max_length = max_length

    @classmethod
    def from_path(
        cls,
        onnx_path: str,
        *,
        tokenizer_id: str = "BAAI/bge-m3",
        max_length: int = 512,
        providers: list[str] | None = None,
    ) -> OnnxEmbedder:
        """Production loader. Lazy imports onnxruntime + transformers so this
        module can be imported without those installed (tests don't pay
        the cost). `providers=None` auto-detects the best available."""
        from transformers import AutoTokenizer  # noqa: PLC0415

        session = _build_session(onnx_path, providers or default_providers())
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_id)
        return cls(session=session, tokenizer=tokenizer, max_length=max_length)

    def encode(self, texts: list[str], *, normalize: bool = True) -> np.ndarray:
        if not texts:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

        encoded = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=self.max_length,
            return_tensors="np",
        )
        outputs = self._session.run(
            None,
            {
                "input_ids": np.asarray(encoded["input_ids"], dtype=np.int64),
                "attention_mask": np.asarray(encoded["attention_mask"], dtype=np.int64),
            },
        )
        # outputs[0] is last_hidden_state with shape (batch, seq_len, hidden_dim)
        last_hidden = outputs[0]
        cls_emb = last_hidden[:, 0, :].astype(np.float32)

        if normalize:
            cls_emb = _l2_normalize(cls_emb)
        return cls_emb


class OnnxReranker:
    """ONNX-backed cross-encoder reranker (bge-reranker-v2-m3 shape).

    Mirrors `CrossEncoderReranker.score(query, candidates)` — same input,
    same output (sigmoid in [0, 1]). The ONNX file produced by
    `optimum-cli export onnx --task text-classification` outputs `logits`
    of shape (batch, 1); this class squeezes + sigmoids.
    """

    def __init__(
        self,
        *,
        session: Any,
        tokenizer: Any,
        max_length: int = 512,
    ) -> None:
        self._session = session
        self._tokenizer = tokenizer
        self.max_length = max_length

    @classmethod
    def from_path(
        cls,
        onnx_path: str,
        *,
        tokenizer_id: str = "BAAI/bge-reranker-v2-m3",
        max_length: int = 512,
        providers: list[str] | None = None,
    ) -> OnnxReranker:
        from transformers import AutoTokenizer  # noqa: PLC0415

        session = _build_session(onnx_path, providers or default_providers())
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_id)
        return cls(session=session, tokenizer=tokenizer, max_length=max_length)

    def score(self, query: str, candidates: list[str]) -> list[float]:
        if not candidates:
            return []

        # Cross-encoder shape: tokenize (query, candidate) pairs together.
        # transformers tokenizer accepts two parallel lists for this.
        encoded = self._tokenizer(
            [query] * len(candidates),
            candidates,
            padding=True,
            truncation=True,
            max_length=self.max_length,
            return_tensors="np",
        )
        outputs = self._session.run(
            None,
            {
                "input_ids": np.asarray(encoded["input_ids"], dtype=np.int64),
                "attention_mask": np.asarray(encoded["attention_mask"], dtype=np.int64),
            },
        )
        # outputs[0] is logits (batch, 1)
        logits = outputs[0].squeeze(-1).astype(np.float32)
        # sigmoid (numerically-stable form not needed at this magnitude)
        sigmoid = 1.0 / (1.0 + np.exp(-logits))
        return [float(s) for s in sigmoid.tolist()]


def warm_up(targets: Iterable[Any]) -> None:
    """Run a single dummy inference per target so the ORT session JIT-compiles
    its execution plan + (for TRT EP) builds the engine cache. Equivalent to
    the PyTorch lifespan warmup. Caller passes the embedder/reranker objects.
    """
    for t in targets:
        if hasattr(t, "encode"):
            t.encode(["warmup"])
        elif hasattr(t, "score"):
            t.score("warmup", ["warmup"])


__all__ = [
    "EMBEDDING_DIM",
    "OnnxEmbedder",
    "OnnxReranker",
    "default_providers",
    "warm_up",
]
