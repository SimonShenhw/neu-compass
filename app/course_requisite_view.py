"""Explicit edition selection; plain-text AND/OR, never a flat eligibility graph."""

from __future__ import annotations

from pydantic import ValidationError

from schemas.course_requisite_document import CourseRequisiteDocument, CourseRequisiteListing
from schemas.course_requisites import RequisiteNode
from schemas.course_program_context import CourseProgramContext
from app.program_plan_view import rule_lines as program_rule_lines, scope_label


def render_description_evidence(st, document: CourseRequisiteDocument) -> None:
    st.markdown("**描述中的批准／资格关键词证据（未解释为规则）**")
    evidence = document.description_evidence
    if evidence is None:
        st.text("旧文档未捕获描述证据；不是没有批准或资格条件。")
        return
    if evidence.status == "not_listed":
        st.text("课程块未列出 description 段；条件仍未知。")
    elif evidence.status == "no_keyword_match":
        st.text("记录的描述未匹配当前有限关键词；不是已证明没有资格条件。")
    else:
        st.text("关键词候选待人工复核：可能为可选许可、否定或教学内容；不表示强制条件、已获批准或可注册。")
        for candidate in evidence.candidates:
            st.text(f"描述段 {candidate.paragraph_index + 1} · 关键词：{', '.join(candidate.markers)}")
            st.text(evidence.paragraphs[candidate.paragraph_index])
    if evidence.paragraphs:
        with st.expander("已记录的完整描述（逐段，仅统一空白）"):
            for text in evidence.paragraphs:
                st.text(text)


def render_program_context(st, context: CourseProgramContext | None, *, key: str) -> None:
    st.markdown("**同年度培养方案上下文（与课程先修分开）**")
    st.caption("仅关联显式列出本课程的已对照片段；开放前缀/编号范围不用于匹配。各方案条款不一定都约束本课，不代表你的适用路径。")
    if context is None or not context.schema_available:
        st.caption("项目上下文未提供或存储尚不可用；不从旧 seed 猜条件。")
        return
    if context.unusable_records or "program_context_schema_unusable" in context.warnings:
        st.warning("存在同年度无法使用的方案记录或存储结构；不能据此断言没有更高门槛。")
    if context.unreviewed_records:
        st.caption("有显式列课但尚未对照的方案，未作已核验上下文展示。")
    if not context.plans:
        st.caption("没有可用的同年度显式关联；不是没有学校或项目政策，也不回退其他年度。")
        return
    by_id = {plan.plan_id: plan for plan in context.plans}
    if st.session_state.get(key) not in {None, *by_id}:
        st.session_state.pop(key, None)
    selected = st.selectbox("选择关联培养方案（不默认个人路径）", [None, *by_id], key=key,
        format_func=lambda value: "请明确选择项目／校区／路径" if value is None else f"{by_id[value].program_id} · {scope_label(by_id[value])}")
    if selected is None:
        return
    plan = by_id[selected]
    st.text(f"{plan.program_id} · {scope_label(plan)}")  # Free-text scope labels are not Markdown.
    st.caption(f"{plan.coverage} · 来源片段已对照")
    st.caption("项目成绩/毕业/桥接条件与课程先修最低成绩的用途不同；不取较高值替换原文，不计算个人资格。Spring/Fall 入学适用性另核实。")
    st.text(plan.notes)
    with st.expander("完整关联方案片段（保留分组、可选分支与未知）"):
        st.text("\n".join(program_rule_lines(plan.requirements)))
    st.markdown(f"[官方培养方案来源]({plan.source_url})")
    st.caption(f"来源版次 {plan.source_catalog_year} · 摘录 {plan.captured_on.isoformat()} · 对照 {plan.checked_on} · 不是实时查询")
    if plan.source_html_sha256:
        st.text(f"培养方案 HTML 字节摘要：{plan.source_html_sha256}")
    with st.expander("方案来源摘录（非完整页面或政策）"):
        st.text(plan.source_excerpt)


def legacy_graph_allowed(data: dict | None) -> bool:
    """Any raw structured record blocks fallback, including corrupt records."""
    if data is None:  # Older API: retain legacy navigation, with explicit warning.
        return True
    try:
        bundle = CourseRequisiteListing.model_validate(data)
    except ValidationError:
        return False
    return (not bundle.has_any_stored_records and not bundle.documents and bundle.unusable_records == 0
            and "structured_requisite_schema_unusable" not in bundle.warnings)


def rule_lines(node: RequisiteNode, depth: int = 0) -> list[str]:
    indent = "  " * depth
    if node.kind == "course":
        details = []
        if node.minimum_grade:
            details.append(f"最低成绩：{node.minimum_grade}")
        if node.academic_level:
            details.append(f"原文 level 标记：{node.academic_level}（不自动判断适用学生）")
        if node.concurrent_allowed:
            details.append("原文明示可并修；仍需核实其余条件")
        suffix = f"（{'；'.join(details)}）" if details else ""
        return [f"{indent}- {node.course_code}{suffix}"]
    operator = "全部分支（AND）" if node.kind == "all_of" else "任一分支（OR）"
    lines = [f"{indent}- {operator}"]
    for child in node.children:
        lines.extend(rule_lines(child, depth + 1))
    return lines


def render_course_requisites(st, data: dict | None, *, course_id: str, course_code: str,
                             course_name: str, key: str) -> None:
    st.markdown("**结构化先修／共修 · 目录原规则**")
    st.caption("展示课程块条款和未解释的描述证据；不判断个人注册、减免、成绩、开课或完整政策。旧平铺边不表达 AND/OR/成绩。")
    if data is None:
        st.caption("当前接口尚无结构化规则；旧关系只能作未核验导航参考。")
        return
    try:
        bundle = CourseRequisiteListing.model_validate(data)
    except ValidationError:
        st.warning("结构化规则格式/来源/原文一致性校验未通过，未显示；不回退为旧资格图。")
        return
    if not bundle.schema_available:
        st.caption("结构化先修存储尚不可用；需显式副本迁移，不在页面自动建表。")
        return
    if bundle.unusable_records or "structured_requisite_schema_unusable" in bundle.warnings:
        st.warning("存在无法使用的结构化记录或存储结构；未将它解释成没有要求，也不回退旧图。")
    documents = []
    for document in bundle.documents:
        if (document.course_id, document.course_code, document.course_name) != (course_id, course_code, course_name):
            st.warning("一份结构化记录的课程身份不符，未显示。")
        else:
            documents.append(document)
    if not documents:
        st.caption("没有可用的年度规则；这不表示没有先修或共修要求。")
        return
    by_year = {document.catalog_year: document for document in documents}
    if len(by_year) != len(documents):
        st.warning("同年度有多份冲突规则，未任取第一份。")
        return
    allowed = {None, *by_year}
    if st.session_state.get(key) not in allowed:
        st.session_state.pop(key, None)
    chosen = st.selectbox("选择先修规则 Catalog 年度（不默认最新版本）", [None, *by_year], key=key,
        format_func=lambda year: "请明确选择适用年度" if year is None else f"Catalog {year} · 校区/个人路径未声明")
    if chosen is None:
        return
    document: CourseRequisiteDocument = by_year[chosen]
    st.caption(f"Catalog {document.catalog_year} · 院系页面未声明校区或个人路径 · 不是完整政策")
    st.markdown("**目录标题学分（独立来源证据）**")
    if document.credit_hours is None:
        st.text("旧文档未捕获标题学分证据；不从旧整数 credits 补猜范围。")
    else:
        hours = document.credit_hours
        st.text(f"原标题学分：{hours.raw_text}")
        if hours.kind == "range":
            st.text(f"目录范围：{hours.minimum}–{hours.maximum}；实际班次学分未声明，不取端点或平均值作为固定学分。")
            st.caption("旧详情若有整数，也不是此范围已选定班次学分的证据。")
        else:
            st.text(f"目录固定值：{hours.minimum}；不是当期班次或个人学位计入的确认。")
        st.caption("此证据不重写 Course 的整数 credits，不用于范围筛选、学分求和或资格判断。")
    for name, label in [("prerequisite", "先修条款"), ("corequisite", "共修条款（与先修分开）")]:
        section = getattr(document.requisites, name)
        st.markdown(f"**{label}**")
        if section.status == "not_listed":
            st.text("课程块未列出这一段；不是已证明没有要求。")
        elif section.status == "unparsed":
            st.text(f"未解析：{section.reason}；保留整段，不展示部分成功树。")
            st.text(section.raw_text)
        else:
            st.text("完整段语法已解析；不代表要求已满足。")
            st.text("\n".join(rule_lines(section.rule)))
            with st.expander(f"{label}原文（仅统一空白）"):
                st.text(section.raw_text)
    render_description_evidence(st, document)
    st.markdown(f"[官方院系来源]({document.source.url})")
    st.caption(f"来源捕获 UTC {document.source.captured_at.isoformat()} · 导入 UTC {document.imported_at.isoformat()}；不是实时查询")
    st.text(f"来源 HTML 字节摘要：{document.source.sha256}（不证明不可篡改真实性或个人适用性）")
    context = next((item for item in bundle.program_contexts if item.catalog_year == chosen and item.course_code == course_code), None)
    # Edition-specific widget keys prevent a previous path silently carrying over.
    render_program_context(st, context, key=f"{key}-program-{chosen}")
    st.caption("批准/资格证据和项目片段不是完整学校政策；个人成绩与适用性仍需核实。此规则未用于对话回答或生成学期安排。")
