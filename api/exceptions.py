"""Structured HTTP error responses + exception handlers (PLAN v2.3 Week 8 §3.7 follow-up).

Goal: every API error returns a JSON body with `detail` (existing contract,
backward-compat with all current tests) PLUS `error_type` (new — clients
dispatch on this without parsing detail strings) PLUS `status_code`
(redundant but explicit). All HTTP error paths funnel through here so
the shape is uniform across:

  - `HTTPException` raised by routes for input/validation (422, 503)
  - Domain exceptions (OAuthError / GeminiError / CourseNotFound) raised
    deep in the call stack — previously these would either bubble as 500
    or be hand-caught per route inconsistently
  - Truly unhandled exceptions — caught at the top so the client sees a
    structured 500 instead of FastAPI's default `{"detail": "Internal Server Error"}`

`error_type` taxonomy (stable; clients should treat unknown types as opaque
strings, not as a closed enum):

  - invalid_input        — 422, body validation
  - not_found            — 404, resource missing
  - unauthorized         — 401, auth failed / missing
  - forbidden            — 403, auth ok but not allowed
  - conflict             — 409, state conflict (e.g. dup k=2 violation)
  - service_unavailable  — 503, warmup or degraded mode
  - upstream_error       — 502, LLM / RMP / Reddit failure
  - client_error         — other 4xx
  - internal_error       — 5xx not otherwise classified

Tests: tests/test_api_errors.py — TestClient + a tiny throwaway app
exercising each handler in isolation.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import OAuthError
from db.repository import CourseNotFound
from llm.gemini_client import GeminiError


class ErrorResponse(BaseModel):
    """Canonical error body. `detail` retained for backward-compat with
    existing tests + clients; `error_type` added for programmatic dispatch."""

    detail: str
    error_type: str
    status_code: int


_log = structlog.get_logger("neu_compass.error")


_STATUS_TO_TYPE: dict[int, str] = {
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "invalid_input",
    502: "upstream_error",
    503: "service_unavailable",
}


def _http_status_to_type(status_code: int) -> str:
    """Map HTTP code → error_type taxonomy. Falls back to coarse buckets."""
    if status_code in _STATUS_TO_TYPE:
        return _STATUS_TO_TYPE[status_code]
    if 400 <= status_code < 500:
        return "client_error"
    return "server_error"


def _error_response(
    *,
    status_code: int,
    error_type: str,
    detail: str,
) -> JSONResponse:
    body = ErrorResponse(
        detail=detail,
        error_type=error_type,
        status_code=status_code,
    ).model_dump()
    return JSONResponse(status_code=status_code, content=body)


async def http_exception_handler(
    request: Request, exc: HTTPException,
) -> JSONResponse:
    """Replace FastAPI's default `{"detail": ...}` with structured shape.
    Preserves the original status_code + detail; just adds error_type."""
    return _error_response(
        status_code=exc.status_code,
        error_type=_http_status_to_type(exc.status_code),
        detail=str(exc.detail),
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError,
) -> JSONResponse:
    """Body-validation 422s (the most common 4xx class) previously bypassed
    the ErrorResponse contract entirely — FastAPI's default emits `detail`
    as a LIST of error dicts, which the Streamlit client stringified into a
    raw Python repr. Flatten to one human-readable string."""
    msgs = []
    for err in exc.errors():
        loc = ".".join(
            str(part) for part in err.get("loc", ()) if part != "body"
        )
        msg = err.get("msg", "invalid")
        msgs.append(f"{loc}: {msg}" if loc else str(msg))
    return _error_response(
        status_code=422,
        error_type="invalid_input",
        detail="; ".join(msgs) or "Invalid request body",
    )


async def oauth_error_handler(
    request: Request, exc: OAuthError,
) -> JSONResponse:
    return _error_response(
        status_code=401,
        error_type="unauthorized",
        detail=str(exc),
    )


async def course_not_found_handler(
    request: Request, exc: CourseNotFound,
) -> JSONResponse:
    return _error_response(
        status_code=404,
        error_type="not_found",
        detail=f"Course {str(exc)!r} not found",
    )


async def gemini_error_handler(
    request: Request, exc: GeminiError,
) -> JSONResponse:
    """Gemini failures map to 502 (upstream), not 500. Lets clients decide
    whether to retry (502 → likely yes) vs. give up (500 → check logs)."""
    return _error_response(
        status_code=502,
        error_type="upstream_error",
        detail=f"LLM upstream failure: {exc}",
    )


async def unhandled_exception_handler(
    request: Request, exc: Exception,
) -> JSONResponse:
    """Last-resort handler. Anything not caught above becomes a structured
    500. Logs full traceback for debugging.

    Crucial: do NOT leak the exception message to clients — it could
    expose internals (file paths, stack frames, dependency versions). Use
    a generic detail and rely on `x-request-id` (set by RequestLogMiddleware)
    to correlate the client's failed request to the server log line.
    """
    _log.exception(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        exc_type=type(exc).__name__,
    )
    response = _error_response(
        status_code=500,
        error_type="internal_error",
        detail="Internal server error. Check API logs by x-request-id.",
    )
    # RequestLogMiddleware sets x-request-id on SUCCESS responses, but this
    # handler runs in the outermost ServerErrorMiddleware — outside it — so
    # the one response whose body says "correlate by x-request-id" was the
    # one without the header. Recover it from the structlog contextvars the
    # middleware bound before the exception.
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    if request_id:
        response.headers["x-request-id"] = str(request_id)
    return response


def register_exception_handlers(app: FastAPI) -> None:
    """Wire all handlers to the FastAPI app. Call once during create_app.

    FastAPI dispatches by exception-type isinstance match. Subclasses are
    preferred over their parents, so OAuthError (RuntimeError subclass)
    hits oauth_error_handler before hitting the generic Exception fallback.
    """
    # Registered against STARLETTE's HTTPException on purpose: router-level
    # 404 (unknown path) and 405 (wrong method) raise the starlette class
    # directly, which the FastAPI-subclass registration would miss — those
    # responses then lacked error_type/status_code. FastAPI's HTTPException
    # subclasses starlette's, so this one registration covers both.
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(OAuthError, oauth_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(CourseNotFound, course_not_found_handler)  # type: ignore[arg-type]
    app.add_exception_handler(GeminiError, gemini_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)


__all__ = [
    "ErrorResponse",
    "register_exception_handlers",
]
