"""Provenance storage + actual offline source sync, preserving course/index state."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from db.catalog_source_repository import CatalogSourceRepository
from db.connection import connect
from db.repository import CourseRepository
from schemas.course import Course
from scrapers.neu_catalog import CatalogEntry, _parse_dept_html
from scripts.ingest_neu_catalog import upsert_one
from scripts.init_db import init_database
from scripts.sync_catalog_sources import sync_sources

ROOT = Path(__file__).resolve().parent.parent


def entry(**fields):
    return CatalogEntry(**{
        "course_code": "CS 5800", "course_name": "Algorithms", "credits": 4,
        "description": "Graph algorithms", "catalog_url": "https://catalog.northeastern.edu/course-descriptions/cs/", **fields,
    })


@pytest.mark.parametrize("url", [None, "javascript:alert(1)", "http://catalog.northeastern.edu/course-descriptions/cs/",
    "https://catalog.northeastern.edu.evil.test/course-descriptions/cs/", "https://catalog.northeastern.edu/course-descriptions/ds/",
    "https://user@catalog.northeastern.edu/course-descriptions/cs/", "https://catalog.northeastern.edu/course-descriptions/cs/?redirect=bad"])
def test_explicit_matching_official_url_required(url):
    with pytest.raises(ValueError):
        CatalogSourceRepository.snapshot(entry(catalog_url=url))


def test_snapshot_hash_is_content_stable_and_import_time_is_not_fetch_time():
    a = CatalogSourceRepository.snapshot(entry())
    b = CatalogSourceRepository.snapshot(entry())
    changed = CatalogSourceRepository.snapshot(entry(description="Changed description"))
    assert a.snapshot_id == b.snapshot_id != changed.snapshot_id
    assert a.retrieved_at is None
    assert a.imported_at.tzinfo is not None


def test_real_html_catalog_ingest_preserves_description_and_origin(empty_db):
    html = (ROOT / "tests/fixtures/neu_catalog/dept_cs.html").read_text(encoding="utf-8")
    source = next(item for item in _parse_dept_html(html, source_url="https://catalog.northeastern.edu/course-descriptions/cs/")
                  if item.course_code == "CS 5800")
    repo = CourseRepository(empty_db)
    catalog = CatalogSourceRepository(empty_db)
    cid = upsert_one(source, course_repo=repo, catalog_repo=catalog)
    stored = catalog.get_batch([repo.get(cid)])[cid]
    assert stored.description == source.description
    assert stored.catalog_url == source.catalog_url
    assert stored.course_name == source.course_name
    assert stored.retrieved_at is None


def test_missing_source_schema_cannot_partially_ingest_course(empty_db):
    empty_db.execute("DROP TABLE course_catalog_sources")
    with pytest.raises(ValueError, match="schema missing"):
        upsert_one(entry(), course_repo=CourseRepository(empty_db), catalog_repo=CatalogSourceRepository(empty_db))
    assert empty_db.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 0


def test_source_foreign_key_cascades(empty_db):
    repo = CourseRepository(empty_db)
    sources = CatalogSourceRepository(empty_db)
    cid = upsert_one(entry(), course_repo=repo, catalog_repo=sources)
    empty_db.execute("DELETE FROM courses WHERE course_id=?", (cid,))
    assert empty_db.execute("SELECT COUNT(*) FROM course_catalog_sources").fetchone()[0] == 0


@pytest.fixture
def runtime(tmp_path):
    path = tmp_path / "runtime.db"
    init_database(path)
    conn = connect(path)
    repo = CourseRepository(conn)
    repo.insert(Course(course_id="existing", primary_code="CS 5800", primary_name="Algorithms",
        credits=4, topics_covered=["Existing syllabus topic"], source_review_ids=["syllabus_existing"]), raw_text="Mixed retrieval text")
    repo.mark_indexed("existing")
    conn.execute("UPDATE courses SET search_expansion='keep expansion' WHERE course_id='existing'")
    conn.execute("DROP TABLE course_catalog_sources")
    conn.execute("DELETE FROM schema_versions WHERE version='1.4'")
    conn.commit()
    conn.close()
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "cs.jsonl").write_text(entry().model_dump_json() + "\n", encoding="utf-8")
    return path, archive


def all_course_columns(path):
    conn = connect(path)
    try:
        return [tuple(row) for row in conn.execute("SELECT * FROM courses ORDER BY course_id")]
    finally:
        conn.close()


def test_sync_read_only_then_additive_and_idempotent(runtime):
    path, archive = runtime
    before_bytes = path.read_bytes()
    before_courses = all_course_columns(path)
    report = sync_sources(path, archive)
    assert report["would_store"] == report["matched"] == 1
    assert report["schema_missing"] is True
    assert report["committed"] is False
    assert path.read_bytes() == before_bytes
    committed = sync_sources(path, archive, commit=True)
    assert committed["stored"] == 1
    assert all_course_columns(path) == before_courses
    conn = connect(path)
    snapshot_json = conn.execute("SELECT snapshot FROM course_catalog_sources").fetchone()[0]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()
    repeated = sync_sources(path, archive, commit=True)
    assert repeated["stored"] == 0
    assert repeated["unchanged"] == 1
    conn = connect(path)
    assert conn.execute("SELECT snapshot FROM course_catalog_sources").fetchone()[0] == snapshot_json
    conn.close()


@pytest.mark.parametrize("kind", ["title", "unknown", "ambiguous"])
def test_backfill_does_not_attach_ambiguous_or_mismatched_sources(runtime, kind):
    path, archive = runtime
    if kind == "ambiguous":
        conn = connect(path)
        CourseRepository(conn).insert(Course(course_id="duplicate-code", primary_code="CS 5800", primary_name="Algorithms"))
        conn.commit()
        conn.close()
    else:
        replacement = entry(course_name="Different title") if kind == "title" else entry(course_code="CS 9999")
        (archive / "cs.jsonl").write_text(replacement.model_dump_json(), encoding="utf-8")
    report = sync_sources(path, archive, commit=True)
    assert report["stored"] == 0
    assert report["matched"] == 0
    assert report["skipped_title_mismatch" if kind == "title" else "skipped_unknown_or_ambiguous"] == 1


@pytest.mark.parametrize("bad_record", ["not-json", "missing-url", "conflicting-duplicate"])
def test_bad_archive_aborts_before_ddl_or_course_changes(runtime, bad_record):
    path, archive = runtime
    text = entry().model_dump_json() + "\n"
    if bad_record == "not-json":
        text += "not-json"
    elif bad_record == "missing-url":
        text += entry(catalog_url=None).model_dump_json()
    else:
        text += entry(description="Conflicting archive").model_dump_json()
    (archive / "cs.jsonl").write_text(text, encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        sync_sources(path, archive, commit=True)
    assert path.read_bytes() == before


def test_source_store_failure_rolls_back_schema_and_all_snapshots(runtime, monkeypatch):
    path, archive = runtime
    before = all_course_columns(path)
    def fail(*args):
        raise RuntimeError("Simulated source write failure")
    monkeypatch.setattr(CatalogSourceRepository, "store", fail)
    with pytest.raises(RuntimeError):
        sync_sources(path, archive, commit=True)
    conn = connect(path)
    assert CatalogSourceRepository(conn).available() is False
    assert conn.execute("SELECT 1 FROM schema_versions WHERE version='1.4'").fetchone() is None
    conn.close()
    assert all_course_columns(path) == before


def test_actual_cli_defaults_to_read_only_and_commits_explicitly(runtime):
    path, archive = runtime
    command = [sys.executable, str(ROOT / "scripts/sync_catalog_sources.py"), "--db-path", str(path), "--catalog-dir", str(archive)]
    dry = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert json.loads(dry.stdout)["committed"] is False
    actual = subprocess.run([*command, "--commit"], capture_output=True, text=True, timeout=30)
    assert actual.returncode == 0, actual.stdout + actual.stderr
    assert json.loads(actual.stdout)["stored"] == 1


def test_missing_database_is_not_created(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        sync_sources(missing, tmp_path)
    assert not missing.exists()


def test_sync_checks_content_not_only_id_before_declaring_unchanged(runtime):
    path, archive = runtime
    sync_sources(path, archive, commit=True)
    conn = connect(path)
    data = json.loads(conn.execute("SELECT snapshot FROM course_catalog_sources").fetchone()[0])
    data["description"] = "Accidentally edited without changing the ID"
    conn.execute("UPDATE course_catalog_sources SET snapshot=?", (json.dumps(data),))
    conn.commit()
    conn.close()
    report = sync_sources(path, archive, commit=True)
    assert report["stored"] == 1 and report["unchanged"] == 0
    conn = connect(path)
    assert json.loads(conn.execute("SELECT snapshot FROM course_catalog_sources").fetchone()[0])["description"] == entry().description
    conn.close()
