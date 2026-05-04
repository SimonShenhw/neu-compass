"""Tests for api.routes.chat — NDJSON streaming /chat endpoint.

Gemini is mocked via app.dependency_overrides[get_chat_stream_fn]; tests
never hit the live SDK. The Streamlit-side consumer pattern (httpx stream
+ iter_lines) is verified at test_streamlit_app level — here we just
assert the wire format produced by the FastAPI handler.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Callable

from fastapi.testclient import TestClient

from api.dependencies import get_chat_stream_fn
from llm.gemini_client import GeminiError


def _override_stream(api_client: TestClient, fn: Callable[[str], Iterator[str]]) -> None:
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: fn


def _parse_ndjson(body: str) -> list[dict]:
    """Parse newline-delimited JSON into a list of event dicts."""
    return [json.loads(line) for line in body.splitlines() if line.strip()]


# === Wire format ===


def test_chat_emits_meta_then_tokens_then_done(api_client: TestClient) -> None:
    """Wire contract: first event is meta, last is done, tokens in between."""

    def fake_stream(prompt: str) -> Iterator[str]:
        yield "Hello"
        yield ", world!"

    _override_stream(api_client, fake_stream)
    r = api_client.post("/chat", json={"query": "graph algorithms BFS"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")

    events = _parse_ndjson(r.text)
    assert len(events) >= 4
    assert events[0]["type"] == "meta"
    assert events[-1]["type"] == "done"
    token_events = [e for e in events if e["type"] == "token"]
    assert [e["text"] for e in token_events] == ["Hello", ", world!"]


def test_chat_meta_includes_results_and_matched_via(api_client: TestClient) -> None:
    _override_stream(api_client, lambda p: iter([]))
    r = api_client.post(
        "/chat", json={"query": "graph algorithms BFS DFS", "k": 3},
    )
    events = _parse_ndjson(r.text)
    meta = events[0]
    assert meta["matched_via"] in {"alias", "hybrid", "empty"}
    assert isinstance(meta["results"], list)
    if meta["results"]:
        first = meta["results"][0]
        assert {"course_id", "primary_code", "primary_name", "score"} <= first.keys()


def test_chat_alias_path_promotes_match(api_client: TestClient) -> None:
    """Slang alias 'Algo' resolves to c-cs-5800 via v_course_lookup —
    /chat should report matched_via='alias' and serve that course."""
    _override_stream(api_client, lambda p: iter(["matched"]))
    r = api_client.post("/chat", json={"query": "Algo"})
    meta = _parse_ndjson(r.text)[0]
    assert meta["matched_via"] == "alias"
    assert any(res["course_id"] == "c-cs-5800" for res in meta["results"])


# === Streaming behavior ===


def test_chat_streams_each_chunk_as_separate_token_event(api_client: TestClient) -> None:
    chunks = ["one ", "two ", "three"]

    def fake_stream(prompt: str) -> Iterator[str]:
        yield from chunks

    _override_stream(api_client, fake_stream)
    r = api_client.post("/chat", json={"query": "neural network"})
    events = _parse_ndjson(r.text)
    tokens = [e for e in events if e["type"] == "token"]
    assert [t["text"] for t in tokens] == chunks


def test_chat_no_tokens_still_terminates_with_done(api_client: TestClient) -> None:
    """Empty stream (e.g. safety block) must still produce a 'done' event."""
    _override_stream(api_client, lambda p: iter([]))
    r = api_client.post("/chat", json={"query": "something"})
    events = _parse_ndjson(r.text)
    assert events[0]["type"] == "meta"
    assert events[-1]["type"] == "done"
    assert all(e["type"] != "token" for e in events)


# === Error handling ===


def test_chat_gemini_error_emits_error_event_then_done(api_client: TestClient) -> None:
    def boom_stream(prompt: str) -> Iterator[str]:
        yield "partial..."
        raise GeminiError("simulated quota error")

    _override_stream(api_client, boom_stream)
    r = api_client.post("/chat", json={"query": "x"})
    assert r.status_code == 200  # streaming response always 200; errors go in-stream
    events = _parse_ndjson(r.text)
    types = [e["type"] for e in events]
    assert "error" in types
    assert types[-1] == "done"
    err = next(e for e in events if e["type"] == "error")
    assert "quota" in err["detail"]


def test_chat_unhandled_exception_still_finishes_stream(api_client: TestClient) -> None:
    """A non-GeminiError mid-stream must not leak through; route catches all."""

    def boom_stream(prompt: str) -> Iterator[str]:
        yield "ok"
        raise RuntimeError("unexpected")

    _override_stream(api_client, boom_stream)
    r = api_client.post("/chat", json={"query": "x"})
    events = _parse_ndjson(r.text)
    assert events[-1]["type"] == "done"
    assert any(e["type"] == "error" for e in events)


# === Validation ===


def test_chat_empty_query_returns_422(api_client: TestClient) -> None:
    _override_stream(api_client, lambda p: iter([]))
    r = api_client.post("/chat", json={"query": ""})
    assert r.status_code == 422


def test_chat_invalid_delivery_mode_returns_422(api_client: TestClient) -> None:
    _override_stream(api_client, lambda p: iter([]))
    r = api_client.post(
        "/chat",
        json={"query": "graph", "delivery_mode": "telepathy"},
    )
    assert r.status_code == 422


def test_chat_extra_field_rejected(api_client: TestClient) -> None:
    _override_stream(api_client, lambda p: iter([]))
    r = api_client.post(
        "/chat", json={"query": "graph", "kk": 5},
    )
    assert r.status_code == 422


# === Prompt is fed retrieved courses ===


def test_chat_prompt_contains_retrieved_course_codes(api_client: TestClient) -> None:
    """Sanity: the prompt the LLM sees lists the retrieved courses."""
    seen_prompts: list[str] = []

    def capture_stream(prompt: str) -> Iterator[str]:
        seen_prompts.append(prompt)
        return iter(["ok"])

    _override_stream(api_client, capture_stream)
    api_client.post("/chat", json={"query": "Algo"})
    assert seen_prompts, "stream_fn was never invoked"
    assert "CS 5800" in seen_prompts[0]
