"""Pure, bounded interpretation of self-entered course codes, NOT degree eligibility.
中文：只按用户填写的课号解释已记录规则，不推断成绩、减免、审批、个人资格或开课。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.course_program_context import explicitly_named
from schemas.program_plan import ProgramPlan, RequirementNode, normalize_code

MAX_DRAFT_COURSES = 20
Status = Literal["met", "missing", "unknown", "not_evaluated"]


class DraftCourse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_id: str = Field(min_length=1, max_length=200)
    code: str
    name: str = Field(min_length=1, max_length=500)
    credits: int | None = Field(default=None, strict=True, ge=0, le=12)

    @field_validator("code")
    @classmethod
    def canonical_code(cls, value: str) -> str:
        return normalize_code(value)


class DraftNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=1000)
    status: Status | None
    reasons: list[str] = Field(default_factory=list, max_length=10)
    reasons_omitted: int = Field(default=0, ge=0)
    counted: list[str] = Field(default_factory=list, max_length=MAX_DRAFT_COURSES)
    possible: list[str] = Field(default_factory=list, max_length=MAX_DRAFT_COURSES)
    missing: list[str] = Field(default_factory=list, max_length=10)
    missing_omitted: int = Field(default=0, ge=0)
    shortfall: dict[str, int] = Field(default_factory=dict)
    children: list[DraftNode] = Field(default_factory=list, max_length=40)


class DraftResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    root: DraftNode
    unplaced: list[str] = Field(default_factory=list, max_length=MAX_DRAFT_COURSES)
    summary_counts: dict[str, int]


def _selection(node: RequirementNode, certain: list[DraftCourse], opened: list[DraftCourse]):
    """Lower bound: explicit known values; upper bound: unknown credits at schema cap 12.
    中文：开放池不成为确定候选，未知学分不变成零；某维已足够时不被无关未知拖低。
    """
    statuses, reasons, gaps = [], [], {}
    for dimension, target, known, upper in (
        ("courses", node.min_courses, len(certain), len(certain) + len(opened)),
        ("credits", node.min_credits, sum(c.credits or 0 for c in certain),
         sum(c.credits if c.credits is not None else 12 for c in [*certain, *opened])),
        ("areas", node.min_areas, sum(any(c.code in codes for c in certain) for codes in node.areas.values()),
         sum(any(c.code in codes for c in certain) for codes in node.areas.values())),
    ):
        if target is None:
            continue
        gaps[dimension] = max(0, target - (upper if dimension == "courses" else known))
        status = "met" if known >= target else "missing" if upper < target else "unknown"
        statuses.append(status)
        if status != "met":
            if dimension == "credits":
                reasons.append(f"按已知确定学分距目标差 {max(0, target-known)} 学分；不是确认还需补修的学分。")
                if any(c.credits is None for c in [*certain, *opened]):
                    reasons.append("学分未知：" + "、".join(c.code for c in [*certain, *opened] if c.credits is None))
            elif dimension == "courses":
                reasons.append(f"还差 {max(0, target-upper)} 门（含可能候选的门数上限）。")
            else:
                reasons.append(f"还差 {target-known} 个领域。")
            if opened and dimension != "areas":
                reasons.append("开放池可能计入：" + "、".join(c.code for c in opened) + "；是否能算，要项目确认。")
    status = "missing" if "missing" in statuses else "unknown" if "unknown" in statuses else "met"
    return status, gaps, reasons


def evaluate_draft(plan: ProgramPlan, courses: list[DraftCourse]) -> DraftResult:
    if plan.review_status != "source_checked":
        raise ValueError("Draft requires a source_checked plan")
    courses = [DraftCourse.model_validate(c.model_dump() if isinstance(c, DraftCourse) else c) for c in courses]
    if len(courses) > MAX_DRAFT_COURSES or len({c.code for c in courses}) != len(courses):
        raise ValueError("At most 20 distinct course codes are allowed")
    named = {c.code for c in courses if explicitly_named(plan.requirements, c.code)}
    by_code = {c.code: c for c in courses}
    owners = defaultdict(list)
    node_kinds = {}
    placed = set()

    def candidates(node):
        certain = [c for c in courses if c.code in node.course_codes and c.code not in node.excluded_course_codes]
        opened = [c for c in courses if c.code not in named and c.code not in node.excluded_course_codes
                  and (c.code.split()[0] in node.subject_codes or any(r.contains(c.code) for r in node.course_ranges))]
        return certain, opened

    def collect(node, path=(), active=True):
        node_kinds[path] = node.kind
        active = active and node.kind != "optional"
        certain, opened = candidates(node) if node.kind == "select" else ([], [])
        codes = [node.course_code] if node.kind == "course" and node.course_code in by_code else [c.code for c in certain]
        placed.update(codes)
        placed.update(c.code for c in opened)
        if active and node.kind in {"course", "select"}:
            for code in codes:
                owners[code].append((path, node.label, node.kind))
        for i, child in enumerate(node.children):
            collect(child, (*path, i), active)

    collect(plan.requirements)

    def coactive(first, second):
        common = ()
        for left, right in zip(first, second):
            if left != right:
                return node_kinds[common] != "any_of"
            common = (*common, left)
        return True

    def visit(node, path=(), active=True):
        children = [visit(child, (*path, i), active and node.kind != "optional") for i, child in enumerate(node.children)]
        reasons, counted, possible, missing, gaps = [], [], [], [], {}
        inherited_missing = 0
        if node.kind == "course":
            counted = [node.course_code] if node.course_code in by_code else []
            status = "met" if counted else "missing"
            missing = [] if counted else [node.course_code]
            if active and counted and sum(kind == "course" and coactive(path, other) for other, _, kind in owners[node.course_code]) > 1:
                status = "unknown"
                reasons.append(f"{node.course_code} 重复计入多个规则位置；方案没有记录能否两边都算。")
        elif node.kind == "select":
            certain, opened = candidates(node)
            counted = [c.code for c in certain]
            possible = [c.code for c in [*certain, *opened] if c in opened or c.credits is None]
            status, gaps, reasons = _selection(node, certain, opened)
            shared = [c for c in certain if any(other != path and coactive(path, other) for other, _, _ in owners[c.code])]
            if active and status == "met" and shared:
                alone = [c for c in certain if c not in shared]
                if _selection(node, alone, opened)[0] != "met":
                    status = "unknown"
                    for c in shared:
                        labels = list(dict.fromkeys(label for other, label, _ in owners[c.code] if other != path and coactive(path, other)))
                        reasons.append(f"{c.code} 重复计入『{'、'.join(labels)}』；能否两边都算，方案没有记录。")
            for c in courses:
                if c.code in node.excluded_course_codes:
                    reasons.append(f"{c.code} 在这一组被明确排除，不算。")
            if status == "missing":
                missing = [code for code in node.course_codes if code not in by_code and code not in node.excluded_course_codes]
        elif node.kind == "optional":
            status = "not_evaluated"
            reasons = ["可选分支，不自动判断：" + node.activate_when]
        elif node.kind in {"condition", "unmodeled"}:
            status = "unknown"
            reasons = [("文字条件，草案不判断：" if node.kind == "condition" else "方案里这部分没有建模：") + node.label]
        elif node.kind in {"all_of", "any_of"}:
            applicable = [child for child in children if child.status != "not_evaluated"]
            states = [child.status for child in applicable]
            if not states:
                status, reasons = "unknown", ["只有可选分支，没有可自动计算的规则。"]
            elif node.kind == "all_of":
                status = "missing" if "missing" in states else "unknown" if "unknown" in states else "met"
            else:
                status = "met" if "met" in states else "unknown" if "unknown" in states else "missing"
            counted = list(dict.fromkeys(code for child in applicable for code in child.counted))
            possible = list(dict.fromkeys(code for child in applicable for code in child.possible))
            if status != "met":
                missing = [item for child in applicable if child.status == "missing" for item in (child.missing or [child.label])]
                inherited_missing = sum(child.missing_omitted for child in applicable if child.status == "missing")
        else:
            status, reasons = "unknown", ["未支持的规则，未自动判定。"]
        if not active:
            status, reasons, missing, gaps = None, [], [], {}
            inherited_missing = 0
        return DraftNode(kind=node.kind, label=node.label, status=status, reasons=[r[:3000] for r in reasons[:10]],
            reasons_omitted=max(0, len(reasons)-10), counted=counted, possible=possible, missing=missing[:10],
            missing_omitted=max(0, len(missing)-10) + inherited_missing, shortfall=gaps, children=children)

    root = visit(plan.requirements)
    if plan.coverage == "partial" and root.status == "met":
        root.status = "unknown"
        root.reasons = ["这个方案只记录了部分规则。", *root.reasons][:10]
    counts = {"met": 0, "missing": 0, "unknown": 0}

    def summarize(result, is_root=False):
        if not is_root and result.kind in {"all_of", "any_of", "select"} and result.status in counts:
            counts[result.status] += 1
        for child in result.children:
            summarize(child)
    summarize(root, True)
    return DraftResult(root=root, unplaced=[c.code for c in courses if c.code not in placed], summary_counts=counts)
