"""Additive v1.6 source documents, readonly sync and atomic caller transactions."""

from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from db.connection import connect
from db.course_requisite_repository import CourseRequisiteRepository, content_hash
from db.repository import CourseRepository
from schemas.course import Course
from schemas.course_requisite_document import CourseRequisiteDocument
from schemas.course_requisite_source import CourseRequisiteSource
from scrapers.course_requisites import parse_clause
from scripts.capture_course_requisites import capture_departments
from scripts.init_db import init_database
from scripts.sync_course_requisites import sync_requisites

ROOT = Path(__file__).resolve().parent.parent


def document(course_id="target", course_code="CS 5004", course_name="Design", year="2026-2027", raw="CS 5001 with a minimum grade of B- or CS 5010 with a minimum grade of C-"):
    source = CourseRequisiteSource(url="https://catalog.northeastern.edu/course-descriptions/cs/", catalog_year=year,
        captured_at=datetime(2026, 10, 1, tzinfo=timezone.utc), sha256="a" * 64, byte_count=10, page_title="Computer Science (CS)")
    return CourseRequisiteDocument(course_id=course_id, course_code=course_code, course_name=course_name, catalog_year=year,
        source=source, requisites={"prerequisite": parse_clause(raw), "corequisite": parse_clause("CS 5005")})


def target(conn):
    CourseRepository(conn).insert(Course(course_id="target", primary_code="CS 5004", primary_name="Design"), raw_text="keep")


def test_repository_preserves_unknown_references_scope_and_original_import_time(empty_db):
    target(empty_db)
    repo = CourseRequisiteRepository(empty_db)
    first = document()
    assert repo.store(first)
    original = empty_db.execute("SELECT document FROM course_requisite_documents").fetchone()[0]
    newer_import = first.model_copy(update={"imported_at": datetime(2026, 10, 2, tzinfo=timezone.utc)})
    assert content_hash(first) == content_hash(newer_import)
    assert repo.store(newer_import) is False
    assert empty_db.execute("SELECT document FROM course_requisite_documents").fetchone()[0] == original
    stored = repo.list_for_course("target").documents[0]
    assert stored.requisites.corequisite.rule.course_code == "CS 5005"  # Not in courses; never dropped.
    assert stored.requisites.prerequisite.rule.kind == "any_of" and stored.campus is None
    assert repo.store(document(year="2025-2026"))
    assert len(repo.list_for_course("target").documents) == 2
    assert [item.catalog_year for item in repo.list_for_course("target", catalog_year="2025-2026").documents] == ["2025-2026"]
    assert repo.list_for_course("target", catalog_year="2024-2025").documents == []


@pytest.mark.parametrize("kind", ["course-id", "code", "title", "edition", "campus", "time", "tree-text"])
def test_model_or_store_rejects_rebinding_or_semantic_mismatch(empty_db, kind):
    target(empty_db)
    data = document().model_dump(mode="json")
    if kind == "course-id":
        data["course_id"] = "unseeded"
    elif kind == "code":
        data["course_code"] = "DS 5500"
    elif kind == "title":
        data["course_name"] = "Changed"
    elif kind == "edition":
        data["catalog_year"] = "2025-2026"
    elif kind == "campus":
        data["campus"] = "boston"
    elif kind == "time":
        data["imported_at"] = "2026-10-01T00:00:00"
    else:
        data["requisites"]["prerequisite"]["rule"]["kind"] = "all_of"
    with pytest.raises(ValueError):
        CourseRequisiteRepository(empty_db).store(CourseRequisiteDocument.model_validate(data))
    assert empty_db.execute("SELECT COUNT(*) FROM course_requisite_documents").fetchone()[0] == 0


def test_unchecked_model_copy_cannot_bypass_store_validation(empty_db):
    target(empty_db)
    unchecked = document().model_copy(update={"campus": "boston"})
    with pytest.warns(UserWarning, match="Pydantic serializer warnings"), pytest.raises(ValueError):
        CourseRequisiteRepository(empty_db).store(unchecked)


@pytest.mark.parametrize("kind", ["hash", "column-year", "json-year", "title", "tree-with-rehashed-content", "scalar-json"])
def test_corrupt_records_are_counted_not_treated_as_missing_or_returned(empty_db, kind):
    target(empty_db)
    repo = CourseRequisiteRepository(empty_db)
    repo.store(document())
    if kind == "hash":
        empty_db.execute("UPDATE course_requisite_documents SET content_hash='wrong'")
    elif kind == "column-year":
        empty_db.execute("UPDATE course_requisite_documents SET catalog_year='2025-2026'")
    elif kind == "scalar-json":
        empty_db.execute("UPDATE course_requisite_documents SET document='123'")
    else:
        data = document().model_dump(mode="json")
        if kind == "title":
            data["course_name"] = "Changed"
        elif kind == "json-year":
            data["catalog_year"] = "2025-2026"
        else:
            data["requisites"]["prerequisite"]["rule"]["kind"] = "all_of"
        text = json.dumps(data)
        if kind == "tree-with-rehashed-content":
            payload = {key: value for key, value in data.items() if key != "imported_at"}
            digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            empty_db.execute("UPDATE course_requisite_documents SET document=?,content_hash=?", (text, digest))
        else:
            empty_db.execute("UPDATE course_requisite_documents SET document=?", (text,))
    bundle = repo.list_for_course("target")
    assert bundle.documents == [] and bundle.unusable_records == 1
    assert "structured_requisites_unusable" in bundle.warnings
    assert "structured_requisites_missing" not in bundle.warnings


def test_verified_new_document_can_repair_bad_row_without_trusting_hash_alone(empty_db):
    target(empty_db)
    repo = CourseRequisiteRepository(empty_db)
    good = document()
    repo.store(good)
    empty_db.execute("UPDATE course_requisite_documents SET document='123'")
    assert repo.store(good) and repo.list_for_course("target").documents == [good]


def test_missing_or_malformed_table_never_auto_creates_or_returns_fake_success(empty_db):
    target(empty_db)
    empty_db.execute("DROP TABLE course_requisite_documents")
    repo = CourseRequisiteRepository(empty_db)
    assert repo.list_for_course("target").schema_available is False
    with pytest.raises(ValueError, match="schema missing"):
        repo.store(document())
    assert not repo.available()
    empty_db.execute("CREATE TABLE course_requisite_documents(course_id TEXT, catalog_year TEXT)")
    bundle = repo.list_for_course("target")
    assert bundle.documents == [] and "structured_requisite_schema_unusable" in bundle.warnings


def test_caller_rollback_and_foreign_key_cascade(empty_db):
    target(empty_db)
    empty_db.commit()
    repo = CourseRequisiteRepository(empty_db)
    repo.store(document())
    empty_db.rollback()
    assert repo.list_for_course("target").documents == []
    repo.store(document())
    empty_db.commit()
    empty_db.execute("DELETE FROM courses WHERE course_id='target'")
    assert empty_db.execute("SELECT COUNT(*) FROM course_requisite_documents").fetchone()[0] == 0


@pytest.fixture
def runtime(tmp_path):
    path, archive = tmp_path / "runtime.db", tmp_path / "archive"
    init_database(path)
    conn = connect(path)
    repo = CourseRepository(conn)
    for cid, code, name in [("design", "CS 5004", "Design"), ("algo", "CS 5800", "Algorithms")]:
        repo.insert(Course(course_id=cid, primary_code=code, primary_name=name, topics_covered=["keep topic"]), raw_text="keep raw text")
        repo.mark_indexed(cid)
    conn.execute("UPDATE courses SET search_expansion='keep expansion'")
    conn.execute("INSERT INTO course_prerequisites(course_id,prereq_course_id,requirement,notes) VALUES('algo','design','recommended','keep legacy')")
    conn.execute("DROP TABLE course_requisite_documents")
    conn.execute("DELETE FROM schema_versions WHERE version='1.6'")
    conn.commit()
    conn.close()
    html = b'''<h1>Computer Science (CS)</h1><p>2026-2027 Edition</p>
<div class="courseblock"><p class="courseblocktitle">CS 5004. Design. (4 Hours)</p>
<p class="courseblockextra"><strong>Prerequisite(s): </strong>CS 5001 or CS 5010</p>
<p class="courseblockextra"><strong>Corequisite(s): </strong>CS 5005</p></div>
<div class="courseblock"><p class="courseblocktitle">CS 5800. Algorithms. (4 Hours)</p></div>'''
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=html, headers={"content-type": "text/html"})))
    with client:
        captured = capture_departments(["cs"], "2026-2027", archive, client=client)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(captured), encoding="utf-8")
    return path, manifest, archive


def original_rows(path):
    conn = connect(path)
    try:
        return {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table}")]
                for table in ["courses", "course_prerequisites", "course_catalog_sources", "programs", "program_required_courses", "course_aliases"]}
    finally:
        conn.close()


def test_sync_readonly_then_atomic_additive_and_idempotent(runtime):
    path, manifest, archive = runtime
    before, rows = path.read_bytes(), original_rows(path)
    report = sync_requisites(path, manifest, archive, ["CS 5004", "CS 5800"])
    assert report == {"records": 2, "unparsed_sections": 0, "schema_missing": True, "committed": False, "would_store": 2, "stored": 0}
    assert path.read_bytes() == before
    committed = sync_requisites(path, manifest, archive, ["CS 5004", "CS 5800"], commit=True)
    assert committed["stored"] == 2 and original_rows(path) == rows
    conn = connect(path)
    documents = [tuple(row) for row in conn.execute("SELECT * FROM course_requisite_documents ORDER BY course_id")]
    assert conn.execute("SELECT 1 FROM schema_versions WHERE version='1.6'").fetchone()
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()
    repeat = sync_requisites(path, manifest, archive, ["CS 5004", "CS 5800"], commit=True)
    assert repeat["stored"] == repeat["would_store"] == 0
    conn = connect(path)
    assert [tuple(row) for row in conn.execute("SELECT * FROM course_requisite_documents ORDER BY course_id")] == documents
    conn.close()


@pytest.mark.parametrize("kind", ["title", "ambiguous", "unknown"])
def test_no_course_rewrite_or_schema_commit_to_force_source_match(runtime, kind):
    path, manifest, archive = runtime
    conn = connect(path)
    if kind == "title":
        conn.execute("UPDATE courses SET primary_name='Renamed' WHERE course_id='design'")
    elif kind == "ambiguous":
        CourseRepository(conn).insert(Course(course_id="second", primary_code="CS 5004", primary_name="Design"))
    else:
        conn.execute("DELETE FROM courses WHERE course_id='design'")
    conn.commit()
    conn.close()
    rows = original_rows(path)
    with pytest.raises(ValueError, match="match one existing"):
        sync_requisites(path, manifest, archive, ["CS 5004", "CS 5800"], commit=True)
    conn = connect(path)
    assert not CourseRequisiteRepository(conn).available()
    assert not conn.execute("SELECT 1 FROM schema_versions WHERE version='1.6'").fetchone()
    conn.close()
    assert original_rows(path) == rows


def test_late_store_failure_rolls_back_schema_version_and_earlier_document(runtime, monkeypatch):
    path, manifest, archive = runtime
    rows, store = original_rows(path), CourseRequisiteRepository.store
    def fail_second(self, item):
        if item.course_id == "algo":
            raise ValueError("Injected late failure")
        return store(self, item)
    monkeypatch.setattr(CourseRequisiteRepository, "store", fail_second)
    with pytest.raises(ValueError, match="late failure"):
        sync_requisites(path, manifest, archive, ["CS 5004", "CS 5800"], commit=True)
    conn = connect(path)
    assert not CourseRequisiteRepository(conn).available()
    assert not conn.execute("SELECT 1 FROM schema_versions WHERE version='1.6'").fetchone()
    conn.close()
    assert original_rows(path) == rows


def test_bad_source_fails_before_any_database_open(runtime, monkeypatch):
    import scripts.sync_course_requisites as sync
    path, manifest, archive = runtime
    metadata = json.loads(manifest.read_text())[0]
    (archive / f"{metadata['sha256']}.html").write_bytes(b"changed")
    def no_connect(*args, **kwargs):
        pytest.fail("Bad source reached DB")
    monkeypatch.setattr(sync.sqlite3, "connect", no_connect)
    with pytest.raises(ValueError):
        sync_requisites(path, manifest, archive, ["CS 5004"], commit=True)


def test_misspelled_database_path_is_never_created(runtime):
    path, manifest, archive = runtime
    wrong = path.parent / "typo.db"
    with pytest.raises(OSError):
        sync_requisites(wrong, manifest, archive, ["CS 5004"], commit=True)
    assert not wrong.exists()


def test_real_cli_default_readonly_then_explicit_commit(runtime):
    path, manifest, archive = runtime
    command = [sys.executable, str(ROOT / "scripts/sync_course_requisites.py"), "--db-path", str(path),
               "--manifest-file", str(manifest), "--source-dir", str(archive), "--course-code", "CS 5004"]
    before = path.read_bytes()
    first = subprocess.run(command, capture_output=True, text=True, timeout=45)
    assert first.returncode == 0 and json.loads(first.stdout)["stored"] == 0
    assert before == path.read_bytes()
    for expected in [1, 0]:
        result = subprocess.run([*command, "--commit"], capture_output=True, text=True, timeout=45)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["stored"] == expected


def test_unparsed_source_is_stored_as_unknown_not_partial_successful_tree(runtime):
    path, manifest, archive = runtime
    old = json.loads(manifest.read_text())[0]
    html = (archive / f"{old['sha256']}.html").read_bytes().replace(b"CS 5001 or CS 5010", b"CS 5001 or permission of instructor")
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=html, headers={"content-type": "text/html"}))) as client:
        captures = capture_departments(["cs"], "2026-2027", archive, client=client)
    manifest.write_text(json.dumps(captures))
    command = [sys.executable, str(ROOT / "scripts/sync_course_requisites.py"), "--db-path", str(path),
               "--manifest-file", str(manifest), "--source-dir", str(archive), "--course-code", "CS 5004", "--commit"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr  # Sync outcome, NOT parse/eligibility success.
    report = json.loads(result.stdout)
    assert report["stored"] == 1 and report["unparsed_sections"] == 1 and report["committed"] is True
    conn = connect(path)
    section = CourseRequisiteRepository(conn).list_for_course("design").documents[0].requisites.prerequisite
    assert section.status == "unparsed" and section.rule is None and "permission" in section.raw_text
    conn.close()


def test_same_year_update_replaces_only_that_scope_not_other_year_or_course(empty_db):
    target(empty_db)
    repo = CourseRequisiteRepository(empty_db)
    repo.store(document())
    older = document(year="2025-2026")
    repo.store(older)
    changed = document(raw="CS 5010 with a minimum grade of B-")
    assert repo.store(changed)
    assert repo.list_for_course("target", catalog_year="2026-2027").documents == [changed]
    assert repo.list_for_course("target", catalog_year="2025-2026").documents == [older]
    assert empty_db.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 1


def test_later_course_title_change_quarantines_old_documents_instead_of_rebinding(empty_db):
    target(empty_db)
    repo = CourseRequisiteRepository(empty_db)
    repo.store(document())
    empty_db.execute("UPDATE courses SET primary_name='Changed title' WHERE course_id='target'")
    bundle = repo.list_for_course("target")
    assert bundle.documents == [] and bundle.unusable_records == 1 and bundle.has_any_stored_records
