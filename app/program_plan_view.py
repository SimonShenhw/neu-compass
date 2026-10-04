"""Explicit scope selection and rule-tree display; no eligibility evaluation."""

from __future__ import annotations

from collections import Counter

from pydantic import ValidationError

from schemas.program_plan import ProgramPlan, RequirementNode

PATH_LABELS = {"standard": "普通 MS", "align": "Align", "bridge": "Bridge"}


def render_chat_program_selector(st, programs: list[dict]) -> str | None:
    """Select a family explicitly; never infer personal catalog applicability."""
    by_id = {item["program_id"]: item for item in programs}
    if not by_id:
        return None
    key = "chat_program_id"
    if st.session_state.get(key) not in {None, *by_id}:
        st.session_state.pop(key, None)
    selected = st.selectbox(
        "对话项目（可选；不是方案年度选择）", [None, *by_id], key=key,
        format_func=lambda value: "不指定；有歧义时请明确选择" if value is None else f"{by_id[value]['full_name']} · {value}",
    )
    if selected is not None:
        st.caption("仅区分项目；校区、Catalog 年度与个人适用性尚未由此确认。")
    return selected


def scope_label(plan: ProgramPlan) -> str:
    concentration = plan.concentration or "共同部分／未限定 concentration"
    return f"{plan.campus} · Catalog {plan.catalog_year} · {PATH_LABELS[plan.pathway]} · {concentration}"


def rule_lines(node: RequirementNode, *, depth: int = 0) -> list[str]:
    indent = "  " * depth
    if node.kind == "course":
        return [f"{indent}- {node.course_code}：{node.label}"]
    if node.kind in {"condition", "unmodeled"}:
        kind = "条件（需核实，未自动判定）" if node.kind == "condition" else "尚未建模"
        return [f"{indent}- {kind}：{node.label}"]
    if node.kind == "select":
        minima = []
        if node.min_courses:
            minima.append(f"至少 {node.min_courses} 门")
        if node.min_credits:
            minima.append(f"至少 {node.min_credits} 学分")
        if node.min_areas:
            minima.append(f"至少 {node.min_areas} 个领域")
        lines = [f"{indent}- 组选：{node.label}（{'；'.join(minima)}；不是所有候选均必修）"]
        if node.course_codes:
            lines.append(f"{indent}  候选：{'、'.join(node.course_codes)}")
        if node.subject_codes:
            lines.append(f"{indent}  科目前缀：{'、'.join(node.subject_codes)}（仍需核实级别、先修与开课）")
        for interval in node.course_ranges:
            lines.append(f"{indent}  编号范围：{interval.start}–{interval.end}（不证明每个编号都有课程或当前开课）")
        if node.excluded_course_codes:
            lines.append(f"{indent}  排除：{'、'.join(node.excluded_course_codes)}")
        lines.extend(f"{indent}  领域 {name}：{'、'.join(codes)}" for name, codes in node.areas.items())
        return lines
    if node.kind == "optional":
        return [f"{indent}- 可选分支：{node.label}（{node.activate_when}；不是共同必修）", *rule_lines(node.children[0], depth=depth + 1)]
    operator = "全部分支（AND）" if node.kind == "all_of" else "任一分支（OR）"
    lines = [f"{indent}- {operator}：{node.label}"]
    for child in node.children:
        lines.extend(rule_lines(child, depth=depth + 1))
    return lines


def render_program_plans(st, documents: list[dict], *, key: str, program_id: str | None = None) -> ProgramPlan | None:
    if program_id is not None:
        from app.program_plan_links import consume_plan_selection
        consume_plan_selection(st, documents, key=key, program_id=program_id)
    plans = []
    for document in documents:
        try:
            candidate = ProgramPlan.model_validate(document)
            if program_id is not None and candidate.program_id != program_id:
                st.caption('一份方案与当前项目身份不符，未显示。')
                continue
            plans.append(candidate)
        except ValidationError:
            st.caption("一份版本化规则格式/来源校验未通过，未显示。")
    id_counts = Counter(plan.plan_id for plan in plans)
    scope_counts = Counter(plan.scope_key() for plan in plans)
    unambiguous = [plan for plan in plans if id_counts[plan.plan_id] == scope_counts[plan.scope_key()] == 1]
    if len(unambiguous) != len(plans):
        st.caption("重复的方案身份／范围存在歧义，相关版本未显示。")
    plans = unambiguous
    if not plans:
        st.session_state.pop(key, None)
        st.caption("尚无可用版本化方案；旧 seed 的校区、目录年度和路径未知。")
        return
    by_id = {plan.plan_id: plan for plan in plans}
    if st.session_state.get(key) not in {None, *by_id}:
        st.session_state.pop(key, None)
    chosen = st.selectbox(
        "选择目录版本与路径（不自动判定你的适用年度）", [None, *by_id],
        format_func=lambda value: "请明确选择；不默认最新版本" if value is None else scope_label(by_id[value]),
        key=key,
    )
    if chosen is None or chosen not in by_id:
        return
    plan = by_id[chosen]
    st.caption(scope_label(plan))
    st.caption("入学年份／Spring-Fall 学期需另行确认；此处只展示规则，不判断注册或毕业资格。")
    coverage = "仅规则片段，不是完整培养方案" if plan.coverage == "partial" else "完整性由导入方声明，仍非个人资格审核"
    review = "来源片段已对照" if plan.review_status == "source_checked" else "尚未完成来源对照"
    st.caption(f"{coverage} · {review}")
    st.text(plan.notes)
    st.text("\n".join(rule_lines(plan.requirements)))
    st.markdown(f"[官方目录来源]({plan.source_url})")
    st.caption(f"来源版次 {plan.source_catalog_year} · 摘录日期 {plan.captured_on.isoformat()} · 不证明当前班次开课")
    if plan.source_html_sha256:
        st.text(f"来源 HTML 字节摘要：{plan.source_html_sha256}（不证明来源真实或个人适用性）")
    if plan.checked_by:
        st.text(f"对照记录：{plan.checked_by} · {plan.checked_on}")
    with st.expander("来源摘录（非完整页面存档）"):
        st.text(plan.source_excerpt)
    return plan
