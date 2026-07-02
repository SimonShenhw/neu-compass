"""Streamlit user UI: course search + course detail (PLAN v2.3 §3.7).

Production user-facing frontend until Andy Dong's `compass-frontend` (React)
repo lands. Streamlit is the canonical user surface in v0.x; team docs +
public URL `compass.neu-compass.me` point at it. The FastAPI backend (`api.*`)
is what Andy's React will call once that repo exists.

Main Streamlit page: chat-style course search + course detail panel +
sample-query chips for first-time users + advanced-filter expander in
the sidebar.

Run:
    uv run streamlit run app/streamlit_app.py

Layout:
    [ left: hero (first visit only) + chat history + chat_input ]
    [ right: selected course detail ]
    sidebar: OAuth login/logout + advanced filters expander

Pipeline per user message:
  1. add_message(role='user', content=prompt)
  2. ApiClient.chat_stream({"query": prompt, ...filters}) → NDJSON events
  3. meta event captured to state (drives evidence bubble)
  4. token events stream into st.write_stream — assistant message renders
     incrementally
  5. Final assistant text + evidence persisted to state.messages

Auth: login link / logout button live in the sidebar (render_auth_sidebar).
?code= callback handled at the top via handle_oauth_callback.

PLAN §3.6 red lines: no API key in chat output, no commercial hooks,
OAuth restricted to NEU domains (server-side).
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _format_evidence(results: list[dict]) -> list[dict]:
    """Pull out the (course_id, code, name) tuple per result for the bubble UI."""
    return [
        {
            "course_id": r["course_id"],
            "primary_code": r["primary_code"],
            "primary_name": r["primary_name"],
            "score": r["score"],
        }
        for r in results
    ]


def _summarize_results(results: list[dict], matched_via: str) -> str:
    """Plain-text fallback summary used when Gemini stream unavailable."""
    if not results:
        return "No matching courses. Try different terms or relax filters."
    if matched_via == "alias":
        r = results[0]
        return (
            f"**{r['primary_code']} — {r['primary_name']}** "
            f"(direct alias match)"
        )
    lines = [f"Top {len(results)} matches:"]
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. **{r['primary_code']} — {r['primary_name']}** "
            f"(score {r['score']:.3f})"
        )
    return "\n\n".join(lines)


def stream_assistant(
    api: Any,
    body: dict[str, Any],
    state: Any,
) -> Iterator[str]:
    """Generator for `st.write_stream`. Consumes /chat NDJSON events,
    yields assistant tokens, and side-effect captures the meta event in
    `state['last_chat_meta']` for the post-stream evidence rendering.

    On in-stream error event, yields a user-facing warning + stops. On
    'done', stops. Pure logic; no Streamlit imports.
    """
    state["last_chat_meta"] = None
    state["last_chat_error"] = None
    for event in api.chat_stream(body):
        etype = event.get("type")
        if etype == "meta":
            state["last_chat_meta"] = event
        elif etype == "token":
            text = event.get("text", "")
            if text:
                yield text
        elif etype == "error":
            detail = event.get("detail", "unknown error")
            state["last_chat_error"] = detail
            yield f"\n\n⚠️ {detail}"
            return
        elif etype == "done":
            return


def _recent_history(messages: list[dict], limit: int = 6) -> list[dict]:
    """Last `limit` turns as the {role, content} shape ChatRequest.history
    expects. Content capped at 4000 chars (the API's ChatTurn bound);
    assistant answers can exceed it with long evidence-rich replies."""
    return [
        {"role": m["role"], "content": str(m["content"])[:4000]}
        for m in messages[-limit:]
        if m.get("content")
    ]


def _context_course_ids(messages: list[dict], limit: int = 10) -> list[str]:
    """Course ids from the most recent assistant turn that carried
    evidence — the referent set for follow-ups ("这门课..."). The API
    only uses these when its follow-up detector fires, so sending them
    on every request is harmless."""
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("evidence"):
            return [ev["course_id"] for ev in m["evidence"]][:limit]
    return []


FOLLOWUP_CHIPS_SINGLE: list[str] = [
    "这门课讲什么内容？",
    "这门课作业量大吗？",
    "先修要求是什么？",
]
FOLLOWUP_CHIPS_MULTI: list[str] = [
    "这几门课怎么选？",
    "哪门最适合零基础？",
    "第一门的先修要求？",
]
"""Suggested follow-up chips under the latest answer. Click → injected
via pending_query, riding the same conversation-continuity path the
typed version would take."""


SAMPLE_QUERIES: list[tuple[str, str]] = [
    ("📘 CS 5800", "CS 5800"),
    ("🤖 易学的 AI 选修课", "easy AI elective for ML beginner"),
    ("📊 Database courses", "database management systems"),
    ("⚖️ 课业最轻的 ML 课", "lightest workload ML class"),
]
"""Hero-block sample chips. Shown only on first visit (no chat history yet).
Two languages because the audience is bilingual NEU graduate students;
clicking a chip injects the query string verbatim into the chat pipeline."""


def _render_evidence_block(st: object, results: list[dict], key_prefix: str) -> None:
    """Result cards for one evidence list: rank + code + name + relative
    score bar, with a 查看 button per row. Bar widths normalize against
    the top score WITHIN this list (relative confidence, not absolute).
    Shared by chat history and the live response path so the two can't
    drift apart visually."""
    from app.state_manager import select_course  # noqa: PLC0415
    from app.ui_theme import result_card_html  # noqa: PLC0415

    top = max((float(r.get("score", 0.0)) for r in results), default=0.0)
    for i, ev in enumerate(results):
        score = float(ev.get("score", 0.0))
        pct = int(round(100 * score / top)) if top > 0 else 50
        cols = st.columns([5, 1])
        cols[0].markdown(
            result_card_html(
                rank=i + 1,
                code=ev["primary_code"],
                name=ev["primary_name"],
                score=score,
                pct=max(pct, 8),  # keep a visible sliver for low scores
            ),
            unsafe_allow_html=True,
        )
        if cols[1].button(
            "查看", key=f"{key_prefix}-{ev['course_id']}",
            use_container_width=True,
        ):
            select_course(st.session_state, ev["course_id"])
            st.rerun()


def _render_filters_sidebar(st: object, state: object) -> dict[str, object]:
    """Sidebar 'Advanced filters' expander. Returns the active filters dict
    (already in session_state, returned for convenience). No-side-effect read.
    """
    with st.sidebar:
        st.divider()
        with st.expander("🎯 Advanced filters", expanded=False):
            filters: dict[str, object] = state.get("filters", {}) or {}

            # Only CREDITS is offered. Term / delivery_mode / professor
            # filters exist in the API but their source data is absent
            # catalog-wide (2026-06 data review: term & delivery_mode
            # 0/6,469, professor ~3 courses) — exposing them meant every
            # use returned an empty result set. Re-enable each one when a
            # pipeline actually populates it (syllabus ingestion for term
            # /mode, RMP enrichment for professor).
            credits_str = st.text_input(
                "Credits", value=str(filters.get("credits") or ""),
                placeholder="3", key="filter_credits",
            )

            try:
                credits_v = int(credits_str) if credits_str else None
            except ValueError:
                st.caption("⚠️ Credits must be a number 0-12")
                credits_v = None

            new_filters: dict[str, object] = {
                "credits": credits_v,
            }
            state["filters"] = new_filters

            active = sum(1 for v in new_filters.values() if v not in (None, ""))
            if active:
                st.caption(f"✓ {active} filter{'s' if active > 1 else ''} active")
                # Use on_click rather than mutating state inside the if-block.
                # Streamlit raises StreamlitAPIException if you set
                # st.session_state[<widget_key>] AFTER the widget has been
                # instantiated this render — and the four filter widgets
                # above this button were already created. on_click runs as
                # a callback BEFORE the next rerun, while mutation is legal.
                # `pop` (vs setting "") is what the docs recommend for
                # clearing widget-bound state cleanly.
                st.button(
                    "Clear all",
                    use_container_width=True,
                    key="filter_clear",
                    on_click=_clear_filters_callback,
                )
    return state.get("filters", {})


def _clear_filters_callback() -> None:
    """on_click callback for the 'Clear all' filter button. Runs in the
    callback phase, so mutating widget-bound session_state keys is allowed
    (the alternative — setting state[k]="" inline after the widgets render
    — raises StreamlitAPIException). Caller should not import streamlit
    at module top to keep test imports cheap; lazy import here."""
    import streamlit as st  # noqa: PLC0415
    st.session_state["filters"] = {}
    st.session_state.pop("filter_credits", None)


def render() -> None:
    """Render the chat UI. Imported lazily so `import app.streamlit_app`
    in tests doesn't trigger Streamlit's session machinery."""
    import streamlit as st  # noqa: PLC0415

    from app.api_client import ApiClient, ApiError  # noqa: PLC0415
    from app.state_manager import (  # noqa: PLC0415
        add_message,
        get_messages,
        init_state,
        is_logged_in,
        record_search,
        select_course,
    )
    from app.streamlit_auth_ui import (  # noqa: PLC0415
        handle_oauth_callback,
        render_auth_sidebar,
    )
    from app.ui_theme import (  # noqa: PLC0415
        course_header_html,
        empty_detail_html,
        footer_html,
        guest_banner_html,
        hero_html,
        inject_theme,
        matched_via_badge,
        prereq_label_md,
        program_context_html,
        sidebar_brand_html,
        topic_pills_html,
    )

    st.set_page_config(
        page_title="NEU-Compass · Course Search",
        page_icon="🧭",
        layout="wide",
    )
    inject_theme(st)
    init_state(st.session_state)

    # Process ?code= callback BEFORE rendering anything else (it may rerun).
    handle_oauth_callback()

    # Cookie session (refresh-survival): restore first so a failed restore
    # can queue a cookie clear, then flush — the flush also renders writes
    # queued by the OAuth callback / logout on the previous pass.
    from app.cookie_session import (  # noqa: PLC0415
        flush_pending_cookie,
        restore_login_from_cookie,
    )

    restore_login_from_cookie()
    flush_pending_cookie()

    st.sidebar.markdown(sidebar_brand_html(), unsafe_allow_html=True)
    render_auth_sidebar()
    active_filters = _render_filters_sidebar(st, st.session_state)

    # Corpus size for the hero pill — one /ready call per browser tab,
    # cached in session_state. Failure (API warming) degrades to the
    # number-free wording inside hero_html.
    if "_ready_info" not in st.session_state:
        try:
            with ApiClient(timeout=5.0) as api:
                st.session_state["_ready_info"] = api.ready()
        except ApiError:
            st.session_state["_ready_info"] = {}
    ready_info = st.session_state.get("_ready_info") or {}

    logged_in = is_logged_in(st.session_state)
    st.markdown(
        hero_html(
            logged_in=logged_in,
            display_name=st.session_state.get("user_display_name") or "",
            courses_indexed=ready_info.get("courses_indexed"),
        ),
        unsafe_allow_html=True,
    )

    if not logged_in:
        st.markdown(guest_banner_html(), unsafe_allow_html=True)

    # Sidebar nav (not st.tabs): chat_input must stay bottom-pinned on the
    # search page, which tabs would break. Pages: search / programs / co-op.
    pages = ["🔍 课程搜索 · Search", "🎓 培养方案 · Programs", "💼 Co-op 经验"]

    # Cross-page hand-offs (discover chips, curriculum 查看 buttons) queue
    # a pending_nav_* flag + st.rerun(); we consume it HERE, before the
    # radio instantiates — writing a widget-bound key after the widget
    # rendered raises StreamlitAPIException (see filter-clear note).
    if st.session_state.pop("pending_nav_to_programs", None):
        st.session_state["nav_page"] = pages[1]
    if st.session_state.pop("pending_nav_to_coop", None):
        st.session_state["nav_page"] = pages[2]
    if st.session_state.pop("pending_nav_to_search", None):
        st.session_state["nav_page"] = pages[0]

    nav = st.sidebar.radio("页面 / Pages", pages, key="nav_page")
    if nav.startswith("🎓"):
        from app.program_view import render_program_browser  # noqa: PLC0415

        render_program_browser(st)
        st.markdown(footer_html(), unsafe_allow_html=True)
        return
    if nav.startswith("💼"):
        from app.coop_view import render_coop_panel  # noqa: PLC0415

        render_coop_panel(st)
        st.markdown(footer_html(), unsafe_allow_html=True)
        return

    # 5:3 (was 3:2): the chat stream is the primary surface — review
    # feedback flagged ~35% wasted horizontal space with the old ratio.
    chat_col, detail_col = st.columns([5, 3])

    with chat_col:
        st.subheader("💬 Chat")

        # Discovery + sample chips — only on first visit (no chat history
        # yet). Round-3 fix for the cold-start blank screen: the landing
        # now offers browsable CONTENT (programs / starter courses / co-op
        # teaser), not just an empty chat box with example queries.
        if not get_messages(st.session_state):
            from app.discover_view import render_discover  # noqa: PLC0415

            render_discover(st)
            st.divider()
            st.markdown("**🔍 试试这些查询 / Try these queries:**")
            sample_cols = st.columns(2)
            for i, (label, query) in enumerate(SAMPLE_QUERIES):
                col = sample_cols[i % 2]
                if col.button(
                    label, use_container_width=True, key=f"sample-{i}",
                ):
                    st.session_state["pending_query"] = query
                    st.rerun()
            st.caption(
                "💡 You can also ask in natural language: "
                "*\"easiest 3-credit ML class with low workload\"* / "
                "*\"course on backprop\"*"
            )
            st.divider()

        # Render existing conversation history. enumerate(messages) so the
        # "Open" button keys can include the message index — without that,
        # the same course appearing in two different message evidence
        # blocks (common when user asks repeatedly about a topic) collides
        # on f"open-{role}-{course_id}" and Streamlit raises
        # DuplicateWidgetID, blowing up the entire chat history.
        messages = get_messages(st.session_state)
        for msg_idx, msg in enumerate(messages):
            with st.chat_message(
                msg["role"],
                avatar="🎓" if msg["role"] == "user" else "🧭",
            ):
                st.markdown(msg["content"])
                if msg.get("evidence"):
                    n_ev = len(msg["evidence"])
                    with st.expander(
                        f"📎 Evidence ({n_ev} course{'s' if n_ev > 1 else ''})",
                        expanded=(n_ev <= 3),
                    ):
                        if msg.get("matched_via"):
                            st.markdown(
                                matched_via_badge(msg["matched_via"]),
                                unsafe_allow_html=True,
                            )
                        _render_evidence_block(
                            st, msg["evidence"],
                            key_prefix=f"open-{msg_idx}-{msg['role']}",
                        )
            # Follow-up suggestion chips under the LATEST answer only —
            # they ride the conversation-continuity path (context tier),
            # so a click answers about the course(s) just discussed.
            is_last = msg_idx == len(messages) - 1
            if (
                is_last
                and msg["role"] == "assistant"
                and msg.get("evidence")
                and msg.get("matched_via") not in ("rejected", "empty")
            ):
                chips = (
                    FOLLOWUP_CHIPS_SINGLE
                    if len(msg["evidence"]) == 1
                    else FOLLOWUP_CHIPS_MULTI
                )
                chip_cols = st.columns(len(chips))
                for i, chip in enumerate(chips):
                    if chip_cols[i].button(
                        f"↳ {chip}", key=f"chip-{msg_idx}-{i}",
                        use_container_width=True,
                    ):
                        st.session_state["pending_query"] = chip
                        st.rerun()

        # New input → stream assistant response. Two paths: chat_input box
        # OR a pending_query injected by a hero-block sample chip (above).
        chat_input_value = st.chat_input(
            "问我任何课程问题：CS 5800 / 易学的 ML 课 / algo …"
        )
        pending_query = st.session_state.pop("pending_query", None)
        prompt = chat_input_value or pending_query

        if prompt:
            # Continuity payload BEFORE the new prompt joins the history:
            # history = prior turns (the new question travels as `query`),
            # context ids = the previous answer's evidence (follow-up
            # referent set for the API's context tier).
            prior_messages = get_messages(st.session_state)
            chat_history = _recent_history(prior_messages)
            context_ids = _context_course_ids(prior_messages)

            add_message(st.session_state, role="user", content=prompt)
            with st.chat_message("user", avatar="🎓"):
                st.markdown(prompt)

            chat_body: dict[str, object] = {
                "query": prompt,
                "k": min(st.session_state.get("search_k", 5), 10),
            }
            if chat_history:
                chat_body["history"] = chat_history
            if context_ids:
                chat_body["context_course_ids"] = context_ids
            # Propagate sidebar filters to the chat request — this is what
            # surfaces the backend's term / credits / delivery_mode / professor
            # filtering capability that was previously inaccessible from UI.
            # NB: 0 is a VALID credits value (0-credit seminars/co-ops exist);
            # only None/"" mean "filter not set".
            for fk, fv in (active_filters or {}).items():
                if fv is not None and fv != "":
                    chat_body[fk] = fv
            with st.chat_message("assistant", avatar="🧭"):
                final_text = ""
                try:
                    with ApiClient(
                        session_token=st.session_state.get("session_token")
                    ) as api:
                        stream = stream_assistant(api, chat_body, st.session_state)
                        final_text = st.write_stream(stream) or ""
                except ApiError as e:
                    final_text = f"⚠️ Chat failed: {e.detail}"
                    st.markdown(final_text)

                meta = st.session_state.get("last_chat_meta") or {}
                results = meta.get("results", [])
                matched_via = meta.get("matched_via", "empty")
                if results:
                    record_search(
                        st.session_state,
                        query=prompt,
                        results=results,
                        matched_via=matched_via,
                    )
                    n_live = len(results)
                    with st.expander(
                        f"📎 Evidence ({n_live} course{'s' if n_live > 1 else ''})"
                    ):
                        st.markdown(
                            matched_via_badge(matched_via),
                            unsafe_allow_html=True,
                        )
                        _render_evidence_block(
                            st, results, key_prefix="open-live",
                        )

            add_message(
                st.session_state,
                role="assistant",
                content=final_text,
                evidence=_format_evidence(results),
                matched_via=matched_via,
            )
            # Rerun immediately so the message renders via the HISTORY path.
            # The live evidence block above only exists inside `if prompt:`;
            # on the rerun a 查看 click triggers, prompt is None, so those
            # `open-live-*` widgets are never re-instantiated and Streamlit
            # silently DROPS the click — the buttons were dead. History keys
            # are stable across reruns, so clicks work there.
            st.rerun()

    with detail_col:
        st.subheader("📘 Course Detail")
        cid = st.session_state.get("selected_course_id")
        course: dict | None = None
        if not cid:
            st.markdown(empty_detail_html(), unsafe_allow_html=True)
        else:
            with ApiClient(
                session_token=st.session_state.get("session_token")
            ) as api:
                try:
                    course = api.get_course(cid)
                except ApiError as e:
                    st.error(f"Could not load course: {e.detail}")

        if course:
            st.markdown(
                course_header_html(
                    code=course["primary_code"],
                    name=course["primary_name"],
                    term=course.get("term"),
                    credits=course.get("credits"),
                    delivery_mode=course.get("delivery_mode"),
                ),
                unsafe_allow_html=True,
            )

            if course.get("professor"):
                st.markdown("**Professor:** " + ", ".join(course["professor"]))

            # Soft fields (workload / difficulty / grading / skills) — the
            # product's own sample chips advertise "课业最轻", so when the
            # data exists it MUST be visible. Sections vanish when absent
            # (enrichment coverage grows course-by-course).
            soft_bits: list[str] = []
            if course.get("workload_hours_per_week") is not None:
                soft_bits.append(
                    f"⏱️ 每周约 {course['workload_hours_per_week']:g} 小时"
                )
            if course.get("difficulty_score") is not None:
                soft_bits.append(f"🎚️ 难度 {course['difficulty_score']:g}/5")
            if soft_bits:
                st.markdown(" · ".join(soft_bits))
            if course.get("grading_components"):
                parts = [
                    f"{g['name']} {g['weight'] * 100:.0f}%"
                    if g.get("weight") is not None else str(g["name"])
                    for g in course["grading_components"]
                ]
                st.markdown("**📝 考核构成:** " + " · ".join(parts))

            if course.get("topics_covered"):
                st.markdown("**Topics:**")
                st.markdown(
                    topic_pills_html(course["topics_covered"]),
                    unsafe_allow_html=True,
                )
            if course.get("skill_tags"):
                st.markdown("**🛠️ 技能标签:**")
                st.markdown(
                    topic_pills_html(course["skill_tags"]),
                    unsafe_allow_html=True,
                )
            if course.get("career_relevance"):
                st.markdown(
                    "**💼 职业方向:** " + " · ".join(course["career_relevance"])
                )

            # Layer 3 ontology context (UI round 2): where this course sits
            # in seeded programs + what to take first. Both lists are []
            # for courses outside any seeded program — sections vanish.
            if course.get("program_context"):
                st.markdown("**📋 培养方案定位 · Program fit**")
                st.markdown(
                    program_context_html(course["program_context"]),
                    unsafe_allow_html=True,
                )
            if course.get("prerequisites"):
                st.markdown("**🧱 先修关系 · Prerequisites**")
                # Mini prereq graph (round-3 review's "killer feature" ask):
                # st.graphviz_chart renders the DOT source client-side —
                # no graphviz runtime in the image.
                from rag.prereq_graph import build_prereq_dot  # noqa: PLC0415

                dot = build_prereq_dot(
                    course["primary_code"], course["prerequisites"],
                )
                if dot:
                    st.graphviz_chart(dot)
                for p in course["prerequisites"]:
                    cols = st.columns([4, 1])
                    cols[0].markdown(
                        prereq_label_md(
                            code=p.get("primary_code"),
                            name=p.get("primary_name"),
                            course_id=p["course_id"],
                            requirement=p["requirement"],
                        )
                    )
                    # Only navigable when the prereq exists in the catalog.
                    if p.get("primary_code") and cols[1].button(
                        "查看", key=f"prereq-{p['course_id']}",
                        use_container_width=True,
                    ):
                        select_course(st.session_state, p["course_id"])
                        st.rerun()

            if course.get("ai_policy"):
                # Friendly rendering — the raw st.json dump was the last
                # genuinely embarrassing element in the panel.
                ap = course["ai_policy"]
                with st.expander("🤖 AI 使用政策"):
                    if ap.get("permitted_tools"):
                        st.markdown(
                            "✅ **允许:** " + ", ".join(ap["permitted_tools"])
                        )
                    if ap.get("banned_tools"):
                        st.markdown(
                            "🚫 **禁止:** " + ", ".join(ap["banned_tools"])
                        )
                    if ap.get("disclosure_required"):
                        st.markdown("📣 使用 AI 需声明")
                    if ap.get("notes"):
                        st.caption(ap["notes"])
            if course.get("evidence_snippets"):
                with st.expander(
                    f"Evidence ({len(course['evidence_snippets'])})"
                ):
                    for ev in course["evidence_snippets"]:
                        st.markdown(
                            f"> *{ev['quote']}* — `{ev['source_id']}` "
                            f"(confidence {ev['confidence']:.2f})"
                        )

    st.markdown(footer_html(), unsafe_allow_html=True)


# Streamlit entry point: render() at module top when running via streamlit
# (which sets the main script's __name__ to "__main__"). Plain __main__
# guard so importing this module (tests, other pages) never renders — the
# old `"streamlit" in sys.argv[0]` clause made ANY import under a running
# streamlit process execute render() at import time (see coop_view bug).
if __name__ == "__main__":
    render()
