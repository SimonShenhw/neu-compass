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
    "HydeRetriever",
    "expand_query_via_hyde",
]
