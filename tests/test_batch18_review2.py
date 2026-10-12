"""Round-2 review regressions: synthetic copies, fixed prompt evidence and UI recorders only."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

import scripts.audit_data_coverage as audit
from api.dependencies import get_db_conn
from app.answer_evidence_view import SHORT_WARNING_LABELS, notice_line
from app.course_detail_view import render_course_detail
from db.course_requisite_repository import CourseRequisiteRepository
from db.repository import CourseRepository
from eval.answer_checks import AnswerContext, check_answer, summarize
from llm.prompts.chat_v4 import PROMPT_TEMPLATE
from schemas.answer_evidence import RequisiteSectionEvidence
from schemas.course_requisites import RequisiteSection
from scripts.eval_answers_live import build_case, course_parts
from tests import test_audit_data_coverage as coverage
from tests import test_chat_structured_requisites as structured
from tests.ui_recorder import Recorder


@pytest.fixture
def coverage_copy(tmp_path):
    return coverage.build_seeded(tmp_path / "coverage.sqlite3")


@pytest.mark.parametrize("fault", ["one_valid_duplicate", "non_utf8_twin"])
def test_course_coverage_uses_the_year_rules_chat_can_read(coverage_copy, fault):
    if fault == "one_valid_duplicate":
        coverage.without_keys(coverage_copy, "course_requisite_documents")
        with coverage.writing(coverage_copy) as conn:
            twin = coverage.requisite("c-cs5800", "CS 5800", "Algorithms", prerequisite="CS 5010")
            coverage.put_requisite(conn, "c-cs5800", "2026-2027", twin, digest="0" * 64)
        expected_covered, expected_legacy = 3, 2
    else:
        with coverage.writing(coverage_copy) as conn:
            conn.execute("PRAGMA ignore_check_constraints=ON")
            conn.execute("INSERT INTO course_requisite_documents VALUES "
                         "('c-cs5800','2025-2026',CAST(x'7bff7d' AS TEXT),?)", ("0" * 64,))
        expected_covered, expected_legacy = 2, 3
    report = audit.build_report(coverage_copy, details=True)
    documents = coverage.section(report, "requisite_documents")
    assert coverage.section(report, "fields")["fields"]["prereqs"]["year_rules"] == expected_covered
    assert documents["in_scope_courses"]["with_usable_document_any_year"] == expected_covered
    assert documents["in_scope_courses"]["legacy_prereqs_without_usable_document"] == expected_legacy
    legacy = report["details"]["requisite_documents"]["legacy_prereqs_without_usable_document"]
    assert ("CS 5800" in json.dumps(legacy)) is (fault == "non_utf8_twin")
    if fault == "one_valid_duplicate":
        assert documents["counts"]["duplicate_rows"] == 2
    result = subprocess.run([sys.executable, str(Path(audit.__file__)), "--db-copy", str(coverage_copy), "--details"],
                            cwd=Path(__file__).parents[1], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == report


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_a_live_page_caveat_is_not_a_second_saved_copy_note(lang):
    note = ("These rules come from a saved copy of the catalog, not a live check. " if lang == "en" else
            "这些规则来自目录的存档副本，不是实时核对。")
    live = ("The link opens the page as it is now, not the saved copy, so it may show a later year's rule." if lang == "en"
            else "链接打开的是院系页现在的样子，不是存档副本，页面上可能已经是更新年份的规则。")
    context = AnswerContext(lang=lang)
    compliant = check_answer(note + live, context)
    assert compliant["saved_copy_mentions"] == 1
    assert summarize([compliant])["repeated_saved_copy"] == 0
    assert check_answer(note + note + live, context)["saved_copy_mentions"] == 2


@pytest.mark.parametrize("text", [
    "These rules come from a saved copy; the link opens the current catalog page, not the saved copy.",
    "These rules come from a saved copy, and the link opens the current catalog page rather than the saved copy.",
    "These rules come from a saved copy. The link (https://catalog.northeastern.edu/course-descriptions/cs/) "
    "opens the page as it is now, not the saved copy.",
])
def test_live_link_wording_does_not_erase_a_real_saved_copy_note(text):
    assert check_answer(text, AnswerContext(lang="en"))["saved_copy_mentions"] == 1


@pytest.mark.parametrize("sentinel", [
    "The link opens the current catalog page, which may already show a later year's rule",
    "say so once whenever you cite any recorded rule",
    "captured_at is when that catalog page was saved",
    "older recorded years may be left out",
    "requisites_differ_by_catalog_year means the recorded rules differ even when truncated clause_text looks identical",
    "every listed year has the same rule and requisites_differ_by_catalog_year is absent",
    "an empty or whitespace-only clause_text means the label has no text after it",
])
def test_prompt_review2_contract_is_explicit(sentinel):
    assert sentinel in " ".join(PROMPT_TEMPLATE.split())


def test_truncated_identical_heads_do_not_hide_different_rules(empty_db):
    head = "permission " * 70
    record = structured.seeded(empty_db, structured.document("2026-2027", prerequisite=head + "CS 5010"),
                               structured.document("2025-2026", prerequisite=head + "CS 5800"))
    evidence = structured.evidence_for(empty_db, record)
    projected = structured.projected(record, evidence)
    editions = projected["catalog_requisites"]["editions"]
    assert editions[0]["prerequisite"]["clause_text"] == editions[1]["prerequisite"]["clause_text"]
    assert all(item["prerequisite"]["clause_truncated"] for item in editions)
    assert "requisites_differ_by_catalog_year" in evidence.warnings
    assert "recorded rules differ even when truncated clause_text looks identical" in " ".join(PROMPT_TEMPLATE.split())


def test_whitespace_only_source_text_is_preserved(empty_db):
    document = structured.document()
    document.requisites.prerequisite = RequisiteSection(status="unparsed", raw_text="\n", reason="duplicate_section")
    record = structured.seeded(empty_db, document)
    section = structured.evidence_for(empty_db, record).requisites.editions[0].prerequisite
    assert section.clause_text == "\n" and section.clause_sha256 is not None
    assert "an empty or whitespace-only clause_text" in PROMPT_TEMPLATE


@pytest.mark.parametrize("route", ["/course/c-cs-5800", "/course/c-cs-5800/requisites"])
@pytest.mark.parametrize("invalid_twin", [False, True])
def test_duplicate_valid_year_is_dropped_without_breaking_course_routes(api_client, route, invalid_twin):
    conn = api_client.app.dependency_overrides[get_db_conn]()
    repository = CourseRequisiteRepository(conn)
    repository.store(structured.document("2026-2027"))
    repository.store(structured.document("2025-2026", prerequisite="CS 5004"))
    conn.executescript("CREATE TABLE loose AS SELECT * FROM course_requisite_documents; "
                       "DROP TABLE course_requisite_documents; "
                       "ALTER TABLE loose RENAME TO course_requisite_documents;")
    conn.execute("INSERT INTO course_requisite_documents SELECT * FROM course_requisite_documents "
                 "WHERE catalog_year='2026-2027'")
    if invalid_twin:
        conn.execute("UPDATE course_requisite_documents SET content_hash=? WHERE rowid="
                     "(SELECT MAX(rowid) FROM course_requisite_documents)", ("0" * 64,))
    response = api_client.get(route)
    assert response.status_code == 200
    bundle = response.json() if route.endswith("/requisites") else response.json()["course_requisites"]
    expected_years = ["2026-2027", "2025-2026"] if invalid_twin else ["2025-2026"]
    assert [item["catalog_year"] for item in bundle["documents"]] == expected_years
    assert bundle["unusable_records"] == (1 if invalid_twin else 2)
    assert "structured_requisites_unusable" in bundle["warnings"]
    meta, _ = structured.capture_chat(api_client)
    requisites = meta["results"][0]["answer_evidence"]["requisites"]
    assert [item["catalog_year"] for item in requisites["editions"]] == expected_years
    assert requisites["unusable_records"] == bundle["unusable_records"]


def test_course_detail_does_not_claim_its_selector_omits_older_years(api_client):
    conn = api_client.app.dependency_overrides[get_db_conn]()
    for year in range(2022, 2027):
        CourseRequisiteRepository(conn).store(structured.document(f"{year}-{year + 1}"))
    st = Recorder()
    render_course_detail(st, api_client.get("/course/c-cs-5800").json(), cid="review2")
    assert "更早年份没有列出" not in json.dumps(st.log, ensure_ascii=False)


def test_course_overview_does_not_present_three_year_chat_warnings_as_all_years(api_client):
    conn = api_client.app.dependency_overrides[get_db_conn]()
    CourseRequisiteRepository(conn).store(structured.document(corequisite="CS 5801 and CS 5802 or CS 5803"))
    st = Recorder()
    render_course_detail(st, api_client.get("/course/c-cs-5800").json(), cid="review2")
    captions = [text for kind, text, path in st.log if kind == "caption" and not path]
    assert all(SHORT_WARNING_LABELS[code] not in text for text in captions for code in structured.NEW_CODES)


@pytest.mark.parametrize("code", structured.NEW_CODES)
def test_short_requisite_labels_include_corequisites(code):
    assert "先修/共修" in notice_line([code])


@pytest.mark.parametrize("digest", ["A" * 64, "a" * 63])
def test_truncated_clause_digest_still_has_a_strict_format(digest):
    with pytest.raises(ValidationError):
        RequisiteSectionEvidence(status="unparsed", clause_text="cut", clause_truncated=True,
                                 unparsed_reason="unknown_condition", clause_sha256=digest)


@pytest.mark.parametrize("reason", ["", "x" * 101])
def test_unparsed_reason_remains_nonempty_and_bounded(reason):
    with pytest.raises(ValidationError):
        RequisiteSectionEvidence(status="unparsed", clause_text="raw", unparsed_reason=reason)


def test_eval_discards_a_malformed_year_rules_block(api_client):
    payload = api_client.get("/course/c-cs-5800").json()
    payload["answer_evidence"]["requisites"] = {"storage": "available", "editions": [{"catalog_year": "bad"}]}
    assert course_parts(payload)[2] is None
    question = {"qid": "R2", "lang": "en", "query": "Algo", "course_ids": ["c-cs-5800"], "route": "alias", "notices": []}
    prompt, _ = build_case(question, {"c-cs-5800": payload})
    assert structured.courses_json(prompt)[0]["catalog_requisites"] is None


def test_a_failed_requisite_section_keeps_fields_and_warnings_not_checked(coverage_copy, monkeypatch):
    def broken(self):
        raise KeyError("synthetic-section-failure")

    monkeypatch.setattr(audit._Audit, "requisite_documents", broken)
    report = audit.build_report(coverage_copy)
    fields = coverage.section(report, "fields")
    assert fields["fields"]["prereqs"] == {"status": "not_checked", "code": "requisite_documents_not_checked"}
    assert fields["answer_warnings"] == {"status": "not_checked", "code": "requisite_documents_not_checked"}


def test_report_rules_describe_the_actual_answer_path_and_missing_table_case():
    rules = audit.RULES
    assert "generated_json alone" not in rules["courses"]["text_not_utf8"]
    assert "primary_code" in rules["courses"]["text_not_utf8"]
    assert "primary_name" in rules["courses"]["text_not_utf8"]
    assert "although its table exists" in rules["fields"]["fields"]
    assert "year documents were read as well" not in rules["fields"]["by_department"]
    assert "the report uses none" not in rules["requisite_documents"]["duplicate_rows"]
    for name in ("with_usable_document_any_year", "legacy_prereqs_without_usable_document"):
        assert "chat's year rules" in rules["requisite_documents"][name]


def test_corrupt_requisite_data_page_degrades_repository_chat_and_course_routes(tmp_path, api_client):
    path = tmp_path / "corrupt.sqlite3"
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript((Path(__file__).parents[1] / "db/init.sql").read_text(encoding="utf-8"))
    record = structured.course()
    CourseRepository(conn).insert(record, raw_text="Algorithms")
    CourseRequisiteRepository(conn).store(structured.document())
    conn.commit()
    root_page = conn.execute("SELECT rootpage FROM sqlite_master WHERE name='course_requisite_documents'").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    conn.close()
    with path.open("r+b") as handle:
        handle.seek((root_page - 1) * page_size)
        handle.write(b"\xff" * page_size)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        with pytest.raises(sqlite3.DatabaseError) as failure:
            conn.execute("SELECT document FROM course_requisite_documents").fetchall()
        assert not isinstance(failure.value, sqlite3.OperationalError)
        batch = CourseRequisiteRepository(conn).read_batch([record.course_id])
        assert record.course_id in batch.unreadable
        api_client.app.dependency_overrides[get_db_conn] = lambda: conn
        meta, _ = structured.capture_chat(api_client, {"query": "CS 5800"})
        assert meta["results"][0]["answer_evidence"]["requisites"]["storage"] == "schema_unusable"
        detail = api_client.get("/course/c-cs-5800")
        assert detail.status_code == 200
        assert "structured_requisite_schema_unusable" in detail.json()["course_requisites"]["warnings"]
        assert api_client.get("/course/c-cs-5800/requisites").status_code == 200
    finally:
        conn.close()
