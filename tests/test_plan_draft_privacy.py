"""Real logging exits for draft course reads; no raw ref, course ID or downstream payload."""

import logging

import pytest
import structlog

from api.logging import configure_logging
from db.query_log_repository import QueryLogRepository
from tests.test_safe_error_exits import _json_logs

CID = "c-cs-5800"
REF = "CS 5800"
MARKER = "SYNTHETIC_PRIVATE_DRAFT_MARKER"


@pytest.fixture
def real_logging():
    configure_logging()


def test_resolve_retains_response_and_counts_but_not_ref(api_client, empty_db, real_logging, caplog, monkeypatch):
    import api.routes.resolve as resolver

    monkeypatch.setattr(resolver, "log", structlog.get_logger("synthetic.draft.resolve"))
    with caplog.at_level(logging.INFO):
        response = api_client.get("/resolve/course", params={"ref": REF})
    assert response.status_code == 200 and response.json()["ref"] == REF
    assert response.json()["matches"][0]["course_id"] == CID
    assert REF not in caplog.text and CID not in caplog.text
    assert "resolve.course" in caplog.text and "count" in caplog.text
    assert QueryLogRepository(empty_db).count() == 0


@pytest.mark.parametrize("suffix,status", [(CID, 200), (MARKER, 404), (CID + "/requisites", 200),
                                           (MARKER + "/extra/private", 404)])
def test_course_access_paths_are_templates_even_on_not_found(api_client, real_logging, caplog, suffix, status):
    with caplog.at_level(logging.INFO):
        response = api_client.get("/course/" + suffix)
    assert response.status_code == status
    assert CID not in caplog.text and MARKER not in caplog.text
    assert "/course/{course_id}" in caplog.text and "request.handled" in caplog.text
    assert response.headers.get("x-request-id")


def test_downstream_warning_and_foreign_logs_cannot_leak_course_fields(api_client, real_logging, caplog, monkeypatch):
    from db.course_requisite_repository import CourseRequisiteRepository

    original = CourseRequisiteRepository.list_for_course
    def noisy(self, course_id, *args, **kwargs):
        structlog.get_logger("synthetic.draft.downstream").warning("synthetic.course_warning", course_id=course_id,
            code=REF, candidate_codes=[REF], source=MARKER, name=MARKER, count=1)
        logging.getLogger("synthetic.foreign").warning("raw %s", MARKER)
        return original(self, course_id, *args, **kwargs)
    monkeypatch.setattr(CourseRequisiteRepository, "list_for_course", noisy)
    with caplog.at_level(logging.INFO):
        response = api_client.get("/course/" + CID)
    assert response.status_code == 200
    assert all(value not in caplog.text for value in [CID, REF, MARKER])
    assert "synthetic.course_warning" in caplog.text and "count" in caplog.text


@pytest.mark.parametrize("path", ["/course/" + CID, "/resolve/course?ref=CS%205800"])
def test_exception_exit_keeps_diagnostics_not_course_data(api_client, monkeypatch, real_logging, caplog, path):
    from db.repository import CourseRepository

    def broken(*args, **kwargs):
        raise RuntimeError(MARKER + CID + REF)
    monkeypatch.setattr(CourseRepository, "get", broken)
    monkeypatch.setattr(CourseRepository, "get_batch", broken)
    with caplog.at_level(logging.INFO):
        response = api_client.get(path)
    assert response.status_code == 500
    assert all(value not in caplog.text for value in [CID, REF, MARKER])
    assert "RuntimeError" in caplog.text and "frames" in caplog.text
    assert response.headers.get("x-request-id")


@pytest.mark.parametrize("path,expected", [("/course/private", "/course/{course_id}"),
    ("/course/private/requisites", "/course/{course_id}/requisites"),
    ("/course/private/unknown", "/course/{course_id}"), ("/resolve/course/", "/resolve/course"),
    ("/programs/cs-ms", "/programs/cs-ms"), ("/chat", "/chat")])
def test_log_path_only_normalizes_course_reads(path, expected):
    import api.logging as pipeline

    assert pipeline._course_read_log_path(path) == expected


def test_final_processor_drops_arbitrary_fields_but_other_paths_unchanged(monkeypatch):
    with _json_logs(monkeypatch) as stream:
        structlog.contextvars.bind_contextvars(path="/course/{course_id}", method="GET", request_id="synthetic-rid")
        structlog.get_logger("synthetic.privacy").warning("synthetic.inside", ref=REF, course_id=CID, arbitrary=MARKER,
            count=2, dangling=0, error_type="invalid_record", status=200)
        inside = stream.getvalue()
        assert all(value not in inside for value in [REF, CID, MARKER])
        assert all(key in inside for key in ["count", "dangling", "error_type", "synthetic-rid"])
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(path="/chat")
        structlog.get_logger("synthetic.outside").info("synthetic.outside", query=MARKER)
        assert MARKER in stream.getvalue()  # Separate K batch retains authority over chat/search logs.
