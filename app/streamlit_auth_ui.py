"""Streamlit-side auth UI helpers — login button + OAuth callback + sidebar.

Streamlit imports are lazy so this module loads cleanly outside Streamlit
(tests can `import` it without spinning up the runtime).

Two entry points page modules call:
  - `handle_oauth_callback()` — at the top of render(), processes ?code=
  - `render_auth_sidebar()`   — anywhere in render(), draws the sidebar
"""

from __future__ import annotations


def handle_oauth_callback() -> None:
    """If `?code=` is present in the URL, exchange it via /auth/callback,
    persist the user, and clear the query string so a refresh doesn't
    retry. No-op when no code is present.

    Failures (bad domain, expired code, network) surface via st.error and
    leave the user logged out.
    """
    import streamlit as st  # noqa: PLC0415

    from app.api_client import ApiClient, ApiError  # noqa: PLC0415
    from app.cookie_session import queue_cookie_write  # noqa: PLC0415
    from app.state_manager import login  # noqa: PLC0415

    code = st.query_params.get("code")
    if not code:
        return

    # CSRF (ADR-0021): the state we generated before redirecting to Google
    # must round-trip unchanged. A mismatch means this ?code= was NOT the
    # continuation of a flow this tab started — discard it.
    expected_state = st.session_state.get("oauth_state")
    returned_state = st.query_params.get("state")
    if not expected_state or returned_state != expected_state:
        st.error("Login flow state mismatch — please try signing in again.")
        st.query_params.clear()
        return
    st.session_state.pop("oauth_state", None)  # one-shot

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
    queue_cookie_write(st.session_state, identity.get("session_token"))

    st.query_params.clear()
    st.rerun()


def render_auth_sidebar() -> None:
    """Sidebar block: login link OR logged-in info + logout button."""
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
            # CSRF state survives reruns in session_state; regenerated only
            # when absent so the link stays stable within one login attempt.
            import secrets  # noqa: PLC0415

            if not st.session_state.get("oauth_state"):
                st.session_state["oauth_state"] = secrets.token_urlsafe(24)
            url = authorize_url(state_token=st.session_state["oauth_state"])
            st.markdown(f"[🔐 Sign in with Google]({url})")
            st.caption("Restricted to husky.neu.edu / northeastern.edu.")


__all__ = ["handle_oauth_callback", "render_auth_sidebar"]
