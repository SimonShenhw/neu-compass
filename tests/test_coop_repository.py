"""Tests for db.coop_repository — uses the empty_db fixture (in-memory SQLite)."""

from __future__ import annotations

import sqlite3

import pytest

from db.coop_repository import CoopNotFound, CoopRepository
from schemas.coop import CoopExperience, Industry


@pytest.fixture
def repo(empty_db: sqlite3.Connection) -> CoopRepository:
    return CoopRepository(empty_db)


def _coop(coop_id: str = "c1", **overrides) -> CoopExperience:
    base = {
        "coop_id": coop_id,
        "company": "State Street",
        "role": "Quant Dev",
    }
    base.update(overrides)
    return CoopExperience(**base)


def _seed_user(conn: sqlite3.Connection, user_id: str, contributions: int = 0) -> None:
    conn.execute(
        "INSERT INTO users (user_id, email, domain, contribution_count) "
        "VALUES (?, ?, ?, ?)",
        (user_id, f"{user_id}@husky.neu.edu", "husky.neu.edu", contributions),
    )
    conn.commit()


# === add / get ===

def test_add_and_get(repo: CoopRepository) -> None:
    repo.add(_coop(industry=Industry.QUANT_FINTECH, coop_term="Summer 2025"))
    fetched = repo.get("c1")
    assert fetched.company == "State Street"
    assert fetched.industry == Industry.QUANT_FINTECH
    assert fetched.coop_term == "Summer 2025"
    assert fetched.created_at is not None


def test_add_with_related_courses_roundtrips(repo: CoopRepository) -> None:
    repo.add(_coop(related_courses=["CS 5800", "AAI 6600"]))
    fetched = repo.get("c1")
    assert fetched.related_courses == ["CS 5800", "AAI 6600"]


def test_add_duplicate_raises(repo: CoopRepository) -> None:
    repo.add(_coop())
    with pytest.raises(sqlite3.IntegrityError):
        repo.add(_coop())


def test_get_missing_raises(repo: CoopRepository) -> None:
    with pytest.raises(CoopNotFound):
        repo.get("nonexistent")


def test_exists(repo: CoopRepository) -> None:
    assert not repo.exists("c1")
    repo.add(_coop())
    assert repo.exists("c1")


# === upsert ===

def test_upsert_inserts_when_missing(repo: CoopRepository) -> None:
    repo.upsert(_coop(role="Initial Role"))
    assert repo.get("c1").role == "Initial Role"


def test_upsert_updates_existing(repo: CoopRepository) -> None:
    repo.add(_coop(role="Old"))
    repo.upsert(_coop(role="New"))
    assert repo.get("c1").role == "New"


# === delete ===

def test_delete(repo: CoopRepository) -> None:
    repo.add(_coop())
    repo.delete("c1")
    assert not repo.exists("c1")


def test_delete_missing_raises(repo: CoopRepository) -> None:
    with pytest.raises(CoopNotFound):
        repo.delete("nonexistent")


# === list_all / list_seed ===

def test_list_all(repo: CoopRepository) -> None:
    repo.add(_coop("c1"))
    repo.add(_coop("c2", company="Fidelity"))
    repo.add(_coop("c3", company="Moderna"))
    rows = repo.list_all()
    assert len(rows) == 3


def test_list_seed_filters_is_seed_data(repo: CoopRepository) -> None:
    repo.add(_coop("c1", is_seed_data=True))
    repo.add(_coop("c2", is_seed_data=False))
    repo.add(_coop("c3", is_seed_data=True))
    seeds = repo.list_seed()
    assert {c.coop_id for c in seeds} == {"c1", "c3"}


# === list_visible_to_user ===

def test_visibility_anonymous_user_sees_only_level_0(
    repo: CoopRepository,
) -> None:
    """No user record / never logged in -> contribution_count treated as 0."""
    repo.add(_coop("c-pub", visibility_level=0))
    repo.add(_coop("c-detail", visibility_level=1))
    repo.add(_coop("c-premium", visibility_level=2))
    visible = repo.list_visible_to_user("ghost-user-never-existed")
    assert {c.coop_id for c in visible} == {"c-pub"}


def test_visibility_one_contribution_unlocks_level_1(
    repo: CoopRepository, empty_db: sqlite3.Connection,
) -> None:
    _seed_user(empty_db, "u1", contributions=1)
    repo.add(_coop("c-pub", visibility_level=0))
    repo.add(_coop("c-detail", visibility_level=1))
    repo.add(_coop("c-premium", visibility_level=2))
    visible = repo.list_visible_to_user("u1")
    assert {c.coop_id for c in visible} == {"c-pub", "c-detail"}


def test_visibility_two_contributions_unlocks_premium(
    repo: CoopRepository, empty_db: sqlite3.Connection,
) -> None:
    _seed_user(empty_db, "u1", contributions=2)
    repo.add(_coop("c-pub", visibility_level=0))
    repo.add(_coop("c-detail", visibility_level=1))
    repo.add(_coop("c-premium", visibility_level=2))
    visible = repo.list_visible_to_user("u1")
    assert {c.coop_id for c in visible} == {"c-pub", "c-detail", "c-premium"}


# === list_by_company / industry ===

def test_list_by_company_case_insensitive(repo: CoopRepository) -> None:
    repo.add(_coop("c1", company="State Street"))
    repo.add(_coop("c2", company="STATE STREET"))
    repo.add(_coop("c3", company="Fidelity"))
    matches = repo.list_by_company("state street")
    assert {c.coop_id for c in matches} == {"c1", "c2"}


def test_list_by_industry(repo: CoopRepository) -> None:
    repo.add(_coop("c1", industry=Industry.QUANT_FINTECH))
    repo.add(_coop("c2", industry=Industry.BIG_TECH))
    repo.add(_coop("c3", industry=Industry.QUANT_FINTECH))
    matches = repo.list_by_industry(Industry.QUANT_FINTECH)
    assert {c.coop_id for c in matches} == {"c1", "c3"}


# === counts ===

def test_count_by_industry(repo: CoopRepository) -> None:
    repo.add(_coop("c1", industry=Industry.QUANT_FINTECH))
    repo.add(_coop("c2", industry=Industry.QUANT_FINTECH))
    repo.add(_coop("c3", industry=Industry.BIG_TECH))
    repo.add(_coop("c4"))  # no industry
    counts = repo.count_by_industry()
    assert counts["quant_fintech"] == 2
    assert counts["big_tech"] == 1
    assert counts["unknown"] == 1


def test_count_by_visibility(repo: CoopRepository) -> None:
    repo.add(_coop("c1", visibility_level=0))
    repo.add(_coop("c2", visibility_level=0))
    repo.add(_coop("c3", visibility_level=1))
    repo.add(_coop("c4", visibility_level=2))
    counts = repo.count_by_visibility()
    assert counts == {0: 2, 1: 1, 2: 1}


# === FK to users with SET NULL ===

def test_contributor_set_null_on_user_delete(
    repo: CoopRepository, empty_db: sqlite3.Connection,
) -> None:
    _seed_user(empty_db, "u1")
    repo.add(_coop(contributor_user_id="u1"))
    empty_db.execute("DELETE FROM users WHERE user_id = 'u1'")
    empty_db.commit()
    fetched = repo.get("c1")
    assert fetched.contributor_user_id is None
