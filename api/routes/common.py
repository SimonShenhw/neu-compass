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
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import structlog

from config import settings
from api.error_fields import error_frames, safe_error_fields
from api.model_budget import ModelBudgetExhausted
from api.query_fields import query_fields
from llm.gemini_client import GeminiError, error_log_fields
from rag.filters import filter_course_ids
from rag.reranker import CrossEncoderReranker, rerank_blend_with_rejection
from rag.retriever import SearchHit
from schemas.course import Course

log = structlog.get_logger("neu_compass.routes.common")


# PLAN v2.2 §3.4 + ADR-0015. Tunable; ADR-supplement if changed.
# 中文：出自 PLAN v2.2 §3.4 + ADR-0015；可调参数，改动需补充 ADR。
RERANK_POOL_SIZE = settings.rerank_pool_size
"""Candidates HybridRetriever returns before rerank+blend narrows to req.k.
Env-overridable (RERANK_POOL_SIZE, default 20) so the NAS can A/B pool sizes
without a redeploy — the cross-encoder pass over this pool is the /search
p50 bottleneck there.

HybridRetriever 返回的候选数量，之后由 rerank+blend 收窄到 req.k。可通过
环境变量覆盖（RERANK_POOL_SIZE，默认 20），这样 NAS 端无需重新部署即可
A/B 测试候选池大小 —— 对该候选池做交叉编码器前向计算正是 /search 在那台
机器上的 p50 延迟瓶颈。"""

RERANKER_REJECT_THRESHOLD = 0.05
"""Raw bge-reranker sigmoid below which the query has no good match.
Calibrated by ADR-0016 ROC sweep (was 0.4 in PLAN v2.2 §3.4 spec);
empirical data on test_set v0.2 showed 0.4 false-rejected ~26% of real
queries. T=0.05 catches all 4 adversarial AND keeps real R@5 baseline.

低于此 bge-reranker 原始 sigmoid 值即判定查询无良好匹配。由 ADR-0016 的
ROC 扫描校准得出（PLAN v2.2 §3.4 规格原为 0.4）；test_set v0.2 的实测数据
显示 0.4 会误拒约 26% 的真实查询。T=0.05 既能拦下全部 4 条对抗查询，又能
保住真实查询的 R@5 基线。"""

BLEND_ALPHA = 0.4
"""Z-score blend weight on RRF leg. 0.0 = pure reranker, 1.0 = pure RRF.
Locked by ADR-0015 sweep on test_set v0.2 (n=42); re-sweep on v0.3 mandatory.

RRF 一路在 Z-score 融合中的权重。0.0 = 纯 reranker，1.0 = 纯 RRF。由
ADR-0015 在 test_set v0.2（n=42）上的扫描锁定；换到 v0.3 后必须重新扫描。"""


@dataclass(frozen=True)
class RetrievalDecision:
    """Final outcome, plus initial rerank metadata for route-owned rejection logs.

    A successful rescue clears rejected/reason, not meta's original gate verdict.
    中文：最终结果与首次重排元数据；救回后清除拒答状态／原因，原门控元数据仍供路由使用。
    """

    hits: list[SearchHit]
    rejected: bool
    rejection_reason: str | None
    rescued: bool
    meta: dict[str, object]


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


def filter_courses(
    conn: sqlite3.Connection, courses: list[Course], filters: dict[str, object],
) -> list[Course]:
    """Apply the retrieval SQL contract to a shortcut, preserving its input order.

    No explicit filters preserves existing direct-lookup behavior. With filters,
    only indexed courses qualify, just as on the hybrid path. Truncate afterwards.
    中文：无显式筛选时保留直接查找语义；有筛选时与混合路径共用 SQL，之后再截断。
    """
    if not filters or not courses:
        return courses
    allowed = set(filter_course_ids(
        conn, filters, candidate_course_ids=[course.course_id for course in courses],
    ))
    return [course for course in courses if course.course_id in allowed]


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


def rerank_with_gate_and_rescue(
    *,
    query: str,
    hits: list[SearchHit],
    conn: sqlite3.Connection,
    hybrid: Any,
    reranker: CrossEncoderReranker,
    diagnostics: dict[str, float] | None,
    hard_filters: dict[str, object] | None,
    rescue_fn: Callable[[str], str | None] | None,
    pool_size: int,
    blend_alpha: float,
    reject_threshold: float,
    top_k: int,
    gate_builder: Callable[..., Callable[[list[float]], tuple[bool, str]]],
) -> RetrievalDecision:
    """Shared hybrid decision; shortcuts, degraded paths and response assembly stay in routes.

    diagnostics is the initial request-local evidence, never read from hybrid here:
    an optional retry overwrites hybrid.last_diagnostics. Each pass scores once,
    using the original query. Rescue scope and policy are unchanged (ADR-0018/19).
    中文：共享混合检索决策；精确／降级入口与响应组装留在路由。显式接收首次诊断，
    不在此读取会被救援重试覆盖的实例状态；每轮只按原始查询重排一次，门控／救援策略不变。
    """
    texts = fetch_texts(conn, [hit.course.course_id for hit in hits])
    gate_fn = None
    if settings.rejection_mode == "calibrated":
        diag = diagnostics or {}
        gate_fn = gate_builder(query=query, bm25_top=diag.get("bm25_top", 0.0), vec_top=diag.get("vec_top", 0.0))
    blended_hits, meta = rerank_blend_with_rejection(
        query, hits, reranker, fetch_text=texts.get,
        blend_alpha=blend_alpha, reject_threshold=reject_threshold,
        top_k=top_k, gate_fn=gate_fn,
    )
    if not meta["rejected"]:
        return RetrievalDecision(blended_hits, False, None, False, meta)
    rescued = None
    if rescue_fn is not None and (
        gate_fn is None or getattr(gate_fn, "last_p", 1.0) >= settings.rescue_min_probability
    ):
        rescued = attempt_hyde_rescue(
            query=query, conn=conn, hybrid=hybrid, reranker=reranker,
            rescue_fn=rescue_fn, hard_filters=hard_filters,
            pool_size=pool_size, blend_alpha=blend_alpha, top_k=top_k,
        )
    if rescued is not None:
        return RetrievalDecision(rescued, False, None, True, meta)
    return RetrievalDecision([], True, str(meta["reason"]), False, meta)


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
        log.info("rescue.code_pattern_guard", **query_fields(query))
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
            log.info("rescue.declined", **query_fields(query))
            return None

        combined = f"{query}\n\n{expansion}"
        hits = hybrid.search(combined, hard_filters=hard_filters, k=pool_size)
        if not hits:
            log.info("rescue.empty_retrieval", **query_fields(query))
            return None

        texts = fetch_texts(conn, [h.course.course_id for h in hits])
        blended, _ = rerank_blend_with_rejection(
            query, hits, reranker,
            fetch_text=texts.get,
            blend_alpha=blend_alpha,
            reject_threshold=0.0,  # LLM verdict already vouched answerability / LLM 判决已担保可答性
            top_k=top_k,
        )
    except ModelBudgetExhausted:
        # Today's model places are used up (batch T): the original rejection stands, and this is not a verdict.
        # 中文：今天的模型名额用完了（T 批）：保留原来的拒答；这不是模型的判断。
        log.info("rescue.skipped", reason="model_daily_limit")
        return None
    except Exception as e:  # noqa: BLE001 — rescue must never 500 a request / 救援绝不能让请求 500
        # Types, kind and status only: a GeminiError message carries upstream text. Other errors
        # (database, reranker) also record where they were raised.
        # 中文：只记类型、kind 和状态码：GeminiError 的消息里带着上游文字。其他错误（数据库、
        # reranker）另外记录发生的位置。
        where = {} if isinstance(e, GeminiError) else {"frames": error_frames(e)}
        log.warning("rescue.failed", **error_log_fields(e), **where)
        return None
    if not blended:
        return None
    log.info("rescue.accepted", **query_fields(query), count=len(blended))
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
) -> int | None:
    """Return the committed log ID or None; telemetry must NEVER break a request.

    Swallows every failure (including 'no such table: query_log' on a not-yet-migrated
    DB) with a structlog warning. One INSERT + commit on the request's
    own connection; negligible next to retrieval cost.
    遥测写入，绝不能打断请求 —— 任何失败（包括未迁移数据库上的
    'no such table: query_log'）都会被吞掉，只留一条 structlog warning。
    在请求自己的连接上做一次 INSERT + commit；相对检索开销可忽略不计。"""
    try:
        from db.query_log_repository import QueryLogRepository  # noqa: PLC0415

        log_id = QueryLogRepository(conn).add(
            route=route, query=query, matched_via=matched_via, k=k,
            latency_ms=latency_ms, result_course_ids=result_course_ids,
            rejection_reason=rejection_reason, user_id=user_id,
        )
        conn.commit()
    except Exception as e:  # noqa: BLE001 — telemetry is best-effort / 遥测是尽力而为
        log.warning("query_log.write_failed", **safe_error_fields(e))
        return None
    # The row id joins this request's log lines to query_log without the hash key; the text stays in the table.
    # 中文：用行号把这个请求的日志行和 query_log 对上，不需要哈希密钥；原文仍只在表里。
    log.info("query_log.written", query_log_id=log_id)
    return log_id


__all__ = ["BLEND_ALPHA", "RERANK_POOL_SIZE", "RERANKER_REJECT_THRESHOLD", "RetrievalDecision",
           "attempt_hyde_rescue", "build_hard_filters", "fetch_texts", "filter_courses", "log_query",
           "rerank_with_gate_and_rescue"]
