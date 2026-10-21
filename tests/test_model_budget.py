"""Batch T, policy P5: at most MODEL_DAILY_CALL_LIMIT Gemini calls per UTC day (the user chose 200).

Chat answers and HyDE rescues take a place right before the model call; with none left, /chat streams a fixed
`daily_limit` error after the meta and never calls the model, and a rescue keeps the original rejection.
Synthetic data only; the model is always a fake.
"""

from __future__ import annotations

import json
import os
import threading

import pytest
from structlog.testing import capture_logs

from api import model_budget as mb
from api.dependencies import get_chat_stream_fn, get_model_budget


class Day:
    def __init__(self, value="2026-10-21"):
        self.value = value

    def __call__(self):
        return self.value


def budget(tmp_path, limit=3, day=None):
    return mb.ModelBudget(tmp_path / mb.FILENAME, limit, today=day or Day())


def test_places_run_out_at_the_limit_and_come_back_the_next_day(tmp_path):
    day = Day()
    b = budget(tmp_path, 3, day)
    assert [b.acquire() for _ in range(4)] == [True, True, True, False]
    assert b.used() == 3
    day.value = "2026-10-22"
    assert b.used() == 0 and b.acquire() is True and b.used() == 1
    assert json.loads((tmp_path / mb.FILENAME).read_text(encoding="utf-8")) == {"day": "2026-10-22", "calls": 1}


def test_the_count_survives_a_restart(tmp_path):
    first = budget(tmp_path, 3)
    assert first.acquire() and first.acquire()
    second = budget(tmp_path, 3)
    assert second.used() == 2
    assert [second.acquire(), second.acquire()] == [True, False]


@pytest.mark.parametrize("content", ['not json', '{"day": "2026-10-21"}', '{"day": "2026-10-21", "calls": -1}',
                                     '{"day": "2026-10-21", "calls": true}', '{"day": 5, "calls": 1}', '[1, 2]'])
def test_an_unreadable_file_starts_from_zero_and_is_rewritten(tmp_path, content):
    (tmp_path / mb.FILENAME).write_text(content, encoding="utf-8")
    b = budget(tmp_path, 2)
    assert b.used() == 0 and b.acquire()
    assert json.loads((tmp_path / mb.FILENAME).read_text(encoding="utf-8")) == {"day": "2026-10-21", "calls": 1}


def test_an_unwritable_place_still_enforces_the_cap_in_memory_and_warns_once(tmp_path):
    missing = tmp_path / "no-such-directory"
    b = mb.ModelBudget(missing / mb.FILENAME, 2, today=Day())
    with capture_logs() as logs:
        assert [b.acquire(), b.acquire(), b.acquire()] == [True, True, False]
    assert [entry["event"] for entry in logs] == ["model_budget.write_failed", "model_budget.exhausted"]
    assert logs[0]["exc_type"] == "FileNotFoundError" and not missing.exists()


def test_exhaustion_is_logged_once_a_day_without_any_question_text(tmp_path):
    day = Day()
    b = budget(tmp_path, 1, day)
    b.acquire()
    with capture_logs() as logs:
        b.acquire(), b.acquire()
        day.value = "2026-10-22"
        b.acquire(), b.acquire()
    assert logs == [{"event": "model_budget.exhausted", "day": "2026-10-21", "limit": 1, "log_level": "warning"},
                    {"event": "model_budget.exhausted", "day": "2026-10-22", "limit": 1, "log_level": "warning"}]


def test_concurrent_calls_never_take_more_places_than_the_limit(tmp_path):
    b = budget(tmp_path, 50)
    results, lock = [], threading.Lock()

    def worker():
        for _ in range(10):
            ok = b.acquire()
            with lock:
                results.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 50 and b.used() == 50
    assert sorted(os.listdir(tmp_path)) == [mb.FILENAME]  # no temporary files left


@pytest.mark.parametrize("limit", [0, -1, True, 2.0])
def test_a_budget_needs_a_whole_limit_of_at_least_one(tmp_path, limit):
    with pytest.raises(ValueError):
        mb.ModelBudget(tmp_path / mb.FILENAME, limit)


def test_dependency_is_off_at_zero_and_shared_per_database(monkeypatch, tmp_path):
    from config import settings

    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "synthetic.sqlite3"))
    monkeypatch.setattr(settings, "model_daily_call_limit", 0)
    assert get_model_budget() is None
    monkeypatch.setattr(settings, "model_daily_call_limit", 200)
    first, second = get_model_budget(), get_model_budget()
    assert first is second and first.limit == 200 and first.path == (tmp_path / mb.FILENAME).resolve()


@pytest.mark.parametrize("value", ["true", "-1", "100001", "1.5"])
def test_limit_setting_rejects_booleans_and_bad_numbers(monkeypatch, value):
    from config.settings import Settings
    from pydantic import ValidationError

    monkeypatch.setenv("MODEL_DAILY_CALL_LIMIT", value)
    with pytest.raises(ValidationError):
        Settings()
    monkeypatch.setenv("MODEL_DAILY_CALL_LIMIT", "200")
    assert Settings().model_daily_call_limit == 200


# === HyDE rescue ===


def test_rescue_takes_a_place_only_when_it_calls_the_model(monkeypatch, tmp_path):
    import rag.hyde as hyde
    from api.dependencies import get_hyde_rescue_fn
    from config import settings

    calls = []
    monkeypatch.setattr(hyde, "rescue_expand", lambda query: calls.append(query) or "synthetic expansion")
    monkeypatch.setattr(settings, "hyde_rescue", True)
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "synthetic.sqlite3"))
    monkeypatch.setattr(settings, "model_daily_call_limit", 1)
    rescue = get_hyde_rescue_fn()
    assert rescue("synthetic borderline question") == "synthetic expansion"
    with pytest.raises(mb.ModelBudgetExhausted):
        rescue("synthetic second question")
    assert calls == ["synthetic borderline question"]
    monkeypatch.setattr(settings, "model_daily_call_limit", 0)
    assert get_hyde_rescue_fn() is hyde.rescue_expand


def test_a_rescue_without_a_place_keeps_the_rejection_and_says_why(empty_db):
    from api.routes import common

    def no_place(query):
        raise mb.ModelBudgetExhausted

    with capture_logs() as logs:
        result = common.attempt_hyde_rescue(query="synthetic vague question about learning", rescue_fn=no_place,
                                            hybrid=None, reranker=None, conn=empty_db, hard_filters={},
                                            pool_size=10, blend_alpha=0.4, top_k=10)
    assert result is None
    assert [entry["event"] for entry in logs] == ["rescue.skipped"]
    assert logs[0]["reason"] == "model_daily_limit" and "synthetic vague" not in json.dumps(logs)


# === /chat ===


def events(response):
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_chat_without_a_place_streams_meta_then_the_fixed_notice_and_never_calls_the_model(api_client, tmp_path):
    from api.routes import chat as chat_route

    used = mb.ModelBudget(tmp_path / mb.FILENAME, 1, today=Day())
    assert used.acquire()
    called = []
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: (lambda prompt: called.append(prompt) or iter(["x"]))
    api_client.app.dependency_overrides[get_model_budget] = lambda: used
    try:
        stream = events(api_client.post("/chat", json={"query": "graph algorithms BFS"}))
    finally:
        api_client.app.dependency_overrides.pop(get_model_budget, None)
    assert [e["type"] for e in stream] == ["meta", "error", "done"]
    assert stream[1] == {"type": "error", "error_type": "daily_limit", "detail": chat_route.STREAM_ERROR_DETAIL["daily_limit"]}
    assert stream[2] == {"type": "done"} and called == []


def test_chat_with_a_place_answers_as_before_and_takes_exactly_one(api_client, tmp_path):
    fresh = mb.ModelBudget(tmp_path / mb.FILENAME, 5, today=Day())
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: (lambda prompt: iter(["Hello", "!"]))
    api_client.app.dependency_overrides[get_model_budget] = lambda: fresh
    try:
        stream = events(api_client.post("/chat", json={"query": "graph algorithms BFS"}))
    finally:
        api_client.app.dependency_overrides.pop(get_model_budget, None)
    assert [e["type"] for e in stream] == ["meta", "token", "token", "done"] and fresh.used() == 1


def test_chat_without_a_budget_is_unchanged(api_client):
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: (lambda prompt: iter(["Hello"]))
    api_client.app.dependency_overrides[get_model_budget] = lambda: None
    try:
        stream = events(api_client.post("/chat", json={"query": "graph algorithms BFS"}))
    finally:
        api_client.app.dependency_overrides.pop(get_model_budget, None)
    assert [e["type"] for e in stream] == ["meta", "token", "done"]


def test_the_ui_shows_the_daily_limit_notice_as_the_answer(tmp_path):
    from app.streamlit_app import stream_assistant
    from api.routes import chat as chat_route

    class Api:
        def chat_stream(self, body):
            yield {"type": "meta", "results": [], "matched_via": "hybrid"}
            yield {"type": "error", "error_type": "daily_limit", "detail": chat_route.STREAM_ERROR_DETAIL["daily_limit"]}
            yield {"type": "done"}

    state = {}
    shown = list(stream_assistant(Api(), {"query": "synthetic"}, state))
    assert shown == ["⚠️ " + chat_route.STREAM_ERROR_DETAIL["daily_limit"]]
    assert state["last_chat_meta"]["matched_via"] == "hybrid"
    assert state["last_chat_error"] == chat_route.STREAM_ERROR_DETAIL["daily_limit"]
