"""Tests for scripts/seed_aai6600.py — schema regression guard + integration."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.seed_aai6600 import (  # noqa: E402
    COURSE_ID,
    MANUAL_ALIASES,
    build_course,
    main,
)
from schemas.course import DeliveryMode  # noqa: E402


# === Pure: build_course() validates against schema ===

def test_build_course_validates() -> None:
    """Schema regression guard. If schemas/course.py adds a constraint that
    breaks AAI 6600, this test fails immediately rather than during a real run.
    """
    c = build_course()

    assert c.course_id == COURSE_ID
    assert c.primary_code == "AAI 6600"
    assert c.primary_name == "Applied Artificial Intelligence"
    assert c.term == "Spring 2026"
    assert c.credits == 3
    assert c.delivery_mode == DeliveryMode.HYBRID
    assert "Dr. Hema Seshadri" in c.professor
    assert c.prereqs == []


def test_build_course_soft_fields_have_evidence() -> None:
    """Every soft-field-with-value should have at least one evidence_snippet —
    Course.model_validator enforces this; passing build_course() means we did.
    """
    c = build_course()
    evidence_fields = {ev.field for ev in c.evidence_snippets}
    assert "skill_tags" in evidence_fields
    assert "career_relevance" in evidence_fields
    # v1.1: AI policy moved to structured ai_policy field, controversial_signals
    # is empty for AAI 6600 (no syllabus-derivable course-quality red flags).


def test_build_course_workload_unset() -> None:
    """workload_hours / difficulty_score require RMP data, must not be guessed."""
    c = build_course()
    assert c.workload_hours_per_week is None
    assert c.difficulty_score is None


# === v1.1 fields populated from syllabus ===

def test_build_course_instructor_contact() -> None:
    c = build_course()
    assert c.instructor_contact is not None
    assert c.instructor_contact.name == "Dr. Hema Seshadri"
    assert c.instructor_contact.email == "h.seshadri@northeastern.edu"
    assert c.instructor_contact.secondary_contact is not None
    assert "John Wilder" in c.instructor_contact.secondary_contact


def test_build_course_textbooks() -> None:
    c = build_course()
    titles = [t.title for t in c.textbooks]
    assert any("Analytics for Business Success" in t for t in titles)
    # Required textbook should be marked as such
    required = [t for t in c.textbooks if t.is_required]
    assert len(required) >= 1
    # Russell & Norvig is optional
    rn = [t for t in c.textbooks if "Modern Approach" in t.title]
    assert len(rn) == 1
    assert rn[0].is_required is False


def test_build_course_meeting_schedule() -> None:
    from datetime import date as _date, time as _time
    from schemas.course import DayOfWeek as _DOW

    c = build_course()
    assert c.meeting_schedule is not None
    assert len(c.meeting_schedule.slots) == 1
    slot = c.meeting_schedule.slots[0]
    assert slot.day_of_week == _DOW.TUESDAY
    assert slot.start_time == _time(17, 50)
    assert slot.end_time == _time(19, 10)
    assert slot.location == "Snell Library 119"
    assert c.meeting_schedule.start_date == _date(2026, 1, 7)
    assert c.meeting_schedule.end_date == _date(2026, 4, 26)


def test_build_course_ai_policy() -> None:
    c = build_course()
    assert c.ai_policy is not None
    permitted = c.ai_policy.permitted_tools
    assert any("Copilot" in t for t in permitted)
    assert any("Claude" in t for t in permitted)
    assert c.ai_policy.disclosure_required is True
    assert c.ai_policy.notes is not None
    assert "OSCCR" in c.ai_policy.notes


def test_build_course_grading_components_weight_optional() -> None:
    """v1.1: weight=None is now valid — syllabus did not publish weights."""
    c = build_course()
    assert len(c.grading_components) >= 1
    # All components in this seed have weight=None (intentional)
    assert all(g.weight is None for g in c.grading_components)


def test_build_course_schema_version_is_current() -> None:
    from schemas.course import SCHEMA_VERSION

    c = build_course()
    assert c.schema_version == SCHEMA_VERSION  # i.e. "1.1"


# === Integration: full main() against tmp DB ===

@pytest.fixture
def tmp_run(tmp_path: Path) -> tuple[Path, Path]:
    """Run main() against a tmp DB + tmp output dir; return paths."""
    db_path = tmp_path / "seed.db"
    output_dir = tmp_path / "ground_truth"
    rc = main(db_path=str(db_path), output_dir=output_dir)
    assert rc == 0
    return db_path, output_dir


def test_seed_writes_json_dump(tmp_run: tuple[Path, Path]) -> None:
    _, output_dir = tmp_run
    json_path = output_dir / "aai_6600.json"
    assert json_path.exists()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["primary_code"] == "AAI 6600"
    assert data["course_id"] == COURSE_ID


def test_seed_persists_to_db(tmp_run: tuple[Path, Path]) -> None:
    db_path, _ = tmp_run

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT primary_code, status FROM courses WHERE course_id = ?",
            (COURSE_ID,),
        ).fetchone()
        assert row is not None
        assert row["primary_code"] == "AAI 6600"
        assert row["status"] == "pending"  # ADR-0013: fresh insert is always pending
    finally:
        conn.close()


def test_seed_loads_all_aliases(tmp_run: tuple[Path, Path]) -> None:
    db_path, _ = tmp_run

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT alias_text, alias_type FROM course_aliases WHERE primary_course_id = ?",
            (COURSE_ID,),
        ).fetchall()
        loaded = {(r["alias_text"], r["alias_type"]) for r in rows}
        assert loaded == set(MANUAL_ALIASES)
    finally:
        conn.close()


def test_seed_v_course_lookup_returns_primary_plus_aliases(
    tmp_run: tuple[Path, Path],
) -> None:
    """The whole point of the alias system: '应用 AI' should resolve to AAI 6600."""
    db_path, _ = tmp_run

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT searchable_term, alias_type FROM v_course_lookup "
            "WHERE course_id = ?",
            (COURSE_ID,),
        ).fetchall()
        terms = {r["searchable_term"] for r in rows}

        assert "AAI 6600" in terms       # primary
        assert "Applied AI" in terms      # English slang
        assert "6600" in terms            # number-only slang
        assert "应用 AI" in terms         # Chinese slang
        assert "Hema's AI class" in terms  # professor attribution

        # Every alias should be approved (non-pending)
        for r in rows:
            assert r["alias_type"] != "pending"
    finally:
        conn.close()


def test_seed_idempotent(tmp_path: Path) -> None:
    """Running the seed twice yields the same final state — no duplicate rows."""
    db_path = tmp_path / "seed.db"
    output_dir = tmp_path / "ground_truth"

    main(db_path=str(db_path), output_dir=output_dir)
    main(db_path=str(db_path), output_dir=output_dir)  # second run

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        course_count = conn.execute(
            "SELECT COUNT(*) AS n FROM courses WHERE course_id = ?", (COURSE_ID,),
        ).fetchone()["n"]
        alias_count = conn.execute(
            "SELECT COUNT(*) AS n FROM course_aliases WHERE primary_course_id = ?",
            (COURSE_ID,),
        ).fetchone()["n"]

        assert course_count == 1
        assert alias_count == len(MANUAL_ALIASES)
    finally:
        conn.close()
