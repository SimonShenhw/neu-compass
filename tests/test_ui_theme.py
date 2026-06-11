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


# === guest_banner_html ===


def test_guest_banner_mentions_login_path() -> None:
    out = guest_banner_html()
    assert "nc-banner" in out
    assert "level-0" in out


# === matched_via_badge ===


def test_badge_known_tiers_have_distinct_styles() -> None:
    rendered = {tier: matched_via_badge(tier) for tier in
                ("alias", "hybrid", "program", "rejected", "empty")}
    assert all("nc-badge" in v for v in rendered.values())
    # background colors must differ so tiers are visually distinguishable
    assert len({v.split("background:")[1][:8] for v in rendered.values()}) == 5


def test_badge_unknown_tier_falls_back_to_neutral() -> None:
    assert matched_via_badge("some_future_tier") == matched_via_badge("empty")


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


def test_course_header_missing_meta_shows_dash() -> None:
    out = course_header_html(code="CS 5800", name="Algorithms")
    assert out.count("—") == 3  # term / credits / mode all dashed


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
