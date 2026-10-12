"""SIM-02 route characterization, frozen before extraction; synthetic dependencies only."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from structlog.testing import capture_logs

from api.dependencies import get_chat_stream_fn, get_db_conn, get_hybrid_retriever, get_hyde_rescue_fn, get_reranker
from api.routes import chat, search
from config import settings
from db.program_repository import ProgramRepository
from db.repository import CourseRepository
from rag.filters import filter_course_ids
from rag.hybrid import HybridRetriever
from rag.retriever import Retriever, SearchHit
from schemas.course import Course
from schemas.program import Program, ProgramRequiredCourse
from tests.conftest import FixtureReranker

IDS = ["c-cs-5800", "c-ds-5220", "c-aai-6600"]
RAW = ["graph algorithms BFS DFS shortest paths NP completeness",
       "neural network training backpropagation gradient descent",
       "AI fundamentals search reasoning planning"]
REASON = "max_reranker_sigmoid 0.000 < threshold 0.05"
EXPANSION = "synthetic hypothetical course description"


class HybridSpy:
    def __init__(self, conn):
        self.conn = conn
        self.ids = list(IDS)
        self.calls = []
        self.last_diagnostics = None
        self.diagnostics = {"bm25_top": 7.25, "vec_top": 0.61}
        self.empty_retry = False

    def search(self, query, *, hard_filters=None, k=10):
        self.calls.append((query, dict(hard_filters or {}), k))
        self.last_diagnostics = self.diagnostics if len(self.calls) == 1 else {"bm25_top": 99.0, "vec_top": 0.99}
        if self.empty_retry and len(self.calls) > 1:
            return []
        allowed = set(filter_course_ids(self.conn, hard_filters or {}, candidate_course_ids=self.ids))
        repo = CourseRepository(self.conn)
        return [SearchHit(course=repo.get(cid), score=0.3 - index * 0.1)
                for index, cid in enumerate(self.ids) if cid in allowed][:k]


class RerankerSpy:
    def __init__(self):
        self.calls = []
        self.scores = [0.3, 0.9, 0.6]

    def score(self, query, candidates):
        self.calls.append((query, list(candidates)))
        return self.scores[:len(candidates)]


@pytest.fixture
def decision_client(api_client, monkeypatch):
    conn = api_client.app.dependency_overrides[get_db_conn]()
    hybrid, reranker = HybridSpy(conn), RerankerSpy()
    state = SimpleNamespace(client=api_client, conn=conn, hybrid=hybrid, reranker=reranker,
                            rescue_calls=[], rescue_mode="expand", gate_features=[], gate_scores=[],
                            gate_rejected=True, gate_p=0.25, prompts=[])

    def rescue(query):
        state.rescue_calls.append(query)
        if state.rescue_mode == "error":
            raise RuntimeError("synthetic rescue error")
        return None if state.rescue_mode == "decline" else EXPANSION

    def stream(prompt):
        state.prompts.append(prompt)
        yield "fixed "
        yield "answer"

    def build_gate(**features):
        state.gate_features.append(features)

        def gate(scores):
            state.gate_scores.append(scores)
            return state.gate_rejected, "synthetic calibrated decision"

        if state.gate_p is not None:
            gate.last_p = state.gate_p
        return gate

    monkeypatch.setattr(settings, "rejection_mode", "threshold")
    monkeypatch.setattr(settings, "rescue_min_probability", 0.25)
    monkeypatch.setattr(settings, "answer_feedback_enabled", False)
    for module in (chat, search):
        monkeypatch.setattr(module, "build_gate_fn", build_gate)
    api_client.app.dependency_overrides[get_hybrid_retriever] = lambda: hybrid
    api_client.app.dependency_overrides[get_reranker] = lambda: reranker
    api_client.app.dependency_overrides[get_hyde_rescue_fn] = lambda: None
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: stream
    state.enable_rescue = lambda: api_client.app.dependency_overrides.update({get_hyde_rescue_fn: lambda: rescue})
    return state


def request(state, route, payload, via, ids, *, reason=None, telemetry=None):
    with capture_logs() as logs:
        response = state.client.post(route, json=payload, headers={"X-Eval-Run": "sim02-parity"})
    assert response.status_code == 200, response.text
    if route == "/chat":
        assert response.headers["content-type"].startswith("application/x-ndjson")
        events = [json.loads(line) for line in response.text.splitlines()]
        body = events[0]
        assert body["type"] == "meta"
        assert set(body) == {"type", "matched_via", "retrieval_ms", "prompt_version", "results"} | (
            {"rejection_reason"} if reason is not None else set())
        assert events[1:] == [{"type": "token", "text": "fixed "}, {"type": "token", "text": "answer"},
                              {"type": "done"}]
        assert len(state.prompts) == 1
        assert ("rejection_reason" in body) is (reason is not None)
    else:
        body = response.json()
        assert set(body) == {"query", "k", "matched_via", "results", "latency_ms", "rejection_reason"}
        assert body["query"] == payload["query"] and body["k"] == payload.get("k", 10)
        assert all(hit["matched_via"] == via for hit in body["results"])
    assert body["matched_via"] == via
    assert [hit["course_id"] for hit in body["results"]] == ids
    assert body.get("rejection_reason") == reason
    assert body["retrieval_ms" if route == "/chat" else "latency_ms"] >= 0
    rows = state.conn.execute("SELECT * FROM query_log").fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["route"] == route[1:] and row["query"] == payload["query"]
    assert row["k"] == payload.get("k", 5 if route == "/chat" else 10)
    assert row["matched_via"] == (telemetry or via)
    assert row["rejection_reason"] == reason
    assert json.loads(row["result_course_ids"]) == ids
    assert row["user_id"] == "eval:sim02-parity"
    return body, logs


@pytest.mark.parametrize("route", ["/search", "/chat"])
@pytest.mark.parametrize("scenario", ["hybrid", "no_reranker", "empty", "rejected", "rescue_success",
                                      "rescue_decline", "rescue_error", "rescue_empty", "code_guard"])
def test_threshold_path_characterization(decision_client, route, scenario):
    state = decision_client
    query = "opaque topic" if scenario != "code_guard" else "CS 9999"
    ids, via, reason, telemetry = [IDS[1]], "hybrid", None, None
    if scenario == "no_reranker":
        state.client.app.dependency_overrides[get_reranker] = lambda: None
        ids = [IDS[0]]
    elif scenario == "empty":
        state.hybrid.ids = []
        ids, via = [], "empty"
    elif scenario != "hybrid":
        state.reranker.scores = [0.0] * 3
        ids, via, reason = [], "rejected", REASON
        if scenario.startswith("rescue_") or scenario == "code_guard":
            state.enable_rescue()
            state.rescue_mode = scenario.removeprefix("rescue_")
            state.hybrid.empty_retry = scenario == "rescue_empty"
        if scenario == "rescue_success":
            ids, via, reason, telemetry = [IDS[0]], "hybrid", None, "hyde_rescued"
    body, logs = request(state, route, {"query": query, "k": 1}, via, ids, reason=reason, telemetry=telemetry)
    filters = {"primary_code_prefix": "CS"} if scenario == "code_guard" else {}
    pool = 1 if scenario == "no_reranker" else search.RERANK_POOL_SIZE
    assert state.hybrid.calls[0] == ("9999" if scenario == "code_guard" else query, filters, pool)
    retry = scenario in {"rescue_success", "rescue_empty"}
    assert state.hybrid.calls[1:] == ([(f"{query}\n\n{EXPANSION}", filters, pool)] if retry else [])
    expected_rescues = [query] if scenario.startswith("rescue_") else []
    assert state.rescue_calls == expected_rescues
    passes = 0 if scenario in {"empty", "no_reranker"} else (2 if scenario == "rescue_success" else 1)
    assert state.reranker.calls == [(query, RAW if not filters else [RAW[0]])] * passes
    assert state.gate_features == []
    if scenario == "hybrid":
        assert body["results"][0]["score"] == pytest.approx(0.7348469228349535)
    if via == "rejected" and route == "/search":
        rejected = [entry for entry in logs if entry["event"] == "search.rejected"]
        assert len(rejected) == 1
        assert rejected[0]["max_sigmoid"] == 0.0
        assert rejected[0]["n_candidates"] == (1 if filters else 3)
    if telemetry == "hyde_rescued":
        assert len([entry for entry in logs if entry["event"] == f"{route[1:]}.hyde_rescued"]) == 1


@pytest.mark.parametrize("route", ["/search", "/chat"])
@pytest.mark.parametrize("mode", ["accept", "borderline", "high_confidence", "missing_probability",
                                  "missing_diagnostics", "disabled"])
def test_calibrated_path_characterization(decision_client, monkeypatch, route, mode):
    state = decision_client
    monkeypatch.setattr(settings, "rejection_mode", "calibrated")
    if mode != "disabled":
        state.enable_rescue()
    state.gate_rejected = mode != "accept"
    state.gate_p = 0.249 if mode == "high_confidence" else (None if mode == "missing_probability" else 0.25)
    if mode == "missing_diagnostics":
        state.hybrid.diagnostics = None
    if mode == "accept":
        state.reranker.scores = [0.01] * 3  # below raw threshold: calibrated acceptance wins
    via = "rejected" if mode in {"high_confidence", "disabled"} else "hybrid"
    reason = "synthetic calibrated decision" if via == "rejected" else None
    telemetry = None if mode in {"accept", "high_confidence", "disabled"} else "hyde_rescued"
    body, _ = request(state, route, {"query": "opaque topic", "k": 1}, via,
                      [] if reason else [IDS[0] if mode == "accept" else IDS[1]], reason=reason, telemetry=telemetry)
    expected_diag = state.hybrid.diagnostics or {"bm25_top": 0.0, "vec_top": 0.0}
    assert state.gate_features == [{"query": "opaque topic", **expected_diag}]
    assert state.gate_scores == [state.reranker.scores]
    rescued = telemetry == "hyde_rescued"
    assert state.rescue_calls == (["opaque topic"] if rescued else [])
    assert len(state.hybrid.calls) == (2 if rescued else 1)
    assert state.reranker.calls == [("opaque topic", RAW)] * (2 if rescued else 1)
    if mode == "accept":
        assert body["results"][0]["score"] == pytest.approx(0.4898979485566356)


@pytest.mark.parametrize("route", ["/search", "/chat"])
def test_rescue_preserves_effective_filters_and_original_query(decision_client, route):
    state = decision_client
    state.reranker.scores = [0.0] * 3
    state.enable_rescue()
    request(state, route, {"query": "CS opaque topic", "credits": 4, "k": 1}, "hybrid", [IDS[0]],
            telemetry="hyde_rescued")
    filters = {"credits": 4, "primary_code_prefix": "CS"}
    assert state.hybrid.calls == [("opaque topic", filters, search.RERANK_POOL_SIZE),
                                  (f"CS opaque topic\n\n{EXPANSION}", filters, search.RERANK_POOL_SIZE)]
    assert state.reranker.calls == [("CS opaque topic", [RAW[0]])] * 2
    assert state.rescue_calls == ["CS opaque topic"]


@pytest.mark.parametrize("route", ["/search", "/chat"])
def test_k_above_configured_pool_is_preserved(decision_client, monkeypatch, route):
    state = decision_client
    for module in (search, chat):
        monkeypatch.setattr(module, "RERANK_POOL_SIZE", 2)
    request(state, route, {"query": "opaque topic", "k": 3}, "hybrid", [IDS[1], IDS[0], IDS[2]])
    assert state.hybrid.calls == [("opaque topic", {}, 3)]
    assert state.reranker.calls == [("opaque topic", RAW)]


@pytest.mark.parametrize("route", ["/search", "/chat"])
@pytest.mark.parametrize("excluded", [False, True])
def test_alias_and_filter_exclusion_skip_the_decision(decision_client, route, excluded):
    state = decision_client
    state.reranker.scores = [0.0] * 3
    state.enable_rescue()
    payload = {"query": "Algo", "k": 1, **({"credits": 3} if excluded else {})}
    request(state, route, payload, "empty" if excluded else "alias", [] if excluded else [IDS[0]])
    assert state.hybrid.calls == state.reranker.calls == state.rescue_calls == state.gate_features == []


@pytest.mark.parametrize("branch", ["context", "program"])
def test_chat_shortcuts_skip_the_decision(decision_client, branch):
    state = decision_client
    state.reranker.scores = [0.0] * 3
    state.enable_rescue()
    payload = {"query": "this course please", "context_course_ids": [IDS[0]], "k": 1}
    if branch == "program":
        programs = ProgramRepository(state.conn)
        programs.upsert_program(Program(program_id="cs-parity", full_name="Synthetic MSCS", prefix="CS"))
        programs.upsert_required_course(ProgramRequiredCourse(program_id="cs-parity", course_id=IDS[0],
                                        requirement_type="foundation", semester_recommended=1))
        payload = {"query": "CS major first semester", "k": 1}
    request(state, "/chat", payload, branch, [IDS[0]])
    assert state.hybrid.calls == state.reranker.calls == state.rescue_calls == state.gate_features == []


@pytest.mark.parametrize("route", ["/search", "/chat"])
def test_filtered_alternative_anchor_still_reaches_hybrid(decision_client, route):
    state = decision_client
    repo = CourseRepository(state.conn)
    repo.insert(Course(course_id="c-cs-5200", primary_code="CS 5200", primary_name="Synthetic Databases", credits=3),
                raw_text="database query planning")
    repo.mark_indexed("c-cs-5200")
    state.hybrid.ids.append("c-cs-5200")
    request(state, route, {"query": "planning courses like CS 5800", "credits": 3, "k": 1}, "hybrid", ["c-cs-5200"])
    assert len(state.hybrid.calls) == 1
    assert state.hybrid.calls[0][1] == {"credits": 3, "primary_code_prefix": "CS"}
    assert state.reranker.calls == [("planning courses like CS 5800", ["database query planning"])]


@pytest.mark.parametrize("route", ["/search", "/chat"])
def test_empty_raw_text_keeps_name_fallback(decision_client, route):
    state = decision_client
    state.conn.execute("UPDATE courses SET raw_text='' WHERE course_id=?", (IDS[0],))
    request(state, route, {"query": "opaque topic", "k": 1}, "hybrid", [IDS[1]])
    assert state.reranker.calls == [("opaque topic", ["Algorithms", *RAW[1:]])]


@pytest.mark.parametrize("route", ["/search", "/chat"])
def test_acronym_expansion_only_reaches_retrieval_legs(decision_client, route):
    state = decision_client
    app = state.client.app
    expansions = []

    def expand(query):
        expansions.append(query)
        return query + "\nsynthetic acronym expansion"

    class LexicalSpy(FixtureReranker):
        def score(self, query, candidates):
            state.reranker.calls.append((query, list(candidates)))
            return super().score(query, candidates)

    vector = Retriever(embedder=app.state.embedder, index=app.state.faiss_index,
                       course_repo=CourseRepository(state.conn), sqlite_conn=state.conn)
    hybrid = HybridRetriever(vector_retriever=vector, bm25_corpus=app.state.bm25_corpus,
                             course_repo=CourseRepository(state.conn), query_expander=expand)
    app.dependency_overrides[get_hybrid_retriever] = lambda: hybrid
    app.dependency_overrides[get_reranker] = lambda: LexicalSpy()
    request(state, route, {"query": "graph algorithms", "k": 1}, "hybrid", [IDS[0]])
    assert expansions == ["graph algorithms"]
    assert len(state.reranker.calls) == 1
    assert state.reranker.calls[0][0] == "graph algorithms"
