"""Read-time answer evidence; does not change the persisted Course schema.

中文：回答阶段的来源与缺失信息，不改 Course JSON 的持久化版本。
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from schemas.course import COURSE_CODE_PATTERN, EvidenceSnippet
from schemas.course_requisites import RequisiteNode
from schemas.course_program_context import CoursePlacement
from schemas.plan_selection import PlanSelection
from schemas.program_plan import ProgramPlan

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
    the same status and rule tree, the recorded clause text cut to CLAUSE_LIMIT characters. An
    unparsed section also carries the SHA-256 of its whole recorded text, which years are compared
    by (so texts that differ only after the cut still differ); it never reaches the prompt.
    中文：已存年度文档里的一段先修或共修，回答看到的样子：状态和规则树不变，条款原文截到
    CLAUSE_LIMIT 个字符。未解析的一段另带整段原文的 SHA-256，各年度按它比较（所以截断处以后才
    不同也算不同）；它不进提示词。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["not_listed", "parsed", "unparsed"]
    rule: RequisiteNode | None = None
    clause_text: str | None = Field(default=None, max_length=CLAUSE_LIMIT)
    clause_truncated: bool = False
    unparsed_reason: str | None = Field(default=None, min_length=1, max_length=100)
    clause_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def consistent_state(self) -> RequisiteSectionEvidence:
        # The stored RequisiteSection's own rule: only a parsed section has a tree, never a partial one, and an
        # unparsed one keeps its text, which is empty or whitespace-only for labels without clauses.
        # 中文：沿用已存 RequisiteSection 的规则：只有 parsed 有规则树，不给部分成功的树；unparsed 保留原文，
        # 标签后面没有条款时原文为空或只有空白；原文不改写。
        if self.status == "not_listed":
            valid = self.rule is None and self.clause_text is None and not self.clause_truncated and self.unparsed_reason is None
        elif self.status == "unparsed":
            valid = self.rule is None and self.clause_text is not None and self.unparsed_reason is not None
        else:
            valid = self.rule is not None and bool(self.clause_text) and self.unparsed_reason is None
        # Only an unparsed section has a digest, and a text that was not cut must match its own.
        # 中文：只有未解析的一段有摘要；没截断的原文必须和自己的摘要一致。
        if self.clause_sha256 is not None and (
                self.status != "unparsed" or self.clause_text is None
                or (not self.clause_truncated
                    and hashlib.sha256(self.clause_text.encode("utf-8")).hexdigest() != self.clause_sha256)):
            valid = False
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
    the identity, hash or tree checks, or belong to a year with two passing documents (possible
    only in a copy without keys; neither is used). A year's one passing row is kept if its twins fail.
    中文：一门课的回答可用的年度先修文档。storage：可用、没有表、表读不了。editions：可用文档，按
    Catalog 年度从新到旧，最多 MAX_REQUISITE_EDITIONS 份，editions_omitted 是其余可用的份数。
    unusable_records：身份、hash 或规则树核对不过的已存文档，以及同年度有两份都通过核对的文档（只有
    缺键的副本里才会有，两份都不用）；同年度只有一份通过核对则保留它，其余计入不可用。"""

    model_config = ConfigDict(extra="forbid")

    storage: Literal["available", "schema_missing", "schema_unusable"]
    editions: list[RequisiteEdition] = Field(default_factory=list, max_length=MAX_REQUISITE_EDITIONS)
    editions_omitted: int = Field(default=0, ge=0)
    unusable_records: int = Field(default=0, ge=0)
    selected_year: str | None = Field(default=None, pattern=r"^\d{4}-\d{4}$")
    other_years_recorded: int = Field(default=0, ge=0)

    @field_validator("selected_year")
    @classmethod
    def consecutive_selection(cls, value):
        return ProgramPlan.consecutive_years(value) if value is not None else None

    @model_serializer(mode="wrap")
    def legacy_shape_without_selection(self, handler):
        data = handler(self)
        if self.selected_year is None:
            data.pop("selected_year", None)
            data.pop("other_years_recorded", None)
        return data

    @model_validator(mode="after")
    def ordered_distinct_editions(self) -> RequisiteEvidence:
        years = [edition.catalog_year for edition in self.editions]
        if years != sorted(set(years), reverse=True):
            raise ValueError("Editions must be distinct and newest first")
        if self.storage != "available" and (self.editions or self.editions_omitted or self.unusable_records):
            raise ValueError("Unavailable storage has no documents")
        selected_present = self.selected_year is not None and self.selected_year in years
        if selected_present and (years != [self.selected_year] or self.editions_omitted):
            raise ValueError("A recorded selected year must be the only edition shown")
        if self.selected_year is None and self.other_years_recorded:
            raise ValueError("Other years are counted only for an explicit selection")
        if self.selected_year is not None and not selected_present and self.other_years_recorded != len(years) + self.editions_omitted:
            raise ValueError("Missing selected year must retain the legacy edition accounting")
        if self.editions_omitted and len(self.editions) < MAX_REQUISITE_EDITIONS:
            raise ValueError("Editions are omitted only beyond the limit")
        return self


class PlanContext(PlanSelection):
    """Verified response metadata, not a personal POS; tree/excerpts never ride in chat history."""
    coverage: Literal["partial", "complete"]
    review_status: Literal["source_checked"]
    checked_on: date
    captured_on: date
    source_catalog_year: str
    source_url: str
    placements: dict[str, list[CoursePlacement]] = Field(max_length=20)
    placements_omitted: dict[str, int] = Field(max_length=20)

    @field_validator("source_url")
    @classmethod
    def official_plan_source(cls, value):
        return ProgramPlan.catalog_origin(value)

    @model_validator(mode="after")
    def bounded_verified_scope(self):
        archived = re.search(r"/archive/(\d{4}-\d{4})/", self.source_url)
        if self.source_catalog_year != self.catalog_year or (archived and archived[1] != self.catalog_year):
            raise ValueError("Plan source edition must agree with scope")
        if self.checked_on < self.captured_on:
            raise ValueError("Review cannot predate capture")
        if self.placements.keys() != self.placements_omitted.keys() or any(
                not code or len(code) > 100 or len(entries) > 4 or self.placements_omitted[code] < 0
                for code, entries in self.placements.items()):
            raise ValueError("Placement keys/counts must be bounded and consistent")
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
