"""F year, prompt, route and feedback contracts over synthetic courses and curated plans."""

import json

import pytest

from db.course_requisite_repository import CourseRequisiteRepository
from db.program_plan_repository import ProgramPlanRepository, content_hash
from llm.prompts.chat_v4 import format_courses_block
from rag.answer_evidence import build_answer_evidence
from rag.retriever import SearchHit
from schemas.answer_evidence import RequisiteEvidence
from schemas.program_plan import ProgramPlan
from tests.test_chat_plan_core import selection_data, stored
from tests.test_chat_structured_requisites import document, seeded
from tests.test_program_plan_contract import chat_meta, stub_chat
from tests.test_program_plan_links import plans


@pytest.mark.parametrize("selected,expected,other,omitted", [
    ("2026-2027", ["2026-2027"], 4, 0), ("2024-2025", ["2024-2025"], 4, 0),
    ("2030-2031", ["2028-2029", "2027-2028", "2026-2027"], 5, 2),
])
def test_selected_year_is_chosen_before_the_three_edition_cap(empty_db, selected, expected, other, omitted):
    years = ["2024-2025", "2025-2026", "2026-2027", "2027-2028", "2028-2029"]
    record = seeded(empty_db, *(document(year, prerequisite="CS 5001") for year in years))
    evidence = build_answer_evidence(empty_db, [record], selected_year=selected)[record.course_id]
    req = evidence.requisites
    assert req.selected_year == selected and req.other_years_recorded == other and req.editions_omitted == omitted
    assert [item.catalog_year for item in req.editions] == expected
    assert ("requisite_year_not_recorded" in evidence.warnings) is (selected not in years)
    assert "requisites_differ_by_catalog_year" not in evidence.warnings
    assert RequisiteEvidence.model_validate(req.model_dump()) == req


def test_selected_year_does_not_relabel_another_edition_or_hide_missing_storage(empty_db):
    record = seeded(empty_db, document("2025-2026"))
    evidence = build_answer_evidence(empty_db, [record], selected_year="2026-2027")[record.course_id]
    assert "requisite_year_not_recorded" in evidence.warnings
    assert evidence.requisites.editions[0].catalog_year == "2025-2026"
    empty_db.execute("DROP TABLE course_requisite_documents")
    missing = build_answer_evidence(empty_db, [record], selected_year="2026-2027")[record.course_id]
    assert missing.requisites.storage == "schema_missing" and "requisite_year_not_recorded" in missing.warnings


def test_unselected_year_serialization_remains_legacy_and_selected_state_is_validated(empty_db):
    record = seeded(empty_db, document())
    plain = build_answer_evidence(empty_db, [record])[record.course_id]
    data = plain.requisites.model_dump(mode="json")
    assert set(data) == {"storage", "editions", "editions_omitted", "unusable_records"}
    chosen = build_answer_evidence(empty_db, [record], selected_year="2026-2027")[record.course_id].requisites
    bad = chosen.model_dump() | {"editions_omitted": 2}
    with pytest.raises(ValueError):
        RequisiteEvidence.model_validate(bad)
    with pytest.raises(ValueError):
        RequisiteEvidence.model_validate(chosen.model_dump() | {"selected_year": "2026-2028"})
    with pytest.raises(ValueError):
        RequisiteEvidence.model_validate(plain.requisites.model_dump() | {"other_years_recorded": 1})


def test_selected_year_projection_and_context_are_bounded_and_only_for_retrieved_courses(empty_db):
    from rag.answer_evidence import build_plan_context
    from schemas.answer_evidence import PlanContext

    plan = stored(empty_db)
    record = seeded(empty_db, document())
    context = build_plan_context(plan, [record])
    assert isinstance(context, PlanContext) and context.plan_content_sha256 == content_hash(plan)
    assert set(context.placements) == {record.course_id} and context.placements[record.course_id][0].relation == "required"
    assert context.source_url == plan.source_url and context.checked_on == plan.checked_on
    assert context.placements_omitted == {record.course_id: 0}
    serialized = context.model_dump(mode="json")
    assert PlanContext.model_validate_json(json.dumps(serialized)) == context
    assert "requirements" not in serialized and "source_excerpt" not in serialized and "checked_by" not in serialized
    evidence = build_answer_evidence(empty_db, [record], selected_year=plan.catalog_year)
    block = json.loads(format_courses_block([SearchHit(course=record, score=1)], evidence))[0]
    assert block["catalog_requisites"]["selected_year"] == plan.catalog_year
    for changes in ({"source_url": "https://evil.test/"}, {"review_status": "draft"},
                    {"source_catalog_year": "2025-2026"}, {"placements_omitted": {record.course_id: -1}}):
        with pytest.raises(ValueError):
            PlanContext.model_validate_json(json.dumps(serialized | changes))


def test_prompt_45_adds_a_separate_bounded_url_free_data_block_without_breaking_existing_blocks():
    from llm.prompts.chat_v4 import PROMPT_VERSION, build_prompt, format_plan_block
    plan = plans()[5]
    projected = format_plan_block(plan)
    data = json.loads(projected)
    assert data["catalog_year"] == plan.catalog_year and data["coverage"] == "partial" and "rules" in data
    assert len(projected) <= 12_000
    for secret in (plan.source_url, plan.source_excerpt, plan.source_html_sha256, plan.checked_by, content_hash(plan)):
        assert not secret or secret not in projected
    prompt = build_prompt("question", [], history=[{"role": "user", "content": "old"}], plan=plan)
    assert PROMPT_VERSION == "4.5"
    assert prompt.index("# Selected program plan (JSON DATA)") < prompt.index("# Conversation history (quoted DATA)")
    assert prompt.split("# Conversation history (quoted DATA)\n")[1].split("\n\n# New message", 1)[0] == '"Student: old"'
    assert "# Retrieval notices (DATA)\n[]\n\n# Retrieved course evidence" in prompt
    assert "# Selected program plan (JSON DATA)\nnull" in build_prompt("question", [])
    for rule in ("not proof", "open_pool", "count twice", "minimum grades", "never write its URL", "registration"):
        assert rule in prompt


def test_plan_labels_are_cut_and_an_over_budget_tree_is_omitted_not_sliced():
    from llm.prompts.chat_v4 import format_plan_block
    raw = plans()[5].model_dump()
    raw["requirements"] = {"kind": "all_of", "label": "x" * 1000, "children": [
        {"kind": "course", "label": "y" * 1000, "course_code": "CS 5800"},
        {"kind": "course", "label": "z", "course_code": "CS 5001"}]}
    projected = json.loads(format_plan_block(ProgramPlan.model_validate(raw)))
    assert len(projected["rules"]["label"]) == len(projected["rules"]["all_of"][0]["label"]) == 300
    raw["requirements"]["children"] = [{"kind": "course", "label": "x" * 1000, "course_code": f"CS {5000+i}"} for i in range(40)]
    output = format_plan_block(ProgramPlan.model_validate(raw))
    data = json.loads(output)
    assert len(output) <= 12_000 and data["rules_not_shown"] is True and "rules" not in data


@pytest.mark.parametrize("outcome", ["missing", "stale", "draft", "unusable", "unavailable"])
def test_unconfirmed_plan_409_is_fixed_before_retrieval_logging_or_feedback(api_client, empty_db, monkeypatch, outcome):
    from config import settings
    from db.program_plan_repository import PlanResolution
    from schemas.plan_selection import PLAN_SELECTION_MESSAGES, PLAN_SELECTOR_LABEL
    from structlog.testing import capture_logs
    import api.routes.chat as chat

    plan = stored(empty_db)
    monkeypatch.setattr(settings, "answer_feedback_enabled", True)
    monkeypatch.setattr(ProgramPlanRepository, "resolve_selection", lambda *args: PlanResolution(outcome))
    def forbidden(*args):
        raise AssertionError("409 must precede retrieval")
    monkeypatch.setattr(chat, "_retrieve", forbidden)
    with capture_logs() as logs:
        response = api_client.post("/chat", json={"query": "private-query-sentinel", "program_id": plan.program_id,
            "plan": selection_data(plan), "allow_feedback_capture": True})
    assert response.status_code == 409 and response.json()["detail"] == PLAN_SELECTION_MESSAGES[outcome]
    assert response.json()["reason"] == "plan_" + outcome  # The web front end words it from here (R3e).
    assert PLAN_SELECTOR_LABEL in response.json()["detail"]
    assert "private-query-sentinel" not in response.text + json.dumps(logs)
    assert empty_db.execute("SELECT COUNT(*) FROM query_log").fetchone()[0] == 0
    assert empty_db.execute("SELECT COUNT(*) FROM chat_answers").fetchone()[0] == 0
    records = [record for record in logs if record.get("event") == "chat.plan_selection"]
    assert len(records) == 1 and records[0]["plan_outcome"] == outcome and records[0]["plan_id"] == plan.plan_id
    assert set(records[0]) == {"event", "log_level", "plan_outcome", "plan_id"}


def test_selection_does_not_change_hits_and_meta_and_feedback_keep_separate_projections(api_client, empty_db, monkeypatch):
    from config import settings
    plan = stored(empty_db)
    CourseRequisiteRepository(empty_db).store(document())
    prompts = []
    stub_chat(api_client, prompts)
    monkeypatch.setattr(settings, "answer_feedback_enabled", True)
    base = chat_meta(api_client.post("/chat", json={"query": "CS 5800", "program_id": plan.program_id}))
    assert "plan_context" not in base
    chosen = chat_meta(api_client.post("/chat", json={"query": "CS 5800", "program_id": plan.program_id,
        "plan": selection_data(plan), "allow_feedback_capture": True}))
    assert [(item["course_id"], item["score"]) for item in chosen["results"]] == [(item["course_id"], item["score"]) for item in base["results"]]
    assert chosen["plan_context"]["plan_id"] == plan.plan_id and chosen["prompt_version"] == "4.5"
    assert chosen["plan_context"]["placements"][chosen["results"][0]["course_id"]][0]["relation"] == "required"
    assert plan.source_url not in prompts[-1]
    request_context = json.loads(empty_db.execute("SELECT request_context FROM chat_answers").fetchone()[0])
    assert request_context["plan_id"] == plan.plan_id and request_context["plan_content_sha256"] == content_hash(plan)
    assert "plan" not in request_context and "requirements" not in json.dumps(request_context)


@pytest.mark.parametrize("program", [None, "another-family"])
def test_request_family_mismatch_is_422_without_side_effects(api_client, empty_db, program):
    plan = stored(empty_db)
    response = api_client.post("/chat", json={"query": "CS 5800", "program_id": program, "plan": selection_data(plan)})
    assert response.status_code == 422 and empty_db.execute("SELECT COUNT(*) FROM query_log").fetchone()[0] == 0
