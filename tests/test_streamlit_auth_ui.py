"""Tests for app.streamlit_auth_ui — import smoke + helper exposure.

The render functions need Streamlit's session machinery and aren't
exercised here; UI behavior is covered by manual QA in soft-launch."""

from __future__ import annotations


def test_module_imports_without_streamlit_running() -> None:
    import app.streamlit_auth_ui  # noqa: F401


def test_helpers_callable() -> None:
    from app.streamlit_auth_ui import handle_oauth_callback, render_auth_sidebar
    assert callable(handle_oauth_callback)
    assert callable(render_auth_sidebar)
