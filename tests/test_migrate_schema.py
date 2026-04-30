"""Tests for scripts/migrate_schema.py — DB-level migration runner."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from schemas.course import SCHEMA_VERSION  # noqa: E402
from scripts.init_db import init_database  # noqa: E402
from scripts.migrate_schema import migrate_all  # noqa: E402


def _minimal_v1_0_blob() -> dict:
    """A minimum v1.0 generated_json blob — schema_version 1.0 + no v1.1 keys."""
    return {
        "course_id": "u1",
        "primary_code": "CS 5800",
        "primary_name": "Algorithms",
        "schema_version": "1.0",
        "professor": [],
        "term": "Spring 2026",
        "credits": 4,
        "prereqs": [],
        "delivery_mode": None,
        "workload_hours_per_week": None,
        "difficulty_score": None,
        "grading_components": [],
        "topics_covered": [],
        "skill_tags": [],
        "career_relevance": [],
        "controversial_signals": [],
        "evidence_snippets": [],
        "extraction_confidence": None,
        "source_review_ids": [],
        "created_at": "2026-04-30T00:00:00Z",
        "updated_at": "2026-04-30T00:00:00Z",
    }


def _seed_v1_0_row(db_path: Path, course_id: str = "u1") -> None:
    init_database(db_path)
    blob = _minimal_v1_0_blob()
    blob["course_id"] = course_id

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO courses
            (course_id, primary_code, primary_name, metadata,
             generated_json, schema_version, status)
        VALUES (?, ?, ?, '{}', ?, '1.0', 'pending')
        """,
        (course_id, "CS 5800", "Algorithms", json.dumps(blob)),
    )
    conn.commit()
    conn.close()


def test_migrate_all_v1_0_to_current(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    _seed_v1_0_row(db_path)

    counts = migrate_all(db_path)
    assert counts == {"already_current": 0, "migrated": 1, "errors": 0}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT schema_version, generated_json FROM courses WHERE course_id='u1'"
        ).fetchone()
    finally:
        conn.close()

    # Both the column and the embedded JSON should now match SCHEMA_VERSION.
    assert row["schema_version"] == SCHEMA_VERSION
    data = json.loads(row["generated_json"])
    assert data["schema_version"] == SCHEMA_VERSION

    # All v1.1 fields present (default values).
    assert data["instructor_contact"] is None
    assert data["textbooks"] == []
    assert data["meeting_schedule"] is None
    assert data["ai_policy"] is None


def test_migrate_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    _seed_v1_0_row(db_path)

    migrate_all(db_path)
    counts = migrate_all(db_path)

    assert counts["migrated"] == 0
    assert counts["already_current"] == 1


def test_migrate_dry_run_does_not_persist(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    _seed_v1_0_row(db_path)

    counts = migrate_all(db_path, dry_run=True)
    assert counts["migrated"] == 1   # would have migrated 1
    assert counts["already_current"] == 0

    # But the DB row should still be at v1.0
    conn = sqlite3.connect(str(db_path))
    try:
        ver = conn.execute(
            "SELECT schema_version FROM courses WHERE course_id='u1'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert ver == "1.0"


def test_migrate_mixed_versions(tmp_path: Path) -> None:
    """Already-current rows are skipped; v1.0 rows are migrated."""
    db_path = tmp_path / "test.db"
    init_database(db_path)

    conn = sqlite3.connect(str(db_path))
    # One v1.0 row
    blob_v1_0 = _minimal_v1_0_blob()
    blob_v1_0["course_id"] = "u_old"
    conn.execute(
        "INSERT INTO courses (course_id, primary_code, primary_name, metadata, "
        "generated_json, schema_version, status) "
        "VALUES (?, ?, ?, '{}', ?, '1.0', 'pending')",
        ("u_old", "CS 5800", "Algorithms", json.dumps(blob_v1_0)),
    )
    # One already-current row
    blob_current = _minimal_v1_0_blob()
    blob_current["course_id"] = "u_new"
    blob_current["schema_version"] = SCHEMA_VERSION
    conn.execute(
        "INSERT INTO courses (course_id, primary_code, primary_name, metadata, "
        "generated_json, schema_version, status) "
        "VALUES (?, ?, ?, '{}', ?, ?, 'pending')",
        ("u_new", "DS 5220", "ML", json.dumps(blob_current), SCHEMA_VERSION),
    )
    conn.commit()
    conn.close()

    counts = migrate_all(db_path)
    assert counts["migrated"] == 1
    assert counts["already_current"] == 1
    assert counts["errors"] == 0


def test_migrate_empty_db_safe(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    init_database(db_path)
    counts = migrate_all(db_path)
    assert counts == {"already_current": 0, "migrated": 0, "errors": 0}


def test_migrate_unknown_version_counts_as_error(tmp_path: Path) -> None:
    """A row at version '0.5' (unknown) should error rather than crash the runner."""
    db_path = tmp_path / "test.db"
    init_database(db_path)

    blob = _minimal_v1_0_blob()
    blob["schema_version"] = "0.5"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO courses (course_id, primary_code, primary_name, metadata, "
        "generated_json, schema_version, status) "
        "VALUES ('u1', 'CS 5800', 'Algorithms', '{}', ?, '0.5', 'pending')",
        (json.dumps(blob),),
    )
    conn.commit()
    conn.close()

    counts = migrate_all(db_path)
    assert counts["errors"] == 1
    assert counts["migrated"] == 0
