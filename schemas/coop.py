"""Co-op experience schema (PLAN §1.4 / §6).

One row per UGC submission. PII redaction (PLAN §6.3) is the contributor's
+ curator's responsibility BEFORE write — the schema doesn't redact, it just
records the audit trail in `redaction_audit`.

每条 UGC(用户生成内容)提交对应一行。PII 脱敏(PLAN §6.3)是贡献者 +
审核员在写入之前的责任 —— 这个 schema 本身不做脱敏,只是在
`redaction_audit` 里记录审计轨迹。

Visibility tiers (PLAN §6.4):
  0 — preview tier (公司 + 岗位 + 时长, fully public)
  1 — detail tier (interview flow + technical questions; user needs ≥1 contribution)
  2 — premium tier (NEU alumni placement; user needs ≥2 contributions + 1 invite)

可见性分级(PLAN §6.4):
  0 —— 预览层(公司 + 岗位 + 时长,完全公开)
  1 —— 详情层(面试流程 + 技术问题;用户需要 ≥1 次贡献)
  2 —— 高级层(NEU 校友去向;用户需要 ≥2 次贡献 + 1 次邀请)

The row's `visibility_level` is the MINIMUM contribution count required to
view this row. Frontend checks `users.contribution_count >= visibility_level`.

这一行的 `visibility_level` 是查看该行所需的最低贡献次数。前端检查的是
`users.contribution_count >= visibility_level`。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Industry(StrEnum):
    """Industry buckets used for analytics + k-anonymity filtering.

    PLAN §6.5 Seed Data distribution targets:
      QUANT_FINTECH: 12  (State Street, Fidelity, Wellington, MFS, Putnam)
      BIG_TECH:      8   (Amazon, Google, Microsoft Boston offices)
      BIOTECH_HEALTH: 5  (Moderna, Vertex, IQVIA)
      STARTUP:       5   (Boston AI startup ecosystem)

    中文:用于数据分析 + k-匿名(k-anonymity)过滤的行业分桶。

    PLAN §6.5 种子数据(Seed Data)分布目标:
      QUANT_FINTECH:  12(State Street、Fidelity、Wellington、MFS、Putnam)
      BIG_TECH:        8(Amazon、Google、Microsoft 波士顿办公室)
      BIOTECH_HEALTH:  5(Moderna、Vertex、IQVIA)
      STARTUP:         5(波士顿 AI 创业生态圈)
    """

    QUANT_FINTECH = "quant_fintech"
    BIG_TECH = "big_tech"
    BIOTECH_HEALTH = "biotech_health"
    STARTUP = "startup"
    CONSULTING = "consulting"
    OTHER = "other"


class CoopExperience(BaseModel):
    """One Co-op record. Maps 1:1 to coop_experiences table in db/init.sql.

    中文:一条 Co-op 记录。与 db/init.sql 中的 coop_experiences 表一一对应。
    """

    model_config = ConfigDict(extra="forbid")

    # === Identity ===
    # 中文:身份标识
    coop_id: str = Field(min_length=1)

    # === Always-shown (preview tier) ===
    # 中文:始终展示(预览层)
    company: str = Field(min_length=1)
    role: str = Field(min_length=1)
    industry: Industry | None = None
    # 中文:例如 'Summer 2025'、'Spring 2026'、'Fall 2025'
    coop_term: str | None = Field(
        default=None,
        description="e.g. 'Summer 2025', 'Spring 2026', 'Fall 2025'",
    )
    duration_months: int | None = Field(default=None, ge=1, le=8)
    related_courses: list[str] = Field(default_factory=list)

    # === Detail tier (visibility_level >= 1) ===
    # 中文:详情层(visibility_level >= 1)
    # 中文:已按 PLAN §6.3 完成 PII 脱敏的自由文本
    interview_summary: str | None = Field(
        default=None, max_length=10_000,
        description="Already PII-redacted free text per PLAN §6.3",
    )
    # 中文:已脱敏的技术面试问题
    technical_questions: str | None = Field(
        default=None, max_length=10_000,
        description="Redacted technical interview questions",
    )

    # === Premium tier (visibility_level >= 2) ===
    # 中文:高级层(visibility_level >= 2)
    # 中文:区间桶,如 '$30-35/hr' —— 绝不存储精确数字
    salary_range_usd: str | None = Field(
        default=None,
        description="Bucket like '$30-35/hr' — never store exact figure",
    )

    # === Provenance ===
    # 中文:溯源信息
    is_seed_data: bool = False
    # 中文:查看该行所需的最低 contribution_count
    visibility_level: int = Field(
        default=0, ge=0, le=2,
        description="Min contribution_count required to view this row",
    )
    # 中文:种子数据(团队整理、无个人贡献者)时为 NULL
    contributor_user_id: str | None = Field(
        default=None,
        description="NULL for seed data (team-curated, no individual contributor)",
    )
    # 中文:谁审核的 + 脱敏了什么,自由文本
    redaction_audit: str | None = Field(
        default=None,
        description="Who reviewed + what was redacted, free text",
    )
    created_at: datetime | None = None  # set by DB
    # 中文:由数据库设置


def is_uniquely_identifying(
    coop: CoopExperience,
    corpus: list[CoopExperience],
    *,
    k: int = 2,
) -> bool:
    """Check if (company, role, coop_term) triple in `coop` appears <k times
    across `corpus`. PLAN §6.3 / v1.3 PII k-anonymity rule.

    Use BEFORE inserting a new Co-op row: if returns True, the row is
    uniquely identifying (only one person at NEU did this combo) and must
    be further generalized (e.g. company → industry bucket) before publish.

    中文(WHAT,做什么):检查 `coop` 里的 (company, role, coop_term) 三元组
    在 `corpus` 中出现的次数是否 <k。这是 PLAN §6.3 / v1.3 的 PII
    k-匿名(k-anonymity)规则。

    中文(WHY/怎么用):必须在插入一条新 Co-op 记录之前调用。若返回
    True,说明这一行具有唯一识别性(全 NEU 只有一个人做过这个
    公司+岗位+学期的组合),发布前必须先做进一步泛化(例如把
    company 换成更粗粒度的 industry 分桶)。
    """
    key = (coop.company, coop.role, coop.coop_term)
    matching = sum(
        1 for c in corpus
        if (c.company, c.role, c.coop_term) == key
    )
    # k-anonymity check: True (unsafe to publish) iff fewer than k rows in
    # the corpus share this exact triple, INCLUDING `coop` itself if it's
    # already part of `corpus` — a brand-new row being checked pre-insert
    # only "matches" prior rows, so callers should pass the corpus BEFORE
    # this row is added.
    # 中文:k-匿名检查 —— 语料库中与该三元组完全相同的行数少于 k 时返回
    # True(不宜发布),这里的计数包含 `coop` 自身(如果它已经在 `corpus`
    # 里的话);对于插入前的新行检查,它只会匹配到之前已存在的行,所以
    # 调用方应当传入"加入这一行之前"的语料库。
    return matching < k


__all__ = ["CoopExperience", "Industry", "is_uniquely_identifying"]
