"""Structlog configuration + per-request access log middleware.

Structlog 配置 + 每请求一条的访问日志中间件。

`configure_logging()` is idempotent — safe to call multiple times (e.g. from
both the FastAPI lifespan and from a Streamlit entrypoint). Uses
`structlog.contextvars` so handlers can `.bind(...)` and have the bound
keys flow into the access-log line emitted on response.

`configure_logging()` 是幂等的 —— 可以安全地多次调用（例如同时被 FastAPI
的 lifespan 和某个 Streamlit 入口调用）。使用 `structlog.contextvars`，
这样各处理器 `.bind(...)` 绑定的键就能自动流入响应时输出的那条访问
日志。

PLAN §7.5 / v2.0 §4.1: structlog is the project's only logger. JSON in prod
(log_format='json') for ingestion; console renderer for local dev.

PLAN §7.5 / v2.0 §4.1：structlog 是本项目唯一的日志库。生产环境用 JSON
（log_format='json'）方便采集；本地开发用控制台渲染器。
"""

from __future__ import annotations

import logging
import re
import sys
import time
import uuid
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from config import settings
from api.error_fields import safe_error_fields
from api.exceptions import internal_error_response

_CONFIGURED = False
_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _safe_exception(_logger: Any, _name: str, event: dict[str, Any]) -> dict[str, Any]:
    """Consume exc_info before either renderer can print traceback text or Rich locals."""
    info = event.pop("exc_info", None)
    event.pop("exception", None)
    event.pop("stack_info", None)
    if info:
        exc = info if isinstance(info, BaseException) else (
            info[1] if isinstance(info, tuple) and len(info) == 3 else sys.exc_info()[1])
        if isinstance(exc, BaseException):
            event.update(safe_error_fields(exc))
    return event


class _SafeForeignLogs(logging.Filter):
    """Sanitize the shared record BEFORE all downstream handlers (including caplog).

    Project structlog output is already processed. Foreign library messages are untrusted;
    keep level and safe exception location, not URLs, bodies or exception text.
    """

    def __init__(self, renderer: Any) -> None:
        super().__init__()
        self.renderer = renderer

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "_safe_structlog", False):
            fields: dict[str, object] = {"event": "stdlib.error" if record.levelno >= logging.ERROR else "stdlib.log",
                                         "level": record.levelname.lower()}
            context = structlog.contextvars.get_contextvars()
            fields.update({key: context[key] for key in ("request_id", "method", "path") if key in context})
            if record.exc_info and record.exc_info[1] is not None:
                fields.update(safe_error_fields(record.exc_info[1]))
            record.msg = self.renderer(None, record.levelname.lower(), fields)
            record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def configure_logging() -> structlog.stdlib.BoundLogger:
    """Initialize structlog. Returns the project root logger.

    初始化 structlog。返回项目的根 logger。

    Call once at process start. Subsequent calls are no-ops; this lets a
    Streamlit page and the FastAPI app share one configuration when they
    co-locate (Week 6 dev workflow).

    在进程启动时调用一次。后续调用都是空操作；这样当 Streamlit 页面与
    FastAPI 应用同进程运行时（Week 6 的开发工作流），二者能共享同一份
    配置。
    """
    global _CONFIGURED
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    if not _CONFIGURED:
        renderer: Any
        if settings.log_format == "json":
            renderer = structlog.processors.JSONRenderer()
        else:
            renderer = structlog.dev.ConsoleRenderer(colors=False)

        def render_safe(logger: Any, name: str, event: dict[str, Any]) -> Any:
            return (renderer(logger, name, event),), {"extra": {"_safe_structlog": True}}

        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="iso", utc=True),
                _safe_exception,
                render_safe,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
        # Structlog passes marked, rendered strings; foreign records are sanitized
        # and rendered by the first root handler's filter before any other handler sees them.
        # 中文：structlog 传入带标记的成品字符串；第三方记录先在首个 root handler
        # 的 filter 中安全化和渲染，后面的 handler 不再看到原始消息。
        root = logging.getLogger()
        root.handlers.clear()
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.addFilter(_SafeForeignLogs(renderer))
        handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(handler)
        root.setLevel(log_level)
        _CONFIGURED = True

    return structlog.get_logger("neu_compass")


class RequestLogMiddleware(BaseHTTPMiddleware):
    """One structured access-log line per request, plus a stable x-request-id.

    每个请求输出一条结构化访问日志，并附带一个稳定的 x-request-id。

    Bound via contextvars so route handlers can `structlog.get_logger().info(...)`
    and have request_id / method / path automatically present.

    通过 contextvars 绑定，这样路由处理器只需调用
    `structlog.get_logger().info(...)`，request_id / method / path 就会
    自动出现在日志里。
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID.fullmatch(incoming) else str(uuid.uuid4())
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
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            log.error("request.unhandled", status=500, error_type="internal_error",
                      duration_ms=round(elapsed_ms, 2), **safe_error_fields(exc))
            response = internal_error_response()
            response.headers["x-request-id"] = request_id
            return response

        elapsed_ms = (time.perf_counter() - start) * 1000
        log.info(
            "request.handled",
            status=response.status_code,
            duration_ms=round(elapsed_ms, 2),
        )
        response.headers["x-request-id"] = request_id
        return response


__all__ = ["RequestLogMiddleware", "configure_logging"]
