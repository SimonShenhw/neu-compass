"""CoopRepository — Pydantic CoopExperience <-> SQLite coop_experiences.

Mirrors CourseRepository pattern. Caller owns connection.

Visibility-aware reads: list_visible_to(user_id) joins users.contribution_count
and returns only rows whose visibility_level <= the user's count. Use this
in the API layer; raw list_all() bypasses the tier system and is for admin
/ analytics only.
"""

from __future__ import annotations

import json
import sqlite3

from schemas.coop import CoopExperience, Industry


class CoopNotFound(LookupError):
    """Raised when a coop_id is expected to exist but doesn't."""


class CoopRepository:
    """Pydantic CoopExperience <-> SQLite coop_experiences."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # === Write ===

    def add(self, coop: CoopExperience) -> None:
        """Insert. Raises sqlite3.IntegrityError on duplicate coop_id."""
        self._conn.execute(
            """
            INSERT INTO coop_experiences (
                coop_id, company, role, industry, coop_term, duration_months,
                related_courses, interview_summary, technical_questions,
                salary_range_usd, contributor_user_id,
                is_seed_data, visibility_level, redaction_audit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._params(coop),
        )

    def upsert(self, coop: CoopExperience) -> None:
        """Insert or update on coop_id. UPDATE preserves created_at via not
        touching it; visibility_level / contributor_user_id reset to row's
        new values."""
        self._conn.execute(
            """
            INSERT INTO coop_experiences (
                coop_id, company, role, industry, coop_term, duration_months,
                related_courses, interview_summary, technical_questions,
                salary_range_usd, contributor_user_id,
                is_seed_data, visibility_level, redaction_audit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(coop_id) DO UPDATE SET
                company             = excluded.company,
                role                = excluded.role,
                industry            = excluded.industry,
                coop_term           = excluded.coop_term,
                duration_months     = excluded.duration_months,
                related_courses     = excluded.related_courses,
                interview_summary   = excluded.interview_summary,
                technical_questions = excluded.technical_questions,
                salary_range_usd    = excluded.salary_range_usd,
                contributor_user_id = excluded.contributor_user_id,
                is_seed_data        = excluded.is_seed_data,
                visibility_level    = excluded.visibility_level,
                redaction_audit     = excluded.redaction_audit
            """,
            self._params(coop),
        )

    def delete(self, coop_id: str) -> None:
        """Hard delete. Use sparingly; prefer setting visibility_level=2 to
        hide bad data while preserving audit trail."""
        cursor = self._conn.execute(
            "DELETE FROM coop_experiences WHERE coop_id = ?", (coop_id,),
        )
        if cursor.rowcount == 0:
            raise CoopNotFound(coop_id)

    # === Read ===

    def get(self, coop_id: str) -> CoopExperience:
        row = self._conn.execute(
            "SELECT * FROM coop_experiences WHERE coop_id = ?", (coop_id,),
        ).fetchone()
        if row is None:
            raise CoopNotFound(coop_id)
        return self._row_to_coop(row)

    def exists(self, coop_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM coop_experiences WHERE coop_id = ?", (coop_id,),
        ).fetchone() is not None

    def list_all(self) -> list[CoopExperience]:
        """Admin / analytics view; bypasses visibility tiers."""
        rows = self._conn.execute(
            "SELECT * FROM coop_experiences ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_coop(r) for r in rows]

    def list_seed(self) -> list[CoopExperience]:
        rows = self._conn.execute(
            "SELECT * FROM coop_experiences WHERE is_seed_data = 1 "
            "ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_coop(r) for r in rows]

    def list_visible_to_user(self, user_id: str) -> list[CoopExperience]:
        """Visibility-aware list: returns only rows whose visibility_level
        is <= the user's contribution_count. PLAN §6.4 give-to-get gate.

        Unknown user (never logged in) sees only level-0 rows.
        """
        contribution_count = self._get_contribution_count(user_id)
        rows = self._conn.execute(
            "SELECT * FROM coop_experiences "
            "WHERE visibility_level <= ? "
            "ORDER BY created_at DESC",
            (contribution_count,),
        ).fetchall()
        return [self._row_to_coop(r) for r in rows]

    def list_by_company(self, company: str) -> list[CoopExperience]:
        rows = self._conn.execute(
            "SELECT * FROM coop_experiences WHERE company = ? COLLATE NOCASE "
            "ORDER BY created_at DESC",
            (company,),
        ).fetchall()
        return [self._row_to_coop(r) for r in rows]

    def list_by_industry(self, industry: Industry) -> list[CoopExperience]:
        rows = self._conn.execute(
            "SELECT * FROM coop_experiences WHERE industry = ? "
            "ORDER BY created_at DESC",
            (industry.value,),
        ).fetchall()
        return [self._row_to_coop(r) for r in rows]

    def count_by_industry(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT COALESCE(industry, 'unknown') AS ind, COUNT(*) AS n "
            "FROM coop_experiences GROUP BY ind"
        ).fetchall()
        return {r["ind"]: r["n"] for r in rows}

    def count_by_visibility(self) -> dict[int, int]:
        rows = self._conn.execute(
            "SELECT visibility_level, COUNT(*) AS n "
            "FROM coop_experiences GROUP BY visibility_level"
        ).fetchall()
        return {r["visibility_level"]: r["n"] for r in rows}

    # === Internal ===

    def _get_contribution_count(self, user_id: str) -> int:
        row = self._conn.execute(
            "SELECT contribution_count FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return int(row["contribution_count"]) if row else 0

    @staticmethod
    def _params(coop: CoopExperience) -> tuple:
        return (
            coop.coop_id,
            coop.company,
            coop.role,
            coop.industry.value if coop.industry else None,
            coop.coop_term,
            coop.duration_months,
            json.dumps(coop.related_courses),
            coop.interview_summary,
            coop.technical_questions,
            coop.salary_range_usd,
            coop.contributor_user_id,
            int(coop.is_seed_data),
            coop.visibility_level,
            coop.redaction_audit,
        )

    @staticmethod
    def _row_to_coop(row: sqlite3.Row) -> CoopExperience:
        return CoopExperience.model_validate(
            {
                "coop_id": row["coop_id"],
                "company": row["company"],
                "role": row["role"],
                "industry": row["industry"],
                "coop_term": row["coop_term"],
                "duration_months": row["duration_months"],
                "related_courses": json.loads(row["related_courses"]) if row["related_courses"] else [],
                "interview_summary": row["interview_summary"],
                "technical_questions": row["technical_questions"],
                "salary_range_usd": row["salary_range_usd"],
                "contributor_user_id": row["contributor_user_id"],
                "is_seed_data": bool(row["is_seed_data"]),
                "visibility_level": row["visibility_level"],
                "redaction_audit": row["redaction_audit"],
                "created_at": row["created_at"],
            }
        )
