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
    assert _minimal().schema_version == "1.0"


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
