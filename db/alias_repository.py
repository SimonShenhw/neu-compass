"""AliasRepository — Pydantic Alias <-> SQLite course_aliases table.

Mirrors CourseRepository semantics: caller owns the connection and
manages commits. Constructor takes an open sqlite3.Connection.

语义与 CourseRepository 一致:连接(connection)由调用方持有、commit 也由
调用方负责。构造函数接受一个已打开的 sqlite3.Connection。

Insertion comes in two flavors:
  add()         strict — duplicate (alias_text, alias_type, primary_course_id)
                raises sqlite3.IntegrityError per the UNIQUE index
  add_or_skip() idempotent — INSERT OR IGNORE, returns None on dup

插入有两种形态:
  add()         严格版 —— (alias_text, alias_type, primary_course_id) 重复时,
                按 UNIQUE 索引的约束抛出 sqlite3.IntegrityError
  add_or_skip() 幂等版 —— INSERT OR IGNORE,重复时返回 None

Review workflow (PLAN §1.4 / §3 LLM alias detector):
  L3 LLM inferences land via add() with review_status='pending';
  human curator drains the queue via list_pending() + update_review_status().

审核流程(PLAN §1.4 / §3 LLM 别名检测器):
  L3 层 LLM 推断出的别名通过 add() 写入,review_status 为 'pending';
  人工审核员通过 list_pending() + update_review_status() 清空待审队列。

Resolution (Week 4 query normalizer):
  resolve(term) goes through v_course_lookup view (approved aliases +
  primary codes only). For pending review, use list_pending() instead.

解析(第 4 周查询归一化器):
  resolve(term) 走 v_course_lookup 视图(只包含已批准的别名 + 规范代码)。
  想看待审核的内容,请改用 list_pending()。
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from schemas.alias import Alias, AliasReviewStatus


class AliasNotFound(LookupError):
    """Raised when an alias_id is expected to exist but doesn't.

    中文:当某个 alias_id 预期应该存在、但实际查无此记录时抛出。
    """


class AliasRepository:
    """Pydantic Alias <-> SQLite course_aliases. Caller owns the connection.

    中文:Pydantic 的 Alias 对象与 SQLite course_aliases 表之间的映射层。
    连接(connection)的生命周期(创建、commit、close)由调用方负责,
    本类从不自行提交或关闭连接。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # === Write ===
    # 中文:写操作

    def add(self, alias: Alias) -> int:
        """Insert a new alias. Returns the assigned alias_id.

        Raises sqlite3.IntegrityError on:
          - duplicate (alias_text, alias_type, primary_course_id)
          - missing primary_course_id (FK violation)

        中文:插入一条新别名。返回分配到的 alias_id。
        以下情况会抛出 sqlite3.IntegrityError:
          - (alias_text, alias_type, primary_course_id) 重复
          - primary_course_id 不存在(外键违规)
        """
        cursor = self._conn.execute(
            """
            INSERT INTO course_aliases
                (alias_text, alias_type, primary_course_id, confidence,
                 valid_from, valid_until, source, review_status, evidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._params(alias),
        )
        return int(cursor.lastrowid)  # type: ignore[arg-type]

    def add_or_skip(self, alias: Alias) -> int | None:
        """Insert if not present; skip silently on duplicate. Returns alias_id
        if inserted, None if skipped.

        Use for idempotent batch loads (manual L2 alias entry, seed scripts).
        Note: this still raises IntegrityError if primary_course_id FK is bad —
        only the UNIQUE index constraint is treated as ignorable.

        中文:不存在则插入;重复则静默跳过。插入成功返回 alias_id,
        跳过则返回 None。

        用于幂等的批量加载(手工录入 L2 别名、seed 脚本)。注意:若
        primary_course_id 外键无效,这里仍然会抛出 IntegrityError ——
        只有 UNIQUE 索引的冲突才被当作可忽略。
        """
        cursor = self._conn.execute(
            """
            INSERT OR IGNORE INTO course_aliases
                (alias_text, alias_type, primary_course_id, confidence,
                 valid_from, valid_until, source, review_status, evidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._params(alias),
        )
        return int(cursor.lastrowid) if cursor.rowcount > 0 else None

    def add_many(self, aliases: list[Alias], *, skip_duplicates: bool = True) -> int:
        """Bulk insert. Returns count actually inserted (excludes skipped duplicates).

        中文:批量插入。返回实际插入的条数(不含被跳过的重复项)。
        """
        method = self.add_or_skip if skip_duplicates else self.add
        inserted = 0
        for alias in aliases:
            result = method(alias)
            if result is not None:
                inserted += 1
        return inserted

    def update_review_status(
        self,
        alias_id: int,
        new_status: AliasReviewStatus,
    ) -> None:
        """Transition pending -> approved/rejected (LLM alias review queue).

        Strict: only updates if the row exists. Raises AliasNotFound otherwise.
        Caller may freely transition between any states; we don't enforce a
        specific FSM here because rejection-then-approval is a valid pattern
        (curator changes mind; new evidence appears).

        中文:把状态从 pending 转为 approved/rejected(LLM 别名审核队列)。
        严格校验:只有行确实存在才会更新,否则抛出 AliasNotFound。
        调用方可以在任意状态间自由转换;这里不强制某个具体的有限状态机
        (FSM),因为"先拒绝、后又批准"是合法场景(审核员改变主意,
        或出现了新证据)。
        """
        cursor = self._conn.execute(
            "UPDATE course_aliases SET review_status = ? WHERE alias_id = ?",
            (new_status.value, alias_id),
        )
        if cursor.rowcount == 0:
            raise AliasNotFound(alias_id)

    def delete(self, alias_id: int) -> None:
        """Hard delete. Prefer update_review_status('rejected') for audit trails;
        delete is for genuine cleanup (typo, accidental insert).

        中文:硬删除。若需要保留审计记录,请优先用
        update_review_status('rejected');delete 只用于真正的清理场景
        (录入笔误、误操作插入)。
        """
        cursor = self._conn.execute(
            "DELETE FROM course_aliases WHERE alias_id = ?", (alias_id,)
        )
        if cursor.rowcount == 0:
            raise AliasNotFound(alias_id)

    # === Read ===
    # 中文:读操作

    def get(self, alias_id: int) -> Alias:
        row = self._conn.execute(
            "SELECT * FROM course_aliases WHERE alias_id = ?", (alias_id,)
        ).fetchone()
        if row is None:
            raise AliasNotFound(alias_id)
        return self._row_to_alias(row)

    def exists(self, alias_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM course_aliases WHERE alias_id = ?", (alias_id,)
        ).fetchone()
        return row is not None

    def find_by_text(self, alias_text: str) -> list[Alias]:
        """Case-insensitive lookup (column has COLLATE NOCASE).

        中文:大小写不敏感的查找(该列定义了 COLLATE NOCASE)。
        """
        rows = self._conn.execute(
            "SELECT * FROM course_aliases WHERE alias_text = ? COLLATE NOCASE",
            (alias_text,),
        ).fetchall()
        return [self._row_to_alias(r) for r in rows]

    def list_by_course(self, primary_course_id: str) -> list[Alias]:
        rows = self._conn.execute(
            "SELECT * FROM course_aliases WHERE primary_course_id = ? "
            "ORDER BY alias_type, alias_text",
            (primary_course_id,),
        ).fetchall()
        return [self._row_to_alias(r) for r in rows]

    def list_by_status(
        self, status: AliasReviewStatus, *, limit: int | None = None,
    ) -> list[Alias]:
        sql = (
            "SELECT * FROM course_aliases WHERE review_status = ? "
            "ORDER BY created_at"
        )
        params: list = [status.value]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_alias(r) for r in rows]

    def list_pending(self, *, limit: int | None = None) -> list[Alias]:
        """LLM-inferred aliases awaiting human review. Used by the review UI.

        中文:等待人工审核的 LLM 推断别名。供审核界面(review UI)使用。
        """
        return self.list_by_status(AliasReviewStatus.PENDING, limit=limit)

    def count_by_status(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT review_status, COUNT(*) AS n FROM course_aliases GROUP BY review_status"
        ).fetchall()
        return {r["review_status"]: r["n"] for r in rows}

    def resolve(self, term: str) -> list[str]:
        """Resolve a free-form term to one or more course_ids.

        Walks v_course_lookup view, which unions primary_codes + approved aliases.
        Pending aliases are excluded. Case-insensitive (COLLATE NOCASE on
        alias_text + primary_code).

        中文:把一个自由文本的词语解析为一个或多个 course_id。
        查的是 v_course_lookup 视图,它是 primary_code 与已批准别名的并集。
        待审核的别名不包含在内。大小写不敏感(alias_text + primary_code
        都定义了 COLLATE NOCASE)。
        """
        rows = self._conn.execute(
            "SELECT DISTINCT course_id FROM v_course_lookup "
            "WHERE searchable_term = ? COLLATE NOCASE",
            (term,),
        ).fetchall()
        return [r["course_id"] for r in rows]

    # === Internal ===
    # 中文:内部实现细节

    @staticmethod
    def _params(alias: Alias) -> tuple:
        """Build the 9-element parameter tuple for INSERT.

        中文:为 INSERT 语句构造 9 个元素的参数元组。
        """
        return (
            alias.alias_text,
            alias.alias_type.value,
            alias.primary_course_id,
            alias.confidence,
            alias.valid_from.isoformat() if alias.valid_from else None,
            alias.valid_until.isoformat() if alias.valid_until else None,
            alias.source.value,
            alias.review_status.value,
            alias.evidence,
        )

    @staticmethod
    def _row_to_alias(row: sqlite3.Row) -> Alias:
        """Hydrate an Alias from a sqlite3.Row.

        Pydantic handles the str->date / str->datetime parsing automatically
        for the date / datetime fields.

        中文:把 sqlite3.Row 还原(hydrate)成 Alias 对象。
        date / datetime 字段的 str->date、str->datetime 解析由 Pydantic
        自动完成。
        """
        return Alias.model_validate(
            {
                "alias_id": row["alias_id"],
                "alias_text": row["alias_text"],
                "alias_type": row["alias_type"],
                "primary_course_id": row["primary_course_id"],
                "confidence": row["confidence"],
                "valid_from": row["valid_from"],
                "valid_until": row["valid_until"],
                "source": row["source"],
                "review_status": row["review_status"],
                "evidence": row["evidence"],
                "created_at": row["created_at"],
            }
        )
