"""AliasRepository — Pydantic Alias <-> SQLite course_aliases table.

Mirrors CourseRepository semantics: caller owns the connection and
manages commits. Constructor takes an open sqlite3.Connection.

Insertion comes in two flavors:
  add()         strict — duplicate (alias_text, alias_type, primary_course_id)
                raises sqlite3.IntegrityError per the UNIQUE index
  add_or_skip() idempotent — INSERT OR IGNORE, returns None on dup

Review workflow (PLAN §1.4 / §3 LLM alias detector):
  L3 LLM inferences land via add() with review_status='pending';
  human curator drains the queue via list_pending() + update_review_status().

Resolution (Week 4 query normalizer):
  resolve(term) goes through v_course_lookup view (approved aliases +
  primary codes only). For pending review, use list_pending() instead.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from schemas.alias import Alias, AliasReviewStatus


class AliasNotFound(LookupError):
    """Raised when an alias_id is expected to exist but doesn't."""


class AliasRepository:
    """Pydantic Alias <-> SQLite course_aliases. Caller owns the connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # === Write ===

    def add(self, alias: Alias) -> int:
        """Insert a new alias. Returns the assigned alias_id.

        Raises sqlite3.IntegrityError on:
          - duplicate (alias_text, alias_type, primary_course_id)
          - missing primary_course_id (FK violation)
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
        """Bulk insert. Returns count actually inserted (excludes skipped duplicates)."""
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
        """
        cursor = self._conn.execute(
            "UPDATE course_aliases SET review_status = ? WHERE alias_id = ?",
            (new_status.value, alias_id),
        )
        if cursor.rowcount == 0:
            raise AliasNotFound(alias_id)

    def delete(self, alias_id: int) -> None:
        """Hard delete. Prefer update_review_status('rejected') for audit trails;
        delete is for genuine cleanup (typo, accidental insert)."""
        cursor = self._conn.execute(
            "DELETE FROM course_aliases WHERE alias_id = ?", (alias_id,)
        )
        if cursor.rowcount == 0:
            raise AliasNotFound(alias_id)

    # === Read ===

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
        """Case-insensitive lookup (column has COLLATE NOCASE)."""
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
        """LLM-inferred aliases awaiting human review. Used by the review UI."""
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
        """
        rows = self._conn.execute(
            "SELECT DISTINCT course_id FROM v_course_lookup "
            "WHERE searchable_term = ? COLLATE NOCASE",
            (term,),
        ).fetchall()
        return [r["course_id"] for r in rows]

    # === Internal ===

    @staticmethod
    def _params(alias: Alias) -> tuple:
        """Build the 9-element parameter tuple for INSERT."""
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
