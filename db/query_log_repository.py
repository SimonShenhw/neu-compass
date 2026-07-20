"""QueryLogRepository — structured per-request telemetry (signal-driven 阶段).

One row per /search or /chat request. This table is the data source for
everything gated on "real query logs": eval-set mining (test_set v0.4),
rejection-gate recalibration, alias-candidate discovery.

每个 /search 或 /chat 请求对应一行记录。这张表是所有依赖"真实查询日志"
才能做的事情的数据来源:评测集挖掘(test_set v0.4)、拒答门重新校准、
别名候选发现。

PII: `query` is raw user text. Retention/redaction is the operator's
responsibility per docs/pii_redaction.md red lines — this repo only writes.

PII 提示:`query` 字段是用户输入的原始文本。留存 / 脱敏是运维人员的
责任,遵循 docs/pii_redaction.md 里的红线 —— 本仓储只负责写入,不做脱敏。

Pattern mirrors the other repositories: caller owns the connection AND the
commit. The route-side helper (api/routes/common.log_query) wraps add() in
a never-raise guard — telemetry must not break requests.

写法与其他仓储一致:连接(connection)和 commit 都由调用方负责。路由层的
辅助函数(api/routes/common.log_query)把 add() 包在一个"绝不抛出"的
保护层里 —— 遥测(telemetry)绝不能把正常请求搞挂。
"""

from __future__ import annotations

import json
import sqlite3


class QueryLogRepository:
    # Caller owns the connection lifecycle and the commit, same contract as
    # every other repository in this package — this class never commits or
    # closes the connection it's given.
    # 中文:连接(connection)的生命周期和 commit 都由调用方负责,与本包里
    # 其他仓储遵循同一套约定 —— 本类自己从不提交或关闭传入的连接。
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(
        self,
        *,
        route: str,
        query: str,
        matched_via: str | None,
        k: int | None,
        latency_ms: float | None,
        result_course_ids: list[str] | None = None,
        rejection_reason: str | None = None,
        user_id: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO query_log (
                route, query, matched_via, k, latency_ms,
                result_course_ids, rejection_reason, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                route, query, matched_via, k, latency_ms,
                json.dumps(result_course_ids or [], ensure_ascii=False),
                rejection_reason, user_id,
            ),
        )

    def list_recent(self, limit: int = 100) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM query_log ORDER BY log_id DESC LIMIT ?", (limit,)
        ).fetchall()

    def count(self) -> int:
        return int(
            self._conn.execute("SELECT COUNT(*) AS n FROM query_log").fetchone()["n"]
        )


__all__ = ["QueryLogRepository"]
