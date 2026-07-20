"""Structured HTTP error responses + exception handlers (PLAN v2.3 Week 8 §3.7 follow-up).

结构化 HTTP 错误响应 + 异常处理器（PLAN v2.3 Week 8 §3.7 后续工作）。

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

目标：每个 API 错误都返回一个 JSON body，包含 `detail`（既有契约，向后
兼容当前所有测试）加上 `error_type`（新增 —— 客户端凭它分发处理，无需
解析 detail 字符串）加上 `status_code`（虽冗余但更明确）。所有 HTTP
错误路径都汇聚到这里，从而在以下几类情况下保持统一形状：

  - 路由为输入/校验问题抛出的 `HTTPException`（422、503）
  - 调用栈深处抛出的领域异常（OAuthError / GeminiError /
    CourseNotFound）—— 以前这些要么冒泡成 500，要么由各路由各自手工
    捕获、处理方式并不统一
  - 真正未被处理的异常 —— 在最外层兜住，让客户端看到结构化的 500，
    而不是 FastAPI 默认的 `{"detail": "Internal Server Error"}`

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

`error_type` 分类体系（稳定；客户端应把未知类型当作不透明字符串处理，
而不是当作封闭枚举）：

  - invalid_input        —— 422，请求体校验失败
  - not_found            —— 404，资源不存在
  - unauthorized         —— 401，鉴权失败或缺失
  - forbidden            —— 403，鉴权通过但不允许
  - conflict             —— 409，状态冲突（如 k=2 违规去重）
  - service_unavailable  —— 503，预热中或降级模式
  - upstream_error       —— 502，LLM / RMP / Reddit 调用失败
  - client_error         —— 其他 4xx
  - internal_error       —— 未归类的 5xx

Tests: tests/test_api_errors.py — TestClient + a tiny throwaway app
exercising each handler in isolation.

测试：tests/test_api_errors.py —— 用 TestClient 加一个小型一次性 app，
逐个隔离演练每个处理器。
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
    existing tests + clients; `error_type` added for programmatic dispatch.
    规范化的错误响应体。`detail` 保留是为了向后兼容现有测试与客户端；
    新增 `error_type` 供程序化分发使用。"""

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
    """Map HTTP code → error_type taxonomy. Falls back to coarse buckets.
    把 HTTP 状态码映射到 error_type 分类；映射不到时退回粗粒度分桶。"""
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
    Preserves the original status_code + detail; just adds error_type.
    把 FastAPI 默认的 `{"detail": ...}` 替换成结构化形状。保留原始的
    status_code + detail，只是新增 error_type。"""
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
    raw Python repr. Flatten to one human-readable string.
    请求体校验触发的 422（最常见的一类 4xx）以前完全绕开了 ErrorResponse
    契约 —— FastAPI 默认把 `detail` 输出成一个错误字典组成的列表，
    Streamlit 客户端会把它字符串化成一坨原始 Python repr。这里把它压平
    成一条人类可读的字符串。"""
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
    whether to retry (502 → likely yes) vs. give up (500 → check logs).
    Gemini 失败映射到 502（上游错误），而不是 500。让客户端自己判断要不要
    重试（502 → 大概率可以）还是放弃（500 → 该去查日志了）。"""
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

    最后一道处理器。前面没兜住的任何异常都会变成结构化的 500。记录完整
    traceback 供调试使用。

    Crucial: do NOT leak the exception message to clients — it could
    expose internals (file paths, stack frames, dependency versions). Use
    a generic detail and rely on `x-request-id` (set by RequestLogMiddleware)
    to correlate the client's failed request to the server log line.

    关键点：绝不能把异常消息泄漏给客户端 —— 它可能暴露内部信息（文件
    路径、调用栈帧、依赖库版本）。这里用通用的 detail 文案，靠
    `x-request-id`（由 RequestLogMiddleware 设置）把客户端这次失败的
    请求和服务端日志行关联起来。
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
    # 中文：RequestLogMiddleware 只在成功响应上设置 x-request-id，但这个
    # 处理器运行在最外层的 ServerErrorMiddleware 之外 —— 于是恰恰是那个
    # body 里写着"请按 x-request-id 关联"的响应，自己反而没带这个请求头。
    # 从 middleware 在异常发生前绑定的 structlog contextvars 里把它找回来。
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    if request_id:
        response.headers["x-request-id"] = str(request_id)
    return response


def register_exception_handlers(app: FastAPI) -> None:
    """Wire all handlers to the FastAPI app. Call once during create_app.

    把所有处理器接到 FastAPI 应用上。在 create_app 期间调用一次即可。

    FastAPI dispatches by exception-type isinstance match. Subclasses are
    preferred over their parents, so OAuthError (RuntimeError subclass)
    hits oauth_error_handler before hitting the generic Exception fallback.

    FastAPI 按异常类型的 isinstance 匹配来分发。子类优先于父类，所以
    OAuthError（RuntimeError 的子类）会先命中 oauth_error_handler，然后
    才轮到通用的 Exception 兜底。
    """
    # Registered against STARLETTE's HTTPException on purpose: router-level
    # 404 (unknown path) and 405 (wrong method) raise the starlette class
    # directly, which the FastAPI-subclass registration would miss — those
    # responses then lacked error_type/status_code. FastAPI's HTTPException
    # subclasses starlette's, so this one registration covers both.
    # 中文：这里故意注册的是 STARLETTE 的 HTTPException：路由级别的 404
    # （未知路径）和 405（方法不对）直接抛出的是 starlette 的异常类，若
    # 只注册 FastAPI 子类会漏掉它们 —— 导致这些响应缺少
    # error_type/status_code。FastAPI 的 HTTPException 是 starlette 那个
    # 的子类，所以这一处注册能同时覆盖两者。
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
