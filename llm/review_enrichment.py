"""Bridge: RmpProfessorSummary → SourceDocument list for the LLM extractor.

Per PLAN_v2.0 §4 Q2=B, RMP reviews flow into Course.evidence_snippets via the
existing extract_v1 LLM pipeline (rather than a parallel Course-mutating
helper). Each review becomes one `<source id="rmp_review_X" type="rmp_review">`
chunk; the LLM can then cite that id when populating soft fields like
difficulty_score / workload_hours_per_week / controversial_signals, and
schemas.course's model_validator enforces the evidence_snippet ↔ source_id
correspondence (PLAN §3.3 / §2.1).

This module is pure data-shaping — no LLM calls. Caller (e.g. an ingestion
script that wants to enrich a Course with RMP reviews) packages the output
together with the syllabus into a single LLM extraction request.
"""

from __future__ import annotations

from typing import Callable

from llm.formatter import SourceDocument, format_sources
from llm.gemini_client import generate_structured
from llm.prompts.extract_v1_1 import build_prompt
from schemas.course import Course
from scrapers.rmp import RmpProfessorSummary, RmpReview

# source_id prefix matches the convention in schemas.course evidence_snippets.
RMP_SOURCE_ID_PREFIX = "rmp_review_"
RMP_SOURCE_TYPE = "rmp_review"
CATALOG_SOURCE_TYPE = "catalog"

# LLM-callable shape: accept a prompt string + Course schema, return a Course.
# `generate_structured` matches via partial application; tests pass a mock.
LlmFn = Callable[[str, type[Course]], Course]


def _default_llm_fn(prompt: str, schema: type[Course]) -> Course:
    return generate_structured(prompt, schema=schema)


def reviews_to_source_documents(
    summary: RmpProfessorSummary,
) -> list[SourceDocument]:
    """One SourceDocument per RmpReview in the summary.

    Empty list if the professor has no reviews. Skips reviews with empty
    review_id (defensive; _parse_review_node should already drop those).

    The content is a structured plain-text dump rather than JSON — the LLM
    extractor (extract_v1.py) reads each <source> as free-form prose, and
    structured fields here help it ground numeric soft fields.
    """
    docs: list[SourceDocument] = []
    for r in summary.reviews:
        if not r.review_id:
            continue
        docs.append(_review_to_source(r, professor_name=summary.name))
    return docs


def _review_to_source(review: RmpReview, *, professor_name: str) -> SourceDocument:
    """Single review → one SourceDocument."""
    header_lines: list[str] = []
    header_lines.append(f"professor: {professor_name}")
    if review.course_code_mentioned:
        header_lines.append(f"course: {review.course_code_mentioned}")
    if review.overall_rating is not None:
        header_lines.append(f"quality_rating: {review.overall_rating}/5")
    if review.difficulty_rating is not None:
        header_lines.append(f"difficulty_rating: {review.difficulty_rating}/5")
    if review.created_date:
        header_lines.append(f"date: {review.created_date}")
    if review.rating_tags:
        header_lines.append(f"tags: {', '.join(review.rating_tags)}")

    metadata = {"professor": professor_name}
    if review.course_code_mentioned:
        metadata["course_code"] = review.course_code_mentioned

    content = "\n".join(header_lines) + "\n---\n" + (review.comment or "")
    return SourceDocument(
        source_id=f"{RMP_SOURCE_ID_PREFIX}{review.review_id}",
        source_type=RMP_SOURCE_TYPE,
        content=content,
        metadata=metadata,
    )


def assemble_sources(
    course: Course,
    raw_text: str | None,
    rmp_summaries: list[RmpProfessorSummary],
) -> list[SourceDocument]:
    """Build the SourceDocument list for an enrichment LLM call.

    Order: catalog/syllabus first (source of truth for hard fields), then
    RMP reviews (which feed soft fields). Empty raw_text → no catalog entry.
    """
    docs: list[SourceDocument] = []
    if raw_text:
        docs.append(
            SourceDocument(
                source_id=f"catalog_{course.course_id}",
                source_type=CATALOG_SOURCE_TYPE,
                content=raw_text,
                metadata={"course_code": course.primary_code},
            )
        )
    for summary in rmp_summaries:
        docs.extend(reviews_to_source_documents(summary))
    return docs


# Fields the LLM extraction is ALLOWED to write. Everything else keeps the
# incoming course's value. Rationale (data-quality review, 2026-06): the
# extraction prompt only sees raw_text (description) + reviews, so hard
# fields the catalog parsed separately (credits from the title line,
# prereq codes from anchor tags) come back null from the LLM — and the old
# return-the-LLM-object-wholesale behavior CLOBBERED them on upsert.
# CS 5800 lost its credits exactly this way, which then broke the
# credits=4 filter on the flagship demo course.
ENRICHMENT_FIELDS: tuple[str, ...] = (
    "professor",
    "workload_hours_per_week",
    "difficulty_score",
    "grading_components",
    "topics_covered",
    "skill_tags",
    "career_relevance",
    "controversial_signals",
    "ai_policy",
    "evidence_snippets",
    "extraction_confidence",
    "source_review_ids",
)


def enrich_course(
    course: Course,
    raw_text: str | None,
    rmp_summaries: list[RmpProfessorSummary],
    *,
    llm_fn: LlmFn = _default_llm_fn,
) -> Course:
    """Run the LLM extraction pipeline on (course, syllabus, RMP reviews)
    and MERGE the soft fields onto the incoming Course.

    Merge, not replace: only ENRICHMENT_FIELDS are taken from the LLM
    output (and only when non-empty) — hard catalog facts (credits, term,
    prereqs, cross-listings, code/name) always keep the incoming values,
    because the LLM never saw the sources they came from.

    Tests pass `llm_fn` to bypass the live Gemini call. Production uses
    the default which delegates to `gemini_client.generate_structured`.

    Raises whatever GeminiError / ValidationError the LLM call surfaces —
    caller decides whether to retry / log / fail loud.
    """
    docs = assemble_sources(course, raw_text, rmp_summaries)
    sources_xml = format_sources(docs)
    prompt = build_prompt(sources_xml)

    extracted = llm_fn(prompt, Course)

    updates: dict[str, object] = {}
    for field in ENRICHMENT_FIELDS:
        value = getattr(extracted, field)
        # None / empty list = the LLM found nothing in its sources; keep
        # whatever the course already had rather than erasing it.
        if value is None or value == []:
            continue
        updates[field] = value
    # model_copy(update=...) skips validators; re-validate so the
    # soft-field-requires-evidence invariant still holds on the merge.
    return Course.model_validate(
        {**course.model_dump(), **updates},
    )


__all__ = [
    "CATALOG_SOURCE_TYPE",
    "ENRICHMENT_FIELDS",
    "LlmFn",
    "RMP_SOURCE_ID_PREFIX",
    "RMP_SOURCE_TYPE",
    "assemble_sources",
    "enrich_course",
    "reviews_to_source_documents",
]
