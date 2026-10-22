"""Replace query_log question text older than the retention period with its keyed hash (batch T, policy P3).

The user chose 90 days on 10-21. A row is kept, so the counts, the routes and the hit mix stay measurable; only
`query` changes, to `redacted:<16 hex>:<length>`. The hash and the length are the ones the operational log already
carries (`api.query_fields`), so a log line and its row still match after the text is gone. A row whose text already
has exactly that shape is left alone, which also makes a second run a no-op. The redaction leaves saved answers alone;
`delete_expired_answers` handles them.

Needs a real key (`api.query_hash.derive_key(SESSION_SECRET)`): the callers refuse to run without one, because a
random key would destroy the text and leave hashes that match nothing. Saved answers (opt-in) older than the same
period are deleted with their votes (`delete_expired_answers`; the user chose this on 10-21 too).

中文：把超过留存期的 query_log 问题原文换成带密钥的哈希（T 批，政策 P3；用户 10-21 定为 90 天）。行保留，提问量、
路由和命中方式照样能统计；只改 `query` 一列，换成 `redacted:<16 位十六进制>:<长度>`。哈希和长度就是运行日志里已有的
那两个（`api.query_fields`），所以原文没了以后，日志行和这一行仍然对得上。原文本来就是这个形状的行不动，所以第二遍
不会再改。换哈希不碰保存的回答，它们由 `delete_expired_answers` 处理。必须有真密钥：没有密钥时调用方拒绝运行，因为随机密钥会
毁掉原文，留下的哈希又什么也对不上。超过同一期限的保存回答（勾选以后才有）连同评价一起删除（`delete_expired_answers`；
也是用户 10-21 定的）。
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone

from api.query_hash import HASH_CHARS, keyed_hash

PREFIX = "redacted:"
MARKER = re.compile(rf"redacted:[0-9a-f]{{{HASH_CHARS}}}:[0-9]+")
BATCH = 500
CHECKPOINT_WAIT_MS = 100  # see checkpoint(). 中文：见 checkpoint()。
# Already redacted: the prefix, 16 lowercase hex characters, a colon, then only digits (at least one). SQLite's
# length(), substr() and GLOB stop at a NUL, so the byte length must equal the character length too: a marker is pure
# ASCII, and a crafted "marker + NUL + text" would otherwise pass and keep its text forever (A24 L2).
# 中文：已经换过的行：前缀、16 位小写十六进制、冒号，后面全是数字（至少一位）。SQLite 的 length()、substr()、GLOB
# 遇到 NUL 就停，所以还要求字节数等于字符数：标记全是 ASCII，否则「标记＋NUL＋原文」会被当成已经换过，原文永远留着。
_ALREADY = ("length(query) > 26 AND length(CAST(query AS BLOB)) = length(query) "
            "AND substr(query, 1, 9) = 'redacted:' AND substr(query, 26, 1) = ':' "
            "AND substr(query, 10, 16) NOT GLOB '*[^0-9a-f]*' AND substr(query, 27) NOT GLOB '*[^0-9]*'")


def marker(text: str, key: bytes) -> str:
    return f"{PREFIX}{keyed_hash(text, key)}:{len(text)}"


def _cutoff(now: datetime, days: int) -> str:
    if type(days) is not int or days < 1:
        raise ValueError("Retention needs a whole number of days, at least 1")
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    # query_log.created_at is SQLite's CURRENT_TIMESTAMP: UTC, "YYYY-MM-DD HH:MM:SS". 中文：UTC 时间。
    return (now.astimezone(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def count_expired(conn: sqlite3.Connection, *, now: datetime, days: int) -> int:
    """How many rows a run would change, without changing anything. 中文：只数会改几行，不改。"""
    return conn.execute(f"SELECT count(*) FROM query_log WHERE julianday(created_at) < julianday(?) AND NOT ({_ALREADY})",
                        (_cutoff(now, days),)).fetchone()[0]


def _has_answers(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_answers'").fetchone() is not None


_ANSWERS_EXPIRED = "SELECT answer_id FROM chat_answers WHERE julianday(created_at) < julianday(?)"


def count_expired_answers(conn: sqlite3.Connection, *, now: datetime, days: int) -> tuple[int, int]:
    """(saved answers, votes) a run would delete, without deleting. 中文：只数会删几条回答、几个评价。"""
    cutoff = _cutoff(now, days)
    if not _has_answers(conn):
        return 0, 0
    answers = conn.execute(f"SELECT count(*) FROM ({_ANSWERS_EXPIRED})", (cutoff,)).fetchone()[0]
    votes = conn.execute(f"SELECT count(*) FROM answer_feedback WHERE answer_id IN ({_ANSWERS_EXPIRED})",
                         (cutoff,)).fetchone()[0]
    return answers, votes


def delete_expired_answers(conn: sqlite3.Connection, *, now: datetime, days: int) -> tuple[int, int]:
    """Delete saved answers (opt-in, `chat_answers`) older than the same period, with their votes (the user chose
    on 10-21: an answer can restate the question). Votes go first, so this holds even without the foreign key's
    cascade. Returns (answers, votes). 中文：删除超过同一期限的保存回答（勾选以后才有）和它们的评价（用户 10-21 定：
    回答可能复述问题）。先删评价，所以没有外键级联也成立。返回（回答数，评价数）。"""
    cutoff = _cutoff(now, days)
    if not _has_answers(conn):
        return 0, 0
    with conn:
        votes = conn.execute(f"DELETE FROM answer_feedback WHERE answer_id IN ({_ANSWERS_EXPIRED})", (cutoff,)).rowcount
        answers = conn.execute("DELETE FROM chat_answers WHERE julianday(created_at) < julianday(?)", (cutoff,)).rowcount
    return answers, votes


def checkpoint(conn: sqlite3.Connection) -> None:
    """Move the WAL into the database file and truncate it, best effort, after a run (A24 L3). With secure_delete on
    (db.connection.connect), the replaced text and the deleted answers are then gone from the files on disk.

    While a TRUNCATE checkpoint waits for a reader on an older snapshot (the backup sidecar's copy, the weekly stats, an
    export), SQLite holds back every new writer. So it waits at most CHECKPOINT_WAIT_MS, not the connection's 5 seconds,
    and the API's writes go through (A24 recheck LOW-R1). If it gives up, the WAL keeps the old frames until the next
    run truncates it, or until the last connection closes: SQLite's own automatic checkpoints never truncate the file.
    中文：跑完以后尽量把 WAL 写回库文件并截断。secure_delete 打开时（db.connection.connect），换掉的原文和删掉的回答就
    从磁盘上的文件里消失了。TRUNCATE 在等旧快照上的读者（备份边车的复制、每周统计、导出）时，SQLite 会挡住所有新的写入，
    所以最多只等 CHECKPOINT_WAIT_MS，不等连接默认的 5 秒，API 的写入就不会被挡住。等不到就放弃，WAL 里的旧帧留到下一次
    运行截断，或者最后一个连接关闭；SQLite 自己的自动 checkpoint 从来不截断文件。"""
    try:
        previous = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        conn.execute(f"PRAGMA busy_timeout = {CHECKPOINT_WAIT_MS}")
    except sqlite3.Error:
        return
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    except sqlite3.Error:
        pass
    finally:
        try:
            conn.execute(f"PRAGMA busy_timeout = {int(previous)}")
        except sqlite3.Error:
            pass


def redact_expired(conn: sqlite3.Connection, *, key: bytes, now: datetime, days: int) -> int:
    """Replace the text of every expired row, in short write transactions of at most BATCH rows; returns the count.

    Each UPDATE also checks the text it read, so a row that changed in between is left for the next batch.
    中文：分批（每批最多 BATCH 行、各自一个短的写事务）替换所有到期行的原文，返回改了几行。每条 UPDATE 都核对读到的原文，
    中间被改过的行留给下一批。
    """
    if not isinstance(key, bytes) or len(key) < 16:
        raise ValueError("Retention needs the derived key")
    cutoff = _cutoff(now, days)
    total = 0
    while True:
        rows = conn.execute(f"SELECT log_id, query FROM query_log WHERE julianday(created_at) < julianday(?) "
                            f"AND NOT ({_ALREADY}) ORDER BY log_id LIMIT ?", (cutoff, BATCH)).fetchall()
        if not rows:
            return total
        with conn:
            changed = conn.executemany("UPDATE query_log SET query = ? WHERE log_id = ? AND query = ?",
                                       [(marker(text, key), log_id, text) for log_id, text in rows]).rowcount
        total += changed
        if changed == 0:  # Every row changed under us; let the next run see them. 中文：都被别人改了，下次再看。
            return total


__all__ = ["BATCH", "CHECKPOINT_WAIT_MS", "MARKER", "PREFIX", "checkpoint", "count_expired", "count_expired_answers",
           "delete_expired_answers", "marker", "redact_expired"]
