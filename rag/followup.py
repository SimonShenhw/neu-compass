"""Follow-up (anaphora) detection for conversational retrieval.

The /chat endpoint is stateless per request; the UI sends the previous
turn's evidence as `context_course_ids`. This module decides whether the
NEW query is a follow-up about those courses ("这门课作业量大吗?",
"what does it cover?") versus a fresh query that should run the normal
alias → program → hybrid pipeline.

Design: cheap deterministic tier first (house style — same philosophy as
the alias tier and the regex Layer-2 filter). A query is a follow-up iff
it contains a referent expression AND carries no course signal of its own
(no course-code-shaped token). An LLM query-rewrite fallback is a known
upgrade path once query_log shows real follow-ups this heuristic misses
(mine for: matched_via in (rejected, hybrid-noise) where the previous
turn had evidence).

Pure functions, no I/O — mirror query_normalizer's testing story.
"""

from __future__ import annotations

import re

# Course-code-shaped token = the query names its own course; never treat
# as a follow-up even if a referent word also appears ("AAI 6620 和这门课
# 比怎么样" names a NEW course — let retrieval handle it; history still
# reaches the answer prompt for the comparison).
# 2-4 letters + 3-4 digits, space optional — matches the alias tier's
# tolerance for "cs5800" / "CS 5800" / "AAI6620".
_CODE_RE = re.compile(r"[A-Za-z]{2,4}\s?\d{3,4}", re.ASCII)

# Referent expressions that point at the previous turn's course(s).
# Conservative on purpose: bare "它"/"it" appears in compound words and
# idioms less often than 这门课-style noun phrases, but the surrounding
# no-code requirement keeps false positives cheap (worst case: context
# courses get fed to the LLM alongside an answerable query).
_REFERENT_RE = re.compile(
    r"(?:这门课|那门课|这课|该课|这门|此课|这[个两三]课|它|"
    r"上面(?:这|那|的)|刚才(?:这|那|的)|前面(?:这|那|的)|"
    r"\bthis (?:course|class|one)\b|\bthat (?:course|class|one)\b|"
    r"\bthe (?:course|class)\b|\bit\b|\bthem\b|\bthese\b|\bboth\b)",
    re.IGNORECASE,
)


def is_followup_query(query: str) -> bool:
    """True iff `query` references the previous turn's course(s) and names
    no course of its own. Caller must also require non-empty context ids —
    a referent with nothing to refer to is just a vague query for the
    normal pipeline (whose gate will handle it)."""
    if not query or not query.strip():
        return False
    if _CODE_RE.search(query):
        return False
    return bool(_REFERENT_RE.search(query))


__all__ = ["is_followup_query"]
