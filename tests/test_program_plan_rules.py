"""Semantic rule/schema checks, not student eligibility or live source validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from schemas.program_plan import ProgramPlan, RequirementNode

ROOT = Path(__file__).resolve().parent.parent


def plan_data():
    return json.loads((ROOT / "data/program_plan_seed/boston_2026_2027_core_fragments.json").read_text(encoding="utf-8"))[0]


def leaf(code="CS 5800"):
    return {"kind": "course", "label": "Recorded course", "course_code": code}


@pytest.mark.parametrize("rule", [
    {"kind": "course", "label": "Missing code"},
    {"kind": "course", "label": "Bad code", "course_code": "FAKE 999"},
    {"kind": "all_of", "label": "Empty"},
    {"kind": "any_of", "label": "One", "children": [leaf()]},
    {"kind": "any_of", "label": "Flattened", "children": [leaf(), leaf("CS 5010")], "course_code": "CS 5800"},
    {"kind": "unmodeled", "label": "Pretending to be code", "course_code": "CS 5800"},
    {"kind": "condition", "label": "Pretending to be group", "children": [leaf()]},
    {"kind": "select", "label": "No minimum", "course_codes": ["CS 5800"]},
    {"kind": "select", "label": "Impossible", "course_codes": ["CS 5800"], "min_courses": 2},
    {"kind": "select", "label": "Duplicate", "course_codes": ["cs5800", "CS 5800"], "min_courses": 1},
    {"kind": "select", "label": "Not pool", "course_codes": ["CS 5800"], "min_courses": 1, "areas": {"a": ["CS 5010"]}},
    {"kind": "select", "label": "Impossible areas", "course_codes": ["CS 5800"], "min_courses": 1, "min_areas": 2, "areas": {"a": ["CS 5800"]}},
    {"kind": "course", "label": " ", "course_code": "CS 5800"},
])
def test_invalid_or_ambiguous_rule_shapes_rejected(rule):
    with pytest.raises(ValueError):
        RequirementNode.model_validate(rule)


def test_and_or_nested_relationships_survive_serialization():
    rule = RequirementNode.model_validate({"kind": "all_of", "label": "AND", "children": [
        leaf(), {"kind": "any_of", "label": "OR", "children": [leaf("EECE 7205"), leaf("CS 5010")]},
    ]})
    back = RequirementNode.model_validate_json(rule.model_dump_json())
    assert back == rule
    assert back.children[1].kind == "any_of"
    assert back.children[1].children[0].course_code == "EECE 7205"


def test_course_and_credit_and_area_minima_are_separate_constraints():
    rule = RequirementNode(kind="select", label="Breadth", course_codes=["CS 5100", "CS 5500", "CS 5800"],
        min_courses=3, min_credits=12, min_areas=2, areas={"a": ["CS 5100"], "b": ["CS 5500", "CS 5800"]})
    assert (rule.min_courses, rule.min_credits, rule.min_areas) == (3, 12, 2)


@pytest.mark.parametrize("field,value", [
    ("catalog_year", "2026"), ("catalog_year", "2026-2028"), ("source_catalog_year", "2025-2026"),
    ("campus", "Boston"), ("pathway", "ordinary"), ("source_url", "javascript:alert(1)"),
    ("source_url", "https://catalog.northeastern.edu.evil.test/graduate/cs/"),
    ("source_url", "https://catalog.northeastern.edu/graduate/cs/?redirect=evil"),
    ("source_url", "https://catalog.northeastern.edu/archive/2025-2026/graduate/cs/"),
    ("checked_by", None), ("checked_by", " "), ("checked_on", "2026-09-29"),
    ("coverage", "complete"), ("source_excerpt", "\n "),
])
def test_invalid_scope_or_overclaimed_coverage_rejected(field, value):
    data = plan_data()
    data[field] = value
    with pytest.raises(ValueError):
        ProgramPlan.model_validate(data)


def test_schema_budget_rejects_excessive_depth():
    data = plan_data()
    node = leaf()
    for _ in range(9):
        node = {"kind": "all_of", "label": "Deep", "children": [leaf("CS 5010"), node]}
    data["requirements"] = node
    with pytest.raises(ValueError, match="budget"):
        ProgramPlan.model_validate(data)


def test_schema_budget_rejects_excessive_node_count():
    data = plan_data()
    data["requirements"] = {"kind": "all_of", "label": "Many", "children": [
        {"kind": "all_of", "label": "Subgroup", "children": [leaf() for _ in range(30)]} for _ in range(4)
    ]}
    with pytest.raises(ValueError, match="budget"):
        ProgramPlan.model_validate(data)


def test_area_minimum_cannot_double_count_a_course_into_multiple_areas():
    with pytest.raises(ValueError, match="partition"):
        RequirementNode(kind="select", label="Overlapping", course_codes=["CS 5100", "CS 5500"],
            min_courses=2, min_areas=2, areas={"a": ["CS 5100"], "b": ["CS 5100", "CS 5500"]})


def test_bundled_fragments_have_honest_source_scope_and_do_not_upgrade_legacy_seeds():
    raw = json.loads((ROOT / "data/program_plan_seed/boston_2026_2027_core_fragments.json").read_text(encoding="utf-8"))
    plans = [ProgramPlan.model_validate(item) for item in raw]
    assert len(plans) == 3
    assert all(plan.coverage == "partial" and plan.pathway == "standard" for plan in plans)
    assert all(plan.campus == "boston" and plan.catalog_year == "2026-2027" for plan in plans)
    ds = next(plan for plan in plans if plan.program_id == "ds-ms")
    choices = [node for node in ds.requirements.children if node.kind == "any_of"]
    assert [[node.course_code for node in group.children] for group in choices] == [["CS 5800", "EECE 7205"], ["CS 6140", "EECE 5644"]]
    info = next(plan for plan in plans if plan.program_id == "info-ms")
    assert info.concentration == "general"
    assert [node.course_code for node in info.requirements.children[0].children] == ["INFO 5100", "INFO 5101"]
    cs = next(plan for plan in plans if plan.program_id == "cs-ms")
    assert "CS 5001" not in cs.model_dump_json()  # Align is not silently imported into standard core.
