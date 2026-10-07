"""Programs page: database text stays text (HTML cards on one line, notes as literal Markdown).

中文：培养方案页：数据库里的文字按文字显示（HTML 卡片留在一行里，说明按纯文字放进 Markdown）。
"""

from __future__ import annotations

from markdown_it import MarkdownIt

LINKED = "x\r\n\r\n[note](https://elsewhere.example/page)"


def test_cards_keep_database_text_inside_one_html_block() -> None:
    """A blank line inside a value would end the HTML block, and the rest would be parsed as
    Markdown, links included. 中文：值里的空行会结束 HTML 块，后面的内容会按 Markdown 解析（包括链接）。"""
    from app.program_view import _course_row_html, _program_card_html, _program_header_html

    outputs = [_program_card_html(prefix=LINKED, full_name=LINKED, course_count=3),
               _program_header_html(prefix=LINKED, full_name=LINKED),
               _course_row_html(code=LINKED, name=LINKED, requirement_type="core", notes=LINKED)]
    for out in outputs:
        assert "\n" not in out and "\r" not in out
        assert [token.type for token in MarkdownIt("commonmark").parse(out)] == ["html_block"]
    assert "Acme &amp; &lt;Co&gt;" in _program_header_html(prefix="CS", full_name="Acme & <Co>")


def test_curriculum_shows_database_text_as_written(monkeypatch) -> None:
    import httpx
    from streamlit.testing.v1 import AppTest

    import app.api_client as api_module
    from app.answer_evidence_view import literal_markdown

    curriculum = {"program_id": "cs-ms", "prefix": "CS", "full_name": "MS " + LINKED, "notes": "Notes " + LINKED,
                  "plans": [], "semesters": [{"semester": 1, "courses": [
                      {"course_id": "neu-cs-5010", "primary_code": "CS 5010", "primary_name": "Design " + LINKED,
                       "requirement_type": "core", "notes": "Edge " + LINKED}]}]}
    original = api_module.ApiClient
    monkeypatch.setattr(api_module, "ApiClient", lambda **kwargs: original(
        base_url="http://synthetic-widget",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=curriculum)), **kwargs))
    app = AppTest.from_string(
        "import streamlit as st\nfrom app.program_view import render_program_browser\nrender_program_browser(st)")
    app.session_state["selected_program_id"] = "cs-ms"
    app.run(timeout=45)
    assert not app.exception
    assert literal_markdown(curriculum["notes"]) in [item.value for item in app.caption]
    cards = [item for item in app.markdown if item.value.startswith("<div")]
    assert len(cards) == 2 and all(item.allow_html for item in cards)  # The header and the one row.
    for item in cards:
        assert [token.type for token in MarkdownIt("commonmark").parse(item.value)] == ["html_block"]
