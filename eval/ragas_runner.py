"""Ragas integration for RAG evaluation (Faithfulness / Context Precision /
Context Recall).

Decoupled in two layers:

  1. build_ragas_inputs(test_set, retriever, course_repo)
       Pure transform from our (query, expected_course_ids) test set into
       Ragas-shaped rows: question + retrieved contexts + ground_truth text.
       Tests cover this end-to-end with a fake retriever.

  2. run_ragas_eval(inputs, llm, embeddings, metrics)
       Thin wrapper around `ragas.evaluate`. Real Ragas API churns between
       versions — keep this surface narrow so version bumps only touch this
       function. Returns a flat metric -> score dict.

Tests for layer 2 mock both `ragas` and `datasets` imports. CI doesn't
need an LLM key. Real evaluation: provide a langchain-compatible LLM
client (Gemini works via langchain-google-genai) at call time.

PLAN §4.2 metric targets:
  Recall@5 ≥ 0.75
  Faithfulness ≥ 0.85   (Ragas gives this with LLM judge)
  Context Precision ≥ 0.80
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from db.repository import CourseRepository
from rag.retriever import SearchHit


class _RetrieverLike(Protocol):
    def search(self, query: str, *, k: int = ...) -> list[SearchHit]: ...


@dataclass
class RagasInput:
    """One test case in Ragas-friendly shape.

    Ragas conventions:
      - question: the user query
      - contexts: list of strings, the retrieved documents/snippets
      - ground_truth: the canonical answer text against which we measure
    """

    question: str
    contexts: list[str]
    ground_truth: str


def build_ragas_inputs(
    test_set: dict,
    retriever: _RetrieverLike,
    course_repo: CourseRepository,
    *,
    k: int = 5,
) -> list[RagasInput]:
    """Run retriever over each test_set query, build Ragas-ready rows.

    `contexts` is built from the retrieved courses' raw_text (truncated to
    a reasonable LLM context window). `ground_truth` is the concatenated
    canonical info of expected courses; for adversarial queries with no
    expected courses, it's an empty string and Ragas may skip those metrics.
    """
    inputs: list[RagasInput] = []
    for entry in test_set.get("queries", []):
        query = entry["query"]
        hits = retriever.search(query, k=k)
        contexts = [_context_text(h) for h in hits]

        ground_truth = _ground_truth_text(
            entry.get("expected_course_ids", []),
            course_repo,
        )

        inputs.append(RagasInput(
            question=query,
            contexts=contexts,
            ground_truth=ground_truth,
        ))
    return inputs


def _context_text(hit: SearchHit) -> str:
    """Build a context string for one hit. Prefer raw_text; fall back to
    primary_code + primary_name + topics."""
    course = hit.course
    if course.created_at:  # exists, has all fields populated
        if hasattr(course, "raw_text") and getattr(course, "raw_text", None):
            return course.raw_text  # type: ignore[attr-defined]
    # Fallback: build a brief description from the schema
    pieces = [f"{course.primary_code}: {course.primary_name}"]
    if course.topics_covered:
        pieces.append("Topics: " + ", ".join(course.topics_covered))
    if course.term:
        pieces.append(f"Term: {course.term}")
    return " | ".join(pieces)


def _ground_truth_text(
    course_ids: list[str], course_repo: CourseRepository,
) -> str:
    """Build a ground-truth string from expected course_ids. Empty if list
    is empty (adversarial query)."""
    if not course_ids:
        return ""
    pieces = []
    for cid in course_ids:
        try:
            c = course_repo.get(cid)
        except Exception:
            continue
        pieces.append(f"{c.primary_code}: {c.primary_name}")
    return " | ".join(pieces)


def run_ragas_eval(
    inputs: list[RagasInput],
    *,
    llm: Any | None = None,
    embeddings: Any | None = None,
    metrics: list | None = None,
) -> dict[str, float]:
    """Call ragas.evaluate. Caller supplies LLM + embeddings + metric list.

    This wrapper is intentionally minimal — Ragas API has shifted across
    versions (0.1.x → 0.2.x → 1.x), so the surface area we depend on stays
    small. If Ragas crashes here, only this function changes.

    Default metrics (when metrics=None):
      - context_precision: fraction of retrieved contexts that are actually
        relevant to the question (LLM judge)
      - context_recall: fraction of ground-truth claims found in contexts

    For Faithfulness, we'd need an "answer" — we don't generate one yet,
    so it's not in defaults. Add when API surface includes synthesis.
    """
    # Lazy imports: tests don't need ragas/datasets installed-by-default
    # (they will be when uv sync runs, but mocking is cleaner).
    from datasets import Dataset  # type: ignore[import-not-found]  # noqa: PLC0415
    from ragas import evaluate  # type: ignore[import-not-found]  # noqa: PLC0415

    if metrics is None:
        # Lazy import metric symbols since they live under different paths
        # in different Ragas versions.
        from ragas.metrics import (  # type: ignore[import-not-found]  # noqa: PLC0415
            context_precision,
            context_recall,
        )
        metrics = [context_precision, context_recall]

    rows = [
        {
            "question": i.question,
            "contexts": i.contexts,
            "ground_truth": i.ground_truth,
        }
        for i in inputs
    ]
    dataset = Dataset.from_list(rows)

    kwargs: dict[str, Any] = {"metrics": metrics}
    if llm is not None:
        kwargs["llm"] = llm
    if embeddings is not None:
        kwargs["embeddings"] = embeddings

    result = evaluate(dataset, **kwargs)
    return _flatten_ragas_result(result)


def _flatten_ragas_result(result: Any) -> dict[str, float]:
    """Coerce Ragas's Result object into a flat metric -> score dict.

    Ragas versions return either a dict-like Result, a pandas DataFrame, or
    a custom EvaluationResult. Try each path; raise on truly unknown shape.
    """
    if hasattr(result, "to_pandas"):
        df = result.to_pandas()
        # Numeric columns are the metrics
        return {
            col: float(df[col].mean())
            for col in df.columns
            if df[col].dtype.kind in "fi"
        }
    if isinstance(result, dict):
        return {k: float(v) for k, v in result.items() if isinstance(v, (int, float))}
    raise TypeError(f"Unknown Ragas result shape: {type(result)!r}")


__all__ = [
    "RagasInput",
    "build_ragas_inputs",
    "run_ragas_eval",
]
