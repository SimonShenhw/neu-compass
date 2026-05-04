"""UserRepository — Pydantic User <-> SQLite users table.

Mirrors CourseRepository pattern. Caller owns the connection.

Key method: `upsert_login()` is the single entry point the OAuth callback
uses. It either creates the row (first login) or just stamps last_login_at
+ refreshes display_name. Email/domain are required; we trust the OAuth
layer (app/auth.py) to have already vetted them against the whitelist
before calling this.

contribution_count is NOT touched by upsert_login — it's modified by
increment_contribution_count() when the user submits a Co-op record
(PLAN §6.4 give-to-get gate).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from schemas.user import User


class UserNotFound(LookupError):
    """Raised when a user_id is expected to exist but doesn't."""


class UserRepository:
    """Pydantic User <-> SQLite users table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # === Read ===

    def get(self, user_id: str) -> User | None:
        row = self._conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,),
        ).fetchone()
        return self._row_to_user(row) if row else None

    def get_by_email(self, email: str) -> User | None:
        row = self._conn.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,),
        ).fetchone()
        return self._row_to_user(row) if row else None

    def exists(self, user_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM users WHERE user_id = ?", (user_id,),
        ).fetchone() is not None

    def count(self) -> int:
        return int(
            self._conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        )

    # === Write ===

    def upsert_login(
        self,
        *,
        user_id: str,
        email: str,
        domain: str,
        display_name: str | None = None,
    ) -> User:
        """Create the user row on first login OR refresh last_login_at +
        display_name on subsequent logins. Returns the persisted User.

        Caller is responsible for domain whitelist enforcement (see
        app.auth.is_email_allowed) BEFORE calling this — the repo trusts
        what it gets.
        """
        self._conn.execute(
            """
            INSERT INTO users (
                user_id, email, domain, display_name, last_login_at
            ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                email         = excluded.email,
                domain        = excluded.domain,
                display_name  = COALESCE(excluded.display_name, users.display_name),
                last_login_at = CURRENT_TIMESTAMP
            """,
            (user_id, email, domain, display_name),
        )
        out = self.get(user_id)
        if out is None:
            # Race / DB bug — surface loudly rather than return None
            raise UserNotFound(user_id)
        return out

    def increment_contribution_count(self, user_id: str) -> int:
        """+1 to contribution_count. Returns the new value.

        Used after a successful Co-op upload (PLAN §6.4 give-to-get gate).
        """
        cur = self._conn.execute(
            "UPDATE users SET contribution_count = contribution_count + 1 "
            "WHERE user_id = ?",
            (user_id,),
        )
        if cur.rowcount == 0:
            raise UserNotFound(user_id)
        row = self._conn.execute(
            "SELECT contribution_count FROM users WHERE user_id = ?", (user_id,),
        ).fetchone()
        return int(row["contribution_count"])

    def delete(self, user_id: str) -> None:
        """Hard delete (cascades to user_unlocks via FK). Reserve for true
        cleanup — for retention, prefer leaving the row + scrubbing PII fields."""
        cur = self._conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        if cur.rowcount == 0:
            raise UserNotFound(user_id)

    # === Internal ===

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> User:
        return User.model_validate(
            {
                "user_id": row["user_id"],
                "email": row["email"],
                "domain": row["domain"],
                "display_name": row["display_name"],
                "contribution_count": row["contribution_count"],
                "created_at": row["created_at"],
                "last_login_at": row["last_login_at"],
            }
        )


__all__ = ["UserNotFound", "UserRepository"]
