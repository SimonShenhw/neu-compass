"""The real Streamlit page (AppTest with a mock API) given the error event /chat writes since FIX-01:
the partial answer and the fixed notice are shown once through the answer filter, no feedback
receipt is kept, and later reruns never POST /chat again, also when the question came from a sample
chip. Set-up follows test_request_admission.py's page test.

中文：真实的 Streamlit 页面（AppTest + 模拟 API）收到 FIX-01 之后 /chat 写出的错误事件：部分回答和
固定提示经过回答过滤只显示一次，不保留反馈凭证；之后的 rerun 不会再 POST /chat，问题来自示例按钮
时也一样。页面搭法照 test_request_admission.py 里的页面测试。
"""

from __future__ import annotations

import json

import httpx
import pytest

from api.routes.chat import STREAM_ERROR_DETAIL, _stream_error_event


def _body(error_type: str, tokens: list[str]) -> bytes:
    out = (json.dumps({"type": "meta", "matched_via": "hybrid", "results": []}) + "\n").encode("utf-8")
    for token in tokens:
        out += (json.dumps({"type": "token", "text": token}) + "\n").encode("utf-8")
    return out + _stream_error_event(error_type) + (json.dumps({"type": "done"}) + "\n").encode("utf-8")


def _page(monkeypatch: pytest.MonkeyPatch, body: bytes, posts: list[str]):  # noqa: ANN202
    from streamlit.testing.v1 import AppTest  # noqa: PLC0415

    import app.api_client as api_module  # noqa: PLC0415
    import app.cookie_session as cookies  # noqa: PLC0415
    import app.discover_view as discover  # noqa: PLC0415
    import app.program_view as programs  # noqa: PLC0415
    import app.streamlit_app as main  # noqa: PLC0415
    import app.streamlit_auth_ui as auth  # noqa: PLC0415
    from config import settings  # noqa: PLC0415

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"status": "ready", "courses_indexed": 3, "bm25_corpus": 3})
        posts.append(request.url.path)
        return httpx.Response(200, content=body)

    monkeypatch.setattr(settings, "answer_feedback_enabled", False)
    original = api_module.ApiClient
    monkeypatch.setattr(api_module, "ApiClient", lambda **kwargs: original(
        base_url="http://synthetic-widget", transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(auth, "handle_oauth_callback", lambda: None)
    monkeypatch.setattr(auth, "render_auth_sidebar", lambda: None)
    monkeypatch.setattr(cookies, "restore_login_from_cookie", lambda: False)
    monkeypatch.setattr(cookies, "flush_pending_cookie", lambda: None)
    monkeypatch.setattr(discover, "render_discover", lambda st: None)
    monkeypatch.setattr(programs, "get_programs_cached", lambda st: [])
    monkeypatch.setattr(main, "_render_filters_sidebar", lambda st, state: {})
    app = AppTest.from_string("from app.streamlit_app import render\nrender()").run(timeout=45)
    assert not app.exception and not posts
    return app


@pytest.mark.parametrize(("error_type", "tokens"), [
    ("upstream_error", ["partial "]),
    ("no_answer", []),
    ("internal_error", ["ok"]),
])
def test_error_event_is_shown_once_and_reruns_do_not_post_again(
    monkeypatch: pytest.MonkeyPatch, error_type: str, tokens: list[str],
) -> None:
    from app.answer_evidence_view import answer_markdown  # noqa: PLC0415

    posts: list[str] = []
    app = _page(monkeypatch, _body(error_type, tokens), posts)
    app.chat_input[0].set_value("synthetic question").run(timeout=45)
    assert not app.exception and posts == ["/chat"]
    messages = app.session_state["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    notice = f"⚠️ {STREAM_ERROR_DETAIL[error_type]}"
    expected = "".join(tokens) + "\n\n" + notice if tokens else notice
    assert messages[-1]["content"] == expected and "feedback" not in messages[-1]
    shown = [item.value.strip() for item in app.markdown]
    assert shown.count(answer_markdown(expected).strip()) == 1
    app.run(timeout=45)
    app.run(timeout=45)
    assert not app.exception and posts == ["/chat"]


def test_sample_chip_error_then_reruns_do_not_post_again(monkeypatch: pytest.MonkeyPatch) -> None:
    posts: list[str] = []
    app = _page(monkeypatch, _body("upstream_error", ["partial "]), posts)
    app.button(key="sample-0").click().run(timeout=45)
    assert not app.exception and posts == ["/chat"]
    app.run(timeout=45)
    app.run(timeout=45)
    assert not app.exception and posts == ["/chat"]
