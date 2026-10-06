"""Versioned plans must not silently turn legacy seeds into catalog facts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from db.program_plan_repository import ProgramPlanRepository
from db.program_repository import ProgramRepository
from schemas.program import Program, ProgramRequiredCourse
from schemas.program_plan import ProgramPlan

ROOT = Path(__file__).resolve().parent.parent


def seed_plan(conn):
    ProgramRepository(conn).upsert_program(Program(program_id="cs-ms", full_name="CS seed", prefix="CS"))
    data = json.loads((ROOT / "data/program_plan_seed/boston_2026_2027_core_fragments.json").read_text(encoding="utf-8"))[0]
    plan = ProgramPlan.model_validate(data)
    ProgramPlanRepository(conn).store(plan)
    return plan


def seed_legacy_first_semester_edge(conn):
    """A guessed semester-1 edge that stored scoped rules must keep switched off."""
    ProgramRepository(conn).upsert_required_course(ProgramRequiredCourse(
        program_id="cs-ms", course_id="c-cs-5800", requirement_type="core", semester_recommended=1))


def stub_chat(api_client, prompts=None):
    """No real LLM: record the prompt (optional) and stream one token."""
    from api.dependencies import get_chat_stream_fn  # noqa: PLC0415

    def fake_stream(prompt):
        if prompts is not None:
            prompts.append(prompt)
        return iter(["ok"])
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: fake_stream


def chat_meta(response):
    assert response.status_code == 200, response.text
    return json.loads(response.text.splitlines()[0])


def test_legacy_curriculum_identifies_unknown_scope_and_unverified_seed(api_client, empty_db):
    ProgramRepository(empty_db).add_program(Program(program_id="cs-ms", full_name="CS MS seed", prefix="CS"))
    body = api_client.get("/programs/cs-ms").json()
    assert body["plans"] == []
    assert "legacy_seed_unverified" in body["warnings"]
    assert "legacy_scope_unknown" in body["warnings"]


def test_prefix_ambiguity_requests_selection_instead_of_picking_first(api_client, empty_db):
    repo = ProgramRepository(empty_db)
    repo.add_program(Program(program_id="cs-ms", full_name="CS MS", prefix="CS"))
    repo.add_program(Program(program_id="cs-align", full_name="CS Align", prefix="CS"))
    response = api_client.post("/chat", json={"query": "CS first semester"})
    assert response.status_code == 409
    assert "cs-ms" in response.text and "cs-align" in response.text
    from app.program_plan_view import SELECTOR_LABEL  # noqa: PLC0415

    assert f"「{SELECTOR_LABEL}」" in response.json()["detail"]  # Names the selector the student sees.


def test_explicit_program_selection_is_accepted(api_client, empty_db):
    ProgramRepository(empty_db).add_program(Program(program_id="cs-ms", full_name="CS MS", prefix="CS"))
    response = api_client.post("/chat", json={"query": "CS first semester", "program_id": "cs-ms"})
    assert response.status_code == 200


def test_api_retains_full_and_tree_even_when_lab_not_in_course_database(api_client, empty_db):
    plan = seed_plan(empty_db)
    body = api_client.get("/programs/cs-ms").json()
    assert body["plan_schema_available"] is True
    assert body["plans"] == [plan.model_dump(mode="json")]
    core = body["plans"][0]["requirements"]["children"][0]
    assert core["kind"] == "all_of"
    assert [node["course_code"] for node in core["children"]] == ["CS 5010", "CS 5011", "CS 5800"]
    assert body["semesters"] == []  # Never create guessed schedule rows from the tree.
    assert api_client.get("/programs").json()[0]["plan_count"] == 1


def test_plan_filters_never_fall_back_to_latest_or_another_path(api_client, empty_db):
    seed_plan(empty_db)
    for params in ({"campus": "seattle"}, {"catalog_year": "2025-2026"}, {"pathway": "align"}):
        response = api_client.get("/programs/cs-ms/plans", params=params)
        assert response.status_code == 200
        assert response.json()["plans"] == []
    body = api_client.get("/programs/cs-ms/plans", params={"campus": "boston", "catalog_year": "2026-2027", "pathway": "standard"}).json()
    assert len(body["plans"]) == 1
    assert "not_an_eligibility_evaluator" in body["warnings"]


@pytest.mark.parametrize("params", [{"pathway": "unknown"}, {"campus": "Boston; DROP TABLE programs"},
                                     {"catalog_year": "2026"}, {"catalog_year": "2026-2028"}])
def test_invalid_plan_scope_is_422(api_client, empty_db, params):
    seed_plan(empty_db)
    assert api_client.get("/programs/cs-ms/plans", params=params).status_code == 422


def test_old_database_has_honest_empty_plan_response_without_auto_ddl(api_client, empty_db):
    ProgramRepository(empty_db).add_program(Program(program_id="cs-ms", full_name="CS", prefix="CS"))
    empty_db.execute("DROP TABLE program_plans")
    body = api_client.get("/programs/cs-ms/plans").json()
    assert body["schema_available"] is False and body["plans"] == []
    assert not ProgramPlanRepository(empty_db).available()
    assert api_client.get("/programs/cs-ms").json()["plan_schema_available"] is False


def test_bad_source_document_not_returned_or_linked(api_client, empty_db):
    plan = seed_plan(empty_db)
    bad = plan.model_dump(mode="json")
    bad["source_url"] = "https://evil.test/"
    empty_db.execute("UPDATE program_plans SET document=?", (json.dumps(bad),))
    body = api_client.get("/programs/cs-ms").json()
    assert body["plans"] == []
    assert "evil.test" not in json.dumps(body)


def test_versioned_rule_fragment_does_not_enable_guessed_first_semester(api_client, empty_db):
    """Scoped rules carry no verified schedule: the legacy guessed semester-1
    sequence stays OFF (no "program" route even though a semester-1 edge
    exists), but the student still gets an answer plus an explicit notice —
    never a 409 error turn for the most common onboarding question."""
    seed_plan(empty_db)
    seed_legacy_first_semester_edge(empty_db)
    stub_chat(api_client)
    meta = chat_meta(api_client.post("/chat", json={"query": "CS first semester", "program_id": "cs-ms"}))
    assert meta["matched_via"] != "program"
    assert meta["notices"] == ["program_schedule_unverified"]


@pytest.mark.parametrize("query", ["CS 专业第一学期选什么课", "CS 有没有基础一点的课", "CS 入门课推荐"])
def test_unverified_schedule_reaches_prompt_and_query_log(api_client, empty_db, query):
    """The three onboarding phrasings that used to 409: answered, notice in the
    prompt (so the model says it), and the organic query is still logged."""
    from db.query_log_repository import QueryLogRepository  # noqa: PLC0415

    seed_plan(empty_db)
    prompts = []
    stub_chat(api_client, prompts)
    meta = chat_meta(api_client.post("/chat", json={"query": query}))
    assert meta["notices"] == ["program_schedule_unverified"]
    assert '"program_schedule_unverified"' in prompts[0]
    assert QueryLogRepository(empty_db).list_recent()[0]["query"] == query


def test_legacy_only_family_keeps_shortcut_without_notice(api_client, empty_db):
    """No scoped records: the unverified legacy semester-1 shortcut is unchanged."""
    ProgramRepository(empty_db).add_program(Program(program_id="cs-ms", full_name="CS", prefix="CS"))
    seed_legacy_first_semester_edge(empty_db)
    stub_chat(api_client)
    meta = chat_meta(api_client.post("/chat", json={"query": "CS first semester"}))
    assert meta["matched_via"] == "program"
    assert "notices" not in meta


def test_unknown_explicit_program_is_404(api_client):
    assert api_client.post("/chat", json={"query": "first semester", "program_id": "unknown"}).status_code == 404


def test_program_plans_unknown_family_is_404(api_client):
    assert api_client.get("/programs/unknown/plans").status_code == 404


def test_invalid_scoped_document_cannot_reactivate_legacy_guessed_schedule(api_client, empty_db):
    seed_plan(empty_db)
    seed_legacy_first_semester_edge(empty_db)
    empty_db.execute("UPDATE program_plans SET document='{}'")
    stub_chat(api_client)
    meta = chat_meta(api_client.post("/chat", json={"query": "CS first semester"}))
    assert meta["matched_via"] != "program"
    assert meta["notices"] == ["program_schedule_unverified"]


def test_explicit_family_and_query_prefix_conflict_requires_clarification(api_client, empty_db):
    ProgramRepository(empty_db).add_program(Program(program_id="cs-ms", full_name="CS", prefix="CS"))
    response = api_client.post("/chat", json={"query": "AAI first semester", "program_id": "cs-ms"})
    assert response.status_code == 409
    from app.program_plan_view import SELECTOR_LABEL  # noqa: PLC0415

    assert f"「{SELECTOR_LABEL}」" in response.json()["detail"] and "不指定" in response.json()["detail"]


def test_ambiguous_program_does_not_call_model_or_hybrid(api_client, empty_db):
    from types import SimpleNamespace
    from api.dependencies import get_chat_stream_fn, get_hybrid_retriever
    repo = ProgramRepository(empty_db)
    repo.add_program(Program(program_id="cs-ms", full_name="CS", prefix="CS"))
    repo.add_program(Program(program_id="cs-align", full_name="CS Align", prefix="CS"))
    def forbidden(*args, **kwargs):
        raise AssertionError("No model/hybrid call allowed for ambiguous selection")
    hybrid = SimpleNamespace(search=forbidden)
    api_client.app.dependency_overrides[get_hybrid_retriever] = lambda: hybrid
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: forbidden
    assert api_client.post("/chat", json={"query": "CS first semester"}).status_code == 409


def test_extended_rules_round_trip_through_api_without_flattening(api_client, empty_db):
    data = json.loads((ROOT / "data/program_plan_seed/boston_2026_2027_extended_rules.json").read_text(encoding="utf-8"))
    for family in ["cs-ms", "ds-ms", "info-ms"]:
        ProgramRepository(empty_db).add_program(Program(program_id=family, full_name=family, prefix=family.split("-")[0].upper()))
    repo = ProgramPlanRepository(empty_db)
    for item in data:
        repo.store(ProgramPlan.model_validate(item))
    ds = api_client.get("/programs/ds-ms/plans", params={"campus": "boston", "catalog_year": "2026-2027", "pathway": "standard"}).json()
    assert len(ds["plans"]) == 3
    assert {item["concentration"] for item in ds["plans"]} == {item["concentration"] for item in data if item["program_id"] == "ds-ms"}
    info = api_client.get("/programs/info-ms").json()["plans"][0]
    assert info["requirements"]["children"][1]["kind"] == "any_of"
    assert info["requirements"]["children"][1]["children"][0]["children"][0]["excluded_course_codes"] == ["INFO 5200"]
    assert any(node["kind"] == "optional" for node in info["requirements"]["children"])
    cs = api_client.get("/programs/cs-ms/plans").json()["plans"][0]
    assert cs["requirements"]["children"][2]["course_ranges"] == [{"start": "CS 5100", "end": "CS 7980"}]
