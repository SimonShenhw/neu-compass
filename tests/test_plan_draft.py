"""Deterministic draft rules; no transcript, grades, eligibility or network inference."""

import importlib

import pytest

from schemas.program_plan import RequirementNode
from tests.test_program_plan_links import plans


def node(kind, label="Synthetic", **fields):
    return RequirementNode(kind=kind, label=label, **fields)


def course(code="CS 5001", credits=4):
    return {"course_id": code.replace(" ", "-"), "code": code, "name": "Synthetic " + code, "credits": credits}


def evaluate(rule, courses=(), *, partial=False):
    module = importlib.import_module("schemas.plan_draft")
    plan = plans()[0].model_copy(update={"requirements": rule, "coverage": "partial" if partial else "complete"})
    return module.evaluate_draft(plan, [module.DraftCourse(**c) for c in courses])


def evaluate_rule(rule, courses=()):
    """Assert internal rule truth independently of the always-conservative plan root.

    L7 changes the public root policy, not course/select/AND/OR semantics. Use a valid
    partial plan container so the old affirmative rule assertions still exercise a child.
    """
    from schemas.program_plan import ProgramPlan

    module = importlib.import_module("schemas.plan_draft")
    wrapper = node("all_of", label="Unit rule container", children=[rule, node("condition", label="Personal conditions")])
    plan = ProgramPlan.model_validate({**plans()[0].model_dump(), "coverage": "partial", "requirements": wrapper.model_dump()})
    return module.evaluate_draft(plan, [module.DraftCourse(**c) for c in courses]).root.children[0]


@pytest.mark.parametrize("present,status", [(False, "missing"), (True, "met")])
def test_course_leaf_and_normalization(present, status):
    result = evaluate_rule(node("course", course_code="cs5001"), [course("cs5001")] if present else [])
    assert result.status == status
    assert result.counted == (["CS 5001"] if present else [])
    assert result.missing == ([] if present else ["CS 5001"])


@pytest.mark.parametrize("kind,courses,status", [("all_of", [], "missing"), ("all_of", [course()], "unknown"),
    ("any_of", [], "unknown"), ("any_of", [course()], "met")])
def test_composite_precedence(kind, courses, status):
    rule = node(kind, children=[node("course", course_code="CS 5001"), node("condition", label="GPA unknown")])
    assert evaluate_rule(rule, courses).status == status


def test_all_met_any_all_missing_and_optional_only_have_explicit_results():
    children = [node("course", course_code="CS 5001"), node("course", course_code="CS 5002")]
    assert evaluate_rule(node("all_of", children=children), [course(), course("CS 5002")]).status == "met"
    assert evaluate_rule(node("any_of", children=children)).status == "missing"
    opt = node("optional", activate_when="Thesis approval", children=[children[0]])
    result = evaluate(node("all_of", children=[opt, opt]), [course()])
    assert result.root.status == "unknown"  # Optional-only never creates an affirmative empty AND.
    assert result.root.children[0].status == "not_evaluated"
    assert result.root.children[0].children[0].status is None
    assert result.root.children[0].children[0].counted == ["CS 5001"]


def test_optional_does_not_count_as_owner_or_participate_in_summary():
    selected = node("select", course_codes=["CS 5001"], min_courses=1)
    optional = node("optional", activate_when="Only if selected", children=[selected])
    result = evaluate(node("all_of", children=[selected, optional]), [course()])
    assert result.root.status == "unknown" and result.root.children[0].status == "met"
    assert result.summary_counts == {"met": 1, "missing": 0, "unknown": 0}
    assert result.root.children[1].status == "not_evaluated"


@pytest.mark.parametrize("kind,phrase", [("condition", "GPA"), ("unmodeled", "没有建模")])
def test_text_conditions_and_unmodeled_never_pass(kind, phrase):
    result = evaluate(node(kind, label="GPA"), [course()])
    assert result.root.status == "unknown" and phrase in " ".join(result.root.reasons)


@pytest.mark.parametrize("credits,status,gap", [(4, "met", 0), (0, "missing", 4), (None, "unknown", 4)])
def test_credit_none_zero_and_known_are_distinct(credits, status, gap):
    result = evaluate_rule(node("select", course_codes=["CS 5001"], min_credits=4), [course(credits=credits)])
    assert result.status == status and result.shortfall["credits"] == gap
    if credits is None:
        assert "学分未知" in " ".join(result.reasons) and result.possible == ["CS 5001"]


def test_unknown_credit_upper_bound_can_prove_missing_and_known_suffices():
    pool = ["CS 5001", "CS 5002"]
    assert evaluate(node("select", course_codes=pool, min_credits=20), [course(credits=None)]).root.status == "missing"
    result = evaluate_rule(node("select", course_codes=pool, min_credits=4), [course(), course("CS 5002", None)])
    assert result.status == "met"


@pytest.mark.parametrize("courses,status,gap", [([], "missing", 2), ([course()], "missing", 1),
    ([course(), course("CS 5999")], "unknown", 0), ([course(), course("CS 5002")], "met", 0)])
def test_count_threshold_with_open_pool(courses, status, gap):
    result = evaluate_rule(node("select", course_codes=["CS 5001", "CS 5002"], subject_codes=["CS"], min_courses=2), courses)
    assert result.status == status and result.shortfall["courses"] == gap


def test_named_anywhere_including_exclusions_cannot_become_open_pool():
    root = node("all_of", children=[node("select", label="open", subject_codes=["CS"], min_courses=1),
        node("select", label="finite", course_codes=["CS 5001", "CS 5002"], excluded_course_codes=["CS 5001"], min_courses=1)])
    result = evaluate(root, [course()])
    assert result.root.children[0].status == "missing" and result.root.children[0].possible == []
    assert "明确排除" in " ".join(result.root.children[1].reasons)
    assert result.unplaced == []  # M2: explicitly excluded is mentioned, not eligible.


def test_shared_named_helper_does_not_use_truncated_four_placements():
    import schemas.course_program_context as shared

    leaf = node("course", course_code="CS 5001")
    root = node("all_of", children=[leaf] * 5 + [node("select", subject_codes=["CS"], min_courses=1)])
    assert shared.explicitly_named(root, "CS 5001") is True
    assert shared.explicitly_named(root, "CS 5999") is False
    result = evaluate(root, [course(), course("CS 5999")])
    assert result.root.children[-1].possible == ["CS 5999"]
    assert result.root.children[-1].status == "unknown"


def test_open_ranges_credits_and_excluded_courses():
    pool = node("select", course_ranges=[{"start": "CS 5100", "end": "CS 5999"}],
                excluded_course_codes=["CS 5200"], min_credits=4)
    result = evaluate(pool, [course("CS 5100"), course("CS 5200"), course("CS 6000")])
    assert result.root.status == "unknown" and result.root.possible == ["CS 5100"]
    assert result.unplaced == ["CS 6000"]


@pytest.mark.parametrize("codes,status,areas", [(["CS 5001", "CS 5002"], "missing", 1),
    (["CS 5001", "DS 5001"], "met", 0)])
def test_areas_are_counted_by_partition_not_course_count(codes, status, areas):
    pool = node("select", course_codes=["CS 5001", "CS 5002", "DS 5001"], min_courses=2, min_areas=2,
                areas={"CS": ["CS 5001", "CS 5002"], "DS": ["DS 5001"]})
    result = evaluate_rule(pool, [course(c) for c in codes])
    assert result.status == status and result.shortfall["areas"] == areas


@pytest.mark.parametrize("extra,status", [(False, "unknown"), (True, "met")])
def test_cross_group_dependency_removed_then_recomputed(extra, status):
    first = node("select", label="first", course_codes=["CS 5001", "CS 5002"], min_courses=1)
    other = node("course", label="other", course_code="CS 5001")
    result = evaluate(node("all_of", children=[first, other]), [course(), *([course("CS 5002")] if extra else [])])
    assert result.root.children[0].status == status
    if not extra:
        assert "重复计入" in " ".join(result.root.children[0].reasons)


def test_duplicate_leaves_unknown_and_ancestors_are_not_counted_twice():
    leaf = node("course", course_code="CS 5001")
    result = evaluate(node("all_of", children=[leaf, leaf]), [course()])
    assert all(c.status == "unknown" for c in result.root.children)
    simple = evaluate(node("all_of", children=[leaf, node("condition", label="unknown")]), [course()])
    assert simple.root.children[0].status == "met"


def test_partial_root_never_met_summary_excludes_root_and_optional():
    root = node("all_of", children=[node("course", course_code="CS 5001"), node("course", course_code="CS 5002")])
    result = evaluate(root, [course(), course("CS 5002")], partial=True)
    assert result.root.status == "unknown" and "部分规则" in " ".join(result.root.reasons)
    assert result.summary_counts == {"met": 0, "missing": 0, "unknown": 0}


def test_missing_lists_and_reasons_are_bounded_not_silently_dropped():
    root = node("all_of", children=[node("course", course_code=f"CS {5000+i}") for i in range(20)])
    result = evaluate(root).root
    assert len(result.missing) == 10 and result.missing_omitted == 10
    assert len(result.reasons) <= 10


def test_input_cap_duplicate_codes_and_strict_credit_types():
    mod = importlib.import_module("schemas.plan_draft")
    for bad in [True, -1, 13, "4", 4.5]:
        with pytest.raises(ValueError):
            mod.DraftCourse(**course(credits=bad))
    rule = node("condition", label="unknown")
    with pytest.raises(ValueError):
        evaluate(rule, [course(f"CS {5000+i}") for i in range(21)])
    with pytest.raises(ValueError):
        evaluate(rule, [course(), course("cs5001")])
    plan = plans()[0].model_copy(update={"review_status": "draft"})
    with pytest.raises(ValueError):
        mod.evaluate_draft(plan, [])


def test_result_extra_fields_rejected_and_inputs_unchanged():
    mod = importlib.import_module("schemas.plan_draft")
    plan = plans()[0]
    before = plan.model_dump_json()
    data = [mod.DraftCourse(**course())]
    result = mod.evaluate_draft(plan, data)
    assert plan.model_dump_json() == before and data[0].code == "CS 5001"
    with pytest.raises(ValueError):
        mod.DraftResult.model_validate({**result.model_dump(), "can_graduate": True})


def test_nested_missing_omissions_propagate_without_losing_counts():
    inner = node("all_of", children=[node("course", course_code=f"CS {5000+i}") for i in range(20)])
    outer = node("all_of", children=[inner, node("course", course_code="CS 5999")])
    result = evaluate(outer).root
    assert len(result.missing) == 10 and result.missing_omitted == 11


def test_satisfied_or_does_not_promote_unused_alternatives_to_group_missing():
    root = node("any_of", children=[node("course", course_code="CS 5001"), node("course", course_code="CS 5002")])
    result = evaluate_rule(root, [course()])
    assert result.status == "met" and result.missing == [] and result.missing_omitted == 0


def test_select_must_meet_each_dimension_and_both_overlap_owners_recompute():
    first = node("select", label="first", course_codes=["CS 5001", "CS 5002"], min_courses=2, min_credits=8)
    result = evaluate(first, [course(credits=0), course("CS 5002", 4)]).root
    assert result.status == "missing" and result.shortfall == {"courses": 0, "credits": 4}
    second = node("select", label="second", course_codes=["CS 5001", "CS 5003"], min_credits=4)
    overlap = evaluate(node("all_of", children=[first, second]), [course(), course("CS 5002")]).root
    assert [c.status for c in overlap.children] == ["unknown", "unknown"]


def test_unknown_rule_kind_fails_closed_and_optional_activation_is_preserved():
    future = node("condition", label="future").model_copy(update={"kind": "future_rule"})
    assert evaluate(future).root.status == "unknown"
    opt = node("optional", activate_when="Approval required", children=[node("course", course_code="CS 5001")])
    result = evaluate(opt, [course()]).root
    assert result.status == "not_evaluated" and "Approval required" in result.reasons[0]


def test_all_shared_surplus_candidates_are_removed_together_for_reuse_audit():
    first = node("select", label="first", course_codes=["CS 5001", "CS 5002"], min_courses=1)
    second = node("select", label="second", course_codes=["CS 5001", "CS 5002"], min_courses=1)
    result = evaluate(node("all_of", children=[first, second]), [course(), course("CS 5002")]).root
    assert [c.status for c in result.children] == ["unknown", "unknown"]


def test_reason_cap_counts_omitted_exclusions():
    excluded = [f"CS {5000+i}" for i in range(20)]
    pool = node("select", course_codes=[*excluded, "CS 5999"], excluded_course_codes=excluded, min_courses=1)
    result = evaluate(pool, [course(code) for code in excluded]).root
    assert len(result.reasons) == 10 and result.reasons_omitted == 11


def test_same_course_in_mutually_exclusive_or_exits_is_not_double_counting():
    leaf = node("course", course_code="CS 5001")
    result = evaluate_rule(node("any_of", children=[leaf, leaf]), [course()])
    assert result.status == "met" and all(c.status == "met" for c in result.children)
    first = node("select", course_codes=["CS 5001"], min_courses=1)
    second = node("select", course_codes=["CS 5001"], min_credits=4)
    result = evaluate_rule(node("any_of", children=[first, second]), [course()])
    assert result.status == "met" and all(c.status == "met" for c in result.children)


def test_or_exit_does_not_hide_reuse_with_a_separate_all_of_requirement():
    selected = node("select", course_codes=["CS 5001"], min_courses=1)
    alternatives = node("any_of", children=[selected, node("course", course_code="CS 5999")])
    result = evaluate(node("all_of", children=[alternatives, node("course", course_code="CS 5001")]), [course()]).root
    assert result.children[0].children[0].status == "unknown"


def test_valid_partial_unmodeled_child_never_claims_met():
    from schemas.plan_draft import DraftCourse, evaluate_draft
    from schemas.program_plan import ProgramPlan

    root = node("all_of", children=[node("unmodeled", label="Policy not captured"), node("course", course_code="CS 5001")])
    plan = ProgramPlan.model_validate({**plans()[0].model_dump(), "coverage": "partial", "requirements": root.model_dump()})
    result = evaluate_draft(plan, [DraftCourse(**course())]).root
    assert result.children[0].status == "unknown" and result.status == "unknown"


@pytest.mark.parametrize("optional", [False, True])
def test_exclusion_only_mention_blocks_other_open_pools(optional):
    from schemas.course_program_context import course_placements, explicitly_named
    from schemas.plan_draft import DraftCourse, evaluate_draft
    from schemas.program_plan import ProgramPlan

    membership = ({"course_ranges": [{"start": "CS 5000", "end": "CS 5999"}]} if optional
                  else {"subject_codes": ["CS"]})
    excluded = node("select", label="exclusion only", excluded_course_codes=["CS 5001"],
                    min_courses=1, **membership)
    other = node("optional", activate_when="Project approval", children=[excluded]) if optional else excluded
    rules = node("all_of", children=[node("select", label="other open pool", subject_codes=["CS"], min_courses=1), other])
    plan = ProgramPlan.model_validate({**plans()[0].model_dump(), "coverage": "partial", "requirements": rules.model_dump()})
    assert explicitly_named(plan.requirements, "cs5001") is True
    placements, omitted = course_placements(plan.requirements, "CS 5001")
    assert [p.relation for p in placements] == ["excluded"] and omitted == 0
    result = evaluate_draft(plan, [DraftCourse(**course())])
    assert result.root.children[0].status == "missing" and result.root.children[0].possible == []
    assert result.unplaced == []  # Exclusion-only mention still blocks other open pools (H3 unchanged).


def test_valid_partial_condition_child_never_claims_met():
    from schemas.plan_draft import DraftCourse, evaluate_draft
    from schemas.program_plan import ProgramPlan

    rules = node("all_of", children=[node("condition", label="GPA approval"), node("course", course_code="CS 5001")])
    plan = ProgramPlan.model_validate({**plans()[0].model_dump(), "coverage": "partial", "requirements": rules.model_dump()})
    result = evaluate_draft(plan, [DraftCourse(**course())])
    assert result.root.status == "unknown" and result.root.children[0].status == "unknown"
    assert "文字条件" in " ".join(result.root.children[0].reasons)
