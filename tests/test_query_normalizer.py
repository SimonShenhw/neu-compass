"""Tests for rag.query_normalizer — uses real AliasRepository."""

from __future__ import annotations

import sqlite3

import pytest

from db.alias_repository import AliasRepository
from db.repository import CourseRepository
from rag.query_normalizer import normalize_query_to_course_ids
from schemas.alias import Alias, AliasReviewStatus, AliasSource, AliasType
from schemas.course import Course


@pytest.fixture
def alias_repo(empty_db: sqlite3.Connection) -> AliasRepository:
    """Seed: AAI 6600 + 4 aliases (matches scripts/seed_aai6600 essentials)."""
    course_repo = CourseRepository(empty_db)
    course_repo.insert(Course(
        course_id="neu-aai-6600", primary_code="AAI 6600",
        primary_name="Applied AI",
    ))
    course_repo.insert(Course(
        course_id="neu-cs-5800", primary_code="CS 5800",
        primary_name="Algorithms",
    ))

    repo = AliasRepository(empty_db)
    for text, atype in [
        ("Applied AI", AliasType.SLANG),
        ("应用 AI", AliasType.SLANG),
        ("6600", AliasType.SLANG),
        ("Hema's AI class", AliasType.PROFESSOR_ATTRIBUTION),
    ]:
        repo.add(Alias(
            alias_text=text, alias_type=atype,
            primary_course_id="neu-aai-6600",
            source=AliasSource.MANUAL,
            review_status=AliasReviewStatus.APPROVED,
        ))
    repo.add(Alias(
        alias_text="Algo", alias_type=AliasType.SLANG,
        primary_course_id="neu-cs-5800",
        source=AliasSource.MANUAL,
        review_status=AliasReviewStatus.APPROVED,
    ))
    return repo


# === Empty / trivial cases ===

def test_empty_query_returns_empty(alias_repo: AliasRepository) -> None:
    assert normalize_query_to_course_ids("", alias_repo=alias_repo) == []


def test_whitespace_query_returns_empty(alias_repo: AliasRepository) -> None:
    assert normalize_query_to_course_ids("   \t  \n", alias_repo=alias_repo) == []


def test_no_match_returns_empty(alias_repo: AliasRepository) -> None:
    assert normalize_query_to_course_ids(
        "I want to learn quantum physics", alias_repo=alias_repo,
    ) == []


# === Full course code ===

def test_full_code_with_space(alias_repo: AliasRepository) -> None:
    assert normalize_query_to_course_ids(
        "AAI 6600 怎么样", alias_repo=alias_repo,
    ) == ["neu-aai-6600"]


def test_full_code_without_space(alias_repo: AliasRepository) -> None:
    assert normalize_query_to_course_ids(
        "AAI6600 vs CS5800", alias_repo=alias_repo,
    ) == ["neu-aai-6600", "neu-cs-5800"]


def test_full_code_lowercase(alias_repo: AliasRepository) -> None:
    """v_course_lookup uses COLLATE NOCASE; case-insensitive."""
    assert normalize_query_to_course_ids(
        "aai 6600 worth taking?", alias_repo=alias_repo,
    ) == ["neu-aai-6600"]


# === Bare 4-digit number ===

def test_bare_number(alias_repo: AliasRepository) -> None:
    assert normalize_query_to_course_ids(
        "6600 怎么样", alias_repo=alias_repo,
    ) == ["neu-aai-6600"]


def test_bare_number_skipped_when_full_code_present(
    alias_repo: AliasRepository,
) -> None:
    """If '6600' appears as part of a fully matched code, don't double-resolve.
    The full code 'AAI 6600' wins; '6600' shouldn't add the same course again."""
    result = normalize_query_to_course_ids("AAI 6600 fall", alias_repo=alias_repo)
    assert result == ["neu-aai-6600"]
    assert len(result) == 1


# === Whole-query slang ===

def test_short_slang_whole_query(alias_repo: AliasRepository) -> None:
    """'Algo' (4 chars) is short enough to be tried as a whole-query alias."""
    assert normalize_query_to_course_ids("Algo", alias_repo=alias_repo) == [
        "neu-cs-5800",
    ]


def test_chinese_slang_whole_query(alias_repo: AliasRepository) -> None:
    assert normalize_query_to_course_ids("应用 AI", alias_repo=alias_repo) == [
        "neu-aai-6600",
    ]


def test_long_query_skips_whole_match(alias_repo: AliasRepository) -> None:
    """Queries > MAX_WHOLE_QUERY_LEN are not whole-matched against aliases."""
    long_query = "I'm looking for an introduction to AI but with a focus on practical projects rather than theory"
    assert len(long_query) > 30
    # No course code in this text -> nothing resolves
    assert normalize_query_to_course_ids(long_query, alias_repo=alias_repo) == []


# === Multi-course queries ===

def test_query_mentioning_two_courses(alias_repo: AliasRepository) -> None:
    result = normalize_query_to_course_ids(
        "compare CS 5800 and AAI 6600", alias_repo=alias_repo,
    )
    assert set(result) == {"neu-cs-5800", "neu-aai-6600"}


def test_dedup_repeated_mention(alias_repo: AliasRepository) -> None:
    result = normalize_query_to_course_ids(
        "AAI 6600 vs AAI 6600 again", alias_repo=alias_repo,
    )
    assert result == ["neu-aai-6600"]


# === Pending aliases not leaked ===

def test_pending_alias_does_not_leak_through_normalizer(
    alias_repo: AliasRepository,
) -> None:
    """ADR equivalent for the alias view: pending L3 entries shouldn't
    affect normalizer output."""
    alias_repo.add(Alias(
        alias_text="risky_guess", alias_type=AliasType.SLANG,
        primary_course_id="neu-aai-6600",
        source=AliasSource.LLM_INFERRED,
        review_status=AliasReviewStatus.PENDING,
    ))
    assert normalize_query_to_course_ids(
        "risky_guess", alias_repo=alias_repo,
    ) == []


# === Boundary: bare 4-digit not matching any course ===

def test_unknown_number_returns_empty(alias_repo: AliasRepository) -> None:
    assert normalize_query_to_course_ids(
        "9999 is a great class", alias_repo=alias_repo,
    ) == []


def test_unknown_full_code_returns_empty(alias_repo: AliasRepository) -> None:
    """Adversarial query 'AAI 9999' (PLAN §4.1) — must not hallucinate."""
    assert normalize_query_to_course_ids(
        "AAI 9999 怎么样", alias_repo=alias_repo,
    ) == []
