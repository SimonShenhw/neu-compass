"""Three-step retriever: SQLite hard filter -> FAISS vector search -> rehydrate.

Implements PLAN §1.2 query path. ADR-0013 invariant enforced via
status='indexed' filter — pending courses cannot be returned.

实现 PLAN §1.2 的查询路径。通过 status='indexed' 过滤强制满足 ADR-0013
不变量 —— 未完成入库的课程不会被返回。

Hard filters supported (PLAN metadata JSON1 indexes):
  term, credits, delivery_mode  (exact match)
  professor                     (LIKE substring, optional)

支持的硬过滤条件(PLAN 元数据 JSON1 索引):
  term、credits、delivery_mode(精确匹配)
  professor(LIKE 子串匹配,可选)

Hybrid search (BM25 + vector) and HyDE expansion live in separate modules
under rag/ later (Week 5). This file is the canonical "default" retriever.

混合检索(BM25 + 向量)和 HyDE 扩写后续(第 5 周)放在 rag/ 下的独立模块
中。本文件是规范的"默认"检索器。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from db.repository import CourseRepository
from rag.embedder import EmbedderProtocol
from rag.index import FaissIndex
from schemas.course import Course

# Status of courses eligible for retrieval. ADR-0013: pending = not yet
# embedded; failed = gave up; only indexed has a valid FAISS row.
# 中文:可被检索的课程状态。ADR-0013:pending = 尚未完成 embedding;
# failed = 已放弃处理;只有 indexed 才在 FAISS 里有对应行。
ELIGIBLE_STATUS = "indexed"


@dataclass
class SearchHit:
    """One result with similarity score + Course payload.

    中文:一条检索结果,携带相似度分数 + Course 数据体。
    """

    course: Course
    score: float


class Retriever:
    """Composes embedder + FAISS index + SQLite hard filter.

    中文:组合 embedder + FAISS 索引 + SQLite 硬过滤的检索器。
    """

    def __init__(
        self,
        *,
        embedder: EmbedderProtocol,
        index: FaissIndex,
        course_repo: CourseRepository,
        sqlite_conn: sqlite3.Connection,
    ) -> None:
        self._embedder = embedder
        self._index = index
        self._course_repo = course_repo
        self._conn = sqlite_conn

    def search(
        self,
        query: str,
        *,
        hard_filters: dict[str, Any] | None = None,
        k: int = 10,
    ) -> list[SearchHit]:
        """Run the three-step pipeline. Returns top-k hits sorted by score.

        中文:跑完三步流水线,返回按分数排序的 top-k 结果。
        """
        top = self.search_ids(query, hard_filters=hard_filters, k=k)
        if not top:
            return []
        # Batch hydrate — one SELECT + one Pydantic parse per hit, instead of
        # the N+1 per-row get() this used to do (k*3=60 SELECTs per /search
        # via HybridRetriever's candidate pool).
        # 中文:批量回填 —— 每条命中只需一次 SELECT + 一次 Pydantic 解析,
        # 取代旧版逐行 get() 的 N+1 查询(经 HybridRetriever 候选池,相当于
        # 每次 /search 发出 k*3=60 条 SELECT)。
        courses = self._course_repo.get_batch([cid for cid, _ in top])
        return [
            SearchHit(course=courses[cid], score=score)
            for cid, score in top
            if cid in courses
        ]

    def search_ids(
        self,
        query: str,
        *,
        hard_filters: dict[str, Any] | None = None,
        k: int = 10,
    ) -> list[tuple[str, float]]:
        """ID-only variant of search(): (course_id, score) pairs, no SQLite
        rehydration. HybridRetriever uses this for its vector leg — it only
        needs IDs for RRF fusion and hydrates once on the fused top-k.

        中文:search() 的纯 ID 版本:返回 (course_id, score) 对,不做 SQLite
        回填。HybridRetriever 的向量路用这个方法 —— RRF 融合只需要 ID,
        回填只在融合后的 top-k 上做一次。
        """
        # Only hit SQLite when filters actually narrow the pool. The old
        # unconditional call fetched all ~6.5k indexed ids on EVERY
        # unfiltered search and then threw the list away — pure waste on
        # the common path.
        # 中文:只有过滤条件真正会缩小候选池时才查 SQLite。旧版无条件调用
        # 会在每次无过滤搜索时都取出全部约 6.5k 个 indexed id 再整体丢弃——
        # 在最常见的路径上纯属浪费。
        if hard_filters:
            candidate_ids = self.filter_ids(hard_filters)
            # Empty candidate set after filter -> no results possible
            # 中文:过滤后候选集为空 -> 不可能有结果。
            if not candidate_ids:
                return []
            candidates: list[str] | None = candidate_ids
        else:
            candidates = None  # "search the whole index" — the cheap path
            # 中文:即"搜索整个索引"—— 最便宜的路径。

        query_vec = self._embedder.encode([query])[0]
        return self._index.search(query_vec, k=k, candidate_course_ids=candidates)

    # === Hard filter ===
    # 中文:=== 硬过滤 ===

    def filter_ids(self, filters: dict[str, Any]) -> list[str]:
        """Public access to the SQLite hard-filter step. HybridRetriever uses
        this to scope its BM25 leg to the same allowed set as the vector leg
        (instead of intersecting with the vector top-k, which silently
        dropped BM25-only hits that passed the filter).

        中文:对外暴露 SQLite 硬过滤这一步。HybridRetriever 用它把 BM25 路
        限定在与向量路相同的允许集合内(而不是与向量 top-k 求交 —— 那样会
        悄悄丢掉"通过了过滤、但只在 BM25 路命中"的结果)。
        """
        return self._sqlite_filter(filters)

    def _sqlite_filter(self, filters: dict[str, Any]) -> list[str]:
        """Apply WHERE on courses table; only return status='indexed' rows.

        中文:对 courses 表施加 WHERE 条件;只返回 status='indexed' 的行。
        """
        clauses = ["status = ?"]
        params: list[Any] = [ELIGIBLE_STATUS]

        if "term" in filters:
            clauses.append("json_extract(metadata, '$.term') = ?")
            params.append(filters["term"])

        if "credits" in filters:
            clauses.append("json_extract(metadata, '$.credits') = ?")
            params.append(filters["credits"])

        if "delivery_mode" in filters:
            clauses.append("json_extract(metadata, '$.delivery_mode') = ?")
            params.append(filters["delivery_mode"])

        if "professor" in filters:
            # Substring match against the professor JSON array's text dump.
            # Acceptable for MVP; precise array-element match would need
            # json_each in a subquery.
            # 中文:对 professor JSON 数组的文本转储做子串匹配。对 MVP 来说
            # 可以接受;要精确匹配数组元素,则需要在子查询里用 json_each。
            clauses.append("json_extract(metadata, '$.professor') LIKE ?")
            params.append(f"%{filters['professor']}%")

        if "primary_code_prefix" in filters:
            # Layer 2 (PLAN v3.0+): when the query mentions a program / major
            # prefix (AAI, CS, DS, EECE, INFO, ...), narrow the candidate pool
            # at the SQLite layer BEFORE BM25/vector retrieval. Bilingual NEU
            # students often phrase questions like "我是 AAI 专业 ..." — without
            # this filter the hybrid leg pulls in cross-discipline noise (ALY /
            # ARTG / BINF) that has lexical/semantic similarity but is wrong.
            # Format: "AAI" matches "AAI 5015", "AAI 6640", etc. We append a
            # space so 'CS' doesn't accidentally match 'CSYE'.
            # 中文:Layer 2(PLAN v3.0+):当查询提到某个专业 / 项目前缀
            # (AAI、CS、DS、EECE、INFO 等)时,在 BM25/向量检索之前先在
            # SQLite 层缩小候选池。双语 NEU 学生常这样提问:"我是 AAI 专业
            # ..." —— 没有这层过滤,混合检索会带入跨学科噪声(ALY / ARTG /
            # BINF),这些课程词面/语义上相似,但其实是错的。格式:"AAI"
            # 匹配 "AAI 5015"、"AAI 6640" 等。末尾补一个空格,避免 'CS'
            # 意外匹配到 'CSYE'。
            prefix = str(filters["primary_code_prefix"]).upper()
            clauses.append("primary_code LIKE ?")
            params.append(f"{prefix} %")

        sql = f"SELECT course_id FROM courses WHERE {' AND '.join(clauses)}"
        rows = self._conn.execute(sql, params).fetchall()
        return [r["course_id"] for r in rows]


__all__ = ["ELIGIBLE_STATUS", "Retriever", "SearchHit"]
