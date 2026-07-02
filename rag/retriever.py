"""Three-step retriever: SQLite hard filter -> FAISS vector search -> rehydrate.

Implements PLAN §1.2 query path. ADR-0013 invariant enforced via
status='indexed' filter — pending courses cannot be returned.

Hard filters supported (PLAN metadata JSON1 indexes):
  term, credits, delivery_mode  (exact match)
  professor                     (LIKE substring, optional)

Hybrid search (BM25 + vector) and HyDE expansion live in separate modules
under rag/ later (Week 5). This file is the canonical "default" retriever.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from db.repository import CourseRepository
from rag.embedder import EmbedderProtocol
from rag.index import FaissIndex
from schemas.course import Course

# Status of courses eligible for retrieval. ADR-0013: pending = not yet
# embedded; failed = gave up; only indexed has a valid FAISS row.
ELIGIBLE_STATUS = "indexed"


@dataclass
class SearchHit:
    """One result with similarity score + Course payload."""

    course: Course
    score: float


class Retriever:
    """Composes embedder + FAISS index + SQLite hard filter."""

    def __init__(
        self,
        *,
        embedder: EmbedderProtocol,
        index: FaissIndex,
        course_repo: CourseRepository,
        sqlite_conn: sqlite3.Connection,
    ) -> None:
        self._embedder = embedder
        self._index = index
        self._course_repo = course_repo
        self._conn = sqlite_conn

    def search(
        self,
        query: str,
        *,
        hard_filters: dict[str, Any] | None = None,
        k: int = 10,
    ) -> list[SearchHit]:
        """Run the three-step pipeline. Returns top-k hits sorted by score."""
        top = self.search_ids(query, hard_filters=hard_filters, k=k)
        if not top:
            return []
        # Batch hydrate — one SELECT + one Pydantic parse per hit, instead of
        # the N+1 per-row get() this used to do (k*3=60 SELECTs per /search
        # via HybridRetriever's candidate pool).
        courses = self._course_repo.get_batch([cid for cid, _ in top])
        return [
            SearchHit(course=courses[cid], score=score)
            for cid, score in top
            if cid in courses
        ]

    def search_ids(
        self,
        query: str,
        *,
        hard_filters: dict[str, Any] | None = None,
        k: int = 10,
    ) -> list[tuple[str, float]]:
        """ID-only variant of search(): (course_id, score) pairs, no SQLite
        rehydration. HybridRetriever uses this for its vector leg — it only
        needs IDs for RRF fusion and hydrates once on the fused top-k."""
        # Only hit SQLite when filters actually narrow the pool. The old
        # unconditional call fetched all ~6.5k indexed ids on EVERY
        # unfiltered search and then threw the list away — pure waste on
        # the common path.
        if hard_filters:
            candidate_ids = self.filter_ids(hard_filters)
            # Empty candidate set after filter -> no results possible
            if not candidate_ids:
                return []
            candidates: list[str] | None = candidate_ids
        else:
            candidates = None  # "search the whole index" — the cheap path

        query_vec = self._embedder.encode([query])[0]
        return self._index.search(query_vec, k=k, candidate_course_ids=candidates)

    # === Hard filter ===

    def filter_ids(self, filters: dict[str, Any]) -> list[str]:
        """Public access to the SQLite hard-filter step. HybridRetriever uses
        this to scope its BM25 leg to the same allowed set as the vector leg
        (instead of intersecting with the vector top-k, which silently
        dropped BM25-only hits that passed the filter)."""
        return self._sqlite_filter(filters)

    def _sqlite_filter(self, filters: dict[str, Any]) -> list[str]:
        """Apply WHERE on courses table; only return status='indexed' rows."""
        clauses = ["status = ?"]
        params: list[Any] = [ELIGIBLE_STATUS]

        if "term" in filters:
            clauses.append("json_extract(metadata, '$.term') = ?")
            params.append(filters["term"])

        if "credits" in filters:
            clauses.append("json_extract(metadata, '$.credits') = ?")
            params.append(filters["credits"])

        if "delivery_mode" in filters:
            clauses.append("json_extract(metadata, '$.delivery_mode') = ?")
            params.append(filters["delivery_mode"])

        if "professor" in filters:
            # Substring match against the professor JSON array's text dump.
            # Acceptable for MVP; precise array-element match would need
            # json_each in a subquery.
            clauses.append("json_extract(metadata, '$.professor') LIKE ?")
            params.append(f"%{filters['professor']}%")

        if "primary_code_prefix" in filters:
            # Layer 2 (PLAN v3.0+): when the query mentions a program / major
            # prefix (AAI, CS, DS, EECE, INFO, ...), narrow the candidate pool
            # at the SQLite layer BEFORE BM25/vector retrieval. Bilingual NEU
            # students often phrase questions like "我是 AAI 专业 ..." — without
            # this filter the hybrid leg pulls in cross-discipline noise (ALY /
            # ARTG / BINF) that has lexical/semantic similarity but is wrong.
            # Format: "AAI" matches "AAI 5015", "AAI 6640", etc. We append a
            # space so 'CS' doesn't accidentally match 'CSYE'.
            prefix = str(filters["primary_code_prefix"]).upper()
            clauses.append("primary_code LIKE ?")
            params.append(f"{prefix} %")

        sql = f"SELECT course_id FROM courses WHERE {' AND '.join(clauses)}"
        rows = self._conn.execute(sql, params).fetchall()
        return [r["course_id"] for r in rows]


__all__ = ["ELIGIBLE_STATUS", "Retriever", "SearchHit"]
