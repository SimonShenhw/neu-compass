"""Year-scoped clause documents; consistent hashes are NOT eligibility proofs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.course import COURSE_CODE_PATTERN
from schemas.course_requisites import CatalogRequisites
from schemas.course_requisite_source import CourseRequisiteSource
from schemas.course_description_evidence import CourseDescriptionEvidence
from schemas.course_program_context import CourseProgramContext
from schemas.catalog_credit_hours import CatalogCreditHours
from scrapers.course_requisites import parse_clause


class CourseRequisiteDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format_version: Literal["1"] = "1"
    course_id: str = Field(min_length=1, max_length=200)
    course_code: str
    course_name: str = Field(min_length=1, max_length=300)
    catalog_year: str
    campus: None = None  # The department pages do not declare campus scope.
    coverage: Literal["courseblock_clauses_only"] = "courseblock_clauses_only"
    source: CourseRequisiteSource
    requisites: CatalogRequisites
    description_evidence: CourseDescriptionEvidence | None = None  # Old records were not captured.
    credit_hours: CatalogCreditHours | None = None  # No inference from old Course.credits.
    imported_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("course_code")
    @classmethod
    def canonical_code(cls, value):
        match = COURSE_CODE_PATTERN.fullmatch(value.strip().upper())
        if not match:
            raise ValueError("Invalid course code")
        return f"{match.group(1)} {match.group(2)}"

    @field_validator("imported_at")
    @classmethod
    def aware_import(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Import time must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def consistent_identity_and_syntax(self):
        if self.catalog_year != self.source.catalog_year:
            raise ValueError("Document/source edition mismatch")
        department = self.course_code.split()[0].lower()
        if self.source.url != f"https://catalog.northeastern.edu/course-descriptions/{department}/":
            raise ValueError("Document/source department mismatch")
        for section in [self.requisites.prerequisite, self.requisites.corequisite]:
            if section.status == "parsed" and parse_clause(section.raw_text) != section:
                raise ValueError("Stored syntax tree does not match the recorded clause")
        return self


class CourseRequisiteListing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_available: bool = False
    has_any_stored_records: bool = False  # Includes corrupt/other-edition rows.
    documents: list[CourseRequisiteDocument] = Field(default_factory=list)
    unusable_records: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)
    program_contexts: list[CourseProgramContext] = Field(default_factory=list)

    @model_validator(mode="after")
    def contexts_match_documents(self):
        identities = {(item.course_code, item.catalog_year) for item in self.documents}
        keys = [(item.course_code, item.catalog_year) for item in self.program_contexts]
        if len(set(keys)) != len(keys) or any(key not in identities for key in keys):
            raise ValueError("Program contexts must reference distinct available course editions")
        return self
