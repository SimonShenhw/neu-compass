"""Co-op experience domain model and distinct-contributor publication helpers.

Curated seeds are a separate provenance class. UGC is collected privately and
reviewed before publication; visibility_level describes the content field tier,
not a moderation decision. Two different authenticated accounts are necessary
but not sufficient for privacy: free text still requires human redaction.
中文：种子策展与 UGC 分开；私有收集后先审核，内容分层不能替代审核。
不同登录账号是门槛，不保证自然人不同或自由文本已完全匿名。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import hashlib
import json
import unicodedata

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
        default=None, max_length=10_000,
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
    """Count distinct non-seed contributors in the FINAL reviewed corpus.

    Include the target itself when evaluating publication. Unknown contributors
    and curator seeds cannot establish anonymity; repeated rows from one user
    count once. The caller is responsible for supplying only reviewed records.
    中文：传入含目标的最终已审核集合；按不同贡献者计数，种子/空身份不计数。
    """
    if k < 1:
        raise ValueError("k must be positive")
    key = coop_group_key(coop.company, coop.role, coop.coop_term)
    contributors = {
        c.contributor_user_id for c in corpus
        if c.contributor_user_id and not c.is_seed_data
        and coop_group_key(c.company, c.role, c.coop_term) == key
    }
    return len(contributors) < k


def coop_group_key(company: str, role: str, coop_term: str | None) -> str:
    """Stable logical-experience key; case/spacing/Unicode variants are not new credit.

    中文：同公司、岗位、学期的逻辑经历使用稳定键，大小写/空格变体不另记功。
    """
    parts = [
        " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())
        for value in (company, role, coop_term)
    ]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode("utf-8")).hexdigest()


def derive_visibility(*, interview_summary: str | None, technical_questions: str | None,
                      salary_range_usd: str | None) -> int:
    """Content-derived field tier, shared by submission and curator review."""
    if salary_range_usd:
        return 2
    return int(bool(interview_summary or technical_questions))


__all__ = ["CoopExperience", "Industry", "coop_group_key", "derive_visibility", "is_uniquely_identifying"]
