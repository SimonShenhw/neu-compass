"""Tests for app.coop_view — import smoke. The render() body needs
Streamlit's session machinery; UI behavior is covered by manual QA in
the soft-launch (Week 6 acceptance: team of 3 hits public URL)."""

from __future__ import annotations

import pytest


def test_module_imports_without_streamlit_running() -> None:
    import app.coop_view  # noqa: F401


def test_render_callable_exposed() -> None:
    """Streamlit entry-point script must expose render()."""
    from app.coop_view import render
    assert callable(render)


@pytest.mark.parametrize("status", ["pending", "approved", "rejected", "published"])
@pytest.mark.parametrize("duplicate", [True, False])
def test_upload_result_uses_server_count_and_review_state(status, duplicate) -> None:
    from app.coop_view import apply_upload_result
    state = {"user_contribution_count": 99}
    apply_upload_result(state, {
        "coop_id": "c1", "status": status, "duplicate": duplicate,
        "contribution_count": 0, "contribution_credited": False,
    })
    assert state["user_contribution_count"] == 0
    message = state["_coop_upload_success"]
    assert "c1" in message
    assert ("重复提交" in message) == duplicate
    if status == "pending":
        assert "尚未公开" in message
        assert "未新增贡献奖励" in message
