"""Batch T, policy P7: weekly read-only counts with no question text, emails or IDs. Synthetic databases only."""

import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from scripts.weekly_stats import weekly_stats
from tests.conftest import INIT_SQL_PATH

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 21)  # window for 7 days: 2026-10-15 .. 2026-10-21
SECRET_TEXT = "synthetic private question text"


def seeded_db(tmp_path):
    path = tmp_path / "synthetic.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(INIT_SQL_PATH.read_text(encoding="utf-8"))
    rows = [("2026-10-15 00:00:00", "search", "alias", None),  # the window's first second. 中文：窗口的第一秒。
            ("2026-10-15 09:00:00", "search", "alias", None), ("2026-10-15 10:00:00", "chat", "hybrid", None),
            ("2026-10-21 23:59:59", "chat", "rejected", None), ("2026-10-20 08:00:00", "search", "hybrid", "eval:synthetic"),
            ("2026-10-18 12:00:00", "chat", "made_up_mode", None), ("2026-10-14 23:59:59", "search", "hybrid", None),
            ("2026-10-22 00:00:00", "chat", "hybrid", None)]
    for created, route, mode, user in rows:
        conn.execute("INSERT INTO query_log (created_at, route, query, matched_via, user_id, result_course_ids) "
                     "VALUES (?, ?, ?, ?, ?, '[\"c-synthetic-course\"]')", (created, route, SECRET_TEXT, mode, user))
    conn.execute("INSERT INTO users (user_id, email, domain, created_at) VALUES "
                 "('synthetic-sub-1', 'synthetic1@northeastern.edu', 'northeastern.edu', '2026-10-16 00:00:00'), "
                 "('synthetic-sub-2', 'synthetic2@northeastern.edu', 'northeastern.edu', '2026-09-01 00:00:00')")
    for i, status in enumerate(["pending", "pending", "published", "rejected"]):
        conn.execute("INSERT INTO coop_submissions (coop_id, contributor_user_id, submission_key, group_key, payload, "
                     "review_status) VALUES (?, 'synthetic-sub-1', ?, 'g', '{}', ?)", (f"coop-{i}", f"k{i}", status))
    for i, (created, rating, updated) in enumerate([("2026-10-16 00:00:00", "up", "2026-10-16 00:00:00"),
                                                    ("2026-10-10 00:00:00", "down", "2026-10-17 00:00:00"),
                                                    ("2026-10-10 00:00:00", "up", "2026-10-10 00:00:00")]):
        conn.execute("INSERT INTO chat_answers (answer_id, query_log_id, answer_text, answer_sha256, feedback_token_hash, "
                     "prompt_version, request_context, created_at, expires_at) VALUES (?, ?, 'synthetic answer', ?, ?, "
                     "'4.5', '{}', ?, 0)", (f"{i:032x}", i + 1, "a" * 64, "b" * 64, created))
        conn.execute("INSERT INTO answer_feedback (answer_id, rating, updated_at) VALUES (?, ?, ?)", (f"{i:032x}", rating, updated))
    conn.commit()
    conn.close()
    (tmp_path / "model_budget.json").write_text(json.dumps({"day": "2026-10-21", "calls": 17}), encoding="utf-8")
    return path


def test_counts_for_the_window_by_day_route_traffic_and_mode(tmp_path):
    report = weekly_stats(seeded_db(tmp_path), days=7, today=TODAY)
    assert report["window"] == {"first_day": "2026-10-15", "last_day": "2026-10-21", "days": 7}
    per_day = report["questions_per_day"]
    assert list(per_day) == [f"2026-10-{d}" for d in range(15, 22)]
    assert per_day["2026-10-15"] == {"unmarked_chat": 1, "unmarked_search": 2}
    assert per_day["2026-10-18"] == {"unmarked_chat": 1} and per_day["2026-10-20"] == {"eval_search": 1}
    assert per_day["2026-10-21"] == {"unmarked_chat": 1} and per_day["2026-10-16"] == {}
    assert report["unmarked_retrieval_modes"] == {"alias": 2, "hybrid": 1, "rejected": 1, "unknown": 1}
    assert report["votes"] == {"up": 1, "down": 1} and report["saved_answers"] == 1
    assert report["accounts"] == {"total": 2, "created_in_window": 1}
    assert report["coop_submissions"] == {"pending": 2, "published": 1}
    assert report["model_calls_today"] == 17


def test_a_stale_or_missing_budget_file_is_left_out(tmp_path):
    path = seeded_db(tmp_path)
    (tmp_path / "model_budget.json").write_text(json.dumps({"day": "2026-10-20", "calls": 5}), encoding="utf-8")
    assert "model_calls_today" not in weekly_stats(path, days=7, today=TODAY)
    (tmp_path / "model_budget.json").unlink()
    assert "model_calls_today" not in weekly_stats(path, days=7, today=TODAY)


def run_cli(*args):
    env = {"PATH": "/usr/bin:/bin", "GEMINI_API_KEY": "ci-placeholder-not-a-secret", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "scripts/weekly_stats.py", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)


def test_cli_prints_counts_only_and_leaves_the_database_unchanged(tmp_path):
    path = seeded_db(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = run_cli("--db-path", str(path), "--today", "2026-10-21")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["accounts"]["total"] == 2
    for private in [SECRET_TEXT, "synthetic1@", "synthetic-sub-1", "c-synthetic-course", "eval:synthetic", "made_up_mode"]:
        assert private not in result.stdout + result.stderr
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(("args", "code"), [(("--days", "0"), 1), (("--days", "32"), 1), (("--today", "21/10/2026"), 1),
                                            (("--days", "seven"), 2)])
def test_cli_rejects_bad_windows_without_echoing_them(tmp_path, args, code):
    result = run_cli("--db-path", str(seeded_db(tmp_path)), *args)
    assert result.returncode == code and "seven" not in result.stderr and "21/10" not in result.stderr


def test_cli_missing_database_fails_without_creating_it(tmp_path):
    missing = tmp_path / "missing.sqlite3"
    assert run_cli("--db-path", str(missing)).returncode == 1 and not missing.exists()
