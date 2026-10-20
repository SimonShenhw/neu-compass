"""Rescue rules, log fields and latency the shared retrieval decision owns for both routes.

Reuses the frozen parity fixture (synthetic dependencies only); the parity file itself stays unchanged.
"""

from __future__ import annotations

import json
import time

import pytest
from structlog.testing import capture_logs

from api.dependencies import get_hybrid_retriever
from api.query_fields import query_fields
from api.routes import chat, search
from config import settings
from tests import test_retrieval_decision_parity as parity

decision_client = parity.decision_client


def _post(state, route, payload):
    with capture_logs() as logs:
        response = state.client.post(route, json=payload)
    assert response.status_code == 200, response.text
    body = json.loads(response.text.splitlines()[0]) if route == "/chat" else response.json()
    rows = [dict(row) for row in state.conn.execute("SELECT * FROM query_log").fetchall()]
    return body, rows, logs


@pytest.fixture
def fake_clock(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(time, "perf_counter", lambda: clock["t"])
    return clock


@pytest.mark.parametrize("route", ["/search", "/chat"])
@pytest.mark.parametrize("mode", ["threshold", "calibrated"])
def test_no_rescue_attempt_without_rescue_fn(decision_client, monkeypatch, route, mode):
    """With HyDE off (the default) a rejection never enters attempt_hyde_rescue."""
    state = decision_client
    monkeypatch.setattr(settings, "rejection_mode", mode)
    state.reranker.scores = [0.0] * 3
    body, _, logs = _post(state, route, {"query": "opaque topic", "k": 1})
    assert body["matched_via"] == "rejected"
    assert [entry["event"] for entry in logs if entry["event"].startswith("rescue.")] == []


@pytest.mark.parametrize("route", ["/search", "/chat"])
@pytest.mark.parametrize(("min_p", "rescued"), [(0.5, False), (0.3, True)])
def test_rescue_threshold_is_read_from_settings(decision_client, monkeypatch, route, min_p, rescued):
    """The borderline cut-off follows settings.rescue_min_probability, not a fixed number."""
    state = decision_client
    monkeypatch.setattr(settings, "rejection_mode", "calibrated")
    monkeypatch.setattr(settings, "rescue_min_probability", min_p)
    state.gate_p = 0.3
    state.enable_rescue()
    _post(state, route, {"query": "opaque topic", "k": 1})
    assert state.rescue_calls == (["opaque topic"] if rescued else [])


@pytest.mark.parametrize("route", ["/search", "/chat"])
def test_rescue_with_k_above_pool_keeps_k_order_and_scores(decision_client, monkeypatch, route):
    """A rescue with k > RERANK_POOL_SIZE retrieves k candidates and returns the second pass's full order."""
    state = decision_client
    for module in (search, chat):
        monkeypatch.setattr(module, "RERANK_POOL_SIZE", 2)
    state.enable_rescue()
    passes = iter([[0.0, 0.0, 0.0], [0.2, 0.7, 0.4]])

    def score(query, candidates):
        state.reranker.calls.append((query, list(candidates)))
        return next(passes)[: len(candidates)]

    state.reranker.score = score
    body, rows, _ = _post(state, route, {"query": "opaque topic", "k": 3})
    assert [call[2] for call in state.hybrid.calls] == [3, 3]
    assert [hit["course_id"] for hit in body["results"]] == ["c-ds-5220", "c-cs-5800", "c-aai-6600"]
    assert [round(hit["score"], 6) for hit in body["results"]] == [0.778663, -0.191432, -0.587231]
    assert json.loads(rows[0]["result_course_ids"]) == ["c-ds-5220", "c-cs-5800", "c-aai-6600"]


@pytest.mark.parametrize("route", ["/search", "/chat"])
def test_rejection_log_fields_and_latency(decision_client, fake_clock, route):
    """search.rejected keeps its fields and latency; chat's retrieval_ms is taken before the rerank."""
    state = decision_client
    state.reranker.scores = [0.0] * 3
    plain = state.reranker.score

    def slow(query, candidates):
        fake_clock["t"] += 1.0  # the rerank "takes" one second
        return plain(query, candidates)

    state.reranker.score = slow
    body, rows, logs = _post(state, route, {"query": "CS opaque topic", "k": 1})
    assert body["matched_via"] == "rejected"
    if route == "/search":
        [entry] = [entry for entry in logs if entry["event"] == "search.rejected"]
        assert entry == {"event": "search.rejected", "log_level": "info", **query_fields("CS opaque topic"),
                         "max_sigmoid": 0.0, "n_candidates": 1, "duration_ms": 1000.0}
        assert body["latency_ms"] == 1000.0 and rows[0]["latency_ms"] == 1000.0
    else:
        assert body["retrieval_ms"] == 0.0 and rows[0]["latency_ms"] == 0.0


@pytest.mark.parametrize("route", ["/search", "/chat"])
def test_hyde_rescued_event_fields(decision_client, route):
    """The hyde_rescued event carries the question's hash and length (not its text) and the number of results."""
    state = decision_client
    state.reranker.scores = [0.0] * 3
    state.enable_rescue()
    body, _, logs = _post(state, route, {"query": "opaque topic", "k": 1})
    event = f"{route[1:]}.hyde_rescued"
    [entry] = [entry for entry in logs if entry["event"] == event]
    assert entry == {"event": event, "log_level": "info", **query_fields("opaque topic"),
                     "count": len(body["results"])}
    assert len(body["results"]) == 1


class _NoDiagnosticsSpy(parity.HybridSpy):
    """A retriever that never exposes last_diagnostics (HybridRetriever always sets it)."""

    def __init__(self, conn):
        super().__init__(conn)
        del self.last_diagnostics

    def search(self, query, *, hard_filters=None, k=10):
        hits = super().search(query, hard_filters=hard_filters, k=k)
        del self.last_diagnostics
        return hits


@pytest.mark.parametrize("route", ["/search", "/chat"])
@pytest.mark.parametrize("scores", [[0.3, 0.9, 0.6], [0.0, 0.0, 0.0]])
def test_threshold_mode_does_not_need_retriever_diagnostics(decision_client, route, scores):
    """As before the extraction, the threshold gate never reads last_diagnostics."""
    state = decision_client
    spy = _NoDiagnosticsSpy(state.conn)
    state.client.app.dependency_overrides[get_hybrid_retriever] = lambda: spy
    state.reranker.scores = scores
    body, _, _ = _post(state, route, {"query": "opaque topic", "k": 1})
    assert body["matched_via"] == ("rejected" if max(scores) == 0.0 else "hybrid")
