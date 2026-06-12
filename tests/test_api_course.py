"""Tests for api.routes.course — GET /course/{course_id}."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from db.program_repository import ProgramRepository
from schemas.program import CoursePrerequisite, Program, ProgramRequiredCourse


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


# === Program-ontology context (UI round 2) ===


def test_get_course_no_ontology_returns_empty_lists(
    api_client: TestClient,
) -> None:
    """Course outside any seeded program — both lists default empty."""
    r = api_client.get("/course/c-cs-5800")
    assert r.status_code == 200
    body = r.json()
    assert body["program_context"] == []
    assert body["prerequisites"] == []


def test_get_course_resolves_program_context_and_prereqs(
    api_client: TestClient, empty_db: sqlite3.Connection,
) -> None:
    repo = ProgramRepository(empty_db)
    repo.upsert_program(Program(
        program_id="cs-ms", full_name="MS in Computer Science", prefix="CS",
    ))
    repo.upsert_required_course(ProgramRequiredCourse(
        program_id="cs-ms", course_id="c-cs-5800",
        requirement_type="core", semester_recommended=1,
    ))
    repo.upsert_prerequisite(CoursePrerequisite(
        course_id="c-cs-5800", prereq_course_id="c-aai-6600",
        requirement="recommended",
    ))
    empty_db.commit()

    r = api_client.get("/course/c-cs-5800")
    assert r.status_code == 200
    body = r.json()
    assert body["program_context"] == [{
        "program_id": "cs-ms",
        "program_name": "MS in Computer Science",
        "requirement_type": "core",
        "semester_recommended": 1,
    }]
    assert body["prerequisites"] == [{
        "course_id": "c-aai-6600",
        "primary_code": "AAI 6600",
        "primary_name": body["prerequisites"][0]["primary_name"],
        "requirement": "recommended",
    }]
    assert body["prerequisites"][0]["primary_name"]  # resolved, non-empty


def test_get_course_dangling_prereq_keeps_raw_id(
    api_client: TestClient, empty_db: sqlite3.Connection,
) -> None:
    """Prereq edge pointing at a course not in the catalog: code/name None,
    raw course_id still returned so the UI can show something.

    The schema FK normally forbids this (ON DELETE CASCADE cleans edges),
    so toggle the pragma to simulate a legacy/corrupted DB — the route
    must degrade gracefully rather than 500."""
    empty_db.commit()  # PRAGMA foreign_keys is a no-op inside a transaction
    empty_db.execute("PRAGMA foreign_keys = OFF")
    empty_db.execute(
        "INSERT INTO course_prerequisites "
        "(course_id, prereq_course_id, requirement) "
        "VALUES ('c-cs-5800', 'c-ghost-9999', 'required')"
    )
    empty_db.commit()
    empty_db.execute("PRAGMA foreign_keys = ON")

    r = api_client.get("/course/c-cs-5800")
    assert r.status_code == 200
    p = r.json()["prerequisites"][0]
    assert p["course_id"] == "c-ghost-9999"
    assert p["primary_code"] is None
    assert p["primary_name"] is None
