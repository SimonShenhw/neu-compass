"""POST /search — alias-first → HybridRetriever → rerank+blend+reject.

POST /search —— 先走别名匹配 → HybridRetriever → 重排+融合+拒答。

Pipeline (PLAN v2.2 §1.2 query path + §3.4 rejection + §3.5 blending):
  1. query_normalizer: regex → AliasRepository.resolve via v_course_lookup
     (which excludes review_status='pending' aliases — ADR §3.2 boundary).
     If alias hit, return immediately (no LLM/vector cost).
  2. HybridRetriever: BM25 + vector via RRF. Hard filters apply at the
     SQLite layer (Retriever._sqlite_filter) so pending courses can't leak
     (ADR-0013).
  3. Cross-encoder rerank + Z-score blend (ADR-0015) when reranker is loaded:
     - Single bge-reranker-v2-m3 pass over the candidate pool.
     - Reject if `max(raw_sigmoid) < RERANKER_REJECT_THRESHOLD`.
     - Otherwise α-blend RRF + reranker, sort, truncate to req.k.

流水线（PLAN v2.2 §1.2 查询路径 + §3.4 拒答 + §3.5 融合）：
  1. query_normalizer：正则 → 经 v_course_lookup 调用 AliasRepository.resolve
     （该视图排除 review_status='pending' 的别名 —— ADR §3.2 边界）。
     命中别名则立即返回（不产生 LLM/向量开销）。
  2. HybridRetriever：BM25 + 向量，经 RRF 融合。硬过滤在 SQLite 层生效
     （Retriever._sqlite_filter），待审核课程不会泄漏（ADR-0013）。
  3. 加载了 reranker 时，交叉编码器重排 + Z-score 融合（ADR-0015）：
     - 对候选池做一次 bge-reranker-v2-m3 前向计算。
     - 若 `max(raw_sigmoid) < RERANKER_REJECT_THRESHOLD` 则拒答。
     - 否则用 α 混合 RRF 与 reranker 分数，排序后截断到 req.k。

The alias path is keyed by exact text after light regex extraction. The
hybrid path handles natural-language and 中英 mix. Together they cover
"5800" / "Algo" / "应用 AI" / "course on backprop" without per-query
heuristics in the route.

别名路径以轻量正则抽取后的精确文本为键；混合路径处理自然语言与中英混合
输入。两者合力覆盖 "5800" / "Algo" / "应用 AI" / "course on backprop"
这类查询，路由里无需逐查询写特判逻辑。

If `app.state.reranker` is None (e.g. degraded environment without the
~600MB weights), the route falls back to bare hybrid output. Tests that
exercise rejection inject a deterministic stub via conftest.

若 `app.state.reranker` 为 None（例如降级环境缺少约 600MB 的权重文件），
路由退回纯 hybrid 输出。测试用例通过 conftest 注入确定性 stub 来演练拒答
逻辑。
"""

from __future__ import annotations

import time
from typing import Annotated, Callable

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status

from api.dependencies import (
    DbConn,
    get_alias_repo,
    get_course_repo,
    get_hybrid_retriever,
    get_hyde_rescue_fn,
    get_reranker,
)
from api.models import SearchHitOut, SearchRequest, SearchResponse
from api.routes.common import (
    attempt_hyde_rescue,
    build_hard_filters,
    fetch_texts,
    log_query,
)
from config import settings
from db.alias_repository import AliasRepository
from db.repository import CourseRepository
from llm.query_filter_extractor import extract_filters_adaptive
from rag.hybrid import HybridRetriever
from rag.query_normalizer import normalize_query_to_course_ids
from rag.rejection import build_gate_fn
from rag.reranker import CrossEncoderReranker, rerank_blend_with_rejection
from schemas.course import DeliveryMode

router = APIRouter(prefix="/search", tags=["search"])

log = structlog.get_logger("neu_compass.search")

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


def _elapsed_ms(started: float) -> float:
    """Elapsed time since `started` (perf_counter) in milliseconds, rounded.
    自 `started`（perf_counter）以来的耗时（毫秒），已四舍五入。"""
    return round((time.perf_counter() - started) * 1000, 2)


@router.post(
    "",
    response_model=SearchResponse,
    summary="Course search (alias → hybrid → rerank+blend+reject)",
    description=(
        "Production search path. Three-stage pipeline:\n\n"
        "1. **Alias resolution** — `query_normalizer` strips/lowercases the "
        "query and looks it up in `v_course_lookup` (which excludes "
        "`review_status='pending'` aliases). On hit, returns immediately "
        "with `matched_via='alias'`, score=1.0. Covers `'CS 5800'` / "
        "`'cs5800'` / `'Algo'` / `'应用 AI'`.\n"
        "2. **Hybrid retrieval** — BM25 (110 stopwords filtered) + bge-m3 "
        "vector via Reciprocal Rank Fusion (RRF, k=60). Hard filters apply "
        "at SQLite layer; only `status='indexed'` rows surface (ADR-0013).\n"
        "3. **Rerank + Z-score blend + reject** (PLAN v2.2 §3.4 + §3.5) — "
        "single bge-reranker-v2-m3 pass over the candidate pool. "
        "If `max(raw_sigmoid) < 0.05` (ADR-0016): "
        "`matched_via='rejected'`, empty results, populated "
        "`rejection_reason`. Otherwise α=0.4 Z-score blend "
        "(ADR-0015) reorders the top-5 and returns `matched_via='hybrid'`.\n\n"
        "**Latency budget**: alias path ~3ms, hybrid+rerank ~50ms p50 "
        "post-warmup."
    ),
    responses={
        200: {
            "description": (
                "Search resolved. `matched_via` ∈ {alias, hybrid, empty, "
                "rejected}. `results=[]` when matched_via is empty or "
                "rejected; `rejection_reason` is non-null only when rejected."
            ),
        },
        422: {
            "description": (
                "Invalid request (empty query, k out of range, unknown "
                "delivery_mode, extra unknown fields)."
            ),
        },
    },
)
def search(
    req: SearchRequest,
    alias_repo: Annotated[AliasRepository, Depends(get_alias_repo)],
    course_repo: Annotated[CourseRepository, Depends(get_course_repo)],
    hybrid: Annotated[HybridRetriever, Depends(get_hybrid_retriever)],
    reranker: Annotated[CrossEncoderReranker | None, Depends(get_reranker)],
    rescue_fn: Annotated[
        Callable[[str], str | None] | None, Depends(get_hyde_rescue_fn)
    ],
    conn: DbConn,
    x_eval_run: Annotated[str | None, Header()] = None,
) -> SearchResponse:
    # Sync `def` on purpose: FastAPI runs it in the threadpool. The embedder +
    # reranker forward passes here take 100ms (RTX 5090) to seconds (NAS Iris
    # Xe) — as `async def` they ran ON the event loop, starving every other
    # request including /health and /ready (whose failures can trigger Docker
    # healthcheck restarts). Model singletons hold their own locks.
    # 中文：此处故意用同步 def —— FastAPI 会把它丢进线程池执行。这里的嵌入器 +
    # reranker 前向计算耗时从 100ms（RTX 5090）到数秒（NAS Iris Xe）不等 ——
    # 若写成 `async def` 就会占住事件循环，拖慢包括 /health、/ready 在内的所有
    # 其他请求（它们一旦失败可能触发 Docker healthcheck 重启）。模型单例自带锁。
    started = time.perf_counter()

    # Eval-harness traffic (scripts/eval_via_api.py) self-identifies via
    # X-Eval-Run so query_log mining can separate it from organic users:
    # user_id IS NULL = organic, 'eval:<label>' = our own measurement runs.
    # 中文：评测脚手架（scripts/eval_via_api.py）的流量通过 X-Eval-Run 自报家门，
    # 这样挖掘 query_log 时能把它和真实用户区分开：user_id IS NULL = 真实用户，
    # 'eval:<label>' = 我们自己的测量跑。
    telemetry_user = f"eval:{x_eval_run}" if x_eval_run else None

    # Validate enum-typed filter early (FastAPI Pydantic accepts the str via
    # SearchRequest, but DeliveryMode would 500 if mistyped at the retriever).
    # 中文：提前校验枚举类型的过滤字段（FastAPI/Pydantic 在 SearchRequest 层
    # 只接受字符串；若拼错值，到检索器里用 DeliveryMode 转换就会 500）。
    if req.delivery_mode is not None:
        try:
            DeliveryMode(req.delivery_mode)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid delivery_mode: {req.delivery_mode!r}",
            ) from e

    # 1) Alias path — cheap. If the user typed a code or known slang, resolve
    #    directly and skip the embedder/BM25 entirely. Two guards:
    #    - Explicit request filters (term/credits/mode/professor) bypass the
    #      alias shortcut entirely: the alias tier can't apply them, and
    #      returning an unfiltered hit would silently contradict the request.
    #      The hybrid path enforces filters at the SQLite layer.
    #    - All-dangling alias resolution falls THROUGH to hybrid instead of
    #      returning matched_via="alias" with empty results (/chat already
    #      behaved this way; the routes had diverged).
    # 中文：1）别名路径 —— 代价很低。用户输入课程代码或已知俗称时，直接解析
    #    命中，完全跳过嵌入器/BM25。两条保护：
    #    - 请求带显式过滤条件（term/credits/mode/professor）时，完全绕开别名
    #      捷径：别名层无法施加这些过滤，若返回未过滤的命中会悄悄违背请求
    #      本意。过滤条件由混合路径在 SQLite 层强制执行。
    #    - 若别名全部指向已消失的课程，直接落入（fall through）混合路径，
    #      而不是返回 matched_via="alias" 但结果为空（/chat 那边本就是这样
    #      处理的；两条路由此前已经出现分叉）。
    hard_filters = build_hard_filters(req)
    alias_ids = (
        []
        if hard_filters
        else normalize_query_to_course_ids(req.query, alias_repo=alias_repo)
    )
    if alias_ids:
        results: list[SearchHitOut] = []
        for cid in alias_ids[: req.k]:
            try:
                course = course_repo.get(cid)
            except LookupError:
                # Alias points at a course_id that's vanished — log and skip
                # 中文：别名指向的 course_id 已不存在 —— 记录日志并跳过
                log.warning("search.alias_dangling", course_id=cid)
                continue
            results.append(
                SearchHitOut(
                    course_id=course.course_id,
                    primary_code=course.primary_code,
                    primary_name=course.primary_name,
                    score=1.0,
                    matched_via="alias",
                )
            )
        if results:
            elapsed_ms = _elapsed_ms(started)
            log.info(
                "search.alias_hit",
                query=req.query,
                count=len(results),
                duration_ms=elapsed_ms,
            )
            log_query(
                conn, route="search", query=req.query, matched_via="alias",
                k=req.k, latency_ms=elapsed_ms,
                result_course_ids=[r.course_id for r in results],
                user_id=telemetry_user,
            )
            return SearchResponse(
                query=req.query,
                k=req.k,
                matched_via="alias",
                results=results,
                latency_ms=elapsed_ms,
            )

    # 2) Hybrid path — embedder + BM25 + RRF over a wider candidate pool
    #    so rerank has room to reorder.
    # 中文：2）混合路径 —— 在更大的候选池上跑嵌入器 + BM25 + RRF，
    #    给 rerank 留出重新排序的空间。

    # Layer 2 (PLAN v3.0+): if the query mentions a program / major prefix,
    # narrow the candidate pool at SQLite WHERE so vector + BM25 don't pull
    # in cross-discipline noise. Cheap regex first; LLM fallback is wired
    # through llm_fn (passing None here = regex-only — adding the LLM hop
    # is a follow-up once we measure regex hit rate from real query logs).
    # 中文：Layer 2（PLAN v3.0+）：若查询中提到了培养方案/专业前缀，就在 SQLite
    # WHERE 里收窄候选池，避免向量 + BM25 混入跨学科噪声。优先走廉价正则；
    # LLM 兜底已经接入 llm_fn（这里传 None = 仅用正则 —— 等实测正则命中率后
    # 再决定是否加上 LLM 这一跳，属于后续工作）。
    extracted = extract_filters_adaptive(req.query, llm_fn=None)
    if not extracted.is_empty():
        hard_filters.update(extracted.to_hard_filter())
        log.info(
            "search.prefilter_applied",
            program_prefix=extracted.program_prefix,
            sanitized_query=extracted.sanitized_query[:80],
        )

    # The query passed to the embedder/BM25 is the sanitized form when
    # filters were extracted — focuses similarity on semantic intent, not
    # the program-name token (which has been moved into hard_filters).
    # 中文：抽取出过滤条件时，传给嵌入器/BM25 的是清洗后的查询 —— 让相似度
    # 计算聚焦于语义意图，而不是已经挪进 hard_filters 的专业名 token。
    retrieval_query = (
        extracted.sanitized_query
        if not extracted.is_empty() and extracted.sanitized_query
        else req.query
    )
    pool_size = max(req.k, RERANK_POOL_SIZE) if reranker is not None else req.k
    hybrid_hits = hybrid.search(
        retrieval_query, hard_filters=hard_filters or None, k=pool_size,
    )

    if not hybrid_hits:
        elapsed_ms = _elapsed_ms(started)
        log.info(
            "search.hybrid_empty",
            query=req.query,
            duration_ms=elapsed_ms,
        )
        log_query(
            conn, route="search", query=req.query, matched_via="empty",
            k=req.k, latency_ms=elapsed_ms, user_id=telemetry_user,
        )
        return SearchResponse(
            query=req.query, k=req.k, matched_via="empty",
            results=[], latency_ms=round(elapsed_ms, 2),
        )

    # 3) Rerank + Z-score blend + reject (PLAN v2.2 §3.4 + §3.5).
    #    If reranker isn't loaded, fall back to bare hybrid (degraded mode).
    # 中文：3）重排 + Z-score 融合 + 拒答（PLAN v2.2 §3.4 + §3.5）。
    #    若 reranker 未加载，退回纯 hybrid（降级模式）。
    was_rescued = False
    if reranker is None:
        final_hits = hybrid_hits[: req.k]
        rejection_reason: str | None = None
    else:
        # One batched SELECT for all candidate texts (was ≤20 per-row queries).
        # 中文：对所有候选文本做一次批量 SELECT（此前是最多 20 条逐行查询）。
        texts = fetch_texts(conn, [h.course.course_id for h in hybrid_hits])
        # ADR-0018: calibrated gate fuses leg evidence the cross-encoder
        # can't see; opt-in via REJECTION_MODE=calibrated. Falls back to
        # the ADR-0016 threshold gate otherwise (gate_fn=None).
        # 中文（ADR-0018）：校准拒答门融合了交叉编码器看不到的两路证据；
        # 通过 REJECTION_MODE=calibrated 开启，否则退回 ADR-0016 的阈值门
        # （gate_fn=None）。
        gate_fn = None
        if settings.rejection_mode == "calibrated":
            diag = hybrid.last_diagnostics or {}
            gate_fn = build_gate_fn(
                query=req.query,
                bm25_top=diag.get("bm25_top", 0.0),
                vec_top=diag.get("vec_top", 0.0),
            )
        blended_hits, meta = rerank_blend_with_rejection(
            req.query, hybrid_hits, reranker,
            fetch_text=texts.get,
            blend_alpha=BLEND_ALPHA,
            reject_threshold=RERANKER_REJECT_THRESHOLD,
            top_k=req.k,
            gate_fn=gate_fn,
        )
        if meta["rejected"]:
            # ADR-0019: one LLM second-opinion + HyDE retrieval retry for
            # would-be-rejected queries. Garbage stays rejected (REJECT
            # verdict); evidence-poor real queries get a second chance.
            # Borderline-only: a high-confidence gate rejection skips the
            # LLM entirely (its verdict is flaky exactly on gibberish).
            # 中文（ADR-0019）：对本会被拒答的查询，追加一次 LLM 复核意见 +
            # HyDE 检索重试。真正的乱码仍维持拒答（REJECT 判决）；证据不足
            # 的真实查询则获得第二次机会。仅对临界情形生效：高置信度的门控
            # 拒答会完全跳过 LLM（LLM 恰恰在乱码上判断最不稳定）。
            rescued = None
            if rescue_fn is not None and (
                gate_fn is None
                or getattr(gate_fn, "last_p", 1.0)
                >= settings.rescue_min_probability
            ):
                rescued = attempt_hyde_rescue(
                    query=req.query, conn=conn, hybrid=hybrid,
                    reranker=reranker, rescue_fn=rescue_fn,
                    hard_filters=hard_filters or None,
                    pool_size=pool_size, blend_alpha=BLEND_ALPHA,
                    top_k=req.k,
                )
            if rescued is None:
                elapsed_ms = _elapsed_ms(started)
                log.info(
                    "search.rejected",
                    query=req.query,
                    max_sigmoid=meta["max_sigmoid"],
                    n_candidates=meta["n_candidates"],
                    duration_ms=elapsed_ms,
                )
                log_query(
                    conn, route="search", query=req.query,
                    matched_via="rejected", k=req.k, latency_ms=elapsed_ms,
                    rejection_reason=str(meta["reason"]),
                    user_id=telemetry_user,
                )
                return SearchResponse(
                    query=req.query, k=req.k, matched_via="rejected",
                    results=[], latency_ms=round(elapsed_ms, 2),
                    rejection_reason=str(meta["reason"]),
                )
            log.info("search.hyde_rescued", query=req.query, count=len(rescued))
            final_hits = rescued
            rejection_reason = None
            was_rescued = True
        else:
            final_hits = blended_hits
            rejection_reason = None

    results = [
        SearchHitOut(
            course_id=h.course.course_id,
            primary_code=h.course.primary_code,
            primary_name=h.course.primary_name,
            score=float(h.score),
            matched_via="hybrid",
        )
        for h in final_hits
    ]
    elapsed_ms = (time.perf_counter() - started) * 1000
    log.info(
        "search.hybrid",
        query=req.query,
        count=len(results),
        rerank_applied=reranker is not None,
        duration_ms=round(elapsed_ms, 2),
    )
    # Telemetry distinguishes hyde_rescued from organic hybrid (the API
    # response keeps "hybrid" — clients don't care HOW retrieval succeeded,
    # but ADR-0019 rescue-rate measurement mines query_log for it).
    # 中文：遥测层面区分 hyde_rescued 与普通 hybrid（API 响应本身仍统一显示
    # "hybrid" —— 客户端不关心检索具体是怎么成功的；但 ADR-0019 的救援率
    # 度量需要从 query_log 里挖出这个区分）。
    if was_rescued:
        telemetry_via = "hyde_rescued"
    else:
        telemetry_via = "hybrid" if results else "empty"
    log_query(
        conn, route="search", query=req.query,
        matched_via=telemetry_via,
        k=req.k, latency_ms=round(elapsed_ms, 2),
        result_course_ids=[r.course_id for r in results],
        user_id=telemetry_user,
    )
    return SearchResponse(
        query=req.query,
        k=req.k,
        matched_via="hybrid" if results else "empty",
        results=results,
        latency_ms=round(elapsed_ms, 2),
        rejection_reason=rejection_reason,
    )


