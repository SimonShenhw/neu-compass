"""Tests for api.routes.health — /health and /ready."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from tests.conftest import build_test_app


def test_health_always_200(api_client: TestClient) -> None:
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_after_state_set(api_client: TestClient) -> None:
    """build_test_app populates state.ready=True, so /ready should be ready."""
    r = api_client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    # 3 courses seeded, BM25 corpus over the same 3
    assert body["courses_indexed"] == 3
    assert body["bm25_corpus"] == 3


def test_ready_warming_when_state_missing(empty_db: sqlite3.Connection) -> None:
    """Bare app with no state populated → /ready returns 'warming'."""
    from api.main import create_app  # noqa: PLC0415

    app = create_app(run_startup=False)
    # Don't populate state; mimic a process that's still in lifespan.
    with TestClient(app) as client:
        r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "warming"
    assert r.json()["courses_indexed"] == 0
    assert r.json()["bm25_corpus"] == 0


def test_request_id_header_round_trip(api_client: TestClient) -> None:
    """RequestLogMiddleware echoes (or assigns) x-request-id."""
    r = api_client.get("/health", headers={"x-request-id": "test-abc-123"})
    assert r.headers["x-request-id"] == "test-abc-123"

    r2 = api_client.get("/health")  # no incoming id → server assigns one
    assert r2.headers.get("x-request-id")
    assert len(r2.headers["x-request-id"]) >= 8


def test_build_test_app_helper_exposed() -> None:
    """The conftest helper is part of the test fixture contract — keep it
    importable so dedicated tests can build apps with non-default state."""
    assert callable(build_test_app)
