"""Shared helpers for route modules — single point of truth for plumbing
that /search and /chat both need.

各路由模块共用的辅助函数 —— /search 与 /chat 都需要的管道逻辑的唯一
权威来源。

Why this exists: the two routes previously each carried their own copy of
(a) a per-course `_fetch_text` closure (≤20 single-row SELECTs per request)
and (b) the request→hard_filters mapping. Copies drift; the batched
fetch is also simply faster (one `IN (...)` round-trip).

为什么要抽出来：这两条路由以前各自维护一份 (a) 逐课程的 `_fetch_text`
闭包（每次请求最多 20 条单行 SELECT）和 (b) 请求→hard_filters 的映射
逻辑。副本容易走样；批量查询本身也更快（一次 `IN (...)` 往返即可）。

`attempt_hyde_rescue` (ADR-0019) also lives here because both routes run
the same rejection block and must share the same rescue semantics.

`attempt_hyde_rescue`（ADR-0019）也放在这里，因为两条路由跑的是同一段
拒答逻辑，救援语义必须保持一致。
"""

from __future__ import annotations

import sqlite3
from typing import Any, Callable, Protocol

import structlog

from rag.retriever import SearchHit

log = structlog.get_logger("neu_compass.routes.common")


class _FilterableRequest(Protocol):
    """Structural type covering SearchRequest and ChatRequest — both carry
    the same four optional hard-filter fields.
    结构化类型，覆盖 SearchRequest 与 ChatRequest —— 两者携带同样的
    四个可选硬过滤字段。"""

    term: str | None
    credits: int | None
    delivery_mode: str | None
    professor: str | None


def build_hard_filters(req: _FilterableRequest) -> dict[str, object]:
    """Pull the optional filter fields off the request into the dict shape
    Retriever._sqlite_filter expects. Skips None — `hard_filters={}` would
    still go through the WHERE-status branch with no narrowing.
    把请求上的可选过滤字段整理成 Retriever._sqlite_filter 期望的 dict
    形状。跳过 None —— 即便 `hard_filters={}`，仍会走 WHERE-status 分支，
    只是不做进一步收窄。"""
    filters: dict[str, object] = {}
    if req.term is not None:
        filters["term"] = req.term
    if req.credits is not None:
        filters["credits"] = req.credits
    if req.delivery_mode is not None:
        filters["delivery_mode"] = req.delivery_mode
    if req.professor is not None:
        filters["professor"] = req.professor
    return filters


def fetch_texts(
    conn: sqlite3.Connection,
    course_ids: list[str],
) -> dict[str, str | None]:
    """Batch-fetch raw_text for the reranker in ONE query.

    为 reranker 用一次查询批量取回 raw_text。

    Returns {course_id: raw_text} for rows that exist; missing IDs are
    omitted, so `result.get(cid)` keeps the same None-fallback semantics
    the old per-row closure had (reranker falls back to primary_name).

    返回 {course_id: raw_text}，只包含存在的行；缺失的 id 直接不出现，
    这样 `result.get(cid)` 仍保留旧版逐行闭包的 None 兜底语义（reranker
    会退回用 primary_name）。
    """
    if not course_ids:
        return {}
    placeholders = ",".join("?" * len(course_ids))
    rows = conn.execute(
        f"SELECT course_id, raw_text FROM courses WHERE course_id IN ({placeholders})",
        list(course_ids),
    ).fetchall()
    return {r["course_id"]: r["raw_text"] for r in rows}


def attempt_hyde_rescue(
    *,
    query: str,
    conn: sqlite3.Connection,
    hybrid: Any,
    reranker: Any,
    rescue_fn: Callable[[str], str | None],
    hard_filters: dict[str, object] | None,
    pool_size: int,
    blend_alpha: float,
    top_k: int,
) -> list[SearchHit] | None:
    """ADR-0019 rescue pass for a gate-rejected query.

    ADR-0019：对被拒答门拦下的查询做一次救援。

    One LLM call second-opinions the query:
      - REJECT verdict (gibberish / homework / admin / fictional) → None;
        the caller keeps the original rejection. Garbage gets no retry.
      - Otherwise the hypothetical course description is appended to the
        query and retrieval re-runs — the embedder sees the expansion
        (HyDE distribution alignment + acronyms spelled out), while the
        reranker re-scores against the ORIGINAL query so the returned
        ordering still reflects what the user actually asked.

    调用一次 LLM 给查询做复核：
      - 判为 REJECT（乱码/作业/行政事务/虚构内容）→ 返回 None；调用方
        保留原本的拒答结果。垃圾查询不会重试。
      - 否则把假设性的课程描述拼接到查询后重新检索 —— 嵌入器能看到这段
        扩写内容（HyDE 分布对齐 + 缩写被写全），而 reranker 仍按原始
        查询重新打分，因此返回的排序依旧反映用户实际问的是什么。

    Rejection is disabled on the retry on purpose: the LLM verdict replaced
    the evidence gate as the answerability judgment. Any failure (LLM error,
    empty retrieval) degrades to None — never breaks the original response.

    重试时故意关闭拒答：LLM 的判决已经取代证据门成为"能不能回答"的判断
    依据。任何失败（LLM 出错、检索为空）都会降级为 None —— 绝不会打断
    原本的响应。
    """
    from rag.rejection import query_has_code_pattern  # noqa: PLC0415
    from rag.reranker import rerank_blend_with_rejection  # noqa: PLC0415

    # Hard guard, no LLM consulted: a course-code-shaped query that reached
    # the gate already missed the alias tier — the course does not exist.
    # Live probe showed Gemini judges "AAI 9999" a plausible course query
    # and would happily write it a hypothetical description.
    # 中文：硬性保护，不咨询 LLM：形如课程代码的查询能走到这个门，说明它
    # 已经没能命中别名层 —— 该课程根本不存在。实测发现 Gemini 会把
    # "AAI 9999" 判断成一个看似合理的课程查询，并欣然为它编一段假设性描述。
    if query_has_code_pattern(query):
        log.info("rescue.code_pattern_guard", query=query[:80])
        return None

    # ONE try over the whole rescue (LLM + retry retrieval + rerank): the
    # caller already has a valid rejected response in hand — a transient
    # inference/DB error during this OPTIONAL second chance must degrade to
    # None, never 500 the request. (Previously only the LLM call was
    # guarded, contradicting this function's documented contract.)
    # 中文：整个救援过程（LLM + 重试检索 + 重排）只包一层 try：调用方手上
    # 已经有一个合法的拒答响应 —— 这次可选的"第二次机会"里若发生瞬时性
    # 推理/DB 错误，必须降级为 None，绝不能让请求 500。（此前只对 LLM 调用
    # 加了保护，与本函数文档承诺的契约相矛盾。）
    try:
        expansion = rescue_fn(query)
        if expansion is None:
            log.info("rescue.declined", query=query[:80])
            return None

        combined = f"{query}\n\n{expansion}"
        hits = hybrid.search(combined, hard_filters=hard_filters, k=pool_size)
        if not hits:
            log.info("rescue.empty_retrieval", query=query[:80])
            return None

        texts = fetch_texts(conn, [h.course.course_id for h in hits])
        blended, _ = rerank_blend_with_rejection(
            query, hits, reranker,
            fetch_text=texts.get,
            blend_alpha=blend_alpha,
            reject_threshold=0.0,  # LLM verdict already vouched answerability / LLM 判决已担保可答性
            top_k=top_k,
        )
    except Exception as e:  # noqa: BLE001 — rescue must never 500 a request / 救援绝不能让请求 500
        log.warning("rescue.failed", error=str(e)[:200])
        return None
    if not blended:
        return None
    log.info("rescue.accepted", query=query[:80], count=len(blended))
    return blended


def log_query(
    conn: sqlite3.Connection,
    *,
    route: str,
    query: str,
    matched_via: str | None,
    k: int | None,
    latency_ms: float | None,
    result_course_ids: list[str] | None = None,
    rejection_reason: str | None = None,
    user_id: str | None = None,
) -> None:
    """Telemetry write that must NEVER break a request — swallows every
    failure (including 'no such table: query_log' on a not-yet-migrated
    DB) with a structlog warning. One INSERT + commit on the request's
    own connection; negligible next to retrieval cost.
    遥测写入，绝不能打断请求 —— 任何失败（包括未迁移数据库上的
    'no such table: query_log'）都会被吞掉，只留一条 structlog warning。
    在请求自己的连接上做一次 INSERT + commit；相对检索开销可忽略不计。"""
    try:
        from db.query_log_repository import QueryLogRepository  # noqa: PLC0415

        QueryLogRepository(conn).add(
            route=route, query=query, matched_via=matched_via, k=k,
            latency_ms=latency_ms, result_course_ids=result_course_ids,
            rejection_reason=rejection_reason, user_id=user_id,
        )
        conn.commit()
    except Exception as e:  # noqa: BLE001 — telemetry is best-effort / 遥测是尽力而为
        log.warning("query_log.write_failed", error=str(e)[:120])


__all__ = ["attempt_hyde_rescue", "build_hard_filters", "fetch_texts", "log_query"]
