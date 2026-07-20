"""Course schema v1.1 — adds instructor / textbook / meeting / ai_policy.

Layer model unchanged from v1.0:
- Hard fields (L1, Catalog source): SQLite WHERE filter, must be 100% accurate.
  None is allowed (信息缺失) but a wrong value is not.
- Soft fields (L2, LLM-inferred): semantic retrieval + summarization.
  Every non-empty soft value must be backed by an evidence_snippet —
  see SOFT_FIELDS_REQUIRING_EVIDENCE for the enforced subset (PLAN §2.1).

分层模型与 v1.0 保持不变:
- 硬字段(L1,来自 Catalog):用于 SQLite WHERE 过滤,必须 100% 准确。
  允许是 None(信息缺失),但绝不允许是错误的值。
- 软字段(L2,LLM 推断):用于语义检索 + 摘要生成。
  每一个非空的软字段取值都必须有 evidence_snippet 支撑 —— 强制要求的
  具体子集见 SOFT_FIELDS_REQUIRING_EVIDENCE(PLAN §2.1)。

Schema history:
  1.0 (Day 2): initial release — 18 fields per PLAN §2.2
  1.1 (Day 4): + instructor_contact, textbooks, meeting_schedule, ai_policy.
               grading_components.weight made Optional (most CPS syllabi
               don't publish weights — Day 3 dry run confirmed this).
               All new fields are Optional/empty by default, so loading
               a v1.0 record into v1.1 Pydantic class works without
               migration. scripts/migrate_schema.py canonicalizes on demand.

Schema 版本历史:
  1.0(第 2 天):首个版本 —— 按 PLAN §2.2 共 18 个字段
  1.1(第 4 天):新增 instructor_contact、textbooks、meeting_schedule、
               ai_policy。grading_components.weight 改为 Optional
               (大多数 CPS 课程大纲不公布具体权重 —— 第 3 天的试运行
               证实了这一点)。所有新字段默认都是 Optional / 空,所以
               把 v1.0 的记录直接加载进 v1.1 的 Pydantic 类,不需要
               migration 也能正常工作。scripts/migrate_schema.py
               按需做规范化迁移。

For SQL DDL changes, see db/init.sql + db/migrations/.
For data-level migrations, see scripts/migrate_schema.py.

SQL DDL 变更见 db/init.sql + db/migrations/。
数据层面的迁移见 scripts/migrate_schema.py。
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.1"

# CS 5800 / AAI 6600 / DS 5230A — 2-4 letter dept + 4 digits + optional trailing letter
# 中文:例如 CS 5800 / AAI 6600 / DS 5230A —— 2-4 个字母的系代码 + 4 位数字 +
# 可选的结尾字母
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
    """One quote backing a soft field value (PLAN §2.3).

    中文:支撑某个软字段(soft field)取值的一条引用证据(PLAN §2.3)。
    """

    model_config = ConfigDict(extra="forbid")

    # 中文:该证据支撑的软字段名,例如 'difficulty_score'
    field: str = Field(description="Soft field this evidence supports, e.g. 'difficulty_score'")
    # 中文:被支撑的取值(类型应与对应软字段一致)
    value: Any = Field(description="The supported value (matches the soft field's type)")
    # 中文:例如 'rmp_review_98765'、'reddit_t1_abc'
    source_id: str = Field(min_length=1, description="e.g. 'rmp_review_98765', 'reddit_t1_abc'")
    quote: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0)


class GradingComponent(BaseModel):
    """One row of the grading rubric, e.g. {'name': 'midterm', 'weight': 0.3}.

    weight is Optional in v1.1 — most CPS syllabi don't publish exact weights.
    Recording {name: "discussion board", weight: None} is preferred to dropping
    the entry entirely (which loses the fact that this component exists).

    中文:评分细则(grading rubric)中的一行,例如
    {'name': 'midterm', 'weight': 0.3}。

    weight 在 v1.1 中是 Optional 的 —— 大多数 CPS 课程大纲并不公布具体的
    权重数字。记录 {name: "discussion board", weight: None} 比整条丢弃更
    可取(整条丢弃会连"这个评分项存在"这个事实一起丢掉)。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    weight: float | None = Field(default=None, ge=0.0, le=1.0)


class InstructorContact(BaseModel):
    """Instructor contact info (v1.1).

    name typically duplicates Course.professor[0] but stays here for
    standalone use. Email is OK to store: NEU faculty emails are publicly
    listed on the directory; this is not protected PII like student emails.

    中文:授课教师的联系方式(v1.1)。

    name 通常与 Course.professor[0] 重复,但仍单独保留在这里以便独立使用。
    Email 可以放心存储:NEU 教职工邮箱在教职工目录中是公开信息,不像学生
    邮箱那样属于需要保护的 PII。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    email: str | None = None
    # 中文:自由文本,例如 'Tue 3-5 PM @ Snell 410' 或 'by appointment via email'
    office_hours: str | None = Field(
        default=None,
        description="Free-form: 'Tue 3-5 PM @ Snell 410' or 'by appointment via email'",
    )
    # 中文:例如学术负责人(academic lead)的姓名 + 邮箱
    secondary_contact: str | None = Field(
        default=None,
        description="e.g. academic lead's name + email",
    )


class Textbook(BaseModel):
    """Required or optional textbook (v1.1).

    中文:必读或选读教材(v1.1)。
    """

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

    中文:每周固定某一天的一次上课时段(v1.1)。

    一门课可以有多个时段(例如周一+周三+周五)。时间字段使用 Pydantic 的
    `time` 类型 —— 接受 '17:50' 这样的字符串输入,序列化为 ISO
    'HH:MM:SS' 格式输出。
    """

    model_config = ConfigDict(extra="forbid")

    day_of_week: DayOfWeek
    start_time: time
    end_time: time
    # 中文:例如 'Snell Library 119' 或 'Online'
    location: str | None = Field(default=None, description="e.g. 'Snell Library 119' or 'Online'")

    @model_validator(mode="after")
    def _end_after_start(self) -> MeetingSlot:
        if self.end_time <= self.start_time:
            raise ValueError(
                f"end_time ({self.end_time}) must be after start_time ({self.start_time})"
            )
        return self


class MeetingSchedule(BaseModel):
    """Full meeting schedule for a course (v1.1).

    中文:某门课程完整的上课时间表(v1.1)。
    """

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

    中文:课程的 AI / 生成式工具使用政策(v1.1)。

    结构化字段覆盖的是学生实际会用来筛选的问题:"能不能用 Copilot?"、
    "是否要求声明使用了 AI?"。非结构化的处罚细节 / 微妙之处放在 `notes` 里。
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
# 中文:非空时必须有 evidence_snippet 支撑的软字段集合。
# 结构化字段(grading_components、topics_covered、instructor_contact、
# textbooks、meeting_schedule、ai_policy)不在此列 —— 它们的证据就是源
# 文档本身,通过 source_review_ids 记录,不需要逐字段的 evidence_snippet。
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

    中文:完整的课程记录(PLAN §2.2 + v1.1 新增字段)。

    `course_id` 是内部稳定的 UUID(由摄取(ingestion)流水线分配,课程
    改名后依然保持不变)。`primary_code` 是人类可读的规范代码。代码 /
    名称的其他变体见 `course_aliases` 表(PLAN §1.4)。
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # === Identity ===
    # 中文:身份标识
    course_id: str = Field(min_length=1, description="Internal stable UUID")
    primary_code: str = Field(description="Canonical code, e.g. 'CS 5800'")
    primary_name: str = Field(min_length=1)
    schema_version: str = Field(default=SCHEMA_VERSION)

    # === L1: Hard fields ===
    # 中文:L1 硬字段
    professor: list[str] = Field(default_factory=list)
    term: str | None = None
    credits: int | None = Field(default=None, ge=0, le=12)
    prereqs: list[str] = Field(default_factory=list)
    delivery_mode: DeliveryMode | None = None

    # === L1.5: Structured catalog details (v1.1) ===
    # 中文:结构化的目录细节(v1.1)
    instructor_contact: InstructorContact | None = None
    textbooks: list[Textbook] = Field(default_factory=list)
    meeting_schedule: MeetingSchedule | None = None
    ai_policy: AIPolicy | None = None

    # === L2: Soft fields ===
    # 中文:L2 软字段
    workload_hours_per_week: float | None = Field(default=None, ge=0.0)
    difficulty_score: float | None = Field(default=None, ge=1.0, le=5.0)
    grading_components: list[GradingComponent] = Field(default_factory=list)
    topics_covered: list[str] = Field(default_factory=list)
    skill_tags: list[str] = Field(default_factory=list)
    career_relevance: list[str] = Field(default_factory=list)
    controversial_signals: list[str] = Field(default_factory=list)

    # === Provenance ===
    # 中文:溯源信息
    evidence_snippets: list[EvidenceSnippet] = Field(default_factory=list)
    extraction_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_review_ids: list[str] = Field(default_factory=list)

    # === Timestamps ===
    # 中文:时间戳
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    # Normalizes to "DEPT NNNN" (single space, uppercase) regardless of how
    # the source data was punctuated/cased — downstream code (aliasing,
    # SQLite lookups) can then rely on one canonical spelling.
    # 中文:统一归一化为 "DEPT NNNN" 格式(单个空格、全大写),无论源数据
    # 原本的大小写 / 标点是什么样 —— 下游代码(别名匹配、SQLite 查找)就能
    # 依赖这一种规范拼写。
    @field_validator("primary_code")
    @classmethod
    def _normalize_code(cls, v: str) -> str:
        normalized = v.strip().upper()
        m = COURSE_CODE_PATTERN.match(normalized)
        if not m:
            raise ValueError(f"Invalid course code format: {v!r} (expected e.g. 'CS 5800')")
        return f"{m.group(1)} {m.group(2)}"

    # Guards every free-text list field at once: rejects blank/whitespace-only
    # entries and strips surrounding whitespace from the rest. Applied here
    # (not per-field) because the same defect (an empty string sneaking into
    # a list) can come from any LLM-extraction field, not just one.
    # 中文:一次性守护所有自由文本的列表字段:拒绝空白 / 纯空格条目,并把
    # 其余条目两端的空白去掉。之所以写成一个校验器覆盖全部字段(而非逐
    # 字段各写一个),是因为"空字符串混进列表"这个缺陷可能来自任何一个
    # LLM 抽取字段,不只是某一个。
    @field_validator("professor", "prereqs", "topics_covered", "skill_tags",
                     "career_relevance", "controversial_signals", "source_review_ids")
    @classmethod
    def _no_empty_strings(cls, v: list[str]) -> list[str]:
        if any(not s or not s.strip() for s in v):
            raise ValueError("List entries must be non-empty strings")
        return [s.strip() for s in v]

    # WHAT: cross-field validator — for every field in
    # SOFT_FIELDS_REQUIRING_EVIDENCE that's actually populated (non-None, and
    # non-empty if it's a list), at least one EvidenceSnippet.field must name it.
    # WHY: soft (L2, LLM-inferred) fields are unverified claims by
    # construction — an unsupported soft value is indistinguishable from a
    # hallucination. Enforcing this at the Pydantic layer (rather than only
    # in the extraction prompt) means a bad LLM response fails LOUDLY at
    # construction time instead of silently reaching SQLite/FAISS and
    # surfacing to a student as an uncited "fact" (PLAN §2.1).
    # 中文(WHAT,做什么):跨字段校验器 —— 对 SOFT_FIELDS_REQUIRING_EVIDENCE
    # 中每一个"确实有值"的字段(非 None;若是列表则还要求非空),必须至少
    # 有一条 EvidenceSnippet 的 field 指向它。
    # 中文(WHY,为什么):软字段(L2,由 LLM 推断而来)从设计上讲就是未经
    # 证实的说法 —— 一个没有证据支撑的软字段取值,和一次幻觉
    # (hallucination)没有区别。把这条约束放在 Pydantic 这一层强制执行
    # (而不是只依赖抽取提示词里的要求),意味着一次糟糕的 LLM 响应会在
    # 对象构造阶段就大声报错,而不是悄悄流入 SQLite/FAISS,最终变成学生
    # 看到的一条没有引用来源的"事实"(PLAN §2.1)。
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

    中文:Schema 迁移入口(PLAN §2.4)。
    每次版本号提升都新增一个分支。迁移是纯粹的 dict 变换,不访问数据库。
    通过 scripts/migrate_schema.py 对整个数据库批量执行。
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

    中文:v1.0 -> v1.1:新增 4 个可选字段,不丢失任何原有数据。

    所有新字段默认值都是 None / []  —— 即便不在这里显式赋值,加载进
    v1.1 的 Pydantic 模型时 Pydantic 也会自动套用这些默认值;这里把
    它们提前写进 JSON,是为了让磁盘上的表示与内存中的表示保持一致。
    """
    return {
        **data,
        "instructor_contact": data.get("instructor_contact"),
        "textbooks": data.get("textbooks", []),
        "meeting_schedule": data.get("meeting_schedule"),
        "ai_policy": data.get("ai_policy"),
        "schema_version": "1.1",
    }
