"""I course-read privacy and K question metadata coexist in the real JSON pipeline."""

import json

import httpx
import pytest
import structlog

from api.dependencies import get_chat_stream_fn
from api.query_fields import query_fields
from config import settings
from tests.test_log_query_fields import documented
from tests.test_safe_error_exits import _json_logs

CID = "c-cs-5800"
REF = "CS 5800"
CANARY = "synthetic_IK_private_marker"
QUESTION = "graph algorithms BFS DFS " + CANARY + " 中文问题"
SECRET = "synthetic-integration-log-key"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import importlib

    def forbidden(*args, **kwargs):
        raise AssertionError("External HTTP forbidden in offline integration")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(settings, "session_secret", SECRET)
    # Real logging caches a route's first processor chain. Keep these test loggers local
    # so later capture_logs tests still see their original, unprimed route proxies.
    for name in ("api.routes.search", "api.routes.chat", "api.routes.common", "api.routes.resolve",
                 "db.course_requisite_repository"):
        module = importlib.import_module(name)
        monkeypatch.setattr(module, "log", structlog.get_logger("synthetic.integration." + name))


def events(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.startswith("{")]


@pytest.mark.parametrize("route", ["/search", "/chat"])
@pytest.mark.parametrize("course_first", [False, True], ids=["question-first", "course-first"])
def test_alternating_requests_keep_course_scope_and_question_join(api_client, empty_db, monkeypatch,
                                                                route, course_first):
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: (lambda prompt: iter(["synthetic answer"]))

    def read_courses():
        resolved = api_client.get("/resolve/course", params={"ref": REF},
                                  headers={"x-request-id": "ik-resolve"})
        detail = api_client.get("/course/" + CID, headers={"x-request-id": "ik-course"})
        assert resolved.status_code == detail.status_code == 200
        assert resolved.json()["ref"] == REF and detail.json()["primary_code"] == REF

    with _json_logs(monkeypatch) as stream:
        if course_first:
            read_courses()
            assert empty_db.execute("SELECT COUNT(*) FROM query_log").fetchone()[0] == 0
        response = api_client.post(route, json={"query": QUESTION, "k": 1},
                                   headers={"x-request-id": "ik-question"})
        assert response.status_code == 200 and response.headers["x-request-id"] == "ik-question"
        if not course_first:
            read_courses()
        captured = events(stream)
        assert CANARY not in stream.getvalue()

    for rid, path in [("ik-resolve", "/resolve/course"), ("ik-course", "/course/{course_id}")]:
        scoped = [item for item in captured if item.get("request_id") == rid]
        assert scoped and all(item["path"] == path and item["method"] == "GET" for item in scoped)
        assert CID not in repr(scoped) and REF not in repr(scoped)
        assert not any({"query_hash", "query_len", "query_log_id"} & item.keys() for item in scoped)
        handled = [item for item in scoped if item["event"] == "request.handled"]
        assert len(handled) == 1 and handled[0]["status"] == 200

    [row] = empty_db.execute("SELECT log_id, query, route FROM query_log").fetchall()
    assert row["query"] == QUESTION and row["route"] == route.lstrip("/")
    scoped = [item for item in captured if item.get("request_id") == "ik-question"]
    assert scoped and all(item["path"] == route and item["method"] == "POST" for item in scoped)
    name = "search.hybrid" if route == "/search" else "chat.retrieved"
    [question] = [item for item in scoped if item["event"] == name]
    assert (question["query_hash"], question["query_len"]) == (documented(SECRET, QUESTION), len(QUESTION))
    [written] = [item for item in scoped if item["event"] == "query_log.written"]
    assert written["query_log_id"] == row["log_id"]


def test_course_scope_drops_question_metadata_but_keeps_diagnostics(api_client, empty_db, monkeypatch):
    from db.course_requisite_repository import CourseRequisiteRepository

    original = CourseRequisiteRepository.list_for_course

    def noisy(self, course_id, *args, **kwargs):
        structlog.get_logger("synthetic.integration").warning("synthetic.course_diagnostic",
            **query_fields(QUESTION), query_log_id=99, course_id=course_id, source=CANARY,
            catalog_year="2026-2027", count=1)
        return original(self, course_id, *args, **kwargs)

    monkeypatch.setattr(CourseRequisiteRepository, "list_for_course", noisy)
    with _json_logs(monkeypatch) as stream:
        response = api_client.get("/course/" + CID, headers={"x-request-id": "ik-diagnostics"})
        captured = events(stream)
    assert response.status_code == 200
    [diagnostic] = [item for item in captured if item["event"] == "synthetic.course_diagnostic"]
    assert not {"query_hash", "query_len", "query_log_id", "course_id", "source"} & diagnostic.keys()
    assert diagnostic["path"] == "/course/{course_id}" and diagnostic["catalog_year"] == "2026-2027"
    assert diagnostic["count"] == 1 and diagnostic["request_id"] == "ik-diagnostics"
    assert CANARY not in stream.getvalue() and CID not in stream.getvalue()
    assert empty_db.execute("SELECT COUNT(*) FROM query_log").fetchone()[0] == 0


def test_question_request_clears_stale_caller_context(api_client, monkeypatch):
    with _json_logs(monkeypatch) as stream:
        with structlog.contextvars.bound_contextvars(query=CANARY):
            response = api_client.post("/search", json={"query": QUESTION, "k": 1})
        captured = events(stream)
    assert response.status_code == 200 and captured
    assert CANARY not in stream.getvalue()
    [question] = [item for item in captured if item["event"] == "search.hybrid"]
    assert (question["query_hash"], question["query_len"]) == (documented(SECRET, QUESTION), len(QUESTION))
