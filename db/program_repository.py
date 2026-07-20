"""ProgramRepository — Pydantic Program <-> SQLite programs / required_courses
/ prerequisites tables (PLAN v3.0 Layer 3).

The repository is read-mostly at runtime: `list_required_courses(program_id,
semester=N)` powers the chat route's program-aware shortcut for queries
like "我是 AAI 专业，第一学期选啥". Writes happen in seed scripts only.

该仓储在运行时以读为主:`list_required_courses(program_id, semester=N)`
支撑聊天路由中"按专业感知"的捷径查询,例如"我是 AAI 专业,第一学期选啥"。
写操作只发生在 seed(数据播种)脚本中。

ADR-0013 stays in force — these are derived rows that link courses to a
program ontology; the courses themselves remain authoritative in `courses`.

ADR-0013 仍然生效 —— 这里的行是把课程与专业本体(ontology)关联起来的
派生数据;课程本身的权威数据仍然在 `courses` 表中。
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
    """Raised when a program_id is expected to exist but doesn't.

    中文:当某个 program_id 预期应该存在、但实际查无此记录时抛出。
    """


class ProgramRepository:
    """Caller owns the connection lifecycle; route layer commits.

    中文:连接(connection)的生命周期由调用方负责;commit 由路由层完成,
    本类自身从不提交事务。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # === Programs ===
    # 中文:专业(Program)相关操作

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
        """Idempotent insert keyed on program_id — handy for re-runnable seeds.

        中文:以 program_id 为键的幂等插入 —— 方便可重复运行的 seed 脚本。
        """
        # ON CONFLICT strategy: full overwrite via excluded.* on every column.
        # Unlike CourseRepository.upsert there's no "preserve if not
        # re-supplied" column here — seed files always carry the complete
        # program record, so a straight overwrite is safe.
        # 中文:ON CONFLICT 策略 —— 每一列都用 excluded.* 完整覆盖。和
        # CourseRepository.upsert 不同,这里没有"本次未提供就保留旧值"的
        # 列 —— seed 文件总是携带完整的 program 记录,直接整体覆盖是安全的。
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
        to plain prefix-filtered retrieval (Layer 2 path).

        中文:把提取出的前缀(如 'AAI')映射到某个 program。若该前缀没有
        任何 program 被 seed 过,返回 None —— 此时调用方应退回到纯前缀
        过滤的检索方式(Layer 2 路径)。
        """
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
    # 中文:必修课程(专业 -> 课程 的边)

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
        # ON CONFLICT strategy: keyed on (program_id, course_id); only the
        # annotation columns (requirement_type, semester_recommended, notes)
        # are overwritten — there's no separate identity column left to
        # preserve, the composite key IS the identity.
        # 中文:ON CONFLICT 策略 —— 以 (program_id, course_id) 为键;只覆盖
        # 注解类的列(requirement_type、semester_recommended、notes),
        # 没有另外需要保留的身份列 —— 这个复合键本身就是身份标识。
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

        中文:按学期(semester,1 = 第一学期,2 = 第二学期,……)和/或
        requirement_type 过滤。两者都为 None 时表示返回整个专业。

        结果排序:按 requirement_type('foundation' < 'core' < ...)排序
        只是个粗略的想法,但在这一层强制执行会把 UI 层的关注点搅进数据层。
        所以这里改为按 (semester, course_id) 排序,让路由层拿到稳定、
        可读的输出。
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

    def list_programs_for_course(
        self, course_id: str,
    ) -> list[tuple[Program, ProgramRequiredCourse]]:
        """Reverse lookup: every program that lists `course_id` in its
        curriculum, with the edge annotation (requirement_type / semester).
        Powers the course-detail panel's "where does this course fit"
        block. One JOIN, ordered by program_id for stable UI output.

        中文:反向查找 —— 找出所有课程表中包含 `course_id` 的 program,
        并附带边上的注解(requirement_type / semester)。用于支撑课程详情
        面板里"这门课在专业里处于什么位置"的板块。一次 JOIN 搞定,按
        program_id 排序以保证 UI 输出稳定。
        """
        rows = self._conn.execute(
            """
            SELECT p.program_id, p.full_name, p.prefix, p.department,
                   p.college, p.notes,
                   e.course_id, e.requirement_type, e.semester_recommended,
                   e.notes AS edge_notes
            FROM program_required_courses e
            JOIN programs p ON p.program_id = e.program_id
            WHERE e.course_id = ?
            ORDER BY p.program_id
            """,
            (course_id,),
        ).fetchall()
        out: list[tuple[Program, ProgramRequiredCourse]] = []
        for r in rows:
            program = Program(
                program_id=r["program_id"], full_name=r["full_name"],
                prefix=r["prefix"], department=r["department"],
                college=r["college"], notes=r["notes"],
            )
            edge = ProgramRequiredCourse(
                program_id=r["program_id"], course_id=r["course_id"],
                requirement_type=r["requirement_type"],
                semester_recommended=r["semester_recommended"],
                notes=r["edge_notes"],
            )
            out.append((program, edge))
        return out

    # === Prerequisites (course -> course edges) ===
    # 中文:先修课(课程 -> 课程 的边)

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
        # ON CONFLICT strategy: keyed on (course_id, prereq_course_id); only
        # requirement/notes are overwritten, mirroring upsert_required_course.
        # 中文:ON CONFLICT 策略 —— 以 (course_id, prereq_course_id) 为键;
        # 只覆盖 requirement/notes,与上面的 upsert_required_course 同构。
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
