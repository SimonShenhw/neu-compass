"""F contracts: exact explicit selection, fail-closed resolution and bounded placements.
中文：先冻结新功能的行为；仅内存库和仓库策展方案，不调模型或真实运行数据。
"""

import sqlite3

import pytest

from db.program_plan_repository import ProgramPlanRepository, content_hash
from db.program_repository import ProgramRepository
from schemas.program import Program
from schemas.program_plan import ProgramPlan, RequirementNode
from tests.test_program_plan_links import plans


def selection_data(plan):
    return {name: getattr(plan, name) for name in ("program_id", "plan_id", "campus", "catalog_year", "pathway", "concentration")} | {
        "plan_content_sha256": content_hash(plan)}


def stored(conn, plan=None):
    plan = plan or plans()[5]
    ProgramRepository(conn).upsert_program(Program(program_id=plan.program_id, full_name="Synthetic program", prefix="CS"))
    ProgramPlanRepository(conn).store(plan)
    return plan


def resolve(conn, plan, **changes):
    from schemas.plan_selection import PlanSelection
    return ProgramPlanRepository(conn).resolve_selection(PlanSelection(**(selection_data(plan) | changes)))


def test_link_and_request_share_one_strict_selection_schema():
    from api.models import ChatRequest
    from app.program_plan_links import PlanLink
    from schemas.plan_selection import PlanSelection

    plan = plans()[5]
    assert issubclass(PlanLink, PlanSelection)
    selection = PlanSelection(**selection_data(plan))
    link = PlanLink.from_plan(plan)
    assert link.model_dump(exclude={"format_version"}) == selection.model_dump()
    assert ChatRequest(query="CS 5800", program_id=plan.program_id, plan=selection).plan == selection
    for program in (None, "another-family"):
        with pytest.raises(ValueError):
            ChatRequest(query="CS 5800", program_id=program, plan=selection)
    assert PlanSelection(**(selection_data(plan) | {"concentration": None})).scope_key() != PlanSelection(
        **(selection_data(plan) | {"concentration": "null"})).scope_key()


@pytest.mark.parametrize("changes", [{"program_id": 1}, {"plan_id": "../bad"}, {"campus": "Boston"},
    {"catalog_year": "2026-2028"}, {"pathway": "general"}, {"concentration": " "},
    {"plan_content_sha256": "F" * 64}, {"extra": True}])
def test_selection_rejects_bad_types_scope_and_extras(changes):
    from schemas.plan_selection import PlanSelection
    with pytest.raises(ValueError):
        PlanSelection(**(selection_data(plans()[5]) | changes))


@pytest.mark.parametrize("outcome", ["selected", "missing", "stale", "draft", "unusable", "unavailable"])
def test_each_resolution_outcome_is_explicit_and_only_selected_has_a_plan(empty_db, outcome):
    plan = stored(empty_db)
    if outcome == "missing":
        empty_db.execute("DELETE FROM program_plans")
    elif outcome == "draft":
        raw = plan.model_dump() | {"review_status": "draft"}
        plan = ProgramPlan.model_validate(raw)
        ProgramPlanRepository(empty_db).store(plan, allow_downgrade=True)
    elif outcome == "unusable":
        empty_db.execute("UPDATE program_plans SET document='{}'")
    elif outcome == "unavailable":
        empty_db.execute("DROP TABLE program_plans")
    result = resolve(empty_db, plan, **({"plan_content_sha256": "0" * 64} if outcome == "stale" else {}))
    assert result.outcome == outcome
    assert result.plan == (plan if outcome == "selected" else None)


@pytest.mark.parametrize("column,value", [("document", "not json"), ("content_hash", "0" * 64), ("campus", "seattle")])
def test_stored_integrity_failure_is_not_called_a_client_revision_change(empty_db, column, value):
    plan = stored(empty_db)
    # A corrupt archive/copy can lack today's CHECK; production inserts cannot create this row.
    empty_db.execute("PRAGMA ignore_check_constraints=ON")
    empty_db.execute(f'UPDATE program_plans SET "{column}"=?', (value,))
    empty_db.execute("PRAGMA ignore_check_constraints=OFF")
    assert resolve(empty_db, plan).outcome == "unusable"


def test_scope_change_and_duplicate_scope_never_choose_first(empty_db):
    plan = stored(empty_db)
    assert resolve(empty_db, plan, campus="seattle").outcome == "stale"
    empty_db.execute("CREATE TABLE copied AS SELECT * FROM program_plans")
    empty_db.execute("DROP TABLE program_plans")
    empty_db.execute("ALTER TABLE copied RENAME TO program_plans")
    empty_db.execute("INSERT INTO program_plans SELECT * FROM program_plans")
    assert resolve(empty_db, plan).outcome == "unusable"


def test_unreadable_table_is_unavailable_not_missing(empty_db):
    plan = stored(empty_db)
    empty_db.set_authorizer(lambda action, table, *args: sqlite3.SQLITE_DENY
                            if action == sqlite3.SQLITE_READ and table == "program_plans" else sqlite3.SQLITE_OK)
    try:
        assert resolve(empty_db, plan).outcome == "unavailable"
    finally:
        empty_db.set_authorizer(None)


def test_real_seed_placements_keep_leaf_options_exclusions_optional_and_open_pools():
    from schemas.course_program_context import course_placements

    all_plans = plans()
    assert len(all_plans) == 7
    align = next(plan for plan in all_plans if plan.pathway == "align")
    for code in ("CS 5800", "CS 5001", "CS 5003", "CS 5002", "CS 5004", "CS 5005", "CS 5008", "CS 5009"):
        entries, omitted = course_placements(align.requirements, code)
        assert entries and entries[0].relation == "required" and not omitted
        assert all(entry.relation != "open_pool" for entry in entries)
    bridge = next(plan for plan in all_plans if plan.pathway == "bridge")
    assert course_placements(bridge.requirements, "INFO 5101")[0][0].relation == "required"
    info = next(plan for plan in all_plans if plan.program_id == "info-ms" and plan.pathway == "standard")
    excluded, omitted = course_placements(info.requirements, "INFO 5200")
    assert len(excluded) == 4 and omitted == 2 and all(item.relation == "excluded" for item in excluded)
    assert all(item.under_any_of for item in excluded)
    assert len(course_placements(info.requirements, "INFO 6105")[0]) == 4
    assert course_placements(info.requirements, "INFO 6105")[1] == 2
    for plan in all_plans:
        # Every seed tree is traversed, with unknown courses never called excluded/required.
        assert course_placements(plan.requirements, "ZZ 9999") == ([], 0)
    ds = next(plan for plan in all_plans if plan.concentration == "engineering-theory-modeling")
    candidates, omitted = course_placements(ds.requirements, "EECE 5360")
    assert len(candidates) == 2 and not omitted and all(item.relation == "select_candidate" for item in candidates)
    assert {item.min_credits for item in candidates} == {4, 12}


def test_placements_are_ranked_before_capping_and_named_anywhere_suppresses_open_pool():
    from schemas.course_program_context import course_placements

    tree = RequirementNode(kind="all_of", label="root", children=[
        RequirementNode(kind="select", label="open", subject_codes=["CS"], min_credits=4),
        RequirementNode(kind="select", label="candidate", course_codes=["CS 5800"], min_courses=1),
        RequirementNode(kind="optional", label="co-op", activate_when="only with approval", children=[
            RequirementNode(kind="course", label="leaf", course_code="CS 5800")])])
    entries, omitted = course_placements(tree, "CS 5800")
    assert [item.relation for item in entries] == ["optional_branch", "select_candidate"] and omitted == 0
    assert entries[0].activate_when == ["only with approval"] and entries[0].path == ["root", "co-op", "leaf"]
    assert course_placements(tree, "CS 7180")[0][0].relation == "open_pool"


def test_nested_any_of_optional_and_finite_area_minima_are_kept():
    from schemas.course_program_context import course_placements

    tree = RequirementNode(kind="optional", label="x" * 1000, activate_when="approved", children=[
        RequirementNode(kind="any_of", label="OR", children=[
            RequirementNode(kind="course", label="course", course_code="CS 5800"),
            RequirementNode(kind="select", label="pool", course_codes=["CS 5800", "CS 5200"], min_courses=2,
                min_areas=2, areas={"A": ["CS 5800"], "B": ["CS 5200"]})])])
    entries, _ = course_placements(tree, "CS 5800")
    assert [item.relation for item in entries] == ["any_of_option", "select_candidate"]
    assert all(item.under_any_of and item.activate_when == ["approved"] and len(item.path[0]) == 300 for item in entries)
    assert entries[1].areas == ["A"] and entries[1].min_areas == 2
