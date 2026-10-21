"""Batch L (10-21): program and plan choices kept across pages, Log out as a button callback, a course the
catalog names twice in one group shown once, and draft input that ends like a sentence. Offline AppTest over
MockTransport and synthetic data only."""

import pytest

from app.course_requisite_view import rule_lines
from app.plan_draft_view import parse_course_codes
from app.state_manager import init_state, login, logout
from schemas.course_requisites import RequisiteNode
from tests.page_layout_support import page, run
from tests.test_chat_plan_ui import choose, plan_curricula
from tests.test_course_requisite_view import FakeSt, bundle, document, render
from tests.test_program_plan_links import plans


def nav(app, word):
    radio = app.radio(key="nav_page")
    radio.set_value(next(option for option in radio.options if word in option))
    return run(app)


def subheaders(app):
    return [element.value for element in app.subheader]


def align_plan():
    return next(plan for plan in plans() if plan.pathway == "align")


# === L-1: choices kept across pages ===


def test_l1_search_program_and_plan_survive_visits_to_other_pages(monkeypatch):
    backend, documents, calls = plan_curricula(monkeypatch)
    plan = align_plan()
    app = choose(page(), plan_id=plan.plan_id)
    nav(app, "Programs")
    assert not [box for box in app.selectbox if box.key in {"chat_program_id", "chat_plan_id"}]
    nav(app, "Compare")
    nav(app, "Search")
    assert app.selectbox(key="chat_program_id").value == "cs-ms"
    assert app.selectbox(key="chat_plan_id").value == plan.plan_id
    app.chat_input[0].set_value("CS 5800")
    run(app)
    assert backend.posts[-1]["program_id"] == "cs-ms" and backend.posts[-1]["plan"]["plan_id"] == plan.plan_id


def test_l1_a_plan_revised_while_away_is_still_cleared_with_one_notice(monkeypatch):
    backend, documents, calls = plan_curricula(monkeypatch)
    app = choose(page(), plan_id=align_plan().plan_id)
    nav(app, "Programs")
    documents["cs-ms"][1]["notes"] += " revised synthetic notes"
    nav(app, "Search")
    assert app.selectbox(key="chat_program_id").value == "cs-ms"
    assert app.selectbox(key="chat_plan_id").value is None
    assert sum("方案有更新" in item.value for item in app.caption) == 1


def test_l1_choosing_no_program_is_kept_too(monkeypatch):
    plan_curricula(monkeypatch)
    app = choose(page(), plan_id=align_plan().plan_id)
    app.selectbox(key="chat_program_id").set_value(None)
    run(app)
    nav(app, "Programs")
    nav(app, "Search")
    assert app.selectbox(key="chat_program_id").value is None
    assert not [box for box in app.selectbox if box.key == "chat_plan_id"]


def test_l1_programs_page_plan_choice_survives_a_visit_to_search(monkeypatch):
    import app.program_policy_view as policy

    plan_curricula(monkeypatch)
    monkeypatch.setattr(policy, "load_selected_program_policy_evidence", lambda st, plan: None)
    chosen = next(plan for plan in plans() if plan.program_id == "cs-ms")
    app = page()
    app.session_state["selected_program_id"] = "cs-ms"
    nav(app, "Programs")
    app.selectbox(key="program-plan-cs-ms").set_value(chosen.plan_id)
    run(app)
    nav(app, "Search")
    nav(app, "Programs")
    assert app.selectbox(key="program-plan-cs-ms").value == chosen.plan_id
    app.button(key="prog-refresh-cs-ms").click()
    run(app)
    assert app.selectbox(key="program-plan-cs-ms").value is None
    nav(app, "Search")
    nav(app, "Programs")
    assert app.selectbox(key="program-plan-cs-ms").value is None


def test_l1_keep_and_clear_touch_only_choices_that_exist():
    from app.state_manager import clear_choices, keep_choices

    state = {"chat_program_id": "cs-ms", "program-plan-ds-ms": "p", "nav_page": "x", "filters": {"credits": 4}}
    keep_choices(state)
    assert state == {"chat_program_id": "cs-ms", "program-plan-ds-ms": "p", "nav_page": "x", "filters": {"credits": 4}}
    clear_choices(state)
    assert state == {"chat_program_id": None, "program-plan-ds-ms": None, "nav_page": "x", "filters": {"credits": 4}}
    empty = {}
    keep_choices(empty)
    clear_choices(empty)
    assert empty == {}


# === L-2: Log out ===


def test_l2_log_out_stays_on_the_page_and_clears_identity_lists_and_choices(monkeypatch):
    import app.streamlit_auth_ui as auth
    from app.cookie_session import COOKIE_NAME

    real_sidebar = auth.render_auth_sidebar
    backend, documents, calls = plan_curricula(monkeypatch)
    monkeypatch.setattr(auth, "render_auth_sidebar", real_sidebar)
    app = page(token="synthetic-token")
    app.session_state["user_email"] = "synthetic@example.test"
    # AppTest's st.context.cookies is a stand-in, so the guest branch is given its CSRF state up front.
    app.session_state["oauth_state"] = "synthetic-oauth-state"
    choose(app, plan_id=align_plan().plan_id)
    nav(app, "Compare")
    [button] = [button for button in app.button if button.label == "Log out"]
    button.click()
    run(app)
    assert "Compare" in app.radio(key="nav_page").value
    assert "⚖️ 课程对比" in subheaders(app) and "💬 提问" not in subheaders(app)
    assert not [button for button in app.button if button.label == "Log out"]
    assert app.session_state["user_id"] is None and app.session_state["session_token"] is None
    assert app.session_state["chat_program_id"] is None and app.session_state["chat_plan_id"] is None
    assert ("clear", COOKIE_NAME, None, None) in app.session_state["_pending_cookie"]
    nav(app, "Search")
    program = app.selectbox(key="chat_program_id")
    # A None set through session state shows the placeholder in the browser, so it must read like the None option.
    assert program.value is None and program.proto.placeholder == "不指定"
    assert not [box for box in app.selectbox if box.key == "chat_plan_id"]


def test_l2_logout_and_account_switch_clear_choices_but_keep_filters_and_page():
    state = {}
    init_state(state)
    state.update({"user_id": "a", "chat_program_id": "cs-ms", "chat_plan_id": "p", "program-plan-cs-ms": "p",
                  "filters": {"credits": 4}, "nav_page": "x", "selected_program_id": "cs-ms"})
    logout(state)
    assert [state[key] for key in ("chat_program_id", "chat_plan_id", "program-plan-cs-ms")] == [None, None, None]
    assert state["filters"] == {"credits": 4} and state["nav_page"] == "x" and state["selected_program_id"] == "cs-ms"
    login(state, user_id="a", user_email="a@example.test")
    state.update({"chat_program_id": "cs-ms", "program-plan-cs-ms": "p"})
    login(state, user_id="a", user_email="a@example.test")
    assert state["chat_program_id"] == "cs-ms" and state["program-plan-cs-ms"] == "p"
    login(state, user_id="b", user_email="b@example.test")
    assert state["chat_program_id"] is None and state["program-plan-cs-ms"] is None


# === L-3: a course the catalog names twice in one group ===

CS5008 = ("( CS 5001 with a minimum grade of C- or CS 5001 with a minimum grade of C- ); "
          "( CS 5002 with a minimum grade of C- or CS 5002 with a minimum grade of C- )")
NOTE = "（目录原文在这一组里把同一门课列了不止一次，这里只显示一次）"


def test_l3_the_cs_5008_wording_is_stored_twice_but_shown_once_with_a_note():
    doc = document(raw=CS5008)
    section = doc.requisites.prerequisite
    assert [[child.course_code for child in group.children] for group in section.rule.children] == [
        ["CS 5001", "CS 5001"], ["CS 5002", "CS 5002"]]
    st = FakeSt(choice="2026-2027")
    render(st, bundle(doc))
    assert "\n".join(rule_lines(section.rule)) in st.texts
    assert rule_lines(section.rule) == [
        "- 全部分支（AND）",
        f"  - 任一分支（OR）{NOTE}",
        "    - CS 5001（最低成绩：C-）",
        f"  - 任一分支（OR）{NOTE}",
        "    - CS 5002（最低成绩：C-）",
    ]
    assert section.raw_text in st.texts
    assert [len(group.children) for group in section.rule.children] == [2, 2]


def leaf(code, **fields):
    return RequisiteNode(kind="course", course_code=code, **fields)


def test_l3_only_identical_sibling_leaves_are_merged():
    rule = RequisiteNode(kind="any_of", children=[
        leaf("CS 5001", minimum_grade="C-"), leaf("CS 5001", minimum_grade="B"),
        leaf("CS 5001", minimum_grade="C-", concurrent_allowed=True), leaf("CS 5001", minimum_grade="C-")])
    assert rule_lines(rule) == [
        f"- 任一分支（OR）{NOTE}",
        "  - CS 5001（最低成绩：C-）",
        "  - CS 5001（最低成绩：B）",
        "  - CS 5001（最低成绩：C-；原文明示可并修；仍需核实其余条件）",
    ]
    nested = RequisiteNode(kind="all_of", children=[
        leaf("CS 5001"), RequisiteNode(kind="any_of", children=[leaf("CS 5001"), leaf("CS 5002")])])
    assert NOTE not in "\n".join(rule_lines(nested)) and "\n".join(rule_lines(nested)).count("CS 5001") == 2


# === L-4: draft input that ends like a sentence ===


@pytest.mark.parametrize(("raw", "codes"), [
    ("CS 5800.", ["CS 5800"]),
    ("CS 5800。", ["CS 5800"]),
    ("CS 5800, CS 5004.", ["CS 5800", "CS 5004"]),
    ("CS 5800。CS 5004。", ["CS 5800", "CS 5004"]),
    ("CS 5800\u200b", ["CS 5800"]),
    ("\ufeffCS\u200c 5800\u2060", ["CS 5800"]),
    ("CS 58\u200d00", ["CS 5800"]),
    ("cs5800.", ["CS 5800"]),
    ("ＣＳ　５８００．", ["CS 5800"]),
])
def test_l4_a_closing_period_or_zero_width_character_does_not_break_the_last_code(raw, codes):
    assert parse_course_codes(raw) == (codes, [])


def test_l4_invalid_tokens_are_still_reported_once_without_the_period():
    assert parse_course_codes("neu-cs-6130.") == ([], ["neu-cs-6130"])
    assert parse_course_codes("CS 5800 XYZ.") == (["CS 5800"], ["XYZ"])
    assert parse_course_codes("CS 5800 .") == (["CS 5800"], [])
