"""Tests for api.routes.program — GET /programs + GET /programs/{id}."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from db.program_repository import ProgramRepository
from schemas.program import Program, ProgramRequiredCourse


def _seed_program(conn: sqlite3.Connection) -> None:
    repo = ProgramRepository(conn)
    repo.upsert_program(Program(
        program_id="cs-ms", full_name="MS in Computer Science", prefix="CS",
    ))
    repo.upsert_required_course(ProgramRequiredCourse(
        program_id="cs-ms", course_id="c-cs-5800",
        requirement_type="core", semester_recommended=1,
    ))
    repo.upsert_required_course(ProgramRequiredCourse(
        program_id="cs-ms", course_id="c-aai-6600",
        requirement_type="elective_pool", semester_recommended=None,
    ))
    conn.commit()


def test_list_programs_empty(api_client: TestClient) -> None:
    r = api_client.get("/programs")
    assert r.status_code == 200
    assert r.json() == []


def test_list_programs_with_course_count(
    api_client: TestClient, empty_db: sqlite3.Connection,
) -> None:
    _seed_program(empty_db)
    r = api_client.get("/programs")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["program_id"] == "cs-ms"
    assert rows[0]["prefix"] == "CS"
    assert rows[0]["course_count"] == 2


def test_curriculum_grouped_null_semester_last(
    api_client: TestClient, empty_db: sqlite3.Connection,
) -> None:
    _seed_program(empty_db)
    r = api_client.get("/programs/cs-ms")
    assert r.status_code == 200
    body = r.json()
    assert body["full_name"] == "MS in Computer Science"
    semesters = body["semesters"]
    assert [g["semester"] for g in semesters] == [1, None]
    sem1 = semesters[0]["courses"]
    assert sem1[0]["primary_code"] == "CS 5800"
    assert sem1[0]["requirement_type"] == "core"
    anytime = semesters[1]["courses"]
    assert anytime[0]["primary_code"] == "AAI 6600"


def test_curriculum_unknown_program_404(api_client: TestClient) -> None:
    r = api_client.get("/programs/nope-ms")
    assert r.status_code == 404
    assert r.json()["error_type"] == "not_found"


def test_curriculum_dangling_edge_skipped(
    api_client: TestClient, empty_db: sqlite3.Connection,
) -> None:
    """Edge whose course isn't in the catalog must drop out, not 500."""
    _seed_program(empty_db)
    empty_db.commit()
    empty_db.execute("PRAGMA foreign_keys = OFF")
    empty_db.execute(
        "INSERT INTO program_required_courses "
        "(program_id, course_id, requirement_type, semester_recommended) "
        "VALUES ('cs-ms', 'c-ghost-1', 'core', 1)"
    )
    empty_db.commit()
    empty_db.execute("PRAGMA foreign_keys = ON")

    r = api_client.get("/programs/cs-ms")
    assert r.status_code == 200
    sem1 = r.json()["semesters"][0]["courses"]
    assert all(c["course_id"] != "c-ghost-1" for c in sem1)
