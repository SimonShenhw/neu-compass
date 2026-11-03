"""Exact explicit plan identity shared by chat and public links; no database imports.
中文：范围与内容版本必须同时明确；不是个人适用性或签名凭证。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.program_plan import ProgramPlan

# The web front end's plan selector, which appears once 「项目」 is set to a program with checked plans
# (web/src/pages/SearchRoute.tsx). The web words these refusals itself from `reason`; these details, for API clients,
# are its sentences for them word for word (web/src/models/chatFailure.ts).
# 中文：新前端的方案选择框（「项目」选了有核对过方案的项目才出现）；新前端按 reason 说话，这几条 detail 给 API 的调用方，和它的说法逐字相同。
PLAN_SELECTOR_LABEL = "方案"
# The web front end clears the choice on these (and only these) 409s (web/src/layout/SearchContext.tsx), so each says
# the question was not answered. 中文：新前端只在这几种 409 时清除方案选择，所以每条都说明这个问题还没有回答。
_AGAIN = "可以在「方案」里重新选择后再问，或不选方案直接再问。"
PLAN_SELECTION_MESSAGES = {
    "missing": "所选方案已不可用，这个问题还没有回答；方案选择已清除。" + _AGAIN,
    "stale": "所选方案的范围或内容版本已变化，这个问题还没有回答；方案选择已清除。" + _AGAIN,
    "draft": "所选方案尚未完成来源对照，这个问题还没有回答；方案选择已清除。" + _AGAIN,
    "unusable": "所选方案的身份、范围或格式无法确认，这个问题还没有回答；方案选择已清除。" + _AGAIN,
    "unavailable": ("暂时无法核对所选方案，这个问题还没有回答；方案选择已清除。可以先不选方案直接再问，"
                    "稍后再到「方案」里选择。"),
}


class PlanSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    program_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    plan_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")
    campus: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")
    catalog_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    pathway: Literal["standard", "align", "bridge"]
    concentration: str | None = Field(default=None, min_length=1, max_length=100)
    plan_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("catalog_year")
    @classmethod
    def edition(cls, value):
        return ProgramPlan.consecutive_years(value)

    @field_validator("concentration")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Blank concentration is not a declared scope")
        return value

    def scope_key(self):
        return (self.program_id, self.campus, self.catalog_year, self.pathway, self.concentration or "")
