"""Pure, bounded interpretation of self-entered course codes, NOT degree eligibility.
中文：只按用户填写的课号解释已记录规则，不推断成绩、减免、审批、个人资格或开课。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


def _selection(node: RequirementNode, certain: list[DraftCourse], opened: list[DraftCourse],
               elsewhere: frozenset[str] = frozenset()):
    """Lower bound: explicit known values; upper bound: unknown credits at schema cap 12.
    `elsewhere`: pool courses already counted by another group; the caller names them in their own reason.
    中文：开放池不成为确定候选，未知学分不变成零；某维已足够时不被无关未知拖低。已算进别组的开放池课程由调用方另写原因。
    The range line appears once, at the first unmet count or credit target. 中文：范围那一行每组只写一次。
    """
    statuses, reasons, gaps = [], [], {}
    pool = [c.code for c in opened if c.code not in elsewhere]
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
                reasons.append(f"还差 {target-upper} 门（含可能候选的门数上限）。" if upper < target else
                               f"确定计入 {known} 门，其余要靠范围内可能计入的课，需项目确认。")
            else:
                reasons.append(f"还差 {target-known} 个领域。")
            if pool and dimension != "areas":
                reasons.append("范围内可能计入：" + "、".join(pool) + "；是否能算，要项目确认。")
                pool = []
    status = "missing" if "missing" in statuses else "unknown" if "unknown" in statuses else "met"
    return status, gaps, reasons


def _blocked_codes(node: RequirementNode) -> set[str]:
    """Codes no open pool may take: `course` leaves and exclusions anywhere in the plan.
    Another group's finite candidates are not blocked: a spare one may still count here (H3, 2026-10-20).
    中文：任何开放池都不收的课号：整份方案里的 `course` 叶子和任何位置的排除项。别组的有限候选不在此列，
    多修的那门仍可能计入本组（H3，2026-10-20）。
    """
    found = {node.course_code} if node.kind == "course" else set(node.excluded_course_codes)
    for child in node.children:
        found |= _blocked_codes(child)
    return found


def evaluate_draft(plan: ProgramPlan, courses: list[DraftCourse]) -> DraftResult:
    if plan.review_status != "source_checked":
        raise ValueError("Draft requires a source_checked plan")
    courses = [DraftCourse.model_validate(c.model_dump() if isinstance(c, DraftCourse) else c) for c in courses]
    if len(courses) > MAX_DRAFT_COURSES or len({c.code for c in courses}) != len(courses):
        raise ValueError("At most 20 distinct course codes are allowed")
    blocked = _blocked_codes(plan.requirements)
    by_code = {c.code: c for c in courses}
    owners = defaultdict(list)
    node_kinds = {}
    placed = set()

    def candidates(node):
        certain = [c for c in courses if c.code in node.course_codes and c.code not in node.excluded_course_codes]
        opened = [c for c in courses if c.code not in blocked and c.code not in node.course_codes
                  and (c.code.split()[0] in node.subject_codes or any(r.contains(c.code) for r in node.course_ranges))]
        return certain, opened

    def collect(node, path=(), active=True):
        node_kinds[path] = node.kind
        active = active and node.kind != "optional"
        certain, opened = candidates(node) if node.kind == "select" else ([], [])
        codes = [node.course_code] if node.kind == "course" and node.course_code in by_code else [c.code for c in certain]
        placed.update(codes)
        placed.update(c.code for c in opened)
        placed.update(c.code for c in courses if c.code in node.excluded_course_codes)
        if active and node.kind in {"course", "select"}:
            for code in codes:
                owners[code].append((path, node.label, node.kind))
        for i, child in enumerate(node.children):
            collect(child, (*path, i), active)

    collect(plan.requirements)

    def group_missing(child):
        if child.kind == "any_of":
            return child.label + "（任选其一，见子项）"
        if child.kind == "all_of":
            return child.label + "（全部子项，见下方）"
        if child.kind == "course":
            return child.label + "（" + "、".join(child.missing) + "）"
        gaps = child.shortfall
        parts = ([f"还差 {gaps['courses']} 门"] if gaps.get("courses") else [])
        if gaps.get("credits"):
            parts.append(f"按已知确定学分距目标差 {gaps['credits']} 学分")
        if gaps.get("areas"):
            parts.append(f"还差 {gaps['areas']} 个领域")
        return child.label + ("（" + "；".join(parts) + "）" if parts else "")

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
            # A pool course another active group already counts: one reason line per such group, never a ✅ here.
            # 中文：已算进另一个同时生效的组的开放池课程：每个组合成一行原因，这一组不会因此变成 ✅。
            elsewhere = defaultdict(list)
            for c in opened:
                for label in dict.fromkeys(label for other, label, _ in owners[c.code]
                                           if other != path and coactive(path, other)):
                    elsewhere[label].append(c.code)
            status, gaps, reasons = _selection(node, certain, opened,
                                               frozenset(code for codes in elsewhere.values() for code in codes))
            if status != "met":
                reasons += [f"{'、'.join(codes)} 已算进『{label}』；能不能同时算这一组，要项目确认。"
                            for label, codes in elsewhere.items()]
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
                missing = list(dict.fromkeys(item for child in applicable if child.status == "missing"
                    for item in ([group_missing(child)] if node.kind == "any_of" or child.kind in {"select", "any_of"} else child.missing or [child.label])))
                inherited_missing = sum(child.missing_omitted for child in applicable
                    if child.status == "missing" and node.kind != "any_of" and child.kind not in {"select", "any_of"})
        else:
            status, reasons = "unknown", ["未支持的规则，未自动判定。"]
        if not active:
            status, reasons, missing, gaps = None, [], [], {}
            inherited_missing = 0
        return DraftNode(kind=node.kind, label=node.label, status=status, reasons=[r[:3000] for r in reasons[:10]],
            reasons_omitted=max(0, len(reasons)-10), counted=counted, possible=possible, missing=missing[:10],
            missing_omitted=max(0, len(missing)-10) + inherited_missing, shortfall=gaps, children=children)

    root = visit(plan.requirements)
    if root.status == "met":
        root.status = "unknown"
        note = "这个方案只记录了部分规则。" if plan.coverage == "partial" else "只按已记录规则计算，不作个人学位或注册审核。"
        reasons = [note, *root.reasons]
        root.reasons_omitted += max(0, len(reasons)-10)
        root.reasons = reasons[:10]
    counts = {"met": 0, "missing": 0, "unknown": 0}

    def summarize(result, is_root=False):
        if not is_root and result.kind in {"all_of", "any_of", "select"} and result.status in counts:
            counts[result.status] += 1
        if result.kind == "any_of":
            return  # One choice group, not every alternative as a simultaneous requirement.
        for child in result.children:
            summarize(child)
    summarize(root, True)
    return DraftResult(root=root, unplaced=[c.code for c in courses if c.code not in placed], summary_counts=counts)
