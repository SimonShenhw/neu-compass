"""Course schema v1: dual-layer Pydantic models for SQLite filter + RAG retrieval.

Hard fields (L1, Catalog source): SQLite WHERE filter, must be 100% accurate.
None is allowed (信息缺失) but a wrong value is not.

Soft fields (L2, LLM-inferred): semantic retrieval + summarization. Every
non-empty soft value must be backed by at least one EvidenceSnippet — see
SOFT_FIELDS_REQUIRING_EVIDENCE for the enforced subset (PLAN §2.1).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"

# CS 5800 / AAI 6600 / DS 5230A — 2-4 letter dept + 4 digits + optional trailing letter
COURSE_CODE_PATTERN = re.compile(r"^([A-Z]{2,4})\s?(\d{4}[A-Z]?)$")


class DataSource(StrEnum):
    CATALOG = "catalog"
    SYLLABUS = "syllabus"
    RMP = "rmp"
    REDDIT = "reddit"
    UGC = "ugc"
    LLM = "llm"


class DeliveryMode(StrEnum):
    IN_PERSON = "in_person"
    ONLINE = "online"
    HYBRID = "hybrid"
    ASYNC = "async"


class EvidenceSnippet(BaseModel):
    """One quote backing a soft field value (PLAN §2.3)."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(description="Soft field this evidence supports, e.g. 'difficulty_score'")
    value: Any = Field(description="The supported value (matches the soft field's type)")
    source_id: str = Field(min_length=1, description="e.g. 'rmp_review_98765', 'reddit_t1_abc'")
    quote: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0)


class GradingComponent(BaseModel):
    """One row of the grading rubric, e.g. {'name': 'midterm', 'weight': 0.3}."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    weight: float = Field(ge=0.0, le=1.0)


# Soft fields that REQUIRE evidence_snippets when non-empty.
# Structured fields (grading_components, topics_covered) are excluded — their
# evidence is the source document itself, recorded via source_review_ids.
SOFT_FIELDS_REQUIRING_EVIDENCE: frozenset[str] = frozenset(
    {
        "workload_hours_per_week",
        "difficulty_score",
        "skill_tags",
        "career_relevance",
        "controversial_signals",
    }
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Course(BaseModel):
    """Full course record (PLAN §2.2).

    `course_id` is an internal stable UUID (assigned by the ingestion pipeline,
    survives renames). `primary_code` is the human-readable canonical code.
    See `course_aliases` table (PLAN §1.4) for code/name variants.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # === Identity ===
    course_id: str = Field(min_length=1, description="Internal stable UUID")
    primary_code: str = Field(description="Canonical code, e.g. 'CS 5800'")
    primary_name: str = Field(min_length=1)
    schema_version: str = Field(default=SCHEMA_VERSION)

    # === L1: Hard fields ===
    professor: list[str] = Field(default_factory=list)
    term: str | None = None
    credits: int | None = Field(default=None, ge=0, le=12)
    prereqs: list[str] = Field(default_factory=list)
    delivery_mode: DeliveryMode | None = None

    # === L2: Soft fields ===
    workload_hours_per_week: float | None = Field(default=None, ge=0.0)
    difficulty_score: float | None = Field(default=None, ge=1.0, le=5.0)
    grading_components: list[GradingComponent] = Field(default_factory=list)
    topics_covered: list[str] = Field(default_factory=list)
    skill_tags: list[str] = Field(default_factory=list)
    career_relevance: list[str] = Field(default_factory=list)
    controversial_signals: list[str] = Field(default_factory=list)

    # === Provenance ===
    evidence_snippets: list[EvidenceSnippet] = Field(default_factory=list)
    extraction_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_review_ids: list[str] = Field(default_factory=list)

    # === Timestamps ===
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @field_validator("primary_code")
    @classmethod
    def _normalize_code(cls, v: str) -> str:
        normalized = v.strip().upper()
        m = COURSE_CODE_PATTERN.match(normalized)
        if not m:
            raise ValueError(f"Invalid course code format: {v!r} (expected e.g. 'CS 5800')")
        return f"{m.group(1)} {m.group(2)}"

    @field_validator("professor", "prereqs", "topics_covered", "skill_tags",
                     "career_relevance", "controversial_signals", "source_review_ids")
    @classmethod
    def _no_empty_strings(cls, v: list[str]) -> list[str]:
        if any(not s or not s.strip() for s in v):
            raise ValueError("List entries must be non-empty strings")
        return [s.strip() for s in v]

    @model_validator(mode="after")
    def _check_soft_field_evidence(self) -> Course:
        evidence_fields = {ev.field for ev in self.evidence_snippets}
        for field_name in SOFT_FIELDS_REQUIRING_EVIDENCE:
            v = getattr(self, field_name)
            has_value = v is not None and (not isinstance(v, list) or len(v) > 0)
            if has_value and field_name not in evidence_fields:
                raise ValueError(
                    f"Soft field {field_name!r} has value but no evidence_snippet. "
                    f"PLAN §2.1 requires evidence for all inferred fields."
                )
        return self


def migrate(data: dict[str, Any], from_version: str) -> dict[str, Any]:
    """Schema migration entrypoint (PLAN §2.4).

    Each version bump adds a branch here. Only 1.0 exists today.
    """
    if from_version == SCHEMA_VERSION:
        return data
    raise NotImplementedError(
        f"Migration from {from_version} to {SCHEMA_VERSION} not implemented"
    )
