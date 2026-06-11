"""HyDE — Hypothetical Document Embeddings query expansion.

Pattern from Gao et al. 2022. The LLM generates a hypothetical course
description that *would* answer the user's query; we then embed THAT
description (not the query itself) before vector search.

Why it helps:
  - User queries are short + interrogative ("hard NLP class")
  - Course descriptions are long + declarative ("This course covers...")
  - Embedding spaces don't perfectly align across these two distributions
  - Embedding a hypothetical description nudges the query vector closer
    to the document distribution

Cost: 1 extra LLM call per query (~$0.0001 on Gemini 2.5 Flash). Caller
decides whether to apply HyDE always or only when the cheap path returns
weak results (PLAN §8 budget discipline).
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from llm.gemini_client import generate_text
from rag.retriever import SearchHit

DEFAULT_TEMPERATURE = 0.3  # mild creativity; too high invents non-existent topics

HYDE_PROMPT_TEMPLATE = """Generate a 2-3 sentence hypothetical course description \
that would directly answer a graduate student's question about a Northeastern \
University course. Write the description as if you were the course catalog. \
Output ONLY the description, no preamble, no quoting back the question.

Student question: {query}

Course description:"""


class _RetrieverLike(Protocol):
    def search(
        self, query: str, *, hard_filters: dict[str, Any] | None = ..., k: int = ...,
    ) -> list[SearchHit]: ...


# ADR-0019: second-opinion prompt for the rescue pass. One call does BOTH
# jobs — intent judgment (keeps the adversarial wall: garbage gets no
# second chance) and HyDE expansion (gives real-but-evidence-poor queries
# like "VC dimension PAC learning" / "CRM 认知偏差" a retrieval retry).
RESCUE_PROMPT_TEMPLATE = """A university course-search engine rejected the \
query below as "no matching course". You are the second-opinion judge.

Decide: is this a plausible query a student would type to find an EXISTING \
university course or course topic? The query may be in Chinese or mixed \
Chinese/English; technical jargon, theory terms, and field acronyms (expand \
them from context) are all plausible course topics.

- If NO — gibberish, homework/assignment requests, campus services or \
admin questions, chit-chat, jokes, or fictional/speculative topics that no \
real university teaches as a course today (e.g. time travel, teleportation, \
magic) — output exactly: REJECT
- If YES — output a 2-3 sentence hypothetical course description (in \
English) that would answer it, written as if from the course catalog. \
Spell out any acronyms using the query's context. No preamble.

Query: {query}
"""


def rescue_expand(
    query: str,
    *,
    generate_fn: Callable[[str], str] | None = None,
    temperature: float = 0.0,
) -> str | None:
    """Second-opinion expansion for the rejection rescue pass (ADR-0019).

    Returns the hypothetical description, or None when the LLM judges the
    query not course-seeking (REJECT) — caller keeps the original rejection.

    temperature=0.0 (not DEFAULT_TEMPERATURE): the REJECT-vs-expand verdict
    is a judgment call and must be as deterministic as possible — at 0.3,
    borderline fictional queries ("time travel paradox engineering")
    flipped verdicts between runs (observed on the v0.3 eval).
    """
    prompt = RESCUE_PROMPT_TEMPLATE.format(query=query)
    if generate_fn is None:
        out = generate_text(prompt, temperature=temperature)
    else:
        out = generate_fn(prompt)
    text = out.strip()
    if not text or text.upper().startswith("REJECT"):
        return None
    return text


def expand_query_via_hyde(
    query: str,
    *,
    generate_fn: Callable[[str], str] | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
) -> str:
    """Generate a hypothetical course description for the query.

    Default uses llm.gemini_client.generate_text; tests inject a fake.
    Returns the LLM output stripped of leading/trailing whitespace.
    """
    prompt = HYDE_PROMPT_TEMPLATE.format(query=query)
    if generate_fn is None:
        return generate_text(prompt, temperature=temperature).strip()
    return generate_fn(prompt).strip()


class HydeRetriever:
    """Wraps a base retriever; expands query via LLM before passing through.

    Drop-in interface compatible with Retriever / HybridRetriever — same
    .search(query, hard_filters=..., k=...) signature returning list[SearchHit].
    """

    def __init__(
        self,
        *,
        base_retriever: _RetrieverLike,
        expand_fn: Callable[[str], str] | None = None,
        prepend_original: bool = True,
    ) -> None:
        self._base = base_retriever
        self._expand_fn = expand_fn
        # When True, the expanded text is "<original>\n\n<hypothetical>" so the
        # base retriever sees BOTH the user's original phrasing (good for term
        # matches) and the LLM expansion (good for distribution alignment).
        self._prepend_original = prepend_original

    def search(
        self,
        query: str,
        *,
        hard_filters: dict[str, Any] | None = None,
        k: int = 10,
    ) -> list[SearchHit]:
        expanded = self._expand_query(query)
        if self._prepend_original:
            combined = f"{query}\n\n{expanded}"
        else:
            combined = expanded
        return self._base.search(combined, hard_filters=hard_filters, k=k)

    def _expand_query(self, query: str) -> str:
        if self._expand_fn is None:
            return expand_query_via_hyde(query)
        return expand_query_via_hyde(query, generate_fn=self._expand_fn)


__all__ = [
    "DEFAULT_TEMPERATURE",
    "HYDE_PROMPT_TEMPLATE",
    "RESCUE_PROMPT_TEMPLATE",
    "HydeRetriever",
    "expand_query_via_hyde",
    "rescue_expand",
]
