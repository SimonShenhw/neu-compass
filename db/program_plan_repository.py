"""Scoped plan documents; no auto-DDL, no rewriting legacy seed/course rows."""

from __future__ import annotations

import hashlib
import json
import sqlite3

import structlog

from schemas.program_plan import ProgramPlan
from schemas.course_program_context import CourseProgramContext, explicitly_mentions

log = structlog.get_logger("neu_compass.program_plans")


def content_hash(plan: ProgramPlan) -> str:
    data = plan.model_dump(mode="json")
    # New optional capabilities must not invalidate persisted 05A documents.
    # 中文：忽略本批新增字段的空默认值，保持旧文档摘要可读；非空新规则参与摘要。
    if data.get("source_html_sha256") is None:
        data.pop("source_html_sha256", None)
    stack = [data["requirements"]]
    while stack:
        node = stack.pop()
        for key in ("subject_codes", "course_ranges", "excluded_course_codes", "activate_when"):
            if not node.get(key):
                node.pop(key, None)
        stack.extend(node["children"])
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ProgramPlanRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def available(self) -> bool:
        return self._conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='program_plans'").fetchone() is not None

    def has_records_for_program(self, program_id: str) -> bool:
        # Even corrupt scoped records must not silently reactivate guessed schedules.
        return self.available() and self._conn.execute(
            "SELECT 1 FROM program_plans WHERE program_id=? LIMIT 1", (program_id,),
        ).fetchone() is not None

    def store(self, plan: ProgramPlan) -> bool:
        """Caller owns transaction; True means content changed, not source verified."""
        plan = ProgramPlan.model_validate(plan.model_dump())
        if not self.available():
            raise ValueError("Program plan schema missing")
        if not self._conn.execute("SELECT 1 FROM programs WHERE program_id=?", (plan.program_id,)).fetchone():
            raise ValueError("Plan needs an existing program; do not create/replace legacy seeds here")
        self.validate_slot(plan)
        prior = self._conn.execute("SELECT * FROM program_plans WHERE plan_id=?", (plan.plan_id,)).fetchone()
        digest = content_hash(plan)
        if prior and prior["content_hash"] == digest:
            try:
                stored = ProgramPlan.model_validate_json(prior["document"])
                if stored == plan:
                    return False
            except ValueError:
                pass
        self._conn.execute(
            "INSERT INTO program_plans(plan_id, program_id, campus, catalog_year, pathway, concentration, document, content_hash) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(plan_id) DO UPDATE SET document=excluded.document, content_hash=excluded.content_hash",
            (plan.plan_id, *plan.scope_key(), plan.model_dump_json(), digest),
        )
        return True

    def validate_slot(self, plan: ProgramPlan) -> None:
        if not self.available():
            return
        prior = self._conn.execute("SELECT * FROM program_plans WHERE plan_id=?", (plan.plan_id,)).fetchone()
        if prior and (prior["program_id"], prior["campus"], prior["catalog_year"], prior["pathway"], prior["concentration"]) != plan.scope_key():
            raise ValueError("Existing plan ID cannot be rebound to another scope")
        occupied = self._conn.execute(
            "SELECT plan_id FROM program_plans WHERE program_id=? AND campus=? AND catalog_year=? AND pathway=? AND concentration=?",
            plan.scope_key(),
        ).fetchone()
        if occupied and occupied["plan_id"] != plan.plan_id:
            raise ValueError("Scope already has another plan ID")

    def list_for_program(self, program_id: str, *, campus: str | None = None,
                         catalog_year: str | None = None, pathway: str | None = None) -> list[ProgramPlan]:
        if not self.available():
            return []
        clauses, params = ["program_id=?"], [program_id]
        for key, value in (("campus", campus), ("catalog_year", catalog_year), ("pathway", pathway)):
            if value is not None:
                clauses.append(f"{key}=?")
                params.append(value)
        rows = self._conn.execute(
            f"SELECT * FROM program_plans WHERE {' AND '.join(clauses)} ORDER BY catalog_year DESC, campus, pathway, concentration, plan_id",
            params,
        ).fetchall()
        plans = []
        for row in rows:
            try:
                plan = ProgramPlan.model_validate_json(row["document"])
                scope = (row["program_id"], row["campus"], row["catalog_year"], row["pathway"], row["concentration"])
                if plan.scope_key() != scope or plan.plan_id != row["plan_id"] or content_hash(plan) != row["content_hash"]:
                    raise ValueError("Stored plan identity/content mismatch")
                plans.append(plan)
            except ValueError:
                log.warning("program.plan_unusable", plan_id=row["plan_id"])
        return plans

    def course_context(self, course_code: str, catalog_year: str) -> CourseProgramContext:
        """All explicitly named scopes, not an inferred personal program or grade."""
        context = CourseProgramContext(course_code=course_code, catalog_year=catalog_year,
            schema_available=self.available(), warnings=["explicit_mentions_only_not_personal_applicability",
                "program_rules_not_merged_with_course_prerequisite_grades", "no_match_is_not_no_program_policy"])
        if not context.schema_available:
            context.warnings.append("program_context_schema_unavailable")
            return context
        try:
            rows = self._conn.execute(
                "SELECT plan_id,program_id,campus,catalog_year,pathway,concentration,document,content_hash "
                "FROM program_plans WHERE catalog_year=? ORDER BY program_id,campus,pathway,concentration,plan_id",
                (context.catalog_year,),
            ).fetchall()
        except sqlite3.DatabaseError:
            context.warnings.append("program_context_schema_unusable")
            return context
        for row in rows:
            try:
                if len(row["document"]) > 200_000:
                    raise ValueError("Stored context outside budget")
                plan = ProgramPlan.model_validate_json(row["document"])
                scope = (row["program_id"], row["campus"], row["catalog_year"], row["pathway"], row["concentration"])
                if plan.scope_key() != scope or plan.plan_id != row["plan_id"] or content_hash(plan) != row["content_hash"]:
                    raise ValueError("Stored plan context identity/content mismatch")
                if not explicitly_mentions(plan.requirements, context.course_code):
                    continue
                if plan.review_status != "source_checked":
                    context.unreviewed_records += 1
                    continue
                context.plans.append(plan)
            except (ValueError, TypeError):
                context.unusable_records += 1  # Same-year rows; relevance cannot be recovered safely.
                log.warning("program.course_context_unusable", plan_id=row["plan_id"])
        if (len({plan.plan_id for plan in context.plans}) != len(context.plans)
                or len({plan.scope_key() for plan in context.plans}) != len(context.plans)):
            # A broken table without original constraints must not choose a winner.
            context.unusable_records += len(context.plans)
            context.plans.clear()
            context.warnings.append("program_context_duplicate_identity_or_scope")
        if context.unusable_records:
            context.warnings.append("program_context_records_unusable")
        if context.unreviewed_records:
            context.warnings.append("program_context_records_unreviewed")
        if not context.plans:
            context.warnings.append("program_context_no_explicit_checked_match")
        return context
