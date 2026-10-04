"""Same-edition plans that explicitly name a course; NOT personal membership."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.program_plan import ProgramPlan, RequirementNode, normalize_code
from schemas.course_requisite_source import CourseRequisiteSource


def explicitly_mentions(node: RequirementNode, code: str) -> bool:
    # Prefix/range coverage and prose mentions cannot prove a specific match.
    # 中文：只匹配显式叶子/有限候选；不从标签或开放选修范围推断个人适用性。
    if node.kind == "course":
        return node.course_code == code
    if node.kind == "select":
        return code in node.course_codes and code not in node.excluded_course_codes
    return any(explicitly_mentions(child, code) for child in node.children)


class CourseProgramContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_code: str
    catalog_year: str
    schema_available: bool = False
    plans: list[ProgramPlan] = Field(default_factory=list)
    unusable_records: int = Field(default=0, ge=0)
    unreviewed_records: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("course_code")
    @classmethod
    def canonical_code(cls, value):
        return normalize_code(value)

    @field_validator("catalog_year")
    @classmethod
    def consecutive_years(cls, value):
        return CourseRequisiteSource.edition(value)

    @model_validator(mode="after")
    def scoped_context_only(self):
        if self.plans and not self.schema_available:
            raise ValueError("Unavailable context cannot carry plans")
        if len({plan.plan_id for plan in self.plans}) != len(self.plans) or len({plan.scope_key() for plan in self.plans}) != len(self.plans):
            raise ValueError("Duplicate plan identities/scopes must not become first-match context")
        for plan in self.plans:
            if (plan.catalog_year != self.catalog_year or plan.review_status != "source_checked"
                    or not explicitly_mentions(plan.requirements, self.course_code)):
                raise ValueError("Context needs a same-edition, source-checked explicit course mention")
        return self
