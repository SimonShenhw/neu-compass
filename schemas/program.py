"""Program ontology schemas (PLAN v3.0 Layer 3).

A `Program` is a NEU master's / bachelor's program (e.g. AAI MS, CS Align,
DS MS). It links to courses via `ProgramRequiredCourse`, which carries the
"how does this course fit into the program" annotation: requirement_type
(core / foundation / elective / capstone) and an optional
semester_recommended.

The chat route uses these to answer queries like "我是 AAI 专业，第一学期
选什么" deterministically — no hybrid retrieval guess-work.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RequirementType = Literal["core", "foundation", "elective_pool", "capstone"]
PrereqRequirement = Literal["required", "recommended", "concurrent"]


class Program(BaseModel):
    """A degree program (Master's / Bachelor's). prefix links to
    `courses.primary_code` — e.g. prefix='AAI' covers all 'AAI 5xxx/6xxx'."""

    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(min_length=1, max_length=64)
    full_name: str = Field(min_length=1)
    prefix: str = Field(
        min_length=1, max_length=10,
        description="Course-code prefix; uppercase. Used for retrieval pre-filter.",
    )
    department: str | None = None
    college: str | None = None
    notes: str | None = None


class ProgramRequiredCourse(BaseModel):
    """Edge: program -> course with annotation. semester_recommended=1 means
    'recommended for the first semester of this program'."""

    model_config = ConfigDict(extra="forbid")

    program_id: str
    course_id: str
    requirement_type: RequirementType
    semester_recommended: int | None = Field(default=None, ge=1, le=8)
    notes: str | None = None


class CoursePrerequisite(BaseModel):
    """Edge: course X requires having taken prereq_course_id first."""

    model_config = ConfigDict(extra="forbid")

    course_id: str
    prereq_course_id: str
    requirement: PrereqRequirement = "required"
    notes: str | None = None


__all__ = [
    "CoursePrerequisite",
    "PrereqRequirement",
    "Program",
    "ProgramRequiredCourse",
    "RequirementType",
]
