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


def safe_error_fields(exc: BaseException) -> dict[str, object]:
    """Type, chained type and at most six frames; context is useful even with `from None`."""
    fields: dict[str, object] = {"exc_type": type(exc).__name__, "frames": error_frames(exc)}
    cause = exc.__cause__ if exc.__cause__ is not None else exc.__context__
    if cause is not None:
        fields["cause_type"] = type(cause).__name__
    return fields
