"""Structlog configuration + per-request access log middleware.

`configure_logging()` is idempotent — safe to call multiple times (e.g. from
both the FastAPI lifespan and from a Streamlit entrypoint). Uses
`structlog.contextvars` so handlers can `.bind(...)` and have the bound
keys flow into the access-log line emitted on response.

PLAN §7.5 / v2.0 §4.1: structlog is the project's only logger. JSON in prod
(log_format='json') for ingestion; console renderer for local dev.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from config import settings

_CONFIGURED = False


def configure_logging() -> structlog.stdlib.BoundLogger:
    """Initialize structlog. Returns the project root logger.

    Call once at process start. Subsequent calls are no-ops; this lets a
    Streamlit page and the FastAPI app share one configuration when they
    co-locate (Week 6 dev workflow).
    """
    global _CONFIGURED
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    if not _CONFIGURED:
        renderer: Any
        if settings.log_format == "json":
            renderer = structlog.processors.JSONRenderer()
        else:
            renderer = structlog.dev.ConsoleRenderer(colors=False)

        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="iso", utc=True),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                renderer,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
        # stdlib logging routes through structlog's renderer above. We just need
        # a stream handler on the root that doesn't mangle the already-formatted
        # message (structlog hands us the final string).
        root = logging.getLogger()
        root.handlers.clear()
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(handler)
        root.setLevel(log_level)
        _CONFIGURED = True

    return structlog.get_logger("neu_compass")


class RequestLogMiddleware(BaseHTTPMiddleware):
    """One structured access-log line per request, plus a stable x-request-id.

    Bound via contextvars so route handlers can `structlog.get_logger().info(...)`
    and have request_id / method / path automatically present.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        log = structlog.get_logger("neu_compass.request")
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000
            log.exception("request.unhandled", duration_ms=round(elapsed_ms, 2))
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000
        log.info(
            "request.handled",
            status=response.status_code,
            duration_ms=round(elapsed_ms, 2),
        )
        response.headers["x-request-id"] = request_id
        return response


__all__ = ["RequestLogMiddleware", "configure_logging"]
