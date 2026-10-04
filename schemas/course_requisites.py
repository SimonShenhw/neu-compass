"""Lossless clause text plus bounded syntax trees, NOT enrollment decisions.

中文：不改 Course v1.1 或旧边；没列出/不能解析都不表示没有要求。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.course import COURSE_CODE_PATTERN

Grade = Literal["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F", "P", "S"]


class RequisiteNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["course", "all_of", "any_of"]
    course_code: str | None = None
    minimum_grade: Grade | None = None
    academic_level: Literal["Graduate", "Undergraduate"] | None = None
    concurrent_allowed: bool = False
    children: list[RequisiteNode] = Field(default_factory=list, max_length=120)

    @field_validator("course_code")
    @classmethod
    def canonical_code(cls, value):
        if value is None:
            return value
        match = COURSE_CODE_PATTERN.fullmatch(value.strip().upper())
        if not match:
            raise ValueError("Invalid requisite course code")
        return f"{match.group(1)} {match.group(2)}"

    @model_validator(mode="after")
    def valid_shape(self):
        if self.kind == "course":
            if not self.course_code or self.children:
                raise ValueError("Course leaf needs a code and no children")
        elif (len(self.children) < 2 or self.course_code is not None
              or self.minimum_grade is not None or self.academic_level is not None
              or self.concurrent_allowed):
            raise ValueError("AND/OR needs at least two children and no leaf fields")
        return self


class RequisiteSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["not_listed", "parsed", "unparsed"]
    raw_text: str | None = Field(default=None, max_length=20_000)
    rule: RequisiteNode | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def consistent_state(self):
        if self.status == "not_listed":
            if self.raw_text is not None or self.rule is not None or self.reason is not None:
                raise ValueError("Missing section cannot carry a rule or clause")
        elif self.status == "unparsed":
            if self.raw_text is None or self.rule is not None or self.reason is None:
                raise ValueError("Unparsed section retains text and reason, never a partial rule")
        elif not self.raw_text or not self.raw_text.strip() or self.rule is None or self.reason is not None:
            raise ValueError("Parsed section needs text and rule, not a failure reason")
        if self.rule:
            stack, count = [(self.rule, 1)], 0
            while stack:
                node, depth = stack.pop()
                count += 1
                if count > 120 or depth > 10:
                    raise ValueError("Requisite tree exceeds node/depth budget")
                stack.extend((child, depth + 1) for child in node.children)
        return self


class CatalogRequisites(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grammar_version: Literal["1"] = "1"
    prerequisite: RequisiteSection
    corequisite: RequisiteSection
