"""Exact history feedback keys: suffix-only lookups do not pin the orchestration prefix."""

import httpx
from streamlit.testing.v1 import AppTest

from tests.test_home_cache_page import RECEIPT, SCRIPT, page as page, run


def test_history_feedback_keys_are_exact_and_reruns_never_revote(request, monkeypatch):
    from app.answer_feedback_view import CAPTURE_OPT_IN_KEY
    from config import settings

    _, backend = request.getfixturevalue("page")
    original_send = httpx.Client.send
    def guarded_send(client, request, **kwargs):
        assert isinstance(client._transport, httpx.MockTransport), "No live networking in feedback characterization"
        return original_send(client, request, **kwargs)
    monkeypatch.setattr(httpx.Client, "send", guarded_send)
    monkeypatch.setattr(settings, "answer_feedback_enabled", True)
    app = run(AppTest.from_string(SCRIPT))
    app.checkbox(key=CAPTURE_OPT_IN_KEY).check()
    run(app)
    app.chat_input[0].set_value("synthetic question")
    run(app)
    expected = [f"answer-feedback-1-{RECEIPT['answer_id']}-{rating}" for rating in ("up", "down")]
    keys = [item.key for item in app.button if RECEIPT["answer_id"] in str(item.key)]
    assert keys == expected
    app.button(key=expected[0]).click()
    run(app)
    assert app.session_state["messages"][-1]["feedback_rating"] == "up"
    assert backend.posts() == ["/chat", "/feedback"]
    run(app)
    assert app.button(key=expected[0]).disabled
    app.button(key=expected[1]).click()
    run(app)
    assert app.session_state["messages"][-1]["feedback_rating"] == "down"
    assert backend.posts() == ["/chat", "/feedback", "/feedback"]
    run(app)
    assert backend.posts() == ["/chat", "/feedback", "/feedback"]
