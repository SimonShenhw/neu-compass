"""scripts/repair_course_names.py: read-only report by default; --commit repairs only names that are a
sentence of the course's own description, keeps raw_text, and keeps the status (no index reads the
name, and a 'pending' course would drop out of search).

中文：scripts/repair_course_names.py：默认只读；--commit 只修「名称是这门课自己描述里的一句话」的记录，
保留 raw_text，status 保持不变（两个索引都不读名称；设成 pending 反而会让课程从搜索里消失）。
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
    # Other sentence endings count too.
    ("这门课介绍关系型数据库管理系统，以及它们作为一类软件系统的设计和使用方法。",
     ["这门课介绍关系型数据库管理系统，以及它们作为一类软件系统的设计和使用方法。之后讲查询优化。"], True),
    ("Why do relational database systems matter for software design?",
     ["Why do relational database systems matter for software design? This course answers it."], True),
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


def test_cli_names_the_code_with_conflicting_archived_titles(runtime, capsys):
    path, archive = runtime
    (archive / "cs2.jsonl").write_text(entry("CS 5800", "Algorithms II").model_dump_json() + "\n", encoding="utf-8")
    assert cli(["--db-path", str(path), "--catalog-dir", str(archive)]) == 1
    assert "Conflicting archived titles for CS 5800" in capsys.readouterr().out


def test_cli_defaults_to_read_only_and_fails_closed(runtime, tmp_path, capsys):
    path, archive = runtime
    assert cli(["--db-path", str(path), "--catalog-dir", str(archive)]) == 0
    assert json.loads(capsys.readouterr().out)["committed"] is False
    assert rows(path)["neu-cs-5200"]["primary_name"] == SENTENCE
    assert cli(["--db-path", str(tmp_path / "missing.db"), "--catalog-dir", str(archive)]) == 1
    assert not (tmp_path / "missing.db").exists()  # A typo never creates an empty database.


def test_cli_reports_a_vanished_course_as_a_failure_without_committing(runtime, monkeypatch, capsys):
    from db.repository import CourseNotFound  # noqa: PLC0415

    path, archive = runtime
    before = rows(path)

    def vanished(self, course_id, name):
        raise CourseNotFound(course_id)

    monkeypatch.setattr(CourseRepository, "rename", vanished)
    assert cli(["--db-path", str(path), "--catalog-dir", str(archive), "--commit"]) == 1
    assert "no transaction committed" in capsys.readouterr().out and rows(path) == before


def test_cli_lets_other_lookup_errors_surface_as_bugs(runtime, monkeypatch):
    """Only CourseNotFound is an expected failure; another KeyError is a bug and keeps its traceback.
    The transaction still rolls back. 中文：只有 CourseNotFound 是预期的失败；别的 KeyError 是 bug，
    保留 traceback；事务照样回滚。"""
    path, archive = runtime
    before = rows(path)
    rename = CourseRepository.rename

    def buggy(self, course_id, name):
        rename(self, course_id, name)  # The write happens, so the rollback is really tested.
        raise KeyError("primary_name")

    monkeypatch.setattr(CourseRepository, "rename", buggy)
    with pytest.raises(KeyError):
        cli(["--db-path", str(path), "--catalog-dir", str(archive), "--commit"])
    assert rows(path) == before


def test_a_sentence_found_only_in_the_stored_raw_text_also_counts(runtime):
    """Archived descriptions can be missing or newer; the stored raw_text is the text the bad name
    was copied from."""
    path, archive = runtime
    (archive / "cs.jsonl").write_text("\n".join(item.model_dump_json() for item in (
        entry("CS 5200", "Database Management Systems", "A rewritten archived description."),
        entry("CS 5800", "Algorithms", "Graph algorithms."), entry("CS 6140", "Machine Learning", "Learning."),
    )) + "\n", encoding="utf-8")
    assert [item["code"] for item in repair_names(path, archive)["repairs"]] == ["CS 5200"]


def test_a_named_mismatch_takes_the_catalog_title(runtime):
    """--use-catalog-title is for a rename a person decided (AAI 6600 in production; CS 6140 here).
    中文：--use-catalog-title 用于由人决定的改名（生产上是 AAI 6600，这里用 CS 6140）。"""
    path, archive = runtime
    before = rows(path)
    report = repair_names(path, archive, use_catalog_title=["CS 6140"])
    assert rows(path) == before and report["repaired"] == 0
    assert [item["code"] for item in report["named_repairs"]] == ["CS 6140"]
    assert report["named_repairs"][0]["catalog"] == "Machine Learning"
    assert [item["code"] for item in report["repairs"]] == ["CS 5200"] and report["other_mismatches"] == []

    report = repair_names(path, archive, commit=True, use_catalog_title=["CS 6140"])
    after = rows(path)
    assert report["repaired"] == 2
    fixed, old = after["neu-cs-6140"], before["neu-cs-6140"]
    assert fixed["primary_name"] == "Machine Learning"
    assert json.loads(fixed["generated_json"]) == {**json.loads(old["generated_json"]),
                                                   "primary_name": "Machine Learning"}
    assert (fixed["raw_text"], fixed["status"], fixed["indexed_at"], fixed["metadata"]) == (
        old["raw_text"], "indexed", old["indexed_at"], old["metadata"])
    again = repair_names(path, archive, commit=True, use_catalog_title=["CS 6140"])
    assert again["repaired"] == 0 and again["matched"] == 3  # Re-running changes nothing.
    assert sync_sources(path, archive)["skipped_title_mismatch"] == 0  # Both snapshots can attach now.


@pytest.mark.parametrize("code", ["CS6140", "CS 7777"])
def test_a_named_code_not_in_the_archive_fails_before_the_database_is_opened(runtime, tmp_path, code):
    path, archive = runtime
    # A missing database would raise FileNotFoundError if it were opened first.
    with pytest.raises(ValueError, match="not in the archive"):
        repair_names(tmp_path / "missing.db", archive, commit=True, use_catalog_title=[code])


@pytest.mark.parametrize("commit", [True, False])
def test_a_named_code_without_exactly_one_course_writes_nothing(runtime, commit):
    path, archive = runtime  # CS 9999 is archived but not in this database.
    before = rows(path)
    with pytest.raises(ValueError, match="CS 9999: 0 courses"):
        repair_names(path, archive, commit=commit, use_catalog_title=["CS 9999"])
    assert rows(path) == before  # Not even the CS 5200 repair.


def test_a_named_code_with_two_courses_writes_nothing(runtime):
    """The schema allows a repeated primary_code; a named rename then has no single target."""
    path, archive = runtime
    conn = connect(path)
    CourseRepository(conn).insert(Course(course_id="neu-cs-6140-copy", primary_code="CS 6140",
                                         primary_name="Machine Learning (old title)", credits=4), raw_text="Learning.")
    conn.commit()
    conn.close()
    before = rows(path)
    with pytest.raises(ValueError, match="CS 6140: 2 courses"):
        repair_names(path, archive, commit=True, use_catalog_title=["CS 6140"])
    assert rows(path) == before


def test_a_named_code_that_is_also_a_sentence_is_one_repair(runtime):
    path, archive = runtime
    report = repair_names(path, archive, commit=True, use_catalog_title=["CS 5200", "CS 5200"])
    assert [item["code"] for item in report["repairs"]] == ["CS 5200"] and report["named_repairs"] == []
    assert report["repaired"] == 1 and rows(path)["neu-cs-5200"]["primary_name"] == "Database Management Systems"


def test_every_unknown_named_code_is_listed_with_its_spelling(runtime):
    path, archive = runtime
    with pytest.raises(ValueError) as info:
        repair_names(path, archive, use_catalog_title=["CS 6140 ", "cs 6140", "CS 7777"])
    assert str(info.value) == "--use-catalog-title codes not in the archive: 'CS 6140 ', 'CS 7777', 'cs 6140'"


def test_cli_reports_an_empty_archive_by_name(runtime, tmp_path, capsys):
    path, _ = runtime
    empty = tmp_path / "empty-archive"
    empty.mkdir()
    assert cli(["--db-path", str(path), "--catalog-dir", str(empty)]) == 1
    assert "No JSONL catalog archives found" in capsys.readouterr().out


def test_cli_takes_repeated_catalog_title_codes(runtime, capsys):
    path, archive = runtime
    base = ["--db-path", str(path), "--catalog-dir", str(archive), "--commit"]
    assert cli([*base, "--use-catalog-title", "CS 6140", "--use-catalog-title", "CS 5800"]) == 0
    report = json.loads(capsys.readouterr().out)
    # CS 5800 already matches: counted as matched, nothing to rename.
    assert report["repaired"] == 2 and [item["code"] for item in report["named_repairs"]] == ["CS 6140"]
    assert rows(path)["neu-cs-6140"]["primary_name"] == "Machine Learning"
    assert cli([*base, "--use-catalog-title", "CS 7777"]) == 1
    # The script's own failures name the code, so a misspelt one is easy to tell from a duplicate.
    assert capsys.readouterr().out.strip() == (
        "Course name repair failed: --use-catalog-title codes not in the archive: 'CS 7777'; no transaction committed.")
    assert cli([*base, "--use-catalog-title", "CS 9999"]) == 1
    assert "--use-catalog-title CS 9999: 0 courses in the database, need exactly one" in capsys.readouterr().out
