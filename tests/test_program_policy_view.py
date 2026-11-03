"""Selected-plan policy display, not merged rules or registration eligibility."""

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from db.program_plan_repository import ProgramPlanRepository, content_hash
from db.program_repository import ProgramRepository
from rag.program_policy_evidence import ProgramPolicyReader
from schemas.program import Program
from schemas.program_plan import ProgramPlan
from schemas.program_policy_view import ProgramPolicyView
from tests.test_program_policy_evidence import fixture_bundle
from tests.test_program_plan_contract import chat_meta, seed_plan, stub_chat


def assert_no_guessed_schedule(api_client):
    """Scoped rules never reactivate the legacy guessed sequence; the student
    gets an answer with the explicit unverified-schedule notice instead."""
    stub_chat(api_client)
    meta = chat_meta(api_client.post("/chat", json={"query": "CS first semester", "program_id": "cs-ms"}))
    assert meta["matched_via"] != "program"
    assert meta["notices"] == ["program_schedule_unverified"]

ROOT = Path(__file__).resolve().parent.parent


def test_selected_policy_route_exists_without_reactivating_legacy_guesses(api_client, empty_db):
    plan = seed_plan(empty_db)
    response = api_client.get(f"/programs/{plan.program_id}/plans/{plan.plan_id}/policies")
    assert response.status_code == 200
    assert response.json()["status"] == "stale"
    assert response.json()["policies"] == []
    assert_no_guessed_schedule(api_client)


def setup_reader(tmp_path):
    data, bundle_file, plan_file, policy_dir, program_dir = fixture_bundle(tmp_path)
    plan = ProgramPlan.model_validate(json.loads(plan_file.read_text())[0])
    return plan, data, ProgramPolicyReader(bundle_file, policy_dir, program_dir)


def file_bytes(root):
    return {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_reader_is_readonly_uncached_and_returns_only_verified_selected_paragraphs(tmp_path, monkeypatch):
    import sqlite3
    plan, _, reader = setup_reader(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("Evidence reader cannot open DB or HTTP")
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(httpx, "Client", forbidden)
    before = file_bytes(tmp_path)
    view = reader.read(plan)
    assert view.status == "ready" and view.link.home_college == "khoury"
    assert view.scope.scope_key() == plan.scope_key() and view.plan_content_sha256 == content_hash(plan)
    assert view.policies[0].fragments[0].source_paragraph == "Independent synthetic policy paragraph."
    assert file_bytes(tmp_path) == before
    next(reader.policy_source_dir.glob("*.html")).write_bytes(b"changed after ready")
    assert reader.read(plan).status == "unusable"  # Not a cached successful response.


@pytest.mark.parametrize("kind,expected", [
    ("bundle-missing", "unavailable"), ("bundle-invalid", "unusable"), ("bundle-oversized", "unusable"),
    ("policy-html-missing", "unavailable"), ("policy-sidecar-missing", "unavailable"),
    ("program-html-missing", "unavailable"), ("program-sidecar-missing", "unavailable"),
    ("policy-bytes", "unusable"), ("program-bytes", "unusable"), ("policy-metadata", "unusable"),
    ("program-metadata", "unusable"), ("paragraph", "unusable"), ("not-linked", "not_linked"),
    ("revision", "stale"), ("campus", "stale"), ("pathway", "stale"), ("concentration", "stale"),
    ("program", "stale"), ("review-date", "stale"), ("draft", "draft"),
])
def test_reader_failure_states_never_include_partial_evidence(tmp_path, kind, expected):
    plan, data, reader = setup_reader(tmp_path)
    link, policy = data["links"][0], data["policies"][0]
    if kind == "bundle-missing":
        reader.bundle_file.unlink()
    elif kind == "bundle-invalid":
        reader.bundle_file.write_text("{}")
    elif kind == "bundle-oversized":
        reader.bundle_file.write_bytes(b" " * 300_001)
    elif kind.endswith("-missing"):
        directory = reader.policy_source_dir if kind.startswith("policy") else reader.program_source_dir
        extension = "html" if "html" in kind else "json"
        next(directory.glob(f"*.{extension}")).unlink()
    elif kind in {"policy-bytes", "program-bytes"}:
        directory = reader.policy_source_dir if kind.startswith("policy") else reader.program_source_dir
        next(directory.glob("*.html")).write_bytes(b"tampered")
    elif kind in {"policy-metadata", "program-metadata"}:
        directory = reader.policy_source_dir if kind.startswith("policy") else reader.program_source_dir
        path = next(directory.glob("*.json"))
        meta = json.loads(path.read_text())
        meta["captured_at"] = "2026-10-04T10:00:00Z"
        path.write_text(json.dumps(meta))
    elif kind == "paragraph":
        policy["fragments"][0]["paragraph_sha256"] = "0" * 64
        reader.bundle_file.write_text(json.dumps(data))
    elif kind == "not-linked":
        link["plan_id"] = "other-plan-id"
        reader.bundle_file.write_text(json.dumps(data))
    elif kind == "revision":
        changed = plan.model_dump(mode="json")
        changed["notes"] += " new revision"
        plan = ProgramPlan.model_validate(changed)
    elif kind in {"campus", "pathway", "concentration", "program"}:
        key, value = {"campus": ("campus", "seattle"), "pathway": ("pathway", "align"),
            "concentration": ("concentration", "other"), "program": ("program_id", "other-ms")}[kind]
        link[key] = value
        reader.bundle_file.write_text(json.dumps(data))
    elif kind == "review-date":
        changed = plan.model_dump(mode="json")
        changed["checked_on"] = "2026-10-03"
        plan = ProgramPlan.model_validate(changed)
        link["plan_content_sha256"] = content_hash(plan)
        reader.bundle_file.write_text(json.dumps(data))
    else:
        changed = plan.model_dump(mode="json")
        changed["review_status"] = "draft"
        plan = ProgramPlan.model_validate(changed)
    before = file_bytes(tmp_path)
    view = reader.read(plan)
    assert view.status == expected
    assert view.policies == [] and view.link is None and view.checked_by is None and view.checked_on is None
    assert view.warnings and file_bytes(tmp_path) == before


def test_unreadable_file_is_an_unavailable_state_not_a_traceback(tmp_path, monkeypatch):
    plan, _, reader = setup_reader(tmp_path)
    original_open = Path.open
    def deny(path, *args, **kwargs):
        if path == reader.bundle_file:
            raise PermissionError("private path must not leak")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", deny)
    view = reader.read(plan)
    assert view.status == "unavailable" and "private path" not in view.model_dump_json()


def test_selected_policy_isolation_does_not_load_unrelated_college_archives(tmp_path):
    plan, data, reader = setup_reader(tmp_path)
    extra = json.loads(json.dumps(data["policies"][0]))
    extra["policy_id"] = "unrelated-camd"
    extra["authority"] = "camd"
    extra["source"]["url"] = "https://catalog.northeastern.edu/graduate/arts-media-design/academic-policies-procedures/masters-degrees/"
    extra["source"]["sha256"] = "0" * 64  # No unrelated archive exists.
    link = dict(data["links"][0], plan_id="unrelated-ds-camd", program_id="ds-ms", concentration="data-design-visualization",
        home_college="camd", policy_ids=["unrelated-camd"])
    data["policies"].append(extra)
    data["links"].append(link)
    reader.bundle_file.write_text(json.dumps(data))
    assert reader.read(plan).status == "ready"


def test_program_changed_between_verification_and_association_read_is_not_trusted(tmp_path, monkeypatch):
    import rag.program_policy_evidence as module
    plan, _, reader = setup_reader(tmp_path)
    original = module.verify_archived_source
    def change_after_check(*args):
        result = original(*args)
        next(reader.program_source_dir.glob("*.html")).write_bytes(b"changed after verified read")
        return result
    monkeypatch.setattr(module, "verify_archived_source", change_after_check)
    assert reader.read(plan).status == "unusable"


@pytest.mark.parametrize("kind", ["status", "scope", "revision", "reference", "paragraph", "authority", "review", "complete", "extra"])
def test_wire_contract_rejects_inconsistent_ready_or_nonready_evidence(tmp_path, kind):
    plan, _, reader = setup_reader(tmp_path)
    data = reader.read(plan).model_dump(mode="json")
    if kind == "status":
        data["status"] = "unavailable"
    elif kind == "scope":
        data["scope"]["campus"] = "seattle"
    elif kind == "revision":
        data["plan_content_sha256"] = "0" * 64
    elif kind == "reference":
        data["link"]["policy_ids"] = ["unknown"]
    elif kind == "paragraph":
        data["policies"][0]["fragments"][0]["source_paragraph"] = "Forged paragraph"
    elif kind == "authority":
        data["link"]["home_college"] = "engineering"
    elif kind == "review":
        data["checked_on"] = "2026-10-01"
    elif kind == "complete":
        data["coverage"] = "complete"
    else:
        data["eligible"] = True
    with pytest.raises(ValidationError):
        ProgramPolicyView.model_validate(data)


def seed_fixture_plan(conn, plan):
    ProgramRepository(conn).upsert_program(Program(program_id=plan.program_id, full_name="Legacy family", prefix="CS"))
    ProgramPlanRepository(conn).store(plan)


def test_api_selected_evidence_is_readonly_no_store_and_keeps_existing_contracts(api_client, empty_db, tmp_path):
    from api.dependencies import get_program_policy_reader
    plan, _, reader = setup_reader(tmp_path)
    seed_fixture_plan(empty_db, plan)
    api_client.app.dependency_overrides[get_program_policy_reader] = lambda: reader
    before_changes, before_files = empty_db.total_changes, file_bytes(tmp_path)
    before_plan = empty_db.execute("SELECT document,content_hash FROM program_plans").fetchall()
    sql = []
    empty_db.set_trace_callback(sql.append)
    response = api_client.get(f"/programs/{plan.program_id}/plans/{plan.plan_id}/policies")
    empty_db.set_trace_callback(None)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["status"] == "ready"
    assert empty_db.total_changes == before_changes and file_bytes(tmp_path) == before_files
    assert empty_db.execute("SELECT document,content_hash FROM program_plans").fetchall() == before_plan
    assert all(not statement.lstrip().split()[0].lower() in {"insert", "update", "delete", "create", "drop", "alter"} for statement in sql)
    assert api_client.get("/programs/cs-ms").json()["plans"] == [plan.model_dump(mode="json")]
    assert api_client.get("/programs/cs-ms/plans").json()["plans"] == [plan.model_dump(mode="json")]
    assert_no_guessed_schedule(api_client)
    next(reader.policy_source_dir.glob("*.html")).unlink()
    failed = api_client.get(f"/programs/{plan.program_id}/plans/{plan.plan_id}/policies")
    assert failed.status_code == 200 and failed.json()["status"] == "unavailable" and failed.json()["policies"] == []


@pytest.mark.parametrize("kind", ["unknown-family", "unknown-plan", "another-family", "missing-schema", "bad-document", "bad-hash"])
def test_api_cannot_return_another_family_or_unusable_plan(api_client, empty_db, tmp_path, kind):
    from api.dependencies import get_program_policy_reader
    plan, _, _ = setup_reader(tmp_path)
    seed_fixture_plan(empty_db, plan)
    class NeverRead:
        def read(self, value):
            pytest.fail("Unknown/unusable plans must not load policy archives")
    api_client.app.dependency_overrides[get_program_policy_reader] = lambda: NeverRead()
    family, plan_id = plan.program_id, plan.plan_id
    if kind == "unknown-family":
        family = "unknown"
    elif kind == "unknown-plan":
        plan_id = "unknown"
    elif kind == "another-family":
        family = "info-ms"
        ProgramRepository(empty_db).upsert_program(Program(program_id=family, full_name="Other", prefix="INFO"))
    elif kind == "missing-schema":
        empty_db.execute("DROP TABLE program_plans")
    elif kind == "bad-document":
        empty_db.execute("UPDATE program_plans SET document='{}'")
    else:
        empty_db.execute("UPDATE program_plans SET content_hash=?", ("0" * 64,))
    before = empty_db.total_changes
    response = api_client.get(f"/programs/{family}/plans/{plan_id}/policies")
    assert response.status_code == 404 and empty_db.total_changes == before
    if kind == "missing-schema":
        assert not ProgramPlanRepository(empty_db).available()


def test_dependency_archive_defaults_follow_sqlite_directory_not_cwd(tmp_path, monkeypatch):
    from api.dependencies import get_program_policy_reader
    from config import settings
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "runtime/courses.db"))
    monkeypatch.setattr(settings, "program_policy_source_dir", None)
    monkeypatch.setattr(settings, "program_catalog_source_dir", None)
    reader = get_program_policy_reader()
    assert reader.policy_source_dir == tmp_path / "runtime/raw/program_policy_catalog"
    assert reader.program_source_dir == tmp_path / "runtime/raw/program_catalog"
    monkeypatch.setattr(settings, "program_policy_source_dir", tmp_path / "explicit-policy")
    monkeypatch.setattr(settings, "program_catalog_source_dir", tmp_path / "explicit-program")
    assert get_program_policy_reader().policy_source_dir == tmp_path / "explicit-policy"
    assert get_program_policy_reader().program_source_dir == tmp_path / "explicit-program"
