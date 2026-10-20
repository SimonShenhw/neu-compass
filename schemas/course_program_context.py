"""Same-edition plans and bounded placements; NOT personal membership."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.program_plan import CourseRange, ProgramPlan, RequirementNode, normalize_code
from schemas.course_requisite_source import CourseRequisiteSource


class CoursePlacement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: list[str] = Field(min_length=1, max_length=8)
    relation: Literal["required", "any_of_option", "select_candidate", "optional_branch", "excluded", "open_pool"]
    under_any_of: bool = False
    activate_when: list[str] = Field(default_factory=list, max_length=8)
    min_courses: int | None = Field(default=None, ge=1, le=100)
    min_credits: int | None = Field(default=None, ge=1, le=200)
    min_areas: int | None = Field(default=None, ge=1, le=40)
    areas: list[str] = Field(default_factory=list, max_length=40)
    subject_codes: list[str] = Field(default_factory=list, max_length=20)
    course_ranges: list[CourseRange] = Field(default_factory=list, max_length=20)

    @field_validator("path", "areas")
    @classmethod
    def bounded_labels(cls, values):
        if any(not value or len(value) > 300 for value in values):
            raise ValueError("Placement labels must be bounded")
        return values

    @field_validator("activate_when")
    @classmethod
    def bounded_conditions(cls, values):
        if any(not value.strip() or len(value) > 500 for value in values):
            raise ValueError("Placement activation must be bounded and explicit")
        return values


def explicitly_named(root: RequirementNode, code: str) -> bool:
    """Shared whole-document mention test, including exclusions and optional branches.
    中文：点名含排除名单，不等于显式允许计入；不依赖 placement 的四项输出上限。
    """
    code = normalize_code(code)
    def named(node):
        return (node.course_code == code or code in node.course_codes or code in node.excluded_course_codes
                or any(named(child) for child in node.children))
    return named(root)


def course_placements(root: RequirementNode, code: str) -> tuple[list[CoursePlacement], int]:
    """Leaf, candidate, exclusion, then open pool; a named code never also gets an open-pool claim.
    中文：保留 OR／可选条件两条独立轴，不把候选或可选分支变成共同必修。
    """
    code = normalize_code(code)
    is_named = explicitly_named(root, code)
    found = []

    def visit(node, path=(), under_any=False, conditions=()):
        here = [*path, node.label[:300]]
        common = {"path": here, "under_any_of": under_any, "activate_when": list(conditions)}
        if node.kind == "course" and node.course_code == code:
            relation = "any_of_option" if under_any else "optional_branch" if conditions else "required"
            found.append((0, CoursePlacement(**common, relation=relation)))
        elif node.kind == "select":
            relation = ("excluded" if code in node.excluded_course_codes else
                        "select_candidate" if code in node.course_codes else
                        "open_pool" if not is_named and (code.split()[0] in node.subject_codes
                            or any(interval.contains(code) for interval in node.course_ranges)) else None)
            if relation:
                found.append(({"select_candidate": 1, "excluded": 2, "open_pool": 3}[relation], CoursePlacement(
                    **common, relation=relation, min_courses=node.min_courses, min_credits=node.min_credits,
                    min_areas=node.min_areas, areas=[name[:300] for name, codes in node.areas.items() if code in codes],
                    subject_codes=node.subject_codes, course_ranges=[item.model_dump() for item in node.course_ranges])))
        for child in node.children:
            visit(child, here, under_any or node.kind == "any_of",
                  (*conditions, node.activate_when) if node.kind == "optional" else conditions)

    visit(root)
    ordered = [item for _, item in sorted(found, key=lambda pair: pair[0])]
    return ordered[:4], max(0, len(ordered) - 4)


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
