"""Filter and rejection contracts across API retrieval branches (all offline)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.dependencies import (
    get_chat_stream_fn, get_db_conn, get_hybrid_retriever, get_hyde_rescue_fn, get_reranker,
)
from config import settings
from db.program_repository import ProgramRepository
from db.repository import CourseRepository
from rag.filters import filter_course_ids
from rag.hybrid import HybridRetriever
from schemas.program import Program, ProgramRequiredCourse

COURSE_IDS = ["c-aai-6600", "c-cs-5800", "c-ds-5220"]
FILTER_CASES = [
    ({"credits": 4}, ["c-cs-5800", "c-ds-5220"]),
    ({"term": "Fall 2025"}, ["c-ds-5220"]),
    ({"delivery_mode": "hybrid"}, ["c-aai-6600"]),
    ({"professor": "hopper"}, ["c-cs-5800", "c-ds-5220"]),
    (
        {"credits": 4, "term": "Spring 2026", "delivery_mode": "in_person", "professor": "Hopper"},
        ["c-cs-5800"],
    ),
    ({"credits": 0}, []),
    ({"term": "Summer 2099"}, []),
    ({"delivery_mode": "online"}, []),
    ({"professor": "Nobody"}, []),
]


class NoHybridSearch:
    last_diagnostics = None

    def search(self, *args, **kwargs):
        raise AssertionError("An explicit reference must not become an unrelated hybrid search")


@pytest.fixture
def advisor(api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "rejection_mode", "threshold")
    monkeypatch.setattr(settings, "hyde_rescue", False)
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: lambda prompt: iter([])
    api_client.app.dependency_overrides[get_hybrid_retriever] = lambda: NoHybridSearch()
    conn = api_client.app.dependency_overrides[get_db_conn]()
    courses = CourseRepository(conn)
    programs = ProgramRepository(conn)
    programs.upsert_program(Program(program_id="cs-review", full_name="MSCS fixture", prefix="CS"))
    for cid in COURSE_IDS:
        professor = "Alan Turing" if cid == "c-aai-6600" else "Grace Hopper"
        courses.upsert(courses.get(cid).model_copy(update={"professor": [professor]}))
        courses.mark_indexed(cid)
        programs.upsert_required_course(ProgramRequiredCourse(
            program_id="cs-review", course_id=cid,
            requirement_type="foundation", semester_recommended=1,
        ))
    return api_client


def _response(client: TestClient, route: str, payload: dict) -> dict:
    response = client.post(route, json=payload)
    assert response.status_code == 200, response.text
    return json.loads(response.text.splitlines()[0]) if route == "/chat" else response.json()


@pytest.mark.parametrize("route", ["/chat", "/search"])
@pytest.mark.parametrize(("filters", "allowed"), FILTER_CASES)
def test_exact_course_reference_obeys_filters(advisor, route, filters, allowed) -> None:
    body = _response(advisor, route, {"query": "CS 5800", **filters})
    expected = [cid for cid in allowed if cid == "c-cs-5800"]
    assert [hit["course_id"] for hit in body["results"]] == expected
    assert body["matched_via"] == ("alias" if expected else "empty")


@pytest.mark.parametrize("branch", ["context", "program"])
@pytest.mark.parametrize(("filters", "allowed"), FILTER_CASES)
def test_chat_shortcuts_obey_all_explicit_filters(advisor, branch, filters, allowed) -> None:
    payload = {"query": "this course please", "context_course_ids": COURSE_IDS}
    if branch == "program":
        payload = {"query": "CS major first semester"}
    body = _response(advisor, "/chat", {**payload, **filters})
    assert [hit["course_id"] for hit in body["results"]] == allowed
    assert body["matched_via"] == (branch if allowed else "empty")


@pytest.mark.parametrize("branch", ["context", "program", "alias_chat", "alias_search"])
def test_shortcuts_filter_before_top_k(advisor, monkeypatch, branch) -> None:
    route = "/search" if branch == "alias_search" else "/chat"
    payload = {"query": "this course please", "context_course_ids": COURSE_IDS, "credits": 4, "k": 1}
    if branch == "program":
        payload.pop("context_course_ids")
        payload["query"] = "CS major first semester"
    elif branch.startswith("alias_"):
        payload.pop("context_course_ids")
        payload["query"] = "shared nickname"
        module = "api.routes.search" if route == "/search" else "api.routes.chat"
        monkeypatch.setattr(f"{module}.normalize_query_to_course_ids", lambda *args, **kw: COURSE_IDS)
    body = _response(advisor, route, payload)
    assert [hit["course_id"] for hit in body["results"]] == ["c-cs-5800"]


@pytest.mark.parametrize("route", ["/chat", "/search"])
def test_filtered_alias_cannot_return_pending_course(advisor, route) -> None:
    conn = advisor.app.dependency_overrides[get_db_conn]()
    conn.execute("UPDATE courses SET status='pending' WHERE course_id=?", ("c-cs-5800",))
    body = _response(advisor, route, {"query": "CS 5800", "credits": 4})
    assert body["matched_via"] == "empty"
    assert body["results"] == []


@pytest.mark.parametrize("route", ["/chat", "/search"])
@pytest.mark.parametrize("mode", ["threshold", "calibrated"])
def test_program_prefix_does_not_disable_rejection(api_client, monkeypatch, route, mode) -> None:
    monkeypatch.setattr(settings, "rejection_mode", mode)
    monkeypatch.setattr(settings, "hyde_rescue", False)
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: lambda prompt: iter([])
    calls = []
    if mode == "calibrated":
        def build_gate(**features):
            calls.append(features)
            def gate(scores):
                return True, "review gate rejected unrelated query"
            gate.last_p = 0.01
            return gate
        module = "api.routes.chat" if route == "/chat" else "api.routes.search"
        monkeypatch.setattr(f"{module}.build_gate_fn", build_gate)
    body = _response(api_client, route, {"query": "CS banana monkey yellow nonsense"})
    assert body["matched_via"] == "rejected"
    assert body["results"] == []
    assert body["rejection_reason"]
    if mode == "calibrated":
        assert len(calls) == 1
        assert calls[0]["query"] == "CS banana monkey yellow nonsense"


@pytest.mark.parametrize("route", ["/chat", "/search"])
def test_hyde_retry_preserves_effective_filters(api_client, monkeypatch, route) -> None:
    monkeypatch.setattr(settings, "rejection_mode", "threshold")
    monkeypatch.setattr(settings, "hyde_rescue", True)
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: lambda prompt: iter([])
    rescued_queries = []
    def rescue(query):
        rescued_queries.append(query)
        return "neural network training backpropagation gradient descent"
    api_client.app.dependency_overrides[get_hyde_rescue_fn] = lambda: rescue
    filters_seen = []
    original_search = HybridRetriever.search
    def capture_search(self, query, *, hard_filters=None, k=10):
        filters_seen.append(dict(hard_filters or {}))
        return original_search(self, query, hard_filters=hard_filters, k=k)
    monkeypatch.setattr(HybridRetriever, "search", capture_search)
    body = _response(api_client, route, {"query": "CS opaque topic", "credits": 4, "k": 1})
    assert rescued_queries == ["CS opaque topic"]
    assert filters_seen == [{"credits": 4, "primary_code_prefix": "CS"}] * 2
    assert [hit["course_id"] for hit in body["results"]] == ["c-cs-5800"]


def test_prefix_query_can_use_calibrated_crosslingual_acceptance(api_client, monkeypatch) -> None:
    """A calibrated acceptance must not be replaced by the raw-sigmoid threshold."""
    monkeypatch.setattr(settings, "rejection_mode", "calibrated")
    monkeypatch.setattr(settings, "hyde_rescue", False)
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: lambda prompt: iter([])
    class LowReranker:
        def score(self, query, candidates):
            return [0.044] * len(candidates)
    api_client.app.dependency_overrides[get_reranker] = lambda: LowReranker()
    seen = []
    def build_gate(**features):
        def gate(scores):
            seen.append(scores)
            return False, "review crosslingual evidence accepted"
        return gate
    monkeypatch.setattr("api.routes.chat.build_gate_fn", build_gate)
    body = _response(api_client, "/chat", {"query": "CS 算法相关课程"})
    assert body["matched_via"] == "hybrid"
    assert seen == [[0.044]]
    assert [hit["course_id"] for hit in body["results"]] == ["c-cs-5800"]


def test_empty_sql_shortlist_cannot_expand_to_full_corpus(advisor) -> None:
    conn = advisor.app.dependency_overrides[get_db_conn]()
    assert filter_course_ids(conn, {}, candidate_course_ids=[]) == []


def test_sql_shortlist_ids_are_bound_parameters(advisor) -> None:
    conn = advisor.app.dependency_overrides[get_db_conn]()
    assert filter_course_ids(conn, {}, candidate_course_ids=[
        "c-cs-5800", "missing') OR 1=1 --",
    ]) == ["c-cs-5800"]


def test_full_and_shortlist_sql_filters_share_semantics(advisor) -> None:
    conn = advisor.app.dependency_overrides[get_db_conn]()
    filters = {"professor": "hopper", "term": "Spring 2026", "credits": 4}
    assert filter_course_ids(conn, filters) == ["c-cs-5800"]
    assert filter_course_ids(conn, filters, candidate_course_ids=COURSE_IDS) == ["c-cs-5800"]


def test_sql_prefix_matches_department_boundary(advisor) -> None:
    conn = advisor.app.dependency_overrides[get_db_conn]()
    courses = CourseRepository(conn)
    courses.upsert(courses.get("c-aai-6600").model_copy(update={"primary_code": "CSYE 6600"}))
    courses.mark_indexed("c-aai-6600")
    assert filter_course_ids(conn, {"primary_code_prefix": "cs"}) == ["c-cs-5800"]


@pytest.mark.parametrize("route", ["/chat", "/search"])
def test_high_confidence_prefix_rejection_skips_hyde(api_client, monkeypatch, route) -> None:
    monkeypatch.setattr(settings, "rejection_mode", "calibrated")
    monkeypatch.setattr(settings, "hyde_rescue", True)
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: lambda prompt: iter([])
    def rescue(query):
        raise AssertionError("A high-confidence rejection must not call the LLM")
    api_client.app.dependency_overrides[get_hyde_rescue_fn] = lambda: rescue
    def build_gate(**features):
        def gate(scores):
            return True, "review high-confidence rejection"
        gate.last_p = 0.0
        return gate
    module = "api.routes.chat" if route == "/chat" else "api.routes.search"
    monkeypatch.setattr(f"{module}.build_gate_fn", build_gate)
    body = _response(api_client, route, {"query": "CS banana monkey yellow nonsense"})
    assert body["matched_via"] == "rejected"
    assert body["results"] == []


@pytest.fixture
def anchor_client(empty_db, monkeypatch):
    """Seed + one extra 3-credit CS course, indexed BEFORE the app builds its
    BM25/FAISS (courses added later are not retrievable in the fixture app)."""
    from schemas.course import Course  # noqa: PLC0415
    from tests.conftest import build_test_app, seed_minimal_corpus  # noqa: PLC0415

    monkeypatch.setattr(settings, "rejection_mode", "threshold")
    monkeypatch.setattr(settings, "hyde_rescue", False)
    seed_minimal_corpus(empty_db)
    repo = CourseRepository(empty_db)
    repo.insert(Course(course_id="c-cs-5200", primary_code="CS 5200",
                       primary_name="Database Management Systems", credits=3),
                raw_text="database systems SQL query planning")
    repo.mark_indexed("c-cs-5200")
    app = build_test_app(empty_db, seed=False)
    app.dependency_overrides[get_chat_stream_fn] = lambda: lambda prompt: iter([])
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("route", ["/chat", "/search"])
def test_filtered_out_anchor_of_alternatives_question_falls_back_to_hybrid(anchor_client, route) -> None:
    """Review 2026-10-03: "courses like CS 5800" with a 3-credit filter used to
    return EMPTY because the alias tier resolved the 4-credit anchor and the
    filter removed it. The question is about OTHER courses: hybrid answers it
    under the same filter (and the excluded anchor never comes back)."""
    body = _response(anchor_client, route, {"query": "planning courses like CS 5800", "credits": 3})
    assert body["matched_via"] == "hybrid"
    assert [hit["course_id"] for hit in body["results"]] == ["c-cs-5200"]


@pytest.mark.parametrize("route", ["/chat", "/search"])
def test_direct_reference_still_reports_filtered_out_course_as_empty(anchor_client, route) -> None:
    """Asking ABOUT the course (no alternatives cue) keeps the batch-02 rule:
    an excluded referent is empty, never replaced by unrelated courses."""
    body = _response(anchor_client, route, {"query": "CS 5800 planning", "credits": 3})
    assert body["matched_via"] == "empty" and body["results"] == []


@pytest.mark.parametrize("query,expected", [
    ("courses like CS 5800", True), ("和 CS 5800 类似的课", True), ("CS 5800 的替代课", True),
    ("other than CS 5800", True), ("CS 5800 怎么样", False), ("CS 5800", False),
    ("is CS 5800 hard", False), ("likely", False),
])
def test_alternatives_cue_detection(query, expected) -> None:
    from rag.query_normalizer import asks_for_alternatives  # noqa: PLC0415

    assert asks_for_alternatives(query) is expected
