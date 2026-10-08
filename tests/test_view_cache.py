"""OPT-02: the per-tab caches of read-only page content (app.view_cache) and the views that use them.

A failure is remembered for FAILURE_TTL_SECONDS and then tried again; a success is fetched again after
SUCCESS_TTL_SECONDS; a failed refetch serves the last success of the same viewer scope; an entry is
never served to another scope; expire_all() (the refresh button) makes the next read fetch again. The
clock is replaced, so nothing sleeps. The real page (AppTest) is in test_home_cache_page.py.

中文：OPT-02：页面只读内容的按标签页缓存（app.view_cache）以及用到它的视图。失败记
FAILURE_TTL_SECONDS 秒后重试；成功的结果 SUCCESS_TTL_SECONDS 秒后重新获取；重新获取失败时给出同一访客
范围上次的成功结果；记录绝不给另一个范围用；expire_all()（刷新按钮）让下一次读取重新获取。时钟是替换的，
不用真的等待。真实页面（AppTest）在 test_home_cache_page.py。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app import view_cache
from app.api_client import ApiError
from tests.ui_recorder import Recorder

ROOT = Path(__file__).resolve().parent.parent
START = 1000.0
OK_TTL = view_cache.SUCCESS_TTL_SECONDS
FAIL_TTL = view_cache.FAILURE_TTL_SECONDS


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(view_cache, "clock", fake)
    return fake


class Source:
    """fetch(): returns or raises the queued outcomes in order; the last one repeats."""

    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return copy.deepcopy(outcome)


def busy():
    return ApiError(503, "synthetic upstream text", error_type="service_busy", retry_after_seconds=30)


# === The cache itself ===


def test_a_success_is_served_until_the_success_ttl_then_fetched_again(clock):
    state, source = {}, Source({"courses_indexed": 3}, {"courses_indexed": 4})
    assert view_cache.cached(state, "k", source) == {"courses_indexed": 3}
    clock.now = START + OK_TTL - 1
    assert view_cache.cached(state, "k", source) == {"courses_indexed": 3} and source.calls == 1
    clock.now = START + OK_TTL
    assert view_cache.cached(state, "k", source) == {"courses_indexed": 4} and source.calls == 2


def test_a_failure_is_remembered_for_the_failure_ttl_then_tried_again(clock):
    original = busy()
    state, source = {}, Source(original, {"courses_indexed": 3})
    with pytest.raises(ApiError) as first:
        view_cache.cached(state, "k", source)
    # The first read gets the fetch's own error, countdown included.
    assert first.value is original and first.value.retry_after_seconds == 30
    assert first.value.detail == "服务正忙，请30 秒后手动重试。"
    clock.now = START + FAIL_TTL - 1
    with pytest.raises(ApiError) as again:
        view_cache.cached(state, "k", source)
    assert source.calls == 1  # No second request while the failure is fresh.
    # A new object with the same fields; the Retry-After countdown is no longer current, so it is gone.
    assert again.value is not original
    assert (again.value.status_code, again.value.error_type) == (503, "service_busy")
    assert again.value.detail == "服务正忙，请稍后手动重试。" and again.value.retry_after_seconds is None
    assert "synthetic upstream text" not in repr(state)
    clock.now = START + FAIL_TTL
    assert view_cache.cached(state, "k", source) == {"courses_indexed": 3} and source.calls == 2


@pytest.mark.parametrize("error", [ApiError(404, "Program 'x' not found"), ApiError(504, "timeout"),
                                   ApiError(401, "Invalid token", error_type="unauthorized"),
                                   ApiError(503, "unreachable", error_type="transport_error")])
def test_the_rebuilt_error_has_the_fields_the_pages_show(clock, error):
    state = {}
    with pytest.raises(ApiError):
        view_cache.cached(state, "k", Source(error))
    with pytest.raises(ApiError) as again:
        view_cache.cached(state, "k", Source(["unused"]))
    assert (again.value.status_code, again.value.detail, again.value.error_type) == (
        error.status_code, error.detail, error.error_type)


def test_a_failed_refetch_serves_the_last_success_until_the_next_try(clock):
    state, source = {}, Source(["v1"], busy(), ["v2"])
    assert view_cache.cached(state, "k", source) == ["v1"]
    clock.now = START + OK_TTL
    assert view_cache.cached(state, "k", source) == ["v1"] and source.calls == 2
    clock.now = START + OK_TTL + FAIL_TTL - 1
    assert view_cache.cached(state, "k", source) == ["v1"] and source.calls == 2
    clock.now = START + OK_TTL + FAIL_TTL
    assert view_cache.cached(state, "k", source) == ["v2"] and source.calls == 3


def test_an_entry_is_never_served_to_another_scope_not_even_as_the_fallback(clock):
    state = {}
    assert view_cache.cached(state, "k", Source(["member row"]), scope="session:a") == ["member row"]
    guest = Source(busy())
    with pytest.raises(ApiError):
        view_cache.cached(state, "k", guest, scope=view_cache.GUEST_SCOPE)
    assert guest.calls == 1 and "member row" not in repr(state)
    assert view_cache.peek(state, "k", scope="session:a") is None
    member = Source(["member row 2"])
    assert view_cache.cached(state, "k", member, scope="session:a") == ["member row 2"] and member.calls == 1


@pytest.mark.parametrize("stored", [["raw list"], {"value": 1}, None, "text", 3])
def test_malformed_entries_are_fetched_again(clock, stored):
    state, source = {"k": stored}, Source(["fresh"])
    assert view_cache.cached(state, "k", source) == ["fresh"] and source.calls == 1


def test_errors_other_than_api_errors_are_not_cached(clock):
    state, source = {}, Source(ValueError("synthetic"), ["fresh"])
    with pytest.raises(ValueError):
        view_cache.cached(state, "k", source)
    assert "k" not in state
    assert view_cache.cached(state, "k", source) == ["fresh"] and source.calls == 2


def test_a_clock_before_the_fetch_time_fetches_again(clock):
    state, source = {}, Source(["v1"], ["v2"])
    view_cache.cached(state, "k", source)
    clock.now = START - 1
    assert view_cache.cached(state, "k", source) == ["v2"] and source.calls == 2


def test_on_success_gets_the_previous_success_of_the_scope(clock):
    seen = []
    state, source = {}, Source(["v1"], busy(), ["v2"])
    record = lambda previous, value: seen.append((previous, value))  # noqa: E731
    view_cache.cached(state, "k", source, on_success=record)
    clock.now = START + OK_TTL
    view_cache.cached(state, "k", source, on_success=record)  # Fails: no call.
    clock.now = START + OK_TTL + FAIL_TTL
    view_cache.cached(state, "k", source, on_success=record)
    assert seen == [(None, ["v1"]), (["v1"], ["v2"])]
    view_cache.cached(state, "k", Source(["other"]), scope="session:b", on_success=record)
    assert seen[-1] == (None, ["other"])  # Another scope's success is not its previous value.


def test_store_records_a_fresh_success(clock):
    state, source = {}, Source(["fetched"])
    view_cache.store(state, "k", ["stored"])
    assert view_cache.cached(state, "k", source) == ["stored"] and source.calls == 0
    clock.now = START + OK_TTL
    assert view_cache.cached(state, "k", source) == ["fetched"] and source.calls == 1


def test_expire_all_fetches_every_entry_again_keeps_the_fallback_and_touches_nothing_else(clock):
    scopes = {view_cache.READY_KEY: view_cache.PUBLIC_SCOPE, view_cache.COOP_TEASER_KEY: "session:a",
              view_cache.PROGRAMS_KEY: view_cache.PUBLIC_SCOPE}
    state = {"messages": [{"role": "user", "content": "q"}], "pending_query": "q", "chat_program_id": "cs-ms",
             "program-plan-cs-ms": "plan-1", "_coop_upload_success": "saved"}
    others = copy.deepcopy(state)
    for key, scope in scopes.items():
        view_cache.cached(state, key, Source([f"old {key}"]), scope=scope)
    for program in ("cs-ms", "ds-ms"):
        view_cache.cached(view_cache.curricula(state), program, Source({"old": program}))
    view_cache.expire_all(state)
    assert {key: value for key, value in state.items() if key in others} == others
    for key, scope in scopes.items():
        source = Source([f"new {key}"])
        assert view_cache.cached(state, key, source, scope=scope) == [f"new {key}"] and source.calls == 1
    failing = Source(busy())  # A failed refetch after a refresh still shows the last success.
    assert view_cache.cached(view_cache.curricula(state), "cs-ms", failing) == {"old": "cs-ms"}
    assert failing.calls == 1
    source = Source({"new": "ds-ms"})
    assert view_cache.cached(view_cache.curricula(state), "ds-ms", source) == {"new": "ds-ms"}


@pytest.mark.parametrize("container", [["bad"], "bad", None])
def test_expire_all_and_curricula_replace_a_malformed_container(clock, container):
    state = {view_cache.CURRICULUM_KEY: container}
    view_cache.expire_all(state)
    assert view_cache.curricula(state) == {} and state[view_cache.CURRICULUM_KEY] == {}


def test_viewer_scope_is_one_per_token_and_does_not_hold_the_token():
    assert {view_cache.viewer_scope(state) for state in ({}, {"session_token": None}, {"session_token": ""},
                                                          {"session_token": 7})} == {view_cache.GUEST_SCOPE}
    first = view_cache.viewer_scope({"session_token": "synthetic-session-a"})
    second = view_cache.viewer_scope({"session_token": "synthetic-session-b"})
    assert len({first, second, view_cache.GUEST_SCOPE}) == 3
    assert first == view_cache.viewer_scope({"session_token": "synthetic-session-a"})
    assert "synthetic-session-a" not in first


# === The views (Streamlit stand-in) ===


class FakeClient:
    """ApiClient stand-in: each method returns or raises its queued outcomes (the last one repeats) and
    records (method, session_token, args)."""

    routes: dict = {}
    calls: list = []

    def __init__(self, *, session_token=None, timeout=30.0, **kwargs) -> None:
        self.session_token = session_token

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _answer(self, name, *args):
        FakeClient.calls.append((name, self.session_token, args))
        queue = FakeClient.routes[name]
        outcome = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return copy.deepcopy(outcome)

    def ready(self):
        return self._answer("ready")

    def list_coop(self):
        return self._answer("list_coop")

    def list_programs(self):
        return self._answer("list_programs")

    def get_program_curriculum(self, program_id):
        return self._answer("get_program_curriculum", program_id)


@pytest.fixture
def api(monkeypatch):
    import app.api_client as api_module

    FakeClient.routes, FakeClient.calls = {}, []
    monkeypatch.setattr(api_module, "ApiClient", FakeClient)
    return FakeClient


def page(state):
    """A new script run over the same session state."""
    return Recorder({"log": [], "stack": [()], "state": state, "choice": None, "html": []})


def shown(st, kind="markdown"):
    return [value for entry_kind, value, _ in st.log if entry_kind == kind]


GUEST_ROW = {"company": "Guest Visible Co", "role": "SWE", "visibility_level": 0}
MEMBER_ROW = {"company": "Member Visible Co", "role": "Quant", "visibility_level": 2,
              "salary_range_usd": "$40/hr"}


def test_coop_teaser_recovers_after_a_failure_without_fetching_on_every_rerun(api, clock):
    from app.discover_view import _render_coop_teaser

    api.routes = {"list_coop": [busy(), [GUEST_ROW]]}
    state = {}
    assert _render_coop_teaser(page(state)) is True and len(api.calls) == 1
    clock.now = START + FAIL_TTL - 1
    st = page(state)
    assert _render_coop_teaser(st) is True and len(api.calls) == 1
    assert not any("Guest Visible Co" in value for value in shown(st))
    clock.now = START + FAIL_TTL
    st = page(state)
    assert _render_coop_teaser(st) is False and len(api.calls) == 2
    assert any("Guest Visible Co" in value for value in shown(st))
    clock.now = START + FAIL_TTL + OK_TTL - 1
    _render_coop_teaser(page(state))
    assert len(api.calls) == 2


def test_coop_teaser_follows_login_token_change_and_logout(api, clock):
    from app.discover_view import _render_coop_teaser
    from app.state_manager import login, logout

    api.routes = {"list_coop": [[GUEST_ROW], [MEMBER_ROW], [GUEST_ROW]]}
    state = {}
    st = page(state)
    _render_coop_teaser(st)
    assert any("Guest Visible Co" in value for value in shown(st))
    login(state, user_id="u-synthetic", user_email="synthetic@northeastern.edu", session_token="synthetic-session-a")
    st = page(state)
    _render_coop_teaser(st)
    assert [(name, token) for name, token, _ in api.calls] == [("list_coop", None), ("list_coop", "synthetic-session-a")]
    assert any("Member Visible Co" in value for value in shown(st))
    assert not any("Guest Visible Co" in value for value in shown(st))
    logout(state)
    assert view_cache.COOP_TEASER_KEY not in state
    st = page(state)
    _render_coop_teaser(st)
    assert api.calls[-1][:2] == ("list_coop", None)
    assert not any("Member Visible Co" in value for value in shown(st))


def test_a_member_listing_is_not_the_fallback_after_the_token_goes(api, clock):
    """No logout() call (say the token is dropped by another path): the scope still changes."""
    from app.discover_view import _render_coop_teaser

    api.routes = {"list_coop": [[MEMBER_ROW], busy()]}
    state = {"session_token": "synthetic-session-a"}
    _render_coop_teaser(page(state))
    state["session_token"] = None
    st = page(state)
    assert _render_coop_teaser(st) is True
    assert not any("Member Visible Co" in value for value in shown(st)) and "Member Visible Co" not in repr(state)


def test_program_page_error_is_kept_for_the_failure_ttl_and_then_recovers(api, clock):
    from app.program_view import render_program_browser

    api.routes = {"list_programs": [ApiError(503, "unreachable", error_type="transport_error"),
                                    [{"program_id": "cs-ms", "prefix": "CS", "full_name": "Synthetic CS",
                                      "course_count": 2, "plan_count": 0}]]}
    state = {}
    for now in (START, START + FAIL_TTL - 1):
        clock.now = now
        st = page(state)
        render_program_browser(st)
        assert shown(st, "error") == ["无法加载培养方案列表: 服务暂不可用，请稍后手动重试。"]
    assert len(api.calls) == 1
    clock.now = START + FAIL_TTL
    st = page(state)
    render_program_browser(st)
    assert not shown(st, "error") and any("Synthetic CS" in value for value in shown(st))
    assert len(api.calls) == 2


def test_one_landing_rerun_asks_for_the_failed_program_list_once(api, clock):
    """The chat selector, the program row and the starter row all read the list; while its failure is
    fresh none of them sends the request again."""
    from app.discover_view import PARTIAL_NOTICE, render_discover
    from app.program_view import get_programs_cached

    api.routes = {"list_programs": [busy()], "list_coop": [[]]}
    state = {}
    st = page(state)
    with pytest.raises(ApiError):
        get_programs_cached(st)
    render_discover(st)
    assert [name for name, _, _ in api.calls] == ["list_programs", "list_coop"]
    assert shown(st, "caption") == [PARTIAL_NOTICE]


@pytest.mark.parametrize("routes,notice", [
    ({"list_programs": [[]], "list_coop": [[]]}, False),  # Empty but loaded: nothing is missing.
    ({"list_programs": [[]], "list_coop": [busy()]}, True),
    ({"list_programs": [[{"program_id": "cs-ms", "prefix": "CS", "course_count": 1}]],
      "get_program_curriculum": [busy()], "list_coop": [[]]}, True),
    ({"list_programs": [[{"program_id": "cs-ms", "prefix": "CS", "course_count": 1}]],
      "get_program_curriculum": [{"prefix": "CS", "semesters": []}], "list_coop": [[GUEST_ROW]]}, False),
    # One featured curriculum shown, the next one failed (cs-ms is fetched before ds-ms).
    ({"list_programs": [[{"program_id": "cs-ms", "prefix": "CS", "course_count": 1},
                         {"program_id": "ds-ms", "prefix": "DS", "course_count": 1}]],
      "get_program_curriculum": [{"prefix": "CS", "semesters": [{"semester": 1, "courses": [
          {"course_id": "neu-cs-5010", "primary_code": "CS 5010", "primary_name": "Synthetic course",
           "requirement_type": "core"}]}]}, busy()], "list_coop": [[]]}, True),
    ({"list_programs": [[]], "list_coop": [{"detail": "not a list"}]}, False),  # Malformed: no section.
])
def test_landing_names_the_refresh_button_only_when_a_section_is_missing(api, clock, routes, notice):
    from app.discover_view import PARTIAL_NOTICE, render_discover

    api.routes = routes
    st = page({})
    render_discover(st)
    assert (PARTIAL_NOTICE in shown(st, "caption")) is notice
    assert shown(st, "caption").count(PARTIAL_NOTICE) <= 1


def test_each_program_section_reports_a_failed_list_itself(api, clock):
    """The two rows read the same list, so on the landing either flag alone would show the notice;
    each keeps its own contract."""
    from app.discover_view import _render_program_row, _render_starter_row

    api.routes = {"list_programs": [busy()]}
    state = {}
    assert _render_program_row(page(state)) is True
    assert _render_starter_row(page(state)) is True
    assert len(api.calls) == 1


def seed_plans():
    return [p for name in ("boston_2026_2027_extended_rules.json", "boston_2026_2027_pathway_rules.json")
            for p in json.loads((ROOT / "data/program_plan_seed" / name).read_text(encoding="utf-8"))
            if p["program_id"] == "cs-ms"]


def curriculum(plans):
    row = {"course_id": "neu-cs-5010", "primary_code": "CS 5010", "primary_name": "Synthetic course",
           "requirement_type": "core", "notes": None}
    return {"program_id": "cs-ms", "prefix": "CS", "full_name": "Synthetic CS", "notes": None,
            "semesters": [{"semester": 1, "courses": [row]}], "plan_schema_available": True, "plans": plans}


@pytest.mark.parametrize("change", ["notes", "removed", "reordered", "none"])
def test_a_curriculum_refetch_with_other_plans_drops_the_plan_choice_and_says_so(api, clock, change):
    from app.program_view import PLAN_REVISED_NOTICE, _render_curriculum

    before = seed_plans()
    after = copy.deepcopy(before)
    if change == "notes":
        after[0]["notes"] += " Revised."
    elif change == "removed":
        after.pop()
    elif change == "reordered":
        after.reverse()
    api.routes = {"get_program_curriculum": [curriculum(before), curriculum(after)]}
    state = {}
    _render_curriculum(page(state), "cs-ms")
    choice = before[0]["plan_id"]
    state["program-plan-cs-ms"] = choice  # The student's selection.
    clock.now = START + OK_TTL
    st = page(state)
    _render_curriculum(st, "cs-ms")
    assert len(api.calls) == 2
    if change == "none":
        assert state["program-plan-cs-ms"] == choice and PLAN_REVISED_NOTICE not in shown(st, "info")
    else:
        assert "program-plan-cs-ms" not in state and shown(st, "info") == [PLAN_REVISED_NOTICE]
        st = page(state)
        _render_curriculum(st, "cs-ms")  # Said once.
        assert PLAN_REVISED_NOTICE not in shown(st, "info") and len(api.calls) == 2


def test_changed_plans_without_a_choice_say_nothing(api, clock):
    from app.program_view import PLAN_REVISED_NOTICE, _render_curriculum

    after = seed_plans()
    after[0]["notes"] += " Revised."
    api.routes = {"get_program_curriculum": [curriculum(seed_plans()), curriculum(after)]}
    state = {}
    _render_curriculum(page(state), "cs-ms")
    clock.now = START + OK_TTL
    st = page(state)
    _render_curriculum(st, "cs-ms")
    assert len(api.calls) == 2 and PLAN_REVISED_NOTICE not in shown(st, "info")


def test_a_choice_without_a_loaded_curriculum_is_dropped(api, clock):
    """Nothing to compare the fetched plans with, so the choice cannot be shown to be unchanged."""
    from app.program_view import get_curriculum_cached

    plans = seed_plans()
    api.routes = {"get_program_curriculum": [curriculum(plans)]}
    state = {"program-plan-cs-ms": plans[0]["plan_id"]}
    get_curriculum_cached(page(state), "cs-ms")
    assert "program-plan-cs-ms" not in state


def test_the_notice_is_only_for_the_family_whose_choice_was_dropped(api, clock):
    from app.program_view import PLAN_REVISED_NOTICE, _render_curriculum

    api.routes = {"get_program_curriculum": [curriculum(seed_plans())]}
    state = {"_program_plan_revised": "ds-ms"}
    st = page(state)
    _render_curriculum(st, "cs-ms")
    assert PLAN_REVISED_NOTICE not in shown(st, "info") and state["_program_plan_revised"] == "ds-ms"


def test_refresh_keeps_an_unchanged_plan_choice_and_a_failed_refetch_keeps_the_page(api, clock):
    from app.program_view import PLAN_REVISED_NOTICE, _render_curriculum

    plans = seed_plans()
    api.routes = {"get_program_curriculum": [curriculum(plans), busy(), curriculum(copy.deepcopy(plans))]}
    state = {}
    _render_curriculum(page(state), "cs-ms")
    state["program-plan-cs-ms"] = plans[0]["plan_id"]
    view_cache.expire_all(state)
    st = page(state)
    _render_curriculum(st, "cs-ms")  # The refetch fails: the loaded curriculum stays on the page.
    assert not shown(st, "error") and state["program-plan-cs-ms"] == plans[0]["plan_id"]
    view_cache.expire_all(state)
    st = page(state)
    _render_curriculum(st, "cs-ms")
    assert len(api.calls) == 3 and state["program-plan-cs-ms"] == plans[0]["plan_id"]
    assert PLAN_REVISED_NOTICE not in shown(st, "info")


def test_the_family_refresh_button_still_drops_the_choice_and_refetches(api, clock, monkeypatch):
    from app.program_view import _render_curriculum

    plans = seed_plans()
    api.routes = {"get_program_curriculum": [curriculum(plans)]}
    state = {}
    _render_curriculum(page(state), "cs-ms")
    state["program-plan-cs-ms"] = plans[0]["plan_id"]
    st = page(state)
    monkeypatch.setattr(Recorder, "button", lambda self, label, **kwargs: label == "刷新方案及政策证据")
    _render_curriculum(st, "cs-ms")
    assert len(api.calls) == 2 and "program-plan-cs-ms" not in state


def test_logout_drops_the_teaser_key_the_view_cache_uses():
    from app.state_manager import logout

    state = {view_cache.COOP_TEASER_KEY: object(), view_cache.PROGRAMS_KEY: "public", "filters": {"credits": 4}}
    logout(state)
    assert view_cache.COOP_TEASER_KEY not in state
    assert state[view_cache.PROGRAMS_KEY] == "public" and state["filters"] == {"credits": 4}
