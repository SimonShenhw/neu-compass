"""CourseRepository — Pydantic Course <-> SQLite courses table.

Per ADR-0013, SQLite is the source of truth. Inserts always set status='pending';
the embed pipeline calls mark_indexed() after FAISS write succeeds.

据 ADR-0013,SQLite 是唯一事实来源(source of truth)。插入时一律把 status
设为 'pending';嵌入(embed)流水线会在 FAISS 写入成功后调用 mark_indexed()。

The metadata column duplicates the L1 hard fields from the full Course dump
(stored in generated_json) so SQLite JSON1 indexes can serve hot-path filter
queries — see db/init.sql idx_courses_term / idx_courses_credits.

metadata 列复制了完整 Course dump(存于 generated_json)中的 L1 硬字段,
这样 SQLite 的 JSON1 索引就能服务高频过滤查询 —— 参见 db/init.sql 中的
idx_courses_term / idx_courses_credits。
"""

from __future__ import annotations

import json
import sqlite3

from schemas.course import Course


class CourseNotFound(LookupError):
    """Raised when a course_id is expected to exist but doesn't.

    中文:当某个 course_id 预期应该存在、但实际查无此记录时抛出。
    """


class CourseRepository:
    """Pydantic Course <-> SQLite. Caller owns the connection lifecycle.

    中文:Pydantic 的 Course 对象与 SQLite 之间的映射层。连接(connection)
    的生命周期(何时 commit/rollback/close)由调用方负责,本类自己不管。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # === Write ===
    # 中文:写操作

    def insert(self, course: Course, *, raw_text: str | None = None) -> None:
        """Insert a new course with status='pending'.

        Raises sqlite3.IntegrityError if course_id already exists; use upsert()
        for idempotent writes.

        中文:插入一门新课程,status 设为 'pending'。
        若 course_id 已存在会抛出 sqlite3.IntegrityError;需要幂等写入
        请改用 upsert()。
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

        中文:按 course_id 插入或更新。status 会被重置为 'pending'、
        indexed_at 清空 —— 因为内容变了,原有的 FAISS 向量已经过期失效。
        若本次调用没有再传 raw_text,则保留旧值(用 COALESCE 兜底)。
        """
        metadata, generated = self._serialize(course)
        # ON CONFLICT strategy: every column is overwritten by `excluded.*`
        # EXCEPT raw_text (COALESCE keeps the existing row's value when a new
        # one isn't supplied this call) — status/indexed_at are force-reset to
        # 'pending'/NULL so a stale FAISS embedding is never silently left
        # marked 'indexed'.
        # 中文:ON CONFLICT 策略 —— 除 raw_text 外的所有列都被 excluded.*
        # 覆盖(raw_text 在本次未提供新值时,用 COALESCE 保留该行的旧值);
        # status/indexed_at 被强制重置为 'pending'/NULL,确保过期的 FAISS
        # 向量绝不会被悄悄地继续标记成 'indexed'。
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

        中文:把状态从 pending 转为 indexed,在 FAISS 写入成功后调用。
        严格校验:若当前 status 不是 'pending' 则抛出 ValueError —— 用来
        抓"重复标记"之类的 bug 以及 FAISS 重试的边界情况;拿不准的话,
        调用方应先自行调用 get_status() 确认。
        """
        self._transition(course_id, expected_from="pending", to="indexed", set_indexed_at=True)

    def mark_failed(self, course_id: str) -> None:
        """Transition pending -> failed (giving up on this row).

        中文:把状态从 pending 转为 failed(放弃这一行,不再重试)。
        """
        self._transition(course_id, expected_from="pending", to="failed")

    def reset_to_pending(self, course_id: str) -> None:
        """Reset failed -> pending for manual retry.

        中文:把状态从 failed 重置回 pending,供人工手动重试。
        """
        self._transition(course_id, expected_from="failed", to="pending")

    # === Read ===
    # 中文:读操作

    def get(self, course_id: str) -> Course:
        row = self._conn.execute(
            "SELECT generated_json FROM courses WHERE course_id = ?",
            (course_id,),
        ).fetchone()
        if row is None:
            raise CourseNotFound(course_id)
        return Course.model_validate_json(row["generated_json"])

    def get_batch(self, course_ids: list[str]) -> dict[str, Course]:
        """Fetch multiple courses in a single SQL round-trip.

        Returns {course_id: Course} for IDs that exist; missing IDs are
        silently omitted (callers decide whether to error or skip).
        Used by HybridRetriever.search to avoid N+1 — fetching k=20 hits
        as 20 individual SELECTs adds noticeable latency under load.

        Empty input → empty dict (no SQL query).

        中文:一次 SQL 往返取回多门课程。
        返回 {course_id: Course},只包含实际存在的 ID;缺失的 ID 被静默
        忽略(是报错还是跳过,由调用方自行决定)。HybridRetriever.search
        用它来避免 N+1 查询 —— 取 k=20 个命中结果如果发 20 条独立
        SELECT,在负载下延迟会明显变差。
        输入为空 → 直接返回空字典(不发 SQL 查询)。
        """
        if not course_ids:
            return {}
        # Placeholders are static `?` markers (one per id) — values bound via
        # params, not interpolated. This is safe.
        # 中文:占位符是静态的 `?` 标记(每个 id 一个)—— 实际值通过 params
        # 参数绑定传入,而非字符串拼接,因此是安全的。
        placeholders = ",".join("?" * len(course_ids))
        rows = self._conn.execute(
            f"SELECT generated_json FROM courses WHERE course_id IN ({placeholders})",
            list(course_ids),
        ).fetchall()
        out: dict[str, Course] = {}
        for row in rows:
            course = Course.model_validate_json(row["generated_json"])
            out[course.course_id] = course
        return out

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

        中文:按规范代码查找(大小写不敏感)。找不到时返回 None。
        注意:这里只匹配 primary_code 列,不查 alias(别名)表。
        需要感知别名的查找,请直接查 v_course_lookup 视图。
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
    # 中文:内部实现细节

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
        # 中文:更新影响 0 行:要么课程不存在,要么 status 对不上。这里
        # 特意区分开、给出有用的错误信息 —— 反面例子是静默地什么也不做,
        # 那样会把嵌入流水线里的真实 bug 盖住。
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

        中文:构造用于落库的 (metadata_json, generated_json) 二元组。
        metadata:只含 L1 硬字段,对应 db/init.sql 里
        idx_courses_term / idx_courses_credits 索引的预期。
        generated_json:完整的 Pydantic dump,包含所有软字段 + evidence。
        """
        metadata = {
            "term": course.term,
            "credits": course.credits,
            "professor": course.professor,
            "prereqs": course.prereqs,
            "delivery_mode": course.delivery_mode.value if course.delivery_mode else None,
        }
        return json.dumps(metadata), course.model_dump_json()
