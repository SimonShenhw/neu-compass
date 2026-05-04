"""POST /search — alias-first then HybridRetriever fallback.

Pipeline (PLAN §1.2 query path):
  1. query_normalizer: regex → AliasRepository.resolve via v_course_lookup
     (which excludes review_status='pending' aliases — ADR §3.2 boundary).
     If alias hit, return immediately (no LLM/vector cost).
  2. HybridRetriever: BM25 + vector via RRF. Hard filters apply at the
     SQLite layer (Retriever._sqlite_filter) so pending courses can't leak
     (ADR-0013).

The alias path is keyed by exact text after light regex extraction. The
hybrid path handles natural-language and 中英 mix. Together they cover
"5800" / "Algo" / "应用 AI" / "course on backprop" without per-query
heuristics in the route.
"""

from __future__ import annotations

import time
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import (
    get_alias_repo,
    get_course_repo,
    get_hybrid_retriever,
)
from api.models import SearchHitOut, SearchRequest, SearchResponse
from db.alias_repository import AliasRepository
from db.repository import CourseRepository
from rag.hybrid import HybridRetriever
from rag.query_normalizer import normalize_query_to_course_ids
from schemas.course import DeliveryMode

router = APIRouter(prefix="/search", tags=["search"])

log = structlog.get_logger("neu_compass.search")


@router.post("", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    alias_repo: Annotated[AliasRepository, Depends(get_alias_repo)],
    course_repo: Annotated[CourseRepository, Depends(get_course_repo)],
    hybrid: Annotated[HybridRetriever, Depends(get_hybrid_retriever)],
) -> SearchResponse:
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
        elapsed_ms = (time.perf_counter() - started) * 1000
        log.info(
            "search.alias_hit",
            query=req.query,
            count=len(results),
            duration_ms=round(elapsed_ms, 2),
        )
        return SearchResponse(
            query=req.query,
            k=req.k,
            matched_via="alias",
            results=results,
            latency_ms=round(elapsed_ms, 2),
        )

    # 2) Hybrid path — embedder + BM25 + RRF.
    hard_filters = _build_hard_filters(req)
    hits = hybrid.search(req.query, hard_filters=hard_filters or None, k=req.k)
    results = [
        SearchHitOut(
            course_id=h.course.course_id,
            primary_code=h.course.primary_code,
            primary_name=h.course.primary_name,
            score=float(h.score),
            matched_via="hybrid",
        )
        for h in hits
    ]
    elapsed_ms = (time.perf_counter() - started) * 1000
    log.info(
        "search.hybrid",
        query=req.query,
        count=len(results),
        duration_ms=round(elapsed_ms, 2),
    )
    return SearchResponse(
        query=req.query,
        k=req.k,
        matched_via="hybrid" if results else "empty",
        results=results,
        latency_ms=round(elapsed_ms, 2),
    )


def _build_hard_filters(req: SearchRequest) -> dict[str, object]:
    """Pull the optional filter fields off the request into the dict shape
    Retriever._sqlite_filter expects. Skips None — `hard_filters={}` would
    still go through the WHERE-status branch with no narrowing."""
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
