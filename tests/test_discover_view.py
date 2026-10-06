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
    assert [value for kind, value, _ in st.log if kind == "caption"] == ["🔒 这条有面试细节：分享自己的经验并通过审核后解锁"]
    assert ("button", "去看看 →", ()) in st.log


def test_coop_teaser_lock_names_only_what_the_row_has_and_the_viewer_lacks():
    """visibility_level is what a row contains; the API leaves out what the viewer has not
    unlocked. A level-1 row has no salary, and an unlocked field needs no lock."""
    def captions(*rows):
        st = Recorder()
        st.session_state["_coop_teaser_cache"] = list(rows)
        _render_coop_teaser(st)
        return [value for kind, value, _ in st.log if kind == "caption"]

    base = {"company": "Acme", "role": "SWE"}
    assert captions({**base, "visibility_level": 2}) == ["🔒 这条有面试细节和薪资区间：分享自己的经验并通过审核后解锁"]
    assert captions({**base, "visibility_level": 2, "interview_summary": "two rounds"}) == [
        "🔒 这条有薪资区间：分享自己的经验并通过审核后解锁"]
    assert captions({**base, "visibility_level": 1, "technical_questions": "SQL"}) == []
    assert captions({**base, "visibility_level": 2, "interview_summary": "x", "salary_range_usd": "$30/hr"}) == []
    assert captions({**base, "visibility_level": 0}) == []


def test_starter_card_values_stay_inside_one_html_block():
    from app.discover_view import _starter_card_html  # noqa: PLC0415

    card = _starter_card_html(code="CS 5010", name="Program Design\n\n[note](https://elsewhere.example/page)",
                              prefix="CS")
    assert "\n" not in card and [token.type for token in MarkdownIt("commonmark").parse(card)] == ["html_block"]
