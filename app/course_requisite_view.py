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


def render_prerequisite_links(st, course: dict, requisite_bundle: dict | None) -> None:
    """Legacy prerequisite edges as NAVIGATION, under the structured rules.

    Without structured records: the old flat graph + labelled rows (unverified).
    With them: the flat graph stays hidden (it would contradict AND/OR), but
    the 查看 jump buttons remain as plain links — hiding them too stranded the
    student on a page with no way to the prerequisite courses.

    中文：把旧先修边作为导航显示在结构化规则下方。没有结构化记录时：旧平铺图 +
    带标注的行（未核验）。有结构化记录时：平铺图继续隐藏（会与 AND/OR 矛盾），
    但"查看"跳转按钮作为纯链接保留 —— 连按钮一起隐藏会让学生无法去看先修课。
    """
    from app.state_manager import select_course  # noqa: PLC0415
    from app.ui_theme import prereq_label_md  # noqa: PLC0415

    prereqs = course.get("prerequisites") or []
    if not prereqs:
        return
    graph_allowed = legacy_graph_allowed(requisite_bundle)
    if graph_allowed:
        st.markdown("**🧱 旧平铺先修关系（未核验，仅供导航）**")
        st.caption("旧边不表达 AND/OR、最低成绩或共修；不能用它判断哪些课全部必修或能否注册。")
        # Mini prereq graph (round-3 review's "killer feature" ask):
        # st.graphviz_chart renders the DOT source client-side — no graphviz
        # runtime in the image.
        # 中文：迷你先修图（第三轮评审要的"杀手功能"）：st.graphviz_chart 在
        # 客户端渲染 DOT 源码 —— 镜像里不需要 graphviz 运行时。
        from rag.prereq_graph import build_prereq_dot  # noqa: PLC0415

        dot = build_prereq_dot(course["primary_code"], prereqs)
        if dot:
            st.graphviz_chart(dot)
    else:
        st.markdown("**🔗 去看看这些先修课**")
        st.caption("只用来跳转；不表示「都要」还是「任选」、最低成绩或是否必修，以上面的先修规则为准。")
    for p in prereqs:
        cols = st.columns([4, 1])
        if graph_allowed:
            cols[0].markdown(prereq_label_md(
                code=p.get("primary_code"), name=p.get("primary_name"),
                course_id=p["course_id"], requirement=p["requirement"],
            ))
        else:
            # No required/recommended label next to structured rules; plain text.
            # 中文：结构化规则旁不标注"必修/建议"；纯文本显示。
            cols[0].text(" · ".join(
                part for part in (p.get("primary_code"), p.get("primary_name")) if part
            ) or p["course_id"])
        # Only navigable when the prereq exists in the catalog.
        # 中文：只有先修课存在于目录中时才可跳转。
        if p.get("primary_code") and cols[1].button(
            "查看", key=f"prereq-{p['course_id']}", use_container_width=True,
        ):
            select_course(st.session_state, p["course_id"])
            st.rerun()


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
    """The chosen edition's prerequisite/corequisite rules up front; every caveat, the credit
    evidence, description keywords and source details folded into 先修的来源与说明, and the
    same-year program context in its own expander. 中文：所选年份的先修/共修规则放在前面；
    所有说明、学分证据、描述关键词和来源信息收进「先修的来源与说明」，同年度培养方案上下文
    单独一个折叠区。"""
    st.markdown("**🧩 先修要求**")
    st.caption("按目录原文整理，不判断你能不能注册；能否选课以学校系统为准。")
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
    # Several editions: the student must choose (never default to the latest).
    # Exactly one: there is no choice to make — show it by default (still
    # labelled "path not declared"); the student can still clear it.
    # 中文：有多个年度时必须由学生选择（绝不默认最新）。只有一个年度时没有可选
    # 的余地 —— 默认展开它（仍标注"路径未声明"），学生依然可以清空。
    single = len(by_year) == 1
    if single and key not in st.session_state:
        # Initialise ONCE (first render of this course's widget). A student who
        # then picks the blank option keeps None — it's never re-forced.
        # 中文：只在首次渲染时初始化一次。学生之后选空选项会保持 None，不再强制。
        st.session_state[key] = next(iter(by_year))
    chosen = st.selectbox("先修规则的 Catalog 年份（不会默认选最新）", [None, *by_year], key=key,
        format_func=lambda year: "请选择适用的年份" if year is None else f"Catalog {year}（校区和个人路径未声明）")
    if chosen is None:
        return
    if single:
        st.caption("目前只记录了这一个 Catalog 年份，已默认显示；它不一定是你适用的年份。")
    document: CourseRequisiteDocument = by_year[chosen]
    for name, label in [("prerequisite", "先修课"), ("corequisite", "共修课（与先修分开）")]:
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
    with st.expander("📎 先修的来源与说明"):
        st.caption("展示课程块条款和未解释的描述证据；不判断个人注册、减免、成绩、开课或完整政策。旧平铺边不表达 AND/OR/成绩。")
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
        render_description_evidence(st, document)
        st.markdown(f"[官方院系来源]({document.source.url})")
        st.caption(f"来源捕获 UTC {document.source.captured_at.isoformat()} · 导入 UTC {document.imported_at.isoformat()}；不是实时查询")
        st.text(f"来源 HTML 字节摘要：{document.source.sha256}（不证明不可篡改真实性或个人适用性）")
        st.caption("批准/资格证据和项目片段不是完整学校政策；个人成绩与适用性仍需核实。此规则未用于对话回答或生成学期安排。")
    context = next((item for item in bundle.program_contexts if item.catalog_year == chosen and item.course_code == course_code), None)
    with st.expander("🎓 同一年份培养方案里的相关要求"):
        # Edition-specific widget keys prevent a previous path silently carrying over.
        render_program_context(st, context, key=f"{key}-program-{chosen}")
