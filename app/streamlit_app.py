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


SAMPLE_QUERIES: list[tuple[str, str]] = [
    ("📘 CS 5800", "CS 5800"),
    ("🤖 易学的 AI 选修课", "easy AI elective for ML beginner"),
    ("📊 Database courses", "database management systems"),
    ("⚖️ 课业最轻的 ML 课", "lightest workload ML class"),
]
"""Hero-block sample chips. Shown only on first visit (no chat history yet).
Two languages because the audience is bilingual NEU graduate students;
clicking a chip injects the query string verbatim into the chat pipeline."""


def _render_filters_sidebar(st: object, state: object) -> dict[str, object]:
    """Sidebar 'Advanced filters' expander. Returns the active filters dict
    (already in session_state, returned for convenience). No-side-effect read.
    """
    with st.sidebar:
        st.divider()
        with st.expander("🎯 Advanced filters", expanded=False):
            filters: dict[str, object] = state.get("filters", {}) or {}

            term_v = st.text_input(
                "Term", value=filters.get("term") or "",
                placeholder="fall 2026", key="filter_term",
            )
            credits_str = st.text_input(
                "Credits", value=str(filters.get("credits") or ""),
                placeholder="3", key="filter_credits",
            )
            delivery_v = st.selectbox(
                "Delivery mode",
                ["", "in_person", "online", "hybrid", "async"],
                index=0 if not filters.get("delivery_mode") else
                ["", "in_person", "online", "hybrid", "async"].index(
                    str(filters.get("delivery_mode"))
                ),
                key="filter_delivery",
            )
            prof_v = st.text_input(
                "Professor", value=filters.get("professor") or "",
                placeholder="e.g. Smith", key="filter_prof",
            )

            try:
                credits_v = int(credits_str) if credits_str else None
            except ValueError:
                st.caption("⚠️ Credits must be a number 0-12")
                credits_v = None

            new_filters: dict[str, object] = {
                "term": term_v or None,
                "credits": credits_v,
                "delivery_mode": delivery_v or None,
                "professor": prof_v or None,
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
    for k in ("filter_term", "filter_credits", "filter_delivery", "filter_prof"):
        st.session_state.pop(k, None)


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
        guest_banner_html,
        hero_html,
        inject_theme,
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

    render_auth_sidebar()
    active_filters = _render_filters_sidebar(st, st.session_state)

    logged_in = is_logged_in(st.session_state)
    st.markdown(
        hero_html(
            logged_in=logged_in,
            display_name=st.session_state.get("user_display_name") or "",
        ),
        unsafe_allow_html=True,
    )

    if not logged_in:
        st.markdown(guest_banner_html(), unsafe_allow_html=True)

    # Sidebar nav (not st.tabs): chat_input must stay bottom-pinned on the
    # search page, which tabs would break. Co-op finally gets an entry point
    # in the product UI instead of living as an orphan standalone page.
    nav = st.sidebar.radio(
        "页面 / Pages",
        ["🔍 课程搜索 · Search", "💼 Co-op 经验"],
        key="nav_page",
    )
    if nav.startswith("💼"):
        from app.coop_view import render_coop_panel  # noqa: PLC0415

        render_coop_panel(st)
        return

    chat_col, detail_col = st.columns([3, 2])

    with chat_col:
        st.subheader("💬 Chat")

        # Hero block — only on first visit (no chat history yet). This is the
        # main UX fix from Week 8 review: users were landing on an empty
        # two-column layout and not realizing the chat_input below was the
        # query entry point. Sample chips both signal "this is where you ask"
        # AND give working examples for cold-start users.
        if not get_messages(st.session_state):
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
        for msg_idx, msg in enumerate(get_messages(st.session_state)):
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("evidence"):
                    with st.expander(
                        f"📎 Evidence ({len(msg['evidence'])} courses)"
                    ):
                        for ev in msg["evidence"]:
                            cols = st.columns([3, 1])
                            cols[0].markdown(
                                f"**{ev['primary_code']}** — {ev['primary_name']}"
                            )
                            if cols[1].button(
                                "Open",
                                key=f"open-{msg_idx}-{msg['role']}-{ev['course_id']}",
                            ):
                                select_course(st.session_state, ev["course_id"])
                                st.rerun()

        # New input → stream assistant response. Two paths: chat_input box
        # OR a pending_query injected by a hero-block sample chip (above).
        chat_input_value = st.chat_input(
            "Ask about a course (e.g. 'CS 5800', '易学的 ML 课', 'algo')..."
        )
        pending_query = st.session_state.pop("pending_query", None)
        prompt = chat_input_value or pending_query

        if prompt:
            add_message(st.session_state, role="user", content=prompt)
            with st.chat_message("user"):
                st.markdown(prompt)

            chat_body: dict[str, object] = {
                "query": prompt,
                "k": min(st.session_state.get("search_k", 5), 10),
            }
            # Propagate sidebar filters to the chat request — this is what
            # surfaces the backend's term / credits / delivery_mode / professor
            # filtering capability that was previously inaccessible from UI.
            for fk, fv in (active_filters or {}).items():
                if fv not in (None, "", 0):
                    chat_body[fk] = fv
            with st.chat_message("assistant"):
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
                    with st.expander(f"📎 Evidence ({len(results)} courses)"):
                        for ev in results:
                            cols = st.columns([3, 1])
                            cols[0].markdown(
                                f"**{ev['primary_code']}** — {ev['primary_name']}"
                            )
                            if cols[1].button(
                                "Open",
                                key=f"open-live-{ev['course_id']}",
                            ):
                                select_course(st.session_state, ev["course_id"])
                                st.rerun()

            add_message(
                st.session_state,
                role="assistant",
                content=final_text,
                evidence=_format_evidence(results),
                matched_via=matched_via,
            )

    with detail_col:
        st.subheader("📘 Course Detail")
        cid = st.session_state.get("selected_course_id")
        if not cid:
            st.info(
                "Click a course in the chat panel to see full syllabus details "
                "(grading, AI policy, evidence quotes)."
            )
            return

        with ApiClient(
            session_token=st.session_state.get("session_token")
        ) as api:
            try:
                course = api.get_course(cid)
            except ApiError as e:
                st.error(f"Could not load course: {e.detail}")
                return

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
        if course.get("topics_covered"):
            st.markdown("**Topics:**")
            st.markdown(
                topic_pills_html(course["topics_covered"]),
                unsafe_allow_html=True,
            )
        if course.get("ai_policy"):
            with st.expander("AI policy"):
                st.json(course["ai_policy"])
        if course.get("evidence_snippets"):
            with st.expander(f"Evidence ({len(course['evidence_snippets'])})"):
                for ev in course["evidence_snippets"]:
                    st.markdown(
                        f"> *{ev['quote']}* — `{ev['source_id']}` "
                        f"(confidence {ev['confidence']:.2f})"
                    )


# Streamlit entry point: render() at module top when running via streamlit.
# Guarded so `import app.streamlit_app` (in tests) doesn't trigger Streamlit.
if __name__ == "__main__" or "streamlit" in sys.argv[0].lower():
    render()
