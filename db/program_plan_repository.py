"""Scoped plan documents; no auto-DDL, no rewriting legacy seed/course rows."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime
from typing import NamedTuple

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


class PlanDowngradeError(ValueError):
    """Storing would replace verified plan provenance with a weaker version."""

    def __init__(self, downgrades: list[dict[str, str]]):
        self.downgrades = downgrades
        listed = ", ".join(f"{item['plan_id']} ({item['reason']})" for item in downgrades)
        super().__init__(f"Refusing to replace stored plans with less-verified or older versions: {listed}")

    def __reduce__(self):
        # Rebuild from the list, not from self.args (the message), so pickle/copy work;
        # the state dict carries __notes__ and any other attributes along.
        return type(self), (self.downgrades,), self.__dict__


class RecordedProvenance(NamedTuple):
    """The provenance fields a stored document records, read without plan validation."""

    source_html_sha256: str | None
    review_status: str | None
    captured_on: date | None


def provenance_downgrade(prior: ProgramPlan | RecordedProvenance | None, incoming: ProgramPlan) -> str | None:
    """Why replacing `prior` with `incoming` loses verified provenance, else None.

    A fingerprinted document (its source HTML is checked against the archive on
    every sync) must not give way to an unfingerprinted one, nor a source_checked
    document to a draft, nor a fingerprinted capture to an older one. A different
    fingerprint captured the same day or later is a re-capture, not a downgrade.
    The first rule that applies is the reason: fingerprint, review, capture date.
    The capture-date rule needs the stored capture date; without one it cannot apply,
    while the fingerprint and review rules still do.
    中文：已带来源指纹（每次同步都对照存档核验）的方案不能被无指纹版本替换，
    source_checked 不能被 draft 替换，带指纹的抓取也不能被更早的抓取替换；指纹不同、
    抓取日期相同或更晚属于重新抓取，不算降级。原因按指纹、审核、抓取日期的顺序取第一条。
    抓取日期规则需要旧行有抓取日期，读不出时这条不适用，指纹与审核两条照常适用。
    """
    if prior is None:
        return None
    if prior.source_html_sha256 and not incoming.source_html_sha256:
        return "drops_source_fingerprint"
    if prior.review_status == "source_checked" and incoming.review_status != "source_checked":
        return "drops_source_review"
    if (prior.source_html_sha256 and incoming.source_html_sha256
            and prior.source_html_sha256 != incoming.source_html_sha256
            and prior.captured_on is not None and incoming.captured_on < prior.captured_on):
        return "drops_newer_capture"
    return None


def _recorded(document: str) -> RecordedProvenance | None:
    """The provenance a stored document records; None unless it is a JSON object.

    Provenance checks read only these three fields from the raw JSON instead of
    validating the whole plan: a row whose content hash no longer matches, or whose
    document a newer or older build cannot validate (extra="forbid", a tightened
    validator), may still be the only record of a fingerprinted capture, so a weaker
    document must not replace it silently. Equally or better verified ones repair it.
    A field the object lacks (all three in {}) reads as None; any other fingerprint
    value counts as a fingerprint, so an unexpected shape errs on refusing.
    中文：防降级只从原始 JSON 读这三项，不做整份方案校验：哈希对不上、或新旧版本校验不过
    （extra="forbid"、校验收紧）的行，可能仍是某次带指纹抓取的唯一记录，较弱的版本不能
    悄悄覆盖；同等或更强的版本仍可修复。缺的字段（{} 三项全缺）读作 None；指纹字段只要
    有非空值就算有指纹，形状意外时宁可拒绝。
    """
    try:
        data = json.loads(document)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    fingerprint, status, captured = (data.get(key) for key in ("source_html_sha256", "review_status", "captured_on"))
    try:
        # datetime.fromisoformat also reads "2026-10-01T00:00:00", which a plan date accepts.
        captured_on = datetime.fromisoformat(captured).date() if isinstance(captured, str) else None
    except ValueError:
        captured_on = None
    return RecordedProvenance(
        None if fingerprint in (None, "") else str(fingerprint),
        status if isinstance(status, str) else None,
        captured_on,
    )


def _verified(row: sqlite3.Row) -> ProgramPlan:
    """The stored plan, or ValueError when its identity or content hash no longer matches."""
    plan = ProgramPlan.model_validate_json(row["document"])
    scope = (row["program_id"], row["campus"], row["catalog_year"], row["pathway"], row["concentration"])
    if plan.scope_key() != scope or plan.plan_id != row["plan_id"] or content_hash(plan) != row["content_hash"]:
        raise ValueError("Stored plan identity/content mismatch")
    return plan


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

    def store(self, plan: ProgramPlan, *, allow_downgrade: bool = False) -> bool:
        """Caller owns transaction; True means content changed, not source verified.

        Raises PlanDowngradeError instead of replacing a stored plan with a
        less-verified one, unless allow_downgrade. The stored side is judged by
        what its document records, even when it fails integrity or plan validation.
        """
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
        if prior and not allow_downgrade:
            reason = provenance_downgrade(_recorded(prior["document"]), plan)
            if reason:
                raise PlanDowngradeError([{"plan_id": plan.plan_id, "reason": reason}])
        self._conn.execute(
            "INSERT INTO program_plans(plan_id, program_id, campus, catalog_year, pathway, concentration, document, content_hash) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(plan_id) DO UPDATE SET document=excluded.document, content_hash=excluded.content_hash",
            (plan.plan_id, *plan.scope_key(), plan.model_dump_json(), digest),
        )
        return True

    def recorded(self, plan_id: str) -> RecordedProvenance | None:
        """The provenance the stored document for plan_id records, or None."""
        if not self.available():
            return None
        row = self._conn.execute("SELECT document FROM program_plans WHERE plan_id=?", (plan_id,)).fetchone()
        return _recorded(row["document"]) if row else None

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
                plans.append(_verified(row))
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
