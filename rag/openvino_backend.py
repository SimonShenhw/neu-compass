"""OpenVINO backend for bge-m3 + bge-reranker-v2-m3 via optimum-intel.

Drop-in replacement for OnnxEmbedder / OnnxReranker that runs inference
through OpenVINO Runtime *natively* (no ONNX intermediate). Implements
the same EmbedderProtocol / score(...) surface as the PyTorch/ONNX
backends so HybridRetriever + rerank_blend_with_rejection are unchanged.

Why this exists when we already have ONNX:
  The ONNX path (onnxruntime-openvino) chokes on Intel GPU compile of
  the bge-m3 model — `GatherND` with u8 indices isn't supported by the
  Intel GPU plugin's `program_builder`. The optimum-intel direct-to-IR
  export bypasses ONNX intermediate representation, so the GatherND
  surfaces with int64 indices that GPU compiles cleanly.

Latency on i5-1235U + Iris Xe 80EU (NAS), expected:
  - This backend (OpenVINO IR + Iris Xe GPU FP16): ~100-300 ms /search
  - ONNX + OpenVINO CPU EP (fallback, current):    ~7-10 s   /search
  See https://gist.github.com/ravi9/7023573645ed37a0c5e40b5b1b0af759
  + https://huggingface.co/docs/optimum-intel/openvino/inference

Setup:
  1. PC: `uv sync --extra openvino` (adds optimum-intel[openvino])
  2. PC: `uv run python scripts/export_openvino.py` (~5 min)
  3. Transfer ./openvino/{embedder,reranker} to NAS runtime-data/openvino/
  4. NAS: set INFERENCE_BACKEND=openvino + OPENVINO_MODEL_DIR=/data/openvino

Design:
  - `OvEmbedder` / `OvReranker` accept already-built model + tokenizer in
    __init__ so tests don't need optimum-intel installed.
  - `from_path()` classmethod is the production loader (lazy SDK import).
  - device + ov_config come from settings; default device="GPU" for Iris Xe.
  - CACHE_DIR points to a persistent volume so the GPU-compiled kernel cache
    survives container restarts (first boot ~60s, subsequent boots ~5s).
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Iterable
from typing import Any

import numpy as np
import structlog

_log = structlog.get_logger("neu_compass.openvino")

EMBEDDING_DIM = 1024  # bge-m3 dense vector dimension (mirrors rag.embedder)

# Single-query embedding cache size. Repeats are STRUCTURAL, not
# hypothetical: the UI's hero sample chips and follow-up chips send
# fixed query strings, so every first-time visitor and every chip click
# re-embeds the same handful of texts (~50-100ms each on Iris Xe).
_QUERY_CACHE_SIZE = 256


def _build_ov_config(*, cache_dir: str | None) -> dict[str, str]:
    """Return ov_config dict tuned for low-latency single-query inference.

    PERFORMANCE_HINT=LATENCY tells OpenVINO to optimize for minimum p50
    latency rather than throughput. CACHE_DIR persists compiled GPU
    kernels across restarts (first boot pays the compile cost once).
    """
    cfg = {"PERFORMANCE_HINT": "LATENCY"}
    if cache_dir:
        cfg["CACHE_DIR"] = cache_dir
    return cfg


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (vectors / norms).astype(np.float32)


class OvEmbedder:
    """OpenVINO-backed embedder (bge-m3 family).

    Loads an `OVModelForFeatureExtraction` and performs CLS-token pooling
    + L2 normalization — matches FlagEmbedding's `encode(return_dense=True)`
    output bit-for-bit (within FP16 quantization noise).
    """

    def __init__(
        self,
        *,
        model: Any,
        tokenizer: Any,
        max_length: int = 512,
    ) -> None:
        self._model = model
        self._tokenizer = tokenizer
        self.max_length = max_length
        # optimum-intel OVModel* hold ONE OpenVINO InferRequest — concurrent
        # forward passes on the same instance are NOT safe. Sync routes run
        # in FastAPI's threadpool, so serialize inference here.
        self._lock = threading.Lock()
        # LRU for the single-text (query) case only — document batches
        # during indexing must not evict query entries or bloat memory.
        # Guarded by the same lock as inference (dict ops are cheap).
        self._query_cache: OrderedDict[tuple[str, bool], np.ndarray] = (
            OrderedDict()
        )

    @classmethod
    def from_path(
        cls,
        model_dir: str,
        *,
        tokenizer_id: str = "BAAI/bge-m3",
        max_length: int = 512,
        device: str = "GPU",
        cache_dir: str | None = None,
    ) -> OvEmbedder:
        """Production loader. Lazy imports so tests don't pay the cost.

        `device` accepts standard OpenVINO device strings: "GPU", "CPU",
        "AUTO:GPU,CPU", "MULTI:GPU,CPU", etc. Default "GPU" targets the
        integrated Iris Xe on the NAS.
        """
        from optimum.intel import OVModelForFeatureExtraction  # noqa: PLC0415
        from transformers import AutoTokenizer  # noqa: PLC0415

        model = OVModelForFeatureExtraction.from_pretrained(
            model_dir,
            device=device,
            ov_config=_build_ov_config(cache_dir=cache_dir),
        )
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_id)
        return cls(model=model, tokenizer=tokenizer, max_length=max_length)

    def encode(self, texts: list[str], *, normalize: bool = True) -> np.ndarray:
        if not texts:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

        # Single-text fast path: query embeddings are deterministic, and
        # the UI's fixed sample/follow-up chips guarantee verbatim repeats.
        cache_key = (texts[0], normalize) if len(texts) == 1 else None
        if cache_key is not None:
            with self._lock:
                hit = self._query_cache.get(cache_key)
                if hit is not None:
                    self._query_cache.move_to_end(cache_key)
                    return hit[np.newaxis, :].copy()

        # Tokenization INSIDE the lock on purpose: the shared HF fast
        # tokenizer (Rust) raises "Already borrowed" under concurrent
        # truncation/padding re-config — FastAPI's threadpool can run two
        # /search requests at once. Mirrors the pytorch backend's locking.
        with self._lock:
            encoded = self._tokenizer(
                texts,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            outputs = self._model(**encoded)
        # last_hidden_state shape: (batch, seq_len, hidden_dim). CLS-pool [:, 0, :].
        cls_emb = outputs.last_hidden_state[:, 0, :].numpy().astype(np.float32)
        if normalize:
            cls_emb = _l2_normalize(cls_emb)

        if cache_key is not None:
            with self._lock:
                self._query_cache[cache_key] = cls_emb[0].copy()
                self._query_cache.move_to_end(cache_key)
                while len(self._query_cache) > _QUERY_CACHE_SIZE:
                    self._query_cache.popitem(last=False)
        return cls_emb


class OvReranker:
    """OpenVINO-backed cross-encoder reranker (bge-reranker-v2-m3 family).

    Mirrors `CrossEncoderReranker.score(query, candidates)`: tokenizes
    (query, candidate) pairs together and returns sigmoid scores in [0, 1].
    """

    def __init__(
        self,
        *,
        model: Any,
        tokenizer: Any,
        max_length: int = 512,
    ) -> None:
        self._model = model
        self._tokenizer = tokenizer
        self.max_length = max_length
        self._lock = threading.Lock()  # see OvEmbedder.__init__

    @classmethod
    def from_path(
        cls,
        model_dir: str,
        *,
        tokenizer_id: str = "BAAI/bge-reranker-v2-m3",
        max_length: int = 512,
        device: str = "GPU",
        cache_dir: str | None = None,
    ) -> OvReranker:
        from optimum.intel import OVModelForSequenceClassification  # noqa: PLC0415
        from transformers import AutoTokenizer  # noqa: PLC0415

        model = OVModelForSequenceClassification.from_pretrained(
            model_dir,
            device=device,
            ov_config=_build_ov_config(cache_dir=cache_dir),
        )
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_id)
        return cls(model=model, tokenizer=tokenizer, max_length=max_length)

    def score(self, query: str, candidates: list[str]) -> list[float]:
        if not candidates:
            return []

        # Tokenize inside the lock — see OvEmbedder.encode for why.
        with self._lock:
            encoded = self._tokenizer(
                [query] * len(candidates),
                candidates,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            # Measurement hook for the max_length A/B (RERANKER_MAX_LENGTH):
            # padded seq len tells us how much of the 512 budget real pools
            # use. DEBUG level — invisible at the prod INFO default.
            _log.debug(
                "reranker.batch",
                pairs=len(candidates),
                padded_len=int(encoded["input_ids"].shape[1]),
                max_length=self.max_length,
            )
            outputs = self._model(**encoded)
        # logits shape (batch, 1) for cross-encoder binary head.
        logits = outputs.logits.squeeze(-1).numpy().astype(np.float32)
        sigmoid = 1.0 / (1.0 + np.exp(-logits))
        return [float(s) for s in sigmoid.tolist()]


def warm_up(targets: Iterable[Any]) -> None:
    """Run a single dummy inference per target so OpenVINO finishes any
    deferred device compile + warms the kernel cache. The first real
    request after this is fast.
    """
    for t in targets:
        if hasattr(t, "encode"):
            t.encode(["warmup"])
        elif hasattr(t, "score"):
            t.score("warmup", ["warmup"])


__all__ = [
    "EMBEDDING_DIM",
    "OvEmbedder",
    "OvReranker",
    "warm_up",
]
