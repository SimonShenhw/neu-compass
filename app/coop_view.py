"""Streamlit Co-op page: progressive-unlock listing of NEU Co-op rows.

Streamlit Co-op 页面：NEU Co-op 记录的渐进解锁列表。

Run:
    uv run streamlit run app/coop_view.py

Tier model (PLAN §6.4 give-to-get gate, ADR §3.4):
  level 0: company + role + term + duration  (visible to everyone)
  level 1: + interview_summary + technical_questions
           (requires user.contribution_count >= 1)
  level 2: + salary_range_usd
           (requires user.contribution_count >= 2)

分级模型（PLAN §6.4 give-to-get 门槛，ADR §3.4）：
  level 0：公司 + 职位 + 学期 + 时长（所有人可见）
  level 1：+ 面试摘要 + 技术问题
           （需要 user.contribution_count >= 1）
  level 2：+ 薪资区间
           （需要 user.contribution_count >= 2）

The API lists curated seeds and reviewed UGC with a current two-contributor
cohort, then redacts fields according to the caller's tier. Uploads are private
and pending; submitting is not publishing and does not immediately earn credit.
中文：API 只列策展种子和满足不同贡献者门槛的已审核经历，再做字段分层；
上传先私有待审，不等于公开或立即获得贡献奖励。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# What a listed row contains (visibility_level), not what the viewer has unlocked.
# 中文：一条记录本身包含哪些内容（visibility_level），不是看的人已经解锁了什么。
# What each level guarantees (schemas.coop.derive_visibility): level 2 is any row with a salary
# range, with or without interview details. 中文：每个等级保证有的内容：2 级是有薪资区间的行，
# 面试细节不一定有。
VISIBILITY_LABELS = {0: "基础信息", 1: "含面试细节", 2: "含薪资区间"}
# The API's industry codes, in form order; only the shown label is Chinese.
# 中文：API 的行业代码，按表单顺序；只有显示的文字是中文。
INDUSTRY_LABELS = {
    "quant_fintech": "量化 / 金融科技", "big_tech": "大型科技公司", "biotech_health": "生物科技 / 医疗",
    "startup": "创业公司", "consulting": "咨询", "other": "其他",
}


def industry_label(code: str) -> str:
    return INDUSTRY_LABELS.get(code, code)


def apply_upload_result(state, response: dict) -> None:
    """Use the server's count/state; never infer credit from HTTP 201.

    中文：贡献数与审核状态以服务端为准，不从提交成功自行推断加一。
    """
    state["user_contribution_count"] = response["contribution_count"]
    messages = {
        "pending": "已私有收集，等待人工脱敏审核；尚未公开，也未新增贡献奖励。",
        "approved": "已审核，等待至少两个不同贡献者的同组经历齐备后公开。",
        "published": "已审核并公开；贡献奖励以服务端计数为准。",
        "rejected": "此提交已被审核拒绝；未公开，请联系审核员处理。",
    }
    prefix = "重复提交，保留原记录（内容未替换）。" if response["duplicate"] else ""
    state["_coop_upload_success"] = f"{prefix} `{response['coop_id']}`：{messages[response['status']]}"


def render() -> None:
    """Standalone Co-op page (page config + auth chrome + panel). The main
    app (streamlit_app) mounts render_coop_panel directly instead.

    独立的 Co-op 页面（page config + 认证 chrome + 面板）。主 app
    （streamlit_app）实际是直接挂载 render_coop_panel，不走这条路径。"""
    import streamlit as st  # noqa: PLC0415

    from app.cookie_session import (  # noqa: PLC0415
        flush_pending_cookie,
        restore_login_from_cookie,
    )
    from app.state_manager import init_state  # noqa: PLC0415
    from app.streamlit_auth_ui import (  # noqa: PLC0415
        handle_oauth_callback,
        render_auth_sidebar,
    )

    st.set_page_config(page_title="NEU-Compass · Co-op", layout="wide")
    init_state(st.session_state)
    handle_oauth_callback()
    # Same cookie choreography as the main page — without these the
    # callback's queued session-cookie write never reaches the browser
    # and login on this standalone page doesn't survive a refresh.
    # 中文:与主页面相同的 cookie 编排 —— 没有这几步，回调排队的
    # session-cookie 写入永远到不了浏览器，本独立页面上的登录状态也
    # 扛不过一次刷新。
    restore_login_from_cookie()
    flush_pending_cookie()
    render_auth_sidebar()
    render_coop_panel(st)


def render_coop_panel(st) -> None:
    """Co-op listing + upload form. Caller owns page config / auth chrome /
    theme — this只负责面板本体, so the main app can mount it as a nav page.

    Co-op 列表 + 上传表单。page config / 认证 chrome / 主题均由调用方
    负责 —— 本函数只管面板本体，这样主 app 才能把它当作一个导航页挂载。"""
    from app.api_client import ApiClient, ApiError  # noqa: PLC0415
    from app.state_manager import is_logged_in  # noqa: PLC0415

    st.subheader("💼 NEU Co-op 经验")
    st.caption("这里有整理好的示例记录，也有同学分享的 Co-op 经验。同学的分享先人工去掉个人信息并审核，"
               "同一类经验至少有 2 位不同的同学分享后才公开。你分享的经验公开后，可以解锁更多细节。")

    # The previous upload's actual server state survives the rerun.
    # 中文：重跑后显示上一次提交的真实服务端状态，不暗示立即解锁。
    success_msg = st.session_state.pop("_coop_upload_success", None)
    if success_msg:
        st.success(success_msg)

    session_token = st.session_state.get("session_token")
    if not is_logged_in(st.session_state):
        st.info(
            "你现在是游客：只能看到公开记录的公司、职位、行业、学期和时长。用 NEU 邮箱登录并分享自己的经验，"
            "经验公开后能看到更多：1 条看面试细节，2 条看薪资区间。"
        )

    # === Listing ===
    # 中文:列表
    with ApiClient(session_token=session_token) as api:
        try:
            coops = api.list_coop()
        except ApiError as e:
            st.error(f"Co-op 列表加载失败：{e.detail}")
            coops = []

    from app.ui_theme import labelled_line_html, plain_text_html  # noqa: PLC0415

    if not coops:
        st.warning("还没有可以公开的 Co-op 经验，欢迎分享第一条。")
    else:
        for c in coops:
            with st.container(border=True):
                cols = st.columns([3, 1])
                # Reviewed student submissions: escaped HTML lines and st.text, never Markdown
                # (Streamlit's Markdown keeps links of any scheme and other syntax).
                # 中文：审核过的学生投稿：用转义的 HTML 行和 st.text 显示，不当 Markdown
                # （Streamlit 的 Markdown 会保留任意协议的链接和其他语法）。
                term = f" · {plain_text_html(c['coop_term'])}" if c.get("coop_term") else ""
                cols[0].markdown(
                    f'<div class="nc-line"><b>{plain_text_html(c["company"])}</b> — '
                    f'{plain_text_html(c["role"])}{term}</div>',
                    unsafe_allow_html=True,
                )
                cols[1].caption(VISIBILITY_LABELS.get(c["visibility_level"], f"等级 {c['visibility_level']}"))

                if c.get("industry"):
                    st.markdown(labelled_line_html("行业", industry_label(c["industry"])), unsafe_allow_html=True)
                if c.get("duration_months"):
                    st.markdown(labelled_line_html("时长", f"{c['duration_months']} 个月"), unsafe_allow_html=True)

                # Detail tier — the API redacts fields the caller's tier
                # hasn't earned; visibility_level comes from what the row
                # holds (schemas.coop.derive_visibility: 1 = interview
                # details and no salary, 2 = a salary range, with or without
                # interview details), so absent-but-existing fields get a
                # give-to-get unlock hint instead of silent nothing, and only
                # what the level guarantees is claimed.
                # 中文:详情分级 —— 调用方分级还没赚到的字段，API 会
                # 直接打码；visibility_level 由这一行的内容决定（1 = 有面试
                # 细节、没有薪资，2 = 有薪资区间，面试细节不一定有），所以
                # "缺失但其实存在"的字段会得到一个 give-to-get 解锁提示，
                # 并且只说这个等级保证有的内容。
                has_detail = c.get("interview_summary") or c.get(
                    "technical_questions"
                )
                if c.get("interview_summary"):
                    with st.expander("面试经过"):
                        st.text(c["interview_summary"])
                if c.get("technical_questions"):
                    with st.expander("技术问题"):
                        st.text(c["technical_questions"])
                if c["visibility_level"] == 1 and not has_detail:
                    st.caption("🔒 这条有面试细节：你分享的经验有 1 条公开后解锁")

                # Premium tier
                if c.get("salary_range_usd"):
                    st.markdown(labelled_line_html("💰 薪资区间", c["salary_range_usd"]), unsafe_allow_html=True)
                elif c["visibility_level"] >= 2:
                    st.caption("🔒 这条有薪资区间：你分享的经验有 2 条公开后解锁")

    # === Upload form (logged-in users only) ===
    # 中文:上传表单（仅限已登录用户）
    st.divider()
    st.subheader("分享你的 Co-op 经验")

    if not is_logged_in(st.session_state):
        st.info("用 NEU 邮箱登录后才能分享。")
        return

    with st.form("coop_upload"):
        company = st.text_input("公司 *")
        role = st.text_input("职位 *")
        coop_term = st.text_input("Co-op 学期（例如 Summer 2025）")
        # format_func renders None as a clear "不填" prompt instead of the literal string
        # "None" — users thought they had to pick "None" as an explicit value. The option
        # values are the API's industry codes and stay as they are.
        # 中文：format_func 把 None 显示成清晰的「不填」，而不是字面的 "None" —— 之前用户
        # 以为必须显式选 "None"。选项值是 API 的行业代码，保持不变。
        industry = st.selectbox(
            "行业",
            options=[None, *INDUSTRY_LABELS],
            format_func=lambda x: "不填" if x is None else industry_label(x),
        )
        duration_months = st.number_input(
            "时长（月）", min_value=1, max_value=8, value=6, step=1,
        )
        related_courses = st.text_input(
            "相关课程（用逗号分隔课程代码，例如 AAI 6600, DS 5220）"
        )
        interview_summary = st.text_area(
            "面试经过（请先去掉姓名、联系方式等个人信息）", max_chars=10_000,
        )
        technical_questions = st.text_area(
            "技术问题（请先去掉个人信息）", max_chars=10_000,
        )
        salary_range_usd = st.text_input(
            "薪资区间（例如 $30-35/hr，可不填）"
        )

        submitted = st.form_submit_button("提交")
        if submitted:
            if not company.strip() or not role.strip():
                # Client-side check for the * fields — without it an empty
                # submit surfaced the server's raw pydantic error list with
                # the (irrelevant) k-anonymity generalization advice.
                # 中文:对带 * 的必填字段做客户端校验 —— 没有这一步，
                # 空提交会直接暴露服务端原始的 pydantic 错误列表，
                # 还夹杂着（此时并不相关的）k-匿名泛化建议。
                st.error("公司和职位是必填项。")
                return
            payload: dict = {
                "company": company.strip(),
                "role": role.strip(),
                "coop_term": coop_term.strip() or None,
                "industry": industry,
                "duration_months": int(duration_months) if duration_months else None,
                "related_courses": [
                    c.strip() for c in related_courses.split(",") if c.strip()
                ],
                "interview_summary": interview_summary.strip() or None,
                "technical_questions": technical_questions.strip() or None,
                "salary_range_usd": salary_range_usd.strip() or None,
            }
            with ApiClient(session_token=session_token) as api:
                try:
                    resp = api.upload_coop(payload)
                    apply_upload_result(st.session_state, resp)
                    st.rerun()
                except ApiError as e:
                    # The generalization hint only applies to the
                    # k-anonymity rejection — not to validation 422s.
                    # 中文:泛化建议只适用于 k-匿名拒绝的情形 ——
                    # 不适用于校验类的 422。
                    if e.status_code == 422 and "uniquely identifying" in str(
                        e.detail
                    ):
                        st.error(
                            f"提交被拒：{e.detail}\n\n"
                            "可以把其中一项写得更笼统一些（例如写行业而不是公司名）再提交。"
                        )
                    else:
                        st.error(f"提交失败：{e.detail}")


# `__main__` only: Streamlit sets the MAIN script's __name__ to "__main__",
# so `streamlit run app/coop_view.py` still works. The old extra clause
# (`"streamlit" in sys.argv[0]`) also fired when streamlit_app lazily
# IMPORTED this module (argv[0] is the streamlit binary) — running render()
# at import time and double-rendering the whole panel inside the main app.
# 中文:仅 `__main__`：Streamlit 会把主脚本的 __name__ 设为 "__main__"，
# 所以 `streamlit run app/coop_view.py` 依然能正常工作。旧的那条额外
# 判断（`"streamlit" in sys.argv[0]`）在 streamlit_app 惰性导入本模块时
# 也会触发（argv[0] 就是 streamlit 这个可执行文件）—— 导致在导入时就
# 执行 render()，在主 app 里把整个面板重复渲染了一遍。
if __name__ == "__main__":
    render()
