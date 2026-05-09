"""Tests for db.program_repository — Layer 3 of the v3.0 RAG plan.

Covers: program CRUD, prefix lookup, semester-filtered required-course list,
prerequisite edges, FK behavior, and idempotent upserts (so seed scripts
can re-run safely).
"""

from __future__ import annotations

import sqlite3

import pytest

from db.program_repository import ProgramNotFound, ProgramRepository
from db.repository import CourseRepository
from schemas.course import Course
from schemas.program import CoursePrerequisite, Program, ProgramRequiredCourse


# === Fixtures ===


@pytest.fixture
def seeded_db(empty_db: sqlite3.Connection) -> sqlite3.Connection:
    """A few AAI courses to satisfy the FK on program_required_courses."""
    repo = CourseRepository(empty_db)
    for cid, code, name in [
        ("c-aai-5015", "AAI 5015", "Math Concepts"),
        ("c-aai-5025", "AAI 5025", "Python"),
        ("c-aai-6600", "AAI 6600", "Intro to AI"),
        ("c-aai-6610", "AAI 6610", "Applied ML"),
        ("c-aai-6640", "AAI 6640", "Applied Deep Learning"),
        ("c-aai-6980", "AAI 6980", "Capstone"),
    ]:
        repo.insert(Course(course_id=cid, primary_code=code, primary_name=name))
        repo.mark_indexed(cid)
    return empty_db


@pytest.fixture
def program_repo(seeded_db: sqlite3.Connection) -> ProgramRepository:
    return ProgramRepository(seeded_db)


def _aai_program() -> Program:
    return Program(
        program_id="aai-ms",
        full_name="MPS Applied AI",
        prefix="AAI",
        department="Applied AI",
        college="College of Professional Studies",
    )


# === Programs CRUD ===


def test_add_and_get_program(program_repo: ProgramRepository) -> None:
    program_repo.add_program(_aai_program())
    out = program_repo.get_program("aai-ms")
    assert out.prefix == "AAI"
    assert out.full_name == "MPS Applied AI"


def test_get_program_raises_when_missing(program_repo: ProgramRepository) -> None:
    with pytest.raises(ProgramNotFound):
        program_repo.get_program("does-not-exist")


def test_find_by_prefix_returns_program(program_repo: ProgramRepository) -> None:
    program_repo.add_program(_aai_program())
    found = program_repo.find_by_prefix("AAI")
    assert found is not None
    assert found.program_id == "aai-ms"


def test_find_by_prefix_is_case_insensitive(program_repo: ProgramRepository) -> None:
    """The prefix column has COLLATE NOCASE so 'aai' / 'AAI' / 'Aai' all match.
    User-facing extractor uppercases anyway, but the repo shouldn't depend
    on that contract."""
    program_repo.add_program(_aai_program())
    assert program_repo.find_by_prefix("aai") is not None
    assert program_repo.find_by_prefix("Aai") is not None


def test_find_by_prefix_returns_none_when_no_match(
    program_repo: ProgramRepository,
) -> None:
    """No program seeded for prefix 'XYZ' → None, not exception. Caller
    should fall back to plain prefix-filtered retrieval (Layer 2)."""
    assert program_repo.find_by_prefix("XYZ") is None


def test_upsert_program_is_idempotent(program_repo: ProgramRepository) -> None:
    """Seed scripts must be safely re-runnable."""
    program_repo.upsert_program(_aai_program())
    program_repo.upsert_program(_aai_program())  # second run, no error
    assert program_repo.get_program("aai-ms").prefix == "AAI"


def test_upsert_program_overwrites_changed_fields(
    program_repo: ProgramRepository,
) -> None:
    program_repo.upsert_program(_aai_program())
    revised = _aai_program().model_copy(update={"full_name": "Revised AAI MS"})
    program_repo.upsert_program(revised)
    assert program_repo.get_program("aai-ms").full_name == "Revised AAI MS"


def test_list_programs_returns_all(program_repo: ProgramRepository) -> None:
    program_repo.add_program(_aai_program())
    program_repo.add_program(Program(
        program_id="cs-ms", full_name="CS MS", prefix="CS",
    ))
    out = program_repo.list_programs()
    assert {p.program_id for p in out} == {"aai-ms", "cs-ms"}


# === Required courses ===


def test_add_and_list_required_courses(program_repo: ProgramRepository) -> None:
    program_repo.add_program(_aai_program())
    program_repo.add_required_course(ProgramRequiredCourse(
        program_id="aai-ms", course_id="c-aai-5015",
        requirement_type="foundation", semester_recommended=1,
    ))
    program_repo.add_required_course(ProgramRequiredCourse(
        program_id="aai-ms", course_id="c-aai-6600",
        requirement_type="core", semester_recommended=1,
    ))
    program_repo.add_required_course(ProgramRequiredCourse(
        program_id="aai-ms", course_id="c-aai-6610",
        requirement_type="core", semester_recommended=2,
    ))

    s1 = program_repo.list_required_courses("aai-ms", semester=1)
    assert {e.course_id for e in s1} == {"c-aai-5015", "c-aai-6600"}

    s2 = program_repo.list_required_courses("aai-ms", semester=2)
    assert {e.course_id for e in s2} == {"c-aai-6610"}


def test_list_required_courses_filter_by_requirement_type(
    program_repo: ProgramRepository,
) -> None:
    program_repo.add_program(_aai_program())
    program_repo.add_required_course(ProgramRequiredCourse(
        program_id="aai-ms", course_id="c-aai-5015",
        requirement_type="foundation",
    ))
    program_repo.add_required_course(ProgramRequiredCourse(
        program_id="aai-ms", course_id="c-aai-6980",
        requirement_type="capstone",
    ))
    foundations = program_repo.list_required_courses(
        "aai-ms", requirement_type="foundation",
    )
    assert [e.course_id for e in foundations] == ["c-aai-5015"]


def test_required_course_fk_to_courses_enforced(
    program_repo: ProgramRepository,
) -> None:
    program_repo.add_program(_aai_program())
    with pytest.raises(sqlite3.IntegrityError):
        program_repo.add_required_course(ProgramRequiredCourse(
            program_id="aai-ms", course_id="c-does-not-exist",
            requirement_type="core",
        ))


def test_required_course_fk_to_program_enforced(
    program_repo: ProgramRepository,
) -> None:
    """No program seeded → FK violation."""
    with pytest.raises(sqlite3.IntegrityError):
        program_repo.add_required_course(ProgramRequiredCourse(
            program_id="ghost-ms", course_id="c-aai-5015",
            requirement_type="core",
        ))


def test_upsert_required_course_is_idempotent(
    program_repo: ProgramRepository,
) -> None:
    program_repo.add_program(_aai_program())
    edge = ProgramRequiredCourse(
        program_id="aai-ms", course_id="c-aai-5015",
        requirement_type="foundation", semester_recommended=1,
    )
    program_repo.upsert_required_course(edge)
    program_repo.upsert_required_course(
        edge.model_copy(update={"semester_recommended": 2}),
    )
    out = program_repo.list_required_courses("aai-ms")
    assert len(out) == 1
    assert out[0].semester_recommended == 2


# === Prerequisites ===


def test_add_and_list_prerequisites(program_repo: ProgramRepository) -> None:
    program_repo.add_prerequisite(CoursePrerequisite(
        course_id="c-aai-6610",
        prereq_course_id="c-aai-5015",
        requirement="required",
    ))
    program_repo.add_prerequisite(CoursePrerequisite(
        course_id="c-aai-6610",
        prereq_course_id="c-aai-6600",
        requirement="required",
    ))
    out = program_repo.list_prerequisites("c-aai-6610")
    assert {p.prereq_course_id for p in out} == {"c-aai-5015", "c-aai-6600"}


def test_self_prerequisite_blocked(program_repo: ProgramRepository) -> None:
    """init.sql CHECK constraint: course_id <> prereq_course_id."""
    with pytest.raises(sqlite3.IntegrityError):
        program_repo.add_prerequisite(CoursePrerequisite(
            course_id="c-aai-6610",
            prereq_course_id="c-aai-6610",
        ))


def test_upsert_prerequisite_is_idempotent(program_repo: ProgramRepository) -> None:
    edge = CoursePrerequisite(
        course_id="c-aai-6610",
        prereq_course_id="c-aai-5015",
        requirement="required",
    )
    program_repo.upsert_prerequisite(edge)
    program_repo.upsert_prerequisite(
        edge.model_copy(update={"requirement": "recommended"}),
    )
    out = program_repo.list_prerequisites("c-aai-6610")
    assert len(out) == 1
    assert out[0].requirement == "recommended"


def test_program_cascade_delete_required_courses(
    program_repo: ProgramRepository, seeded_db: sqlite3.Connection,
) -> None:
    """Dropping a program removes its program_required_courses rows
    (FK ON DELETE CASCADE). Prerequisites table is course-bound, NOT
    program-bound, so it isn't affected."""
    program_repo.add_program(_aai_program())
    program_repo.add_required_course(ProgramRequiredCourse(
        program_id="aai-ms", course_id="c-aai-5015",
        requirement_type="foundation",
    ))
    seeded_db.execute("DELETE FROM programs WHERE program_id = ?", ("aai-ms",))
    seeded_db.commit()
    assert program_repo.list_required_courses("aai-ms") == []
