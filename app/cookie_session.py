"""Browser-cookie session persistence for the Streamlit UI.

为 Streamlit UI 提供浏览器 cookie 会话持久化。

Streamlit's session_state dies with the browser tab — before this module,
every refresh of compass.neu-compass.me logged the user out, the #1
retention killer flagged before first real-user distribution.

Streamlit 的 session_state 会随浏览器标签页关闭而消失 —— 在本模块出现之前，
每次刷新 compass.neu-compass.me 都会让用户掉线，这是首次真实用户分发前
被标记出的头号留存杀手。

Mechanics: Streamlit can READ request cookies (st.context.cookies) but has
no API to WRITE them, so writes go through a zero-height components.html
iframe running document.cookie against the parent document (srcdoc iframes
share the parent origin). Restore path on page load:

    cookie present + not logged in
        → GET /auth/me with the cookie token
        → state_manager.login(...)

机制：Streamlit 能读取请求 cookie（st.context.cookies），但没有写入它们的
API，因此写入要经过一个零高度的 components.html iframe，在其中对父文档
执行 document.cookie（srcdoc iframe 与父文档共享 origin）。页面加载时的
恢复路径：

    cookie 存在 + 尚未登录
        → 用该 cookie token 调用 GET /auth/me
        → state_manager.login(...)

The API re-verifies the itsdangerous signature + max_age on every /auth/me
call, so a stale or tampered cookie degrades to anonymous (and the cookie
gets cleared) — never a forged identity.

API 在每次 /auth/me 调用时都会重新校验 itsdangerous 签名 + max_age，因此
过期或被篡改的 cookie 只会降级为匿名（同时该 cookie 会被清除）—— 绝不会
伪造出一个身份。

Module layout mirrors ui_theme / state_manager: pure string builders and
state-dict logic (testable without Streamlit) + thin glue functions with
lazy streamlit imports at the bottom.

模块结构与 ui_theme / state_manager 一致：纯字符串构造函数 + 状态字典逻辑
（无需 Streamlit 即可测试），底部再加一层带惰性 streamlit 导入的薄胶水函数。
"""

from __future__ import annotations

import hmac
import json
from typing import Any, Callable, MutableMapping

SessionState = MutableMapping[str, Any]

COOKIE_NAME = "nc_session"
OAUTH_STATE_COOKIE = "nc_oauth_state"
OAUTH_STATE_MAX_AGE = 600  # seconds to complete the Google round-trip / 完成 Google 往返所需秒数

_PENDING_KEY = "_pending_cookie"
_RESTORE_DONE_KEY = "_cookie_restore_done"


# === Pure builders ===


def _write_cookie_js(name: str, value: str, max_age_seconds: int) -> str:
    """JS snippet that writes one cookie.

    Writes via window.parent.document so the cookie lands on the app's
    host even if the component iframe ever stops inheriting the parent
    origin; falls back to the local document. `Secure` is added only on
    https so the dev preview (http://localhost) doesn't silently drop the
    cookie. json.dumps escapes the value defensively — it's URL-safe
    base64 today, but a quote in a future format must not break out of
    the JS string.

    写入一个 cookie 的 JS 代码片段。通过 window.parent.document 写入，
    这样即使组件 iframe 某天不再继承父文档的 origin，cookie 依然落在
    app 所在的 host 上；写不到时退回本地 document。仅在 https 下才附加
    `Secure`，避免本地预览（http://localhost）悄悄丢失 cookie。
    json.dumps 对取值做防御性转义 —— 现在是 URL-safe base64，但以后
    格式里若出现引号，也绝不能让它跳出 JS 字符串。
    """
    return (
        "<script>\n"
        "(function () {\n"
        "  var doc = document;\n"
        "  try { if (window.parent && window.parent.document) "
        "{ doc = window.parent.document; } } catch (e) {}\n"
        "  var secure = '';\n"
        "  try { if ((doc.location || window.location).protocol === 'https:')"
        " { secure = '; Secure'; } } catch (e) {}\n"
        f"  doc.cookie = {json.dumps(name)} + '=' + "
        f"{json.dumps(value)} + '; path=/; max-age={int(max_age_seconds)}"
        "; SameSite=Lax' + secure;\n"
        "})();\n"
        "</script>"
    )


def _clear_cookie_js(name: str) -> str:
    """JS snippet that deletes one cookie (max-age=0).
    删除一个 cookie 的 JS 代码片段（max-age=0）。"""
    return (
        "<script>\n"
        "(function () {\n"
        "  var doc = document;\n"
        "  try { if (window.parent && window.parent.document) "
        "{ doc = window.parent.document; } } catch (e) {}\n"
        f"  doc.cookie = {json.dumps(name)} + "
        "'=; path=/; max-age=0; SameSite=Lax';\n"
        "})();\n"
        "</script>"
    )


def set_cookie_js(token: str, max_age_seconds: int) -> str:
    """JS snippet that persists the session token as a cookie.
    把会话 token 持久化为 cookie 的 JS 代码片段。"""
    return _write_cookie_js(COOKIE_NAME, token, max_age_seconds)


def clear_cookie_js() -> str:
    """JS snippet that deletes the session cookie.
    删除会话 cookie 的 JS 代码片段。"""
    return _clear_cookie_js(COOKIE_NAME)


def oauth_state_cookie_js(state: str) -> str:
    """Short-lived CSRF-state cookie for the OAuth round-trip.

    Why a cookie and not st.session_state: navigating to Google reloads
    the page on return, which builds a FRESH Streamlit session —
    session_state can never survive to the callback (the original
    ADR-0021 in-session check failed 100% of real logins). The cookie
    rides the browser across the redirect, and also covers a login link
    opened in a new tab.

    用于 OAuth 往返的短生命周期 CSRF-state cookie。为什么用 cookie 而不是
    st.session_state：跳转到 Google 再返回时会重新加载页面，从而生成一个
    全新的 Streamlit 会话 —— session_state 永远撑不到回调那一刻（最初
    ADR-0021 的同会话检查曾让 100% 的真实登录失败）。cookie 能跟着浏览器
    穿过整个重定向，也覆盖了登录链接在新标签页打开的情形。
    """
    return _write_cookie_js(OAUTH_STATE_COOKIE, state, OAUTH_STATE_MAX_AGE)


def oauth_state_matches(expected: str | None, returned: str | None) -> bool:
    """CSRF check: both present and equal (constant-time compare).
    CSRF 校验：两者都存在且相等（常数时间比较）。"""
    if not expected or not returned:
        return False
    return hmac.compare_digest(str(expected), str(returned))


# === State-machine (pure dict ops) ===
# 中文:状态机（纯字典操作）
#
# Why queue-then-flush instead of rendering the JS inline at the call site:
# both login (OAuth callback) and logout immediately st.rerun(), which can
# tear down the current render before the browser executes the component
# iframe. The queue survives the rerun in session_state; flush runs early
# in the NEXT render, which completes normally.
#
# 中文:为什么用"先排队、后统一 flush"而不是在调用处直接内联渲染 JS：
# 登录（OAuth 回调）和登出都会立刻 st.rerun()，这可能在浏览器执行组件
# iframe 之前就把当前这次渲染撕毁。队列在 session_state 中能挺过 rerun；
# flush 在下一次渲染的早期运行，那一次能正常跑完。
#
# The queue is a LIST of ops (a successful OAuth callback needs two:
# clear the state cookie + set the session cookie). Ops on the same
# cookie execute in call order, so the last one wins in the browser.
#
# 中文:队列是一个操作列表（一次成功的 OAuth 回调需要两个操作：清掉
# state cookie + 设置 session cookie）。同一个 cookie 上的多个操作按
# 调用顺序执行，浏览器里最终生效的是最后一个。


def _queue(
    state: SessionState,
    action: str,
    name: str,
    value: str | None = None,
    max_age: int | None = None,
) -> None:
    pending = state.get(_PENDING_KEY)
    if not isinstance(pending, list):
        pending = []
        state[_PENDING_KEY] = pending
    pending.append((action, name, value, max_age))


def queue_cookie_write(state: SessionState, token: str | None) -> None:
    if token:
        # max_age None = resolved from settings at flush time.
        # 中文:max_age 为 None 表示在 flush 时才从 settings 里解析。
        _queue(state, "set", COOKIE_NAME, token, None)


def queue_cookie_clear(state: SessionState) -> None:
    _queue(state, "clear", COOKIE_NAME)


def queue_oauth_state_clear(state: SessionState) -> None:
    """Drop the CSRF-state cookie once the callback consumed it.
    回调消费完 CSRF-state cookie 后，将其丢弃。"""
    _queue(state, "clear", OAUTH_STATE_COOKIE)


def pop_pending_cookie_html(
    state: SessionState, max_age_seconds: int,
) -> str | None:
    """Return the queued cookie JS (and consume the queue), or None.
    返回排队中的 cookie JS（同时消费掉队列），没有则返回 None。"""
    pending = state.pop(_PENDING_KEY, None)
    if not pending:
        return None
    parts: list[str] = []
    for action, name, value, max_age in pending:
        if action == "set" and value:
            parts.append(
                _write_cookie_js(
                    name, value,
                    max_age if max_age is not None else max_age_seconds,
                )
            )
        elif action == "clear":
            parts.append(_clear_cookie_js(name))
    return "".join(parts) or None


def restore_login(
    state: SessionState,
    cookie_token: str | None,
    fetch_me: Callable[[str], dict[str, Any]],
) -> bool:
    """Attempt cookie → login restore. At most once per browser tab.

    The once-guard is set BEFORE any other check on purpose: st.context
    .cookies reflects the page-load request, not live JS state, so after a
    logout in this tab the stale cookie is still visible there — without
    the guard the very next rerun would silently log the user back in.

    fetch_me raising ApiError(401) means the cookie is stale/invalid → a
    clear is queued so the browser drops it. Any other failure (API down,
    timeout) leaves the cookie alone; a later full page reload retries.

    尝试"cookie → 恢复登录"。每个浏览器标签页最多执行一次。

    这个只执行一次的标志特意设在其他任何检查之前：st.context.cookies
    反映的是页面加载那一刻的请求，而非实时 JS 状态，所以本标签页登出后，
    过期的 cookie 在这里依然可见 —— 没有这个标志，下一次 rerun 就会
    悄悄把用户重新登录回去。

    fetch_me 抛出 ApiError(401) 意味着 cookie 已过期/无效 → 排队一次
    清除操作，让浏览器丢弃它。其他任何失败（API 挂了、超时）都不动
    这个 cookie；之后一次完整的页面刷新会重试。
    """
    from app.api_client import ApiError  # noqa: PLC0415
    from app.state_manager import is_logged_in, login  # noqa: PLC0415

    if state.get(_RESTORE_DONE_KEY):
        return False
    state[_RESTORE_DONE_KEY] = True
    if is_logged_in(state) or not cookie_token:
        return False

    try:
        me = fetch_me(cookie_token)
    except ApiError as e:
        if e.status_code == 401:
            queue_cookie_clear(state)
        return False

    login(
        state,
        user_id=me["user_id"],
        user_email=me["email"],
        contribution_count=me.get("contribution_count", 0),
        session_token=cookie_token,
    )
    if me.get("display_name"):
        state["user_display_name"] = me["display_name"]
    return True


# === Streamlit glue (lazy imports, no logic) ===
# 中文:Streamlit 胶水层（惰性导入，不含业务逻辑）


def flush_pending_cookie() -> None:
    """Render any queued cookie write/clear. Call once per render, early,
    at a point reached on EVERY rerun.
    渲染所有排队中的 cookie 写入/清除。每次渲染调用一次，且要在早期、
    每次 rerun 都必经的位置调用。"""
    import streamlit as st  # noqa: PLC0415
    import streamlit.components.v1 as components  # noqa: PLC0415

    from config import settings  # noqa: PLC0415

    html = pop_pending_cookie_html(
        st.session_state, settings.session_max_age_seconds,
    )
    if html:
        components.html(html, height=0)


def restore_login_from_cookie() -> bool:
    """Page-load restore: st.context cookie → /auth/me → login state.
    页面加载时的恢复：st.context cookie → /auth/me → 登录状态。"""
    import streamlit as st  # noqa: PLC0415

    from app.api_client import ApiClient  # noqa: PLC0415

    try:
        cookie_token = st.context.cookies.get(COOKIE_NAME)
    except Exception:  # st.context unavailable (e.g. bare script run)
        # 中文:st.context 不可用（例如裸脚本运行）
        cookie_token = None

    def fetch_me(token: str) -> dict[str, Any]:
        with ApiClient(session_token=token) as api:
            return api.auth_me()

    restored = restore_login(st.session_state, cookie_token, fetch_me)
    if restored:
        # A restore changes what the sidebar/hero should show this render;
        # rerun so the whole page renders logged-in from the top.
        # 中文:恢复登录会改变本次渲染中侧边栏/hero 应显示的内容；
        # 重新运行以便整页从头以已登录状态渲染。
        st.rerun()
    return restored


__all__ = [
    "COOKIE_NAME",
    "OAUTH_STATE_COOKIE",
    "OAUTH_STATE_MAX_AGE",
    "clear_cookie_js",
    "flush_pending_cookie",
    "oauth_state_cookie_js",
    "oauth_state_matches",
    "pop_pending_cookie_html",
    "queue_cookie_clear",
    "queue_cookie_write",
    "queue_oauth_state_clear",
    "restore_login",
    "restore_login_from_cookie",
    "set_cookie_js",
]
