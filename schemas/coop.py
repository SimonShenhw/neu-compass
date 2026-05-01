"""Co-op experience schema (PLAN §1.4 / §6).

One row per UGC submission. PII redaction (PLAN §6.3) is the contributor's
+ curator's responsibility BEFORE write — the schema doesn't redact, it just
records the audit trail in `redaction_audit`.

Visibility tiers (PLAN §6.4):
  0 — preview tier (公司 + 岗位 + 时长, fully public)
  1 — detail tier (interview flow + technical questions; user needs ≥1 contribution)
  2 — premium tier (NEU alumni placement; user needs ≥2 contributions + 1 invite)

The row's `visibility_level` is the MINIMUM contribution count required to
view this row. Frontend checks `users.contribution_count >= visibility_level`.
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
    """

    QUANT_FINTECH = "quant_fintech"
    BIG_TECH = "big_tech"
    BIOTECH_HEALTH = "biotech_health"
    STARTUP = "startup"
    CONSULTING = "consulting"
    OTHER = "other"


class CoopExperience(BaseModel):
    """One Co-op record. Maps 1:1 to coop_experiences table in db/init.sql."""

    model_config = ConfigDict(extra="forbid")

    # === Identity ===
    coop_id: str = Field(min_length=1)

    # === Always-shown (preview tier) ===
    company: str = Field(min_length=1)
    role: str = Field(min_length=1)
    industry: Industry | None = None
    coop_term: str | None = Field(
        default=None,
        description="e.g. 'Summer 2025', 'Spring 2026', 'Fall 2025'",
    )
    duration_months: int | None = Field(default=None, ge=1, le=8)
    related_courses: list[str] = Field(default_factory=list)

    # === Detail tier (visibility_level >= 1) ===
    interview_summary: str | None = Field(
        default=None, max_length=10_000,
        description="Already PII-redacted free text per PLAN §6.3",
    )
    technical_questions: str | None = Field(
        default=None, max_length=10_000,
        description="Redacted technical interview questions",
    )

    # === Premium tier (visibility_level >= 2) ===
    salary_range_usd: str | None = Field(
        default=None,
        description="Bucket like '$30-35/hr' — never store exact figure",
    )

    # === Provenance ===
    is_seed_data: bool = False
    visibility_level: int = Field(
        default=0, ge=0, le=2,
        description="Min contribution_count required to view this row",
    )
    contributor_user_id: str | None = Field(
        default=None,
        description="NULL for seed data (team-curated, no individual contributor)",
    )
    redaction_audit: str | None = Field(
        default=None,
        description="Who reviewed + what was redacted, free text",
    )
    created_at: datetime | None = None  # set by DB


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
    """
    key = (coop.company, coop.role, coop.coop_term)
    matching = sum(
        1 for c in corpus
        if (c.company, c.role, c.coop_term) == key
    )
    return matching < k


__all__ = ["CoopExperience", "Industry", "is_uniquely_identifying"]
