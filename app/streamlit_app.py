"""Main Streamlit page: chat-style course search + course detail panel.

Run:
    uv run streamlit run app/streamlit_app.py

Layout:
    [ left: chat history + input + streamed assistant response ]
    [ right: selected course detail ]

Pipeline per user message:
  1. add_message(role='user', content=prompt)
  2. ApiClient.chat_stream({"query": prompt, ...}) → NDJSON events
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

    st.set_page_config(
        page_title="NEU-Compass · Course Search",
        layout="wide",
    )
    init_state(st.session_state)

    # Process ?code= callback BEFORE rendering anything else (it may rerun).
    handle_oauth_callback()

    render_auth_sidebar()

    st.title("NEU-Compass · 选课助手")
    st.caption("F1 合规 MVP · 仅限 NEU 学生使用")

    if not is_logged_in(st.session_state):
        st.info(
            "🔒 You are browsing as guest — only level-0 (preview) Co-op data is "
            "visible. Log in with your NEU email (sidebar) to see contribution-gated content."
        )

    chat_col, detail_col = st.columns([3, 2])

    with chat_col:
        st.subheader("💬 Chat")

        # Render existing conversation history
        for msg in get_messages(st.session_state):
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
                                key=f"open-{msg['role']}-{ev['course_id']}",
                            ):
                                select_course(st.session_state, ev["course_id"])
                                st.rerun()

        # New input → stream assistant response
        if prompt := st.chat_input("Ask about a course (e.g. 'CS 5800', 'Algo')..."):
            add_message(st.session_state, role="user", content=prompt)
            with st.chat_message("user"):
                st.markdown(prompt)

            chat_body = {
                "query": prompt,
                "k": min(st.session_state.get("search_k", 5), 10),
            }
            with st.chat_message("assistant"):
                final_text = ""
                try:
                    with ApiClient(user_id=st.session_state.get("user_id")) as api:
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

        with ApiClient(user_id=st.session_state.get("user_id")) as api:
            try:
                course = api.get_course(cid)
            except ApiError as e:
                st.error(f"Could not load course: {e.detail}")
                return

        st.markdown(f"### {course['primary_code']} — {course['primary_name']}")
        meta_cols = st.columns(3)
        meta_cols[0].metric("Term", course.get("term") or "—")
        meta_cols[1].metric("Credits", course.get("credits") or "—")
        meta_cols[2].metric(
            "Mode",
            (course.get("delivery_mode") or "—").replace("_", " "),
        )

        if course.get("professor"):
            st.markdown("**Professor:** " + ", ".join(course["professor"]))
        if course.get("topics_covered"):
            st.markdown("**Topics:**")
            for t in course["topics_covered"]:
                st.markdown(f"- {t}")
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
