"""scripts/repair_course_names.py: read-only report by default; --commit repairs only names that are a
sentence of the course's own description, keeps raw_text, and leaves the course pending for re-index.

中文：scripts/repair_course_names.py：默认只读；--commit 只修「名称是这门课自己描述里的一句话」的记录，
保留 raw_text，并把课程留成 pending 等重新索引。
"""

from __future__ import annotations

import json

import pytest

from db.connection import connect
from db.repository import CourseRepository
from schemas.course import Course
from scrapers.neu_catalog import CatalogEntry
from scripts.init_db import init_database
from scripts.repair_course_names import cli, is_description_sentence, repair_names
from scripts.sync_catalog_sources import sync_sources

URL = "https://catalog.northeastern.edu/course-descriptions/cs/"
SENTENCE = "Introduces relational database management systems as a class of software systems."
DESCRIPTION = SENTENCE + " Prepares students to be sophisticated users of database management systems."


def entry(code, name, description=DESCRIPTION):
    return CatalogEntry(course_code=code, course_name=name, description=description, credits=4, catalog_url=URL)


@pytest.fixture()
def runtime(tmp_path):
    path = tmp_path / "runtime.db"
    init_database(path)
    conn = connect(path)
    repo = CourseRepository(conn)
    repo.insert(Course(course_id="neu-cs-5200", primary_code="CS 5200", primary_name=SENTENCE, credits=4),
                raw_text=DESCRIPTION)
    repo.insert(Course(course_id="neu-cs-5800", primary_code="CS 5800", primary_name="Algorithms", credits=4),
                raw_text="Graph algorithms.")
    repo.insert(Course(course_id="neu-cs-6140", primary_code="CS 6140", primary_name="Machine Learning (old title)",
                       credits=4), raw_text="Learning.")
    for course_id in ("neu-cs-5200", "neu-cs-5800", "neu-cs-6140"):
        repo.mark_indexed(course_id)
    conn.commit()
    conn.close()
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "cs.jsonl").write_text("\n".join(item.model_dump_json() for item in (
        entry("CS 5200", "Database Management Systems"), entry("CS 5800", "Algorithms", "Graph algorithms."),
        entry("CS 6140", "Machine Learning", "Learning."), entry("CS 9999", "Not In This Database", "x"),
    )) + "\n", encoding="utf-8")
    return path, archive


def rows(path):
    conn = connect(path)
    try:
        return {row["course_id"]: dict(row) for row in conn.execute(
            "SELECT course_id, primary_name, raw_text, status, indexed_at, metadata, generated_json FROM courses")}
    finally:
        conn.close()


def test_report_is_read_only_and_separates_repairs_from_other_mismatches(runtime):
    path, archive = runtime
    before = rows(path)
    report = repair_names(path, archive)
    assert report["committed"] is False and report["repaired"] == 0 and rows(path) == before
    assert [item["code"] for item in report["repairs"]] == ["CS 5200"]
    assert report["repairs"][0]["catalog"] == "Database Management Systems"
    assert [item["code"] for item in report["other_mismatches"]] == ["CS 6140"]  # A rename: listed, not changed.
    assert report["matched"] == 1 and report["skipped_unknown_or_ambiguous"] == 1


def test_commit_repairs_name_column_and_json_and_keeps_text_and_index_state(runtime):
    """Neither index reads the name, so the course stays 'indexed' (a 'pending' course would drop
    out of search until a re-embed it does not need) and its raw_text is untouched."""
    path, archive = runtime
    before = rows(path)
    report = repair_names(path, archive, commit=True)
    after = rows(path)
    assert report["repaired"] == 1
    fixed, old = after["neu-cs-5200"], before["neu-cs-5200"]
    assert fixed["primary_name"] == "Database Management Systems"
    assert json.loads(fixed["generated_json"]) == {**json.loads(old["generated_json"]),
                                                   "primary_name": "Database Management Systems"}
    assert (fixed["raw_text"], fixed["status"], fixed["indexed_at"], fixed["metadata"]) == (
        old["raw_text"], "indexed", old["indexed_at"], old["metadata"])
    assert after["neu-cs-5800"] == before["neu-cs-5800"] and after["neu-cs-6140"] == before["neu-cs-6140"]
    assert repair_names(path, archive, commit=True)["repaired"] == 0  # Idempotent.


def test_after_the_repair_the_catalog_snapshot_can_attach(runtime):
    """The point of the repair: sync_catalog_sources skipped CS 5200 as a title mismatch."""
    path, archive = runtime
    assert sync_sources(path, archive)["skipped_title_mismatch"] == 2  # CS 5200 and the renamed CS 6140.
    repair_names(path, archive, commit=True)
    assert sync_sources(path, archive)["skipped_title_mismatch"] == 1


@pytest.mark.parametrize("name,texts,expected", [
    (SENTENCE, [DESCRIPTION], True),
    (SENTENCE, ["Something else entirely."], False),  # Not from its own description.
    ("Graph algorithms.", ["Graph algorithms. Dynamic programming."], False),  # Too short for a sentence.
    ("Database Management Systems", [DESCRIPTION], False),  # No sentence ending.
    ("Introduces relational database management systems", [DESCRIPTION], False),  # In it, but not a sentence.
    ("  Introduces   relational database management systems as a class of software systems. ", [DESCRIPTION], True),
])
def test_only_a_sentence_from_the_course_own_description_counts(name, texts, expected):
    assert is_description_sentence(name, texts) is expected


def test_conflicting_archive_titles_abort_before_any_change(runtime):
    path, archive = runtime
    (archive / "cs2.jsonl").write_text(entry("CS 5800", "Algorithms II").model_dump_json() + "\n", encoding="utf-8")
    before = rows(path)
    with pytest.raises(ValueError, match="Conflicting archived titles"):
        repair_names(path, archive, commit=True)
    assert rows(path) == before


def test_cli_defaults_to_read_only_and_fails_closed(runtime, tmp_path, capsys):
    path, archive = runtime
    assert cli(["--db-path", str(path), "--catalog-dir", str(archive)]) == 0
    assert json.loads(capsys.readouterr().out)["committed"] is False
    assert rows(path)["neu-cs-5200"]["primary_name"] == SENTENCE
    assert cli(["--db-path", str(tmp_path / "missing.db"), "--catalog-dir", str(archive)]) == 1
    assert not (tmp_path / "missing.db").exists()  # A typo never creates an empty database.


def test_a_sentence_found_only_in_the_stored_raw_text_also_counts(runtime):
    """Archived descriptions can be missing or newer; the stored raw_text is the text the bad name
    was copied from."""
    path, archive = runtime
    (archive / "cs.jsonl").write_text("\n".join(item.model_dump_json() for item in (
        entry("CS 5200", "Database Management Systems", "A rewritten archived description."),
        entry("CS 5800", "Algorithms", "Graph algorithms."), entry("CS 6140", "Machine Learning", "Learning."),
    )) + "\n", encoding="utf-8")
    assert [item["code"] for item in repair_names(path, archive)["repairs"]] == ["CS 5200"]
