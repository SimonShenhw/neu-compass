"""Tests for app.state_manager — pure functions over a state mapping.

State is just a dict-like; no Streamlit needed in tests."""

from __future__ import annotations

import pytest

from app.state_manager import (
    DEFAULTS,
    add_message,
    clear_conversation,
    get_messages,
    init_state,
    is_logged_in,
    login,
    logout,
    record_search,
    select_course,
)


# === init_state ===


def test_init_state_populates_defaults() -> None:
    state: dict = {}
    init_state(state)
    for k, default in DEFAULTS.items():
        assert k in state
    assert state["user_id"] is None
    assert state["messages"] == []
    assert state["filters"] == {}


def test_init_state_is_idempotent() -> None:
    state: dict = {}
    init_state(state)
    state["user_id"] = "u-1"
    state["messages"].append({"role": "user", "content": "hi"})
    init_state(state)  # second call must NOT overwrite
    assert state["user_id"] == "u-1"
    assert len(state["messages"]) == 1


def test_init_state_uses_independent_mutable_copies() -> None:
    """Two states must not share the same list/dict object — otherwise
    appending to one bleeds into the other."""
    a: dict = {}
    b: dict = {}
    init_state(a)
    init_state(b)
    a["messages"].append({"role": "user", "content": "x"})
    assert b["messages"] == []


# === login / logout ===


def test_is_logged_in_falsy_by_default() -> None:
    state: dict = {}
    init_state(state)
    assert is_logged_in(state) is False


def test_login_sets_identity_fields() -> None:
    state: dict = {}
    init_state(state)
    login(
        state,
        user_id="g-sub-123",
        user_email="a@husky.neu.edu",
        contribution_count=2,
    )
    assert is_logged_in(state) is True
    assert state["user_id"] == "g-sub-123"
    assert state["user_email"] == "a@husky.neu.edu"
    assert state["user_contribution_count"] == 2


def test_logout_clears_identity_and_conversation() -> None:
    state: dict = {}
    init_state(state)
    login(state, user_id="u-1", user_email="x@husky.neu.edu", contribution_count=1)
    add_message(state, role="user", content="hi")
    state["search_results"] = [{"course_id": "c-1"}]
    state["selected_course_id"] = "c-1"
    state["filters"] = {"term": "Spring 2026"}

    logout(state)

    assert state["user_id"] is None
    assert state["user_email"] is None
    assert state["user_contribution_count"] == 0
    assert state["messages"] == []
    assert state["search_results"] == []
    assert state["selected_course_id"] is None
    # Filters intentionally preserved across logout
    assert state["filters"] == {"term": "Spring 2026"}


# === messages ===


def test_add_message_user_then_assistant() -> None:
    state: dict = {}
    init_state(state)
    add_message(state, role="user", content="hi")
    add_message(
        state,
        role="assistant",
        content="hello",
        evidence=[{"course_id": "c-1", "primary_code": "CS 5800"}],
        matched_via="alias",
    )
    msgs = get_messages(state)
    assert len(msgs) == 2
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["evidence"][0]["course_id"] == "c-1"
    assert msgs[1]["matched_via"] == "alias"


def test_add_message_rejects_invalid_role() -> None:
    state: dict = {}
    init_state(state)
    with pytest.raises(ValueError):
        add_message(state, role="system", content="oops")


def test_clear_conversation_keeps_user_identity() -> None:
    state: dict = {}
    init_state(state)
    login(state, user_id="u-1", user_email="x@husky.neu.edu")
    add_message(state, role="user", content="x")
    clear_conversation(state)
    assert state["user_id"] == "u-1"
    assert state["messages"] == []
    assert state["last_query"] is None


# === record_search ===


def test_record_search_sets_first_result_as_selected() -> None:
    state: dict = {}
    init_state(state)
    record_search(
        state,
        query="graph",
        results=[
            {"course_id": "c-cs-5800"},
            {"course_id": "c-aai-6600"},
        ],
        matched_via="hybrid",
    )
    assert state["last_query"] == "graph"
    assert len(state["search_results"]) == 2
    assert state["selected_course_id"] == "c-cs-5800"


def test_record_search_empty_does_not_change_selection() -> None:
    state: dict = {}
    init_state(state)
    state["selected_course_id"] = "c-existing"
    record_search(state, query="nothing", results=[], matched_via="empty")
    assert state["selected_course_id"] == "c-existing"


def test_select_course_updates_selection() -> None:
    state: dict = {}
    init_state(state)
    select_course(state, "c-aai-6600")
    assert state["selected_course_id"] == "c-aai-6600"
    select_course(state, None)
    assert state["selected_course_id"] is None
