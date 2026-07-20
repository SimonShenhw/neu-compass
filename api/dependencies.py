"""FastAPI dependency injection: SQLite conn, repositories, and retrievers.

FastAPI 依赖注入：SQLite 连接、各 Repository 与检索器。

Per-request connection pattern (cheap on SQLite — no pool overhead). Heavy
state (embedder, FAISS index, BM25 corpus) lives on `app.state` populated
during lifespan; we read it via `Request.app.state` so tests can override
by simply assigning to the field.

每请求一个连接的模式（在 SQLite 上代价很低 —— 无需连接池开销）。重量级
状态（嵌入器、FAISS 索引、BM25 语料）存在 `app.state` 上，由 lifespan
填充；我们通过 `Request.app.state` 读取它，这样测试只需给字段赋值就能
覆盖。

Why per-request conn (not a single shared one): SQLite default
`check_same_thread=True`. FastAPI dispatches sync routes via threadpool;
sharing a connection across threads would require `check_same_thread=False`
+ external locking. Per-request connect is ~1ms and side-steps the issue.

为什么每请求单开一个连接（而不是共用一个）：SQLite 默认
`check_same_thread=True`。FastAPI 通过线程池派发同步路由；跨线程共享
连接需要 `check_same_thread=False` + 外部加锁。每请求单开连接耗时约
1ms，绕开了这个问题。
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
# 中文：LLM 流式输出函数。测试里通过 app.dependency_overrides 覆盖，
# 这样 /chat 测试就不需要真的调用 Gemini。
def get_chat_stream_fn() -> Callable[[str], _Iter[str]]:
    return generate_text_stream


# HyDE rescue expansion (ADR-0019). None when the feature is off — routes
# skip the rescue entirely. Tests override with a fake to avoid Gemini.
# 中文（ADR-0019）：HyDE 救援扩写。功能关闭时返回 None —— 路由会完全跳过
# 救援逻辑。测试用假函数覆盖以避免调用 Gemini。
def get_hyde_rescue_fn() -> Callable[[str], str | None] | None:
    if not settings.hyde_rescue:
        return None
    from rag.hyde import rescue_expand  # noqa: PLC0415

    return rescue_expand


# === Session auth (ADR-0021) ===


def get_current_user_id(request: Request) -> str | None:
    """Resolve the caller's identity from `Authorization: Bearer <token>`.

    从 `Authorization: Bearer <token>` 解析调用者身份。

    - no Authorization header → None (anonymous — fine for public routes)
    - header present but token invalid/expired → 401 (an explicit credential
      that fails verification is an error, never silent anonymity)

    - 没有 Authorization 请求头 → None（匿名 —— 公开路由可以接受）
    - 请求头存在但令牌无效/过期 → 401（显式提供的凭证校验失败属于错误，
      绝不能悄悄降级为匿名）
    """
    from fastapi import HTTPException, status  # noqa: PLC0415

    from app.session_tokens import verify_session_token  # noqa: PLC0415

    header = request.headers.get("Authorization", "")
    if not header:
        return None
    token = header.removeprefix("Bearer ").strip()
    payload = verify_session_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token. Log in again.",
        )
    return str(payload["user_id"])


# OAuth code-exchange function. Tests override to bypass real Google.
# 中文：OAuth 授权码兑换函数。测试会覆盖它以绕开真实的 Google 调用。
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
    weights aren't present (CI, integration without GPU).
    交叉编码器 reranker。未加载时返回 None —— 调用方（如 /search）把 None
    理解为"跳过 rerank+blend，保留 hybrid 路径"，这样在没有 reranker 权重
    的降级环境（CI、无 GPU 的集成环境）里 API 依然能用。"""
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
    # ADR-0020: acronym expansion feeds the retrieval legs only; it's a
    # no-op (returns the query untouched) when the glossary file is absent.
    # 中文（ADR-0020）：缩写扩写只喂给检索两路；术语表文件缺失时它是
    # no-op（原样返回查询）。
    expander = None
    if settings.acronym_expansion:
        from rag.acronyms import expand_query  # noqa: PLC0415

        expander = expand_query
    return HybridRetriever(
        vector_retriever=vector, bm25_corpus=bm25, course_repo=course_repo,
        query_expander=expander,
        fusion_mode=settings.fusion_mode,
        fusion_weight=settings.fusion_weight,
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
