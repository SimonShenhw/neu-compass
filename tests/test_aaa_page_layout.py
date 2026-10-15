"""Frozen main-page layout contracts; run early for fail-fast full-scope mutations.

中文：固定容器、有序元素、HTML 及完整布局元数据；仅在明确的未改产品基线上显式生成快照。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from tests.page_layout_support import (
    SNAPSHOT_NAMES,
    SNAPSHOTS,
    install_backend,
    layout_snapshot,
    page,
    render_layout_case,
    run,
    snapshot_json,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def fixed_public_base_url(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "public_base_url", "http://localhost:8501")


@pytest.fixture
def backend(monkeypatch):
    return install_backend(monkeypatch)


@pytest.mark.parametrize("name", SNAPSHOT_NAMES)
def test_ordered_page_layout(backend, monkeypatch, name):
    app, forwarded = render_layout_case(name, monkeypatch, backend)
    actual = layout_snapshot(app, forwarded)
    path = SNAPSHOTS / f"{name}.json"
    expected_text = path.read_text(encoding="utf-8")
    assert actual == json.loads(expected_text)
    assert snapshot_json(actual) == expected_text


def test_second_question_skips_detail_until_post_chat_finishes(backend):
    app = page()
    app.chat_input[0].set_value("first question")
    run(app)
    assert app.session_state["selected_course_id"] == "c-algo"
    before = len(backend.requests)
    app.chat_input[0].set_value("second question")
    run(app)
    assert [f"{method} {path}" for method, path, _ in backend.requests[before:]] == [
        "POST /chat", "GET /course/c-algo",
    ]
    assert [body["query"] for body in backend.posts] == ["first question", "second question"]


def test_moved_renderers_have_the_correct_nearest_with_container():
    tree = ast.parse((ROOT / "app/streamlit_app.py").read_text(encoding="utf-8"))
    render = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "render")
    parents = {child: parent for parent in ast.walk(render) for child in ast.iter_child_nodes(parent)}
    expected = {"render_landing": "chat_col", "render_chat_history": "chat_col", "render_selected_course": "detail_col"}
    found = set()
    for call in ast.walk(render):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id not in expected:
            continue
        found.add(call.func.id)
        ancestor = parents[call]
        while not isinstance(ancestor, (ast.With, ast.AsyncWith)) and ancestor is not render:
            ancestor = parents[ancestor]
        assert isinstance(ancestor, ast.With)
        assert len(ancestor.items) == 1
        context = ancestor.items[0].context_expr
        assert isinstance(context, ast.Name) and context.id == expected[call.func.id]
    assert found == set(expected)


@pytest.mark.parametrize("relative,name", [
    ("app/chat_view.py", None), ("app/discover_view.py", "render_landing"),
    ("app/course_detail_view.py", "render_selected_course"),
])
def test_moved_blocks_cannot_create_chat_input_or_feedback_request_body(relative, name):
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    scope = tree if name is None else next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    assert not any(isinstance(node, ast.Attribute) and node.attr == "chat_input" for node in ast.walk(scope))
    assert not any(isinstance(node, ast.Dict) and any(isinstance(key, ast.Constant) and key.value == "allow_feedback_capture"
                                                   for key in node.keys) for node in ast.walk(scope))
