"""Tests for llm.alias_detector — candidate queueing logic.

Uses the real AliasRepository against an in-memory DB (via the empty_db
fixture from conftest) so we exercise the de-dup + resolve paths.
"""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from db.alias_repository import AliasRepository
from db.repository import CourseRepository
from llm.alias_detector import (
    AliasCandidate,
    DEFAULT_CONFIDENCE_THRESHOLD,
    MAX_EVIDENCE_LEN,
    queue_candidates,
)
from schemas.alias import Alias, AliasReviewStatus, AliasSource, AliasType
from schemas.course import Course


@pytest.fixture
def repo(empty_db: sqlite3.Connection) -> AliasRepository:
    course_repo = CourseRepository(empty_db)
    course_repo.insert(Course(
        course_id="uuid-cs5800", primary_code="CS 5800",
        primary_name="Algorithms",
    ))
    course_repo.insert(Course(
        course_id="uuid-aai6600", primary_code="AAI 6600",
        primary_name="Applied AI",
    ))
    return AliasRepository(empty_db)


def _candidate(
    text: str = "Algo",
    course: str = "uuid-cs5800",
    confidence: float = 0.7,
    alias_type: AliasType = AliasType.SLANG,
    excerpt: str = "saw 'Algo' in this reddit post about CS 5800",
) -> AliasCandidate:
    return AliasCandidate(
        alias_text=text,
        alias_type=alias_type,
        primary_course_id=course,
        confidence=confidence,
        source_excerpt=excerpt,
    )


# === Pydantic validation of AliasCandidate ===

def test_candidate_rejects_empty_text() -> None:
    with pytest.raises(ValidationError):
        AliasCandidate(
            alias_text="", alias_type=AliasType.SLANG,
            primary_course_id="x", confidence=0.5, source_excerpt="x",
        )


def test_candidate_rejects_confidence_out_of_range() -> None:
    with pytest.raises(ValidationError):
        AliasCandidate(
            alias_text="x", alias_type=AliasType.SLANG,
            primary_course_id="x", confidence=1.5, source_excerpt="x",
        )


def test_candidate_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        AliasCandidate(
            alias_text="x", alias_type=AliasType.SLANG,
            primary_course_id="x", confidence=0.5, source_excerpt="x",
            unexpected="boom",
        )


# === queue_candidates happy path ===

def test_queue_single_candidate(repo: AliasRepository) -> None:
    counts = queue_candidates([_candidate()], repo=repo)
    assert counts == {"queued": 1, "skipped_low_confidence": 0, "skipped_already_known": 0}

    pending = repo.list_pending()
    assert len(pending) == 1
    assert pending[0].alias_text == "Algo"
    assert pending[0].source == AliasSource.LLM_INFERRED
    assert pending[0].review_status == AliasReviewStatus.PENDING


def test_queue_persists_evidence_excerpt(repo: AliasRepository) -> None:
    queue_candidates([_candidate(excerpt="full reddit body here")], repo=repo)
    persisted = repo.list_pending()[0]
    assert persisted.evidence == "full reddit body here"


def test_queue_truncates_long_excerpt(repo: AliasRepository) -> None:
    long_excerpt = "x" * 2000
    queue_candidates([_candidate(excerpt=long_excerpt)], repo=repo)
    persisted = repo.list_pending()[0]
    assert persisted.evidence is not None
    assert len(persisted.evidence) == MAX_EVIDENCE_LEN


# === Skip rules ===

def test_skip_low_confidence(repo: AliasRepository) -> None:
    counts = queue_candidates(
        [_candidate(confidence=0.2)],
        repo=repo,
        confidence_threshold=DEFAULT_CONFIDENCE_THRESHOLD,
    )
    assert counts["skipped_low_confidence"] == 1
    assert counts["queued"] == 0
    assert repo.list_pending() == []


def test_threshold_inclusive(repo: AliasRepository) -> None:
    """confidence == threshold should pass (>= behavior)."""
    counts = queue_candidates(
        [_candidate(confidence=0.4)],
        repo=repo, confidence_threshold=0.4,
    )
    assert counts["queued"] == 1


def test_skip_when_already_resolves_via_primary_code(
    repo: AliasRepository,
) -> None:
    """If candidate text matches the course's primary_code, it already
    resolves through v_course_lookup — no point queueing."""
    counts = queue_candidates(
        [_candidate(text="CS 5800", course="uuid-cs5800")],
        repo=repo,
    )
    assert counts["skipped_already_known"] == 1
    assert counts["queued"] == 0


def test_skip_when_approved_alias_already_exists(
    repo: AliasRepository,
) -> None:
    """If an approved alias already maps text -> course, skip."""
    repo.add(Alias(
        alias_text="Algo", alias_type=AliasType.SLANG,
        primary_course_id="uuid-cs5800",
        source=AliasSource.MANUAL,
        review_status=AliasReviewStatus.APPROVED,
    ))
    counts = queue_candidates([_candidate(text="Algo")], repo=repo)
    assert counts["skipped_already_known"] == 1


def test_skip_when_pending_alias_already_exists(
    repo: AliasRepository,
) -> None:
    """Re-running detector shouldn't pile up duplicate pending entries."""
    queue_candidates([_candidate(text="Algo")], repo=repo)
    # second run with same candidate
    counts = queue_candidates([_candidate(text="Algo")], repo=repo)
    assert counts["queued"] == 0
    assert counts["skipped_already_known"] == 1
    assert len(repo.list_pending()) == 1


def test_does_not_skip_same_text_for_different_course(
    repo: AliasRepository,
) -> None:
    """Distinct courses can legitimately share an alias_text candidate;
    only the (text, course) pair triggers de-dup."""
    queue_candidates([_candidate(text="Hard", course="uuid-cs5800")], repo=repo)
    counts = queue_candidates(
        [_candidate(text="Hard", course="uuid-aai6600")],
        repo=repo,
    )
    assert counts["queued"] == 1


# === Mixed batch ===

def test_mixed_batch_counts_correctly(repo: AliasRepository) -> None:
    candidates = [
        _candidate(text="Algo"),                                    # queues
        _candidate(text="lowconf", confidence=0.2),                 # low conf
        _candidate(text="CS 5800"),                                 # already resolves
        _candidate(text="Algo"),                                    # dup of #1
        _candidate(text="MyClass", course="uuid-aai6600",
                   excerpt="y"),                                    # queues (different course)
    ]
    counts = queue_candidates(candidates, repo=repo)
    assert counts == {
        "queued": 2,
        "skipped_low_confidence": 1,
        "skipped_already_known": 2,
    }


def test_pending_aliases_do_not_leak_to_resolve(repo: AliasRepository) -> None:
    """The whole point of pending: must NOT be findable via resolve()."""
    queue_candidates([_candidate(text="risky_guess")], repo=repo)

    # Pending alias is in DB ...
    assert len(repo.find_by_text("risky_guess")) == 1
    # ... but not in v_course_lookup
    assert repo.resolve("risky_guess") == []
