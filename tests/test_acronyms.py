"""Tests for rag.acronyms (ADR-0020 §3) + HybridRetriever query_expander
wiring + the search_expansion BM25 column."""

from __future__ import annotations

import sqlite3

from db.repository import CourseRepository
from rag.acronyms import expand_query, load_glossary
from rag.hybrid import BM25Corpus, HybridRetriever
from schemas.course import Course

_GLOSSARY = {
    "CRM": ("crisis resource management", "customer relationship management"),
    "NLP": ("natural language processing",),
    "ML": ("machine learning",),
}


# === expand_query ===


def test_expand_appends_all_in_corpus_senses() -> None:
    out = expand_query("CRM 认知偏差 团队决策", glossary=_GLOSSARY)
    assert "crisis resource management" in out
    assert "customer relationship management" in out
    assert out.startswith("CRM 认知偏差 团队决策")  # original query preserved


def test_expand_case_insensitive_for_3plus_letters() -> None:
    out = expand_query("intro to nlp course", glossary=_GLOSSARY)
    assert "natural language processing" in out


def test_expand_two_letter_requires_uppercase() -> None:
    # "ml" prose stays untouched; "ML" expands — mirrors the Layer-2
    # AMBIGUOUS_PREFIXES conservatism for short tokens.
    assert expand_query("how many ml in a liter", glossary=_GLOSSARY) == \
        "how many ml in a liter"
    assert "machine learning" in expand_query("ML electives", glossary=_GLOSSARY)


def test_expand_skips_sense_already_in_query() -> None:
    q = "crisis resource management CRM training"
    out = expand_query(q, glossary=_GLOSSARY)
    assert out.count("crisis resource management") == 1


def test_expand_no_glossary_is_identity() -> None:
    assert expand_query("CRM teams", glossary={}) == "CRM teams"


def test_load_glossary_missing_file_returns_empty(tmp_path) -> None:
    load_glossary.cache_clear()
    assert load_glossary(str(tmp_path / "nope.json")) == {}
    load_glossary.cache_clear()


def test_load_glossary_caps_senses(tmp_path) -> None:
    p = tmp_path / "g.json"
    p.write_text('{"abc": ["s1", "s2", "s3", "s4", "s5"]}', encoding="utf-8")
    load_glossary.cache_clear()
    g = load_glossary(str(p))
    assert g["ABC"] == ("s1", "s2", "s3")  # upper-keyed, capped at 3
    load_glossary.cache_clear()


# === HybridRetriever query_expander wiring ===


class _SpyRetriever:
    def __init__(self) -> None:
        self.last_query: str | None = None

    def search(self, query, *, hard_filters=None, k=10):
        self.last_query = query
        return []


def test_hybrid_applies_expander_to_legs() -> None:
    spy = _SpyRetriever()
    hybrid = HybridRetriever(
        vector_retriever=spy,
        bm25_corpus=BM25Corpus({}),
        course_repo=None,  # never reached: both legs come back empty
        query_expander=lambda q: q + " EXPANDED",
    )
    hybrid.search("CRM teams", k=3)
    assert spy.last_query == "CRM teams EXPANDED"


def test_hybrid_without_expander_passes_query_through() -> None:
    spy = _SpyRetriever()
    hybrid = HybridRetriever(
        vector_retriever=spy, bm25_corpus=BM25Corpus({}), course_repo=None,
    )
    hybrid.search("CRM teams", k=3)
    assert spy.last_query == "CRM teams"


# === search_expansion column in BM25Corpus.from_db ===


def test_bm25_from_db_includes_expansion_column(empty_db: sqlite3.Connection) -> None:
    repo = CourseRepository(empty_db)
    repo.insert(
        Course(course_id="c-1", primary_code="CS 5800", primary_name="Algorithms"),
        raw_text="graph algorithms shortest paths",
    )
    repo.mark_indexed("c-1")
    empty_db.execute(
        "UPDATE courses SET search_expansion = ? WHERE course_id = ?",
        ("dynamic programming interview prep 动态规划", "c-1"),
    )
    corpus = BM25Corpus.from_db(empty_db)
    # English expansion term reachable...
    assert [c for c, _ in corpus.search("interview prep", k=3)] == ["c-1"]
    # ...and the zh keywords are reachable via CJK bigrams.
    assert [c for c, _ in corpus.search("动态规划", k=3)] == ["c-1"]


def test_bm25_from_db_tolerates_missing_expansion_column() -> None:
    """Pre-migration DBs (no search_expansion column) must still build."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE courses (course_id TEXT PRIMARY KEY, raw_text TEXT, "
        "status TEXT)"
    )
    conn.execute(
        "INSERT INTO courses VALUES ('c-1', 'graph algorithms', 'indexed')"
    )
    corpus = BM25Corpus.from_db(conn)
    assert corpus.count == 1
    assert [c for c, _ in corpus.search("graph", k=3)] == ["c-1"]
