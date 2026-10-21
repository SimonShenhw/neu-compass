"""The query_log retention inside the API process: once at startup, then every 24 hours (batch T, policy P3).

Each run replaces expired question text with its keyed hash, then deletes saved answers (and their votes) older than
the same period. The API already holds `SESSION_SECRET` and the database, so the hash key never has to reach another
container. The API restarts on every deploy, so a run also happens then. Off when `QUERY_LOG_RETENTION_DAYS` is 0 (the
code default); skipped as a whole, with one warning, when there is no `SESSION_SECRET` (production always has one,
login needs it). A failed run logs its exception type only and the next one tries again; it never stops the API. Log
lines carry counts, never text.

中文：在 API 进程里跑 query_log 到期清理：启动时一次，之后每 24 小时一次（T 批，政策 P3）。每次先把到期的问题原文换成
带密钥的哈希，再删除超过同一期限的保存回答（连同评价）。API 本来就有 `SESSION_SECRET` 和数据库，哈希密钥不必交给别的
容器；每次上线 API 都会重启，也会跑一次。`QUERY_LOG_RETENTION_DAYS` 为 0（代码默认）时关闭；没有 `SESSION_SECRET` 时
整个跳过，并记一条警告（生产一定有它，登录要用）。某一次失败只记异常类型，下一次再试，绝不让 API 停下。日志里只有
计数，没有原文。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

INTERVAL_SECONDS = 24 * 60 * 60


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run_once(*, connect: Callable[[str], Any], db_path: str, key: bytes, days: int,
             now: datetime) -> tuple[int, int, int]:
    """(rows replaced, saved answers deleted, votes deleted). 中文：（换了几行，删了几条回答，删了几个评价）。"""
    from db.query_log_retention import delete_expired_answers, redact_expired  # noqa: PLC0415

    conn = connect(db_path)
    try:
        replaced = redact_expired(conn, key=key, now=now, days=days)
        answers, votes = delete_expired_answers(conn, now=now, days=days)
        return replaced, answers, votes
    finally:
        conn.close()


def start(*, connect: Callable[[str], Any], db_path: str, secret: str, days: int, log: Any,
          clock: Callable[[], datetime] = _utc_now, interval: float = INTERVAL_SECONDS) -> Callable[[], None]:
    """Start the daily thread and return a function that stops it (also a no-op stop when nothing started)."""
    if not days:
        return lambda: None
    if not secret:
        log.warning("query_log.retention_skipped", reason="no_session_secret", days=days)
        return lambda: None
    from api.query_hash import derive_key  # noqa: PLC0415

    key, stop = derive_key(secret), threading.Event()

    def loop() -> None:
        while True:
            try:
                replaced, answers, votes = run_once(connect=connect, db_path=db_path, key=key, days=days, now=clock())
                log.info("query_log.retention", replaced=replaced, answers_deleted=answers, votes_deleted=votes,
                         days=days)
            except Exception as exc:  # noqa: BLE001 — never stop the API; the next run tries again.
                log.warning("query_log.retention_failed", exc_type=type(exc).__name__, days=days)
            if stop.wait(interval):
                return

    thread = threading.Thread(target=loop, name="query-log-retention", daemon=True)
    thread.start()

    def stop_thread() -> None:
        stop.set()
        thread.join(timeout=10)

    return stop_thread


__all__ = ["INTERVAL_SECONDS", "run_once", "start"]
