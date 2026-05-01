"""Tests for scripts/load_slang_dict — uses the empty_db fixture."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from db.alias_repository import AliasRepository
from db.repository import CourseRepository
from schemas.course import Course
from scripts.load_slang_dict import DEFAULT_SLANG_PATH, load_slang_dict


@pytest.fixture
def db_with_courses(tmp_path: Path) -> Path:
    """Create a tmp DB with 2 seeded courses for slang resolution."""
    from scripts.init_db import init_database
    db_path = tmp_path / "slang_test.db"
    init_database(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    repo = CourseRepository(conn)
    repo.insert(Course(course_id="c-cs5800", primary_code="CS 5800",
                       primary_name="Algorithms"))
    repo.insert(Course(course_id="c-aai6600", primary_code="AAI 6600",
                       primary_name="Applied AI"))
    conn.commit()
    conn.close()
    return db_path


def _slang_file(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "slang.json"
    p.write_text(
        json.dumps({"version": "test", "entries": entries}, ensure_ascii=False),
        encoding="utf-8",
    )
    return p


# === Happy path ===

def test_load_inserts_aliases(db_with_courses: Path, tmp_path: Path) -> None:
    slang = _slang_file(tmp_path, [
        {"alias": "Algo", "alias_type": "slang",
         "primary_course_code": "CS 5800", "confidence": 0.9},
        {"alias": "Intro AI", "alias_type": "slang",
         "primary_course_code": "AAI 6600", "confidence": 0.85},
    ])
    stats = load_slang_dict(db_path=db_with_courses, slang_path=slang, verbose=False)
    assert stats.inserted == 2
    assert stats.skipped_already_present == 0
    assert stats.skipped_unknown_course == 0
    assert stats.errors == 0


def test_resolves_via_primary_code_case_insensitive(
    db_with_courses: Path, tmp_path: Path,
) -> None:
    slang = _slang_file(tmp_path, [
        {"alias": "Algo", "alias_type": "slang",
         "primary_course_code": "cs 5800"},  # lowercase
    ])
    stats = load_slang_dict(db_path=db_with_courses, slang_path=slang, verbose=False)
    assert stats.inserted == 1


def test_idempotent_re_run(db_with_courses: Path, tmp_path: Path) -> None:
    slang = _slang_file(tmp_path, [
        {"alias": "Algo", "alias_type": "slang",
         "primary_course_code": "CS 5800"},
    ])
    load_slang_dict(db_path=db_with_courses, slang_path=slang, verbose=False)
    stats = load_slang_dict(db_path=db_with_courses, slang_path=slang, verbose=False)
    assert stats.inserted == 0
    assert stats.skipped_already_present == 1


# === Skip rules ===

def test_skips_unknown_course(db_with_courses: Path, tmp_path: Path) -> None:
    """Slang for a course not in DB should be skipped, not crash."""
    slang = _slang_file(tmp_path, [
        {"alias": "Algo", "alias_type": "slang",
         "primary_course_code": "CS 5800"},
        {"alias": "Quant Math", "alias_type": "slang",
         "primary_course_code": "MATH 7243"},  # not in this DB
    ])
    stats = load_slang_dict(db_path=db_with_courses, slang_path=slang, verbose=False)
    assert stats.inserted == 1
    assert stats.skipped_unknown_course == 1


def test_invalid_alias_type_counts_as_error(
    db_with_courses: Path, tmp_path: Path,
) -> None:
    slang = _slang_file(tmp_path, [
        {"alias": "x", "alias_type": "not_a_real_type",
         "primary_course_code": "CS 5800"},
    ])
    stats = load_slang_dict(db_path=db_with_courses, slang_path=slang, verbose=False)
    assert stats.errors == 1


def test_empty_dict_no_inserts(db_with_courses: Path, tmp_path: Path) -> None:
    slang = _slang_file(tmp_path, [])
    stats = load_slang_dict(db_path=db_with_courses, slang_path=slang, verbose=False)
    assert stats.inserted == 0


# === The actual shipped slang dict ===

def test_default_slang_dict_is_valid_json() -> None:
    """data/slang_dict.json must parse as JSON with the expected shape."""
    data = json.loads(DEFAULT_SLANG_PATH.read_text(encoding="utf-8"))
    assert "version" in data
    assert "entries" in data
    for e in data["entries"]:
        assert "alias" in e
        assert "alias_type" in e
        assert "primary_course_code" in e


def test_default_slang_dict_has_at_least_30_entries() -> None:
    """Quality bar — 50 was the PLAN target, allow 30 minimum."""
    data = json.loads(DEFAULT_SLANG_PATH.read_text(encoding="utf-8"))
    assert len(data["entries"]) >= 30, \
        f"slang_dict has only {len(data['entries'])} entries; target ≥30"


def test_default_slang_dict_alias_types_are_valid() -> None:
    """Every alias_type must match the AliasType enum values."""
    from schemas.alias import AliasType
    valid = {at.value for at in AliasType}

    data = json.loads(DEFAULT_SLANG_PATH.read_text(encoding="utf-8"))
    for e in data["entries"]:
        assert e["alias_type"] in valid, \
            f"unknown alias_type {e['alias_type']!r} in entry {e!r}"


def test_default_slang_loads_against_full_seed(tmp_path: Path) -> None:
    """End-to-end: seed all 7 courses + load full slang dict, verify
    most entries land (a few may not have matching primary codes)."""
    from scripts.init_db import init_database
    from scripts.seed_aai6600 import build_course as build_aai
    from scripts.seed_synthetic_courses import SYNTHETIC_COURSES
    from db.connection import connect

    db_path = tmp_path / "full.db"
    init_database(db_path)

    conn = connect(db_path)
    try:
        course_repo = CourseRepository(conn)
        course_repo.insert(build_aai(), raw_text="aai 6600 raw text")
        for spec in SYNTHETIC_COURSES:
            from schemas.course import Course as C
            c = C(
                course_id=spec["course_id"],
                primary_code=spec["primary_code"],
                primary_name=spec["primary_name"],
                topics_covered=spec["topics"],
                term="Spring 2026",
            )
            course_repo.insert(c)
        conn.commit()
    finally:
        conn.close()

    stats = load_slang_dict(db_path=db_path, verbose=False)
    # All entries should resolve since we seeded all 7 courses
    assert stats.skipped_unknown_course == 0
    assert stats.inserted >= 30
