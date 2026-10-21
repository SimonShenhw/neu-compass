"""Offline AppTest and HTTP guards for private, explicit-action draft entry."""

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from tests.page_layout_support import run
from tests.test_plan_draft import course, node
from tests.test_program_plan_links import plans

BAD = '<b>source</b> [x](https://elsewhere.example) **bold**'
SCRIPT = '''
import streamlit as st
from schemas.program_plan import ProgramPlan
from app.state_manager import init_state, logout, login
from app.plan_draft_view import render_plan_draft
init_state(st.session_state)
raw = st.session_state.get("test_plan")
render_plan_draft(st, ProgramPlan.model_validate(raw) if raw else None)
st.button("Synthetic logout", key="test-logout", on_click=logout, args=(st.session_state,))
st.button("Synthetic account switch", key="test-switch", on_click=login, args=(st.session_state,), kwargs={"user_id": "new", "user_email": "synthetic@example.test"})
'''


@pytest.fixture
def backend(monkeypatch):
    import app.api_client as clients

    original = clients.ApiClient
    trace = {"calls": [], "ambiguous": set(), "missing": set(), "failed": set(), "malformed": set(), "crosslisted": {}}

    def handler(request):
        trace["calls"].append((request.method, request.url.path, request.url.params.get("ref"), request.headers.get("authorization")))
        assert request.method == "GET", "No writes permitted"
        if request.url.path == "/resolve/course":
            ref = request.url.params["ref"]
            primary = trace["crosslisted"].get(ref, ref)
            match = {"course_id": primary.replace(" ", "-"), "primary_code": primary, "primary_name": BAD}
            matches = [] if ref in trace["missing"] else [match, {**match, "course_id": "other"}] if ref in trace["ambiguous"] else [match]
            return httpx.Response(200, json={"ref": ref, "matches": matches})
        assert request.url.path.startswith("/course/")
        code = request.url.path.rsplit("/", 1)[1].replace("-", " ")
        if code in trace["failed"]:
            return httpx.Response(503, json={"detail": BAD})
        item = course(code)
        return httpx.Response(200, json={"course_id": item["course_id"], "primary_code": code, "primary_name": BAD,
                                        "credits": True if code in trace["malformed"] else item["credits"]})

    prior_send = httpx.Client.send
    def guarded_send(client, request, **kwargs):
        assert isinstance(client._transport, httpx.MockTransport), "Live HTTP forbidden"
        return prior_send(client, request, **kwargs)
    monkeypatch.setattr(httpx.Client, "send", guarded_send)
    monkeypatch.setattr(clients, "ApiClient", lambda **kwargs: original(base_url="http://synthetic-draft", transport=httpx.MockTransport(handler), **kwargs))
    return trace


def page(plan="default"):
    app = AppTest.from_string(SCRIPT)
    if plan == "default":
        plan = plans()[0]
    app.session_state["test_plan"] = plan.model_dump(mode="json") if plan else None
    app.session_state["session_token"] = "synthetic-token"
    return run(app)


def add(app, value):
    app.text_area(key="plan-draft-input").set_value(value)
    app.button(key="FormSubmitter:plan-draft-form-加入草案").click()
    return run(app)


def shown(app):
    return "\n".join(e.value for group in [app.text, app.caption, app.warning, app.info, app.error, app.markdown] for e in group)


@pytest.mark.parametrize("kind", ["none", "draft"])
def test_no_selected_or_draft_plan_has_no_workspace_or_requests(backend, kind):
    plan = None if kind == "none" else plans()[0].model_copy(update={"review_status": "draft"})
    app = page(plan)
    assert not app.text_area and not backend["calls"]
    assert "我的选课草案" not in shown(app)


def test_batch_parse_dedup_request_budget_scope_and_no_rerun_requests(backend):
    app = page()
    add(app, "cs5001, CS 5002\nDS5001 cs5001")
    assert [c["code"] for c in app.session_state["plan_draft_courses"]] == ["CS 5001", "CS 5002", "DS 5001"]
    assert len(backend["calls"]) == 6
    assert all(token == "Bearer synthetic-token" for _, _, _, token in backend["calls"])
    backend["calls"].clear()
    run(app)
    add(app, "CS5001")
    assert not backend["calls"] and len(app.session_state["plan_draft_courses"]) == 3


def test_unknown_ambiguous_and_invalid_inputs_are_not_accepted(backend):
    backend["missing"].add("CS 5001")
    backend["ambiguous"].add("CS 5002")
    app = page()
    add(app, "CS5001 CS5002 <b>bad</b> CS5003")
    assert [c["code"] for c in app.session_state["plan_draft_courses"]] == ["CS 5003"]
    assert len(backend["calls"]) == 4
    assert "没有找到" in shown(app) and "对上多门" in shown(app)
    assert not any("<b>bad</b>" in e.value for e in app.markdown)


def test_failed_and_malformed_course_details_do_not_poison_other_entries(backend):
    backend["failed"].add("CS 5001")
    backend["malformed"].add("CS 5002")
    app = page()
    add(app, "CS5001 CS5002 CS5003")
    assert [c["code"] for c in app.session_state["plan_draft_courses"]] == ["CS 5003"]
    assert "未加入" in shown(app)


def test_twenty_input_limit_before_network_and_full_state_is_unchanged(backend):
    app = page()
    add(app, " ".join(f"CS{5000+i}" for i in range(21)))
    assert not backend["calls"] and not app.session_state["plan_draft_courses"]
    assert "20" in shown(app)
    app.session_state["plan_draft_courses"] = [course(f"CS {5000+i}") for i in range(19)]
    add(app, "CS5998 CS5999")
    assert len(app.session_state["plan_draft_courses"]) == 19
    assert "最多" in shown(app)


def test_alias_primary_dedup_remove_clear_and_identity_lifecycle(backend):
    backend["crosslisted"]["DS 5001"] = "CS 5001"
    app = page()
    add(app, "DS5001 CS5001")
    assert len(app.session_state["plan_draft_courses"]) == 1
    app.button(key="draft-remove-CS 5001").click()
    run(app)
    assert not app.session_state["plan_draft_courses"]
    add(app, "CS5002")
    app.button(key="draft-clear").click()
    run(app)
    assert not app.session_state["plan_draft_courses"]
    add(app, "CS5003")
    app.button(key="test-switch").click()
    run(app)
    assert not app.session_state["plan_draft_courses"]
    add(app, "CS5004")
    app.button(key="test-logout").click()
    run(app)
    assert not app.session_state["plan_draft_courses"]


def test_new_session_empty_plan_switch_preserves_courses_and_recomputes(backend):
    first = plans()[0].model_copy(update={"requirements": node("course", label="first", course_code="CS 5001")})
    app = page(first)
    add(app, "CS5001")
    assert "first" in shown(app)
    second = first.model_copy(update={"plan_id": "synthetic-second", "requirements": node("course", label="second", course_code="CS 5999")})
    app.session_state["test_plan"] = second.model_dump(mode="json")
    backend["calls"].clear()
    run(app)
    assert len(app.session_state["plan_draft_courses"]) == 1 and not backend["calls"]
    assert "second" in shown(app) and "CS 5999" in shown(app)
    fresh = page()
    assert not fresh.session_state["plan_draft_courses"]


def test_plain_labels_names_course_links_and_no_affirmative_degree_language(backend):
    plan = plans()[0].model_copy(update={"requirements": node("course", label=BAD, course_code="CS 5001")})
    app = page(plan)
    add(app, "CS5001")
    assert any(BAD in e.value for e in app.text)
    assert not any("elsewhere.example" in e.value for e in app.markdown)
    assert any("?course=CS-5001" in e.value for e in app.markdown)
    assert all(phrase not in shown(app) for phrase in ["全部满足", "可以毕业", "符合要求"])
    assert "不判断" in shown(app) and "部分规则" in shown(app)


def test_real_program_page_places_draft_after_policy_before_legacy_seed(backend, monkeypatch):
    import app.program_view as programs
    import app.program_policy_view as policy

    selected = plans()[0]
    monkeypatch.setattr(programs, "get_curriculum_cached", lambda st, pid: {"prefix": "CS", "full_name": "Synthetic",
        "plans": [selected.model_dump(mode="json")], "semesters": []})
    monkeypatch.setattr(policy, "load_selected_program_policy_evidence", lambda st, plan: st.text("POLICY_MARKER"))
    script = 'import streamlit as st\nfrom app.state_manager import init_state\nfrom app.program_view import _render_curriculum\ninit_state(st.session_state)\n_render_curriculum(st, "cs-ms")'
    app = AppTest.from_string(script)
    app.session_state["program-plan-cs-ms"] = selected.plan_id
    run(app)
    elements = list(app)
    policy_pos = next(i for i, e in enumerate(elements) if e.type == "text" and e.value == "POLICY_MARKER")
    draft_pos = next(i for i, e in enumerate(elements) if e.type == "subheader" and "我的选课草案" in e.value)
    legacy_pos = next(i for i, e in enumerate(elements) if e.type == "caption" and "以下是旧 seed" in e.value)
    assert policy_pos < draft_pos < legacy_pos and not backend["calls"]


def test_malformed_state_fails_closed_without_evaluation_or_network(backend):
    app = page()
    app.session_state["plan_draft_courses"] = [{"code": "bad"}]
    run(app)
    assert app.error and not backend["calls"]


def test_group_tree_keeps_and_or_and_selection_operators(backend):
    rule = node("all_of", children=[node("any_of", children=[node("course", course_code="CS 5001"),
        node("course", course_code="CS 5002")]), node("select", course_codes=["CS 5003"], min_courses=1)])
    app = page(plans()[0].model_copy(update={"requirements": rule}))
    assert "AND" in shown(app) and "OR" in shown(app) and "组选" in shown(app)


def test_malformed_ambiguous_entries_are_rejected_not_rendered_or_selected(backend, monkeypatch):
    previous = httpx.Client.send
    def malformed(client, request, **kwargs):
        if request.url.path == "/resolve/course":
            return httpx.Response(200, json={"matches": [None, {"course_id": "bad"}]}, request=request)
        return previous(client, request, **kwargs)
    monkeypatch.setattr(httpx.Client, "send", malformed)
    app = page()
    add(app, "CS5001")
    assert not app.session_state["plan_draft_courses"] and "未加入" in shown(app)


@pytest.mark.parametrize("credits,label", [(0, "0 学分"), (None, "学分未知")])
def test_detail_unknown_and_zero_credits_not_interchanged(backend, monkeypatch, credits, label):
    previous = httpx.Client.send
    def changed(client, request, **kwargs):
        response = previous(client, request, **kwargs)
        if request.url.path.startswith("/course/"):
            response = httpx.Response(200, json={**response.json(), "credits": credits}, request=request)
        return response
    monkeypatch.setattr(httpx.Client, "send", changed)
    app = page()
    add(app, "CS5001")
    assert app.session_state["plan_draft_courses"][0]["credits"] == credits
    assert label in shown(app)


def test_identity_mismatch_not_accepted(backend, monkeypatch):
    previous = httpx.Client.send
    def wrong_id(client, request, **kwargs):
        response = previous(client, request, **kwargs)
        if request.url.path.startswith("/course/"):
            response = httpx.Response(200, json={**response.json(), "course_id": "different"}, request=request)
        return response
    monkeypatch.setattr(httpx.Client, "send", wrong_id)
    app = page()
    add(app, "CS5001")
    assert not app.session_state["plan_draft_courses"] and "身份或字段无效" in shown(app)


def test_invalid_input_alerts_do_not_create_markdown_links(backend):
    from markdown_it import MarkdownIt

    app = page()
    add(app, "[x](https://elsewhere.example)")
    assert not backend["calls"] and not app.session_state["plan_draft_courses"]
    assert app.warning
    rendered = "\n".join(MarkdownIt("commonmark").render(e.value) for e in app.warning)
    assert '<a href=' not in rendered
