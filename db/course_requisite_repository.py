"""Separate course/year storage; caller owns transactions, never auto-DDL."""

from __future__ import annotations

import hashlib
import json
import sqlite3

import structlog

from schemas.course_requisite_document import CourseRequisiteDocument, CourseRequisiteListing
from db.program_plan_repository import ProgramPlanRepository

log = structlog.get_logger("neu_compass.course_requisites")
BASE_WARNINGS = ["course_block_only_not_full_policy_or_eligibility", "campus_and_personal_pathway_not_declared",
                 "legacy_prerequisite_edges_not_verified_logic", "structured_requisites_not_used_by_chat"]


def content_hash(document: CourseRequisiteDocument) -> str:
    payload = document.model_dump(mode="json", exclude={"imported_at"})
    # Preserve independently stored 05C-2/3 hashes; only NEW empty defaults.
    for key in ("description_evidence", "credit_hours"):
        if payload.get(key) is None:
            payload.pop(key, None)
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class CourseRequisiteRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def available(self) -> bool:
        return self._conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='course_requisite_documents'").fetchone() is not None

    def validate_identity(self, document: CourseRequisiteDocument):
        course = self._conn.execute("SELECT primary_code, primary_name FROM courses WHERE course_id=?", (document.course_id,)).fetchone()
        if course is None or (course["primary_code"], course["primary_name"]) != (document.course_code, document.course_name):
            raise ValueError("Requisite document must match the existing course ID, code and title")

    def _decode(self, row, identity) -> CourseRequisiteDocument:
        if len(row["document"]) > 200_000:
            raise ValueError("Stored document outside budget")
        document = CourseRequisiteDocument.model_validate_json(row["document"])
        if ((document.course_id, document.catalog_year) != (row["course_id"], row["catalog_year"])
                or (document.course_code, document.course_name) != identity or content_hash(document) != row["content_hash"]):
            raise ValueError("Stored requisite document identity/content mismatch")
        return document

    def needs_store(self, document: CourseRequisiteDocument) -> bool:
        self.validate_identity(document)
        if not self.available():
            return True
        row = self._conn.execute("SELECT * FROM course_requisite_documents WHERE course_id=? AND catalog_year=?",
                                 (document.course_id, document.catalog_year)).fetchone()
        if row is None:
            return True
        try:
            old = self._decode(row, (document.course_code, document.course_name))
            return content_hash(old) != content_hash(document)
        except (ValueError, TypeError):
            return True  # Verified new inputs may replace a corrupt record.

    def store(self, document: CourseRequisiteDocument) -> bool:
        # Reject model_copy/unchecked assignments that bypass initial validation.
        document = CourseRequisiteDocument.model_validate(document.model_dump(mode="json"))
        if not self.available():
            raise ValueError("Course requisite schema missing; explicit migration required")
        if not self.needs_store(document):
            return False
        self._conn.execute(
            "INSERT INTO course_requisite_documents(course_id,catalog_year,document,content_hash) VALUES(?,?,?,?) "
            "ON CONFLICT(course_id,catalog_year) DO UPDATE SET document=excluded.document, content_hash=excluded.content_hash",
            (document.course_id, document.catalog_year, document.model_dump_json(), content_hash(document)),
        )
        return True

    def list_for_course(self, course_id: str, *, catalog_year: str | None = None) -> CourseRequisiteListing:
        bundle = CourseRequisiteListing(schema_available=self.available(), warnings=list(BASE_WARNINGS))
        if not bundle.schema_available:
            bundle.warnings.append("structured_requisite_schema_unavailable")
            return bundle
        course = self._conn.execute("SELECT primary_code,primary_name FROM courses WHERE course_id=?", (course_id,)).fetchone()
        if course is None:
            bundle.warnings.append("structured_requisites_missing")
            return bundle
        clause, params = "course_id=?", [course_id]
        if catalog_year is not None:
            clause += " AND catalog_year=?"
            params.append(catalog_year)
        try:
            bundle.has_any_stored_records = self._conn.execute("SELECT 1 FROM course_requisite_documents WHERE course_id=? LIMIT 1", (course_id,)).fetchone() is not None
            rows = self._conn.execute(f"SELECT course_id,catalog_year,document,content_hash FROM course_requisite_documents WHERE {clause} ORDER BY catalog_year DESC", params).fetchall()
        except sqlite3.DatabaseError:
            log.warning("course.requisite_schema_unusable", course_id=course_id)
            bundle.warnings.append("structured_requisite_schema_unusable")
            return bundle
        for row in rows:
            try:
                bundle.documents.append(self._decode(row, (course["primary_code"], course["primary_name"])))
            except (ValueError, TypeError):
                bundle.unusable_records += 1
                log.warning("course.requisite_document_unusable", course_id=course_id, catalog_year=row["catalog_year"])
        if bundle.unusable_records:
            bundle.warnings.append("structured_requisites_unusable")
        if not rows:
            bundle.warnings.append("structured_requisites_missing")
        # Read-time context only: never mix program rules into course source hashes.
        plan_repo = ProgramPlanRepository(self._conn)
        bundle.program_contexts = [plan_repo.course_context(item.course_code, item.catalog_year) for item in bundle.documents]
        return bundle
