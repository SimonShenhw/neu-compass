"""No auto-DDL/latest edition or legacy-logic fallbacks on course detail."""

from datetime import datetime, timezone

import pytest

from db.course_requisite_repository import CourseRequisiteRepository
from schemas.course_requisite_document import CourseRequisiteDocument
from scrapers.course_requisites import parse_clause


def source_document(year="2026-2027", raw="(CS 5001 or CS 5004 with a minimum grade of B-); DS 5110"):
    return CourseRequisiteDocument(course_id="c-cs-5800", course_code="CS 5800", course_name="Algorithms", catalog_year=year,
        source={"url": "https://catalog.northeastern.edu/course-descriptions/cs/", "catalog_year": year,
                "captured_at": datetime(2026, 10, 1, tzinfo=timezone.utc), "sha256": "b" * 64, "byte_count": 10, "page_title": "Computer Science (CS)"},
        requisites={"prerequisite": parse_clause(raw), "corequisite": parse_clause("CS 5005")})


def test_course_detail_reports_structured_requisite_state_without_inventing_rules(api_client):
    response = api_client.get("/course/c-cs-5800")
    assert response.status_code == 200
    bundle = response.json()["course_requisites"]
    assert bundle["documents"] == []
    assert "structured_requisites_missing" in bundle["warnings"]


def test_exact_requisite_edition_endpoint_exists_and_does_not_guess(api_client):
    response = api_client.get("/course/c-cs-5800/requisites", params={"catalog_year": "2024-2025"})
    assert response.status_code == 200
    assert response.json()["documents"] == []


def test_old_database_course_get_never_creates_requisite_table(api_client, empty_db):
    empty_db.execute("DROP TABLE IF EXISTS course_requisite_documents")
    response = api_client.get("/course/c-cs-5800")
    assert response.status_code == 200
    assert response.json()["course_requisites"]["schema_available"] is False
    assert not empty_db.execute("SELECT 1 FROM sqlite_master WHERE name='course_requisite_documents'").fetchone()


def test_detail_and_exact_edition_keep_and_or_grade_and_corequisite(api_client, empty_db):
    repo = CourseRequisiteRepository(empty_db)
    repo.store(source_document())
    repo.store(source_document("2025-2026", "CS 5010 with a minimum grade of C- (Graduate)"))
    body = api_client.get("/course/c-cs-5800").json()
    assert body["schema_version"] == "1.1" and body["prerequisites"] == []
    assert len(body["course_requisites"]["documents"]) == 2
    selected = api_client.get("/course/c-cs-5800/requisites", params={"catalog_year": "2026-2027"}).json()
    assert len(selected["documents"]) == 1 and selected["has_any_stored_records"] is True
    document = selected["documents"][0]
    assert document["campus"] is None
    rule = document["requisites"]["prerequisite"]["rule"]
    assert rule["kind"] == "all_of" and rule["children"][0]["kind"] == "any_of"
    assert rule["children"][0]["children"][1]["minimum_grade"] == "B-"
    assert document["requisites"]["corequisite"]["rule"]["course_code"] == "CS 5005"
    missing = api_client.get("/course/c-cs-5800/requisites", params={"catalog_year": "2024-2025"}).json()
    assert missing["documents"] == [] and missing["has_any_stored_records"] is True


@pytest.mark.parametrize("year", ["latest", "2026", "2026-2028", "2027-2026", "2026-2027?campus=boston"])
def test_requisite_endpoint_rejects_invalid_edition_instead_of_selecting_latest(api_client, year):
    assert api_client.get("/course/c-cs-5800/requisites", params={"catalog_year": year}).status_code == 422


def test_requisite_endpoint_missing_course_is_404_and_old_schema_is_explicit(api_client, empty_db):
    assert api_client.get("/course/missing/requisites").status_code == 404
    empty_db.execute("DROP TABLE course_requisite_documents")
    response = api_client.get("/course/c-cs-5800/requisites", params={"catalog_year": "2026-2027"})
    assert response.status_code == 200 and response.json()["schema_available"] is False


def test_corrupt_document_is_not_returned_as_none_required_or_erased_from_state(api_client, empty_db):
    CourseRequisiteRepository(empty_db).store(source_document())
    empty_db.execute("UPDATE course_requisite_documents SET content_hash='bad'")
    response = api_client.get("/course/c-cs-5800").json()["course_requisites"]
    assert response["documents"] == [] and response["unusable_records"] == 1
    assert response["has_any_stored_records"] is True
    assert "structured_requisites_unusable" in response["warnings"]


@pytest.mark.parametrize("raw,status", [(None, "not_listed"), ("CS 5001 or permission of instructor", "unparsed")])
def test_detail_preserves_unknown_status_not_empty_successful_rule(api_client, empty_db, raw, status):
    CourseRequisiteRepository(empty_db).store(source_document(raw=raw))
    section = api_client.get("/course/c-cs-5800").json()["course_requisites"]["documents"][0]["requisites"]["prerequisite"]
    assert section["status"] == status and section["rule"] is None and section["raw_text"] == raw
