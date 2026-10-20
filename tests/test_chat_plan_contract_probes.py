"""Independent branch probes before freezing the final F acceptance scope."""

import json

import pytest

from db.program_plan_repository import content_hash
from schemas.program_plan import ProgramPlan
from tests.test_chat_plan_core import resolve, selection_data, stored
from tests.test_program_plan_links import plans


def test_python_selection_is_strict_and_the_schema_never_imports_db():
    import ast
    from pathlib import Path
    import schemas.plan_selection as module
    from schemas.plan_selection import PlanSelection
    with pytest.raises(ValueError):
        PlanSelection(**(selection_data(plans()[5]) | {"campus": b"boston"}))
    assert not any(isinstance(node, ast.ImportFrom) and (node.module or "").startswith("db")
                   for node in ast.walk(ast.parse(Path(module.__file__).read_text())))


def test_duplicate_id_in_another_scope_cannot_bypass_scope_count_guard(empty_db):
    plan = stored(empty_db)
    other = ProgramPlan.model_validate(plan.model_dump() | {"campus": "seattle"})
    empty_db.execute("CREATE TABLE copied AS SELECT * FROM program_plans")
    empty_db.execute("DROP TABLE program_plans")
    empty_db.execute("ALTER TABLE copied RENAME TO program_plans")
    empty_db.execute("INSERT INTO program_plans(plan_id,program_id,campus,catalog_year,pathway,concentration,document,content_hash) VALUES(?,?,?,?,?,?,?,?)",
        (other.plan_id, *other.scope_key(), other.model_dump_json(), content_hash(other)))
    assert resolve(empty_db, plan).outcome == "unusable"


def test_open_range_coverage_and_candidate_minima_are_explicit_not_inferred_membership():
    from schemas.course_program_context import course_placements
    align = next(plan for plan in plans() if plan.pathway == "align")
    entries, _ = course_placements(align.requirements, "CS 7180")
    assert entries and all(item.relation == "open_pool" for item in entries)
    ds = next(plan for plan in plans() if plan.program_id == "ds-ms")
    entries, _ = course_placements(ds.requirements, "CS 5800")
    assert any(item.relation == "any_of_option" for item in entries)
    cs = plans()[0]
    entries, _ = course_placements(cs.requirements, "CS 5200")
    assert any(item.relation == "select_candidate" and item.min_courses and item.min_areas for item in entries)


def test_each_seed_rule_projection_preserves_operators_pools_minima_areas_and_conditions():
    from llm.prompts.chat_v4 import format_plan_block

    def compare(node, projected):
        assert projected["label"] == node.label[:300]
        if node.kind == "course":
            assert projected["course"] == node.course_code
        elif node.kind == "select":
            pool = projected["select"]
            for field in ("course_codes", "subject_codes", "excluded_course_codes", "min_courses", "min_credits", "min_areas"):
                assert pool[field] == getattr(node, field)
            assert pool["course_ranges"] == [item.model_dump() for item in node.course_ranges]
            assert pool["areas"] == [{"name": name[:300], "course_codes": codes} for name, codes in node.areas.items()]
        elif node.kind == "optional":
            assert projected["activate_when"] == node.activate_when
            compare(node.children[0], projected["optional"])
        elif node.kind in {"any_of", "all_of"}:
            assert len(projected[node.kind]) == len(node.children)
            for child, result in zip(node.children, projected[node.kind], strict=True):
                compare(child, result)
        else:
            assert projected[node.kind] == node.label[:300]
    for plan in plans():
        compare(plan.requirements, json.loads(format_plan_block(plan))["rules"])


def test_a_selected_year_cannot_be_shown_alongside_another_edition(empty_db):
    from rag.answer_evidence import build_answer_evidence
    from schemas.answer_evidence import RequisiteEvidence
    from tests.test_chat_structured_requisites import document, seeded
    record = seeded(empty_db, document("2025-2026"), document("2026-2027"))
    value = build_answer_evidence(empty_db, [record])[record.course_id].requisites.model_dump()
    with pytest.raises(ValueError):
        RequisiteEvidence.model_validate(value | {"selected_year": "2026-2027", "other_years_recorded": 1})


def test_family_clearing_resets_the_bound_plan_even_when_no_widget_is_rendered():
    from app.chat_plan_view import render_chat_plan_selector
    class Surface:
        session_state = {"_chat_plan_family": "cs-ms", "chat_plan_id": "old-choice"}
    surface = Surface()
    assert render_chat_plan_selector(surface, None) is None
    assert surface.session_state["chat_plan_id"] is None


def test_plan_sources_never_extend_the_model_answer_link_allowlist():
    from app.answer_evidence_view import answer_markdown
    url = plans()[5].source_url
    assert f"]({url})" not in answer_markdown(f"[plan]({url})")
    assert "](https://catalog.northeastern.edu/course-descriptions/cs/)" in answer_markdown(
        "[catalog](https://catalog.northeastern.edu/course-descriptions/cs/)")


def test_meta_review_dates_placement_limits_and_ranges_are_validated():
    from rag.answer_evidence import build_plan_context
    from schemas.answer_evidence import PlanContext
    from schemas.course import Course
    from schemas.course_program_context import CoursePlacement
    context = build_plan_context(plans()[5], [Course(course_id="c", primary_code="CS 5800", primary_name="Synthetic")]).model_dump(mode="json")
    for changed in ({"checked_on": "1900-01-01"}, {"placements": {"c": context["placements"]["c"] * 5}},
                    {"placements_omitted": {}}, {"placements_omitted": {"c": "not a number"}}):
        with pytest.raises(ValueError):
            PlanContext.model_validate_json(json.dumps(context | changed))
    with pytest.raises(ValueError):
        CoursePlacement(path=["p"], relation="open_pool", course_ranges=[{"start": "CS 9001", "end": "CS 8001"}])


def test_duplicate_scope_with_distinct_ids_is_unusable(empty_db):
    plan = stored(empty_db)
    other = ProgramPlan.model_validate(plan.model_dump() | {"plan_id": plan.plan_id + "-duplicate"})
    empty_db.execute("CREATE TABLE copied AS SELECT * FROM program_plans")
    empty_db.execute("DROP TABLE program_plans")
    empty_db.execute("ALTER TABLE copied RENAME TO program_plans")
    empty_db.execute("INSERT INTO program_plans(plan_id,program_id,campus,catalog_year,pathway,concentration,document,content_hash) VALUES(?,?,?,?,?,?,?,?)",
        (other.plan_id, *other.scope_key(), other.model_dump_json(), content_hash(other)))
    assert resolve(empty_db, plan).outcome == "unusable"


def test_the_selected_year_is_passed_through_the_route_not_just_the_pure_builder(api_client, empty_db):
    from db.course_requisite_repository import CourseRequisiteRepository
    from tests.test_chat_structured_requisites import document
    from tests.test_program_plan_contract import chat_meta, stub_chat
    plan = stored(empty_db)
    for year in ("2025-2026", "2026-2027", "2027-2028"):
        CourseRequisiteRepository(empty_db).store(document(year))
    stub_chat(api_client)
    meta = chat_meta(api_client.post("/chat", json={"query": "CS 5800", "program_id": plan.program_id,
                                                  "plan": selection_data(plan)}))
    requisites = meta["results"][0]["answer_evidence"]["requisites"]
    assert requisites["selected_year"] == "2026-2027" and requisites["other_years_recorded"] == 2
    assert [edition["catalog_year"] for edition in requisites["editions"]] == ["2026-2027"]
