"""Tests for query_log telemetry — repository, route wiring, never-raise."""

from __future__ import annotations

import json
import sqlite3

from fastapi.testclient import TestClient

from db.query_log_repository import QueryLogRepository


# === repository ===


def test_add_and_list_roundtrip(empty_db: sqlite3.Connection) -> None:
    repo = QueryLogRepository(empty_db)
    repo.add(
        route="search", query="CS 5800", matched_via="alias", k=5,
        latency_ms=3.2, result_course_ids=["c-cs-5800"],
    )
    empty_db.commit()
    rows = repo.list_recent()
    assert repo.count() == 1
    assert rows[0]["route"] == "search"
    assert rows[0]["matched_via"] == "alias"
    assert json.loads(rows[0]["result_course_ids"]) == ["c-cs-5800"]


def test_route_check_constraint(empty_db: sqlite3.Connection) -> None:
    import pytest  # noqa: PLC0415

    repo = QueryLogRepository(empty_db)
    with pytest.raises(sqlite3.IntegrityError):
        repo.add(route="bogus", query="x", matched_via=None, k=1, latency_ms=1.0)


# === route wiring (api_client fixture: in-memory db + init.sql applied) ===


def test_search_alias_logs_row(api_client: TestClient, empty_db) -> None:
    r = api_client.post("/search", json={"query": "CS 5800", "k": 3})
    assert r.status_code == 200
    rows = QueryLogRepository(empty_db).list_recent()
    assert len(rows) == 1
    assert rows[0]["route"] == "search"
    assert rows[0]["matched_via"] == "alias"
    assert rows[0]["query"] == "CS 5800"
    assert rows[0]["latency_ms"] is not None


def test_search_rejected_logs_reason(api_client: TestClient, empty_db) -> None:
    r = api_client.post("/search", json={"query": "zzz nonexistent topic", "k": 3})
    assert r.status_code == 200
    assert r.json()["matched_via"] == "rejected"
    rows = QueryLogRepository(empty_db).list_recent()
    assert rows[0]["matched_via"] == "rejected"
    assert rows[0]["rejection_reason"]


def test_chat_logs_row(api_client: TestClient, empty_db) -> None:
    from api.dependencies import get_chat_stream_fn  # noqa: PLC0415

    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: (
        lambda prompt: iter(["ok"])
    )
    r = api_client.post("/chat", json={"query": "graph algorithms BFS", "k": 3})
    assert r.status_code == 200
    rows = QueryLogRepository(empty_db).list_recent()
    assert rows[0]["route"] == "chat"
    assert rows[0]["query"] == "graph algorithms BFS"


def test_logging_failure_never_breaks_request(
    api_client: TestClient, empty_db, monkeypatch,
) -> None:
    """Telemetry write blowing up (e.g. un-migrated DB) must not 500."""
    def boom(self, **kwargs):
        raise sqlite3.OperationalError("no such table: query_log")

    monkeypatch.setattr(QueryLogRepository, "add", boom)
    r = api_client.post("/search", json={"query": "CS 5800", "k": 3})
    assert r.status_code == 200
    assert r.json()["matched_via"] == "alias"
