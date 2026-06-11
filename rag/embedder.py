"""bge-m3 embedder wrapper.

bge-m3 is multilingual + multi-granularity, suitable for the中英 mixed query
mix we expect from NEU students. Output: 1024-dim dense vectors,
L2-normalized so FAISS IndexFlatIP behaves as cosine similarity.

The model is ~2.3GB on first download. Tests should NOT trigger this —
inject a FakeEmbedder via the EmbedderProtocol instead. BGEM3Embedder
itself loads the model lazily (first .encode() call) so importing this
module is cheap.
"""

from __future__ import annotations

import threading
from typing import Protocol

import numpy as np

EMBEDDING_DIM = 1024  # bge-m3 dense vector dimension


class EmbedderProtocol(Protocol):
    """Minimal interface for any embedder. Tests pass a fake; production
    uses BGEM3Embedder. Output shape: (len(texts), EMBEDDING_DIM) float32."""

    def encode(self, texts: list[str], *, normalize: bool = True) -> np.ndarray: ...


class BGEM3Embedder:
    """BAAI/bge-m3 with FlagEmbedding. Lazy load on first encode().

    Set device='cpu' to skip GPU. On 5090 + cu128, batch=32 should embed
    ~1k chunks in a few seconds. Caller controls batch_size to balance
    throughput vs VRAM (max_length=8192 means a batch of 32 is ~10GB).

    `compile_mode` is a Week 9 Day 2 hook: when set (e.g. "default",
    "reduce-overhead"), the inner XLMRoberta backbone is wrapped via
    torch.compile after load. Best-effort — if FlagEmbedding's internal
    structure changes, the wrap silently no-ops with a warning so the
    embedder still works.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        *,
        device: str = "cuda",
        use_fp16: bool = True,
        batch_size: int = 32,
        max_length: int = 8192,
        compile_mode: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.use_fp16 = use_fp16
        self.batch_size = batch_size
        self.max_length = max_length
        self.compile_mode = compile_mode
        self._model: object | None = None
        # Sync routes run in FastAPI's threadpool; serialize lazy load +
        # forward pass (FlagEmbedding makes no thread-safety promise).
        self._lock = threading.Lock()

    def _load(self) -> object:
        """First-call model download + load. Triggers ~2.3GB download."""
        if self._model is not None:
            return self._model

        # Lazy import: don't drag FlagEmbedding + torch into every test that
        # only needs the fake.
        from FlagEmbedding import BGEM3FlagModel  # noqa: PLC0415

        self._model = BGEM3FlagModel(
            self.model_name,
            use_fp16=self.use_fp16,
            devices=[self.device] if self.device else None,
        )

        if self.compile_mode:
            _try_compile_inner_backbone(self._model, mode=self.compile_mode)

        return self._model

    def encode(self, texts: list[str], *, normalize: bool = True) -> np.ndarray:
        if not texts:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

        with self._lock:
            model = self._load()
            # FlagEmbedding's BGEM3FlagModel.encode returns dict; we want dense.
            out = model.encode(  # type: ignore[attr-defined]
                texts,
                batch_size=self.batch_size,
                max_length=self.max_length,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
        vecs = np.asarray(out["dense_vecs"], dtype=np.float32)

        if normalize:
            vecs = _l2_normalize(vecs)
        return vecs


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    """Normalize each row to unit L2 norm. Returns float32. Zero rows stay zero."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (vectors / norms).astype(np.float32)


def _try_compile_inner_backbone(flag_model: object, *, mode: str) -> None:
    """Wrap FlagEmbedding's inner XLMRoberta backbone with torch.compile.

    FlagEmbedding 1.x layout: BGEM3FlagModel.model is the BGE wrapper, and
    `.model.model` is the actual transformers backbone (an nn.Module). We
    can torch.compile the backbone in place — FlagEmbedding's encode() will
    call the compiled forward path automatically.

    Best-effort: any failure (FlagEmbedding internal restructure, torch.compile
    not supported on the device, OOM during compile) downgrades to a warning
    and leaves the un-compiled model in place. The embedder still works,
    just at PyTorch baseline speed.

    The `inner is None` early return is deliberately placed BEFORE the
    `import torch` so callers that ship without GPU / without torch (rare
    but possible) — and unit tests with a stub flag_model — don't pay the
    ~2s torch lazy-import cost just to learn the wrap is unreachable.
    """
    inner = getattr(flag_model, "model", None)
    backbone = getattr(inner, "model", None) if inner is not None else None
    if backbone is None:
        print(
            "warning: BGEM3Embedder compile_mode set but FlagEmbedding's "
            "inner backbone not found at .model.model — skipping compile"
        )
        return

    try:
        import torch  # noqa: PLC0415

        if not isinstance(backbone, torch.nn.Module):
            print(
                "warning: BGEM3Embedder inner backbone is not a torch.nn.Module — "
                "skipping compile"
            )
            return
        compiled = torch.compile(backbone, mode=mode)
        inner.model = compiled
    except Exception as e:  # noqa: BLE001 — best-effort wrap
        print(f"warning: torch.compile failed for BGEM3Embedder: {e}")


__all__ = ["EMBEDDING_DIM", "BGEM3Embedder", "EmbedderProtocol"]
