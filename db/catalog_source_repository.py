"""Separate provenance snapshots; NEVER infer official origin from raw_text.

中文：独立目录快照；来源不明的 raw_text 不能自动升级成官方内容。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

import structlog
from pydantic import ValidationError

from schemas.answer_evidence import CatalogSnapshot
from schemas.course import Course
from scrapers.neu_catalog import CatalogEntry

log = structlog.get_logger("neu_compass.catalog_sources")


class CatalogSourceRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def available(self) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='course_catalog_sources'",
        ).fetchone() is not None

    @staticmethod
    def snapshot(entry: CatalogEntry) -> CatalogSnapshot:
        record = {
            "course_code": entry.course_code, "course_name": entry.course_name,
            "description": (entry.description or "").strip() or None,
            "credits": entry.credits, "prereq_codes": entry.prereqs,
            "catalog_url": entry.catalog_url,
        }
        snapshot = CatalogSnapshot(
            **record, snapshot_id="pending", imported_at=datetime.now(timezone.utc),
        )
        canonical = snapshot.model_dump(mode="json", exclude={"snapshot_id", "imported_at", "retrieved_at"})
        digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        return snapshot.model_copy(update={"snapshot_id": f"catalog:{digest}"})

    def store(self, course_id: str, snapshot: CatalogSnapshot) -> None:
        """Caller owns transaction. No changes to Course JSON, status or raw_text."""
        row = self._conn.execute(
            "SELECT primary_code, primary_name FROM courses WHERE course_id=?", (course_id,),
        ).fetchone()
        if row is None or (row["primary_code"], row["primary_name"]) != (snapshot.course_code, snapshot.course_name):
            raise ValueError("Catalog snapshot must match the existing course code and title")
        self._conn.execute(
            "INSERT INTO course_catalog_sources(course_id, snapshot) VALUES(?,?) "
            "ON CONFLICT(course_id) DO UPDATE SET snapshot=excluded.snapshot",
            (course_id, snapshot.model_dump_json()),
        )

    def get_batch(self, courses: list[Course]) -> dict[str, CatalogSnapshot]:
        if not courses or not self.available():
            return {}
        placeholders = ",".join("?" for _ in courses)
        rows = self._conn.execute(
            f"SELECT course_id, snapshot FROM course_catalog_sources WHERE course_id IN ({placeholders})",
            [course.course_id for course in courses],
        ).fetchall()
        identities = {course.course_id: (course.primary_code, course.primary_name) for course in courses}
        snapshots = {}
        for row in rows:
            try:
                snapshot = CatalogSnapshot.model_validate_json(row["snapshot"])
                if identities[row["course_id"]] != (snapshot.course_code, snapshot.course_name):
                    raise ValueError("Snapshot identity mismatch")
                snapshots[row["course_id"]] = snapshot
            except (ValidationError, ValueError):
                log.warning("catalog.snapshot_unusable", course_id=row["course_id"])
        return snapshots
