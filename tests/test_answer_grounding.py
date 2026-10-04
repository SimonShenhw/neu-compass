"""Answer evidence must be visible, source-aware, and shared with the prompt."""

from __future__ import annotations

import json

import pytest

from api.dependencies import get_chat_stream_fn, get_db_conn
from db.catalog_source_repository import CatalogSourceRepository
from db.repository import CourseRepository
from db.program_repository import ProgramRepository
from schemas.course import Course
from schemas.program import Program, ProgramRequiredCourse
from scrapers.neu_catalog import CatalogEntry


def capture_chat(client, payload=None):
    prompts = []
    def stream(prompt):
        prompts.append(prompt)
        return iter(["Offline fixture answer"])
    client.app.dependency_overrides[get_chat_stream_fn] = lambda: stream
    response = client.post("/chat", json=payload or {"query": "Algo"})
    assert response.status_code == 200
    return json.loads(response.text.splitlines()[0]), prompts[0]


def test_chat_exposes_missing_fields_and_does_not_promote_raw_text(api_client):
    meta, _ = capture_chat(api_client)
    evidence = meta["results"][0]["answer_evidence"]
    assert evidence["catalog"] is None
    assert "workload_hours_per_week" in evidence["missing_fields"]
    assert "difficulty_score" in evidence["missing_fields"]
    assert "catalog_description" in evidence["missing_fields"]


def test_detail_exposes_the_same_evidence_contract(api_client):
    detail = api_client.get("/course/c-cs-5800").json()
    evidence = detail["answer_evidence"]
    assert evidence["catalog"] is None
    assert "workload_hours_per_week" in evidence["missing_fields"]


def test_prompt_makes_absence_explicit_instead_of_omitting_it(api_client):
    _, prompt = capture_chat(api_client)
    assert '"workload_hours_per_week": null' in prompt
    assert '"difficulty_score": null' in prompt
    assert "Missing does NOT mean zero" in prompt


def store_catalog(client, **updates):
    conn = client.app.dependency_overrides[get_db_conn]()
    entry = CatalogEntry(**{
        "course_code": "CS 5800", "course_name": "Algorithms", "credits": 4,
        "description": "OFFICIAL SNAPSHOT: graph algorithms and dynamic programming.",
        "catalog_url": "https://catalog.northeastern.edu/course-descriptions/cs/", **updates,
    })
    snapshot = CatalogSourceRepository.snapshot(entry)
    CatalogSourceRepository(conn).store("c-cs-5800", snapshot)
    return snapshot


def test_prompt_and_metadata_use_the_recorded_catalog_not_mixed_text(api_client):
    snapshot = store_catalog(api_client)
    conn = api_client.app.dependency_overrides[get_db_conn]()
    conn.execute("UPDATE courses SET raw_text=? WHERE course_id=?", ("MIXED REVIEW TEXT: definitely easy", "c-cs-5800"))
    meta, prompt = capture_chat(api_client)
    evidence = meta["results"][0]["answer_evidence"]
    assert meta["prompt_version"] == "4.0"
    assert evidence["catalog"]["description"] == snapshot.description
    assert evidence["catalog"]["retrieved_at"] is None
    assert "catalog_retrieval_date_unknown" in evidence["warnings"]
    assert snapshot.snapshot_id in prompt
    assert snapshot.catalog_url in prompt
    assert snapshot.description in prompt
    assert "MIXED REVIEW TEXT" not in prompt
    assert evidence == api_client.get("/course/c-cs-5800").json()["answer_evidence"]


def test_soft_estimates_keep_quotes_and_source_ids(api_client):
    conn = api_client.app.dependency_overrides[get_db_conn]()
    repo = CourseRepository(conn)
    record = repo.get("c-cs-5800").model_dump()
    record.update(workload_hours_per_week=10.0, difficulty_score=3.5, evidence_snippets=[
        {"field": field, "value": value, "source_id": "rmp_review_test",
         "quote": "Reported 10 h/week; difficulty 3.5/5", "confidence": 0.8}
        for field, value in [("workload_hours_per_week", 10.0), ("difficulty_score", 3.5)]
    ])
    repo.upsert(Course.model_validate(record))
    repo.mark_indexed("c-cs-5800")
    meta, prompt = capture_chat(api_client)
    evidence = meta["results"][0]["answer_evidence"]
    assert evidence["catalog"] is None  # A source ID is not an official snapshot.
    assert "extracted_evidence_not_official_facts" in evidence["warnings"]
    assert "workload_hours_per_week" not in evidence["missing_fields"]
    assert "difficulty_score" not in evidence["missing_fields"]
    assert "rmp_review_test" in prompt
    assert "Reported 10 h/week" in prompt
    assert '"workload_hours_per_week": 10.0' in prompt
    assert '"extraction_confidence": 0.8' in prompt


def test_old_schema_degrades_honestly_without_changing_courses(api_client):
    conn = api_client.app.dependency_overrides[get_db_conn]()
    before = conn.execute("SELECT generated_json, raw_text, status FROM courses WHERE course_id='c-cs-5800'").fetchone()
    conn.execute("DROP TABLE course_catalog_sources")
    meta, prompt = capture_chat(api_client)
    assert meta["results"][0]["answer_evidence"]["catalog"] is None
    assert api_client.get("/course/c-cs-5800").status_code == 200
    after = conn.execute("SELECT generated_json, raw_text, status FROM courses WHERE course_id='c-cs-5800'").fetchone()
    assert tuple(before) == tuple(after)
    assert '"catalog": null' in prompt


@pytest.mark.parametrize("corruption", ["url", "identity", "department"])
def test_bad_snapshot_is_not_promoted_to_official(api_client, corruption):
    snapshot = store_catalog(api_client).model_dump(mode="json")
    if corruption == "url":
        snapshot["catalog_url"] = "javascript:alert(1)"
    elif corruption == "identity":
        snapshot["course_name"] = "Other course"
    else:
        snapshot["catalog_url"] = "https://catalog.northeastern.edu/course-descriptions/ds/"
    conn = api_client.app.dependency_overrides[get_db_conn]()
    conn.execute("UPDATE course_catalog_sources SET snapshot=?", (json.dumps(snapshot),))
    meta, prompt = capture_chat(api_client)
    assert meta["results"][0]["answer_evidence"]["catalog"] is None
    assert "javascript:alert" not in prompt
    assert "Other course" not in prompt


def test_conflicting_credits_are_explicit(api_client):
    store_catalog(api_client, credits=3)
    meta, prompt = capture_chat(api_client)
    evidence = meta["results"][0]["answer_evidence"]
    assert "catalog_metadata_conflict" in evidence["warnings"]
    assert evidence["catalog"]["credits"] == 3
    assert '"credits": 4' in prompt and '"credits": 3' in prompt


def test_program_shortcut_is_not_presented_as_verified_plan(api_client):
    conn = api_client.app.dependency_overrides[get_db_conn]()
    repo = ProgramRepository(conn)
    repo.upsert_program(Program(program_id="cs-review", full_name="MSCS review seed", prefix="CS"))
    repo.upsert_required_course(ProgramRequiredCourse(
        program_id="cs-review", course_id="c-cs-5800", requirement_type="foundation", semester_recommended=1,
    ))
    meta, _ = capture_chat(api_client, {"query": "CS first semester"})
    assert meta["matched_via"] == "program"
    assert "program_seed_unverified" in meta["results"][0]["answer_evidence"]["warnings"]
    assert "program_seed_unverified" in api_client.get("/course/c-cs-5800").json()["answer_evidence"]["warnings"]
