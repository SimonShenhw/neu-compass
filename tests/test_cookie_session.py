"""Tests for app.cookie_session — JS builders, queue/flush state machine,
and the cookie→login restore logic (pure parts; the streamlit glue is a
thin lazy-import wrapper, same convention as ui_theme/state_manager)."""

from __future__ import annotations

import pytest

from app.api_client import ApiError
from app.cookie_session import (
    COOKIE_NAME,
    OAUTH_STATE_COOKIE,
    clear_cookie_js,
    oauth_state_cookie_js,
    oauth_state_matches,
    pop_pending_cookie_html,
    queue_cookie_clear,
    queue_cookie_write,
    queue_oauth_state_clear,
    restore_login,
    set_cookie_js,
)
from app.state_manager import init_state, is_logged_in, login


# === JS builders ===


def test_set_cookie_js_contains_token_and_attributes() -> None:
    js = set_cookie_js("tok-abc.123", 604800)
    assert COOKIE_NAME in js
    assert '"tok-abc.123"' in js
    assert "max-age=604800" in js
    assert "SameSite=Lax" in js
    assert "path=/" in js


def test_set_cookie_js_escapes_hostile_token() -> None:
    """A quote in the token must not break out of the JS string literal."""
    js = set_cookie_js("a\"; document.cookie='pwned", 60)
    assert "pwned" in js  # present, but...
    assert '"a\\"; document.cookie=\'pwned"' in js  # ...inside the literal


def test_clear_cookie_js_expires_immediately() -> None:
    js = clear_cookie_js()
    assert COOKIE_NAME in js
    assert "max-age=0" in js


# === queue / flush state machine ===


def test_queue_write_then_pop_returns_set_js() -> None:
    state: dict = {}
    queue_cookie_write(state, "tok-1")
    html = pop_pending_cookie_html(state, 3600)
    assert html is not None and '"tok-1"' in html and "max-age=3600" in html
    # consumed — second pop is a no-op
    assert pop_pending_cookie_html(state, 3600) is None


def test_queue_write_none_token_is_noop() -> None:
    """Dev mode (SESSION_SECRET unset) mints no token — nothing to persist."""
    state: dict = {}
    queue_cookie_write(state, None)
    assert pop_pending_cookie_html(state, 3600) is None


def test_queue_clear_then_pop_returns_clear_js() -> None:
    state: dict = {}
    queue_cookie_clear(state)
    html = pop_pending_cookie_html(state, 3600)
    assert html is not None and "max-age=0" in html


def test_clear_overrides_pending_write() -> None:
    """Logout right after login: the clear must win."""
    state: dict = {}
    queue_cookie_write(state, "tok-1")
    queue_cookie_clear(state)
    html = pop_pending_cookie_html(state, 3600)
    assert html is not None and "max-age=0" in html


def test_oauth_callback_queue_combines_state_clear_and_session_write() -> None:
    """Successful OAuth callback queues TWO ops: drop the consumed CSRF
    state cookie + persist the session token. Both must flush."""
    state: dict = {}
    queue_oauth_state_clear(state)
    queue_cookie_write(state, "tok-login")
    html = pop_pending_cookie_html(state, 3600)
    assert html is not None
    assert OAUTH_STATE_COOKIE in html and "max-age=0" in html
    assert '"tok-login"' in html and "max-age=3600" in html
    assert pop_pending_cookie_html(state, 3600) is None  # consumed


# === OAuth CSRF state (cookie round-trip) ===


def test_oauth_state_cookie_js_short_lived() -> None:
    js = oauth_state_cookie_js("state-abc")
    assert OAUTH_STATE_COOKIE in js
    assert '"state-abc"' in js
    assert "max-age=600" in js


def test_oauth_state_matches() -> None:
    assert oauth_state_matches("s1", "s1") is True
    assert oauth_state_matches("s1", "s2") is False
    assert oauth_state_matches(None, "s1") is False
    assert oauth_state_matches("s1", None) is False
    assert oauth_state_matches("", "") is False


# === restore_login ===


def _fresh_state() -> dict:
    state: dict = {}
    init_state(state)
    return state


def test_restore_success_logs_in_and_keeps_token() -> None:
    state = _fresh_state()

    def fetch_me(token: str) -> dict:
        assert token == "tok-9"
        return {
            "user_id": "u-9",
            "email": "u9@husky.neu.edu",
            "display_name": "Nine",
            "contribution_count": 3,
        }

    assert restore_login(state, "tok-9", fetch_me) is True
    assert is_logged_in(state)
    assert state["session_token"] == "tok-9"
    assert state["user_display_name"] == "Nine"
    assert state["user_contribution_count"] == 3


def test_restore_runs_at_most_once_per_tab() -> None:
    state = _fresh_state()
    calls: list[str] = []

    def fetch_me(token: str) -> dict:
        calls.append(token)
        return {"user_id": "u", "email": "u@husky.neu.edu"}

    assert restore_login(state, "tok", fetch_me) is True
    # Second attempt (another rerun) must not even hit the API.
    assert restore_login(state, "tok", fetch_me) is False
    assert calls == ["tok"]


def test_restore_skips_when_already_logged_in_but_still_burns_guard() -> None:
    """OAuth-callback tab: login happened before the restore check ever ran.
    The guard must still be set so a later logout + stale st.context cookie
    can't silently re-login this tab."""
    state = _fresh_state()
    login(
        state, user_id="u-1", user_email="u1@husky.neu.edu",
        session_token="tok-live",
    )

    def fetch_me(token: str) -> dict:  # pragma: no cover - must not be called
        raise AssertionError("API must not be hit when already logged in")

    assert restore_login(state, "tok-stale", fetch_me) is False
    # Guard burned: after logout, no resurrection from the stale cookie.
    assert restore_login(state, "tok-stale", fetch_me) is False


def test_restore_no_cookie_is_noop() -> None:
    state = _fresh_state()
    assert restore_login(state, None, lambda t: {}) is False
    assert not is_logged_in(state)


def test_restore_401_queues_cookie_clear() -> None:
    state = _fresh_state()

    def fetch_me(token: str) -> dict:
        raise ApiError(401, "Invalid or expired session token.")

    assert restore_login(state, "tok-stale", fetch_me) is False
    assert not is_logged_in(state)
    html = pop_pending_cookie_html(state, 3600)
    assert html is not None and "max-age=0" in html


@pytest.mark.parametrize("status_code", [500, 504])
def test_restore_transient_error_keeps_cookie(status_code: int) -> None:
    """API down/timeout: leave the cookie alone — a later reload retries."""
    state = _fresh_state()

    def fetch_me(token: str) -> dict:
        raise ApiError(status_code, "boom")

    assert restore_login(state, "tok", fetch_me) is False
    assert pop_pending_cookie_html(state, 3600) is None
