"""Version-scoped rule documents, separate from legacy guessed program edges.

These describe requirements, NOT an eligibility or graduation evaluator.
中文：保存原逻辑与未知条件，不把候选代码摊平成共同必修，也不自动判资格。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.course import COURSE_CODE_PATTERN


def normalize_code(value: str) -> str:
    match = COURSE_CODE_PATTERN.fullmatch(value.strip().upper())
    if not match:
        raise ValueError("Invalid course code")
    return f"{match.group(1)} {match.group(2)}"


class CourseRange(BaseModel):
    """A catalog code interval, not proof that every number is a real course."""
    model_config = ConfigDict(extra="forbid")
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def endpoints(cls, value: str) -> str:
        code = normalize_code(value)
        if not re.fullmatch(r"[A-Z]{2,4} \d{4}", code):
            raise ValueError("Numeric ranges cannot imply suffix ordering")
        return code

    @model_validator(mode="after")
    def ordered_same_subject(self) -> CourseRange:
        start_subject, start_number = self.start.split()
        end_subject, end_number = self.end.split()
        if start_subject != end_subject or int(start_number) > int(end_number):
            raise ValueError("Range must be ordered within one subject")
        return self

    def contains(self, code: str) -> bool:
        subject, number = code.split()
        return (number.isdigit() and subject == self.start.split()[0]
                and int(self.start.split()[1]) <= int(number) <= int(self.end.split()[1]))


class RequirementNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["course", "all_of", "any_of", "select", "optional", "condition", "unmodeled"]
    label: str = Field(min_length=1, max_length=1000)
    course_code: str | None = None
    children: list[RequirementNode] = Field(default_factory=list, max_length=40)
    course_codes: list[str] = Field(default_factory=list, max_length=100)
    subject_codes: list[str] = Field(default_factory=list, max_length=20)
    course_ranges: list[CourseRange] = Field(default_factory=list, max_length=20)
    excluded_course_codes: list[str] = Field(default_factory=list, max_length=100)
    activate_when: str | None = Field(default=None, min_length=1, max_length=500)
    min_courses: int | None = Field(default=None, ge=1, le=100)
    min_credits: int | None = Field(default=None, gt=0, le=200)
    min_areas: int | None = Field(default=None, ge=1, le=40)
    areas: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("label")
    @classmethod
    def nonblank_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Rule label must not be blank")
        return value

    @field_validator("course_code")
    @classmethod
    def course_format(cls, value):
        return normalize_code(value) if value is not None else None

    @field_validator("course_codes", "excluded_course_codes")
    @classmethod
    def pool_format(cls, values):
        values = [normalize_code(value) for value in values]
        if len(values) != len(set(values)):
            raise ValueError("Course pool must not contain duplicate codes")
        return values

    @field_validator("subject_codes")
    @classmethod
    def subject_format(cls, values):
        values = [value.strip().upper() for value in values]
        if any(not re.fullmatch(r"[A-Z]{2,4}", value) for value in values) or len(values) != len(set(values)):
            raise ValueError("Subjects must be distinct catalog prefixes")
        return values

    @field_validator("activate_when")
    @classmethod
    def nonblank_activation(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Optional activation must be explicit")
        return value

    @model_validator(mode="after")
    def consistent_node(self) -> RequirementNode:
        pool_fields = bool(self.course_codes or self.subject_codes or self.course_ranges or self.excluded_course_codes
                           or self.areas or self.min_courses or self.min_credits or self.min_areas)
        if self.kind != "optional" and self.activate_when is not None:
            raise ValueError("Activation belongs only to optional branches")
        if self.kind == "course":
            if not self.course_code or self.children or pool_fields:
                raise ValueError("Course leaf requires one code and no group fields")
        elif self.kind in {"all_of", "any_of"}:
            if len(self.children) < 2 or self.course_code or pool_fields:
                raise ValueError("AND/OR group requires at least two children and no pool/code fields")
        elif self.kind == "select":
            if self.course_code or self.children or not (self.course_codes or self.subject_codes or self.course_ranges) or not (self.min_courses or self.min_credits):
                raise ValueError("Selection requires a pool and course/credit minimum; not an AND list")
            for index, interval in enumerate(self.course_ranges):
                for prior in self.course_ranges[:index]:
                    if interval.contains(prior.start) or prior.contains(interval.start):
                        raise ValueError("Numeric ranges must not overlap")
            for code in self.excluded_course_codes:
                if (code not in self.course_codes and code.split()[0] not in self.subject_codes
                        and not any(interval.contains(code) for interval in self.course_ranges)):
                    raise ValueError("Excluded course must belong to the declared candidate set")
            finite_pool = set(self.course_codes) - set(self.excluded_course_codes)
            excluded = set(self.excluded_course_codes)
            range_has_remaining = any(
                any(f"{interval.start.split()[0]} {number:04d}" not in excluded
                    for number in range(int(interval.start.split()[1]), int(interval.end.split()[1]) + 1))
                for interval in self.course_ranges
            )
            if not self.subject_codes and not range_has_remaining and not finite_pool:
                raise ValueError("Exclusions remove every candidate")
            if self.min_courses and not (self.subject_codes or self.course_ranges) and self.min_courses > len(finite_pool):
                raise ValueError("Course minimum exceeds distinct pool size")
            normalized_areas = {}
            if len(self.areas) > 40:
                raise ValueError("Too many named areas")
            for name, codes in self.areas.items():
                if not name.strip() or not codes:
                    raise ValueError("Areas must have names and courses")
                normalized = [normalize_code(code) for code in codes]
                if len(normalized) != len(set(normalized)) or not set(normalized).issubset(finite_pool):
                    raise ValueError("Area must reference distinct courses in this pool")
                normalized_areas[name] = normalized
            self.areas = normalized_areas
            if self.min_areas and (self.min_areas > len(self.areas) or self.min_courses is None or self.min_areas > self.min_courses):
                raise ValueError("Area minimum needs enough named areas and a compatible course minimum")
            if self.min_areas:
                if self.subject_codes or self.course_ranges:
                    raise ValueError("Area counting needs an enumerated finite pool")
                memberships = [code for codes in self.areas.values() for code in codes]
                if len(memberships) != len(set(memberships)) or set(memberships) != finite_pool:
                    raise ValueError("Area-based selections need an explicit, non-overlapping partition of the pool")
        elif self.kind == "optional":
            if not self.activate_when or len(self.children) != 1 or self.course_code or pool_fields:
                raise ValueError("Optional branch requires activation text and exactly one child, no pool/code")
        elif self.course_code or self.children or pool_fields:
            raise ValueError("Textual conditions/unmodeled rules cannot masquerade as course groups")
        return self


class ProgramPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")
    program_id: str = Field(min_length=1, max_length=64)
    campus: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")
    catalog_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    pathway: Literal["standard", "align", "bridge"]
    concentration: str | None = Field(default=None, min_length=1, max_length=100)
    coverage: Literal["partial", "complete"] = "partial"
    review_status: Literal["draft", "source_checked"] = "draft"
    checked_by: str | None = Field(default=None, min_length=1, max_length=100)
    checked_on: date | None = None
    source_url: str
    source_title: str = Field(min_length=1, max_length=300)
    source_catalog_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    source_excerpt: str = Field(min_length=1, max_length=6000)
    source_html_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    captured_on: date
    notes: str = Field(min_length=1, max_length=2500)
    requirements: RequirementNode

    @field_validator("program_id", "concentration", "checked_by", "source_title", "source_excerpt", "notes")
    @classmethod
    def nonblank_text(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Plan text/identifiers must not be blank")
        return value

    @field_validator("catalog_year")
    @classmethod
    def consecutive_years(cls, value: str) -> str:
        start, end = map(int, value.split("-"))
        if end != start + 1:
            raise ValueError("Catalog year must be a consecutive academic year")
        return value

    @field_validator("source_url")
    @classmethod
    def catalog_origin(cls, value: str) -> str:
        if not re.fullmatch(r"https://catalog\.northeastern\.edu/(?:archive/\d{4}-\d{4}/)?graduate/[a-z0-9/-]+/", value):
            raise ValueError("An explicit official graduate catalog URL is required")
        return value

    @model_validator(mode="after")
    def bounded_and_honest(self) -> ProgramPlan:
        if self.source_catalog_year != self.catalog_year:
            raise ValueError("Source edition and plan scope must agree")
        archived = re.search(r"/archive/(\d{4}-\d{4})/", self.source_url)
        if archived and archived.group(1) != self.catalog_year:
            raise ValueError("Archived URL edition must match the plan scope")
        if self.review_status == "source_checked" and (not self.checked_by or not self.checked_on):
            raise ValueError("Source checked documents must record reviewer and date")
        if self.checked_on and self.checked_on < self.captured_on:
            raise ValueError("Review cannot predate the recorded capture")
        stack = [(self.requirements, 1)]
        count = 0
        unknown = False
        while stack:
            node, depth = stack.pop()
            count += 1
            if count > 120 or depth > 8:
                raise ValueError("Rule document exceeds node/depth budget")
            unknown |= node.kind == "unmodeled"
            stack.extend((child, depth + 1) for child in node.children)
        if self.coverage == "complete" and (unknown or self.review_status != "source_checked"):
            raise ValueError("Incomplete/unreviewed rules cannot claim complete coverage")
        return self

    def scope_key(self) -> tuple[str, str, str, str, str]:
        return (self.program_id, self.campus, self.catalog_year, self.pathway, self.concentration or "")
