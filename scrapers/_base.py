"""Shared scraper utilities: HTTP client, retry, structured logging.

Every scraper in this package should:
  1. Use create_client() instead of httpx.Client() directly (sane defaults +
     consistent User-Agent).
  2. Wrap network calls in fetch_with_retry() (3 tries, exponential backoff).
  3. logger.bind(scraper="xxx", ...) at the top of public functions so
     structlog logs identify the source.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger("scrapers")

# 30s read covers slow pages; 10s connect catches dead hosts fast.
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)

# Identify ourselves; some sites serve different content / block on missing UA.
DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": "neu-compass/0.1 (academic project; +https://github.com/SimonShenhw/neu-compass)",
    "Accept-Language": "en-US,en;q=0.9",
}

# Errors that should trigger retry (transient). Auth / 4xx errors don't retry.
TRANSIENT_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)


def create_client(
    *,
    extra_headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
) -> httpx.Client:
    """Build a configured httpx.Client. Caller manages lifecycle (use as ctx manager)."""
    headers = {**DEFAULT_HEADERS, **(extra_headers or {})}
    return httpx.Client(
        timeout=timeout or DEFAULT_TIMEOUT,
        headers=headers,
        follow_redirects=True,
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(TRANSIENT_EXCEPTIONS),
    reraise=True,
)
def fetch_with_retry(
    client: httpx.Client,
    url: str,
    *,
    method: str = "GET",
    **kwargs: Any,
) -> httpx.Response:
    """GET (or other method) with 3-attempt exponential backoff on transient errors.

    Non-transient (4xx, parse errors) bubble up immediately — no point retrying
    a 401 or a malformed JSON.
    """
    response = client.request(method, url, **kwargs)
    response.raise_for_status()
    return response


__all__ = [
    "DEFAULT_HEADERS",
    "DEFAULT_TIMEOUT",
    "TRANSIENT_EXCEPTIONS",
    "create_client",
    "fetch_with_retry",
    "logger",
]
