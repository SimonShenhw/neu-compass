"""Tests for app.api_client — uses httpx.MockTransport so no live server needed."""

from __future__ import annotations

import httpx
import pytest

from app.api_client import ApiClient, ApiError


def _client(handler, *, user_id: str | None = None) -> ApiClient:
    transport = httpx.MockTransport(handler)
    return ApiClient(
        base_url="http://test", user_id=user_id, transport=transport,
    )


# === Happy paths ===


def test_health_returns_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(200, json={"status": "ok"})

    with _client(handler) as api:
        assert api.health() == {"status": "ok"}


def test_search_passes_query_and_filters() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "query": "graph",
                "k": 5,
                "matched_via": "hybrid",
                "results": [],
                "latency_ms": 1.0,
            },
        )

    with _client(handler) as api:
        api.search("graph", k=5, term="Spring 2026", credits=4)

    assert seen["body"] == {
        "query": "graph", "k": 5, "term": "Spring 2026", "credits": 4,
    }


def test_search_omits_unset_filters() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "query": "x", "k": 10, "matched_via": "empty",
            "results": [], "latency_ms": 1.0,
        })

    with _client(handler) as api:
        api.search("x")

    assert seen["body"] == {"query": "x", "k": 10}


def test_get_course_uses_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/course/c-cs-5800"
        return httpx.Response(
            200, json={"course_id": "c-cs-5800", "primary_code": "CS 5800"},
        )

    with _client(handler) as api:
        body = api.get_course("c-cs-5800")
    assert body["course_id"] == "c-cs-5800"


# === Auth header ===


def test_user_id_header_attached() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["x-user-id"] = request.headers.get("x-user-id")
        return httpx.Response(200, json=[])

    with _client(handler, user_id="u-test") as api:
        api.list_coop()

    assert seen["x-user-id"] == "u-test"


def test_set_user_id_swaps_header() -> None:
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("x-user-id"))
        return httpx.Response(200, json=[])

    with _client(handler) as api:
        api.list_coop()
        api.set_user_id("u-1")
        api.list_coop()
        api.set_user_id(None)
        api.list_coop()

    assert seen == [None, "u-1", None]


# === Error path ===


def test_4xx_raises_apierror_with_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422, json={"detail": "Submission would be uniquely identifying"},
        )

    with _client(handler) as api:
        with pytest.raises(ApiError) as ei:
            api.upload_coop({"company": "X", "role": "Y"})
    assert ei.value.status_code == 422
    assert "uniquely identifying" in ei.value.detail


def test_5xx_raises_apierror_with_text_when_no_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal boom")

    with _client(handler) as api:
        with pytest.raises(ApiError) as ei:
            api.health()
    assert ei.value.status_code == 500
    assert "internal boom" in ei.value.detail


# === oauth_callback ===


def test_oauth_callback_posts_code() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        seen["body"] = _json.loads(request.content)
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "user_id": "u-1",
                "email": "alice@husky.neu.edu",
                "display_name": "Alice",
                "contribution_count": 0,
            },
        )

    with _client(handler) as api:
        body = api.oauth_callback("auth-code-x")

    assert seen["url"].endswith("/auth/callback")
    assert seen["body"] == {"code": "auth-code-x"}
    assert body["user_id"] == "u-1"


def test_oauth_callback_with_redirect_uri() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        seen["body"] = _json.loads(request.content)
        return httpx.Response(200, json={"user_id": "u", "email": "a@x", "contribution_count": 0})

    with _client(handler) as api:
        api.oauth_callback("c", redirect_uri="https://x.example/cb")

    assert seen["body"]["redirect_uri"] == "https://x.example/cb"


def test_oauth_callback_401_raises_apierror() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Domain not allowed"})

    with _client(handler) as api:
        with pytest.raises(ApiError) as ei:
            api.oauth_callback("c")
    assert ei.value.status_code == 401
    assert "Domain not allowed" in ei.value.detail


# === chat_stream ===


def test_chat_stream_yields_parsed_events() -> None:
    """Stream returns one dict per NDJSON line."""
    ndjson = (
        '{"type": "meta", "matched_via": "alias", "results": []}\n'
        '{"type": "token", "text": "hello "}\n'
        '{"type": "token", "text": "world"}\n'
        '{"type": "done"}\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat"
        return httpx.Response(
            200,
            content=ndjson.encode("utf-8"),
            headers={"content-type": "application/x-ndjson"},
        )

    with _client(handler) as api:
        events = list(api.chat_stream({"query": "Algo"}))

    assert [e["type"] for e in events] == ["meta", "token", "token", "done"]
    assert events[0]["matched_via"] == "alias"
    assert events[1]["text"] == "hello "
    assert events[2]["text"] == "world"


def test_chat_stream_skips_malformed_lines() -> None:
    """A garbled line shouldn't kill the whole stream."""
    body = (
        '{"type": "meta", "results": []}\n'
        "this is not json\n"
        '{"type": "token", "text": "ok"}\n'
        '{"type": "done"}\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode("utf-8"))

    with _client(handler) as api:
        events = list(api.chat_stream({"query": "q"}))

    types = [e["type"] for e in events]
    assert types == ["meta", "token", "done"]


def test_chat_stream_raises_on_pre_stream_error() -> None:
    """If the server returns 4xx before streaming starts, ApiError surfaces."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "Invalid query"})

    with _client(handler) as api:
        with pytest.raises(ApiError) as ei:
            list(api.chat_stream({"query": ""}))
    assert ei.value.status_code == 422
    assert "Invalid query" in ei.value.detail
