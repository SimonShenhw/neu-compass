"""H3 (2026-10-20): another group's finite candidate inside this group's range may count here, marked uncertain.

A spare breadth course inside the elective range used to be kept out of the elective pool because the plan named it
elsewhere, so electives showed a false "missing". Course leaves and exclusions anywhere in the plan still stay out.
中文：别组的有限候选落在本组范围里，也算「可能计入」并写明原因；必修叶子和任何位置的排除项照旧不进开放池。
"""

from schemas.plan_draft import DraftCourse, evaluate_draft
from tests.plan_draft_support import seed_documents
from tests.test_plan_draft import course, evaluate, node

RANGE = [{"start": "CS 5100", "end": "CS 7980"}]
BREADTH = node("select", label="Breadth", course_codes=["CS 5100", "CS 5400", "CS 5500", "CS 5520"], min_courses=3)
ELECTIVES = node("select", label="Electives", course_codes=["CS 5097"], course_ranges=RANGE, min_credits=8)
SPARE = "CS 5100、CS 5400、CS 5500、CS 5520 已算进『Breadth』；能不能同时算这一组，要项目确认。"


def drafted(*codes):
    return [course(code) for code in codes]


def test_a_spare_breadth_course_in_the_elective_range_is_possible_not_missing():
    result = evaluate(node("all_of", children=[BREADTH, ELECTIVES]),
                      drafted("CS 5100", "CS 5400", "CS 5500", "CS 5520", "CS 5097"), partial=True)
    breadth, electives = result.root.children
    assert breadth.status == "met"
    assert electives.status == "unknown" and electives.counted == ["CS 5097"]
    assert electives.possible == ["CS 5100", "CS 5400", "CS 5500", "CS 5520"]
    assert SPARE in electives.reasons
    assert not any(reason.startswith("范围内可能计入") for reason in electives.reasons)


def test_the_mscs_seed_example_from_the_interim_review():
    plan = next(p for seed, p in seed_documents()
                if seed == "boston_2026_2027_extended_rules.json" and p.program_id == "cs-ms")
    codes = ["CS 5010", "CS 5011", "CS 5800", "CS 5100", "CS 5400", "CS 5500", "CS 5520", "CS 5097", "CS 7990"]
    result = evaluate_draft(plan, [DraftCourse(**course(code)) for code in codes])
    electives = result.root.children[2]
    assert electives.status == "unknown"
    assert electives.possible == ["CS 5100", "CS 5400", "CS 5500", "CS 5520"]  # CS 5800 is a core leaf: never
    assert any(reason.startswith("CS 5100、CS 5400、CS 5500、CS 5520 已算进『广度") for reason in electives.reasons)
    assert result.root.status == "unknown" and result.summary_counts["missing"] == 0


def test_a_required_leaf_in_the_range_stays_out_of_the_pool():
    core = node("course", label="Algorithms", course_code="CS 5800")
    result = evaluate(node("all_of", children=[core, ELECTIVES]), drafted("CS 5800"), partial=True)
    electives = result.root.children[1]
    assert electives.status == "missing" and electives.possible == []


def test_the_range_line_lists_only_courses_not_counted_elsewhere():
    result = evaluate(node("all_of", children=[BREADTH, ELECTIVES]),
                      drafted("CS 5100", "CS 5400", "CS 5500", "CS 5520", "CS 6000"), partial=True)
    electives = result.root.children[1]
    assert "范围内可能计入：CS 6000；是否能算，要项目确认。" in electives.reasons
    assert SPARE in electives.reasons


def test_a_course_counted_in_an_alternative_exit_is_not_counted_elsewhere():
    project = node("select", label="Project", course_codes=["CS 5100"], min_courses=1)
    thesis = node("select", label="Thesis", course_ranges=RANGE, min_courses=2)
    result = evaluate(node("any_of", label="Exit", children=[project, thesis]), drafted("CS 5100"), partial=True)
    thesis_result = result.root.children[1]
    assert thesis_result.possible == ["CS 5100"]
    assert not any("已算进" in reason for reason in thesis_result.reasons)
    assert any(reason.startswith("范围内可能计入：CS 5100") for reason in thesis_result.reasons)


def test_a_met_group_needs_no_reason_about_other_groups():
    electives = node("select", label="Electives", course_codes=["CS 5097", "CS 5098"], course_ranges=RANGE,
                     min_credits=8)
    result = evaluate(node("all_of", children=[BREADTH, electives]),
                      drafted("CS 5100", "CS 5400", "CS 5500", "CS 5097", "CS 5098"), partial=True)
    assert result.root.children[1].status == "met"
    assert not any("已算进" in reason for reason in result.root.children[1].reasons)
