"""Separate course/year storage; caller owns transactions, never auto-DDL."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field

import structlog

from schemas.course_requisite_document import CourseRequisiteDocument, CourseRequisiteListing
from db.program_plan_repository import ProgramPlanRepository

log = structlog.get_logger("neu_compass.course_requisites")
BASE_WARNINGS = ["course_block_only_not_full_policy_or_eligibility", "campus_and_personal_pathway_not_declared",
                 "legacy_prerequisite_edges_not_verified_logic"]


@dataclass(frozen=True)
class RequisiteBatch:
    """Usable documents per course (newest catalog year first) and per-course counts of stored
    documents that failed the checks; storage is available / schema_missing / schema_unusable, and
    unreadable holds the courses whose own rows could not be read (each of them is schema_unusable).
    中文：每门课的可用文档（Catalog 年度从新到旧），以及每门课核对不过的已存文档数；storage 为
    可用／没有表／表读不了；unreadable 是自己的行读不了的课（每门都按表读不了处理）。"""

    storage: str
    documents: dict[str, list[CourseRequisiteDocument]] = field(default_factory=dict)
    unusable: Counter = field(default_factory=Counter)
    unreadable: set = field(default_factory=set)


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

    def _batch_rows(self, ids: list[str]) -> tuple[dict, list]:
        marks = ",".join("?" * len(ids))
        names = {row["course_id"]: (row["primary_code"], row["primary_name"]) for row in self._conn.execute(
            f"SELECT course_id,primary_code,primary_name FROM courses WHERE course_id IN ({marks})", ids)}
        rows = self._conn.execute(
            "SELECT course_id,catalog_year,document,content_hash FROM course_requisite_documents "
            f"WHERE course_id IN ({marks}) ORDER BY course_id, catalog_year DESC", ids).fetchall()
        return names, rows

    def read_batch(self, course_ids: list[str]) -> RequisiteBatch:
        """The documents of several courses for one answer, with the checks list_for_course applies
        (the course row's code and title, the edition, the content hash and the tree), in two queries;
        no program context. Read errors never fail the answer: a value SQLite cannot read fails the
        whole query, so then each course is read alone, and only a course whose own rows fail is
        unreadable (schema_unusable) while the others keep their documents.
        中文：一次回答要用的几门课的文档，核对和 list_for_course 相同（课程行的代码和名称、年度、内容
        hash、规则树），两次查询；不带培养方案上下文。读出错不让回答失败：SQLite 读不了的值会让整条查询
        失败，这时逐门课再读，只有自己的行读不了的课算 unreadable（表读不了），其他课照常。"""
        ids = list(dict.fromkeys(course_ids))
        batch = RequisiteBatch("available")
        try:
            if not self.available():
                return RequisiteBatch("schema_missing")
            if not ids:
                return batch
            names, rows = self._batch_rows(ids)
        except sqlite3.DatabaseError:
            log.warning("course.requisite_batch_unreadable", courses=len(ids))
            names, rows = {}, []
            for course_id in ids:
                try:
                    own_names, own_rows = self._batch_rows([course_id])
                except sqlite3.DatabaseError:
                    batch.unreadable.add(course_id)
                    log.warning("course.requisite_schema_unusable", course_id=course_id)
                else:
                    names.update(own_names)
                    rows.extend(own_rows)
        for row in rows:
            try:
                if row["course_id"] not in names:
                    raise ValueError("No course row")
                document = self._decode(row, names[row["course_id"]])
            except (ValueError, TypeError):
                batch.unusable[row["course_id"]] += 1
                log.warning("course.requisite_document_unusable", course_id=row["course_id"],
                            catalog_year=row["catalog_year"])
            else:
                batch.documents.setdefault(row["course_id"], []).append(document)
        return batch

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
        # Match chat: one passing row wins over invalid twins; two passing rows make that year unusable.
        # 中文：与聊天一致：只有一行核对通过就用它；同年两行都通过则该年全部不用。
        years = Counter(item.catalog_year for item in bundle.documents)
        bundle.unusable_records += sum(count for count in years.values() if count > 1)
        bundle.documents = [item for item in bundle.documents if years[item.catalog_year] == 1]
        if bundle.unusable_records:
            bundle.warnings.append("structured_requisites_unusable")
        if not rows:
            bundle.warnings.append("structured_requisites_missing")
        # Read-time context only: never mix program rules into course source hashes.
        plan_repo = ProgramPlanRepository(self._conn)
        bundle.program_contexts = [plan_repo.course_context(item.course_code, item.catalog_year) for item in bundle.documents]
        return bundle
