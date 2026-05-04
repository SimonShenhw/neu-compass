"""Tests for api.routes.course — GET /course/{course_id}."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_get_course_returns_full_pydantic_dump(api_client: TestClient) -> None:
    r = api_client.get("/course/c-cs-5800")
    assert r.status_code == 200
    body = r.json()
    assert body["course_id"] == "c-cs-5800"
    assert body["primary_code"] == "CS 5800"
    assert body["primary_name"] == "Algorithms"
    assert body["term"] == "Spring 2026"
    assert body["credits"] == 4
    assert body["delivery_mode"] == "in_person"
    # Soft fields: empty by default in seed (no real reviews)
    assert body["evidence_snippets"] == []
    assert body["topics_covered"] == []
    # Schema version stays in lockstep with schemas.course.SCHEMA_VERSION
    assert body["schema_version"] == "1.1"


def test_get_course_404_when_missing(api_client: TestClient) -> None:
    r = api_client.get("/course/c-does-not-exist")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_get_course_works_for_aai(api_client: TestClient) -> None:
    """Sanity that the seed has multiple courses retrievable by id."""
    r = api_client.get("/course/c-aai-6600")
    assert r.status_code == 200
    assert r.json()["primary_code"] == "AAI 6600"
