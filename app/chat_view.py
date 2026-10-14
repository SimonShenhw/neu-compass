"""Chat continuity and history, with orchestration-owned compatibility hooks.

中文：对话连续性与历史展示；主入口传入既有 renderer，保留运行时替换边界。
"""

from __future__ import annotations

from typing import Any, Callable


def _recent_history(messages: list[dict], limit: int = 6) -> list[dict]:
    """Last `limit` turns as ChatRequest.history; retain slice/filter order.

    Content is capped at 4000 chars (the API's ChatTurn bound): assistant answers can exceed it
    with long evidence-rich replies.
    中文：保留原切片／过滤顺序，内容按 API 的 ChatTurn 上限截断到 4000 字符：带大量证据的助手
    长回答可能超限。
    """
    return [
        {"role": m["role"], "content": str(m["content"])[:4000]}
        for m in messages[-limit:]
        if m.get("content")
    ]


def _context_course_ids(messages: list[dict], limit: int = 10) -> list[str]:
    """Latest assistant evidence supplies ordered follow-up referents ("这门课...").

    The API only uses these when its follow-up detector fires, so sending them on every request
    is harmless.
    中文：取最近一条带证据的助手回复，不去重、不改变顺序或切片语义。API 只在追问检测器命中时
    才使用它们，因此每次请求都带上也无副作用。
    """
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("evidence"):
            return [ev["course_id"] for ev in m["evidence"]][:limit]
    return []


def render_chat_history(
    st: Any,
    messages: list[dict],
    *,
    render_message_text: Callable[..., None],
    render_evidence_block: Callable[..., None],
    matched_via_badge: Callable[[str], str],
    single_chips: list[str],
    multi_chips: list[str],
) -> None:
    """Render in the caller's chat column, after landing and before a new turn.

    Hooks and chip lists come from the main entry at call time, without importing
    that entry here. 中文：显式依赖保留主入口替换点，不反向导入主入口。
    """
    # Index + role in the 查看 keys: the same course in two answers (common when a student asks about a
    # topic repeatedly) would otherwise collide on f"open-{role}-{course_id}", and Streamlit's
    # DuplicateWidgetID would take down the whole chat history.
    # 中文：「查看」按钮的 key 带上消息序号＋角色：同一门课出现在两条回答的证据里（反复追问同一主题时
    # 很常见）会在 f"open-{role}-{course_id}" 上撞 key，DuplicateWidgetID 会让整个聊天历史崩掉。
    for msg_idx, msg in enumerate(messages):
        with st.chat_message(
            msg["role"],
            avatar="🎓" if msg["role"] == "user" else "🧭",
        ):
            from app.answer_evidence_view import render_retrieval_notices  # noqa: PLC0415

            render_message_text(st, msg)
            render_retrieval_notices(st, msg.get("notices"))
            if msg.get("evidence"):
                n_ev = len(msg["evidence"])
                with st.expander(
                    f"📎 相关课程（{n_ev} 门）",
                    expanded=(n_ev <= 3),
                ):
                    if msg.get("matched_via"):
                        st.markdown(
                            matched_via_badge(msg["matched_via"]),
                            unsafe_allow_html=True,
                        )
                    render_evidence_block(
                        st, msg["evidence"],
                        key_prefix=f"open-{msg_idx}-{msg['role']}",
                    )
        if msg['role'] == 'assistant':
            from app.answer_feedback_view import render_answer_feedback  # noqa: PLC0415

            render_answer_feedback(st, msg, key_prefix=f'answer-feedback-{msg_idx}')
        # Chips belong only to the latest eligible assistant answer: they ride the conversation-
        # continuity path (context tier), so a click asks about the course(s) just discussed.
        # 中文：追问只挂在最新的、有可用检索证据的助手回复下：它们走对话连续性路径（context 档），
        # 点击即是在追问刚讨论过的那（几）门课。
        is_last = msg_idx == len(messages) - 1
        if (
            is_last
            and msg["role"] == "assistant"
            and msg.get("evidence")
            and msg.get("matched_via") not in ("rejected", "empty")
        ):
            chips = single_chips if len(msg["evidence"]) == 1 else multi_chips
            chip_cols = st.columns(len(chips))
            for i, chip in enumerate(chips):
                if chip_cols[i].button(
                    f"↳ {chip}", key=f"chip-{msg_idx}-{i}",
                    use_container_width=True,
                ):
                    st.session_state["pending_query"] = chip
                    st.rerun()
