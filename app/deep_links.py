"""Deep links: `?course=` / `?program=` in, copyable share URLs out.

深链：入口是 `?course=` / `?program=`，出口是可复制的分享 URL。

Why this exists (ADR-0028 ranked roadmap, "do before distributing"): a
student who finds something useful has no way to hand it to a classmate.
Everything in the app lives behind session_state, so the URL never changes
and "look at this course" degrades to "open the site, search CS 5800, no
the other one". Deep links are the organic-spread mechanism itself.

为什么需要它（ADR-0028 排序路线图中的「分发之前必须做」）：学生发现了有用
的东西，却没有办法把它递给同学。应用里的一切都活在 session_state 背后，
URL 从不变化，于是「你看看这门课」就退化成了「打开网站、搜 CS 5800、不是
那门、是另一门」。深链本身就是自发传播的机制。

Two halves, and both are required — a link nobody can produce cannot
spread:
  - CONSUME: `apply_deep_link(st, pages=...)`, called from the pre-radio
    block of streamlit_app.render().
  - PRODUCE: `share_url(...)` + `course_share_ref(...)`, rendered as a
    copyable box in the course detail panel and the curriculum view.

两半缺一不可 —— 一条没人能生产出来的链接是传播不起来的：
  - 消费：`apply_deep_link(st, pages=...)`，由 streamlit_app.render() 中
    radio 之前的那个区块调用。
  - 生产：`share_url(...)` + `course_share_ref(...)`，在课程详情面板和
    课程表视图里渲染成一个可复制的框。

Ordering constraints inside render() — both are load-bearing:
  1. AFTER `handle_oauth_callback()`. That function calls
     `st.query_params.clear()` when it handles an OAuth return, so a
     deep-link read placed before it would see params on a normal visit
     and an empty dict on an OAuth return.
  2. BEFORE `st.sidebar.radio(..., key="nav_page")`. We route by writing
     `nav_page`, and writing a widget-bound key after its widget rendered
     raises StreamlitAPIException (same rule as the pending_nav flags and
     the filter-clear callback).

render() 内部的两条顺序约束，都不是可有可无的：
  1. 必须在 `handle_oauth_callback()` 之后。该函数处理 OAuth 回调时会
     调用 `st.query_params.clear()`，所以放在它前面读深链，正常访问时能读到
     参数、而 OAuth 返回时会读到空字典。
  2. 必须在 `st.sidebar.radio(..., key="nav_page")` 之前。我们靠写
     `nav_page` 来路由，而组件渲染后再写它绑定的 key 会抛
     StreamlitAPIException（与 pending_nav 标志、filter-clear 回调同一条
     规则）。

Deliberate non-goal: the URL is NOT rewritten as the user navigates.
Assigning to `st.query_params` triggers a rerun, and a state→URL sync loop
is one missed equality check away from an infinite rerun. The explicit
share box gets the same link into the user's clipboard with none of that
risk. The incoming param is left in place (not cleared) so the address bar
stays shareable and a refresh reproduces the view — re-application is
blocked by a session flag, not by mutating the URL.

刻意不做的事：用户导航时不回写 URL。给 `st.query_params` 赋值会触发 rerun，
而 state→URL 的同步回路只要漏掉一次相等判断就会变成无限 rerun。显式的分享
框能把同一条链接送进用户剪贴板，且完全没有这个风险。传入的参数保持原样
（不清除），这样地址栏始终可分享、刷新也能复现同一视图 —— 阻止重复应用靠
的是一个会话标志，而不是改写 URL。
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

COURSE_PARAM = "course"
PROGRAM_PARAM = "program"

# One-shot guard. Underscore prefix = transient session bookkeeping, not
# user state (same convention as _programs_cache / _curriculum_cache).
# 中文：一次性守卫。下划线前缀 = 临时会话记账，而非用户状态（与
# _programs_cache / _curriculum_cache 同一套约定）。
APPLIED_FLAG = "_deep_link_applied"

_WHITESPACE_RE = re.compile(r"\s+")


# === Produce ===
# 中文：生产


def course_share_ref(primary_code: str) -> str:
    """'CS 5800' → 'CS-5800'. Dashes over %20 / '+' because the result is
    meant to be READ in a chat message, not just clicked.
    'CS 5800' → 'CS-5800'。用连字符而不是 %20 或 '+'，因为这串东西是要在
    聊天消息里被人读到的，不只是被点击。"""
    return _WHITESPACE_RE.sub("-", primary_code.strip())


def share_url(
    base_url: str,
    *,
    course: str | None = None,
    program: str | None = None,
    plan=None,
) -> str:
    """Build a copyable deep link onto the public UI origin.

    Percent-encoding is left to urlencode; a ref that survives it unchanged
    (the common 'CS-5800' case) stays human-readable, and one that doesn't
    (a slang alias with CJK) still round-trips correctly.

    拼出一条指向公网 UI 地址的可复制深链。

    百分号编码交给 urlencode 处理；能原样通过的 ref（常见的 'CS-5800'）保持
    人类可读，通不过的（含中日韩字符的俗称别名）也依然能正确往返。
    """
    if plan is not None:
        from app.program_plan_links import PlanLink
        target = PlanLink.from_plan(plan)
        if course is not None or (program is not None and program != target.program_id):
            raise ValueError('Plan link cannot share a conflicting destination')
        params = target.query_pairs()
    else:
        params = [(k, v) for k, v in ((COURSE_PARAM, course), (PROGRAM_PARAM, program)) if v]
    # rstrip, not "strip one slash": PUBLIC_BASE_URL is hand-edited, and a
    # stray 'https://x.dev//' must not become a protocol-relative '//?...'.
    # 中文：用 rstrip 而不是「去掉一个斜杠」：PUBLIC_BASE_URL 是手工填的，
    # 多打一个斜杠的 'https://x.dev//' 不能变成协议相对的 '//?...'。
    root = base_url.rstrip("/")
    if not params:
        return f"{root}/"
    return f"{root}/?{urlencode(params)}"


# === Consume (pure part — no Streamlit) ===
# 中文：消费（纯逻辑部分 —— 不碰 Streamlit）


def match_program_ref(ref: str, programs: list[dict]) -> str | None:
    """Match a `?program=` ref against the cached GET /programs list.

    Accepts the canonical program_id ('cs-ms') or the prefix ('CS'), both
    case-insensitively. Programs need no resolve endpoint of their own —
    the UI already holds the full list per tab, so this is a local scan.

    An ambiguous PREFIX resolves to nothing rather than to an arbitrary
    winner: two programs sharing a prefix is a data shape we don't have
    today but shouldn't silently guess at if we ever do.

    中文：把 `?program=` 的 ref 与缓存的 GET /programs 列表做匹配。

    接受规范的 program_id（'cs-ms'）或前缀（'CS'），两者都大小写不敏感。
    培养方案不需要自己的 resolve 端点 —— UI 每个标签页本来就持有完整列表，
    所以这里只是一次本地扫描。

    有歧义的前缀会解析为 None，而不是随便挑一个赢家：两个培养方案共用前缀
    是我们今天没有的数据形态，但真出现了也不该悄悄猜。
    """
    needle = (ref or "").strip().lower()
    if not needle:
        return None

    for p in programs:
        if str(p.get("program_id", "")).lower() == needle:
            return str(p["program_id"])

    by_prefix = [
        str(p["program_id"])
        for p in programs
        if str(p.get("prefix", "")).lower() == needle and p.get("program_id")
    ]
    return by_prefix[0] if len(by_prefix) == 1 else None


# === Consume (Streamlit side) ===
# 中文：消费（Streamlit 那一侧）


def apply_deep_link(st, *, pages: list[str]) -> None:
    """Legacy refs once per session; exact plan links once per query token.

    No-op when neither param is present, or when this session already
    applied one. Both params together are legal: the program is teed up in
    the Programs page and the (more specific) course wins the landing page.

    Transient API failures do NOT burn the one-shot flag — the ref is
    retried on the next rerun, mirroring the "failures are not cached so a
    warming API recovers" rule in program_view's fetch helpers.

    中文：每个会话消费一次 `?course=` / `?program=`，然后路由过去。

    两个参数都不存在、或本会话已经应用过时，什么也不做。两个参数同时出现是
    合法的：培养方案会在 Programs 页面里备好，而更具体的课程赢得落地页。

    临时性的 API 失败不会烧掉这个一次性标志 —— 下一次 rerun 会重试该 ref，
    与 program_view 抓取辅助函数里「失败不缓存，好让预热中的 API 能恢复」
    这条规则保持一致。
    """
    from app.program_plan_links import has_plan_link
    if has_plan_link(st.query_params):
        _apply_plan_ref(st, pages=pages)
        return
    if st.session_state.get(APPLIED_FLAG):
        return

    course_ref = _read_param(st, COURSE_PARAM)
    program_ref = _read_param(st, PROGRAM_PARAM)
    if not course_ref and not program_ref:
        return

    settled = True
    if program_ref:
        settled &= _apply_program_ref(st, program_ref, pages=pages)
    if course_ref:
        settled &= _apply_course_ref(st, course_ref, pages=pages)
    if settled:
        st.session_state[APPLIED_FLAG] = True


def _apply_plan_ref(st, *, pages: list[str]) -> None:
    from app.api_client import ApiClient, ApiError
    from app.program_plan_links import (APPLIED_KEY, PENDING_KEY, MESSAGES,
        clear_plan_link_selection, plan_query_token, read_plan_link, resolve_plan_link)

    token = plan_query_token(st.query_params)
    if st.session_state.get(APPLIED_KEY) == token:
        return
    # This runs before nav/plan widgets; never retain another link's selection.
    clear_plan_link_selection(st.session_state)
    st.session_state['nav_page'] = pages[1]
    try:
        target = read_plan_link(st.query_params)
    except ValueError:
        st.warning(MESSAGES['invalid'])
    else:
        st.session_state.pop(f'program-plan-{target.program_id}', None)
        cache = st.session_state.get('_curriculum_cache')
        if not isinstance(cache, dict):
            cache = {}
            st.session_state['_curriculum_cache'] = cache
        cache.pop(target.program_id, None)
        try:
            # Fresh GET, not the session curriculum cache: pin current revision.
            with ApiClient(session_token=st.session_state.get('session_token'), timeout=8.0) as api:
                body = api.get_program_curriculum(target.program_id)
        except ApiError as exc:
            if exc.status_code in {408, 429} or exc.status_code >= 500:
                st.warning('🔗 方案链接暂时无法核对，稍后重试；未保留旧方案选择。')
                return
            st.warning(MESSAGES['unavailable'])
        except ValueError:
            st.warning(MESSAGES['unusable'])
        else:
            status, plan = resolve_plan_link(target, body)
            if plan is None:
                st.warning(MESSAGES[status])
            else:
                cache[target.program_id] = body
                st.session_state['selected_program_id'] = target.program_id
                st.session_state[PENDING_KEY] = target.model_dump(mode='json')
    st.session_state[APPLIED_KEY] = token
    st.session_state[APPLIED_FLAG] = True


def _ref_label(ref: str) -> str:
    """The ref is user-controlled and we echo it back inside a markdown code
    span. Streamlit blocks raw HTML, but a backtick would close the span and
    let a crafted link render arbitrary markdown (`[点这里](https://evil)`)
    inside our own warning — a phishing surface on a URL anyone can forge.
    Strip the delimiter and cap the length.

    中文：ref 由用户控制，而我们要把它回显进一个 markdown 代码段里。
    Streamlit 会拦掉裸 HTML，但一个反引号就能闭合代码段，让精心构造的链接
    在我们自己的警告框里渲染出任意 markdown（`[点这里](https://evil)`）——
    这是一个任何人都能伪造 URL 的钓鱼面。去掉分隔符并限制长度。"""
    return ref.replace("`", "")[:64]


def _read_param(st, name: str) -> str:
    """One query param as a stripped str ('' when absent). st.query_params
    yields the LAST value for a repeated key, which is the behavior we want
    for a hand-edited URL.
    中文：把一个查询参数读成去空白的字符串（不存在时为 ''）。重复键时
    st.query_params 返回最后一个值，这正是手工编辑过的 URL 想要的行为。"""
    try:
        raw = st.query_params.get(name)
    except Exception:  # st.query_params unavailable (bare script run)
        # 中文：st.query_params 不可用（裸脚本运行）
        return ""
    return str(raw).strip() if raw else ""


def _apply_program_ref(st, ref: str, *, pages: list[str]) -> bool:
    """Route to the Programs page. Returns False on a transient API failure
    so the caller retries next rerun.
    中文：路由到培养方案页面。临时性 API 失败时返回 False，让调用方在下一次
    rerun 重试。"""
    from app.api_client import ApiError  # noqa: PLC0415
    from app.program_view import get_programs_cached  # noqa: PLC0415

    try:
        programs = get_programs_cached(st)
    except ApiError as e:
        st.warning(f"🔗 链接里的培养方案暂时打不开（API {e.status_code}），稍后重试。")
        return False

    program_id = match_program_ref(ref, programs)
    if program_id is None:
        st.warning(
            f"🔗 链接指向的培养方案 `{_ref_label(ref)}` 不存在 — 已打开完整列表。"
        )
        return True

    st.session_state["selected_program_id"] = program_id
    st.session_state["nav_page"] = pages[1]
    return True


def _apply_course_ref(st, ref: str, *, pages: list[str]) -> bool:
    """Resolve the ref via GET /resolve/course and open that course's detail
    panel. Returns False on a transient API failure.
    中文：通过 GET /resolve/course 解析该 ref，并打开对应课程的详情面板。
    临时性 API 失败时返回 False。"""
    from app.api_client import ApiClient, ApiError  # noqa: PLC0415

    try:
        with ApiClient(
            session_token=st.session_state.get("session_token"), timeout=8.0,
        ) as api:
            body = api.resolve_course(ref)
    except ApiError as e:
        st.warning(f"🔗 链接里的课程暂时打不开（API {e.status_code}），稍后重试。")
        return False

    matches = body.get("matches") or []
    if not matches:
        st.warning(
            f"🔗 链接指向的课程 `{_ref_label(ref)}` 没找到 — "
            "可能已停开，或链接被截断了。"
        )
        return True

    st.session_state["selected_course_id"] = matches[0]["course_id"]
    st.session_state["nav_page"] = pages[0]
    if len(matches) > 1:
        others = "、".join(m["primary_code"] for m in matches[1:4])
        st.info(
            f"🔗 `{_ref_label(ref)}` 对应多门课程，已打开 "
            f"**{matches[0]['primary_code']}**；其他：{others}"
        )
    return True


__all__ = [
    "APPLIED_FLAG",
    "COURSE_PARAM",
    "PROGRAM_PARAM",
    "apply_deep_link",
    "course_share_ref",
    "match_program_ref",
    "share_url",
]
