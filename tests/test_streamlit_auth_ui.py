"""Tests for app.streamlit_auth_ui — import smoke + helper exposure.

The render functions need Streamlit's session machinery and aren't
exercised here; UI behavior is covered by manual QA in soft-launch."""

from __future__ import annotations

import pytest


def test_module_imports_without_streamlit_running() -> None:
    import app.streamlit_auth_ui  # noqa: F401


def test_helpers_callable() -> None:
    from app.streamlit_auth_ui import handle_oauth_callback, render_auth_sidebar
    assert callable(handle_oauth_callback)
    assert callable(render_auth_sidebar)


FIXED = "登录未完成。可从左侧栏重新发起登录。"


@pytest.mark.parametrize("value", [
    "[note](https://elsewhere.example/page)", "access_denied\n\nx", "Access-Denied", "a" * 65, "", "a b",
])
def test_oauth_error_shows_only_a_well_formed_code(value) -> None:
    """?error= comes from a URL anyone can write and st.warning renders Markdown.
    中文：?error= 来自任何人都能写的 URL，st.warning 会渲染 Markdown。"""
    from app.streamlit_auth_ui import oauth_error_message

    assert oauth_error_message("access_denied") == "登录未完成（`access_denied`）。可从左侧栏重新发起登录。"
    assert oauth_error_message(value) == FIXED


def test_the_callback_warns_with_the_checked_message() -> None:
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string("from app.streamlit_auth_ui import handle_oauth_callback\nhandle_oauth_callback()")
    app.query_params["error"] = "x\n\n[note](https://elsewhere.example/page)"
    app.run(timeout=30)
    assert not app.exception
    assert [item.value for item in app.warning] == [FIXED]
