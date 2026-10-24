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
import threading
from pathlib import Path
from collections.abc import Iterator as _Iter
from typing import Annotated, Any, Callable, Iterator

from fastapi import Depends, Request

from config import settings
from db.alias_repository import AliasRepository
from db.connection import connect
from db.coop_repository import CoopRepository
from db.coop_submission_repository import CoopSubmissionRepository
from db.program_repository import ProgramRepository
from db.repository import CourseRepository
from db.user_repository import UserRepository
from api.google_oauth import exchange_code_for_token
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


def get_coop_submission_repo(conn: DbConn) -> CoopSubmissionRepository:
    from fastapi import HTTPException  # noqa: PLC0415

    tables = {row["name"] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('coop_submissions','coop_contribution_credits')",
    )}
    if len(tables) != 2:
        raise HTTPException(status_code=503, detail="Co-op moderation schema unavailable; apply the v1.3 migration")
    return CoopSubmissionRepository(conn)


def get_user_repo(conn: DbConn) -> UserRepository:
    return UserRepository(conn)


def get_program_repo(conn: DbConn) -> ProgramRepository:
    return ProgramRepository(conn)


def get_program_policy_reader():
    """No file reads until the selected-plan endpoint calls read()."""
    from rag.program_policy_evidence import ProgramPolicyReader  # noqa: PLC0415

    data_root = Path(settings.sqlite_path).expanduser().resolve().parent
    return ProgramPolicyReader(settings.program_policy_bundle_path,
        settings.program_policy_source_dir or data_root / "raw/program_policy_catalog",
        settings.program_catalog_source_dir or data_root / "raw/program_catalog")


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

    budget = get_model_budget()
    if budget is None:
        return rescue_expand

    # Only reached when the course-code guard let the query through, so a place is taken only for a real call.
    # 中文：只有通过了课号规则才会走到这里，所以只为真正的调用占名额。
    def budgeted_rescue(query: str) -> str | None:
        if not budget.acquire():
            from api.model_budget import ModelBudgetExhausted  # noqa: PLC0415

            raise ModelBudgetExhausted
        return rescue_expand(query)

    return budgeted_rescue


# Daily cap on Gemini calls (batch T, P5). None when MODEL_DAILY_CALL_LIMIT is 0. One object per process, so
# every request counts against the same file. 中文：Gemini 调用的每日上限（T 批，P5）；MODEL_DAILY_CALL_LIMIT 为 0
# 时返回 None。每个进程一个对象，所有请求都记在同一个文件上。
def get_model_budget() -> Any:
    limit = settings.model_daily_call_limit
    if not limit:
        return None
    from api.model_budget import FILENAME  # noqa: PLC0415

    return _model_budget(str(Path(settings.sqlite_path).expanduser().resolve().parent / FILENAME), limit)


_BUDGETS: dict[tuple[str, int], Any] = {}
_BUDGETS_LOCK = threading.Lock()  # Two first requests must not build two counters. 中文：别让两个首个请求建出两个计数器。


def _model_budget(path: str, limit: int) -> Any:
    from api.model_budget import ModelBudget  # noqa: PLC0415

    with _BUDGETS_LOCK:
        if (path, limit) not in _BUDGETS:
            _BUDGETS[(path, limit)] = ModelBudget(Path(path), limit)
        return _BUDGETS[(path, limit)]


# === Session auth (ADR-0021) ===


def get_current_user_id(request: Request) -> str | None:
    """Resolve the caller's identity from `Authorization: Bearer <token>`, or else from the API's session cookie.

    从 `Authorization: Bearer <token>` 解析调用者身份；没有这个头时，看 API 的会话 cookie。

    - no Authorization header and no session cookie → None (anonymous — fine for public routes)
    - header present but token invalid/expired → 401 (an explicit credential
      that fails verification is an error, never silent anonymity); the cookie is not looked at
    - no header, session cookie (R2a) valid → its user, and `request.state.session_from_cookie` is set; invalid or
      expired → None: the browser sends the cookie by itself, so a stale one must not turn public pages into 401s.
      /auth/me and /auth/delete-account answer 401 and expire it.
    - every call marks the request (R2a), so its response, the guest's too, is sent `Cache-Control: private,
      no-store` (api/private_cache.py).

    - 没有 Authorization 请求头、也没有会话 cookie → None（匿名 —— 公开路由可以接受）
    - 请求头存在但令牌无效/过期 → 401（显式提供的凭证校验失败属于错误，
      绝不能悄悄降级为匿名）；这时不看 cookie
    - 没有请求头、有会话 cookie（R2a）：有效就是它的用户，并记下 `request.state.session_from_cookie`；无效或过期
      就是 None：cookie 是浏览器自己带的，坏 cookie 不能让公开页面都变成 401。/auth/me 和 /auth/delete-account
      会回 401 并让它过期。
    - 每次调用都给请求做个记号（R2a），它的响应（游客的也算）就带上 `Cache-Control: private, no-store`
      （api/private_cache.py）。
    """
    from fastapi import HTTPException, status  # noqa: PLC0415

    from api.private_cache import IDENTITY_READ  # noqa: PLC0415
    from api.session_cookie import COOKIE_NAME  # noqa: PLC0415
    from api.session_tokens import verify_session_token  # noqa: PLC0415

    # First, before any 401: the answer depends on who is asking, whatever it turns out to be.
    # 中文：放在最前面、任何 401 之前：不管结果是什么，回答都取决于是谁在问。
    setattr(request.state, IDENTITY_READ, True)
    header = request.headers.get("Authorization", "")
    if not header:
        cookie = request.cookies.get(COOKIE_NAME, "")
        if not cookie:
            return None
        payload = verify_session_token(cookie)
        if payload is None:
            return None
        request.state.session_from_cookie = True
        return str(payload["user_id"])
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
    "get_model_budget",
    "get_oauth_exchange_fn",
    "get_program_repo",
    "get_program_policy_reader",
    "get_reranker",
    "get_retriever",
    "get_user_repo",
]
