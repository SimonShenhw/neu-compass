"""Tests for rag.reranker — pure-Python with a mock cross-encoder.

The real FlagReranker model is ~600MB and needs GPU; tests inject a
hand-rolled scoring function via a CrossEncoderReranker subclass override
so we don't hit the ML stack at all.
"""

from __future__ import annotations

import pytest

from rag.reranker import (
    CrossEncoderReranker,
    rerank_blend_hits,
    rerank_blend_with_rejection,
    rerank_pairs,
    rerank_search_hits,
    zscore_blend,
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


# === zscore_blend ===


def test_zscore_blend_empty_returns_empty() -> None:
    assert zscore_blend([], [], 0.5) == []


def test_zscore_blend_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        zscore_blend([0.1, 0.2], [0.5], 0.5)


def test_zscore_blend_alpha_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="alpha must be in"):
        zscore_blend([0.1, 0.2], [0.5, 0.6], -0.1)
    with pytest.raises(ValueError, match="alpha must be in"):
        zscore_blend([0.1, 0.2], [0.5, 0.6], 1.5)


def test_zscore_blend_alpha_one_preserves_rrf_order() -> None:
    """α=1.0 → blended order matches RRF order, ignoring reranker."""
    rrf = [0.10, 0.05, 0.20]  # ranking: idx2 > idx0 > idx1
    rer = [0.99, 0.99, 0.01]  # reranker would prefer 0,1 over 2
    blended = zscore_blend(rrf, rer, alpha=1.0)
    # idx2 has highest RRF → highest blended
    assert blended[2] > blended[0] > blended[1]


def test_zscore_blend_alpha_zero_preserves_rerank_order() -> None:
    """α=0.0 → blended order matches reranker order, ignoring RRF."""
    rrf = [0.99, 0.99, 0.01]  # RRF would prefer 0,1 over 2
    rer = [0.10, 0.05, 0.20]  # reranker: idx2 > idx0 > idx1
    blended = zscore_blend(rrf, rer, alpha=0.0)
    assert blended[2] > blended[0] > blended[1]


def test_zscore_blend_alpha_half_centers_on_zero() -> None:
    """Z-score normalization → mean of blended values is ~0."""
    rrf = [0.1, 0.2, 0.3, 0.4]
    rer = [0.4, 0.3, 0.2, 0.1]
    blended = zscore_blend(rrf, rer, alpha=0.5)
    assert abs(sum(blended) / len(blended)) < 1e-9


def test_zscore_blend_zero_variance_leg_neutralized() -> None:
    """All-equal RRF leg has std=0 → contributes 0 to the blend; reranker
    leg drives ordering even with α=1.0 weight on RRF... wait. With α=1.0
    and RRF z=0 everywhere, blended is all zero → no ordering signal.
    With α=0.5, only the reranker's standardized variation shows through."""
    rrf = [0.5, 0.5, 0.5]   # zero variance → z = [0, 0, 0]
    rer = [0.1, 0.5, 0.9]   # nontrivial variance
    blended = zscore_blend(rrf, rer, alpha=0.5)
    # Reranker order preserved because its z is the only nonzero contribution
    assert blended[2] > blended[1] > blended[0]


def test_zscore_blend_both_zero_variance_returns_zeros() -> None:
    rrf = [0.5, 0.5, 0.5]
    rer = [0.1, 0.1, 0.1]
    blended = zscore_blend(rrf, rer, alpha=0.5)
    assert blended == [0.0, 0.0, 0.0]


def test_zscore_blend_single_item() -> None:
    """Single-item pool: std=0 on both legs → blended is 0."""
    blended = zscore_blend([0.5], [0.7], alpha=0.5)
    assert blended == [0.0]


# === rerank_blend_hits ===


def _hit(cid: str, score: float) -> SearchHit:
    """Build a SearchHit with a syntactically valid code; course_id carries identity."""
    return SearchHit(
        course=_course(cid=cid, code="CS 5800", name=cid),
        score=score,
    )


def test_rerank_blend_hits_alpha_zero_matches_reranker_ordering() -> None:
    """α=0.0 → ordering driven entirely by reranker score."""
    r = _StubReranker(_word_overlap_score)
    # RRF would put 'rome' first (higher upstream score), but reranker should
    # put 'algo' first based on text overlap with the query.
    hits = [
        _hit("c-rome", 0.9),
        _hit("c-algo", 0.1),
    ]
    raw_texts = {
        "c-algo": "graph algorithms BFS DFS",
        "c-rome": "ancient roman empire",
    }
    out = rerank_blend_hits(
        "graph algorithms",
        hits,
        r,
        fetch_text=lambda cid: raw_texts.get(cid),
        blend_alpha=0.0,
    )
    assert out[0].course.course_id == "c-algo"


def test_rerank_blend_hits_alpha_one_matches_rrf_ordering() -> None:
    """α=1.0 → ordering driven by upstream RRF score, reranker ignored."""
    r = _StubReranker(_word_overlap_score)
    # Reranker would put 'algo' first, but RRF gives 'rome' a much higher score.
    hits = [
        _hit("c-rome", 0.9),
        _hit("c-algo", 0.1),
    ]
    raw_texts = {
        "c-algo": "graph algorithms BFS DFS",
        "c-rome": "ancient roman empire",
    }
    out = rerank_blend_hits(
        "graph algorithms",
        hits,
        r,
        fetch_text=lambda cid: raw_texts.get(cid),
        blend_alpha=1.0,
    )
    assert out[0].course.course_id == "c-rome"


def test_rerank_blend_hits_top_k_truncates() -> None:
    r = _StubReranker(_word_overlap_score)
    hits = [_hit(f"c{i}", 0.1 * i) for i in range(5)]
    out = rerank_blend_hits(
        "x", hits, r,
        fetch_text=lambda cid: "x",
        blend_alpha=0.5, top_k=2,
    )
    assert len(out) == 2


def test_rerank_blend_hits_empty_returns_empty() -> None:
    r = _StubReranker(_word_overlap_score)
    out = rerank_blend_hits(
        "q", [], r, fetch_text=lambda cid: "", blend_alpha=0.5,
    )
    assert out == []


def test_rerank_blend_hits_score_is_blended_zscore_not_raw() -> None:
    """Returned .score is the blended Z-score, not the input RRF or raw sigmoid."""
    r = _StubReranker(_word_overlap_score)
    hits = [
        _hit("c-a", 0.5),
        _hit("c-b", 0.3),
    ]
    out = rerank_blend_hits(
        "x", hits, r,
        fetch_text=lambda cid: "x x x" if cid == "c-a" else "y",
        blend_alpha=0.5,
    )
    # Blended Z-scores sum to ~0 (centered) and are not in the input range.
    assert abs(sum(h.score for h in out)) < 1e-9
    assert all(-3 < h.score < 3 for h in out)


# === rerank_blend_with_rejection ===


def test_rerank_blend_with_rejection_empty_hits_returns_no_candidates() -> None:
    r = _StubReranker(_word_overlap_score)
    out, meta = rerank_blend_with_rejection(
        "q", [], r,
        fetch_text=lambda cid: None,
        blend_alpha=0.4, reject_threshold=0.4,
    )
    assert out == []
    assert meta["rejected"] is False
    assert meta["reason"] == "no_candidates"
    assert meta["n_candidates"] == 0


def test_rerank_blend_with_rejection_rejects_below_threshold() -> None:
    """All candidates score 0 → max sigmoid 0 < 0.4 → rejected."""
    r = _StubReranker(_word_overlap_score)
    hits = [_hit("c-rome", 0.5), _hit("c-greece", 0.3)]
    out, meta = rerank_blend_with_rejection(
        "graph algorithms BFS", hits, r,
        fetch_text=lambda cid: "ancient roman empire" if cid == "c-rome"
                               else "classical athens",
        blend_alpha=0.4, reject_threshold=0.4,
    )
    assert out == []
    assert meta["rejected"] is True
    assert "max_reranker_sigmoid" in meta["reason"]
    assert meta["max_sigmoid"] == 0.0
    assert meta["n_candidates"] == 2


def test_rerank_blend_with_rejection_accepts_when_one_candidate_passes() -> None:
    """Even one candidate above threshold should pass the gate."""
    r = _StubReranker(_word_overlap_score)
    hits = [_hit("c-algo", 0.5), _hit("c-rome", 0.3)]
    raw_texts = {
        "c-algo": "graph algorithms BFS DFS",
        "c-rome": "ancient roman empire",
    }
    out, meta = rerank_blend_with_rejection(
        "graph algorithms", hits, r,
        fetch_text=lambda cid: raw_texts.get(cid),
        blend_alpha=0.4, reject_threshold=0.4,
    )
    assert meta["rejected"] is False
    assert meta["max_sigmoid"] == 1.0  # full overlap
    assert meta["n_above_threshold"] == 1
    assert len(out) == 2
    assert out[0].course.course_id == "c-algo"  # blended ranks algo first


def test_rerank_blend_with_rejection_top_k_truncates_after_blend() -> None:
    r = _StubReranker(_word_overlap_score)
    hits = [_hit(f"c{i}", 0.1 * i) for i in range(5)]
    out, meta = rerank_blend_with_rejection(
        "x", hits, r,
        fetch_text=lambda cid: "x",  # all candidates score 1.0
        blend_alpha=0.5, reject_threshold=0.4, top_k=2,
    )
    assert meta["rejected"] is False
    assert len(out) == 2


def test_rerank_blend_with_rejection_meta_n_above_threshold() -> None:
    r = _StubReranker(_word_overlap_score)
    hits = [_hit("c-good", 0.5), _hit("c-bad", 0.5)]
    raw_texts = {
        "c-good": "graph algorithms",  # score 1.0
        "c-bad": "ancient empire",     # score 0
    }
    out, meta = rerank_blend_with_rejection(
        "graph algorithms", hits, r,
        fetch_text=lambda cid: raw_texts.get(cid),
        blend_alpha=0.4, reject_threshold=0.4,
    )
    assert meta["rejected"] is False
    assert meta["n_above_threshold"] == 1
    assert meta["n_candidates"] == 2


def test_rerank_blend_with_rejection_uses_raw_sigmoid_not_blended() -> None:
    """Rejection decision must use raw sigmoid max, not the blended Z-score.
    A pool whose blended scores are all ~0 (after centering) should still
    pass the gate if the raw sigmoid was high."""
    r = _StubReranker(_word_overlap_score)
    # Two identical-text candidates → both raw sigmoid = 1.0, but Z-score
    # of equal values is 0 (zero variance leg neutralized).
    hits = [_hit("c-a", 0.5), _hit("c-b", 0.5)]
    out, meta = rerank_blend_with_rejection(
        "graph algorithms", hits, r,
        fetch_text=lambda cid: "graph algorithms",  # same for both
        blend_alpha=0.4, reject_threshold=0.4,
    )
    # Blended z-scores would be all 0 here, but rejection should NOT trigger
    # because raw max sigmoid is 1.0.
    assert meta["rejected"] is False
    assert meta["max_sigmoid"] == 1.0
