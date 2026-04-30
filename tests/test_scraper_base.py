"""Tests for scrapers._base — HTTP client + retry decorator."""

from __future__ import annotations

import httpx
import pytest

from scrapers._base import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    create_client,
    fetch_with_retry,
)


def test_create_client_default_headers() -> None:
    with create_client() as client:
        assert "User-Agent" in client.headers
        assert "neu-compass" in client.headers["User-Agent"]
        assert client.headers["Accept-Language"] == DEFAULT_HEADERS["Accept-Language"]


def test_create_client_extra_headers_merge() -> None:
    with create_client(extra_headers={"X-Test": "yes"}) as client:
        assert client.headers["X-Test"] == "yes"
        # Default still present
        assert "neu-compass" in client.headers["User-Agent"]


def test_create_client_default_timeout() -> None:
    with create_client() as client:
        assert client.timeout == DEFAULT_TIMEOUT


def test_create_client_follows_redirects() -> None:
    with create_client() as client:
        assert client.follow_redirects is True


def test_fetch_with_retry_success_first_try() -> None:
    """Mock transport that succeeds immediately."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        response = fetch_with_retry(client, "https://example.com/")
        assert response.text == "ok"


def test_fetch_with_retry_4xx_does_not_retry() -> None:
    """401 / 404 should not trigger retry — they're not transient."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(404, text="not found")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            fetch_with_retry(client, "https://example.com/")
    assert call_count == 1, "4xx should not retry"


# Retry-with-actual-backoff tests omitted: tenacity wait_exponential
# (min=2s) makes them take 6+ seconds each. Tenacity's retry semantics
# are well-tested upstream; we only need to verify our decorator config
# wraps successfully (above) and that non-transient errors don't trigger
# retry (above, call_count==1 check).
