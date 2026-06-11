"""BM25 + vector hybrid retrieval via Reciprocal Rank Fusion (RRF).

Why hybrid: Week 4 smoke test (docs/rag_smoke_results.md §6) showed
adversarial query "quantum cryptography" got vector score 0.485,
HIGHER than legitimate match "graph algorithms" at 0.463. Absolute
score thresholds don't work — bge-m3 compresses STEM-text similarities
into a narrow 0.4-0.7 band.

BM25 contributes lexical matching (exact term hits) which the vector
embedder under-weights. RRF combines the two rankings without needing
to normalize their score scales:

    rrf_score(item) = sum over rankings of  1 / (k + rank_in_ranking)

with default k=60 (standard RRF parameter from Cormack et al. 2009).
This makes top-1 in each list contribute the most, with diminishing
returns. Robust to scale differences.

Tokenization: ASCII alnum tokens (whitespace + lowercase) with English
stopwords filtered, PLUS CJK character bigrams (ADR-0020). Stopword
filter widens the inversion gap reported in docs/rag_smoke_results.md §7
(vector-only inversion was -0.022; hybrid without stopwords was +0.001 —
borderline). Adversarial queries like "ancient roman history" otherwise
gain BM25 mass from "and"/"of" appearing in every course's raw_text.

CJK bigrams (no jieba dependency — char bigrams are the standard
segmentation-free CJK indexing trick): Chinese queries previously got
ZERO lexical signal against the English corpus. With the doc-expansion
field adding 中文 keywords per course (scripts/generate_doc_expansion.py),
bigrams give both sides a shared vocabulary, opening the BM25 leg for
the bilingual half of the user base.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Protocol

from rank_bm25 import BM25Okapi

from db.repository import CourseRepository
from rag.retriever import ELIGIBLE_STATUS, SearchHit

DEFAULT_RRF_K = 60

# ASCII alnum tokens (lowercased) + CJK runs handled separately as bigrams.
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CJK_RUN_RE = re.compile(r"[一-鿿]+")

# English stopwords. Hardcoded (rather than nltk.download('stopwords')) so
# `tokenize` works offline / in CI / on first checkout. Sourced from NLTK's
# English list; words that could plausibly carry signal in a course-search
# context (e.g. "again" → repeat-able? "before"/"after" → pre/co-req hints)
# are kept conservatively. If you change this list, re-run
# scripts/smoke_hybrid_compare.py to confirm the real-min vs adv-max gap.
STOPWORDS: frozenset[str] = frozenset({
    "a", "about", "all", "also", "am", "an", "and", "any", "are", "as",
    "at", "be", "been", "being", "both", "but", "by", "can", "could",
    "did", "do", "does", "doing", "down", "during", "each", "few", "for",
    "from", "further", "had", "has", "have", "having", "he", "her",
    "here", "hers", "herself", "him", "himself", "his", "how", "i", "if",
    "in", "into", "is", "it", "its", "itself", "just", "me", "more",
    "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on",
    "once", "only", "or", "other", "our", "ours", "ourselves", "out",
    "over", "own", "s", "same", "she", "should", "so", "some", "such",
    "t", "than", "that", "the", "their", "theirs", "them", "themselves",
    "then", "there", "these", "they", "this", "those", "through", "to",
    "too", "under", "until", "up", "very", "was", "we", "were", "what",
    "when", "where", "which", "while", "who", "whom", "why", "will",
    "with", "would", "you", "your", "yours", "yourself", "yourselves",
})


def tokenize(text: str) -> list[str]:
    """Lowercase ASCII-alnum tokens (stopword-filtered) + CJK char bigrams.

    Bigrams over each contiguous CJK run ("机器学习" → 机器/器学/学习);
    a lone CJK char is kept as-is. Bag-of-words downstream, so ordering
    between the ASCII and CJK groups is irrelevant.
    """
    out = [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]
    for run in _CJK_RUN_RE.findall(text):
        if len(run) == 1:
            out.append(run)
        else:
            out.extend(run[i : i + 2] for i in range(len(run) - 1))
    return out


class _RetrieverLike(Protocol):
    """The vector retriever interface we depend on (Retriever or fake)."""

    def search(
        self,
        query: str,
        *,
        hard_filters: dict[str, Any] | None = ...,
        k: int = ...,
    ) -> list[SearchHit]: ...


class BM25Corpus:
    """In-memory BM25 index over courses.raw_text. Rebuilt on every restart
    (cheap: tokenize + score for ≤ 1000 docs is ~10ms).

    Construct via BM25Corpus.from_db(conn) for the standard path. The
    constructor takes a {course_id: raw_text} dict for tests.
    """

    def __init__(self, course_texts: dict[str, str]) -> None:
        self._course_ids: list[str] = list(course_texts.keys())
        self._vocab: set[str] = set()
        if not self._course_ids:
            self._bm25: BM25Okapi | None = None
            self._doc_tokens: list[frozenset[str]] = []
            return

        tokenized = [tokenize(course_texts[cid]) for cid in self._course_ids]
        # Replace any all-empty tokenization with a single sentinel so BM25Okapi
        # doesn't crash on empty docs (e.g. raw_text=null edge case).
        tokenized = [toks if toks else ["__empty__"] for toks in tokenized]
        self._bm25 = BM25Okapi(tokenized)
        # Per-doc token sets: search() needs "does this doc contain ANY query
        # token" as a membership test. Score>0 can't serve that — BM25 IDF
        # degenerates to 0 for terms in half the corpus (e.g. N=2, n=1), so a
        # genuine token match can legitimately score 0.0.
        self._doc_tokens = [frozenset(toks) for toks in tokenized]
        for toks in tokenized:
            self._vocab.update(toks)

    @classmethod
    def from_db(
        cls,
        conn: sqlite3.Connection,
        *,
        status_filter: str | None = ELIGIBLE_STATUS,
    ) -> BM25Corpus:
        """Build a BM25 corpus from courses.raw_text + search_expansion.

        Default status_filter='indexed' matches what the retriever returns —
        BM25 + vector see the same eligible row set, otherwise rankings
        could diverge.

        search_expansion (ADR-0020, doc2query + zh keywords) joins the BM25
        document ONLY — dense embeddings stay computed from raw_text, so
        expansion can widen lexical recall but never perturbs the vector
        leg. Column may be absent on pre-migration DBs → plain raw_text.
        """
        cols = {row[1] for row in conn.execute("PRAGMA table_info(courses)")}
        text_expr = "COALESCE(raw_text, '')"
        if "search_expansion" in cols:
            text_expr += " || ' ' || COALESCE(search_expansion, '')"
        sql = f"SELECT course_id, {text_expr} AS raw_text FROM courses"
        params: list[Any] = []
        if status_filter is not None:
            sql += " WHERE status = ?"
            params.append(status_filter)
        rows = conn.execute(sql, params).fetchall()
        return cls({r["course_id"]: r["raw_text"] for r in rows})

    def search(
        self,
        query: str,
        *,
        k: int = 10,
        allowed_ids: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Top-k BM25 hits as [(course_id, score), ...] sorted desc.

        Returns [] if NO query token appears in the corpus vocab. This is
        a stronger "no match" signal than score==0, which can also occur
        for tiny corpora where BM25 IDF degenerates (N=2, n=1 → log(1)=0).

        Only docs sharing ≥1 token with the query are returned — argsort
        alone would pad the result with zero-overlap docs up to k, and those
        then siphon RRF mass from genuine hits during fusion.

        `allowed_ids` (optional) restricts the ranking to that course-id set
        BEFORE the top-k cut — used when hard filters narrowed the corpus,
        so a doc that passes the filter but ranks #61 globally still makes
        the within-filter top-k.
        """
        if self._bm25 is None or not self._course_ids:
            return []

        tokens = tokenize(query)
        if not tokens:
            return []

        # Vocab-overlap check: distinguishes "no match possible" from
        # "match exists but BM25 IDF happens to score it zero".
        if not any(t in self._vocab for t in tokens):
            return []

        token_set = set(tokens)
        scores = self._bm25.get_scores(tokens)
        eligible = [
            i
            for i in range(len(self._course_ids))
            if self._doc_tokens[i] & token_set
            and (allowed_ids is None or self._course_ids[i] in allowed_ids)
        ]
        eligible.sort(key=lambda i: -scores[i])
        return [
            (self._course_ids[i], float(scores[i]))
            for i in eligible[:k]
        ]

    @property
    def count(self) -> int:
        return len(self._course_ids)


def reciprocal_rank_fusion(
    rankings: list[list[str]],
    *,
    k: int = DEFAULT_RRF_K,
) -> dict[str, float]:
    """Combine N ranked id-lists via RRF. `k` damps the contribution of
    low-rank items; default 60 is from the original RRF paper."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, item_id in enumerate(ranking, start=1):
            fused[item_id] = fused.get(item_id, 0.0) + 1.0 / (k + rank)
    return fused


def convex_combination(
    vec_pairs: list[tuple[str, float]],
    bm25_pairs: list[tuple[str, float]],
    *,
    weight_vec: float,
) -> dict[str, float]:
    """Score-aware fusion: weight_vec·minmax(vec) + (1-weight_vec)·minmax(bm25).

    Bruch et al. (TOIS 2023, arXiv:2210.11934): a tuned convex combination
    of NORMALIZED scores beats RRF in- and out-of-domain — RRF's rank-only
    view throws away the score magnitudes that distinguish a confident
    dense match from barely-made-the-cutoff noise. Min-max is per leg per
    query (intra-pool); a doc missing from one leg contributes 0 from that
    leg (it wasn't competitive there). Degenerate one-item / all-equal legs
    normalize to 1.0 — top of a leg is full evidence, however small the
    pool.
    """
    if not 0.0 <= weight_vec <= 1.0:
        raise ValueError(f"weight_vec must be in [0, 1], got {weight_vec}")

    def _minmax(pairs: list[tuple[str, float]]) -> dict[str, float]:
        if not pairs:
            return {}
        vals = [s for _, s in pairs]
        lo, hi = min(vals), max(vals)
        if hi - lo < 1e-12:
            return {cid: 1.0 for cid, _ in pairs}
        return {cid: (s - lo) / (hi - lo) for cid, s in pairs}

    n_vec = _minmax(vec_pairs)
    n_bm25 = _minmax(bm25_pairs)
    return {
        cid: weight_vec * n_vec.get(cid, 0.0)
        + (1.0 - weight_vec) * n_bm25.get(cid, 0.0)
        for cid in n_vec.keys() | n_bm25.keys()
    }


class HybridRetriever:
    """RRF combination of vector + BM25 retrieval.

    Mirrors Retriever.search interface (returns list[SearchHit]) so it's a
    drop-in replacement. hard_filters apply to both legs:
      - vector leg: pushed through to underlying retriever's SQLite filter
      - BM25 leg: scoped to the same SQLite-filtered id set (via the
        retriever's filter_ids when available; intersection with the vector
        candidate set as fallback for fakes)
    """

    def __init__(
        self,
        *,
        vector_retriever: _RetrieverLike,
        bm25_corpus: BM25Corpus,
        course_repo: CourseRepository,
        rrf_k: int = DEFAULT_RRF_K,
        candidate_multiplier: int = 3,
        query_expander: Any | None = None,
        fusion_mode: str = "rrf",
        fusion_weight: float = 0.5,
    ) -> None:
        self._vector = vector_retriever
        self._bm25 = bm25_corpus
        self._course_repo = course_repo
        self._rrf_k = rrf_k
        self._candidate_multiplier = candidate_multiplier
        # ADR-0022: "rrf" (rank-only, ADR-0001 era default) or "convex"
        # (score-aware min-max combination; weight = vector leg's share).
        self._fusion_mode = fusion_mode
        self._fusion_weight = fusion_weight
        # ADR-0020: optional Callable[[str], str] applied to the query for
        # the RETRIEVAL legs only (e.g. rag.acronyms.expand_query). Caller's
        # reranker + rejection gate keep seeing the original query, so the
        # expander can only add recall, never shift relevance judgment.
        self._query_expander = query_expander
        # Per-leg top scores from the LAST search() call. The calibrated
        # rejection gate (rag/rejection.py, ADR-0018) reads these — the
        # fused RRF score deliberately erases score magnitudes, but the
        # gate needs the raw lexical/dense evidence the cross-encoder
        # doesn't see. Instance attribute is safe: routes get a fresh
        # HybridRetriever per request (api/dependencies.py).
        self.last_diagnostics: dict[str, float] | None = None

    def search(
        self,
        query: str,
        *,
        hard_filters: dict[str, Any] | None = None,
        k: int = 10,
    ) -> list[SearchHit]:
        candidate_k = k * self._candidate_multiplier
        if self._query_expander is not None:
            query = self._query_expander(query)

        # Leg 1: vector. Prefer the ID-only path (no per-candidate SQLite
        # rehydration — fusion only needs IDs; hydration happens once on the
        # fused top-k below). Fall back to .search() for retriever fakes
        # that only implement the SearchHit interface.
        search_ids = getattr(self._vector, "search_ids", None)
        if callable(search_ids):
            vec_pairs = search_ids(query, hard_filters=hard_filters, k=candidate_k)
        else:
            vec_pairs = [
                (h.course.course_id, h.score)
                for h in self._vector.search(
                    query, hard_filters=hard_filters, k=candidate_k,
                )
            ]
        vec_ids = [cid for cid, _ in vec_pairs]

        # Leg 2: BM25, scoped to the SAME filtered set as the vector leg when
        # hard_filters are active. The old approach intersected BM25 output
        # with the vector top-(k*3) — which silently dropped a course that
        # passes the filter and ranks #1 on BM25 but #61 on vector. Fakes
        # without filter_ids keep the old (lossier) intersection behavior.
        allowed: set[str] | None = None
        if hard_filters:
            filter_ids = getattr(self._vector, "filter_ids", None)
            allowed = (
                set(filter_ids(hard_filters)) if callable(filter_ids) else set(vec_ids)
            )
        bm25_hits = self._bm25.search(query, k=candidate_k, allowed_ids=allowed)
        bm25_ids = [cid for cid, _ in bm25_hits]

        self.last_diagnostics = {
            "vec_top": float(vec_pairs[0][1]) if vec_pairs else 0.0,
            "bm25_top": float(bm25_hits[0][1]) if bm25_hits else 0.0,
        }

        if not vec_ids and not bm25_ids:
            return []

        if self._fusion_mode == "convex":
            fused = convex_combination(
                vec_pairs, bm25_hits, weight_vec=self._fusion_weight,
            )
        else:
            fused = reciprocal_rank_fusion(
                [vec_ids, bm25_ids],
                k=self._rrf_k,
            )

        top_k = sorted(fused, key=lambda c: -fused[c])[:k]
        if not top_k:
            return []
        # Batch fetch — avoids N+1 (was k SELECTs in a list comprehension).
        courses = self._course_repo.get_batch(top_k)
        return [
            SearchHit(course=courses[cid], score=fused[cid])
            for cid in top_k
            if cid in courses  # skip dangling refs (alias points at vanished course)
        ]


__all__ = [
    "DEFAULT_RRF_K",
    "BM25Corpus",
    "HybridRetriever",
    "convex_combination",
    "reciprocal_rank_fusion",
    "tokenize",
]
