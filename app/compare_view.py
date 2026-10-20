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
NO_RULES = "没有可用的年度规则；不表示没有先修或共修要求。"
UNRECOGNISED = "服务返回了无法识别的内容。"
BAD_CELL = "这一项的数据格式不对，没有显示。"
SESSION_NOTE = "列表只保存在这个页面会话里；刷新浏览器或重新登录以后要重新加入。"
# Caveats that qualify one cell are repeated there; the description row keeps the full line.
# 中文：只针对某一格的提醒在那一格再写一次；描述那一行仍保留完整的提醒。
HEADER_NOTICES = frozenset({"catalog_metadata_conflict", "synthetic_record_not_real_course"})
ESTIMATE_NOTICES = frozenset({"field_evidence_value_conflict"})
TOPIC_NOTICES = frozenset({"topics_source_unavailable"})


def _own_documents(course: dict) -> list:
    try:
        bundle = CourseRequisiteListing.model_validate(course.get("course_requisites"))
    except ValidationError:
        return []
    return [d for d in bundle.documents if (d.course_id, d.course_code, d.course_name)
            == (course["course_id"], course["primary_code"], course["primary_name"])]


def requisite_summary(course: dict) -> list[str]:
    """Use the full listing, not chat's newest-three evidence or legacy flat edges.
    中文：只比较完整、身份相符且校验通过的年度条款；不代选个人适用年度。
    """
    data = course.get("course_requisites")
    if data is None:
        return [NO_RULES]
    try:
        bundle = CourseRequisiteListing.model_validate(data)
    except ValidationError:
        return ["年度规则没有通过校验，暂不显示；不表示没有先修或共修要求。"]
    if not bundle.schema_available:
        return ["结构化先修规则暂时不可用；不表示没有先修或共修要求。"]
    lines = []
    if bundle.unusable_records or "structured_requisite_schema_unusable" in bundle.warnings:
        lines.append("存在不可用记录或存储结构；不能据此确认完整要求。")
    own = _own_documents(course)
    if len(own) != len(bundle.documents):
        lines.append("有课程身份不符的年度记录，未用于比较。")
    if not own:
        return [*lines, NO_RULES]
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


def credit_range_note(course: dict) -> str | None:
    """The newest own year's title credits, when they are a range: the header's integer is not that range.
    中文：最新一份本课程年度文档的标题学分是范围时提醒：表头的整数学分不是已选定班次的学分。
    """
    own = _own_documents(course)
    if not own or len({d.catalog_year for d in own}) != len(own):
        return None
    hours = max(own, key=lambda d: d.catalog_year).credit_hours
    if hours is None or hours.kind != "range":
        return None
    return f"目录标题学分：{hours.raw_text}；实际班次学分未声明。"


def _usable(body: object) -> bool:
    return isinstance(body, dict) and all(isinstance(body.get(k), str) for k in ("course_id", "primary_code", "primary_name"))


def _warnings(course: dict) -> list[str]:
    evidence = course.get("answer_evidence")
    warnings = evidence.get("warnings") if isinstance(evidence, dict) else None
    return [code for code in warnings if isinstance(code, str)] if isinstance(warnings, list) else []


def _notice(st: Any, course: dict, codes: frozenset[str]) -> None:
    from app.answer_evidence_view import notice_line  # noqa: PLC0415

    line = notice_line(_warnings(course), only=codes)
    if line:
        st.caption(line)


def _view_course(state, cid: str) -> None:
    select_course(state, cid)
    state["pending_nav_to_search"] = True


def _plain(st: Any, value: object) -> None:
    st.markdown(f'<div class="nc-line">{plain_text_html(value)}</div>', unsafe_allow_html=True)


def _guarded(st: Any, render, *args) -> None:
    # One malformed field must not take down the other cells and columns.
    # 中文：一个字段格式不对，不能让别的格子和别的列一起消失。
    try:
        render(st, *args)
    except (AttributeError, KeyError, TypeError, ValueError):
        st.text(BAD_CELL)


def _header(st: Any, course: dict) -> None:
    st.markdown(course_header_html(code=course["primary_code"], name=course["primary_name"],
        term=course.get("term"), credits=course.get("credits"), delivery_mode=course.get("delivery_mode")),
        unsafe_allow_html=True)
    _notice(st, course, HEADER_NOTICES)
    note = credit_range_note(course)
    if note:
        st.caption(literal_markdown(note))


def _catalog(st: Any, evidence: dict | None) -> None:
    from app.answer_evidence_view import _when, render_course_overview  # noqa: PLC0415

    if evidence is None:
        st.text("目录存档情况没有记录。")
        return
    render_course_overview(st, evidence)
    try:
        snapshot = CatalogSnapshot.model_validate(evidence.get("catalog"))
    except ValidationError:
        return
    if not snapshot.description:
        st.text("目录存档没有描述记录。")
    # The caption above already says the archive is not a live check. Same date format as the detail page.
    # 中文：上面的说明已经写了存档不是实时核对；日期格式和详情页相同。
    st.text(f"目录抓取：{_when(snapshot.retrieved_at) if snapshot.retrieved_at else '没有记录'}。")


def _cell(st: Any, row: str, course: dict) -> None:
    from app.answer_evidence_view import FIELD_LABELS  # noqa: PLC0415

    evidence = course.get("answer_evidence")
    if row == "官方目录描述":
        _catalog(st, evidence)
    elif row == "学生评价里的估计":
        _plain(st, soft_estimates(course) or "没有记录")
        st.caption("来自学生评价的估计，不是官方信息；缺失不等于零或简单。")
        _notice(st, course, ESTIMATE_NOTICES)
    elif row == "先修／共修":
        for line in requisite_summary(course):
            st.text(line)
        st.caption("在详情里看完整规则")
    elif row == "主题":
        if course.get("topics_covered"):
            st.markdown(topic_pills_html(course["topics_covered"]), unsafe_allow_html=True)
        else:
            st.text("没有记录")
        _notice(st, course, TOPIC_NOTICES)
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
        st.info("在「🔍 课程搜索」页打开一门课的详情，点 ➕ 加入对比，最多选择 4 门课。")
        return
    st.caption(f"已选择 {len(ids)}/{MAX_COMPARE_COURSES} 门；按加入顺序展示，不排名、不判断选课或毕业资格。")
    st.caption(SESSION_NOTE)
    st.button("清空对比", key="compare-clear", on_click=clear_compare, args=(st.session_state,))
    courses, errors = {}, {}
    with ApiClient(session_token=st.session_state.get("session_token")) as api:
        for cid in ids:
            try:
                body = api.get_course(cid)
            except ApiError as exc:
                errors[cid] = exc.detail
                continue
            if _usable(body):
                courses[cid] = body
            else:
                errors[cid] = UNRECOGNISED
    if errors:
        # A click only reruns the page, which reads every course again; the list stays.
        # 中文：点一下只是重跑页面，重新读取每门课；列表不变。
        st.button("🔄 重新加载", key="compare-reload")
    for col, cid in zip(st.columns(len(ids)), ids, strict=True):
        with col:
            if cid in errors:
                st.error(literal_markdown(f"课程加载失败（{cid}）：" + errors[cid]))
            else:
                _guarded(st, _header, courses[cid])
    # A separate horizontal container per field keeps later rows aligned across columns. Every cell and button
    # names its course: below 640 px Streamlit stacks the columns, and the header is then far away.
    # 中文：一行一个水平容器；描述再长，也不会把后面的字段挤到别的课程同一行。手机上 Streamlit 会把列叠起来，
    # 表头离得很远，所以每个格子和按钮都写上是哪门课。
    for row in ROWS:
        for col, cid in zip(st.columns(len(ids)), ids, strict=True):
            with col:
                code = literal_markdown(courses[cid]["primary_code"] if cid in courses else cid)
                st.markdown(f"**{row}** · {code}")
                if row == "操作":
                    if cid not in errors:
                        st.button(f"查看详情 · {code}", key=f"compare-view-{cid}", on_click=_view_course,
                                  args=(st.session_state, cid))
                    st.button(f"移出对比 · {code}", key=f"compare-remove-{cid}", on_click=remove_from_compare,
                              args=(st.session_state, cid))
                elif cid in errors:
                    st.text("加载失败")
                else:
                    _guarded(st, _cell, row, courses[cid])
