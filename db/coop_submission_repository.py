"""Private moderation queue; review, publish, and credit form ONE transaction.

中文：私有待审队列；审核、公开与奖励原子化，仓储不提交调用方事务。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator

from db.coop_repository import CoopRepository
from db.user_repository import UserRepository
from schemas.coop import CoopExperience, coop_group_key, derive_visibility, is_uniquely_identifying


class CoopSubmissionRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        # A standalone SAVEPOINT would commit on RELEASE. Start an outer
        # transaction first; serialize read-then-publish against other reviewers.
        # 中文：先开启外层事务，避免 RELEASE 隐式提交；串行化审核与记功。
        if not self._conn.in_transaction:
            self._conn.execute("BEGIN IMMEDIATE")
        self._conn.execute("SAVEPOINT coop_moderation")
        try:
            yield
        except Exception:
            self._conn.execute("ROLLBACK TO coop_moderation")
            self._conn.execute("RELEASE coop_moderation")
            raise
        else:
            self._conn.execute("RELEASE coop_moderation")

    def submit(self, coop: CoopExperience) -> tuple[sqlite3.Row, bool]:
        if not coop.contributor_user_id or coop.is_seed_data:
            raise ValueError("A submission requires a non-seed contributor")
        key = coop_group_key(coop.company, coop.role, coop.coop_term)
        with self._atomic():
            cursor = self._conn.execute(
                "INSERT INTO coop_submissions "
                "(coop_id, contributor_user_id, submission_key, group_key, payload) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(contributor_user_id, submission_key) DO NOTHING",
                (coop.coop_id, coop.contributor_user_id, key, key,
                 coop.model_dump_json(exclude={"created_at"})),
            )
            row = self._conn.execute(
                "SELECT * FROM coop_submissions WHERE contributor_user_id=? AND submission_key=?",
                (coop.contributor_user_id, key),
            ).fetchone()
            return row, cursor.rowcount == 0

    def get(self, coop_id: str) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM coop_submissions WHERE coop_id=?", (coop_id,),
        ).fetchone()
        if row is None:
            raise LookupError(coop_id)
        return row

    def list_queue(self) -> list[sqlite3.Row]:
        """Operator-only; no public route exposes the queue or raw payloads."""
        return self._conn.execute(
            "SELECT * FROM coop_submissions ORDER BY created_at, coop_id",
        ).fetchall()

    def review(self, coop_id: str, *, approve: bool, reviewer: str, audit: str,
               redacted: CoopExperience | None = None) -> list[str]:
        """Approve a sanitized replacement or reject; publish eligible peers too.

        Repeated identical decisions are no-ops. Terminal decisions cannot be
        edited; changing published content requires a separate withdrawal workflow.
        中文：批准需提供脱敏替换内容；重复同向决定不记功，终态不接受反向更改。
        """
        if not reviewer.strip() or not audit.strip():
            raise ValueError("Reviewer and redaction audit are required")
        with self._atomic():
            # Also acquires the write lock if the caller already opened a transaction.
            self._conn.execute(
                "UPDATE coop_submissions SET review_status=review_status WHERE coop_id=?", (coop_id,),
            )
            row = self.get(coop_id)
            if row["review_status"] != "pending":
                if (approve and row["review_status"] in {"approved", "published"}) or (
                    not approve and row["review_status"] == "rejected"
                ):
                    return []
                raise ValueError("A reviewed submission cannot change decision")
            if not approve:
                self._conn.execute(
                    "UPDATE coop_submissions SET review_status='rejected', reviewer=?, "
                    "redaction_audit=?, reviewed_at=CURRENT_TIMESTAMP WHERE coop_id=?",
                    (reviewer.strip(), audit.strip(), coop_id),
                )
                return []
            if redacted is None:
                raise ValueError("Approval requires a sanitized replacement")
            coop = redacted.model_copy(update={
                "coop_id": coop_id, "contributor_user_id": row["contributor_user_id"],
                "is_seed_data": False, "redaction_audit": audit.strip(),
                "visibility_level": derive_visibility(
                    interview_summary=redacted.interview_summary,
                    technical_questions=redacted.technical_questions,
                    salary_range_usd=redacted.salary_range_usd,
                ),
            })
            key = coop_group_key(coop.company, coop.role, coop.coop_term)
            self._conn.execute(
                "UPDATE coop_submissions SET review_status='approved', group_key=?, payload=?, "
                "reviewer=?, redaction_audit=?, reviewed_at=CURRENT_TIMESTAMP WHERE coop_id=?",
                (key, coop.model_dump_json(exclude={"created_at"}), reviewer.strip(), audit.strip(), coop_id),
            )
            peers = self._conn.execute(
                "SELECT * FROM coop_submissions WHERE group_key=? "
                "AND review_status IN ('approved','published') ORDER BY created_at, coop_id", (key,),
            ).fetchall()
            corpus = [CoopExperience.model_validate_json(peer["payload"]) for peer in peers]
            if is_uniquely_identifying(coop, corpus, k=2):
                return []
            published = []
            for peer, experience in zip(peers, corpus, strict=True):
                if peer["review_status"] == "published":
                    continue
                CoopRepository(self._conn).add(experience)
                credit = self._conn.execute(
                    "INSERT INTO coop_contribution_credits(user_id, group_key, coop_id) "
                    "VALUES (?, ?, ?) ON CONFLICT(user_id, group_key) DO NOTHING",
                    (peer["contributor_user_id"], key, peer["coop_id"]),
                )
                if credit.rowcount == 1:
                    UserRepository(self._conn).increment_contribution_count(peer["contributor_user_id"])
                self._conn.execute(
                    "UPDATE coop_submissions SET review_status='published' WHERE coop_id=?", (peer["coop_id"],),
                )
                published.append(peer["coop_id"])
            return published
