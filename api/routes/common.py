"""Shared helpers for route modules — single point of truth for plumbing
that /search and /chat both need.

Why this exists: the two routes previously each carried their own copy of
(a) a per-course `_fetch_text` closure (≤20 single-row SELECTs per request)
and (b) the request→hard_filters mapping. Copies drift; the batched
fetch is also simply faster (one `IN (...)` round-trip).
"""

from __future__ import annotations

import sqlite3
from typing import Protocol


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


__all__ = ["build_hard_filters", "fetch_texts"]
