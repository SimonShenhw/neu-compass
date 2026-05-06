"""Tests for api.exceptions — structured error response + global handlers.

PLAN v2.3 Week 8 §3.7 follow-up. Verifies:
  1. HTTPException raised by routes gets the new {detail, error_type,
     status_code} shape (backward-compat: detail field preserved).
  2. Domain exceptions (OAuthError / CourseNotFound / GeminiError) get
     mapped to the right status code + error_type, even if raised deep
     in the call stack without a per-route try/except.
  3. Truly unhandled exceptions become structured 500 (not FastAPI default
     `{"detail": "Internal Server Error"}`) and don't leak the exception
     message to the client.

Uses a throwaway FastAPI app — keeps the tests isolated from project
routers / fixtures / DB / auth / model state.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.exceptions import register_exception_handlers
from app.auth import OAuthError
from db.repository import CourseNotFound
from llm.gemini_client import GeminiError


@pytest.fixture
def app() -> FastAPI:
    """Tiny app with handlers + one route per exception type."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/raise-http-422")
    def _r422() -> None:
        raise HTTPException(status_code=422, detail="bad input")

    @app.get("/raise-http-503")
    def _r503() -> None:
        raise HTTPException(status_code=503, detail="warming")

    @app.get("/raise-http-404")
    def _r404() -> None:
        raise HTTPException(status_code=404, detail="missing")

    @app.get("/raise-oauth")
    def _oauth() -> None:
        raise OAuthError("invalid grant")

    @app.get("/raise-not-found")
    def _nf() -> None:
        raise CourseNotFound("neu-cs-9999")

    @app.get("/raise-gemini")
    def _gem() -> None:
        raise GeminiError("rate limit exceeded")

    @app.get("/raise-unhandled")
    def _bad() -> None:
        raise RuntimeError("internal state corrupted")

    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    # raise_server_exceptions=False so the unhandled-exception handler can
    # return a 500 response instead of the test client re-raising.
    return TestClient(app, raise_server_exceptions=False)


# === HTTPException → structured shape ===


def test_http_exception_422_has_invalid_input_type(client: TestClient) -> None:
    r = client.get("/raise-http-422")
    assert r.status_code == 422
    body = r.json()
    assert body["detail"] == "bad input"
    assert body["error_type"] == "invalid_input"
    assert body["status_code"] == 422


def test_http_exception_503_has_service_unavailable_type(
    client: TestClient,
) -> None:
    r = client.get("/raise-http-503")
    assert r.status_code == 503
    assert r.json()["error_type"] == "service_unavailable"


def test_http_exception_404_has_not_found_type(client: TestClient) -> None:
    r = client.get("/raise-http-404")
    assert r.status_code == 404
    assert r.json()["error_type"] == "not_found"


# === Domain exceptions → handler-mapped types ===


def test_oauth_error_maps_to_401_unauthorized(client: TestClient) -> None:
    r = client.get("/raise-oauth")
    assert r.status_code == 401
    body = r.json()
    assert body["error_type"] == "unauthorized"
    assert "invalid grant" in body["detail"]


def test_course_not_found_maps_to_404(client: TestClient) -> None:
    r = client.get("/raise-not-found")
    assert r.status_code == 404
    body = r.json()
    assert body["error_type"] == "not_found"
    assert "neu-cs-9999" in body["detail"]


def test_gemini_error_maps_to_502_upstream(client: TestClient) -> None:
    r = client.get("/raise-gemini")
    assert r.status_code == 502
    body = r.json()
    assert body["error_type"] == "upstream_error"
    assert "rate limit" in body["detail"]


# === Unhandled fallback ===


def test_unhandled_exception_maps_to_500(client: TestClient) -> None:
    r = client.get("/raise-unhandled")
    assert r.status_code == 500
    body = r.json()
    assert body["error_type"] == "internal_error"


def test_unhandled_exception_does_not_leak_internal_detail(
    client: TestClient,
) -> None:
    """Defense against leaking exception type / message / file paths to
    clients. The detail must be a fixed generic string — server logs are
    where the real diagnostic lives, correlated by x-request-id."""
    r = client.get("/raise-unhandled")
    body = r.json()
    assert "RuntimeError" not in body["detail"]
    assert "internal state corrupted" not in body["detail"]
    assert "Internal server error" in body["detail"]


# === Cross-cutting invariants ===


def test_response_always_includes_status_code_field(client: TestClient) -> None:
    """Every error response includes status_code for client convenience."""
    paths = [
        "/raise-http-422",
        "/raise-http-503",
        "/raise-oauth",
        "/raise-not-found",
        "/raise-gemini",
        "/raise-unhandled",
    ]
    for path in paths:
        r = client.get(path)
        assert r.json()["status_code"] == r.status_code, path


def test_detail_field_preserved_for_backward_compat(client: TestClient) -> None:
    """Existing clients reading response['detail'] (32+ tests across the
    project) still work — `detail` field is always present + a string."""
    paths = [
        "/raise-http-422",
        "/raise-oauth",
        "/raise-not-found",
        "/raise-gemini",
        "/raise-unhandled",
    ]
    for path in paths:
        r = client.get(path)
        body = r.json()
        assert "detail" in body, path
        assert isinstance(body["detail"], str), path
        assert len(body["detail"]) > 0, path


def test_error_type_is_in_taxonomy(client: TestClient) -> None:
    """error_type values come from a documented closed-ish set. Clients
    can rely on string equality for dispatch."""
    expected = {
        "invalid_input", "not_found", "unauthorized", "forbidden",
        "conflict", "service_unavailable", "upstream_error",
        "client_error", "server_error", "internal_error",
    }
    paths = [
        "/raise-http-422",
        "/raise-http-503",
        "/raise-http-404",
        "/raise-oauth",
        "/raise-not-found",
        "/raise-gemini",
        "/raise-unhandled",
    ]
    for path in paths:
        r = client.get(path)
        et = r.json()["error_type"]
        assert et in expected, f"{path}: unknown error_type {et!r}"
