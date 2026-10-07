"""Course detail panel: what a student needs first, provenance folded underneath.

Order: header → recorded description + one caveat line → review estimates → prerequisites →
grading / topics / skills / careers → instructors → program fit → AI policy → 来源与说明
(full provenance, missing fields, quotes) → share link. Extracted fields (instructors, grading
names, careers, AI policy) come from an LLM reading reviews and syllabi, so they render as
escaped HTML lines, never as Markdown.

中文：课程详情面板：学生最先要看的在上面，来源信息收在下面。顺序：标题 → 记录的描述 + 一行
提示 → 评价里的估计 → 先修要求 → 考核 / 主题 / 技能 / 职业方向 → 任课老师 → 培养方案定位 →
AI 政策 → 来源与说明（完整来源、缺失字段、引文）→ 分享链接。抽取字段（老师、考核项名称、
职业方向、AI 政策）来自模型读评价和大纲的结果，所以用转义后的 HTML 行显示，不当 Markdown。
"""

from __future__ import annotations

from typing import Any


def soft_estimates(course: dict) -> str | None:
    """'⏱️ 每周约 12 小时 · 🎚️ 难度 4/5', or None when neither estimate exists."""
    bits = []
    if course.get("workload_hours_per_week") is not None:
        bits.append(f"⏱️ 每周约 {course['workload_hours_per_week']:g} 小时")
    if course.get("difficulty_score") is not None:
        bits.append(f"🎚️ 难度 {course['difficulty_score']:g}/5")
    return " · ".join(bits) if bits else None


def grading_text(components: list[dict]) -> str:
    return " · ".join(
        f"{item['name']} {item['weight'] * 100:.0f}%" if item.get("weight") is not None else str(item["name"])
        for item in components
    )


def _line(st: Any, label: str, value: object) -> None:
    from app.ui_theme import labelled_line_html  # noqa: PLC0415

    st.markdown(labelled_line_html(label, value), unsafe_allow_html=True)


def render_course_detail(st: Any, course: dict, *, cid: str) -> None:
    from app.answer_evidence_view import (  # noqa: PLC0415
        render_answer_evidence, render_course_overview, render_field_evidence,
    )
    from app.course_requisite_view import render_course_requisites, render_prerequisite_links  # noqa: PLC0415
    from app.deep_links import course_share_ref, share_url  # noqa: PLC0415
    from app.ui_theme import (  # noqa: PLC0415
        course_header_html, plain_text_html, program_context_html, topic_pills_html,
    )
    from config import settings  # noqa: PLC0415

    evidence = course.get("answer_evidence")
    st.markdown(
        course_header_html(
            code=course["primary_code"], name=course["primary_name"], term=course.get("term"),
            credits=course.get("credits"), delivery_mode=course.get("delivery_mode"),
        ),
        unsafe_allow_html=True,
    )
    render_course_overview(st, evidence)

    # The product's own sample chips advertise "课业最轻": when the estimates exist they must be
    # visible, and labelled as estimates. 中文：示例查询本身就在宣传「课业最轻」，有估计值时
    # 必须显示出来，并标明是估计。
    estimates = soft_estimates(course)
    if estimates:
        _line(st, "学生评价里的估计", estimates)

    requisite_bundle = course.get("course_requisites")
    render_course_requisites(st, requisite_bundle, course_id=course["course_id"],
        course_code=course["primary_code"], course_name=course["primary_name"], key=f"course-requisites-{cid}")
    render_prerequisite_links(st, course, requisite_bundle)

    if course.get("grading_components"):
        _line(st, "📝 考核构成", grading_text(course["grading_components"]))
    if course.get("topics_covered"):
        st.markdown("**主题**")
        st.markdown(topic_pills_html(course["topics_covered"]), unsafe_allow_html=True)
    if course.get("skill_tags"):
        st.markdown("**🛠️ 技能**")
        st.markdown(topic_pills_html(course["skill_tags"]), unsafe_allow_html=True)
    if course.get("career_relevance"):
        _line(st, "💼 职业方向", " · ".join(course["career_relevance"]))
    if course.get("professor"):
        _line(st, "任课老师", ", ".join(course["professor"]))

    # Layer 3 ontology context: where this course sits in seeded programs. Empty for courses
    # outside any seeded program. 中文：Layer 3 本体上下文：本课在已 seed 培养方案中的位置；
    # 不在任何已 seed 方案里的课程为空。
    if course.get("program_context"):
        st.markdown("**📋 在培养方案里的位置**")
        st.markdown(program_context_html(course["program_context"]), unsafe_allow_html=True)

    policy = course.get("ai_policy")
    if policy:
        with st.expander("🤖 AI 使用政策"):
            if policy.get("permitted_tools"):
                _line(st, "✅ 允许", ", ".join(policy["permitted_tools"]))
            if policy.get("banned_tools"):
                _line(st, "🚫 禁止", ", ".join(policy["banned_tools"]))
            if policy.get("disclosure_required"):
                st.markdown("📣 使用 AI 需要声明")
            if policy.get("notes"):
                st.markdown(f'<div class="nc-line">{plain_text_html(policy["notes"])}</div>', unsafe_allow_html=True)

    snippets = course.get("evidence_snippets") or []
    with st.expander("📎 来源与说明（数据从哪来、缺了什么）"):
        render_answer_evidence(st, evidence, detailed=True, show_description=False)
        if snippets:
            st.markdown(f"**评价和大纲原文摘录（{len(snippets)} 条）**")
            render_field_evidence(st, snippets)

    # Share link — the produce half of deep links. st.code gets a hover copy button for free.
    # 中文：分享链接 —— 深链的生产半边。st.code 自带悬停复制按钮。
    with st.expander("🔗 分享这门课"):
        st.code(share_url(settings.public_base_url, course=course_share_ref(course["primary_code"])), language=None)
        st.caption("把链接发给同学，他们打开就直接看到这门课。")


__all__ = ["grading_text", "render_course_detail", "soft_estimates"]
