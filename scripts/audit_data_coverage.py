"""Read-only data coverage, conflict and source report over an explicit offline SQLite copy.

Answers "which course and which field to fill next" with counts, not a single course total. Every
count names its denominator, and every category has a one-line rule in the report; categories of
one denominator are exclusive and add up to it. A section whose table is missing (or whose input
section could not be checked) is "not_checked" with a code, so a check that did not run never reads
as "checked, nothing found". Default output is aggregate counts only; --details adds bounded lists
of course codes and plan IDs per gap category.

The copy is opened like release_preflight.py opens it: an existing local file without -wal/-shm/
-journal sidecars, mode=ro&immutable=1, query_only, trusted_schema=OFF, one BEGIN snapshot, a
time/VM-step budget, and a fingerprint compared before and after. On top of that a SQLite
authorizer allows only the listed columns of the course, catalog, requisite and program tables
and denies everything else, including SQL functions and reads through views or triggers. User
tables (users, query_log, Co-op, chat answers, feedback) and courses.raw_text are never read. No
writes, no network, no Settings/.env. Unknown catalog retrieval dates stay unknown; a hash or a
source_checked review is never counted as officially correct or currently applicable, and a
partial plan is never counted as complete.

中文：对显式给出的离线 SQLite 副本做只读的数据覆盖、冲突与来源报告，回答「下一批补哪门课、
哪个字段」。每个计数都写明分母，每个类别都在报告里附一句规则；同一分母下的类别互斥、相加
等于分母。表不存在（或依赖的上一节没查成）时该节是 not_checked 并带原因码，不会把「没查」
写成「查了、没问题」。默认只输出汇总计数；--details 才附上各缺口类别的课程代码与方案 ID
（有上限）。打开方式与 release_preflight.py 相同：已存在、无旁文件的本地副本，mode=ro&
immutable=1、query_only、trusted_schema=OFF、一次 BEGIN 快照、执行预算，前后核对文件指纹。
另加 SQLite 授权回调：只允许读列出的课程、目录、先修和培养方案表的指定列，其余一律拒绝，
包括 SQL 函数和经由视图/触发器的读取。用户表（users、query_log、Co-op、聊天回答、反馈）和
courses.raw_text 从不读取。不写入、不联网、不读 Settings/.env。抓取日期未知就写未知；hash 或
source_checked 不算官方正确或当前适用；partial 方案不算完整。
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.course_requisite_repository import content_hash as requisite_content_hash  # noqa: E402
from db.program_plan_repository import content_hash as plan_content_hash  # noqa: E402
from rag.answer_evidence import AVAILABILITY_FIELDS, course_answer_evidence  # noqa: E402
from schemas.answer_evidence import CatalogSnapshot  # noqa: E402
from schemas.catalog_credit_hours import CatalogCreditHours  # noqa: E402
from schemas.course import COURSE_CODE_PATTERN, Course  # noqa: E402
from schemas.course_requisite_document import CourseRequisiteDocument  # noqa: E402
from schemas.program_plan import ProgramPlan  # noqa: E402
from scripts.release_preflight import (  # noqa: E402
    MAX_DB_BYTES, Inputs, PreflightError, _existing, _sidecars_absent,
)

FORMAT_VERSION = 1
MAX_ROWS = 200_000  # Per table; more rows fail the section instead of truncating it.
MAX_COURSE_JSON = 1_000_000
MAX_SNAPSHOT_JSON = 100_000
MAX_DOCUMENT_JSON = 200_000  # The repositories' own budget for requisite and plan documents.
DEADLINE_SECONDS = 60
MAX_VM_STEPS = 500_000_000
PROGRESS_INTERVAL = 10_000  # SQLite VM steps between budget checks.
DEFAULT_MAX_CODES = 25
MAX_CODES_LIMIT = 500
EXPECTED_VERSIONS = frozenset(f"1.{number}" for number in range(8))
COURSE_STATUSES = ("pending", "indexed", "failed")
EDITION = re.compile(r"\d{4}-\d{4}")
PLAN_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,99}")

# Columns the authorizer lets a statement read; nothing else, not even through a view.
# 中文：授权回调只放行这些列；其余一律拒绝，经由视图读取也不行。
READABLE = {
    "sqlite_master": frozenset({"type", "name"}),
    "schema_versions": frozenset({"version"}),
    "courses": frozenset({"course_id", "primary_code", "primary_name", "status", "generated_json"}),
    "course_catalog_sources": frozenset({"course_id", "snapshot"}),
    "course_requisite_documents": frozenset({"course_id", "catalog_year", "document", "content_hash"}),
    "programs": frozenset({"program_id"}),
    "program_plans": frozenset({"plan_id", "program_id", "campus", "catalog_year", "pathway",
                                "concentration", "document", "content_hash"}),
    "program_required_courses": frozenset({"program_id", "course_id"}),
    "course_prerequisites": frozenset({"course_id", "prereq_course_id"}),
}
DATA_TABLES = tuple(name for name in READABLE if name != "sqlite_master")

FIELD_CATEGORIES = ("missing", "catalog_only", "catalog_conflict", "catalog_consistent",
                    "extracted_estimate", "course_sources_only", "no_recorded_source")
LIMITATIONS = (
    "offline_copy_consistency_is_not_proven",
    "catalog_url_and_hash_checks_are_not_authenticity_or_current_offering",
    "source_checked_means_a_person_compared_the_capture_not_official_or_current",
    "extracted_estimates_are_not_official_facts",
    "course_level_source_ids_do_not_say_which_field_they_support",
    "unknown_retrieval_dates_stay_unknown",
    "legacy_seed_rows_are_not_verified_rules",
    "query_demand_not_read_so_no_enrichment_priority",
)

RULES = {
    "courses": {
        "oversize": "generated_json longer than 1,000,000 characters; not decoded",
        "invalid_json": "generated_json is not text or not valid JSON",
        "invalid_record": "valid JSON that the Course model rejects, as the API would",
        "identity_mismatch": "course_id, primary_code or primary_name column differs from the decoded record; "
                             "excluded because every join would be ambiguous",
        "synthetic": "decoded record the answer path marks synthetic_record_not_real_course; excluded from coverage",
        "in_scope": "every other row: the denominator of the course-level sections",
        "duplicate_code_rows": "in-scope rows whose code another in-scope row also has (not exclusive)",
    },
    "catalog_snapshots": {
        "usable": "one snapshot row that the CatalogSnapshot model accepts and whose code and title equal the "
                  "course's, which is when the answer path attaches it",
        "absent": "no snapshot row for the course",
        "duplicate_rows": "more than one snapshot row for the course; none is used",
        "oversize": "snapshot longer than 100,000 characters",
        "invalid_json": "snapshot is not text or not valid JSON",
        "invalid_record": "valid JSON that the CatalogSnapshot model rejects",
        "identity_mismatch": "snapshot code or title differs from the course's (a name inconsistency); not attached",
        "orphan_rows": "snapshot rows whose course_id is not in courses (denominator: snapshot rows)",
        "rows_for_courses_out_of_scope": "snapshot rows of excluded courses (denominator: snapshot rows)",
        "retrieval_date_unknown": "usable snapshot without retrieved_at; import time is never used instead",
    },
    "fields": {
        "missing": "no stored value (None or empty list; 0 counts as a value), and no catalog value",
        "catalog_only": "no stored value, but the usable catalog snapshot has one (credits, prereqs)",
        "catalog_conflict": "stored value differs from the usable catalog snapshot (credits; prereq code sets, "
                            "including codes the snapshot does not list)",
        "catalog_consistent": "stored value equals the usable catalog snapshot (credits; prereq code sets)",
        "extracted_estimate": "stored value with an evidence snippet for the field: extracted, not official",
        "course_sources_only": "stored value without field evidence; the course records source IDs, which do "
                               "not say which field they support",
        "no_recorded_source": "stored value with no field evidence, no source IDs and no catalog comparison",
    },
    "requisite_documents": {
        "usable": "decodes as CourseRequisiteDocument, matches its row's course and edition and the course's "
                  "code and title, and its content hash matches: what the course detail page would show",
        "orphan_rows": "course_id not in courses",
        "rows_for_courses_out_of_scope": "document of an excluded course",
        "duplicate_rows": "more than one row for the same course and edition; none is used",
        "oversize": "document longer than 200,000 characters",
        "invalid_json": "document is not text or not valid JSON",
        "invalid_record": "valid JSON that the document model rejects (including a syntax tree that no longer "
                          "matches its clause)",
        "row_identity_mismatch": "document course_id or edition differs from its row",
        "course_identity_mismatch": "document code or title differs from the course's",
        "content_hash_mismatch": "stored content hash differs from the document's",
        "legacy_prereqs_without_usable_document": "in-scope course with a stored prereq code list and no usable "
                                                  "document in any edition: answers rely on the code list only",
    },
    "program_plans": {
        "usable": "decodes as ProgramPlan, matches its row's plan ID and scope, content hash matches, and no "
                  "other usable row has the same scope or plan ID",
        "orphan_rows": "program_id not in programs",
        "oversize": "document longer than 200,000 characters",
        "invalid_json": "document is not text or not valid JSON",
        "invalid_record": "valid JSON that the ProgramPlan model rejects",
        "identity_mismatch": "document plan ID or scope differs from its row",
        "content_hash_mismatch": "stored content hash differs from the document's",
        "duplicate_scope_or_id": "usable rows that share a scope or plan ID; no winner is chosen",
        "complete": "coverage 'complete' (the model requires source_checked and no unmodeled rule); "
                    "partial is never counted as complete",
        "source_checked": "a person recorded comparing the document with its capture; not official correctness "
                          "or current applicability",
    },
    "legacy_rows": {
        "rows": "legacy seed rows, counted only; not verified program rules or prerequisite logic",
        "rows_for_courses_out_of_scope": "rows naming a course that is not in scope (excluded or missing)",
        "rows_for_unknown_programs": "program_required_courses rows whose program_id is not a text ID in programs",
    },
}


class _NotChecked(Exception):
    """A section that could not run; its code says why."""


class _Failed(Exception):
    """A section that ran into a fixed, known failure; its code says which."""


class _Reads:
    """SQLite authorizer: SELECT of the READABLE columns only, never through a view or trigger.

    中文：SQLite 授权回调：只允许 SELECT 读 READABLE 里的列，不允许经由视图或触发器读取。
    """

    def __init__(self):
        self.denied = 0

    def __call__(self, action, table, column, database, source):
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_TRANSACTION and table in ("BEGIN", "ROLLBACK"):
            return sqlite3.SQLITE_OK
        if (action == sqlite3.SQLITE_READ and source is None and database in (None, "main")
                and column in READABLE.get(table, ())):
            return sqlite3.SQLITE_OK
        self.denied += 1
        return sqlite3.SQLITE_DENY


def _decode(text, budget, model):
    """(category, value) with category 'decoded', 'oversize', 'invalid_json' or 'invalid_record'."""
    if not isinstance(text, str):
        return "invalid_json", None
    if len(text) > budget:
        return "oversize", None
    try:
        json.loads(text)
    except (ValueError, RecursionError):
        return "invalid_json", None
    try:
        return "decoded", model.model_validate_json(text)
    except (ValueError, RecursionError):  # pydantic's ValidationError is a ValueError.
        return "invalid_record", None


def _department(code: str) -> str:
    return code.split()[0]


def _listable_code(value) -> str | None:
    """A column value fit for --details: a well-formed course code, normalized; else None."""
    if not isinstance(value, str):
        return None
    match = COURSE_CODE_PATTERN.fullmatch(value.strip().upper())
    return f"{match.group(1)} {match.group(2)}" if match else None


def _codes(values) -> set[str]:
    return {" ".join(value.split()).upper() for value in values}


def field_category(course: Course, field: str, snapshot: CatalogSnapshot | None) -> str:
    """The FIELD_CATEGORIES entry for one stored field; RULES['fields'] says what each means.

    The catalog comparison comes first (credits and prereqs, only when a usable snapshot has a value),
    then the field's own evidence, then the course's recorded sources.
    中文：先和可用目录快照比较（只有学分和先修代码，且快照里有值时），再看该字段的抽取证据，
    最后看课程记录的来源 ID。
    """
    value = getattr(course, field)
    if snapshot is not None and field == "credits" and snapshot.credits is not None:
        if value is None:
            return "catalog_only"
        return "catalog_consistent" if value == snapshot.credits else "catalog_conflict"
    if snapshot is not None and field == "prereqs":
        stored, listed = _codes(value), _codes(snapshot.prereq_codes)
        if stored or listed:
            if not stored:
                return "catalog_only"
            return "catalog_consistent" if stored == listed else "catalog_conflict"
    if value is None or value == []:
        return "missing"
    if any(snippet.field == field for snippet in course.evidence_snippets):
        return "extracted_estimate"
    return "course_sources_only" if course.source_review_ids else "no_recorded_source"


def credit_comparison(hours: CatalogCreditHours | None, credits: int | None) -> str:
    """How a requisite document's literal catalog hours compare with the course's stored credits.

    Only a fixed whole number is compared: a range is not a selected section's credits, and a
    fraction cannot equal the integer credits field.
    中文：只比较固定的整数学时；范围不是某个班次的学分，小数也不可能等于整数学分字段。
    """
    if hours is None:
        return "not_captured"
    if hours.kind == "range":
        return "range_not_compared"
    if hours.fixed_integer() is None:
        return "fractional_not_compared"
    if credits is None:
        return "course_credits_missing"
    return "consistent" if hours.fixed_integer() == credits else "conflict"


def _nonzero(counter) -> dict:
    return {key: value for key, value in sorted(counter.items()) if value}


def _all(keys, counter) -> dict:
    return {key: counter.get(key, 0) for key in keys}


def _date_range(values) -> dict:
    days = sorted(value.date().isoformat() for value in values)
    return {"earliest": days[0] if days else None, "latest": days[-1] if days else None}


class _Audit:
    def __init__(self, conn: sqlite3.Connection, reads: _Reads, details: bool):
        self.conn, self.reads, self.want_details = conn, reads, details
        self.sections: dict[str, dict] = {}
        self.details: dict[str, dict] = defaultdict(dict)
        self.tables: set[str] = set()
        self.scope: dict[str, Course] = {}  # In-scope courses by course_id.
        self.known_ids: set[str] = set()  # Every course_id in courses, decodable or not.
        self.snapshots: dict[str, CatalogSnapshot] = {}  # Usable snapshots by course_id.
        self.documents: dict[str, set[str]] = defaultdict(set)  # course_id -> editions with a usable document.
        self.program_ids: set | None = None

    # --- plumbing -------------------------------------------------------------------------------

    def run(self, name, function):
        denied = self.reads.denied
        try:
            self.sections[name] = {"status": "checked", **function()}
        except _NotChecked as exc:
            self.sections[name] = {"status": "not_checked", "code": exc.args[0]}
        except _Failed as exc:
            self.sections[name] = {"status": "failed", "code": exc.args[0]}
        except sqlite3.Error:
            # SQLite messages can quote schema text; report a fixed code only.
            code = "read_outside_allowlist" if self.reads.denied > denied else "database_error"
            self.sections[name] = {"status": "failed", "code": code}
        except Exception:
            self.sections[name] = {"status": "failed", "code": "section_failed"}
        if self.sections[name]["status"] != "checked":
            self.details.pop(name, None)  # No lists from a section that did not finish.

    def rows(self, sql):
        rows = self.conn.execute(sql).fetchmany(MAX_ROWS + 1)
        if len(rows) > MAX_ROWS:
            raise _Failed("row_budget")
        return rows

    def require(self, *tables):
        if any(table not in self.tables for table in tables):
            raise _NotChecked("table_missing")

    def require_section(self, name):
        if self.sections.get(name, {}).get("status") != "checked":
            raise _NotChecked(f"{name}_not_checked")

    def programs(self) -> set | None:
        """Every program_id in programs, or None when that table is missing."""
        if self.program_ids is None and "programs" in self.tables:
            self.program_ids = {row["program_id"] for row in self.rows("SELECT program_id FROM programs")}
        return self.program_ids

    def note(self, section, key, item):
        if self.want_details:
            self.details[section].setdefault(key, []).append(item)

    # --- sections -------------------------------------------------------------------------------

    def schema(self):
        self.tables = {row["name"] for row in self.rows("SELECT type, name FROM sqlite_master")
                       if row["type"] == "table" and isinstance(row["name"], str)}
        result = {"rule": "data tables this report reads, found by name with type 'table'; a view or other "
                          "object of that name counts as missing",
                  "tables": {name: name in self.tables for name in DATA_TABLES}}
        if "schema_versions" in self.tables:
            versions = [row["version"] for row in self.rows("SELECT version FROM schema_versions")]
            result["schema_versions"] = {
                "present": sorted(EXPECTED_VERSIONS.intersection(versions)),
                "missing": sorted(EXPECTED_VERSIONS.difference(versions)),
                "other_rows": sum(version not in EXPECTED_VERSIONS for version in versions),
            }
        return result

    def courses(self):
        self.require("courses")
        rows = self.rows("SELECT course_id, primary_code, primary_name, status, generated_json FROM courses")
        counts, statuses = Counter(), Counter()
        departments = Counter()
        for row in rows:
            self.known_ids.add(row["course_id"])
            statuses[row["status"] if row["status"] in COURSE_STATUSES else "other"] += 1
            category, course = _decode(row["generated_json"], MAX_COURSE_JSON, Course)
            if course is not None:
                if (row["course_id"], row["primary_code"], row["primary_name"]) != (
                        course.course_id, course.primary_code, course.primary_name):
                    category = "identity_mismatch"
                elif "synthetic_record_not_real_course" in course_answer_evidence(course).warnings:
                    category = "synthetic"
                else:
                    category = "in_scope"
                    self.scope[course.course_id] = course
                    departments[_department(course.primary_code)] += 1
            counts[category] += 1
            if category not in ("in_scope", "synthetic"):
                self.note("courses", category, _listable_code(row["primary_code"]))
        codes = Counter(course.primary_code for course in self.scope.values())
        duplicates = {code: count for code, count in codes.items() if count > 1}
        for code in duplicates:
            self.note("courses", "duplicate_codes", code)
        exclusive = ("in_scope", "synthetic", "identity_mismatch", "invalid_record", "invalid_json", "oversize")
        return {
            "denominator": {"course_rows": len(rows)},
            "counts": _all(exclusive, counts),
            "in_scope": {"denominator": len(self.scope), "duplicate_code_groups": len(duplicates),
                         "duplicate_code_rows": sum(duplicates.values()),
                         "by_department": dict(sorted(departments.items()))},
            "status_column": _all((*COURSE_STATUSES, "other"), statuses),
            "rules": RULES["courses"],
        }

    def catalog_snapshots(self):
        self.require_section("courses")
        self.require("course_catalog_sources")
        rows = self.rows("SELECT course_id, snapshot FROM course_catalog_sources")
        per_course = defaultdict(list)
        extra = Counter()
        for row in rows:
            if row["course_id"] not in self.known_ids:
                extra["orphan_rows"] += 1
            elif row["course_id"] not in self.scope:
                extra["rows_for_courses_out_of_scope"] += 1
            else:
                per_course[row["course_id"]].append(row["snapshot"])
        counts, departments = Counter(), defaultdict(Counter)
        for course_id, course in self.scope.items():
            stored = per_course.get(course_id, [])
            if not stored:
                category = "absent"
            elif len(stored) > 1:
                category = "duplicate_rows"
            else:
                category, snapshot = _decode(stored[0], MAX_SNAPSHOT_JSON, CatalogSnapshot)
                if snapshot is not None:
                    if (snapshot.course_code, snapshot.course_name) != (course.primary_code, course.primary_name):
                        category = "identity_mismatch"
                    else:
                        category = "usable"
                        self.snapshots[course_id] = snapshot
            counts[category] += 1
            departments[_department(course.primary_code)][category] += 1
            if category != "usable":
                self.note("catalog_snapshots", category, course.primary_code)
        usable = list(self.snapshots.values())
        known = [snapshot.retrieved_at for snapshot in usable if snapshot.retrieved_at is not None]
        exclusive = ("usable", "absent", "duplicate_rows", "identity_mismatch", "invalid_record", "invalid_json",
                     "oversize")
        return {
            "denominator": {"courses_in_scope": len(self.scope)},
            "counts": _all(exclusive, counts),
            "snapshot_rows": {"denominator": len(rows),
                              **_all(("orphan_rows", "rows_for_courses_out_of_scope"), extra)},
            "usable": {
                "denominator": len(usable),
                "retrieval_date_unknown": len(usable) - len(known),
                "retrieval_date_known": len(known),
                "retrieved_on": _date_range(known),
                "description_missing": sum(not snapshot.description for snapshot in usable),
                "credits_missing": sum(snapshot.credits is None for snapshot in usable),
                "prereq_codes_listed": sum(bool(snapshot.prereq_codes) for snapshot in usable),
            },
            "by_department": {name: {"courses_in_scope": sum(counter.values()), **_nonzero(counter)}
                              for name, counter in sorted(departments.items())},
            "rules": RULES["catalog_snapshots"],
        }

    def fields(self):
        self.require_section("courses")
        compared = self.sections.get("catalog_snapshots", {}).get("status") == "checked"
        table = {field: Counter() for field in AVAILABILITY_FIELDS}
        departments = defaultdict(lambda: {field: Counter() for field in AVAILABILITY_FIELDS})
        sizes, warnings, description = Counter(), Counter(), Counter()
        for course_id, course in self.scope.items():
            department = _department(course.primary_code)
            sizes[department] += 1
            snapshot = self.snapshots.get(course_id) if compared else None
            # The same warnings the chat prompt and the course page get for this course.
            warnings.update(set(course_answer_evidence(course, snapshot).warnings))
            description["present_in_usable_snapshot" if snapshot and snapshot.description else "missing"] += 1
            for field in AVAILABILITY_FIELDS:
                category = field_category(course, field, snapshot)
                table[field][category] += 1
                departments[department][field][category] += 1
                if category in ("missing", "catalog_only", "catalog_conflict"):
                    self.note("fields", f"{field}.{category}", course.primary_code)
        result = {
            "denominator": {"courses_in_scope": len(self.scope)},
            "categories": list(FIELD_CATEGORIES),
            "fields": {field: _all(FIELD_CATEGORIES, counter) for field, counter in table.items()},
            "by_department": {
                name: {"courses_in_scope": sizes[name],
                       **{field: _nonzero(counter) for field, counter in fields.items()}}
                for name, fields in sorted(departments.items())},
            "rules": RULES["fields"],
        }
        if compared:
            result["catalog_comparison"] = {"status": "checked"}
            result["catalog_description"] = _all(("present_in_usable_snapshot", "missing"), description)
            result["answer_warnings"] = dict(sorted(warnings.items()))
        else:
            # Without checked snapshots the catalog categories would read as zero and the warnings as
            # "no catalog source": say that they were not compared instead.
            for key in ("catalog_comparison", "catalog_description", "answer_warnings"):
                result[key] = {"status": "not_checked", "code": "catalog_snapshots_not_checked"}
        return result

    def requisite_documents(self):
        self.require_section("courses")
        self.require("course_requisite_documents")
        rows = self.rows("SELECT course_id, catalog_year, document, content_hash FROM course_requisite_documents")
        seen = Counter((row["course_id"], row["catalog_year"]) for row in rows)
        counts = Counter()
        editions = defaultdict(lambda: {"usable": 0, "unusable": 0, "prerequisite": Counter(),
                                        "corequisite": Counter(), "description_evidence": Counter(),
                                        "credit_hours_vs_course_credits": Counter(), "captured": [],
                                        "courses": set()})
        for row in rows:
            course_id = row["course_id"]
            edition = row["catalog_year"] if isinstance(row["catalog_year"], str) and EDITION.fullmatch(
                row["catalog_year"]) else "unrecognized"
            document = None
            if course_id not in self.known_ids:
                category = "orphan_rows"
            elif course_id not in self.scope:
                category = "rows_for_courses_out_of_scope"
            elif seen[(course_id, row["catalog_year"])] > 1:
                category = "duplicate_rows"
            else:
                course = self.scope[course_id]
                category, document = _decode(row["document"], MAX_DOCUMENT_JSON, CourseRequisiteDocument)
                if document is not None:
                    if (document.course_id, document.catalog_year) != (course_id, row["catalog_year"]):
                        category = "row_identity_mismatch"
                    elif (document.course_code, document.course_name) != (course.primary_code, course.primary_name):
                        category = "course_identity_mismatch"
                    elif requisite_content_hash(document) != row["content_hash"]:
                        category = "content_hash_mismatch"
                    else:
                        category = "usable"
            counts[category] += 1
            if category != "usable":
                editions[edition]["unusable"] += 1
                if course_id in self.scope:
                    self.note("requisite_documents", category,
                              {"code": self.scope[course_id].primary_code, "catalog_year": edition})
                continue
            course = self.scope[course_id]
            stats = editions[document.catalog_year]
            stats["usable"] += 1
            stats["courses"].add(course_id)
            stats["captured"].append(document.source.captured_at)
            self.documents[course_id].add(document.catalog_year)
            for name in ("prerequisite", "corequisite"):
                section = getattr(document.requisites, name)
                stats[name][section.status] += 1
                if section.status == "unparsed":
                    self.note("requisite_documents", f"{name}_unparsed",
                              {"code": course.primary_code, "catalog_year": document.catalog_year})
            evidence = document.description_evidence
            stats["description_evidence"][evidence.status if evidence else "not_captured"] += 1
            comparison = credit_comparison(document.credit_hours, course.credits)
            stats["credit_hours_vs_course_credits"][comparison] += 1
            if comparison == "conflict":
                self.note("requisite_documents", "credit_hours_conflict",
                          {"code": course.primary_code, "catalog_year": document.catalog_year})
        departments = defaultdict(lambda: {"courses_in_scope": 0, "with_usable_document": Counter()})
        legacy_only = 0
        for course_id, course in self.scope.items():
            department = departments[_department(course.primary_code)]
            department["courses_in_scope"] += 1
            for edition in self.documents.get(course_id, ()):
                department["with_usable_document"][edition] += 1
            if course.prereqs and not self.documents.get(course_id):
                legacy_only += 1
                self.note("requisite_documents", "legacy_prereqs_without_usable_document", course.primary_code)
        exclusive = ("usable", "orphan_rows", "rows_for_courses_out_of_scope", "duplicate_rows", "oversize",
                     "invalid_json", "invalid_record", "row_identity_mismatch", "course_identity_mismatch",
                     "content_hash_mismatch")
        return {
            "denominator": {"document_rows": len(rows)},
            "counts": _all(exclusive, counts),
            "by_catalog_year": {
                edition: {
                    "usable": stats["usable"], "unusable": stats["unusable"],
                    "courses_in_scope_covered": len(stats["courses"]),
                    "prerequisite": _all(("parsed", "unparsed", "not_listed"), stats["prerequisite"]),
                    "corequisite": _all(("parsed", "unparsed", "not_listed"), stats["corequisite"]),
                    "description_evidence": _all(("not_listed", "no_keyword_match", "review_needed", "not_captured"),
                                                 stats["description_evidence"]),
                    "credit_hours_vs_course_credits": _all(
                        ("consistent", "conflict", "course_credits_missing", "range_not_compared",
                         "fractional_not_compared", "not_captured"), stats["credit_hours_vs_course_credits"]),
                    "captured_on": _date_range(stats["captured"]),
                } for edition, stats in sorted(editions.items())},
            "courses_in_scope": {"denominator": len(self.scope),
                                 "with_usable_document_any_year": len(self.documents),
                                 "legacy_prereqs_without_usable_document": legacy_only},
            "by_department": {name: {"courses_in_scope": item["courses_in_scope"],
                                     "with_usable_document": dict(sorted(item["with_usable_document"].items()))}
                              for name, item in sorted(departments.items())},
            "rules": RULES["requisite_documents"],
        }

    def program_plans(self):
        self.require("program_plans")
        program_ids = self.programs()
        rows = self.rows("SELECT plan_id, program_id, campus, catalog_year, pathway, concentration, document, "
                         "content_hash FROM program_plans")
        counts, candidates = Counter(), []
        for row in rows:
            if program_ids is not None and row["program_id"] not in program_ids:
                category = "orphan_rows"
            else:
                category, plan = _decode(row["document"], MAX_DOCUMENT_JSON, ProgramPlan)
                if plan is not None:
                    scope = (row["program_id"], row["campus"], row["catalog_year"], row["pathway"], row["concentration"])
                    if plan.scope_key() != scope or plan.plan_id != row["plan_id"]:
                        category = "identity_mismatch"
                    elif plan_content_hash(plan) != row["content_hash"]:
                        category = "content_hash_mismatch"
                    else:
                        candidates.append(plan)
                        continue
            counts[category] += 1
            plan_id = row["plan_id"] if isinstance(row["plan_id"], str) and PLAN_ID.fullmatch(row["plan_id"]) else None
            self.note("program_plans", category, plan_id)
        scopes = Counter(plan.scope_key() for plan in candidates)
        ids = Counter(plan.plan_id for plan in candidates)
        usable = []
        for plan in candidates:
            if scopes[plan.scope_key()] > 1 or ids[plan.plan_id] > 1:
                counts["duplicate_scope_or_id"] += 1
                self.note("program_plans", "duplicate_scope_or_id", plan.plan_id)
            else:
                counts["usable"] += 1
                usable.append(plan)
        by_program = defaultdict(lambda: defaultdict(Counter))
        for plan in usable:
            stats = by_program[plan.program_id][plan.catalog_year]
            stats["usable"] += 1
            stats[plan.coverage] += 1
            stats[plan.review_status] += 1
            self.note("program_plans", "usable_scopes", {
                "plan_id": plan.plan_id, "program_id": plan.program_id, "campus": plan.campus,
                "catalog_year": plan.catalog_year, "pathway": plan.pathway, "concentration": plan.concentration,
                "coverage": plan.coverage, "review_status": plan.review_status})
        exclusive = ("usable", "orphan_rows", "oversize", "invalid_json", "invalid_record", "identity_mismatch",
                     "content_hash_mismatch", "duplicate_scope_or_id")
        result = {
            "denominator": {"plan_rows": len(rows)},
            "counts": _all(exclusive, counts),
            "usable": {
                "denominator": len(usable),
                "coverage": _all(("partial", "complete"), Counter(plan.coverage for plan in usable)),
                "review_status": _all(("draft", "source_checked"), Counter(plan.review_status for plan in usable)),
                "source_fingerprint": {"recorded": sum(bool(plan.source_html_sha256) for plan in usable),
                                       "missing": sum(not plan.source_html_sha256 for plan in usable)},
                "captured_on": {"earliest": min((plan.captured_on.isoformat() for plan in usable), default=None),
                                "latest": max((plan.captured_on.isoformat() for plan in usable), default=None)},
            },
            "by_program": {
                program: {edition: _all(("usable", "partial", "complete", "draft", "source_checked"), stats)
                          for edition, stats in sorted(editions.items())}
                for program, editions in sorted(by_program.items())},
            "rules": RULES["program_plans"],
        }
        if program_ids is None:
            result["programs"] = {"status": "not_checked", "code": "table_missing"}
        else:
            complete = {plan.program_id for plan in usable if plan.coverage == "complete"}
            planned = {plan.program_id for plan in usable}
            result["programs"] = {
                "status": "checked",
                "denominator": {"program_rows": len(program_ids)},
                "with_complete_plan": len(complete & program_ids),
                "with_only_partial_plans": len((planned - complete) & program_ids),
                "without_usable_plan": len(program_ids - planned),
            }
            for program in program_ids - planned:
                self.note("program_plans", "programs_without_usable_plan", program if isinstance(program, str) else None)
        return result

    def legacy_rows(self):
        self.require_section("courses")
        result = {"rules": RULES["legacy_rows"]}
        for table, columns in (("program_required_courses", "program_id, course_id"),
                               ("course_prerequisites", "course_id, prereq_course_id")):
            if table not in self.tables:
                result[table] = {"status": "not_checked", "code": "table_missing"}
                continue
            rows = self.rows(f"SELECT {columns} FROM {table}")
            names = [column.strip() for column in columns.split(",")]
            course_columns = [name for name in names if name.endswith("course_id")]
            outside = sum(any(row[name] not in self.scope for name in course_columns) for row in rows)
            result[table] = {"status": "checked", "rows": len(rows), "rows_for_courses_out_of_scope": outside}
            if table == "course_prerequisites":
                result[table]["courses_in_scope_with_edges"] = len(
                    {row["course_id"] for row in rows if row["course_id"] in self.scope})
            elif self.programs() is not None:
                # Keyed only by text IDs the programs table has; the rest are counted, not named.
                known = Counter(row["program_id"] for row in rows
                                if isinstance(row["program_id"], str) and row["program_id"] in self.programs())
                result[table]["by_program"] = dict(sorted(known.items()))
                result[table]["rows_for_unknown_programs"] = len(rows) - sum(known.values())
            else:
                result[table]["by_program"] = {"status": "not_checked", "code": "table_missing"}
        return result


def _bounded(details: dict, limit: int) -> dict:
    output = {}
    for section, groups in sorted(details.items()):
        output[section] = {}
        for key, items in sorted(groups.items()):
            listed = [item for item in items if item is not None]
            listed.sort(key=lambda item: json.dumps(item, sort_keys=True))
            output[section][key] = {"items": listed[:limit], "omitted": len(listed) - min(len(listed), limit),
                                    "unlisted_malformed": len(items) - len(listed)}
    return output


def _connect(path: Path, reads: _Reads, budget: dict) -> sqlite3.Connection:
    # immutable avoids creating shm/wal files; valid only for a stable offline copy.
    conn = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA trusted_schema=OFF")
        deadline, steps = time.monotonic() + DEADLINE_SECONDS, 0

        def bounded():
            nonlocal steps
            steps += PROGRESS_INTERVAL
            budget["exceeded"] = budget["exceeded"] or steps > MAX_VM_STEPS or time.monotonic() > deadline
            return int(budget["exceeded"])

        conn.set_progress_handler(bounded, PROGRESS_INTERVAL)
        conn.set_authorizer(reads)  # After the PRAGMAs: from here on only reads of READABLE columns.
        conn.execute("BEGIN")  # One read snapshot.
    except BaseException:
        conn.close()
        raise
    return conn


SECTIONS = ("schema", "courses", "catalog_snapshots", "fields", "requisite_documents", "program_plans", "legacy_rows")


def build_report(db_copy, *, details: bool = False, max_codes: int = DEFAULT_MAX_CODES) -> dict:
    if not isinstance(max_codes, int) or not 1 <= max_codes <= MAX_CODES_LIMIT:
        raise ValueError("max_codes outside 1..500")
    report = {"format_version": FORMAT_VERSION, "report": "data_coverage", "complete": False,
              "database": {"status": "failed", "code": "database_unavailable"},
              "sections": {name: {"status": "not_checked", "code": "database_unavailable"} for name in SECTIONS},
              "limitations": list(LIMITATIONS), "rules_doc": "docs/data-coverage-report.md"}
    inputs, reads, budget = Inputs(), _Reads(), {"exceeded": False}
    try:
        path = _existing(Path(db_copy))
        _sidecars_absent(path)
        path = inputs.track(path, MAX_DB_BYTES)
    except PreflightError as exc:
        report["database"]["code"] = exc.args[0]
        return report
    except FileNotFoundError:
        report["database"]["code"] = "database_copy_missing"  # Never created.
        return report
    except OSError:
        report["database"]["code"] = "database_copy_unreadable"
        return report
    try:
        conn = _connect(path, reads, budget)
    except sqlite3.Error:
        report["database"]["code"] = "sqlite_budget" if budget["exceeded"] else "database_open_failed"
        return report
    audit = _Audit(conn, reads, details)
    try:
        for name in SECTIONS:
            audit.run(name, getattr(audit, name))
            if budget["exceeded"] and audit.sections[name]["status"] == "failed":
                audit.sections[name]["code"] = "sqlite_budget"
            if name == "schema" and audit.sections[name]["status"] != "checked":
                break  # Not a readable SQLite database: report no section at all.
    finally:
        conn.close()
    if audit.sections["schema"]["status"] != "checked":
        report["database"]["code"] = audit.sections["schema"]["code"]
        return report
    try:
        inputs.unchanged()
        _sidecars_absent(path)
    except (PreflightError, OSError):
        # Results read from a copy that changed underneath are not reported at all.
        report["database"]["code"] = "inputs_changed_during_check"
        return report
    report["database"] = {"status": "checked", "code": "read_only_snapshot"}
    report["sections"] = audit.sections
    report["complete"] = all(section["status"] == "checked" for section in audit.sections.values())
    if details:
        report["details"] = {"max_codes": max_codes, **_bounded(audit.details, max_codes)}
    return report


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse echoes the offending value, and a path can be private.
        print(json.dumps({"format_version": FORMAT_VERSION, "report": "data_coverage", "complete": False,
                          "code": "invalid_arguments"}))
        raise SystemExit(1)


def cli(argv=None) -> int:
    parser = _Parser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db-copy", required=True, type=Path,
                        help="existing standalone offline copy (no -wal/-shm/-journal next to it)")
    parser.add_argument("--details", action="store_true",
                        help="also list course codes / plan IDs per gap category (bounded)")
    parser.add_argument("--max-codes", type=int, default=DEFAULT_MAX_CODES,
                        help=f"items per listed category with --details, 1..{MAX_CODES_LIMIT}")
    args = parser.parse_args(argv)
    if not 1 <= args.max_codes <= MAX_CODES_LIMIT:
        parser.error("max-codes")
    try:
        report = build_report(args.db_copy, details=args.details, max_codes=args.max_codes)
    except Exception:
        print(json.dumps({"format_version": FORMAT_VERSION, "report": "data_coverage", "complete": False,
                          "code": "audit_failed"}))
        return 1
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
    if report["database"]["status"] != "checked":
        return 1
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(cli())
