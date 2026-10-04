"""Description evidence is not an enrollment rule or automatic approval."""

import hashlib
import json

import httpx
import pytest
from bs4 import BeautifulSoup

from db.connection import connect
from db.course_requisite_repository import CourseRequisiteRepository, content_hash
from db.program_plan_repository import ProgramPlanRepository
from schemas.course_description_evidence import CourseDescriptionEvidence
from schemas.course_requisite_document import CourseRequisiteDocument
from scrapers.course_description_evidence import extract_description_evidence
from scripts.audit_course_requisites import build_report
from scripts.capture_course_requisites import capture_departments
from scripts.sync_course_requisites import sync_requisites
from tests.test_course_requisite_sources import archive, source_html
from tests.test_course_requisite_storage import document, target, runtime, original_rows


def test_report_preserves_all_description_paragraphs_without_turning_permission_into_rule(tmp_path):
    content = source_html().replace(
        b'<p class="cb_desc">Approval outside requisite clauses is not evaluated.</p>',
        b'<p class="cb_desc">Studies algorithms.</p><p class="cb_desc">'
        b'Students who do not meet course prerequisites may seek permission of instructor.</p>',
    )
    manifest, directory, _ = archive(tmp_path, content)
    item = build_report(manifest, directory, ["CS 5004"])["records"][0]
    evidence = item["description_evidence"]
    assert evidence["status"] == "review_needed"
    assert evidence["paragraphs"] == ["Studies algorithms.", "Students who do not meet course prerequisites may seek permission of instructor."]
    assert evidence["candidates"] == [{"paragraph_index": 1, "markers": ["permission"]}]
    assert item["requisites"]["prerequisite"]["rule"]["kind"] == "all_of"


def test_program_context_old_schema_is_explicit_and_never_auto_creates_table(empty_db):
    empty_db.execute("DROP TABLE program_plans")
    context = ProgramPlanRepository(empty_db).course_context("CS 5004", "2026-2027")
    assert context.schema_available is False and context.plans == []
    assert not ProgramPlanRepository(empty_db).available()


@pytest.mark.parametrize("text,status,markers", [
    ("Requires admission to MS program or completion of all transition courses.", "review_needed", ["admission"]),
    ("Students may work in teams with the permission of the instructor.", "review_needed", ["permission"]),
    ("No approval is required for this assignment.", "review_needed", ["approval"]),
    ("Covers a working approval process in financial systems.", "review_needed", ["approval"]),
    ("Restricted to eligible, admitted students with consent.", "review_needed", ["permission", "admission", "eligibility", "restriction"]),
    ("Registration requires qualified students to enroll.", "review_needed", ["registration", "qualification"]),
    ("Requires programming experience.", "no_keyword_match", []),
    ("Permissionless software and enterprise-grade architecture.", "no_keyword_match", []),
    ("APPROVED experiential work for eligible students.", "review_needed", ["approval", "eligibility"]),
])
def test_keyword_scan_preserves_negation_optional_and_false_positives_as_candidates(text, status, markers):
    evidence = CourseDescriptionEvidence.from_paragraphs([text])
    assert evidence.status == status and evidence.paragraphs == [text]
    assert [item.markers for item in evidence.candidates] == ([markers] if markers else [])
    assert "rule" not in evidence.model_dump() and "eligible" not in evidence.model_dump()


@pytest.mark.parametrize("html", ["", '<p class="cb_desc"> \n </p>'])
def test_missing_or_blank_description_is_not_no_conditions(html):
    result = extract_description_evidence(BeautifulSoup(html, "html.parser"))
    assert result.status == "not_listed" and result.paragraphs == []


def test_all_paragraphs_normalized_in_order_and_html_kept_as_text():
    block = BeautifulSoup('<p class="cb_desc"> Study\n  data. </p><p class="cb_desc">'
        'No <b>approval</b> required. &lt;script&gt;x()&lt;/script&gt;</p>', "html.parser")
    result = extract_description_evidence(block)
    assert result.paragraphs == ["Study data.", "No approval required. <script>x()</script>"]
    assert result.candidates[0].paragraph_index == 1


@pytest.mark.parametrize("kind", ["status", "index", "missing", "wrong-marker", "duplicate", "blank", "whitespace", "paragraph-size", "total-size", "count", "extra", "version"])
def test_invalid_or_reinterpreted_description_evidence_is_rejected(kind):
    data = CourseDescriptionEvidence.from_paragraphs(["Permission is not required."]).model_dump(mode="json")
    if kind == "status":
        data["status"] = "no_keyword_match"
    elif kind == "index":
        data["candidates"][0]["paragraph_index"] = 1
    elif kind == "missing":
        data["candidates"] = []
    elif kind == "wrong-marker":
        data["candidates"][0]["markers"] = ["admission"]
    elif kind == "duplicate":
        data["candidates"] *= 2
    elif kind in ["blank", "whitespace"]:
        data["paragraphs"] = ["" if kind == "blank" else "  Permission is not required."]
    elif kind == "paragraph-size":
        data["paragraphs"] = ["x" * 20_001]
    elif kind == "total-size":
        data["paragraphs"] = ["x" * 20_000] * 4
    elif kind == "count":
        data["paragraphs"] = ["x"] * 31
    elif kind == "extra":
        data["eligible"] = True
    else:
        data["format_version"] = "2"
    with pytest.raises(ValueError):
        CourseDescriptionEvidence.model_validate(data)


def test_old_05c2_document_hash_is_independently_constructed_and_idempotent(empty_db):
    target(empty_db)
    old = document().model_dump(mode="json")
    old.pop("description_evidence")
    old.pop("credit_hours")  # This field did not exist in the 05C-2 shape either.
    old_content = {key: value for key, value in old.items() if key != "imported_at"}
    digest = hashlib.sha256(json.dumps(old_content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    raw = json.dumps(old, ensure_ascii=False)
    empty_db.execute("INSERT INTO course_requisite_documents VALUES(?,?,?,?)", ("target", "2026-2027", raw, digest))
    repo = CourseRequisiteRepository(empty_db)
    restored = repo.list_for_course("target").documents[0]
    assert restored.description_evidence is None and content_hash(restored) == digest
    assert repo.store(restored) is False
    assert empty_db.execute("SELECT document FROM course_requisite_documents").fetchone()[0] == raw
    enhanced = CourseRequisiteDocument.model_validate({**old, "description_evidence":
        CourseDescriptionEvidence.from_paragraphs(["Requires admission to MS program."]).model_dump(mode="json")})
    assert content_hash(enhanced) != digest and repo.store(enhanced) is True
    assert repo.store(enhanced) is False


def test_store_rejects_mutated_nested_evidence_even_if_hash_would_be_recomputed(empty_db):
    target(empty_db)
    data = document().model_dump(mode="json")
    data["description_evidence"] = CourseDescriptionEvidence.from_paragraphs(["Approval required."]).model_dump(mode="json")
    new = CourseRequisiteDocument.model_validate(data)
    new.description_evidence.candidates.clear()  # Bypass construction deliberately.
    with pytest.raises(ValueError):
        CourseRequisiteRepository(empty_db).store(new)
    assert empty_db.execute("SELECT COUNT(*) FROM course_requisite_documents").fetchone()[0] == 0


@pytest.mark.parametrize('with_feedback_schema', [True, False])
def test_sync_from_verified_archive_keeps_description_separate_and_other_rows_unchanged(runtime, with_feedback_schema):
    path, manifest, directory = runtime
    conn = connect(path)
    try:
        if not with_feedback_schema:
            conn.execute('DROP TABLE answer_feedback')
            conn.execute('DROP TABLE chat_answers')
            conn.execute("DELETE FROM schema_versions WHERE version='1.7'")
            conn.commit()
        versions_before = {r['version'] for r in conn.execute('SELECT version FROM schema_versions')}
        schema_before = [tuple(r) for r in conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE tbl_name != 'course_requisite_documents' ORDER BY type,name")]
    finally:
        conn.close()
    content = source_html().replace(b"Approval outside requisite clauses is not evaluated.",
        b"Requires admission to MS program or completion of all transition courses.")
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content, headers={"content-type": "text/html"}))) as client:
        captured = capture_departments(["cs"], "2026-2027", directory, client=client)
    manifest.write_text(json.dumps(captured))
    before, rows = path.read_bytes(), original_rows(path)
    assert sync_requisites(path, manifest, directory, ["CS 5004"])["stored"] == 0
    assert before == path.read_bytes()
    assert sync_requisites(path, manifest, directory, ["CS 5004"], commit=True)["stored"] == 1
    conn = connect(path)
    try:
        new = CourseRequisiteRepository(conn).list_for_course("design").documents[0]
        assert new.description_evidence.status == "review_needed"
        assert new.description_evidence.paragraphs == ["Requires admission to MS program or completion of all transition courses."]
        assert new.requisites.prerequisite.rule.kind == "all_of"
        assert conn.execute("SELECT version FROM schema_versions WHERE version='1.6'").fetchone()
        # Only the explicit requisite-table migration is allowed here. Preserve
        # a feedback schema if present; never install it into an older copy.
        assert {r['version'] for r in conn.execute('SELECT version FROM schema_versions')} == versions_before | {'1.6'}
        assert [tuple(r) for r in conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE tbl_name != 'course_requisite_documents' ORDER BY type,name")] == schema_before
    finally:
        conn.close()
    assert original_rows(path) == rows
    assert sync_requisites(path, manifest, directory, ["CS 5004"], commit=True)["stored"] == 0


def test_description_over_budget_fails_whole_report_no_truncation(tmp_path):
    content = source_html().replace(b"Approval outside requisite clauses is not evaluated.", b"x" * 20_001)
    manifest, directory, _ = archive(tmp_path, content)
    with pytest.raises(ValueError):
        build_report(manifest, directory, ["CS 5004"])
