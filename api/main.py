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
from typing import AsyncIterator

from fastapi import FastAPI

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
    """Heavy startup: load FAISS, build BM25, warm bge-m3 (~70s)."""
    log = configure_logging()
    log.info(
        "api.startup.begin",
        sqlite_path=settings.sqlite_path,
        faiss_index_path=settings.faiss_index_path,
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

    # 3) bge-m3 model load + warm encode — the expensive one. Forces the
    # ~70s download/load HERE so the first user request doesn't pay it.
    embedder = BGEM3Embedder(device=settings.embedding_device)
    embedder.encode(["warmup"])
    log.info("api.startup.embedder_warm")

    # 4) bge-reranker-v2-m3 cross-encoder — second model load, ~30s. Powers
    # the rerank+blend+reject layer in /search (PLAN v2.2 §3.4 + §3.5).
    reranker = CrossEncoderReranker()
    reranker.score("warmup", ["warmup"])
    log.info("api.startup.reranker_warm")

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
