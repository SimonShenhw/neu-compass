"""Real offline CLI invocation and additive-migration regressions; tmp DB only."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from db.connection import connect
from db.coop_repository import CoopRepository
from db.coop_submission_repository import CoopSubmissionRepository
from schemas.coop import CoopExperience
from scripts.init_db import init_database
from scripts.migrate_coop_submissions import migrate

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def runtime(tmp_path):
    path = tmp_path / "runtime.db"
    init_database(path)
    conn = connect(path)
    for uid in ("u1", "u2"):
        conn.execute("INSERT INTO users(user_id,email,domain) VALUES(?,?,?)", (uid, f"{uid}@husky.neu.edu", "husky.neu.edu"))
        CoopSubmissionRepository(conn).submit(CoopExperience(
            coop_id=uid, contributor_user_id=uid, company="Fidelity", role="Quant Dev",
            interview_summary="Private original contact details",
        ))
    CoopRepository(conn).add(CoopExperience(coop_id="seed", company="Curated", role="Dev", is_seed_data=True))
    conn.commit()
    conn.close()
    return path


def run_review(runtime, *args):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/review_coop.py"), "--db-path", str(runtime), *args],
        capture_output=True, text=True, timeout=30,
    )


def test_migration_dry_run_is_read_only_and_commit_is_idempotent(runtime):
    conn = connect(runtime)
    # Simulate the old runtime schema, preserving its users/seed records.
    conn.execute("DROP TABLE coop_contribution_credits")
    conn.execute("DROP TABLE coop_submissions")
    conn.execute("DELETE FROM schema_versions WHERE version='1.3'")
    conn.commit()
    conn.close()
    before = runtime.read_bytes()
    assert migrate(runtime) == ["coop_contribution_credits", "coop_submissions"]
    assert runtime.read_bytes() == before
    assert migrate(runtime, commit=True) == ["coop_contribution_credits", "coop_submissions"]
    assert migrate(runtime, commit=True) == []
    conn = connect(runtime)
    try:
        assert [c.coop_id for c in CoopRepository(conn).list_all()] == ["seed"]
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM schema_versions WHERE version='1.3'").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_migration_missing_path_does_not_create_database(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        migrate(missing)
    assert not missing.exists()


def test_list_hides_private_payload(runtime):
    result = run_review(runtime, "--list")
    assert result.returncode == 0, result.stdout + result.stderr
    assert {row["status"] for row in json.loads(result.stdout)} == {"pending"}
    assert "Private original" not in result.stdout
    assert "Fidelity" not in result.stdout


def test_default_review_is_dry_run_then_pair_publishes(runtime, tmp_path):
    sanitized = tmp_path / "sanitized.json"
    sanitized.write_text(json.dumps({"company": "Fidelity", "role": "Quant Dev", "interview_summary": "Two rounds"}), encoding="utf-8")
    args = ["--redacted-file", str(sanitized), "--reviewer", "curator", "--audit", "Identifiers removed"]
    before = runtime.read_bytes()
    dry = run_review(runtime, "--approve", "u1", *args)
    assert dry.returncode == 0
    assert "dry-run" in dry.stdout
    assert runtime.read_bytes() == before
    first = run_review(runtime, "--approve", "u1", *args, "--commit")
    assert first.returncode == 0, first.stdout + first.stderr
    assert json.loads(first.stdout)["status"] == "approved"
    second = run_review(runtime, "--approve", "u2", *args, "--commit")
    assert second.returncode == 0, second.stdout + second.stderr
    assert set(json.loads(second.stdout)["published_ids"]) == {"u1", "u2"}
    repeated = run_review(runtime, "--approve", "u2", *args, "--commit")
    assert repeated.returncode == 0
    assert json.loads(repeated.stdout)["published_ids"] == []
    conn = connect(runtime)
    try:
        assert {row[0] for row in conn.execute("SELECT contribution_count FROM users")} == {1}
        assert CoopRepository(conn).get("u1").interview_summary == "Two rounds"
    finally:
        conn.close()


@pytest.mark.parametrize("args", [
    ["--approve", "u1", "--commit"],
    ["--approve", "unknown", "--reviewer", "curator", "--audit", "checked", "--commit"],
    ["--reject", "u1", "--reviewer", "curator", "--commit"],
])
def test_invalid_review_fails_without_writes(runtime, args):
    before = runtime.read_bytes()
    result = run_review(runtime, *args)
    assert result.returncode == 1
    assert runtime.read_bytes() == before
    assert "Private original" not in result.stdout + result.stderr


def test_cli_rejection_is_private_and_does_not_reward(runtime):
    result = run_review(runtime, "--reject", "u1", "--reviewer", "curator", "--audit", "Not sufficiently redacted", "--commit")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"status": "rejected", "published_ids": []}
    conn = connect(runtime)
    try:
        assert [c.coop_id for c in CoopRepository(conn).list_public()] == ["seed"]
        assert {row[0] for row in conn.execute("SELECT contribution_count FROM users")} == {0}
    finally:
        conn.close()
