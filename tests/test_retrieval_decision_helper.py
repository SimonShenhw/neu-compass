"""Shared-decision boundary checks beyond the pre-extraction route characterization."""

from types import SimpleNamespace

import pytest

from api.dependencies import get_hybrid_retriever
from api.routes import chat, common, search
from config import settings
from db.repository import CourseRepository
from rag.retriever import SearchHit
from tests import test_retrieval_decision_parity as parity

# Register the frozen route fixture without copying its setup.
decision_client = parity.decision_client


def decide(state, **overrides):
    kwargs = dict(query="opaque topic", hits=[SearchHit(course=CourseRepository(state.conn).get("c-cs-5800"), score=0.3)],
                  conn=state.conn, hybrid=state.hybrid, reranker=state.reranker,
                  diagnostics={"bm25_top": 7.25, "vec_top": 0.61}, hard_filters=None, rescue_fn=None,
                  pool_size=7, blend_alpha=0.4, reject_threshold=0.05, top_k=2,
                  gate_builder=search.build_gate_fn)
    kwargs.update(overrides)
    return common.rerank_with_gate_and_rescue(**kwargs)


@pytest.mark.parametrize("diagnostics", [None, {"bm25_top": 1.5, "vec_top": 0.2}])
def test_initial_diagnostics_are_explicit_not_read_from_hybrid(decision_client, monkeypatch, diagnostics):
    state = decision_client
    monkeypatch.setattr(settings, "rejection_mode", "calibrated")
    state.gate_rejected = False

    class UnreadableDiagnostics:
        @property
        def last_diagnostics(self):
            raise AssertionError("The decision must not consult mutable retriever state")

    decision = decide(state, hybrid=UnreadableDiagnostics(), diagnostics=diagnostics)
    assert state.gate_features == [{"query": "opaque topic", **(diagnostics or {"bm25_top": 0.0, "vec_top": 0.0})}]
    assert decision.rejected is False and decision.rescued is False


@pytest.mark.parametrize("result", ["none", "empty", "hits"])
def test_decision_retains_initial_meta_and_none_only_rescue_contract(decision_client, monkeypatch, result):
    state = decision_client
    state.reranker.scores = [0.0]
    calls = []
    filters = {"credits": 4}
    hits = [SearchHit(course=CourseRepository(state.conn).get("c-cs-5800"), score=1.0)]
    rescued = None if result == "none" else ([] if result == "empty" else hits)

    def rescue(**kwargs):
        calls.append(kwargs)
        return rescued

    monkeypatch.setattr(common, "attempt_hyde_rescue", rescue)
    rescue_fn = lambda query: "synthetic description"
    decision = decide(state, hard_filters=filters, rescue_fn=rescue_fn)
    assert len(calls) == 1
    assert calls[0] == dict(query="opaque topic", conn=state.conn, hybrid=state.hybrid, reranker=state.reranker,
                           rescue_fn=rescue_fn, hard_filters=filters, pool_size=7, blend_alpha=0.4, top_k=2)
    assert calls[0]["hard_filters"] is filters
    assert decision.meta == {"rejected": True, "reason": "max_reranker_sigmoid 0.000 < threshold 0.05",
                             "max_sigmoid": 0.0, "n_candidates": 1, "n_above_threshold": 0}
    assert decision.rejected is (result == "none")
    assert decision.rescued is (result != "none")
    assert decision.hits == ([] if result == "none" else rescued)
    assert decision.rejection_reason == (decision.meta["reason"] if result == "none" else None)
    assert len(state.reranker.calls) == 1


def test_accepted_decision_keeps_one_pass_metadata(decision_client):
    state = decision_client
    decision = decide(state)
    assert decision.rejected is False and decision.rejection_reason is None and decision.rescued is False
    assert decision.meta == {"rejected": False, "max_sigmoid": 0.3, "n_candidates": 1, "n_above_threshold": 1}
    assert [hit.course.course_id for hit in decision.hits] == ["c-cs-5800"]
    assert decision.hits[0].score == 0.0
    assert len(state.reranker.calls) == 1


def test_chat_empty_path_never_calls_the_shared_decision(decision_client, monkeypatch):
    state = decision_client
    state.hybrid.ids = []

    def forbidden(**kwargs):
        raise AssertionError("The empty shortcut must skip the shared decision")

    monkeypatch.setattr(chat, "rerank_with_gate_and_rescue", forbidden)
    response = state.client.post("/chat", json={"query": "opaque topic"})
    assert response.status_code == 200
    assert '"matched_via": "empty"' in response.text


def test_constants_remain_importable_and_request_diagnostics_remain_isolated(decision_client):
    for name in ("BLEND_ALPHA", "RERANK_POOL_SIZE", "RERANKER_REJECT_THRESHOLD"):
        assert getattr(search, name) == getattr(chat, name) == getattr(common, name)
    state = decision_client
    fake = SimpleNamespace()
    repo = CourseRepository(state.conn)
    first = get_hybrid_retriever(fake, fake, repo)
    second = get_hybrid_retriever(fake, fake, repo)
    assert first is not second
    first.last_diagnostics = {"bm25_top": 99.0}
    assert second.last_diagnostics is None
