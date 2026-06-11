"""Streamlit session-state SOP (PLAN §7.6 / v2.0 §4.1).

st.session_state is a per-tab dict-like that survives Streamlit reruns.
Mutating it from many call sites makes state hard to reason about — this
module is the single entry point that initializes / reads / writes it.
Page modules call init_state(st.session_state) once at the top of render().

Why a flat key namespace (user_id, user_email) instead of nested
(user={"id":..., "email":...}): Streamlit's diff-based rerun behavior
fires on the top-level key, so flat keys give finer-grained reactivity.
Nested dicts force callers to mutate-in-place, which is easy to get wrong.

The functions here are pure given a state mapping — no Streamlit imports —
so unit tests pass an ordinary dict() in.
"""

from __future__ import annotations

from typing import Any, MutableMapping

# Mapping abstraction: production gets st.session_state, tests get dict().
SessionState = MutableMapping[str, Any]

DEFAULTS: dict[str, Any] = {
    # Auth
    "user_id": None,
    "user_email": None,
    "user_contribution_count": 0,
    "session_token": None,   # ADR-0021 signed bearer credential
    # Conversation (chat)
    "messages": [],          # [{"role", "content", "evidence", "matched_via"}]
    # Last search context (drives course detail panel)
    "last_query": None,
    "search_results": [],
    "search_k": 10,
    "filters": {},
    "selected_course_id": None,
}


def init_state(state: SessionState) -> None:
    """Idempotent — safe to call at the top of every page render."""
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


def is_logged_in(state: SessionState) -> bool:
    return bool(state.get("user_id"))


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
    """Clear identity + conversation. Search filters keep — nothing private
    in them, and the user shouldn't have to retype after logout/login."""
    state["user_id"] = None
    state["user_email"] = None
    state["user_contribution_count"] = 0
    state["session_token"] = None
    state["messages"] = []
    state["search_results"] = []
    state["selected_course_id"] = None


# === Conversation ===


def add_message(
    state: SessionState,
    *,
    role: str,
    content: str,
    evidence: list[dict] | None = None,
    matched_via: str | None = None,
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


def get_messages(state: SessionState) -> list[dict]:
    return state.get("messages", [])


def clear_conversation(state: SessionState) -> None:
    state["messages"] = []
    state["last_query"] = None
    state["search_results"] = []
    state["selected_course_id"] = None


# === Search context ===


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


__all__ = [
    "DEFAULTS",
    "SessionState",
    "add_message",
    "clear_conversation",
    "get_messages",
    "init_state",
    "is_logged_in",
    "login",
    "logout",
    "record_search",
    "select_course",
]
