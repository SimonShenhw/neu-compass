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

Z-score blending (PLAN v2.2 §3.5):
  `rerank_blend_hits` linearly combines the upstream RRF score with the
  reranker sigmoid after standardizing each leg per call. α picks a point
  on the {pure-RRF, pure-reranker} continuum. Z-score over Min-Max because
  the reranker's bimodal sigmoid distribution would otherwise be compressed
  at the top of the pool, exactly where ranking discrimination matters.
"""

from __future__ import annotations

from typing import Callable, TypeVar

from rag.retriever import SearchHit

DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"

T = TypeVar("T")


class CrossEncoderReranker:
    """bge-reranker-v2-m3 wrapper. Lazy-loaded; caller manages threading.

    `compile_mode` (Week 9 Day 2 hook): when set (e.g. "default",
    "reduce-overhead"), the inner transformers model is wrapped with
    torch.compile after load. Roughly 10-25% latency reduction on RTX 5090
    in our 20-pair rerank batch; compilation cost (~5-30s) is paid once
    during lifespan warmup. NO effect when caller goes through OnnxReranker
    instead — torch.compile is PyTorch-only.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_RERANKER_MODEL,
        *,
        device: str = "cuda",
        use_fp16: bool = True,
        compile_mode: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.use_fp16 = use_fp16
        self.compile_mode = compile_mode
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

        if self.compile_mode:
            try:
                model = torch.compile(model, mode=self.compile_mode)
            except Exception as e:  # noqa: BLE001 — best-effort wrap
                print(f"warning: torch.compile failed for reranker: {e}")

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


def zscore_blend(
    rrf_scores: list[float],
    rerank_scores: list[float],
    alpha: float,
) -> list[float]:
    """Linearly blend two scoring signals after Z-score normalization.

    Returns per-item blended score in input order. Higher = more relevant.

    Args:
      rrf_scores: upstream fusion scores (e.g. HybridRetriever .score)
      rerank_scores: cross-encoder sigmoid scores in [0, 1]
      alpha: weight on the RRF leg. α=1.0 → pure RRF ordering;
             α=0.0 → pure reranker ordering. Must be in [0, 1].

    Standardization is per call (mean+std over the input pool), not against
    any global distribution — the blend is intra-pool. If a leg has zero
    variance (all equal), its Z-score is 0 and the other leg drives ordering.

    PLAN v2.2 §3.5 locks Z-score over Min-Max: Min-Max compresses the
    bge-reranker bimodal sigmoid distribution at the top of the pool
    (where discrimination matters most) and amplifies RRF's narrow score
    range arbitrarily. Z-score gives clean α semantics: α=0.5 strictly
    means "equal weight on both standardized signals".
    """
    if len(rrf_scores) != len(rerank_scores):
        raise ValueError(
            f"score list length mismatch: "
            f"rrf={len(rrf_scores)} rerank={len(rerank_scores)}"
        )
    if not 0.0 <= alpha <= 1.0:
        raise ValueError(f"alpha must be in [0, 1], got {alpha}")
    if not rrf_scores:
        return []

    import numpy as np  # noqa: PLC0415  — local import keeps import-time cost low

    rrf = np.asarray(rrf_scores, dtype=np.float64)
    rer = np.asarray(rerank_scores, dtype=np.float64)

    # Variance floor avoids amplifying float64 round-off into spurious z-scores.
    # Example: [0.1, 0.1, 0.1].std() is ~1e-17 (not exactly 0) because 0.1 isn't
    # exactly representable; a strict `> 0` check would divide noise by noise
    # and yield z-scores of magnitude 1 from a constant input.
    _STD_EPSILON = 1e-12

    rrf_std = float(rrf.std())
    rer_std = float(rer.std())
    rrf_z = (rrf - rrf.mean()) / rrf_std if rrf_std > _STD_EPSILON else np.zeros_like(rrf)
    rer_z = (rer - rer.mean()) / rer_std if rer_std > _STD_EPSILON else np.zeros_like(rer)

    blended = alpha * rrf_z + (1.0 - alpha) * rer_z
    return [float(b) for b in blended]


def rerank_blend_hits(
    query: str,
    hits: list[SearchHit],
    reranker: CrossEncoderReranker,
    *,
    fetch_text: Callable[[str], str | None],
    blend_alpha: float,
    top_k: int | None = None,
) -> list[SearchHit]:
    """Z-score blend the upstream score in `hits[i].score` with the reranker
    sigmoid, then sort desc.

    Caller responsibilities:
      - hits MUST come from HybridRetriever (or anything where .score is the
        upstream fusion score). Blending is meaningless if .score is already
        a reranker score.
      - For PLAN §3.4 rejection layer, use `rerank_blend_with_rejection`
        instead — it shares the single reranker pass with the rejection
        gate, avoiding a redundant scoring call.

    Returns SearchHits with `.score` set to the blended Z-score (typically
    -2 to +2; centered on 0; not in [0, 1]). Use the raw reranker sigmoid
    for absolute-threshold decisions.
    """
    if not hits:
        return []

    pairs: list[tuple[SearchHit, str]] = []
    for hit in hits:
        text = fetch_text(hit.course.course_id) or hit.course.primary_name
        pairs.append((hit, text))

    rrf_scores = [hit.score for hit, _ in pairs]
    texts = [text for _, text in pairs]
    rerank_scores = reranker.score(query, texts)

    blended = zscore_blend(rrf_scores, rerank_scores, alpha=blend_alpha)

    indexed = list(zip([hit for hit, _ in pairs], blended))
    indexed.sort(key=lambda t: -t[1])
    if top_k is not None:
        indexed = indexed[:top_k]
    return [SearchHit(course=hit.course, score=score) for hit, score in indexed]


def rerank_blend_with_rejection(
    query: str,
    hits: list[SearchHit],
    reranker: CrossEncoderReranker,
    *,
    fetch_text: Callable[[str], str | None],
    blend_alpha: float,
    reject_threshold: float,
    top_k: int | None = None,
) -> tuple[list[SearchHit], dict[str, object]]:
    """Combined rejection-and-blend pass for PLAN v2.2 §3.4 + §3.5.

    Two questions in one reranker call:
      1. **Reject?** If `max(raw_sigmoid) < reject_threshold`, the query
         has no good answer — return ([], {"rejected": True, ...}).
         Rejection is decided on RAW sigmoid (not blended z-score) because
         it's an absolute-confidence question, not a ranking question.
      2. **Order?** If accepted, Z-score blend the upstream RRF score with
         the same raw sigmoid (alpha = blend_alpha), sort desc, truncate
         to top_k, return as SearchHits with blended z-score in `.score`.

    Returns:
      (hits, meta) where meta is one of:
        {"rejected": True, "reason": str, "max_sigmoid": float,
         "n_candidates": int}
        {"rejected": False, "max_sigmoid": float,
         "n_above_threshold": int, "n_candidates": int}

    Single reranker pass — score(query, texts) is called once. The
    rejection gate and the blend share the same sigmoid output.
    """
    n = len(hits)
    if n == 0:
        return [], {
            "rejected": False,
            "reason": "no_candidates",
            "max_sigmoid": 0.0,
            "n_candidates": 0,
            "n_above_threshold": 0,
        }

    pairs: list[tuple[SearchHit, str]] = []
    for hit in hits:
        text = fetch_text(hit.course.course_id) or hit.course.primary_name
        pairs.append((hit, text))

    rrf_scores = [hit.score for hit, _ in pairs]
    texts = [text for _, text in pairs]
    rerank_scores = reranker.score(query, texts)

    max_sig = max(rerank_scores) if rerank_scores else 0.0
    n_above = sum(1 for s in rerank_scores if s >= reject_threshold)

    if max_sig < reject_threshold:
        return [], {
            "rejected": True,
            "reason": (
                f"max_reranker_sigmoid {max_sig:.3f} < threshold {reject_threshold}"
            ),
            "max_sigmoid": float(max_sig),
            "n_candidates": n,
            "n_above_threshold": 0,
        }

    blended = zscore_blend(rrf_scores, rerank_scores, alpha=blend_alpha)
    indexed = list(zip([hit for hit, _ in pairs], blended))
    indexed.sort(key=lambda t: -t[1])
    if top_k is not None:
        indexed = indexed[:top_k]

    return (
        [SearchHit(course=hit.course, score=score) for hit, score in indexed],
        {
            "rejected": False,
            "max_sigmoid": float(max_sig),
            "n_candidates": n,
            "n_above_threshold": n_above,
        },
    )


__all__ = [
    "DEFAULT_RERANKER_MODEL",
    "CrossEncoderReranker",
    "rerank_blend_hits",
    "rerank_blend_with_rejection",
    "rerank_pairs",
    "rerank_search_hits",
    "zscore_blend",
]
