"""Tests for rag.query_normalizer — uses real AliasRepository."""

from __future__ import annotations

import sqlite3

import pytest

from db.alias_repository import AliasRepository
from db.repository import CourseRepository
from rag.query_normalizer import (
    MAX_COURSE_REF_LEN,
    normalize_query_to_course_ids,
    resolve_course_ref,
)
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


def test_full_code_embedded_in_chinese_sentence(
    alias_repo: AliasRepository,
) -> None:
    """Regression: bilingual NEU users type '那AAI 6600这门课能给我说说吗'.
    Python 3 \\b is Unicode-aware by default — CJK chars count as word
    chars, so '那A' has no boundary between '那' and 'A' and the regex
    misses the embedded code. Fixed by re.ASCII flag in the patterns."""
    for q in [
        "那AAI 6600这门课的信息能给我说说吗",
        "我想学AAI6600请问难吗",
        "听说AAI 6600挺好的",
    ]:
        assert normalize_query_to_course_ids(
            q, alias_repo=alias_repo,
        ) == ["neu-aai-6600"], f"Failed for query: {q!r}"


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


# ===========================================================================
# resolve_course_ref — the deep-link (?course=) sibling
# ===========================================================================


@pytest.fixture
def course_repo(empty_db: sqlite3.Connection) -> CourseRepository:
    """Same connection the alias_repo fixture seeds; request BOTH fixtures
    in a test so the courses exist before the repo is used."""
    return CourseRepository(empty_db)


# === Tier 0: the ref is already an internal course_id ===

def test_ref_accepts_raw_internal_course_id(
    alias_repo: AliasRepository, course_repo: CourseRepository,
) -> None:
    assert resolve_course_ref(
        "neu-cs-5800", alias_repo=alias_repo, course_repo=course_repo,
    ) == ["neu-cs-5800"]


def test_ref_internal_course_id_is_case_insensitive(
    alias_repo: AliasRepository, course_repo: CourseRepository,
) -> None:
    """Catalog ids are lowercase; a ref shouted in a chat message still lands."""
    assert resolve_course_ref(
        "NEU-CS-5800", alias_repo=alias_repo, course_repo=course_repo,
    ) == ["neu-cs-5800"]


# === Tier 1: URL separators standing in for the code's space ===

@pytest.mark.parametrize(
    "ref",
    ["CS-5800", "CS_5800", "CS+5800", "CS 5800", "cs5800", "cs-5800"],
)
def test_ref_url_separator_forms_all_resolve(
    ref: str, alias_repo: AliasRepository, course_repo: CourseRepository,
) -> None:
    """v_course_lookup stores the canonical 'CS 5800' — every spelling a URL
    (or a human hand-writing a link) produces has to normalize back onto it."""
    assert resolve_course_ref(
        ref, alias_repo=alias_repo, course_repo=course_repo,
    ) == ["neu-cs-5800"]


def test_ref_resolves_slang_alias(
    alias_repo: AliasRepository, course_repo: CourseRepository,
) -> None:
    """?course=Algo is a legal share — the alias tier is the whole point."""
    assert resolve_course_ref(
        "Algo", alias_repo=alias_repo, course_repo=course_repo,
    ) == ["neu-cs-5800"]


def test_ref_resolves_cjk_slang_alias(
    alias_repo: AliasRepository, course_repo: CourseRepository,
) -> None:
    assert resolve_course_ref(
        "应用 AI", alias_repo=alias_repo, course_repo=course_repo,
    ) == ["neu-aai-6600"]


# === Non-matches are ordinary, not errors ===

@pytest.mark.parametrize("ref", ["", "   ", "-", "---", "CS-9999", "neu-cs-9999"])
def test_ref_junk_returns_empty(
    ref: str, alias_repo: AliasRepository, course_repo: CourseRepository,
) -> None:
    assert resolve_course_ref(
        ref, alias_repo=alias_repo, course_repo=course_repo,
    ) == []


def test_ref_over_length_rejected_before_db(
    alias_repo: AliasRepository, course_repo: CourseRepository,
) -> None:
    """Padding a valid code past the cap must NOT resolve — otherwise the
    length guard is decorative and arbitrarily long refs reach SQLite."""
    ref = "CS-5800" + "x" * MAX_COURSE_REF_LEN
    assert len(ref) > MAX_COURSE_REF_LEN
    assert resolve_course_ref(
        ref, alias_repo=alias_repo, course_repo=course_repo,
    ) == []


def test_ref_pending_alias_does_not_leak(
    alias_repo: AliasRepository, course_repo: CourseRepository,
) -> None:
    """A shared link must not be a side door around alias review."""
    alias_repo.add(Alias(
        alias_text="unreviewed-guess", alias_type=AliasType.SLANG,
        primary_course_id="neu-aai-6600",
        source=AliasSource.LLM_INFERRED,
        review_status=AliasReviewStatus.PENDING,
    ))
    assert resolve_course_ref(
        "unreviewed-guess", alias_repo=alias_repo, course_repo=course_repo,
    ) == []


def test_ref_with_hyphen_in_alias_text_resolves(
    alias_repo: AliasRepository, course_repo: CourseRepository,
) -> None:
    """The raw form is tried after the de-separated one, so an alias whose
    text genuinely contains a hyphen is still reachable."""
    alias_repo.add(Alias(
        alias_text="e-commerce", alias_type=AliasType.SLANG,
        primary_course_id="neu-cs-5800",
        source=AliasSource.MANUAL,
        review_status=AliasReviewStatus.APPROVED,
    ))
    assert resolve_course_ref(
        "e-commerce", alias_repo=alias_repo, course_repo=course_repo,
    ) == ["neu-cs-5800"]
