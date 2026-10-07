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

import pytest
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from api.dependencies import get_chat_stream_fn, get_db_conn
from api.routes import chat as chat_route
from db.program_repository import ProgramRepository
from llm.gemini_client import GeminiError
from schemas.program import Program, ProgramRequiredCourse


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
    # 'rejected' added in v2: chat path now mirrors /search by running a
    # reranker reject pass; an off-topic query lands here.
    assert meta["matched_via"] in {"alias", "hybrid", "empty", "rejected"}
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
    assert err == {"type": "error", "error_type": "upstream_error",
                   "detail": chat_route.STREAM_ERROR_DETAIL["upstream_error"]}
    assert "quota" not in r.text


def test_chat_unhandled_exception_still_finishes_stream(api_client: TestClient) -> None:
    """A non-GeminiError mid-stream must not leak through; route catches all."""

    def boom_stream(prompt: str) -> Iterator[str]:
        yield "ok"
        raise RuntimeError("unexpected")

    _override_stream(api_client, boom_stream)
    r = api_client.post("/chat", json={"query": "x"})
    events = _parse_ndjson(r.text)
    assert events[-1]["type"] == "done"
    err = next(e for e in events if e["type"] == "error")
    assert err == {"type": "error", "error_type": "internal_error",
                   "detail": chat_route.STREAM_ERROR_DETAIL["internal_error"]}
    assert "unexpected" not in r.text


# Placeholder upstream text: a credential-like value, a URL and a request body (FIX-01).
UPSTREAM_PARTS = ("placeholder-credential-123", "https://upstream.example/v1/stream", "request-body-sample")


class _UpstreamFailure(RuntimeError):
    code = 429
    status = "RESOURCE_EXHAUSTED"


def _upstream_failure() -> GeminiError:
    cause = _UpstreamFailure(f"POST {UPSTREAM_PARTS[1]}?key={UPSTREAM_PARTS[0]} body={UPSTREAM_PARTS[2]}")
    error = GeminiError(f"Gemini stream interrupted: {type(cause).__name__}: {cause}", kind="stream_interrupted")
    error.__cause__ = cause
    return error


def _logged(entries: list[dict], name: str) -> list[dict]:
    return [entry for entry in entries if entry["event"] == name]


def test_chat_upstream_failure_reaches_neither_the_client_nor_the_log_call(api_client: TestClient) -> None:
    def boom_stream(prompt: str) -> Iterator[str]:
        yield "partial..."
        yield "more"
        raise _upstream_failure()

    _override_stream(api_client, boom_stream)
    with capture_logs() as entries:
        r = api_client.post("/chat", json={"query": "x"})
    events = _parse_ndjson(r.text)
    assert [e["text"] for e in events if e["type"] == "token"] == ["partial...", "more"]
    assert [e["type"] for e in events][-2:] == ["error", "done"]
    # The whole call: no message, no exc_info.
    assert _logged(entries, "chat.stream_failed") == [{
        "event": "chat.stream_failed", "log_level": "warning", "tokens_sent": 2,
        "exc_type": "GeminiError", "error_kind": "stream_interrupted", "cause_type": "_UpstreamFailure",
        "upstream_status": 429, "upstream_reason": "RESOURCE_EXHAUSTED",
    }]
    for part in UPSTREAM_PARTS:
        assert part not in r.text
        assert part not in repr(entries)


def test_chat_unexpected_error_logs_where_it_happened_not_its_message(api_client: TestClient) -> None:
    def boom_stream(prompt: str) -> Iterator[str]:
        yield "ok"
        raise RuntimeError(f"state at {UPSTREAM_PARTS[1]} with {UPSTREAM_PARTS[0]}")

    _override_stream(api_client, boom_stream)
    with capture_logs() as entries:
        r = api_client.post("/chat", json={"query": "x"})
    [entry] = _logged(entries, "chat.stream_unhandled")
    frames = entry.pop("frames")
    # error, not exception, and no exc_info: a rendered traceback would end with the message.
    assert entry == {"event": "chat.stream_unhandled", "log_level": "error", "tokens_sent": 1,
                     "exc_type": "RuntimeError"}
    assert frames[-1].startswith("test_api_chat.py:") and frames[-1].endswith(" boom_stream")
    for part in UPSTREAM_PARTS:
        assert part not in r.text
        assert part not in repr(entries)


def test_chat_unexpected_error_frames_are_the_innermost_six(api_client: TestClient) -> None:
    def level(depth: int) -> None:
        if depth == 0:
            raise RuntimeError("deep")
        level(depth - 1)

    def boom_stream(prompt: str) -> Iterator[str]:
        yield "ok"
        level(8)

    _override_stream(api_client, boom_stream)
    with capture_logs() as entries:
        api_client.post("/chat", json={"query": "x"})
    [entry] = _logged(entries, "chat.stream_unhandled")
    assert len(entry["frames"]) == 6
    assert all(frame.endswith(" level") for frame in entry["frames"])  # boom_stream is further out.


class _BrokenKind(GeminiError):
    @property
    def kind(self) -> str:  # type: ignore[override]
        raise RuntimeError("kind lookup failed")

    @kind.setter
    def kind(self, value: str) -> None:
        pass


def test_chat_error_with_an_unreadable_kind_still_ends_the_stream(api_client: TestClient) -> None:
    """Reading the kind happens inside the except block; a second error there would end the stream
    with neither error nor done (and leave the traceback to the middleware's log.exception)."""

    def boom_stream(prompt: str) -> Iterator[str]:
        yield "partial..."
        raise _BrokenKind("upstream text")

    _override_stream(api_client, boom_stream)
    events = _parse_ndjson(api_client.post("/chat", json={"query": "x"}).text)
    assert [e["type"] for e in events][-2:] == ["error", "done"]
    assert next(e for e in events if e["type"] == "error")["error_type"] == "upstream_error"


@pytest.mark.parametrize("kind", ["empty_stream", "empty_response"])
def test_chat_empty_answer_gets_its_own_notice(api_client: TestClient, kind: str) -> None:
    """A safety block or empty completion: "ask again later" would not help."""

    def empty_stream(prompt: str) -> Iterator[str]:
        raise GeminiError("Gemini produced no text", kind=kind)
        yield  # pragma: no cover - makes this a generator

    _override_stream(api_client, empty_stream)
    events = _parse_ndjson(api_client.post("/chat", json={"query": "x"}).text)
    err = next(e for e in events if e["type"] == "error")
    assert err == {"type": "error", "error_type": "no_answer", "detail": chat_route.STREAM_ERROR_DETAIL["no_answer"]}
    assert events[-1] == {"type": "done"}


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


# === v2: reranker reject on chat path (mirror /search behavior) ===


def test_chat_rejects_when_reranker_below_threshold(api_client: TestClient) -> None:
    """Adversarial query with no token overlap to any seeded course's raw_text
    forces FixtureReranker to score ~0 for every candidate; the rejection
    gate (max_sigmoid < threshold) trips and matched_via flips to 'rejected'.
    Mirrors test_api_search.test_search_* but on the chat path."""
    _override_stream(api_client, lambda p: iter([]))
    r = api_client.post(
        "/chat",
        json={"query": "ancient roman emperors and empires", "k": 3},
    )
    assert r.status_code == 200
    events = _parse_ndjson(r.text)
    meta = events[0]
    assert meta["matched_via"] == "rejected"
    assert meta["results"] == []
    assert "rejection_reason" in meta
    assert "max_reranker_sigmoid" in meta["rejection_reason"]


def test_chat_rejected_path_still_calls_llm_with_empty_courses(
    api_client: TestClient,
) -> None:
    """When rejected, the prompt is still built (with empty hits) and the
    LLM is still invoked. The chat_v2 prompt instructs the LLM to honestly
    say 'no matching course' rather than hallucinating alternatives."""
    seen_prompts: list[str] = []

    def capture_stream(prompt: str) -> Iterator[str]:
        seen_prompts.append(prompt)
        return iter(["I couldn't find a matching course."])

    _override_stream(api_client, capture_stream)
    r = api_client.post(
        "/chat",
        json={"query": "ancient roman emperors and empires", "k": 3},
    )
    assert r.status_code == 200
    assert seen_prompts, "stream_fn must still be invoked on rejected path"
    # Empty hits produce '(no matches found in catalog)' in the courses block
    assert "no matches found in catalog" in seen_prompts[0]


def test_chat_rejection_reason_omitted_on_alias_path(api_client: TestClient) -> None:
    """Alias short-circuit doesn't go through the reranker; rejection_reason
    must remain absent in the meta event on alias hits."""
    _override_stream(api_client, lambda p: iter(["ok"]))
    r = api_client.post("/chat", json={"query": "Algo", "k": 3})
    meta = _parse_ndjson(r.text)[0]
    assert meta["matched_via"] == "alias"
    assert meta.get("rejection_reason") is None


def test_chat_legitimate_query_passes_rejection_gate(api_client: TestClient) -> None:
    """A query with token overlap to a seeded course's raw_text has
    max_sigmoid above threshold — matched_via='hybrid', no rejection."""
    _override_stream(api_client, lambda p: iter(["ok"]))
    r = api_client.post(
        "/chat",
        json={"query": "graph algorithms BFS shortest paths", "k": 3},
    )
    meta = _parse_ndjson(r.text)[0]
    assert meta["matched_via"] == "hybrid"
    assert meta.get("rejection_reason") is None
    assert any(res["course_id"] == "c-cs-5800" for res in meta["results"])


# === Layer 3: program-aware shortcut for "X 专业第一学期" queries ===


def _seed_aai_program(api_client: TestClient) -> None:
    """Seed a minimal AAI program (c-aai-6600 as semester=1 foundation)
    into the test app's DB so the program-aware path activates."""
    # api_client.app.dependency_overrides[get_db_conn] is set to a lambda
    # returning the shared in-memory connection — pull it out and seed.
    conn = api_client.app.dependency_overrides[get_db_conn]()
    repo = ProgramRepository(conn)
    repo.upsert_program(Program(
        program_id="aai-ms",
        full_name="MPS Applied AI",
        prefix="AAI",
        department="Applied AI",
    ))
    repo.upsert_required_course(ProgramRequiredCourse(
        program_id="aai-ms",
        course_id="c-aai-6600",
        requirement_type="foundation",
        semester_recommended=1,
    ))


def test_chat_program_path_for_first_semester_query(api_client: TestClient) -> None:
    """The headline Layer 3 case: 'AAI 专业第一学期推荐' should hit the
    program ontology, NOT hybrid retrieval — matched_via='program' and
    only returns courses seeded as semester=1 for that program."""
    _seed_aai_program(api_client)
    _override_stream(api_client, lambda p: iter(["ok"]))
    r = api_client.post(
        "/chat",
        json={"query": "我是 AAI 专业, 第一学期选什么课比较好?", "k": 5},
    )
    assert r.status_code == 200
    meta = _parse_ndjson(r.text)[0]
    assert meta["matched_via"] == "program"
    course_ids = [res["course_id"] for res in meta["results"]]
    assert "c-aai-6600" in course_ids


def test_chat_program_path_falls_through_when_program_not_seeded(
    api_client: TestClient,
) -> None:
    """If the prefix is detected but no program is seeded for it, we must
    NOT short-circuit to a 'program' path with empty results — fall
    through to hybrid (Layer 2 prefix filter still applied)."""
    _override_stream(api_client, lambda p: iter(["ok"]))
    r = api_client.post(
        "/chat",
        json={"query": "DS 专业第一学期推荐", "k": 5},
    )
    meta = _parse_ndjson(r.text)[0]
    # No DS program seeded → program path skipped → falls through to hybrid
    # (which then either succeeds or gets rejected by the reranker, but
    # never reports matched_via='program').
    assert meta["matched_via"] != "program"


def test_chat_program_path_skipped_without_foundational_intent(
    api_client: TestClient,
) -> None:
    """Prefix alone is not enough — without a 'first-semester / 基础 /
    foundational' signal, the user is asking about something specific and
    hybrid retrieval is the right tool."""
    _seed_aai_program(api_client)
    _override_stream(api_client, lambda p: iter(["ok"]))
    r = api_client.post(
        "/chat",
        json={"query": "AAI 课程里关于强化学习的有哪些?", "k": 5},
    )
    meta = _parse_ndjson(r.text)[0]
    # Query mentions AAI but is asking about a specific topic; program
    # shortcut should not fire.
    assert meta["matched_via"] != "program"


def test_chat_program_path_not_used_on_explicit_alias(
    api_client: TestClient,
) -> None:
    """Alias has higher priority than the program path — typing 'Algo'
    must still resolve to CS 5800 even if the user is technically in the
    AAI program."""
    _seed_aai_program(api_client)
    _override_stream(api_client, lambda p: iter(["ok"]))
    r = api_client.post("/chat", json={"query": "Algo", "k": 3})
    meta = _parse_ndjson(r.text)[0]
    assert meta["matched_via"] == "alias"


# === Conversation continuity: context tier (2026-06) ===


def test_chat_followup_takes_context_tier(api_client, empty_db) -> None:
    """A referent query ('这门课...') + context_course_ids from the
    previous turn must resolve via the context tier — matched_via=context,
    results = exactly the context course — instead of running noisy
    retrieval on a query with no course signal."""
    import json as _json

    from api.dependencies import get_chat_stream_fn

    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: (
        lambda prompt: iter(["回答"])
    )
    r = api_client.post("/chat", json={
        "query": "那你能给我讲讲这门课大概讲什么内容吗？",
        "k": 5,
        "history": [
            {"role": "user", "content": "CS 5800 这门课怎么样?"},
            {"role": "assistant", "content": "CS 5800 是 Algorithms..."},
        ],
        "context_course_ids": ["c-cs-5800"],
    })
    assert r.status_code == 200
    meta = _json.loads(r.text.strip().splitlines()[0])
    assert meta["matched_via"] == "context"
    assert [h["course_id"] for h in meta["results"]] == ["c-cs-5800"]


def test_chat_fresh_query_ignores_context_ids(api_client, empty_db) -> None:
    """A query that names its own course must NOT be hijacked by stale
    context ids — alias tier wins."""
    import json as _json

    from api.dependencies import get_chat_stream_fn

    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: (
        lambda prompt: iter(["ok"])
    )
    r = api_client.post("/chat", json={
        "query": "AAI 6600 怎么样",
        "k": 3,
        "context_course_ids": ["c-cs-5800"],
    })
    assert r.status_code == 200
    meta = _json.loads(r.text.strip().splitlines()[0])
    assert meta["matched_via"] == "alias"
    assert meta["results"][0]["course_id"] == "c-aai-6600"


def test_chat_history_reaches_prompt(api_client, empty_db) -> None:
    """The answer prompt must carry the conversation history block."""
    captured: dict = {}

    from api.dependencies import get_chat_stream_fn

    def _capture_fn(prompt: str):
        captured["prompt"] = prompt
        return iter(["ok"])

    api_client.app.dependency_overrides[get_chat_stream_fn] = (
        lambda: _capture_fn
    )
    r = api_client.post("/chat", json={
        "query": "这门课作业量大吗?",
        "k": 3,
        "history": [{"role": "user", "content": "CS 5800 怎么样"}],
        "context_course_ids": ["c-cs-5800"],
    })
    assert r.status_code == 200
    assert "Student: CS 5800 怎么样" in captured["prompt"]


def test_chat_context_ids_capped_and_validated(api_client) -> None:
    """history >12 turns or >10 context ids → 422 (bounded payloads)."""
    r = api_client.post("/chat", json={
        "query": "这门课怎么样",
        "context_course_ids": [f"c-{i}" for i in range(11)],
    })
    assert r.status_code == 422
