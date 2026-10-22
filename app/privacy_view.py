"""The 数据与隐私 page (batch T, policy P2): what the site keeps, who can see it, for how long, how to delete it.

Every sentence follows what the code does today, and the variable parts come from the settings the UI runs with
(QUERY_LOG_RETENTION_DAYS, ANSWER_FEEDBACK_ENABLED, PRIVACY_CONTACT_EMAIL), so the page cannot promise a cleanup
that is switched off. Plain text only: nothing here comes from a user, and the contact address is shown as written.
No legal promises; it describes practice.

中文：「数据与隐私」页（T 批，政策 P2）：网站留了什么、谁能看、留多久、怎么删。每句话都对应代码现在的做法，可变的部分
取自 UI 运行时的设置（QUERY_LOG_RETENTION_DAYS、ANSWER_FEEDBACK_ENABLED、PRIVACY_CONTACT_EMAIL），所以页面不会承诺
一个没打开的清理。只用纯文字：这里没有用户输入，联系邮箱原样显示。不做法律意义上的承诺，只写实际做法。
"""

from __future__ import annotations

from typing import Any

BACKUP_COPIES = 14  # scripts/backup_daemon.py KEEP. 中文：与 scripts/backup_daemon.py 的 KEEP 一致。


def privacy_sections(settings: Any) -> list[tuple[str, list[str]]]:
    """(heading, sentences) in page order; a pure function of the settings. 中文：按页面顺序的（标题，句子）。"""
    days = settings.query_log_retention_days
    feedback = settings.answer_feedback_enabled is True
    contact = settings.privacy_contact_email
    kept = [
        "你每次搜索和提问的原文，会存进不公开的查询日志。日志不和你的账号关联：登录了也不记是谁问的。",
        (f"原文保存 {days} 天，到期以后换成一段带密钥的哈希；那一行还留着时间、搜到的课程和检索方式，用来统计。" if days
         else "目前没有自动清理提问原文。"),
        "运行日志里，提问只记带密钥的哈希和长度，不记原文；登录只记学校域名，不记是谁。",
        ("回答由 Google 的 Gemini 生成：你的问题、这次对话最近几轮和检索到的课程信息会发给 Gemini。"
         "个别搜索在判断要不要放弃时，也会把问题发给 Gemini 再确认一次。Google 怎样处理这些数据，以 Google 的条款为准。"),
        "用 Google 账号登录时，记下你的邮箱、名字和学校域名，用来识别你，并计算 Co-op 贡献等级。",
        "Co-op 投稿先私下保存、人工审核；同一公司、职位、学期至少有两个不同投稿人的投稿通过审核，才一起公开，公开时不显示投稿人。",
        ("只有你勾选「允许保存」以后，回答和你的 👍／👎 才会保存，同样不记是谁；不勾选时只有上面的查询日志。" if feedback
         else "回答反馈功能目前关闭：回答不保存。"),
        "选课草案和课程对比只在这次会话里，刷新或登出就清空，不写数据库。",
    ]
    who = ["服务器上的数据只有维护者能看，不卖、也不交给第三方；公开的 Co-op 经验按贡献等级给访客看；"
           "生成回答要把问题发给 Google Gemini，见上。",
           "网站经 Cloudflare 转发到服务器：连接在 Cloudflare 那里解密再转发，所以 Cloudflare 能看到传输的内容。"]
    keep_for = [
        f"提问原文：{days} 天，到期换成哈希。" if days else "提问原文：目前没有自动清理。",
        (f"每日备份保留 {BACKUP_COPIES} 份，所以到期清理掉的内容，在备份里最多再多留大约两周。" if days
         else f"每日备份保留 {BACKUP_COPIES} 份，大约两周。"),
        "账号和 Co-op 投稿：保留到你删除为止。",
    ]
    if feedback:
        # The same task deletes them (db.query_log_retention.delete_expired_answers). 中文：同一个清理任务删除。
        if days:
            keep_for.append(f"保存的回答和评价：{days} 天后删除。")
        else:
            keep_for.append("保存的回答和评价：目前没有自动清理；想删除可以写邮件联系。" if contact
                            else "保存的回答和评价：目前没有自动清理。")
    unnamed = "提问和保存的回答" if feedback else "提问"
    delete = [
        "登录以后，可以在本页最下面删除你的账号和 Co-op 投稿。",
        f"{unnamed}都不记是谁（登录了也一样），挑不出哪一条是你的，"
        + ("只能等到期清理。" if days else "目前也没有自动清理。"),
    ]
    if contact:
        delete.append(f"别的问题或删除请求，写邮件到 {contact}。")
    return [("记了什么", kept), ("谁能看", who), ("留多久", keep_for), ("怎么删", delete)]


DELETE_RESULT_KEY = "_account_deletion_result"
DELETE_WHAT = ("会删掉：你的账号（邮箱、名字、学校域名、贡献数），你提交的全部 Co-op 投稿（包括已经公开的）和解锁记录，以及别人对"
               "你那些公开经验的解锁记录。同一组公开的投稿如果因此只剩一个人的，那份也会撤回，等有新的同组投稿再一起公开。"
               "提问和保存的回答本来就不和账号关联，不受影响。已经做进每日备份的数据，最多还会在备份里留大约两周。删除不能撤销。")


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
            # docs/request-admission.md). 中文：没收到回复，服务器可能已经删完了，不能说「什么也没删」。
            state[DELETE_RESULT_KEY] = ("error", "这次没收到服务器的确认，不确定删除有没有完成。请刷新页面：变成游客了，"
                                                 "就是已经删掉了；还是登录状态的话，可以再删一次。")
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
    st.caption("这里写的是本站现在的实际做法，不是法律意义上的承诺。")
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
