"""Tests for db/init.sql — schema correctness, constraints, view behavior."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INIT_SQL = (PROJECT_ROOT / "db" / "init.sql").read_text(encoding="utf-8")


@pytest.fixture
def db() -> Iterator[sqlite3.Connection]:
    """In-memory SQLite with init.sql applied + FK enforcement on."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(INIT_SQL)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _insert_course(db: sqlite3.Connection, course_id: str = "uuid-1",
                   code: str = "CS 5800", metadata: str = "{}") -> None:
    db.execute(
        "INSERT INTO courses (course_id, primary_code, primary_name, metadata, generated_json) "
        "VALUES (?, ?, ?, json(?), '{}')",
        (course_id, code, "Algorithms", metadata),
    )
    db.commit()


# === Structure ===

def test_all_expected_tables_exist(db: sqlite3.Connection) -> None:
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {r["name"] for r in rows}
    expected = {"courses", "course_aliases", "users", "user_unlocks",
                "coop_experiences", "user_courses", "schema_versions"}
    assert expected.issubset(names), f"Missing: {expected - names}"


def test_v_course_lookup_view_exists(db: sqlite3.Connection) -> None:
    rows = db.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()
    assert "v_course_lookup" in {r["name"] for r in rows}


def test_schema_version_seeded(db: sqlite3.Connection) -> None:
    versions = {r["version"] for r in db.execute("SELECT version FROM schema_versions")}
    assert "1.0" in versions
    assert "1.1" in versions  # PLAN v2.2 §3.6 — user_courses added


def test_idempotent_re_run(db: sqlite3.Connection) -> None:
    """init.sql 跑两次不应该报错 (CREATE ... IF NOT EXISTS)."""
    db.executescript(INIT_SQL)
    db.commit()
    row = db.execute(
        "SELECT COUNT(*) AS n FROM schema_versions WHERE version='1.0'"
    ).fetchone()
    assert row["n"] == 1  # INSERT OR IGNORE 防止重复


# === courses constraints ===

def test_course_status_default_pending(db: sqlite3.Connection) -> None:
    _insert_course(db)
    row = db.execute("SELECT status FROM courses WHERE course_id='uuid-1'").fetchone()
    assert row["status"] == "pending"


def test_course_status_check_constraint(db: sqlite3.Connection) -> None:
    _insert_course(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE courses SET status='bogus' WHERE course_id='uuid-1'")


def test_course_status_transitions(db: sqlite3.Connection) -> None:
    _insert_course(db)
    for state in ("indexed", "failed", "pending"):
        db.execute("UPDATE courses SET status=? WHERE course_id='uuid-1'", (state,))
        db.commit()


def test_course_updated_at_trigger(db: sqlite3.Connection) -> None:
    """updated_at 应在 UPDATE 后被触发器自动刷新.

    Deterministic version: instead of sleeping 1.1s and hoping CURRENT_TIMESTAMP
    crosses a second boundary (flaky under load), seed the row with an
    obviously-stale timestamp, then mutate a different column. The trigger's
    WHEN clause matches, fires CURRENT_TIMESTAMP, and the assertion is just
    `new_value != '2020-01-01 00:00:00'` — independent of clock resolution.
    """
    _insert_course(db)
    db.execute(
        "UPDATE courses SET updated_at='2020-01-01 00:00:00' WHERE course_id='uuid-1'"
    )
    db.commit()

    # Now mutate a different column. The trigger's WHEN clause fires because
    # NEW.updated_at == OLD.updated_at (we didn't touch it).
    db.execute("UPDATE courses SET primary_name='New Name' WHERE course_id='uuid-1'")
    db.commit()

    new_value = db.execute(
        "SELECT updated_at FROM courses WHERE course_id='uuid-1'"
    ).fetchone()["updated_at"]
    assert new_value != "2020-01-01 00:00:00"


def test_credits_indexed_via_json_extract(db: sqlite3.Connection) -> None:
    """硬过滤典型查询 pattern: WHERE term=? AND credits=?."""
    _insert_course(db, "uuid-1", "CS 5800", '{"credits": 4, "term": "Spring 2026"}')
    _insert_course(db, "uuid-2", "DS 5220", '{"credits": 3, "term": "Spring 2026"}')

    rows = db.execute("""
        SELECT course_id FROM courses
        WHERE json_extract(metadata, '$.credits') = 4
          AND json_extract(metadata, '$.term') = 'Spring 2026'
    """).fetchall()
    assert [r["course_id"] for r in rows] == ["uuid-1"]


# === course_aliases constraints ===

def test_alias_type_check(db: sqlite3.Connection) -> None:
    _insert_course(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO course_aliases (alias_text, alias_type, primary_course_id, source) "
            "VALUES ('foo', 'invalid_type', 'uuid-1', 'manual')"
        )


def test_alias_source_check(db: sqlite3.Connection) -> None:
    _insert_course(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO course_aliases (alias_text, alias_type, primary_course_id, source) "
            "VALUES ('foo', 'slang', 'uuid-1', 'wiki_scraped')"
        )


def test_alias_confidence_bounds(db: sqlite3.Connection) -> None:
    _insert_course(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO course_aliases "
            "(alias_text, alias_type, primary_course_id, source, confidence) "
            "VALUES ('foo', 'slang', 'uuid-1', 'manual', 1.5)"
        )


def test_alias_unique_combo(db: sqlite3.Connection) -> None:
    _insert_course(db)
    db.execute(
        "INSERT INTO course_aliases "
        "(alias_text, alias_type, primary_course_id, source) "
        "VALUES ('5800', 'slang', 'uuid-1', 'manual')"
    )
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO course_aliases "
            "(alias_text, alias_type, primary_course_id, source) "
            "VALUES ('5800', 'slang', 'uuid-1', 'manual')"
        )


def test_alias_fk_cascades_on_course_delete(db: sqlite3.Connection) -> None:
    _insert_course(db)
    db.execute(
        "INSERT INTO course_aliases "
        "(alias_text, alias_type, primary_course_id, source) "
        "VALUES ('5800', 'slang', 'uuid-1', 'manual')"
    )
    db.commit()

    db.execute("DELETE FROM courses WHERE course_id='uuid-1'")
    db.commit()

    rows = db.execute("SELECT * FROM course_aliases").fetchall()
    assert len(rows) == 0


# === v_course_lookup view ===

def test_v_lookup_includes_primary_code(db: sqlite3.Connection) -> None:
    _insert_course(db)
    rows = db.execute(
        "SELECT searchable_term, alias_type FROM v_course_lookup WHERE course_id='uuid-1'"
    ).fetchall()
    terms = {(r["searchable_term"], r["alias_type"]) for r in rows}
    assert ("CS 5800", "primary") in terms


def test_v_lookup_filters_pending_aliases(db: sqlite3.Connection) -> None:
    _insert_course(db)
    db.execute(
        "INSERT INTO course_aliases "
        "(alias_text, alias_type, primary_course_id, source, review_status) "
        "VALUES ('5800', 'slang', 'uuid-1', 'manual', 'approved')"
    )
    db.execute(
        "INSERT INTO course_aliases "
        "(alias_text, alias_type, primary_course_id, source, review_status) "
        "VALUES ('hidden', 'slang', 'uuid-1', 'llm_inferred', 'pending')"
    )
    db.commit()

    terms = {r["searchable_term"] for r in
             db.execute("SELECT searchable_term FROM v_course_lookup")}
    assert "5800" in terms
    assert "hidden" not in terms     # pending 别名不进 view


# === users / user_unlocks ===

def test_user_email_unique(db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO users (user_id, email, domain) "
        "VALUES ('u1', 'a@husky.neu.edu', 'husky.neu.edu')"
    )
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO users (user_id, email, domain) "
            "VALUES ('u2', 'a@husky.neu.edu', 'husky.neu.edu')"
        )


def test_user_unlock_unique_per_pair(db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO users (user_id, email, domain) "
        "VALUES ('u1', 'a@husky.neu.edu', 'husky.neu.edu')"
    )
    db.execute("INSERT INTO user_unlocks (user_id, coop_id) VALUES ('u1', 'c1')")
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO user_unlocks (user_id, coop_id) VALUES ('u1', 'c1')")


def test_user_unlock_cascades_on_user_delete(db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO users (user_id, email, domain) "
        "VALUES ('u1', 'a@husky.neu.edu', 'husky.neu.edu')"
    )
    db.execute("INSERT INTO user_unlocks (user_id, coop_id) VALUES ('u1', 'c1')")
    db.commit()

    db.execute("DELETE FROM users WHERE user_id='u1'")
    db.commit()
    rows = db.execute("SELECT * FROM user_unlocks").fetchall()
    assert len(rows) == 0


# === coop_experiences ===

def test_coop_visibility_check(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO coop_experiences "
            "(coop_id, company, role, visibility_level) "
            "VALUES ('c1', 'TestCo', 'Dev', 99)"
        )


def test_coop_is_seed_check(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO coop_experiences "
            "(coop_id, company, role, is_seed_data) "
            "VALUES ('c1', 'TestCo', 'Dev', 5)"
        )


def test_coop_contributor_set_null_on_user_delete(db: sqlite3.Connection) -> None:
    """User deletion shouldn't lose Co-op data — FK is ON DELETE SET NULL."""
    db.execute(
        "INSERT INTO users (user_id, email, domain) "
        "VALUES ('u1', 'a@husky.neu.edu', 'husky.neu.edu')"
    )
    db.execute(
        "INSERT INTO coop_experiences "
        "(coop_id, company, role, contributor_user_id) "
        "VALUES ('c1', 'TestCo', 'Dev', 'u1')"
    )
    db.commit()

    db.execute("DELETE FROM users WHERE user_id='u1'")
    db.commit()
    row = db.execute(
        "SELECT contributor_user_id FROM coop_experiences WHERE coop_id='c1'"
    ).fetchone()
    assert row["contributor_user_id"] is None


# === user_courses (PLAN v2.2 §3.6) ===


def _seed_user_and_course(db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO users (user_id, email, domain) "
        "VALUES ('u1', 'a@husky.neu.edu', 'husky.neu.edu')"
    )
    _insert_course(db, "uuid-1", "CS 5800")


def test_user_courses_status_default_planning(db: sqlite3.Connection) -> None:
    _seed_user_and_course(db)
    db.execute(
        "INSERT INTO user_courses (user_id, course_id, term) "
        "VALUES ('u1', 'uuid-1', 'fall_2026')"
    )
    db.commit()
    row = db.execute(
        "SELECT status, visibility FROM user_courses WHERE user_id='u1'"
    ).fetchone()
    assert row["status"] == "planning"
    assert row["visibility"] == "private"


def test_user_courses_status_check_constraint(db: sqlite3.Connection) -> None:
    _seed_user_and_course(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO user_courses (user_id, course_id, term, status) "
            "VALUES ('u1', 'uuid-1', 'fall_2026', 'bogus')"
        )


def test_user_courses_visibility_check_constraint(db: sqlite3.Connection) -> None:
    _seed_user_and_course(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO user_courses (user_id, course_id, term, visibility) "
            "VALUES ('u1', 'uuid-1', 'fall_2026', 'world_readable')"
        )


def test_user_courses_unique_per_user_course_term(db: sqlite3.Connection) -> None:
    """A user can plan/enroll the same course in DIFFERENT terms (retake), but
    not the same (user, course, term) twice."""
    _seed_user_and_course(db)
    db.execute(
        "INSERT INTO user_courses (user_id, course_id, term) "
        "VALUES ('u1', 'uuid-1', 'fall_2026')"
    )
    db.commit()

    # Different term — allowed.
    db.execute(
        "INSERT INTO user_courses (user_id, course_id, term) "
        "VALUES ('u1', 'uuid-1', 'spring_2027')"
    )
    db.commit()

    # Same triple — rejected.
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO user_courses (user_id, course_id, term) "
            "VALUES ('u1', 'uuid-1', 'fall_2026')"
        )


def test_user_courses_cascades_on_user_delete(db: sqlite3.Connection) -> None:
    _seed_user_and_course(db)
    db.execute(
        "INSERT INTO user_courses (user_id, course_id, term) "
        "VALUES ('u1', 'uuid-1', 'fall_2026')"
    )
    db.commit()

    db.execute("DELETE FROM users WHERE user_id='u1'")
    db.commit()
    rows = db.execute("SELECT * FROM user_courses").fetchall()
    assert len(rows) == 0


def test_user_courses_cascades_on_course_delete(db: sqlite3.Connection) -> None:
    _seed_user_and_course(db)
    db.execute(
        "INSERT INTO user_courses (user_id, course_id, term) "
        "VALUES ('u1', 'uuid-1', 'fall_2026')"
    )
    db.commit()

    db.execute("DELETE FROM courses WHERE course_id='uuid-1'")
    db.commit()
    rows = db.execute("SELECT * FROM user_courses").fetchall()
    assert len(rows) == 0


def test_user_courses_updated_at_trigger(db: sqlite3.Connection) -> None:
    """Deterministic — see test_course_updated_at_trigger for rationale."""
    _seed_user_and_course(db)
    db.execute(
        "INSERT INTO user_courses (user_id, course_id, term) "
        "VALUES ('u1', 'uuid-1', 'fall_2026')"
    )
    db.execute(
        "UPDATE user_courses SET updated_at='2020-01-01 00:00:00' WHERE user_id='u1'"
    )
    db.commit()

    db.execute(
        "UPDATE user_courses SET status='enrolled' WHERE user_id='u1'"
    )
    db.commit()
    new_value = db.execute(
        "SELECT updated_at FROM user_courses WHERE user_id='u1'"
    ).fetchone()["updated_at"]
    assert new_value != "2020-01-01 00:00:00"
