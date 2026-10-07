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


def test_industry_codes_stay_the_api_values_in_form_order() -> None:
    from app.coop_view import INDUSTRY_LABELS, VISIBILITY_LABELS, industry_label

    assert list(INDUSTRY_LABELS) == ["quant_fintech", "big_tech", "biotech_health", "startup", "consulting", "other"]
    assert industry_label("big_tech") == "大型科技公司" and industry_label("new_code") == "new_code"
    assert set(VISIBILITY_LABELS) == {0, 1, 2}


def test_listing_shows_reviewed_submissions_as_plain_text(monkeypatch) -> None:
    """Company, role, term and salary as escaped HTML lines; interview text via st.text. Markdown
    in a submission must stay literal (Streamlit's Markdown would keep its links)."""
    import httpx
    from markdown_it import MarkdownIt
    from streamlit.testing.v1 import AppTest

    import app.api_client as api_module

    linked = "[note](https://elsewhere.example/page)"
    rows = [{"coop_id": "c1", "company": "Acme <i>Co</i> " + linked, "role": "Data **intern**", "coop_term": "Summer 2026",
             "industry": "big_tech", "duration_months": 6, "visibility_level": 2,
             "interview_summary": "Two rounds " + linked, "technical_questions": "SQL joins",
             "salary_range_usd": "$30-35/hr " + linked}]
    original = api_module.ApiClient
    monkeypatch.setattr(api_module, "ApiClient", lambda **kwargs: original(
        base_url="http://synthetic-widget", transport=httpx.MockTransport(lambda request: httpx.Response(200, json=rows)),
        **kwargs))
    app = AppTest.from_string(
        "import streamlit as st\nfrom app.coop_view import render_coop_panel\nrender_coop_panel(st)").run(timeout=45)
    assert not app.exception
    with_data = [item.value for item in app.markdown if "elsewhere.example" in item.value or "**intern**" in item.value]
    assert len(with_data) == 2  # Company line and salary line.
    for value in with_data:
        assert value.startswith("<div") and [t.type for t in MarkdownIt("commonmark").parse(value)] == ["html_block"]
    # Without unsafe_allow_html the escaped lines would show as literal markup.
    html_lines = [item for item in app.markdown if item.value.startswith("<div")]
    assert len(html_lines) >= 4 and all(item.allow_html for item in html_lines)
    assert any("Acme &lt;i&gt;Co&lt;/i&gt;" in value for value in with_data)  # Escaped, not raw HTML.
    assert "Two rounds " + linked in [item.value for item in app.text]
    assert any(item.value == "含薪资区间" for item in app.caption)  # Level 2 only guarantees the salary.
    assert any("行业" in item.value and "大型科技公司" in item.value for item in app.markdown)


def test_lock_captions_claim_only_what_the_level_guarantees(monkeypatch) -> None:
    """derive_visibility: 1 = interview details and no salary, 2 = a salary range, with or without
    interview details. The API leaves out what the viewer has not unlocked, and a share counts once
    it is published. 中文：1 = 有面试细节、没有薪资，2 = 有薪资区间（面试细节不一定有）；API 不返回
    访客还没解锁的字段；分享在公开时才计入。"""
    import httpx
    from streamlit.testing.v1 import AppTest

    import app.api_client as api_module

    rows = [{"coop_id": coop_id, "company": "Acme", "role": coop_id, "visibility_level": level, **fields}
            for coop_id, level, fields in (("a", 1, {}), ("b", 2, {}), ("c", 2, {"salary_range_usd": "$30/hr"}),
                                           ("d", 0, {}))]
    original = api_module.ApiClient
    monkeypatch.setattr(api_module, "ApiClient", lambda **kwargs: original(
        base_url="http://synthetic-widget", transport=httpx.MockTransport(lambda request: httpx.Response(200, json=rows)),
        **kwargs))
    app = AppTest.from_string(
        "import streamlit as st\nfrom app.coop_view import render_coop_panel\nrender_coop_panel(st)").run(timeout=45)
    assert not app.exception
    assert [item.value for item in app.caption if item.value.startswith("🔒")] == [
        "🔒 这条有面试细节：你分享的经验有 1 条公开后解锁", "🔒 这条有薪资区间：你分享的经验有 2 条公开后解锁"]
    # The level label claims only what the level guarantees, and the page says when shares unlock.
    assert [item.value for item in app.caption if item.value in {"基础信息", "含面试细节", "含薪资区间"}] == [
        "含面试细节", "含薪资区间", "含薪资区间", "基础信息"]
    assert any("你分享的经验公开后，可以解锁更多细节" in item.value for item in app.caption)
    assert not any("审核通过" in item.value for item in [*app.info, *app.caption])
