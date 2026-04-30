"""Push LLM-discovered potential aliases into the human-review queue.

Decoupled by design: this module doesn't know how candidates are produced
(LLM extraction output / heuristic regex / manual entry — all valid). It
takes pre-built AliasCandidate objects and queues them with proper
defaults (source=llm_inferred, review_status=pending, evidence excerpt).

PLAN §1.4 L3 source layer is exactly this path: anything LLM infers
defaults to pending and waits for human curator approval before it leaks
into v_course_lookup.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from db.alias_repository import AliasRepository
from schemas.alias import Alias, AliasReviewStatus, AliasSource, AliasType

DEFAULT_CONFIDENCE_THRESHOLD = 0.4

# Limit how much source text we store as evidence (PLAN §1.4 docstring says
# "前 500 字") — keeps the column bounded and the curator UI readable.
MAX_EVIDENCE_LEN = 500


class AliasCandidate(BaseModel):
    """A potential alias surfaced by an LLM extraction or heuristic scan.

    Pre-persistence shape — distinct from `Alias` so the detector can validate
    candidate shape independently from the persisted form (e.g., we may later
    add candidate-only fields like `seen_count` for de-dup ranking).
    """

    model_config = ConfigDict(extra="forbid")

    alias_text: str = Field(min_length=1)
    alias_type: AliasType
    primary_course_id: str = Field(min_length=1, description="Course this likely refers to")
    confidence: float = Field(ge=0.0, le=1.0)
    source_excerpt: str = Field(min_length=1, description="Text fragment that triggered this guess")


def queue_candidates(
    candidates: list[AliasCandidate],
    *,
    repo: AliasRepository,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> dict[str, int]:
    """Queue LLM-inferred aliases as pending. Returns counts:
        {'queued': N, 'skipped_low_confidence': N, 'skipped_already_known': N}

    Skip rules:
      1. confidence < threshold      — signal too weak, don't waste curator time
      2. already exists for this course (any status) — caller already proposed it
      3. already resolves to this course (via primary code or approved alias)
    """
    counts = {
        "queued": 0,
        "skipped_low_confidence": 0,
        "skipped_already_known": 0,
    }

    for cand in candidates:
        if cand.confidence < confidence_threshold:
            counts["skipped_low_confidence"] += 1
            continue

        if _already_known(cand, repo):
            counts["skipped_already_known"] += 1
            continue

        alias = Alias(
            alias_text=cand.alias_text,
            alias_type=cand.alias_type,
            primary_course_id=cand.primary_course_id,
            source=AliasSource.LLM_INFERRED,
            review_status=AliasReviewStatus.PENDING,
            confidence=cand.confidence,
            evidence=cand.source_excerpt[:MAX_EVIDENCE_LEN],
        )
        result = repo.add_or_skip(alias)
        if result is not None:
            counts["queued"] += 1
        else:
            # add_or_skip dedups on (text, type, primary) — a parallel queue
            # of identical candidates from different sources is fine.
            counts["skipped_already_known"] += 1

    return counts


def _already_known(cand: AliasCandidate, repo: AliasRepository) -> bool:
    """Check if this candidate would be a duplicate or already-resolvable.

    Two distinct conditions:
      a. Existing row in course_aliases with same (text, primary, any status).
      b. Term already resolves to this course via v_course_lookup
         (matches primary_code OR an approved alias).
    """
    existing = repo.find_by_text(cand.alias_text)
    if any(a.primary_course_id == cand.primary_course_id for a in existing):
        return True

    resolved = repo.resolve(cand.alias_text)
    return cand.primary_course_id in resolved


__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "MAX_EVIDENCE_LEN",
    "AliasCandidate",
    "queue_candidates",
]
