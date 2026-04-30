"""Tests for schemas.course (Day 2)."""

from typing import Any

import pytest
from pydantic import ValidationError

from schemas.course import (
    SCHEMA_VERSION,
    Course,
    DeliveryMode,
    EvidenceSnippet,
    GradingComponent,
    migrate,
)


def _minimal(**overrides: Any) -> Course:
    base: dict[str, Any] = {
        "course_id": "uuid-test-001",
        "primary_code": "CS 5800",
        "primary_name": "Algorithms",
    }
    base.update(overrides)
    return Course(**base)


def _evidence(field: str, **overrides: Any) -> EvidenceSnippet:
    base: dict[str, Any] = {
        "field": field,
        "value": "x",
        "source_id": "src_1",
        "quote": "test quote",
        "confidence": 0.8,
    }
    base.update(overrides)
    return EvidenceSnippet(**base)


# === Identity & defaults ===

def test_minimal_course_passes() -> None:
    c = _minimal()
    assert c.primary_code == "CS 5800"
    assert c.schema_version == SCHEMA_VERSION
    assert c.evidence_snippets == []


def test_schema_version_default_is_const() -> None:
    assert _minimal().schema_version == SCHEMA_VERSION


# === course_code normalization & validation ===

def test_course_code_normalizes_lowercase() -> None:
    assert _minimal(primary_code="cs5800").primary_code == "CS 5800"


def test_course_code_normalizes_no_space() -> None:
    assert _minimal(primary_code="AAI6600").primary_code == "AAI 6600"


def test_course_code_with_trailing_letter() -> None:
    assert _minimal(primary_code="DS 5230A").primary_code == "DS 5230A"


def test_course_code_invalid_raises() -> None:
    with pytest.raises(ValidationError):
        _minimal(primary_code="INVALID")
    with pytest.raises(ValidationError):
        _minimal(primary_code="CS")
    with pytest.raises(ValidationError):
        _minimal(primary_code="123 4567")


# === Hard field bounds ===

def test_credits_bounds() -> None:
    _minimal(credits=4)
    _minimal(credits=0)
    with pytest.raises(ValidationError):
        _minimal(credits=-1)
    with pytest.raises(ValidationError):
        _minimal(credits=15)


def test_delivery_mode_enum() -> None:
    c = _minimal(delivery_mode=DeliveryMode.HYBRID)
    assert c.delivery_mode == DeliveryMode.HYBRID
    with pytest.raises(ValidationError):
        _minimal(delivery_mode="bogus")


def test_no_empty_strings_in_lists() -> None:
    with pytest.raises(ValidationError):
        _minimal(professor=["Dr. Zhang", ""])
    with pytest.raises(ValidationError):
        _minimal(prereqs=["   "])


# === Soft field evidence requirement (PLAN §2.1) ===

def test_difficulty_without_evidence_raises() -> None:
    with pytest.raises(ValidationError, match="difficulty_score"):
        _minimal(difficulty_score=4.0)


def test_difficulty_with_evidence_passes() -> None:
    c = _minimal(
        difficulty_score=4.0,
        evidence_snippets=[_evidence("difficulty_score", value=4.0)],
    )
    assert c.difficulty_score == 4.0


def test_difficulty_score_bounds() -> None:
    ev = [_evidence("difficulty_score", value=3.0)]
    _minimal(difficulty_score=1.0, evidence_snippets=ev)
    _minimal(difficulty_score=5.0, evidence_snippets=ev)
    with pytest.raises(ValidationError):
        _minimal(difficulty_score=0.5, evidence_snippets=ev)
    with pytest.raises(ValidationError):
        _minimal(difficulty_score=5.5, evidence_snippets=ev)


def test_skill_tags_empty_no_evidence_needed() -> None:
    c = _minimal(skill_tags=[])
    assert c.skill_tags == []


def test_skill_tags_with_value_needs_evidence() -> None:
    with pytest.raises(ValidationError, match="skill_tags"):
        _minimal(skill_tags=["python"])


def test_skill_tags_with_evidence_passes() -> None:
    c = _minimal(
        skill_tags=["python", "ml"],
        evidence_snippets=[_evidence("skill_tags", value=["python", "ml"])],
    )
    assert c.skill_tags == ["python", "ml"]


def test_grading_components_no_evidence_required() -> None:
    """grading_components is structured (Syllabus source), not in the strict set."""
    c = _minimal(grading_components=[GradingComponent(name="midterm", weight=0.3)])
    assert len(c.grading_components) == 1


def test_topics_covered_no_evidence_required() -> None:
    c = _minimal(topics_covered=["dynamic programming", "graphs"])
    assert len(c.topics_covered) == 2


# === EvidenceSnippet validation ===

def test_evidence_confidence_bounds() -> None:
    EvidenceSnippet(field="x", value="y", source_id="z", quote="q", confidence=0.0)
    EvidenceSnippet(field="x", value="y", source_id="z", quote="q", confidence=1.0)
    with pytest.raises(ValidationError):
        EvidenceSnippet(field="x", value="y", source_id="z", quote="q", confidence=1.5)
    with pytest.raises(ValidationError):
        EvidenceSnippet(field="x", value="y", source_id="z", quote="q", confidence=-0.1)


def test_evidence_quote_not_empty() -> None:
    with pytest.raises(ValidationError):
        EvidenceSnippet(field="x", value="y", source_id="z", quote="", confidence=0.5)


def test_evidence_source_id_not_empty() -> None:
    with pytest.raises(ValidationError):
        EvidenceSnippet(field="x", value="y", source_id="", quote="q", confidence=0.5)


# === GradingComponent ===

def test_grading_weight_bounds() -> None:
    GradingComponent(name="midterm", weight=0.3)
    with pytest.raises(ValidationError):
        GradingComponent(name="midterm", weight=1.5)
    with pytest.raises(ValidationError):
        GradingComponent(name="midterm", weight=-0.1)


# === Strictness ===

def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        _minimal(unknown_field="x")


def test_evidence_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        EvidenceSnippet(
            field="x", value="y", source_id="z", quote="q",
            confidence=0.5, extra="boom",
        )


# === Roundtrip ===

def test_json_roundtrip_with_evidence() -> None:
    c1 = _minimal(
        difficulty_score=3.5,
        skill_tags=["python", "sql"],
        evidence_snippets=[
            _evidence("difficulty_score", value=3.5),
            _evidence("skill_tags", value=["python", "sql"]),
        ],
    )
    blob = c1.model_dump_json()
    c2 = Course.model_validate_json(blob)
    assert c1 == c2


# === Migration ===

def test_migrate_same_version_passthrough() -> None:
    data = {"foo": "bar"}
    assert migrate(data, SCHEMA_VERSION) == data


def test_migrate_unknown_version_raises() -> None:
    with pytest.raises(NotImplementedError):
        migrate({}, "0.9")


# === v1.1: schema bump ===

def test_schema_version_is_1_1() -> None:
    assert SCHEMA_VERSION == "1.1"


def test_grading_component_weight_optional_in_v1_1() -> None:
    from schemas.course import GradingComponent
    GradingComponent(name="discussion board")
    GradingComponent(name="midterm", weight=None)
    GradingComponent(name="final", weight=0.4)
    with pytest.raises(ValidationError):
        GradingComponent(name="x", weight=1.5)


# === v1.1: new structured models ===

def test_instructor_contact_minimal() -> None:
    from schemas.course import InstructorContact
    c = InstructorContact(name="Dr. Smith")
    assert c.email is None
    assert c.office_hours is None


def test_instructor_contact_extra_forbidden() -> None:
    from schemas.course import InstructorContact
    with pytest.raises(ValidationError):
        InstructorContact(name="x", phone="x")  # phone not in schema


def test_textbook_required_default() -> None:
    from schemas.course import Textbook
    t = Textbook(title="Foo")
    assert t.is_required is True
    assert t.authors == []


def test_meeting_slot_validates_time_strings() -> None:
    from schemas.course import DayOfWeek, MeetingSlot
    s = MeetingSlot(
        day_of_week=DayOfWeek.TUESDAY,
        start_time="17:50",  # accepted as time(17,50)
        end_time="19:10",
        location="Snell 119",
    )
    assert s.start_time.hour == 17
    assert s.end_time.minute == 10


def test_meeting_slot_rejects_inverted_times() -> None:
    from schemas.course import DayOfWeek, MeetingSlot
    with pytest.raises(ValidationError, match="end_time"):
        MeetingSlot(
            day_of_week=DayOfWeek.MONDAY,
            start_time="14:00",
            end_time="13:00",
        )


def test_meeting_schedule_rejects_inverted_dates() -> None:
    from schemas.course import MeetingSchedule
    with pytest.raises(ValidationError, match="end_date"):
        MeetingSchedule(start_date="2026-04-26", end_date="2026-01-07")


def test_meeting_schedule_default_timezone() -> None:
    from schemas.course import MeetingSchedule
    s = MeetingSchedule()
    assert s.timezone == "America/New_York"


def test_ai_policy_defaults() -> None:
    from schemas.course import AIPolicy
    p = AIPolicy()
    assert p.disclosure_required is True
    assert p.permitted_tools == []
    assert p.banned_tools == []


# === v1.1: Course with new fields ===

def test_course_v1_1_fields_default_none() -> None:
    """Backward compat: v1.0 callers don't set the new fields — they get defaults."""
    c = _minimal()
    assert c.instructor_contact is None
    assert c.textbooks == []
    assert c.meeting_schedule is None
    assert c.ai_policy is None


def test_course_v1_1_fields_roundtrip() -> None:
    from schemas.course import (
        AIPolicy, DayOfWeek, InstructorContact,
        MeetingSchedule, MeetingSlot, Textbook,
    )

    c1 = _minimal(
        instructor_contact=InstructorContact(name="Dr. Z", email="z@nu.edu"),
        textbooks=[Textbook(title="Foo", authors=["Bar"])],
        meeting_schedule=MeetingSchedule(
            slots=[MeetingSlot(
                day_of_week=DayOfWeek.WEDNESDAY,
                start_time="14:00", end_time="15:30",
            )],
        ),
        ai_policy=AIPolicy(permitted_tools=["Claude"]),
    )
    c2 = Course.model_validate_json(c1.model_dump_json())
    assert c1 == c2


# === v1.1: migration 1.0 -> 1.1 ===

def test_migrate_1_0_to_1_1_adds_new_fields() -> None:
    v1_0 = {
        "course_id": "u1",
        "primary_code": "CS 5800",
        "primary_name": "Algorithms",
        "schema_version": "1.0",
    }
    v1_1 = migrate(v1_0, from_version="1.0")

    assert v1_1["schema_version"] == "1.1"
    assert v1_1["instructor_contact"] is None
    assert v1_1["textbooks"] == []
    assert v1_1["meeting_schedule"] is None
    assert v1_1["ai_policy"] is None
    # Original keys preserved
    assert v1_1["course_id"] == "u1"
    assert v1_1["primary_code"] == "CS 5800"


def test_migrate_1_0_does_not_clobber_existing_v1_1_keys() -> None:
    """If a v1.0 row somehow already has v1.1 keys, migrate respects them."""
    data = {
        "course_id": "u1",
        "schema_version": "1.0",
        "textbooks": [{"title": "Existing", "authors": [], "is_required": True,
                        "url": None, "isbn": None}],
    }
    migrated = migrate(data, from_version="1.0")
    assert len(migrated["textbooks"]) == 1
    assert migrated["textbooks"][0]["title"] == "Existing"


def test_migrated_v1_0_data_validates_as_course() -> None:
    """End-to-end: migrate v1.0 dict, then load into v1.1 Course."""
    v1_0 = {
        "course_id": "u1",
        "primary_code": "CS 5800",
        "primary_name": "Algorithms",
        "schema_version": "1.0",
        "professor": [], "term": None, "credits": 4,
        "prereqs": [], "delivery_mode": None,
        "workload_hours_per_week": None, "difficulty_score": None,
        "grading_components": [], "topics_covered": [],
        "skill_tags": [], "career_relevance": [], "controversial_signals": [],
        "evidence_snippets": [], "extraction_confidence": None,
        "source_review_ids": [],
        "created_at": "2026-04-30T00:00:00Z",
        "updated_at": "2026-04-30T00:00:00Z",
    }
    migrated = migrate(v1_0, from_version="1.0")
    course = Course.model_validate(migrated)
    assert course.schema_version == "1.1"
    assert course.credits == 4
