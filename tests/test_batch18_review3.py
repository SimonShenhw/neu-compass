"""Third-review regressions: synthetic databases and evidence recorders only."""

import json

import pytest

import scripts.audit_data_coverage as audit
from api.dependencies import get_db_conn
from app.answer_evidence_view import WARNING_LABELS, render_answer_evidence
from app.course_detail_view import render_course_detail
from db.course_requisite_repository import CourseRequisiteRepository
from eval.answer_checks import AnswerContext, check_answer
from llm.prompts.chat_v4 import PROMPT_TEMPLATE
from tests import test_audit_data_coverage as coverage
from tests import test_chat_structured_requisites as structured
from tests.ui_recorder import Recorder

URL = "https://catalog.northeastern.edu/course-descriptions/cs/"
NOTES = {"en": "These rules come from a saved copy of the catalog, not a live check. ",
         "zh": "这些规则来自目录的存档副本，不是实时核对。"}
LIVE_CASES = [
    ("en", f"[NEU course catalog]({URL}) opens the current page, not the saved copy."),
    ("en", f"{URL} opens the current page, not the saved copy."),
    ("en", "The link goes to the current page, not the saved copy."),
    ("en", "The link takes you to the current catalog page, not the saved copy."),
    ("en", "The link opens the current page instead of the saved copy."),
    ("en", "The link opens the live page, which isn't the saved copy."),
    ("en", "The link opens the live page, which is not the saved copy."),
    ("en", "The link opens the page as it is today, not the saved copy."),
    ("en", "Opening the link shows the current page, not the saved copy."),
    ("en", "The link opens the current page rather than the saved copy."),
    ("en", "The link points to the current page, not the saved copy."),
    ("en", "The URL opens the current page, not the saved copy."),
    ("zh", "链接打开的是当前页面，并非存档副本。"),
    ("zh", "链接打开的是当前页面（非存档副本）。"),
    ("zh", "链接指向目前的院系页面，不是存档副本。"),
    ("zh", "该链接指向最新的目录页，而非存档副本。"),
    ("zh", "打开链接看到的是当前页面，不是存档副本。"),
    ("zh", "点开链接会看到当前页面，不是存档副本。"),
    ("zh", f"[NEU 官方课程目录]({URL})打开的是当前页面，不是存档副本。"),
    ("zh", "链接打开的是当前页面，不是那份存档副本。"),
]


@pytest.mark.parametrize("lang,live", LIVE_CASES)
def test_live_link_variants_do_not_repeat_the_archived_source_note(lang, live):
    note = NOTES[lang]
    assert check_answer(note + live, AnswerContext(lang=lang))["saved_copy_mentions"] == 1
    assert check_answer(note + note + live, AnswerContext(lang=lang))["saved_copy_mentions"] == 2


@pytest.mark.parametrize("lang,live", [
    ("en", "The link opens the current page rather than the saved copy."),
    ("en", "The link points to the current page, not the saved copy."),
    ("en", "The URL opens the current page, not the saved copy."),
    ("zh", "链接打开的是当前页面，而非存档副本。"),
])
def test_previously_supported_aliases_have_independent_saved_copy_tests(lang, live):
    assert check_answer(NOTES[lang] + live, AnswerContext(lang=lang))["saved_copy_mentions"] == 1


@pytest.mark.parametrize("text", [
    "These rules come from a saved copy. Not the saved copy: consult your advisor.",
    "These rules come from a saved copy. The link opens the current page, not the saved copy; "
    "these rules still come from a saved copy.",
    "这些规则来自目录的存档副本。链接打开的是当前页面，并非存档副本，这些规则仍来自存档副本。",
])
def test_live_exclusion_keeps_actual_notes_and_requires_a_live_link_context(text):
    assert check_answer(text, AnswerContext(lang="zh" if "规则" in text else "en"))["saved_copy_mentions"] == 2


@pytest.mark.parametrize("fault,covered", [("one_valid", 2), ("two_valid", 1), ("non_utf8", 1),
                                          ("non_utf8_other_year", 1)])
def test_annual_course_counts_follow_usable_rules_not_row_categories(tmp_path, fault, covered):
    path = coverage.build_seeded(tmp_path / "coverage.sqlite3")
    coverage.without_keys(path, "course_requisite_documents")
    with coverage.writing(path) as conn:
        document = coverage.requisite("c-cs5800", "CS 5800", "Algorithms")
        if fault.startswith("non_utf8"):
            conn.execute("INSERT INTO course_requisite_documents VALUES "
                         "('c-cs5800',?,CAST(x'7bff7d' AS TEXT),?)",
                         ("2025-2026" if fault == "non_utf8_other_year" else "2026-2027", "0" * 64))
        else:
            coverage.put_requisite(conn, "c-cs5800", "2026-2027", document,
                                   digest="0" * 64 if fault == "one_valid" else None)
    report = audit.build_report(path, details=True)
    documents = coverage.section(report, "requisite_documents")
    assert documents["by_catalog_year"]["2026-2027"]["courses_in_scope_covered"] == covered
    assert documents["by_department"]["CS"]["by_catalog_year"]["2026-2027"]["with_usable_document"] == covered
    assert documents["in_scope_courses"]["with_usable_document_any_year"] == covered + 1
    assert coverage.section(report, "fields")["fields"]["prereqs"]["year_rules"] == covered + 1
    # Both twins remain in row-quality statistics even if one is served.
    assert documents["counts"]["duplicate_rows"] == (0 if fault == "non_utf8_other_year" else
                                                   (1 if fault == "non_utf8" else 2))


def test_annual_coverage_includes_all_years_beyond_the_chat_cap(tmp_path):
    path = coverage.build_seeded(tmp_path / "years.sqlite3")
    with coverage.writing(path) as conn:
        for year in range(2021, 2026):
            edition = f"{year}-{year + 1}"
            coverage.put_requisite(conn, "c-cs5800", edition,
                                   coverage.requisite("c-cs5800", "CS 5800", "Algorithms", year=edition))
    report = audit.build_report(path)
    documents = coverage.section(report, "requisite_documents")
    for year in range(2021, 2027):
        edition = f"{year}-{year + 1}"
        assert documents["by_catalog_year"][edition]["courses_in_scope_covered"] >= 1
        assert documents["by_department"]["CS"]["by_catalog_year"][edition]["with_usable_document"] >= 1


def test_warning_rule_text_keeps_both_required_inputs():
    assert "catalog was compared and (the year rules were checked or their table is missing)" in (
        audit.RULES["fields"]["by_department"])


@pytest.mark.parametrize("code", structured.NEW_CODES)
def test_course_source_expander_retains_full_requisite_warnings(api_client, code):
    conn = api_client.app.dependency_overrides[get_db_conn]()
    CourseRequisiteRepository(conn).store(structured.document())
    payload = api_client.get("/course/c-cs-5800").json()
    payload["answer_evidence"]["warnings"] = [code]
    st = Recorder()
    render_course_detail(st, payload, cid="review3")
    captions = [text for kind, text, _ in st.under("📎 来源与说明（数据从哪来、缺了什么）") if kind == "caption"]
    assert WARNING_LABELS[code] in captions
    assert "先修/共修" in WARNING_LABELS[code]


def test_answer_cards_show_years_by_default(api_client):
    conn = api_client.app.dependency_overrides[get_db_conn]()
    CourseRequisiteRepository(conn).store(structured.document())
    evidence = api_client.get("/course/c-cs-5800").json()["answer_evidence"]
    st = Recorder()
    render_answer_evidence(st, evidence)
    assert any("课程块原文" in str(text) and "2026-2027" in str(text) for _, text, _ in st.log)


@pytest.mark.parametrize("sentence", [
    "say so once per answer (not once per course or rule) whenever you cite any recorded rule",
    "Never say those years have the same rule when this warning is present; "
    "the comparison used the full recorded clauses, not just the shown text.",
])
def test_prompt_once_per_answer_and_full_difference_guard_are_pinned(sentence):
    assert sentence in " ".join(PROMPT_TEMPLATE.split())


@pytest.mark.parametrize("route", ["/course/c-cs-5800", "/course/c-cs-5800/requisites"])
def test_unreadable_course_identity_degrades_both_get_routes(api_client, route):
    conn = api_client.app.dependency_overrides[get_db_conn]()
    CourseRequisiteRepository(conn).store(structured.document())
    conn.execute("UPDATE courses SET primary_name=CAST(x'416c676fff' AS TEXT) WHERE course_id='c-cs-5800'")
    meta, _ = structured.capture_chat(api_client)
    assert meta["results"][0]["answer_evidence"]["requisites"]["storage"] == "schema_unusable"
    response = api_client.get(route)
    assert response.status_code == 200
    listing = response.json() if route.endswith("/requisites") else response.json()["course_requisites"]
    assert listing["documents"] == []
    assert "structured_requisite_schema_unusable" in listing["warnings"]
    assert "Algo" not in json.dumps(listing)
