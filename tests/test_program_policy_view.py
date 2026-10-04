"""Selected-plan policy display, not merged rules or registration eligibility."""

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.api_client import ApiClient, ApiError
from app.program_plan_view import render_program_plans
from app.program_policy_view import load_selected_program_policy_evidence, render_program_policy_evidence
from db.program_plan_repository import ProgramPlanRepository, content_hash
from db.program_repository import ProgramRepository
from rag.program_policy_evidence import ProgramPolicyReader
from schemas.program import Program
from schemas.program_plan import ProgramPlan
from schemas.program_policy import paragraph_hash
from schemas.program_policy_view import ProgramPolicyView
from tests.test_program_policy_evidence import fixture_bundle
from tests.test_program_plan_view import FakeSurface
from tests.test_program_plan_contract import seed_plan

ROOT = Path(__file__).resolve().parent.parent


def test_selector_returns_only_the_explicitly_selected_plan():
    data = json.loads((ROOT / "data/program_plan_seed/boston_2026_2027_extended_rules.json").read_text())[0]
    assert render_program_plans(FakeSurface(), [data], key="selected") is None
    selected = render_program_plans(FakeSurface(choice=data["plan_id"]), [data], key="selected")
    assert selected is not None and selected.plan_id == data["plan_id"]


def test_removed_plan_selection_is_cleared_without_a_fallback():
    data = json.loads((ROOT / "data/program_plan_seed/boston_2026_2027_extended_rules.json").read_text())[0]
    st = FakeSurface(choice="removed-plan")
    st.session_state["selected"] = "removed-plan"
    assert render_program_plans(st, [data], key="selected") is None
    assert "selected" not in st.session_state and not st.texts


def test_selected_policy_route_exists_without_reactivating_legacy_guesses(api_client, empty_db):
    plan = seed_plan(empty_db)
    response = api_client.get(f"/programs/{plan.program_id}/plans/{plan.plan_id}/policies")
    assert response.status_code == 200
    assert response.json()["status"] == "stale"
    assert response.json()["policies"] == []
    assert api_client.post("/chat", json={"query": "CS first semester", "program_id": "cs-ms"}).status_code == 409


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


def test_ready_view_has_review_provenance_limits_and_plaintext_only(tmp_path):
    plan, data, reader = setup_reader(tmp_path)
    marker = '[unsafe](https://evil.test) <script>bad</script>'
    data["checked_by"] = marker
    fragment = data["policies"][0]["fragments"][0]
    fragment["summary"], fragment["limitation"] = marker, marker
    reader.bundle_file.write_text(json.dumps(data))
    view = reader.read(plan)
    st = FakeSurface()
    render_program_policy_evidence(st, plan, view.model_dump(mode="json"))
    assert any("仅选定片段" in text and "不合并" in text for text in st.captions)
    assert any("不证明来源真实" in text for text in st.captions)
    assert any(marker in text for text in st.texts)
    assert any("Independent synthetic policy paragraph." == text for text in st.texts)
    assert all("evil.test" not in text and "<script>" not in text for text in st.markdowns)
    assert st.markdowns == [f"[官方政策来源]({view.policies[0].source.url})"]


def test_even_source_paragraph_html_is_only_displayed_as_plaintext(tmp_path):
    plan, _, reader = setup_reader(tmp_path)
    view = reader.read(plan).model_dump(mode="json")
    marker = '<script>bad</script> [unsafe](https://evil.test)'
    fragment = view["policies"][0]["fragments"][0]
    fragment["source_paragraph"], fragment["paragraph_sha256"] = marker, paragraph_hash(marker)
    st = FakeSurface()
    render_program_policy_evidence(st, plan, view)
    assert marker in st.texts and all("evil.test" not in text and "<script>" not in text for text in st.markdowns)


@pytest.mark.parametrize("status", ["not_linked", "draft", "stale", "unavailable", "unusable"])
def test_failed_view_only_warns_without_old_policy_links_or_text(tmp_path, status):
    plan, _, reader = setup_reader(tmp_path)
    view = reader.read(plan).model_dump(mode="json")
    view.update(status=status, policies=[], link=None, checked_on=None, checked_by=None)
    st = FakeSurface()
    render_program_policy_evidence(st, plan, view)
    assert st.captions and st.texts == st.markdowns == []


@pytest.mark.parametrize("kind", ["different-plan", "different-current-revision", "different-scope", "bad-format", "bad-url"])
def test_ui_rechecks_expected_plan_identity_and_wire_before_rendering(tmp_path, kind):
    plan, _, reader = setup_reader(tmp_path)
    view = reader.read(plan).model_dump(mode="json")
    if kind == "different-plan":
        view["plan_id"] = view["link"]["plan_id"] = "other"
    elif kind == "different-current-revision":
        view["plan_content_sha256"] = view["link"]["plan_content_sha256"] = "0" * 64
    elif kind == "different-scope":
        view["scope"]["campus"] = view["link"]["campus"] = "seattle"
    elif kind == "bad-format":
        view = {}
    else:
        view["policies"][0]["source"]["url"] = "javascript:bad"
    st = FakeSurface()
    render_program_policy_evidence(st, plan, view)
    assert st.captions and not st.texts and not st.markdowns


@pytest.mark.parametrize("kind", ["empty", "duplicate-id", "duplicate-scope"])
def test_selector_clears_missing_or_ambiguous_scope_and_never_picks_last(kind):
    data = json.loads((ROOT / "data/program_plan_seed/boston_2026_2027_extended_rules.json").read_text())[0]
    docs = []
    if kind != "empty":
        duplicate = json.loads(json.dumps(data))
        if kind == "duplicate-id":
            duplicate["campus"] = "seattle"
        else:
            duplicate["plan_id"] = "other"
        docs = [data, duplicate]
    st = FakeSurface(choice=data["plan_id"])
    st.session_state["selected"] = data["plan_id"]
    assert render_program_plans(st, docs, key="selected") is None
    assert "selected" not in st.session_state and not st.texts


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
    assert api_client.post("/chat", json={"query": "CS first semester", "program_id": "cs-ms"}).status_code == 409
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


def test_client_calls_only_the_selected_public_get_and_preserves_auth_header(tmp_path):
    plan, _, reader = setup_reader(tmp_path)
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=reader.read(plan).model_dump(mode="json"))
    with ApiClient(base_url="http://api.test", session_token="sample", transport=httpx.MockTransport(handle)) as api:
        response = api.get_program_policies(plan.program_id, plan.plan_id)
    assert response["status"] == "ready" and len(calls) == 1
    assert calls[0].method == "GET" and calls[0].url.path == f"/programs/{plan.program_id}/plans/{plan.plan_id}/policies"
    assert calls[0].headers["authorization"] == "Bearer sample" and not calls[0].url.query


@pytest.mark.parametrize("fail", ["timeout", "connect", "404", "bad-json"])
def test_ui_api_failure_does_not_crash_or_keep_a_previous_policy(tmp_path, monkeypatch, fail):
    plan, _, _ = setup_reader(tmp_path)
    def handle(request):
        if fail == "timeout":
            raise httpx.ReadTimeout("fail", request=request)
        if fail == "connect":
            raise httpx.ConnectError("fail", request=request)
        if fail == "404":
            return httpx.Response(404, json={"detail": "<script>private</script>"})
        return httpx.Response(200, content=b"not-json", headers={"content-type": "application/json"})
    monkeypatch.setattr("app.api_client.ApiClient", lambda **kwargs:
        ApiClient(base_url="http://api.test", transport=httpx.MockTransport(handle), **kwargs))
    st = FakeSurface()
    load_selected_program_policy_evidence(st, plan)
    assert any("无法加载" in caption for caption in st.captions) and not st.texts and not st.markdowns
    assert not any("private" in caption for caption in st.captions)


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


def widget_app(monkeypatch, plan, reader, *, backend=None):
    from streamlit.testing.v1 import AppTest
    backend = backend if backend is not None else {"plan": plan}
    class WidgetApi:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get_program_curriculum(self, program_id):
            import streamlit as st
            st.session_state["curriculum_calls"] = st.session_state.get("curriculum_calls", 0) + 1
            current = backend["plan"]
            return dict(program_id=current.program_id, prefix="CS", full_name="Example plan family", semesters=[],
                plans=[current.model_dump(mode="json")])
        def get_program_policies(self, program_id, plan_id):
            import streamlit as st
            st.session_state["policy_calls"] = st.session_state.get("policy_calls", 0) + 1
            assert program_id == plan.program_id and plan_id == plan.plan_id
            if backend.get("outage"):
                raise ApiError(503, "outage")
            return reader.read(backend["plan"]).model_dump(mode="json")
    monkeypatch.setattr("app.api_client.ApiClient", WidgetApi)
    return AppTest.from_string('''
import streamlit as st
from app.program_view import render_program_browser
st.session_state.setdefault("selected_program_id", "cs-ms")
render_program_browser(st)
''').run(timeout=45)


def test_real_browser_panel_loads_only_after_choice_and_clears_on_none_or_refresh(tmp_path, monkeypatch):
    plan, _, reader = setup_reader(tmp_path)
    app = widget_app(monkeypatch, plan, reader)
    assert not app.exception and app.selectbox[0].value is None
    assert app.session_state["curriculum_calls"] == 1
    assert "policy_calls" not in app.session_state
    app.selectbox[0].set_value(plan.plan_id).run(timeout=45)
    assert not app.exception and app.session_state["policy_calls"] == 1
    assert any(item.value == "Independent synthetic policy paragraph." for item in app.text)
    app.selectbox[0].set_value(None).run(timeout=45)
    assert not app.exception and app.session_state["policy_calls"] == 1
    assert not any("Independent synthetic policy" in item.value for item in app.text)
    app.selectbox[0].set_value(plan.plan_id).run(timeout=45)
    assert not app.exception and app.session_state["policy_calls"] == 2
    next(button for button in app.button if button.key == "prog-refresh-cs-ms").click().run(timeout=45)
    assert not app.exception and app.selectbox[0].value is None
    assert app.session_state["curriculum_calls"] == 2 and app.session_state["policy_calls"] == 2
    assert not any("Independent synthetic policy" in item.value for item in app.text)


def test_real_widget_recovers_from_api_outage_without_using_a_prior_ready_response(tmp_path, monkeypatch):
    plan, _, reader = setup_reader(tmp_path)
    backend = {"plan": plan}
    app = widget_app(monkeypatch, plan, reader, backend=backend)
    app.selectbox[0].set_value(plan.plan_id).run(timeout=45)
    assert not app.exception and any("Independent synthetic policy" in item.value for item in app.text)
    backend["outage"] = True
    app.run(timeout=45)
    assert not app.exception and any("无法加载" in item.value for item in app.caption)
    assert not any("Independent synthetic policy" in item.value for item in app.text)
    backend["outage"] = False
    next(reader.policy_source_dir.glob("*.html")).unlink()
    app.run(timeout=45)
    assert not app.exception and any("来源存档不可用" in item.value for item in app.caption)
    assert not any("Independent synthetic policy" in item.value for item in app.text)


def test_real_widget_current_backend_revision_requires_explicit_refresh_and_reselection(tmp_path, monkeypatch):
    plan, _, reader = setup_reader(tmp_path)
    backend = {"plan": plan}
    app = widget_app(monkeypatch, plan, reader, backend=backend)
    app.selectbox[0].set_value(plan.plan_id).run(timeout=45)
    revised = plan.model_dump(mode="json")
    revised["notes"] += " New backend revision."
    backend["plan"] = ProgramPlan.model_validate(revised)
    app.run(timeout=45)
    assert not app.exception and any("当前所选方案" in item.value for item in app.caption)
    assert not any("Independent synthetic policy" in item.value for item in app.text)
    next(button for button in app.button if button.key == "prog-refresh-cs-ms").click().run(timeout=45)
    assert not app.exception and app.selectbox[0].value is None
    app.selectbox[0].set_value(plan.plan_id).run(timeout=45)
    assert not app.exception and any("须重新核对" in item.value for item in app.caption)
    assert any("New backend revision" in item.value for item in app.text)
    assert not any("Independent synthetic policy" in item.value for item in app.text)
