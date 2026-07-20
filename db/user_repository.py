"""UserRepository — Pydantic User <-> SQLite users table.

Mirrors CourseRepository pattern. Caller owns the connection.

模式与 CourseRepository 一致(镜像其写法)。连接(connection)由调用方持有
和管理。

Key method: `upsert_login()` is the single entry point the OAuth callback
uses. It either creates the row (first login) or just stamps last_login_at
+ refreshes display_name. Email/domain are required; we trust the OAuth
layer (app/auth.py) to have already vetted them against the whitelist
before calling this.

关键方法:`upsert_login()` 是 OAuth 回调唯一的入口。它要么新建这一行
(首次登录),要么只是刷新 last_login_at + display_name(后续登录)。
email/domain 是必填的;这里信任 OAuth 层(app/auth.py)在调用本方法前
已经用白名单校验过它们。

contribution_count is NOT touched by upsert_login — it's modified by
increment_contribution_count() when the user submits a Co-op record
(PLAN §6.4 give-to-get gate).

contribution_count 不会被 upsert_login 触碰 —— 它只在用户提交 Co-op
记录时,由 increment_contribution_count() 修改(对应 PLAN §6.4
"贡献换权限" / give-to-get 门槛机制)。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from schemas.user import User


class UserNotFound(LookupError):
    """Raised when a user_id is expected to exist but doesn't.

    中文:当某个 user_id 预期应该存在、但实际查无此记录时抛出。
    """


class UserRepository:
    """Pydantic User <-> SQLite users table.

    中文:Pydantic 的 User 对象与 SQLite users 表之间的映射层。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # === Read ===
    # 中文:读操作

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
    # 中文:写操作

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

        中文:首次登录时新建用户行,后续登录时只刷新 last_login_at +
        display_name。返回落库后的 User。

        调用方在调用本方法之前,必须自行完成域名白名单校验
        (参见 app.auth.is_email_allowed)—— 本仓储无条件信任传入的数据。
        """
        # ON CONFLICT strategy: email/domain/last_login_at are always
        # overwritten with the fresh OAuth values; display_name uses
        # COALESCE so a login event that doesn't carry a display name (some
        # OAuth flows omit it) never blanks out a previously-seen name.
        # contribution_count is deliberately absent from this statement
        # entirely — a login must NEVER reset a user's earned contribution
        # count, so increment_contribution_count() is the only writer of
        # that column.
        # 中文:ON CONFLICT 策略 —— email/domain/last_login_at 每次都用本次
        # OAuth 拿到的新值覆盖;display_name 用 COALESCE,这样某次登录若
        # 没带显示名(部分 OAuth 流程会省略)也不会把之前记录下来的名字
        # 清空。contribution_count 完全没有出现在这条语句里 —— 登录绝不
        # 能重置用户已经攒下的贡献计数,只有 increment_contribution_count()
        # 才能写这一列。
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
            # 中文:并发竞态或数据库 bug —— 这里选择大声报错,而不是
            # 悄悄返回 None。
            raise UserNotFound(user_id)
        return out

    def increment_contribution_count(self, user_id: str) -> int:
        """+1 to contribution_count. Returns the new value.

        Used after a successful Co-op upload (PLAN §6.4 give-to-get gate).

        中文:把 contribution_count 加 1,返回新值。
        在用户成功上传一条 Co-op 记录后调用(PLAN §6.4 的"贡献换权限"
        / give-to-get 门槛机制)。
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
        cleanup — for retention, prefer leaving the row + scrubbing PII fields.

        中文:硬删除(通过外键级联删除 user_unlocks)。请只在真正需要清理
        数据时使用 —— 若是出于保留策略的考虑,更推荐保留该行、只清洗
        (scrub)其中的 PII 字段。
        """
        cur = self._conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        if cur.rowcount == 0:
            raise UserNotFound(user_id)

    # === Internal ===
    # 中文:内部实现细节

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
