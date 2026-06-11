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

# Fitted on the NAS 2026-06-11 by scripts/calibrate_rejection.py against
# the production stack (openvino int8, pool=10): n=90 gate-path queries
# (50 answerable synthesized from catalog / 40 unanswerable, 8 categories),
# AUC 0.9795 vs 0.9605 for max-sigmoid alone. Run report:
# NAS /data/rejection_calibration.json + ADR-0018. Do not hand-edit —
# re-run the script if the embedder/reranker/corpus changes.
DEFAULT_COEFFICIENTS: dict[str, float] = {
    "bias": -4.4408,
    "w_logit_sigmoid": 0.5844,
    "w_log1p_bm25": 1.5115,
    "w_vec_top": 4.3305,
    "w_code_miss": -4.5121,
}

REJECT_BELOW = 0.3
"""Reject when P(answerable) < this. NOT the LR midpoint (0.5) on purpose:
the operating rule is "maximize unanswerable catch subject to ZERO
false-rejects on the calibration answerable set", which the calibration
grid resolves to 0.3 (false-rej 0/50, caught 31/40; at 0.5 it's 1/50 and
36/40). Product asymmetry: refusing a real student query is worse than
returning weak results for an unanswerable one — /chat's grounded prompt
still answers "not in catalog" for the latter. Live feature probes show
the residual irreducible overlap is q042-style homework-admin (p≈0.25,
reject) vs q018-style theory jargon (p≈0.20, sadly also rejected) — see
ADR-0018 for the measured distribution. Adjust only with a re-fit."""

_LOGIT_EPS = 1e-6  # max_sigmoid=0.0 → logit ≈ -13.8 instead of -inf


@dataclass(frozen=True)
class RejectionFeatures:
    """Inputs the gate fuses. All cheap — computed from values the request
    already produced (no extra model calls)."""

    max_sigmoid: float
    bm25_top: float
    vec_top: float
    code_pattern_miss: bool


def query_has_code_pattern(query: str) -> bool:
    """True iff the query contains a course-code-shaped token (excluding
    calendar phrases like "fall 2025"). Callers on the hybrid path combine
    this with the fact that alias resolution already missed (or the request
    would have returned at the alias tier)."""
    return any(
        m.group(1).lower() not in _NOT_DEPT_WORDS
        for m in _COURSE_CODE_RE.finditer(query)
    )


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
        """P(answerable) ∈ (0, 1)."""
        z = (
            self._c["bias"]
            + self._c["w_logit_sigmoid"] * _logit(f.max_sigmoid)
            + self._c["w_log1p_bm25"] * math.log1p(max(f.bm25_top, 0.0))
            + self._c["w_vec_top"] * f.vec_top
            + self._c["w_code_miss"] * (1.0 if f.code_pattern_miss else 0.0)
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
            f"vec_top={f.vec_top:.3f}, code_miss={f.code_pattern_miss})"
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

    def gate_fn(sigmoids: list[float]) -> tuple[bool, str]:
        f = RejectionFeatures(
            max_sigmoid=max(sigmoids) if sigmoids else 0.0,
            bm25_top=bm25_top,
            vec_top=vec_top,
            code_pattern_miss=code_miss,
        )
        reject, _, reason = g.decide(f)
        return reject, reason

    return gate_fn


__all__ = [
    "DEFAULT_COEFFICIENTS",
    "REJECT_BELOW",
    "CalibratedRejectionGate",
    "RejectionFeatures",
    "build_gate_fn",
    "query_has_code_pattern",
]
