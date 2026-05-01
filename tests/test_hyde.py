"""Tests for rag.hyde — uses fake expand_fn + fake base_retriever, no LLM."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from rag.hyde import (
    HYDE_PROMPT_TEMPLATE,
    HydeRetriever,
    expand_query_via_hyde,
)
from rag.retriever import SearchHit


@dataclass
class _FakeBase:
    """Records what query made it to .search."""
    last_query: str | None = None
    last_filters: dict | None = None
    last_k: int | None = None
    return_hits: list[SearchHit] = field(default_factory=list)

    def search(self, query, *, hard_filters=None, k=10):
        self.last_query = query
        self.last_filters = hard_filters
        self.last_k = k
        return list(self.return_hits)


# === expand_query_via_hyde ===

def test_expand_query_passes_query_to_prompt() -> None:
    captured = {}

    def fake_gen(prompt: str) -> str:
        captured["prompt"] = prompt
        return "synthetic description"

    out = expand_query_via_hyde("find an NLP class", generate_fn=fake_gen)
    assert out == "synthetic description"
    assert "find an NLP class" in captured["prompt"]


def test_expand_query_strips_whitespace() -> None:
    out = expand_query_via_hyde(
        "x", generate_fn=lambda p: "  hello world\n\n",
    )
    assert out == "hello world"


def test_prompt_template_has_query_placeholder() -> None:
    assert "{query}" in HYDE_PROMPT_TEMPLATE


def test_prompt_template_outputs_only_description() -> None:
    """Common LLM failure: preambling 'Sure, here's...'. Prompt should
    explicitly suppress that."""
    assert "ONLY" in HYDE_PROMPT_TEMPLATE


# === HydeRetriever ===

def test_hyde_retriever_passes_expanded_query_to_base() -> None:
    base = _FakeBase()
    retriever = HydeRetriever(
        base_retriever=base,
        expand_fn=lambda p: "EXPANDED CONTEXT",
        prepend_original=False,
    )
    retriever.search("user query")
    assert base.last_query == "EXPANDED CONTEXT"


def test_hyde_retriever_prepends_original_by_default() -> None:
    base = _FakeBase()
    retriever = HydeRetriever(
        base_retriever=base,
        expand_fn=lambda p: "EXPANDED CONTEXT",
    )
    retriever.search("user query")
    assert "user query" in base.last_query
    assert "EXPANDED CONTEXT" in base.last_query


def test_hyde_retriever_passes_through_filters_and_k() -> None:
    base = _FakeBase()
    retriever = HydeRetriever(
        base_retriever=base, expand_fn=lambda p: "x",
    )
    retriever.search("q", hard_filters={"term": "Spring 2026"}, k=7)
    assert base.last_filters == {"term": "Spring 2026"}
    assert base.last_k == 7


def test_hyde_retriever_returns_base_hits_unchanged() -> None:
    """HyDE only expands the query; result format passes through."""
    from db.repository import CourseRepository
    from schemas.course import Course
    import sqlite3

    # Inline minimal setup
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from pathlib import Path
    init_sql = Path("db/init.sql").read_text(encoding="utf-8")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(init_sql)
    course_repo = CourseRepository(conn)
    course_repo.insert(Course(course_id="c-1", primary_code="CS 5800",
                              primary_name="Algos"))
    course_repo.mark_indexed("c-1")

    fixed_hit = SearchHit(course=course_repo.get("c-1"), score=0.9)
    base = _FakeBase(return_hits=[fixed_hit])
    retriever = HydeRetriever(
        base_retriever=base, expand_fn=lambda p: "x",
    )
    results = retriever.search("any query")
    assert results == [fixed_hit]
    conn.close()


def test_hyde_retriever_no_llm_call_per_default_constructor_path() -> None:
    """Constructing HydeRetriever WITHOUT calling .search must NOT trigger
    any LLM activity (lazy on first search)."""
    base = _FakeBase()
    HydeRetriever(base_retriever=base)
    # If we got here without exception, lazy init held
    assert base.last_query is None
