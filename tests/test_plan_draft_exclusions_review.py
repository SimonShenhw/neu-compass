"""Exclusion eligibility is distinct from whether a rule mentions a course."""

import pytest

from schemas.plan_draft import DraftCourse, evaluate_draft
from schemas.program_plan import ProgramPlan
from tests.test_plan_draft import course, node
from tests.test_program_plan_links import plans


@pytest.mark.parametrize("wrapped", [False, True], ids=["root", "child"])
def test_finite_selection_exclusion_cannot_count_even_when_mentioned(wrapped):
    pool = node("select", label="Finite electives", course_codes=["CS 5001", "CS 5002"],
                excluded_course_codes=["CS 5001"], min_courses=1, min_credits=4)
    rule = node("all_of", children=[pool, node("condition", label="Policy")]) if wrapped else pool
    plan = ProgramPlan.model_validate({**plans()[0].model_dump(), "coverage": "partial",
                                       "requirements": rule.model_dump()})
    result = evaluate_draft(plan, [DraftCourse(**course("CS 5001", credits=4))])
    selection = result.root.children[0] if wrapped else result.root

    assert selection.status == "missing"
    assert selection.counted == [] and selection.possible == []
    assert selection.shortfall["courses"] == 1 and selection.shortfall["credits"] == 4
    assert any("CS 5001" in reason and "明确排除" in reason for reason in selection.reasons)
    assert result.unplaced == []  # Mentioned by the exclusion; never eligible for the pool.
