"""Open candidate sets and optional branches must retain their semantics."""

import json
from pathlib import Path

import pytest

from schemas.program_plan import RequirementNode
from app.program_plan_view import rule_lines

ROOT = Path(__file__).resolve().parent.parent


def extended_plans():
    return json.loads((ROOT / "data/program_plan_seed/boston_2026_2027_extended_rules.json").read_text(encoding="utf-8"))


def test_subject_pool_preserves_exceptions_without_listing_all_courses():
    rule = RequirementNode.model_validate({
        "kind": "select", "label": "Restricted", "subject_codes": ["INFO"],
        "excluded_course_codes": ["INFO 5200"], "min_credits": 16,
    })
    assert rule.subject_codes == ["INFO"]
    assert rule.course_codes == []
    assert rule.excluded_course_codes == ["INFO 5200"]


def test_numeric_range_is_not_two_required_endpoint_courses():
    rule = RequirementNode.model_validate({
        "kind": "select", "label": "Electives", "min_credits": 12,
        "course_ranges": [{"start": "CS 5100", "end": "CS 7980"}],
        "course_codes": ["CS 7990"],
    })
    assert rule.course_ranges[0].start == "CS 5100"
    text = "\n".join(rule_lines(rule))
    assert "CS 5100–CS 7980" in text and "编号范围" in text
    assert "不证明" in text  # A numerical interval is not a list of actual offerings.


def test_optional_branch_does_not_become_a_common_requirement():
    rule = RequirementNode.model_validate({
        "kind": "optional", "label": "Co-op", "activate_when": "选择 Co-op 时",
        "children": [{"kind": "course", "label": "Preparation", "course_code": "ENCP 6000"}],
    })
    assert rule.kind == "optional"
    text = "\n".join(rule_lines(rule))
    assert "可选分支" in text and "选择 Co-op 时" in text


def test_subject_exclusions_render_separately_from_positive_candidates():
    rule = RequirementNode.model_validate({
        "kind": "select", "label": "Other", "min_credits": 12,
        "subject_codes": ["CSYE", "DAMG", "INFO", "TELE"],
        "course_codes": ["MUST 5510"], "excluded_course_codes": ["CSYE 6220", "INFO 5200"],
    })
    text = "\n".join(rule_lines(rule))
    assert "科目前缀" in text and "排除：CSYE 6220、INFO 5200" in text


@pytest.mark.parametrize("change", [
    {"subject_codes": ["INFO", "info"]}, {"subject_codes": ["INFO; DROP"]},
    {"excluded_course_codes": ["CS 5800"]}, {"excluded_course_codes": ["INFO 5200", "info5200"]},
    {"activate_when": "Not an optional branch"},
    {"course_ranges": [{"start": "CS 7000", "end": "CS 5000"}]},
    {"course_ranges": [{"start": "CS 5000", "end": "DS 7000"}]},
    {"course_ranges": [{"start": "CS 5000A", "end": "CS 7000"}]},
    {"course_ranges": [{"start": "CS 5000", "end": "CS 6000"}, {"start": "CS 6000", "end": "CS 7000"}]},
])
def test_invalid_open_pools_are_rejected(change):
    data = {"kind": "select", "label": "Open pool", "subject_codes": ["INFO"], "min_credits": 12, **change}
    with pytest.raises(ValueError):
        RequirementNode.model_validate(data)


@pytest.mark.parametrize("data", [
    {"kind": "optional", "label": "Missing activation", "children": [{"kind": "condition", "label": "C"}]},
    {"kind": "optional", "label": "Empty", "activate_when": "Chosen", "children": []},
    {"kind": "optional", "label": "Multiple", "activate_when": "Chosen", "children": [{"kind": "condition", "label": "C"}, {"kind": "condition", "label": "D"}]},
    {"kind": "optional", "label": "Wrong pool", "activate_when": "Chosen", "children": [{"kind": "condition", "label": "C"}], "course_codes": ["CS 5800"]},
    {"kind": "optional", "label": "Blank", "activate_when": " ", "children": [{"kind": "condition", "label": "C"}]},
    {"kind": "course", "label": "Wrong fields", "course_code": "CS 5800", "subject_codes": ["CS"]},
])
def test_invalid_optional_or_mixed_nodes_are_rejected(data):
    with pytest.raises(ValueError):
        RequirementNode.model_validate(data)


def test_finite_exclusions_affect_feasible_course_minimum():
    with pytest.raises(ValueError):
        RequirementNode(kind="select", label="Finite", course_codes=["CS 5800", "CS 5010"],
                        excluded_course_codes=["CS 5800"], min_courses=2)
    with pytest.raises(ValueError):
        RequirementNode(kind="select", label="Empty", course_codes=["CS 5800"],
                        excluded_course_codes=["CS 5800"], min_credits=4)


def test_open_pools_cannot_pretend_their_areas_are_fully_enumerated():
    with pytest.raises(ValueError, match="enumerated"):
        RequirementNode(kind="select", label="Not finite", subject_codes=["CS"],
            course_codes=["CS 5100"], min_courses=1, min_areas=1, areas={"A": ["CS 5100"]})


def test_exclusions_cannot_remove_every_number_in_a_small_range():
    with pytest.raises(ValueError, match="every candidate"):
        RequirementNode(kind="select", label="Empty range", min_credits=4,
            course_ranges=[{"start": "CS 5100", "end": "CS 5101"}],
            excluded_course_codes=["CS 5100", "CS 5101"])


def test_extended_bundle_remains_partial_standard_and_has_scoped_concentrations():
    from schemas.program_plan import ProgramPlan
    from schemas.program_source import SourceCapture
    plans = [ProgramPlan.model_validate(item) for item in extended_plans()]
    assert len(plans) == len({plan.scope_key() for plan in plans}) == 5
    assert all(plan.coverage == "partial" and plan.pathway == "standard" for plan in plans)
    assert {plan.concentration for plan in plans if plan.program_id == "ds-ms"} == {
        "computer-science", "data-design-visualization", "engineering-theory-modeling"}
    manifest = [SourceCapture.model_validate(item) for item in json.loads((ROOT / "data/program_plan_seed/boston_2026_2027_source_manifest.json").read_text())]
    assert len(manifest) == 3
    by_hash = {item.sha256: item for item in manifest}
    for plan in plans:
        source = by_hash[plan.source_html_sha256]
        assert (source.url, source.catalog_year, source.captured_at.date()) == (plan.source_url, plan.catalog_year, plan.captured_on)


def test_real_breadth_and_exit_semantics_are_not_flattened():
    from schemas.program_plan import ProgramPlan
    plans = [ProgramPlan.model_validate(item) for item in extended_plans()]
    cs = plans[0]
    breadth = cs.requirements.children[1]
    assert (breadth.min_courses, breadth.min_credits, breadth.min_areas) == (3, 12, 2)
    assert len(breadth.course_codes) == 25 and len(breadth.areas) == 3
    assert "CS 5500" not in [leaf.course_code for leaf in cs.requirements.children[0].children]
    ds_groups = [[node.min_credits for node in plan.requirements.children if node.kind == "select"] for plan in plans if plan.program_id == "ds-ms"]
    assert ds_groups == [[16], [8, 8], [4, 12]]
    info = plans[-1]
    exits = info.requirements.children[1]
    assert exits.kind == "any_of" and len(exits.children) == 3
    assert [[node.course_code for node in branch.children if node.kind == "course"] for branch in exits.children] == [[], ["INFO 7945"], ["INFO 7945", "INFO 7990"]]
    assert [[node.min_credits for node in branch.children if node.kind == "select"] for branch in exits.children] == [[16, 12], [12, 12], [8, 12]]
    for plan in plans:
        assert plan.requirements.children[-1].kind == "unmodeled"
        optional = [node for node in plan.requirements.children if node.kind == "optional"]
        assert optional and all(node.activate_when for node in optional)
