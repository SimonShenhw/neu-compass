"""Shared helpers for route modules — single point of truth for plumbing
that /search and /chat both need.

Why this exists: the two routes previously each carried their own copy of
(a) a per-course `_fetch_text` closure (≤20 single-row SELECTs per request)
and (b) the request→hard_filters mapping. Copies drift; the batched
fetch is also simply faster (one `IN (...)` round-trip).

`attempt_hyde_rescue` (ADR-0019) also lives here because both routes run
the same rejection block and must share the same rescue semantics.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Callable, Protocol

import structlog

from rag.retriever import SearchHit

log = structlog.get_logger("neu_compass.routes.common")


class _FilterableRequest(Protocol):
    """Structural type covering SearchRequest and ChatRequest — both carry
    the same four optional hard-filter fields."""

    term: str | None
    credits: int | None
    delivery_mode: str | None
    professor: str | None


def build_hard_filters(req: _FilterableRequest) -> dict[str, object]:
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


def fetch_texts(
    conn: sqlite3.Connection,
    course_ids: list[str],
) -> dict[str, str | None]:
    """Batch-fetch raw_text for the reranker in ONE query.

    Returns {course_id: raw_text} for rows that exist; missing IDs are
    omitted, so `result.get(cid)` keeps the same None-fallback semantics
    the old per-row closure had (reranker falls back to primary_name).
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

    One LLM call second-opinions the query:
      - REJECT verdict (gibberish / homework / admin / fictional) → None;
        the caller keeps the original rejection. Garbage gets no retry.
      - Otherwise the hypothetical course description is appended to the
        query and retrieval re-runs — the embedder sees the expansion
        (HyDE distribution alignment + acronyms spelled out), while the
        reranker re-scores against the ORIGINAL query so the returned
        ordering still reflects what the user actually asked.

    Rejection is disabled on the retry on purpose: the LLM verdict replaced
    the evidence gate as the answerability judgment. Any failure (LLM error,
    empty retrieval) degrades to None — never breaks the original response.
    """
    from rag.rejection import query_has_code_pattern  # noqa: PLC0415
    from rag.reranker import rerank_blend_with_rejection  # noqa: PLC0415

    # Hard guard, no LLM consulted: a course-code-shaped query that reached
    # the gate already missed the alias tier — the course does not exist.
    # Live probe showed Gemini judges "AAI 9999" a plausible course query
    # and would happily write it a hypothetical description.
    if query_has_code_pattern(query):
        log.info("rescue.code_pattern_guard", query=query[:80])
        return None

    try:
        expansion = rescue_fn(query)
    except Exception as e:  # noqa: BLE001 — rescue must never 500 a request
        log.warning("rescue.llm_failed", error=str(e))
        return None
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
        reject_threshold=0.0,  # LLM verdict already vouched answerability
        top_k=top_k,
    )
    if not blended:
        return None
    log.info("rescue.accepted", query=query[:80], count=len(blended))
    return blended


__all__ = ["attempt_hyde_rescue", "build_hard_filters", "fetch_texts"]
