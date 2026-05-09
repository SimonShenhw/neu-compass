"""ProgramRepository — Pydantic Program <-> SQLite programs / required_courses
/ prerequisites tables (PLAN v3.0 Layer 3).

The repository is read-mostly at runtime: `list_required_courses(program_id,
semester=N)` powers the chat route's program-aware shortcut for queries
like "我是 AAI 专业，第一学期选啥". Writes happen in seed scripts only.

ADR-0013 stays in force — these are derived rows that link courses to a
program ontology; the courses themselves remain authoritative in `courses`.
"""

from __future__ import annotations

import sqlite3

from schemas.program import (
    CoursePrerequisite,
    Program,
    ProgramRequiredCourse,
    RequirementType,
)


class ProgramNotFound(LookupError):
    """Raised when a program_id is expected to exist but doesn't."""


class ProgramRepository:
    """Caller owns the connection lifecycle; route layer commits."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # === Programs ===

    def add_program(self, program: Program) -> None:
        self._conn.execute(
            """
            INSERT INTO programs (program_id, full_name, prefix, department, college, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (program.program_id, program.full_name, program.prefix,
             program.department, program.college, program.notes),
        )

    def upsert_program(self, program: Program) -> None:
        """Idempotent insert keyed on program_id — handy for re-runnable seeds."""
        self._conn.execute(
            """
            INSERT INTO programs (program_id, full_name, prefix, department, college, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(program_id) DO UPDATE SET
                full_name = excluded.full_name,
                prefix = excluded.prefix,
                department = excluded.department,
                college = excluded.college,
                notes = excluded.notes
            """,
            (program.program_id, program.full_name, program.prefix,
             program.department, program.college, program.notes),
        )

    def get_program(self, program_id: str) -> Program:
        row = self._conn.execute(
            "SELECT program_id, full_name, prefix, department, college, notes "
            "FROM programs WHERE program_id = ?",
            (program_id,),
        ).fetchone()
        if row is None:
            raise ProgramNotFound(program_id)
        return Program(**dict(row))

    def find_by_prefix(self, prefix: str) -> Program | None:
        """Map an extracted prefix (e.g. 'AAI') to a program. Returns None
        when no program is seeded for that prefix — caller should fall back
        to plain prefix-filtered retrieval (Layer 2 path)."""
        row = self._conn.execute(
            "SELECT program_id, full_name, prefix, department, college, notes "
            "FROM programs WHERE prefix = ? COLLATE NOCASE LIMIT 1",
            (prefix,),
        ).fetchone()
        return Program(**dict(row)) if row else None

    def list_programs(self) -> list[Program]:
        rows = self._conn.execute(
            "SELECT program_id, full_name, prefix, department, college, notes "
            "FROM programs ORDER BY program_id"
        ).fetchall()
        return [Program(**dict(r)) for r in rows]

    # === Required courses (program -> course edges) ===

    def add_required_course(self, edge: ProgramRequiredCourse) -> None:
        self._conn.execute(
            """
            INSERT INTO program_required_courses
                (program_id, course_id, requirement_type, semester_recommended, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (edge.program_id, edge.course_id, edge.requirement_type,
             edge.semester_recommended, edge.notes),
        )

    def upsert_required_course(self, edge: ProgramRequiredCourse) -> None:
        self._conn.execute(
            """
            INSERT INTO program_required_courses
                (program_id, course_id, requirement_type, semester_recommended, notes)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(program_id, course_id) DO UPDATE SET
                requirement_type = excluded.requirement_type,
                semester_recommended = excluded.semester_recommended,
                notes = excluded.notes
            """,
            (edge.program_id, edge.course_id, edge.requirement_type,
             edge.semester_recommended, edge.notes),
        )

    def list_required_courses(
        self,
        program_id: str,
        *,
        semester: int | None = None,
        requirement_type: RequirementType | None = None,
    ) -> list[ProgramRequiredCourse]:
        """Filter by semester (1 = first, 2 = second, ...) and/or requirement
        type. Both None = whole program.

        Result order: requirement_type ('foundation' < 'core' < ...) is
        coarse, but enforcing it here would smear UI concerns into the data
        layer. We sort by (semester, course_id) so the route gets stable,
        readable output.
        """
        clauses = ["program_id = ?"]
        params: list[object] = [program_id]
        if semester is not None:
            clauses.append("semester_recommended = ?")
            params.append(semester)
        if requirement_type is not None:
            clauses.append("requirement_type = ?")
            params.append(requirement_type)

        sql = (
            "SELECT program_id, course_id, requirement_type, "
            "semester_recommended, notes FROM program_required_courses "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY semester_recommended IS NULL, semester_recommended, course_id"
        )
        rows = self._conn.execute(sql, params).fetchall()
        return [ProgramRequiredCourse(**dict(r)) for r in rows]

    # === Prerequisites (course -> course edges) ===

    def add_prerequisite(self, edge: CoursePrerequisite) -> None:
        self._conn.execute(
            """
            INSERT INTO course_prerequisites
                (course_id, prereq_course_id, requirement, notes)
            VALUES (?, ?, ?, ?)
            """,
            (edge.course_id, edge.prereq_course_id, edge.requirement, edge.notes),
        )

    def upsert_prerequisite(self, edge: CoursePrerequisite) -> None:
        self._conn.execute(
            """
            INSERT INTO course_prerequisites
                (course_id, prereq_course_id, requirement, notes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(course_id, prereq_course_id) DO UPDATE SET
                requirement = excluded.requirement,
                notes = excluded.notes
            """,
            (edge.course_id, edge.prereq_course_id, edge.requirement, edge.notes),
        )

    def list_prerequisites(self, course_id: str) -> list[CoursePrerequisite]:
        rows = self._conn.execute(
            "SELECT course_id, prereq_course_id, requirement, notes "
            "FROM course_prerequisites WHERE course_id = ? "
            "ORDER BY prereq_course_id",
            (course_id,),
        ).fetchall()
        return [CoursePrerequisite(**dict(r)) for r in rows]


__all__ = ["ProgramNotFound", "ProgramRepository"]
