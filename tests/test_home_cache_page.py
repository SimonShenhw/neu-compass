"""OPT-02 on the real Streamlit page (AppTest with a mock API and a replaced view-cache clock).

- While the API warms up (GET 503), the hero, program row and Co-op teaser are fetched once and then
  left alone for 30 s; the first rerun after that brings them back, with no reload. Fresh content is
  not fetched again on reruns, and is fetched again after 5 min.
- The sidebar's refresh button fetches the cached content again and never repeats a POST: not the
  question, not the vote, not the Co-op submission.
- The Co-op teaser follows the session token and the contribution count the page knows: a login fetches
  it with the token, an upload response with a new count fetches it again (without repeating the POST),
  and dropping the token never shows the member's listing again. Empty lists are fresh successes too.

中文：真实 Streamlit 页面上的 OPT-02（AppTest + 模拟 API + 替换过的页面缓存时钟）。API 预热期间（GET
返回 503），hero、项目行和 Co-op 预览只取一次，然后 30 秒内不再取；之后的第一次 rerun 就能恢复，不用
重新加载页面。有效期内的内容 rerun 时不重新获取，5 分钟后重新获取。侧边栏的刷新按钮重新获取缓存的
内容，绝不重发任何 POST：提问、评价、Co-op 投稿都不会。Co-op 预览跟着会话 token 和页面已知的贡献数
走：登录后带 token 重新获取，投稿响应带回新的贡献数时也重新获取（不重发 POST），token 没了之后绝不再
显示会员看到的列表。空列表同样是有效的成功结果。
"""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from app import view_cache

START = 1000.0
SCRIPT = "from app.streamlit_app import render\nrender()"
GUEST_ROW = {"company": "Guest Visible Co", "role": "SWE", "visibility_level": 0}
MEMBER_ROW = {"company": "Member Visible Co", "role": "Quant", "visibility_level": 0}
PROGRAMS = [{"program_id": "cs-ms", "prefix": "CS", "full_name": "Synthetic CS", "course_count": 1, "plan_count": 0}]
CURRICULUM = {"program_id": "cs-ms", "prefix": "CS", "full_name": "Synthetic CS", "notes": None,
              "semesters": [{"semester": 1, "courses": [{"course_id": "neu-cs-5010", "primary_code": "CS 5010",
                                                          "primary_name": "Synthetic starter",
                                                          "requirement_type": "core", "notes": None}]}],
              "plans": [], "plan_schema_available": True}
ANSWER = "Synthetic answer."
RECEIPT = {"answer_id": "a" * 32, "answer_sha256": hashlib.sha256(ANSWER.encode("utf-8")).hexdigest(),
           "feedback_token": "t" * 43}
REFRESH_KEY = "view_cache_refresh"


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> float:
        return self.now


class Backend:
    """MockTransport handler. GETs answer 503 while `down`; every request is recorded as
    (method, path, Authorization header)."""

    def __init__(self) -> None:
        self.down = False
        self.expired = False  # A token is sent but the API no longer accepts it (401 on /coop).
        self.not_json: set[str] = set()  # GET paths answered 200 with an HTML page.
        self.curriculum = CURRICULUM
        self.empty_lists = False
        self.contribution_rows = False
        self.contribution_count = 0
        # Models an earlier contribution being published, not credit for this pending upload.
        self.upload_contribution_count = None
        self.requests: list[tuple[str, str, str | None]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization")
        path = request.url.path
        self.requests.append((request.method, path, auth))
        if request.method == "POST":
            body = json.loads(request.content)
            if path == "/chat":
                events = [{"type": "meta", "matched_via": "hybrid", "results": []},
                          {"type": "token", "text": ANSWER}, {"type": "done", "feedback": RECEIPT}]
                return httpx.Response(200, content="".join(json.dumps(e) + "\n" for e in events).encode())
            if path == "/feedback":
                return httpx.Response(200, json={"answer_id": body["answer_id"], "rating": body["rating"]})
            if path == "/coop":
                if self.upload_contribution_count is not None:
                    self.contribution_count = self.upload_contribution_count
                return httpx.Response(201, json={"coop_id": "c-synthetic", "accepted": True, "visibility_level": 0,
                                                 "status": "pending", "duplicate": False,
                                                 "contribution_count": self.contribution_count})
            return httpx.Response(404, json={"detail": "not found"})
        if self.down:
            return httpx.Response(503, json={"status": "warming", "courses_indexed": 0, "bm25_corpus": 0})
        if path in self.not_json:
            return httpx.Response(200, content=b"<html>synthetic maintenance page</html>")
        if path == "/coop" and auth and self.expired:
            return httpx.Response(401, json={"detail": "Invalid or expired session token"})
        if path == "/ready":
            return httpx.Response(200, json={"status": "ready", "courses_indexed": 4321, "bm25_corpus": 3})
        if path == "/coop":
            if self.empty_lists:
                return httpx.Response(200, json=[])
            if self.contribution_rows and auth:
                # Like the API: same public rows; only gated fields change, not the row's intrinsic level.
                return httpx.Response(200, json=[
                    {"company": "Synthetic Interview Co", "role": "SWE", "visibility_level": 1,
                     "interview_summary": "Synthetic interview" if self.contribution_count >= 1 else None},
                    {"company": "Synthetic Salary Co", "role": "SWE", "visibility_level": 2,
                     "salary_range_usd": "$40/hr" if self.contribution_count >= 2 else None},
                ])
            return httpx.Response(200, json=[MEMBER_ROW] if auth else [GUEST_ROW])
        if path == "/programs":
            return httpx.Response(200, json=[] if self.empty_lists else PROGRAMS)
        if path.startswith("/programs/"):
            return httpx.Response(200, json=self.curriculum)
        return httpx.Response(404, json={"detail": "not found"})

    def gets(self) -> list[str]:
        return sorted(path for method, path, _ in self.requests if method == "GET")

    def posts(self) -> list[str]:
        return [path for method, path, _ in self.requests if method == "POST"]


@pytest.fixture
def page(monkeypatch):
    import app.answer_feedback_view as feedback_view
    import app.api_client as api_module
    import app.cookie_session as cookies
    import app.streamlit_app as main
    import app.streamlit_auth_ui as auth
    from config import settings

    clock, backend = Clock(), Backend()
    monkeypatch.setattr(view_cache, "clock", clock)
    monkeypatch.setattr(settings, "answer_feedback_enabled", False)
    original = api_module.ApiClient
    client = lambda **kwargs: original(  # noqa: E731
        base_url="http://synthetic-widget", transport=httpx.MockTransport(backend), **kwargs)
    monkeypatch.setattr(api_module, "ApiClient", client)
    # answer_feedback_view binds ApiClient when it is first imported, so it gets the same stand-in.
    # 中文：answer_feedback_view 在第一次导入时就绑定了 ApiClient，所以给它同一个替身。
    monkeypatch.setattr(feedback_view, "ApiClient", client)
    monkeypatch.setattr(auth, "handle_oauth_callback", lambda: None)
    monkeypatch.setattr(auth, "render_auth_sidebar", lambda: None)
    monkeypatch.setattr(cookies, "restore_login_from_cookie", lambda: False)
    monkeypatch.setattr(cookies, "flush_pending_cookie", lambda: None)
    monkeypatch.setattr(main, "_render_filters_sidebar", lambda st, state: {})
    return clock, backend


def run(app: AppTest) -> AppTest:
    app.run(timeout=45)
    assert not app.exception
    return app


def markdown(app: AppTest) -> str:
    return "\n".join(item.value for item in app.markdown)


def captions(app: AppTest) -> list[str]:
    return [item.value for item in app.caption]


def test_a_warming_api_is_left_alone_for_30_s_and_then_recovers_without_a_reload(page):
    from app.discover_view import PARTIAL_NOTICE

    clock, backend = page
    backend.down = True
    app = run(AppTest.from_string(SCRIPT))
    assert "📚 NEU 研究生课程目录" in markdown(app) and "4,321" not in markdown(app)
    # Three readers of the program list (chat selector, program row, starter row): one request.
    assert backend.gets() == ["/coop", "/programs", "/ready"]
    assert PARTIAL_NOTICE in captions(app) and "暂时无法加载项目列表；课程搜索仍可使用。" in captions(app)
    clock.now = START + 10
    run(app)
    backend.down = False
    clock.now = START + view_cache.FAILURE_TTL_SECONDS - 1
    run(app)
    assert len(backend.gets()) == 3 and "4,321" not in markdown(app)
    clock.now = START + view_cache.FAILURE_TTL_SECONDS
    run(app)
    assert backend.gets() == ["/coop", "/coop", "/programs", "/programs", "/programs/cs-ms", "/ready", "/ready"]
    assert "📚 4,321 门课" in markdown(app) and "Guest Visible Co" in markdown(app)
    assert "Synthetic starter" in markdown(app) and PARTIAL_NOTICE not in captions(app)
    loaded = START + view_cache.FAILURE_TTL_SECONDS
    clock.now = loaded + view_cache.SUCCESS_TTL_SECONDS - 1
    run(app)
    assert len(backend.gets()) == 7
    clock.now = loaded + view_cache.SUCCESS_TTL_SECONDS
    run(app)
    assert len(backend.gets()) == 11 and not backend.posts()


def test_refresh_fetches_the_cached_content_again_and_never_repeats_the_question_or_the_vote(page, monkeypatch):
    from app.answer_feedback_view import CAPTURE_OPT_IN_KEY
    from config import settings

    clock, backend = page
    monkeypatch.setattr(settings, "answer_feedback_enabled", True)
    app = run(AppTest.from_string(SCRIPT))
    next(item for item in app.checkbox if item.key == CAPTURE_OPT_IN_KEY).check()
    run(app)
    app.chat_input[0].set_value("synthetic question")
    run(app)
    assert backend.posts() == ["/chat"]
    next(item for item in app.button if item.key.endswith(f"{RECEIPT['answer_id']}-up")).click()
    run(app)
    assert backend.posts() == ["/chat", "/feedback"]
    before = len(backend.gets())
    run(app)
    assert len(backend.gets()) == before  # A plain rerun fetches nothing.
    app.button(key=REFRESH_KEY).click()
    run(app)
    # The landing is gone once there is a conversation: /ready and the selector's /programs only.
    assert sorted(path for _, path, _ in backend.requests[-2:]) == ["/programs", "/ready"]
    assert len(backend.gets()) == before + 2
    run(app)
    assert backend.posts() == ["/chat", "/feedback"] and len(backend.gets()) == before + 2
    assert app.session_state["messages"][-1]["feedback_rating"] == "up"


def test_refresh_never_repeats_a_coop_submission(page):
    clock, backend = page
    app = AppTest.from_string(SCRIPT)
    app.session_state["user_id"] = "u-synthetic"
    app.session_state["user_email"] = "synthetic@northeastern.edu"
    app.session_state["session_token"] = "synthetic-session-a"
    run(app)
    app.radio[0].set_value("💼 Co-op 经验")
    run(app)
    next(item for item in app.text_input if item.label == "公司 *").input("Synthetic Co")
    next(item for item in app.text_input if item.label == "职位 *").input("Synthetic role")
    next(item for item in app.button if item.label == "提交").click()
    run(app)
    assert backend.posts() == ["/coop"]
    assert any("c-synthetic" in item.value for item in app.success)
    app.button(key=REFRESH_KEY).click()
    run(app)
    run(app)
    assert backend.posts() == ["/coop"]


def test_the_coop_teaser_follows_the_session_token(page):
    clock, backend = page
    app = run(AppTest.from_string(SCRIPT))
    assert "Guest Visible Co" in markdown(app)
    app.session_state["user_id"] = "u-synthetic"
    app.session_state["user_email"] = "synthetic@northeastern.edu"
    app.session_state["session_token"] = "synthetic-session-a"
    run(app)
    coop = [auth for method, path, auth in backend.requests if path == "/coop"]
    assert coop == [None, "Bearer synthetic-session-a"]
    assert "Member Visible Co" in markdown(app) and "Guest Visible Co" not in markdown(app)
    backend.down = True  # Without the token the guest fetch fails: the member listing is not the fallback.
    app.session_state["session_token"] = None
    app.session_state["user_id"] = None
    run(app)
    assert [auth for method, path, auth in backend.requests if path == "/coop"][-1] is None
    assert "Member Visible Co" not in markdown(app)
    assert not backend.posts()


def test_logging_in_and_out_repeats_no_question(page):
    """Roadmap OPT-02: switching identity must not resend a POST (reviewer B, batch 16, probe a5)."""
    clock, backend = page
    app = run(AppTest.from_string(SCRIPT))
    app.chat_input[0].set_value("synthetic question")
    run(app)
    assert backend.posts() == ["/chat"]
    app.session_state["user_id"] = "u-synthetic"
    app.session_state["user_email"] = "synthetic@northeastern.edu"
    app.session_state["session_token"] = "synthetic-session-a"
    run(app)
    app.session_state["session_token"] = None
    app.session_state["user_id"] = None
    run(app)
    app.button(key=REFRESH_KEY).click()
    run(app)
    assert backend.posts() == ["/chat"]


def test_an_outage_longer_than_one_failure_window_keeps_retrying_and_recovers(page):
    """The API's cold start takes 70-100 s, two or three of the documented 30 s windows (reviewer B,
    batch 16). Literal seconds here pin the documented window."""
    from app.discover_view import PARTIAL_NOTICE

    clock, backend = page
    backend.down = True
    app = run(AppTest.from_string(SCRIPT))
    assert len(backend.gets()) == 3
    for elapsed, gets in ((15, 3), (30, 6), (45, 6), (60, 9), (90, 12)):
        clock.now = START + elapsed
        run(app)  # Never a traceback, however many windows fail.
        assert len(backend.gets()) == gets and "4,321" not in markdown(app)
        assert PARTIAL_NOTICE in captions(app)
    backend.down = False
    clock.now = START + 120
    run(app)
    assert "📚 4,321 门课" in markdown(app) and "Synthetic starter" in markdown(app)
    assert PARTIAL_NOTICE not in captions(app)
    clock.now = START + 120 + 299
    run(app)
    assert len(backend.gets()) == 16  # 12 + /ready, /programs, /coop, /programs/cs-ms; fresh for 5 min.


def test_the_sidebar_refresh_keeps_an_unchanged_plan_choice(page, monkeypatch):
    """Reviewer B (batch 16): only expire_all() direct calls were tested, not the button on the page."""
    import app.program_policy_view as policy
    from app.program_view import PLAN_REVISED_NOTICE

    from tests.test_view_cache import curriculum, seed_plans

    clock, backend = page
    monkeypatch.setattr(policy, "load_selected_program_policy_evidence", lambda st, item: st.caption("Policy stub"))
    backend.curriculum = curriculum(seed_plans())
    app = AppTest.from_string(SCRIPT)
    app.session_state["selected_program_id"] = "cs-ms"
    app.session_state["nav_page"] = "🎓 培养方案 · Programs"
    run(app)
    choice = seed_plans()[0]["plan_id"]
    app.selectbox[0].set_value(choice)
    run(app)
    app.button(key=REFRESH_KEY).click()
    run(app)
    assert [path for _, path, _ in backend.requests].count("/programs/cs-ms") == 2
    assert app.selectbox[0].value == choice and any(item.value == "Policy stub" for item in app.caption)
    assert not [item for item in app.info if item.value == PLAN_REVISED_NOTICE]


CURRICULUM_SCRIPT = """
import streamlit as st
from app.program_view import _render_curriculum
_render_curriculum(st, "cs-ms")
"""


@pytest.mark.parametrize("changed", [True, False])
def test_a_refetched_curriculum_resets_the_real_plan_selectbox_only_when_its_plans_changed(page, monkeypatch, changed):
    import app.program_policy_view as policy
    from app.program_view import PLAN_REVISED_NOTICE

    from tests.test_view_cache import curriculum, seed_plans

    clock, backend = page
    monkeypatch.setattr(policy, "load_selected_program_policy_evidence", lambda st, item: st.caption("Policy stub"))
    backend.curriculum = curriculum(seed_plans())
    app = run(AppTest.from_string(CURRICULUM_SCRIPT))
    choice = seed_plans()[0]["plan_id"]
    app.selectbox[0].set_value(choice)
    run(app)
    assert app.selectbox[0].value == choice and any(item.value == "Policy stub" for item in app.caption)
    after = seed_plans()
    if changed:
        after[0]["notes"] += " Revised."
    backend.curriculum = curriculum(after)
    clock.now = START + view_cache.SUCCESS_TTL_SECONDS
    run(app)
    assert [path for _, path, _ in backend.requests] == ["/programs/cs-ms", "/programs/cs-ms"]
    notices = [item.value for item in app.info if item.value == PLAN_REVISED_NOTICE]
    if changed:
        assert app.selectbox[0].value is None and notices == [PLAN_REVISED_NOTICE]
        assert not any(item.value == "Policy stub" for item in app.caption)
        run(app)  # Said once; the selection stays cleared until the student picks again.
        assert app.selectbox[0].value is None and not [item for item in app.info if item.value == PLAN_REVISED_NOTICE]
    else:
        assert app.selectbox[0].value == choice and not notices


@pytest.mark.parametrize("body", [[], "ready", {"status": "ready", "courses_indexed": None}])
def test_an_unexpected_ready_body_shows_the_number_free_hero(page, monkeypatch, body):
    clock, backend = page
    original = Backend.__call__

    def answer(self, request):
        if request.url.path == "/ready":
            self.requests.append((request.method, request.url.path, None))
            return httpx.Response(200, json=body)
        return original(self, request)

    monkeypatch.setattr(Backend, "__call__", answer)
    app = run(AppTest.from_string(SCRIPT))
    assert "📚 NEU 研究生课程目录" in markdown(app)


def test_the_refresh_button_is_in_the_sidebar_on_every_page(page):
    from app.discover_view import PARTIAL_NOTICE

    clock, backend = page
    app = run(AppTest.from_string(SCRIPT))
    for label in ("🔍 课程搜索 · Search", "🎓 培养方案 · Programs", "💼 Co-op 经验"):
        app.radio[0].set_value(label)
        run(app)
        assert [item.key for item in app.sidebar.button] == [REFRESH_KEY]
        # The landing's notice names the button by its label (reviewer B, batch 16).
        assert [item.label for item in app.sidebar.button] == [view_cache.REFRESH_LABEL]
    assert f"「{view_cache.REFRESH_LABEL}」" in PARTIAL_NOTICE


def test_changed_plans_with_nothing_chosen_on_the_real_selectbox_say_nothing(page):
    """Reviewer A (batch 16): real Streamlit registers the selectbox's key with None, so "a key is
    present" is not "a plan was chosen"."""
    from app.program_view import PLAN_REVISED_NOTICE

    from tests.test_view_cache import curriculum, seed_plans

    from app.program_plan_view import PLAN_PLACEHOLDER

    clock, backend = page
    backend.curriculum = curriculum(seed_plans())
    app = run(AppTest.from_string(CURRICULUM_SCRIPT))
    assert app.selectbox[0].value is None
    # A cleared choice shows the placeholder in the browser, so it must read like the None option.
    assert app.selectbox[0].placeholder == PLAN_PLACEHOLDER
    after = seed_plans()
    after[0]["notes"] += " Revised."
    backend.curriculum = curriculum(after)
    clock.now = START + view_cache.SUCCESS_TTL_SECONDS
    run(app)
    assert len(backend.requests) == 2 and not [item for item in app.info if item.value == PLAN_REVISED_NOTICE]


def sidebar_captions(app: AppTest) -> list[str]:
    return [item.value for item in app.sidebar.caption]


def test_a_failed_refresh_says_the_page_shows_the_last_loaded_content(page):
    from app.streamlit_app import FALLBACK_NOTICE

    clock, backend = page
    app = run(AppTest.from_string(SCRIPT))
    assert "📚 4,321 门课" in markdown(app) and FALLBACK_NOTICE not in sidebar_captions(app)
    backend.down = True
    app.button(key=REFRESH_KEY).click()
    run(app)
    assert "📚 4,321 门课" in markdown(app) and "Guest Visible Co" in markdown(app)
    assert sidebar_captions(app).count(FALLBACK_NOTICE) == 1
    run(app)  # Still the last loaded content while the failures are fresh: still said.
    assert FALLBACK_NOTICE in sidebar_captions(app)
    backend.down = False
    clock.now = START + view_cache.FAILURE_TTL_SECONDS
    run(app)
    assert "📚 4,321 门课" in markdown(app) and FALLBACK_NOTICE not in sidebar_captions(app)


def test_a_refetch_that_is_not_json_keeps_the_page_working(page):
    """Before OPT-02 a cached success was never fetched again; now it is, so a 2xx HTML page from a
    proxy must not turn into a traceback on every page."""
    from app.streamlit_app import FALLBACK_NOTICE

    clock, backend = page
    app = run(AppTest.from_string(SCRIPT))
    backend.not_json = {"/ready", "/programs", "/coop"}
    clock.now = START + view_cache.SUCCESS_TTL_SECONDS
    run(app)  # run() asserts that the page raised nothing.
    assert "📚 4,321 门课" in markdown(app) and "Guest Visible Co" in markdown(app)
    assert FALLBACK_NOTICE in sidebar_captions(app) and "synthetic maintenance page" not in markdown(app)


def test_a_first_load_that_is_not_json_shows_the_number_free_page(page):
    from app.discover_view import PARTIAL_NOTICE

    clock, backend = page
    backend.not_json = {"/ready", "/programs", "/coop"}
    app = run(AppTest.from_string(SCRIPT))
    assert "📚 NEU 研究生课程目录" in markdown(app) and PARTIAL_NOTICE in captions(app)


def test_an_expired_session_drops_the_member_teaser_and_promises_no_retry(page):
    """Reviewer A (batch 16): a 401 is an answer, not an outage: the member listing is not kept as a
    fallback, and the landing does not say it will load later."""
    from app.discover_view import PARTIAL_NOTICE
    from app.streamlit_app import FALLBACK_NOTICE

    clock, backend = page
    app = AppTest.from_string(SCRIPT)
    app.session_state["user_id"] = "u-synthetic"
    app.session_state["user_email"] = "synthetic@northeastern.edu"
    app.session_state["session_token"] = "synthetic-session-a"
    run(app)
    assert "Member Visible Co" in markdown(app)
    backend.expired = True
    clock.now = START + view_cache.SUCCESS_TTL_SECONDS
    run(app)
    assert "Member Visible Co" not in markdown(app)
    assert PARTIAL_NOTICE not in captions(app) and FALLBACK_NOTICE not in sidebar_captions(app)


def test_empty_successful_home_lists_are_fresh_for_five_minutes(page):
    from app.discover_view import PARTIAL_NOTICE
    from app.streamlit_app import FALLBACK_NOTICE

    clock, backend = page
    backend.empty_lists = True
    app = AppTest.from_string(SCRIPT)
    for now, calls in ((START, 1), (START + 31, 1), (START + 300, 2)):
        clock.now = now
        run(app)
        assert backend.gets().count("/coop") == calls
        assert backend.gets().count("/programs") == calls
        assert PARTIAL_NOTICE not in captions(app)
        assert FALLBACK_NOTICE not in sidebar_captions(app)
        assert "**💼 最近的 Co-op 经验**" not in markdown(app)
        assert "**🎓 按培养方案浏览**" not in markdown(app)
    assert not backend.posts()


def test_upload_response_count_change_refreshes_home_teaser_without_reposting(page):
    clock, backend = page
    backend.contribution_rows = True
    backend.upload_contribution_count = 1
    app = AppTest.from_string(SCRIPT)
    app.session_state["user_id"] = "u-synthetic"
    app.session_state["user_email"] = "synthetic@northeastern.edu"
    app.session_state["session_token"] = "synthetic-session-a"
    app.session_state["user_contribution_count"] = 0
    run(app)
    assert any("🔒 这条有面试细节" in text for text in captions(app))
    app.radio[0].set_value("💼 Co-op 经验")
    run(app)
    next(item for item in app.text_input if item.label == "公司 *").input("Synthetic Pending Co")
    next(item for item in app.text_input if item.label == "职位 *").input("Synthetic role")
    next(item for item in app.button if item.label == "提交").click()
    run(app)
    assert app.session_state["user_contribution_count"] == 1
    app.radio[0].set_value("🔍 课程搜索 · Search")
    run(app)
    assert not any("🔒 这条有面试细节" in text for text in captions(app))
    assert any("🔒 这条有薪资区间" in text for text in captions(app))
    # Same token and the clock never moved, so the refetch came from the new count, not the 5-minute TTL.
    assert clock.now == START and app.session_state["session_token"] == "synthetic-session-a"
    gets = backend.gets()
    run(app)
    run(app)
    assert backend.gets() == gets
    assert backend.posts() == ["/coop"]
