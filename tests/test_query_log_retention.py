"""Batch T, policy P3: query_log text older than the retention period becomes its keyed hash; the row stays. Saved
answers older than the same period are deleted with their votes (the user chose this on 10-21).

Synthetic databases and a synthetic secret only.
"""

import json
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.query_fields import query_fields
from api.query_hash import derive_key, keyed_hash
from db import query_log_retention as retention
from tests.conftest import INIT_SQL_PATH

ROOT = Path(__file__).resolve().parent.parent
SECRET = "synthetic-retention-secret"
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)  # cutoff for 90 days: 2026-07-23 12:00:00
OLD_ROWS = {"old-search": "2026-07-01 08:00:00", "just-old": "2026-07-23 11:59:59", "old-eval": "2026-06-30 23:00:00",
            "fake-marker": "2026-07-02 09:00:00", "iso-old": "2026-07-01T10:00:00"}
KEPT_ROWS = {"at-cutoff": "2026-07-23 12:00:00", "recent": "2026-10-20 18:00:00"}


def add(conn, text, created_at, *, route="chat", user_id=None):
    cursor = conn.execute(
        "INSERT INTO query_log (created_at, route, query, matched_via, k, latency_ms, result_course_ids, "
        "rejection_reason, user_id) VALUES (?, ?, ?, 'hybrid', 10, 12.5, '[\"c-1\"]', NULL, ?)",
        (created_at, route, text, user_id))
    conn.commit()
    return cursor.lastrowid


def seeded(conn):
    """Synthetic rows: question text names its own row, so a leak is easy to spot. 中文：每行原文写着自己是哪行。"""
    ids = {}
    for name, created in {**OLD_ROWS, **KEPT_ROWS}.items():
        text = {"fake-marker": "redacted:abc", "old-eval": "synthetic eval question"}.get(name, f"synthetic question {name}")
        ids[name] = add(conn, text, created, route="search" if name == "old-search" else "chat",
                        user_id="eval:synthetic" if name == "old-eval" else None)
    already = retention.marker("synthetic text redacted earlier", derive_key(SECRET))
    ids["already"] = add(conn, already, "2026-06-01 00:00:00")
    return ids


def rows(conn):
    return {row["log_id"]: dict(row) for row in conn.execute("SELECT * FROM query_log ORDER BY log_id")}


def test_hash_matches_the_operational_log_hash(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "session_secret", SECRET)
    for text in ["CS 5800", "推荐一门入门 ML 课", "", "a\ud800b"]:
        assert keyed_hash(text, derive_key(SECRET)) == query_fields(text)["query_hash"]
        assert retention.marker(text, derive_key(SECRET)) == (
            f"redacted:{query_fields(text)['query_hash']}:{query_fields(text)['query_len']}")
    assert derive_key(SECRET) != derive_key(SECRET + "x")


def test_expired_text_becomes_its_hash_and_everything_else_stays(empty_db):
    ids, key = seeded(empty_db), derive_key(SECRET)
    before = rows(empty_db)
    assert retention.count_expired(empty_db, now=NOW, days=90) == 5
    assert retention.redact_expired(empty_db, key=key, now=NOW, days=90) == 5
    after = rows(empty_db)
    for name in OLD_ROWS:
        log_id = ids[name]
        assert after[log_id]["query"] == retention.marker(before[log_id]["query"], key)
        assert retention.MARKER.fullmatch(after[log_id]["query"])
        assert {k: v for k, v in after[log_id].items() if k != "query"} == {
            k: v for k, v in before[log_id].items() if k != "query"}
    for name in [*KEPT_ROWS, "already"]:
        assert after[ids[name]] == before[ids[name]]
    assert not any("synthetic question old" in row["query"] for row in after.values())
    assert retention.count_expired(empty_db, now=NOW, days=90) == 0
    assert retention.redact_expired(empty_db, key=key, now=NOW, days=90) == 0
    assert rows(empty_db) == after


class Interleaved:
    """A connection on which another writer changes one row between the read and the first write batch.
    中文：读完以后、第一批写入之前，另一个写入方改了一行。"""

    def __init__(self, conn, log_id, text):
        self.conn, self.log_id, self.text, self.done = conn, log_id, text, False

    def execute(self, *args):
        return self.conn.execute(*args)

    def executemany(self, *args):
        if not self.done:
            self.done = True
            self.conn.execute("UPDATE query_log SET query = ? WHERE log_id = ?", (self.text, self.log_id))
        return self.conn.executemany(*args)

    def __enter__(self):
        return self.conn.__enter__()

    def __exit__(self, *exc):
        return self.conn.__exit__(*exc)


def test_a_row_changed_between_the_read_and_the_write_is_redacted_from_its_new_text(empty_db):
    ids, key = seeded(empty_db), derive_key(SECRET)
    changed = "synthetic text another writer put there"
    assert retention.redact_expired(Interleaved(empty_db, ids["old-search"], changed), key=key, now=NOW, days=90) == 5
    assert rows(empty_db)[ids["old-search"]]["query"] == retention.marker(changed, key)


class AlwaysChanged(Interleaved):
    """Another writer changes every row before each write batch, so no UPDATE ever matches what was read.
    中文：每一批写入之前，另一个写入方都把行改掉，UPDATE 一行也对不上。"""

    def __init__(self, conn):
        self.conn, self.batches = conn, 0

    def executemany(self, sql, params):
        self.batches += 1
        assert self.batches <= 3, "the run kept retrying rows that keep changing"
        params = list(params)
        self.conn.executemany("UPDATE query_log SET query = query || ' again' WHERE log_id = ?", [(p[1],) for p in params])
        return self.conn.executemany(sql, params)


def test_a_batch_that_changes_nothing_ends_the_run(empty_db):
    """Rows that keep changing are left for the next run instead of looping (B24). 中文：留给下一次，不打转。"""
    seeded(empty_db)
    busy = AlwaysChanged(empty_db)
    assert retention.redact_expired(busy, key=derive_key(SECRET), now=NOW, days=90) == 0
    assert busy.batches == 1 and retention.count_expired(empty_db, now=NOW, days=90) == 5


def test_small_batches_cover_every_row(empty_db, monkeypatch):
    monkeypatch.setattr(retention, "BATCH", 2)
    for i in range(7):
        add(empty_db, f"synthetic batch question {i}", "2026-05-01 00:00:00")
    assert retention.redact_expired(empty_db, key=derive_key(SECRET), now=NOW, days=90) == 7
    assert all(retention.MARKER.fullmatch(row["query"]) for row in rows(empty_db).values())


def test_the_redaction_alone_leaves_saved_answers_and_votes(empty_db):
    """Their own deletion is below. 中文：回答的删除在下面单独测。"""
    log_id = add(empty_db, "synthetic answered question", "2026-05-01 00:00:00")
    empty_db.execute("INSERT INTO chat_answers (answer_id, query_log_id, answer_text, answer_sha256, feedback_token_hash, "
                     "prompt_version, request_context, expires_at) VALUES (?, ?, 'synthetic answer', ?, ?, '4.5', '{}', 0)",
                     ("a" * 32, log_id, "b" * 64, "c" * 64))
    empty_db.execute("INSERT INTO answer_feedback (answer_id, rating) VALUES (?, 'up')", ("a" * 32,))
    empty_db.commit()
    assert retention.redact_expired(empty_db, key=derive_key(SECRET), now=NOW, days=90) == 1
    assert empty_db.execute("SELECT count(*) FROM chat_answers").fetchone()[0] == 1
    assert empty_db.execute("SELECT rating FROM answer_feedback").fetchone()[0] == "up"


@pytest.mark.parametrize("text", ["redacted:" + "0" * 16 + ":x", "redacted:" + "G" * 16 + ":5", "redacted:" + "0" * 16 + ":",
                                  "redacted:" + "0" * 15 + ":12", "xredacted:" + "0" * 16 + ":3",
                                  # A24 L2: SQLite's text functions stop at a NUL. 中文：SQLite 的文字函数遇 NUL 就停。
                                  "redacted:" + "0" * 16 + ":12" + chr(0) + "synthetic hidden question"])
def test_only_the_exact_marker_shape_counts_as_already_redacted(empty_db, text):
    log_id = add(empty_db, text, "2026-05-01 00:00:00")
    assert retention.redact_expired(empty_db, key=derive_key(SECRET), now=NOW, days=90) == 1
    assert rows(empty_db)[log_id]["query"] == retention.marker(text, derive_key(SECRET))


@pytest.mark.parametrize(("kwargs", "message"), [
    ({"days": 0}, "days"), ({"days": True}, "days"), ({"days": 1.5}, "days"),
    ({"now": datetime(2026, 10, 21, 12, 0)}, "timezone"), ({"key": b"short"}, "key"), ({"key": "not-bytes" * 4}, "key"),
])
def test_bad_arguments_change_nothing(empty_db, kwargs, message):
    add(empty_db, "synthetic question", "2026-05-01 00:00:00")
    before = rows(empty_db)
    arguments = {"key": derive_key(SECRET), "now": NOW, "days": 90, **kwargs}
    with pytest.raises(ValueError, match=message):
        retention.redact_expired(empty_db, **arguments)
    assert rows(empty_db) == before


# === Saved answers: the same period, then deleted with their votes ===

OLD_ANSWERS = {"old-voted": "2026-07-01 08:00:00", "old-unvoted": "2026-06-15 00:00:00",
               "just-old": "2026-07-23 11:59:59", "iso-old": "2026-07-01T10:00:00"}
KEPT_ANSWERS = {"at-cutoff": "2026-07-23 12:00:00", "recent": "2026-10-20 18:00:00"}
VOTES = {"old-voted": "up", "just-old": "down", "iso-old": "up", "at-cutoff": "up", "recent": "down"}


def add_answer(conn, log_id, created_at, n, vote=None):
    answer_id = f"{n:032x}"
    conn.execute("INSERT INTO chat_answers (answer_id, query_log_id, answer_text, answer_sha256, feedback_token_hash, "
                 "prompt_version, request_context, created_at, expires_at) VALUES (?, ?, ?, ?, ?, '4.5', '{}', ?, 0)",
                 (answer_id, log_id, f"synthetic answer {n}", "b" * 64, "c" * 64, created_at))
    if vote:
        conn.execute("INSERT INTO answer_feedback (answer_id, rating) VALUES (?, ?)", (answer_id, vote))
    conn.commit()
    return answer_id


def answers_seeded(conn):
    """Each answer on its own synthetic question, on either side of the cutoff. 中文：期限两边各有回答。"""
    ids = {}
    for n, (name, created) in enumerate({**OLD_ANSWERS, **KEPT_ANSWERS}.items(), start=1):
        ids[name] = add_answer(conn, add(conn, f"synthetic question {name}", created), created, n, VOTES.get(name))
    return ids


def answer_ids(conn, table):
    return sorted(row[0] for row in conn.execute(f"SELECT answer_id FROM {table}"))


def test_expired_answers_go_with_their_votes_and_newer_ones_stay(empty_db):
    ids = answers_seeded(empty_db)
    questions = rows(empty_db)
    assert retention.count_expired_answers(empty_db, now=NOW, days=90) == (4, 3)
    assert retention.delete_expired_answers(empty_db, now=NOW, days=90) == (4, 3)
    kept = sorted(ids[name] for name in KEPT_ANSWERS)
    assert answer_ids(empty_db, "chat_answers") == kept and answer_ids(empty_db, "answer_feedback") == kept
    assert rows(empty_db) == questions  # The question rows are the redaction's job. 中文：问题行归换哈希管。
    assert retention.count_expired_answers(empty_db, now=NOW, days=90) == (0, 0)
    assert retention.delete_expired_answers(empty_db, now=NOW, days=90) == (0, 0)


def test_votes_go_first_so_none_is_left_without_the_cascade(empty_db):
    answers_seeded(empty_db)
    empty_db.execute("PRAGMA foreign_keys = OFF")
    assert retention.delete_expired_answers(empty_db, now=NOW, days=90) == (4, 3)
    orphans = empty_db.execute("SELECT count(*) FROM answer_feedback WHERE answer_id NOT IN "
                               "(SELECT answer_id FROM chat_answers)").fetchone()[0]
    assert orphans == 0 and len(answer_ids(empty_db, "answer_feedback")) == 2


def test_a_database_without_saved_answers_has_none_to_delete(empty_db):
    add(empty_db, "synthetic question", "2026-05-01 00:00:00")
    empty_db.executescript("DROP TABLE answer_feedback; DROP TABLE chat_answers;")
    assert retention.count_expired_answers(empty_db, now=NOW, days=90) == (0, 0)
    assert retention.delete_expired_answers(empty_db, now=NOW, days=90) == (0, 0)
    assert retention.redact_expired(empty_db, key=derive_key(SECRET), now=NOW, days=90) == 1


@pytest.mark.parametrize("kwargs", [{"days": 0}, {"days": True}, {"days": 1.5}, {"now": datetime(2026, 10, 21, 12, 0)}])
def test_answer_deletion_with_bad_arguments_deletes_nothing(empty_db, kwargs):
    answers_seeded(empty_db)
    for function in (retention.count_expired_answers, retention.delete_expired_answers):
        with pytest.raises(ValueError):
            function(empty_db, **{"now": NOW, "days": 90, **kwargs})
    assert len(answer_ids(empty_db, "chat_answers")) == 6 and len(answer_ids(empty_db, "answer_feedback")) == 5


# === The daily task inside the API ===


class Log:
    def __init__(self):
        self.events, self.lock = [], threading.Lock()

    def _add(self, level, event, **fields):
        with self.lock:
            self.events.append((level, event, fields))

    def info(self, event, **fields):
        self._add("info", event, **fields)

    def warning(self, event, **fields):
        self._add("warning", event, **fields)


def file_db(tmp_path, *, answers=False):
    path = tmp_path / "synthetic.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(INIT_SQL_PATH.read_text(encoding="utf-8"))
    conn.row_factory = sqlite3.Row
    ids = seeded(conn)
    if answers:  # One expired and one kept, each with a vote. 中文：一条到期、一条没到期，各带一个评价。
        add_answer(conn, ids["old-search"], OLD_ROWS["old-search"], 1, "up")
        add_answer(conn, ids["recent"], KEPT_ROWS["recent"], 2, "down")
    conn.close()
    return path


def wait_for(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def test_task_is_off_without_days():
    from api import query_log_retention_task as task

    log, calls = Log(), []

    def connect(path):
        calls.append(path)
        return sqlite3.connect(":memory:")

    stop = task.start(connect=connect, db_path="unused", secret=SECRET, days=0, log=log, interval=0.01)
    time.sleep(0.2)  # long enough for a thread that should not exist to have run. 中文：不该有的线程也该跑过了。
    stop()
    assert calls == [] and log.events == [] and not [t for t in threading.enumerate() if t.name == "query-log-retention"]


def test_without_a_secret_the_task_keeps_the_text_but_still_deletes_expired_answers(tmp_path):
    """A24 L4: hashing needs the key, deleting answers does not. 中文：换哈希要密钥，删回答不要。"""
    from api import query_log_retention_task as task
    from db.connection import connect

    path, log = file_db(tmp_path, answers=True), Log()
    stop = task.start(connect=connect, db_path=str(path), secret="", days=90, log=log, clock=lambda: NOW, interval=0.05)
    try:
        assert wait_for(lambda: len([1 for _, event, _ in log.events if event == "query_log.retention"]) >= 2)
    finally:
        stop()
    assert [e for e in log.events if e[1] == "query_log.retention_skipped"] == [
        ("warning", "query_log.retention_skipped", {"reason": "no_session_secret", "days": 90})]  # once, at start
    runs = [fields for _, event, fields in log.events if event == "query_log.retention"]
    assert runs[0] == {"replaced": None, "answers_deleted": 1, "votes_deleted": 1, "days": 90}
    conn = sqlite3.connect(path)
    assert [text for (text,) in conn.execute("SELECT query FROM query_log") if text.startswith("synthetic question old")]
    assert answer_ids(conn, "chat_answers") == answer_ids(conn, "answer_feedback") == [f"{2:032x}"]
    conn.close()


def test_connections_overwrite_what_they_delete(monkeypatch):
    """A24 L3: secure_delete is on even where SQLite's build default is off (simulated here).
    中文：即使 SQLite 编译默认关着（这里模拟），连接也打开 secure_delete。"""
    import db.connection as connection

    real = sqlite3.connect

    def default_off(*args, **kwargs):
        conn = real(*args, **kwargs)
        conn.execute("PRAGMA secure_delete = OFF")
        return conn

    monkeypatch.setattr(connection.sqlite3, "connect", default_off)
    conn = connection.connect(":memory:")
    assert conn.execute("PRAGMA secure_delete").fetchone()[0] == 1
    conn.close()


@pytest.mark.parametrize("checkpointed_first", [True, False])
def test_after_a_run_the_old_text_is_gone_from_the_files_on_disk(tmp_path, checkpointed_first):
    """A24 L3: with another connection open, as in the API, closing the run's connection does not checkpoint, so the
    run checkpoints itself. The old text can be in the database file or still in WAL frames, which stay in the WAL
    file until it is truncated, so the run truncates it. 中文：和 API 里一样另有连接开着，关掉这次的连接不会
    checkpoint，所以要自己做。旧文字可能在库文件里，也可能还在 WAL 的旧帧里（WAL 文件不截断，旧帧就一直在），所以要截断。"""
    from api import query_log_retention_task as task
    from db.connection import connect

    path = tmp_path / "synthetic.sqlite3"
    setup = connect(path)
    setup.executescript(INIT_SQL_PATH.read_text(encoding="utf-8"))
    texts = [f"synthetic private question number {i:04d}" for i in range(40)]
    for text in texts:
        add(setup, text, "2026-05-01 00:00:00")
    add_answer(setup, add(setup, "synthetic question with a saved answer", "2026-05-01 00:00:00"), "2026-05-01 00:00:00",
               7, "up")
    if checkpointed_first:  # the text is in the database file. 中文：原文在库文件里。
        setup.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    other = connect(path)
    other.execute("SELECT count(*) FROM query_log").fetchall()
    replaced, answers, votes = task.run_once(connect=connect, db_path=str(path), key=derive_key(SECRET), days=90, now=NOW)
    assert (replaced, answers, votes) == (41, 1, 1)
    wal = path.with_name(path.name + "-wal")
    on_disk = path.read_bytes() + (wal.read_bytes() if wal.exists() else b"")
    assert not [text for text in texts if text.encode() in on_disk] and b"synthetic answer 7" not in on_disk
    other.close()
    setup.close()


class NoCheckpoint:
    """A connection whose WAL checkpoint fails, after the run's own work has committed. 中文：checkpoint 失败的连接。"""

    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, *args):
        if "wal_checkpoint" in sql:
            raise sqlite3.OperationalError("synthetic checkpoint failure")
        return self.conn.execute(sql, *args)

    def executemany(self, *args):
        return self.conn.executemany(*args)

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self.conn.__enter__()

    def __exit__(self, *exc):
        return self.conn.__exit__(*exc)


def test_a_failed_checkpoint_does_not_turn_a_finished_run_into_a_failed_one(tmp_path):
    """The checkpoint is best effort: the replaced text and deleted answers are committed before it (A24 L3).
    中文：checkpoint 只是尽力而为；换哈希和删回答在它之前已经提交。"""
    from api import query_log_retention_task as task
    from db.connection import connect

    path = file_db(tmp_path, answers=True)
    result = task.run_once(connect=lambda p: NoCheckpoint(connect(p)), db_path=str(path), key=derive_key(SECRET),
                           days=90, now=NOW)
    assert result == (5, 1, 1)
    conn = sqlite3.connect(path)
    assert retention.count_expired(conn, now=NOW, days=90) == 0 and answer_ids(conn, "chat_answers") == [f"{2:032x}"]
    conn.close()


def test_task_runs_at_start_then_every_interval_and_stops(tmp_path):
    from api import query_log_retention_task as task
    from db.connection import connect

    path, log = file_db(tmp_path, answers=True), Log()
    stop = task.start(connect=connect, db_path=str(path), secret=SECRET, days=90, log=log, clock=lambda: NOW,
                      interval=0.05)
    try:
        assert wait_for(lambda: len([1 for _, event, _ in log.events if event == "query_log.retention"]) >= 2)
    finally:
        stop()
    runs = [fields for _, event, fields in log.events if event == "query_log.retention"]
    assert runs[0] == {"replaced": 5, "answers_deleted": 1, "votes_deleted": 1, "days": 90}
    assert runs[1] == {"replaced": 0, "answers_deleted": 0, "votes_deleted": 0, "days": 90}
    assert not [event for _, event, _ in log.events if event == "query_log.retention_skipped"]  # it has the key
    assert not [name for name in threading.enumerate() if name.name == "query-log-retention"]
    conn = sqlite3.connect(path)
    assert not [text for (text,) in conn.execute("SELECT query FROM query_log") if text.startswith("synthetic question old")]
    assert answer_ids(conn, "chat_answers") == answer_ids(conn, "answer_feedback") == [f"{2:032x}"]
    conn.close()


def test_a_failed_run_logs_the_type_only_and_the_next_run_still_happens(tmp_path):
    from api import query_log_retention_task as task
    from db.connection import connect

    path, log, calls = file_db(tmp_path), Log(), []

    def flaky(db_path):
        calls.append(db_path)
        if len(calls) == 1:
            raise sqlite3.OperationalError("synthetic locked database at /secret/path")
        return connect(db_path)

    stop = task.start(connect=flaky, db_path=str(path), secret=SECRET, days=90, log=log, clock=lambda: NOW, interval=0.05)
    try:
        assert wait_for(lambda: any(event == "query_log.retention" for _, event, _ in log.events))
    finally:
        stop()
    assert log.events[0] == ("warning", "query_log.retention_failed", {"exc_type": "OperationalError", "days": 90})
    assert "secret" not in json.dumps([fields for _, _, fields in log.events])


def test_lifespan_starts_the_task_with_the_settings_and_stops_it(monkeypatch):
    import api.main as main
    from api import query_log_retention_task as task
    from config import settings
    from fastapi.testclient import TestClient

    started, stopped = [], []
    monkeypatch.setattr(settings, "query_log_retention_days", 45)  # not compose's 90. 中文：不用 compose 的 90。
    monkeypatch.setattr(settings, "session_secret", SECRET)
    monkeypatch.setattr(main.FaissIndex, "load", staticmethod(lambda *a, **k: SimpleNamespace(count=1, manifest=object())))
    monkeypatch.setattr(main, "connect", lambda path: sqlite3.connect(":memory:"))
    monkeypatch.setattr(main.BM25Corpus, "from_db", staticmethod(lambda conn: SimpleNamespace(count=1)))
    monkeypatch.setattr(main, "_build_inference_stack", lambda log: (object(), None))
    monkeypatch.setattr(task, "start", lambda **kwargs: started.append(kwargs) or (lambda: stopped.append(True)))
    with TestClient(main.create_app(run_startup=True)):
        assert len(started) == 1 and not stopped
    assert started[0]["days"] == 45 and started[0]["secret"] == SECRET and started[0]["db_path"] == settings.sqlite_path
    assert started[0]["connect"] is main.connect and stopped == [True]


# === The manual command ===


def run_cli(*args, env_secret=SECRET, days=None):
    env = {"PATH": "/usr/bin:/bin", "GEMINI_API_KEY": "ci-placeholder-not-a-secret", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONIOENCODING": "utf-8", "SESSION_SECRET": env_secret}
    if days is not None:
        env["QUERY_LOG_RETENTION_DAYS"] = str(days)
    return subprocess.run([sys.executable, "scripts/redact_query_log.py", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)


def test_cli_dry_run_counts_and_a_real_run_replaces_and_deletes(tmp_path):
    path = file_db(tmp_path, answers=True)
    dry = run_cli("--db-path", str(path), "--days", "90", "--dry-run", env_secret="")
    assert dry.returncode == 0, dry.stderr
    expected_dry = sqlite3.connect(path)
    count = retention.count_expired(expected_dry, now=datetime.now(timezone.utc), days=90)
    answers, votes = retention.count_expired_answers(expected_dry, now=datetime.now(timezone.utc), days=90)
    expected_dry.close()
    assert answers >= 1  # the 2026-07-01 answer, on any date the suite runs. 中文：7 月 1 日那条总是到期的。
    assert json.loads(dry.stdout) == {"dry_run": True, "days": 90, "would_replace": count,
                                      "would_delete_answers": answers, "would_delete_votes": votes}
    real = run_cli("--db-path", str(path), days=90)
    assert real.returncode == 0, real.stderr
    assert json.loads(real.stdout) == {"dry_run": False, "days": 90, "replaced": count, "answers_deleted": answers,
                                       "votes_deleted": votes}
    output = real.stdout + real.stderr + dry.stdout + dry.stderr
    assert "synthetic question" not in output and "synthetic answer" not in output
    after = sqlite3.connect(path)
    assert retention.count_expired_answers(after, now=datetime.now(timezone.utc), days=90) == (0, 0)
    assert len(answer_ids(after, "chat_answers")) == 2 - answers
    after.close()


@pytest.mark.parametrize(("args", "secret", "days", "code"), [
    (("--days", "90"), "", None, 2),       # a real run needs the key
    ((), SECRET, None, 2),                 # retention off and no --days
    (("--days", "0"), SECRET, None, 2),
    (("--days", "0"), SECRET, 90, 2),      # an explicit 0 is not "use the setting" (B24)
    (("--days", "ninety"), SECRET, None, 2),
])
def test_cli_refuses_without_a_key_or_days_and_changes_nothing(tmp_path, args, secret, days, code):
    path = file_db(tmp_path, answers=True)
    before = sqlite3.connect(path).execute("SELECT query FROM query_log ORDER BY log_id").fetchall()
    result = run_cli("--db-path", str(path), *args, env_secret=secret, days=days)
    assert result.returncode == code
    assert "ninety" not in result.stderr  # argparse would echo the value; the safe parser does not
    assert sqlite3.connect(path).execute("SELECT query FROM query_log ORDER BY log_id").fetchall() == before
    assert len(answer_ids(sqlite3.connect(path), "answer_feedback")) == 2


def test_cli_missing_database_fails_without_creating_it(tmp_path):
    missing = tmp_path / "missing.sqlite3"
    result = run_cli("--db-path", str(missing), "--days", "90")
    assert result.returncode == 1 and not missing.exists()


def test_cli_clears_the_old_text_from_disk_while_another_connection_is_open(tmp_path):
    """As when the API is running: closing the command's connection does not checkpoint, so it checkpoints itself
    (A24 L3). 中文：和 API 开着库时一样，关掉命令的连接不会 checkpoint，所以命令自己做。"""
    path = file_db(tmp_path)
    other = sqlite3.connect(path)
    other.execute("SELECT count(*) FROM query_log").fetchall()
    result = run_cli("--db-path", str(path), "--days", "90")
    assert result.returncode == 0, result.stderr
    wal = path.with_name(path.name + "-wal")
    on_disk = path.read_bytes() + (wal.read_bytes() if wal.exists() else b"")
    assert b"synthetic question old-search" not in on_disk and b"synthetic eval question" not in on_disk
    other.close()


@pytest.mark.parametrize("dry_run", [False, True])
def test_cli_storage_error_fails_with_the_fixed_line_only(tmp_path, dry_run):
    """A file that is not a database: exit 1, one fixed line, no exception text (B24). 中文：固定一行，不带异常原文。"""
    path = tmp_path / "synthetic.sqlite3"
    path.write_bytes(b"synthetic bytes that are not a database" * 4)
    before = path.read_bytes()
    result = run_cli("--db-path", str(path), "--days", "90", *(["--dry-run"] if dry_run else []))
    assert result.returncode == 1 and result.stdout == ""
    assert result.stderr == "Query log retention failed (input/storage); a partial run keeps every finished batch.\n"
    assert path.read_bytes() == before


@pytest.mark.parametrize("value", ["true", "-1", "3651", "1.5"])
def test_retention_days_setting_rejects_booleans_and_bad_numbers(monkeypatch, value):
    from config.settings import Settings
    from pydantic import ValidationError

    monkeypatch.setenv("QUERY_LOG_RETENTION_DAYS", value)
    with pytest.raises(ValidationError):
        Settings()
    monkeypatch.setenv("QUERY_LOG_RETENTION_DAYS", "90")
    assert Settings().query_log_retention_days == 90


@pytest.mark.parametrize("name", ["query_log_retention_days", "model_daily_call_limit"])
def test_a_python_boolean_is_not_taken_as_one(name):
    """An env string like "true" already fails int parsing; this is the guard for a value set in code."""
    from config.settings import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(**{name: True})
    assert getattr(Settings(**{name: 1}), name) == 1
