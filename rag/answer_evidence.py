"""Shared prompt/API provenance and availability, built without model calls."""

from __future__ import annotations

import sqlite3

from db.catalog_source_repository import CatalogSourceRepository
from schemas.answer_evidence import CatalogSnapshot, CourseAnswerEvidence
from schemas.course import Course

AVAILABILITY_FIELDS = (
    "credits", "term", "delivery_mode", "professor", "prereqs", "topics_covered",
    "skill_tags", "workload_hours_per_week", "difficulty_score", "grading_components", "career_relevance",
)


def course_answer_evidence(course: Course, catalog: CatalogSnapshot | None = None,
                           *, program_seed: bool = False) -> CourseAnswerEvidence:
    missing = [field for field in AVAILABILITY_FIELDS if getattr(course, field) is None or getattr(course, field) == []]
    warnings = []
    if catalog is None or not catalog.description:
        missing.insert(0, "catalog_description")
    if catalog is None:
        warnings.append("catalog_source_unavailable")
    elif catalog.retrieved_at is None:
        warnings.append("catalog_retrieval_date_unknown")
    if catalog and catalog.credits is not None and course.credits is not None and catalog.credits != course.credits:
        warnings.append("catalog_metadata_conflict")
    if course.evidence_snippets:
        warnings.append("extracted_evidence_not_official_facts")
    if any(snippet.field in {"workload_hours_per_week", "difficulty_score"}
           and snippet.value != getattr(course, snippet.field) for snippet in course.evidence_snippets):
        warnings.append("field_evidence_value_conflict")
    if course.topics_covered and not course.source_review_ids and not any(
        snippet.field == "topics_covered" for snippet in course.evidence_snippets
    ):
        warnings.append("topics_source_unavailable")
    if course.prereqs or (catalog and catalog.prereq_codes):
        warnings.append("prerequisite_logic_unavailable")
    if program_seed:
        warnings.append("program_seed_unverified")
    if course.course_id.startswith("synth-") or any(source.startswith("synthetic_seed_") for source in course.source_review_ids):
        warnings.append("synthetic_record_not_real_course")
    return CourseAnswerEvidence(
        catalog=catalog, field_evidence=course.evidence_snippets,
        source_review_ids=course.source_review_ids, missing_fields=missing, warnings=warnings,
    )


def build_answer_evidence(conn: sqlite3.Connection, courses: list[Course],
                          *, program_seed: bool = False) -> dict[str, CourseAnswerEvidence]:
    catalogs = CatalogSourceRepository(conn).get_batch(courses)
    return {course.course_id: course_answer_evidence(course, catalogs.get(course.course_id), program_seed=program_seed)
            for course in courses}
