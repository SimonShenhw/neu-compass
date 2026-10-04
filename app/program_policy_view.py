"""Plain-text selected policy evidence; never guess scope or keep a stale cache."""

from __future__ import annotations

from pydantic import ValidationError

from db.program_plan_repository import content_hash
from schemas.program_plan import ProgramPlan
from schemas.program_policy import COLLEGE_NAMES
from schemas.program_policy_view import ProgramPolicyView

STATUS_TEXT = {
    "not_linked": "该精确方案尚无政策证据关联；不能套用其他年度、方向或路径。",
    "draft": "该方案尚未完成来源对照，未显示关联政策证据。",
    "stale": "方案范围或内容版本已变化，政策关联须重新核对；未显示旧证据。",
    "unavailable": "政策文件或来源存档不可用；未重新抓取或回退到旧 seed。",
    "unusable": "政策证据或来源一致性校验未通过；未显示不完整的可信片段。",
}


def render_program_policy_evidence(st, plan: ProgramPlan, data: dict) -> None:
    """Revalidate wire identity/revision before rendering even one fragment."""
    try:
        view = ProgramPolicyView.model_validate(data)
    except (ValidationError, TypeError):
        st.caption("政策响应格式／来源字段校验未通过，未显示证据。")
        return
    if (view.plan_id != plan.plan_id or view.scope.scope_key() != plan.scope_key()
            or view.plan_content_sha256 != content_hash(plan)):
        st.caption("政策响应与当前所选方案的范围／内容版本不一致；请刷新方案后重试，未显示旧证据。")
        return
    if view.status != "ready":
        st.caption(STATUS_TEXT[view.status])
        return
    if plan.review_status != "source_checked" or view.checked_on < plan.checked_on:
        st.caption("方案来源对照或审核版本已变化，未显示旧政策证据。")
        return
    st.caption("学校／学院政策证据：仅选定片段，不是完整政策或个人资格审核；不合并不同用途的成绩／学分条件。")
    st.text(f"Home college（项目页关联，不按课程前缀猜）：{COLLEGE_NAMES[view.link.home_college]}")
    st.text(f"政策对照记录：{view.checked_by} · {view.checked_on}")
    st.caption("SHA 核对只证明本地输入一致，不证明来源真实、摘要语义正确或你的个人适用年度。")
    for policy in view.policies:
        authority = "学校通用" if policy.authority == "university" else COLLEGE_NAMES[policy.authority]
        st.text(f"{authority} · {policy.source.page_title}")
        # Only the schema-checked official URL enters markdown, never titles,
        # notes, summaries, review names, source paragraphs or warning payloads.
        st.markdown(f"[官方政策来源]({policy.source.url})")
        st.caption(f"Catalog {policy.source.catalog_year} · 捕获 {policy.source.captured_at.isoformat()} · 选定片段")
        st.text(f"政策 HTML 字节摘要：{policy.source.sha256}")
        for fragment in policy.fragments:
            st.text(f"摘要：{fragment.summary}")
            st.text(f"限制／未知：{fragment.limitation}")
            kind = "段落" if fragment.source_kind == "paragraph" else "列表块"
            prefix = "p" if fragment.source_kind == "paragraph" else "l"
            with st.expander(f"政策原文片段 · {policy.policy_id} · {prefix}{fragment.paragraph_index}"):
                st.text(f"正文零基{kind} {fragment.paragraph_index} · 标题：{fragment.heading or '无小节标题'}")
                st.text(fragment.source_paragraph)
                st.text(f"{kind}文字摘要：{fragment.paragraph_sha256}")


def load_selected_program_policy_evidence(st, plan: ProgramPlan) -> None:
    """No cache or persistent selected evidence; clearing a choice clears output."""
    from app.api_client import ApiClient, ApiError  # noqa: PLC0415

    try:
        with ApiClient(session_token=st.session_state.get("session_token"), timeout=8.0) as api:
            data = api.get_program_policies(plan.program_id, plan.plan_id)
    except (ApiError, ValueError):
        st.caption("无法加载所选方案的政策证据；未使用旧缓存，方案规则仍可浏览。")
        return
    render_program_policy_evidence(st, plan, data)
