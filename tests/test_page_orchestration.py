"""SIM-03 characterization: freeze public page behavior BEFORE extracting any production code."""

from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

from app.streamlit_app import _context_course_ids, _recent_history
from tests.page_layout_support import ANSWER, COURSES, MULTI, SINGLE, install_backend, page, run

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("limit", [6, 2, 0, -2])
def test_history_window_and_slice_before_filtering(limit):
    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i), "extra": i} for i in range(9)]
    messages[-2]["content"] = ""
    messages[-1]["content"] = None
    original = copy.deepcopy(messages)
    expected_indices = {6: [3, 4, 5, 6], 2: [], 0: list(range(7)), -2: list(range(2, 7))}[limit]
    assert _recent_history(messages, limit) == [{"role": messages[i]["role"], "content": str(i)} for i in expected_indices]
    assert messages == original


def test_history_conversion_and_4000_character_bound_are_exact():
    assert _recent_history([
        {"role": "assistant", "content": "界" * 4001, "evidence": COURSES},
        {"role": "user", "content": 123}, {"role": "user", "content": 0},
        {"role": "user", "content": " \t "},
    ]) == [{"role": "assistant", "content": "界" * 4000},
        {"role": "user", "content": "123"}, {"role": "user", "content": " \t "}]
    assert _recent_history([]) == []
    with pytest.raises(KeyError):
        _recent_history([{"content": "truthy"}])


@pytest.mark.parametrize("limit,expected", [(10, ["a", "b", "a"]), (1, ["a"]), (0, []), (-1, ["a", "b"])])
def test_context_latest_assistant_evidence_keeps_order_and_duplicates(limit, expected):
    messages = [
        {"role": "assistant", "evidence": [{"course_id": "old"}]},
        {"role": "assistant", "evidence": [{"course_id": "a"}, {"course_id": "b"}, {"course_id": "a"}]},
        {"role": "assistant", "evidence": []}, {"role": "user", "evidence": [{"course_id": "not-user"}]},
    ]
    original = copy.deepcopy(messages)
    assert _context_course_ids(messages, limit) == expected
    assert messages == original


def test_context_default_cap_and_existing_malformed_behavior():
    assert _context_course_ids([{"role": "assistant", "evidence": [{"course_id": str(i)} for i in range(12)]}]) == [str(i) for i in range(10)]
    assert _context_course_ids([]) == []
    assert _context_course_ids([{"role": "user", "evidence": COURSES}]) == []
    with pytest.raises(KeyError):
        _context_course_ids([{"role": "assistant", "evidence": [{}]}])


@pytest.fixture
def backend(monkeypatch):
    return install_backend(monkeypatch)


def test_cold_landing_has_four_samples_then_hides_on_submit(backend):
    from app.streamlit_app import SAMPLE_QUERIES
    from app.ui_theme import empty_detail_html
    app = page()
    assert [app.button(key=f"sample-{i}").label for i in range(4)] == [label for label, _ in SAMPLE_QUERIES]
    assert backend.trace == ["filters", "landing"]
    assert empty_detail_html() in [item.value for item in app.markdown]
    app.button(key="sample-0").click()
    run(app)
    assert backend.queued == ["CS 5800"]
    assert len(backend.posts) == 1 and backend.posts[0]["query"] == "CS 5800"
    assert backend.posts[0]["credits"] == 0 and backend.posts[0]["professor"] == "Synthetic Prof"
    assert "delivery_mode" not in backend.posts[0]
    # Click pass still has no prompt and queues it from the landing; the submit pass must not.
    assert backend.trace.count("landing") == 2
    run(app)  # AppTest retains interrupted-pass fragments until a complete stable render.
    assert len(backend.posts) == 1 and backend.trace.count("landing") == 2
    assert not [button for button in app.button if str(button.key).startswith("sample-")]
    assert not [button for button in app.button if str(button.key).startswith("open-live-")]


@pytest.mark.parametrize("status", [200, 500])
def test_history_open_selects_second_course_and_keeps_detail_fetch_semantics(backend, status):
    backend.results = copy.deepcopy(COURSES)
    app = page(token="synthetic-session")
    app.chat_input[0].set_value("courses")
    run(app)
    assert app.session_state["selected_course_id"] == "c-algo"
    backend.course_status = status
    app.button(key="open-1-assistant-c-ml").click()
    run(app)
    assert app.session_state["selected_course_id"] == "c-ml"
    assert len(backend.posts) == 1
    assert backend.requests[-1] == ("GET", "/course/c-ml", "Bearer synthetic-session")
    if status == 200:
        assert any("Synthetic ML" in item.value and "nc-card-name" in item.value for item in app.markdown)
    else:
        assert [item.value for item in app.error][0].startswith("课程详情加载失败")
    before = len(backend.requests)
    run(app)
    assert len(backend.requests) == before + 1  # Detail is intentionally not cached.
    assert len(backend.posts) == 1


@pytest.mark.parametrize("count,labels", [(1, SINGLE), (2, MULTI)])
def test_followup_queues_prompt_and_sends_prior_history_and_context(backend, count, labels):
    backend.results = copy.deepcopy(COURSES[:count])
    app = page()
    app.chat_input[0].set_value("first question")
    run(app)
    assert [app.button(key=f"chip-1-{i}").label for i in range(3)] == labels
    prior = [{"role": "user", "content": "first question"}, {"role": "assistant", "content": ANSWER}]
    app.button(key="chip-1-1").click()
    run(app)
    assert backend.queued == [labels[1].removeprefix("↳ ")]
    assert len(backend.posts) == 2
    body = backend.posts[-1]
    assert body["query"] == backend.queued[-1]
    assert body["history"] == prior  # New prompt must not already be in history.
    assert body["context_course_ids"] == [item["course_id"] for item in COURSES[:count]]
    assert [msg["role"] for msg in app.session_state["messages"]] == ["user", "assistant", "user", "assistant"]
    assert app.button(key="open-1-assistant-c-algo") and app.button(key="open-3-assistant-c-algo")
    run(app)
    assert [button.key for button in app.button if str(button.key).startswith("chip-")] == ["chip-3-0", "chip-3-1", "chip-3-2"]
    assert len(backend.posts) == 2


@pytest.mark.parametrize("last", [
    {"role": "assistant", "content": "empty", "evidence": []},
    {"role": "assistant", "content": "rejected", "evidence": COURSES, "matched_via": "rejected"},
    {"role": "assistant", "content": "empty retrieval", "evidence": COURSES, "matched_via": "empty"},
    {"role": "user", "content": "user with evidence", "evidence": COURSES},
])
def test_only_eligible_latest_assistant_has_chips(backend, last):
    messages = [{"role": "assistant", "content": "older", "evidence": COURSES[:1], "matched_via": "hybrid"}, last]
    app = page(messages=messages)
    assert not [button for button in app.button if str(button.key).startswith("chip-")]
    assert not backend.posts and "landing" not in backend.trace


def test_chosen_program_reaches_chat_body_and_navigation_remains_first(backend):
    backend.programs = [{"program_id": "cs-ms", "prefix": "CS", "full_name": "Synthetic CS"}]
    app = page()
    assert app.radio[0].key == "nav_page"
    app.selectbox(key="chat_program_id").select("cs-ms")
    run(app)
    app.chat_input[0].set_value("my selected program")
    run(app)
    assert backend.posts[0]["program_id"] == "cs-ms"


def test_history_uses_main_global_renderers_and_filters_only_assistant(backend, monkeypatch):
    import app.streamlit_app as main
    from app.answer_evidence_view import answer_markdown
    roles, prefixes = [], []
    original_text, original_evidence = main._render_message_text, main._render_evidence_block
    def text(st, msg):
        roles.append(msg["role"])
        original_text(st, msg)
    def evidence(st, results, key_prefix):
        prefixes.append(key_prefix)
        original_evidence(st, results, key_prefix)
    monkeypatch.setattr(main, "_render_message_text", text)
    monkeypatch.setattr(main, "_render_evidence_block", evidence)
    app = page(messages=[{"role": "user", "content": ANSWER},
        {"role": "assistant", "content": ANSWER, "evidence": COURSES[:1], "matched_via": "hybrid"}])
    assert roles == ["user", "assistant"] and prefixes == ["open-1-assistant"]
    shown = [item.value for item in app.markdown]
    assert ANSWER in shown and answer_markdown(ANSWER) in shown


def test_orchestration_order_and_chat_column_ownership_remain_explicit():
    tree = ast.parse((ROOT / "app/streamlit_app.py").read_text(encoding="utf-8"))
    render = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "render")
    parents = {child: node for node in ast.walk(render) for child in ast.iter_child_nodes(node)}
    calls = [node for node in ast.walk(render) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    landing = next(node for node in calls if node.func.id in {"render_discover", "render_landing"})
    history = next(node for node in calls if node.func.id in {"_render_message_text", "render_chat_history"})
    submit = min(node.lineno for node in calls if node.func.id == "add_message")
    assert landing.lineno < history.lineno < submit
    for node in (landing, history):
        ancestors = []
        while node is not render:
            node = parents[node]
            ancestors.append(node)
        assert any(isinstance(item, ast.With) and any(isinstance(entry.context_expr, ast.Name)
            and entry.context_expr.id == "chat_col" for entry in item.items) for item in ancestors)
    assert sum(node.func.id == "_end_page" for node in calls) == 3
