"""Browser-cookie session persistence for the Streamlit UI.

Streamlit's session_state dies with the browser tab — before this module,
every refresh of compass.neu-compass.me logged the user out, the #1
retention killer flagged before first real-user distribution.

Mechanics: Streamlit can READ request cookies (st.context.cookies) but has
no API to WRITE them, so writes go through a zero-height components.html
iframe running document.cookie against the parent document (srcdoc iframes
share the parent origin). Restore path on page load:

    cookie present + not logged in
        → GET /auth/me with the cookie token
        → state_manager.login(...)

The API re-verifies the itsdangerous signature + max_age on every /auth/me
call, so a stale or tampered cookie degrades to anonymous (and the cookie
gets cleared) — never a forged identity.

Module layout mirrors ui_theme / state_manager: pure string builders and
state-dict logic (testable without Streamlit) + thin glue functions with
lazy streamlit imports at the bottom.
"""

from __future__ import annotations

import json
from typing import Any, Callable, MutableMapping

SessionState = MutableMapping[str, Any]

COOKIE_NAME = "nc_session"

_PENDING_KEY = "_pending_cookie"
_RESTORE_DONE_KEY = "_cookie_restore_done"


# === Pure builders ===


def set_cookie_js(token: str, max_age_seconds: int) -> str:
    """JS snippet that persists the session token as a cookie.

    Writes via window.parent.document so the cookie lands on the app's
    host even if the component iframe ever stops inheriting the parent
    origin; falls back to the local document. `Secure` is added only on
    https so the dev preview (http://localhost) doesn't silently drop the
    cookie. json.dumps escapes the token defensively — it's URL-safe
    base64 today, but a quote in a future format must not break out of
    the JS string.
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
        f"  doc.cookie = {json.dumps(COOKIE_NAME)} + '=' + "
        f"{json.dumps(token)} + '; path=/; max-age={int(max_age_seconds)}"
        "; SameSite=Lax' + secure;\n"
        "})();\n"
        "</script>"
    )


def clear_cookie_js() -> str:
    """JS snippet that deletes the session cookie (max-age=0)."""
    return (
        "<script>\n"
        "(function () {\n"
        "  var doc = document;\n"
        "  try { if (window.parent && window.parent.document) "
        "{ doc = window.parent.document; } } catch (e) {}\n"
        f"  doc.cookie = {json.dumps(COOKIE_NAME)} + "
        "'=; path=/; max-age=0; SameSite=Lax';\n"
        "})();\n"
        "</script>"
    )


# === State-machine (pure dict ops) ===
#
# Why queue-then-flush instead of rendering the JS inline at the call site:
# both login (OAuth callback) and logout immediately st.rerun(), which can
# tear down the current render before the browser executes the component
# iframe. The queue survives the rerun in session_state; flush runs early
# in the NEXT render, which completes normally.


def queue_cookie_write(state: SessionState, token: str | None) -> None:
    if token:
        state[_PENDING_KEY] = ("set", token)


def queue_cookie_clear(state: SessionState) -> None:
    state[_PENDING_KEY] = ("clear", None)


def pop_pending_cookie_html(
    state: SessionState, max_age_seconds: int,
) -> str | None:
    """Return the queued cookie JS (and consume the queue), or None."""
    pending = state.pop(_PENDING_KEY, None)
    if not pending:
        return None
    action, token = pending
    if action == "set" and token:
        return set_cookie_js(token, max_age_seconds)
    if action == "clear":
        return clear_cookie_js()
    return None


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


def flush_pending_cookie() -> None:
    """Render any queued cookie write/clear. Call once per render, early,
    at a point reached on EVERY rerun."""
    import streamlit as st  # noqa: PLC0415
    import streamlit.components.v1 as components  # noqa: PLC0415

    from config import settings  # noqa: PLC0415

    html = pop_pending_cookie_html(
        st.session_state, settings.session_max_age_seconds,
    )
    if html:
        components.html(html, height=0)


def restore_login_from_cookie() -> bool:
    """Page-load restore: st.context cookie → /auth/me → login state."""
    import streamlit as st  # noqa: PLC0415

    from app.api_client import ApiClient  # noqa: PLC0415

    try:
        cookie_token = st.context.cookies.get(COOKIE_NAME)
    except Exception:  # st.context unavailable (e.g. bare script run)
        cookie_token = None

    def fetch_me(token: str) -> dict[str, Any]:
        with ApiClient(session_token=token) as api:
            return api.auth_me()

    restored = restore_login(st.session_state, cookie_token, fetch_me)
    if restored:
        # A restore changes what the sidebar/hero should show this render;
        # rerun so the whole page renders logged-in from the top.
        st.rerun()
    return restored


__all__ = [
    "COOKIE_NAME",
    "clear_cookie_js",
    "flush_pending_cookie",
    "pop_pending_cookie_html",
    "queue_cookie_clear",
    "queue_cookie_write",
    "restore_login",
    "restore_login_from_cookie",
    "set_cookie_js",
]
