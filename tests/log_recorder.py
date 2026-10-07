"""Stand-in for a module-level structlog logger: records every call as (level, event, fields).

The project configures structlog with cache_logger_on_first_use=True, so structlog.testing's
capture_logs() misses loggers that an earlier test already used. Tests monkeypatch the module's
`log` with this recorder instead and assert on exactly what would have been written.

中文：代替模块级 structlog logger，把每次调用记成 (level, event, fields)。项目的 structlog 配置开了
cache_logger_on_first_use=True，前面的测试用过的 logger，capture_logs() 抓不到；所以测试用
monkeypatch 把模块里的 `log` 换成这个记录器，直接断言本来会写进日志的内容。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class LogRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def __getattr__(self, level: str) -> Callable[..., None]:
        if level.startswith("__"):
            raise AttributeError(level)

        def record(event: str, *args: Any, **fields: Any) -> None:
            if args:
                fields = {**fields, "_args": args}
            self.calls.append((level, event, fields))

        return record

    def events(self, name: str) -> list[tuple[str, str, dict[str, Any]]]:
        return [call for call in self.calls if call[1] == name]

    def text(self) -> str:
        return repr(self.calls)
