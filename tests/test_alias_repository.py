"""Tests for db.alias_repository — Alias <-> SQLite mapping + workflow."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from db.alias_repository import AliasNotFound, AliasRepository
from db.repository import CourseRepository
from schemas.alias import Alias, AliasReviewStatus, AliasSource, AliasType
from schemas.course import Course


@pytest.fixture
def repo(empty_db: sqlite3.Connection) -> AliasRepository:
    return AliasRepository(empty_db)


@pytest.fixture
def course_seed(empty_db: sqlite3.Connection) -> str:
    """Insert one Course so aliases have a valid FK target. Returns course_id."""
    course_repo = CourseRepository(empty_db)
    c = Course(
        course_id="uuid-cs5800",
        primary_code="CS 5800",
        primary_name="Algorithms",
    )
    course_repo.insert(c)
    return c.course_id


def _alias(
    primary_course_id: str = "uuid-cs5800",
    text: str = "5800",
    alias_type: AliasType = AliasType.SLANG,
    source: AliasSource = AliasSource.MANUAL,
    review_status: AliasReviewStatus = AliasReviewStatus.APPROVED,
    **kw: object,
) -> Alias:
    return Alias(
        alias_text=text,
        alias_type=alias_type,
        primary_course_id=primary_course_id,
        source=source,
        review_status=review_status,
        **kw,
    )


# === Schema-level Alias validation ===

def test_alias_date_consistency() -> None:
    with pytest.raises(ValueError, match="valid_until"):
        Alias(
            alias_text="x", alias_type=AliasType.SLANG, primary_course_id="u",
            source=AliasSource.MANUAL,
            valid_from=date(2027, 1, 1), valid_until=date(2026, 1, 1),
        )


def test_alias_confidence_bounds() -> None:
    with pytest.raises(ValueError):
        Alias(
            alias_text="x", alias_type=AliasType.SLANG, primary_course_id="u",
            source=AliasSource.MANUAL, confidence=1.5,
        )


def test_alias_extra_forbidden() -> None:
    with pytest.raises(ValueError):
        Alias(
            alias_text="x", alias_type=AliasType.SLANG, primary_course_id="u",
            source=AliasSource.MANUAL, unknown_field="x",
        )


# === add() write semantics ===

def test_add_returns_alias_id(repo: AliasRepository, course_seed: str) -> None:
    aid = repo.add(_alias(text="Algo"))
    assert isinstance(aid, int)
    assert aid >= 1


def test_add_duplicate_raises(repo: AliasRepository, course_seed: str) -> None:
    """UNIQUE (alias_text, alias_type, primary_course_id) is enforced."""
    repo.add(_alias(text="5800"))
    with pytest.raises(sqlite3.IntegrityError):
        repo.add(_alias(text="5800"))


def test_add_same_text_different_type_ok(repo: AliasRepository, course_seed: str) -> None:
    """UNIQUE is on (text, type, primary). Same text with different type is fine."""
    repo.add(_alias(text="Hema's", alias_type=AliasType.PROFESSOR_ATTRIBUTION))
    repo.add(_alias(text="Hema's", alias_type=AliasType.SLANG))
    aliases = repo.find_by_text("Hema's")
    assert len(aliases) == 2


def test_add_bad_fk_raises(repo: AliasRepository, empty_db: sqlite3.Connection) -> None:
    """No course with this id; FK violation."""
    with pytest.raises(sqlite3.IntegrityError):
        repo.add(_alias(primary_course_id="does-not-exist"))


def test_add_or_skip_inserts_first_time(repo: AliasRepository, course_seed: str) -> None:
    aid = repo.add_or_skip(_alias(text="Algo"))
    assert aid is not None


def test_add_or_skip_returns_none_on_duplicate(
    repo: AliasRepository, course_seed: str,
) -> None:
    repo.add(_alias(text="5800"))
    result = repo.add_or_skip(_alias(text="5800"))
    assert result is None


def test_add_many(repo: AliasRepository, course_seed: str) -> None:
    aliases = [
        _alias(text="Algo"),
        _alias(text="5800"),
        _alias(text="算法课"),
    ]
    inserted = repo.add_many(aliases)
    assert inserted == 3


def test_add_many_skips_duplicates(repo: AliasRepository, course_seed: str) -> None:
    repo.add(_alias(text="5800"))
    aliases = [
        _alias(text="5800"),    # dup, skipped
        _alias(text="Algo"),    # new, inserted
        _alias(text="5800"),    # dup again
    ]
    inserted = repo.add_many(aliases)
    assert inserted == 1


# === get / exists ===

def test_get_returns_alias(repo: AliasRepository, course_seed: str) -> None:
    aid = repo.add(_alias(text="5800", confidence=0.9))
    fetched = repo.get(aid)
    assert fetched.alias_id == aid
    assert fetched.alias_text == "5800"
    assert fetched.alias_type == AliasType.SLANG
    assert fetched.confidence == 0.9
    assert fetched.created_at is not None  # auto-populated by SQLite


def test_get_missing_raises(repo: AliasRepository) -> None:
    with pytest.raises(AliasNotFound):
        repo.get(999999)


def test_exists(repo: AliasRepository, course_seed: str) -> None:
    aid = repo.add(_alias(text="5800"))
    assert repo.exists(aid)
    assert not repo.exists(999999)


# === find_by_text ===

def test_find_by_text_case_insensitive(repo: AliasRepository, course_seed: str) -> None:
    repo.add(_alias(text="ALGO"))
    found = repo.find_by_text("algo")
    assert len(found) == 1
    assert found[0].alias_text == "ALGO"


def test_find_by_text_unicode(repo: AliasRepository, course_seed: str) -> None:
    repo.add(_alias(text="算法课"))
    assert len(repo.find_by_text("算法课")) == 1


def test_find_by_text_no_match(repo: AliasRepository) -> None:
    assert repo.find_by_text("nonexistent") == []


# === list_by_course ===

def test_list_by_course(repo: AliasRepository, course_seed: str) -> None:
    repo.add(_alias(text="A"))
    repo.add(_alias(text="B", alias_type=AliasType.PROFESSOR_ATTRIBUTION))
    aliases = repo.list_by_course(course_seed)
    assert len(aliases) == 2
    # Ordered by alias_type, alias_text per query
    assert aliases[0].alias_type == AliasType.PROFESSOR_ATTRIBUTION
    assert aliases[1].alias_type == AliasType.SLANG


# === list_by_status / list_pending ===

def test_list_pending(repo: AliasRepository, course_seed: str) -> None:
    repo.add(_alias(text="approved", review_status=AliasReviewStatus.APPROVED))
    repo.add(_alias(text="pending1", review_status=AliasReviewStatus.PENDING,
                    source=AliasSource.LLM_INFERRED, confidence=0.6))
    repo.add(_alias(text="pending2", review_status=AliasReviewStatus.PENDING,
                    source=AliasSource.LLM_INFERRED, confidence=0.55,
                    alias_type=AliasType.PROFESSOR_ATTRIBUTION))

    pending = repo.list_pending()
    texts = {a.alias_text for a in pending}
    assert texts == {"pending1", "pending2"}


def test_list_pending_with_limit(repo: AliasRepository, course_seed: str) -> None:
    for i in range(5):
        repo.add(_alias(
            text=f"t{i}", review_status=AliasReviewStatus.PENDING,
            source=AliasSource.LLM_INFERRED,
        ))
    assert len(repo.list_pending(limit=2)) == 2


# === update_review_status ===

def test_update_review_status_approves(repo: AliasRepository, course_seed: str) -> None:
    aid = repo.add(_alias(
        text="LLM-found",
        review_status=AliasReviewStatus.PENDING,
        source=AliasSource.LLM_INFERRED,
        confidence=0.6,
    ))
    repo.update_review_status(aid, AliasReviewStatus.APPROVED)
    assert repo.get(aid).review_status == AliasReviewStatus.APPROVED


def test_update_review_status_rejects(repo: AliasRepository, course_seed: str) -> None:
    aid = repo.add(_alias(
        text="bad-suggestion",
        review_status=AliasReviewStatus.PENDING,
        source=AliasSource.LLM_INFERRED,
    ))
    repo.update_review_status(aid, AliasReviewStatus.REJECTED)
    assert repo.get(aid).review_status == AliasReviewStatus.REJECTED


def test_update_review_status_missing_raises(repo: AliasRepository) -> None:
    with pytest.raises(AliasNotFound):
        repo.update_review_status(999999, AliasReviewStatus.APPROVED)


# === delete ===

def test_delete(repo: AliasRepository, course_seed: str) -> None:
    aid = repo.add(_alias(text="typo"))
    repo.delete(aid)
    assert not repo.exists(aid)


def test_delete_missing_raises(repo: AliasRepository) -> None:
    with pytest.raises(AliasNotFound):
        repo.delete(999999)


# === count_by_status ===

def test_count_by_status(repo: AliasRepository, course_seed: str) -> None:
    repo.add(_alias(text="ok1"))
    repo.add(_alias(text="ok2", alias_type=AliasType.PROFESSOR_ATTRIBUTION))
    repo.add(_alias(
        text="pending",
        review_status=AliasReviewStatus.PENDING,
        source=AliasSource.LLM_INFERRED,
    ))
    counts = repo.count_by_status()
    assert counts == {"approved": 2, "pending": 1}


# === resolve via v_course_lookup ===

def test_resolve_finds_primary_code(
    repo: AliasRepository, course_seed: str,
) -> None:
    """primary_code is in v_course_lookup even without any alias."""
    course_ids = repo.resolve("CS 5800")
    assert course_ids == ["uuid-cs5800"]


def test_resolve_finds_approved_alias(
    repo: AliasRepository, course_seed: str,
) -> None:
    repo.add(_alias(text="5800", review_status=AliasReviewStatus.APPROVED))
    course_ids = repo.resolve("5800")
    assert course_ids == ["uuid-cs5800"]


def test_resolve_skips_pending_alias(
    repo: AliasRepository, course_seed: str,
) -> None:
    """The view filters review_status='approved'; pending aliases must NOT
    leak into resolution (PLAN §3 LLM detector defaults to pending)."""
    repo.add(_alias(
        text="risky_guess",
        review_status=AliasReviewStatus.PENDING,
        source=AliasSource.LLM_INFERRED,
        confidence=0.5,
    ))
    assert repo.resolve("risky_guess") == []


def test_resolve_case_insensitive(repo: AliasRepository, course_seed: str) -> None:
    repo.add(_alias(text="Algo"))
    assert repo.resolve("ALGO") == ["uuid-cs5800"]
    assert repo.resolve("algo") == ["uuid-cs5800"]


def test_resolve_no_match(repo: AliasRepository, course_seed: str) -> None:
    assert repo.resolve("nonexistent course") == []


def test_resolve_chinese_alias(repo: AliasRepository, course_seed: str) -> None:
    """Multi-byte alias resolution (the AAI 6600 use case for 应用 AI)."""
    repo.add(_alias(text="算法课"))
    assert repo.resolve("算法课") == ["uuid-cs5800"]


# === FK cascade ===

def test_aliases_cascade_on_course_delete(
    repo: AliasRepository, course_seed: str, empty_db: sqlite3.Connection,
) -> None:
    """Deleting a course should cascade-delete its aliases (db/init.sql)."""
    repo.add(_alias(text="A"))
    repo.add(_alias(text="B", alias_type=AliasType.PROFESSOR_ATTRIBUTION))

    empty_db.execute("DELETE FROM courses WHERE course_id = ?", (course_seed,))
    empty_db.commit()

    assert repo.list_by_course(course_seed) == []


# === Date fields roundtrip ===

def test_valid_dates_roundtrip(repo: AliasRepository, course_seed: str) -> None:
    aid = repo.add(_alias(
        text="versioned",
        alias_type=AliasType.VERSION,
        valid_from=date(2024, 1, 1),
        valid_until=date(2026, 12, 31),
    ))
    fetched = repo.get(aid)
    assert fetched.valid_from == date(2024, 1, 1)
    assert fetched.valid_until == date(2026, 12, 31)
