"""BM25 + vector hybrid retrieval via Reciprocal Rank Fusion (RRF).

Why hybrid: Week 4 smoke test (docs/rag_smoke_results.md §6) showed
adversarial query "quantum cryptography" got vector score 0.485,
HIGHER than legitimate match "graph algorithms" at 0.463. Absolute
score thresholds don't work — bge-m3 compresses STEM-text similarities
into a narrow 0.4-0.7 band.

BM25 contributes lexical matching (exact term hits) which the vector
embedder under-weights. RRF combines the two rankings without needing
to normalize their score scales:

    rrf_score(item) = sum over rankings of  1 / (k + rank_in_ranking)

with default k=60 (standard RRF parameter from Cormack et al. 2009).
This makes top-1 in each list contribute the most, with diminishing
returns. Robust to scale differences.

Tokenization: ASCII-only (whitespace + lowercase + alnum). Chinese
queries will still get hit on co-occurring English terms (course codes,
prof names) but pure-Chinese BM25 needs jieba-style segmentation —
deferred to v2.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Protocol

import numpy as np
from rank_bm25 import BM25Okapi

from db.repository import CourseRepository
from rag.retriever import ELIGIBLE_STATUS, SearchHit

DEFAULT_RRF_K = 60

# ASCII alnum tokens (lowercased). Chinese chars get filtered out — see module
# docstring; pure-Chinese BM25 is a v2 problem.
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Default tokenizer for the BM25 layer."""
    return _TOKEN_RE.findall(text.lower())


class _RetrieverLike(Protocol):
    """The vector retriever interface we depend on (Retriever or fake)."""

    def search(
        self,
        query: str,
        *,
        hard_filters: dict[str, Any] | None = ...,
        k: int = ...,
    ) -> list[SearchHit]: ...


class BM25Corpus:
    """In-memory BM25 index over courses.raw_text. Rebuilt on every restart
    (cheap: tokenize + score for ≤ 1000 docs is ~10ms).

    Construct via BM25Corpus.from_db(conn) for the standard path. The
    constructor takes a {course_id: raw_text} dict for tests.
    """

    def __init__(self, course_texts: dict[str, str]) -> None:
        self._course_ids: list[str] = list(course_texts.keys())
        self._vocab: set[str] = set()
        if not self._course_ids:
            self._bm25: BM25Okapi | None = None
            return

        tokenized = [tokenize(course_texts[cid]) for cid in self._course_ids]
        # Replace any all-empty tokenization with a single sentinel so BM25Okapi
        # doesn't crash on empty docs (e.g. raw_text=null edge case).
        tokenized = [toks if toks else ["__empty__"] for toks in tokenized]
        self._bm25 = BM25Okapi(tokenized)
        for toks in tokenized:
            self._vocab.update(toks)

    @classmethod
    def from_db(
        cls,
        conn: sqlite3.Connection,
        *,
        status_filter: str | None = ELIGIBLE_STATUS,
    ) -> BM25Corpus:
        """Build a BM25 corpus from courses.raw_text.

        Default status_filter='indexed' matches what the retriever returns —
        BM25 + vector see the same eligible row set, otherwise rankings
        could diverge.
        """
        sql = "SELECT course_id, COALESCE(raw_text, '') AS raw_text FROM courses"
        params: list[Any] = []
        if status_filter is not None:
            sql += " WHERE status = ?"
            params.append(status_filter)
        rows = conn.execute(sql, params).fetchall()
        return cls({r["course_id"]: r["raw_text"] for r in rows})

    def search(
        self,
        query: str,
        *,
        k: int = 10,
    ) -> list[tuple[str, float]]:
        """Top-k BM25 hits as [(course_id, score), ...] sorted desc.

        Returns [] if NO query token appears in the corpus vocab. This is
        a stronger "no match" signal than score==0, which can also occur
        for tiny corpora where BM25 IDF degenerates (N=2, n=1 → log(1)=0).
        """
        if self._bm25 is None or not self._course_ids:
            return []

        tokens = tokenize(query)
        if not tokens:
            return []

        # Vocab-overlap check: distinguishes "no match possible" from
        # "match exists but BM25 IDF happens to score it zero".
        if not any(t in self._vocab for t in tokens):
            return []

        scores = self._bm25.get_scores(tokens)
        sorted_idx = np.argsort(-scores)[: k]
        return [
            (self._course_ids[i], float(scores[i]))
            for i in sorted_idx
        ]

    @property
    def count(self) -> int:
        return len(self._course_ids)


def reciprocal_rank_fusion(
    rankings: list[list[str]],
    *,
    k: int = DEFAULT_RRF_K,
) -> dict[str, float]:
    """Combine N ranked id-lists via RRF. `k` damps the contribution of
    low-rank items; default 60 is from the original RRF paper."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, item_id in enumerate(ranking, start=1):
            fused[item_id] = fused.get(item_id, 0.0) + 1.0 / (k + rank)
    return fused


class HybridRetriever:
    """RRF combination of vector + BM25 retrieval.

    Mirrors Retriever.search interface (returns list[SearchHit]) so it's a
    drop-in replacement. hard_filters apply to both legs:
      - vector leg: pushed through to underlying retriever's SQLite filter
      - BM25 leg: post-filter via intersection with vector candidate set
        (BM25 doesn't know about SQLite metadata; vector retriever already
         applied the filter, so reusing its candidate set is the cheap path)
    """

    def __init__(
        self,
        *,
        vector_retriever: _RetrieverLike,
        bm25_corpus: BM25Corpus,
        course_repo: CourseRepository,
        rrf_k: int = DEFAULT_RRF_K,
        candidate_multiplier: int = 3,
    ) -> None:
        self._vector = vector_retriever
        self._bm25 = bm25_corpus
        self._course_repo = course_repo
        self._rrf_k = rrf_k
        self._candidate_multiplier = candidate_multiplier

    def search(
        self,
        query: str,
        *,
        hard_filters: dict[str, Any] | None = None,
        k: int = 10,
    ) -> list[SearchHit]:
        candidate_k = k * self._candidate_multiplier

        # Leg 1: vector
        vec_hits = self._vector.search(
            query, hard_filters=hard_filters, k=candidate_k,
        )
        vec_ids = [h.course.course_id for h in vec_hits]

        # Leg 2: BM25
        bm25_hits = self._bm25.search(query, k=candidate_k)
        bm25_ids = [cid for cid, _ in bm25_hits]

        # Filter BM25 if hard_filters narrowed vec_hits.
        # Logic: vec_hits already has the filter applied. If hard_filters
        # is set, BM25 candidates must come from the same allowed set,
        # otherwise BM25 could surface filtered-out courses.
        if hard_filters:
            allowed = set(vec_ids)
            bm25_ids = [cid for cid in bm25_ids if cid in allowed]

        if not vec_ids and not bm25_ids:
            return []

        fused = reciprocal_rank_fusion(
            [vec_ids, bm25_ids],
            k=self._rrf_k,
        )

        top_k = sorted(fused, key=lambda c: -fused[c])[:k]
        return [
            SearchHit(course=self._course_repo.get(cid), score=fused[cid])
            for cid in top_k
        ]


__all__ = [
    "DEFAULT_RRF_K",
    "BM25Corpus",
    "HybridRetriever",
    "reciprocal_rank_fusion",
    "tokenize",
]
