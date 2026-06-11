"""Calibrated rejection gate — ADR-0018 (2026-06 RAG quality pass).

Why this exists: the ADR-0016 gate is `max(reranker sigmoid) < 0.05`.
Its own calibration data shows the limit of that design — answerable
theory-jargon queries (q018 "VC dimension PAC learning", max σ 0.0051)
score BELOW adversarial fake course codes (q040 "CS 0001", max σ 0.0278).
The two distributions interleave in [0.005, 0.03], so NO scalar threshold
on max-sigmoid can separate them: at T=0.05 production false-rejects 4/38
real queries (measured live, eval/api_eval_pool10_int8.json).

The fix is information, not threshold-tuning. The cross-encoder under-rates
exact-jargon matches, but the retrieval legs it sits on do not:
q013 "graph algorithms BFS DFS shortest paths" has a huge BM25 score
against the right course's raw_text. Conversely "CS 0001" looks like a
course code, ALREADY failed alias resolution (or it would never reach the
gate), and matches nothing lexically specific. The gate therefore fuses:

    x1 = logit(max_sigmoid)      cross-encoder confidence (log-odds scale)
    x2 = log1p(bm25_top)         lexical evidence from the BM25 leg
    x3 = vec_top                 dense cosine of the best vector hit
    x4 = code_pattern_miss       query looks like "DEPT 1234" but the alias
                                 tier missed → likely nonexistent course

into P(answerable) = sigmoid(w·x + b), rejecting below REJECT_BELOW.

Coefficients are DATA-LOCKED by scripts/calibrate_rejection.py (run on the
NAS against the production OpenVINO stack; calibration set = synthesized
answerable queries built from catalog raw_text + synthesized unanswerable
queries across 8 UAEval4RAG-style categories; eval test_set v0.2 is fully
held out). Re-fit + update here if the embedder/reranker/corpus changes.
See docs/adr/0018-calibrated-rejection-gate.md.

Rollout: settings.rejection_mode selects "threshold" (ADR-0016 behavior,
default) or "calibrated" (this gate). NAS compose opts in explicitly.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable

# Queries shaped like a course code ("CS 5800", "aai9999", "CSYE 0042").
# Mirrors rag/query_normalizer's ASCII discipline: CJK must not extend the
# word boundary. 4-5 digits covers NEU's 4-digit codes + typo'd 5-digit.
_COURSE_CODE_RE = re.compile(r"\b([A-Za-z]{2,5})\s?\d{4,5}\b", re.ASCII)

# Words that satisfy the letters-then-digits shape but are calendar terms,
# not department codes: "fall 2025" / "spring 2026" must NOT count as a
# code-pattern miss — they're routine in perfectly answerable queries.
_NOT_DEPT_WORDS = frozenset({
    "fall", "spring", "summer", "winter", "autumn", "term", "year", "since",
})

# CJK detection for the cjk_dominant feature. The BM25 leg is ASCII-only
# (rag/hybrid.py documented limitation), so bm25_top is STRUCTURALLY zero
# for Chinese queries — without this feature the gate reads missing lexical
# evidence as negative evidence and false-rejects answerable 中文 queries
# (v0.3 eval first surfaced this: q091/q093). The coefficient learned from
# Chinese calibration samples compensates.
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")

# Fitted on the NAS 2026-06-11 (v5 run, post-ADR-0020 corpus) by
# scripts/calibrate_rejection.py against the production stack (openvino
# int8, pool=10, search_expansion live, acronym expander on). The ADR-0020
# doc-expansion field shifted the BM25 score distribution (gibberish like
# "keyboard mash" suddenly matched piano-course expansions and leaked
# through the v4 fit) — exactly the "corpus 大改" re-fit trigger. Note the
# fit's own response: w_log1p_bm25 dropped 0.96 → 0.78, the model learned
# lexical evidence is now mildly inflated. Calibration set: 50 easy + 15
# hard-jargon + 15 zh answerable / 50 unanswerable. Grid at p<0.4: 0/79
# false-rejects, 39/50 caught. Do not hand-edit — re-run the script if the
# embedder/reranker/quantization/corpus changes.
DEFAULT_COEFFICIENTS: dict[str, float] = {
    "bias": -1.6277,
    "w_logit_sigmoid": 0.5944,
    "w_log1p_bm25": 0.7822,
    "w_vec_top": 2.9949,
    "w_code_miss": -3.4026,
    "w_cjk": 1.7244,
}

REJECT_BELOW = 0.4
"""Reject when P(answerable) < this. NOT the LR midpoint (0.5) on purpose:
the operating rule is "maximize unanswerable catch subject to ZERO
false-rejects on the calibration answerable set", which the v4 grid
resolves to 0.4 (false-rej 0/80, caught 39/50; 0.5 trades a false-reject
for 2 more catches). Product asymmetry: refusing a real student query is
worse than returning weak results for an unanswerable one — /chat's
grounded prompt still answers "not in catalog" for the latter. Measured
residual on the held-out set: q018-style pure theory jargon (p≈0.26)
remains below the line; q042 homework-admin (p≈0.28) stays correctly
rejected. Adjust only together with a re-fit (ADR-0018)."""

_LOGIT_EPS = 1e-6  # max_sigmoid=0.0 → logit ≈ -13.8 instead of -inf


@dataclass(frozen=True)
class RejectionFeatures:
    """Inputs the gate fuses. All cheap — computed from values the request
    already produced (no extra model calls)."""

    max_sigmoid: float
    bm25_top: float
    vec_top: float
    code_pattern_miss: bool
    cjk_dominant: bool = False


def query_has_code_pattern(query: str) -> bool:
    """True iff the query contains a course-code-shaped token (excluding
    calendar phrases like "fall 2025"). Callers on the hybrid path combine
    this with the fact that alias resolution already missed (or the request
    would have returned at the alias tier)."""
    return any(
        m.group(1).lower() not in _NOT_DEPT_WORDS
        for m in _COURSE_CODE_RE.finditer(query)
    )


def query_is_cjk_dominant(query: str, *, threshold: float = 0.3) -> bool:
    """True iff CJK characters make up more than `threshold` of the query's
    non-space characters — the regime where the ASCII-only BM25 leg goes
    structurally silent and bm25_top=0 carries no signal."""
    chars = [c for c in query if not c.isspace()]
    if not chars:
        return False
    cjk = sum(1 for c in chars if _CJK_RE.match(c))
    return cjk / len(chars) > threshold


def _logit(p: float) -> float:
    p = min(max(p, _LOGIT_EPS), 1.0 - _LOGIT_EPS)
    return math.log(p / (1.0 - p))


class CalibratedRejectionGate:
    """Tiny logistic-regression gate over RejectionFeatures."""

    def __init__(
        self,
        coefficients: dict[str, float] | None = None,
        *,
        reject_below: float = REJECT_BELOW,
    ) -> None:
        self._c = dict(DEFAULT_COEFFICIENTS if coefficients is None else coefficients)
        self.reject_below = reject_below

    def probability(self, f: RejectionFeatures) -> float:
        """P(answerable) ∈ (0, 1).

        The BM25 term is an INTERACTION with (not cjk): lexical evidence
        only counts for non-CJK queries. Plain additive cjk couldn't
        express "BM25 is trustworthy only when the ASCII tokenizer saw the
        query" — fitting Chinese samples additively collapsed the BM25
        weight globally (1.51→0.07) and regressed the English queries BM25
        was rescuing. With the interaction, w_log1p_bm25 is learned on
        English-only variation and w_cjk absorbs the missing-evidence
        regime's baseline shift.
        """
        is_cjk = 1.0 if f.cjk_dominant else 0.0
        z = (
            self._c["bias"]
            + self._c["w_logit_sigmoid"] * _logit(f.max_sigmoid)
            + self._c["w_log1p_bm25"]
            * math.log1p(max(f.bm25_top, 0.0)) * (1.0 - is_cjk)
            + self._c["w_vec_top"] * f.vec_top
            + self._c["w_code_miss"] * (1.0 if f.code_pattern_miss else 0.0)
            + self._c.get("w_cjk", 0.0) * is_cjk
        )
        return 1.0 / (1.0 + math.exp(-z))

    def decide(self, f: RejectionFeatures) -> tuple[bool, float, str]:
        """Returns (reject, p_answerable, reason)."""
        p = self.probability(f)
        reject = p < self.reject_below
        reason = (
            f"calibrated_gate p_answerable={p:.3f} "
            f"{'<' if reject else '>='} {self.reject_below} "
            f"(max_sigmoid={f.max_sigmoid:.4f}, bm25_top={f.bm25_top:.2f}, "
            f"vec_top={f.vec_top:.3f}, code_miss={f.code_pattern_miss}, "
            f"cjk={f.cjk_dominant})"
        )
        return reject, p, reason


def build_gate_fn(
    *,
    query: str,
    bm25_top: float,
    vec_top: float,
    gate: CalibratedRejectionGate | None = None,
) -> Callable[[list[float]], tuple[bool, str]]:
    """Adapter for rerank_blend_with_rejection's `gate_fn` hook.

    The reranker pass produces the sigmoid list INSIDE that function, so the
    route can't precompute max_sigmoid — it hands this closure over instead.
    Leg diagnostics (bm25_top / vec_top) come from
    HybridRetriever.last_diagnostics; code_pattern_miss is derivable here
    because any request that reaches the hybrid path already missed alias.
    """
    g = gate or CalibratedRejectionGate()
    code_miss = query_has_code_pattern(query)
    cjk = query_is_cjk_dominant(query)

    def gate_fn(sigmoids: list[float]) -> tuple[bool, str]:
        f = RejectionFeatures(
            max_sigmoid=max(sigmoids) if sigmoids else 0.0,
            bm25_top=bm25_top,
            vec_top=vec_top,
            code_pattern_miss=code_miss,
            cjk_dominant=cjk,
        )
        reject, p, reason = g.decide(f)
        # Routes read this to scope the ADR-0019 rescue: a HIGH-CONFIDENCE
        # rejection (p far below the line) gets no LLM second opinion —
        # observed leak: Gemini's verdict flips run-to-run on borderline
        # gibberish, but the gate's p≈0.02 was never in doubt.
        gate_fn.last_p = p  # type: ignore[attr-defined]
        return reject, reason

    gate_fn.last_p = 1.0  # type: ignore[attr-defined]
    return gate_fn


__all__ = [
    "DEFAULT_COEFFICIENTS",
    "REJECT_BELOW",
    "CalibratedRejectionGate",
    "RejectionFeatures",
    "build_gate_fn",
    "query_has_code_pattern",
    "query_is_cjk_dominant",
]
