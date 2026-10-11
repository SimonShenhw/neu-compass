"""OPT-04 step 1: year-scoped prerequisite rules reach the chat answer as sourced evidence.

Synthetic in-memory databases only; the model is a stand-in that records the prompt. Not a live
answer-quality check (that needs real model calls, which this batch does not make).
中文：OPT-04 第一步：按年度记录的先修规则作为有来源的证据进入聊天回答。只用内存中的合成库，
模型是记录提示词的替身；不是真实回答质量检查。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from api.dependencies import get_chat_stream_fn, get_db_conn
from app.answer_evidence_view import (
    COMPACT_WARNINGS, SHORT_WARNING_LABELS, WARNING_LABELS, evidence_summary, notice_line, requisite_years_line,
)
from db.course_requisite_repository import BASE_WARNINGS, CourseRequisiteRepository, content_hash
from db.repository import CourseRepository
from eval.answer_checks import CODES
from llm.prompts.chat_v4 import PROMPT_TEMPLATE, format_courses_block
from rag.answer_evidence import build_answer_evidence, course_answer_evidence, requisite_evidence
from rag.retriever import SearchHit
from schemas.answer_evidence import CLAUSE_LIMIT, MAX_REQUISITE_EDITIONS, RequisiteEvidence
from schemas.course import Course
from schemas.course_requisite_document import CourseRequisiteDocument
from schemas.course_requisite_source import CourseRequisiteSource
from scrapers.course_requisites import parse_clause

NESTED = "(CS 5001 or CS 5004 with a minimum grade of B-); DS 5110 (may be taken concurrently)"
NEW_CODES = ("requisites_differ_by_catalog_year", "requisite_clause_unparsed", "structured_requisites_unusable")
CS_PAGE = "https://catalog.northeastern.edu/course-descriptions/cs/"


def document(year="2026-2027", prerequisite=NESTED, corequisite=None, *, course_id="c-cs-5800", code="CS 5800",
             name="Algorithms"):
    source = CourseRequisiteSource(url=CS_PAGE, catalog_year=year, captured_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                                   sha256="a" * 64, byte_count=10, page_title="Computer Science (CS)")
    return CourseRequisiteDocument(course_id=course_id, course_code=code, course_name=name, catalog_year=year,
                                   source=source, requisites={"prerequisite": parse_clause(prerequisite),
                                                              "corequisite": parse_clause(corequisite)})


def course(**updates):
    return Course(**{"course_id": "c-cs-5800", "primary_code": "CS 5800", "primary_name": "Algorithms", **updates})


def seeded(conn, *documents, **updates):
    record = course(**updates)
    CourseRepository(conn).insert(record, raw_text="")
    repo = CourseRequisiteRepository(conn)
    for item in documents:
        assert repo.store(item)
    return record


def evidence_for(conn, record):
    return build_answer_evidence(conn, [record])[record.course_id]


def projected(record, evidence):
    return json.loads(format_courses_block([SearchHit(course=record, score=1)], {record.course_id: evidence}))[0]


# --- evidence -----------------------------------------------------------------------------------

def test_a_year_rule_closes_both_prerequisite_gaps(empty_db):
    """With a usable year document the AND/OR logic is known and the rule is not missing, even when
    the flat list is empty; without one, both gaps stay exactly as before."""
    flat = seeded(empty_db, document(), prereqs=["CS 5004", "CS 5001"])
    evidence = evidence_for(empty_db, flat)
    assert "prerequisite_logic_unavailable" not in evidence.warnings
    assert [edition.catalog_year for edition in evidence.requisites.editions] == ["2026-2027"]
    assert evidence.requisites.storage == "available"

    empty_db.execute("DELETE FROM courses")
    empty = seeded(empty_db, document())
    assert "prereqs" not in evidence_for(empty_db, empty).missing_fields

    empty_db.execute("DELETE FROM courses")
    without = seeded(empty_db, prereqs=["CS 5004"])
    evidence = evidence_for(empty_db, without)
    assert evidence.requisites.editions == []
    assert "prerequisite_logic_unavailable" in evidence.warnings
    assert evidence.warnings == course_answer_evidence(without).warnings  # The pre-4.4 output.
    empty_db.execute("DELETE FROM courses")
    nothing = seeded(empty_db)
    assert "prereqs" in evidence_for(empty_db, nothing).missing_fields


def test_editions_are_listed_newest_first_and_the_rest_counted(empty_db):
    years = ["2025-2026", "2028-2029", "2026-2027", "2024-2025", "2027-2028"]
    record = seeded(empty_db, *(document(year) for year in years))
    requisites = evidence_for(empty_db, record).requisites
    assert [edition.catalog_year for edition in requisites.editions] == ["2028-2029", "2027-2028", "2026-2027"]
    assert len(requisites.editions) == MAX_REQUISITE_EDITIONS
    assert requisites.editions_omitted == 2
    assert requisites.unusable_records == 0


@pytest.mark.parametrize(("older", "differ"), [(NESTED, False), ("CS 5004", True), (None, True)])
def test_years_with_different_rules_are_flagged(empty_db, older, differ):
    record = seeded(empty_db, document("2026-2027"), document("2025-2026", prerequisite=older))
    warnings = evidence_for(empty_db, record).warnings
    assert ("requisites_differ_by_catalog_year" in warnings) is differ
    assert "requisite_clause_unparsed" not in warnings


def test_a_corequisite_change_alone_is_a_difference(empty_db):
    record = seeded(empty_db, document("2026-2027", corequisite="CS 5801"), document("2025-2026"))
    assert "requisites_differ_by_catalog_year" in evidence_for(empty_db, record).warnings


def test_the_same_rule_in_other_words_is_not_a_difference(empty_db):
    """Parsed clauses are compared by their trees: "A; B" and "A and B" are one rule."""
    record = seeded(empty_db, document("2026-2027"), document("2025-2026", prerequisite=NESTED.replace("); ", ") and ")))
    evidence = evidence_for(empty_db, record)
    newer, older = (edition.prerequisite for edition in evidence.requisites.editions)
    assert newer.rule == older.rule and newer.clause_text != older.clause_text
    assert "requisites_differ_by_catalog_year" not in evidence.warnings


@pytest.mark.parametrize(("oldest", "code"), [("CS 5004", "requisites_differ_by_catalog_year"),
                                              ("CS 5004 and CS 5010 or CS 5600", "requisite_clause_unparsed")])
def test_every_listed_year_is_checked_not_only_the_newest(empty_db, oldest, code):
    record = seeded(empty_db, document("2026-2027"), document("2025-2026"), document("2024-2025", prerequisite=oldest))
    evidence = evidence_for(empty_db, record)
    assert [edition.catalog_year for edition in evidence.requisites.editions] == ["2026-2027", "2025-2026", "2024-2025"]
    assert code in evidence.warnings


@pytest.mark.parametrize(("older", "differ"), [("CS 5004 and CS 5010 or CS 5600", False),
                                               ("CS 5004 and CS 5010 or CS 5700", True)])
def test_unparsed_clauses_are_compared_by_their_text(empty_db, older, differ):
    record = seeded(empty_db, document("2026-2027", prerequisite="CS 5004 and CS 5010 or CS 5600"),
                    document("2025-2026", prerequisite=older))
    warnings = evidence_for(empty_db, record).warnings
    assert ("requisites_differ_by_catalog_year" in warnings) is differ
    assert "requisite_clause_unparsed" in warnings


def test_an_unparsed_corequisite_is_flagged_too(empty_db):
    record = seeded(empty_db, document(corequisite="CS 5801 and CS 5802 or CS 5803"))
    evidence = evidence_for(empty_db, record)
    assert evidence.requisites.editions[0].corequisite.status == "unparsed"
    assert "requisite_clause_unparsed" in evidence.warnings


def test_an_unparsed_clause_keeps_its_text_and_no_tree(empty_db):
    mixed = "CS 5004 and CS 5010 or CS 5600"  # AND and OR at one level: precedence is not assumed.
    record = seeded(empty_db, document(prerequisite=mixed))
    evidence = evidence_for(empty_db, record)
    section = evidence.requisites.editions[0].prerequisite
    assert (section.status, section.rule, section.clause_text) == ("unparsed", None, mixed)
    assert section.unparsed_reason == parse_clause(mixed).reason
    assert "requisite_clause_unparsed" in evidence.warnings
    assert "requisites_differ_by_catalog_year" not in evidence.warnings


def test_an_empty_clause_is_kept_as_recorded(empty_db):
    """A label with no clause after it is stored as unparsed with empty text (empty and missing stay distinct); the
    answer gets that state, not a failed answer."""
    record = seeded(empty_db, document(prerequisite=""))
    evidence = evidence_for(empty_db, record)
    section = evidence.requisites.editions[0].prerequisite
    assert (section.status, section.rule, section.clause_text, section.unparsed_reason) == (
        "unparsed", None, "", "empty_clause")
    assert "requisite_clause_unparsed" in evidence.warnings
    assert projected(record, evidence)["catalog_requisites"]["editions"][0]["prerequisite"] == {
        "status": "unparsed", "clause_text": "", "clause_truncated": False}


def test_a_document_the_block_cannot_carry_costs_its_edition_not_the_answer(empty_db, monkeypatch):
    """The next usable edition takes its place within the limit, and the document is counted unusable."""
    import rag.answer_evidence as answer_evidence  # noqa: PLC0415

    record = seeded(empty_db, *(document(f"{year}-{year + 1}") for year in range(2023, 2027)))
    project = answer_evidence.requisite_edition

    def refuse_newest(item):
        if item.catalog_year == "2026-2027":
            raise ValueError("not representable")
        return project(item)

    monkeypatch.setattr(answer_evidence, "requisite_edition", refuse_newest)
    evidence = evidence_for(empty_db, record)
    assert [edition.catalog_year for edition in evidence.requisites.editions] == ["2025-2026", "2024-2025", "2023-2024"]
    assert (evidence.requisites.editions_omitted, evidence.requisites.unusable_records) == (0, 1)
    assert "structured_requisites_unusable" in evidence.warnings


@pytest.mark.parametrize(("tail", "differ"), [(" and CS 5010", True), (" and CS 5800", False)])
def test_long_unparsed_clauses_are_compared_whole(empty_db, tail, differ):
    """Years are compared by the whole recorded text (its digest), not by the cut text the prompt gets."""
    head = " ".join(["permission"] * 70)  # Longer than the cut; not the grammar, so kept as an unparsed clause.
    record = seeded(empty_db, document("2026-2027", prerequisite=head + tail),
                    document("2025-2026", prerequisite=head + " and CS 5800"))
    evidence = evidence_for(empty_db, record)
    newer, older = (edition.prerequisite for edition in evidence.requisites.editions)
    assert newer.status == older.status == "unparsed" and newer.clause_truncated and older.clause_truncated
    assert newer.clause_text == older.clause_text == head[:CLAUSE_LIMIT]
    assert ("requisites_differ_by_catalog_year" in evidence.warnings) is differ
    block = format_courses_block([SearchHit(course=record, score=1)], {record.course_id: evidence})
    assert newer.clause_sha256 not in block and "clause_sha256" not in block


@pytest.mark.parametrize(("length", "truncated"), [(CLAUSE_LIMIT, False), (CLAUSE_LIMIT + 1, True)])
def test_clause_limit_boundary(empty_db, length, truncated):
    clause = ("permission " * 60)[:length - 1] + "x"  # Not the grammar: kept as an unparsed clause.
    assert len(" ".join(clause.split())) == length
    record = seeded(empty_db, document(prerequisite=clause))
    section = evidence_for(empty_db, record).requisites.editions[0].prerequisite
    assert section.status == "unparsed"
    assert (section.clause_truncated, len(section.clause_text)) == (truncated, CLAUSE_LIMIT)


def test_a_long_clause_is_cut_and_marked_but_its_rule_is_whole(empty_db):
    clause = " or ".join(f"CS {5001 + index}" for index in range(70))
    assert len(clause) > CLAUSE_LIMIT
    record = seeded(empty_db, document(prerequisite=clause))
    section = evidence_for(empty_db, record).requisites.editions[0].prerequisite
    assert section.clause_text == clause[:CLAUSE_LIMIT] and section.clause_truncated is True
    assert len(section.rule.children) == 70
    corequisite = evidence_for(empty_db, record).requisites.editions[0].corequisite
    assert (corequisite.status, corequisite.clause_text, corequisite.clause_truncated) == ("not_listed", None, False)


def test_documents_that_fail_their_checks_are_counted_never_used(empty_db):
    record = seeded(empty_db, document("2026-2027"), document("2025-2026", prerequisite="CS 5004"))
    empty_db.execute("UPDATE course_requisite_documents SET content_hash=? WHERE catalog_year='2025-2026'", ("b" * 64,))
    evidence = evidence_for(empty_db, record)
    assert [edition.catalog_year for edition in evidence.requisites.editions] == ["2026-2027"]
    assert evidence.requisites.unusable_records == 1
    assert "structured_requisites_unusable" in evidence.warnings
    # A course renamed after the import: its documents no longer describe it.
    empty_db.execute("UPDATE courses SET primary_name='Advanced Algorithms'")
    renamed = course(primary_name="Advanced Algorithms")
    evidence = evidence_for(empty_db, renamed)
    assert evidence.requisites.editions == [] and evidence.requisites.unusable_records == 2
    assert "structured_requisites_unusable" in evidence.warnings


def test_the_course_rows_code_and_title_are_checked_as_on_the_course_page(empty_db):
    """The course row was renamed after the import but the answered record was not: the course page does not use
    the document, and neither does the answer."""
    record = seeded(empty_db, document())
    empty_db.execute("UPDATE courses SET primary_name='Advanced Algorithms'")
    assert CourseRequisiteRepository(empty_db).list_for_course(record.course_id).documents == []
    requisites = evidence_for(empty_db, record).requisites
    assert (requisites.editions, requisites.unusable_records) == ([], 1)


@pytest.mark.parametrize("hit", [{"primary_name": "Algorithms (old title)"}, {"primary_code": "CS 5810"}])
def test_a_document_for_another_identity_than_the_answered_course_is_not_used(empty_db, hit):
    """The hit's own code and title must match too (the course page compares the same three)."""
    seeded(empty_db, document())
    evidence = evidence_for(empty_db, course(**hit))
    assert evidence.requisites.editions == [] and evidence.requisites.unusable_records == 1
    assert "structured_requisites_unusable" in evidence.warnings


def test_a_document_for_another_course_id_is_not_used():
    """The course ID must match as well as the code and title."""
    requisites = requisite_evidence(course(), [document(course_id="c-cs-5800-copy")])
    assert requisites.editions == [] and requisites.unusable_records == 1
    assert requisite_evidence(course(), [document()]).unusable_records == 0


def test_rows_without_a_course_or_with_a_non_text_document_are_counted(empty_db):
    """A copy without keys or constraints: neither row fails the batch or reaches the answer."""
    record = seeded(empty_db, document("2026-2027"))
    empty_db.executescript(
        "CREATE TABLE loose AS SELECT * FROM course_requisite_documents;"
        "DROP TABLE course_requisite_documents; ALTER TABLE loose RENAME TO course_requisite_documents;")
    empty_db.execute("INSERT INTO course_requisite_documents VALUES ('c-cs-5800', '2025-2026', 42, 'x')")
    empty_db.execute("INSERT INTO course_requisite_documents VALUES ('c-gone', '2026-2027', '{}', 'x')")
    batch = CourseRequisiteRepository(empty_db).read_batch(["c-cs-5800", "c-gone"])
    assert batch.storage == "available"
    assert [item.catalog_year for item in batch.documents["c-cs-5800"]] == ["2026-2027"]
    assert (batch.unusable["c-cs-5800"], batch.unusable["c-gone"]) == (1, 1) and "c-gone" not in batch.documents
    assert evidence_for(empty_db, record).requisites.unusable_records == 1


def test_each_course_gets_only_its_own_documents(empty_db):
    first = seeded(empty_db, document())
    second = course(course_id="c-cs-6140", primary_code="CS 6140", primary_name="Machine Learning")
    CourseRepository(empty_db).insert(second, raw_text="")
    CourseRequisiteRepository(empty_db).store(document("2025-2026", prerequisite="CS 5800", course_id="c-cs-6140",
                                                       code="CS 6140", name="Machine Learning"))
    evidence = build_answer_evidence(empty_db, [first, second])
    assert [edition.catalog_year for edition in evidence[first.course_id].requisites.editions] == ["2026-2027"]
    rule = evidence[second.course_id].requisites.editions[0].prerequisite.rule
    assert (rule.kind, rule.course_code) == ("course", "CS 5800")
    # Another course's documents are neither used nor counted as this course's unusable ones.
    assert [evidence[key].requisites.unusable_records for key in (first.course_id, second.course_id)] == [0, 0]
    assert not any("structured_requisites_unusable" in item.warnings for item in evidence.values())


@pytest.mark.parametrize("unreadable", ["course_row", "document_row"])
def test_a_value_sqlite_cannot_read_costs_only_its_own_course(empty_db, unreadable):
    """One query reads every hit; after it fails each course is read alone, so the others keep their rules."""
    first = seeded(empty_db, document())
    second = course(course_id="c-cs-6140", primary_code="CS 6140", primary_name="Machine Learning")
    CourseRepository(empty_db).insert(second, raw_text="")
    empty_db.execute("PRAGMA ignore_check_constraints=ON")
    if unreadable == "course_row":
        empty_db.execute("UPDATE courses SET primary_name=CAST(x'ff' AS TEXT) WHERE course_id='c-cs-6140'")
    else:
        empty_db.execute("INSERT INTO course_requisite_documents VALUES "
                         "('c-cs-6140', '2026-2027', CAST(x'7bff7d' AS TEXT), 'x')")
    batch = CourseRequisiteRepository(empty_db).read_batch([first.course_id, second.course_id])
    assert (batch.storage, batch.unreadable) == ("available", {second.course_id})
    evidence = build_answer_evidence(empty_db, [first, second])
    assert [edition.catalog_year for edition in evidence[first.course_id].requisites.editions] == ["2026-2027"]
    assert "structured_requisites_unusable" not in evidence[first.course_id].warnings
    assert evidence[second.course_id].requisites == RequisiteEvidence(storage="schema_unusable")
    assert "structured_requisites_unusable" in evidence[second.course_id].warnings


def test_two_documents_for_one_year_choose_neither(empty_db):
    """Only a copy without keys can hold two; neither is used and both are counted."""
    record = seeded(empty_db, document("2026-2027"), document("2025-2026"))
    empty_db.executescript(
        "CREATE TABLE loose AS SELECT * FROM course_requisite_documents;"
        "DROP TABLE course_requisite_documents; ALTER TABLE loose RENAME TO course_requisite_documents;")
    other = document("2026-2027", prerequisite="CS 5004")
    empty_db.execute("INSERT INTO course_requisite_documents VALUES (?,?,?,?)",
                     (other.course_id, other.catalog_year, other.model_dump_json(), content_hash(other)))
    requisites = evidence_for(empty_db, record).requisites
    assert [edition.catalog_year for edition in requisites.editions] == ["2025-2026"]
    assert requisites.unusable_records == 2


def test_a_year_held_twice_is_counted_unusable_not_omitted(empty_db):
    """Four usable years and one year held twice (a copy without keys): the newest three are shown, one usable year
    is left out, and both copies of the doubled year are unusable."""
    record = seeded(empty_db, *(document(f"{year}-{year + 1}") for year in range(2023, 2027)))
    empty_db.executescript(
        "CREATE TABLE loose AS SELECT * FROM course_requisite_documents;"
        "DROP TABLE course_requisite_documents; ALTER TABLE loose RENAME TO course_requisite_documents;")
    for clause in (NESTED, "CS 5004"):
        twin = document("2022-2023", prerequisite=clause)
        empty_db.execute("INSERT INTO course_requisite_documents VALUES (?,?,?,?)",
                         (twin.course_id, twin.catalog_year, twin.model_dump_json(), content_hash(twin)))
    requisites = evidence_for(empty_db, record).requisites
    assert [edition.catalog_year for edition in requisites.editions] == ["2026-2027", "2025-2026", "2024-2025"]
    assert (requisites.editions_omitted, requisites.unusable_records) == (1, 2)


def test_missing_or_unreadable_storage_degrades_to_the_old_answer(empty_db):
    record = seeded(empty_db, document(), prereqs=["CS 5004"])
    empty_db.execute("DROP TABLE course_requisite_documents")
    evidence = evidence_for(empty_db, record)
    assert evidence.requisites == RequisiteEvidence(storage="schema_missing")
    assert evidence.warnings == course_answer_evidence(record).warnings
    empty_db.execute("CREATE TABLE course_requisite_documents (course_id TEXT, catalog_year TEXT)")
    evidence = evidence_for(empty_db, record)
    assert evidence.requisites == RequisiteEvidence(storage="schema_unusable")
    assert evidence.warnings == [*course_answer_evidence(record).warnings, "structured_requisites_unusable"]
    assert "prerequisite_logic_unavailable" in evidence.warnings


def test_the_evidence_model_refuses_inconsistent_blocks():
    """The API and stored history carry this block; it cannot claim more than the documents say."""
    from pydantic import ValidationError  # noqa: PLC0415

    from schemas.answer_evidence import RequisiteSectionEvidence  # noqa: PLC0415

    newer, older = (requisite_evidence(course(), [document(year)]).editions[0] for year in ("2026-2027", "2025-2026"))
    assert RequisiteEvidence(storage="available", editions=[newer, older]).editions == [newer, older]
    four = [requisite_evidence(course(), [document(f"{year}-{year + 1}")]).editions[0] for year in range(2026, 2022, -1)]
    for bad in ({"storage": "available", "editions": [older, newer]},
                {"storage": "available", "editions": four},
                {"storage": "available", "editions": [newer, newer]},
                {"storage": "schema_missing", "editions": [newer]},
                {"storage": "schema_unusable", "unusable_records": 1},
                {"storage": "available", "editions": [newer], "editions_omitted": 1}):
        with pytest.raises(ValidationError):
            RequisiteEvidence(**bad)
    for bad in ({"status": "not_listed", "clause_text": "CS 5004"},
                {"status": "not_listed", "clause_truncated": True},
                {"status": "parsed", "clause_text": "CS 5004"},
                {"status": "parsed", "rule": newer.prerequisite.rule, "clause_text": "x", "unparsed_reason": "r"},
                {"status": "unparsed", "clause_text": "x"},
                {"status": "unparsed", "rule": newer.prerequisite.rule, "clause_text": "x", "unparsed_reason": "r"},
                {"status": "unparsed", "unparsed_reason": "r"},
                {"status": "parsed", "rule": newer.prerequisite.rule, "clause_text": "x",
                 "clause_sha256": hashlib.sha256(b"x").hexdigest()},
                {"status": "unparsed", "clause_text": "x", "unparsed_reason": "r", "clause_sha256": "0" * 64},
                {"status": "parsed", "rule": newer.prerequisite.rule},
                {"status": "parsed", "rule": newer.prerequisite.rule, "clause_text": ""},
                {"status": "unparsed", "clause_text": "x" * (CLAUSE_LIMIT + 1), "unparsed_reason": "r"}):
        with pytest.raises(ValidationError):
            RequisiteSectionEvidence(**bad)
    assert len(RequisiteSectionEvidence(status="unparsed", clause_text="x" * CLAUSE_LIMIT, unparsed_reason="r")
               .clause_text) == CLAUSE_LIMIT
    # A cut text cannot be checked against the digest of the whole one.
    assert RequisiteSectionEvidence(status="unparsed", clause_text="x", clause_truncated=True, unparsed_reason="r",
                                    clause_sha256="0" * 64).clause_sha256 == "0" * 64
    # A label with no clause after it is stored as unparsed with empty text; the block carries that state.
    assert RequisiteSectionEvidence(status="unparsed", clause_text="", unparsed_reason="empty_clause").clause_text == ""
    with pytest.raises(ValidationError):
        newer.model_validate({**newer.model_dump(), "catalog_url": "https://example.org/course-descriptions/cs/"})
    with pytest.raises(ValidationError):
        newer.model_validate({**newer.model_dump(), "catalog_year": "2026-27"})


# --- prompt -------------------------------------------------------------------------------------

def test_the_prompt_gets_the_rule_in_the_words_it_explains(empty_db):
    record = seeded(empty_db, document(corequisite="CS 5010 with a minimum grade of C- (Graduate)"))
    data = projected(record, evidence_for(empty_db, record))
    assert data["catalog_requisites"] == {
        "editions": [{
            "catalog_year": "2026-2027", "catalog_url": CS_PAGE, "captured_at": "2026-10-01T00:00:00Z",
            "prerequisite": {
                "status": "parsed",
                "rule": {"all_of": [{"any_of": [{"course": "CS 5001"}, {"course": "CS 5004", "minimum_grade": "B-"}]},
                                    {"course": "DS 5110", "may_be_taken_concurrently": True}]},
                "clause_text": NESTED, "clause_truncated": False,
            },
            "corequisite": {
                "status": "parsed", "rule": {"course": "CS 5010", "minimum_grade": "C-", "level": "Graduate"},
                "clause_text": "CS 5010 with a minimum grade of C- (Graduate)", "clause_truncated": False,
            },
        }],
        "editions_not_shown": 0,
    }


def test_an_unparsed_clause_reaches_the_prompt_without_its_internal_reason(empty_db):
    mixed = "CS 5004 and CS 5010 or CS 5600"
    record = seeded(empty_db, document(prerequisite=mixed))
    evidence = evidence_for(empty_db, record)
    block = format_courses_block([SearchHit(course=record, score=1)], {record.course_id: evidence})
    section = json.loads(block)[0]["catalog_requisites"]["editions"][0]["prerequisite"]
    assert section == {"status": "unparsed", "clause_text": mixed, "clause_truncated": False}
    assert evidence.requisites.editions[0].prerequisite.unparsed_reason not in block
    for internal in ("a" * 64, "imported_at\": \"2026", "unparsed_reason", "\"kind\"", "\"children\""):
        assert internal not in block


def test_flat_code_lists_are_left_out_next_to_a_year_rule(empty_db):
    from db.catalog_source_repository import CatalogSourceRepository  # noqa: PLC0415
    from scrapers.neu_catalog import CatalogEntry  # noqa: PLC0415

    record = seeded(empty_db, document(), prereqs=["CS 5004", "CS 5001"])
    snapshot = CatalogSourceRepository.snapshot(CatalogEntry(
        course_code="CS 5800", course_name="Algorithms", description="Graphs.", prereqs=["CS 5004"], catalog_url=CS_PAGE))
    CatalogSourceRepository(empty_db).store(record.course_id, snapshot)
    evidence = evidence_for(empty_db, record)
    data = projected(record, evidence)
    assert "prereqs" not in data["recorded_metadata"]
    assert "prereq_codes" not in data["answer_evidence"]["catalog"]
    # The evidence the API returns keeps them: the projection never mutates it.
    assert evidence.catalog.prereq_codes == ["CS 5004"]
    empty_db.execute("DELETE FROM course_requisite_documents")
    data = projected(record, evidence_for(empty_db, record))
    assert data["recorded_metadata"]["prereqs"] == ["CS 5004", "CS 5001"]
    assert data["answer_evidence"]["catalog"]["prereq_codes"] == ["CS 5004"]
    assert data["catalog_requisites"] == {"editions": [], "editions_not_shown": 0}


def test_editions_not_shown_reaches_the_prompt(empty_db):
    record = seeded(empty_db, *(document(f"{year}-{year + 1}") for year in range(2022, 2027)))
    assert projected(record, evidence_for(empty_db, record))["catalog_requisites"]["editions_not_shown"] == 2


def test_rules_for_year_scoped_requisites():
    rules = " ".join(PROMPT_TEMPLATE.split())
    for sentinel in (
        "one entry per catalog year, newest first (editions_not_shown counts older recorded years left out)",
        "Treat one year's rule as the student's only if the student named that catalog year in this conversation",
        "an entry or start term (e.g. Fall 2026) is not a catalog year, so never map one to the other",
        "if they differ, say so briefly and ask which catalog year applies to the student",
        "If the student names a catalog year that has no entry here, say these records give no rule for that year",
        "and never give another year's rule as theirs",
        "all_of means every branch is required and any_of means any one branch is enough",
        "A corequisite is a separate requirement, not a course to finish first",
        "status not_listed: that year's course block lists none, which does not prove there is no requirement",
        "give its clause_text as recorded (say so when clause_truncated is true;",
        "an empty clause_text means the label has no text after it) and say it needs checking",
        "Never say the student is eligible, meets or has met a requirement, or can register",
        "structured_requisites_unusable means some recorded rules for this course could not be read",
        "Cite a rule like a description: a Markdown link to that entry's catalog_url with the same label",
        "The link opens that page as it is now, not the saved copy, so it may show a later year's rule: "
        "say so when you cite a rule from any entry but the newest",
        "if every listed year has the same rule, say which catalog years it covers",
        "keep the nesting, minimum_grade, may_be_taken_concurrently and the level mark "
        "(Graduate/Undergraduate, as written in the clause) exactly as given",
        "approvals, placement, transfer credit and program rules are not covered",
        "for this course could not be read: do not treat any year as having no requirement",
        "Without catalog_requisites entries, prerequisite codes do NOT encode AND/OR logic",
    ):
        assert sentinel in rules, sentinel


# --- API ----------------------------------------------------------------------------------------

def courses_json(prompt):
    block = prompt.split("# Retrieved course evidence (JSON DATA)\n", 1)[1]
    return json.loads(block.rsplit("\n\nAnswer:", 1)[0])


def capture_chat(client, payload=None):
    prompts = []

    def stream(prompt):
        prompts.append(prompt)
        return iter(["Offline fixture answer"])

    client.app.dependency_overrides[get_chat_stream_fn] = lambda: stream
    response = client.post("/chat", json=payload or {"query": "Algo"})
    assert response.status_code == 200
    return json.loads(response.text.splitlines()[0]), prompts[0]


def test_chat_meta_course_page_and_prompt_share_the_year_rules(api_client):
    conn = api_client.app.dependency_overrides[get_db_conn]()
    CourseRequisiteRepository(conn).store(document("2025-2026", prerequisite="CS 5004"))
    CourseRequisiteRepository(conn).store(document("2026-2027"))
    meta, prompt = capture_chat(api_client)
    assert meta["prompt_version"] == "4.4"
    evidence = meta["results"][0]["answer_evidence"]
    assert [edition["catalog_year"] for edition in evidence["requisites"]["editions"]] == ["2026-2027", "2025-2026"]
    assert "requisites_differ_by_catalog_year" in evidence["warnings"]
    assert '"catalog_requisites": {' in prompt and '"any_of": [' in prompt
    detail = api_client.get("/course/c-cs-5800").json()
    assert detail["answer_evidence"] == evidence
    assert detail["course_requisites"]["warnings"][:len(BASE_WARNINGS)] == BASE_WARNINGS
    assert "structured_requisites_not_used_by_chat" not in json.dumps(detail)


def test_chat_still_answers_when_the_rules_cannot_be_read(api_client):
    conn = api_client.app.dependency_overrides[get_db_conn]()
    conn.execute("DROP TABLE course_requisite_documents")
    conn.execute("CREATE TABLE course_requisite_documents (course_id TEXT, catalog_year TEXT)")
    meta, prompt = capture_chat(api_client)
    evidence = meta["results"][0]["answer_evidence"]
    assert evidence["requisites"] == {"storage": "schema_unusable", "editions": [], "editions_omitted": 0,
                                      "unusable_records": 0}
    assert "structured_requisites_unusable" in evidence["warnings"]
    assert '"catalog_requisites": {\n      "editions": [],' in prompt


def test_an_empty_clause_does_not_fail_chat_or_the_course_page(api_client):
    conn = api_client.app.dependency_overrides[get_db_conn]()
    CourseRequisiteRepository(conn).store(document(prerequisite=""))
    meta, _ = capture_chat(api_client)
    evidence = meta["results"][0]["answer_evidence"]
    assert evidence["requisites"]["editions"][0]["prerequisite"]["clause_text"] == ""
    detail = api_client.get("/course/c-cs-5800")
    assert detail.status_code == 200 and detail.json()["answer_evidence"] == evidence


# --- UI and eval --------------------------------------------------------------------------------

def test_new_codes_have_labels_and_are_never_printed_by_answers():
    for code in NEW_CODES:
        assert WARNING_LABELS[code] and SHORT_WARNING_LABELS[code] and code in COMPACT_WARNINGS
        assert code in CODES
    assert notice_line(list(NEW_CODES)) == "⚠️ " + "；".join(SHORT_WARNING_LABELS[code] for code in NEW_CODES) + "。"


def test_the_evidence_card_names_the_recorded_years_only_from_a_valid_block(empty_db):
    record = seeded(empty_db, *(document(f"{year}-{year + 1}") for year in range(2022, 2027)))
    evidence = evidence_for(empty_db, record).model_dump(mode="json")
    line = "先修规则：已存 Catalog 2026-2027、Catalog 2025-2026、Catalog 2024-2025 的课程块原文，另有 2 个更早年份没有列出（非实时核验，不判断能否注册）"
    assert requisite_years_line(evidence) == line
    assert line in evidence_summary(evidence)
    # A block whose only fault is a year that is not YYYY-YYYY: the caption renders Markdown, so it shows nothing.
    edition = evidence["requisites"]["editions"][0]
    broken = {"requisites": {"storage": "available", "editions": [{**edition, "catalog_year": "*[x](y)*"}]}}
    assert requisite_years_line(broken) is None
    assert requisite_years_line({"requisites": None}) is None and requisite_years_line({}) is None
    for storage in ("available", "schema_missing"):  # No edition, no years line.
        assert requisite_years_line({"requisites": RequisiteEvidence(storage=storage).model_dump(mode="json")}) is None


def test_the_live_eval_builds_the_same_prompt_as_chat_from_the_course_page(api_client):
    from scripts.eval_answers_live import build_case  # noqa: PLC0415

    conn = api_client.app.dependency_overrides[get_db_conn]()
    CourseRequisiteRepository(conn).store(document())
    meta, chat_prompt = capture_chat(api_client)
    payload = api_client.get("/course/c-cs-5800").json()
    question = {"qid": "T1", "lang": "en", "query": "Algo", "course_ids": ["c-cs-5800"], "route": meta["matched_via"],
                "notices": []}
    prompt, context = build_case(question, {"c-cs-5800": payload})
    assert courses_json(prompt) == courses_json(chat_prompt)
    assert courses_json(prompt)[0]["catalog_requisites"]["editions"][0]["catalog_year"] == "2026-2027"
    assert CS_PAGE in context.allowed_urls
    assert "catalog_requisites" in context.prompt_keys and "may_be_taken_concurrently" in context.prompt_keys
    # The AND/OR caveat is expected only where the answer gets a flat list without a year rule.
    flat = {**payload, "prereqs": ["CS 5004"]}
    assert build_case(question, {"c-cs-5800": flat})[1].prereq_relevant is False
    without = {**flat, "answer_evidence": {**flat["answer_evidence"], "requisites": None}}
    assert build_case(question, {"c-cs-5800": without})[1].prereq_relevant is True
