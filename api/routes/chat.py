"""POST /chat — streamed grounded course advisor (Week 6 PLAN §4.1).

Pipeline:
  query
    → query_normalizer → AliasRepository.resolve  (cheap exact path)
    → HybridRetriever.search (k=5 by default)     (semantic fallback)
    → llm.prompts.chat_v1.build_prompt
    → Gemini stream (token-by-token)

Wire format: NDJSON. One JSON object per line, chunks of:
  {"type": "meta",  "matched_via": "alias|hybrid|empty",
                    "results": [{"course_id", "primary_code", "primary_name", "score"}]}
  {"type": "token", "text": "..."}     (zero or more)
  {"type": "error", "detail": "..."}   (only on Gemini failure)
  {"type": "done"}                     (always last)

Streamlit consumes via httpx.stream + iter_lines + st.write_stream.
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

    Sync `def` on purpose (mirrors /search): retrieval + rerank run for
    100ms-to-seconds and would otherwise block the event loop. The NDJSON
    generator below stays a sync generator — Starlette already iterates
    those in the threadpool.
    """
    # Pre-ready gate: /chat invokes Gemini lazy-init via stream_fn. If hit
    # during lifespan warmup (~70s bge-m3 cold start), the SDK lazy-import
    # would block the request indefinitely. Refuse fast with 503 instead.
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
        matched_via="hyde_rescued" if was_rescued else matched_via,
        k=req.k, latency_ms=round(retrieval_ms, 2),
        result_course_ids=[h.course.course_id for h in hits],
        rejection_reason=rejection_reason,
        # Same eval-vs-organic split as /search: NULL = organic.
        user_id=f"eval:{x_eval_run}" if x_eval_run else None,
    )

    prompt = build_prompt(
        req.query, hits,
        history=[t.model_dump() for t in req.history],
    )

    def event_stream() -> Iterator[bytes]:
        # Meta first so the client can render evidence bubbles before LLM
        # tokens land.
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
        except Exception as e:  # defensive — never crash the stream
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

    `prefix_applied` is True iff the hybrid path was taken with a Layer 2
    program-prefix hard filter active. Caller uses it to scope the
    reranker reject threshold (within-program candidates shouldn't be
    rejected wholesale — see chat handler comment).

    When a reranker is available the hybrid leg requests a wider pool
    (RERANK_POOL_SIZE=20) so the reranker has room to reorder.
    """
    # Tier 0: conversation context (2026-06 continuity). A follow-up that
    # references "this course" without naming one resolves against the
    # previous turn's evidence (context_course_ids from the client) —
    # otherwise retrieval runs on a query with zero course signal, returns
    # noise, and the user gets "找不到匹配课程" right after discussing the
    # course. score=1.0 like the alias tier: the referent is explicit, no
    # ranking or rejection gate applies.
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
    extracted = extract_filters_adaptive(req.query, llm_fn=None)

    # Tier 2: program ontology shortcut. Only fires when (a) prefix detected,
    # (b) the query expresses "first-semester / foundational" intent, and
    # (c) a program is seeded for that prefix. Falls through to hybrid
    # otherwise (e.g. AAI prefix but the user is asking about a specific
    # advanced topic — let hybrid do its job).
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
