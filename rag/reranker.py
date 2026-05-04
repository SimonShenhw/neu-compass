"""Cross-encoder reranker (bge-reranker-v2-m3) — Week 6 PLAN §4.4 P1.

Why a cross-encoder on top of vector + BM25:
  Vector + BM25 (RRF) gives broad recall but ranking accuracy degrades
  on STEM-heavy text where bge-m3 dense scores cluster in 0.4-0.7 (see
  docs/rag_smoke_results.md §6). A cross-encoder scores each (query,
  candidate) pair jointly through one transformer pass, producing a
  much sharper ranking signal — at ~50ms/batch latency cost.

Pipeline insertion (caller decides):
    candidates = hybrid_retriever.search(query, k=20)   # broad recall
    reranked   = reranker.rerank_search_hits(           # narrow precision
        query, candidates, fetch_text=fetch_raw_text, top_k=10,
    )

The pure scoring API is `score(query, candidates: list[str]) -> list[float]`
— testable without the SQLite layer. `rerank_search_hits` is a
SearchHit-aware wrapper that pulls raw_text via a caller-provided
fetch_text callable; tests pass a dict-backed fetcher.

Lazy load: the FlagReranker model (~600MB on disk, ~1.5s GPU init) is
NOT loaded at import time. First .score() call triggers it.
"""

from __future__ import annotations

from typing import Callable, TypeVar

from rag.retriever import SearchHit

DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"

T = TypeVar("T")


class CrossEncoderReranker:
    """bge-reranker-v2-m3 wrapper. Lazy-loaded; caller manages threading."""

    def __init__(
        self,
        model_name: str = DEFAULT_RERANKER_MODEL,
        *,
        device: str = "cuda",
        use_fp16: bool = True,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.use_fp16 = use_fp16
        self._model: object | None = None

    def _load(self) -> tuple[object, object]:
        """Load tokenizer + model via raw transformers (HuggingFace).

        We bypass FlagEmbedding.FlagReranker because its older code path
        calls `tokenizer.prepare_for_model` which has been removed from
        transformers >= 4.30. Going through AutoModelForSequenceClassification
        gives us the same bge-reranker-v2-m3 weights without that coupling.
        """
        if self._model is not None:
            return self._tokenizer, self._model  # type: ignore[return-value]

        import torch  # noqa: PLC0415
        from transformers import (  # noqa: PLC0415
            AutoModelForSequenceClassification,
            AutoTokenizer,
        )

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
        model.eval()
        if self.device == "cuda" and torch.cuda.is_available():
            model = model.to("cuda")
            if self.use_fp16:
                model = model.half()
        self._model = model
        self._torch = torch  # cache for score()
        return self._tokenizer, self._model

    def score(self, query: str, candidates: list[str]) -> list[float]:
        """Score each candidate against the query. Higher = more relevant.

        Empty input → empty output. Output is sigmoid-normalized to [0, 1]
        so absolute thresholds become meaningful (a future "no clear match"
        rejection layer can use ~0.5 as the cut).
        """
        if not candidates:
            return []
        tokenizer, model = self._load()
        torch = self._torch  # type: ignore[attr-defined]

        inputs = tokenizer(
            [query] * len(candidates),
            candidates,
            padding=True,
            truncation=True,
            return_tensors="pt",
            max_length=512,
        )
        if self.device == "cuda" and torch.cuda.is_available():
            inputs = {k: v.to("cuda") for k, v in inputs.items()}

        with torch.no_grad():
            logits = model(**inputs).logits.view(-1).float()
            probs = torch.sigmoid(logits)
        return [float(p) for p in probs.cpu().tolist()]


def rerank_pairs(
    query: str,
    pairs: list[tuple[T, str]],
    reranker: CrossEncoderReranker,
    *,
    top_k: int | None = None,
) -> list[tuple[T, float]]:
    """Score (payload, text) pairs and return them sorted by reranker
    score desc. Pure utility — keeps the reranker generic over payload type.

    `top_k=None` keeps all input pairs; otherwise truncates after sort.
    """
    if not pairs:
        return []
    payloads, texts = zip(*pairs)
    scores = reranker.score(query, list(texts))
    scored = list(zip(payloads, scores))
    scored.sort(key=lambda t: -t[1])
    if top_k is not None:
        scored = scored[:top_k]
    return scored


def rerank_search_hits(
    query: str,
    hits: list[SearchHit],
    reranker: CrossEncoderReranker,
    *,
    fetch_text: Callable[[str], str | None],
    top_k: int | None = None,
) -> list[SearchHit]:
    """Rerank SearchHits using each hit's raw_text (resolved via
    `fetch_text(course_id)`). Hits whose fetch_text returns None or empty
    fall back to `course.primary_name` so they still get scored.

    Returns SearchHits with the cross-encoder score in `.score` (replacing
    the upstream RRF fused score). Caller relies on this score going
    forward, e.g. for absolute-threshold "no clear match" decisions.
    """
    if not hits:
        return []

    pairs: list[tuple[SearchHit, str]] = []
    for hit in hits:
        text = fetch_text(hit.course.course_id) or hit.course.primary_name
        pairs.append((hit, text))

    scored = rerank_pairs(query, pairs, reranker, top_k=top_k)
    return [SearchHit(course=hit.course, score=score) for hit, score in scored]


__all__ = [
    "DEFAULT_RERANKER_MODEL",
    "CrossEncoderReranker",
    "rerank_pairs",
    "rerank_search_hits",
]
