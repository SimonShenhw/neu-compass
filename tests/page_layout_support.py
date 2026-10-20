"""Shared offline page harness for orchestration, layout tests and fixture generation."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import httpx
from google.protobuf.json_format import MessageToDict
from streamlit.runtime.forward_msg_queue import ForwardMsgQueue
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import Block

SCRIPT = "from app.streamlit_app import render\nrender()"
COURSES = [
    {"course_id": "c-algo", "primary_code": "CS 5800", "primary_name": "Synthetic Algorithms", "score": 0.9},
    {"course_id": "c-ml", "primary_code": "DS 5220", "primary_name": "Synthetic ML", "score": 0.7},
]
SINGLE = ["↳ 这门课讲什么内容？", "↳ 这门课作业量大吗？", "↳ 先修要求是什么？"]
MULTI = ["↳ 这几门课怎么选？", "↳ 哪门最适合零基础？", "↳ 第一门的先修要求？"]
ANSWER = "Synthetic [untrusted](https://elsewhere.example) answer."


class Backend:
    def __init__(self):
        self.results = copy.deepcopy(COURSES[:1])
        self.programs = []
        self.course_status = 200
        self.requests = []
        self.posts = []
        self.queued = []
        self.trace = []

    def __call__(self, request):
        self.requests.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.method == "POST":
            assert request.url.path == "/chat"
            self.posts.append(json.loads(request.content))
            self.trace.append("post")
            events = [{"type": "meta", "results": self.results, "matched_via": "hybrid",
                       "notices": ["program_schedule_unverified"]},
                {"type": "token", "text": ANSWER}, {"type": "done"}]
            return httpx.Response(200, content="".join(json.dumps(event) + "\n" for event in events).encode())
        if request.url.path == "/ready":
            return httpx.Response(200, json={"status": "ready", "courses_indexed": 3, "bm25_corpus": 3})
        if request.url.path.startswith("/programs/"):
            # F looks up versioned plans after a family is explicitly chosen; this legacy-only
            # synthetic family has none. No additional widget or automatic choice is expected.
            return httpx.Response(200, json={"program_id": request.url.path.rsplit("/", 1)[1],
                "plan_schema_available": True, "plans": []})
        if request.url.path.startswith("/course/"):
            if self.course_status != 200:
                return httpx.Response(self.course_status, json={"detail": "synthetic detail failure"})
            course = next(item for item in COURSES if request.url.path.endswith(item["course_id"]))
            return httpx.Response(200, json={**course, "credits": 4, "term": "Fall 2026"})
        raise AssertionError(f"Unexpected synthetic request: {request.method} {request.url.path}")


def install_backend(monkeypatch):
    import streamlit as st
    import app.api_client as clients
    import app.cookie_session as cookies
    import app.discover_view as discover
    import app.program_view as programs
    import app.streamlit_app as main
    import app.streamlit_auth_ui as auth
    from config import settings

    backend = Backend()
    original_client, original_send, original_rerun = clients.ApiClient, httpx.Client.send, st.rerun
    def guarded_send(client, request, **kwargs):
        assert isinstance(client._transport, httpx.MockTransport), "Live network prohibited in characterization tests"
        return original_send(client, request, **kwargs)
    monkeypatch.setattr(httpx.Client, "send", guarded_send)
    monkeypatch.setattr(clients, "ApiClient", lambda **kwargs: original_client(
        base_url="http://synthetic-orchestration", transport=httpx.MockTransport(backend), **kwargs))
    monkeypatch.setattr(settings, "answer_feedback_enabled", False)
    monkeypatch.setattr(auth, "handle_oauth_callback", lambda: None)
    monkeypatch.setattr(auth, "render_auth_sidebar", lambda: None)
    monkeypatch.setattr(cookies, "restore_login_from_cookie", lambda: False)
    monkeypatch.setattr(cookies, "flush_pending_cookie", lambda: None)
    def filters(st, state):
        backend.trace.append("filters")
        return {"credits": 0, "professor": "Synthetic Prof", "delivery_mode": ""}
    monkeypatch.setattr(main, "_render_filters_sidebar", filters)
    monkeypatch.setattr(discover, "render_discover", lambda st: backend.trace.append("landing"))
    monkeypatch.setattr(programs, "get_programs_cached", lambda st: backend.programs)
    def rerun(*args, **kwargs):
        if st.session_state.get("pending_query") is not None:
            backend.queued.append(st.session_state["pending_query"])
        return original_rerun(*args, **kwargs)
    monkeypatch.setattr(st, "rerun", rerun)
    return backend


def run(app):
    app.run(timeout=45)
    assert not app.exception
    return app


def page(*, messages=None, token=None):
    app = AppTest.from_string(SCRIPT)
    if messages is not None:
        app.session_state["messages"] = copy.deepcopy(messages)
    if token:
        app.session_state["session_token"] = token
        app.session_state["user_id"] = "synthetic-user"
    return run(app)


SNAPSHOTS = Path(__file__).with_name("fixtures") / "page_layout"
SNAPSHOT_NAMES = (
    "history", "history-3", "history-long", "history-empty-rejected", "landing",
    "detail-None", "detail-200", "detail-404", "detail-500",
)
DISCOVER_MARKER = "Synthetic discover placement marker"
EXTRA_COURSES = [
    {"course_id": "c-db", "primary_code": "CS 5200", "primary_name": "Synthetic Databases", "score": 0.5},
    {"course_id": "c-nlp", "primary_code": "CS 6120", "primary_name": "Synthetic NLP", "score": 0.2},
    {"course_id": "c-systems", "primary_code": "CS 5600", "primary_name": "Synthetic Systems", "score": 0.1},
    {"course_id": "c-net", "primary_code": "CS 5700", "primary_name": "Synthetic Networks", "score": 0.05},
]


def capture_layout_messages(monkeypatch):
    """Observe Streamlit's pinned-version queue; chain and restore any existing hook."""
    captured = []
    previous = ForwardMsgQueue._before_enqueue_msg

    def capture(message):
        captured.append(MessageToDict(message, preserving_proto_field_name=True))
        if previous:
            previous(message)

    monkeypatch.setattr(ForwardMsgQueue, "_before_enqueue_msg", capture)
    return captured


def history(last_count=4):
    """Original receipt-bearing 1/4 (or 1/3) history, retained as a historical contract."""
    messages = []
    for turn, evidence in enumerate([COURSES[:1], [*COURSES, *EXTRA_COURSES][:last_count]]):
        content = f"Synthetic answer {turn} with **bold**."
        messages.extend([
            {"role": "user", "content": f"Synthetic question {turn}"},
            {"role": "assistant", "content": content, "evidence": copy.deepcopy(evidence),
             "matched_via": "hybrid", "notices": ["program_schedule_unverified"],
             "feedback": {"answer_id": f"{turn:032x}", "feedback_token": "s" * 43,
                          "answer_sha256": hashlib.sha256(content.encode()).hexdigest()}},
        ])
    return messages


def additional_history(name):
    if name == "history-long":
        turns = [("alias", COURSES[:1]), ("context", [*COURSES, *EXTRA_COURSES]),
                 ("program", COURSES), ("alias", COURSES[:1])]
    else:
        assert name == "history-empty-rejected"
        turns = [("empty", []), ("rejected", COURSES[:1])]
    messages = []
    for turn, (tier, evidence) in enumerate(turns):
        answer = {"role": "assistant", "content": f"Synthetic {tier} answer {turn}",
                  "matched_via": tier, "evidence": copy.deepcopy(evidence)}
        if tier == "empty":
            answer["notices"] = ["program_schedule_unverified"]
        messages.extend([{"role": "user", "content": f"Synthetic question {turn}"}, answer])
    return messages


def render_layout_case(name, monkeypatch, backend):
    """One scenario shared by tests and the explicit fixture-generation command."""
    from config import settings

    assert name in SNAPSHOT_NAMES
    monkeypatch.setattr(settings, "public_base_url", "http://localhost:8501")
    captured = capture_layout_messages(monkeypatch)
    if name in ("history", "history-3"):
        monkeypatch.setattr(settings, "answer_feedback_enabled", True)
        app = page(messages=history(3 if name == "history-3" else 4))
        assert len([button for button in app.button if str(button.key).startswith("answer-feedback-")]) == 4
    elif name.startswith("history-"):
        monkeypatch.setattr(settings, "answer_feedback_enabled", False)
        app = page(messages=additional_history(name))
        assert not [button for button in app.button if str(button.key).startswith("answer-feedback-")]
    elif name == "landing":
        import app.discover_view as discover

        monkeypatch.setattr(discover, "render_discover", lambda st: st.markdown(DISCOVER_MARKER))
        app = page()
    else:
        if name == "detail-404":
            original = type(backend).__call__

            def not_found(self, request):
                if request.url.path.startswith("/course/"):
                    self.requests.append((request.method, request.url.path, request.headers.get("authorization")))
                    return httpx.Response(404, json={"detail": "Course not found", "error_type": "not_found"})
                return original(self, request)

            monkeypatch.setattr(type(backend), "__call__", not_found)
        backend.course_status = 500 if name == "detail-500" else 200
        app = page(messages=[{"role": "user", "content": "fixed question"}])
        captured.clear()
        if name != "detail-None":
            app.session_state["selected_course_id"] = "c-algo"
        run(app)
        expected_error = {
            "detail-404": "课程详情加载失败：Course not found",
            "detail-500": "课程详情加载失败：服务暂时出错，请稍后手动重试。",
        }.get(name)
        if expected_error:
            assert [item.value for item in app.error] == [expected_error]
    assert not backend.posts
    return app, captured


def stable_proto(value):
    """Keep user widget keys, omit script form IDs, canonicalize integral proto floats."""
    if isinstance(value, dict):
        result = {key: stable_proto(item) for key, item in value.items() if key != "form_id"}
        widget_id = value.get("id")
        if isinstance(widget_id, str) and widget_id.startswith("$$ID-"):
            result.pop("id")
            key = widget_id.split("-", 2)[-1]
            if key != "None":
                result["key"] = key
        return result
    if isinstance(value, list):
        return [stable_proto(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def layout_snapshot(app, forwarded):
    """Ordered node protos and complete new_element/add_block geometry, relative to chat/detail."""
    metadata = {}
    for message in forwarded:
        if "delta" in message:
            metadata[tuple(message.get("metadata", {}).get("delta_path", []))] = message["delta"]
    rows = []

    def walk(node, absolute, relative):
        proto = MessageToDict(node.proto, preserving_proto_field_name=True) if node.proto is not None else {}
        delta = metadata.get(tuple(absolute), {})
        geometry = {kind: delta[kind] for kind in ("new_element", "add_block") if kind in delta}
        rows.append({"path": relative, "type": node.type, "proto": stable_proto(proto),
                     "delta": stable_proto(geometry)})
        if isinstance(node, Block):
            for index, child in sorted(node.children.items()):
                path = ["chat" if index == 0 else "detail"] if relative == ["columns"] else [*relative, index]
                walk(child, [*absolute, index], path)

    columns = [(index, child) for index, child in app.main.children.items()
               if isinstance(child, Block) and child.type == "flex_container"
               and any(isinstance(item, Block) and item.type == "column" for item in child.children.values())]
    assert len(columns) == 1, "Main chat/detail columns must remain explicit"
    index, node = columns[0]
    walk(node, [0, index], ["columns"])
    return rows


def snapshot_json(rows):
    """One compact node per line; generator output is byte-identical to committed fixtures."""
    return "[\n" + ",\n".join("  " + json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + "\n]\n"
