"""Streamlit-side auth UI helpers — login button + OAuth callback + sidebar.

Streamlit 侧的认证 UI 辅助函数 —— 登录按钮 + OAuth 回调 + 侧边栏。

Streamlit imports are lazy so this module loads cleanly outside Streamlit
(tests can `import` it without spinning up the runtime).

Streamlit 的导入都是惰性的，所以本模块在 Streamlit 环境之外也能干净加载
（测试可以直接 `import` 它，而不必启动运行时）。

Two entry points page modules call:
  - `handle_oauth_callback()` — at the top of render(), processes ?code=
  - `render_auth_sidebar()`   — anywhere in render(), draws the sidebar

页面模块会调用的两个入口点：
  - `handle_oauth_callback()` —— 位于 render() 顶部，处理 ?code=
  - `render_auth_sidebar()`   —— render() 中任意位置调用，绘制侧边栏
"""

from __future__ import annotations


def handle_oauth_callback() -> None:
    """If `?code=` is present in the URL, exchange it via /auth/callback,
    persist the user, and clear the query string so a refresh doesn't
    retry. No-op when no code is present.

    Failures (bad domain, expired code, network) surface via st.error and
    leave the user logged out.

    若 URL 中存在 `?code=`，就通过 /auth/callback 兑换它、持久化用户身份，
    并清空查询字符串以免刷新时重试。没有 code 时什么也不做。

    失败情形（域名不合法、code 过期、网络问题）通过 st.error 呈现，并让
    用户保持登出状态。
    """
    import streamlit as st  # noqa: PLC0415

    from app.api_client import ApiClient, ApiError  # noqa: PLC0415
    from app.cookie_session import (  # noqa: PLC0415
        OAUTH_STATE_COOKIE,
        oauth_state_matches,
        queue_cookie_write,
        queue_oauth_state_clear,
    )
    from app.state_manager import login  # noqa: PLC0415

    # Google's deny path redirects back with ?error=access_denied (no code).
    # Without this branch the params silently stuck around and the page
    # just looked logged-out with zero explanation.
    # 中文:Google 的拒绝路径会带着 ?error=access_denied（没有 code）跳回来。
    # 没有这个分支的话，参数会悄悄滞留，页面只是看起来"登出"，没有任何解释。
    oauth_error = st.query_params.get("error")
    code = st.query_params.get("code")
    if oauth_error and not code:
        st.warning(
            f"登录未完成（{oauth_error}）。可从左侧栏重新发起登录。"
        )
        st.query_params.clear()
        return
    if not code:
        return

    # CSRF (ADR-0021, reworked): the state we generated before redirecting
    # to Google must round-trip unchanged. The expected value lives in a
    # short-lived COOKIE, not session_state — the redirect back from
    # Google is a fresh page load with a fresh Streamlit session, so
    # session_state never survives to this point (the original in-session
    # check rejected 100% of real logins). The cookie rides the browser
    # across the redirect and also covers new-tab flows.
    # 中文(ADR-0021，重做过):跳到 Google 之前生成的 state，必须原样
    # 往返回来。期望值存在一个短生命周期的 COOKIE 里，而非 session_state
    # —— 从 Google 跳回来是一次全新的页面加载、全新的 Streamlit 会话，
    # session_state 根本撑不到这一步（最初的同会话检查曾拒绝 100% 的
    # 真实登录）。cookie 能跟着浏览器穿过整个重定向，也覆盖新标签页流程。
    try:
        expected_state = st.context.cookies.get(OAUTH_STATE_COOKIE)
    except Exception:  # st.context unavailable (bare script run)
        # 中文:st.context 不可用（裸脚本运行）
        expected_state = None
    returned_state = st.query_params.get("state")
    if not oauth_state_matches(expected_state, returned_state):
        st.error("Login flow state mismatch — please try signing in again.")
        st.query_params.clear()
        return
    # One-shot: drop the consumed state cookie on the next flush.
    # 中文:一次性操作:下一次 flush 时丢弃已消费掉的 state cookie。
    queue_oauth_state_clear(st.session_state)
    st.session_state.pop("oauth_state", None)

    try:
        with ApiClient() as api:
            identity = api.oauth_callback(code)
    except ApiError as e:
        st.error(f"Login failed: {e.detail}")
        st.query_params.clear()
        return

    login(
        st.session_state,
        user_id=identity["user_id"],
        user_email=identity["email"],
        contribution_count=identity.get("contribution_count", 0),
        session_token=identity.get("session_token"),
    )
    if identity.get("display_name"):
        st.session_state["user_display_name"] = identity["display_name"]

    # Persist the session across refreshes. Queued (not rendered inline)
    # because the st.rerun() below would tear down an inline component
    # before the browser executes it — cookie_session.flush_pending_cookie
    # renders it early in the next pass.
    # 中文:让会话在刷新后依然存活。这里用排队而非内联渲染，因为下面的
    # st.rerun() 会在浏览器执行内联组件之前就把它撕毁 ——
    # cookie_session.flush_pending_cookie 会在下一轮渲染早期把它渲染出来。
    queue_cookie_write(st.session_state, identity.get("session_token"))

    st.query_params.clear()
    st.rerun()


def render_auth_sidebar() -> None:
    """Sidebar block: login link OR logged-in info + logout button.
    侧边栏区块：登录链接 或 已登录信息 + 登出按钮。"""
    import streamlit as st  # noqa: PLC0415

    from app.auth import authorize_url  # noqa: PLC0415
    from app.cookie_session import queue_cookie_clear  # noqa: PLC0415
    from app.state_manager import is_logged_in, logout  # noqa: PLC0415

    with st.sidebar:
        if is_logged_in(st.session_state):
            email = st.session_state.get("user_email", "")
            display_name = st.session_state.get("user_display_name") or email
            st.markdown(f"**Signed in as**  \n`{display_name}`")
            st.caption(
                "Contributions: "
                f"{st.session_state.get('user_contribution_count', 0)}"
            )
            if st.button("Log out", use_container_width=True):
                queue_cookie_clear(st.session_state)
                logout(st.session_state)
                st.rerun()
        else:
            # CSRF state: stable per tab via session_state (so the link
            # doesn't churn every rerun), persisted to a short-lived cookie
            # so it survives the redirect to Google and back (see
            # handle_oauth_callback for why session_state alone cannot).
            # 中文:CSRF state：靠 session_state 做到每个标签页内稳定
            # （这样链接不会每次 rerun 都变），并持久化到一个短生命周期
            # 的 cookie，让它扛过跳转到 Google 再回来的过程（为什么单靠
            # session_state 不够，见 handle_oauth_callback）。
            import html as _html  # noqa: PLC0415
            import secrets  # noqa: PLC0415

            import streamlit.components.v1 as components  # noqa: PLC0415

            from app.cookie_session import (  # noqa: PLC0415
                OAUTH_STATE_COOKIE,
                oauth_state_cookie_js,
            )

            if not st.session_state.get("oauth_state"):
                # ADOPT an existing state cookie before minting a new one:
                # the cookie is shared browser-wide, so two logged-out tabs
                # each minting their own value would clobber each other —
                # whichever tab the user logs in from then fails the CSRF
                # check with the other tab's state.
                # 中文:铸造新 cookie 之前先"认领"已存在的 state cookie：
                # cookie 是浏览器全局共享的，两个登出标签页各自铸造自己的
                # 值会互相覆盖 —— 用户最终从哪个标签页登录，就会拿着
                # 另一个标签页的 state 去做 CSRF 校验，从而失败。
                try:
                    existing = st.context.cookies.get(OAUTH_STATE_COOKIE)
                except Exception:
                    existing = None
                st.session_state["oauth_state"] = (
                    existing or secrets.token_urlsafe(24)
                )
            state_token = st.session_state["oauth_state"]
            components.html(oauth_state_cookie_js(state_token), height=0)

            # Raw anchor with target=_self: Streamlit markdown links force
            # target=_blank, which sent users to Google in a NEW tab and
            # left the original tab looking logged-out. Same-tab round-trip
            # lands the ?code= callback right here.
            # 中文:原生 <a> 标签 + target=_self：Streamlit 的 markdown
            # 链接会强制 target=_blank，导致用户在新标签页跳去 Google，
            # 原标签页却仍看起来像登出状态。同标签页往返能让 ?code=
            # 回调直接落回这里。
            url = authorize_url(state_token=state_token)
            st.markdown(
                f'<a href="{_html.escape(url, quote=True)}" target="_self">'
                "🔐 Sign in with Google</a>",
                unsafe_allow_html=True,
            )
            st.caption("Restricted to husky.neu.edu / northeastern.edu.")


__all__ = ["handle_oauth_callback", "render_auth_sidebar"]
