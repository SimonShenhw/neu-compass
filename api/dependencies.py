"""FastAPI dependency injection: SQLite conn, repositories, and retrievers.

Per-request connection pattern (cheap on SQLite — no pool overhead). Heavy
state (embedder, FAISS index, BM25 corpus) lives on `app.state` populated
during lifespan; we read it via `Request.app.state` so tests can override
by simply assigning to the field.

Why per-request conn (not a single shared one): SQLite default
`check_same_thread=True`. FastAPI dispatches sync routes via threadpool;
sharing a connection across threads would require `check_same_thread=False`
+ external locking. Per-request connect is ~1ms and side-steps the issue.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator as _Iter
from typing import Annotated, Any, Callable, Iterator

from fastapi import Depends, Request

from config import settings
from db.alias_repository import AliasRepository
from db.connection import connect
from db.coop_repository import CoopRepository
from db.program_repository import ProgramRepository
from db.repository import CourseRepository
from db.user_repository import UserRepository
from app.auth import exchange_code_for_token
from llm.gemini_client import generate_text_stream
from rag.embedder import EmbedderProtocol
from rag.hybrid import BM25Corpus, HybridRetriever
from rag.index import FaissIndex
from rag.reranker import CrossEncoderReranker
from rag.retriever import Retriever


# === SQLite connection (per request) ===


def get_db_conn() -> Iterator[sqlite3.Connection]:
    conn = connect(settings.sqlite_path)
    try:
        yield conn
    finally:
        conn.close()


DbConn = Annotated[sqlite3.Connection, Depends(get_db_conn)]


# === Repositories (per request, cheap wrappers around conn) ===


def get_course_repo(conn: DbConn) -> CourseRepository:
    return CourseRepository(conn)


def get_alias_repo(conn: DbConn) -> AliasRepository:
    return AliasRepository(conn)


def get_coop_repo(conn: DbConn) -> CoopRepository:
    return CoopRepository(conn)


def get_user_repo(conn: DbConn) -> UserRepository:
    return UserRepository(conn)


def get_program_repo(conn: DbConn) -> ProgramRepository:
    return ProgramRepository(conn)


# LLM streaming function. Override in tests via app.dependency_overrides
# so /chat tests don't need a real Gemini call.
def get_chat_stream_fn() -> Callable[[str], _Iter[str]]:
    return generate_text_stream


# HyDE rescue expansion (ADR-0019). None when the feature is off — routes
# skip the rescue entirely. Tests override with a fake to avoid Gemini.
def get_hyde_rescue_fn() -> Callable[[str], str | None] | None:
    if not settings.hyde_rescue:
        return None
    from rag.hyde import rescue_expand  # noqa: PLC0415

    return rescue_expand


# OAuth code-exchange function. Tests override to bypass real Google.
def get_oauth_exchange_fn() -> Callable[..., dict[str, Any]]:
    return exchange_code_for_token


# === Process-wide state (populated by lifespan; tests assign directly) ===


def get_embedder(request: Request) -> EmbedderProtocol:
    embedder = getattr(request.app.state, "embedder", None)
    if embedder is None:
        raise RuntimeError("Embedder not initialized — check lifespan ran")
    return embedder


def get_faiss_index(request: Request) -> FaissIndex:
    index = getattr(request.app.state, "faiss_index", None)
    if index is None:
        raise RuntimeError("FAISS index not initialized — check lifespan ran")
    return index


def get_bm25_corpus(request: Request) -> BM25Corpus:
    bm25 = getattr(request.app.state, "bm25_corpus", None)
    if bm25 is None:
        raise RuntimeError("BM25 corpus not initialized — check lifespan ran")
    return bm25


def get_reranker(request: Request) -> CrossEncoderReranker | None:
    """Cross-encoder reranker. Returns None when not loaded — callers
    (e.g. /search) treat None as "skip rerank+blend, keep hybrid path"
    so the API still works in degraded environments where the reranker
    weights aren't present (CI, integration without GPU)."""
    return getattr(request.app.state, "reranker", None)


# === Composed retrievers (per request — cheap glue) ===


def get_retriever(
    embedder: Annotated[EmbedderProtocol, Depends(get_embedder)],
    index: Annotated[FaissIndex, Depends(get_faiss_index)],
    course_repo: Annotated[CourseRepository, Depends(get_course_repo)],
    conn: DbConn,
) -> Retriever:
    return Retriever(
        embedder=embedder, index=index, course_repo=course_repo, sqlite_conn=conn
    )


def get_hybrid_retriever(
    vector: Annotated[Retriever, Depends(get_retriever)],
    bm25: Annotated[BM25Corpus, Depends(get_bm25_corpus)],
    course_repo: Annotated[CourseRepository, Depends(get_course_repo)],
) -> HybridRetriever:
    return HybridRetriever(
        vector_retriever=vector, bm25_corpus=bm25, course_repo=course_repo
    )


__all__ = [
    "DbConn",
    "get_alias_repo",
    "get_bm25_corpus",
    "get_chat_stream_fn",
    "get_coop_repo",
    "get_course_repo",
    "get_db_conn",
    "get_embedder",
    "get_faiss_index",
    "get_hybrid_retriever",
    "get_hyde_rescue_fn",
    "get_oauth_exchange_fn",
    "get_program_repo",
    "get_reranker",
    "get_retriever",
    "get_user_repo",
]
