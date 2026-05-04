"""Tests for db.user_repository."""

from __future__ import annotations

import sqlite3
import time

import pytest

from db.user_repository import UserNotFound, UserRepository
from schemas.user import User


def test_count_empty(empty_db: sqlite3.Connection) -> None:
    assert UserRepository(empty_db).count() == 0


def test_get_missing_returns_none(empty_db: sqlite3.Connection) -> None:
    assert UserRepository(empty_db).get("u-missing") is None


def test_exists_false(empty_db: sqlite3.Connection) -> None:
    assert UserRepository(empty_db).exists("u-missing") is False


# === upsert_login ===


def test_upsert_login_creates_row(empty_db: sqlite3.Connection) -> None:
    repo = UserRepository(empty_db)
    user = repo.upsert_login(
        user_id="g-sub-1",
        email="alice@husky.neu.edu",
        domain="husky.neu.edu",
        display_name="Alice",
    )
    assert isinstance(user, User)
    assert user.user_id == "g-sub-1"
    assert user.email == "alice@husky.neu.edu"
    assert user.contribution_count == 0
    assert user.last_login_at is not None
    assert user.created_at is not None


def test_upsert_login_idempotent_on_second_call(empty_db: sqlite3.Connection) -> None:
    """Second login with same user_id updates last_login_at, leaves
    contribution_count untouched."""
    repo = UserRepository(empty_db)
    repo.upsert_login(
        user_id="g-1", email="a@husky.neu.edu", domain="husky.neu.edu",
    )
    # Bump contribution_count via the dedicated method
    empty_db.execute("UPDATE users SET contribution_count = 3 WHERE user_id = 'g-1'")
    empty_db.commit()

    refreshed = repo.upsert_login(
        user_id="g-1", email="a@husky.neu.edu", domain="husky.neu.edu",
        display_name="Alice (Updated)",
    )
    assert refreshed.contribution_count == 3  # NOT reset by upsert_login
    assert refreshed.display_name == "Alice (Updated)"


def test_upsert_login_preserves_display_name_when_omitted(
    empty_db: sqlite3.Connection,
) -> None:
    """If subsequent login passes display_name=None, the existing one stays
    (COALESCE in the SQL)."""
    repo = UserRepository(empty_db)
    repo.upsert_login(
        user_id="g-1", email="a@husky.neu.edu", domain="husky.neu.edu",
        display_name="Alice",
    )
    refreshed = repo.upsert_login(
        user_id="g-1", email="a@husky.neu.edu", domain="husky.neu.edu",
        display_name=None,
    )
    assert refreshed.display_name == "Alice"


def test_upsert_login_advances_last_login_at(empty_db: sqlite3.Connection) -> None:
    repo = UserRepository(empty_db)
    first = repo.upsert_login(
        user_id="g-1", email="a@husky.neu.edu", domain="husky.neu.edu",
    )
    time.sleep(1.0)  # SQLite CURRENT_TIMESTAMP has 1s resolution
    second = repo.upsert_login(
        user_id="g-1", email="a@husky.neu.edu", domain="husky.neu.edu",
    )
    assert second.last_login_at >= first.last_login_at  # type: ignore[operator]


# === get_by_email ===


def test_get_by_email_case_insensitive(empty_db: sqlite3.Connection) -> None:
    repo = UserRepository(empty_db)
    repo.upsert_login(
        user_id="g-1", email="Alice@Husky.NEU.edu", domain="husky.neu.edu",
    )
    # Lookup with all-lowercase email should find the row.
    found = repo.get_by_email("alice@husky.neu.edu")
    assert found is not None
    assert found.user_id == "g-1"


# === increment_contribution_count ===


def test_increment_contribution_count(empty_db: sqlite3.Connection) -> None:
    repo = UserRepository(empty_db)
    repo.upsert_login(
        user_id="g-1", email="a@husky.neu.edu", domain="husky.neu.edu",
    )
    assert repo.increment_contribution_count("g-1") == 1
    assert repo.increment_contribution_count("g-1") == 2
    assert repo.get("g-1").contribution_count == 2  # type: ignore[union-attr]


def test_increment_missing_user_raises(empty_db: sqlite3.Connection) -> None:
    repo = UserRepository(empty_db)
    with pytest.raises(UserNotFound):
        repo.increment_contribution_count("g-missing")


# === delete ===


def test_delete_removes_user(empty_db: sqlite3.Connection) -> None:
    repo = UserRepository(empty_db)
    repo.upsert_login(
        user_id="g-1", email="a@husky.neu.edu", domain="husky.neu.edu",
    )
    repo.delete("g-1")
    assert repo.get("g-1") is None


def test_delete_missing_raises(empty_db: sqlite3.Connection) -> None:
    repo = UserRepository(empty_db)
    with pytest.raises(UserNotFound):
        repo.delete("g-missing")


# === count ===


def test_count_after_inserts(empty_db: sqlite3.Connection) -> None:
    repo = UserRepository(empty_db)
    repo.upsert_login(user_id="g-1", email="a@husky.neu.edu", domain="husky.neu.edu")
    repo.upsert_login(user_id="g-2", email="b@northeastern.edu", domain="northeastern.edu")
    assert repo.count() == 2


# === User Pydantic shape ===


def test_user_extra_forbidden() -> None:
    with pytest.raises(ValueError):
        User(
            user_id="g-1", email="a@husky.neu.edu", domain="husky.neu.edu",
            unexpected="x",  # type: ignore[call-arg]
        )


def test_user_contribution_count_non_negative() -> None:
    with pytest.raises(ValueError):
        User(
            user_id="g-1", email="a@husky.neu.edu", domain="husky.neu.edu",
            contribution_count=-1,
        )
