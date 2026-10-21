"""Draft IDs/credits live only in one Streamlit session; immutable list updates."""

import importlib

import pytest

from app import state_manager as sm
from tests.test_plan_draft import course


def draft(code="CS 5001"):
    return importlib.import_module("schemas.plan_draft").DraftCourse(**course(code)).model_dump()


def test_new_sessions_have_independent_empty_drafts():
    a, b = {}, {}
    sm.init_state(a)
    sm.init_state(b)
    assert a["plan_draft_courses"] == b["plan_draft_courses"] == []
    assert a["plan_draft_courses"] is not b["plan_draft_courses"]


def test_batch_add_order_dedup_and_remove_do_not_mutate_old_values():
    state = {}
    assert sm.add_draft_courses(state, [draft(), draft("CS 5002"), draft()]) == "added"
    old = state["plan_draft_courses"]
    assert sm.add_draft_courses(state, [draft()]) == "already"
    sm.remove_draft_course(state, "cs5001")
    assert [c["code"] for c in state["plan_draft_courses"]] == ["CS 5002"]
    assert len(old) == 2
    sm.remove_draft_course(state, "CS 5999")
    sm.clear_draft(state)
    assert state["plan_draft_courses"] == [] and len(old) == 2


def test_twenty_course_cap_is_atomic_and_dedup_precedes_cap():
    state = {}
    assert sm.add_draft_courses(state, [draft(f"CS {5000+i}") for i in range(20)]) == "added"
    before = list(state["plan_draft_courses"])
    assert sm.add_draft_courses(state, [draft("CS 5000")]) == "already"
    assert sm.add_draft_courses(state, [draft("CS 5999")]) == "full"
    assert state["plan_draft_courses"] == before


def test_chat_clear_and_same_identity_preserve_but_logout_and_identity_change_clear():
    state = {"plan_draft_courses": [draft()], "user_id": "a", "messages": []}
    sm.clear_conversation(state)
    assert state["plan_draft_courses"]
    sm.login(state, user_id="a", user_email="a@example.test")
    assert state["plan_draft_courses"]
    sm.login(state, user_id="b", user_email="b@example.test")
    assert state["plan_draft_courses"] == []
    state["plan_draft_courses"] = [draft()]
    sm.logout(state)
    assert state["plan_draft_courses"] == []


def test_invalid_batch_does_not_change_draft():
    state = {"plan_draft_courses": [draft()]}
    with pytest.raises(ValueError):
        sm.add_draft_courses(state, [{**draft("CS 5002"), "credits": True}])
    assert len(state["plan_draft_courses"]) == 1


def test_clear_and_identity_change_remove_unsubmitted_form_text_too():
    state = {"plan_draft_courses": [draft()], "plan-draft-input": "CS 5001 CS 5002", "user_id": "a"}
    sm.clear_draft(state)
    assert state["plan-draft-input"] == "" and state["plan_draft_courses"] == []
    state["plan-draft-input"] = "CS 5999"
    sm.login(state, user_id="b", user_email="synthetic@example.test")
    assert state["plan-draft-input"] == ""


def test_mixed_duplicate_batch_preserves_first_metadata_and_input_objects():
    first = draft()
    state = {"plan_draft_courses": [first]}
    replacement = {**draft(), "credits": 12, "name": "Different synthetic metadata"}
    added = draft("CS 5002")
    assert sm.add_draft_courses(state, [replacement, added]) == "added"
    assert state["plan_draft_courses"] == [first, added]
    assert first["credits"] == 4 and replacement["credits"] == 12
