"""One SQLite metadata-filter contract for hybrid retrieval and exact shortcuts.

中文：混合检索与精确入口共用同一套 SQLite 元数据筛选规则。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

ELIGIBLE_STATUS = "indexed"


def filter_course_ids(
    conn: sqlite3.Connection,
    filters: Mapping[str, Any],
    *,
    candidate_course_ids: Sequence[str] | None = None,
) -> list[str]:
    """Return indexed IDs satisfying AND-combined filters, optionally within a shortlist.

    Exact term/credits/mode and case-insensitive professor LIKE semantics are
    unchanged from Retriever's original SQL. All values remain bound parameters.
    中文：保留原有精确匹配、教授 LIKE 和 indexed 状态规则；所有值参数绑定。
    """
    if candidate_course_ids is not None and not candidate_course_ids:
        return []
    clauses = ["status = ?"]
    params: list[Any] = [ELIGIBLE_STATUS]
    for field in ("term", "credits", "delivery_mode"):
        if field in filters:
            clauses.append(f"json_extract(metadata, '$.{field}') = ?")
            params.append(filters[field])
    if "professor" in filters:
        clauses.append("json_extract(metadata, '$.professor') LIKE ?")
        params.append(f"%{filters['professor']}%")
    if "primary_code_prefix" in filters:
        # The space prevents CS from also matching CSYE.
        # 中文：前缀后加空格，避免 CS 同时匹配 CSYE。
        clauses.append("primary_code LIKE ?")
        params.append(f"{str(filters['primary_code_prefix']).upper()} %")
    if candidate_course_ids is not None:
        placeholders = ",".join("?" for _ in candidate_course_ids)
        clauses.append(f"course_id IN ({placeholders})")
        params.extend(candidate_course_ids)
    rows = conn.execute(
        f"SELECT course_id FROM courses WHERE {' AND '.join(clauses)}", params,
    ).fetchall()
    return [row["course_id"] for row in rows]
