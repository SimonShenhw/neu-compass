"""Read-time answer evidence; does not change the persisted Course schema.

中文：回答阶段的来源与缺失信息，不改 Course JSON 的持久化版本。
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.course import COURSE_CODE_PATTERN, EvidenceSnippet


class CatalogSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_code: str
    course_name: str = Field(min_length=1)
    description: str | None = Field(default=None, max_length=20_000)
    credits: int | None = Field(default=None, ge=0, le=12)
    prereq_codes: list[str] = Field(default_factory=list)
    catalog_url: str
    snapshot_id: str
    imported_at: datetime
    retrieved_at: datetime | None = None  # Old JSONL archives do not record this.

    @field_validator("course_code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        match = COURSE_CODE_PATTERN.fullmatch(value.strip().upper())
        if not match:
            raise ValueError("Invalid catalog course code")
        return f"{match.group(1)} {match.group(2)}"

    @field_validator("catalog_url")
    @classmethod
    def official_catalog_url(cls, value: str) -> str:
        # Exact HTTPS origin/path; never turn arbitrary source IDs into links.
        if not re.fullmatch(r"https://catalog\.northeastern\.edu/course-descriptions/[a-z]{2,8}/", value):
            raise ValueError("An explicit official NEU catalog department URL is required")
        return value

    @model_validator(mode="after")
    def matching_department(self) -> CatalogSnapshot:
        dept = self.course_code.split(" ")[0].lower()
        if self.catalog_url != f"https://catalog.northeastern.edu/course-descriptions/{dept}/":
            raise ValueError("Catalog department does not match course code")
        return self


class CourseAnswerEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog: CatalogSnapshot | None = None
    field_evidence: list[EvidenceSnippet] = Field(default_factory=list)
    source_review_ids: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
