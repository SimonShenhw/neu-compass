"""Streamlit session-state SOP (PLAN §7.6 / v2.0 §4.1).

Streamlit session-state 标准操作规程（PLAN §7.6 / v2.0 §4.1）。

st.session_state is a per-tab dict-like that survives Streamlit reruns.
Mutating it from many call sites makes state hard to reason about — this
module is the single entry point that initializes / reads / writes it.
Page modules call init_state(st.session_state) once at the top of render().

st.session_state 是一个按标签页隔离、能扛过 Streamlit rerun 的类字典
对象。在很多调用点各自修改它会让状态变得难以推理 —— 本模块是初始化 /
读取 / 写入它的唯一入口。各页面模块在 render() 顶部调用一次
init_state(st.session_state)。

Why a flat key namespace (user_id, user_email) instead of nested
(user={"id":..., "email":...}): Streamlit's diff-based rerun behavior
fires on the top-level key, so flat keys give finer-grained reactivity.
Nested dicts force callers to mutate-in-place, which is easy to get wrong.

为什么用扁平的键命名空间（user_id、user_email）而不是嵌套结构
（user={"id":..., "email":...}）：Streamlit 基于 diff 的 rerun 行为按
顶层键触发，扁平键能带来更细粒度的响应性。嵌套字典则会强迫调用方
原地修改（mutate-in-place），很容易出错。

The functions here are pure given a state mapping — no Streamlit imports —
so unit tests pass an ordinary dict() in.

本模块中的函数在给定 state 映射后都是纯函数 —— 不导入 Streamlit ——
因此单元测试可以直接传一个普通的 dict() 进来。
"""

from __future__ import annotations

from typing import Any, MutableMapping

# Mapping abstraction: production gets st.session_state, tests get dict().
SessionState = MutableMapping[str, Any]
MAX_COMPARE_COURSES = 4

DEFAULTS: dict[str, Any] = {
    # Auth
    # 中文:认证
    "user_id": None,
    "user_email": None,
    "user_contribution_count": 0,
    "session_token": None,   # ADR-0021 signed bearer credential / 签名的 bearer 凭证
    # Conversation (chat)
    # 中文:对话（聊天）
    "messages": [],          # [{"role", "content", "evidence", "matched_via"}]
    # Last search context (drives course detail panel)
    # 中文:最近一次搜索上下文（驱动课程详情面板）
    "last_query": None,
    "search_results": [],
    "search_k": 10,
    "filters": {},
    "selected_course_id": None,
    "compare_course_ids": [],
}


def init_state(state: SessionState) -> None:
    """Idempotent — safe to call at the top of every page render.
    幂等 —— 可以放心地在每次页面渲染的最前面调用。"""
    for k, default in DEFAULTS.items():
        if k in state:
            continue
        if isinstance(default, list):
            state[k] = list(default)
        elif isinstance(default, dict):
            state[k] = dict(default)
        else:
            state[k] = default


# === Auth ===
# 中文:认证


def is_logged_in(state: SessionState) -> bool:
    return bool(state.get("user_id"))


def valid_identity(identity: object) -> bool:
    """True when an /auth success body has the shape login() needs.

    Check before changing any session or cookie state: a malformed success is a failure, not a
    KeyError/TypeError or a partial login. Used by the OAuth callback and the cookie restore.
    中文：/auth 成功响应是否具备 login() 需要的形状。更新会话或 cookie 前先校验：畸形的成功响应
    算失败，不能变成 KeyError／TypeError 或半登录状态。OAuth 回调和 cookie 恢复共用。
    """
    return (isinstance(identity, dict)
        and isinstance(identity.get("user_id"), str) and bool(identity["user_id"])
        and isinstance(identity.get("email"), str) and bool(identity["email"])
        and type(identity.get("contribution_count", 0)) is int
        and identity.get("contribution_count", 0) >= 0
        and (identity.get("session_token") is None or isinstance(identity["session_token"], str))
        and (identity.get("display_name") is None or isinstance(identity["display_name"], str)))


def login(
    state: SessionState,
    *,
    user_id: str,
    user_email: str,
    contribution_count: int = 0,
    session_token: str | None = None,
) -> None:
    state["user_id"] = user_id
    state["user_email"] = user_email
    state["user_contribution_count"] = contribution_count
    state["session_token"] = session_token


def logout(state: SessionState) -> None:
    """Clear identity + conversation + the Co-op teaser fetched for this
    account (app.view_cache.COOP_TEASER_KEY: the API redacts it by tier; the
    view cache also never serves it to another scope). Search filters keep —
    nothing private in them, and the user shouldn't have to retype after
    logout/login.

    清空身份 + 对话 + 替这个账号获取的 Co-op 预览（app.view_cache.COOP_TEASER_KEY：
    API 按等级裁剪它；页面缓存本身也绝不会把它给另一个范围用）。搜索过滤器
    保留 —— 里面没有任何隐私信息，用户也不该在登出/登录之后还要重新输入一遍。"""
    state["user_id"] = None
    state["user_email"] = None
    state["user_display_name"] = None
    state["user_contribution_count"] = 0
    state["session_token"] = None
    state["messages"] = []
    state["search_results"] = []
    state["selected_course_id"] = None
    clear_compare(state)
    for key in ['last_chat_feedback','last_chat_meta','last_chat_error','answer_feedback_capture_opt_in',
                '_coop_teaser_cache']:
        state.pop(key, None)


# === Conversation ===
# 中文:对话


def add_message(
    state: SessionState,
    *,
    role: str,
    content: str,
    evidence: list[dict] | None = None,
    matched_via: str | None = None,
    feedback: dict | None = None,
    notices: list[str] | None = None,
    plan_context: dict | None = None,
) -> None:
    if role not in {"user", "assistant"}:
        raise ValueError(f"role must be 'user' or 'assistant', got {role!r}")
    state["messages"].append(
        {
            "role": role,
            "content": content,
            "evidence": evidence or [],
            "matched_via": matched_via,
        }
    )
    # Server retrieval notices (e.g. program_schedule_unverified) ride along
    # with the answer so the history re-render shows them too. Bounded plain
    # codes only; the view maps known codes to text and ignores the rest.
    # 中文：服务端检索提示码随回答一起存进历史，重渲染时同样显示。只存有界
    # 的纯代码；由视图把已知代码映射成文字，未知代码一律忽略。
    if role == "assistant" and notices:
        codes = [n for n in notices if isinstance(n, str) and 0 < len(n) <= 64][:10]
        if codes:
            state["messages"][-1]["notices"] = codes
    if role == 'assistant' and feedback is not None:
        from app.answer_feedback_view import bind_feedback_receipt
        target = bind_feedback_receipt(feedback, content)
        if target is not None:
            state['messages'][-1]['feedback'] = target
    if role == "assistant" and plan_context is not None:
        from app.chat_plan_view import validated_plan_context
        context = validated_plan_context(plan_context)
        if context is not None and set(context.placements) == {item["course_id"] for item in evidence or []}:
            state["messages"][-1]["plan_context"] = context.model_dump(mode="json")


def get_messages(state: SessionState) -> list[dict]:
    return state.get("messages", [])


def clear_conversation(state: SessionState) -> None:
    state["messages"] = []
    state["last_query"] = None
    state["search_results"] = []
    state["selected_course_id"] = None
    for key in ['last_chat_feedback','last_chat_meta','last_chat_error','answer_feedback_capture_opt_in']:
        state.pop(key, None)


# === Search context ===
# 中文:搜索上下文


def record_search(
    state: SessionState,
    *,
    query: str,
    results: list[dict],
    matched_via: str,
) -> None:
    state["last_query"] = query
    state["search_results"] = results
    if results:
        state["selected_course_id"] = results[0]["course_id"]


def select_course(state: SessionState, course_id: str | None) -> None:
    state["selected_course_id"] = course_id


def add_to_compare(state: SessionState, course_id: str) -> str:
    """Ordered per-tab IDs only; duplicates take precedence over a full list.
    中文：只保留标签页内有序 ID，不存详情；满额时已在列表的课仍返回 already。
    """
    ids = state.get("compare_course_ids", [])
    if course_id in ids:
        return "already"
    if len(ids) >= MAX_COMPARE_COURSES:
        return "full"
    state["compare_course_ids"] = [*ids, course_id]
    return "added"


def remove_from_compare(state: SessionState, course_id: str) -> None:
    state["compare_course_ids"] = [cid for cid in state.get("compare_course_ids", []) if cid != course_id]


def clear_compare(state: SessionState) -> None:
    state["compare_course_ids"] = []


__all__ = [
    "DEFAULTS",
    "MAX_COMPARE_COURSES",
    "SessionState",
    "add_to_compare",
    "add_message",
    "clear_compare",
    "clear_conversation",
    "get_messages",
    "init_state",
    "is_logged_in",
    "login",
    "logout",
    "record_search",
    "remove_from_compare",
    "select_course",
]
