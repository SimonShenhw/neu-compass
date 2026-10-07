"""Landing discovery block: the Co-op teaser shows reviewed submissions as plain text.

中文：落地页发现区：Co-op 预览把审核过的投稿按纯文本显示。
"""

from __future__ import annotations

from markdown_it import MarkdownIt

from app.discover_view import _render_coop_teaser
from tests.ui_recorder import Recorder


def test_coop_teaser_lines_are_escaped_html_blocks_not_markdown():
    st = Recorder()
    st.session_state["_coop_teaser_cache"] = [  # Cached listing: no API call.
        {"company": "Acme <i>Co</i> [note](https://elsewhere.example/page)", "role": "Data **intern**",
         "visibility_level": 1},
        {"company": "Beta", "role": "SWE", "visibility_level": 0},
        {"company": "Gamma", "role": "QR", "visibility_level": 2},  # Only the first two are shown.
    ]
    _render_coop_teaser(st)
    lines = [value for kind, value, _ in st.log if kind == "markdown" and value.startswith("<div")]
    assert len(lines) == 2
    for line in lines:
        assert [token.type for token in MarkdownIt("commonmark").parse(line)] == ["html_block"]
        assert line in st.html  # Without unsafe_allow_html the escaped markup would show literally.
    assert "Acme &lt;i&gt;Co&lt;/i&gt; [note](https://elsewhere.example/page)" in lines[0]  # Escaped HTML.
    assert "Data **intern**" in lines[0]
    assert [value for kind, value, _ in st.log if kind == "caption"] == ["🔒 这条有面试细节：你分享的经验公开后解锁"]
    assert ("button", "去看看 →", ()) in st.log


def test_coop_teaser_lock_names_only_what_the_row_has_and_the_viewer_lacks():
    """visibility_level comes from what a row holds (derive_visibility): 1 = interview details and no
    salary, 2 = a salary range, with or without interview details. The API leaves out what the
    viewer has not unlocked, so only what the level guarantees is claimed, and an unlocked field
    needs no lock."""
    def captions(*rows):
        st = Recorder()
        st.session_state["_coop_teaser_cache"] = list(rows)
        _render_coop_teaser(st)
        return [value for kind, value, _ in st.log if kind == "caption"]

    base = {"company": "Acme", "role": "SWE"}
    assert captions({**base, "visibility_level": 1}) == ["🔒 这条有面试细节：你分享的经验公开后解锁"]
    assert captions({**base, "visibility_level": 2}) == ["🔒 这条有薪资区间：你分享的经验公开后解锁"]
    assert captions({**base, "visibility_level": 2, "interview_summary": "two rounds"}) == [
        "🔒 这条有薪资区间：你分享的经验公开后解锁"]
    assert captions({**base, "visibility_level": 1, "technical_questions": "SQL"}) == []
    assert captions({**base, "visibility_level": 2, "salary_range_usd": "$30/hr"}) == []  # Salary only: all there is.
    assert captions({**base, "visibility_level": 2, "interview_summary": "x", "salary_range_usd": "$30/hr"}) == []
    assert captions({**base, "visibility_level": 0}) == []


def test_starter_card_values_stay_inside_one_html_block():
    from app.discover_view import _starter_card_html  # noqa: PLC0415

    card = _starter_card_html(code="CS 5010", name="Program Design\n\n[note](https://elsewhere.example/page)",
                              prefix="CS")
    assert "\n" not in card and [token.type for token in MarkdownIt("commonmark").parse(card)] == ["html_block"]


def test_starter_row_shows_each_card_as_escaped_html():
    """Every value is escaped (the code too), and the card is passed with unsafe_allow_html; without
    it the escaped markup would show literally. 中文：每个值都转义（课程代码也是），卡片带
    unsafe_allow_html 传入；否则转义后的标记会原样显示出来。"""
    from app.discover_view import _render_starter_row  # noqa: PLC0415

    st = Recorder()
    st.session_state["_programs_cache"] = [{"program_id": "cs-ms", "prefix": "CS <i>MS</i>"}]
    st.session_state["_curriculum_cache"] = {"cs-ms": {"prefix": "CS <i>MS</i>", "semesters": [{"semester": 1, "courses": [
        {"course_id": "neu-cs-5010", "primary_code": "CS <b>5010</b>", "primary_name": "Design <u>x</u>",
         "requirement_type": "core"}]}]}}
    _render_starter_row(st)
    (card,) = (value for kind, value, _ in st.log if kind == "markdown" and value.startswith("<div"))
    assert card in st.html
    assert "CS &lt;b&gt;5010&lt;/b&gt;" in card and "Design &lt;u&gt;x&lt;/u&gt;" in card and "CS &lt;i&gt;MS" in card
    assert ("button", "查看", ()) in st.log
