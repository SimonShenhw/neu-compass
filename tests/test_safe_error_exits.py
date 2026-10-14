"""SAFE-02: synthetic secrets through actual response and rendered logging exits."""

from __future__ import annotations

import contextlib
import functools
import io
import json
import logging
import re
import sqlite3
import tomllib
import types
from pathlib import Path

import anyio
import httpx
import pytest
import structlog

from api.dependencies import get_oauth_exchange_fn
from api.error_fields import safe_error_fields
from api.logging import configure_logging
from app.api_client import ApiClient, ApiError
from app.auth import exchange_code_for_token
from db.answer_feedback_repository import AnswerFeedbackRepository
from db.program_repository import ProgramAmbiguous
from db.query_log_repository import QueryLogRepository
from db.repository import CourseRepository
from schemas.program import Program

MARKER = "tok_MARKER_123"
EMAIL = "marker-email@example.invalid"


@pytest.fixture
def real_logging():
    # Run before caplog installs its call-phase handler; exercise the real renderer.
    configure_logging()


def _event(caplog, name):
    lines = [r.getMessage() for r in caplog.records if name in r.getMessage()]
    assert len(lines) == 1, (name, lines)
    return lines[0]


def _secret_free(caplog, response):
    for marker in (MARKER, EMAIL):
        assert marker not in response.text
        assert marker not in caplog.text


@pytest.mark.parametrize("kind", ["exchange", "domain", "network", "invalid_json", "missing_token"])
def test_real_oauth_exchange_is_safe(api_client, real_logging, caplog, kind):
    def handler(request):
        if kind == "network":
            raise httpx.ConnectError(MARKER)
        if kind == "exchange":
            return httpx.Response(400, json={"error": "invalid_grant", "error_description": MARKER})
        if kind == "invalid_json":
            return httpx.Response(200, text=MARKER)
        return httpx.Response(200, json={} if kind == "missing_token" else {"id_token": MARKER})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        fn = functools.partial(exchange_code_for_token, http_client=http,
            id_token_verifier=lambda token: {"sub": "synthetic-sub", "email": EMAIL, "email_verified": True})
        api_client.app.dependency_overrides[get_oauth_exchange_fn] = lambda: fn
        with caplog.at_level(logging.INFO):
            response = api_client.post("/auth/callback", json={"code": MARKER})
    assert response.status_code == 401
    _secret_free(caplog, response)
    line = _event(caplog, "auth.callback.rejected")
    reasons = {"exchange": "token_exchange_rejected", "domain": "domain_not_allowed",
        "network": "token_endpoint_unreachable", "invalid_json": "missing_id_token", "missing_token": "missing_id_token"}
    assert reasons[kind] in line
    if kind == "exchange":
        assert "upstream_status" in line and "400" in line and "invalid_grant" in line
    if kind == "domain":
        assert "email_domain" in line and "example.invalid" in line


@pytest.mark.parametrize("code", [MARKER, "a b", "a" * 65, ["invalid_grant"]])
def test_google_error_field_is_validated(api_client, real_logging, caplog, code):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(
        400, json={"error": code, "error_description": MARKER}))) as http:
        fn = functools.partial(exchange_code_for_token, http_client=http)
        api_client.app.dependency_overrides[get_oauth_exchange_fn] = lambda: fn
        with caplog.at_level(logging.INFO):
            response = api_client.post("/auth/callback", json={"code": "synthetic"})
    assert response.status_code == 401
    _secret_free(caplog, response)
    assert "google_error" not in _event(caplog, "auth.callback.rejected")


@pytest.mark.parametrize("payload", ["refused", {}, [], {"user_id": "u"},
    {"user_id": [], "email": EMAIL}, {"user_id": "u", "email": EMAIL, "contribution_count": MARKER}])
def test_callback_ui_never_raises_or_renders_raw_detail(monkeypatch, payload):
    from streamlit.testing.v1 import AppTest
    import app.api_client as client_module
    import app.cookie_session as cookie_module

    monkeypatch.setattr(cookie_module, "oauth_state_matches", lambda *args: True)
    factory = ApiClient
    status = 401 if payload == "refused" else 200
    body = {"detail": MARKER} if status == 401 else payload
    monkeypatch.setattr(client_module, "ApiClient", lambda: factory(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json=body))))
    app = AppTest.from_string("from app.streamlit_auth_ui import handle_oauth_callback\nhandle_oauth_callback()")
    app.query_params.update(code=MARKER, state="synthetic")
    app.run(timeout=30)
    assert not app.exception
    assert [item.value for item in app.error] == ["Login failed. Please try signing in again."]
    assert not dict(app.query_params)
    assert "user_id" not in app.session_state.filtered_state


@pytest.mark.parametrize("chained", ["cause", "context"])
def test_uncaught_error_is_consumed_once(api_client, real_logging, caplog, chained):
    def boom():
        try:
            raise ValueError(EMAIL)
        except ValueError as exc:
            if chained == "cause":
                raise RuntimeError(MARKER) from exc
            raise RuntimeError(MARKER) from None

    api_client.app.add_api_route("/test-boom", boom, methods=["GET"])
    with caplog.at_level(logging.INFO):
        response = api_client.get("/test-boom")  # Default raise_server_exceptions=True.
    assert response.status_code == 500
    assert response.json() == {"status_code": 500, "error_type": "internal_error",
        "detail": "Internal server error. Check API logs by x-request-id."}
    assert response.headers["x-request-id"]
    _secret_free(caplog, response)
    line = _event(caplog, "request.unhandled")
    assert "unhandled_exception" not in caplog.text
    assert "RuntimeError" in line and "ValueError" in line
    assert "cause_type" in line and "frames" in line and "test_safe_error_exits.py" in line


def test_repository_failure_uses_safe_uncaught_exit(api_client, monkeypatch, real_logging, caplog):
    def boom(*args):
        raise sqlite3.OperationalError(MARKER)
    monkeypatch.setattr(CourseRepository, "get", boom)
    with caplog.at_level(logging.INFO):
        response = api_client.get("/course/c-cs-5800")
    assert response.status_code == 500
    assert response.headers["x-request-id"]
    _secret_free(caplog, response)
    line = _event(caplog, "request.unhandled")
    assert "OperationalError" in line and "frames" in line
    assert "cause_type" not in line  # Starlette's EndOfStream re-raise is not a cause.


def test_query_log_failure_does_not_break_search_or_leak(api_client, monkeypatch, real_logging, caplog):
    def boom(*args, **kwargs):
        raise sqlite3.OperationalError(MARKER)
    monkeypatch.setattr(QueryLogRepository, "add", boom)
    with caplog.at_level(logging.INFO):
        response = api_client.post("/search", json={"query": "Algo"})
    assert response.status_code == 200
    _secret_free(caplog, response)
    assert "OperationalError" in _event(caplog, "query_log.write_failed")


def test_feedback_storage_failure_has_safe_diagnostic(api_client, monkeypatch, real_logging, caplog):
    from config import settings
    monkeypatch.setattr(settings, "answer_feedback_enabled", True)
    monkeypatch.setattr(AnswerFeedbackRepository, "schema_available", lambda self: True)
    def boom(*args):
        raise sqlite3.OperationalError(MARKER)
    monkeypatch.setattr(AnswerFeedbackRepository, "vote", boom)
    with caplog.at_level(logging.INFO):
        response = api_client.post("/feedback", json={"answer_id": "a" * 32,
            "answer_sha256": "b" * 64, "feedback_token": "c" * 43, "rating": "up"})
    assert response.status_code == 503
    _secret_free(caplog, response)
    line = _event(caplog, "feedback.storage_failed")
    assert "OperationalError" in line and "frames" in line


@pytest.mark.parametrize("path", ["/course/", "/programs/"])
def test_not_found_does_not_echo_input(api_client, path):
    response = api_client.get(path + MARKER)
    assert response.status_code == 404
    assert MARKER not in response.text


@pytest.mark.parametrize("path", ["/search", "/chat"])
def test_invalid_enum_does_not_echo_input(api_client, path):
    response = api_client.post(path, json={"query": "Algo", "delivery_mode": MARKER})
    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid delivery_mode"


def test_ambiguous_program_keeps_choices_without_exception_text(api_client, monkeypatch):
    import api.routes.chat as chat
    programs = [Program(program_id="cs-ms", full_name="CS MS", prefix="CS", department="CS", college="Khoury")]
    def boom(*args, **kwargs):
        raise ProgramAmbiguous(MARKER, programs)
    monkeypatch.setattr(chat, "_retrieve", boom)
    response = api_client.post("/chat", json={"query": "Algo"})
    assert response.status_code == 409
    assert "cs-ms" in response.json()["detail"]
    assert MARKER not in response.text and "Multiple programs" not in response.text


@pytest.mark.parametrize("key", ["bad field", "<field-marker>", "x" * 65])
def test_validation_hides_unsafe_field_names(api_client, key):
    response = api_client.post("/search", json={"query": "Algo", key: MARKER})
    assert response.status_code == 422
    assert "<field>" in response.json()["detail"]
    assert key not in response.text and MARKER not in response.text


def test_validation_still_names_safe_extra_field(api_client):
    response = api_client.post("/search", json={"query": "Algo", MARKER: "synthetic"})
    assert response.status_code == 422
    assert MARKER in response.json()["detail"]


@pytest.mark.parametrize("value", ["bad request id", "x" * 65, "a/b", "valid_1.2-3"])
def test_request_id_is_bounded(api_client, value):
    response = api_client.get("/health", headers={"x-request-id": value})
    returned = response.headers["x-request-id"]
    assert re.fullmatch(r"[A-Za-z0-9._-]{1,64}", returned)
    assert (returned == value) is (value == "valid_1.2-3")


@pytest.mark.parametrize(("status", "body"), [(500, "plain"), (502, "json"), (418, "plain"), (401, "plain")])
def test_client_error_text_is_fixed(status, body):
    with ApiClient(transport=httpx.MockTransport(lambda request: httpx.Response(status,
        **({"json": {"detail": MARKER, "error_type": "upstream_error"}} if body == "json" else {"text": MARKER})))) as api:
        with pytest.raises(ApiError) as info:
            api.health()
    assert info.value.status_code == status
    assert MARKER not in info.value.detail and MARKER not in str(info.value)
    if body == "json":
        assert info.value.error_type == "upstream_error"


def test_invalid_success_json_is_apierror():
    with ApiClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=MARKER))) as api:
        with pytest.raises(ApiError) as info:
            api.health()
    assert info.value.status_code == 502 and info.value.error_type == "invalid_response"
    assert MARKER not in str(info.value)


def test_ui_default_hides_traceback():
    config = tomllib.loads((Path(__file__).parents[1] / ".streamlit/config.toml").read_text())
    assert config.get("client", {}).get("showErrorDetails") == "type"


def test_last_resort_handler_logs_safely(real_logging, caplog):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.exceptions import register_exception_handlers
    app = FastAPI()
    register_exception_handlers(app)
    @app.get("/boom")
    def boom():
        # No BaseHTTPMiddleware here: Starlette cannot promote context into cause.
        # This pins the helper's own implicit-context fallback, not Starlette's rewrite.
        try:
            raise ValueError(EMAIL)
        except ValueError:
            raise RuntimeError(MARKER) from None
    with caplog.at_level(logging.INFO), TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")
    assert response.status_code == 500
    _secret_free(caplog, response)
    line = _event(caplog, "unhandled_exception")
    assert "RuntimeError" in line and "ValueError" in line and "frames" in line


@pytest.mark.parametrize("middleware", [True, False])
def test_uncaught_event_fields_are_whitelisted_before_rendering(api_client, middleware):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from structlog.testing import capture_logs
    from api.exceptions import register_exception_handlers
    app = api_client.app if middleware else FastAPI()
    if not middleware:
        register_exception_handlers(app)
    def boom():
        raise RuntimeError(MARKER)
    app.add_api_route("/synthetic-error", boom, methods=["GET"])
    with capture_logs() as entries, TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/synthetic-error")
    assert response.status_code == 500
    event = "request.unhandled" if middleware else "unhandled_exception"
    errors = [entry for entry in entries if entry["event"] == event]
    assert len(errors) == 1
    assert set(errors[0]) <= {"event", "log_level", "request_id", "method", "path", "status",
        "duration_ms", "error_type", "exc_type", "cause_type", "frames"}
    assert "frames" in errors[0] and "exc_info" not in errors[0]
    if middleware:
        assert errors[0]["status"] == 500 and errors[0]["error_type"] == "internal_error"


@pytest.mark.parametrize("email", ["marker-email@EXAMPLE.INVALID", "marker-email@a b", "marker-email@" + "a" * 254])
def test_refused_domain_field_is_lowercase_and_bounded(api_client, real_logging, caplog, email):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"id_token": "fake"}))) as http:
        fn = functools.partial(exchange_code_for_token, http_client=http,
            id_token_verifier=lambda token: {"sub": "synthetic", "email": email, "email_verified": True})
        api_client.app.dependency_overrides[get_oauth_exchange_fn] = lambda: fn
        with caplog.at_level(logging.INFO):
            response = api_client.post("/auth/callback", json={"code": "synthetic"})
    assert response.status_code == 401 and email not in response.text and email not in caplog.text
    line = _event(caplog, "auth.callback.rejected")
    if email.endswith("EXAMPLE.INVALID"):
        assert "example.invalid" in line and "EXAMPLE.INVALID" not in line
    else:
        assert "email_domain" not in line


@pytest.mark.parametrize("log_format", ["json", "console"])
def test_stdlib_and_structlog_exception_rendering_is_safe(monkeypatch, caplog, log_format):
    import api.logging as pipeline
    from config import settings
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    previous = structlog.get_config().copy()
    configured = pipeline._CONFIGURED
    stream = io.StringIO()
    monkeypatch.setattr(settings, "log_format", log_format)
    monkeypatch.setattr(pipeline, "_CONFIGURED", False)
    try:
        configure_logging()
        root.handlers[0].setStream(stream)
        try:
            raise RuntimeError(MARKER)
        except RuntimeError:
            logging.getLogger("thirdparty.synthetic").exception(EMAIL)
            structlog.get_logger("synthetic").exception("synthetic.failed")
        text = stream.getvalue()
        assert MARKER not in text and EMAIL not in text
        assert "RuntimeError" in text and "frames" in text
        assert "synthetic.failed" in text
        assert "Traceback" not in text
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)
        structlog.configure(**previous)
        pipeline._CONFIGURED = configured


# --- Review follow-ups (2026-10-13): wrapper causes, pre-header meta, pins, cookie restore ---


@contextlib.contextmanager
def _json_logs(monkeypatch):
    """Real pipeline rendering JSON into a StringIO, inside the test call (caplog's phase)."""
    import api.logging as pipeline
    from config import settings
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    previous = structlog.get_config().copy()
    configured = pipeline._CONFIGURED
    stream = io.StringIO()
    monkeypatch.setattr(settings, "log_format", "json")
    monkeypatch.setattr(pipeline, "_CONFIGURED", False)
    try:
        configure_logging()
        root.handlers[0].setStream(stream)
        yield stream
    finally:
        structlog.contextvars.clear_contextvars()
        root.handlers[:] = handlers
        root.setLevel(level)
        structlog.configure(**previous)
        pipeline._CONFIGURED = configured


def _rendered_events(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.startswith("{")]


@pytest.mark.parametrize("chained", [False, True])
def test_error_after_headers_names_no_framework_cause(empty_db, chained):
    from fastapi.responses import StreamingResponse
    from fastapi.testclient import TestClient
    from structlog.testing import capture_logs
    from tests.conftest import build_test_app
    app = build_test_app(empty_db)
    def stream():
        def chunks():
            yield b"{}\n"
            if chained:
                raise RuntimeError(MARKER) from ValueError(EMAIL)
            raise RuntimeError(MARKER)
        return StreamingResponse(chunks(), media_type="application/x-ndjson")
    app.add_api_route("/synthetic-stream", stream, methods=["GET"])
    with capture_logs() as entries, TestClient(app, raise_server_exceptions=False) as client:
        client.get("/synthetic-stream")
    [event] = [entry for entry in entries if entry["event"] == "unhandled_exception"]
    assert event["exc_type"] == "RuntimeError"
    # collapse_excgroups() re-raises inside `except` for its group; the group is not the cause.
    assert event.get("cause_type") == ("ValueError" if chained else None)
    assert MARKER not in repr(entries) and EMAIL not in repr(entries)


@pytest.mark.parametrize("failure", ["score", "serialise"])
def test_chat_meta_failure_is_a_safe_pre_header_500(api_client, monkeypatch, real_logging, caplog, failure):
    import api.routes.chat as chat
    from api.dependencies import get_chat_stream_fn
    original = chat._retrieve
    class BadScore:
        def __float__(self):
            raise ValueError(MARKER)
    class MetaJson:
        @staticmethod
        def dumps(payload, *args, **kwargs):
            if isinstance(payload, dict) and payload.get("type") == "meta":
                raise ValueError(MARKER)
            return json.dumps(payload, *args, **kwargs)
    def retrieve(req, alias_repo, course_repo, *args):
        _, _, hard_filters, notices = original(req, alias_repo, course_repo, *args)
        score = BadScore() if failure == "score" else 0.5
        hit = types.SimpleNamespace(course=course_repo.get("c-cs-5800"), score=score)
        return [hit], "alias", hard_filters, notices
    monkeypatch.setattr(chat, "_retrieve", retrieve)
    if failure == "serialise":
        monkeypatch.setattr(chat, "json", MetaJson)
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: (lambda prompt: iter(["unused"]))
    with caplog.at_level(logging.INFO):
        response = api_client.post("/chat", json={"query": "Algo"})  # Default raise_server_exceptions=True.
    assert response.status_code == 500 and response.json()["error_type"] == "internal_error"
    assert response.headers["x-request-id"]
    _secret_free(caplog, response)
    line = _event(caplog, "request.unhandled")
    assert "ValueError" in line and "chat.py:" in line


def test_structlog_exception_paths_keep_only_safe_location(monkeypatch):
    with _json_logs(monkeypatch) as stream:
        structlog.get_logger("synthetic").error("synthetic.kwarg", exception=MARKER)
        try:
            raise RuntimeError(MARKER)
        except RuntimeError:
            structlog.get_logger("synthetic").exception("synthetic.only_structlog")
        events = {event["event"]: event for event in _rendered_events(stream)}
        assert MARKER not in stream.getvalue()
    assert "exception" not in events["synthetic.kwarg"]
    only = events["synthetic.only_structlog"]
    assert only["exc_type"] == "RuntimeError"
    assert any(frame.startswith("test_safe_error_exits.py:") for frame in only["frames"])


def test_foreign_error_keeps_origin_request_context_and_location(monkeypatch):
    with _json_logs(monkeypatch) as stream:
        structlog.contextvars.bind_contextvars(request_id="synthetic-rid", method="GET", path="/synthetic")
        try:
            raise RuntimeError(MARKER)
        except RuntimeError:
            logging.getLogger("thirdparty.synthetic").exception("ignored %s", EMAIL)
        [event] = [e for e in _rendered_events(stream) if e["event"] == "stdlib.error"]
        assert MARKER not in stream.getvalue() and EMAIL not in stream.getvalue()
    assert event["logger"] == "thirdparty.synthetic" and event["timestamp"].endswith("Z")
    assert (event["request_id"], event["method"], event["path"]) == ("synthetic-rid", "GET", "/synthetic")
    assert event["exc_type"] == "RuntimeError" and event["frames"]


def test_invalid_request_ids_get_fresh_replacements(api_client):
    returned = {api_client.get("/health", headers={"x-request-id": "bad id"}).headers["x-request-id"]
                for _ in range(2)}
    assert len(returned) == 2


def test_google_non_object_error_body_is_a_401(api_client, real_logging, caplog):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(400, json=[MARKER]))) as http:
        fn = functools.partial(exchange_code_for_token, http_client=http)
        api_client.app.dependency_overrides[get_oauth_exchange_fn] = lambda: fn
        with caplog.at_level(logging.INFO):
            response = api_client.post("/auth/callback", json={"code": "synthetic"})
    assert response.status_code == 401
    _secret_free(caplog, response)
    assert "token_exchange_rejected" in _event(caplog, "auth.callback.rejected")


@pytest.mark.parametrize("me", [{}, [], {"user_id": ["x"], "email": 5},
    {"user_id": "u", "email": EMAIL, "contribution_count": "3"},
    {"user_id": "u", "email": EMAIL, "contribution_count": True},
    {"user_id": "u", "email": EMAIL, "display_name": 5},
    {"user_id": "u", "email": EMAIL, "contribution_count": -1}])
def test_cookie_restore_rejects_malformed_identity(me):
    from app.cookie_session import restore_login
    from app.state_manager import init_state, is_logged_in
    state: dict = {}
    init_state(state)
    assert restore_login(state, "synthetic-token", lambda token: me) is False
    assert not is_logged_in(state) and state["session_token"] is None
    assert not state.get("_pending_cookie")  # Not a 401: the cookie stays for a later reload.


# --- Second review (2026-10-13): only framework wrappers are skipped; identity branches ---


def _group_context():
    try:
        raise ExceptionGroup("synthetic", [ValueError(MARKER)])
    except ExceptionGroup:
        raise RuntimeError(MARKER)  # noqa: B904 - implicit context on purpose


def _end_of_stream_context():
    try:
        raise anyio.EndOfStream
    except anyio.EndOfStream:
        raise RuntimeError(MARKER)  # noqa: B904 - implicit, not suppressed


def _end_of_stream_cause():
    raise RuntimeError(MARKER) from anyio.EndOfStream()


def _from_none_over_value_error():
    try:
        raise ValueError(MARKER)
    except ValueError:
        raise RuntimeError(MARKER) from None


def _from_none_over_other_anyio():
    try:
        raise anyio.ClosedResourceError
    except anyio.ClosedResourceError:
        raise RuntimeError(MARKER) from None


def _collapsed(depth):
    """What starlette's collapse_excgroups() does: unwrap single-member groups, re-raise in the handler."""
    group: BaseException = RuntimeError(MARKER)
    for _ in range(depth):
        group = ExceptionGroup("synthetic", [group])
    try:
        raise group
    except BaseException as caught:
        exc = caught
        while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
            exc = exc.exceptions[0]
        raise exc  # noqa: B904 - the implicit context is exactly what collapse_excgroups() leaves


@pytest.mark.parametrize(("scenario", "expected"), [
    (_group_context, "ExceptionGroup"), (_end_of_stream_context, "EndOfStream"),
    (_end_of_stream_cause, "EndOfStream"), (_from_none_over_value_error, "ValueError"),
    (_from_none_over_other_anyio, "ClosedResourceError"),
    (functools.partial(_collapsed, 1), None), (functools.partial(_collapsed, 2), None),
], ids=["group", "end_of_stream", "explicit_end_of_stream", "from_none", "other_anyio", "collapsed", "nested"])
def test_only_framework_wrappers_are_skipped_as_causes(scenario, expected):
    with pytest.raises(RuntimeError) as info:
        scenario()
    assert safe_error_fields(info.value).get("cause_type") == expected


@pytest.mark.parametrize(("identity", "valid"), [
    ({"user_id": "", "email": EMAIL}, False), ({"user_id": "u", "email": ""}, False),
    ({"user_id": "u", "email": EMAIL, "session_token": 5}, False),
    ({"user_id": "u", "email": EMAIL, "session_token": ["t"]}, False),
    ({"user_id": ["x"], "email": EMAIL}, False), ({"user_id": "u", "email": 5}, False),
    ({"user_id": "u", "email": EMAIL}, True),
    ({"user_id": "u", "email": EMAIL, "contribution_count": 0, "session_token": None, "display_name": None}, True),
    ({"user_id": "u", "email": EMAIL, "contribution_count": 3, "session_token": "t", "display_name": "Name"}, True),
])
def test_valid_identity_branches(identity, valid):
    from app.state_manager import valid_identity
    assert valid_identity(identity) is valid
