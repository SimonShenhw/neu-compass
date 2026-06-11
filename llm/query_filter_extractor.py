"""Extract structured filters (QueryFilters) from a natural-language query.

Layer 2 of the v3.0 RAG quality plan. Two paths:

1. **Regex (fast, free)**: detect explicit program-prefix tokens like
   `AAI`, `CS`, `DS`, `EECE`, `INFO`, `MATH`, ... when they appear as a
   bare word in the query. Catches the common case where a bilingual user
   types "我是 aai 专业 第一学期选啥" or "what should I take for CS major".
   Zero LLM cost, ~microseconds.

2. **LLM (slower, $$)**: when no explicit prefix is in the query but
   the query mentions a program / major name (e.g. "AI 专业", "数据科学",
   "I'm in the data analytics program"), an LLM call maps the program
   name to a prefix. ~200-500ms + Gemini token cost.

`extract_filters_adaptive` tries regex first; only calls the LLM if no
prefix was found AND a "program/major" keyword is present (heuristic gate
that skips the LLM for ~80% of queries that have neither signal).

The LLM hook is `Callable[[str], dict[str, object]]` for testability —
production passes a Gemini-backed extractor; tests pass a fake.
"""

from __future__ import annotations

import re
from typing import Callable

from schemas.query_filter import QueryFilters

# NEU graduate program prefixes we recognize. Sourced from the catalog scrape
# (231 unique department codes, but most users only mention these top-level
# prefixes). Add to this list as new programs surface in real query logs.
KNOWN_PROGRAM_PREFIXES: frozenset[str] = frozenset({
    "AAI",   # Applied AI
    "CS",    # Computer Science
    "CSYE",  # Computer Systems Engineering (Khoury / IS)
    "DS",    # Data Science
    "EECE",  # Electrical & Computer Engineering
    "INFO",  # Information Systems
    "ALY",   # Analytics
    "BINF",  # Bioinformatics
    "MATH",  # Mathematics
    "MGSC",  # Management Science
    "STAT",  # Statistics (graduate)
    "IE",    # Industrial Engineering
})

# Prefixes that double as ordinary English words. Case-insensitive matching
# turned "any info on machine learning courses" into program_prefix='INFO'
# (→ hard filter primary_code LIKE 'INFO %', silently hiding everything
# else). For these we only accept the ALL-CAPS spelling — a user naming the
# Information Systems program writes "INFO", prose writes "info".
AMBIGUOUS_PREFIXES: frozenset[str] = frozenset({"INFO", "IE"})

# `re.ASCII` so CJK chars don't act as word chars (same fix we made in
# query_normalizer for the '那aai' case). The {2,5} bound covers the
# longest known prefix (CSYE, BINF, MGSC = 4 chars; STAT = 4; we leave 5
# of headroom).
_PREFIX_RE = re.compile(
    r"\b(" + "|".join(sorted(KNOWN_PROGRAM_PREFIXES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE | re.ASCII,
)

# Heuristic that signals "user is talking about a program / major". When a
# regex-prefix scan misses but one of these words is present, it's worth
# spending an LLM call to try mapping a free-form program name. When NEITHER
# the prefix NOR these keywords are present, skip extraction entirely.
_PROGRAM_KEYWORDS_RE = re.compile(
    r"(?:专业|major|program|主修|课程方向|track|concentration|degree)",
    re.IGNORECASE,
)


def extract_filters_regex(query: str) -> QueryFilters:
    """Pure regex pass — no LLM. Returns a QueryFilters with program_prefix
    set if a known prefix appears as a word in the query, else None.

    Sanitized query: the matched prefix word is removed (case-preserving
    by index removal), and surrounding whitespace is collapsed. This keeps
    the BM25 / vector embeddings focused on the rest of the query.
    """
    if not query or not query.strip():
        return QueryFilters(sanitized_query="")

    match = next(
        (
            m
            for m in _PREFIX_RE.finditer(query)
            if m.group(1).upper() not in AMBIGUOUS_PREFIXES or m.group(1).isupper()
        ),
        None,
    )
    if not match:
        return QueryFilters(sanitized_query=query)

    prefix = match.group(1).upper()
    # Strip the matched prefix from the query for the sanitized form.
    sanitized = (query[: match.start()] + query[match.end():]).strip()
    sanitized = re.sub(r"\s+", " ", sanitized)
    return QueryFilters(program_prefix=prefix, sanitized_query=sanitized)


def extract_filters_adaptive(
    query: str,
    *,
    llm_fn: Callable[[str], dict[str, object]] | None = None,
) -> QueryFilters:
    """Adaptive extraction — fast path first, LLM fallback only when needed.

    Decision tree:
      1. Regex finds an explicit prefix → return that, skip LLM.
      2. No prefix BUT program-keyword present (`专业`, `major`, ...) AND
         `llm_fn` is provided → call the LLM to map the program name.
      3. Otherwise → no filter (passthrough). Saves the LLM call when the
         user's query has no program intent at all.

    `llm_fn(query) -> dict` must return a dict with keys 'program_prefix'
    (str | None) and 'sanitized_query' (str). The dict is fed to
    QueryFilters; Pydantic validates. Caller decides Gemini / Claude / etc.
    """
    regex_result = extract_filters_regex(query)
    if not regex_result.is_empty():
        return regex_result

    # No explicit prefix. Worth an LLM call only if a program keyword is in
    # the query — otherwise the LLM would be guessing in a vacuum.
    if llm_fn is None or not _PROGRAM_KEYWORDS_RE.search(query):
        return regex_result  # passthrough (program_prefix=None)

    try:
        raw = llm_fn(query)
    except Exception:
        # LLM failed — degrade to passthrough rather than blocking the request.
        # Caller log captures the trace; user still gets retrieval.
        return regex_result

    # Validate via Pydantic; missing/extra fields => fall back to regex result.
    try:
        return QueryFilters(**raw)
    except Exception:
        return regex_result


__all__ = [
    "AMBIGUOUS_PREFIXES",
    "KNOWN_PROGRAM_PREFIXES",
    "extract_filters_adaptive",
    "extract_filters_regex",
]
