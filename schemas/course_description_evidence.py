"""Keyword candidates in whole description paragraphs, NOT interpreted rules.

中文：保留所有段落；关键词包括假阳性/否定/可选许可，不判断注册资格。
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Marker = Literal["permission", "approval", "admission", "eligibility", "restriction", "registration", "qualification"]
PATTERNS = {
    "permission": re.compile(r"\b(?:permission|consent)\b", re.I),
    "approval": re.compile(r"\b(?:approval|approved)\b", re.I),
    "admission": re.compile(r"\b(?:admission|admitted)\b", re.I),
    "eligibility": re.compile(r"\b(?:eligible|eligibility)\b", re.I),
    "restriction": re.compile(r"\b(?:restricted|restriction|restrictions)\b", re.I),
    "registration": re.compile(r"\b(?:enroll(?:ment|ed|ing)?|registration|register(?:ed|ing)?)\b", re.I),
    "qualification": re.compile(r"\b(?:qualification|qualifications|qualified|qualify)\b", re.I),
}


class DescriptionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paragraph_index: int = Field(ge=0, lt=30)
    markers: list[Marker] = Field(min_length=1, max_length=7)


def candidate_data(paragraphs: list[str]) -> list[dict]:
    result = []
    for index, text in enumerate(paragraphs):
        markers = [name for name, pattern in PATTERNS.items() if pattern.search(text)]
        if markers:
            result.append({"paragraph_index": index, "markers": markers})
    return result


class CourseDescriptionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format_version: Literal["1"] = "1"
    status: Literal["not_listed", "no_keyword_match", "review_needed"]
    paragraphs: list[str] = Field(default_factory=list, max_length=30)
    candidates: list[DescriptionCandidate] = Field(default_factory=list, max_length=30)

    @field_validator("paragraphs")
    @classmethod
    def bounded_normalized_text(cls, values):
        if any(not value or value != " ".join(value.split()) or len(value) > 20_000 for value in values):
            raise ValueError("Description paragraphs must be nonblank, normalized and bounded")
        if sum(map(len, values)) > 60_000:
            raise ValueError("Description exceeds text budget; do not truncate evidence")
        return values

    @model_validator(mode="after")
    def consistent_candidates(self):
        expected = candidate_data(self.paragraphs)
        status = "not_listed" if not self.paragraphs else "review_needed" if expected else "no_keyword_match"
        if self.status != status or [item.model_dump() for item in self.candidates] != expected:
            raise ValueError("Description status/markers do not match the whole recorded paragraphs")
        return self

    @classmethod
    def from_paragraphs(cls, paragraphs: list[str]) -> CourseDescriptionEvidence:
        candidates = candidate_data(paragraphs)
        status = "not_listed" if not paragraphs else "review_needed" if candidates else "no_keyword_match"
        return cls(status=status, paragraphs=paragraphs, candidates=candidates)
