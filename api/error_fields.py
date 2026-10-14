"""Small, dependency-free safe diagnostics; never render exceptions or locals.

中文：无路由依赖的安全诊断字段；不渲染异常文字、源码或局部变量。
"""

from __future__ import annotations

import os
import traceback


def error_frames(exc: BaseException, limit: int = 6) -> list[str]:
    """Innermost frames, basename only, in the existing `file:line function` format."""
    if limit <= 0:
        return []
    try:
        summary = traceback.StackSummary.extract(traceback.walk_tb(exc.__traceback__), lookup_lines=False)
        return [f"{os.path.basename(frame.filename)}:{frame.lineno} {frame.name}" for frame in summary[-min(limit, 6):]]
    except Exception:  # Diagnostics must not replace the original error.
        return []


def _group_contains(group: BaseExceptionGroup, exc: BaseException) -> bool:
    return any(inner is exc or (isinstance(inner, BaseExceptionGroup) and _group_contains(inner, exc))
               for inner in group.exceptions)


def _framework_context(exc: BaseException) -> bool:
    """Starlette re-raise artefacts are contexts, not causes.

    `BaseHTTPMiddleware` re-raises a cause-less app error `from None` inside `except anyio.EndOfStream`;
    after headers, `collapse_excgroups()` unwraps (possibly nested) single-member groups and re-raises
    the error inside `except` for the outermost one.
    中文：Starlette 重抛留下的包装异常不是原因：无原因的错误在 `except anyio.EndOfStream` 中被
    `from None` 重抛；流头发出后，`collapse_excgroups()` 拆开（可能嵌套的）单成员异常组，
    在处理最外层异常组时重抛。
    """
    context = exc.__context__
    if isinstance(context, BaseExceptionGroup):
        return _group_contains(context, exc)
    return (exc.__suppress_context__ and type(context).__name__ == "EndOfStream"
            and type(context).__module__.startswith("anyio"))


def safe_error_fields(exc: BaseException) -> dict[str, object]:
    """Type, chained type and at most six frames; context is useful even with `from None`."""
    fields: dict[str, object] = {"exc_type": type(exc).__name__, "frames": error_frames(exc)}
    if exc.__cause__ is not None:
        cause = exc.__cause__
    elif exc.__context__ is not None and not _framework_context(exc):
        cause = exc.__context__
    else:
        cause = None
    if cause is not None:
        fields["cause_type"] = type(cause).__name__
    return fields
