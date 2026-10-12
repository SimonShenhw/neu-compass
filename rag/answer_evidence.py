"""Shared prompt/API provenance and availability, built without model calls."""

from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter

import structlog

from db.catalog_source_repository import CatalogSourceRepository
from db.course_requisite_repository import CourseRequisiteRepository
from schemas.answer_evidence import (
    CLAUSE_LIMIT, MAX_REQUISITE_EDITIONS, CatalogSnapshot, CourseAnswerEvidence, RequisiteEdition,
    RequisiteEvidence, RequisiteSectionEvidence,
)
from schemas.course import Course
from schemas.course_requisite_document import CourseRequisiteDocument
from schemas.course_requisites import RequisiteSection

log = structlog.get_logger("neu_compass.answer_evidence")
AVAILABILITY_FIELDS = (
    "credits", "term", "delivery_mode", "professor", "prereqs", "topics_covered",
    "skill_tags", "workload_hours_per_week", "difficulty_score", "grading_components", "career_relevance",
)
# Source-ID prefix -> stable kind code, so the prompt and the UI can say where a field came
# from without showing students raw review IDs. Unknown prefixes are "other", never guessed.
# 中文：来源 ID 前缀 → 稳定的来源类型码；提示词与界面据此说明来源，不必把原始评价 ID
# 给学生看。未知前缀一律归为 other，不猜。
SOURCE_KIND_PREFIXES = (
    ("rmp_review_", "rmp_review"), ("reddit_", "reddit"), ("syllabus_", "syllabus"),
    ("synthetic_seed_", "synthetic"), ("catalog_", "catalog_derived"),
)


def source_kind(source_id: str) -> str:
    return next((kind for prefix, kind in SOURCE_KIND_PREFIXES if source_id.startswith(prefix)), "other")


def _section(section: RequisiteSection) -> RequisiteSectionEvidence:
    text = section.raw_text
    return RequisiteSectionEvidence(
        status=section.status, rule=section.rule, clause_text=None if text is None else text[:CLAUSE_LIMIT],
        clause_truncated=text is not None and len(text) > CLAUSE_LIMIT, unparsed_reason=section.reason,
        clause_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest() if section.status == "unparsed" else None)


def requisite_edition(document: CourseRequisiteDocument) -> RequisiteEdition:
    return RequisiteEdition(
        catalog_year=document.catalog_year, catalog_url=document.source.url, captured_at=document.source.captured_at,
        prerequisite=_section(document.requisites.prerequisite), corequisite=_section(document.requisites.corequisite))


def requisite_evidence(course: Course, documents: list[CourseRequisiteDocument], unusable: int = 0) -> RequisiteEvidence:
    """The editions an answer may use, from documents that already passed the repository's checks.
    A document for another course code or title than the course being answered about, and every
    document of a catalog year that has more than one, are counted unusable; none is chosen. So is a
    document this block cannot carry: one stored record never fails the whole answer.
    中文：回答可用的年度规则，输入是已通过仓库核对的文档。代码或名称和这门课对不上的文档，以及同一
    年度有不止一份时这一年度的全部文档，都算不可用；不从中选一份。这个证据块表达不了的文档也算不可用：
    一份已存记录不会让整个回答失败。"""
    own = [document for document in documents
           if (document.course_id, document.course_code, document.course_name)
           == (course.course_id, course.primary_code, course.primary_name)]
    years = Counter(document.catalog_year for document in own)
    usable = sorted((document for document in own if years[document.catalog_year] == 1),
                    key=lambda document: document.catalog_year, reverse=True)
    editions = []
    for document in usable:
        try:
            editions.append(requisite_edition(document))
        except ValueError:  # pydantic's ValidationError is a ValueError.
            log.warning("answer_evidence.requisite_edition_unusable", course_id=document.course_id,
                        catalog_year=document.catalog_year)
    return RequisiteEvidence(
        storage="available", editions=editions[:MAX_REQUISITE_EDITIONS],
        editions_omitted=max(0, len(editions) - MAX_REQUISITE_EDITIONS),
        unusable_records=unusable + len(documents) - len(editions))


def _rules(edition: RequisiteEdition) -> tuple:
    def key(section: RequisiteSectionEvidence):
        # An unparsed clause is compared by its whole recorded text (its digest: the text shown is cut), a parsed
        # one by its tree. 中文：未解析的一段按整段原文比（用摘要，显示的原文是截过的），已解析的按规则树比。
        return (section.status, section.rule.model_dump_json() if section.rule else None,
                (section.clause_sha256 or section.clause_text) if section.status == "unparsed" else None)
    return key(edition.prerequisite), key(edition.corequisite)


def course_answer_evidence(course: Course, catalog: CatalogSnapshot | None = None,
                           *, program_seed: bool = False, requisites: RequisiteEvidence | None = None) -> CourseAnswerEvidence:
    # With a usable year document, that year's rule is known even when the flat prereqs list is
    # empty, and its AND/OR logic is available: neither gap applies. Without one, nothing changes.
    # 中文：有可用的年度文档时，即使平铺的 prereqs 为空，那一年的规则也是已知的，AND/OR 也有：这两项
    # 缺口都不成立。没有时和以前完全一样。
    editions = requisites.editions if requisites else []
    missing = [field for field in AVAILABILITY_FIELDS
               if (getattr(course, field) is None or getattr(course, field) == []) and not (field == "prereqs" and editions)]
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
    if (course.prereqs or (catalog and catalog.prereq_codes)) and not editions:
        warnings.append("prerequisite_logic_unavailable")
    if len({_rules(edition) for edition in editions}) > 1:
        warnings.append("requisites_differ_by_catalog_year")
    if any(section.status == "unparsed" for edition in editions for section in (edition.prerequisite, edition.corequisite)):
        warnings.append("requisite_clause_unparsed")
    if requisites and (requisites.unusable_records or requisites.storage == "schema_unusable"):
        warnings.append("structured_requisites_unusable")
    if program_seed:
        warnings.append("program_seed_unverified")
    if course.course_id.startswith("synth-") or any(source.startswith("synthetic_seed_") for source in course.source_review_ids):
        warnings.append("synthetic_record_not_real_course")
    return CourseAnswerEvidence(
        catalog=catalog, field_evidence=course.evidence_snippets,
        source_review_ids=course.source_review_ids, missing_fields=missing, warnings=warnings, requisites=requisites,
    )


def build_answer_evidence(conn: sqlite3.Connection, courses: list[Course],
                          *, program_seed: bool = False) -> dict[str, CourseAnswerEvidence]:
    catalogs = CatalogSourceRepository(conn).get_batch(courses)
    batch = CourseRequisiteRepository(conn).read_batch([course.course_id for course in courses])
    evidence = {}
    for course in courses:
        if batch.storage != "available":
            requisites = RequisiteEvidence(storage=batch.storage)
        elif course.course_id in batch.unreadable:  # Its own rows could not be read; the other courses keep theirs.
            requisites = RequisiteEvidence(storage="schema_unusable")
        else:
            requisites = requisite_evidence(course, batch.documents.get(course.course_id, []),
                                            batch.unusable[course.course_id])
        evidence[course.course_id] = course_answer_evidence(
            course, catalogs.get(course.course_id), program_seed=program_seed, requisites=requisites)
    return evidence
