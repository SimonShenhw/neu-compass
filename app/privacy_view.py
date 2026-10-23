"""The 数据与隐私 page (batch T, policy P2): what the site keeps, who can see it, for how long, how to delete it.

The words live in api/privacy_text.py since R2a, shared with `GET /privacy`; this page renders them from the settings
the UI runs with (QUERY_LOG_RETENTION_DAYS, ANSWER_FEEDBACK_ENABLED, PRIVACY_CONTACT_EMAIL), and keeps the Streamlit
delete control. Plain text only: nothing here comes from a user, and the contact address is shown as written.

中文：「数据与隐私」页（T 批，政策 P2）：网站留了什么、谁能看、留多久、怎么删。R2a 起文字放在 api/privacy_text.py，和
`GET /privacy` 共用；本页按 UI 运行时的设置（QUERY_LOG_RETENTION_DAYS、ANSWER_FEEDBACK_ENABLED、PRIVACY_CONTACT_EMAIL）
显示它们，并保留 Streamlit 的删除控件。只用纯文字：这里没有用户输入，联系邮箱原样显示。
"""

from __future__ import annotations

from typing import Any

from api.privacy_text import BACKUP_COPIES, DELETE_WHAT, INTRO, privacy_sections

DELETE_RESULT_KEY = "_account_deletion_result"


def _delete_account() -> None:
    """The delete button's on_click callback: it runs before the next run, so that run renders logged out from the
    top (no mid-run st.rerun(), see app.streamlit_auth_ui._log_out). 中文：删除按钮的 on_click 回调，在下一轮之前执行。"""
    import streamlit as st  # noqa: PLC0415

    from app.api_client import ApiClient, ApiError  # noqa: PLC0415
    from app.cookie_session import queue_cookie_clear  # noqa: PLC0415
    from app.state_manager import logout  # noqa: PLC0415

    state = st.session_state
    try:
        with ApiClient(session_token=state.get("session_token"), timeout=15.0) as api:
            api.delete_account()
    except ApiError as e:
        if e.status_code == 401:  # Expired token, or the account is already gone. 中文：登录失效，或账号已经不在。
            queue_cookie_clear(state)
            logout(state)
            state[DELETE_RESULT_KEY] = ("error", "这个登录已经失效，本页已登出。如果账号还在，请重新登录以后再删除。")
        elif e.status_code in (502, 503, 504):
            # No answer, or a gateway's: the server may have finished, so "nothing deleted" would not be known (A24 L5;
            # docs/request-admission.md). Being a guest after a refresh does not prove it either, since a login can
            # also just expire; the same words as the web front end's (R5c, the user's wording).
            # 中文：没收到回复，服务器可能已经删完了，不能说「什么也没删」。刷新后变成游客也证明不了删了（登录也会自己
            # 过期），和新前端用同一句（R5c，用户定的说法）。
            state[DELETE_RESULT_KEY] = ("error", "这次没收到服务器的确认，不确定删除有没有完成。刷新后若仍是登录状态，"
                                                 "可以再试；若已变成游客但需要确认，请联系维护者。")
        else:
            state[DELETE_RESULT_KEY] = ("error", "删除没有完成，什么也没删。请稍后再试；一直不行的话，请写邮件联系。")
        return
    queue_cookie_clear(state)
    logout(state)
    state[DELETE_RESULT_KEY] = ("ok", "你的账号和 Co-op 投稿已经删除，本页已登出。每日备份里的副本最多再留大约两周。")


def render_privacy_page(st: Any) -> None:
    from app.state_manager import is_logged_in  # noqa: PLC0415
    from app.text_render import literal_markdown  # noqa: PLC0415
    from config import settings  # noqa: PLC0415

    st.subheader("🔒 数据与隐私")
    st.caption(INTRO)
    result = st.session_state.pop(DELETE_RESULT_KEY, None)
    if isinstance(result, tuple) and len(result) == 2:
        (st.success if result[0] == "ok" else st.error)(result[1])
    for heading, sentences in privacy_sections(settings):
        st.markdown(f"**{heading}**")
        for sentence in sentences:
            st.markdown("- " + literal_markdown(sentence))
    if is_logged_in(st.session_state):
        st.markdown("**删除我的账号和投稿**")
        st.caption(DELETE_WHAT)
        confirmed = st.checkbox("我知道删除以后不能恢复", key="delete-account-confirm")
        st.button("删除我的账号和投稿", key="delete-account", disabled=not confirmed, on_click=_delete_account)


__all__ = ["BACKUP_COPIES", "DELETE_RESULT_KEY", "DELETE_WHAT", "privacy_sections", "render_privacy_page"]
