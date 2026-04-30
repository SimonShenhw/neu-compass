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
        candidate_ids = self._sqlite_filter(hard_filters or {})

        # Empty candidate set after filter -> no results possible
        if hard_filters and not candidate_ids:
            return []

        query_vec = self._embedder.encode([query])[0]

        # Pass candidate_ids only when filters narrowed something. None means
        # "search the whole index" which is the default (and cheaper) path.
        candidates = candidate_ids if hard_filters else None

        top = self._index.search(query_vec, k=k, candidate_course_ids=candidates)
        return [
            SearchHit(course=self._course_repo.get(cid), score=score)
            for cid, score in top
        ]

    # === Hard filter ===

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

        sql = f"SELECT course_id FROM courses WHERE {' AND '.join(clauses)}"
        rows = self._conn.execute(sql, params).fetchall()
        return [r["course_id"] for r in rows]


__all__ = ["ELIGIBLE_STATUS", "Retriever", "SearchHit"]
