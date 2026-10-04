"""POST /chat — streamed grounded course advisor (Week 6 PLAN §4.1).

POST /chat —— 流式输出、基于检索证据的选课顾问（Week 6 PLAN §4.1）。

Pipeline:
  query
    → query_normalizer → AliasRepository.resolve  (cheap exact path)
    → HybridRetriever.search (k=5 by default)     (semantic fallback)
    → llm.prompts.chat_v4.build_prompt (history + explicit provenance/gaps)
    → Gemini stream (token-by-token)

流水线：查询依次经过 query_normalizer → AliasRepository.resolve（低成本的
精确匹配路径），再到 HybridRetriever.search（默认 k=5，语义兜底路径），
然后交给 llm.prompts.chat_v4.build_prompt（感知历史、区分来源与缺失值），
最后由 Gemini 逐 token 流式输出。

Wire format: NDJSON. One JSON object per line, chunks of:
  {"type": "meta",  "matched_via": "alias|hybrid|empty",
                    "results": [{"course_id", "primary_code", "primary_name", "score"}]}
  {"type": "token", "text": "..."}     (zero or more)
  {"type": "error", "detail": "..."}   (only on Gemini failure)
  {"type": "done", "feedback": {...}}  (optional receipt, always last)

线路格式：NDJSON。每行一个 JSON 对象，依次是：meta（携带 matched_via 与
results，供前端先渲染证据）、零到多个 token（逐字输出的文本片段）、
可选的 error（上游流失败时出现）、以及总是最后出现的 done。
done.feedback 仅在服务端启用、本请求明确允许保存、完整非空回答及关联存储
都成功时出现；凭证不放入 meta。默认不新增完整回答保存，原查询日志仍记录。

Streamlit consumes via httpx.stream + iter_lines + st.write_stream.

Streamlit 端通过 httpx.stream + iter_lines + st.write_stream 消费这个流。
"""

from __future__ import annotations

import json
import re
import sqlite3
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
    filter_courses,
    log_query,
)
from api.routes.search import (
    BLEND_ALPHA,
    RERANK_POOL_SIZE,
    RERANKER_REJECT_THRESHOLD,
)
from db.alias_repository import AliasRepository
from db.program_repository import ProgramAmbiguous, ProgramNotFound, ProgramRepository
from db.program_plan_repository import ProgramPlanRepository
from db.repository import CourseRepository
from config import settings
from llm.gemini_client import GeminiError
from llm.prompts.chat_v4 import PROMPT_VERSION, build_prompt
from llm.query_filter_extractor import extract_filters_adaptive
from rag.followup import is_followup_query
from rag.answer_evidence import build_answer_evidence
from rag.hybrid import HybridRetriever
from rag.query_normalizer import asks_for_alternatives, normalize_query_to_course_ids
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
        "primary_name, score, answer_evidence}, ...], prompt_version, notices?}` — emitted first so the client can "
        "render evidence bubbles before tokens land. `notices` appears only when "
        "non-empty, e.g. `program_schedule_unverified`: a first-semester/foundational "
        "question for a family whose version-scoped rules carry no verified schedule "
        "was answered from hybrid retrieval instead of a guessed sequence.\n"
        "2. `{\"type\": \"token\", \"text\": \"...\"}` — zero or more, "
        "Gemini stream chunks.\n"
        "3. `{\"type\": \"error\", \"detail\": \"...\"}` — only on Gemini "
        "stream failure.\n"
        "4. `{\"type\": \"done\", \"feedback\": {answer_id, answer_sha256, feedback_token}}` "
        "— always last; feedback is optional and issued only after a complete, "
        "non-empty answer and successful private storage. Never in meta. "
        "Receipt authorizes only this answer's latest vote via `POST /feedback`.\n\n"
        "Context, exact aliases, and program shortcuts apply explicit filters "
        "before top-k. Hybrid candidates use the same reranker/rejection "
        "policy as `/search`, including queries with a program prefix."
        " Answer evidence distinguishes archived catalog snapshots, extracted "
        "field quotes, unverified provenance and explicit data gaps; it is not "
        "a live catalog verification."
    ),
    responses={
        200: {
            "description": "NDJSON event stream. See description for shape.",
            "content": {"application/x-ndjson": {}},
        },
        422: {"description": "Invalid query / k / delivery_mode."},
        409: {"description": "Program selection is ambiguous or conflicts with the query's program prefix."},
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
    if req.program_id is not None:
        try:
            program_repo.get_program(req.program_id)
        except ProgramNotFound as exc:
            raise HTTPException(status_code=404, detail="Selected program_id not found") from exc
    try:
        hits, matched_via, hard_filters, notices = _retrieve(
            req, alias_repo, course_repo, hybrid, reranker, program_repo, conn,
        )
    except ProgramAmbiguous as exc:
        # The UI shows `detail` verbatim to the student — lead with Chinese.
        # 中文：UI 会把 detail 原样展示给学生，所以中文在前。
        choices = ", ".join(p.program_id for p in exc.programs)
        raise HTTPException(status_code=409, detail=(
            f"这个专业前缀对应多个项目，请先在上方「对话项目」里选择：{choices}。"
            f" ({exc})"
        )) from exc
    retrieval_ms = (time.perf_counter() - started) * 1000

    # Prefixes scope candidates, not relevance; keep the /search gate policy.
    # 中文：专业前缀只缩小候选池，不能证明相关性；与 /search 使用同一拒答策略。
    rejection_reason: str | None = None
    was_rescued = False
    if matched_via == "hybrid" and reranker is not None and hits:
        # One batched SELECT for all candidate texts (was ≤20 per-row queries).
        texts = fetch_texts(conn, [h.course.course_id for h in hits])

        gate_fn = None
        if settings.rejection_mode == "calibrated":
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
            reject_threshold=RERANKER_REJECT_THRESHOLD,
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
                    hard_filters=hard_filters or None,
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
    query_log_id = log_query(
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

    answer_evidence = build_answer_evidence(
        conn, [hit.course for hit in hits], program_seed=matched_via == "program",
    )
    prompt = build_prompt(
        req.query, hits,
        history=[t.model_dump() for t in req.history],
        evidence=answer_evidence, retrieval_mode=matched_via, notices=notices,
    )

    def event_stream() -> Iterator[bytes]:
        # Meta first so the client can render evidence bubbles before LLM
        # tokens land.
        # 中文：先发 meta，让客户端能在 LLM token 到达前先渲染证据气泡。
        meta_payload: dict[str, Any] = {
            "type": "meta",
            "matched_via": matched_via,
            "retrieval_ms": round(retrieval_ms, 2),
            "prompt_version": PROMPT_VERSION,
            "results": [
                {
                    "course_id": h.course.course_id,
                    "primary_code": h.course.primary_code,
                    "primary_name": h.course.primary_name,
                    "score": float(h.score),
                    "answer_evidence": answer_evidence[h.course.course_id].model_dump(mode="json"),
                }
                for h in hits
            ],
        }
        if rejection_reason is not None:
            meta_payload["rejection_reason"] = rejection_reason
        # Only present when non-empty, so the legacy meta shape is unchanged.
        # 中文：仅在非空时出现，旧的 meta 形状保持不变。
        if notices:
            meta_payload["notices"] = list(notices)
        yield (json.dumps(meta_payload) + "\n").encode("utf-8")

        # Bound memory and issue a receipt only after normal upstream completion.
        from schemas.answer_feedback import MAX_ANSWER_CHARS
        answer_parts: list[str] = []
        answer_chars = 0
        capture_answer = (query_log_id is not None and req.allow_feedback_capture
                          and settings.answer_feedback_enabled is True)
        feedback_receipt = None
        try:
            for chunk in stream_fn(prompt):
                if not isinstance(chunk, str):
                    raise TypeError('Chat tokens must be text')
                if capture_answer and chunk:
                    answer_chars += len(chunk)
                    if answer_chars <= MAX_ANSWER_CHARS:
                        answer_parts.append(chunk)
                    else:
                        capture_answer = False
                        answer_parts.clear()
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

        else:
            if capture_answer and ''.join(answer_parts).strip():
                feedback_receipt = _store_completed_answer(conn, query_log_id,
                    ''.join(answer_parts), req)
        done: dict[str, Any] = {"type": "done"}
        if feedback_receipt is not None:
            done['feedback'] = feedback_receipt
        yield (json.dumps(done) + "\n").encode("utf-8")

    return StreamingResponse(event_stream(), media_type="application/x-ndjson",
        headers={'Cache-Control':'no-store'})


def _store_completed_answer(conn, query_log_id, text, req):
    """Best effort after query commit. Failure never publishes a receipt."""
    # Recheck at completion: a disabled operator gate cannot publish a receipt.
    if settings.answer_feedback_enabled is not True or req.allow_feedback_capture is not True:
        return None
    from db.answer_feedback_repository import AnswerFeedbackRepository
    try:
        repo = AnswerFeedbackRepository(conn)
        if not repo.schema_available():
            return None
        context = req.model_dump(include={'k','term','credits','delivery_mode','professor',
            'program_id','context_course_ids'})
        context['history_turn_count'] = len(req.history)
        receipt = repo.store_completed(query_log_id=query_log_id, answer_text=text,
            prompt_version=PROMPT_VERSION, request_context=context)
        conn.commit()
        return receipt.model_dump(mode='json')
    except Exception as exc:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        # Never print token, answer, raw query, or exception detail.
        log.warning('chat.feedback_capture_failed', error_type=type(exc).__name__)
        return None


def _retrieve(
    req: ChatRequest,
    alias_repo: AliasRepository,
    course_repo: CourseRepository,
    hybrid: HybridRetriever,
    reranker: CrossEncoderReranker | None,
    program_repo: ProgramRepository,
    conn: sqlite3.Connection,
) -> tuple[list[SearchHit], str, dict[str, object], list[str]]:
    """Multi-tier retrieval: hits, route, effective hard filters, notices.

    多层级检索，返回命中、路由、实际生效的硬筛选条件和提示码。

    Tier order (most-specific first; first hit wins):

      0. **context** — a follow-up resolves previously returned course IDs.
      1. **alias** — explicit course-code or slang resolution via
         v_course_lookup. Cheapest path; bypasses hybrid + reranker.
      2. **program** (Layer 3) — prefix or explicit program_id plus
         "first-semester / foundational" intent. Ambiguity requires selection
         (409). A family with stored version-scoped rules but no verified
         schedule falls through to hybrid with the
         `program_schedule_unverified` notice — never the legacy guessed
         sequence, never an error. Only legacy-only families retain the
         unverified semester=1 shortcut.
      3. **hybrid** — BM25 + vector fusion over the indexed corpus, with
         Layer 2 program-prefix pre-filter applied at the SQLite layer.
         Caller runs reranker reject on this output.
      4. **empty** — nothing surfaced anywhere.

    层级顺序（从最具体到最泛，第一个命中者获胜）：

      0. **context** —— 追问解析上一轮返回的课程 ID。
      1. **alias** —— 经 v_course_lookup 显式解析课程代码或俗称。代价最低
         的路径；完全绕开 hybrid + reranker。
      2. **program**（Layer 3）—— 前缀或显式项目加"第一学期/基础课"意图。
         歧义需选择（409）；已有版本化规则却无核验学期安排时，带
         `program_schedule_unverified` 提示码落到 hybrid —— 不用旧猜测顺序，
         也不报错。仅旧 seed 项目保留未核验的 semester=1 捷径，不代表注册资格。
      3. **hybrid** —— 在已索引语料上融合 BM25 + 向量，并在 SQLite 层
         应用 Layer 2 的专业前缀预过滤。调用方会对这一路输出跑 reranker
         拒答检查。
      4. **empty** —— 哪一路都没有命中。

    Return the effective filters so an optional HyDE retry cannot lose the
    extracted prefix. Exact shortcuts filter BEFORE top-k and do not replace
    an excluded referent with unrelated hybrid results.
    中文：返回生效筛选供 HyDE 复用；精确入口先筛选再截断，不用无关课程替代。

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
    hard_filters = build_hard_filters(req)
    notices: list[str] = []
    if req.context_course_ids and is_followup_query(req.query):
        ctx_courses = course_repo.get_batch(req.context_course_ids)
        if ctx_courses:
            courses = filter_courses(conn, [
                ctx_courses[cid] for cid in req.context_course_ids if cid in ctx_courses
            ], hard_filters)
            ctx_hits = [SearchHit(course=course, score=1.0) for course in courses[: req.k]]
            log.info("chat.context_path", query=req.query[:80], count=len(ctx_hits))
            return ctx_hits, ("context" if ctx_hits else "empty"), hard_filters, notices

    # Exact references obey filters without becoming unrelated semantic searches.
    # 中文：精确课程引用也遵守筛选，不将排除的课程替换成语义检索结果。
    alias_ids = normalize_query_to_course_ids(req.query, alias_repo=alias_repo)
    if alias_ids:
        alias_courses = course_repo.get_batch(alias_ids)
        if alias_courses:
            courses = filter_courses(conn, [
                alias_courses[cid] for cid in alias_ids if cid in alias_courses
            ], hard_filters)
            hits = [SearchHit(course=course, score=1.0) for course in courses[: req.k]]
            # Anchor exception, same rule as /search: "courses like X" whose X
            # the filters exclude is a question about OTHER courses -> hybrid.
            # 中文：锚点例外，与 /search 同规则：问"类似 X 的课"而 X 被筛掉时，
            # 问的是其他课程 -> 走 hybrid。
            if hits or not (hard_filters and asks_for_alternatives(req.query)):
                return hits, ("alias" if hits else "empty"), hard_filters, notices
            log.info("chat.alias_anchor_filtered_fallback", query=req.query[:80])

    # Layer 2 + Layer 3: extract program prefix from query (regex first).
    # 中文：Layer 2 + Layer 3：从查询中抽取专业前缀（优先走正则）。
    extracted = extract_filters_adaptive(req.query, llm_fn=None)

    # Tier 2: prefix or explicit family plus foundational intent. Resolve
    # ambiguity before retrieval; scoped rule documents never imply a schedule.
    # Unseeded families/other intents continue to hybrid as before.
    # 中文：前缀或显式项目加基础课意图；先消除歧义，版本化规则不等于学期安排。
    if (
        (extracted.program_prefix is not None or req.program_id is not None)
        and _FOUNDATIONAL_INTENT_RE.search(req.query)
    ):
        program = (program_repo.get_program(req.program_id) if req.program_id
                   else program_repo.find_by_prefix(extracted.program_prefix))
        if program is not None:
            if req.program_id and extracted.program_prefix and program.prefix.upper() != extracted.program_prefix.upper():
                raise HTTPException(status_code=409, detail=(
                    "上方选择的对话项目与问题里的专业前缀不一致；请清空项目选择或改写问题。"
                    " (Selected program_id conflicts with the detected program prefix.)"
                ))
            if ProgramPlanRepository(conn).has_records_for_program(program.program_id):
                # Version-scoped rules exist but no verified schedule does. The
                # legacy guessed sequence must stay off — but this is the most
                # common onboarding question, so answer it (hybrid, below) and
                # say plainly that no verified schedule exists, never a 409.
                # 中文：已有版本化规则、但没有核验过的学期安排。旧的猜测顺序仍然
                # 不用 —— 但这是新生最常问的问题，所以走下面的 hybrid 照常回答，
                # 并明确说明没有核验的学期安排，而不是返回 409。
                notices.append("program_schedule_unverified")
                log.info("chat.program_schedule_unverified", program_id=program.program_id)
            else:
                edges = program_repo.list_required_courses(
                    program.program_id, semester=1,
                )
                program_courses = course_repo.get_batch([edge.course_id for edge in edges])
                for edge in edges:
                    if edge.course_id not in program_courses:
                        log.warning(
                            "chat.program_dangling", program_id=program.program_id,
                            course_id=edge.course_id,
                        )
                if program_courses:
                    courses = filter_courses(conn, [
                        program_courses[edge.course_id] for edge in edges
                        if edge.course_id in program_courses
                    ], hard_filters)
                    program_hits = [
                        SearchHit(course=course, score=1.0) for course in courses[: req.k]
                    ]
                    log.info(
                        "chat.program_path", program_id=program.program_id,
                        prefix=program.prefix, count=len(program_hits),
                    )
                    return program_hits, ("program" if program_hits else "empty"), hard_filters, notices

    # Tier 3: hybrid with Layer 2 prefix pre-filter.
    # 中文：Tier 3：带 Layer 2 前缀预过滤的 hybrid。
    prefix_applied = not extracted.is_empty()
    if prefix_applied:
        hard_filters.update(extracted.to_hard_filter())
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
    hits = hybrid.search(retrieval_query, hard_filters=hard_filters or None, k=pool_size)
    return hits, ("hybrid" if hits else "empty"), hard_filters, notices
