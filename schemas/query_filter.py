"""Structured filters extracted from a natural-language query.

Layer 2 in the v3.0 RAG quality plan (see docs/PLAN_v3.0.md follow-up):
the chat / search route extracts these filters from the user's query
BEFORE running hybrid retrieval. The retriever then applies them as hard
filters at the SQLite layer (`Retriever._sqlite_filter`), narrowing the
candidate pool — e.g. "我是 AAI 专业 ..." → program_prefix='AAI' →
retrieval only sees the 23 AAI courses, not all 6469.

The pattern follows Cole Hoffer's "Structured Pre-Filtering for RAG"
(https://www.colehoffer.ai/articles/advanced-rag-structured-pre-filtering)
and Haystack's `QueryMetadataExtractor`. Two-step: (1) extract structured
filter, (2) sanitize the query (strip filter parts so embeddings focus on
semantic intent), (3) retrieve on the filtered subset.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class QueryFilters(BaseModel):
    """Filters extracted from a user query — all optional except sanitized_query.

    Empty / null fields mean "no signal detected"; the route SHOULD NOT
    apply that field as a filter (passing None as a SQL value would still
    match nothing). The route checks `is_empty()` to decide whether to
    short-circuit the LLM extraction step entirely.
    """

    model_config = ConfigDict(extra="forbid")

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

    sanitized_query: str = Field(
        description=(
            "The original query with filter-related phrases stripped, so "
            "the BM25 / vector legs see only semantic intent. Empty string "
            "is allowed (means the entire query was filter signals)."
        ),
    )

    def is_empty(self) -> bool:
        """True iff no filter fields were populated. Caller can skip the
        retriever pre-filter step entirely and pass the original query."""
        return self.program_prefix is None

    def to_hard_filter(self) -> dict[str, object]:
        """Convert to the dict shape Retriever._sqlite_filter expects.
        Only populated fields go in — None fields are dropped, not encoded."""
        out: dict[str, object] = {}
        if self.program_prefix is not None:
            out["primary_code_prefix"] = self.program_prefix
        return out


__all__ = ["QueryFilters"]
