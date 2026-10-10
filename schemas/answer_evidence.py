"""Read-time answer evidence; does not change the persisted Course schema.

中文：回答阶段的来源与缺失信息，不改 Course JSON 的持久化版本。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.course import COURSE_CODE_PATTERN, EvidenceSnippet
from schemas.course_requisites import RequisiteNode

# Exact HTTPS origin/path of an official NEU catalog department page; also the only link
# target the UI lets a model answer keep.
# 中文：NEU 官方目录院系页的精确 HTTPS 地址形式；也是界面允许模型回答保留的唯一链接目标。
OFFICIAL_CATALOG_URL = re.compile(r"https://catalog\.northeastern\.edu/course-descriptions/[a-z]{2,8}/")
# Year-scoped rules an answer may use per course (newest first; the rest are only counted), and
# how much of each clause's recorded text it gets. Listing the newest first is a bound, not a
# choice: no edition is the student's unless the student says so.
# 中文：每门课给回答的年度规则份数（新的在前，其余只计数）和每段条款原文的长度上限。新的在前
# 只是限量，不是替学生选：学生没说，哪一份都不是学生适用的年度。
MAX_REQUISITE_EDITIONS = 3
CLAUSE_LIMIT = 600


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
        if not OFFICIAL_CATALOG_URL.fullmatch(value):
            raise ValueError("An explicit official NEU catalog department URL is required")
        return value

    @model_validator(mode="after")
    def matching_department(self) -> CatalogSnapshot:
        dept = self.course_code.split(" ")[0].lower()
        if self.catalog_url != f"https://catalog.northeastern.edu/course-descriptions/{dept}/":
            raise ValueError("Catalog department does not match course code")
        return self


class RequisiteSectionEvidence(BaseModel):
    """One prerequisite or corequisite section of a stored year document, as an answer sees it:
    the same status and rule tree, the recorded clause text cut to CLAUSE_LIMIT characters.
    中文：已存年度文档里的一段先修或共修，回答看到的样子：状态和规则树不变，条款原文截到
    CLAUSE_LIMIT 个字符。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["not_listed", "parsed", "unparsed"]
    rule: RequisiteNode | None = None
    clause_text: str | None = Field(default=None, max_length=CLAUSE_LIMIT)
    clause_truncated: bool = False
    unparsed_reason: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def consistent_state(self) -> RequisiteSectionEvidence:
        # The stored RequisiteSection's own rule: only a parsed section has a tree, never a partial one.
        # 中文：沿用已存 RequisiteSection 的规则：只有 parsed 有规则树，不给部分成功的树。
        if self.status == "not_listed":
            valid = self.rule is None and self.clause_text is None and not self.clause_truncated and self.unparsed_reason is None
        elif self.status == "unparsed":
            valid = self.rule is None and bool(self.clause_text) and self.unparsed_reason is not None
        else:
            valid = self.rule is not None and bool(self.clause_text) and self.unparsed_reason is None
        if not valid:
            raise ValueError("Requisite section state is inconsistent")
        return self


class RequisiteEdition(BaseModel):
    """One catalog year's course-block rules for a course, with where and when they were captured."""

    model_config = ConfigDict(extra="forbid")

    catalog_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    catalog_url: str
    captured_at: datetime
    prerequisite: RequisiteSectionEvidence
    corequisite: RequisiteSectionEvidence

    @field_validator("catalog_url")
    @classmethod
    def official_catalog_url(cls, value: str) -> str:
        if not OFFICIAL_CATALOG_URL.fullmatch(value):
            raise ValueError("An explicit official NEU catalog department URL is required")
        return value


class RequisiteEvidence(BaseModel):
    """The year-scoped prerequisite documents an answer may use for one course.

    storage: available, schema_missing (no table) or schema_unusable (the table cannot be read).
    editions: usable documents, newest catalog year first, at most MAX_REQUISITE_EDITIONS;
    editions_omitted counts the other usable ones. unusable_records: stored documents that failed
    the identity, hash or tree checks, or that share a catalog year with another one (only a copy
    without keys can hold two; neither is used).
    中文：一门课的回答可用的年度先修文档。storage：可用、没有表、表读不了。editions：可用文档，按
    Catalog 年度从新到旧，最多 MAX_REQUISITE_EDITIONS 份，editions_omitted 是其余可用的份数。
    unusable_records：身份、hash 或规则树核对不过的已存文档，以及和另一份同年度的（只有缺键的副本里
    才会有两份，两份都不用）。"""

    model_config = ConfigDict(extra="forbid")

    storage: Literal["available", "schema_missing", "schema_unusable"]
    editions: list[RequisiteEdition] = Field(default_factory=list, max_length=MAX_REQUISITE_EDITIONS)
    editions_omitted: int = Field(default=0, ge=0)
    unusable_records: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def ordered_distinct_editions(self) -> RequisiteEvidence:
        years = [edition.catalog_year for edition in self.editions]
        if years != sorted(set(years), reverse=True):
            raise ValueError("Editions must be distinct and newest first")
        if self.storage != "available" and (self.editions or self.editions_omitted or self.unusable_records):
            raise ValueError("Unavailable storage has no documents")
        if self.editions_omitted and len(self.editions) < MAX_REQUISITE_EDITIONS:
            raise ValueError("Editions are omitted only beyond the limit")
        return self


class CourseAnswerEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog: CatalogSnapshot | None = None
    field_evidence: list[EvidenceSnippet] = Field(default_factory=list)
    source_review_ids: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # None: not looked up (old callers and stored history); then nothing about prerequisites changes.
    # 中文：None 表示没有查（旧调用方和已存历史）；这时先修相关的输出和以前一样。
    requisites: RequisiteEvidence | None = None
