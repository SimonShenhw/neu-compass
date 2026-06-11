"""POST /search — alias-first → HybridRetriever → rerank+blend+reject.

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

The alias path is keyed by exact text after light regex extraction. The
hybrid path handles natural-language and 中英 mix. Together they cover
"5800" / "Algo" / "应用 AI" / "course on backprop" without per-query
heuristics in the route.

If `app.state.reranker` is None (e.g. degraded environment without the
~600MB weights), the route falls back to bare hybrid output. Tests that
exercise rejection inject a deterministic stub via conftest.
"""

from __future__ import annotations

import time
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import (
    DbConn,
    get_alias_repo,
    get_course_repo,
    get_hybrid_retriever,
    get_reranker,
)
from api.models import SearchHitOut, SearchRequest, SearchResponse
from api.routes.common import build_hard_filters, fetch_texts
from config import settings
from db.alias_repository import AliasRepository
from db.repository import CourseRepository
from llm.query_filter_extractor import extract_filters_adaptive
from rag.hybrid import HybridRetriever
from rag.query_normalizer import normalize_query_to_course_ids
from rag.reranker import CrossEncoderReranker, rerank_blend_with_rejection
from schemas.course import DeliveryMode

router = APIRouter(prefix="/search", tags=["search"])

log = structlog.get_logger("neu_compass.search")

# PLAN v2.2 §3.4 + ADR-0015. Tunable; ADR-supplement if changed.
RERANK_POOL_SIZE = settings.rerank_pool_size
"""Candidates HybridRetriever returns before rerank+blend narrows to req.k.
Env-overridable (RERANK_POOL_SIZE, default 20) so the NAS can A/B pool sizes
without a redeploy — the cross-encoder pass over this pool is the /search
p50 bottleneck there."""

RERANKER_REJECT_THRESHOLD = 0.05
"""Raw bge-reranker sigmoid below which the query has no good match.
Calibrated by ADR-0016 ROC sweep (was 0.4 in PLAN v2.2 §3.4 spec);
empirical data on test_set v0.2 showed 0.4 false-rejected ~26% of real
queries. T=0.05 catches all 4 adversarial AND keeps real R@5 baseline."""

BLEND_ALPHA = 0.4
"""Z-score blend weight on RRF leg. 0.0 = pure reranker, 1.0 = pure RRF.
Locked by ADR-0015 sweep on test_set v0.2 (n=42); re-sweep on v0.3 mandatory."""


def _elapsed_ms(started: float) -> float:
    """Elapsed time since `started` (perf_counter) in milliseconds, rounded."""
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
    conn: DbConn,
) -> SearchResponse:
    # Sync `def` on purpose: FastAPI runs it in the threadpool. The embedder +
    # reranker forward passes here take 100ms (RTX 5090) to seconds (NAS Iris
    # Xe) — as `async def` they ran ON the event loop, starving every other
    # request including /health and /ready (whose failures can trigger Docker
    # healthcheck restarts). Model singletons hold their own locks.
    started = time.perf_counter()

    # Validate enum-typed filter early (FastAPI Pydantic accepts the str via
    # SearchRequest, but DeliveryMode would 500 if mistyped at the retriever).
    if req.delivery_mode is not None:
        try:
            DeliveryMode(req.delivery_mode)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid delivery_mode: {req.delivery_mode!r}",
            ) from e

    # 1) Alias path — cheap. If the user typed a code or known slang, resolve
    #    directly and skip the embedder/BM25 entirely.
    alias_ids = normalize_query_to_course_ids(req.query, alias_repo=alias_repo)
    if alias_ids:
        results: list[SearchHitOut] = []
        for cid in alias_ids[: req.k]:
            try:
                course = course_repo.get(cid)
            except LookupError:
                # Alias points at a course_id that's vanished — log and skip
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
        elapsed_ms = _elapsed_ms(started)
        log.info(
            "search.alias_hit",
            query=req.query,
            count=len(results),
            duration_ms=elapsed_ms,
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
    hard_filters = build_hard_filters(req)

    # Layer 2 (PLAN v3.0+): if the query mentions a program / major prefix,
    # narrow the candidate pool at SQLite WHERE so vector + BM25 don't pull
    # in cross-discipline noise. Cheap regex first; LLM fallback is wired
    # through llm_fn (passing None here = regex-only — adding the LLM hop
    # is a follow-up once we measure regex hit rate from real query logs).
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
        return SearchResponse(
            query=req.query, k=req.k, matched_via="empty",
            results=[], latency_ms=round(elapsed_ms, 2),
        )

    # 3) Rerank + Z-score blend + reject (PLAN v2.2 §3.4 + §3.5).
    #    If reranker isn't loaded, fall back to bare hybrid (degraded mode).
    if reranker is None:
        final_hits = hybrid_hits[: req.k]
        rejection_reason: str | None = None
    else:
        # One batched SELECT for all candidate texts (was ≤20 per-row queries).
        texts = fetch_texts(conn, [h.course.course_id for h in hybrid_hits])
        blended_hits, meta = rerank_blend_with_rejection(
            req.query, hybrid_hits, reranker,
            fetch_text=texts.get,
            blend_alpha=BLEND_ALPHA,
            reject_threshold=RERANKER_REJECT_THRESHOLD,
            top_k=req.k,
        )
        if meta["rejected"]:
            elapsed_ms = _elapsed_ms(started)
            log.info(
                "search.rejected",
                query=req.query,
                max_sigmoid=meta["max_sigmoid"],
                n_candidates=meta["n_candidates"],
                duration_ms=elapsed_ms,
            )
            return SearchResponse(
                query=req.query, k=req.k, matched_via="rejected",
                results=[], latency_ms=round(elapsed_ms, 2),
                rejection_reason=str(meta["reason"]),
            )
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
    return SearchResponse(
        query=req.query,
        k=req.k,
        matched_via="hybrid" if results else "empty",
        results=results,
        latency_ms=round(elapsed_ms, 2),
        rejection_reason=rejection_reason,
    )


