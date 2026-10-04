"""Selected-plan evidence transport; failure states cannot contain usable rules."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.program_plan import ProgramPlan
from schemas.program_policy import (PlanPolicyLink, PolicyEvidence, PolicyFragment,
    normalized_text, paragraph_hash)


class PolicyScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    program_id: str = Field(min_length=1, max_length=64)
    campus: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")
    catalog_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    pathway: Literal["standard", "align", "bridge"]
    concentration: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("catalog_year")
    @classmethod
    def edition(cls, value):
        return ProgramPlan.consecutive_years(value)

    @field_validator("program_id", "concentration")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Policy scope cannot be blank")
        return value

    def scope_key(self):
        return (self.program_id, self.campus, self.catalog_year, self.pathway, self.concentration or "")

    @classmethod
    def from_plan(cls, plan: ProgramPlan):
        return cls(**{key: getattr(plan, key) for key in cls.model_fields})


class PolicyFragmentOut(PolicyFragment):
    source_paragraph: str = Field(min_length=1, max_length=20_000)

    @model_validator(mode="after")
    def paragraph_matches(self):
        if (self.source_paragraph != normalized_text(self.source_paragraph)
                or paragraph_hash(self.source_paragraph) != self.paragraph_sha256):
            raise ValueError("Displayed policy source block must match its fingerprint")
        return self


class PolicyEvidenceOut(PolicyEvidence):
    fragments: list[PolicyFragmentOut] = Field(min_length=1, max_length=30)


class ProgramPolicyView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")
    scope: PolicyScope
    plan_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["ready", "not_linked", "draft", "stale", "unavailable", "unusable"]
    coverage: Literal["selected_fragments_only"] = "selected_fragments_only"
    link: PlanPolicyLink | None = None
    checked_by: str | None = Field(default=None, min_length=1, max_length=100)
    checked_on: date | None = None
    policies: list[PolicyEvidenceOut] = Field(default_factory=list, max_length=20)
    warnings: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def honest_state(self):
        if self.status != "ready":
            if self.policies or self.link or self.checked_by is not None or self.checked_on is not None:
                raise ValueError("Non-ready policy view cannot contain usable evidence")
            return self
        if not self.link or not self.policies or not self.checked_by or not self.checked_by.strip() or not self.checked_on:
            raise ValueError("Ready evidence needs an explicit link, policies and review record")
        if (self.link.plan_id != self.plan_id or self.link.scope_key() != self.scope.scope_key()
                or self.link.plan_content_sha256 != self.plan_content_sha256):
            raise ValueError("Policy view/link identity or revision mismatch")
        ids = [p.policy_id for p in self.policies]
        if len(set(ids)) != len(ids) or ids != self.link.policy_ids or len({p.source.url for p in self.policies}) != len(ids):
            raise ValueError("Policy view must preserve exactly the selected references")
        for policy in self.policies:
            if (policy.source.catalog_year != self.scope.catalog_year
                    or policy.authority not in {"university", self.link.home_college}
                    or self.checked_on < policy.source.captured_at.date()):
                raise ValueError("Policy view source scope/review mismatch")
        return self
