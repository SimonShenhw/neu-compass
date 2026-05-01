"""Tests for rag.hybrid — BM25Corpus + RRF + HybridRetriever."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pytest

from db.repository import CourseRepository
from rag.hybrid import (
    BM25Corpus,
    DEFAULT_RRF_K,
    HybridRetriever,
    reciprocal_rank_fusion,
    tokenize,
)
from rag.retriever import SearchHit
from schemas.course import Course


# === tokenize ===

def test_tokenize_lowercase_and_alnum() -> None:
    assert tokenize("Hello, World 123!") == ["hello", "world", "123"]


def test_tokenize_handles_punctuation_aggressively() -> None:
    assert tokenize("Dr. Zhang's class — A+") == ["dr", "zhang", "s", "class", "a"]


def test_tokenize_drops_chinese_chars() -> None:
    """Documented limitation: Chinese chars filtered out by ASCII alnum regex."""
    assert tokenize("应用 AI fundamentals") == ["ai", "fundamentals"]


def test_tokenize_empty() -> None:
    assert tokenize("") == []


# === reciprocal_rank_fusion ===

def test_rrf_single_ranking_decreases_with_rank() -> None:
    fused = reciprocal_rank_fusion([["a", "b", "c"]], k=10)
    assert fused["a"] > fused["b"] > fused["c"]


def test_rrf_combines_two_rankings() -> None:
    """An item ranked 1st by both should beat one ranked 1st by only one."""
    fused = reciprocal_rank_fusion([["a", "b"], ["a", "c"]], k=60)
    # 'a' appears at rank 1 in both -> strongest
    assert fused["a"] > fused["b"]
    assert fused["a"] > fused["c"]


def test_rrf_fairness_across_k() -> None:
    """Larger k makes rank differences smaller; smaller k amplifies them."""
    small_k = reciprocal_rank_fusion([["a", "b"]], k=1)
    big_k = reciprocal_rank_fusion([["a", "b"]], k=1000)
    # rank gap matters more with small k
    assert (small_k["a"] - small_k["b"]) > (big_k["a"] - big_k["b"])


def test_rrf_default_k_is_60() -> None:
    """Standard RRF param from Cormack et al. — sanity-check exposed constant."""
    assert DEFAULT_RRF_K == 60


# === BM25Corpus ===

def test_bm25_empty_corpus_returns_empty() -> None:
    corpus = BM25Corpus({})
    assert corpus.search("anything", k=5) == []


def test_bm25_finds_exact_term() -> None:
    """Use 4 docs to avoid BM25 IDF=0 degeneracy at N=2."""
    corpus = BM25Corpus({
        "c1": "graph algorithms BFS DFS shortest paths",
        "c2": "k-means clustering dimensionality reduction",
        "c3": "neural network training backpropagation",
        "c4": "convex optimization Lagrangian duality",
    })
    hits = corpus.search("BFS DFS", k=5)
    assert hits[0][0] == "c1"


def test_bm25_unmatched_query_returns_empty() -> None:
    """Vocab-overlap check rejects zero-overlap queries cleanly."""
    corpus = BM25Corpus({"c1": "graph algorithms",
                          "c2": "neural networks",
                          "c3": "linear algebra"})
    assert corpus.search("xylophone giraffe quantum", k=5) == []


def test_bm25_handles_empty_doc() -> None:
    """Course with no raw_text shouldn't crash BM25Okapi or be returned."""
    corpus = BM25Corpus({
        "c-empty": "",
        "c-algo": "graph algorithms BFS DFS",
        "c-ml": "neural network training",
        "c-stats": "linear algebra eigenvalues",
    })
    hits = corpus.search("graph algorithms", k=5)
    assert hits[0][0] == "c-algo"


def test_bm25_from_db(empty_db: sqlite3.Connection) -> None:
    course_repo = CourseRepository(empty_db)
    courses = [
        ("c-algo",  "CS 5800",  "Algos",   "graph algorithms BFS DFS shortest paths"),
        ("c-ml",    "DS 5220",  "ML",      "neural network training backpropagation"),
        ("c-stats", "MATH 7243","Stats",   "linear algebra eigenvalues SVD"),
        ("c-eng",   "INFO 6105","Data Eng","Apache Spark distributed pipelines"),
    ]
    for cid, code, name, text in courses:
        course_repo.insert(
            Course(course_id=cid, primary_code=code, primary_name=name),
            raw_text=text,
        )
        course_repo.mark_indexed(cid)

    corpus = BM25Corpus.from_db(empty_db)
    assert corpus.count == 4

    hits = corpus.search("graph algorithms", k=4)
    assert hits[0][0] == "c-algo"


def test_bm25_from_db_filters_pending(empty_db: sqlite3.Connection) -> None:
    """ADR-0013: only status=indexed rows go into the BM25 corpus."""
    course_repo = CourseRepository(empty_db)
    seeds = [
        ("c-i1",       "CS 5800",  True),
        ("c-i2",       "DS 5220",  True),
        ("c-i3",       "DS 5230",  True),
        ("c-pending",  "MATH 7243", False),
    ]
    for cid, code, indexed in seeds:
        course_repo.insert(
            Course(course_id=cid, primary_code=code, primary_name="x"),
            raw_text=f"raw text for {cid}",
        )
        if indexed:
            course_repo.mark_indexed(cid)

    corpus = BM25Corpus.from_db(empty_db)
    assert corpus.count == 3  # c-pending excluded


# === HybridRetriever ===

@dataclass
class _FakeVecRetriever:
    """Returns a fixed ranking of courses for any query. Lets us test RRF
    behavior independently from real embeddings."""
    course_repo: CourseRepository
    ranking: list[str]
    last_filters: dict | None = None
    last_k: int | None = None

    def search(self, query, *, hard_filters=None, k=10):
        self.last_filters = hard_filters
        self.last_k = k
        # Apply hard_filters by treating as "intersect with allowed" set —
        # mimics Retriever.search semantics for the test
        ids = self.ranking
        if hard_filters and "_allowed_ids" in hard_filters:
            ids = [c for c in ids if c in hard_filters["_allowed_ids"]]
        return [
            SearchHit(course=self.course_repo.get(cid), score=1.0 / (i + 1))
            for i, cid in enumerate(ids[:k])
        ]


@pytest.fixture
def hybrid_setup(empty_db: sqlite3.Connection):
    course_repo = CourseRepository(empty_db)
    courses = [
        Course(course_id="c-algo", primary_code="CS 5800", primary_name="Algos"),
        Course(course_id="c-ml", primary_code="DS 5220", primary_name="ML"),
        Course(course_id="c-stats", primary_code="MATH 7243",
               primary_name="Stats"),
    ]
    raw_texts = {
        "c-algo": "graph algorithms BFS DFS shortest paths NP completeness",
        "c-ml": "neural network training backpropagation gradient descent",
        "c-stats": "linear algebra eigenvalues SVD convex optimization",
    }
    for c in courses:
        course_repo.insert(c, raw_text=raw_texts[c.course_id])
        course_repo.mark_indexed(c.course_id)

    bm25 = BM25Corpus.from_db(empty_db)
    return course_repo, bm25, raw_texts


def test_hybrid_returns_search_hits(hybrid_setup) -> None:
    course_repo, bm25, _ = hybrid_setup
    fake_vec = _FakeVecRetriever(course_repo, ["c-algo", "c-ml", "c-stats"])
    hybrid = HybridRetriever(
        vector_retriever=fake_vec,
        bm25_corpus=bm25,
        course_repo=course_repo,
    )
    hits = hybrid.search("graph algorithms", k=3)
    assert len(hits) >= 1
    assert all(isinstance(h, SearchHit) for h in hits)


def test_hybrid_promotes_dual_winner(hybrid_setup) -> None:
    """If vector AND BM25 both rank c-algo first, c-algo must be #1 in fused."""
    course_repo, bm25, _ = hybrid_setup
    fake_vec = _FakeVecRetriever(course_repo, ["c-algo", "c-ml", "c-stats"])
    hybrid = HybridRetriever(
        vector_retriever=fake_vec,
        bm25_corpus=bm25,
        course_repo=course_repo,
    )
    hits = hybrid.search("graph algorithms BFS", k=3)
    assert hits[0].course.course_id == "c-algo"


def test_hybrid_compensates_when_vector_misranks(hybrid_setup) -> None:
    """Vector ranks c-stats #1 (wrong); BM25 ranks c-algo #1 (right).
    RRF should pull c-algo above c-stats because its rank-1 BM25 + rank-2
    vector beats c-stats's rank-1 vector + missing-from-BM25."""
    course_repo, bm25, _ = hybrid_setup
    fake_vec = _FakeVecRetriever(
        course_repo, ["c-stats", "c-algo", "c-ml"],
    )
    hybrid = HybridRetriever(
        vector_retriever=fake_vec,
        bm25_corpus=bm25,
        course_repo=course_repo,
    )
    hits = hybrid.search("graph algorithms BFS DFS", k=3)
    # c-algo has both BM25 #1 (strong lexical match) and vector #2;
    # c-stats has only vector #1, no BM25 hit
    assert hits[0].course.course_id == "c-algo"


def test_hybrid_no_bm25_match_falls_back_to_vector(hybrid_setup) -> None:
    """Pure-Chinese / out-of-vocab query has no BM25 hits; should still
    return the vector ranking."""
    course_repo, bm25, _ = hybrid_setup
    fake_vec = _FakeVecRetriever(course_repo, ["c-stats", "c-algo"])
    hybrid = HybridRetriever(
        vector_retriever=fake_vec,
        bm25_corpus=bm25,
        course_repo=course_repo,
    )
    hits = hybrid.search("xyz unknown words", k=2)
    # vector ranking preserved
    assert [h.course.course_id for h in hits] == ["c-stats", "c-algo"]


def test_hybrid_passes_hard_filters_to_vector(hybrid_setup) -> None:
    course_repo, bm25, _ = hybrid_setup
    fake_vec = _FakeVecRetriever(course_repo, ["c-algo", "c-ml"])
    hybrid = HybridRetriever(
        vector_retriever=fake_vec, bm25_corpus=bm25, course_repo=course_repo,
    )
    hybrid.search("graph", hard_filters={"term": "Spring 2026"}, k=3)
    assert fake_vec.last_filters == {"term": "Spring 2026"}


def test_hybrid_widens_candidate_pool(hybrid_setup) -> None:
    """HybridRetriever asks vector for k * multiplier candidates so the
    BM25 leg has room to surface alternatives."""
    course_repo, bm25, _ = hybrid_setup
    fake_vec = _FakeVecRetriever(course_repo, ["c-algo", "c-ml", "c-stats"])
    hybrid = HybridRetriever(
        vector_retriever=fake_vec, bm25_corpus=bm25, course_repo=course_repo,
        candidate_multiplier=4,
    )
    hybrid.search("graph", k=2)
    assert fake_vec.last_k == 8  # 2 * 4
