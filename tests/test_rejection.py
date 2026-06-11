"""Tests for rag.rejection — calibrated rejection gate (ADR-0018)."""

from __future__ import annotations

from rag.rejection import (
    CalibratedRejectionGate,
    RejectionFeatures,
    build_gate_fn,
    query_has_code_pattern,
)
from rag.reranker import rerank_blend_with_rejection
from rag.retriever import SearchHit
from schemas.course import Course


def _features(**overrides) -> RejectionFeatures:
    base = {
        "max_sigmoid": 0.5,
        "bm25_top": 5.0,
        "vec_top": 0.6,
        "code_pattern_miss": False,
    }
    base.update(overrides)
    return RejectionFeatures(**base)


# === query_has_code_pattern ===


def test_code_pattern_matches_standard_codes() -> None:
    assert query_has_code_pattern("CS 5800")
    assert query_has_code_pattern("cs5800 syllabus")
    assert query_has_code_pattern("is CSYE 12345 offered")


def test_code_pattern_ignores_plain_text_and_years() -> None:
    assert not query_has_code_pattern("graph algorithms BFS DFS")
    # bare 4-digit years have no letter prefix attached
    assert not query_has_code_pattern("best courses for fall 2025")


def test_code_pattern_cjk_does_not_extend_word_boundary() -> None:
    # ASCII flag: CJK chars must not block the match (same fix family as
    # query_normalizer's '那aai' case)
    assert query_has_code_pattern("请问AAI 9999这门课怎么样")


# === CalibratedRejectionGate.probability — directional sanity ===


def test_probability_increases_with_max_sigmoid() -> None:
    g = CalibratedRejectionGate()
    lo = g.probability(_features(max_sigmoid=0.001))
    hi = g.probability(_features(max_sigmoid=0.9))
    assert hi > lo


def test_probability_increases_with_bm25_evidence() -> None:
    g = CalibratedRejectionGate()
    lo = g.probability(_features(bm25_top=0.0))
    hi = g.probability(_features(bm25_top=20.0))
    assert hi > lo


def test_probability_increases_with_vector_similarity() -> None:
    g = CalibratedRejectionGate()
    lo = g.probability(_features(vec_top=0.2))
    hi = g.probability(_features(vec_top=0.9))
    assert hi > lo


def test_code_pattern_miss_lowers_probability() -> None:
    g = CalibratedRejectionGate()
    without = g.probability(_features(code_pattern_miss=False))
    with_miss = g.probability(_features(code_pattern_miss=True))
    assert with_miss < without


def test_probability_bounded() -> None:
    g = CalibratedRejectionGate()
    for f in (
        _features(max_sigmoid=0.0, bm25_top=0.0, vec_top=0.0,
                  code_pattern_miss=True),
        _features(max_sigmoid=1.0, bm25_top=100.0, vec_top=1.0),
    ):
        p = g.probability(f)
        assert 0.0 < p < 1.0


# === decide ===


def test_decide_reject_below_threshold_with_reason() -> None:
    g = CalibratedRejectionGate(reject_below=0.99)  # force rejection
    reject, p, reason = g.decide(_features())
    assert reject is True
    assert 0.0 < p < 0.99
    assert "calibrated_gate" in reason
    assert "p_answerable" in reason


def test_decide_accept_above_threshold() -> None:
    g = CalibratedRejectionGate(reject_below=0.0001)  # force acceptance
    reject, p, _ = g.decide(_features())
    assert reject is False
    assert p > 0.0001


# === build_gate_fn + rerank_blend_with_rejection integration ===


class _FakeReranker:
    """Returns a fixed sigmoid per candidate (order-preserving)."""

    def __init__(self, scores: list[float]) -> None:
        self._scores = scores

    def score(self, query: str, candidates: list[str]) -> list[float]:
        return self._scores[: len(candidates)]


def _hits(n: int) -> list[SearchHit]:
    return [
        SearchHit(
            course=Course(
                course_id=f"c-{i}", primary_code=f"CS 580{i}",
                primary_name=f"Course {i}",
            ),
            score=1.0 / (i + 1),
        )
        for i in range(n)
    ]


def test_gate_fn_overrides_threshold_gate() -> None:
    """With gate_fn provided, the threshold parameter must be ignored:
    sigmoids are all ABOVE the 0.05 threshold, yet the custom gate
    rejects — gate_fn wins."""
    out, meta = rerank_blend_with_rejection(
        "q", _hits(3), _FakeReranker([0.9, 0.8, 0.7]),
        fetch_text=lambda cid: "text",
        blend_alpha=0.4,
        reject_threshold=0.05,
        top_k=3,
        gate_fn=lambda sigmoids: (True, "custom gate says no"),
    )
    assert out == []
    assert meta["rejected"] is True
    assert meta["reason"] == "custom gate says no"


def test_gate_fn_accept_path_still_blends() -> None:
    out, meta = rerank_blend_with_rejection(
        "q", _hits(3), _FakeReranker([0.001, 0.002, 0.003]),  # below 0.05!
        fetch_text=lambda cid: "text",
        blend_alpha=0.4,
        reject_threshold=0.05,
        top_k=2,
        gate_fn=lambda sigmoids: (False, "accepted"),
    )
    assert meta["rejected"] is False
    assert len(out) == 2  # top_k truncation still applies


def test_no_gate_fn_keeps_adr_0016_threshold_behavior() -> None:
    out, meta = rerank_blend_with_rejection(
        "q", _hits(2), _FakeReranker([0.01, 0.02]),
        fetch_text=lambda cid: "text",
        blend_alpha=0.4,
        reject_threshold=0.05,
        top_k=2,
    )
    assert meta["rejected"] is True
    assert "max_reranker_sigmoid" in str(meta["reason"])


def test_build_gate_fn_uses_leg_evidence() -> None:
    """Same low sigmoid: strong BM25+vector evidence accepts, zero
    evidence + code-pattern miss rejects — the exact q018-vs-q040 split
    the scalar threshold cannot make."""
    strong = build_gate_fn(
        query="VC dimension PAC learning theory", bm25_top=18.0, vec_top=0.72,
    )
    weak = build_gate_fn(query="CS 0001", bm25_top=0.4, vec_top=0.35)

    low_sigmoids = [0.01, 0.005, 0.002]
    strong_reject, strong_reason = strong(low_sigmoids)
    weak_reject, _ = weak(low_sigmoids)

    assert strong_reject is False
    assert weak_reject is True
    assert "calibrated_gate" in strong_reason
