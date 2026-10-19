"""Comparison is a bounded, ordered, per-tab workspace, separate from chat."""

import copy

import pytest

from app import state_manager as sm


def test_default_lists_are_independent_and_initialization_is_idempotent():
    first, second = {}, {}
    sm.init_state(first)
    sm.init_state(second)
    assert first["compare_course_ids"] == second["compare_course_ids"] == []
    assert first["compare_course_ids"] is not second["compare_course_ids"]
    first["compare_course_ids"].append("a")
    sm.init_state(first)
    assert first["compare_course_ids"] == ["a"]
    assert second["compare_course_ids"] == sm.DEFAULTS["compare_course_ids"] == []


def test_add_deduplicates_in_insertion_order_without_mutating_old_list():
    state = {"compare_course_ids": ["b"], "other": {"unchanged": True}}
    previous = state["compare_course_ids"]
    assert sm.add_to_compare(state, "a") == "added"
    assert sm.add_to_compare(state, "b") == "already"
    assert state == {"compare_course_ids": ["b", "a"], "other": {"unchanged": True}}
    assert previous == ["b"]


def test_limit_and_duplicate_precedence_at_capacity():
    state = {}
    for cid in ["d", "a", "c", "b"]:
        assert sm.add_to_compare(state, cid) == "added"
    assert sm.add_to_compare(state, "e") == "full"
    assert sm.add_to_compare(state, "c") == "already"
    assert state["compare_course_ids"] == ["d", "a", "c", "b"]


def test_remove_is_idempotent_and_reopens_one_slot():
    state = {"compare_course_ids": ["a", "b", "c", "d"]}
    previous = state["compare_course_ids"]
    sm.remove_from_compare(state, "b")
    sm.remove_from_compare(state, "missing")
    assert state["compare_course_ids"] == ["a", "c", "d"]
    assert previous == ["a", "b", "c", "d"]
    assert sm.add_to_compare(state, "e") == "added"
    assert state["compare_course_ids"] == ["a", "c", "d", "e"]


def test_clear_affects_only_comparison_and_works_before_init():
    state = {"messages": [{"role": "user", "content": "q"}], "selected_course_id": "a"}
    expected = copy.deepcopy(state)
    sm.clear_compare(state)
    sm.clear_compare(state)
    assert state == {**expected, "compare_course_ids": []}
    sm.remove_from_compare({}, "a")


def test_logout_clears_comparison_but_keeps_filters():
    state = {"compare_course_ids": ["a"], "filters": {"credits": 4}, "session_token": "synthetic"}
    sm.logout(state)
    assert state["compare_course_ids"] == []
    assert state["filters"] == {"credits": 4} and state["session_token"] is None


@pytest.mark.parametrize("action", [sm.clear_conversation, lambda s: sm.select_course(s, "b"),
                                    lambda s: sm.record_search(s, query="q", results=[{"course_id": "b"}], matched_via="alias")])
def test_chat_and_detail_actions_do_not_change_comparison(action):
    state = {"compare_course_ids": ["a"], "messages": []}
    action(state)
    assert state["compare_course_ids"] == ["a"]
