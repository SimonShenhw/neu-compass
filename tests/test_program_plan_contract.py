"""Versioned plans must not silently turn legacy seeds into catalog facts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from db.program_plan_repository import ProgramPlanRepository
from db.program_repository import ProgramRepository
from schemas.program import Program
from schemas.program_plan import ProgramPlan

ROOT = Path(__file__).resolve().parent.parent


def seed_plan(conn):
    ProgramRepository(conn).upsert_program(Program(program_id="cs-ms", full_name="CS seed", prefix="CS"))
    data = json.loads((ROOT / "data/program_plan_seed/boston_2026_2027_core_fragments.json").read_text(encoding="utf-8"))[0]
    plan = ProgramPlan.model_validate(data)
    ProgramPlanRepository(conn).store(plan)
    return plan


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
    seed_plan(empty_db)
    response = api_client.post("/chat", json={"query": "CS first semester", "program_id": "cs-ms"})
    assert response.status_code == 409
    assert "no verified semester schedule" in response.json()["detail"]


def test_unknown_explicit_program_is_404(api_client):
    assert api_client.post("/chat", json={"query": "first semester", "program_id": "unknown"}).status_code == 404


def test_program_plans_unknown_family_is_404(api_client):
    assert api_client.get("/programs/unknown/plans").status_code == 404


def test_invalid_scoped_document_cannot_reactivate_legacy_guessed_schedule(api_client, empty_db):
    seed_plan(empty_db)
    empty_db.execute("UPDATE program_plans SET document='{}'")
    response = api_client.post("/chat", json={"query": "CS first semester"})
    assert response.status_code == 409


def test_explicit_family_and_query_prefix_conflict_requires_clarification(api_client, empty_db):
    ProgramRepository(empty_db).add_program(Program(program_id="cs-ms", full_name="CS", prefix="CS"))
    response = api_client.post("/chat", json={"query": "AAI first semester", "program_id": "cs-ms"})
    assert response.status_code == 409


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
