"""Tests for app.ui_theme — pure HTML/CSS string builders.

inject_theme needs a streamlit module and isn't exercised beyond a stub;
the builders are pure functions and get full coverage, including the
html-escaping contract (catalog course names legally contain & / < / ").
"""

from __future__ import annotations

from app.ui_theme import (
    GLOBAL_CSS,
    course_header_html,
    guest_banner_html,
    hero_html,
    inject_theme,
    matched_via_badge,
    topic_pills_html,
)


# === inject_theme ===


def test_inject_theme_wraps_css_in_style_tag() -> None:
    calls: list[tuple[str, bool]] = []

    class _FakeSt:
        def markdown(self, body: str, unsafe_allow_html: bool = False) -> None:
            calls.append((body, unsafe_allow_html))

    inject_theme(_FakeSt())
    assert len(calls) == 1
    body, unsafe = calls[0]
    assert body.startswith("<style>") and body.endswith("</style>")
    assert GLOBAL_CSS in body
    assert unsafe is True


# === hero_html ===


def test_hero_guest_shows_guest_pill() -> None:
    out = hero_html(logged_in=False)
    assert "NEU-Compass" in out
    assert "Guest" in out


def test_hero_logged_in_shows_display_name_escaped() -> None:
    out = hero_html(logged_in=True, display_name="A <b>& B")
    assert "A &lt;b&gt;&amp; B" in out
    assert "<b>&" not in out


# === plain_text_html / labelled_line_html ===


def test_plain_text_lines_escape_html_and_stay_one_html_block() -> None:
    """Extracted fields go through these. A CommonMark parser must read the result as ONE HTML
    block (no Markdown inside), and newlines must not end it early."""
    from markdown_it import MarkdownIt  # noqa: PLC0415

    from app.ui_theme import labelled_line_html, plain_text_html  # noqa: PLC0415

    assert plain_text_html("a <b>&\"x\"</b>\r\nb\n\nc") == "a &lt;b&gt;&amp;&quot;x&quot;&lt;/b&gt;<br>b<br><br>c"
    line = labelled_line_html("任课老师 <i>", "[x](https://elsewhere.example) **y**\n\n$z$ :help[w]")
    assert line.startswith('<div class="nc-line"><span class="nc-line-label">任课老师 &lt;i&gt;：</span>')
    assert "\n" not in line
    assert [token.type for token in MarkdownIt("commonmark").parse(line)] == ["html_block"]


# === guest_banner_html ===


def test_guest_banner_mentions_login_path() -> None:
    """Student wording for the give-to-get tiers in coop_view: level 0 for everyone, 1 published
    contribution for interview details, 2 for salary ranges. A share counts when it is published
    (it needs a peer in the same group), not when it is approved."""
    out = guest_banner_html()
    assert "nc-banner" in out
    assert "游客" in out and "NEU 邮箱登录" in out and "经验公开后" in out and "审核" not in out
    assert "1 条看面试细节" in out and "2 条看薪资区间" in out
    assert "level-0" not in out and "preview" not in out


# === matched_via_badge ===


def test_badge_known_tiers_have_distinct_styles() -> None:
    rendered = {tier: matched_via_badge(tier) for tier in
                ("alias", "hybrid", "program", "rejected", "empty")}
    assert all("nc-badge" in v for v in rendered.values())
    # background colors must differ so tiers are visually distinguishable
    assert len({v.split("background:")[1][:8] for v in rendered.values()}) == 5


def test_badge_unknown_tier_falls_back_to_neutral() -> None:
    assert matched_via_badge("some_future_tier") == matched_via_badge("empty")


def test_badge_labels_describe_the_match_for_students() -> None:
    """The labels used to be retrieval jargon ('直达 · alias', '检索 · hybrid')."""
    labels = {tier: matched_via_badge(tier).split(">")[1].split("<")[0] for tier in
              ("alias", "hybrid", "program", "context", "rejected", "empty")}
    assert labels == {"alias": "按课程代码找到", "hybrid": "按内容检索", "program": "按培养方案",
                      "context": "接着上一个问题", "rejected": "没找到匹配的课", "empty": "没有结果"}


# === course_header_html ===


def test_course_header_includes_code_name_and_chips() -> None:
    out = course_header_html(
        code="CS 5800", name="Algorithms", term="Fall 2026",
        credits=4, delivery_mode="in_person",
    )
    assert "CS 5800" in out
    assert "Algorithms" in out
    assert "Fall 2026" in out
    assert ">4<" in out
    assert "in person" in out  # underscore replaced


def test_course_header_missing_meta_omits_chips() -> None:
    """Absent values are dropped, not dashed — a row of '—' broadcasts
    missing data instead of presenting what we have (round-3 feedback)."""
    out = course_header_html(code="CS 5800", name="Algorithms")
    assert "—" not in out
    assert "nc-meta-chip" not in out  # no empty chips row at all


def test_course_header_escapes_html_in_name() -> None:
    out = course_header_html(code="CS 5800", name="R&D <script>")
    assert "R&amp;D &lt;script&gt;" in out
    assert "<script>" not in out


# === topic_pills_html ===


def test_topic_pills_render_one_pill_per_topic() -> None:
    out = topic_pills_html(["graphs", "DP", "NP & beyond"])
    assert out.count("nc-pill") == 3
    assert "NP &amp; beyond" in out


def test_topic_pills_empty_list_renders_nothing() -> None:
    assert topic_pills_html([]) == ""


# === UI round 2 builders (2026-06) ===


def test_hero_courses_indexed_renders_count() -> None:
    from app.ui_theme import hero_html  # noqa: PLC0415

    out = hero_html(courses_indexed=6469)
    assert "6,469 门课" in out


def test_hero_no_count_falls_back_without_number() -> None:
    from app.ui_theme import hero_html  # noqa: PLC0415

    out = hero_html(courses_indexed=None)
    assert "6,469" not in out
    assert "课程目录" in out


def test_result_card_escapes_and_clamps() -> None:
    from app.ui_theme import result_card_html  # noqa: PLC0415

    out = result_card_html(
        rank=1, code="CS 5800", name="Algo <& Data>", score=0.987, pct=150,
    )
    assert "Algo &lt;&amp; Data&gt;" in out
    assert "width:100%" in out  # clamped
    assert "0.987" in out
    out_low = result_card_html(rank=2, code="X", name="Y", score=0.1, pct=-5)
    assert "width:0%" in out_low


def test_requirement_badge_known_and_fallback() -> None:
    from app.ui_theme import requirement_badge  # noqa: PLC0415

    assert "core" in requirement_badge("core")
    assert "capstone" in requirement_badge("capstone")
    # Unknown type falls back to neutral foundation style, no crash
    assert "nc-badge" in requirement_badge("weird_future_type")


def test_program_context_html_rows() -> None:
    from app.ui_theme import program_context_html  # noqa: PLC0415

    out = program_context_html([
        {
            "program_name": "MS in CS <Khoury>",
            "requirement_type": "core",
            "semester_recommended": 1,
        },
        {
            "program_name": "MSDS",
            "requirement_type": "elective_pool",
            "semester_recommended": None,
        },
    ])
    assert "MS in CS &lt;Khoury&gt;" in out
    assert "第 1 学期推荐" in out
    assert out.count("nc-prog-row") == 2
    # No semester chip for the second row
    assert out.count("学期推荐") == 1
    assert program_context_html([]) == ""


def test_prereq_label_resolved_and_dangling() -> None:
    from app.ui_theme import prereq_label_md  # noqa: PLC0415

    resolved = prereq_label_md(
        code="CS 5800", name="Algorithms", course_id="neu-cs-5800",
        requirement="required",
    )
    assert "**CS 5800**" in resolved and "必须先修" in resolved
    dangling = prereq_label_md(
        code=None, name=None, course_id="c-ghost", requirement="recommended",
    )
    assert "`c-ghost`" in dangling and "建议先修" in dangling


def test_html_helpers_keep_data_inside_one_html_block() -> None:
    """A blank line inside a value would end the HTML block, and the rest would be parsed as
    Markdown, links included. 中文：值里的空行会结束 HTML 块，后面的内容会按 Markdown 解析（包括链接）。"""
    from markdown_it import MarkdownIt  # noqa: PLC0415

    from app.ui_theme import program_context_html, result_card_html  # noqa: PLC0415

    linked = "x\r\n\r\n[note](https://elsewhere.example/page)"
    outputs = [course_header_html(code=linked, name=linked, term=linked), topic_pills_html([linked]),
               result_card_html(rank=1, code=linked, name=linked, score=0.5, pct=50),
               program_context_html([{"program_name": linked, "requirement_type": "core"}])]
    for out in outputs:
        assert "\n" not in out and "\r" not in out
        assert [token.type for token in MarkdownIt("commonmark").parse(out)] == ["html_block"]


def test_prereq_label_shows_database_text_literally() -> None:
    from markdown_it import MarkdownIt  # noqa: PLC0415

    from app.ui_theme import prereq_label_md  # noqa: PLC0415

    label = prereq_label_md(code="CS 5800", name="Algo [note](https://elsewhere.example/page) *x*\n\n# y",
                            course_id="neu-cs-5800", requirement="required")
    tokens = MarkdownIt("commonmark").parse(label)
    types = [token.type for token in tokens] + [child.type for token in tokens for child in token.children or []]
    assert "link_open" not in types and "heading_open" not in types and "em_open" in types  # *必须先修* only.
    assert types.count("strong_open") == 1 and types.count("em_open") == 1 and types.count("paragraph_open") == 1
    text = "".join(child.content for token in tokens for child in token.children or [] if child.type == "text")
    assert "Algo [note](h\u2060ttps:\u2060//elsewhere.example/page) *x* # y" in text


def test_prereq_label_code_and_bare_id_stay_literal_too() -> None:
    from markdown_it import MarkdownIt  # noqa: PLC0415

    from app.ui_theme import prereq_label_md  # noqa: PLC0415

    label = prereq_label_md(code="CS [note](https://elsewhere.example/page)", name="Algorithms",
                            course_id="neu-cs-5800", requirement="required")
    tokens = MarkdownIt("commonmark").parse(label)
    assert "link_open" not in [child.type for token in tokens for child in token.children or []]
    dangling = prereq_label_md(code=None, name=None, course_id="c-ghost\n\n`x` [note](https://elsewhere.example/page)",
                               requirement="recommended")
    assert dangling.startswith("`c-ghost x [note](https://elsewhere.example/page)`")
    tokens = MarkdownIt("commonmark").parse(dangling)
    assert [token.type for token in tokens] == ["paragraph_open", "inline", "paragraph_close"]
    assert "link_open" not in [child.type for child in tokens[1].children]


def test_empty_footer_brand_render() -> None:
    from app.ui_theme import (  # noqa: PLC0415
        empty_detail_html,
        footer_html,
        sidebar_brand_html,
    )

    assert "nc-empty" in empty_detail_html()
    assert "非商业" in footer_html()
    assert "NEU-Compass" in sidebar_brand_html()
