"""Corpus-derived acronym expansion at query time (ADR-0020 §3).

The failure this fixes: "CRM 认知偏差 团队决策" means Crisis Resource
Management (the healthcare-teamwork course defines it that way), but
embeddings read CRM as Customer Relationship Management — the dominant
web sense. The corpus itself disambiguates: the glossary is mined from
course texts by scripts/generate_doc_expansion.py + aggregated by
scripts/apply_doc_expansion.py, so an acronym only ever expands to senses
that actually exist in the catalog.

Multi-sense handling: append ALL in-corpus senses to the query (union
retrieval); the cross-encoder reranker sees the surrounding query context
("认知偏差 团队决策") and ranks the right sense's course up. No LLM call,
no sense-picking error possible at this layer.

Wiring: HybridRetriever applies `expand_query` to its retrieval legs only
— the reranker and the rejection gate still see the ORIGINAL query, so
expansion can only ADD recall, never change what relevance is judged
against. Disabled cleanly when the glossary file is absent.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

from rag.hybrid import STOPWORDS

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GLOSSARY_PATH = PROJECT_ROOT / "data" / "acronym_glossary.json"

# Tokens that pass the shape test but are ordinary words in course-search
# queries — expanding them would inject noise. STOPWORDS already covers
# the function words ("is", "it", ...).
_DENYLIST = frozenset({
    "info", "data", "lab", "labs", "intro", "core", "exam", "fall", "gpa",
    "online", "hybrid", "course", "class", "unit", "term",
})

_ACRO_TOKEN_RE = re.compile(r"\b[A-Za-z]{2,6}\b", re.ASCII)

MAX_SENSES_PER_ACRONYM = 3  # query-bloat guard; apply script also caps


@functools.lru_cache(maxsize=1)
def load_glossary(path: str | None = None) -> dict[str, tuple[str, ...]]:
    """Load {ACRONYM: (sense, ...)} from JSON. Missing/corrupt file → {}
    (feature silently off). lru_cache: one disk read per process."""
    p = Path(path) if path else DEFAULT_GLOSSARY_PATH
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        # Per-entry type check: a structurally-valid JSON with a non-string
        # sense (nested list, number) would otherwise pass load and crash
        # expand_query's sense.lower() on EVERY non-alias request — one bad
        # glossary regeneration = total search outage.
        return {
            k.upper(): tuple(v)[:MAX_SENSES_PER_ACRONYM]
            for k, v in raw.items()
            if isinstance(v, list) and v
            and all(isinstance(s, str) for s in v)
        }
    except Exception:  # noqa: BLE001 — bad glossary must not kill the API
        return {}


def expand_query(
    query: str,
    *,
    glossary: dict[str, tuple[str, ...]] | None = None,
) -> str:
    """Append in-corpus long forms for acronym-shaped tokens in the query.

    Lookup is case-insensitive for tokens of length ≥3; 2-letter tokens
    must be uppercase in the query (lowercase "is"/"ml" prose ambiguity —
    same conservatism as the Layer-2 AMBIGUOUS_PREFIXES rule). Senses
    already present verbatim in the query are skipped.
    """
    g = load_glossary() if glossary is None else glossary
    if not g:
        return query

    additions: list[str] = []
    lowered = query.lower()
    for m in _ACRO_TOKEN_RE.finditer(query):
        tok = m.group(0)
        if tok.lower() in STOPWORDS or tok.lower() in _DENYLIST:
            continue
        if len(tok) == 2 and not tok.isupper():
            continue
        for sense in g.get(tok.upper(), ()):
            if sense.lower() not in lowered:
                additions.append(sense)

    if not additions:
        return query
    # dict.fromkeys: dedupe, keep first-seen order (stable for tests/logs).
    return query + " " + " ".join(dict.fromkeys(additions))


__all__ = [
    "DEFAULT_GLOSSARY_PATH",
    "MAX_SENSES_PER_ACRONYM",
    "expand_query",
    "load_glossary",
]
