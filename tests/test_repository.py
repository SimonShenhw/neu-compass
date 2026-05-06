"""Tests for db.repository — Course <-> SQLite mapping + state machine."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from db.repository import CourseNotFound, CourseRepository
from schemas.course import Course, DeliveryMode, EvidenceSnippet


@pytest.fixture
def repo(empty_db: sqlite3.Connection) -> CourseRepository:
    return CourseRepository(empty_db)


def _course(course_id: str = "uuid-1", **overrides: Any) -> Course:
    base: dict[str, Any] = {
        "course_id": course_id,
        "primary_code": "CS 5800",
        "primary_name": "Algorithms",
    }
    base.update(overrides)
    return Course(**base)


# === insert / get roundtrip ===

def test_insert_and_get_roundtrip(repo: CourseRepository) -> None:
    c = _course(
        credits=4,
        term="Spring 2026",
        difficulty_score=4.2,
        evidence_snippets=[
            EvidenceSnippet(
                field="difficulty_score", value=4.2,
                source_id="rmp_1", quote="brutal homework", confidence=0.85,
            ),
        ],
    )
    repo.insert(c)
    fetched = repo.get("uuid-1")
    assert fetched == c


def test_insert_duplicate_raises(repo: CourseRepository) -> None:
    repo.insert(_course())
    with pytest.raises(sqlite3.IntegrityError):
        repo.insert(_course())  # same course_id


def test_insert_default_status_pending(repo: CourseRepository, empty_db: sqlite3.Connection) -> None:
    repo.insert(_course())
    row = empty_db.execute(
        "SELECT status, indexed_at FROM courses WHERE course_id='uuid-1'"
    ).fetchone()
    assert row["status"] == "pending"
    assert row["indexed_at"] is None


def test_get_missing_raises(repo: CourseRepository) -> None:
    with pytest.raises(CourseNotFound):
        repo.get("nonexistent")


def test_exists(repo: CourseRepository) -> None:
    assert not repo.exists("uuid-1")
    repo.insert(_course())
    assert repo.exists("uuid-1")


# === metadata is queryable via JSON1 (proves L1 hot-path filter works) ===

def test_metadata_extracted_for_json1_index(
    repo: CourseRepository, empty_db: sqlite3.Connection,
) -> None:
    repo.insert(_course(
        course_id="u-cs5800", credits=4, term="Spring 2026",
        professor=["Dr. Zhang"], delivery_mode=DeliveryMode.HYBRID,
    ))
    repo.insert(_course(
        course_id="u-ds5220", primary_code="DS 5220",
        credits=3, term="Spring 2026",
    ))

    rows = empty_db.execute("""
        SELECT course_id FROM courses
        WHERE json_extract(metadata, '$.credits') = 4
          AND json_extract(metadata, '$.term') = 'Spring 2026'
    """).fetchall()
    assert [r["course_id"] for r in rows] == ["u-cs5800"]


def test_metadata_serializes_delivery_mode_as_string(
    repo: CourseRepository, empty_db: sqlite3.Connection,
) -> None:
    repo.insert(_course(delivery_mode=DeliveryMode.ONLINE))
    row = empty_db.execute(
        "SELECT metadata FROM courses WHERE course_id='uuid-1'"
    ).fetchone()
    metadata = json.loads(row["metadata"])
    assert metadata["delivery_mode"] == "online"


def test_raw_text_stored(repo: CourseRepository, empty_db: sqlite3.Connection) -> None:
    repo.insert(_course(), raw_text="catalog desc + syllabus body")
    row = empty_db.execute(
        "SELECT raw_text FROM courses WHERE course_id='uuid-1'"
    ).fetchone()
    assert row["raw_text"] == "catalog desc + syllabus body"


# === upsert ===

def test_upsert_inserts_when_missing(repo: CourseRepository) -> None:
    repo.upsert(_course())
    assert repo.exists("uuid-1")
    assert repo.get_status("uuid-1") == "pending"


def test_upsert_updates_existing(repo: CourseRepository) -> None:
    repo.insert(_course(primary_name="Old Name"))
    repo.upsert(_course(primary_name="New Name"))
    assert repo.get("uuid-1").primary_name == "New Name"


def test_upsert_resets_status_to_pending(repo: CourseRepository) -> None:
    """Upsert means content changed, so existing FAISS embedding is stale."""
    repo.insert(_course())
    repo.mark_indexed("uuid-1")
    assert repo.get_status("uuid-1") == "indexed"

    repo.upsert(_course(primary_name="Updated"))
    assert repo.get_status("uuid-1") == "pending"


def test_upsert_preserves_raw_text_when_not_provided(
    repo: CourseRepository, empty_db: sqlite3.Connection,
) -> None:
    repo.insert(_course(), raw_text="original text")
    repo.upsert(_course(primary_name="Updated"))  # no raw_text arg

    row = empty_db.execute(
        "SELECT raw_text FROM courses WHERE course_id='uuid-1'"
    ).fetchone()
    assert row["raw_text"] == "original text"


def test_upsert_overwrites_raw_text_when_provided(
    repo: CourseRepository, empty_db: sqlite3.Connection,
) -> None:
    repo.insert(_course(), raw_text="original text")
    repo.upsert(_course(), raw_text="new text")

    row = empty_db.execute(
        "SELECT raw_text FROM courses WHERE course_id='uuid-1'"
    ).fetchone()
    assert row["raw_text"] == "new text"


# === state machine: mark_indexed / mark_failed / reset ===

def test_mark_indexed_transitions_pending_to_indexed(
    repo: CourseRepository, empty_db: sqlite3.Connection,
) -> None:
    repo.insert(_course())
    repo.mark_indexed("uuid-1")

    row = empty_db.execute(
        "SELECT status, indexed_at FROM courses WHERE course_id='uuid-1'"
    ).fetchone()
    assert row["status"] == "indexed"
    assert row["indexed_at"] is not None


def test_mark_indexed_on_already_indexed_raises(repo: CourseRepository) -> None:
    """Strict transition: catches double-mark / FAISS retry bugs."""
    repo.insert(_course())
    repo.mark_indexed("uuid-1")
    with pytest.raises(ValueError, match="indexed"):
        repo.mark_indexed("uuid-1")


def test_mark_indexed_on_missing_raises_not_found(repo: CourseRepository) -> None:
    with pytest.raises(CourseNotFound):
        repo.mark_indexed("nonexistent")


def test_mark_failed_transitions_pending_to_failed(repo: CourseRepository) -> None:
    repo.insert(_course())
    repo.mark_failed("uuid-1")
    assert repo.get_status("uuid-1") == "failed"


def test_mark_failed_on_indexed_raises(repo: CourseRepository) -> None:
    repo.insert(_course())
    repo.mark_indexed("uuid-1")
    with pytest.raises(ValueError):
        repo.mark_failed("uuid-1")


def test_reset_to_pending(repo: CourseRepository) -> None:
    repo.insert(_course())
    repo.mark_failed("uuid-1")
    repo.reset_to_pending("uuid-1")
    assert repo.get_status("uuid-1") == "pending"


def test_reset_to_pending_on_indexed_raises(repo: CourseRepository) -> None:
    """Don't allow indexed -> pending without going through upsert."""
    repo.insert(_course())
    repo.mark_indexed("uuid-1")
    with pytest.raises(ValueError):
        repo.reset_to_pending("uuid-1")


# === read patterns ===

def test_get_by_primary_code(repo: CourseRepository) -> None:
    repo.insert(_course(primary_code="CS 5800"))
    assert repo.get_by_primary_code("CS 5800") is not None
    assert repo.get_by_primary_code("DS 9999") is None


def test_get_by_primary_code_case_insensitive(repo: CourseRepository) -> None:
    repo.insert(_course(primary_code="CS 5800"))
    # COLLATE NOCASE on column means lookup is case-insensitive
    assert repo.get_by_primary_code("cs 5800") is not None


def test_list_by_status(repo: CourseRepository) -> None:
    repo.insert(_course("u1"))
    repo.insert(_course("u2"))
    repo.insert(_course("u3"))
    repo.mark_indexed("u2")

    pending = repo.list_by_status("pending")
    indexed = repo.list_by_status("indexed")
    assert {c.course_id for c in pending} == {"u1", "u3"}
    assert {c.course_id for c in indexed} == {"u2"}


def test_list_by_status_with_limit(repo: CourseRepository) -> None:
    for i in range(5):
        repo.insert(_course(f"u{i}"))
    rows = repo.list_by_status("pending", limit=2)
    assert len(rows) == 2


def test_count_by_status(repo: CourseRepository) -> None:
    for i in range(3):
        repo.insert(_course(f"u{i}"))
    repo.mark_indexed("u0")
    repo.mark_failed("u1")

    counts = repo.count_by_status()
    assert counts == {"indexed": 1, "failed": 1, "pending": 1}


def test_get_status_missing_returns_none(repo: CourseRepository) -> None:
    assert repo.get_status("nonexistent") is None


# === get_batch ===

def test_get_batch_returns_courses_keyed_by_id(repo: CourseRepository) -> None:
    repo.insert(_course("uuid-1", primary_code="CS 5800", primary_name="Algorithms"))
    repo.insert(_course("uuid-2", primary_code="CS 5200", primary_name="DB"))
    repo.insert(_course("uuid-3", primary_code="AAI 6600", primary_name="AI Ethics"))

    out = repo.get_batch(["uuid-1", "uuid-3"])
    assert set(out.keys()) == {"uuid-1", "uuid-3"}
    assert out["uuid-1"].primary_code == "CS 5800"
    assert out["uuid-3"].primary_code == "AAI 6600"


def test_get_batch_silently_omits_missing(repo: CourseRepository) -> None:
    """Missing IDs aren't an error — caller decides handling. This matters
    for HybridRetriever where alias points at vanished course_ids."""
    repo.insert(_course("uuid-1"))
    out = repo.get_batch(["uuid-1", "uuid-missing", "uuid-also-missing"])
    assert set(out.keys()) == {"uuid-1"}


def test_get_batch_empty_input_returns_empty_dict(repo: CourseRepository) -> None:
    """No SQL roundtrip on empty input."""
    assert repo.get_batch([]) == {}


def test_get_batch_preserves_order_independence(repo: CourseRepository) -> None:
    """Caller can rely on the dict for lookup; insertion order doesn't
    matter. Defensive against SQLite returning rows in arbitrary order."""
    repo.insert(_course("a"))
    repo.insert(_course("b"))
    repo.insert(_course("c"))
    out_one = repo.get_batch(["c", "a", "b"])
    out_two = repo.get_batch(["a", "b", "c"])
    assert out_one.keys() == out_two.keys() == {"a", "b", "c"}
