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
    assert "Acme &lt;i&gt;Co&lt;/i&gt; [note](https://elsewhere.example/page)" in lines[0]  # Escaped HTML.
    assert "Data **intern**" in lines[0]
    assert [value for kind, value, _ in st.log if kind == "caption"] == ["🔒 面试细节和薪资：登录并分享自己的经验后解锁"]
    assert ("button", "去看看 →", ()) in st.log
