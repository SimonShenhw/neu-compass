"""K (Z5): the operational log carries a keyed hash and the length of a student's question, never its text.

`query_log` still stores the text; `query_log.written` names the row, and whoever holds the key can match the hash.
中文：运行日志里只有学生问题的带密钥哈希和长度，没有原文；`query_log` 照旧存原文，`query_log.written` 给出行号，
有密钥的人也能用哈希对上。
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import logging
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import structlog
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from api.dependencies import get_chat_stream_fn, get_hyde_rescue_fn
from api.logging import _SafeForeignLogs, configure_logging
from api.query_fields import query_fields
from api.routes.common import log_query
from config import settings
from tests import test_retrieval_decision_parity as parity
from tests.conftest import build_test_app

decision_client = parity.decision_client

ROOT = Path(__file__).resolve().parents[1]
SECRET = "synthetic-log-hash-secret"
CANARY = "zqx7canary"
# Longer than the old 80-character cut, so a hash of a truncated question would not match.
# 中文：比原来截断的 80 个字符长；对截断后的文字算哈希就对不上。
LONG = "graph algorithms " + CANARY + " " + " ".join(f"pad{i}" for i in range(20))
EXPANSION = "This course covers graph algorithms BFS DFS shortest paths."
CONTEXT = {"request_id", "method", "path"}  # bound by the request middleware / 请求中间件绑定的字段
# Every event that carries a question hash, written out: a renamed or dropped event fails the scenario check, and
# a new one fails the comparison with the code (test_the_event_table_is_the_codes_list_of_hash_events).
# 中文：所有带问题哈希的事件，照写一遍：事件改名或消失，场景检查就会失败；新加的事件和代码一比也会失败。
EVENTS = {
    "search.alias_anchor_filtered_fallback", "search.alias_hit", "search.alias_filtered_empty",
    "search.prefilter_applied", "search.hybrid_empty", "search.rejected", "search.hyde_rescued", "search.hybrid",
    "chat.hyde_rescued", "chat.retrieved", "chat.context_path", "chat.alias_anchor_filtered_fallback",
    "chat.prefilter_applied", "rescue.code_pattern_guard", "rescue.declined", "rescue.empty_retrieval",
    "rescue.accepted",
}


def documented(secret: str, text: str) -> str:
    # Written out, not imported: this construction is how an operator matches a query_log row to its log lines.
    # 中文：照写一遍、不从模块导入：运维就是按这个算法把 query_log 的一行和日志对上的。
    key = hmac.new(secret.encode("utf-8", "surrogatepass"), b"neu-compass/log-query-hash/v1", hashlib.sha256).digest()
    return hmac.new(key, text.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


@pytest.fixture
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "session_secret", SECRET)


@pytest.fixture
def app_and_db(empty_db: sqlite3.Connection, secret: None):
    app = build_test_app(empty_db, seed=True)
    app.dependency_overrides[get_chat_stream_fn] = lambda: (lambda prompt: iter(["ok"]))
    with TestClient(app) as client:
        yield client, empty_db


def _capture():
    # merge_contextvars as in production: a question bound to the request context shows up here too.
    # 中文：和线上一样合并 contextvars：绑到请求上下文里的问题也会出现在这里。
    return capture_logs(processors=[structlog.contextvars.merge_contextvars])


def _post(client: TestClient, path: str, body: dict) -> tuple[dict | str, list[dict]]:
    with _capture() as entries:
        response = client.post(path, json=body)
    assert response.status_code == 200, response.text
    return (response.json() if path == "/search" else response.text), entries


def _one(entries: list[dict], event: str) -> dict:
    found = [entry for entry in entries if entry["event"] == event]
    assert len(found) == 1, (event, [entry["event"] for entry in entries])
    return found[0]


def _text_free(entries: list[dict]) -> None:
    assert entries
    assert CANARY not in repr(entries)
    assert [entry["event"] for entry in entries if {"query", "sanitized_query"} & entry.keys()] == []


# --- the helper ---------------------------------------------------------------------------------------------


def test_fields_are_a_keyed_hash_and_the_length(secret: None) -> None:
    fields = query_fields(LONG)
    assert fields == {"query_hash": documented(SECRET, LONG), "query_len": len(LONG)}
    assert len(fields["query_hash"]) == 16 and set(fields["query_hash"]) <= set("0123456789abcdef")


def test_named_fields_count_characters(secret: None) -> None:
    assert query_fields("数据科学的课", "sanitized_query") == {
        "sanitized_query_hash": documented(SECRET, "数据科学的课"), "sanitized_query_len": 6}


def test_surrounding_spaces_count_and_change_the_hash(secret: None) -> None:
    assert query_fields(CANARY + " ") == {"query_hash": documented(SECRET, CANARY + " "), "query_len": len(CANARY) + 1}
    assert query_fields(CANARY + " ")["query_hash"] != query_fields(CANARY)["query_hash"]


def test_a_short_question_cannot_be_confirmed_by_hashing_guesses(secret: None) -> None:
    text = "CS 5800 先修是什么"
    digest = query_fields(text)["query_hash"]
    # Not a plain hash anyone can recompute, and not keyed by the session secret itself.
    # 中文：不是谁都能重算的普通哈希，也不是直接拿会话密钥当密钥。
    assert digest != hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    assert digest != hmac.new(SECRET.encode("utf-8"), text.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def test_another_secret_or_another_question_gives_another_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "session_secret", "synthetic-one")
    one = query_fields(CANARY)["query_hash"]
    assert query_fields(CANARY)["query_hash"] == one
    assert query_fields(CANARY + " ")["query_hash"] != one
    monkeypatch.setattr(settings, "session_secret", "synthetic-two")
    assert query_fields(CANARY)["query_hash"] != one


def test_an_unpaired_surrogate_does_not_raise(secret: None) -> None:
    fields = query_fields("a\ud800b")
    assert fields["query_len"] == 3 and len(fields["query_hash"]) == 16


@pytest.mark.parametrize("odd", ["synthetic-\udcff", "synthetic-\ud800"])
def test_a_secret_with_a_stray_byte_still_hashes(monkeypatch: pytest.MonkeyPatch, odd: str) -> None:
    # os.environ turns an undecodable byte into a surrogate; a strict encode would fail every request.
    # 中文：环境变量里解不开的字节会变成代理字符；严格编码的话每个请求都会失败。
    monkeypatch.setattr(settings, "session_secret", odd)
    assert query_fields(CANARY) == {"query_hash": documented(odd, CANARY), "query_len": len(CANARY)}


def test_without_a_secret_each_process_has_its_own_random_key(monkeypatch: pytest.MonkeyPatch,
                                                              tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "session_secret", "")
    here = query_fields(CANARY)["query_hash"]
    assert query_fields(CANARY)["query_hash"] == here
    assert here != hashlib.sha256(CANARY.encode("utf-8")).hexdigest()[:16]
    assert here != documented("", CANARY)
    code = f"from api.query_fields import query_fields; print(query_fields({CANARY!r})['query_hash'])"
    # A minimal environment: the child needs no secret, no .env and nothing else from this process.
    # 中文：最小环境：子进程不需要密钥、.env，也不需要本进程的其他环境变量。
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT), "HOME": str(tmp_path), "SESSION_SECRET": "",
           "GEMINI_API_KEY": "ci-placeholder-not-a-secret", "PYTHONDONTWRITEBYTECODE": "1"}
    others = [subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True,
                             check=True, timeout=60).stdout.strip() for _ in range(2)]
    assert all(len(other) == 16 for other in others)
    assert len({here, *others}) == 3


# --- every log, bind, print, warn and stream-write call in product code -------------------------------------

_LEVELS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "fatal", "msg", "log"}
EVENT_METHODS = _LEVELS | {"a" + name for name in _LEVELS}  # and structlog's async forms: ainfo, alog, ...
LEVEL_FIRST = {"log", "alog"}  # log.log(level, event, ...)
BIND_METHODS = {"bind", "new", "bind_contextvars", "bound_contextvars", "bind_threadlocal"}
BARE_CALLS = {"print", "warn", "bind_contextvars", "bound_contextvars", "bind_threadlocal"}
STREAMS = {"sys.stdout", "sys.stderr", "sys.__stdout__", "sys.__stderr__"}
TEXT_KEYWORDS = {"query", "sanitized_query", "question", "prompt", "message", "text", "q"}
TEXT_SOURCES = {"query", "sanitized_query", "question", "prompt", "retrieval_query", "combined", "expansion",
                "history", "messages", "content", "text"}
# ** splats with known keys: the hash helper and the error-field helpers, none of which copies a message.
# 中文：键是已知的 ** 展开：哈希函数和几个错误字段函数，它们都不抄错误消息。
SAFE_SPLATS = {"query_fields", "safe_error_fields", "error_log_fields", "log_fields"}
# Two error events splat a dict built just before the call from error fields only (checked by hand).
# 中文：两个错误事件展开的是调用前刚建好的字典，里面只有错误字段（人工核对过）。
CHECKED_SPLATS = {("chat.stream_failed", "fields"), ("rescue.failed", "where")}


def _is_log_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Name):
        return node.func.id in BARE_CALLS
    if not isinstance(node.func, ast.Attribute):
        return False
    owner, method = ast.unparse(node.func.value), node.func.attr
    if method in {"write", "writelines"}:
        return owner in STREAMS
    if owner in {"builtins", "warnings"}:
        return method in {"print", "warn"}
    return method in EVENT_METHODS | BIND_METHODS and "log" in owner.lower()


def _is_wrapper(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and (getattr(node.func, "id", None) == "query_fields"
                                           or getattr(node.func, "attr", None) == "query_fields")


def _raw_uses(node: ast.AST) -> list[str]:
    """Names or attributes that hold question text, outside a `query_fields(...)` call."""
    if _is_wrapper(node):
        return []
    found = []
    if isinstance(node, ast.Name) and node.id in TEXT_SOURCES:
        found.append(node.id)
    if isinstance(node, ast.Attribute) and node.attr in TEXT_SOURCES:
        found.append(ast.unparse(node))
    for child in ast.iter_child_nodes(node):
        found += _raw_uses(child)
    return found


def _constant_event(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    return isinstance(node, ast.IfExp) and _constant_event(node.body) and _constant_event(node.orelse)


def _splat_problems(value: ast.AST, event: ast.AST | None) -> list[str]:
    """A ** splat needs keys that can be read here: a dict literal or dict(...), a known helper, or a checked dict.

    中文：** 展开的键必须在这里看得出来：字典字面量或 dict(...)、已知的辅助函数，或人工核对过的字典。
    """
    if isinstance(value, ast.Dict):
        return [f"**{{{key.value!r}: ...}}" for key in value.keys
                if isinstance(key, ast.Constant) and key.value in TEXT_KEYWORDS]
    if (isinstance(value, ast.Call) and getattr(value.func, "id", None) == "dict" and not value.args
            and all(keyword.arg for keyword in value.keywords)):
        return [f"**dict({keyword.arg}=...)" for keyword in value.keywords if keyword.arg in TEXT_KEYWORDS]
    if isinstance(value, ast.Call) and {getattr(value.func, "id", None), getattr(value.func, "attr", None)} & SAFE_SPLATS:
        return []
    if isinstance(value, ast.Name) and isinstance(event, ast.Constant) and (event.value, value.id) in CHECKED_SPLATS:
        return []
    return [f"**{ast.unparse(value)}: keys unknown"]


def problems(call: ast.Call) -> list[str]:
    """Why this log, bind, print, warn or stream-write call could carry question text; empty when it cannot.

    中文：这个日志、绑定、print、warn 或写 stdout／stderr 的调用为什么可能带出问题原文；带不出时返回空列表。
    """
    found, values, event = [], list(call.args), None
    method = getattr(call.func, "attr", None)
    if method in EVENT_METHODS:  # warnings.warn too: its message is the event / warnings.warn 的消息也算事件名
        position = 1 if method in LEVEL_FIRST else 0
        event = values.pop(position) if len(values) > position else None
        if not _constant_event(event):
            found.append("event name is not a constant string")
    for keyword in call.keywords:
        if keyword.arg in TEXT_KEYWORDS:
            found.append(f"{keyword.arg}=")
        if keyword.arg is None:
            found += _splat_problems(keyword.value, event)
        values.append(keyword.value)
    return found + [use for value in values for use in _raw_uses(value)]


def test_no_log_bind_or_print_call_in_product_code_passes_question_text() -> None:
    calls, found = 0, []
    for folder in ("api", "app", "rag", "llm", "db", "schemas", "config"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if _is_log_call(node):
                    calls += 1
                    found += [f"{path.relative_to(ROOT).as_posix()}:{node.lineno} {what}" for what in problems(node)]
    assert calls > 60, calls  # the walk really found the log calls
    assert found == [], "log question text only through query_fields(...), or rename the field"


@pytest.mark.parametrize("source", [
    'log.info("chat.retrieved", query=req.query)',
    'log.info("x", q=req.query[:80])',
    'log.info("x", sanitized=extracted.sanitized_query[:80])',
    'log.info("x", n=len(query))',
    'log.info(f"rescue.code_pattern_guard {query[:80]}")',
    'log.info("x %s" % query)',
    'log.info("x", **{"query": q})',
    'log.info("x", retry=combined[:80])',
    'log.info("x", tail=req.history[-1].content[:80])',
    'log.bind(question=query).info("rescue.empty_retrieval", **query_fields(query))',
    'structlog.contextvars.bind_contextvars(query=req.query)',
    'bind_contextvars(query=req.query)',
    'print("search.hybrid", req.query[:80])',
    'log.log(20, "search.debug", detail=req.query)',
    'log.fatal("x", note=req.query)',
    'log.ainfo("x", note=req.query)',
    'warnings.warn(req.query)',
    'warn(f"slow {query}")',
    'sys.stderr.write(req.query)',
    'sys.stdout.write(query[:80])',
    'builtins.print(req.query)',
    'log.info("x", **dict(query=q))',
    'log.info("x", **extra)',
    'structlog.threadlocal.bind_threadlocal(question=q)',
])
def test_the_guard_catches_the_old_and_the_bound_forms(source: str) -> None:
    calls = [node for node in ast.walk(ast.parse(source)) if _is_log_call(node)]
    assert calls and any(problems(call) for call in calls), source


@pytest.mark.parametrize("source", [
    'log.info("search.alias_hit" if results else "search.alias_filtered_empty", **query_fields(req.query), count=1)',
    'log.info("x", **qf.query_fields(extracted.sanitized_query, "sanitized_query"))',
    'structlog.contextvars.bind_contextvars(request_id=request_id, method=request.method, path=request.url.path)',
    'print("fixed text")',
    'log.log(logging.INFO, "search.hybrid", **query_fields(req.query))',
    'log.warning("rescue.failed", **error_log_fields(e), **where)',
    'warnings.warn("fixed text")',
    'sys.stderr.write("fixed text")',
])
def test_the_guard_lets_text_free_forms_through(source: str) -> None:
    calls = [node for node in ast.walk(ast.parse(source)) if _is_log_call(node)]
    assert calls and not any(problems(call) for call in calls), source


def _hash_events() -> set[str]:
    """Event names of the product log calls that splat `query_fields(...)`, read from the code.

    中文：产品代码里展开 `query_fields(...)` 的日志调用用的事件名，从代码里读出来。
    """
    names: set[str] = set()
    for folder in ("api", "app", "rag", "llm", "db", "schemas", "config"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (_is_log_call(node) and getattr(node.func, "attr", None) in EVENT_METHODS
                        and any(keyword.arg is None and _is_wrapper(keyword.value) for keyword in node.keywords)):
                    event = node.args[1 if node.func.attr in LEVEL_FIRST else 0]
                    options = [event] if isinstance(event, ast.Constant) else [event.body, event.orelse]
                    names |= {option.value for option in options}
    return names


def test_the_event_table_is_the_codes_list_of_hash_events() -> None:
    # A new event that logs a question hash must join EVENTS, and so a scenario must reach it.
    # 中文：新加一个记问题哈希的事件，就得加进 EVENTS，也就得有场景走到它。
    assert _hash_events() == EVENTS


# --- the routes, on every branch that logs a question hash ---------------------------------------------------

# Every scenario question is longer than 80 characters, and the ones with a course code mix cases, so a hash over
# a cut or case-changed copy does not match.
# 中文：每个场景的问题都超过 80 个字符，带课号的那些大小写混排；对截断或改了大小写的文字算哈希就对不上。
TAIL = " " + " ".join(f"pad{i}" for i in range(16))
# id, route, query, extra request fields, world set-up, events that must each appear once.
# 中文：编号、路由、问题、其他请求字段、场景设置、必须各出现一次的事件。
SCENARIOS = [
    ("search-hybrid", "/search", f"opaque topic {CANARY}{TAIL}", {}, {}, ["search.hybrid"]),
    ("search-prefix", "/search", f"CS opaque topic {CANARY}{TAIL}", {}, {},
     ["search.prefilter_applied", "search.hybrid"]),
    ("search-alias", "/search", f"CS 5800 {CANARY}{TAIL}", {}, {}, ["search.alias_hit"]),
    ("search-alias-filtered", "/search", f"CS 5800 {CANARY}{TAIL}", {"credits": 3}, {},
     ["search.alias_filtered_empty"]),
    ("search-anchor", "/search", f"planning courses like CS 5800 {CANARY}{TAIL}", {"credits": 3}, {},
     ["search.alias_anchor_filtered_fallback", "search.prefilter_applied", "search.hybrid_empty"]),
    ("search-declined", "/search", f"opaque topic {CANARY}{TAIL}", {}, {"rescue": "decline"},
     ["rescue.declined", "search.rejected"]),
    ("search-rescued", "/search", f"CS opaque topic {CANARY}{TAIL}", {}, {"rescue": "expand"},
     ["search.prefilter_applied", "rescue.accepted", "search.hyde_rescued", "search.hybrid"]),
    ("search-rescue-empty", "/search", f"opaque topic {CANARY}{TAIL}", {}, {"rescue": "expand", "empty_retry": True},
     ["rescue.empty_retrieval", "search.rejected"]),
    ("search-code-guard", "/search", f"CS 9999 {CANARY}{TAIL}", {}, {"rescue": "expand"},
     ["search.prefilter_applied", "rescue.code_pattern_guard", "search.rejected"]),
    ("chat-hybrid", "/chat", f"opaque topic {CANARY}{TAIL}", {}, {}, ["chat.retrieved"]),
    ("chat-prefix", "/chat", f"CS opaque topic {CANARY}{TAIL}", {}, {}, ["chat.prefilter_applied", "chat.retrieved"]),
    ("chat-context", "/chat", f"this course please {CANARY}{TAIL}", {"context_course_ids": [parity.IDS[0]]}, {},
     ["chat.context_path", "chat.retrieved"]),
    ("chat-anchor", "/chat", f"planning courses like CS 5800 {CANARY}{TAIL}", {"credits": 3}, {},
     ["chat.alias_anchor_filtered_fallback", "chat.prefilter_applied", "chat.retrieved"]),
    ("chat-rescued", "/chat", f"CS opaque topic {CANARY}{TAIL}", {}, {"rescue": "expand"},
     ["chat.prefilter_applied", "rescue.accepted", "chat.hyde_rescued", "chat.retrieved"]),
    # Earlier turns carry the canary too: they go to the prompt, never to a log line.
    # 中文：前几轮对话里也有标记：它们只进提示词，不进日志。
    ("chat-history", "/chat", f"opaque topic {CANARY}{TAIL}",
     {"history": [{"role": "user", "content": f"an earlier question {CANARY}"},
                  {"role": "assistant", "content": f"an earlier answer {CANARY}"}]}, {}, ["chat.retrieved"]),
]
ARGS = "name, route, query, extra, setup, events"


def _arrange(state, setup: dict) -> None:
    if "rescue" in setup:
        state.reranker.scores = [0.0] * 3  # rejected first, so the rescue runs / 先被拒答，救援才会运行
        state.enable_rescue()
        state.rescue_mode = setup["rescue"]
        state.hybrid.empty_retry = setup.get("empty_retry", False)


def _sanitized(query: str) -> str:
    # The program prefix the scenarios use is "CS"; the extractor removes it and collapses spaces.
    # 中文：场景里的专业前缀都是 "CS"；抽取器去掉它并合并空格。
    return " ".join(query.replace("CS", "", 1).split())


def test_the_scenarios_reach_every_event_that_logs_a_question() -> None:
    assert {event for *_, events in SCENARIOS for event in events} == EVENTS
    assert min(len(query) for _, _, query, *_ in SCENARIOS) > 80


@pytest.mark.parametrize(ARGS, SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_every_event_hashes_the_stored_text_and_carries_none_of_it(decision_client, secret, capfd, name, route,
                                                                    query, extra, setup, events) -> None:
    state = decision_client
    _arrange(state, setup)
    with _capture() as entries:
        response = state.client.post(route, json={"query": query, "k": 1, **extra})
    assert response.status_code == 200, response.text
    out, err = capfd.readouterr()
    assert CANARY not in out + err  # print() would reach the container log / print 会进容器日志
    _text_free(entries)
    [row] = state.conn.execute("SELECT log_id, query FROM query_log").fetchall()
    assert row["query"] == query
    for event in events:
        # Each expected event carries its own hash fields under their names, not some other spelling.
        # 中文：每个预期事件都要带自己的哈希字段，字段名也不能换。
        fields = ("sanitized_query_hash", "sanitized_query_len") if event.endswith(".prefilter_applied") else (
            "query_hash", "query_len")
        assert set(fields) <= _one(entries, event).keys(), event
    for entry in entries:
        if "query_hash" in entry:
            assert (entry["query_hash"], entry["query_len"]) == (documented(SECRET, query), len(query)), entry["event"]
        if "sanitized_query_hash" in entry:
            sanitized = _sanitized(query)
            assert (entry["sanitized_query_hash"], entry["sanitized_query_len"]) == (
                documented(SECRET, sanitized), len(sanitized)), entry["event"]
    written = _one(entries, "query_log.written")
    assert {key: value for key, value in written.items() if key not in CONTEXT} == {
        "event": "query_log.written", "log_level": "info", "query_log_id": row["log_id"]}


@pytest.fixture
def real_logging() -> None:
    # During setup, so pytest's call-phase capture handler is installed after it (the set-up resets root handlers).
    # 中文：在 setup 阶段配置：配置会重置 root handler，pytest 在调用阶段才装自己的捕获 handler。
    configure_logging()


@pytest.mark.parametrize(ARGS, SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_the_rendered_log_lines_carry_no_question_text(real_logging, decision_client, secret, caplog, name, route,
                                                       query, extra, setup, events) -> None:
    state = decision_client
    _arrange(state, setup)
    response = state.client.post(route, json={"query": query, "k": 1, **extra})
    assert response.status_code == 200, response.text
    lines = [record.getMessage() for record in caplog.records]
    rendered = "\n".join(lines)
    assert all(event in rendered for event in [*events, "query_log.written"]), rendered
    assert [line for line in lines if CANARY in line] == []


def test_a_library_info_message_is_replaced_before_any_handler_sees_it() -> None:
    record = logging.LogRecord("httpx", logging.INFO, __file__, 1, "GET %s",
                               (f"https://example.invalid/?q={CANARY}",), None)
    assert _SafeForeignLogs(structlog.processors.JSONRenderer()).filter(record) is True
    assert CANARY not in record.getMessage() and '"event": "stdlib.log"' in record.getMessage()


def test_a_failed_write_logs_no_row_id(app_and_db, monkeypatch: pytest.MonkeyPatch) -> None:
    from db.query_log_repository import QueryLogRepository  # noqa: PLC0415

    def broken(self, **kwargs):
        raise sqlite3.OperationalError(f"synthetic failure for {CANARY}")

    monkeypatch.setattr(QueryLogRepository, "add", broken)
    client, _ = app_and_db
    _, entries = _post(client, "/search", {"query": LONG, "k": 3})
    _text_free(entries)
    assert [entry["event"] for entry in entries if entry["event"].startswith("query_log.")] == ["query_log.write_failed"]


def test_a_failed_commit_logs_no_row_id(empty_db: sqlite3.Connection) -> None:
    # A rolled-back row has no id worth reporting, so query_log.written comes only after the commit.
    # 中文：回滚了的行没有可报的行号，所以 query_log.written 只在 commit 之后记。
    class CommitFails:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self._conn = conn

        def __getattr__(self, name: str) -> object:
            return getattr(self._conn, name)

        def commit(self) -> None:
            raise sqlite3.OperationalError(f"synthetic commit failure for {CANARY}")

    with _capture() as entries:
        log_id = log_query(CommitFails(empty_db), route="search", query=LONG, matched_via="hybrid", k=3,
                           latency_ms=1.0)
    assert log_id is None
    _text_free(entries)
    assert [entry["event"] for entry in entries if entry["event"].startswith("query_log.")] == ["query_log.write_failed"]


# --- the earlier route checks on the plain test app ---------------------------------------------------------


def test_search_logs_the_hash_and_query_log_keeps_the_text_that_matches_it(app_and_db) -> None:
    client, conn = app_and_db
    body, entries = _post(client, "/search", {"query": LONG, "k": 3})
    assert body["matched_via"] == "hybrid" and body["results"]
    _text_free(entries)
    event = _one(entries, "search.hybrid")
    assert (event["query_hash"], event["query_len"]) == (documented(SECRET, LONG), len(LONG))
    [row] = conn.execute("SELECT log_id, query FROM query_log").fetchall()
    assert row["query"] == LONG and documented(SECRET, row["query"]) == event["query_hash"]
    assert _one(entries, "query_log.written")["query_log_id"] == row["log_id"]


def test_search_prefilter_hashes_the_sanitized_question(app_and_db) -> None:
    client, _ = app_and_db
    _, entries = _post(client, "/search", {"query": "CS " + LONG, "k": 3})
    _text_free(entries)
    event = _one(entries, "search.prefilter_applied")
    assert event["program_prefix"] == "CS"
    assert (event["sanitized_query_hash"], event["sanitized_query_len"]) == (documented(SECRET, LONG), len(LONG))
    assert _one(entries, "search.hybrid")["query_hash"] == documented(SECRET, "CS " + LONG)


def test_search_alias_path_logs_the_hash(app_and_db) -> None:
    client, _ = app_and_db
    query = "CS 5800 " + CANARY
    body, entries = _post(client, "/search", {"query": query, "k": 3})
    assert body["matched_via"] == "alias"
    _text_free(entries)
    assert _one(entries, "search.alias_hit")["query_hash"] == documented(SECRET, query)


@pytest.mark.parametrize("expansion, events", [
    (None, ("rescue.declined", "search.rejected")),
    (EXPANSION, ("rescue.accepted", "search.hyde_rescued", "search.hybrid")),
])
def test_rejected_and_rescued_searches_log_the_hash(app_and_db, expansion, events) -> None:
    client, _ = app_and_db
    client.app.dependency_overrides[get_hyde_rescue_fn] = lambda: (lambda q: expansion)
    query = CANARY + " nonexistent topic"
    _, entries = _post(client, "/search", {"query": query, "k": 3})
    _text_free(entries)
    for name in events:
        event = _one(entries, name)
        assert (event["query_hash"], event["query_len"]) == (documented(SECRET, query), len(query)), name


def test_chat_logs_the_hash_and_query_log_keeps_the_text(app_and_db) -> None:
    client, conn = app_and_db
    _, entries = _post(client, "/chat", {"query": LONG, "k": 3})
    _text_free(entries)
    event = _one(entries, "chat.retrieved")
    assert (event["query_hash"], event["query_len"]) == (documented(SECRET, LONG), len(LONG))
    [row] = conn.execute("SELECT query FROM query_log").fetchall()
    assert row["query"] == LONG


def test_chat_prefilter_and_context_paths_log_the_hash(app_and_db) -> None:
    client, _ = app_and_db
    _, entries = _post(client, "/chat", {"query": "CS " + LONG, "k": 3})
    _text_free(entries)
    assert _one(entries, "chat.prefilter_applied")["sanitized_query_hash"] == documented(SECRET, LONG)
    followup = "what are the prerequisites of this course " + CANARY
    _, entries = _post(client, "/chat", {"query": followup, "k": 3, "context_course_ids": ["c-cs-5800"]})
    _text_free(entries)
    assert _one(entries, "chat.context_path")["query_hash"] == documented(SECRET, followup)
    assert _one(entries, "chat.retrieved")["query_hash"] == documented(SECRET, followup)
