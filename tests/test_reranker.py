"""Tests for rag.reranker — pure-Python with a mock cross-encoder.

The real FlagReranker model is ~600MB and needs GPU; tests inject a
hand-rolled scoring function via a CrossEncoderReranker subclass override
so we don't hit the ML stack at all.
"""

from __future__ import annotations

import pytest

from rag.reranker import (
    CrossEncoderReranker,
    rerank_pairs,
    rerank_search_hits,
)
from rag.retriever import SearchHit
from schemas.course import Course


class _StubReranker(CrossEncoderReranker):
    """Override score() to return whatever the test rigged. Avoids loading
    the real FlagReranker model."""

    def __init__(self, score_fn) -> None:  # noqa: ANN001
        super().__init__()
        self._score_fn = score_fn

    def score(self, query: str, candidates: list[str]) -> list[float]:
        return [self._score_fn(query, c) for c in candidates]


def _word_overlap_score(query: str, text: str) -> float:
    """Cheap lexical overlap proxy used in tests when we want a deterministic
    'good vs bad' candidate ordering without standing up a real model."""
    q = set(query.lower().split())
    t = set(text.lower().split())
    return len(q & t) / max(1, len(q))


def _course(*, cid: str, code: str, name: str) -> Course:
    return Course(course_id=cid, primary_code=code, primary_name=name)


# === score() ===


def test_score_empty_returns_empty() -> None:
    r = _StubReranker(_word_overlap_score)
    assert r.score("anything", []) == []


def test_score_returns_one_per_candidate() -> None:
    r = _StubReranker(_word_overlap_score)
    out = r.score("graph algorithms", ["graph theory", "ancient rome"])
    assert len(out) == 2
    assert out[0] > out[1]  # graph overlaps query


# === rerank_pairs ===


def test_rerank_pairs_sorts_desc() -> None:
    r = _StubReranker(_word_overlap_score)
    pairs = [
        ("low", "ancient rome"),
        ("high", "graph algorithms BFS DFS"),
        ("mid", "graph"),
    ]
    out = rerank_pairs("graph algorithms", pairs, r)
    payloads = [p for p, _ in out]
    assert payloads == ["high", "mid", "low"]


def test_rerank_pairs_top_k_truncates() -> None:
    r = _StubReranker(_word_overlap_score)
    pairs = [
        ("a", "graph"),
        ("b", "graph algorithms"),
        ("c", "graph algorithms BFS"),
    ]
    out = rerank_pairs("graph algorithms BFS", pairs, r, top_k=2)
    assert len(out) == 2
    assert out[0][0] == "c"


def test_rerank_pairs_empty_input() -> None:
    r = _StubReranker(_word_overlap_score)
    assert rerank_pairs("q", [], r) == []


# === rerank_search_hits ===


def test_rerank_search_hits_uses_fetch_text() -> None:
    r = _StubReranker(_word_overlap_score)
    hits = [
        SearchHit(
            course=_course(cid="c-algo", code="CS 5800", name="Algorithms"),
            score=0.5,
        ),
        SearchHit(
            course=_course(cid="c-rome", code="HIST 2390", name="Roman History"),
            score=0.6,  # initially ranked higher
        ),
    ]
    raw_texts = {
        "c-algo": "graph algorithms BFS DFS shortest paths",
        "c-rome": "ancient roman empire history",
    }
    out = rerank_search_hits(
        "graph algorithms",
        hits,
        r,
        fetch_text=lambda cid: raw_texts.get(cid),
    )
    assert len(out) == 2
    # Reranker should put algo first based on text overlap, even though
    # the upstream score had rome higher.
    assert out[0].course.course_id == "c-algo"
    assert out[0].score > out[1].score


def test_rerank_search_hits_falls_back_to_primary_name() -> None:
    r = _StubReranker(_word_overlap_score)
    hits = [
        SearchHit(
            course=_course(cid="c-algo", code="CS 5800", name="Algorithms"),
            score=0.5,
        ),
    ]
    out = rerank_search_hits(
        "Algorithms",
        hits,
        r,
        fetch_text=lambda cid: None,  # no raw_text available
    )
    # Score should be > 0 because primary_name 'Algorithms' overlaps query
    assert out[0].score > 0


def test_rerank_search_hits_empty() -> None:
    r = _StubReranker(_word_overlap_score)
    assert rerank_search_hits("q", [], r, fetch_text=lambda cid: "") == []


def test_rerank_search_hits_score_replaces_input_score() -> None:
    """Reranker output's .score is the cross-encoder score, NOT the upstream RRF."""
    r = _StubReranker(_word_overlap_score)
    hits = [
        SearchHit(
            course=_course(cid="c-algo", code="CS 5800", name="Algorithms"),
            score=0.0123456789,  # arbitrary upstream score
        ),
    ]
    out = rerank_search_hits(
        "Algorithms",
        hits,
        r,
        fetch_text=lambda cid: "Algorithms graph algorithms",
    )
    assert out[0].score != pytest.approx(0.0123456789)


def test_rerank_search_hits_top_k() -> None:
    r = _StubReranker(_word_overlap_score)
    hits = [
        SearchHit(course=_course(cid=f"c{i}", code=f"CS {1000+i}", name="X"), score=0)
        for i in range(5)
    ]
    out = rerank_search_hits(
        "x", hits, r, fetch_text=lambda cid: "x", top_k=2,
    )
    assert len(out) == 2
