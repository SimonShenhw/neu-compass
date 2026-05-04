"""Tests for app.coop_view — import smoke. The render() body needs
Streamlit's session machinery; UI behavior is covered by manual QA in
the soft-launch (Week 6 acceptance: team of 3 hits public URL)."""

from __future__ import annotations


def test_module_imports_without_streamlit_running() -> None:
    import app.coop_view  # noqa: F401


def test_render_callable_exposed() -> None:
    """Streamlit entry-point script must expose render()."""
    from app.coop_view import render
    assert callable(render)
