"""Alias schema — student口语 / cross-listed / version / rename mapping.

Mirrors db.init.sql course_aliases table:
- alias_type CHECK matches AliasType StrEnum values
- source CHECK matches AliasSource StrEnum values
- review_status CHECK matches AliasReviewStatus StrEnum values
- confidence in [0, 1]

PLAN §1.4 three-tier source strategy:
  L1 official    confidence=1.0, status='approved'   NEU Catalog cross-listed
  L2 manual      confidence~0.95, status='approved'  team Day 2 entry
  L3 llm_inferred confidence 0.5-0.9, status='pending' awaiting human review
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AliasType(StrEnum):
    CROSS_LISTED = "cross_listed"
    VERSION = "version"
    RENAME = "rename"
    SLANG = "slang"
    PROFESSOR_ATTRIBUTION = "professor_attribution"


class AliasSource(StrEnum):
    OFFICIAL = "official"
    MANUAL = "manual"
    LLM_INFERRED = "llm_inferred"


class AliasReviewStatus(StrEnum):
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"


class Alias(BaseModel):
    """One alias_text -> primary_course_id mapping.

    alias_id is None for not-yet-persisted records; set by SQLite AUTOINCREMENT
    on insert. Repository.add() returns the assigned id.
    """

    model_config = ConfigDict(extra="forbid")

    alias_id: int | None = None
    alias_text: str = Field(min_length=1)
    alias_type: AliasType
    primary_course_id: str = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    valid_from: date | None = None
    valid_until: date | None = None
    source: AliasSource
    review_status: AliasReviewStatus = AliasReviewStatus.APPROVED
    evidence: str | None = Field(default=None, max_length=2000)
    created_at: datetime | None = None  # set by DB

    @model_validator(mode="after")
    def _date_consistency(self) -> Alias:
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError(
                f"valid_until ({self.valid_until}) must be on/after valid_from "
                f"({self.valid_from})"
            )
        return self
