"""POST /chat — streamed grounded course advisor (Week 6 PLAN §4.1).

POST /chat —— 流式输出、基于检索证据的选课顾问（Week 6 PLAN §4.1）。

Pipeline:
  query
    → query_normalizer → AliasRepository.resolve  (cheap exact path)
    → HybridRetriever.search (k=5 by default)     (semantic fallback)
    → llm.prompts.chat_v3.build_prompt (history-aware, content-grounded)
    → Gemini stream (token-by-token)

流水线：查询依次经过 query_normalizer → AliasRepository.resolve（低成本的
精确匹配路径），再到 HybridRetriever.search（默认 k=5，语义兜底路径），
然后交给 llm.prompts.chat_v3.build_prompt（感知历史、基于内容生成），
最后由 Gemini 逐 token 流式输出。

Wire format: NDJSON. One JSON object per line, chunks of:
  {"type": "meta",  "matched_via": "alias|hybrid|empty",
                    "results": [{"course_id", "primary_code", "primary_name", "score"}]}
  {"type": "token", "text": "..."}     (zero or more)
  {"type": "error", "detail": "..."}   (only on Gemini failure)
  {"type": "done"}                     (always last)

线路格式：NDJSON。每行一个 JSON 对象，依次是：meta（携带 matched_via 与
results，供前端先渲染证据）、零到多个 token（逐字输出的文本片段）、
可选的 error（仅在 Gemini 失败时出现）、以及总是最后出现的 done。

Streamlit consumes via httpx.stream + iter_lines + st.write_stream.

Streamlit 端通过 httpx.stream + iter_lines + st.write_stream 消费这个流。
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator as _Iter
from typing import Annotated, Any, Callable, Iterator

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from api.dependencies import (
    DbConn,
    get_alias_repo,
    get_chat_stream_fn,
    get_course_repo,
    get_hybrid_retriever,
    get_hyde_rescue_fn,
    get_program_repo,
    get_reranker,
)
from api.models import ChatRequest
from api.routes.common import (
    attempt_hyde_rescue,
    build_hard_filters,
    fetch_texts,
    log_query,
)
from api.routes.search import (
    BLEND_ALPHA,
    RERANK_POOL_SIZE,
    RERANKER_REJECT_THRESHOLD,
)
from db.alias_repository import AliasRepository
from db.program_repository import ProgramRepository
from db.repository import CourseRepository
from config import settings
from llm.gemini_client import GeminiError
from llm.prompts.chat_v3 import build_prompt
from llm.query_filter_extractor import extract_filters_adaptive
from rag.followup import is_followup_query
from rag.hybrid import HybridRetriever
from rag.query_normalizer import normalize_query_to_course_ids
from rag.rejection import build_gate_fn
from rag.reranker import CrossEncoderReranker, rerank_blend_with_rejection
from rag.retriever import SearchHit
from schemas.course import DeliveryMode

# Layer 3 (PLAN v3.0): regex detecting "first-semester / foundational" intent.
# When this fires AND the user mentions a program prefix, we short-circuit
# to the program ontology (programs + program_required_courses) instead of
# guessing via hybrid retrieval. ASCII flag mirrors query_normalizer fix —
# CJK chars don't act as word chars so '基础' boundary works correctly.
# 中文（Layer 3，PLAN v3.0）：识别"第一学期/基础课"意图的正则。当它命中且
# 用户提到了专业前缀时，直接短路到培养方案本体（programs +
# program_required_courses），而不是靠混合检索去猜。ASCII 标志位与
# query_normalizer 的修复思路一致 —— CJK 字符不算单词字符，因此 '基础' 的
# 边界匹配才能正常工作。
_FOUNDATIONAL_INTENT_RE = re.compile(
    r"(?:first[- ]?semester|foundational|core course|入门|基础|"
    r"第一(?:个)?学期|第一年|first[- ]?year|recommended for new|刚入学)",
    re.IGNORECASE,
)

router = APIRouter(prefix="/chat", tags=["chat"])

log = structlog.get_logger("neu_compass.chat")


@router.post(
    "",
    summary="Streamed grounded course advisor (NDJSON)",
    description=(
        "Streams a Gemini-generated answer grounded in the retrieved courses.\n\n"
        "**Wire format**: `application/x-ndjson` — one JSON object per "
        "newline. Object types in order:\n\n"
        "1. `{\"type\": \"meta\", \"matched_via\": \"alias|hybrid|empty\", "
        "\"retrieval_ms\": float, \"results\": [{course_id, primary_code, "
        "primary_name, score}, ...]}` — emitted first so the client can "
        "render evidence bubbles before tokens land.\n"
        "2. `{\"type\": \"token\", \"text\": \"...\"}` — zero or more, "
        "Gemini stream chunks.\n"
        "3. `{\"type\": \"error\", \"detail\": \"...\"}` — only on Gemini "
        "stream failure.\n"
        "4. `{\"type\": \"done\"}` — always last.\n\n"
        "Retrieval mirrors `/search` step 1+2 (alias-first, then hybrid). "
        "**No reranker on the chat path** in v0.1 — tokens stream while "
        "rerank+blend cost would block the first-token latency."
    ),
    responses={
        200: {
            "description": "NDJSON event stream. See description for shape.",
            "content": {"application/x-ndjson": {}},
        },
        422: {"description": "Invalid query / k / delivery_mode."},
    },
)
def chat(
    req: ChatRequest,
    request: Request,
    alias_repo: Annotated[AliasRepository, Depends(get_alias_repo)],
    course_repo: Annotated[CourseRepository, Depends(get_course_repo)],
    hybrid: Annotated[HybridRetriever, Depends(get_hybrid_retriever)],
    reranker: Annotated[CrossEncoderReranker | None, Depends(get_reranker)],
    program_repo: Annotated[ProgramRepository, Depends(get_program_repo)],
    conn: DbConn,
    stream_fn: Annotated[
        Callable[[str], _Iter[str]],
        Depends(get_chat_stream_fn),
    ],
    rescue_fn: Annotated[
        Callable[[str], str | None] | None, Depends(get_hyde_rescue_fn)
    ] = None,
    x_eval_run: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """Stream a Gemini-generated answer grounded in the retrieved courses.

    流式输出由 Gemini 生成、基于检索课程的回答。

    Sync `def` on purpose (mirrors /search): retrieval + rerank run for
    100ms-to-seconds and would otherwise block the event loop. The NDJSON
    generator below stays a sync generator — Starlette already iterates
    those in the threadpool.

    此处故意用同步 def（与 /search 一致）：检索 + 重排耗时从 100ms 到数秒
    不等，否则会阻塞事件循环。下面的 NDJSON 生成器也保持同步生成器 ——
    Starlette 本就会把它们放进线程池里迭代。
    """
    # Pre-ready gate: /chat invokes Gemini lazy-init via stream_fn. If hit
    # during lifespan warmup (~70s bge-m3 cold start), the SDK lazy-import
    # would block the request indefinitely. Refuse fast with 503 instead.
    # 中文：预就绪门禁 —— /chat 通过 stream_fn 触发 Gemini 的惰性初始化。若在
    # lifespan 预热期间（bge-m3 冷启动约 70s）命中，SDK 的惰性 import 会让
    # 请求无限期挂起。这里改为快速返回 503。
    if not getattr(request.app.state, "ready", False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service warming up. Check /ready and retry shortly.",
        )

    if req.delivery_mode is not None:
        try:
            DeliveryMode(req.delivery_mode)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid delivery_mode: {req.delivery_mode!r}",
            ) from e

    started = time.perf_counter()
    hits, matched_via, prefix_applied = _retrieve(
        req, alias_repo, course_repo, hybrid, reranker, program_repo,
    )
    retrieval_ms = (time.perf_counter() - started) * 1000

    # v2: chat path now mirrors /search by running a reranker reject pass on the
    # hybrid candidate pool. If raw sigmoid is below the calibrated threshold
    # (ADR-0016), we hand the LLM an empty list — chat_v2 prompt then says "no
    # match in catalog" instead of falling back to recommending whatever was
    # closest. Cost: one extra reranker forward pass on ≤20 candidates (~50ms
    # on RTX 5090 ONNX).
    #
    # Subtle but important: when Layer 2 prefix filter narrowed the pool (e.g.
    # query mentioned "AAI 专业" so we only retrieved among 23 AAI courses),
    # disable reject. Prefix filter already provides high-precision narrowing;
    # reranker's job here is to ORDER the within-program candidates, not
    # second-guess relevance. Otherwise cross-lingual edge cases like "强化学习"
    # vs "Applied Reinforcement Learning" land just below the 0.05 sigmoid
    # threshold (sigmoid 0.044, observed 2026-05-09) and the user gets a
    # frustrating "no match" reply when AAI 6740 is exactly the answer.
    # 中文：v2 —— chat 路径现在与 /search 一致，会在混合候选池上跑一次
    # reranker 拒答检查。若原始 sigmoid 低于校准阈值（ADR-0016），就把空
    # 列表交给 LLM —— chat_v2 的 prompt 会回答"目录中无匹配"，而不是退而
    # 推荐最接近的那个。代价：对 ≤20 个候选多跑一次 reranker 前向
    # （RTX 5090 ONNX 上约 50ms）。
    #
    # 有个细节但很重要：当 Layer 2 的前缀过滤已经收窄过候选池时（例如查询
    # 提到"AAI 专业"，于是只在 23 门 AAI 课程里检索），要关闭拒答。前缀
    # 过滤本身就提供了高精度的收窄；这里 reranker 的任务是给同专业内候选
    # 排序，而不是重新怀疑相关性。否则像"强化学习" vs
    # "Applied Reinforcement Learning"这类跨语言边界情形会刚好落在 0.05
    # sigmoid 阈值之下（2026-05-09 观测到 sigmoid 0.044），导致 AAI 6740
    # 明明是正确答案，用户却收到令人沮丧的"无匹配"回复。
    rejection_reason: str | None = None
    was_rescued = False
    if matched_via == "hybrid" and reranker is not None and hits:
        # One batched SELECT for all candidate texts (was ≤20 per-row queries).
        texts = fetch_texts(conn, [h.course.course_id for h in hits])

        # Threshold=0.0 disables rejection while still computing blended scores
        # for ordering. We could call a no-reject variant of the function but
        # keeping a single call site is clearer. When the Layer 2 prefix
        # filter narrowed the pool, NO gate runs (threshold or calibrated) —
        # within-prefix candidates shouldn't be rejected wholesale.
        # 中文：阈值设为 0.0 即关闭拒答，但仍会计算融合分数用于排序。本可以
        # 另写一个不拒答的函数变体，但保持单一调用点更清晰。当 Layer 2 前缀
        # 过滤已收窄候选池时，两种门（阈值门或校准门）都不运行 —— 前缀内的
        # 候选不该被整体拒答。
        effective_threshold = 0.0 if prefix_applied else RERANKER_REJECT_THRESHOLD
        gate_fn = None
        if not prefix_applied and settings.rejection_mode == "calibrated":
            diag = hybrid.last_diagnostics or {}
            gate_fn = build_gate_fn(
                query=req.query,
                bm25_top=diag.get("bm25_top", 0.0),
                vec_top=diag.get("vec_top", 0.0),
            )
        blended_hits, rerank_meta = rerank_blend_with_rejection(
            req.query, hits, reranker,
            fetch_text=texts.get,
            blend_alpha=BLEND_ALPHA,
            reject_threshold=effective_threshold,
            top_k=req.k,
            gate_fn=gate_fn,
        )
        if rerank_meta["rejected"]:
            # ADR-0019 rescue — same semantics as /search (incl. the
            # borderline-only scope: high-confidence rejections skip the LLM).
            # 中文（ADR-0019）：救援逻辑，与 /search 语义一致（含仅临界情形
            # 生效的范围限定：高置信度拒答会跳过 LLM）。
            rescued = None
            if rescue_fn is not None and (
                gate_fn is None
                or getattr(gate_fn, "last_p", 1.0)
                >= settings.rescue_min_probability
            ):
                rescued = attempt_hyde_rescue(
                    query=req.query, conn=conn, hybrid=hybrid,
                    reranker=reranker, rescue_fn=rescue_fn,
                    hard_filters=build_hard_filters(req) or None,
                    pool_size=max(req.k, RERANK_POOL_SIZE),
                    blend_alpha=BLEND_ALPHA, top_k=req.k,
                )
            if rescued is not None:
                log.info("chat.hyde_rescued", query=req.query, count=len(rescued))
                hits = rescued
                was_rescued = True
            else:
                hits = []
                matched_via = "rejected"
                rejection_reason = str(rerank_meta["reason"])
        else:
            hits = blended_hits

    log.info(
        "chat.retrieved",
        query=req.query,
        matched_via=matched_via,
        count=len(hits),
        rejection_reason=rejection_reason,
        retrieval_ms=round(retrieval_ms, 2),
    )
    log_query(
        conn, route="chat", query=req.query,
        # Telemetry-only distinction (response keeps "hybrid"): ADR-0019
        # rescue-rate measurement mines query_log for hyde_rescued rows.
        # 中文：仅遥测层面区分（响应本身仍是 "hybrid"）：ADR-0019 的救援率
        # 度量会从 query_log 中挖掘 hyde_rescued 记录。
        matched_via="hyde_rescued" if was_rescued else matched_via,
        k=req.k, latency_ms=round(retrieval_ms, 2),
        result_course_ids=[h.course.course_id for h in hits],
        rejection_reason=rejection_reason,
        # Same eval-vs-organic split as /search: NULL = organic.
        # 中文：与 /search 相同的评测 vs 真实用户区分：NULL = 真实用户。
        user_id=f"eval:{x_eval_run}" if x_eval_run else None,
    )

    prompt = build_prompt(
        req.query, hits,
        history=[t.model_dump() for t in req.history],
    )

    def event_stream() -> Iterator[bytes]:
        # Meta first so the client can render evidence bubbles before LLM
        # tokens land.
        # 中文：先发 meta，让客户端能在 LLM token 到达前先渲染证据气泡。
        meta_payload: dict[str, Any] = {
            "type": "meta",
            "matched_via": matched_via,
            "retrieval_ms": round(retrieval_ms, 2),
            "results": [
                {
                    "course_id": h.course.course_id,
                    "primary_code": h.course.primary_code,
                    "primary_name": h.course.primary_name,
                    "score": float(h.score),
                }
                for h in hits
            ],
        }
        if rejection_reason is not None:
            meta_payload["rejection_reason"] = rejection_reason
        yield (json.dumps(meta_payload) + "\n").encode("utf-8")

        try:
            for chunk in stream_fn(prompt):
                payload = {"type": "token", "text": chunk}
                yield (json.dumps(payload) + "\n").encode("utf-8")
        except GeminiError as e:
            log.warning("chat.stream_failed", error=str(e))
            yield (json.dumps({"type": "error", "detail": str(e)}) + "\n").encode(
                "utf-8"
            )
        except Exception as e:  # defensive — never crash the stream / 防御性：绝不能让流崩溃
            log.exception("chat.stream_unhandled")
            yield (
                json.dumps(
                    {"type": "error", "detail": f"{type(e).__name__}: {e}"}
                )
                + "\n"
            ).encode("utf-8")

        yield (json.dumps({"type": "done"}) + "\n").encode("utf-8")

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


def _retrieve(
    req: ChatRequest,
    alias_repo: AliasRepository,
    course_repo: CourseRepository,
    hybrid: HybridRetriever,
    reranker: CrossEncoderReranker | None,
    program_repo: ProgramRepository,
) -> tuple[list[SearchHit], str, bool]:
    """Multi-tier retrieval, returning (hits, matched_via, prefix_applied).

    多层级检索，返回 (hits, matched_via, prefix_applied)。

    Tier order (most-specific first; first hit wins):

      1. **alias** — explicit course-code or slang resolution via
         v_course_lookup. Cheapest path; bypasses hybrid + reranker.
      2. **program** (Layer 3) — query mentions a program prefix AND a
         "first-semester / foundational" intent → look up the program's
         seeded curriculum and return semester=1 courses. Deterministic;
         answers "AAI 专业第一学期选啥" without retrieval guesswork.
      3. **hybrid** — BM25 + vector + RRF over the indexed corpus, with
         Layer 2 program-prefix pre-filter applied at the SQLite layer.
         Caller runs reranker reject on this output.
      4. **empty** — nothing surfaced anywhere.

    层级顺序（从最具体到最泛，第一个命中者获胜）：

      1. **alias** —— 经 v_course_lookup 显式解析课程代码或俗称。代价最低
         的路径；完全绕开 hybrid + reranker。
      2. **program**（Layer 3）—— 查询提到专业前缀且带有"第一学期/基础课"
         意图 → 查该专业预置的培养方案，返回 semester=1 的课程。这是
         确定性的；无需检索猜测即可回答"AAI 专业第一学期选啥"。
      3. **hybrid** —— 在已索引语料上跑 BM25 + 向量 + RRF，并在 SQLite 层
         应用 Layer 2 的专业前缀预过滤。调用方会对这一路输出跑 reranker
         拒答检查。
      4. **empty** —— 哪一路都没有命中。

    `prefix_applied` is True iff the hybrid path was taken with a Layer 2
    program-prefix hard filter active. Caller uses it to scope the
    reranker reject threshold (within-program candidates shouldn't be
    rejected wholesale — see chat handler comment).

    `prefix_applied` 为 True 当且仅当走了 hybrid 路径且 Layer 2 的专业前缀
    硬过滤处于生效状态。调用方用它来限定 reranker 拒答阈值的作用范围
    （同专业内的候选不该被整体拒答 —— 参见 chat 处理函数里的注释）。

    When a reranker is available the hybrid leg requests a wider pool
    (RERANK_POOL_SIZE=20) so the reranker has room to reorder.

    有 reranker 可用时，hybrid 这一路会请求更大的候选池
    （RERANK_POOL_SIZE=20），给 reranker 留出重新排序的空间。
    """
    # Tier 0: conversation context (2026-06 continuity). A follow-up that
    # references "this course" without naming one resolves against the
    # previous turn's evidence (context_course_ids from the client) —
    # otherwise retrieval runs on a query with zero course signal, returns
    # noise, and the user gets "找不到匹配课程" right after discussing the
    # course. score=1.0 like the alias tier: the referent is explicit, no
    # ranking or rejection gate applies.
    # 中文：Tier 0：对话上下文（2026-06 连续性功能）。追问中提到"这门课"却
    # 没点名具体是哪门时，靠上一轮的证据（客户端传来的 context_course_ids）
    # 来解析所指 —— 否则检索会在一个不含任何课程信号的查询上运行，返回
    # 噪声，用户在刚讨论完某门课后却收到"找不到匹配课程"。score=1.0 与
    # 别名层一样：所指对象已经明确，不需要跑排序或拒答门。
    if req.context_course_ids and is_followup_query(req.query):
        ctx_courses = course_repo.get_batch(req.context_course_ids[: req.k])
        ctx_hits = [
            SearchHit(course=ctx_courses[cid], score=1.0)
            for cid in req.context_course_ids[: req.k]
            if cid in ctx_courses
        ]
        if ctx_hits:
            log.info(
                "chat.context_path",
                query=req.query[:80],
                count=len(ctx_hits),
            )
            return ctx_hits, "context", False

    # Tier 1: alias — skipped when explicit request filters are present:
    # the alias tier can't apply term/credits/mode/professor, so returning
    # an unfiltered hit would contradict the request. Mirrors /search.
    # 中文：Tier 1：别名 —— 请求带显式过滤条件时跳过：别名层无法施加
    # term/credits/mode/professor 过滤，返回未过滤的命中会违背请求本意。
    # 与 /search 逻辑一致。
    alias_ids = (
        []
        if build_hard_filters(req)
        else normalize_query_to_course_ids(req.query, alias_repo=alias_repo)
    )
    if alias_ids:
        out: list[SearchHit] = []
        for cid in alias_ids[: req.k]:
            try:
                course = course_repo.get(cid)
            except LookupError:
                continue
            out.append(SearchHit(course=course, score=1.0))
        if out:
            return out, "alias", False

    # Layer 2 + Layer 3: extract program prefix from query (regex first).
    # 中文：Layer 2 + Layer 3：从查询中抽取专业前缀（优先走正则）。
    extracted = extract_filters_adaptive(req.query, llm_fn=None)

    # Tier 2: program ontology shortcut. Only fires when (a) prefix detected,
    # (b) the query expresses "first-semester / foundational" intent, and
    # (c) a program is seeded for that prefix. Falls through to hybrid
    # otherwise (e.g. AAI prefix but the user is asking about a specific
    # advanced topic — let hybrid do its job).
    # 中文：Tier 2：培养方案本体捷径。仅当（a）检测到前缀、（b）查询表达出
    # "第一学期/基础课"意图、且（c）该前缀已预置培养方案时才触发。否则
    # 落回 hybrid（例如虽有 AAI 前缀，但用户问的是某个具体的高阶话题 ——
    # 交给 hybrid 处理）。
    if (
        extracted.program_prefix is not None
        and _FOUNDATIONAL_INTENT_RE.search(req.query)
    ):
        program = program_repo.find_by_prefix(extracted.program_prefix)
        if program is not None:
            edges = program_repo.list_required_courses(
                program.program_id, semester=1,
            )
            program_hits: list[SearchHit] = []
            for edge in edges[: req.k]:
                try:
                    course = course_repo.get(edge.course_id)
                except LookupError:
                    log.warning(
                        "chat.program_dangling",
                        program_id=program.program_id,
                        course_id=edge.course_id,
                    )
                    continue
                program_hits.append(SearchHit(course=course, score=1.0))
            if program_hits:
                log.info(
                    "chat.program_path",
                    program_id=program.program_id,
                    prefix=program.prefix,
                    count=len(program_hits),
                )
                return program_hits, "program", False

    # Tier 3: hybrid with Layer 2 prefix pre-filter.
    # 中文：Tier 3：带 Layer 2 前缀预过滤的 hybrid。
    filters = build_hard_filters(req)
    prefix_applied = not extracted.is_empty()
    if prefix_applied:
        filters.update(extracted.to_hard_filter())
        log.info(
            "chat.prefilter_applied",
            program_prefix=extracted.program_prefix,
            sanitized_query=extracted.sanitized_query[:80],
        )
    retrieval_query = (
        extracted.sanitized_query
        if prefix_applied and extracted.sanitized_query
        else req.query
    )
    pool_size = max(req.k, RERANK_POOL_SIZE) if reranker is not None else req.k
    hits = hybrid.search(retrieval_query, hard_filters=filters or None, k=pool_size)
    return hits, ("hybrid" if hits else "empty"), prefix_applied
