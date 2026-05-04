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
    from app.state_manager import login  # noqa: PLC0415

    code = st.query_params.get("code")
    if not code:
        return

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
    )
    if identity.get("display_name"):
        st.session_state["user_display_name"] = identity["display_name"]

    st.query_params.clear()
    st.rerun()


def render_auth_sidebar() -> None:
    """Sidebar block: login link OR logged-in info + logout button."""
    import streamlit as st  # noqa: PLC0415

    from app.auth import authorize_url  # noqa: PLC0415
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
                logout(st.session_state)
                st.rerun()
        else:
            url = authorize_url()
            st.markdown(f"[🔐 Sign in with Google]({url})")
            st.caption("Restricted to husky.neu.edu / northeastern.edu.")


__all__ = ["handle_oauth_callback", "render_auth_sidebar"]
