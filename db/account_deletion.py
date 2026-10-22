"""Delete one account and everything it contributed, in one transaction (batch T, policy P4).

The user chose on 10-21 that a logged-in student can delete their account and their Co-op submissions from the
数据与隐私 page. Removed together:
- the Co-op experiences this account published (`coop_experiences.contributor_user_id` would only be set to NULL by
  the foreign key, which would keep the text public without a name, so they are deleted first), and every unlock
  record of those experiences, whoever made it;
- the `users` row, which cascades to this account's own unlocks, planned courses (`user_courses`), Co-op submissions
  (`coop_submissions`, any review state) and contribution credits.
A group this account helped publish that is left with one contributor is withdrawn (k=2): see _withdraw_lone_groups.
Not touched: query_log and saved answers, which never record an account (a real user's `user_id` is NULL), and the
daily backups, which keep a copy for up to 14 days. Returns per-table counts, no identity.

中文：在一个事务里删除一个账号和它投稿的全部内容（T 批，政策 P4）。用户 10-21 定：登录的学生可以在「数据与隐私」页删掉
自己的账号和 Co-op 投稿。一起删掉的：这个账号公开的 Co-op 经验（外键只会把 `contributor_user_id` 置空，文字仍会匿名公开，
所以先删），以及任何人对这些经验的解锁记录；`users` 这一行，它级联删除这个账号自己的解锁记录、计划课程、Co-op 投稿（任何
审核状态）和贡献记功。这个账号参与公开的一组如果只剩一个投稿人，就撤回（k=2），见 _withdraw_lone_groups。不动：
query_log 和保存的回答，它们本来就不记账号；每日备份，里面的副本最多留 14 天。返回各表删了几行，不带身份。
"""

from __future__ import annotations

import sqlite3


class AccountNotFound(LookupError):
    pass


def _withdraw_lone_groups(conn: sqlite3.Connection, groups: list[str], user_id: str) -> int:
    """A group (company, role, term) is public only with two distinct contributors (k=2, coop_submission_repository).
    When the deleted account was one of them, the others' items in that group go back to 'approved' and leave
    coop_experiences (with their unlocks), so the last one cannot point at its author; a later approval in the
    group publishes them again, without a second credit. The user chose this on 10-21. Returns how many went back.
    中文：一组（公司、职位、学期）要有两个不同的投稿人才公开（k=2）。被删的账号是其中之一时，同组别人的内容回到
    'approved'，并从 coop_experiences 撤下（连同解锁记录），免得剩下的那份能认出是谁；之后同组再有通过审核的投稿，
    会一起重新公开，不会重复记功。用户 10-21 定的。返回撤回了几份。"""
    withdrawn = 0
    for group in groups:
        rows = conn.execute("SELECT coop_id, contributor_user_id FROM coop_submissions WHERE group_key = ? "
                            "AND review_status = 'published' AND contributor_user_id != ?", (group, user_id)).fetchall()
        if len({row[1] for row in rows}) >= 2:
            continue
        for coop_id, _contributor in rows:
            conn.execute("DELETE FROM user_unlocks WHERE coop_id = ?", (coop_id,))
            conn.execute("DELETE FROM coop_experiences WHERE coop_id = ?", (coop_id,))
            conn.execute("UPDATE coop_submissions SET review_status = 'approved' WHERE coop_id = ?", (coop_id,))
            withdrawn += 1
    return withdrawn


def delete_account(conn: sqlite3.Connection, user_id: str) -> dict[str, int]:
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("A user id is required")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("Foreign keys must be on: the cascade is what removes the submissions")
    if conn.in_transaction:
        raise RuntimeError("Call outside a transaction; this deletion is one transaction of its own")
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone() is None:
            raise AccountNotFound(user_id)
        published = [row[0] for row in conn.execute(
            "SELECT coop_id FROM coop_experiences WHERE contributor_user_id = ?", (user_id,))]
        groups = [row[0] for row in conn.execute(
            "SELECT DISTINCT group_key FROM coop_submissions WHERE contributor_user_id = ? AND review_status = 'published'",
            (user_id,))]
        marks = ",".join("?" * len(published))
        counts = {
            "published_experiences": len(published),
            "unlocks_of_those": conn.execute(
                f"DELETE FROM user_unlocks WHERE coop_id IN ({marks}) AND user_id != ?", (*published, user_id)
            ).rowcount if published else 0,
            "own_unlocks": conn.execute("SELECT count(*) FROM user_unlocks WHERE user_id = ?", (user_id,)).fetchone()[0],
            "submissions": conn.execute("SELECT count(*) FROM coop_submissions WHERE contributor_user_id = ?",
                                        (user_id,)).fetchone()[0],
            "credits": conn.execute("SELECT count(*) FROM coop_contribution_credits WHERE user_id = ?",
                                    (user_id,)).fetchone()[0],
            "planned_courses": conn.execute("SELECT count(*) FROM user_courses WHERE user_id = ?", (user_id,)).fetchone()[0],
        }
        if published:
            conn.execute(f"DELETE FROM coop_experiences WHERE coop_id IN ({marks})", published)
        counts["withdrawn_from_groups"] = _withdraw_lone_groups(conn, groups, user_id)
        conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        left = sum(conn.execute(f"SELECT count(*) FROM {table} WHERE {column} = ?", (user_id,)).fetchone()[0]
                   for table, column in (("users", "user_id"), ("user_unlocks", "user_id"), ("user_courses", "user_id"),
                                         ("coop_submissions", "contributor_user_id"),
                                         ("coop_contribution_credits", "user_id"),
                                         ("coop_experiences", "contributor_user_id")))
        if left:
            raise RuntimeError("Rows of the account are left after the deletion")
        conn.commit()
        return counts
    except BaseException:
        conn.rollback()
        raise


__all__ = ["AccountNotFound", "delete_account"]
