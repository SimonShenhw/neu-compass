"""FIX-01 through the real logging pipeline. configure_logging() renders structlog events through
stdlib logging, so caplog sees every line any logger writes during the request (structlog or
stdlib, exc_info included) with the request id the middleware bound. The capture_logs() checks in
test_api_chat.py and test_api_errors.py see structlog calls only.

中文：用真实的日志管线检查 FIX-01。configure_logging() 让 structlog 的事件经 stdlib logging 渲染，
所以 caplog 能看到请求期间任何 logger 写出的每一行（structlog 或 stdlib，含 exc_info），以及中间件
绑定的 request id。test_api_chat.py、test_api_errors.py 里的 capture_logs() 只看得到 structlog 的调用。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_chat_stream_fn
from api.logging import configure_logging
from llm.gemini_client import GeminiError

# Placeholder upstream text: a credential-like value, a URL and a request body.
PARTS = ("placeholder-credential-123", "https://upstream.example/v1/stream", "request-body-sample")
UPSTREAM_TEXT = f"POST {PARTS[1]}?key={PARTS[0]} body={PARTS[2]}"


@pytest.fixture()
def real_logging() -> None:
    # During setup, so pytest's capture handler for the test call is installed after it.
    # 中文：在 setup 阶段调用，这样 pytest 给测试调用阶段装的捕获 handler 在它之后才装上。
    configure_logging()


def _gemini_error() -> GeminiError:
    cause = RuntimeError(UPSTREAM_TEXT)
    error = GeminiError(f"Gemini stream interrupted: RuntimeError: {cause}", kind="stream_interrupted")
    error.__cause__ = cause
    return error


def _plain_error() -> Exception:
    return RuntimeError(UPSTREAM_TEXT)


def _logged_once(caplog: pytest.LogCaptureFixture, event: str) -> str:
    lines = [record.getMessage() for record in caplog.records if event in record.getMessage()]
    assert len(lines) == 1, f"{event} logged {len(lines)} times"
    return lines[0]


def _assert_nowhere(caplog: pytest.LogCaptureFixture, *texts: str) -> None:
    for part in PARTS:
        assert part not in caplog.text  # Every record, formatted with any exc_info.
        for text in texts:
            assert part not in text


@pytest.mark.parametrize(("make_error", "event"), [
    (_gemini_error, "chat.stream_failed"),
    (_plain_error, "chat.stream_unhandled"),
])
def test_chat_failure_text_is_in_no_log_line_and_the_line_has_the_request_id(
    api_client: TestClient, real_logging: None, caplog: pytest.LogCaptureFixture,
    make_error: Callable[[], Exception], event: str,
) -> None:
    def boom_stream(prompt: str) -> Iterator[str]:
        yield "partial..."
        raise make_error()

    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: boom_stream
    with caplog.at_level(logging.DEBUG):
        r = api_client.post("/chat", json={"query": "x"})
    assert r.headers["x-request-id"] in _logged_once(caplog, event)
    _assert_nowhere(caplog, r.text)


def test_gemini_502_text_is_in_no_log_line_and_the_line_has_the_request_id(
    api_client: TestClient, real_logging: None, caplog: pytest.LogCaptureFixture,
) -> None:
    def raise_gemini() -> None:
        raise _gemini_error()

    api_client.app.add_api_route("/test-raise-gemini", raise_gemini, methods=["GET"])
    with caplog.at_level(logging.DEBUG):
        r = api_client.get("/test-raise-gemini")
    assert r.status_code == 502
    assert r.headers["x-request-id"] in _logged_once(caplog, "gemini_error")
    _assert_nowhere(caplog, r.text)
