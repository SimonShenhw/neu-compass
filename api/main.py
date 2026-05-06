"""FastAPI app factory + lifespan pre-warm.

The pre-warm hook addresses docs/PLAN_v2.0.md §2.5: bge-m3 cold start is
~70s the first time `BGEM3FlagModel.encode()` is called. If the API
receives a user request before that completes, the request hangs until
the model loads. The lifespan calls `embedder.encode(["warmup"])` so the
load happens during startup, not under user latency.

ADR-0013 invariant: BM25 corpus and FAISS index are derived from SQLite.
Lifespan reads SQLite once at startup to build the BM25 in-memory; if
courses change at runtime (Week 6 has none — courses come from offline
seeds), restart the API to refresh.

Test path: `create_app(run_startup=False)` skips the heavy lifespan;
tests populate app.state with fakes manually. See tests/_api_helpers.py.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI

from api.exceptions import register_exception_handlers
from api.logging import RequestLogMiddleware, configure_logging
from api.routes import auth, chat, coop, course, health, search
from config import settings
from db.connection import connect
from rag.embedder import BGEM3Embedder
from rag.hybrid import BM25Corpus
from rag.index import FaissIndex
from rag.reranker import CrossEncoderReranker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Heavy startup: load FAISS, build BM25, warm embedder + reranker.

    Inference backend dispatch (PLAN Week 9 Day 1):
      - settings.inference_backend == 'pytorch' (default) → PyTorch path
        (FlagEmbedding bge-m3 + transformers cross-encoder), ~70s cold start.
      - settings.inference_backend == 'onnx' → ONNX Runtime path with
        auto-detected execution provider (TensorRT > CUDA > OpenVINO > CPU).
        Requires `uv sync --extra onnx` + `scripts/export_models_onnx.py` run.
        ~3x speedup on RTX 5090 with TRT EP; viable on Intel iGPU NAS via
        OpenVINO EP. See docs/tensorrt_runbook.md.

    Reranker is optional (settings.enable_reranker=False saves ~600 MB RAM
    for NAS deploy). /search degrades to bare hybrid+RRF when reranker is
    None — rejection layer (ADR-0016) becomes inactive in that mode.
    """
    log = configure_logging()
    log.info(
        "api.startup.begin",
        sqlite_path=settings.sqlite_path,
        faiss_index_path=settings.faiss_index_path,
        inference_backend=settings.inference_backend,
        enable_reranker=settings.enable_reranker,
    )

    # 1) FAISS — cheap (read from disk).
    faiss_index = FaissIndex.load(settings.faiss_index_path)
    log.info("api.startup.faiss_loaded", count=faiss_index.count)

    # 2) BM25 corpus from SQLite snapshot — cheap (≤1k docs in ~10ms).
    conn = connect(settings.sqlite_path)
    try:
        bm25_corpus = BM25Corpus.from_db(conn)
        log.info("api.startup.bm25_loaded", count=bm25_corpus.count)
    finally:
        conn.close()

    # 3) Embedder + (optional) reranker — backend-dispatched.
    embedder, reranker = _build_inference_stack(log)

    app.state.embedder = embedder
    app.state.faiss_index = faiss_index
    app.state.bm25_corpus = bm25_corpus
    app.state.reranker = reranker
    app.state.ready = True
    log.info("api.startup.ready")

    try:
        yield
    finally:
        log.info("api.shutdown")


def _build_inference_stack(log: Any) -> tuple[Any, Any]:
    """Construct (embedder, reranker) per settings.inference_backend.

    Returns (embedder, reranker | None). Both are warmed once (a dummy
    encode/score call) so the first user request doesn't pay the JIT/load
    cost. PyTorch path is the established 70s cold-start; ONNX path is
    typically faster but TRT EP first-build is one-off ~30-60s.
    """
    if settings.inference_backend == "onnx":
        return _build_onnx_stack(log)
    return _build_pytorch_stack(log)


def _build_pytorch_stack(log: Any) -> tuple[Any, Any]:
    embedder = BGEM3Embedder(device=settings.embedding_device)
    embedder.encode(["warmup"])
    log.info("api.startup.embedder_warm", backend="pytorch")

    if not settings.enable_reranker:
        log.info("api.startup.reranker_disabled", backend="pytorch")
        return embedder, None

    reranker = CrossEncoderReranker()
    reranker.score("warmup", ["warmup"])
    log.info("api.startup.reranker_warm", backend="pytorch")
    return embedder, reranker


def _build_onnx_stack(log: Any) -> tuple[Any, Any]:
    """ONNX Runtime backend — requires `uv sync --extra onnx` + exported models.

    Fails loudly (RuntimeError) if ONNX_MODEL_DIR is unset or models missing —
    silently falling back to PyTorch would mask a config error and ship the
    slow path to production.
    """
    from pathlib import Path  # noqa: PLC0415

    from rag.onnx_backend import (  # noqa: PLC0415
        OnnxEmbedder,
        OnnxReranker,
        default_providers,
    )

    if not settings.onnx_model_dir:
        raise RuntimeError(
            "INFERENCE_BACKEND=onnx but ONNX_MODEL_DIR not set. "
            "Run `uv run python scripts/export_models_onnx.py --fp16` and set "
            "ONNX_MODEL_DIR=<output path> in .env. "
            "See docs/tensorrt_runbook.md."
        )

    onnx_dir = Path(settings.onnx_model_dir).expanduser()
    embedder_path = onnx_dir / "embedder" / "model.onnx"
    reranker_path = onnx_dir / "reranker" / "model.onnx"

    if not embedder_path.exists():
        raise RuntimeError(
            f"ONNX embedder not found at {embedder_path}. "
            "Run `uv run python scripts/export_models_onnx.py --fp16` first."
        )

    providers = (
        default_providers()
        if settings.onnx_providers == "auto"
        else [p.strip() for p in settings.onnx_providers.split(",") if p.strip()]
    )
    log.info("api.startup.onnx_providers", providers=providers)

    embedder = OnnxEmbedder.from_path(
        str(embedder_path),
        tokenizer_id=settings.embedding_model,
        providers=providers,
    )
    embedder.encode(["warmup"])
    log.info("api.startup.embedder_warm", backend="onnx")

    if not settings.enable_reranker:
        log.info("api.startup.reranker_disabled", backend="onnx")
        return embedder, None

    if not reranker_path.exists():
        raise RuntimeError(
            f"ONNX reranker not found at {reranker_path}. "
            "Either run the exporter again or set ENABLE_RERANKER=false."
        )

    reranker = OnnxReranker.from_path(
        str(reranker_path),
        providers=providers,
    )
    reranker.score("warmup", ["warmup"])
    log.info("api.startup.reranker_warm", backend="onnx")
    return embedder, reranker


def create_app(*, run_startup: bool = True) -> FastAPI:
    """Build the FastAPI app. `run_startup=False` skips lifespan for tests
    that populate app.state with fakes."""
    app = FastAPI(
        title="NEU-Compass API",
        version="0.1.0",
        description="Course RAG + Co-op API. Internal MVP — F1 compliance, not commercial.",
        lifespan=lifespan if run_startup else None,
    )

    app.add_middleware(RequestLogMiddleware)
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(search.router)
    app.include_router(course.router)
    app.include_router(coop.router)
    app.include_router(chat.router)
    app.include_router(auth.router)

    return app


# Module-level instance for `uvicorn api.main:app` runs.
app = create_app()


__all__ = ["app", "create_app", "lifespan"]
