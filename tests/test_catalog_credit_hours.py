"""Range titles must not be dropped or converted to a fictional fixed credit."""

import hashlib
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup
from streamlit.testing.v1 import AppTest

from app.course_requisite_view import legacy_graph_allowed, render_course_requisites
from db.catalog_source_repository import CatalogSourceRepository
from db.connection import connect
from db.course_requisite_repository import CourseRequisiteRepository, content_hash
from db.repository import CourseRepository
from schemas.catalog_credit_hours import CatalogCreditHours
from schemas.course_description_evidence import CourseDescriptionEvidence
from schemas.course_requisite_document import CourseRequisiteDocument
from scrapers.neu_catalog import CatalogEntry, _parse_courseblock, _parse_dept_html
from scripts.audit_course_requisites import build_report
from scripts.capture_course_requisites import capture_departments
from scripts.ingest_neu_catalog import upsert_one
from scripts.sync_course_requisites import sync_requisites
from tests.test_course_requisite_contract import source_document
from tests.test_course_requisite_sources import archive, source_html
from tests.test_course_requisite_storage import document, target, original_rows
from tests.test_course_requisite_storage import runtime  # noqa: F401 - Registers the isolated DB fixture.
from tests.test_course_requisite_view import FakeSt, bundle, app_source

ROOT = Path(__file__).resolve().parent.parent
URL = "https://catalog.northeastern.edu/course-descriptions/cs/"


def parsed(hours):
    html = source_html().decode().replace("(4 Hours)", f"({hours})")
    block = BeautifulSoup(html, "html.parser").select_one("div.courseblock")
    return _parse_courseblock(block, source_url=URL)


def with_hours(doc, text):
    return CourseRequisiteDocument.model_validate({**doc.model_dump(mode="json"), "credit_hours": CatalogCreditHours.from_text(text).model_dump(mode="json")})


def test_range_title_retains_course_identity_and_no_fixed_integer_credit():
    block = BeautifulSoup('<div class="courseblock"><p class="courseblocktitle">'
        'DS 4996. Experiential Education Directed Study. (1-4 Hours)</p>'
        '<p class="cb_desc">Restricted to eligible students.</p></div>', "html.parser").div
    result = _parse_courseblock(block, source_url="https://catalog.northeastern.edu/course-descriptions/ds/")
    assert result is not None
    assert result.course_code == "DS 4996" and result.course_name == "Experiential Education Directed Study"
    assert result.credits is None
    assert result.credit_hours.kind == "range"
    assert result.credit_hours.minimum == 1 and result.credit_hours.maximum == 4


def test_offline_report_accepts_range_title_and_keeps_raw_hours(tmp_path):
    manifest, directory, _ = archive(tmp_path, source_html().replace(b"(4 Hours)", b"(1-4 Hours)"))
    record = build_report(manifest, directory, ["CS 5004"])["records"][0]
    assert record["course_name"] == "Design"
    assert record["credit_hours"]["raw_text"] == "1-4 Hours"
    assert record["credit_hours"]["minimum"] == "1" and record["credit_hours"]["maximum"] == "4"
    assert record["requisites"]["prerequisite"]["rule"]["kind"] == "all_of"


@pytest.mark.parametrize("raw,expected", [
    ("0 Hours", 0), ("1 Hour", 1), ("4 Hours", 4), ("4.0 Hours", 4), ("4Hours", 4),
    ("3.5 Hours", None), (".5 Hours", None), ("0.01 Hours", None),
    ("4.000000000000000000000000001 Hours", None),
])
def test_fixed_zero_and_fractional_literals_keep_exact_decimal_without_rounding(raw, expected):
    result = parsed(raw)
    assert result is not None and result.credits == expected
    assert result.credit_hours.kind == "fixed"
    value = Decimal(raw.removesuffix("Hours").removesuffix("Hour").strip())
    assert result.credit_hours.minimum == result.credit_hours.maximum == value
    assert CatalogEntry.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("raw,minimum,maximum", [
    ("1-4 Hours", "1", "4"), ("1–4 Hours", "1", "4"), ("1—4 Hours", "1", "4"),
    ("1 - 4 Hours", "1", "4"), ("0-12 Hours", "0", "12"),
    ("0.5-1.5 Hours", "0.5", "1.5"), ("1-1 Hour", "1", "1"), ("1.0–4.0 Hours", "1.0", "4.0"),
])
def test_range_separators_bounds_and_equal_range_are_not_fixed_credits(raw, minimum, maximum):
    result = parsed(raw)
    assert result is not None and result.credits is None
    assert result.credit_hours.raw_text == raw and result.credit_hours.kind == "range"
    assert result.credit_hours.model_dump(mode="json")["minimum"] == minimum
    assert result.credit_hours.model_dump(mode="json")["maximum"] == maximum


@pytest.mark.parametrize("raw", [
    "4-1 Hours", "-1-4 Hours", "+4 Hours", "1-13 Hours", "0-12.1 Hours", "13 Hours",
    "1/4 Hours", "1 or 4 Hours", "TBA Hours", "4..5 Hours", "NaN Hours", "Infinity Hours",
    "1e0 Hours", "4 Credits", "1-2-4 Hours", "4 (Hours)", "", "4. Hours", "x" * 101,
])
def test_malformed_or_out_of_budget_title_is_rejected_not_unknown_credit_success(raw):
    assert parsed(raw) is None
    with pytest.raises(ValueError):
        CatalogCreditHours.from_text(raw)


@pytest.mark.parametrize("changes", [
    {"minimum": "2"}, {"maximum": "5"}, {"kind": "fixed"}, {"raw_text": "4-1 Hours"},
    {"minimum": "NaN"}, {"maximum": "Infinity"}, {"selected_credits": 3}, {"format_version": "2"},
])
def test_literal_model_rejects_inconsistent_bounds_or_invented_selected_credits(changes):
    payload = CatalogCreditHours.from_text("1-4 Hours").model_dump(mode="json")
    with pytest.raises(ValueError):
        CatalogCreditHours.model_validate({**payload, **changes})


@pytest.mark.parametrize("raw,wrong", [("1-4 Hours", 4), ("1-1 Hours", 1), ("3.5 Hours", 3), ("4 Hours", None), ("0 Hours", None)])
def test_new_jsonl_cannot_bind_range_or_fraction_to_wrong_legacy_integer(raw, wrong):
    with pytest.raises(ValueError):
        CatalogEntry(course_code="CS 5004", course_name="Design", credits=wrong, credit_hours=CatalogCreditHours.from_text(raw))


def test_legacy_jsonl_remains_unknown_literal_and_fixed_snapshot_hash_is_unchanged():
    old = CatalogEntry.model_validate_json('{"course_code":"CS 5004","course_name":"Design","credits":4}')
    assert old.credit_hours is None and old.credits == 4
    entry = parsed("4 Hours")
    snapshot = CatalogSourceRepository.snapshot(entry)
    original = {"course_code": "CS 5004", "course_name": "Design", "credits": 4,
                "description": "Approval outside requisite clauses is not evaluated.", "prereq_codes": [], "catalog_url": URL}
    digest = hashlib.sha256(json.dumps(original, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert snapshot.snapshot_id == f"catalog:{digest}"
    assert "credit_hours" not in snapshot.model_dump()


def test_department_parser_skips_only_bad_title_and_preserves_range_prerequisite_corequisite():
    html = source_html().decode().replace("(4 Hours)", "(1-4 Hours)")
    bad = '<div class="courseblock"><p class="courseblocktitle">CS 9999. Bad. (4-1 Hours)</p></div>'
    result = _parse_dept_html(html + bad, source_url=URL)
    assert [item.course_code for item in result] == ["CS 5004"]
    assert result[0].requisites.prerequisite.rule.kind == "all_of"
    assert result[0].requisites.corequisite.rule.course_code == "CS 5005"


def test_range_title_keeps_suffix_nonbreaking_space_and_periods_in_name():
    block = BeautifulSoup('<div><p class="courseblocktitle">DS\u00a04996A. Topics in Analysis. Part II. '
        '(0.5\u00a0–\u00a01.5 Hours)</p></div>', "html.parser").div
    entry = _parse_courseblock(block, source_url="https://catalog.northeastern.edu/course-descriptions/ds/")
    assert entry.course_code == "DS 4996A" and entry.course_name == "Topics in Analysis. Part II"
    assert entry.credit_hours.raw_text == "0.5 – 1.5 Hours" and entry.credits is None


def test_range_does_not_turn_unsupported_external_prerequisite_into_partial_success(tmp_path):
    raw = "( CS 3100 with a minimum grade of D- or CIS 310M with a minimum grade of D- ); CS 3800 with a minimum grade of D-"
    content = source_html(raw).replace(b"(4 Hours)", b"(1-6 Hours)")
    manifest, directory, _ = archive(tmp_path, content)
    report = build_report(manifest, directory, ["CS 5004"])
    section = report["records"][0]["requisites"]["prerequisite"]
    assert report["unparsed_sections"] == 1 and section["raw_text"] == raw and section["rule"] is None
    assert report["records"][0]["credit_hours"]["maximum"] == "6"


def test_normal_ingest_keeps_range_credits_unknown_in_v11_and_v14(empty_db):
    repo, sources = CourseRepository(empty_db), CatalogSourceRepository(empty_db)
    cid = upsert_one(parsed("1-4 Hours"), course_repo=repo, catalog_repo=sources)
    course = repo.get(cid)
    assert course.credits is None and course.schema_version == "1.1"
    assert sources.get_batch([course])[cid].credits is None
    row = empty_db.execute("SELECT metadata,generated_json FROM courses WHERE course_id=?", (cid,)).fetchone()
    assert json.loads(row["metadata"])["credits"] is None
    assert json.loads(row["generated_json"])["credits"] is None


@pytest.mark.parametrize("flavor", ["05c2", "05c3"])
def test_independent_old_document_hash_and_idempotency_survive_new_empty_hours(empty_db, flavor):
    target(empty_db)
    payload = document().model_dump(mode="json")
    payload.pop("credit_hours")
    if flavor == "05c2":
        payload.pop("description_evidence")
    else:
        payload["description_evidence"] = CourseDescriptionEvidence.from_paragraphs(["Requires admission."]).model_dump(mode="json")
    original = {key: value for key, value in payload.items() if key != "imported_at"}
    digest = hashlib.sha256(json.dumps(original, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    raw = json.dumps(payload)
    empty_db.execute("INSERT INTO course_requisite_documents VALUES(?,?,?,?)", ("target", "2026-2027", raw, digest))
    repo = CourseRequisiteRepository(empty_db)
    restored = repo.list_for_course("target").documents[0]
    assert restored.credit_hours is None and content_hash(restored) == digest
    assert repo.store(restored) is False
    assert empty_db.execute("SELECT document FROM course_requisite_documents").fetchone()[0] == raw
    updated = with_hours(restored, "1-4 Hours")
    assert content_hash(updated) != digest and repo.store(updated) and not repo.store(updated)


def test_mutated_hours_and_rehashed_bad_bounds_are_rejected_or_quarantined(empty_db):
    target(empty_db)
    repo = CourseRequisiteRepository(empty_db)
    valid = with_hours(document(), "1-4 Hours")
    assert repo.store(valid)
    valid.credit_hours.maximum = Decimal("5")
    with pytest.raises(ValueError):
        repo.store(valid)
    corrupted = valid.model_dump(mode="json")
    hashed = {key: value for key, value in corrupted.items() if key != "imported_at"}
    if hashed["description_evidence"] is None:
        hashed.pop("description_evidence")
    digest = hashlib.sha256(json.dumps(hashed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    empty_db.execute("UPDATE course_requisite_documents SET document=?, content_hash=?", (json.dumps(corrupted), digest))
    state = repo.list_for_course("target")
    assert state.documents == [] and state.unusable_records == 1 and state.has_any_stored_records
    assert not legacy_graph_allowed(state.model_dump(mode="json"))


def replace_capture(manifest, directory, content):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content, headers={"content-type": "text/html"}))) as client:
        captures = capture_departments(["cs"], "2026-2027", directory, client=client)
    manifest.write_text(json.dumps(captures))


def test_explicit_range_sync_is_readonly_then_additive_idempotent_and_keeps_legacy_rows(runtime):
    path, manifest, directory = runtime
    replace_capture(manifest, directory, source_html().replace(b"(4 Hours)", b"(1-4 Hours)"))
    before, rows = path.read_bytes(), original_rows(path)
    assert sync_requisites(path, manifest, directory, ["CS 5004"])["stored"] == 0
    assert path.read_bytes() == before
    assert sync_requisites(path, manifest, directory, ["CS 5004"], commit=True)["stored"] == 1
    conn = connect(path)
    try:
        doc = CourseRequisiteRepository(conn).list_for_course("design").documents[0]
        assert doc.credit_hours == CatalogCreditHours.from_text("1-4 Hours")
        assert doc.requisites.corequisite.rule.course_code == "CS 5005"
    finally:
        conn.close()
    assert original_rows(path) == rows
    assert sync_requisites(path, manifest, directory, ["CS 5004"], commit=True)["stored"] == 0
    replace_capture(manifest, directory, source_html().replace(b"(4 Hours)", b"(2-4 Hours)"))
    assert sync_requisites(path, manifest, directory, ["CS 5004"], commit=True)["stored"] == 1
    assert original_rows(path) == rows


def test_bad_range_fails_before_any_database_open_or_migration(runtime, monkeypatch):
    import scripts.sync_course_requisites as sync
    path, manifest, directory = runtime
    replace_capture(manifest, directory, source_html().replace(b"(4 Hours)", b"(4-1 Hours)"))
    def no_connect(*args, **kwargs):
        pytest.fail("Malformed title reached DB")
    before = path.read_bytes()
    monkeypatch.setattr(sync.sqlite3, "connect", no_connect)
    with pytest.raises(ValueError):
        sync_requisites(path, manifest, directory, ["CS 5004"], commit=True)
    assert path.read_bytes() == before


def test_real_sync_cli_can_store_range_and_unknown_clause_without_claiming_syntax_success(runtime):
    path, manifest, directory = runtime
    raw = "CS 5001 or permission of instructor"
    replace_capture(manifest, directory, source_html(raw).replace(b"(4 Hours)", b"(1-4 Hours)"))
    command = [sys.executable, str(ROOT / "scripts/sync_course_requisites.py"), "--db-path", str(path),
        "--manifest-file", str(manifest), "--source-dir", str(directory), "--course-code", "CS 5004", "--commit"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["stored"] == report["unparsed_sections"] == 1
    conn = connect(path)
    try:
        doc = CourseRequisiteRepository(conn).list_for_course("design").documents[0]
        assert doc.credit_hours.kind == "range" and doc.credit_hours.minimum == 1 and doc.credit_hours.maximum == 4
        assert doc.requisites.prerequisite.status == "unparsed" and doc.requisites.prerequisite.raw_text == raw
        assert doc.requisites.prerequisite.rule is None
    finally:
        conn.close()


@pytest.mark.parametrize("bad", [False, True])
def test_real_report_cli_range_success_or_bad_title_has_no_partial_stdout_or_writes(tmp_path, bad):
    content = source_html().replace(b"(4 Hours)", b"(1-4 Hours)")
    if bad:
        content += b'<div class="courseblock"><p class="courseblocktitle">CS 5800. Algorithms. (4-1 Hours)</p></div>'
    manifest, directory, _ = archive(tmp_path, content)
    before = {str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    command = [sys.executable, str(ROOT / "scripts/audit_course_requisites.py"), "--manifest-file", str(manifest),
               "--source-dir", str(directory), "--course-code", "CS 5004"]
    if bad:
        command += ["--course-code", "CS 5800"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    assert result.returncode == (1 if bad else 0), result.stderr
    if bad:
        assert result.stdout == ""
    else:
        assert json.loads(result.stdout)["records"][0]["credit_hours"]["kind"] == "range"
    assert {str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


def test_course_api_exposes_range_without_replacing_course_integer_or_selecting_latest(api_client, empty_db):
    before = api_client.get("/course/c-cs-5800").json()["credits"]
    CourseRequisiteRepository(empty_db).store(with_hours(source_document(), "1-4 Hours"))
    body = api_client.get("/course/c-cs-5800").json()
    assert body["credits"] == before and body["schema_version"] == "1.1"
    doc = body["course_requisites"]["documents"][0]
    assert doc["credit_hours"]["minimum"] == "1" and doc["credit_hours"]["maximum"] == "4"
    assert "selected_credits" not in doc["credit_hours"]
    response = api_client.get("/course/c-cs-5800/requisites", params={"catalog_year": "2024-2025"})
    assert response.json()["documents"] == []


@pytest.mark.parametrize("raw,expected", [(None, "未捕获标题学分"), ("1-4 Hours", "目录范围：1–4"), ("3.5 Hours", "目录固定值：3.5")])
def test_ui_unknown_range_and_fraction_are_distinct_and_no_fixed_guess(raw, expected):
    doc = document(course_id="design")
    if raw is not None:
        doc = with_hours(doc, raw)
    st = FakeSt("2026-2027")
    render_course_requisites(st, bundle(doc), course_id="design", course_code="CS 5004", course_name="Design", key="year")
    assert any(expected in text for text in st.texts)
    if raw == "1-4 Hours":
        assert any("不取端点或平均值" in text for text in st.texts)
        assert not any("目录固定值" in text for text in st.texts)


def test_real_widget_range_is_shown_only_after_edition_choice_with_unknown_section_credit():
    data = bundle(with_hours(document(course_id="design"), "1-4 Hours"))
    app = AppTest.from_string(app_source(data)).run(timeout=45)
    # One recorded edition is shown by default since review 2026-10-03; the
    # range semantics below are unchanged, and clearing still hides everything.
    assert not app.exception and app.selectbox[0].value == "2026-2027"
    app.selectbox[0].set_value("2026-2027").run(timeout=45)
    assert not app.exception and any("目录范围：1–4" in item.value for item in app.text)
    assert any("实际班次学分未声明" in item.value for item in app.text)
    assert not any("目录固定值" in item.value for item in app.text)
    assert len(app.get("graphviz_chart")) == 0
    app.selectbox[0].set_value(None).run(timeout=45)
    assert not app.exception and len(app.text) == 0
