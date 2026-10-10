"""OPT-03 data coverage report on synthetic offline copies: counts, rules and denominators, never
user tables, never writes.

中文：只用合成的离线副本：计数、规则与分母；不读用户表，不写入。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

import scripts.audit_data_coverage as audit
from db.catalog_source_repository import CatalogSourceRepository
from db.course_requisite_repository import CourseRequisiteRepository
from db.course_requisite_repository import content_hash as requisite_hash
from db.program_plan_repository import ProgramPlanRepository
from db.program_plan_repository import content_hash as plan_hash
from db.repository import CourseRepository
from rag.answer_evidence import AVAILABILITY_FIELDS, build_answer_evidence, course_answer_evidence, requisite_evidence
from schemas.answer_evidence import CatalogSnapshot, RequisiteEvidence
from schemas.catalog_credit_hours import CatalogCreditHours
from schemas.course import Course, EvidenceSnippet
from schemas.course_description_evidence import CourseDescriptionEvidence
from schemas.course_requisite_document import CourseRequisiteDocument
from schemas.course_requisite_source import CourseRequisiteSource
from schemas.program_plan import ProgramPlan
from scrapers.course_requisites import parse_clause

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/audit_data_coverage.py"
SENTINEL = "PRIVATE-SENTINEL-7f3a"
UNREAD_TABLES = {"users", "user_unlocks", "user_courses", "query_log", "coop_experiences", "coop_submissions",
                 "coop_contribution_credits", "chat_answers", "answer_feedback", "course_aliases"}
UTC = timezone.utc
CAPTURED = datetime(2026, 10, 1, 9, tzinfo=UTC)
IN_SCOPE_IDS = ["c-cs5800", "c-cs5200", "c-cs6140", "c-ds5110", "c-aai6600", "c-ds5220a", "c-ds5220b", "c-info6105"]


def catalog_url(code):
    return f"https://catalog.northeastern.edu/course-descriptions/{code.split()[0].lower()}/"


def snapshot(code, name, *, credits=None, prereqs=(), description="Catalog description", retrieved_at=None):
    return CatalogSnapshot(course_code=code, course_name=name, description=description, credits=credits,
                           prereq_codes=list(prereqs), catalog_url=catalog_url(code), snapshot_id="catalog:test",
                           imported_at=datetime(2026, 10, 7, 12, tzinfo=UTC), retrieved_at=retrieved_at)


def requisite(course_id, code, name, *, year="2026-2027", prerequisite=None, corequisite=None, hours=None,
              description=None, captured_at=CAPTURED):
    department = code.split()[0]
    source = CourseRequisiteSource(url=catalog_url(code), catalog_year=year, sha256="a" * 64, byte_count=10,
                                   captured_at=captured_at, page_title=f"Test ({department})")
    evidence = None if description is None else CourseDescriptionEvidence.from_paragraphs(description)
    return CourseRequisiteDocument(
        course_id=course_id, course_code=code, course_name=name, catalog_year=year, source=source,
        requisites={"prerequisite": parse_clause(prerequisite), "corequisite": parse_clause(corequisite)},
        description_evidence=evidence, credit_hours=CatalogCreditHours.from_text(hours) if hours else None)


def plan(plan_id, program_id, *, pathway="standard", coverage="partial", review_status="draft",
         fingerprint=None, unmodeled=True, concentration=None, captured_on="2026-10-01"):
    children = [{"kind": "course", "label": "CS 5800", "course_code": "CS 5800"},
                {"kind": "course", "label": "CS 5004", "course_code": "CS 5004"}]
    if unmodeled:
        children.append({"kind": "unmodeled", "label": "Electives not modeled"})
    data = dict(plan_id=plan_id, program_id=program_id, campus="boston", catalog_year="2026-2027", pathway=pathway,
                concentration=concentration, coverage=coverage, review_status=review_status,
                source_html_sha256=fingerprint,
                source_url="https://catalog.northeastern.edu/graduate/computer-information-science/test/",
                source_title="Test program", source_catalog_year="2026-2027", source_excerpt=f"Excerpt {SENTINEL}",
                captured_on=captured_on, notes=f"Notes {SENTINEL}",
                requirements={"kind": "all_of", "label": "Core", "children": children})
    if review_status == "source_checked":
        data.update(checked_by=f"reviewer {SENTINEL}", checked_on="2026-10-02")
    return ProgramPlan.model_validate(data)


def raw_course(conn, course_id, code, name, generated_json, status="pending"):
    conn.execute("INSERT INTO courses(course_id, primary_code, primary_name, metadata, raw_text, generated_json, "
                 "status) VALUES(?,?,?,?,?,?,?)", (course_id, code, name, "{}", SENTINEL, generated_json, status))


def put_snapshot(conn, course_id, text):
    conn.execute("INSERT INTO course_catalog_sources(course_id, snapshot) VALUES(?,?)", (course_id, text))


def put_requisite(conn, course_id, year, document, digest=None):
    text = document if isinstance(document, str) else document.model_dump_json()
    digest = digest or (requisite_hash(document) if not isinstance(document, str) else "0" * 64)
    conn.execute("INSERT INTO course_requisite_documents(course_id, catalog_year, document, content_hash) "
                 "VALUES(?,?,?,?)", (course_id, year, text, digest))


def put_plan(conn, item, *, digest=None, program_id=None, plan_id=None, document=None):
    conn.execute("INSERT INTO program_plans(plan_id, program_id, campus, catalog_year, pathway, concentration, "
                 "document, content_hash) VALUES(?,?,?,?,?,?,?,?)",
                 (plan_id or item.plan_id, program_id or item.program_id, item.campus, item.catalog_year,
                  item.pathway, item.concentration or "", document or item.model_dump_json(),
                  digest or plan_hash(item)))


def put_program(conn, program_id):
    conn.execute("INSERT INTO programs(program_id, full_name, prefix, notes) VALUES(?,?,?,?)",
                 (program_id, SENTINEL, "X", SENTINEL))


def seed_user_tables(conn):
    """Sentinel rows in every table the report must never read."""
    conn.execute("INSERT INTO users(user_id, email, domain, display_name) VALUES(?,?,?,?)",
                 ("u1", f"{SENTINEL}@husky.neu.edu", "husky.neu.edu", SENTINEL))
    conn.execute("INSERT INTO user_courses(user_id, course_id, term) VALUES('u1', 'c-cs5800', ?)", (SENTINEL,))
    conn.execute("INSERT INTO query_log(log_id, route, query, user_id) VALUES(1, 'chat', ?, 'u1')", (SENTINEL,))
    conn.execute("INSERT INTO coop_experiences(coop_id, company, role, interview_summary) VALUES('x', ?, ?, ?)",
                 (SENTINEL, SENTINEL, SENTINEL))
    conn.execute("INSERT INTO coop_submissions(coop_id, contributor_user_id, submission_key, group_key, payload) "
                 "VALUES('s1', 'u1', 'k', 'g', ?)", (json.dumps({"text": SENTINEL}),))
    conn.execute("INSERT INTO chat_answers(answer_id, query_log_id, answer_text, answer_sha256, feedback_token_hash, "
                 "prompt_version, request_context, expires_at) VALUES(?, 1, ?, ?, ?, '4.3', '{}', 0)",
                 ("a" * 32, SENTINEL, "b" * 64, "c" * 64))
    conn.execute("INSERT INTO answer_feedback(answer_id, rating) VALUES(?, 'up')", ("a" * 32,))
    conn.execute("INSERT INTO course_aliases(alias_text, alias_type, primary_course_id, source, evidence) "
                 "VALUES(?, 'slang', 'c-cs5800', 'manual', ?)", (SENTINEL, SENTINEL))


def build_seeded(path: Path, *, journal="DELETE") -> Path:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript((ROOT / "db/init.sql").read_text(encoding="utf-8"))
    repo = CourseRepository(conn)
    quote = f"quote {SENTINEL}"
    courses = [
        Course(course_id="c-cs5800", primary_code="CS 5800", primary_name="Algorithms", credits=4, prereqs=["CS 5004"]),
        Course(course_id="c-cs5200", primary_code="CS 5200", primary_name="Database Management Systems", credits=4),
        Course(course_id="c-cs6140", primary_code="CS 6140", primary_name="Machine Learning", term="Fall 2026",
               prereqs=["CS 5800", "DS 5220"]),
        Course(course_id="c-ds5110", primary_code="DS 5110", primary_name="Data Management", credits=4,
               workload_hours_per_week=6.0, difficulty_score=3.0, topics_covered=["SQL"],
               source_review_ids=["syllabus_ds5110"],
               evidence_snippets=[EvidenceSnippet(field="workload_hours_per_week", value=6.0,
                                                  source_id="syllabus_ds5110", quote=quote, confidence=0.8),
                                  EvidenceSnippet(field="difficulty_score", value=4.0, source_id="rmp_review_1",
                                                  quote=quote, confidence=0.5)]),
        Course(course_id="c-aai6600", primary_code="AAI 6600", primary_name="Applied Artificial Intelligence",
               professor=["Dr. Example"], source_review_ids=["rmp_review_2"]),
        Course(course_id="c-ds5220a", primary_code="DS 5220", primary_name="Supervised Machine Learning", credits=4,
               prereqs=["DS 5110"]),
        Course(course_id="c-ds5220b", primary_code="DS 5220", primary_name="Supervised Machine Learning", credits=3),
        Course(course_id="c-info6105", primary_code="INFO 6105", primary_name="Data Science Engineering Methods"),
        Course(course_id="synth-0001", primary_code="SYN 1000", primary_name="Synthetic",
               source_review_ids=["synthetic_seed_1"]),
    ]
    for course in courses:
        repo.insert(course, raw_text=SENTINEL)
    repo.mark_indexed("c-cs5800")
    raw_course(conn, "c-bad-json", "CS 9999", "Broken", "{not json")
    raw_course(conn, "c-invalid", "CS 9998", "Invalid", json.dumps({"course_id": "c-invalid"}), status="failed")
    original = Course(course_id="c-mismatch", primary_code="CS 9996", primary_name="Original")
    raw_course(conn, "c-mismatch", "CS 9996", "Renamed In Column", original.model_dump_json())
    raw_course(conn, "c-oversize", "CS 9997", "Oversize", json.dumps({"pad": "a" * 1_000_001}))

    conn.execute("PRAGMA ignore_check_constraints=ON")  # Lets the fixture store JSON the app never would.
    put_snapshot(conn, "c-cs5800", snapshot("CS 5800", "Algorithms", credits=4, prereqs=["CS 5004"],
                                            description=f"Graphs {SENTINEL}").model_dump_json())
    put_snapshot(conn, "c-cs5200", snapshot("CS 5200", "Database Management Systems", credits=3, prereqs=["CS 5800"],
                                            description="",
                                            retrieved_at=datetime(2026, 9, 30, 15, tzinfo=UTC)).model_dump_json())
    put_snapshot(conn, "c-cs6140", "{not json")
    put_snapshot(conn, "c-aai6600", snapshot("AAI 6600", "Old Title").model_dump_json())
    put_snapshot(conn, "c-ds5220a", snapshot("DS 5220", "Supervised Machine Learning", credits=4,
                                             description="Supervised learning").model_dump_json())
    put_snapshot(conn, "c-ds5220b", json.dumps({"course_code": "DS 5220"}))
    put_snapshot(conn, "c-info6105", json.dumps({"pad": "a" * 100_001}))
    put_snapshot(conn, "c-gone", snapshot("CS 5001", "Gone").model_dump_json())
    put_snapshot(conn, "synth-0001", snapshot("SYN 1000", "Synthetic").model_dump_json())

    put_requisite(conn, "c-cs5800", "2026-2027", requisite("c-cs5800", "CS 5800", "Algorithms", prerequisite="CS 5004"))
    put_requisite(conn, "c-cs5200", "2026-2027", requisite("c-cs5200", "CS 5200", "Database Management Systems",
                                                           prerequisite="Junior standing", hours="3 Hours"))
    put_requisite(conn, "c-aai6600", "2025-2026", requisite("c-aai6600", "AAI 6600", "Applied Artificial Intelligence",
                                                            year="2025-2026", hours="1-4 Hours"))
    tampered = requisite("c-ds5110", "DS 5110", "Data Management", prerequisite="DS 5010")
    put_requisite(conn, "c-ds5110", "2026-2027", tampered, digest="f" * 64)
    renamed = requisite("c-cs6140", "CS 6140", "Old Machine Learning", prerequisite="CS 5800")
    put_requisite(conn, "c-cs6140", "2026-2027", renamed)
    other_edition = requisite("c-info6105", "INFO 6105", "Data Science Engineering Methods", year="2025-2026")
    put_requisite(conn, "c-info6105", "2026-2027", other_edition)
    put_requisite(conn, "c-info6105", "2025-2026", json.dumps({"pad": "a" * 200_001}))
    put_requisite(conn, "c-ds5220a", "2026-2027", json.dumps({"format_version": "1"}))
    put_requisite(conn, "c-ds5220b", "2026-2027", "{not json")
    put_requisite(conn, "c-gone", "2026-2027", requisite("c-gone", "CS 5001", "Gone"))
    put_requisite(conn, "synth-0001", "2026-2027", requisite("synth-0001", "SYN 1000", "Synthetic"))
    conn.execute("PRAGMA ignore_check_constraints=OFF")

    for program in ("cs-ms", "ds-ms", "info-ms", "aai-ms"):
        conn.execute("INSERT INTO programs(program_id, full_name, prefix, notes) VALUES(?,?,?,?)",
                     (program, SENTINEL, program.split("-")[0].upper(), SENTINEL))
    put_plan(conn, plan("cs-ms-boston-2026-2027-standard", "cs-ms"))
    put_plan(conn, plan("cs-ms-boston-2026-2027-align", "cs-ms", pathway="align", coverage="complete",
                        review_status="source_checked", unmodeled=False))
    put_plan(conn, plan("ds-ms-boston-2026-2027-standard", "ds-ms", review_status="source_checked",
                        fingerprint="d" * 64))
    put_plan(conn, plan("info-ms-boston-2026-2027-standard", "info-ms"), digest="e" * 64)
    put_plan(conn, plan("gone-ms-boston-2026-2027-standard", "gone-ms"))
    put_plan(conn, plan("aai-ms-boston-2026-2027-standard", "cs-ms"), program_id="aai-ms")  # Rebound to another scope.

    for program, course_id in (("cs-ms", "c-cs5800"), ("ds-ms", "c-ds5110"), ("aai-ms", "c-aai6600"),
                               ("cs-ms", "synth-0001"), ("gone-ms", "c-cs5200")):
        conn.execute("INSERT INTO program_required_courses(program_id, course_id, requirement_type, notes) "
                     "VALUES(?,?,'core',?)", (program, course_id, SENTINEL))
    for course_id, prereq in (("c-cs6140", "c-cs5800"), ("c-cs5200", "c-cs5800")):
        conn.execute("INSERT INTO course_prerequisites(course_id, prereq_course_id, notes) VALUES(?,?,?)",
                     (course_id, prereq, SENTINEL))
    seed_user_tables(conn)
    conn.commit()
    conn.execute(f"PRAGMA journal_mode={journal}")
    conn.close()
    return path


@pytest.fixture
def seeded(tmp_path) -> Path:
    path = build_seeded(tmp_path / "copy.sqlite3")
    assert sorted(item.name for item in tmp_path.iterdir()) == ["copy.sqlite3"]
    return path


def modify(path, *statements):
    conn = sqlite3.connect(path)
    for statement in statements:
        conn.execute(statement)
    conn.commit()
    conn.close()


@contextmanager
def writing(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def without_keys(path, table):
    """Rebuild a table with its columns but no keys or constraints, as an old or crafted copy may have it."""
    modify(path, "DROP VIEW IF EXISTS v_course_lookup", f"CREATE TABLE loose AS SELECT * FROM {table}",
           f"DROP TABLE {table}", f"ALTER TABLE loose RENAME TO {table}")


def section(report, name):
    return report["sections"][name]


def snapshot_dir(directory):
    return {item.name: hashlib.sha256(item.read_bytes()).hexdigest() for item in directory.iterdir()}


def total(block):
    (value,) = block["denominator"].values()
    return value


# --- counts, denominators, rules ---------------------------------------------------------------


def test_course_rows_split_into_exclusive_categories(seeded):
    report = audit.build_report(seeded)
    assert report["database"] == {"status": "checked", "code": "read_only_snapshot"}
    courses = section(report, "courses")
    assert courses["denominator"] == {"course_rows": 13}
    assert courses["counts"] == {"in_scope": 8, "synthetic": 1, "identity_mismatch": 1, "invalid_record": 1,
                                 "invalid_json": 1, "oversize": 1, "duplicate_id": 0, "text_not_utf8": 0}
    assert courses["in_scope_courses"] == {"denominator": {"courses_in_scope": 8}, "duplicate_code_groups": 1,
                                           "duplicate_code_rows": 2,
                                           "by_department": {"AAI": 1, "CS": 3, "DS": 3, "INFO": 1}}
    assert courses["status_column"] == {"pending": 11, "indexed": 1, "failed": 1, "other": 0}


def test_catalog_snapshots_per_course_and_per_row(seeded):
    catalog = section(audit.build_report(seeded), "catalog_snapshots")
    assert catalog["denominator"] == {"courses_in_scope": 8}
    assert catalog["counts"] == {"usable": 3, "absent": 1, "duplicate_rows": 0, "identity_mismatch": 1,
                                 "invalid_record": 1, "invalid_json": 1, "oversize": 1, "text_not_utf8": 0}
    assert catalog["snapshot_rows"] == {"denominator": {"snapshot_rows": 9}, "rows_for_courses_in_scope": 7,
                                        "rows_for_courses_out_of_scope": 1, "orphan_rows": 1,
                                        "rows_with_text_not_utf8": 0}
    assert catalog["usable_snapshots"] == {
        "denominator": {"usable_snapshots": 3}, "retrieval_date_known": 1, "retrieval_date_unknown": 2,
        "retrieved_on": {"earliest": "2026-09-30", "latest": "2026-09-30"}, "description_missing": 1,
        "credits_missing": 0, "prereq_codes_listed": 2}
    assert catalog["by_department"]["CS"] == {"courses_in_scope": 3, "usable": 2, "invalid_json": 1}
    assert catalog["by_department"]["DS"] == {"courses_in_scope": 3, "usable": 1, "absent": 1, "invalid_record": 1}


def test_field_categories_cover_every_in_scope_course(seeded):
    fields = section(audit.build_report(seeded), "fields")
    assert fields["denominator"] == {"courses_in_scope": 8}
    table = fields["fields"]
    assert set(table) == set(AVAILABILITY_FIELDS)
    for counts in table.values():
        assert list(counts) == list(audit.FIELD_CATEGORIES) and sum(counts.values()) == 8
    assert table["credits"] == {"year_rules": 0, "catalog_only": 0, "catalog_lists_none": 0, "catalog_conflict": 1,
                                "catalog_consistent": 2, "missing": 3, "extracted_estimate": 0,
                                "course_sources_only": 1, "no_recorded_source": 1}
    # CS 5800, CS 5200 and AAI 6600 have a usable year document: chat gives its rules, not the stored list.
    assert table["prereqs"] == {"year_rules": 3, "catalog_only": 0, "catalog_lists_none": 0, "catalog_conflict": 1,
                                "catalog_consistent": 0, "missing": 3, "extracted_estimate": 0,
                                "course_sources_only": 0, "no_recorded_source": 1}
    assert table["workload_hours_per_week"]["extracted_estimate"] == 1
    assert table["difficulty_score"]["extracted_estimate"] == 1
    assert table["topics_covered"]["course_sources_only"] == 1
    assert table["professor"]["course_sources_only"] == 1
    assert table["term"]["no_recorded_source"] == 1
    assert table["skill_tags"]["missing"] == 8
    assert fields["catalog_comparison"] == {"status": "checked"}
    assert fields["catalog_description"] == {"present": 2, "empty_in_usable_snapshot": 1, "no_usable_snapshot": 5}
    warnings = fields["answer_warnings"]
    assert warnings["catalog_metadata_conflict"] == 1 and warnings["field_evidence_value_conflict"] == 1
    assert warnings["catalog_retrieval_date_unknown"] == 2 and warnings["catalog_source_unavailable"] == 5
    assert "synthetic_record_not_real_course" not in warnings
    # Year rules: CS 6140 and DS 5220 (a) have a code list and no usable document; CS 5200's clause is kept as text;
    # five courses have documents that cannot be used.
    assert (warnings["prerequisite_logic_unavailable"], warnings["requisite_clause_unparsed"],
            warnings["structured_requisites_unusable"]) == (2, 1, 5)
    cs = fields["by_department"]["CS"]
    assert cs["courses_in_scope"] == 3 and set(cs["fields"]) == set(AVAILABILITY_FIELDS)
    assert cs["fields"]["credits"] == {"catalog_conflict": 1, "catalog_consistent": 1, "missing": 1}
    assert cs["fields"]["prereqs"] == {"year_rules": 2, "no_recorded_source": 1}
    # CS 5800 has a usable snapshot with a description, CS 5200 one without, CS 6140 none (bad JSON).
    assert cs["catalog_description"] == {"empty_in_usable_snapshot": 1, "no_usable_snapshot": 1, "present": 1}
    assert cs["answer_warnings"] == {"catalog_metadata_conflict": 1, "catalog_retrieval_date_unknown": 1,
                                     "catalog_source_unavailable": 1, "prerequisite_logic_unavailable": 1,
                                     "requisite_clause_unparsed": 1, "structured_requisites_unusable": 1}
    # Zero counts are left out here too: no DS course has a usable snapshot without a description.
    assert fields["by_department"]["DS"]["catalog_description"] == {"no_usable_snapshot": 2, "present": 1}
    assert "categories" not in fields


def test_requisite_documents_by_edition(seeded):
    requisites = section(audit.build_report(seeded), "requisite_documents")
    assert requisites["denominator"] == {"document_rows": 11}
    assert requisites["counts"] == {
        "usable": 3, "orphan_rows": 1, "rows_for_courses_out_of_scope": 1, "duplicate_rows": 0, "oversize": 1,
        "invalid_json": 1, "invalid_record": 1, "row_identity_mismatch": 1, "course_identity_mismatch": 1,
        "content_hash_mismatch": 1, "text_not_utf8": 0}
    current, previous = requisites["by_catalog_year"]["2026-2027"], requisites["by_catalog_year"]["2025-2026"]
    assert parse_clause("Junior standing").status == "unparsed"
    assert (current["usable"], current["unusable"], current["courses_in_scope_covered"]) == (2, 7, 2)
    assert current["prerequisite"] == {"parsed": 1, "unparsed": 1, "not_listed": 0}
    assert current["corequisite"] == {"parsed": 0, "unparsed": 0, "not_listed": 2}
    assert current["description_evidence"]["not_captured"] == 2
    assert current["credit_hours_vs_course_credits"] == {
        "consistent": 0, "conflict": 1, "course_credits_missing": 0, "range_not_compared": 0,
        "fractional_not_compared": 0, "not_captured": 1}
    assert current["captured_on"] == {"earliest": "2026-10-01", "latest": "2026-10-01"}
    assert (previous["usable"], previous["unusable"]) == (1, 1)
    assert previous["prerequisite"]["not_listed"] == 1
    assert previous["credit_hours_vs_course_credits"]["range_not_compared"] == 1
    assert requisites["in_scope_courses"] == {"denominator": {"courses_in_scope": 8},
                                              "with_usable_document_any_year": 3,
                                              "legacy_prereqs_without_usable_document": 2}
    none = dict.fromkeys(audit.CREDIT_COMPARISONS, 0)
    assert requisites["by_department"]["CS"] == {"courses_in_scope": 3, "by_catalog_year": {
        "2026-2027": {"with_usable_document": 2, "prerequisite": {"parsed": 1, "unparsed": 1, "not_listed": 0},
                      "corequisite": {"parsed": 0, "unparsed": 0, "not_listed": 2},
                      "credit_hours_vs_course_credits": {**none, "conflict": 1, "not_captured": 1}}}}
    assert requisites["by_department"]["AAI"] == {"courses_in_scope": 1, "by_catalog_year": {
        "2025-2026": {"with_usable_document": 1, "prerequisite": {"parsed": 0, "unparsed": 0, "not_listed": 1},
                      "corequisite": {"parsed": 0, "unparsed": 0, "not_listed": 1},
                      "credit_hours_vs_course_credits": {**none, "range_not_compared": 1}}}}
    assert requisites["by_department"]["DS"] == {"courses_in_scope": 3, "by_catalog_year": {}}


def test_partial_plans_are_never_counted_complete(seeded):
    plans = section(audit.build_report(seeded), "program_plans")
    assert plans["denominator"] == {"plan_rows": 6}
    assert plans["counts"] == {"usable": 3, "orphan_rows": 1, "oversize": 0, "invalid_json": 0, "invalid_record": 0,
                               "identity_mismatch": 1, "content_hash_mismatch": 1, "duplicate_scope_or_id": 0,
                               "text_not_utf8": 0}
    assert plans["usable_plans"] == {
        "denominator": {"usable_plans": 3}, "coverage": {"partial": 2, "complete": 1},
        "review_status": {"draft": 1, "source_checked": 2}, "source_fingerprint": {"recorded": 1, "missing": 2},
        "captured_on": {"earliest": "2026-10-01", "latest": "2026-10-01"}}
    assert plans["by_program"] == {
        "cs-ms": {"by_catalog_year": {"2026-2027": {"usable": 2, "partial": 1, "complete": 1, "draft": 1,
                                                    "source_checked": 1}}},
        "ds-ms": {"by_catalog_year": {"2026-2027": {"usable": 1, "partial": 1, "complete": 0, "draft": 0,
                                                    "source_checked": 1}}}}
    assert plans["usable_plans_with_unlisted_program_id"] == 0
    # A source_checked partial plan (ds-ms) is still partial; only cs-ms has a complete scope.
    assert plans["programs"] == {"denominator": {"program_rows": 4}, "with_any_complete_plan": 1,
                                 "with_only_partial_plans": 1, "without_usable_plan": 2, "id_unusable": 0,
                                 "rows_with_text_not_utf8": 0}


def test_legacy_rows_are_counted_only(seeded):
    legacy = section(audit.build_report(seeded), "legacy_rows")
    assert legacy["program_required_courses"] == {
        "status": "checked", "denominator": {"rows": 5}, "rows_for_courses_in_scope": 4,
        "rows_for_courses_out_of_scope": 1, "by_program": {"aai-ms": 1, "cs-ms": 2, "ds-ms": 1},
        "rows_for_unknown_programs": 1, "rows_with_unlisted_program_id": 0, "rows_with_text_not_utf8": 0}
    assert legacy["course_prerequisites"] == {
        "status": "checked", "denominator": {"rows": 2}, "rows_for_courses_in_scope": 2,
        "rows_for_courses_out_of_scope": 0, "courses_in_scope_with_edges": 2, "rows_with_text_not_utf8": 0}


def test_legacy_edges_with_one_end_out_of_scope(seeded):
    modify(seeded, "INSERT INTO course_prerequisites(course_id, prereq_course_id) VALUES('c-cs5800', 'c-bad-json')",
           "INSERT INTO course_prerequisites(course_id, prereq_course_id) VALUES('c-bad-json', 'c-cs5800')")
    edges = section(audit.build_report(seeded), "legacy_rows")["course_prerequisites"]
    assert (edges["rows_for_courses_in_scope"], edges["rows_for_courses_out_of_scope"]) == (2, 2)
    assert edges["courses_in_scope_with_edges"] == 3  # c-bad-json is out of scope, so its edge names no course here.


def test_non_text_program_ids_are_counted_not_named(seeded):
    # A BLOB keeps its type in a TEXT column (an integer would be stored as text).
    modify(seeded, "INSERT INTO programs(program_id, full_name, prefix) VALUES(x'37', 'Numeric', 'NUM')",
           "INSERT INTO program_required_courses(program_id, course_id, requirement_type) "
           "VALUES(x'37', 'c-cs5800', 'core')")
    report = audit.build_report(seeded, details=True)
    legacy = section(report, "legacy_rows")["program_required_courses"]
    assert legacy["by_program"] == {"aai-ms": 1, "cs-ms": 2, "ds-ms": 1}
    assert (legacy["rows_for_unknown_programs"], legacy["rows_with_unlisted_program_id"]) == (1, 1)
    programs = section(report, "program_plans")["programs"]
    assert programs == {"denominator": {"program_rows": 5}, "with_any_complete_plan": 1,
                        "with_only_partial_plans": 1, "without_usable_plan": 2, "id_unusable": 1,
                        "rows_with_text_not_utf8": 0}
    listed = report["details"]["program_plans"]["programs_without_usable_plan"]
    assert listed == {"items": ["aai-ms", "info-ms"], "omitted": 0, "unlisted_malformed": 0}
    json.dumps(report, sort_keys=True)  # Every key of the report is text.


def test_free_text_ids_are_counted_never_named(seeded):
    free, long_id = "Free text with spaces", "x" * 65
    with writing(seeded) as conn:
        put_program(conn, free)
        put_program(conn, long_id)
        for program in (free, long_id):
            conn.execute("INSERT INTO program_required_courses(program_id, course_id, requirement_type) "
                         "VALUES(?, 'c-cs5800', 'core')", (program,))
        put_plan(conn, plan("free-boston-2026-2027-standard", free))
        put_plan(conn, plan("cs-ms-boston-2026-2027-bridge", "cs-ms", pathway="bridge",
                            concentration="Free concentration text"))
    for details in (False, True):
        report = audit.build_report(seeded, details=details)
        text = json.dumps(report)
        assert free not in text and "Free concentration" not in text and long_id not in text
        assert report["complete"] is True
    plans = section(report, "program_plans")
    assert plans["counts"]["usable"] == 5 and plans["usable_plans_with_unlisted_program_id"] == 1
    assert set(plans["by_program"]) == {"cs-ms", "ds-ms"}
    assert plans["programs"]["without_usable_plan"] == 3  # info-ms, aai-ms and the long ID, which is not named.
    legacy = section(report, "legacy_rows")["program_required_courses"]
    assert legacy["rows_with_unlisted_program_id"] == 2
    listed = report["details"]["program_plans"]
    assert listed["programs_without_usable_plan"] == {"items": ["aai-ms", "info-ms"], "omitted": 0,
                                                      "unlisted_malformed": 1}
    scopes = listed["usable_scopes"]
    assert scopes["unlisted_malformed"] == 1
    bridge = [item for item in scopes["items"] if item["pathway"] == "bridge"]
    assert bridge == [{"plan_id": "cs-ms-boston-2026-2027-bridge", "program_id": "cs-ms", "campus": "boston",
                       "catalog_year": "2026-2027", "pathway": "bridge", "has_concentration": True,
                       "coverage": "partial", "review_status": "draft"}]


def test_null_ids_name_nothing(tmp_path):
    path = tmp_path / "nulls.sqlite3"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript((ROOT / "db/init.sql").read_text(encoding="utf-8"))
    good = Course(course_id="c-1", primary_code="CS 5800", primary_name="Algorithms")
    CourseRepository(conn).insert(good)
    for _ in range(2):  # A TEXT PRIMARY KEY of a rowid table accepts several NULLs.
        conn.execute("INSERT INTO courses(course_id, primary_code, primary_name, metadata, generated_json) "
                     "VALUES(NULL, 'CS 5800', 'Algorithms', '{}', ?)", (good.model_dump_json(),))
    put_snapshot(conn, None, snapshot("CS 5800", "Algorithms").model_dump_json())
    for program in (None, None, "cs-ms"):
        conn.execute("INSERT INTO programs(program_id, full_name, prefix) VALUES(?, 'n', 'N')", (program,))
    item = plan("cs-ms-boston-2026-2027-standard", "cs-ms")  # Stored with a NULL plan_id.
    conn.execute("INSERT INTO program_plans(plan_id, program_id, campus, catalog_year, pathway, concentration, "
                 "document, content_hash) VALUES(NULL, 'cs-ms', 'boston', '2026-2027', 'standard', '', ?, ?)",
                 (item.model_dump_json(), plan_hash(item)))
    conn.commit()
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    # The legacy tables' ID columns are NOT NULL; a NULL there fails the integrity check (see the NOT NULL test).
    report = audit.build_report(path, details=True)
    courses = section(report, "courses")
    assert (courses["counts"]["in_scope"], courses["counts"]["identity_mismatch"]) == (1, 2)
    # Only well-formed column values are named: the rows' code, the program with a usable ID; NULLs name nothing.
    assert listed(report["details"], "courses", "identity_mismatch", "CS") == ["CS 5800", "CS 5800"]
    assert report["details"]["program_plans"] == {
        "identity_mismatch": {"items": [], "omitted": 0, "unlisted_malformed": 1},
        "programs_without_usable_plan": {"items": ["cs-ms"], "omitted": 0, "unlisted_malformed": 0}}
    assert section(report, "catalog_snapshots")["snapshot_rows"] == {
        "denominator": {"snapshot_rows": 1}, "rows_for_courses_in_scope": 0, "rows_for_courses_out_of_scope": 0,
        "orphan_rows": 1, "rows_with_text_not_utf8": 0}
    assert section(report, "program_plans")["programs"] == {
        "denominator": {"program_rows": 3}, "with_any_complete_plan": 0, "with_only_partial_plans": 0,
        "without_usable_plan": 1, "id_unusable": 2, "rows_with_text_not_utf8": 0}


def test_repeated_program_ids_are_not_matched(seeded):
    without_keys(seeded, "programs")
    modify(seeded, "INSERT INTO programs SELECT * FROM programs WHERE program_id='cs-ms'")
    programs = section(audit.build_report(seeded), "program_plans")["programs"]
    assert programs == {"denominator": {"program_rows": 5}, "with_any_complete_plan": 0,
                        "with_only_partial_plans": 1, "without_usable_plan": 2, "id_unusable": 2,
                        "rows_with_text_not_utf8": 0}


def test_repeated_program_ids_name_no_program_in_any_block(seeded):
    """ds-ms (only partial plans) and info-ms (no usable plan) appear twice: neither is counted as a program."""
    without_keys(seeded, "programs")
    modify(seeded, "INSERT INTO programs SELECT * FROM programs WHERE program_id IN ('ds-ms', 'info-ms')")
    report = audit.build_report(seeded, details=True)
    programs = section(report, "program_plans")["programs"]
    assert programs == {"denominator": {"program_rows": 6}, "with_any_complete_plan": 1,
                        "with_only_partial_plans": 0, "without_usable_plan": 1, "id_unusable": 4,
                        "rows_with_text_not_utf8": 0}
    assert report["details"]["program_plans"]["programs_without_usable_plan"]["items"] == ["aai-ms"]


def test_program_ids_that_look_like_report_keys_are_data(seeded):
    with writing(seeded) as conn:
        for program in ("status", "code"):
            put_program(conn, program)
            conn.execute("INSERT INTO program_required_courses(program_id, course_id, requirement_type) "
                         "VALUES(?, 'c-cs5800', 'core')", (program,))
        put_plan(conn, plan("status-boston-2026-2027-standard", "status"))
    report = audit.build_report(seeded)
    assert report["complete"] is True and unexplained(report) == ([], set())
    assert section(report, "legacy_rows")["program_required_courses"]["by_program"]["status"] == 1
    assert section(report, "program_plans")["by_program"]["status"]["by_catalog_year"]["2026-2027"]["usable"] == 1


def aliased_copy(path, numbers):
    """A copy whose programs table shares the users table's b-tree: every name passes, the pages do not."""
    conn = sqlite3.connect(path)
    conn.executescript((ROOT / "db/init.sql").read_text(encoding="utf-8"))
    for number in numbers:
        conn.execute("INSERT INTO users(user_id, email, domain) VALUES(?, ?, 'husky.neu.edu')",
                     (number, f"{number}@husky.neu.edu"))
    conn.execute("DROP TABLE program_required_courses")
    conn.execute("DROP TABLE programs")
    conn.execute("CREATE TABLE programs(program_id TEXT)")
    conn.commit()
    roots = dict(conn.execute("SELECT name, rootpage FROM sqlite_schema WHERE type='table'").fetchall())
    version = conn.execute("PRAGMA schema_version").fetchone()[0]
    conn.execute("PRAGMA writable_schema=ON")
    conn.execute("UPDATE sqlite_schema SET rootpage=? WHERE name='programs'", (roots["users"],))
    conn.execute(f"PRAGMA schema_version={version + 1}")
    conn.execute("PRAGMA writable_schema=OFF")
    conn.commit()
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    return path


def test_a_copy_with_shared_pages_is_refused_before_any_row_is_read(tmp_path):
    numbers = ["104729000000000000001", "104729000000000000002"]
    path = aliased_copy(tmp_path / "aliased.sqlite3", numbers)
    check = sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)
    assert check.execute("PRAGMA quick_check(1)").fetchone() != ("ok",)
    assert check.execute("SELECT count(*) FROM programs").fetchone()[0] == 2  # The aliased rows are readable.
    check.close()
    report = audit.build_report(path, details=True)
    assert report["database"] == {"status": "failed", "code": "database_integrity_failed"}
    assert all(item == {"status": "not_checked", "code": "database_unavailable"}
               for item in report["sections"].values())
    assert "details" not in report and not any(number in json.dumps(report) for number in numbers)
    assert run_cli("--db-copy", str(path), cwd=tmp_path).returncode == 1


def swapped_copy(path, user_ids):
    """A copy whose programs and users tables trade b-trees: every page is used once and every NOT NULL column of
    users still has a value, so quick_check passes, but the users table no longer matches its own indexes."""
    conn = sqlite3.connect(path)
    conn.executescript((ROOT / "db/init.sql").read_text(encoding="utf-8"))
    for user_id in user_ids:
        conn.execute("INSERT INTO users(user_id, email, domain) VALUES(?, ?, 'husky.neu.edu')",
                     (user_id, f"{user_id}@husky.neu.edu"))
    conn.execute("DROP TABLE program_required_courses")
    conn.execute("DROP TABLE programs")
    conn.execute("CREATE TABLE programs(program_id TEXT, c2, c3, c4, c5, c6, c7)")  # As many columns as users.
    conn.execute("INSERT INTO programs VALUES('cs-ms', 'a', 'b', 'c', 0, '2026-10-01', 'd')")
    conn.commit()
    roots = dict(conn.execute("SELECT name, rootpage FROM sqlite_schema WHERE type='table'").fetchall())
    version = conn.execute("PRAGMA schema_version").fetchone()[0]
    conn.execute("PRAGMA writable_schema=ON")
    conn.execute("UPDATE sqlite_schema SET rootpage=? WHERE name='programs'", (roots["users"],))
    conn.execute("UPDATE sqlite_schema SET rootpage=? WHERE name='users'", (roots["programs"],))
    conn.execute(f"PRAGMA schema_version={version + 1}")
    conn.execute("PRAGMA writable_schema=OFF")
    conn.commit()
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    return path


def test_a_copy_whose_tables_trade_b_trees_is_refused(tmp_path):
    user_ids = ["u-alpha-7f3a", "u-beta-7f3a"]  # The ID form the output would name.
    path = swapped_copy(tmp_path / "swapped.sqlite3", user_ids)
    check = sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)
    assert check.execute("PRAGMA quick_check(1)").fetchone() == ("ok",)  # Why quick_check is not enough.
    assert check.execute("PRAGMA integrity_check(1)").fetchone() != ("ok",)
    assert sorted(row[0] for row in check.execute("SELECT program_id FROM programs")) == user_ids
    check.close()
    report = audit.build_report(path, details=True)
    assert report["database"] == {"status": "failed", "code": "database_integrity_failed"}
    assert "details" not in report and not any(user_id in json.dumps(report) for user_id in user_ids)


@pytest.mark.parametrize("keep", ["half", "all_but_one_page"])
def test_a_copy_cut_short_fails_the_integrity_check(seeded, keep):
    data = seeded.read_bytes()
    seeded.write_bytes(data[: len(data) // 2] if keep == "half" else data[:-4096])
    report = audit.build_report(seeded)
    # The check itself finds the file corrupt; a file that is not SQLite at all stays database_error.
    assert report["database"] == {"status": "failed", "code": "database_integrity_failed"}
    assert not report["complete"] and "details" not in report


def test_numeric_ids_are_counted_never_named(seeded):
    """An ID with no letter (an account number, say) is never printed, even in a well-formed column."""
    number, plan_number = "104729000000000000001", "2026000000000001"
    usable_number = "2026000000000002"  # The plan model itself accepts an ID without a letter.
    course_number = "104729000000000000002"  # A second CS 5800, so its items would name the course ID.
    with writing(seeded) as conn:
        put_program(conn, number)
        conn.execute("INSERT INTO program_required_courses(program_id, course_id, requirement_type) "
                     "VALUES(?, 'c-cs5800', 'core')", (number,))
        put_plan(conn, plan("cs-ms-boston-2026-2027-bridge", "cs-ms", pathway="bridge"), plan_id=plan_number)
        put_plan(conn, plan(usable_number, "ds-ms", pathway="bridge"))
        CourseRepository(conn).insert(Course(course_id=course_number, primary_code="CS 5800",
                                             primary_name="Algorithms"), raw_text=SENTINEL)
    for details in (False, True):
        report = audit.build_report(seeded, details=details)
        values = (number, plan_number, usable_number, course_number)
        assert not [value for value in values if value in json.dumps(report)]
    assert {"code": "CS 5800", "course_id": None} in listed(report["details"], "catalog_snapshots", "absent", "CS")
    assert listed(report["details"], "courses", "duplicate_codes", "CS") == [{"code": "CS 5800",
                                                                             "course_ids": ["c-cs5800", None]}]
    legacy = section(report, "legacy_rows")["program_required_courses"]
    assert legacy["rows_with_unlisted_program_id"] == 1
    assert section(report, "program_plans")["counts"]["usable"] == 4
    plans = report["details"]["program_plans"]
    assert plans["programs_without_usable_plan"]["unlisted_malformed"] == 1
    assert plans["identity_mismatch"]["unlisted_malformed"] == 1
    assert plans["usable_scopes"]["unlisted_malformed"] == 1
    without_keys(seeded, "program_plans")
    modify(seeded, f"INSERT INTO program_plans SELECT * FROM program_plans WHERE plan_id='{usable_number}'")
    report = audit.build_report(seeded, details=True)
    assert usable_number not in json.dumps(report)
    assert report["details"]["program_plans"]["duplicate_scope_or_id"] == {"items": [], "omitted": 0,
                                                                           "unlisted_malformed": 2}


def test_course_ids_next_to_a_shared_code_are_checked_whole(seeded):
    """A course ID is named whole or not at all: one that only starts well-formed is not, one of 100 characters is."""
    long_id, tailed = "c-" + "x" * 98, "c-cs5800-copy <free text>"
    with writing(seeded) as conn:
        for course_id in (long_id, tailed):  # Two more CS 5800 records.
            CourseRepository(conn).insert(Course(course_id=course_id, primary_code="CS 5800",
                                                 primary_name="Algorithms"), raw_text=SENTINEL)
    report = audit.build_report(seeded, details=True)
    assert "free text" not in json.dumps(report)
    assert listed(report["details"], "courses", "duplicate_codes", "CS") == [
        {"code": "CS 5800", "course_ids": ["c-cs5800", long_id, None]}]
    assert listed(report["details"], "catalog_snapshots", "absent", "CS") == [
        {"code": "CS 5800", "course_id": long_id}, {"code": "CS 5800", "course_id": None}]


@pytest.mark.parametrize("value, named", [
    ("cs-ms", True), ("a" * 64, True), ("a" * 65, False), ("-cs-ms", False), ("1234", False), ("CS-MS", False),
    ("cs ms", False), ("cs-ms\n", False), ("cs-ms <free text>", False), ("2026-msai", True)])
def test_program_id_form(value, named):
    assert audit._listable_id(value) == (value if named else None)


@pytest.mark.parametrize("value, named", [
    ("cs-ms-boston-2026-2027-standard", True), ("a" * 100, True), ("a" * 101, False), ("2026000000000001", False),
    ("cs-ms-boston-2026-2027-x <free text>", False), ("2026-cs-ms-boston", True)])
def test_plan_id_form(value, named):
    assert bool(audit.PLAN_ID.fullmatch(value)) is named and audit.COURSE_ID is audit.PLAN_ID
    assert audit._listable_plan_id(value) == (value if named else None)


@pytest.mark.parametrize("value, listed", [(" CS 5800 ", "CS 5800"), ("cs5800", "CS 5800"), ("CS 5800 x", None),
                                           (None, None), (5800, None)])
def test_listable_course_code_form(value, listed):
    assert audit._listable_code(value) == listed


def test_ids_and_editions_that_only_start_well_formed_are_not_named(seeded):
    tail = " <free text>"
    with writing(seeded) as conn:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        put_plan(conn, plan("cs-ms-boston-2026-2027-bridge", "cs-ms", pathway="bridge"),
                 plan_id="cs-ms-boston-2026-2027-bridge" + tail)
        put_requisite(conn, "c-cs5800", "2025-2026" + tail, "{not json")
    report = audit.build_report(seeded, details=True)
    assert "free text" not in json.dumps(report)
    editions = section(report, "requisite_documents")["by_catalog_year"]
    assert editions["unrecognized"]["unusable"] == 1 and set(editions) == {"2025-2026", "2026-2027", "unrecognized"}
    assert report["details"]["program_plans"]["identity_mismatch"]["unlisted_malformed"] == 1
    assert listed(report["details"], "requisite_documents", "invalid_json", "CS") == [
        {"catalog_year": "unrecognized", "code": "CS 5800"}]


def test_only_editions_the_app_accepts_are_named(seeded):
    """The app accepts YYYY-YYYY with consecutive years only, so any other eight digits stay unnamed."""
    with writing(seeded) as conn:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        put_requisite(conn, "c-gone", "0012-3456", "{not json")  # An orphan row.
        put_requisite(conn, "c-cs5800", "1234-5678", "{not json")
    report = audit.build_report(seeded, details=True)
    assert "0012-3456" not in json.dumps(report) and "1234-5678" not in json.dumps(report)
    editions = section(report, "requisite_documents")["by_catalog_year"]
    assert editions["unrecognized"]["unusable"] == 2 and set(editions) == {"2025-2026", "2026-2027", "unrecognized"}
    assert listed(report["details"], "requisite_documents", "invalid_json", "CS") == [
        {"catalog_year": "unrecognized", "code": "CS 5800"}]
    assert [audit._edition(value) for value in ("2026-2027", "2026-2028", "2027-2026", None)] == [
        "2026-2027", "unrecognized", "unrecognized", "unrecognized"]


# Keys whose children are data (departments, editions, program IDs, field and table names) or enumerated
# values that the key's own rule lists; their dict children are still checked. WRAPPERS name no count
# themselves, but every name inside them (each category, each denominator) needs a rule.
STRUCTURAL = {"status", "code", "rules"}
WRAPPERS = {"counts", "denominator"}
DATA_MAPS = {"tables", "fields", "by_department", "by_catalog_year", "by_program", "status_column", "answer_warnings",
             "prerequisite", "corequisite", "description_evidence", "credit_hours_vs_course_credits", "coverage",
             "review_status", "source_fingerprint", "retrieved_on", "captured_on"}


def unexplained(report):
    """(names without a rule, rules no reported name uses) over every checked section."""
    missing, unused = [], set()
    for name, item in report["sections"].items():
        if item["status"] == "checked":
            found = set()
            walk_names(item, name, item["rules"], found, missing)
            unused |= {f"{name}.{key}" for key in set(item["rules"]) - found}
    return missing, unused


def walk_names(node, path, rules, found, missing):
    for key, value in node.items():
        if key in STRUCTURAL:
            continue
        if key not in WRAPPERS:
            found.add(key)
            if key not in rules:
                missing.append(f"{path}.{key}")
        if isinstance(value, dict):
            for child in (value.values() if key in DATA_MAPS else [value]):
                if isinstance(child, dict):
                    walk_names(child, f"{path}.{key}", rules, found, missing)


def test_every_reported_name_has_a_rule(seeded):
    assert unexplained(audit.build_report(seeded)) == ([], set())


@pytest.mark.parametrize("statements", [
    ("DROP TABLE course_catalog_sources",),  # Not compared: fewer names, all of them explained.
    ("DROP TABLE programs",),
    ("PRAGMA ignore_check_constraints=ON", "INSERT INTO schema_versions(version) VALUES(CAST(x'ff' AS TEXT))",
     "UPDATE course_catalog_sources SET snapshot=CAST(x'7bff7d' AS TEXT) WHERE course_id='c-cs5800'",
     "UPDATE program_plans SET document=CAST(x'7bff7d' AS TEXT) WHERE plan_id='ds-ms-boston-2026-2027-standard'")])
def test_every_name_in_a_partial_or_damaged_report_has_a_rule(seeded, statements):
    modify(seeded, *statements)
    missing, _ = unexplained(audit.build_report(seeded))
    assert missing == []


def assert_adds_up(report):
    sections = report["sections"]
    for name in ("courses", "catalog_snapshots", "requisite_documents", "program_plans"):
        assert sum(sections[name]["counts"].values()) == total(sections[name]), name
    courses = sections["courses"]
    assert sum(courses["status_column"].values()) == total(courses)
    in_scope = courses["in_scope_courses"]
    assert total(in_scope) == courses["counts"]["in_scope"] == sum(in_scope["by_department"].values())
    sizes = in_scope["by_department"]  # Every per-department block has these departments, of these sizes.
    catalog = sections["catalog_snapshots"]
    rows = catalog["snapshot_rows"]
    assert rows["rows_for_courses_in_scope"] + rows["rows_for_courses_out_of_scope"] + rows["orphan_rows"] == total(rows)
    usable = catalog["usable_snapshots"]
    assert total(usable) == catalog["counts"]["usable"] == usable["retrieval_date_known"] + usable["retrieval_date_unknown"]
    assert {name: item["courses_in_scope"] for name, item in catalog["by_department"].items()} == sizes
    for name, item in catalog["by_department"].items():
        assert sum(value for key, value in item.items() if key != "courses_in_scope") == sizes[name]
    for category, count in catalog["counts"].items():
        assert count == sum(item.get(category, 0) for item in catalog["by_department"].values()), category
    fields = sections["fields"]
    for counts in fields["fields"].values():
        assert sum(counts.values()) == total(fields)
    assert sum(fields["catalog_description"].values()) == total(fields)
    assert {name: item["courses_in_scope"] for name, item in fields["by_department"].items()} == sizes
    for item in fields["by_department"].values():
        for counts in item["fields"].values():
            assert sum(counts.values()) == item["courses_in_scope"]
        assert sum(item["catalog_description"].values()) == item["courses_in_scope"]
    for field, counts in fields["fields"].items():
        per_department = [item["fields"][field] for item in fields["by_department"].values()]
        for category, count in counts.items():
            assert count == sum(item.get(category, 0) for item in per_department), (field, category)
    for state in fields["catalog_description"]:
        assert fields["catalog_description"][state] == sum(
            item["catalog_description"].get(state, 0) for item in fields["by_department"].values())
    for warning, count in fields["answer_warnings"].items():
        assert count == sum(item["answer_warnings"].get(warning, 0) for item in fields["by_department"].values())
    documents = sections["requisite_documents"]
    editions = documents["by_catalog_year"]
    assert sum(stats["usable"] + stats["unusable"] for stats in editions.values()) == total(documents)
    for stats in editions.values():
        for key in ("prerequisite", "corequisite", "description_evidence", "credit_hours_vs_course_credits"):
            assert sum(stats[key].values()) == stats["usable"]
    departments = documents["by_department"].values()
    assert {name: item["courses_in_scope"] for name, item in documents["by_department"].items()} == sizes
    assert sum(sizes.values()) == total(documents["in_scope_courses"])
    for item in departments:
        for stats in item["by_catalog_year"].values():
            for key in ("prerequisite", "corequisite", "credit_hours_vs_course_credits"):
                assert sum(stats[key].values()) == stats["with_usable_document"]
    for edition, stats in editions.items():
        per_department = [item["by_catalog_year"].get(edition) for item in departments]
        assert sum(item["with_usable_document"] for item in per_department if item) == stats["usable"]
        for key in ("prerequisite", "corequisite", "credit_hours_vs_course_credits"):
            for value in stats[key]:
                assert stats[key][value] == sum(item[key][value] for item in per_department if item), (edition, key)
    plans = sections["program_plans"]
    usable = plans["usable_plans"]
    for key in ("coverage", "review_status", "source_fingerprint"):
        assert sum(usable[key].values()) == total(usable) == plans["counts"]["usable"]
    named = [stats for item in plans["by_program"].values() for stats in item["by_catalog_year"].values()]
    assert sum(stats["usable"] for stats in named) + plans["usable_plans_with_unlisted_program_id"] == total(usable)
    for stats in named:
        assert stats["partial"] + stats["complete"] == stats["usable"] == stats["draft"] + stats["source_checked"]
    programs = plans["programs"]
    assert sum(value for key, value in programs.items()
               if key not in ("denominator", "rows_with_text_not_utf8")) == total(programs)
    legacy = sections["legacy_rows"]
    for table in ("program_required_courses", "course_prerequisites"):
        block = legacy[table]
        assert block["rows_for_courses_in_scope"] + block["rows_for_courses_out_of_scope"] == total(block)
    block = legacy["program_required_courses"]
    assert (sum(block["by_program"].values()) + block["rows_for_unknown_programs"]
            + block["rows_with_unlisted_program_id"]) == total(block)
    versions = sections["schema"]["schema_versions"]
    assert versions["expected_version_rows"] + versions["other_rows"] == total(versions)


@pytest.mark.parametrize("extra", [(), ("INSERT INTO programs(program_id, full_name, prefix) VALUES(x'37', 'n', 'N')",
                                        "INSERT INTO program_required_courses(program_id, course_id, requirement_type) "
                                        "VALUES('Free text', 'c-bad-json', 'core')",
                                        "INSERT INTO schema_versions(version) VALUES('9.9')")])
def test_blocks_add_up_to_their_denominators(seeded, extra):
    if extra:
        modify(seeded, *extra)
    assert_adds_up(audit.build_report(seeded))


# --- not checked versus checked with nothing found ----------------------------------------------


def test_empty_copy_is_checked_with_zero_counts(tmp_path):
    path = tmp_path / "empty.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript((ROOT / "db/init.sql").read_text(encoding="utf-8"))
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    report = audit.build_report(path)
    assert report["complete"] is True
    assert all(item["status"] == "checked" for item in report["sections"].values())
    assert section(report, "courses")["counts"]["in_scope"] == 0
    assert section(report, "program_plans")["programs"]["without_usable_plan"] == 0
    assert section(report, "schema")["schema_versions"]["missing"] == []
    assert unexplained(report)[0] == []


def test_missing_tables_are_not_checked_not_zero(seeded):
    modify(seeded, "DROP TABLE course_catalog_sources", "DROP TABLE course_requisite_documents",
           "DROP TABLE program_plans", "DROP TABLE course_prerequisites",
           "DELETE FROM schema_versions WHERE version='1.6'")
    report = audit.build_report(seeded)
    assert report["complete"] is False
    for name in ("catalog_snapshots", "requisite_documents", "program_plans"):
        assert section(report, name) == {"status": "not_checked", "code": "table_missing"}
    fields = section(report, "fields")
    assert fields["status"] == "checked"
    for key in ("catalog_comparison", "catalog_description", "answer_warnings"):
        assert fields[key] == {"status": "not_checked", "code": "catalog_snapshots_not_checked"}
    for field in ("credits", "prereqs"):  # Not compared, so not counted as missing either.
        assert fields["fields"][field] == {"status": "not_checked", "code": "catalog_snapshots_not_checked"}
        assert all(field not in item["fields"] for item in fields["by_department"].values())
    assert fields["fields"]["term"]["no_recorded_source"] == 1
    assert section(report, "legacy_rows")["course_prerequisites"] == {"status": "not_checked", "code": "table_missing"}
    schema = section(report, "schema")
    assert schema["tables"]["course_catalog_sources"] == "missing" and schema["tables"]["courses"] == "present"
    assert schema["schema_versions"]["missing"] == ["1.6"]


@pytest.mark.parametrize("table", ["programs", "course_prerequisites", "program_required_courses", "schema_versions",
                                   "course_catalog_sources", "course_requisite_documents", "program_plans", "courses"])
def test_any_missing_table_makes_the_report_incomplete(seeded, table):
    modify(seeded, "DROP VIEW v_course_lookup", f"DROP TABLE {table}")
    report = audit.build_report(seeded)
    assert report["complete"] is False
    assert section(report, "schema")["tables"][table] == "missing"
    legacy = section(report, "legacy_rows")
    marker = {"status": "not_checked", "code": "table_missing"}
    if table == "programs":
        # The orphan category cannot be decided without programs, so no plan is counted at all.
        assert section(report, "program_plans") == marker
        assert legacy["program_required_courses"]["by_program"] == marker
        assert legacy["program_required_courses"]["denominator"] == {"rows": 5}
    elif table in ("course_prerequisites", "program_required_courses"):
        assert legacy[table] == marker
    elif table == "schema_versions":
        assert section(report, "schema")["schema_versions"] == marker
    elif table == "courses":
        assert section(report, "courses") == marker
        assert section(report, "fields") == {"status": "not_checked", "code": "courses_not_checked"}
    elif table == "course_requisite_documents":
        # Without the year documents a prereq gap cannot be told from a year rule, and the warnings depend on them.
        fields = section(report, "fields")
        no_rules = {"status": "not_checked", "code": "requisite_documents_not_checked"}
        assert fields["fields"]["prereqs"] == fields["answer_warnings"] == no_rules
        assert fields["fields"]["credits"]["catalog_consistent"] == 2 and fields["catalog_description"]["present"] == 2
        assert all("prereqs" not in item["fields"] and "answer_warnings" not in item and "catalog_description" in item
                   for item in fields["by_department"].values())


def test_schema_versions_are_counted_against_the_release_migrations(seeded):
    modify(seeded, "DELETE FROM schema_versions WHERE version='1.6'",
           "INSERT INTO schema_versions(version, notes) VALUES('9.9', 'another build')")
    versions = section(audit.build_report(seeded), "schema")["schema_versions"]
    assert versions == {"status": "checked", "denominator": {"version_rows": 8}, "expected_version_rows": 7,
                        "other_rows": 1, "present": ["1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.7"],
                        "missing": ["1.6"], "rows_with_text_not_utf8": 0}
    shipped = set(re.findall(r"VALUES \('(\d+\.\d+)'", (ROOT / "db/init.sql").read_text(encoding="utf-8")))
    assert audit.EXPECTED_VERSIONS == shipped == {f"1.{number}" for number in range(8)}


def test_present_versions_are_listed_once(seeded):
    without_keys(seeded, "schema_versions")
    modify(seeded, "INSERT INTO schema_versions SELECT * FROM schema_versions WHERE version='1.0'")
    versions = section(audit.build_report(seeded), "schema")["schema_versions"]
    assert versions["present"] == sorted(audit.EXPECTED_VERSIONS) and versions["expected_version_rows"] == 9


def generated_copy(path, definition, value):
    """A copy whose courses table computes generated_json from raw_text, which holds `value`."""
    conn = sqlite3.connect(path)
    conn.executescript((ROOT / "db/init.sql").read_text(encoding="utf-8"))
    conn.execute("DROP VIEW v_course_lookup")
    conn.execute("DROP TABLE courses")
    conn.execute("CREATE TABLE courses(course_id TEXT PRIMARY KEY, primary_code TEXT NOT NULL, primary_name TEXT "
                 f"NOT NULL, metadata JSON, raw_text TEXT, status TEXT NOT NULL DEFAULT 'pending', {definition})")
    conn.execute("INSERT INTO courses(course_id, primary_code, primary_name, metadata, raw_text) "
                 "VALUES('c-1', 'CS 5800', 'Algorithms', '{}', ?)", (value,))
    conn.commit()
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    return path


@pytest.mark.parametrize("definition", ["generated_json JSON GENERATED ALWAYS AS (raw_text) VIRTUAL",
                                        "generated_json JSON GENERATED ALWAYS AS (lower(raw_text)) STORED"])
def test_a_generated_read_column_is_never_read(tmp_path, monkeypatch, definition):
    # A generated column is computed from raw_text without the authorizer being asked about raw_text.
    value = Course(course_id="c-1", primary_code="CS 5800", primary_name="Algorithms",
                   professor=[SENTINEL]).model_dump_json()
    path = generated_copy(tmp_path / "generated.sqlite3", definition, value)
    calls = record_reads(monkeypatch)
    report = audit.build_report(path, details=True)
    assert section(report, "schema")["tables"]["courses"] == "not_plain"
    assert section(report, "courses") == {"status": "not_checked", "code": "table_not_plain"}
    assert report["complete"] is False and SENTINEL not in json.dumps(report)
    assert calls and not any(table == "courses" for _, table, *_ in calls)


def test_a_view_named_like_a_data_table_is_not_read(seeded, monkeypatch):
    modify(seeded, "DROP TABLE program_required_courses",
           "CREATE VIEW program_required_courses AS SELECT user_id AS program_id, email AS course_id FROM users")
    calls = record_reads(monkeypatch)
    report = audit.build_report(seeded)
    assert section(report, "legacy_rows")["program_required_courses"] == {"status": "not_checked",
                                                                          "code": "table_not_plain"}
    assert calls and not any(table in UNREAD_TABLES | {"program_required_courses"} for _, table, *_ in calls)
    assert SENTINEL not in json.dumps(report) and report["complete"] is False


def test_a_virtual_table_named_like_a_data_table_is_not_read(seeded, monkeypatch):
    conn = sqlite3.connect(seeded)
    try:
        conn.execute("DROP TABLE course_prerequisites")
        conn.execute("CREATE VIRTUAL TABLE course_prerequisites USING fts5(course_id, prereq_course_id)")
    except sqlite3.OperationalError:
        pytest.skip("this SQLite build has no FTS5")
    conn.execute("INSERT INTO course_prerequisites VALUES(?, ?)", (SENTINEL, SENTINEL))
    conn.commit()
    conn.close()
    calls = record_reads(monkeypatch)
    report = audit.build_report(seeded)
    assert section(report, "legacy_rows")["course_prerequisites"] == {"status": "not_checked",
                                                                      "code": "table_not_plain"}
    assert calls and not any(table in UNREAD_TABLES | {"course_prerequisites"} for _, table, *_ in calls)
    assert SENTINEL not in json.dumps(report) and report["complete"] is False


def test_a_missing_read_column_is_not_checked(seeded):
    modify(seeded, "ALTER TABLE course_catalog_sources RENAME COLUMN snapshot TO payload")
    report = audit.build_report(seeded)
    assert section(report, "schema")["tables"]["course_catalog_sources"] == "column_missing"
    assert section(report, "catalog_snapshots") == {"status": "not_checked", "code": "column_missing"}


def test_courses_failure_leaves_dependent_sections_not_checked(seeded, monkeypatch):
    def failing(self):
        raise audit._Failed("row_budget")

    monkeypatch.setattr(audit._Audit, "courses", failing)
    report = audit.build_report(seeded, details=True)
    assert section(report, "courses") == {"status": "failed", "code": "row_budget"}
    for name in ("catalog_snapshots", "fields", "requisite_documents", "legacy_rows"):
        assert section(report, name) == {"status": "not_checked", "code": "courses_not_checked"}
    assert section(report, "program_plans")["status"] == "checked"
    assert "courses" not in report["details"]


def test_an_unexpected_error_fails_only_its_section(seeded, monkeypatch):
    def broken(self):
        raise KeyError(SENTINEL)

    monkeypatch.setattr(audit._Audit, "requisite_documents", broken)
    report = audit.build_report(seeded)
    assert section(report, "requisite_documents") == {"status": "failed", "code": "section_failed"}
    assert section(report, "program_plans")["status"] == "checked" and report["complete"] is False
    assert SENTINEL not in json.dumps(report)


def test_row_budget_fails_instead_of_truncating(seeded, monkeypatch):
    conn = sqlite3.connect(seeded)
    conn.row_factory = sqlite3.Row
    probe = audit._Audit(conn, audit._Reads(), {}, False)
    try:
        monkeypatch.setattr(audit, "MAX_ROWS", 13)  # Exactly the course rows: still read.
        assert len(probe.rows("SELECT course_id FROM courses")) == 13
        monkeypatch.setattr(audit, "MAX_ROWS", 12)
        with pytest.raises(audit._Failed, match="row_budget"):
            probe.rows("SELECT course_id FROM courses")
    finally:
        conn.close()


@pytest.mark.parametrize("limit, value", [("MAX_VM_STEPS", 0), ("DEADLINE_SECONDS", -1)])
def test_sqlite_budget_is_a_fixed_failure(seeded, monkeypatch, limit, value):
    monkeypatch.setattr(audit, "PROGRESS_INTERVAL", 1)
    monkeypatch.setattr(audit, limit, value)
    report = audit.build_report(seeded)
    assert report["database"] == {"status": "failed", "code": "sqlite_budget"}
    assert all(item["code"] == "database_unavailable" for item in report["sections"].values())


def test_vm_steps_are_counted_per_progress_interval(seeded, monkeypatch):
    # Each check adds the interval; counting checks instead would make the step budget 100 times looser.
    monkeypatch.setattr(audit, "PROGRESS_INTERVAL", 100)
    monkeypatch.setattr(audit, "MAX_VM_STEPS", 100)
    assert "sqlite_budget" in json.dumps(audit.build_report(seeded))


@pytest.mark.parametrize("seconds, spent", [(audit.DEADLINE_SECONDS - 0.5, False), (audit.DEADLINE_SECONDS + 0.5, True)])
def test_the_deadline_is_the_documented_number_of_seconds(seeded, monkeypatch, seconds, spent):
    class Clock:
        calls = 0

        def monotonic(self):
            self.calls += 1
            return 0.0 if self.calls == 1 else seconds  # The first call sets the deadline.

    monkeypatch.setattr(audit, "time", Clock())
    monkeypatch.setattr(audit, "PROGRESS_INTERVAL", 1)
    assert ("sqlite_budget" in json.dumps(audit.build_report(seeded))) is spent


def test_the_vm_step_budget_boundary(tmp_path, monkeypatch):
    """The budget allows exactly MAX_VM_STEPS: three checks of a three-interval budget pass, the fourth does not."""
    path = tmp_path / "empty.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript((ROOT / "db/init.sql").read_text(encoding="utf-8"))
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    interval = 10 ** 9  # So large that SQLite itself never calls the handler while the PRAGMAs run.
    monkeypatch.setattr(audit, "PROGRESS_INTERVAL", interval)
    monkeypatch.setattr(audit, "MAX_VM_STEPS", 3 * interval)
    handlers = []

    class Recording(sqlite3.Connection):
        def set_progress_handler(self, handler, n):
            handlers.append(handler)
            return super().set_progress_handler(handler, n)

    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True, factory=Recording)
    budget = {"exceeded": False}
    audit._prepare(conn, audit._Reads(), budget)
    (handler,) = handlers
    assert [handler() for _ in range(4)] == [0, 0, 0, 1] and budget["exceeded"] is True
    conn.close()


def test_sqlite_3_37_is_new_enough(seeded, monkeypatch):
    monkeypatch.setattr(audit.sqlite3, "sqlite_version_info", (3, 37, 0))
    assert audit.build_report(seeded)["database"] == {"status": "checked", "code": "read_only_snapshot"}


def test_a_read_error_that_is_not_a_denial_is_a_database_error(seeded, monkeypatch):
    original = audit._Audit.rows

    def rows(self, sql):
        if "FROM courses" in sql:
            raise sqlite3.DatabaseError("damaged page")
        return original(self, sql)

    monkeypatch.setattr(audit._Audit, "rows", rows)
    report = audit.build_report(seeded)
    assert section(report, "courses") == {"status": "failed", "code": "database_error"}
    assert section(report, "fields") == {"status": "not_checked", "code": "courses_not_checked"}


def test_a_budget_spent_mid_audit_fails_the_remaining_sections_with_its_code(seeded, monkeypatch):
    class Clock:
        late = False

        def monotonic(self):
            return 1e9 if self.late else 0.0

    clock = Clock()
    original = audit._Audit.courses

    def late_courses(self):
        clock.late = True  # The deadline passes while the courses are read.
        return original(self)

    monkeypatch.setattr(audit, "time", clock)
    monkeypatch.setattr(audit, "PROGRESS_INTERVAL", 1)
    monkeypatch.setattr(audit._Audit, "courses", late_courses)
    report = audit.build_report(seeded)
    assert report["database"]["status"] == "checked" and report["complete"] is False
    assert section(report, "schema")["status"] == "checked"
    assert section(report, "courses") == {"status": "failed", "code": "sqlite_budget"}
    assert section(report, "program_plans") == {"status": "failed", "code": "sqlite_budget"}
    assert section(report, "fields") == {"status": "not_checked", "code": "courses_not_checked"}


def test_a_section_that_fails_midway_lists_nothing(seeded, monkeypatch):
    def failing(self):
        self.note("legacy_rows", "rows", "CS 5800")
        raise audit._Failed("row_budget")

    monkeypatch.setattr(audit._Audit, "legacy_rows", failing)
    report = audit.build_report(seeded, details=True)
    assert section(report, "legacy_rows") == {"status": "failed", "code": "row_budget"}
    assert "legacy_rows" not in report["details"] and "courses" in report["details"]


MAX_TEXT = 100_000


def test_decode_budget_boundary_and_stored_types():
    text = json.dumps({"pad": "a" * 20})
    assert audit._decode(text, len(text), CatalogSnapshot) == ("invalid_record", None)
    assert audit._decode(text, len(text) - 1, CatalogSnapshot) == ("oversize", None)
    blob = "é".encode() * 10  # A BLOB's budget counts bytes, as the requisite repository's does.
    assert audit._decode(blob, len(blob) - 1, CatalogSnapshot) == ("oversize", None)
    for value in (None, 3, 1.5, audit._Undecodable(b"\xff"), b"\xff{}", b"{not json"):
        assert audit._decode(value, 100, CatalogSnapshot) == ("invalid_json", None), value
    assert audit._decode(b"{}", 100, CatalogSnapshot) == ("invalid_record", None)
    deep = "[" * 200_000 + "]" * 200_000  # Valid JSON, nested deeper than the parser allows.
    with pytest.raises(RecursionError):
        json.loads(deep)
    assert audit._decode(deep, len(deep), CatalogSnapshot) == ("invalid_json", None)
    good = snapshot("CS 5800", "Algorithms").model_dump_json()
    for value in (good, good.encode()):
        category, record = audit._decode(value, len(value), CatalogSnapshot)
        assert category == "decoded" and record.course_code == "CS 5800"


def test_blob_json_is_utf8_or_invalid_like_the_app():
    good = snapshot("CS 5800", "Café").model_dump_json()
    category, record = audit._decode(good.encode("utf-8"), MAX_TEXT, CatalogSnapshot)
    assert category == "decoded" and record.course_name == "Café"
    latin = good.encode("latin-1")  # The same text with é stored as one byte, which is not UTF-8.
    assert audit._decode(latin, MAX_TEXT, CatalogSnapshot) == ("invalid_json", None)
    with pytest.raises(ValueError):
        CatalogSnapshot.model_validate_json(latin)  # The app rejects it as well.


def test_course_json_budget_is_one_million_characters(seeded):
    with writing(seeded) as conn:
        raw_course(conn, "c-long", "CS 9995", "Long", json.dumps({"pad": "a" * 300_000}))
    counts = section(audit.build_report(seeded), "courses")["counts"]
    assert (counts["invalid_record"], counts["oversize"]) == (2, 1)  # c-long is decoded; only c-oversize is not.


@pytest.mark.parametrize("hours, credits, expected", [
    (None, 4, "not_captured"), ("1-4 Hours", 4, "range_not_compared"), ("1.5 Hours", 1, "fractional_not_compared"),
    ("4 Hours", None, "course_credits_missing"), ("4 Hours", 4, "consistent"), ("3 Hours", 4, "conflict"),
    ("0 Hours", 0, "consistent")])
def test_credit_hours_comparison(hours, credits, expected):
    value = CatalogCreditHours.from_text(hours) if hours else None
    assert audit.credit_comparison(value, credits) == expected


def test_text_that_is_not_utf8_counts_for_its_row(seeded):
    modify(seeded, "PRAGMA ignore_check_constraints=ON",
           "UPDATE courses SET generated_json=CAST(x'7bff7d' AS TEXT) WHERE course_id='c-bad-json'",
           "UPDATE courses SET primary_code=CAST(x'4353ff' AS TEXT) WHERE course_id='c-invalid'",
           "UPDATE course_catalog_sources SET snapshot=CAST(x'7bff7d' AS TEXT) WHERE course_id='c-cs5800'",
           "UPDATE course_requisite_documents SET document=CAST(x'7bff7d' AS TEXT) WHERE course_id='c-cs5800'",
           "UPDATE program_plans SET document=CAST(x'7bff7d' AS TEXT) "
           "WHERE plan_id='ds-ms-boston-2026-2027-standard'",
           "INSERT INTO programs(program_id, full_name, prefix) VALUES(CAST(x'ff' AS TEXT), 'n', 'N')",
           "INSERT INTO schema_versions(version) VALUES(CAST(x'ff' AS TEXT))",
           "UPDATE course_prerequisites SET prereq_course_id=CAST(x'ff' AS TEXT) WHERE course_id='c-cs6140'",
           "INSERT INTO program_required_courses(program_id, course_id, requirement_type) "
           "VALUES('cs-ms', CAST(x'ff' AS TEXT), 'core')")
    report = audit.build_report(seeded, details=True)
    assert report["complete"] is True and all(item["status"] == "checked" for item in report["sections"].values())
    # Each value counts for its own row, in its own category ahead of the ordinary ones, and can be found.
    courses = section(report, "courses")["counts"]
    assert (courses["in_scope"], courses["text_not_utf8"], courses["invalid_json"], courses["invalid_record"]) == (
        8, 2, 0, 0)
    # CS 9998's own code is the bad value, so only CS 9999 can be listed.
    assert report["details"]["courses"]["text_not_utf8"] == {
        "unlisted_malformed": 1, "by_department": {"CS": {"items": ["CS 9999"], "omitted": 0}}}
    catalog = section(report, "catalog_snapshots")
    assert (catalog["counts"]["usable"], catalog["counts"]["text_not_utf8"], catalog["counts"]["invalid_json"]) == (
        2, 1, 1)
    assert catalog["snapshot_rows"]["rows_with_text_not_utf8"] == 1
    assert listed(report["details"], "catalog_snapshots", "text_not_utf8", "CS") == ["CS 5800"]
    documents = section(report, "requisite_documents")["counts"]
    assert (documents["usable"], documents["text_not_utf8"], documents["invalid_json"]) == (2, 1, 1)
    assert report["details"]["requisite_documents"]["text_not_utf8"]["by_department"]["CS"]["items"] == [
        {"catalog_year": "2026-2027", "code": "CS 5800"}]
    plans = section(report, "program_plans")
    assert (plans["counts"]["usable"], plans["counts"]["text_not_utf8"], plans["counts"]["invalid_json"]) == (2, 1, 0)
    assert report["details"]["program_plans"]["text_not_utf8"]["items"] == ["ds-ms-boston-2026-2027-standard"]
    assert (plans["programs"]["id_unusable"], plans["programs"]["rows_with_text_not_utf8"]) == (1, 1)
    versions = section(report, "schema")["schema_versions"]
    assert (versions["other_rows"], versions["rows_with_text_not_utf8"]) == (1, 1)
    legacy = section(report, "legacy_rows")
    assert legacy["course_prerequisites"]["rows_with_text_not_utf8"] == 1
    assert legacy["program_required_courses"]["rows_with_text_not_utf8"] == 1
    # Why these come first: any app query that fetches such a value fails as a whole.
    conn = sqlite3.connect(seeded)
    conn.row_factory = sqlite3.Row
    batch = [Course(course_id="c-cs5800", primary_code="CS 5800", primary_name="Algorithms"),
             Course(course_id="c-cs5200", primary_code="CS 5200", primary_name="Database Management Systems")]
    with pytest.raises(sqlite3.OperationalError):
        CatalogSourceRepository(conn).get_batch(batch)
    conn.close()


def test_a_bad_snapshot_row_is_found_even_next_to_a_duplicate(seeded):
    without_keys(seeded, "course_catalog_sources")
    modify(seeded, "INSERT INTO course_catalog_sources(course_id, snapshot) VALUES('c-cs5800', CAST(x'7bff7d' AS TEXT))")
    counts = section(audit.build_report(seeded), "catalog_snapshots")["counts"]
    # The app's catalog query fails on the bad row whether or not the course has another one.
    assert (counts["usable"], counts["text_not_utf8"], counts["duplicate_rows"]) == (2, 1, 0)


def test_a_bad_course_id_is_still_the_key_its_rows_share(seeded):
    modify(seeded, "PRAGMA ignore_check_constraints=ON",
           "UPDATE courses SET course_id=CAST(x'632d636166e9' AS TEXT) WHERE course_id='c-invalid'",
           "INSERT INTO course_catalog_sources(course_id, snapshot) VALUES(CAST(x'632d636166e9' AS TEXT), '{}')")
    rows = section(audit.build_report(seeded), "catalog_snapshots")["snapshot_rows"]
    # SQLite compares the bytes, so the row belongs to an excluded course, not to no course.
    assert (rows["orphan_rows"], rows["rows_for_courses_out_of_scope"], rows["rows_with_text_not_utf8"]) == (1, 2, 1)


def test_bad_rows_of_an_excluded_course_are_listed(seeded):
    modify(seeded, "PRAGMA ignore_check_constraints=ON",
           "UPDATE course_catalog_sources SET snapshot=CAST(x'7bff7d' AS TEXT) WHERE course_id='synth-0001'",
           "UPDATE course_requisite_documents SET document=CAST(x'7bff7d' AS TEXT) WHERE course_id='synth-0001'")
    report = audit.build_report(seeded, details=True)
    catalog = section(report, "catalog_snapshots")
    assert catalog["counts"]["text_not_utf8"] == 0 and catalog["snapshot_rows"]["rows_with_text_not_utf8"] == 1
    # The app still serves the synthetic course, and every batch with it fails: the rows can be found.
    assert listed(report["details"], "catalog_snapshots", "rows_with_text_not_utf8", "SYN") == ["SYN 1000"]
    assert listed(report["details"], "requisite_documents", "text_not_utf8", "SYN") == [
        {"catalog_year": "2026-2027", "code": "SYN 1000"}]


def test_an_excluded_course_with_a_free_text_code_names_nothing(seeded):
    modify(seeded, "PRAGMA ignore_check_constraints=ON",
           f"UPDATE courses SET primary_code='{SENTINEL}' WHERE course_id='synth-0001'",
           "UPDATE course_catalog_sources SET snapshot=CAST(x'7bff7d' AS TEXT) WHERE course_id='synth-0001'")
    report = audit.build_report(seeded, details=True)
    assert SENTINEL not in json.dumps(report)
    assert report["details"]["catalog_snapshots"]["rows_with_text_not_utf8"] == {"unlisted_malformed": 1,
                                                                                 "by_department": {}}


def test_blank_catalog_codes_list_nothing(seeded):
    modify(seeded, "UPDATE course_catalog_sources SET snapshot=json_set(snapshot, '$.prereq_codes', "
                   "json_array('   ', '')) WHERE course_id='c-cs5200'",
           "DELETE FROM course_requisite_documents WHERE course_id='c-cs5200'")  # Else its year rules decide prereqs.
    report = audit.build_report(seeded, details=True)
    assert section(report, "catalog_snapshots")["usable_snapshots"]["prereq_codes_listed"] == 1  # CS 5800 only.
    prereqs = section(report, "fields")["fields"]["prereqs"]
    assert (prereqs["catalog_only"], prereqs["catalog_lists_none"]) == (0, 1)  # CS 5200's catalog lists nothing.
    assert listed(report["details"], "fields", "prereqs.catalog_lists_none", "CS") == ["CS 5200"]


@pytest.mark.parametrize("statement, block", [
    # Any read column decides, not only the JSON one, and ahead of the orphan, scope and identity checks.
    ("UPDATE courses SET status=CAST(x'ff' AS TEXT) WHERE course_id='c-cs5200'", ("courses", "counts")),
    ("UPDATE course_catalog_sources SET snapshot=CAST(x'7bff7d' AS TEXT) WHERE course_id='c-gone'",
     ("catalog_snapshots", "snapshot_rows")),
    ("UPDATE course_requisite_documents SET content_hash=CAST(x'ff' AS TEXT) WHERE course_id='c-cs5200'",
     ("requisite_documents", "counts")),
    ("UPDATE course_requisite_documents SET document=CAST(x'7bff7d' AS TEXT) WHERE course_id='c-gone'",
     ("requisite_documents", "counts")),
    ("UPDATE program_plans SET campus=CAST(x'ff' AS TEXT) WHERE plan_id='ds-ms-boston-2026-2027-standard'",
     ("program_plans", "counts")),
    ("UPDATE program_plans SET document=CAST(x'7bff7d' AS TEXT) WHERE plan_id='gone-ms-boston-2026-2027-standard'",
     ("program_plans", "counts"))])
def test_a_bad_value_in_any_read_column_counts_first(seeded, statement, block):
    modify(seeded, "PRAGMA ignore_check_constraints=ON", statement)
    name, key = block
    counts = section(audit.build_report(seeded), name)[key]
    assert counts["rows_with_text_not_utf8" if key == "snapshot_rows" else "text_not_utf8"] == 1


def test_a_bad_row_among_duplicate_course_ids_is_counted_as_not_utf8(seeded):
    without_keys(seeded, "courses")
    modify(seeded, "INSERT INTO courses SELECT * FROM courses WHERE course_id='c-info6105'",
           "UPDATE courses SET primary_name=CAST(x'4e616dff' AS TEXT) WHERE rowid=(SELECT max(rowid) FROM courses)")
    counts = section(audit.build_report(seeded), "courses")["counts"]
    assert (counts["in_scope"], counts["duplicate_id"], counts["text_not_utf8"]) == (7, 1, 1)


def test_a_bad_requisite_row_next_to_a_duplicate_is_counted_as_not_utf8(seeded):
    without_keys(seeded, "course_requisite_documents")
    modify(seeded, "INSERT INTO course_requisite_documents(course_id, catalog_year, document, content_hash) "
                   "VALUES('c-cs5800', '2026-2027', CAST(x'7bff7d' AS TEXT), 'x')")
    counts = section(audit.build_report(seeded), "requisite_documents")["counts"]
    # The course page's query fails on the bad row whether or not the edition has another one.
    assert (counts["usable"], counts["duplicate_rows"], counts["text_not_utf8"]) == (2, 1, 1)


def test_blob_values_are_not_counted_as_not_utf8(seeded):
    # A BLOB is not TEXT: the app reads it without failing, so it never counts as text that is not UTF-8.
    modify(seeded, "INSERT INTO schema_versions(version) VALUES(x'ff')",
           "INSERT INTO program_required_courses(program_id, course_id, requirement_type) "
           "VALUES(x'ff', 'c-cs5800', 'core')",
           "INSERT INTO course_prerequisites(course_id, prereq_course_id) VALUES('c-cs5800', x'ff')")
    report = audit.build_report(seeded)
    versions = section(report, "schema")["schema_versions"]
    assert (versions["other_rows"], versions["rows_with_text_not_utf8"]) == (1, 0)
    legacy = section(report, "legacy_rows")
    assert legacy["program_required_courses"]["rows_with_text_not_utf8"] == 0
    assert legacy["course_prerequisites"]["rows_with_text_not_utf8"] == 0


def test_undecodable_values_compare_by_their_bytes():
    first, again, other = audit._Undecodable(b"\xfe"), audit._Undecodable(b"\xfe"), audit._Undecodable(b"\xff")
    assert first == again and hash(first) == hash(again) and first != other
    assert first != "�" and first != b"\xfe" and repr(first) == "<not UTF-8>"
    assert audit._text(b"\xfe") == first and audit._text("ok".encode()) == "ok"


# --- consistency with the code paths the app uses ---------------------------------------------


def served_courses(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn, CourseRepository(conn).get_batch(IN_SCOPE_IDS)


BLOB_ROWS = (
    "UPDATE course_catalog_sources SET snapshot=CAST(snapshot AS BLOB) WHERE course_id='c-cs5800'",
    "UPDATE course_requisite_documents SET document=CAST(document AS BLOB) WHERE course_id='c-cs5800'",
    "UPDATE program_plans SET document=CAST(document AS BLOB) WHERE plan_id='ds-ms-boston-2026-2027-standard'",
    "UPDATE courses SET generated_json=CAST(generated_json AS BLOB) WHERE course_id='c-ds5110'",
)


@pytest.mark.parametrize("stored_as", ["text", "blob"])
def test_usable_rows_are_the_ones_the_repositories_serve(seeded, stored_as):
    if stored_as == "blob":  # model_validate_json reads a BLOB of JSON text; SQLite builds differ on json_valid.
        modify(seeded, "PRAGMA ignore_check_constraints=ON", *BLOB_ROWS)
    report = audit.build_report(seeded)
    conn, courses = served_courses(seeded)
    try:
        if stored_as == "blob":
            kinds = conn.execute("SELECT typeof(generated_json) FROM courses WHERE course_id='c-ds5110'").fetchone()
            assert kinds[0] == "blob"
        assert len(courses) == section(report, "courses")["counts"]["in_scope"] == 8
        attached = CatalogSourceRepository(conn).get_batch(list(courses.values()))
        assert len(attached) == section(report, "catalog_snapshots")["counts"]["usable"] == 3
        served = sum(len(CourseRequisiteRepository(conn).list_for_course(course_id).documents)
                     for course_id in courses)
        assert served == section(report, "requisite_documents")["counts"]["usable"] == 3
        plans = sum(len(ProgramPlanRepository(conn).list_for_program(program))
                    for program in ("cs-ms", "ds-ms", "info-ms", "aai-ms"))
        assert plans == section(report, "program_plans")["counts"]["usable"] == 3
    finally:
        conn.close()


def test_oversize_values_are_not_decoded_although_the_app_has_no_limit(seeded):
    # The one documented difference from the app: a valid snapshot over the report's budget is not decoded.
    conn = sqlite3.connect(seeded)
    text = conn.execute("SELECT snapshot FROM course_catalog_sources WHERE course_id='c-cs5200'").fetchone()[0]
    conn.execute("UPDATE course_catalog_sources SET snapshot=? WHERE course_id='c-cs5200'",
                 (text[:-1] + " " * audit.MAX_SNAPSHOT_JSON + "}",))
    conn.commit()
    conn.close()
    counts = section(audit.build_report(seeded), "catalog_snapshots")["counts"]
    assert (counts["usable"], counts["oversize"]) == (2, 2)
    conn, courses = served_courses(seeded)
    try:
        assert "c-cs5200" in CatalogSourceRepository(conn).get_batch([courses["c-cs5200"]])
    finally:
        conn.close()


def test_an_orphan_plan_is_unusable_here_although_the_course_page_shows_it(seeded):
    """A documented difference: course_context does not check programs, so the course page still shows it."""
    with writing(seeded) as conn:
        put_plan(conn, plan("lost-ms-boston-2026-2027-standard", "lost-ms", review_status="source_checked"))
        shown = [item.plan_id for item in ProgramPlanRepository(conn).course_context("CS 5800", "2026-2027").plans]
    assert "lost-ms-boston-2026-2027-standard" in shown
    plans = section(audit.build_report(seeded), "program_plans")
    assert plans["counts"]["orphan_rows"] == 2 and "lost-ms" not in plans["by_program"]
    assert "course_context does not check programs" in audit.RULES["program_plans"]["orphan_rows"]


def chat_evidence(path):
    """What the chat path gives each in-scope course, one course per batch (the report's per-course model)."""
    conn, courses = served_courses(path)
    try:
        return courses, {course_id: build_answer_evidence(conn, [course])[course_id]
                         for course_id, course in courses.items()}
    finally:
        conn.close()


def test_missing_categories_agree_with_answer_evidence(seeded):
    courses, served = chat_evidence(seeded)
    assert any(evidence.requisites.editions for evidence in served.values())  # Year rules are part of the check.
    for course_id, course in courses.items():
        evidence = served[course_id]
        gaps = {field for field in AVAILABILITY_FIELDS
                if audit.field_category(course, field, evidence.catalog, evidence.requisites)
                in ("missing", "catalog_only", "catalog_lists_none")}
        assert gaps == set(evidence.missing_fields) - {"catalog_description"}, course_id
        conflict = audit.field_category(course, "credits", evidence.catalog) == "catalog_conflict"
        assert conflict == ("catalog_metadata_conflict" in evidence.warnings), course_id


@pytest.mark.parametrize("change", ["none", "blob", "editions_differ", "not_utf8_row"])
def test_fields_and_warnings_are_what_the_chat_path_gives(seeded, change):
    """The report's own reading of snapshots and year documents gives the same gaps and warnings as chat."""
    with writing(seeded) as conn:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        if change == "blob":
            for statement in BLOB_ROWS:
                conn.execute(statement)
        elif change == "editions_differ":
            put_requisite(conn, "c-cs5800", "2025-2026", requisite("c-cs5800", "CS 5800", "Algorithms",
                                                                   year="2025-2026", prerequisite="CS 5010"))
        elif change == "not_utf8_row":
            conn.execute("INSERT INTO course_requisite_documents(course_id, catalog_year, document, content_hash) "
                         "VALUES('c-cs5200', '2027-2028', CAST(x'7bff7d' AS TEXT), ?)", ("0" * 64,))
    report = audit.build_report(seeded)
    courses, served = chat_evidence(seeded)
    fields = section(report, "fields")
    expected = Counter(warning for evidence in served.values() for warning in set(evidence.warnings))
    assert fields["answer_warnings"] == dict(sorted(expected.items()))
    for field in AVAILABILITY_FIELDS:
        counts = fields["fields"][field]
        gaps = sum(field in evidence.missing_fields for evidence in served.values())
        assert counts["missing"] + counts["catalog_only"] + counts["catalog_lists_none"] == gaps, field
    assert fields["fields"]["prereqs"]["year_rules"] == sum(bool(item.requisites.editions) for item in served.values())
    flagged = {"editions_differ": "requisites_differ_by_catalog_year", "not_utf8_row": "structured_requisites_unusable"}
    if change in flagged:
        assert flagged[change] in served["c-cs5800" if change == "editions_differ" else "c-cs5200"].warnings
    if change == "not_utf8_row":  # Chat's query for CS 5200 fails, so its year rule is gone and the code is a gap.
        assert served["c-cs5200"].requisites.storage == "schema_unusable"
        assert "prereqs" in served["c-cs5200"].missing_fields


def test_a_year_rule_decides_prereqs_first():
    course = Course(course_id="c-cs5800", primary_code="CS 5800", primary_name="Algorithms", prereqs=["CS 5004"])
    with_rules = requisite_evidence(course, [requisite("c-cs5800", "CS 5800", "Algorithms", prerequisite="CS 5004")])
    listed_snapshot = snapshot("CS 5800", "Algorithms", prereqs=["CS 5010"])
    assert audit.field_category(course, "prereqs", listed_snapshot, with_rules) == "year_rules"
    for without in (None, requisite_evidence(course, []), RequisiteEvidence(storage="schema_unusable")):
        assert audit.field_category(course, "prereqs", listed_snapshot, without) == "catalog_conflict"
    assert audit.field_category(course, "credits", None, with_rules) == "missing"  # Only prereqs has year rules.
    evidence = course_answer_evidence(course, listed_snapshot, requisites=with_rules)
    assert "prereqs" not in evidence.missing_fields and "prerequisite_logic_unavailable" not in evidence.warnings


@pytest.mark.parametrize("stored, listed, expected", [
    ([], [], "catalog_lists_none"), ([], ["CS 5800"], "catalog_only"), (["CS 5800"], [], "catalog_conflict"),
    (["cs  5800"], ["CS 5800"], "catalog_consistent"),
    (["CS 5800", "CS 5004"], ["CS 5004", "CS 5800"], "catalog_consistent"),
    (["CS 5800"], ["CS 5800", "CS 5004"], "catalog_conflict"),
    (["CS5004"], ["CS 5004"], "catalog_consistent"), (["cs5004", "CS 5800"], ["CS 5004", "CS 5800"], "catalog_consistent"),
    ([], ["   "], "catalog_lists_none"), (["CS 5800"], ["CS 5800", ""], "catalog_consistent"),
    (["CS 5004", "not a code"], ["CS 5004"], "catalog_conflict"), (["CS 5800"], ["cs5800"], "catalog_consistent")])
def test_prerequisite_code_sets(stored, listed, expected):
    course = Course(course_id="c", primary_code="CS 6140", primary_name="Machine Learning", prereqs=stored)
    listed_snapshot = snapshot("CS 6140", "Machine Learning", prereqs=listed)
    assert audit.field_category(course, "prereqs", listed_snapshot) == expected


def test_zero_credits_is_a_value_and_no_snapshot_means_no_comparison():
    course = Course(course_id="c", primary_code="CS 6140", primary_name="Machine Learning", credits=0)
    assert audit.field_category(course, "credits", None) == "no_recorded_source"
    with_zero = snapshot("CS 6140", "Machine Learning", credits=0)
    assert audit.field_category(course, "credits", with_zero) == "catalog_consistent"
    assert audit.field_category(course, "credits", snapshot("CS 6140", "Machine Learning")) == "no_recorded_source"
    unset = Course(course_id="c", primary_code="CS 6140", primary_name="Machine Learning")
    assert audit.field_category(unset, "credits", snapshot("CS 6140", "Machine Learning", credits=4)) == "catalog_only"
    assert audit.field_category(unset, "credits", snapshot("CS 6140", "Machine Learning")) == "catalog_lists_none"
    assert audit.field_category(unset, "credits", None) == "missing"
    assert audit.field_category(unset, "prereqs", None) == "missing"


def test_real_catalog_ingest_agrees_and_dates_stay_unknown(tmp_path):
    from scrapers.neu_catalog import _parse_dept_html
    from scripts.ingest_neu_catalog import upsert_one

    path = tmp_path / "ingested.sqlite3"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript((ROOT / "db/init.sql").read_text(encoding="utf-8"))
    entries = {}
    for department in ("cs", "aai"):
        html = (ROOT / f"tests/fixtures/neu_catalog/dept_{department}.html").read_text(encoding="utf-8")
        url = f"https://catalog.northeastern.edu/course-descriptions/{department}/"
        for entry in _parse_dept_html(html, source_url=url):
            entries[entry.course_code] = entry
    repo, catalog = CourseRepository(conn), CatalogSourceRepository(conn)
    for entry in entries.values():
        upsert_one(entry, course_repo=repo, catalog_repo=catalog)
    conn.commit()
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    report = audit.build_report(path)
    snapshots = section(report, "catalog_snapshots")
    assert len(entries) > 10 and {code.split()[0] for code in entries} == {"AAI", "CS"}
    assert snapshots["counts"]["usable"] == len(entries) == section(report, "courses")["counts"]["in_scope"]
    usable = snapshots["usable_snapshots"]
    assert usable["retrieval_date_unknown"] == len(entries)  # The catalog scraper records no fetch time.
    fields = section(report, "fields")["fields"]
    assert fields["credits"]["catalog_conflict"] == fields["prereqs"]["catalog_conflict"] == 0
    assert fields["credits"]["catalog_consistent"] == sum(entry.credits is not None for entry in entries.values())
    assert fields["prereqs"]["catalog_consistent"] == sum(bool(entry.prereqs) for entry in entries.values())
    # Every course has a usable snapshot, so nothing is "missing": the catalog itself lists no value.
    ranges = sum(entry.credits is None for entry in entries.values())
    assert ranges > 0 and fields["credits"]["catalog_lists_none"] == ranges == usable["credits_missing"]
    assert fields["prereqs"]["catalog_lists_none"] == sum(not entry.prereqs for entry in entries.values())
    assert fields["credits"]["missing"] == fields["prereqs"]["missing"] == 0


def test_unknown_retrieval_date_is_not_replaced_by_import_time(seeded):
    modify(seeded, "DELETE FROM course_catalog_sources WHERE course_id='c-cs5200'")
    report = audit.build_report(seeded)
    usable = section(report, "catalog_snapshots")["usable_snapshots"]
    assert usable["retrieval_date_unknown"] == total(usable) == 2
    assert usable["retrieval_date_known"] == 0
    assert usable["retrieved_on"] == {"earliest": None, "latest": None}
    assert "2026-10-07" not in json.dumps(report)  # The snapshots' import date is never reported as a date.


def test_date_ranges_span_every_usable_row(seeded):
    modify(seeded, "UPDATE course_catalog_sources SET snapshot=json_set(snapshot, '$.retrieved_at', "
                   "'2026-08-01T10:00:00Z') WHERE course_id='c-ds5220a'",
           "DELETE FROM course_requisite_documents WHERE course_id='c-ds5220b'")
    with writing(seeded) as conn:
        put_requisite(conn, "c-ds5220b", "2026-2027",
                      requisite("c-ds5220b", "DS 5220", "Supervised Machine Learning",
                                captured_at=datetime(2026, 9, 15, 8, tzinfo=UTC)))
        put_plan(conn, plan("info-ms-boston-2026-2027-align", "info-ms", pathway="align", captured_on="2026-09-01"))
    report = audit.build_report(seeded)
    retrieved = section(report, "catalog_snapshots")["usable_snapshots"]["retrieved_on"]
    assert retrieved == {"earliest": "2026-08-01", "latest": "2026-09-30"}
    captured = section(report, "requisite_documents")["by_catalog_year"]["2026-2027"]["captured_on"]
    assert captured == {"earliest": "2026-09-15", "latest": "2026-10-01"}
    plans = section(report, "program_plans")["usable_plans"]["captured_on"]
    assert plans == {"earliest": "2026-09-01", "latest": "2026-10-01"}


def test_duplicate_rows_choose_no_winner(seeded):
    for table in ("course_catalog_sources", "program_plans", "course_requisite_documents"):
        without_keys(seeded, table)
    modify(seeded, "INSERT INTO course_catalog_sources SELECT * FROM course_catalog_sources WHERE course_id='c-cs5800'",
           "INSERT INTO program_plans SELECT * FROM program_plans WHERE plan_id='ds-ms-boston-2026-2027-standard'",
           "INSERT INTO course_requisite_documents SELECT * FROM course_requisite_documents "
           "WHERE course_id='c-cs5800'")
    report = audit.build_report(seeded)
    catalog = section(report, "catalog_snapshots")["counts"]
    assert (catalog["usable"], catalog["duplicate_rows"]) == (2, 1)
    plans = section(report, "program_plans")
    assert (plans["counts"]["usable"], plans["counts"]["duplicate_scope_or_id"]) == (2, 2)
    assert plans["programs"]["with_only_partial_plans"] == 0 and plans["programs"]["without_usable_plan"] == 3
    documents = section(report, "requisite_documents")["counts"]
    assert (documents["usable"], documents["duplicate_rows"]) == (2, 2)


def test_duplicate_course_ids_use_no_row(seeded):
    without_keys(seeded, "courses")
    modify(seeded, "INSERT INTO courses SELECT * FROM courses WHERE course_id='c-cs5200'")
    report = audit.build_report(seeded, details=True)
    courses = section(report, "courses")
    assert courses["counts"]["duplicate_id"] == 2 and courses["counts"]["in_scope"] == 7
    assert total(courses["in_scope_courses"]) == 7 == sum(courses["in_scope_courses"]["by_department"].values())
    assert report["details"]["courses"]["duplicate_id"]["by_department"] == {"CS": {"items": ["CS 5200", "CS 5200"],
                                                                                    "omitted": 0}}
    # The course's snapshot and document now belong to a course out of scope; nothing is attached to it.
    assert section(report, "catalog_snapshots")["snapshot_rows"]["rows_for_courses_out_of_scope"] == 2
    assert section(report, "requisite_documents")["counts"]["rows_for_courses_out_of_scope"] == 2
    assert_adds_up(report)


@pytest.mark.parametrize("statement, name, category", [
    ("UPDATE courses SET course_id='c-cs5200-renamed' WHERE course_id='c-cs5200'", "courses", "identity_mismatch"),
    ("UPDATE courses SET primary_code='CS 5201' WHERE course_id='c-cs5200'", "courses", "identity_mismatch"),
    ("UPDATE course_catalog_sources SET snapshot=json_set(snapshot, '$.course_code', 'CS 5201') "
     "WHERE course_id='c-cs5200'", "catalog_snapshots", "identity_mismatch"),
    ("UPDATE course_requisite_documents SET document=json_set(document, '$.course_id', 'c-cs5800') "
     "WHERE course_id='c-cs5200'", "requisite_documents", "row_identity_mismatch"),
    ("UPDATE course_requisite_documents SET document=json_set(document, '$.course_code', 'CS 5201') "
     "WHERE course_id='c-cs5200'", "requisite_documents", "course_identity_mismatch"),
    ("UPDATE program_plans SET plan_id='cs-ms-boston-2026-2027-other' "
     "WHERE plan_id='cs-ms-boston-2026-2027-standard'", "program_plans", "identity_mismatch"),
    ("UPDATE program_plans SET campus='oakland' WHERE plan_id='cs-ms-boston-2026-2027-standard'", "program_plans",
     "identity_mismatch"),
    ("UPDATE program_plans SET pathway='bridge' WHERE plan_id='cs-ms-boston-2026-2027-standard'", "program_plans",
     "identity_mismatch"),
    ("UPDATE program_plans SET concentration='ai' WHERE plan_id='cs-ms-boston-2026-2027-standard'", "program_plans",
     "identity_mismatch"),
    ("UPDATE program_plans SET catalog_year='2025-2026' WHERE plan_id='cs-ms-boston-2026-2027-standard'",
     "program_plans", "identity_mismatch"),
])
def test_each_identity_component_is_compared(seeded, statement, name, category):
    before = section(audit.build_report(seeded), name)["counts"]
    modify(seeded, statement)
    after = section(audit.build_report(seeded), name)["counts"]
    usable = "in_scope" if name == "courses" else "usable"
    assert (after[usable], after[category]) == (before[usable] - 1, before[category] + 1)


@pytest.mark.parametrize("course_id, sources", [("synth-0002", []), ("c-seed", ["synthetic_seed_2"])])
def test_synthetic_records_by_id_or_by_source(seeded, course_id, sources):
    with writing(seeded) as conn:
        CourseRepository(conn).insert(Course(course_id=course_id, primary_code="SYN 2000", primary_name="Synthetic",
                                             source_review_ids=sources), raw_text=SENTINEL)
    counts = section(audit.build_report(seeded), "courses")["counts"]
    assert (counts["synthetic"], counts["in_scope"]) == (2, 8)


def test_unknown_status_values_are_counted_as_other(seeded):
    modify(seeded, "PRAGMA ignore_check_constraints=ON",
           "UPDATE courses SET status='archived' WHERE course_id='c-cs5200'")
    status = section(audit.build_report(seeded), "courses")["status_column"]
    assert status == {"pending": 10, "indexed": 1, "failed": 1, "other": 1}


def test_usable_snapshot_counts_count_snapshots(seeded):
    modify(seeded, "UPDATE course_catalog_sources SET snapshot=json_set(snapshot, '$.prereq_codes', "
                   "json_array('CS 5004', 'CS 5010')) WHERE course_id='c-cs5800'",
           "UPDATE course_catalog_sources SET snapshot=json_set(snapshot, '$.credits', 0) WHERE course_id='c-ds5220a'")
    usable = section(audit.build_report(seeded), "catalog_snapshots")["usable_snapshots"]
    assert (usable["prereq_codes_listed"], usable["credits_missing"]) == (2, 0)  # Snapshots, not codes; 0 is a value.


def test_description_evidence_and_corequisite_statuses(seeded):
    with writing(seeded) as conn:
        for course_id, code, name, paragraphs, corequisite in (
                ("c-cs5800", "CS 5800", "Algorithms", [], None),
                ("c-cs5200", "CS 5200", "Database Management Systems", ["Covers relational design."], None),
                ("c-ds5110", "DS 5110", "Data Management", ["Requires permission of the instructor."],
                 "Junior standing")):
            put_requisite(conn, course_id, "2027-2028", requisite(course_id, code, name, year="2027-2028",
                                                                  description=paragraphs, corequisite=corequisite))
    report = audit.build_report(seeded, details=True)
    edition = section(report, "requisite_documents")["by_catalog_year"]["2027-2028"]
    assert edition["usable"] == 3
    assert edition["description_evidence"] == {"not_listed": 1, "no_keyword_match": 1, "review_needed": 1,
                                               "not_captured": 0}
    assert edition["corequisite"] == {"parsed": 0, "unparsed": 1, "not_listed": 2}
    listed = report["details"]["requisite_documents"]["corequisite_unparsed"]["by_department"]
    assert listed == {"DS": {"items": [{"catalog_year": "2027-2028", "code": "DS 5110"}], "omitted": 0}}


def test_plan_rows_that_cannot_be_used(seeded):
    without_keys(seeded, "program_plans")
    standard = plan("cs-ms-boston-2026-2027-standard", "cs-ms")
    with writing(seeded) as conn:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        put_plan(conn, plan("cs-ms-boston-2026-2027-standard-b", "cs-ms"))  # Same scope, another plan ID.
        put_plan(conn, plan("ds-ms-boston-2026-2027-standard", "ds-ms", pathway="bridge"))  # Same plan ID.
        bridge = plan("info-ms-boston-2026-2027-bridge", "info-ms", pathway="bridge")
        padded = bridge.model_dump_json()[:-1] + " " * 150_000 + "}"  # Over 100,000, within 200,000.
        put_plan(conn, bridge, document=padded)
        put_plan(conn, standard, plan_id="cs-ms-bad-json", document="{not json")
        put_plan(conn, standard, plan_id="cs-ms-bad-record", document=json.dumps({"plan_id": "cs-ms-bad-record"}))
        put_plan(conn, standard, plan_id="cs-ms-oversize", document=" " * 200_001)
    counts = section(audit.build_report(seeded), "program_plans")["counts"]
    # Only info-ms bridge and cs-ms align stay usable; both cs-ms standard and both ds-ms rows are duplicates.
    assert (counts["usable"], counts["duplicate_scope_or_id"]) == (2, 4)
    assert (counts["invalid_json"], counts["invalid_record"], counts["oversize"]) == (1, 1, 1)


# --- details ---------------------------------------------------------------------------------


def listed(details, section_name, key, department):
    return details[section_name][key]["by_department"][department]["items"]


def test_details_are_off_by_default_and_bounded(seeded):
    assert "details" not in audit.build_report(seeded)
    details = audit.build_report(seeded, details=True)["details"]
    assert details["max_codes"] == audit.DEFAULT_MAX_CODES
    assert details["courses"]["invalid_json"] == {"unlisted_malformed": 0,
                                                  "by_department": {"CS": {"items": ["CS 9999"], "omitted": 0}}}
    assert listed(details, "courses", "duplicate_codes", "DS") == [{"code": "DS 5220",
                                                                   "course_ids": ["c-ds5220a", "c-ds5220b"]}]
    assert listed(details, "courses", "identity_mismatch", "CS") == ["CS 9996"]
    assert "SYN 1000" not in json.dumps(details["courses"])  # Synthetic rows are excluded, not gaps.
    assert listed(details, "catalog_snapshots", "identity_mismatch", "AAI") == ["AAI 6600"]
    assert listed(details, "catalog_snapshots", "absent", "DS") == ["DS 5110"]
    assert listed(details, "fields", "credits.catalog_conflict", "CS") == ["CS 5200"]
    # CS 5200's catalog lists a code, but its year document gives the rule, so nothing is left to fill.
    assert "prereqs.catalog_only" not in details["fields"] and "prereqs.year_rules" not in details["fields"]
    assert listed(details, "fields", "field_evidence_value_conflict", "DS") == ["DS 5110"]
    assert listed(details, "fields", "catalog_description.empty_in_usable_snapshot", "CS") == ["CS 5200"]
    item = [{"catalog_year": "2026-2027", "code": "CS 5200"}]
    assert listed(details, "requisite_documents", "prerequisite_unparsed", "CS") == item
    assert listed(details, "requisite_documents", "credit_hours_conflict", "CS") == item
    legacy = details["requisite_documents"]["legacy_prereqs_without_usable_document"]["by_department"]
    # Two in-scope courses share DS 5220, so its items say which record they are about.
    assert legacy == {"CS": {"items": ["CS 6140"], "omitted": 0},
                      "DS": {"items": [{"code": "DS 5220", "course_id": "c-ds5220a"}], "omitted": 0}}
    assert listed(details, "fields", "prereqs.catalog_conflict", "DS") == [{"code": "DS 5220", "course_id": "c-ds5220a"}]
    assert listed(details, "fields", "prereqs.missing", "DS") == ["DS 5110", {"code": "DS 5220", "course_id": "c-ds5220b"}]
    # Every category that asks for work is listed, not only the gaps.
    assert listed(details, "fields", "workload_hours_per_week.extracted_estimate", "DS") == ["DS 5110"]
    assert listed(details, "fields", "professor.course_sources_only", "AAI") == ["AAI 6600"]
    assert listed(details, "fields", "term.no_recorded_source", "CS") == ["CS 6140"]
    assert not any(key.endswith("catalog_consistent") for key in details["fields"])
    plans = details["program_plans"]
    assert plans["programs_without_usable_plan"] == {"items": ["aai-ms", "info-ms"], "omitted": 0,
                                                     "unlisted_malformed": 0}
    assert plans["content_hash_mismatch"]["items"] == ["info-ms-boston-2026-2027-standard"]
    assert plans["identity_mismatch"]["items"] == ["aai-ms-boston-2026-2027-standard"]
    assert plans["orphan_rows"]["items"] == ["gone-ms-boston-2026-2027-standard"]
    scopes = plans["usable_scopes"]["items"]
    assert [item["coverage"] for item in scopes if item["program_id"] == "ds-ms"] == ["partial"]
    bounded = audit.build_report(seeded, details=True, max_codes=1)["details"]
    assert bounded["fields"]["prereqs.missing"]["by_department"] == {
        "DS": {"items": ["DS 5110"], "omitted": 1}, "INFO": {"items": ["INFO 6105"], "omitted": 0}}


def test_every_list_names_the_record_of_a_shared_code(seeded):
    with writing(seeded) as conn:
        for course_id, code, name in (("c-cs5200-copy", "CS 5200", "Database Management Systems"),
                                      ("c-ds5110-copy", "DS 5110", "Data Management")):
            CourseRepository(conn).insert(Course(course_id=course_id, primary_code=code, primary_name=name),
                                          raw_text=SENTINEL)
    details = audit.build_report(seeded, details=True)["details"]
    cs5200, ds5110 = {"code": "CS 5200", "course_id": "c-cs5200"}, {"code": "DS 5110", "course_id": "c-ds5110"}
    assert listed(details, "fields", "catalog_description.empty_in_usable_snapshot", "CS") == [cs5200]
    assert listed(details, "fields", "field_evidence_value_conflict", "DS") == [ds5110]
    for key in ("prerequisite_unparsed", "credit_hours_conflict"):
        assert listed(details, "requisite_documents", key, "CS") == [{**cs5200, "catalog_year": "2026-2027"}]


def test_a_code_shared_only_with_an_excluded_course_is_not_shared(seeded):
    with writing(seeded) as conn:
        CourseRepository(conn).insert(Course(course_id="synth-0002", primary_code="CS 5800", primary_name="Algorithms",
                                             source_review_ids=["synthetic_seed_2"]), raw_text=SENTINEL)
    report = audit.build_report(seeded, details=True)
    assert section(report, "courses")["in_scope_courses"]["duplicate_code_groups"] == 1  # DS 5220 only.
    workload = listed(report["details"], "fields", "workload_hours_per_week.missing", "CS")
    assert workload == ["CS 5200", "CS 5800", "CS 6140"]


def test_the_bound_keeps_the_records_of_a_code_together(tmp_path):
    """Items sort by code: a code two courses share is not pushed behind the plain codes and cut off."""
    path = tmp_path / "shared.sqlite3"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript((ROOT / "db/init.sql").read_text(encoding="utf-8"))
    repo = CourseRepository(conn)
    for course_id, code in (("c-b", "CS 5001"), ("c-a", "CS 5001"), ("c-2", "CS 5002"), ("c-3", "CS 5003"),
                            ("c-4", "CS 5004")):
        repo.insert(Course(course_id=course_id, primary_code=code, primary_name=f"Course {code}"))
    conn.commit()
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    gaps = audit.build_report(path, details=True, max_codes=3)["details"]["fields"]["credits.missing"]
    assert gaps["by_department"]["CS"] == {"items": [
        {"code": "CS 5001", "course_id": "c-a"}, {"code": "CS 5001", "course_id": "c-b"}, "CS 5002"], "omitted": 2}


def test_every_department_is_listed_within_the_bound(tmp_path):
    path = tmp_path / "many.sqlite3"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript((ROOT / "db/init.sql").read_text(encoding="utf-8"))
    repo = CourseRepository(conn)
    departments = [f"D{chr(65 + index // 26)}{chr(65 + index % 26)}" for index in range(30)]
    for department in reversed(departments):
        for number in reversed(range(5)):
            code = f"{department} {5000 + number}"
            repo.insert(Course(course_id=f"c-{department}-{number}", primary_code=code, primary_name=f"Course {code}"))
    conn.commit()
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    gaps = audit.build_report(path, details=True, max_codes=2)["details"]["fields"]["credits.missing"]
    assert list(gaps["by_department"]) == departments  # Sorted, although inserted in reverse.
    assert gaps["by_department"]["DAA"] == {"items": ["DAA 5000", "DAA 5001"], "omitted": 3}
    assert all(item["omitted"] == 3 and len(item["items"]) == 2 for item in gaps["by_department"].values())


def test_malformed_column_values_are_counted_not_listed(seeded):
    with writing(seeded) as conn:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute("UPDATE courses SET primary_code=? WHERE course_id='c-bad-json'", (SENTINEL,))
        conn.execute("UPDATE courses SET primary_code='cs 9998' WHERE course_id='c-invalid'")  # Listed normalized.
        put_requisite(conn, "c-ds5220b", "26-27", "{not json")  # Malformed edition: grouped, never a key.
        put_plan(conn, plan("cs-ms-boston-2026-2027-bridge", "cs-ms", pathway="bridge"), plan_id="Not An ID")
    report = audit.build_report(seeded, details=True)
    details = report["details"]
    assert details["courses"]["invalid_json"] == {"unlisted_malformed": 1, "by_department": {}}
    assert listed(details, "courses", "invalid_record", "CS") == ["CS 9998"]
    editions = section(report, "requisite_documents")["by_catalog_year"]
    assert "26-27" not in editions and editions["unrecognized"]["unusable"] == 1
    assert listed(details, "requisite_documents", "invalid_json", "DS") == [
        {"catalog_year": "2026-2027", "code": "DS 5220", "course_id": "c-ds5220b"},
        {"catalog_year": "unrecognized", "code": "DS 5220", "course_id": "c-ds5220b"}]
    assert details["program_plans"]["identity_mismatch"] == {
        "items": ["aai-ms-boston-2026-2027-standard"], "omitted": 0, "unlisted_malformed": 1}
    assert SENTINEL not in json.dumps(report) and "Not An ID" not in json.dumps(report)


def test_value_conflicts_are_listed_without_the_catalog(seeded):
    modify(seeded, "DROP TABLE course_catalog_sources")
    details = audit.build_report(seeded, details=True)["details"]
    assert listed(details, "fields", "field_evidence_value_conflict", "DS") == ["DS 5110"]


def test_department_blocks_say_nothing_about_an_uncompared_catalog(seeded):
    modify(seeded, "DROP TABLE course_catalog_sources")
    departments = section(audit.build_report(seeded), "fields")["by_department"].values()
    # An empty catalog_description or answer_warnings would read as "none found".
    assert all(set(item) == {"courses_in_scope", "fields"} for item in departments)
    assert not any({"credits", "prereqs"} & set(item["fields"]) for item in departments)


@pytest.mark.parametrize("value", [0, audit.MAX_CODES_LIMIT + 1, "5"])
def test_max_codes_is_bounded(seeded, value):
    with pytest.raises(ValueError):
        audit.build_report(seeded, details=True, max_codes=value)


# --- privacy, read-only, inputs --------------------------------------------------------------


DOCUMENTED_COLUMNS = {
    "schema_versions": {"version"},
    "courses": {"course_id", "primary_code", "primary_name", "status", "generated_json"},
    "course_catalog_sources": {"course_id", "snapshot"},
    "course_requisite_documents": {"course_id", "catalog_year", "document", "content_hash"},
    "programs": {"program_id"},
    "program_plans": {"plan_id", "program_id", "campus", "catalog_year", "pathway", "concentration", "document",
                      "content_hash"},
    "program_required_courses": {"program_id", "course_id"},
    "course_prerequisites": {"course_id", "prereq_course_id"},
}


def test_readable_columns_are_the_documented_ones():
    assert {table: set(columns) for table, columns in audit.READABLE.items()} == DOCUMENTED_COLUMNS
    assert not set(audit.READABLE) & UNREAD_TABLES
    doc = (ROOT / "docs/data-coverage-report.md").read_text(encoding="utf-8")
    part = doc.split("## 读什么、不读什么", 1)[1].split("\n## ", 1)[0]
    table = {match.group(1): set(re.findall(r"`(\w+)`", match.group(2)))
             for match in re.finditer(r"^\| `(\w+)` \| (.+) \|$", part, re.MULTILINE)}
    assert table == DOCUMENTED_COLUMNS


def test_documented_limits_and_fixed_lists():
    assert (audit.MAX_ROWS, audit.MAX_COURSE_JSON, audit.MAX_SNAPSHOT_JSON, audit.MAX_DOCUMENT_JSON) == (
        200_000, 1_000_000, 100_000, 200_000)
    assert (audit.DEADLINE_SECONDS, audit.MAX_VM_STEPS, audit.DEFAULT_MAX_CODES, audit.MAX_CODES_LIMIT) == (
        60, 500_000_000, 25, 500)
    assert audit.MIN_SQLITE_VERSION == (3, 37, 0)
    assert audit.LIMITATIONS == (
        "offline_copy_consistency_is_not_proven",
        "catalog_url_and_hash_checks_are_not_authenticity_or_current_offering",
        "source_checked_means_a_person_compared_the_capture_not_official_or_current",
        "extracted_estimates_are_not_official_facts",
        "course_level_source_ids_do_not_say_which_field_they_support",
        "unknown_retrieval_dates_stay_unknown",
        "legacy_seed_rows_are_not_verified_rules",
        "query_demand_not_read_so_no_enrichment_priority",
    )


def record_reads(monkeypatch):
    calls = []
    original = audit._Reads.__call__

    def recording(self, action, table, column, database, source):
        result = original(self, action, table, column, database, source)
        calls.append((action, table, column, source, result))
        return result

    monkeypatch.setattr(audit._Reads, "__call__", recording)
    return calls


def test_user_tables_and_raw_text_are_never_read(seeded, monkeypatch):
    calls = record_reads(monkeypatch)
    report = audit.build_report(seeded, details=True, max_codes=audit.MAX_CODES_LIMIT)
    assert report["complete"] is True
    assert report["limitations"] == list(audit.LIMITATIONS)
    reads = {(table, column) for action, table, column, _, _ in calls if action == sqlite3.SQLITE_READ}
    assert reads == {(table, column) for table, columns in DOCUMENTED_COLUMNS.items() for column in columns}
    assert not any(table in UNREAD_TABLES for _, table, *_ in calls)
    assert all(result == sqlite3.SQLITE_OK for *_, result in calls)
    assert SENTINEL not in json.dumps(report)


def test_a_denied_read_fails_its_section_with_a_fixed_code(seeded, monkeypatch):
    monkeypatch.setattr(audit._Audit, "legacy_rows", lambda self: {"rows": self.rows("SELECT email FROM users")})
    report = audit.build_report(seeded)
    assert section(report, "legacy_rows") == {"status": "failed", "code": "read_outside_allowlist"}
    assert report["complete"] is False and SENTINEL not in json.dumps(report)


@pytest.mark.parametrize("action, table, column, database, source, allowed", [
    (sqlite3.SQLITE_READ, "courses", "generated_json", "main", None, True),
    (sqlite3.SQLITE_READ, "courses", "raw_text", "main", None, False),
    (sqlite3.SQLITE_READ, "courses", "", None, None, False),
    (sqlite3.SQLITE_READ, "users", "email", "main", None, False),
    (sqlite3.SQLITE_READ, "sqlite_master", "name", "main", None, False),
    (sqlite3.SQLITE_READ, "courses", "generated_json", "main", "some_view", False),
    (sqlite3.SQLITE_READ, "courses", "generated_json", "temp", None, False),
    (sqlite3.SQLITE_SELECT, None, None, None, None, True),
    (sqlite3.SQLITE_TRANSACTION, "BEGIN", None, None, None, True),
    (sqlite3.SQLITE_TRANSACTION, "COMMIT", None, None, None, False),
    (sqlite3.SQLITE_FUNCTION, None, "count", None, None, False),
    (sqlite3.SQLITE_PRAGMA, "table_list", None, None, None, False),
    (sqlite3.SQLITE_INSERT, "courses", None, "main", None, False),
    (sqlite3.SQLITE_ATTACH, "other.db", None, None, None, False),
])
def test_authorizer_allows_only_listed_reads(action, table, column, database, source, allowed):
    reads = audit._Reads()
    result = reads(action, table, column, database, source)
    assert result == (sqlite3.SQLITE_OK if allowed else sqlite3.SQLITE_DENY)
    assert reads.denied == (0 if allowed else 1)


def test_copy_is_not_written_and_leaves_no_sidecars(seeded):
    before = snapshot_dir(seeded.parent)
    assert audit.build_report(seeded)["complete"] is True
    assert snapshot_dir(seeded.parent) == before


def test_wal_flagged_copy_is_read_without_creating_sidecars(tmp_path):
    # A plain mode=ro open of a WAL database creates -wal/-shm next to it; immutable does not.
    path = build_seeded(tmp_path / "wal.sqlite3", journal="WAL")
    assert sorted(item.name for item in tmp_path.iterdir()) == ["wal.sqlite3"]
    with path.open("rb") as stream:
        assert stream.read(20)[18:20] == b"\x02\x02"  # WAL flag in the header.
    before = snapshot_dir(tmp_path)
    assert audit.build_report(path)["complete"] is True
    assert snapshot_dir(tmp_path) == before


def test_connection_is_one_read_only_snapshot(seeded, monkeypatch):
    connect = sqlite3.connect
    statements, opened = [], []

    class Recording(sqlite3.Connection):
        def set_progress_handler(self, handler, n):
            statements.append("<budget handler>")
            return super().set_progress_handler(handler, n)

    def tracked(database, *args, **kwargs):
        conn = connect(database, *args, factory=Recording, **kwargs)
        opened.append((database, kwargs))
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(audit.sqlite3, "connect", tracked)
    calls = record_reads(monkeypatch)
    assert audit.build_report(seeded)["complete"] is True
    assert len(opened) == 1 and opened[0][0].endswith("?mode=ro&immutable=1") and opened[0][1]["uri"] is True
    begin = statements.index("BEGIN")
    # The budget is in place before the integrity check, which reads every page of the file.
    assert statements[:5] == ["PRAGMA query_only=ON", "PRAGMA trusted_schema=OFF", "<budget handler>",
                              "PRAGMA integrity_check(1)", "PRAGMA main.table_list"]
    assert statements[5:begin] == [f"PRAGMA main.table_xinfo({table})" for table in audit.DATA_TABLES]
    assert statements.count("BEGIN") == 1 and all(sql.startswith("SELECT ") for sql in statements[begin + 1:])
    # The authorizer was installed after the PRAGMAs and before BEGIN, so it saw no PRAGMA at all.
    assert calls[0][:2] == (sqlite3.SQLITE_TRANSACTION, "BEGIN")
    assert not any(action == sqlite3.SQLITE_PRAGMA for action, *_ in calls)


def declare(path, table, sql):
    """Store another CREATE statement for a table, its rows untouched, as a hand-edited file might have it."""
    with writing(path) as conn:
        version = conn.execute("PRAGMA schema_version").fetchone()[0]
        conn.execute("PRAGMA writable_schema=ON")
        conn.execute("UPDATE sqlite_schema SET sql=? WHERE type='table' AND name=?", (sql, table))
        conn.execute(f"PRAGMA schema_version={version + 1}")
        conn.execute("PRAGMA writable_schema=OFF")


def test_a_null_in_a_not_null_column_refuses_the_whole_copy(seeded):
    """A known limitation: the integrity check reports such a row, so the copy is refused instead of the row being
    counted. CHECK constraints are not checked: SQLite does not load them for a read-only database, so rows stored
    past them (the fixture's bad JSON) are counted one by one."""
    assert audit.build_report(seeded)["complete"] is True
    conn = sqlite3.connect(seeded)
    (declared,) = conn.execute("SELECT sql FROM sqlite_schema WHERE name='course_catalog_sources'").fetchone()
    conn.close()
    assert declared.count("JSON NOT NULL") == 1
    declare(seeded, "course_catalog_sources", declared.replace("JSON NOT NULL", "JSON"))
    modify(seeded, "INSERT INTO course_catalog_sources(course_id, snapshot) VALUES('c-ds5110', NULL)")
    declare(seeded, "course_catalog_sources", declared)
    assert audit.build_report(seeded)["database"] == {"status": "failed", "code": "database_integrity_failed"}


def test_missing_copy_is_not_created(tmp_path):
    path = tmp_path / "absent.sqlite3"
    report = audit.build_report(path)
    assert report["database"] == {"status": "failed", "code": "database_copy_missing"}
    assert not path.exists() and not list(tmp_path.iterdir())


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_sidecars_refuse_the_copy(seeded, suffix):
    Path(str(seeded) + suffix).write_bytes(b"synthetic sidecar")
    before = snapshot_dir(seeded.parent)
    report = audit.build_report(seeded)
    assert report["database"] == {"status": "failed", "code": "offline_copy_sidecars_present"}
    assert snapshot_dir(seeded.parent) == before


def test_a_dangling_sidecar_link_refuses_the_copy(seeded):
    Path(str(seeded) + "-wal").symlink_to(seeded.parent / "absent-target")
    report = audit.build_report(seeded)
    assert report["database"] == {"status": "failed", "code": "offline_copy_sidecars_present"}


@pytest.mark.parametrize("name, code", [
    ("//private-server/share/copy.sqlite3", "nonlocal_input_path"), (".env", "unsafe_input_path"),
    (".env.local", "unsafe_input_path"), (".envrc", "unsafe_input_path"), (".ENV-copy", "unsafe_input_path"),
    ("directory", "input_kind_mismatch"), ("empty.sqlite3", "input_size_budget")])
def test_unsafe_inputs_are_refused_before_opening(tmp_path, name, code):
    path = Path(name) if name.startswith("//") else tmp_path / name
    if name == "directory":
        path.mkdir()
    elif name == "empty.sqlite3":
        path.write_bytes(b"")
    elif not name.startswith("//"):
        path.write_text(SENTINEL)
    report = audit.build_report(path)
    assert report["database"] == {"status": "failed", "code": code}
    assert SENTINEL not in json.dumps(report) and "private-server" not in json.dumps(report)


def test_an_unreadable_copy_has_a_fixed_code(seeded, monkeypatch):
    def unreadable(self, path, budget):
        raise PermissionError(SENTINEL)

    monkeypatch.setattr(audit.Inputs, "track", unreadable)
    report = audit.build_report(seeded)
    assert report["database"] == {"status": "failed", "code": "database_copy_unreadable"}
    assert SENTINEL not in json.dumps(report)


def test_a_failed_open_has_a_fixed_code(seeded, monkeypatch):
    def refused(*args, **kwargs):
        raise sqlite3.OperationalError(SENTINEL)

    monkeypatch.setattr(audit.sqlite3, "connect", refused)
    report = audit.build_report(seeded)
    assert report["database"] == {"status": "failed", "code": "database_open_failed"}
    assert SENTINEL not in json.dumps(report)


def test_sqlite_without_table_list_is_refused(seeded, monkeypatch):
    monkeypatch.setattr(audit.sqlite3, "sqlite_version_info", (3, 36, 0))
    assert audit.build_report(seeded)["database"] == {"status": "failed", "code": "sqlite_version_unsupported"}


def test_not_a_database_reports_no_contents(tmp_path):
    path = tmp_path / f"{SENTINEL}.sqlite3"
    path.write_bytes(f"{SENTINEL} not a SQLite file".encode())
    report = audit.build_report(path)
    assert report["database"] == {"status": "failed", "code": "database_error"}
    assert all(item["status"] == "not_checked" for item in report["sections"].values())
    assert SENTINEL not in json.dumps(report)


@pytest.mark.parametrize("change", ["bytes", "sidecar"])
def test_a_copy_changed_during_the_audit_reports_no_sections(seeded, monkeypatch, change):
    original = audit._Audit.legacy_rows

    def changing(self):
        result = original(self)
        if change == "bytes":
            with seeded.open("ab") as stream:
                stream.write(b"\0")
        else:
            Path(str(seeded) + "-wal").write_bytes(b"")  # Another process opened it in WAL mode.
        return result

    monkeypatch.setattr(audit._Audit, "legacy_rows", changing)
    report = audit.build_report(seeded)
    assert report["database"] == {"status": "failed", "code": "inputs_changed_during_check"}
    assert report["complete"] is False
    assert all(item == {"status": "not_checked", "code": "database_unavailable"}
               for item in report["sections"].values())


# --- command line ----------------------------------------------------------------------------


def run_cli(*args, cwd):
    return subprocess.run([sys.executable, "-B", str(SCRIPT), *args], cwd=cwd, text=True, capture_output=True,
                          timeout=120)


def test_cli_exit_codes(seeded, tmp_path):
    complete = run_cli("--db-copy", str(seeded), cwd=tmp_path)
    assert complete.returncode == 0 and complete.stderr == ""
    assert json.loads(complete.stdout)["complete"] is True
    modify(seeded, "DROP TABLE programs")  # Only a part of program_plans and legacy_rows depends on it.
    partial = run_cli("--db-copy", str(seeded), "--details", cwd=tmp_path)
    assert partial.returncode == 2 and json.loads(partial.stdout)["complete"] is False
    missing = run_cli("--db-copy", str(tmp_path / f"{SENTINEL}.sqlite3"), cwd=tmp_path)
    assert missing.returncode == 1 and json.loads(missing.stdout)["database"]["code"] == "database_copy_missing"
    assert SENTINEL not in missing.stdout + missing.stderr
    bad = run_cli("--db-copy", str(seeded), "--max-codes", SENTINEL, cwd=tmp_path)
    assert bad.returncode == 1 and json.loads(bad.stdout)["code"] == "invalid_arguments"
    assert SENTINEL not in bad.stdout + bad.stderr
    for value in ("0", str(audit.MAX_CODES_LIMIT + 1)):
        over = run_cli("--db-copy", str(seeded), "--details", "--max-codes", value, cwd=tmp_path)
        assert over.returncode == 1 and json.loads(over.stdout)["code"] == "invalid_arguments"
    largest = run_cli("--db-copy", str(seeded), "--details", "--max-codes", str(audit.MAX_CODES_LIMIT), cwd=tmp_path)
    # Accepted (exit 2 only because programs was dropped above).
    assert largest.returncode == 2 and json.loads(largest.stdout)["details"]["max_codes"] == audit.MAX_CODES_LIMIT


def test_cli_reports_a_crash_with_a_fixed_code(seeded, monkeypatch, capsys):
    def crash(*args, **kwargs):
        raise RuntimeError(SENTINEL)

    monkeypatch.setattr(audit, "build_report", crash)
    assert audit.cli(["--db-copy", str(seeded)]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == {"format_version": 1, "report": "data_coverage", "complete": False,
                                      "code": "audit_failed"}
    assert SENTINEL not in output.out + output.err


GUARD = '''
import importlib.abc, os, pathlib, re, sys
EXPECTED = sys.argv[1]
WRITES = {"os.mkdir", "os.rename", "os.remove", "os.rmdir", "os.symlink", "os.link", "os.truncate", "os.chmod",
          "os.chown", "os.utime", "os.chflags", "os.lchflags", "os.lchmod", "os.mkfifo", "os.mknod", "os.setxattr",
          "os.removexattr", "shutil.copyfile", "shutil.copymode", "shutil.copystat", "shutil.copytree", "shutil.move",
          "shutil.rmtree", "shutil.chown", "shutil.make_archive", "shutil.unpack_archive", "tempfile.mkstemp",
          "tempfile.mkdtemp"}
SPAWNS = {"subprocess.Popen", "os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.fork", "os.forkpty",
          "os.startfile", "pty.spawn", "sqlite3.enable_load_extension", "sqlite3.load_extension"}
NETWORK = ("socket.", "urllib.", "http.client.", "ftplib.", "smtplib.", "imaplib.", "poplib.", "nntplib.",
           "telnetlib.", "webbrowser.")


def blocked(reason):
    os.write(2, ("blocked: " + reason + "\\n").encode())  # Seen even when the code swallows the error.
    raise RuntimeError(reason)


class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"config", "api", "app", "dotenv"}:
            blocked("config_import")


sys.meta_path.insert(0, Block())


def traced(statement):
    # SQLite opens or writes files for these without a Python open() call.
    if re.search(r"\\b(ATTACH|DETACH|VACUUM)\\b", statement, re.IGNORECASE):
        os.write(2, b"blocked: attach_or_vacuum\\n")


def audit(event, args):
    if event in WRITES or event in SPAWNS or event.startswith(NETWORK):
        blocked(event)
    if event == "sqlite3.connect" and args[0] != EXPECTED:
        blocked("another_database")
    if event == "open":
        path, mode, flags = args
        if isinstance(path, (str, bytes)) and pathlib.Path(os.fsdecode(path)).name.lower().startswith(".env"):
            blocked("env_read")
        if (mode and any(c in mode for c in "wax+")) or (flags or 0) & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            blocked("disk_write")


import sqlite3
connect = sqlite3.connect


def traced_connect(*args, **kwargs):
    # Every connection traces its statements, so an ATTACH is seen whoever runs it.
    connection = connect(*args, **kwargs)
    connection.set_trace_callback(traced)
    return connection


sqlite3.connect = traced_connect
sys.addaudithook(audit)
sys.path.insert(0, sys.argv[2])
import scripts.audit_data_coverage as module
FAULT = os.environ.get("AUDIT_GUARD_FAULT", "")


def raising(error):
    def broken(*args, **kwargs):
        raise error
    return broken


# Each fault sends the run down one failure branch, so the guard watches that branch as well.
if FAULT == "section_error":
    module.field_category = raising(ValueError("injected"))  # The fields section's unexpected-error branch.
elif FAULT == "section_sqlite_error":
    module._Audit.fields = raising(sqlite3.OperationalError("injected"))
elif FAULT == "row_budget":
    module.MAX_ROWS = 1
elif FAULT == "budget_at_open":
    module.MAX_VM_STEPS, module.PROGRESS_INTERVAL = 0, 1  # The integrity check runs out of steps.
elif FAULT == "changed":
    module.Inputs.unchanged = raising(module.PreflightError("inputs_changed"))
elif FAULT == "crash":
    module.build_report = raising(ValueError("injected"))
raise SystemExit(module.cli(sys.argv[3:]))
'''


@pytest.mark.parametrize("scenario, arguments, exit_code, expected", [
    ("checked", ["--details"], 0, None),
    ("table_missing", ["--details"], 2, None),  # The not_checked branches of require() and of unavailable().
    ("section_error", ["--details"], 2, ("fields", "section_failed")),
    ("section_sqlite_error", ["--details"], 2, ("fields", "database_error")),
    ("row_budget", ["--details"], 2, ("courses", "row_budget")),
    ("integrity_failed", ["--details"], 1, "database_integrity_failed"),
    ("not_a_database", [], 1, "database_error"),
    ("budget_at_open", [], 1, "sqlite_budget"),
    ("changed", ["--details"], 1, "inputs_changed_during_check"),
    ("sidecar", [], 1, "offline_copy_sidecars_present"),
    ("copy_missing", [], 1, "database_copy_missing"),
    ("crash", [], 1, "audit_failed"),
    ("bad_arguments", ["--max-codes", "0"], 1, "invalid_arguments")])
def test_fresh_process_has_no_config_env_network_subprocess_or_writes(seeded, tmp_path, scenario, arguments,
                                                                     exit_code, expected):
    """Every branch, the refusals and failures too, runs without config, .env, network, subprocesses or writes."""
    copy = seeded
    if scenario == "table_missing":
        modify(seeded, "DROP TABLE programs")
    elif scenario == "integrity_failed":
        copy = aliased_copy(tmp_path / "aliased.sqlite3", ["104729000000000000001"])
    elif scenario == "not_a_database":
        seeded.write_bytes(b"not a database " * 300)
    elif scenario == "sidecar":
        Path(f"{seeded}-journal").write_bytes(b"synthetic sidecar")
    elif scenario == "copy_missing":
        copy = tmp_path / "absent.sqlite3"
    uri = copy.resolve().as_uri() + "?mode=ro&immutable=1"
    before = snapshot_dir(tmp_path)
    environment = {**os.environ, "AUDIT_GUARD_FAULT": scenario}
    run = subprocess.run([sys.executable, "-B", "-c", GUARD, uri, str(ROOT), "--db-copy", str(copy), *arguments],
                         cwd=tmp_path, text=True, capture_output=True, timeout=120, env=environment)
    assert run.returncode == exit_code, run.stderr[-2000:]
    assert run.stderr == ""  # A blocked action writes here even when the code catches the error.
    report = json.loads(run.stdout)
    assert SENTINEL not in run.stdout and snapshot_dir(tmp_path) == before
    if scenario == "checked":
        assert report["complete"] is True
    elif isinstance(expected, tuple):
        name, code = expected
        assert report["sections"][name] == {"status": "failed", "code": code}
    elif expected is not None:
        assert (report["database"]["code"] if "database" in report else report["code"]) == expected


def test_the_guard_sees_actions_the_code_swallows(seeded, tmp_path):
    """The guard itself: an attached database and a swallowed write both leave a mark on stderr."""
    expected = seeded.resolve().as_uri() + "?mode=ro&immutable=1"
    probe = GUARD.replace("raise SystemExit(module.cli(sys.argv[3:]))", (
        "import sqlite3\n"
        "connection = sqlite3.connect(EXPECTED, uri=True)\n"
        "connection.execute(\"ATTACH DATABASE ':memory:' AS other\")\n"
        "try:\n"
        "    open('written.tmp', 'w')\n"
        "except RuntimeError:\n"
        "    pass\n"))
    run = subprocess.run([sys.executable, "-B", "-c", probe, expected, str(ROOT)], cwd=tmp_path, text=True,
                         capture_output=True, timeout=120)
    assert "blocked: attach_or_vacuum" in run.stderr and "blocked: disk_write" in run.stderr
    assert not (tmp_path / "written.tmp").exists()
