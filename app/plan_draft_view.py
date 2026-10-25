"""Explicit-action, session-only course draft; never shared with chat or stored.
中文：只在点击加入时取数据；规则计算只读纯函数结果，来源文字不当 Markdown。
"""

from __future__ import annotations

from pydantic import ValidationError

from app.state_manager import add_draft_courses, clear_draft, remove_draft_course
from app.text_render import literal_markdown
# parse_course_codes lives in schemas/plan_draft.py since R4b (the API's draft check reads input the same way); it
# stays importable from here. 中文：R4b 起 parse_course_codes 放在 schemas/plan_draft.py（API 的草案核对同样读输入），
# 这里照样能导入。
from schemas.plan_draft import MAX_DRAFT_COURSES, DraftCourse, DraftNode, evaluate_draft, parse_course_codes
from schemas.program_plan import ProgramPlan


def _courses(state) -> list[DraftCourse]:
    courses = [DraftCourse.model_validate(c) for c in state.get("plan_draft_courses", [])]
    if len(courses) > MAX_DRAFT_COURSES or len({c.code for c in courses}) != len(courses):
        raise ValueError("Invalid draft state")
    return courses


def _add(st, raw: str, existing: list[DraftCourse]) -> None:
    from app.api_client import ApiClient, ApiError  # noqa: PLC0415

    codes, invalid = parse_course_codes(raw)
    if len(codes) > MAX_DRAFT_COURSES:
        st.warning("一次最多填写 20 门；本次没有加入课程。")
        return
    for token in invalid[:10]:
        st.warning(literal_markdown("课号格式不正确，未加入：" + token))
    if len(invalid) > 10:
        st.warning(f"另有 {len(invalid)-10} 项格式不正确；未加入。")
    known = {c.code for c in existing}
    pending = [code for code in codes if code not in known]
    if not pending:
        if codes:
            st.info("这些课号已在草案里，不会重复加入。")
        return
    excess = len(known) + len(pending) - MAX_DRAFT_COURSES
    if excess > 0:
        st.warning(f"草案最多 20 门，本次尚未核对；请从输入减少 {excess} 门，或从草案移除至少 {excess} 门。")
        return
    accepted, taken, twins = [], set(known), {}  # twins: a code an accepted course's H2 matches named -> that course.
    with st.spinner("正在核对课程…"), ApiClient(session_token=st.session_state.get("session_token")) as api:
        for index, code in enumerate(pending):
            try:
                raw_matches = api.resolve_course(code)["matches"]
                if not isinstance(raw_matches, list):
                    raise ValueError("Malformed match list")
                matches = [DraftCourse(course_id=m["course_id"], code=m["primary_code"], name=m["primary_name"])
                           for m in raw_matches]
                if not matches:
                    st.warning(literal_markdown("没有找到 " + code + "；未加入。"))
                    continue
                if len(matches) != 1:
                    exact = [m for m in matches if m.code == code]
                    if len(exact) != 1:
                        st.warning(literal_markdown("对上多门，未加入；请核对完整课号：" + code))
                        for match in matches[:10]:
                            st.text(match.code + " · " + match.name)
                        if len(matches) > 10:
                            st.caption(f"另有 {len(matches)-10} 个候选未展开。")
                        continue
                    match = exact[0]
                    others = list(dict.fromkeys(m.code for m in matches if m != match))
                else:
                    match, others = matches[0], []
                twin = twins.get(match.code) or next((other for other in others if other in taken), None)
                if twin:  # One course under two cross-listed codes counts once.
                    st.warning(literal_markdown(code + " 和 " + twin + " 可能是同一门交叉列出的课，只按 " + twin
                        + " 计入；如果是两门不同的课，请向项目核实。"))
                    continue
                if others:
                    st.warning(literal_markdown("按输入主课号核对 " + code + "；同一引用也匹配 " + "、".join(others[:10])
                        + "（可能交叉列出）；方案按哪个课号算，请向项目核实。"))
                detail = api.get_course(match.course_id)
                candidate = DraftCourse(course_id=detail["course_id"], code=detail["primary_code"],
                    name=detail["primary_name"], credits=detail.get("credits"))
                if candidate.course_id != match.course_id or candidate.code != match.code:
                    raise ValueError("Course identity mismatch")
                accepted.append(candidate.model_dump())
                taken.add(candidate.code)
                twins.update({other: candidate.code for other in others if other not in twins})
                if candidate.code != code:  # A single alias match under another primary code (renumbered, renamed).
                    st.warning(literal_markdown("输入的 " + code + " 对应主课号 " + candidate.code + "，按 " + candidate.code
                        + " 核对；方案按哪个课号算，请向项目核实。"))
            except ApiError as exc:
                st.warning(literal_markdown(code + " 暂时无法核对或加载，未加入；请稍后手动重试。"))
                if exc.error_type in {"transport_error", "transport_timeout"}:
                    st.warning(f"连接或传输中断，后面 {len(pending)-index-1} 门未核对；请稍后手动重试。")
                    break
            except (KeyError, TypeError, ValueError):
                st.warning(literal_markdown(code + " 返回的课程身份或字段无效，未加入。"))
    outcome = add_draft_courses(st.session_state, accepted)
    if outcome == "full":
        st.warning("草案最多 20 门；本次没有加入课程，请减少本次输入后重试。")
    elif outcome == "already":
        st.info("没有新增课程；重复课号不会重复加入。")


def _tree_lines(node: DraftNode, depth: int = 0) -> list[str]:
    labels = {"met": "✅ 按你填的满足", "missing": "⬜ 还缺", "unknown": "❔ 不确定",
              "not_evaluated": "⏸ 可选分支，不自动判断", None: "仅列出，不自动判断"}
    prefix = "  " * depth
    operator = {"all_of": "全部分支（AND）", "any_of": "任选其一（OR）", "select": "组选（非全部必修）"}.get(node.kind, "")
    title = f"{operator} {node.label}" if operator else node.label
    lines = [f"{prefix}{labels[node.status]} — {title}"]
    certain = [code for code in node.counted if code not in node.possible]
    for label, codes in [("按填写计入", certain), ("可能计入／学分未知", node.possible), ("缺项候选", node.missing)]:
        if codes:
            lines.append(f"{prefix}  {label}：{'、'.join(codes)}")
    if node.missing_omitted:
        lines.append(f"{prefix}  另有 {node.missing_omitted} 项候选／子项未展开。")
    lines.extend(f"{prefix}  原因：{reason}" for reason in node.reasons)
    if node.reasons_omitted:
        lines.append(f"{prefix}  另有 {node.reasons_omitted} 项原因未展开。")
    for child in node.children:
        lines.extend(_tree_lines(child, depth + 1))
    return lines


def render_plan_draft(st, plan: ProgramPlan | None) -> None:
    if plan is None or plan.review_status != "source_checked":
        return
    st.subheader("🧮 我的选课草案（只在本次会话）")
    st.caption("填写修过或打算修的课，只按填写课号解释已记录规则；不看成绩、免修、审批或开课学期，不判断能否注册或毕业。")
    st.caption("仅本次会话保存；刷新为新会话、登出或换账号后清空，不写数据库、不分享清单，也不交给聊天。")
    st.caption("学分来自加入时的课程记录，不确认具体班次或个人学位计入。")
    st.button("清空草案", key="draft-clear", on_click=clear_draft, args=(st.session_state,))
    try:
        courses = _courses(st.session_state)
    except (ValueError, TypeError):
        st.error("草案数据格式异常，未计算；请清空后重新添加。")
        return
    with st.form("plan-draft-form", clear_on_submit=False):
        raw = st.text_area("课号（逗号、空格或换行分开，例如 CS 5010, CS 5800）", key="plan-draft-input", max_chars=4000)
        submitted = st.form_submit_button("加入草案")
    if submitted:
        _add(st, raw, courses)
        courses = _courses(st.session_state)
    st.text(f"已填 {len(courses)}/{MAX_DRAFT_COURSES} 门（不区分已修与打算修）")
    from app.deep_links import course_share_ref, share_url  # noqa: PLC0415
    from config import settings  # noqa: PLC0415

    for course in courses:
        credits = "学分未知" if course.credits is None else f"{course.credits} 学分"
        st.text(f"{course.code} · {course.name} · {credits}")
        st.markdown(f"[{course.code} · 课程页／年度先修]({share_url(settings.public_base_url, course=course_share_ref(course.code))})")
        st.button(f"移除 {course.code}", key=f"draft-remove-{course.code}", on_click=remove_draft_course, args=(st.session_state, course.code))
    try:
        result = evaluate_draft(plan, courses)
    except (ValidationError, ValueError):
        st.error("方案或草案无法安全计算；请重新选择已核对方案并检查课号。")
        return
    counts = result.summary_counts
    st.text(f"按记录到的规则：{counts['met']} 组满足、{counts['missing']} 组还缺、{counts['unknown']} 组不确定。")
    if plan.coverage == "partial":
        st.caption("这个方案只记录了部分规则；上述统计不是个人学位或注册审核。")
    st.text("\n".join(_tree_lines(result.root)))
    if result.unplaced:
        st.text("方案里没有写到：" + "、".join(result.unplaced))
        st.caption("方案里没有写到这门课；不代表不能算，也不代表能算，请向项目核实。")
