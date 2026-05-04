"""Tests for llm.review_enrichment — bridge + end-to-end enrich_course."""

from __future__ import annotations

from llm.formatter import format_sources
from llm.review_enrichment import (
    CATALOG_SOURCE_TYPE,
    RMP_SOURCE_ID_PREFIX,
    RMP_SOURCE_TYPE,
    assemble_sources,
    enrich_course,
    reviews_to_source_documents,
)
from schemas.course import Course
from scrapers.rmp import RmpProfessorSummary, RmpReview


def _summary(*reviews: RmpReview, name: str = "Dr. Smith") -> RmpProfessorSummary:
    return RmpProfessorSummary(
        professor_id="p1",
        name=name,
        department="CS",
        num_ratings=len(reviews),
        reviews=list(reviews),
    )


def test_empty_reviews_returns_empty() -> None:
    assert reviews_to_source_documents(_summary()) == []


def test_one_review_one_source() -> None:
    docs = reviews_to_source_documents(_summary(
        RmpReview(
            review_id="rmp42",
            comment="Tough but fair.",
            overall_rating=4.0,
            difficulty_rating=3.5,
            course_code_mentioned="CS 5800",
            created_date="2025-04-01",
            rating_tags=["Caring", "Lecture heavy"],
        ),
    ))
    assert len(docs) == 1
    d = docs[0]
    assert d.source_id == f"{RMP_SOURCE_ID_PREFIX}rmp42"
    assert d.source_type == RMP_SOURCE_TYPE
    assert "CS 5800" in d.content
    assert "quality_rating: 4.0/5" in d.content
    assert "difficulty_rating: 3.5/5" in d.content
    assert "professor: Dr. Smith" in d.content
    assert "Tough but fair." in d.content
    assert d.metadata["course_code"] == "CS 5800"
    assert d.metadata["professor"] == "Dr. Smith"


def test_review_without_optional_fields() -> None:
    """Comment + id only — header should still be valid (just professor)."""
    docs = reviews_to_source_documents(_summary(
        RmpReview(review_id="r1", comment="ok"),
    ))
    assert len(docs) == 1
    d = docs[0]
    assert "professor: Dr. Smith" in d.content
    assert "course:" not in d.content
    assert "course_code" not in d.metadata


def test_skips_review_without_id() -> None:
    """Defensive — _parse_review_node already drops these, but guard anyway."""
    summary = _summary()
    # Bypass Pydantic validation to simulate a corrupt RmpReview shape that
    # somehow got into a summary. We craft via model_construct.
    bad = RmpReview.model_construct(review_id="", comment="ghost")
    summary.reviews.append(bad)
    docs = reviews_to_source_documents(summary)
    assert docs == []


def test_output_round_trips_through_format_sources() -> None:
    """Bridge output must be consumable by format_sources without errors."""
    summary = _summary(
        RmpReview(review_id="rmp1", comment="A"),
        RmpReview(review_id="rmp2", comment="B"),
    )
    docs = reviews_to_source_documents(summary)
    xml = format_sources(docs)
    assert 'id="rmp_review_rmp1"' in xml
    assert 'id="rmp_review_rmp2"' in xml
    assert 'type="rmp_review"' in xml


# === assemble_sources ===


def _course(*, course_id: str = "neu-cs-5800", code: str = "CS 5800") -> Course:
    return Course(course_id=course_id, primary_code=code, primary_name="Algorithms")


def test_assemble_sources_includes_raw_text_as_catalog() -> None:
    course = _course()
    docs = assemble_sources(course, "raw catalog text", [])
    assert len(docs) == 1
    assert docs[0].source_type == CATALOG_SOURCE_TYPE
    assert docs[0].content == "raw catalog text"
    assert docs[0].source_id == f"catalog_{course.course_id}"
    assert docs[0].metadata["course_code"] == course.primary_code


def test_assemble_sources_skips_catalog_when_no_raw_text() -> None:
    docs = assemble_sources(_course(), None, [])
    assert docs == []
    docs = assemble_sources(_course(), "", [])
    assert docs == []


def test_assemble_sources_appends_rmp_reviews() -> None:
    summary = _summary(
        RmpReview(review_id="r1", comment="tough but fair"),
        RmpReview(review_id="r2", comment="loved it"),
    )
    docs = assemble_sources(_course(), "catalog text", [summary])
    assert len(docs) == 3
    assert docs[0].source_type == CATALOG_SOURCE_TYPE
    assert docs[1].source_type == RMP_SOURCE_TYPE
    assert docs[2].source_type == RMP_SOURCE_TYPE


# === enrich_course (mock LLM) ===


def _enriched_course_factory(course_id: str, code: str) -> Course:
    """A mock LLM result that conforms to Course (with evidence)."""
    from schemas.course import EvidenceSnippet

    return Course(
        course_id="WRONG-ID-FROM-LLM",  # caller should override with original
        primary_code=code,
        primary_name="Algorithms (LLM-enriched)",
        difficulty_score=4.0,
        workload_hours_per_week=10.0,
        skill_tags=["graph-algorithms", "complexity-analysis"],
        evidence_snippets=[
            EvidenceSnippet(
                field="difficulty_score",
                value=4.0,
                source_id="rmp_review_r1",
                quote="tough but fair",
                confidence=0.85,
            ),
            EvidenceSnippet(
                field="workload_hours_per_week",
                value=10.0,
                source_id="rmp_review_r2",
                quote="loved it",
                confidence=0.7,
            ),
            EvidenceSnippet(
                field="skill_tags",
                value=["graph-algorithms"],
                source_id="rmp_review_r1",
                quote="tough but fair",
                confidence=0.8,
            ),
        ],
    )


def test_enrich_course_overrides_course_id() -> None:
    """LLM may return any course_id; enrich_course must restore the original."""
    course = _course(course_id="neu-cs-5800", code="CS 5800")
    summary = _summary(
        RmpReview(review_id="r1", comment="tough but fair"),
        RmpReview(review_id="r2", comment="loved it"),
    )

    captured: dict = {}

    def mock_llm(prompt: str, schema: type[Course]) -> Course:
        captured["prompt"] = prompt
        captured["schema"] = schema
        return _enriched_course_factory("WRONG-ID", "CS 5800")

    enriched = enrich_course(course, "catalog text", [summary], llm_fn=mock_llm)

    assert enriched.course_id == "neu-cs-5800"
    assert enriched.primary_code == "CS 5800"
    assert enriched.difficulty_score == 4.0
    assert len(enriched.evidence_snippets) == 3


def test_enrich_course_passes_assembled_prompt_to_llm() -> None:
    """The LLM should see all source contents in the prompt."""
    course = _course(course_id="neu-cs-5800", code="CS 5800")
    summary = _summary(
        RmpReview(review_id="r1", comment="tough but fair"),
    )

    seen_prompt: dict = {}

    def mock_llm(prompt: str, schema: type[Course]) -> Course:
        seen_prompt["text"] = prompt
        return _enriched_course_factory("x", "CS 5800")

    enrich_course(course, "raw catalog body", [summary], llm_fn=mock_llm)

    p = seen_prompt["text"]
    assert "raw catalog body" in p
    assert "tough but fair" in p
    assert 'type="catalog"' in p
    assert 'type="rmp_review"' in p


def test_enrich_course_works_with_no_rmp_summaries() -> None:
    """Enrichment can run on syllabus alone (Gemini will get only catalog source)."""
    course = _course()

    def mock_llm(prompt: str, schema: type[Course]) -> Course:
        assert "rmp_review" not in prompt
        return _enriched_course_factory("x", course.primary_code)

    enriched = enrich_course(course, "syllabus content", [], llm_fn=mock_llm)
    assert enriched.course_id == course.course_id
