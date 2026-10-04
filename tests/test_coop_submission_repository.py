"""Offline review/publish/credit state-machine and transaction regressions."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from db.connection import connect
from db.coop_repository import CoopRepository
from db.coop_submission_repository import CoopSubmissionRepository
from db.user_repository import UserRepository
from schemas.coop import CoopExperience
from scripts.init_db import init_database


def seed_users(conn):
    for uid in ("u1", "u2", "u3"):
        conn.execute("INSERT INTO users(user_id,email,domain) VALUES(?,?,?)", (uid, f"{uid}@husky.neu.edu", "husky.neu.edu"))
    conn.commit()


@pytest.fixture
def repo(empty_db):
    seed_users(empty_db)
    return CoopSubmissionRepository(empty_db)


def experience(cid="c1", uid="u1", **fields):
    return CoopExperience(
        coop_id=cid, contributor_user_id=uid,
        **{"company": "Fidelity", "role": "Quant Dev", "coop_term": "Summer 2025", **fields},
    )


def approve(repo, cid, redacted=None):
    if redacted is None:
        redacted = CoopExperience.model_validate_json(repo.get(cid)["payload"])
    return repo.review(cid, approve=True, reviewer="curator", audit="Identifiers removed; bucket reviewed", redacted=redacted)


def counts(conn):
    return {row["user_id"]: row["contribution_count"] for row in conn.execute("SELECT * FROM users")}


def test_pair_publishes_only_after_both_reviews(repo, empty_db):
    repo.submit(experience())
    repo.submit(experience("c2", "u2"))
    assert approve(repo, "c1") == []
    assert repo.get("c1")["review_status"] == "approved"
    assert CoopRepository(empty_db).list_public() == []
    assert counts(empty_db) == {"u1": 0, "u2": 0, "u3": 0}
    assert set(approve(repo, "c2")) == {"c1", "c2"}
    assert {c.coop_id for c in CoopRepository(empty_db).list_public()} == {"c1", "c2"}
    assert counts(empty_db) == {"u1": 1, "u2": 1, "u3": 0}
    assert approve(repo, "c2") == []
    assert counts(empty_db)["u2"] == 1


def test_seed_does_not_supply_a_second_contributor(repo, empty_db):
    CoopRepository(empty_db).add(experience("seed", None, is_seed_data=True))
    repo.submit(experience())
    assert approve(repo, "c1") == []
    assert [c.coop_id for c in CoopRepository(empty_db).list_public()] == ["seed"]
    assert counts(empty_db)["u1"] == 0


def test_normalized_duplicate_preserves_original_private_content(repo):
    repo.submit(experience(interview_summary="Original"))
    row, duplicate = repo.submit(experience("retry", company=" ＦＩＤＥＬＩＴＹ ", role=" Quant   Dev ", interview_summary="Replacement"))
    assert duplicate is True
    assert row["coop_id"] == "c1"
    assert CoopExperience.model_validate_json(row["payload"]).interview_summary == "Original"


def test_same_user_generalized_records_do_not_create_anonymous_group(repo, empty_db):
    repo.submit(experience())
    repo.submit(experience("c2", company="Other Corp"))
    assert approve(repo, "c1") == []
    assert approve(repo, "c2", experience("c2")) == []
    assert CoopRepository(empty_db).list_public() == []
    repo.submit(experience("c3", "u2"))
    assert set(approve(repo, "c3")) == {"c1", "c2", "c3"}
    assert counts(empty_db) == {"u1": 1, "u2": 1, "u3": 0}
    assert empty_db.execute("SELECT COUNT(*) FROM coop_contribution_credits").fetchone()[0] == 2


def test_different_terms_are_distinct_experiences(repo, empty_db):
    for term in ("Summer 2025", "Spring 2026"):
        for uid in ("u1", "u2"):
            cid = f"{uid}-{term}"
            repo.submit(experience(cid, uid, coop_term=term))
            approve(repo, cid)
    assert counts(empty_db) == {"u1": 2, "u2": 2, "u3": 0}


def test_review_uses_full_sanitized_replacement_and_server_identity(repo, empty_db):
    repo.submit(experience(interview_summary="Contact Person at private address", salary_range_usd="$31.13/hr"))
    repo.submit(experience("c2", "u2"))
    sanitized = experience("forged-id", "u3", interview_summary="Two rounds", salary_range_usd=None, is_seed_data=True, visibility_level=2)
    approve(repo, "c1", sanitized)
    approve(repo, "c2")
    published = CoopRepository(empty_db).get("c1")
    assert published.interview_summary == "Two rounds"
    assert published.salary_range_usd is None
    assert published.visibility_level == 1
    assert published.contributor_user_id == "u1"
    assert published.is_seed_data is False
    assert published.redaction_audit == "Identifiers removed; bucket reviewed"
    assert "private address" not in repo.get("c1")["payload"]


def test_rejected_record_never_counts_toward_publication(repo, empty_db):
    repo.submit(experience())
    repo.submit(experience("c2", "u2"))
    repo.review("c1", approve=False, reviewer="curator", audit="Not redacted")
    assert approve(repo, "c2") == []
    assert CoopRepository(empty_db).list_public() == []
    assert counts(empty_db)["u1"] == 0
    with pytest.raises(ValueError, match="cannot change decision"):
        approve(repo, "c1")


@pytest.mark.parametrize("kwargs", [
    {"reviewer": "", "audit": "reviewed"},
    {"reviewer": "curator", "audit": " "},
    {"reviewer": "curator", "audit": "reviewed"},
])
def test_approval_requires_reviewer_audit_and_replacement(repo, kwargs):
    repo.submit(experience())
    with pytest.raises(ValueError):
        repo.review("c1", approve=True, **kwargs)
    assert repo.get("c1")["review_status"] == "pending"


@pytest.mark.parametrize("failure", ["insert", "credit"])
def test_publication_failure_rolls_back_every_side_effect(repo, empty_db, monkeypatch, failure):
    repo.submit(experience())
    repo.submit(experience("c2", "u2"))
    approve(repo, "c1")
    empty_db.commit()
    if failure == "credit":
        original = UserRepository.increment_contribution_count
        def fail(self, uid):
            if uid == "u2":
                raise RuntimeError("credit failed")
            return original(self, uid)
        monkeypatch.setattr(UserRepository, "increment_contribution_count", fail)
    else:
        original = CoopRepository.add
        def fail(self, coop):
            if coop.coop_id == "c2":
                raise RuntimeError("insert failed")
            return original(self, coop)
        monkeypatch.setattr(CoopRepository, "add", fail)
    with pytest.raises(RuntimeError):
        approve(repo, "c2")
    assert repo.get("c1")["review_status"] == "approved"
    assert repo.get("c2")["review_status"] == "pending"
    assert CoopRepository(empty_db).list_all() == []
    assert empty_db.execute("SELECT COUNT(*) FROM coop_contribution_credits").fetchone()[0] == 0
    assert counts(empty_db) == {"u1": 0, "u2": 0, "u3": 0}


def test_account_deletion_hides_remaining_singleton(repo, empty_db):
    repo.submit(experience())
    repo.submit(experience("c2", "u2"))
    approve(repo, "c1")
    approve(repo, "c2")
    assert len(CoopRepository(empty_db).list_public()) == 2
    UserRepository(empty_db).delete("u2")
    assert CoopRepository(empty_db).list_public() == []


def test_db_rejects_unknown_status_and_duplicate_credit(repo, empty_db):
    repo.submit(experience())
    with pytest.raises(sqlite3.IntegrityError):
        empty_db.execute("UPDATE coop_submissions SET review_status='visible' WHERE coop_id='c1'")
    repo.submit(experience("c2", "u2"))
    approve(repo, "c1")
    approve(repo, "c2")
    row = empty_db.execute("SELECT * FROM coop_contribution_credits LIMIT 1").fetchone()
    with pytest.raises(sqlite3.IntegrityError):
        empty_db.execute("INSERT INTO coop_contribution_credits(user_id,group_key,coop_id) VALUES(?,?,?)", (row["user_id"], row["group_key"], row["coop_id"]))


@pytest.fixture
def runtime_db(tmp_path):
    path = tmp_path / "runtime.db"
    init_database(path)
    conn = connect(path)
    seed_users(conn)
    conn.close()
    return path


def test_repository_does_not_commit_callers_transaction(runtime_db):
    conn = connect(runtime_db)
    observer = connect(runtime_db)
    try:
        CoopSubmissionRepository(conn).submit(experience())
        assert observer.execute("SELECT COUNT(*) FROM coop_submissions").fetchone()[0] == 0
        conn.rollback()
        assert observer.execute("SELECT COUNT(*) FROM coop_submissions").fetchone()[0] == 0
    finally:
        conn.close()
        observer.close()


@pytest.mark.parametrize("operation", ["submit", "review"])
def test_concurrent_connections_cannot_double_credit(runtime_db, operation):
    if operation == "review":
        conn = connect(runtime_db)
        repo = CoopSubmissionRepository(conn)
        repo.submit(experience())
        repo.submit(experience("c2", "u2"))
        conn.commit()
        conn.close()
    barrier = Barrier(2)
    def work(number):
        conn = connect(runtime_db)
        repo = CoopSubmissionRepository(conn)
        try:
            barrier.wait(timeout=10)
            result = repo.submit(experience(f"retry-{number}")) if operation == "submit" else approve(repo, "c1" if number == 1 else "c2")
            conn.commit()
            return (result[0]["coop_id"], result[1]) if operation == "submit" else result
        finally:
            conn.close()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(work, [1, 2]))
    conn = connect(runtime_db)
    try:
        if operation == "submit":
            assert results[0][0] == results[1][0]
            assert sorted(result[1] for result in results) == [False, True]
            assert conn.execute("SELECT COUNT(*) FROM coop_submissions").fetchone()[0] == 1
            assert counts(conn)["u1"] == 0
        else:
            assert counts(conn) == {"u1": 1, "u2": 1, "u3": 0}
            assert len(CoopRepository(conn).list_public()) == 2
    finally:
        conn.close()
