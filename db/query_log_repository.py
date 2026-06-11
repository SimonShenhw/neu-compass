"""QueryLogRepository — structured per-request telemetry (signal-driven 阶段).

One row per /search or /chat request. This table is the data source for
everything gated on "real query logs": eval-set mining (test_set v0.4),
rejection-gate recalibration, alias-candidate discovery.

PII: `query` is raw user text. Retention/redaction is the operator's
responsibility per docs/pii_redaction.md red lines — this repo only writes.

Pattern mirrors the other repositories: caller owns the connection AND the
commit. The route-side helper (api/routes/common.log_query) wraps add() in
a never-raise guard — telemetry must not break requests.
"""

from __future__ import annotations

import json
import sqlite3


class QueryLogRepository:
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
