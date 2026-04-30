"""Course schema v1.1 — adds instructor / textbook / meeting / ai_policy.

Layer model unchanged from v1.0:
- Hard fields (L1, Catalog source): SQLite WHERE filter, must be 100% accurate.
  None is allowed (信息缺失) but a wrong value is not.
- Soft fields (L2, LLM-inferred): semantic retrieval + summarization.
  Every non-empty soft value must be backed by an evidence_snippet —
  see SOFT_FIELDS_REQUIRING_EVIDENCE for the enforced subset (PLAN §2.1).

Schema history:
  1.0 (Day 2): initial release — 18 fields per PLAN §2.2
  1.1 (Day 4): + instructor_contact, textbooks, meeting_schedule, ai_policy.
               grading_components.weight made Optional (most CPS syllabi
               don't publish weights — Day 3 dry run confirmed this).
               All new fields are Optional/empty by default, so loading
               a v1.0 record into v1.1 Pydantic class works without
               migration. scripts/migrate_schema.py canonicalizes on demand.

For SQL DDL changes, see db/init.sql + db/migrations/.
For data-level migrations, see scripts/migrate_schema.py.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.1"

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


class DayOfWeek(StrEnum):
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class EvidenceSnippet(BaseModel):
    """One quote backing a soft field value (PLAN §2.3)."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(description="Soft field this evidence supports, e.g. 'difficulty_score'")
    value: Any = Field(description="The supported value (matches the soft field's type)")
    source_id: str = Field(min_length=1, description="e.g. 'rmp_review_98765', 'reddit_t1_abc'")
    quote: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0)


class GradingComponent(BaseModel):
    """One row of the grading rubric, e.g. {'name': 'midterm', 'weight': 0.3}.

    weight is Optional in v1.1 — most CPS syllabi don't publish exact weights.
    Recording {name: "discussion board", weight: None} is preferred to dropping
    the entry entirely (which loses the fact that this component exists).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    weight: float | None = Field(default=None, ge=0.0, le=1.0)


class InstructorContact(BaseModel):
    """Instructor contact info (v1.1).

    name typically duplicates Course.professor[0] but stays here for
    standalone use. Email is OK to store: NEU faculty emails are publicly
    listed on the directory; this is not protected PII like student emails.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    email: str | None = None
    office_hours: str | None = Field(
        default=None,
        description="Free-form: 'Tue 3-5 PM @ Snell 410' or 'by appointment via email'",
    )
    secondary_contact: str | None = Field(
        default=None,
        description="e.g. academic lead's name + email",
    )


class Textbook(BaseModel):
    """Required or optional textbook (v1.1)."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    authors: list[str] = Field(default_factory=list)
    is_required: bool = True
    url: str | None = None
    isbn: str | None = None


class MeetingSlot(BaseModel):
    """One day-of-week meeting (v1.1).

    A course can have multiple slots (e.g. M+W+F). times use
    Pydantic's `time` type — accepts '17:50' string and serializes
    to ISO 'HH:MM:SS'.
    """

    model_config = ConfigDict(extra="forbid")

    day_of_week: DayOfWeek
    start_time: time
    end_time: time
    location: str | None = Field(default=None, description="e.g. 'Snell Library 119' or 'Online'")

    @model_validator(mode="after")
    def _end_after_start(self) -> MeetingSlot:
        if self.end_time <= self.start_time:
            raise ValueError(
                f"end_time ({self.end_time}) must be after start_time ({self.start_time})"
            )
        return self


class MeetingSchedule(BaseModel):
    """Full meeting schedule for a course (v1.1)."""

    model_config = ConfigDict(extra="forbid")

    slots: list[MeetingSlot] = Field(default_factory=list)
    timezone: str = Field(default="America/New_York")
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def _end_after_start_date(self) -> MeetingSchedule:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError(
                f"end_date ({self.end_date}) must be on/after start_date ({self.start_date})"
            )
        return self


class AIPolicy(BaseModel):
    """Course's AI / generative-tool usage policy (v1.1).

    Structured fields cover what students actually filter on:
    "is Copilot OK?", "is disclosure required?". Unstructured penalty/
    nuance text goes in `notes`.
    """

    model_config = ConfigDict(extra="forbid")

    permitted_tools: list[str] = Field(default_factory=list)
    banned_tools: list[str] = Field(default_factory=list)
    disclosure_required: bool = True
    notes: str | None = None


# Soft fields that REQUIRE evidence_snippets when non-empty.
# Structured fields (grading_components, topics_covered, instructor_contact,
# textbooks, meeting_schedule, ai_policy) are excluded — their evidence is the
# source document itself, recorded via source_review_ids.
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
    """Full course record (PLAN §2.2 + v1.1 additions).

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

    # === L1.5: Structured catalog details (v1.1) ===
    instructor_contact: InstructorContact | None = None
    textbooks: list[Textbook] = Field(default_factory=list)
    meeting_schedule: MeetingSchedule | None = None
    ai_policy: AIPolicy | None = None

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

    Each version bump adds a branch. Migrations are pure dict transforms;
    no DB access. Run via scripts/migrate_schema.py to apply across a DB.
    """
    if from_version == SCHEMA_VERSION:
        return data
    if from_version == "1.0":
        return _migrate_1_0_to_1_1(data)
    raise NotImplementedError(
        f"Migration from {from_version!r} to {SCHEMA_VERSION!r} not implemented"
    )


def _migrate_1_0_to_1_1(data: dict[str, Any]) -> dict[str, Any]:
    """v1.0 -> v1.1: add 4 optional fields, no value loss.

    All new fields default to None / [] — Pydantic would apply these
    defaults anyway when loading into the v1.1 model, but we bake them
    into the JSON so the on-disk representation matches in-memory.
    """
    return {
        **data,
        "instructor_contact": data.get("instructor_contact"),
        "textbooks": data.get("textbooks", []),
        "meeting_schedule": data.get("meeting_schedule"),
        "ai_policy": data.get("ai_policy"),
        "schema_version": "1.1",
    }
