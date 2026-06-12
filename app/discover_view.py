"""Landing-page discovery block — shown only while chat history is empty.

Cold-start users land on an empty chat column and don't know what the
product can do beyond the sample-query chips (Week 8 review finding). This
block turns the blank space into three teasers, each one click from real
content:

  🎓 按培养方案浏览 — program chips → the Programs page (curriculum view)
  🔥 入门推荐       — one semester-1 core/foundation course per featured
                      program → course detail on the search page
  💼 Co-op 风向     — two recent Co-op one-liners → the Co-op page

The main app owns navigation; this module only sets flags + st.rerun():
  - pending_nav_to_programs (+ selected_program_id) — program chip click
  - pending_nav_to_coop — Co-op "去看看" click
  - selected_course_id — 入门推荐 查看 click (stays on the search page)

Defensive by contract: every fetch is wrapped in try/except ApiError and a
failed endpoint silently drops its section — the landing must render even
when half the backend is warming. Program data shares program_view's
per-tab caches (_programs_cache / _curriculum_cache) so the landing and
the Programs page never double-fetch; the Co-op teaser keeps its own
_coop_teaser_cache (fetched once per tab, failure cached as [] like the
hero's _ready_info — a 30s timeout per rerun would freeze the landing).
"""

from __future__ import annotations

import html

# Featured programs for the 入门推荐 row, in display order. Ids missing
# from the seeded set silently drop out (checked against the /programs
# listing first, so unseeded ids never trigger per-rerun 404 fetches).
_FEATURED_PROGRAM_IDS: tuple[str, ...] = ("aai-ms", "cs-ms", "ds-ms")


def _semester1_pick(curriculum: dict) -> dict | None:
    """First semester-1 core/foundation course of a curriculum dict
    (the GET /programs/{id} shape), or None when the program has no
    semester-1 core/foundation entry. Pure dict logic — testable without
    Streamlit or a live API."""
    for group in curriculum.get("semesters", []):
        if group.get("semester") != 1:
            continue
        for course in group.get("courses", []):
            if course.get("requirement_type") in ("core", "foundation"):
                return course
    return None


def _starter_card_html(*, code: str, name: str, prefix: str) -> str:
    """Compact 入门推荐 card: blue code + program pill + course name."""
    return (
        '<div class="nc-result-card">'
        f'<span class="nc-result-code">{html.escape(code)}</span> '
        f'<span class="nc-pill">{html.escape(prefix)}</span><br>'
        f'<span class="nc-result-name">{html.escape(name)}</span>'
        "</div>"
    )


def _render_program_row(st) -> None:
    """🎓 chips, one per seeded program — clicking hands off to the
    Programs page with that program pre-selected."""
    from app.api_client import ApiError  # noqa: PLC0415
    from app.program_view import get_programs_cached  # noqa: PLC0415

    try:
        programs = get_programs_cached(st)
    except ApiError:
        return
    if not programs:
        return

    st.markdown("**🎓 按培养方案浏览 / Browse by program:**")
    cols = st.columns(min(len(programs), 4))
    for i, p in enumerate(programs):
        label = f"{p.get('prefix', '?')} · {int(p.get('course_count', 0))} 门课"
        if cols[i % len(cols)].button(
            label, key=f"disc-prog-{p['program_id']}",
            use_container_width=True,
        ):
            st.session_state["selected_program_id"] = p["program_id"]
            st.session_state["pending_nav_to_programs"] = True
            st.rerun()


def _render_starter_row(st) -> None:
    """🔥 one semester-1 core/foundation course per featured program.
    Featured ids are validated against the /programs listing first so an
    unseeded id costs nothing (no 404 round-trip per rerun)."""
    from app.api_client import ApiError  # noqa: PLC0415
    from app.program_view import (  # noqa: PLC0415
        get_curriculum_cached,
        get_programs_cached,
    )

    try:
        available = {p["program_id"] for p in get_programs_cached(st)}
    except ApiError:
        return

    picks: list[tuple[str, dict]] = []  # (program prefix, course dict)
    for pid in _FEATURED_PROGRAM_IDS:
        if pid not in available:
            continue
        try:
            cur = get_curriculum_cached(st, pid)
        except ApiError:
            continue
        course = _semester1_pick(cur)
        if course:
            picks.append((str(cur.get("prefix", "")), course))
    if not picks:
        return

    st.markdown("**🔥 入门推荐 / Starter picks:**")
    cols = st.columns(len(picks))
    for col, (prefix, course) in zip(cols, picks):
        col.markdown(
            _starter_card_html(
                code=str(course.get("primary_code", "")),
                name=str(course.get("primary_name", "")),
                prefix=prefix,
            ),
            unsafe_allow_html=True,
        )
        if col.button(
            "查看", key=f"disc-course-{course['course_id']}",
            use_container_width=True,
        ):
            st.session_state["selected_course_id"] = course["course_id"]
            st.rerun()


def _render_coop_teaser(st) -> None:
    """💼 first two Co-op rows as one-liners + a hand-off button. Cached
    once per tab in _coop_teaser_cache; an ApiError caches [] (section
    hidden for this tab) — same degradation as the hero's _ready_info,
    because re-fetching a down endpoint on every rerun stalls the page."""
    from app.api_client import ApiClient, ApiError  # noqa: PLC0415

    if "_coop_teaser_cache" not in st.session_state:
        try:
            with ApiClient(
                session_token=st.session_state.get("session_token"),
                timeout=5.0,
            ) as api:
                st.session_state["_coop_teaser_cache"] = api.list_coop()
        except ApiError:
            st.session_state["_coop_teaser_cache"] = []

    coops = st.session_state.get("_coop_teaser_cache") or []
    if not coops:
        return

    st.markdown("**💼 Co-op 风向 / Recent co-ops:**")
    for c in coops[:2]:
        # Markdown, not raw HTML — Streamlit sanitizes markdown itself
        # (same precedent as coop_view's listing rows).
        st.markdown(f"- **{c.get('company', '')}** · {c.get('role', '')}")
        if int(c.get("visibility_level", 0)) >= 1:
            st.caption("🔒 面试细节/薪资 · 贡献解锁")
    if st.button("去看看 →", key="disc-coop"):
        st.session_state["pending_nav_to_coop"] = True
        st.rerun()


def render_discover(st) -> None:
    """The discovery block. Caller (streamlit_app) shows it only when
    get_messages(...) is empty — once a conversation exists the chat
    history owns that space. Sections render independently; a dead
    endpoint drops its section without touching the others."""
    _render_program_row(st)
    _render_starter_row(st)
    _render_coop_teaser(st)


__all__ = ["render_discover"]
