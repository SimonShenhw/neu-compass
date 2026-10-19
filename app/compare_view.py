"""Read-only, row-aligned comparison of up to four existing course details.

中文：只展示已有详情；不打分、不判断资格，不增加 API、缓存或持久化。
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.course_detail_view import grading_text, soft_estimates
from app.state_manager import MAX_COMPARE_COURSES, clear_compare, remove_from_compare, select_course
from app.text_render import labelled_line_html, literal_markdown, plain_text_html
from app.ui_theme import course_header_html, program_context_html, topic_pills_html
from schemas.answer_evidence import CatalogSnapshot
from schemas.course_requisite_document import CourseRequisiteListing

ROWS = ("官方目录描述", "学生评价里的估计", "先修／共修", "主题", "考核构成", "在培养方案里的位置", "缺的数据", "操作")


def requisite_summary(course: dict) -> list[str]:
    """Use the full listing, not chat's newest-three evidence or legacy flat edges.
    中文：只比较完整、身份相符且校验通过的年度条款；不代选个人适用年度。
    """
    data = course.get("course_requisites")
    if data is None:
        return ["没有可用的年度规则；不表示没有先修或共修要求。"]
    try:
        bundle = CourseRequisiteListing.model_validate(data)
    except ValidationError:
        return ["年度规则校验未通过；不回退旧平铺关系。"]
    if not bundle.schema_available:
        return ["结构化先修存储尚不可用。"]
    lines = []
    if bundle.unusable_records or "structured_requisite_schema_unusable" in bundle.warnings:
        lines.append("存在不可用记录或存储结构；不能据此确认完整要求。")
    own = [d for d in bundle.documents if (d.course_id, d.course_code, d.course_name)
           == (course["course_id"], course["primary_code"], course["primary_name"])]
    if len(own) != len(bundle.documents):
        lines.append("有课程身份不符的年度记录，未用于比较。")
    if not own:
        return [*lines, "没有可用的年度规则；不表示没有先修或共修要求。"]
    if len({d.catalog_year for d in own}) != len(own):
        return [*lines, "同年度有冲突记录，未任取一份比较。"]
    lines.append("已记录 Catalog 年份：" + "、".join(sorted((d.catalog_year for d in own), reverse=True)))
    if len(own) == 1:
        lines.append("只记录了一个年度，不能跨年比较。")
    else:
        def key(document):
            # Compare parsed trees; unparsed clauses by complete recorded text, never a cut.
            # 中文：已解析的比树，未解析的比完整原文；not_listed 不等于没有要求。
            return [(s.status, s.rule, s.raw_text if s.status == "unparsed" else None)
                    for s in (document.requisites.prerequisite, document.requisites.corequisite)]
        same = all(key(d) == key(own[0]) for d in own[1:])
        lines.append("这些年度已记录的条款结构相同。" if same else "这些年度已记录的条款不同，请按适用年度核对。")
    return [*lines, "未列出或未解析的条款仍未知；不判断个人适用年度或能否注册。"]


def _view_course(state, cid: str) -> None:
    select_course(state, cid)
    state["pending_nav_to_search"] = True


def _plain(st: Any, value: object) -> None:
    st.markdown(f'<div class="nc-line">{plain_text_html(value)}</div>', unsafe_allow_html=True)


def _catalog(st: Any, evidence: dict | None) -> None:
    from app.answer_evidence_view import render_course_overview  # noqa: PLC0415

    if evidence is None:
        st.text("没有官方目录描述的存档。")
        return
    render_course_overview(st, evidence)
    try:
        snapshot = CatalogSnapshot.model_validate(evidence.get("catalog"))
    except ValidationError:
        return
    if not snapshot.description:
        st.text("目录存档没有描述记录。")
    st.text(f"目录抓取：{snapshot.retrieved_at.isoformat() if snapshot.retrieved_at else '没有记录'}；不是实时核验。")


def _cell(st: Any, row: str, course: dict) -> None:
    from app.answer_evidence_view import FIELD_LABELS  # noqa: PLC0415

    evidence = course.get("answer_evidence")
    if row == "官方目录描述":
        _catalog(st, evidence)
    elif row == "学生评价里的估计":
        _plain(st, soft_estimates(course) or "没有记录")
        st.caption("来自学生评价的估计，不是官方信息；缺失不等于零或简单。")
    elif row == "先修／共修":
        for line in requisite_summary(course):
            st.text(line)
        st.caption("在详情里看完整规则")
    elif row == "主题":
        if course.get("topics_covered"):
            st.markdown(topic_pills_html(course["topics_covered"]), unsafe_allow_html=True)
        else:
            st.text("没有记录")
    elif row == "考核构成":
        _plain(st, grading_text(course["grading_components"]) if course.get("grading_components") else "没有记录")
    elif row == "在培养方案里的位置":
        if course.get("program_context"):
            st.markdown(program_context_html(course["program_context"]), unsafe_allow_html=True)
            st.caption("旧 seed 关系，未核验；不是正式方案，不判断注册或毕业资格。")
        else:
            st.text("没有记录；不表示不属于任何方案。")
    elif row == "缺的数据":
        if evidence is None:
            st.text("缺失字段没有记录；不表示数据齐全。")
        else:
            missing = evidence.get("missing_fields") or []
            st.markdown(labelled_line_html("缺失", "、".join(FIELD_LABELS.get(f, f) for f in missing)
                if missing else "没有列出缺失项；不表示数据齐全"), unsafe_allow_html=True)
            st.caption("缺失不等于零、简单或无要求。")


def render_compare_page(st: Any) -> None:
    from app.api_client import ApiClient, ApiError  # noqa: PLC0415

    st.subheader("⚖️ 课程对比")
    ids = list(st.session_state.get("compare_course_ids", []))[:MAX_COMPARE_COURSES]
    if not ids:
        st.info("在课程详情里点 ➕ 加入对比，最多选择 4 门课。")
        return
    st.caption(f"已选择 {len(ids)}/{MAX_COMPARE_COURSES} 门；按加入顺序展示，不排名、不判断选课或毕业资格。")
    st.button("清空对比", key="compare-clear", on_click=clear_compare, args=(st.session_state,))
    courses, errors = {}, {}
    with ApiClient(session_token=st.session_state.get("session_token")) as api:
        for cid in ids:
            try:
                courses[cid] = api.get_course(cid)
            except ApiError as exc:
                errors[cid] = exc.detail
    for col, cid in zip(st.columns(len(ids)), ids, strict=True):
        with col:
            if cid in errors:
                st.error(literal_markdown("课程加载失败：" + errors[cid]))
            else:
                course = courses[cid]
                st.markdown(course_header_html(code=course["primary_code"], name=course["primary_name"],
                    term=course.get("term"), credits=course.get("credits"), delivery_mode=course.get("delivery_mode")),
                    unsafe_allow_html=True)
    # A separate horizontal container per field keeps later rows aligned across columns.
    # 中文：一行一个水平容器；描述再长，也不会把后面的字段挤到别的课程同一行。
    for row in ROWS:
        for col, cid in zip(st.columns(len(ids)), ids, strict=True):
            with col:
                st.markdown(f"**{row}**")
                if row == "操作":
                    if cid not in errors:
                        st.button("查看详情", key=f"compare-view-{cid}", on_click=_view_course, args=(st.session_state, cid))
                    st.button("移出对比", key=f"compare-remove-{cid}", on_click=remove_from_compare, args=(st.session_state, cid))
                elif cid in errors:
                    st.text("加载失败")
                else:
                    _cell(st, row, courses[cid])
