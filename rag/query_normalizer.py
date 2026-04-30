"""Query -> [course_id] via alias resolution.

Used by the API layer (Week 6) BEFORE semantic search. If the user types
'5800' or 'Applied AI', we resolve directly via v_course_lookup and can
return that course without LLM/vector cost. Falls through to retriever
when no alias match.

Three extraction patterns:
  1. Full code 'CS 5800' / 'AAI6600' (regex normalized to canonical)
  2. Bare 4-digit '5800' (slang for course number)
  3. Whole-query exact match (for 'Applied AI', 'Algo', '应用 AI')
"""

from __future__ import annotations

import re

from db.alias_repository import AliasRepository

# Same as schemas.course COURSE_CODE_PATTERN but case-insensitive + free in text.
_FULL_CODE_RE = re.compile(r"\b([A-Za-z]{2,4})\s?(\d{4}[A-Za-z]?)\b")
_NUMERIC_CODE_RE = re.compile(r"\b(\d{4})\b")

# Cap candidate-text length so we don't try to resolve "the entire essay" against aliases.
MAX_WHOLE_QUERY_LEN = 30


def normalize_query_to_course_ids(
    query: str,
    *,
    alias_repo: AliasRepository,
) -> list[str]:
    """Extract course mentions from a user query and resolve via aliases.

    Returns deduplicated course_ids in the order they were resolved (stable
    enough for tests; production callers should treat as a set).
    """
    if not query or not query.strip():
        return []

    candidates = _extract_candidates(query)

    seen: set[str] = set()
    result: list[str] = []
    for cand in candidates:
        for cid in alias_repo.resolve(cand):
            if cid not in seen:
                seen.add(cid)
                result.append(cid)
    return result


def _extract_candidates(query: str) -> list[str]:
    """Return ordered candidate strings worth probing against the alias view.

    Order matters: more specific (full code) before less (bare number) before
    least (whole query). Caller's resolve() is case-insensitive so we don't
    bother lowercasing here.
    """
    candidates: list[str] = []
    seen: set[str] = set()

    # 1. Full course code patterns
    for m in _FULL_CODE_RE.finditer(query):
        normalized = f"{m.group(1).upper()} {m.group(2).upper()}"
        if normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)

    # 2. Bare 4-digit numbers (skip if already covered by full-code match)
    for m in _NUMERIC_CODE_RE.finditer(query):
        num = m.group(0)
        # Skip if this number was already part of a full-code match
        if any(num in c for c in candidates):
            continue
        if num not in seen:
            seen.add(num)
            candidates.append(num)

    # 3. Whole query (after stripping). Effective for short queries like
    #    "应用 AI", "Algo", "Hema's AI class" that don't match the regexes.
    stripped = query.strip()
    if 1 < len(stripped) <= MAX_WHOLE_QUERY_LEN and stripped not in seen:
        candidates.append(stripped)

    return candidates


__all__ = ["MAX_WHOLE_QUERY_LEN", "normalize_query_to_course_ids"]
