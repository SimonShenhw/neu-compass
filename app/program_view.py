"""Streamlit Program browser: 培养方案 card grid → per-semester curriculum.

Run:
    uv run streamlit run app/program_view.py

Surfaces the Layer 3 ontology head-on: pick a program, see its required
courses grouped by recommended semester, jump into any course's detail
panel. Until now this data only leaked out via /course/{id} program
context — students had no way to ask "show me the whole AAI plan".

State contract (the main app owns navigation; this module only sets flags):
  - selected_program_id: which program's curriculum is open (None = grid).
  - pending_nav_to_search + selected_course_id: set when the user clicks
    查看 on a curriculum row — streamlit_app routes to the search page's
    detail panel on the next rerun. nav_page is NEVER touched here
    (writing a widget-bound key after the widget rendered raises
    StreamlitAPIException; see the filter-clear comment in streamlit_app).
  - _programs_cache / _curriculum_cache: per-tab response caches
    (underscore prefix = transient cache, not user state). Failures are
    NOT cached so a warming API recovers on the next rerun.

The fetch helpers (get_programs_cached / get_curriculum_cached) are shared
with app.discover_view so the landing teasers and this page hit the same
cache instead of double-fetching per tab.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# === Shared fetch helpers (also imported by app.discover_view) ===


def get_programs_cached(st) -> list[dict]:
    """GET /programs once per browser tab, cached in _programs_cache.

    Raises ApiError on an uncached failure — the program page renders
    st.error, the landing discovery block silently drops its section."""
    from app.api_client import ApiClient  # noqa: PLC0415

    cached = st.session_state.get("_programs_cache")
    if cached is not None:
        return cached
    with ApiClient(
        session_token=st.session_state.get("session_token"), timeout=8.0,
    ) as api:
        programs = api.list_programs()
    st.session_state["_programs_cache"] = programs
    return programs


def get_curriculum_cached(st, program_id: str) -> dict:
    """GET /programs/{id} once per (tab, program), cached in
    _curriculum_cache[program_id]. Raises ApiError on uncached failure
    (including 404 for unseeded ids) — callers decide how loud to be."""
    from app.api_client import ApiClient  # noqa: PLC0415

    cache = st.session_state.get("_curriculum_cache")
    if cache is None:
        cache = {}
        st.session_state["_curriculum_cache"] = cache
    if program_id in cache:
        return cache[program_id]
    with ApiClient(
        session_token=st.session_state.get("session_token"), timeout=8.0,
    ) as api:
        curriculum = api.get_program_curriculum(program_id)
    cache[program_id] = curriculum
    return curriculum


# === Pure HTML builders (escaped — catalog names can contain & < ") ===


def _program_card_html(*, prefix: str, full_name: str, course_count: int) -> str:
    """Program card: big blue prefix + full name + curriculum-size pill.
    The 查看课程表 button below it is a Streamlit widget (buttons can't
    live inside markdown HTML), so the card itself stays click-free."""
    return (
        '<div class="nc-card">'
        '<span style="color:#1677FF;font-weight:800;font-size:1.6rem;'
        f'letter-spacing:0.5px;">{html.escape(prefix)}</span>'
        f'<p class="nc-card-name">{html.escape(full_name)}</p>'
        f'<span class="nc-pill">{int(course_count)} 门课程</span>'
        "</div>"
    )


def _program_header_html(*, prefix: str, full_name: str) -> str:
    """Header card for the curriculum view (selected program)."""
    return (
        '<div class="nc-card">'
        f'<span class="nc-card-code" style="font-size:1.35rem;">'
        f"{html.escape(prefix)}</span>"
        f'<p class="nc-card-name">{html.escape(full_name)}</p>'
        "</div>"
    )


def _course_row_html(
    *, code: str, name: str, requirement_type: str, notes: str | None,
) -> str:
    """One curriculum row: blue bold code + name + requirement badge
    (+ optional edge note). Badge comes from ui_theme.requirement_badge so
    the colors stay in lockstep with the course-detail panel — duplicating
    the core/foundation/elective_pool/capstone color table here would
    drift on the next palette pass."""
    from app.ui_theme import requirement_badge  # noqa: PLC0415

    note_html = ""
    if notes:
        note_html = (
            '<div style="color:#8A94A6;font-size:0.78rem;margin-top:2px;">'
            f"{html.escape(notes)}</div>"
        )
    return (
        '<div class="nc-result-card">'
        f'<span class="nc-result-code">{html.escape(code)}</span> '
        f'<span class="nc-result-name">{html.escape(name)}</span> '
        f"{requirement_badge(requirement_type)}"
        f"{note_html}"
        "</div>"
    )


# === Panels ===


def render_program_browser(st) -> None:
    """培养方案 browser panel. Caller owns page config / theme / auth
    chrome — same mounting contract as coop_view.render_coop_panel, so
    the main app can mount it as a nav page. Never lets ApiError escape:
    a down API degrades to st.error, not a stack trace."""
    from app.api_client import ApiError  # noqa: PLC0415

    st.subheader("🎓 培养方案 · Programs")
    st.caption("按学期浏览每个 program 的课程表 · 点击课程查看详情")

    selected = st.session_state.get("selected_program_id")
    if selected:
        if st.button("← 所有培养方案", key="prog-back"):
            st.session_state["selected_program_id"] = None
            st.rerun()
        _render_curriculum(st, selected)
        return

    try:
        programs = get_programs_cached(st)
    except ApiError as e:
        st.error(f"无法加载培养方案列表: {e.detail}")
        return

    if not programs:
        st.info("还没有培养方案数据 — 运行 seed 脚本后刷新。")
        return

    cols = st.columns(2)
    for i, p in enumerate(programs):
        with cols[i % 2]:
            st.markdown(
                _program_card_html(
                    prefix=str(p.get("prefix", "")),
                    full_name=str(p.get("full_name", "")),
                    course_count=int(p.get("course_count", 0)),
                ),
                unsafe_allow_html=True,
            )
            if st.button(
                "查看课程表", key=f"prog-{p['program_id']}",
                use_container_width=True,
            ):
                st.session_state["selected_program_id"] = p["program_id"]
                st.rerun()


def _render_curriculum(st, program_id: str) -> None:
    """Per-semester course table for one program. 查看 buttons hand off to
    the SEARCH page's detail panel via pending_nav_to_search — the detail
    renderer (evidence bubbles, prereq rows) lives there and duplicating
    it here would fork the UI."""
    from app.api_client import ApiError  # noqa: PLC0415

    try:
        cur = get_curriculum_cached(st, program_id)
    except ApiError as e:
        st.error(f"无法加载课程表: {e.detail}")
        return

    st.markdown(
        _program_header_html(
            prefix=str(cur.get("prefix", "")),
            full_name=str(cur.get("full_name", "")),
        ),
        unsafe_allow_html=True,
    )
    if cur.get("notes"):
        st.caption(cur["notes"])

    semesters = cur.get("semesters", [])
    if not semesters:
        st.info("该培养方案还没有课程数据。")
        return

    for group in semesters:
        sem = group.get("semester")
        st.markdown(f"**第 {int(sem)} 学期推荐**" if sem else "**任意学期**")
        for c in group.get("courses", []):
            row_cols = st.columns([5, 1])
            row_cols[0].markdown(
                _course_row_html(
                    code=str(c.get("primary_code", "")),
                    name=str(c.get("primary_name", "")),
                    requirement_type=str(c.get("requirement_type", "")),
                    notes=c.get("notes"),
                ),
                unsafe_allow_html=True,
            )
            if row_cols[1].button(
                "查看", key=f"progcourse-{program_id}-{c['course_id']}",
                use_container_width=True,
            ):
                st.session_state["selected_course_id"] = c["course_id"]
                st.session_state["pending_nav_to_search"] = True
                st.rerun()


def render() -> None:
    """Standalone Program page (page config + theme + panel). The main app
    (streamlit_app) mounts render_program_browser directly instead."""
    import streamlit as st  # noqa: PLC0415

    from app.state_manager import init_state  # noqa: PLC0415
    from app.ui_theme import inject_theme  # noqa: PLC0415

    st.set_page_config(page_title="NEU-Compass · Programs", layout="wide")
    inject_theme(st)
    init_state(st.session_state)
    render_program_browser(st)


__all__ = [
    "get_curriculum_cached",
    "get_programs_cached",
    "render",
    "render_program_browser",
]


# `__main__` only: Streamlit sets the MAIN script's __name__ to "__main__",
# so `streamlit run app/program_view.py` works while imports from
# streamlit_app / tests never render (see the coop_view sys.argv bug note).
if __name__ == "__main__":
    render()
