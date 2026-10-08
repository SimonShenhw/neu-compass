"""OPT-03 data coverage report on synthetic offline copies: counts, rules and denominators, never
user tables, never writes.

中文：只用合成的离线副本：计数、规则与分母；不读用户表，不写入。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
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
from rag.answer_evidence import AVAILABILITY_FIELDS, course_answer_evidence
from schemas.answer_evidence import CatalogSnapshot
from schemas.catalog_credit_hours import CatalogCreditHours
from schemas.course import Course, EvidenceSnippet
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


def catalog_url(code):
    return f"https://catalog.northeastern.edu/course-descriptions/{code.split()[0].lower()}/"


def snapshot(code, name, *, credits=None, prereqs=(), description="Catalog description", retrieved_at=None):
    return CatalogSnapshot(course_code=code, course_name=name, description=description, credits=credits,
                           prereq_codes=list(prereqs), catalog_url=catalog_url(code), snapshot_id="catalog:test",
                           imported_at=datetime(2026, 10, 7, 12, tzinfo=UTC), retrieved_at=retrieved_at)


def requisite(course_id, code, name, *, year="2026-2027", prerequisite=None, hours=None):
    department = code.split()[0]
    source = CourseRequisiteSource(url=catalog_url(code), catalog_year=year, sha256="a" * 64, byte_count=10,
                                   captured_at=datetime(2026, 10, 1, 9, tzinfo=UTC), page_title=f"Test ({department})")
    return CourseRequisiteDocument(
        course_id=course_id, course_code=code, course_name=name, catalog_year=year, source=source,
        requisites={"prerequisite": parse_clause(prerequisite), "corequisite": parse_clause(None)},
        credit_hours=CatalogCreditHours.from_text(hours) if hours else None)


def plan(plan_id, program_id, *, pathway="standard", coverage="partial", review_status="draft",
         fingerprint=None, unmodeled=True):
    children = [{"kind": "course", "label": "CS 5800", "course_code": "CS 5800"},
                {"kind": "course", "label": "CS 5004", "course_code": "CS 5004"}]
    if unmodeled:
        children.append({"kind": "unmodeled", "label": "Electives not modeled"})
    data = dict(plan_id=plan_id, program_id=program_id, campus="boston", catalog_year="2026-2027", pathway=pathway,
                coverage=coverage, review_status=review_status, source_html_sha256=fingerprint,
                source_url="https://catalog.northeastern.edu/graduate/computer-information-science/test/",
                source_title="Test program", source_catalog_year="2026-2027", source_excerpt=f"Excerpt {SENTINEL}",
                captured_on="2026-10-01", notes=f"Notes {SENTINEL}",
                requirements={"kind": "all_of", "label": "Core", "children": children})
    if review_status == "source_checked":
        data.update(checked_by=f"reviewer {SENTINEL}", checked_on="2026-10-02")
    return ProgramPlan.model_validate(data)


def raw_course(conn, course_id, code, name, generated_json, status="pending"):
    conn.execute("INSERT INTO courses(course_id, primary_code, primary_name, metadata, raw_text, generated_json, status) "
                 "VALUES(?,?,?,?,?,?,?)", (course_id, code, name, "{}", SENTINEL, generated_json, status))


def put_snapshot(conn, course_id, text):
    conn.execute("INSERT INTO course_catalog_sources(course_id, snapshot) VALUES(?,?)", (course_id, text))


def put_requisite(conn, course_id, year, document, digest=None):
    text = document if isinstance(document, str) else document.model_dump_json()
    digest = digest or (requisite_hash(document) if not isinstance(document, str) else "0" * 64)
    conn.execute("INSERT INTO course_requisite_documents(course_id, catalog_year, document, content_hash) VALUES(?,?,?,?)",
                 (course_id, year, text, digest))


def put_plan(conn, item, *, digest=None, program_id=None):
    conn.execute("INSERT INTO program_plans(plan_id, program_id, campus, catalog_year, pathway, concentration, document, "
                 "content_hash) VALUES(?,?,?,?,?,?,?,?)",
                 (item.plan_id, program_id or item.program_id, item.campus, item.catalog_year, item.pathway,
                  item.concentration or "", item.model_dump_json(), digest or plan_hash(item)))


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
               evidence_snippets=[EvidenceSnippet(field="workload_hours_per_week", value=6.0, source_id="syllabus_ds5110",
                                                  quote=quote, confidence=0.8),
                                  EvidenceSnippet(field="difficulty_score", value=4.0, source_id="rmp_review_1",
                                                  quote=quote, confidence=0.5)]),
        Course(course_id="c-aai6600", primary_code="AAI 6600", primary_name="Applied Artificial Intelligence",
               professor=["Dr. Example"], source_review_ids=["rmp_review_2"]),
        Course(course_id="c-ds5220a", primary_code="DS 5220", primary_name="Supervised Machine Learning", credits=4,
               prereqs=["DS 5110"]),
        Course(course_id="c-ds5220b", primary_code="DS 5220", primary_name="Supervised Machine Learning", credits=3),
        Course(course_id="c-info6105", primary_code="INFO 6105", primary_name="Data Science Engineering Methods"),
        Course(course_id="synth-0001", primary_code="SYN 1000", primary_name="Synthetic", source_review_ids=["synthetic_seed_1"]),
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
                                            description="", retrieved_at=datetime(2026, 9, 30, 15, tzinfo=UTC)).model_dump_json())
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
    put_plan(conn, plan("ds-ms-boston-2026-2027-standard", "ds-ms", review_status="source_checked", fingerprint="d" * 64))
    put_plan(conn, plan("info-ms-boston-2026-2027-standard", "info-ms"), digest="e" * 64)
    put_plan(conn, plan("gone-ms-boston-2026-2027-standard", "gone-ms"))
    put_plan(conn, plan("aai-ms-boston-2026-2027-standard", "cs-ms"), program_id="aai-ms")  # Rebound to another scope.

    for program, course_id in (("cs-ms", "c-cs5800"), ("ds-ms", "c-ds5110"), ("aai-ms", "c-aai6600"), ("cs-ms", "synth-0001"),
                               ("gone-ms", "c-cs5200")):
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


def section(report, name):
    return report["sections"][name]


def snapshot_dir(directory):
    return {item.name: hashlib.sha256(item.read_bytes()).hexdigest() for item in directory.iterdir()}


# --- counts, denominators, rules ---------------------------------------------------------------


def test_course_rows_split_into_exclusive_categories(seeded):
    report = audit.build_report(seeded)
    assert report["database"] == {"status": "checked", "code": "read_only_snapshot"}
    courses = section(report, "courses")
    assert courses["denominator"] == {"course_rows": 13}
    assert courses["counts"] == {"in_scope": 8, "synthetic": 1, "identity_mismatch": 1, "invalid_record": 1,
                                 "invalid_json": 1, "oversize": 1}
    assert courses["in_scope"] == {"denominator": 8, "duplicate_code_groups": 1, "duplicate_code_rows": 2,
                                   "by_department": {"AAI": 1, "CS": 3, "DS": 3, "INFO": 1}}
    assert courses["status_column"] == {"pending": 11, "indexed": 1, "failed": 1, "other": 0}


def test_catalog_snapshots_per_course_and_per_row(seeded):
    catalog = section(audit.build_report(seeded), "catalog_snapshots")
    assert catalog["denominator"] == {"courses_in_scope": 8}
    assert catalog["counts"] == {"usable": 3, "absent": 1, "duplicate_rows": 0, "identity_mismatch": 1,
                                 "invalid_record": 1, "invalid_json": 1, "oversize": 1}
    assert catalog["snapshot_rows"] == {"denominator": 9, "orphan_rows": 1, "rows_for_courses_out_of_scope": 1}
    assert catalog["usable"] == {"denominator": 3, "retrieval_date_unknown": 2, "retrieval_date_known": 1,
                                 "retrieved_on": {"earliest": "2026-09-30", "latest": "2026-09-30"},
                                 "description_missing": 1, "credits_missing": 0, "prereq_codes_listed": 2}
    assert catalog["by_department"]["CS"] == {"courses_in_scope": 3, "usable": 2, "invalid_json": 1}
    assert catalog["by_department"]["DS"] == {"courses_in_scope": 3, "usable": 1, "absent": 1, "invalid_record": 1}


def test_field_categories_cover_every_in_scope_course(seeded):
    fields = section(audit.build_report(seeded), "fields")
    assert fields["denominator"] == {"courses_in_scope": 8}
    table = fields["fields"]
    assert set(table) == set(AVAILABILITY_FIELDS)
    for counts in table.values():
        assert list(counts) == list(audit.FIELD_CATEGORIES) and sum(counts.values()) == 8
    assert table["credits"] == {"missing": 3, "catalog_only": 0, "catalog_conflict": 1, "catalog_consistent": 2,
                                "extracted_estimate": 0, "course_sources_only": 1, "no_recorded_source": 1}
    assert table["prereqs"] == {"missing": 4, "catalog_only": 1, "catalog_conflict": 1, "catalog_consistent": 1,
                                "extracted_estimate": 0, "course_sources_only": 0, "no_recorded_source": 1}
    assert table["workload_hours_per_week"]["extracted_estimate"] == 1
    assert table["difficulty_score"]["extracted_estimate"] == 1
    assert table["topics_covered"]["course_sources_only"] == 1
    assert table["professor"]["course_sources_only"] == 1
    assert table["term"]["no_recorded_source"] == 1
    assert table["skill_tags"]["missing"] == 8
    assert fields["catalog_comparison"] == {"status": "checked"}
    assert fields["catalog_description"] == {"present_in_usable_snapshot": 2, "missing": 6}
    warnings = fields["answer_warnings"]
    assert warnings["catalog_metadata_conflict"] == 1 and warnings["field_evidence_value_conflict"] == 1
    assert warnings["catalog_retrieval_date_unknown"] == 2 and warnings["catalog_source_unavailable"] == 5
    assert "synthetic_record_not_real_course" not in warnings
    assert fields["by_department"]["CS"]["courses_in_scope"] == 3
    assert fields["by_department"]["CS"]["credits"] == {"catalog_conflict": 1, "catalog_consistent": 1, "missing": 1}


def test_requisite_documents_by_edition(seeded):
    requisites = section(audit.build_report(seeded), "requisite_documents")
    assert requisites["denominator"] == {"document_rows": 11}
    assert requisites["counts"] == {
        "usable": 3, "orphan_rows": 1, "rows_for_courses_out_of_scope": 1, "duplicate_rows": 0, "oversize": 1,
        "invalid_json": 1, "invalid_record": 1, "row_identity_mismatch": 1, "course_identity_mismatch": 1,
        "content_hash_mismatch": 1}
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
    assert requisites["courses_in_scope"] == {"denominator": 8, "with_usable_document_any_year": 3,
                                              "legacy_prereqs_without_usable_document": 2}
    assert requisites["by_department"]["CS"] == {"courses_in_scope": 3, "with_usable_document": {"2026-2027": 2}}
    assert requisites["by_department"]["AAI"] == {"courses_in_scope": 1, "with_usable_document": {"2025-2026": 1}}


def test_partial_plans_are_never_counted_complete(seeded):
    plans = section(audit.build_report(seeded), "program_plans")
    assert plans["denominator"] == {"plan_rows": 6}
    assert plans["counts"] == {"usable": 3, "orphan_rows": 1, "oversize": 0, "invalid_json": 0, "invalid_record": 0,
                               "identity_mismatch": 1, "content_hash_mismatch": 1, "duplicate_scope_or_id": 0}
    assert plans["usable"]["coverage"] == {"partial": 2, "complete": 1}
    assert plans["usable"]["review_status"] == {"draft": 1, "source_checked": 2}
    assert plans["usable"]["source_fingerprint"] == {"recorded": 1, "missing": 2}
    assert plans["by_program"] == {
        "cs-ms": {"2026-2027": {"usable": 2, "partial": 1, "complete": 1, "draft": 1, "source_checked": 1}},
        "ds-ms": {"2026-2027": {"usable": 1, "partial": 1, "complete": 0, "draft": 0, "source_checked": 1}}}
    # A source_checked partial plan (ds-ms) is still partial; only cs-ms has a complete scope.
    assert plans["programs"] == {"status": "checked", "denominator": {"program_rows": 4}, "with_complete_plan": 1,
                                 "with_only_partial_plans": 1, "without_usable_plan": 2}


def test_legacy_rows_are_counted_only(seeded):
    legacy = section(audit.build_report(seeded), "legacy_rows")
    assert legacy["program_required_courses"] == {"status": "checked", "rows": 5, "rows_for_courses_out_of_scope": 1,
                                                  "by_program": {"aai-ms": 1, "cs-ms": 2, "ds-ms": 1},
                                                  "rows_for_unknown_programs": 1}
    assert legacy["course_prerequisites"] == {"status": "checked", "rows": 2, "rows_for_courses_out_of_scope": 0,
                                              "courses_in_scope_with_edges": 2}


def test_non_text_program_ids_are_counted_not_named(seeded):
    # A BLOB keeps its type in a TEXT column (an integer would be stored as text).
    modify(seeded, "INSERT INTO programs(program_id, full_name, prefix) VALUES(x'37', 'Numeric', 'NUM')",
           "INSERT INTO program_required_courses(program_id, course_id, requirement_type) VALUES(x'37', 'c-cs5800', 'core')")
    report = audit.build_report(seeded, details=True)
    legacy = section(report, "legacy_rows")["program_required_courses"]
    assert legacy["by_program"] == {"aai-ms": 1, "cs-ms": 2, "ds-ms": 1} and legacy["rows_for_unknown_programs"] == 2
    plans = section(report, "program_plans")
    assert plans["programs"]["without_usable_plan"] == 3
    assert report["details"]["program_plans"]["programs_without_usable_plan"]["unlisted_malformed"] == 1
    json.dumps(report, sort_keys=True)  # Every key of the report is text.


def test_every_counted_category_has_a_rule(seeded):
    report = audit.build_report(seeded)
    assert report["complete"] is True
    for name in ("courses", "catalog_snapshots", "requisite_documents", "program_plans"):
        item = section(report, name)
        assert set(item["counts"]) <= set(item["rules"]), name
        denominator = next(iter(item["denominator"].values()))
        assert sum(item["counts"].values()) == denominator, name
    assert set(section(report, "fields")["rules"]) == set(audit.FIELD_CATEGORIES)


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


def test_missing_tables_are_not_checked_not_zero(seeded):
    modify(seeded, "DROP TABLE course_catalog_sources", "DROP TABLE course_requisite_documents",
           "DROP TABLE program_plans", "DROP TABLE course_prerequisites", "DELETE FROM schema_versions WHERE version='1.6'")
    report = audit.build_report(seeded)
    assert report["complete"] is False
    for name in ("catalog_snapshots", "requisite_documents", "program_plans"):
        assert section(report, name) == {"status": "not_checked", "code": "table_missing"}
    fields = section(report, "fields")
    assert fields["status"] == "checked"
    for key in ("catalog_comparison", "catalog_description", "answer_warnings"):
        assert fields[key] == {"status": "not_checked", "code": "catalog_snapshots_not_checked"}
    assert fields["fields"]["credits"]["catalog_consistent"] == 0  # Not compared, and the report says so.
    assert section(report, "legacy_rows")["course_prerequisites"] == {"status": "not_checked", "code": "table_missing"}
    schema = section(report, "schema")
    assert schema["tables"]["course_catalog_sources"] is False and schema["tables"]["courses"] is True
    assert schema["schema_versions"]["missing"] == ["1.6"]


def test_a_view_named_like_a_data_table_is_neither_trusted_nor_read(seeded, monkeypatch):
    modify(seeded, "DROP TABLE course_prerequisites",
           "CREATE VIEW course_prerequisites AS SELECT user_id AS course_id, email AS prereq_course_id FROM users")
    calls = record_reads(monkeypatch)
    report = audit.build_report(seeded)
    assert section(report, "legacy_rows")["course_prerequisites"] == {"status": "not_checked", "code": "table_missing"}
    assert not any(table in UNREAD_TABLES or table == "course_prerequisites" for _, table, *_ in calls)
    assert SENTINEL not in json.dumps(report)


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


def test_row_budget_fails_instead_of_truncating(seeded, monkeypatch):
    monkeypatch.setattr(audit, "MAX_ROWS", 1)
    conn = sqlite3.connect(seeded)
    conn.row_factory = sqlite3.Row
    try:
        with pytest.raises(audit._Failed, match="row_budget"):
            audit._Audit(conn, audit._Reads(), False).rows("SELECT course_id FROM courses")
    finally:
        conn.close()


@pytest.mark.parametrize("limit, value", [("MAX_VM_STEPS", 0), ("DEADLINE_SECONDS", -1)])
def test_sqlite_budget_is_a_fixed_failure(seeded, monkeypatch, limit, value):
    monkeypatch.setattr(audit, "PROGRESS_INTERVAL", 1)
    monkeypatch.setattr(audit, limit, value)
    report = audit.build_report(seeded)
    assert report["database"] == {"status": "failed", "code": "sqlite_budget"}
    assert all(item["code"] == "database_unavailable" for item in report["sections"].values())


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


def test_decode_budget_boundary_and_non_text():
    text = json.dumps({"pad": "a" * 20})
    assert audit._decode(text, len(text), CatalogSnapshot) == ("invalid_record", None)
    assert audit._decode(text, len(text) - 1, CatalogSnapshot) == ("oversize", None)
    for value in (None, b"{}", 3):
        assert audit._decode(value, 100, CatalogSnapshot) == ("invalid_json", None)
    deep = "[" * 200_000 + "]" * 200_000  # Valid JSON, nested deeper than the parser allows.
    with pytest.raises(RecursionError):
        json.loads(deep)
    assert audit._decode(deep, len(deep), CatalogSnapshot) == ("invalid_json", None)
    good = snapshot("CS 5800", "Algorithms").model_dump_json()
    category, value = audit._decode(good, len(good), CatalogSnapshot)
    assert category == "decoded" and value.course_code == "CS 5800"


@pytest.mark.parametrize("hours, credits, expected", [
    (None, 4, "not_captured"), ("1-4 Hours", 4, "range_not_compared"), ("1.5 Hours", 1, "fractional_not_compared"),
    ("4 Hours", None, "course_credits_missing"), ("4 Hours", 4, "consistent"), ("3 Hours", 4, "conflict"),
    ("0 Hours", 0, "consistent")])
def test_credit_hours_comparison(hours, credits, expected):
    value = CatalogCreditHours.from_text(hours) if hours else None
    assert audit.credit_comparison(value, credits) == expected


# --- consistency with the code paths the app uses ---------------------------------------------


def in_scope_courses(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    ids = ["c-cs5800", "c-cs5200", "c-cs6140", "c-ds5110", "c-aai6600", "c-ds5220a", "c-ds5220b", "c-info6105"]
    return conn, CourseRepository(conn).get_batch(ids)


def test_usable_rows_are_the_ones_the_repositories_serve(seeded):
    report = audit.build_report(seeded)
    conn, courses = in_scope_courses(seeded)
    try:
        attached = CatalogSourceRepository(conn).get_batch(list(courses.values()))
        assert len(attached) == section(report, "catalog_snapshots")["counts"]["usable"]
        served = sum(len(CourseRequisiteRepository(conn).list_for_course(course_id).documents) for course_id in courses)
        assert served == section(report, "requisite_documents")["counts"]["usable"]
        plans = sum(len(ProgramPlanRepository(conn).list_for_program(program))
                    for program in ("cs-ms", "ds-ms", "info-ms", "aai-ms"))
        assert plans == section(report, "program_plans")["counts"]["usable"]
    finally:
        conn.close()


def test_missing_categories_agree_with_answer_evidence(seeded):
    conn, courses = in_scope_courses(seeded)
    try:
        attached = CatalogSourceRepository(conn).get_batch(list(courses.values()))
    finally:
        conn.close()
    for course_id, course in courses.items():
        snapshot_ = attached.get(course_id)
        evidence = course_answer_evidence(course, snapshot_)
        gaps = {field for field in AVAILABILITY_FIELDS
                if audit.field_category(course, field, snapshot_) in ("missing", "catalog_only")}
        assert gaps == set(evidence.missing_fields) - {"catalog_description"}, course_id
        conflict = audit.field_category(course, "credits", snapshot_) == "catalog_conflict"
        assert conflict == ("catalog_metadata_conflict" in evidence.warnings), course_id


@pytest.mark.parametrize("stored, listed, expected", [
    ([], [], "missing"), ([], ["CS 5800"], "catalog_only"), (["CS 5800"], [], "catalog_conflict"),
    (["cs  5800"], ["CS 5800"], "catalog_consistent"), (["CS 5800", "CS 5004"], ["CS 5004", "CS 5800"], "catalog_consistent"),
    (["CS 5800"], ["CS 5800", "CS 5004"], "catalog_conflict")])
def test_prerequisite_code_sets(stored, listed, expected):
    course = Course(course_id="c", primary_code="CS 6140", primary_name="Machine Learning", prereqs=stored)
    assert audit.field_category(course, "prereqs", snapshot("CS 6140", "Machine Learning", prereqs=listed)) == expected


def test_zero_credits_is_a_value_and_no_snapshot_means_no_comparison():
    course = Course(course_id="c", primary_code="CS 6140", primary_name="Machine Learning", credits=0)
    assert audit.field_category(course, "credits", None) == "no_recorded_source"
    assert audit.field_category(course, "credits", snapshot("CS 6140", "Machine Learning", credits=0)) == "catalog_consistent"
    assert audit.field_category(course, "credits", snapshot("CS 6140", "Machine Learning")) == "no_recorded_source"
    unset = Course(course_id="c", primary_code="CS 6140", primary_name="Machine Learning")
    assert audit.field_category(unset, "credits", snapshot("CS 6140", "Machine Learning", credits=4)) == "catalog_only"


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
        for entry in _parse_dept_html(html, source_url=f"https://catalog.northeastern.edu/course-descriptions/{department}/"):
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
    assert snapshots["usable"]["retrieval_date_unknown"] == len(entries)  # The catalog scraper records no fetch time.
    fields = section(report, "fields")["fields"]
    assert fields["credits"]["catalog_conflict"] == fields["prereqs"]["catalog_conflict"] == 0
    assert fields["credits"]["catalog_consistent"] == sum(entry.credits is not None for entry in entries.values())
    assert fields["prereqs"]["catalog_consistent"] == sum(bool(entry.prereqs) for entry in entries.values())


def test_unknown_retrieval_date_is_not_replaced_by_import_time(seeded):
    modify(seeded, "DELETE FROM course_catalog_sources WHERE course_id='c-cs5200'")
    report = audit.build_report(seeded)
    usable = section(report, "catalog_snapshots")["usable"]
    assert usable["retrieval_date_unknown"] == usable["denominator"] == 2
    assert usable["retrieval_date_known"] == 0
    assert usable["retrieved_on"] == {"earliest": None, "latest": None}
    assert "2026-10-07" not in json.dumps(report)  # The snapshots' import date is never reported as a date.


def test_duplicate_rows_choose_no_winner(seeded):
    modify(seeded,
           "CREATE TABLE loose_sources(course_id TEXT, snapshot TEXT)",
           "INSERT INTO loose_sources SELECT course_id, snapshot FROM course_catalog_sources",
           "INSERT INTO loose_sources SELECT course_id, snapshot FROM course_catalog_sources WHERE course_id='c-cs5800'",
           "DROP TABLE course_catalog_sources", "ALTER TABLE loose_sources RENAME TO course_catalog_sources",
           "CREATE TABLE loose_plans(plan_id TEXT, program_id TEXT, campus TEXT, catalog_year TEXT, pathway TEXT, "
           "concentration TEXT, document TEXT, content_hash TEXT)",
           "INSERT INTO loose_plans SELECT plan_id, program_id, campus, catalog_year, pathway, concentration, document, "
           "content_hash FROM program_plans",
           "INSERT INTO loose_plans SELECT plan_id, program_id, campus, catalog_year, pathway, concentration, document, "
           "content_hash FROM program_plans WHERE plan_id='ds-ms-boston-2026-2027-standard'",
           "DROP TABLE program_plans", "ALTER TABLE loose_plans RENAME TO program_plans",
           "CREATE TABLE loose_docs(course_id TEXT, catalog_year TEXT, document TEXT, content_hash TEXT)",
           "INSERT INTO loose_docs SELECT * FROM course_requisite_documents",
           "INSERT INTO loose_docs SELECT * FROM course_requisite_documents WHERE course_id='c-cs5800'",
           "DROP TABLE course_requisite_documents", "ALTER TABLE loose_docs RENAME TO course_requisite_documents")
    report = audit.build_report(seeded)
    catalog = section(report, "catalog_snapshots")["counts"]
    assert (catalog["usable"], catalog["duplicate_rows"]) == (2, 1)
    plans = section(report, "program_plans")
    assert (plans["counts"]["usable"], plans["counts"]["duplicate_scope_or_id"]) == (2, 2)
    assert plans["programs"]["with_only_partial_plans"] == 0 and plans["programs"]["without_usable_plan"] == 3
    documents = section(report, "requisite_documents")["counts"]
    assert (documents["usable"], documents["duplicate_rows"]) == (2, 2)


# --- details ---------------------------------------------------------------------------------


def test_details_are_off_by_default_and_bounded(seeded):
    assert "details" not in audit.build_report(seeded)
    details = audit.build_report(seeded, details=True)["details"]
    assert details["max_codes"] == audit.DEFAULT_MAX_CODES
    assert details["courses"]["invalid_json"] == {"items": ["CS 9999"], "omitted": 0, "unlisted_malformed": 0}
    assert details["courses"]["duplicate_codes"]["items"] == ["DS 5220"]
    assert details["catalog_snapshots"]["identity_mismatch"]["items"] == ["AAI 6600"]
    assert details["fields"]["credits.catalog_conflict"]["items"] == ["CS 5200"]
    assert details["fields"]["prereqs.catalog_only"]["items"] == ["CS 5200"]
    assert details["requisite_documents"]["prerequisite_unparsed"]["items"] == [{"catalog_year": "2026-2027", "code": "CS 5200"}]
    assert details["requisite_documents"]["credit_hours_conflict"]["items"] == [{"catalog_year": "2026-2027", "code": "CS 5200"}]
    assert sorted(details["requisite_documents"]["legacy_prereqs_without_usable_document"]["items"]) == ["CS 6140", "DS 5220"]
    assert details["program_plans"]["programs_without_usable_plan"]["items"] == ["aai-ms", "info-ms"]
    assert details["program_plans"]["content_hash_mismatch"]["items"] == ["info-ms-boston-2026-2027-standard"]
    assert details["program_plans"]["identity_mismatch"]["items"] == ["aai-ms-boston-2026-2027-standard"]
    scopes = details["program_plans"]["usable_scopes"]["items"]
    assert [item["coverage"] for item in scopes if item["program_id"] == "ds-ms"] == ["partial"]
    bounded = audit.build_report(seeded, details=True, max_codes=1)["details"]
    assert bounded["fields"]["prereqs.missing"] == {"items": ["AAI 6600"], "omitted": 3, "unlisted_malformed": 0}


def test_malformed_column_values_are_counted_not_listed(seeded):
    modify(seeded, f"UPDATE courses SET primary_code='{SENTINEL}' WHERE course_id='c-bad-json'")
    details = audit.build_report(seeded, details=True)["details"]
    assert details["courses"]["invalid_json"] == {"items": [], "omitted": 0, "unlisted_malformed": 1}


@pytest.mark.parametrize("value", [0, audit.MAX_CODES_LIMIT + 1, "5"])
def test_max_codes_is_bounded(seeded, value):
    with pytest.raises(ValueError):
        audit.build_report(seeded, details=True, max_codes=value)


# --- privacy, read-only, inputs --------------------------------------------------------------


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
    reads = {(table, column) for action, table, column, _, _ in calls if action == sqlite3.SQLITE_READ}
    assert reads and all(column in audit.READABLE[table] for table, column in reads)
    assert not any(table in UNREAD_TABLES for _, table, *_ in calls)
    assert ("courses", "raw_text") not in reads
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
    (sqlite3.SQLITE_READ, "courses", "generated_json", "main", "some_view", False),
    (sqlite3.SQLITE_READ, "courses", "generated_json", "temp", None, False),
    (sqlite3.SQLITE_SELECT, None, None, None, None, True),
    (sqlite3.SQLITE_TRANSACTION, "BEGIN", None, None, None, True),
    (sqlite3.SQLITE_TRANSACTION, "COMMIT", None, None, None, False),
    (sqlite3.SQLITE_FUNCTION, None, "count", None, None, False),
    (sqlite3.SQLITE_PRAGMA, "query_only", "OFF", None, None, False),
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

    def tracked(database, *args, **kwargs):
        conn = connect(database, *args, **kwargs)
        opened.append((database, kwargs))
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(audit.sqlite3, "connect", tracked)
    assert audit.build_report(seeded)["complete"] is True
    assert len(opened) == 1 and opened[0][0].endswith("?mode=ro&immutable=1") and opened[0][1]["uri"] is True
    assert statements[:3] == ["PRAGMA query_only=ON", "PRAGMA trusted_schema=OFF", "BEGIN"]
    assert all(sql.split()[0] in {"PRAGMA", "BEGIN", "SELECT"} for sql in statements)
    assert sum(sql == "BEGIN" for sql in statements) == 1


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


@pytest.mark.parametrize("name, code", [("//private-server/share/copy.sqlite3", "nonlocal_input_path"),
                                        (".env", "unsafe_input_path")])
def test_unsafe_paths_are_refused(tmp_path, name, code):
    path = Path(name) if name.startswith("//") else tmp_path / name
    if not name.startswith("//"):
        path.write_text(SENTINEL)
    report = audit.build_report(path)
    assert report["database"] == {"status": "failed", "code": code}
    assert SENTINEL not in json.dumps(report) and "private-server" not in json.dumps(report)


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
    assert all(item == {"status": "not_checked", "code": "database_unavailable"} for item in report["sections"].values())


# --- command line ----------------------------------------------------------------------------


def run_cli(*args, cwd):
    return subprocess.run([sys.executable, "-B", str(SCRIPT), *args], cwd=cwd, text=True, capture_output=True, timeout=120)


def test_cli_exit_codes(seeded, tmp_path):
    complete = run_cli("--db-copy", str(seeded), cwd=tmp_path)
    assert complete.returncode == 0 and complete.stderr == ""
    assert json.loads(complete.stdout)["complete"] is True
    modify(seeded, "DROP TABLE program_plans")
    partial = run_cli("--db-copy", str(seeded), "--details", cwd=tmp_path)
    assert partial.returncode == 2 and json.loads(partial.stdout)["complete"] is False
    missing = run_cli("--db-copy", str(tmp_path / f"{SENTINEL}.sqlite3"), cwd=tmp_path)
    assert missing.returncode == 1 and json.loads(missing.stdout)["database"]["code"] == "database_copy_missing"
    assert SENTINEL not in missing.stdout + missing.stderr
    bad = run_cli("--db-copy", str(seeded), "--max-codes", SENTINEL, cwd=tmp_path)
    assert bad.returncode == 1 and json.loads(bad.stdout)["code"] == "invalid_arguments"
    assert SENTINEL not in bad.stdout + bad.stderr
    over = run_cli("--db-copy", str(seeded), "--details", "--max-codes", "0", cwd=tmp_path)
    assert over.returncode == 1 and json.loads(over.stdout)["code"] == "invalid_arguments"


def test_fresh_process_has_no_config_env_network_subprocess_or_writes(seeded, tmp_path):
    code = '''
import importlib.abc, os, pathlib, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'config', 'api', 'app', 'dotenv'}:
            raise RuntimeError('forbidden_config_import')
sys.meta_path.insert(0, Block())
def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'}:
        raise RuntimeError('forbidden_external_action')
    if event == 'open':
        path, mode, flags = args
        if isinstance(path, (str, bytes)):
            name = pathlib.Path(os.fsdecode(path)).name.lower()
            if name == '.env' or name.startswith('.env.'):
                raise RuntimeError('forbidden_env_read')
        if (mode and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise RuntimeError('forbidden_disk_write')
sys.addaudithook(audit)
sys.path.insert(0, sys.argv[1])
from scripts.audit_data_coverage import cli
raise SystemExit(cli(sys.argv[2:]))
'''
    before = snapshot_dir(tmp_path)
    run = subprocess.run([sys.executable, "-B", "-c", code, str(ROOT), "--db-copy", str(seeded), "--details"],
                         cwd=tmp_path, text=True, capture_output=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    assert run.stderr == ""
    report = json.loads(run.stdout)
    assert report["complete"] is True and SENTINEL not in run.stdout
    assert snapshot_dir(tmp_path) == before
