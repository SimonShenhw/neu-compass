"""CourseRepository — Pydantic Course <-> SQLite courses table.

Per ADR-0013, SQLite is the source of truth. Inserts always set status='pending';
the embed pipeline calls mark_indexed() after FAISS write succeeds.

The metadata column duplicates the L1 hard fields from the full Course dump
(stored in generated_json) so SQLite JSON1 indexes can serve hot-path filter
queries — see db/init.sql idx_courses_term / idx_courses_credits.
"""

from __future__ import annotations

import json
import sqlite3

from schemas.course import Course


class CourseNotFound(LookupError):
    """Raised when a course_id is expected to exist but doesn't."""


class CourseRepository:
    """Pydantic Course <-> SQLite. Caller owns the connection lifecycle."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # === Write ===

    def insert(self, course: Course, *, raw_text: str | None = None) -> None:
        """Insert a new course with status='pending'.

        Raises sqlite3.IntegrityError if course_id already exists; use upsert()
        for idempotent writes.
        """
        metadata, generated = self._serialize(course)
        self._conn.execute(
            """
            INSERT INTO courses (
                course_id, primary_code, primary_name,
                metadata, raw_text, generated_json,
                schema_version, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (course.course_id, course.primary_code, course.primary_name,
             metadata, raw_text, generated, course.schema_version),
        )

    def upsert(self, course: Course, *, raw_text: str | None = None) -> None:
        """Insert or update by course_id.

        Status resets to 'pending' and indexed_at clears — content changed,
        so the FAISS embedding is now stale. raw_text is preserved if not
        provided again (COALESCE keeps the existing value).
        """
        metadata, generated = self._serialize(course)
        self._conn.execute(
            """
            INSERT INTO courses (
                course_id, primary_code, primary_name,
                metadata, raw_text, generated_json,
                schema_version, status, indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', NULL)
            ON CONFLICT(course_id) DO UPDATE SET
                primary_code   = excluded.primary_code,
                primary_name   = excluded.primary_name,
                metadata       = excluded.metadata,
                raw_text       = COALESCE(excluded.raw_text, courses.raw_text),
                generated_json = excluded.generated_json,
                schema_version = excluded.schema_version,
                status         = 'pending',
                indexed_at     = NULL,
                updated_at     = CURRENT_TIMESTAMP
            """,
            (course.course_id, course.primary_code, course.primary_name,
             metadata, raw_text, generated, course.schema_version),
        )

    def mark_indexed(self, course_id: str) -> None:
        """Transition pending -> indexed. Called after FAISS write succeeds.

        Strict: raises ValueError if status is not 'pending'. This catches
        double-mark bugs and FAISS retry edge cases — caller should check
        get_status() first if uncertain.
        """
        self._transition(course_id, expected_from="pending", to="indexed", set_indexed_at=True)

    def mark_failed(self, course_id: str) -> None:
        """Transition pending -> failed (giving up on this row)."""
        self._transition(course_id, expected_from="pending", to="failed")

    def reset_to_pending(self, course_id: str) -> None:
        """Reset failed -> pending for manual retry."""
        self._transition(course_id, expected_from="failed", to="pending")

    # === Read ===

    def get(self, course_id: str) -> Course:
        row = self._conn.execute(
            "SELECT generated_json FROM courses WHERE course_id = ?",
            (course_id,),
        ).fetchone()
        if row is None:
            raise CourseNotFound(course_id)
        return Course.model_validate_json(row["generated_json"])

    def exists(self, course_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM courses WHERE course_id = ?", (course_id,)
        ).fetchone()
        return row is not None

    def get_status(self, course_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT status FROM courses WHERE course_id = ?", (course_id,)
        ).fetchone()
        return row["status"] if row else None

    def get_by_primary_code(self, primary_code: str) -> Course | None:
        """Lookup by canonical code (case-insensitive). Returns None if missing.

        Note: this only matches the primary_code column, NOT the alias table.
        For alias-aware lookup, query v_course_lookup view directly.
        """
        row = self._conn.execute(
            "SELECT generated_json FROM courses WHERE primary_code = ? COLLATE NOCASE",
            (primary_code,),
        ).fetchone()
        return Course.model_validate_json(row["generated_json"]) if row else None

    def list_by_status(self, status: str, *, limit: int | None = None) -> list[Course]:
        sql = "SELECT generated_json FROM courses WHERE status = ?"
        params: list = [status]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = self._conn.execute(sql, params).fetchall()
        return [Course.model_validate_json(r["generated_json"]) for r in rows]

    def count_by_status(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM courses GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    # === Internal ===

    def _transition(
        self, course_id: str, *, expected_from: str, to: str,
        set_indexed_at: bool = False,
    ) -> None:
        clauses = ["status = ?"]
        params: list = [to]
        if set_indexed_at:
            clauses.append("indexed_at = CURRENT_TIMESTAMP")
        sql = (
            f"UPDATE courses SET {', '.join(clauses)} "
            "WHERE course_id = ? AND status = ?"
        )
        params.extend([course_id, expected_from])

        cursor = self._conn.execute(sql, params)
        if cursor.rowcount == 1:
            return

        # 0 rows updated: either course missing, or status mismatch. Disambiguate
        # for a useful error message — the alternative is silent no-op, which
        # masks real bugs in the embed pipeline.
        actual = self.get_status(course_id)
        if actual is None:
            raise CourseNotFound(course_id)
        raise ValueError(
            f"Cannot transition course {course_id!r} to {to!r}: "
            f"current status is {actual!r}, expected {expected_from!r}"
        )

    @staticmethod
    def _serialize(course: Course) -> tuple[str, str]:
        """Build (metadata_json, generated_json) for storage.

        metadata: only L1 hard fields, mirrors db/init.sql idx_courses_term /
        idx_courses_credits expectations.
        generated_json: full Pydantic dump including all soft fields + evidence.
        """
        metadata = {
            "term": course.term,
            "credits": course.credits,
            "professor": course.professor,
            "prereqs": course.prereqs,
            "delivery_mode": course.delivery_mode.value if course.delivery_mode else None,
        }
        return json.dumps(metadata), course.model_dump_json()
