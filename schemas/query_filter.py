"""Structured filters extracted from a natural-language query.

Layer 2 in the v3.0 RAG quality plan (see docs/PLAN_v3.0.md follow-up):
the chat / search route extracts these filters from the user's query
BEFORE running hybrid retrieval. The retriever then applies them as hard
filters at the SQLite layer (`Retriever._sqlite_filter`), narrowing the
candidate pool — e.g. "我是 AAI 专业 ..." → program_prefix='AAI' →
retrieval only sees the 23 AAI courses, not all 6469.

v3.0 RAG 质量提升计划(见 docs/PLAN_v3.0.md 后续章节)中的 Layer 2:
聊天 / 搜索路由在运行混合检索之前,先从用户查询中抽取出这些过滤条件。
检索器随后把它们作为硬过滤(hard filter)施加在 SQLite 层
(`Retriever._sqlite_filter`),收窄候选池 —— 例如"我是 AAI 专业 ..."
→ program_prefix='AAI' → 检索只会看到 23 门 AAI 课程,而不是全部 6469 门。

The pattern follows Cole Hoffer's "Structured Pre-Filtering for RAG"
(https://www.colehoffer.ai/articles/advanced-rag-structured-pre-filtering)
and Haystack's `QueryMetadataExtractor`. Two-step: (1) extract structured
filter, (2) sanitize the query (strip filter parts so embeddings focus on
semantic intent), (3) retrieve on the filtered subset.

这个模式借鉴自 Cole Hoffer 的 "Structured Pre-Filtering for RAG"
(https://www.colehoffer.ai/articles/advanced-rag-structured-pre-filtering)
以及 Haystack 的 `QueryMetadataExtractor`。分两步:(1) 抽取结构化过滤
条件,(2) 净化查询(去掉过滤相关的部分,让嵌入只聚焦语义意图),
(3) 在过滤后的子集上检索。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class QueryFilters(BaseModel):
    """Filters extracted from a user query — all optional except sanitized_query.

    Empty / null fields mean "no signal detected"; the route SHOULD NOT
    apply that field as a filter (passing None as a SQL value would still
    match nothing). The route checks `is_empty()` to decide whether to
    short-circuit the LLM extraction step entirely.

    中文:从用户查询中抽取出的过滤条件 —— 除 sanitized_query 外全部可选。

    字段为空 / null 表示"没有检测到信号";路由不应该把该字段当作过滤条件
    去用(把 None 当 SQL 值传进去,反而会匹配不到任何东西)。路由通过
    检查 `is_empty()` 来决定是否要整体跳过(short-circuit)LLM 抽取这
    一步。
    """

    model_config = ConfigDict(extra="forbid")

    # 中文:用户提到的专业 / 系所对应的课程代码前缀,大写。
    # 示例:'AAI' 对应 Applied AI,'CS' 对应 Computer Science,
    # 'DS' 对应 Data Science,'EECE' 对应 Electrical & Computer
    # Engineering。查询中没有专业信号时为 None。
    program_prefix: str | None = Field(
        default=None,
        description=(
            "Course-code prefix for the program / department the user "
            "mentioned, uppercase. Examples: 'AAI' for Applied AI, 'CS' "
            "for Computer Science, 'DS' for Data Science, 'EECE' for "
            "Electrical & Computer Engineering. None when no program "
            "signal is in the query."
        ),
    )

    # 中文:去掉过滤相关短语后的原始查询,这样 BM25 / 向量两路检索
    # 看到的只有语义意图。允许是空字符串(表示整条查询都是过滤信号)。
    sanitized_query: str = Field(
        description=(
            "The original query with filter-related phrases stripped, so "
            "the BM25 / vector legs see only semantic intent. Empty string "
            "is allowed (means the entire query was filter signals)."
        ),
    )

    def is_empty(self) -> bool:
        """True iff no filter fields were populated. Caller can skip the
        retriever pre-filter step entirely and pass the original query.

        中文:当且仅当没有任何过滤字段被填充时为 True。此时调用方可以
        完全跳过检索器的预过滤步骤,直接传原始查询。
        """
        return self.program_prefix is None

    def to_hard_filter(self) -> dict[str, object]:
        """Convert to the dict shape Retriever._sqlite_filter expects.
        Only populated fields go in — None fields are dropped, not encoded.

        中文:转换成 Retriever._sqlite_filter 期望的字典形状。
        只有被填充的字段才会进入结果 —— None 字段会被丢弃,而不是编码
        进去。
        """
        out: dict[str, object] = {}
        if self.program_prefix is not None:
            out["primary_code_prefix"] = self.program_prefix
        return out


__all__ = ["QueryFilters"]
