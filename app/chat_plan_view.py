"""Explicit chat-plan choice and validated response evidence; no inferred applicability.
中文：选择与服务器返回的方案证据分开；旧消息没有该块时不改变布局。
"""

import hashlib
import json
from collections import Counter

from app.program_plan_links import PlanLink
from app.program_plan_view import PLAN_PLACEHOLDER, scope_label
from app.text_render import literal_markdown
from schemas.answer_evidence import PlanContext
from schemas.plan_selection import PLAN_SELECTOR_LABEL, PlanSelection
from schemas.program_plan import ProgramPlan

CHAT_PLAN_KEY = "chat_plan_id"


def selectable_chat_plans(documents, program_id):
    if not isinstance(documents, list) or len(documents) > 100:
        return []
    try:
        plans = [ProgramPlan.model_validate(item) for item in documents]
    except ValueError:
        return []
    ids = Counter(plan.plan_id for plan in plans)
    scopes = Counter(plan.scope_key() for plan in plans)
    return [plan for plan in plans if plan.program_id == program_id and plan.review_status == "source_checked"
            and ids[plan.plan_id] == scopes[plan.scope_key()] == 1]


def queue_chat_plan_reset(state):
    # A 409 arrives after the widget exists; only the next run may set its bound key.
    state["_chat_plan_reset_pending"] = True


def render_chat_plan_selector(st, program_id):
    from app.api_client import ApiError
    from app.program_view import get_curriculum_cached

    state = st.session_state
    changed_family = state.get("_chat_plan_family") != program_id
    pending = state.pop("_chat_plan_reset_pending", False)
    if changed_family or pending:
        state[CHAT_PLAN_KEY] = None
        state["_chat_plan_revision"] = None
    state["_chat_plan_family"] = program_id
    if program_id is None:
        return None
    try:
        body = get_curriculum_cached(st, program_id)
    except ApiError:
        state[CHAT_PLAN_KEY] = None
        st.caption("暂时无法核对方案列表；未携带方案，课程搜索仍可使用。")
        return None
    documents = body.get("plans", []) if isinstance(body, dict) and body.get("plan_schema_available") is True else []
    plans = selectable_chat_plans(documents, program_id)
    revision = hashlib.sha256(json.dumps(documents, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    previous = state.get("_chat_plan_revision")
    if previous is not None and previous != revision and state.get(CHAT_PLAN_KEY) is not None:
        state[CHAT_PLAN_KEY] = None
        st.caption("方案有更新，之前的方案版本选择已清除，请重新明确选择。")
    state["_chat_plan_revision"] = revision
    by_id = {plan.plan_id: plan for plan in plans}
    if state.get(CHAT_PLAN_KEY) not in {None, *by_id} or not by_id:
        state[CHAT_PLAN_KEY] = None
    if not by_id:
        return None
    chosen = st.selectbox(PLAN_SELECTOR_LABEL, [None, *by_id], key=CHAT_PLAN_KEY, placeholder=PLAN_PLACEHOLDER,
        format_func=lambda value: PLAN_PLACEHOLDER if value is None else scope_label(by_id[value]))
    if chosen is None or chosen not in by_id:
        return None
    st.caption("只按你选的方案解释规则；不判断你是否适用、能否注册或毕业。")
    return PlanSelection.model_validate(PlanLink.from_plan(by_id[chosen]).model_dump(exclude={"format_version"}))


def validated_plan_context(value):
    if not isinstance(value, dict):
        return None
    try:
        text = json.dumps(value, ensure_ascii=False)
        if len(text) > 1_000_000:
            return None
        return PlanContext.model_validate_json(text)
    except (ValueError, TypeError):
        return None


def render_plan_context(st, value, courses=None):
    context = validated_plan_context(value)
    if context is None:
        return
    by_id = {item.get("course_id"): item.get("primary_code") for item in courses or [] if isinstance(item, dict)}
    if courses is not None and set(context.placements) != set(by_id):
        return
    st.caption("本回答按方案：" + literal_markdown(f"{context.program_id} · {scope_label(context)}"))
    st.caption("这是明确选择的方案文档，不代表你的适用年度、注册或毕业资格；未列出课程不代表禁止，开放池仍需核实。")
    if context.coverage == "partial":
        st.caption("仅部分规则；未建模内容未知，条件没有自动判定，跨组重叠不代表可以重复计入。")
    labels = {"required": "方案列明的必修课程", "any_of_option": "OR 分支中的一个选项",
              "select_candidate": "组选候选，并非全部必修", "optional_branch": "仅适用于可选分支",
              "excluded": "本组选明确排除", "open_pool": "开放前缀／范围，不是匹配证明，仍需向项目核实"}
    for index, (course_id, entries) in enumerate(context.placements.items(), 1):
        code = by_id.get(course_id) or f"课程 {index}"
        if not entries:
            st.text(f"{code}：方案没有显式位置记录，不表示不允许或能计入。")
        for entry in entries:
            details = [labels[entry.relation], " > ".join(entry.path)]
            if entry.under_any_of:
                details.append("上层有 OR 分支，不是所有分支共同必修")
            details.extend(f"条件：{condition}" for condition in entry.activate_when)
            details.extend(f"至少 {getattr(entry, key)} {label}" for key, label in (
                ("min_courses", "门"), ("min_credits", "学分"), ("min_areas", "领域")) if getattr(entry, key) is not None)
            if entry.areas:
                details.append("所属领域：" + "、".join(entry.areas))
            st.text(f"{code}：" + "；".join(details))
        if context.placements_omitted[course_id]:
            st.text(f"另有 {context.placements_omitted[course_id]} 处位置未列出，请到培养方案页核对完整规则。")
    st.markdown(f"[方案官方目录来源]({context.source_url})")
    st.caption(f"来源 Catalog {context.source_catalog_year} · 摘录 {context.captured_on} · 对照 {context.checked_on}；非实时核验")
