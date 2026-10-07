"""Search-page layout: the chat input is pinned (main body), the privacy notice comes first, and
the landing content is not rendered while the first question is answered.

中文：搜索页布局：输入框固定在底部（放在主体里）、隐私说明在前、回答第一个问题时不渲染落地内容。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def render_function() -> ast.FunctionDef:
    tree = ast.parse((ROOT / "app/streamlit_app.py").read_text(encoding="utf-8-sig"))
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "render")


def test_chat_input_is_called_in_the_main_body_so_streamlit_pins_it():
    """Inside any `with` container (a column, expander...) Streamlit renders chat_input inline; on
    a 375×812 phone it sat about 2.5 screens down, after the landing content."""
    render = render_function()
    parents = {child: node for node in ast.walk(render) for child in ast.iter_child_nodes(node)}
    calls = [node for node in ast.walk(render) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "chat_input"]
    assert len(calls) == 1
    node = calls[0]
    # On the module itself: a container's method (chat_col.chat_input) also renders inline.
    assert isinstance(node.func.value, ast.Name) and node.func.value.id == "st"
    while node is not render:
        node = parents[node]
        assert not isinstance(node, (ast.With, ast.AsyncWith)), "chat_input must not be inside a `with` block"


def harness(monkeypatch, *, answer: str, refusal: str | None = None):
    import app.api_client as api_module
    import app.cookie_session as cookies
    import app.discover_view as discover
    import app.program_view as programs
    import app.streamlit_app as main
    import app.streamlit_auth_ui as auth
    from config import settings

    events = [{"type": "meta", "results": []}, {"type": "token", "text": answer}, {"type": "done"}]
    body = "".join(json.dumps(event) + "\n" for event in events).encode()

    def handler(request):
        if request.method == "GET" and request.url.path == "/coop":
            return httpx.Response(200, json=[])
        if request.method == "GET":
            return httpx.Response(200, json={"status": "ready", "courses_indexed": 3, "bm25_corpus": 3})
        if refusal is not None:
            return httpx.Response(409, json={"detail": refusal})
        return httpx.Response(200, content=body)

    landing_calls = []
    monkeypatch.setattr(settings, "answer_feedback_enabled", False)
    original = api_module.ApiClient
    monkeypatch.setattr(api_module, "ApiClient", lambda **kwargs: original(
        base_url="http://synthetic-widget", transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(auth, "handle_oauth_callback", lambda: None)
    monkeypatch.setattr(auth, "render_auth_sidebar", lambda: None)
    monkeypatch.setattr(cookies, "restore_login_from_cookie", lambda: False)
    monkeypatch.setattr(cookies, "flush_pending_cookie", lambda: None)
    monkeypatch.setattr(discover, "render_discover", lambda st: landing_calls.append(True))
    monkeypatch.setattr(programs, "get_programs_cached", lambda st: [])
    monkeypatch.setattr(main, "_render_filters_sidebar", lambda st, state: {})
    return landing_calls


def test_landing_is_skipped_while_the_first_question_is_answered(monkeypatch):
    """Streamlit runs the script for the submitted question, then once more (st.rerun) from history.
    Neither run may render the landing: the first answer used to appear below all of it."""
    from app.answer_feedback_view import QUERY_LOG_NOTICE

    landing_calls = harness(monkeypatch, answer="Plain answer.")
    app = AppTest.from_string("from app.streamlit_app import render\nrender()").run(timeout=45)
    assert not app.exception and len(landing_calls) == 1
    # Pinned: AppTest files a main-body chat_input under the bottom block, not under main.
    assert len(app.chat_input) == 1 and len(app.main.chat_input) == 0
    assert any(item.value == QUERY_LOG_NOTICE for item in app.caption)
    app.chat_input[0].set_value("first question").run(timeout=45)
    assert not app.exception and len(landing_calls) == 1  # No landing in either run.
    assert [msg["content"] for msg in app.session_state["messages"]] == ["first question", "Plain answer."]
    app.run(timeout=45)
    assert not app.exception and len(landing_calls) == 1


def test_a_clarification_request_is_filtered_live_as_it_is_from_history(monkeypatch):
    """A 409 detail is stored as the assistant's message; history re-renders it through
    answer_markdown, so the live render must too (AppTest keeps both passes in one tree)."""
    from app.answer_evidence_view import answer_markdown

    detail = "请先选项目，见 [说明](https://elsewhere.example/notes)"
    harness(monkeypatch, answer="unused", refusal=detail)
    app = AppTest.from_string("from app.streamlit_app import render\nrender()").run(timeout=45)
    app.chat_input[0].set_value("CS first semester").run(timeout=45)
    assert not app.exception
    assert app.session_state["messages"][-1]["content"] == f"🧭 {detail}"
    shown = [item.value for item in app.markdown]
    assert answer_markdown(f"🧭 {detail}") in shown and f"🧭 {detail}" not in shown


def test_guest_banner_is_skipped_on_the_coop_page_whose_own_notice_says_the_same(monkeypatch):
    harness(monkeypatch, answer="unused")
    app = AppTest.from_string("from app.streamlit_app import render\nrender()").run(timeout=45)
    assert not app.exception
    # Both notices list what level 0 shows (the API's tier 0 includes the industry).
    assert any("你现在是游客：课程搜索" in item.value and "行业" in item.value for item in app.markdown)
    app.radio[0].set_value("💼 Co-op 经验").run(timeout=45)
    assert not app.exception
    assert not any("你现在是游客：课程搜索" in item.value for item in app.markdown)
    assert any("你现在是游客：只能看到公开记录" in item.value and "行业" in item.value for item in app.info)
    # Curator seed rows are public as well, not only reviewed student shares.
    assert any("示例记录" in item.value and "同学分享" in item.value for item in app.caption)
