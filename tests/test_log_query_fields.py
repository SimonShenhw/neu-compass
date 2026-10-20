"""K (Z5): the operational log carries a keyed hash and the length of a student's question, never its text.

`query_log` still stores the text, and its row can be matched to the log lines with the key.
中文：运行日志里只有学生问题的带密钥哈希和长度，没有原文；`query_log` 照旧存原文，有密钥就能对上日志行。
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from api.dependencies import get_chat_stream_fn, get_hyde_rescue_fn
from api.query_fields import query_fields
from config import settings
from tests.conftest import build_test_app

ROOT = Path(__file__).resolve().parents[1]
SECRET = "synthetic-log-hash-secret"
CANARY = "zqx7canary"
# Longer than the old 80-character cut, so a hash of a truncated question would not match.
# 中文：比原来截断的 80 个字符长；对截断后的文字算哈希就对不上。
LONG = "graph algorithms " + CANARY + " " + " ".join(f"pad{i}" for i in range(20))
EXPANSION = "This course covers graph algorithms BFS DFS shortest paths."


def documented(secret: str, text: str) -> str:
    # Written out, not imported: this construction is how an operator matches a query_log row to its log lines.
    # 中文：照写一遍、不从模块导入：运维就是按这个算法把 query_log 的一行和日志对上的。
    key = hmac.new(secret.encode("utf-8"), b"neu-compass/log-query-hash/v1", hashlib.sha256).digest()
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


def _post(client: TestClient, path: str, body: dict) -> tuple[dict | str, list[dict]]:
    with capture_logs() as entries:
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


def test_a_short_question_cannot_be_confirmed_from_the_log_alone(secret: None) -> None:
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


def test_without_a_secret_each_process_has_its_own_random_key(monkeypatch: pytest.MonkeyPatch,
                                                              tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "session_secret", "")
    here = query_fields(CANARY)["query_hash"]
    assert query_fields(CANARY)["query_hash"] == here
    assert here != hashlib.sha256(CANARY.encode("utf-8")).hexdigest()[:16]
    assert here != documented("", CANARY)
    code = f"from api.query_fields import query_fields; print(query_fields({CANARY!r})['query_hash'])"
    env = {**os.environ, "SESSION_SECRET": "", "PYTHONPATH": str(ROOT)}
    others = [subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True,
                             check=True, timeout=60).stdout.strip() for _ in range(2)]
    assert all(len(other) == 16 for other in others)
    assert len({here, *others}) == 3


# --- every log call in product code -------------------------------------------------------------------------

LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "msg"}
TEXT_KEYWORDS = {"query", "sanitized_query", "question", "prompt", "message", "text", "q"}
TEXT_SOURCES = {"query", "sanitized_query", "question", "prompt"}


def _raw_uses(node: ast.AST) -> list[str]:
    """Names or attributes holding question text, outside a `query_fields(...)` call."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "query_fields":
        return []
    found = []
    if isinstance(node, ast.Name) and node.id in TEXT_SOURCES:
        found.append(node.id)
    if isinstance(node, ast.Attribute) and node.attr in TEXT_SOURCES:
        found.append(ast.unparse(node))
    for child in ast.iter_child_nodes(node):
        found += _raw_uses(child)
    return found


def test_no_log_call_in_product_code_passes_question_text() -> None:
    calls, problems = 0, []
    for folder in ("api", "app", "rag", "llm", "db", "schemas", "config"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in LOG_METHODS and "log" in ast.unparse(node.func.value).lower()):
                    continue
                calls += 1
                where = f"{path.relative_to(ROOT).as_posix()}:{node.lineno}"
                problems += [f"{where} {kw.arg}=" for kw in node.keywords if kw.arg in TEXT_KEYWORDS]
                problems += [f"{where} {use}" for value in [*node.args[1:], *(kw.value for kw in node.keywords)]
                             for use in _raw_uses(value)]
    assert calls > 60, calls  # the walk really found the log calls
    assert problems == []


def test_the_guard_catches_the_old_forms() -> None:
    for source in ('log.info("chat.retrieved", query=req.query)', 'log.info("x", q=req.query[:80])',
                   'log.info("x", sanitized=extracted.sanitized_query[:80])', 'log.info("x", n=len(query))'):
        call = ast.parse(source).body[0].value
        found = [kw.arg for kw in call.keywords if kw.arg in TEXT_KEYWORDS]
        found += [use for kw in call.keywords for use in _raw_uses(kw.value)]
        assert found, source
    assert _raw_uses(ast.parse('f(**query_fields(req.query), count=len(hits))').body[0].value) == []


# --- the routes ---------------------------------------------------------------------------------------------


def test_search_logs_the_hash_and_query_log_keeps_the_text_that_matches_it(app_and_db) -> None:
    client, conn = app_and_db
    body, entries = _post(client, "/search", {"query": LONG, "k": 3})
    assert body["matched_via"] == "hybrid" and body["results"]
    _text_free(entries)
    event = _one(entries, "search.hybrid")
    assert (event["query_hash"], event["query_len"]) == (documented(SECRET, LONG), len(LONG))
    [row] = conn.execute("SELECT query FROM query_log").fetchall()
    assert row["query"] == LONG and documented(SECRET, row["query"]) == event["query_hash"]


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
