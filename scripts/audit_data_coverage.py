"""Read-only data coverage, conflict and source report over an explicit offline SQLite copy.

Answers "which course and which field to fill next" with counts, not a single course total. Each
section and its main blocks of counts name their denominator (the rules give those of the per-department,
per-edition and per-program groups), and every name a section reports has a one-line rule in that
section's `rules`. The categories under `counts`, and the per-field categories, are exclusive and add
up to their denominator; a rule says "not exclusive" where counts overlap. A section, or a
part of one, whose table is missing or unreadable (or whose input section could not be checked) is
"not_checked" with a code, so a check that did not run never reads as "checked, nothing found", and
`complete` is true only when no part anywhere is not_checked or failed. Default output is aggregate
counts only; --details adds lists of course codes (bounded per department) and plan IDs.

The copy is opened like release_preflight.py opens it: an existing local file without -wal/-shm/
-journal sidecars, mode=ro&immutable=1, query_only, trusted_schema=OFF, a time/VM-step budget, one
BEGIN snapshot, and a fingerprint compared before and after. Before any row is read, integrity_check
refuses a damaged file (pages shared between tables, a table whose b-tree disagrees with its indexes, a
file cut short), which could otherwise show another table's bytes under an allowed name, and PRAGMA
table_list/table_xinfo say which data tables are ordinary tables whose read columns are stored columns;
views, virtual tables and generated columns are never read. A SQLite authorizer then allows only the
listed columns of the course, catalog, requisite and program tables and denies everything else, including
SQL functions, PRAGMAs and reads through views or triggers. These checks work on names: user tables
(users, query_log, Co-op, chat answers, feedback) and courses.raw_text are never queried (only the
integrity check reads their pages, and it prints nothing), but values someone copied into an allowed
column, or a file rebuilt consistently with other data under allowed names, are read like any other, so
the output itself names only counts, fixed strings, well-formed codes, IDs and editions, and dates of
validated records. No writes, no network, no Settings/.env. Unknown catalog retrieval dates stay
unknown; a hash or a source_checked review is never counted as officially correct or currently
applicable, and a partial plan is never counted as complete.

中文：对显式给出的离线 SQLite 副本做只读的数据覆盖、冲突与来源报告，回答「下一批补哪门课、
哪个字段」。每一节和主要的计数块都写明分母（按院系、年度、项目的分组，分母见规则），每一节报告的
每个名字都在该节的 rules 里附一句规则；counts 下的类别和各字段的类别互斥、相加等于分母，计数有
重叠时规则里写明「不互斥」。表不存在或不能读（或依赖的上一节没查成）时，该节或该部分是
not_checked 并带原因码，不会把「没查」写成「查了、没问题」；任何一处 not_checked 或 failed，
complete 都是 false。默认只输出汇总计数；--details 才附上课程代码（按院系各自限量）和方案 ID。
打开方式与 release_preflight.py 相同：已存在、无旁文件的本地副本，mode=ro&immutable=1、query_only、
trusted_schema=OFF、执行预算、一次 BEGIN 快照，前后核对文件指纹。读任何一行之前，integrity_check
拒绝损坏的文件（页被几张表共用、表的 b-tree 和自己的索引对不上、文件被截断；否则可能以允许的名字
读到别的表的字节），再用 PRAGMA table_list/table_xinfo 确认要读的表是普通表、要读的列是存储列；
视图、虚拟表、生成列一概不读。之后 SQLite 授权回调只允许读列出的课程、目录、先修和培养方案表的
指定列，其余一律拒绝，包括 SQL 函数、PRAGMA 和经由视图/触发器的读取。这些检查都按名字：用户表
（users、query_log、Co-op、聊天回答、反馈）和 courses.raw_text 从不查询（只有完整性检查会读到它们
的页，什么都不输出），但有人抄进允许的列里的值，或者把别的数据一致地重建在允许名字下的文件，照样会
读到，所以输出本身只有计数、固定文字、格式合格的代码、ID、年度，以及校验过的记录里的日期。不写入、
不联网、不读 Settings/.env。抓取日期未知就写未知；hash 或 source_checked 不算官方正确或当前适用；
partial 方案不算完整。
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
MAX_DOCUMENT_JSON = 200_000  # The requisite repository's own budget, and course_context's for plans.
DEADLINE_SECONDS = 60
MAX_VM_STEPS = 500_000_000
PROGRESS_INTERVAL = 10_000  # SQLite VM steps between budget checks.
DEFAULT_MAX_CODES = 25
MAX_CODES_LIMIT = 500
MIN_SQLITE_VERSION = (3, 37, 0)  # PRAGMA table_list.
EXPECTED_VERSIONS = frozenset(f"1.{number}" for number in range(8))
COURSE_STATUSES = ("pending", "indexed", "failed")
EDITION = re.compile(r"\d{4}-\d{4}")
# The only IDs the output names: lower-case letters, digits and hyphens with at least one letter, so a numeric
# identifier copied into an ID column (an account number, say) is never printed.
# 中文：输出里只会出现这种 ID：小写字母、数字和连字符，且至少有一个字母；抄进 ID 列的纯数字标识（比如账号）
# 不会被印出来。
PLAN_ID = re.compile(r"(?=[a-z0-9-]*[a-z])[a-z0-9][a-z0-9-]{0,99}")
PROGRAM_ID = re.compile(r"(?=[a-z0-9-]*[a-z])[a-z0-9][a-z0-9-]{0,63}")
COURSE_ID = PLAN_ID  # Same form; named only next to a course code that more than one in-scope course has.

# Columns the authorizer lets a statement read; nothing else, not even through a view.
# 中文：授权回调只放行这些列；其余一律拒绝，经由视图读取也不行。
READABLE = {
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
DATA_TABLES = tuple(READABLE)
TABLE_CODES = {"missing": "table_missing", "not_plain": "table_not_plain", "column_missing": "column_missing"}

COURSE_CATEGORIES = ("in_scope", "synthetic", "identity_mismatch", "invalid_record", "invalid_json", "oversize",
                     "duplicate_id", "text_not_utf8")
SNAPSHOT_CATEGORIES = ("usable", "absent", "duplicate_rows", "identity_mismatch", "invalid_record", "invalid_json",
                       "oversize", "text_not_utf8")
CATALOG_FIELDS = ("credits", "prereqs")  # The fields compared with the usable catalog snapshot.
FIELD_CATEGORIES = ("catalog_only", "catalog_lists_none", "catalog_conflict", "catalog_consistent", "missing",
                    "extracted_estimate", "course_sources_only", "no_recorded_source")
# Every category that asks for work: something to fill, to check against the catalog, or to verify.
LISTED_FIELD_CATEGORIES = ("missing", "catalog_only", "catalog_lists_none", "catalog_conflict", "extracted_estimate",
                           "course_sources_only", "no_recorded_source")
DOCUMENT_CATEGORIES = ("usable", "orphan_rows", "rows_for_courses_out_of_scope", "duplicate_rows", "oversize",
                       "invalid_json", "invalid_record", "row_identity_mismatch", "course_identity_mismatch",
                       "content_hash_mismatch", "text_not_utf8")
PARSE_STATUSES = ("parsed", "unparsed", "not_listed")
CREDIT_COMPARISONS = ("consistent", "conflict", "course_credits_missing", "range_not_compared",
                      "fractional_not_compared", "not_captured")
PLAN_CATEGORIES = ("usable", "orphan_rows", "oversize", "invalid_json", "invalid_record", "identity_mismatch",
                   "content_hash_mismatch", "duplicate_scope_or_id", "text_not_utf8")
COURSE_DETAIL_SECTIONS = frozenset({"courses", "catalog_snapshots", "fields", "requisite_documents"})
NOT_COMPARED = {"status": "not_checked", "code": "catalog_snapshots_not_checked"}

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

_NOT_TEXT = "NULL or a number, or not valid JSON (a BLOB holding UTF-8 JSON is read, as the app reads it)"
_NOT_UTF8 = ("a column this report reads holds TEXT that is not valid UTF-8: any app query that fetches that value "
             "fails as a whole, other rows included, so fix these first; decided first")
_ROWS_NOT_UTF8 = ("rows with a read column holding TEXT that is not valid UTF-8 (not exclusive: they are also in the "
                  "counts above)")
_NAMED_IDS = "only IDs of lower-case letters, digits and hyphens with at least one letter (at most 64) are named"
RULES = {
    "schema": {
        "tables": "each data table this report reads, from PRAGMA table_list/table_xinfo before any row is read: "
                  "present (an ordinary table with every column the report reads), missing, not_plain (a view, a "
                  "virtual or shadow table, or one of those columns is generated or hidden; never read) or "
                  "column_missing. Names are matched exactly: a table or column whose name differs only in case "
                  "reads as missing or column_missing and is not read, although SQLite would accept it",
        "schema_versions": "rows of schema_versions; the release migrations 1.0-1.7 are expected",
        "version_rows": "every row of schema_versions: the denominator of this block",
        "expected_version_rows": "rows whose version is one of 1.0-1.7",
        "other_rows": "rows with any other version value (counted, not named)",
        "present": "expected versions that have a row",
        "missing": "expected versions without a row",
        "rows_with_text_not_utf8": _ROWS_NOT_UTF8,
    },
    "courses": {
        "text_not_utf8": f"{_NOT_UTF8}. The app answers from generated_json alone, so with the bad value in another "
                         "column (primary_name, status) it may still serve the course that the report excludes",
        "duplicate_id": "the course_id is shared with another row (possible only without the table's primary key); "
                        "none of these rows is used, while the app's lookups by ID and in batches may each pick a "
                        "different one",
        "oversize": "generated_json longer than 1,000,000 characters (bytes for a BLOB); not decoded, so the report "
                    "cannot say whether the app could read it",
        "invalid_json": f"generated_json is {_NOT_TEXT}",
        "invalid_record": "valid JSON that the Course model rejects, as the API would",
        "identity_mismatch": "course_id, primary_code or primary_name column differs from the decoded record (a NULL "
                             "or non-text course_id always does); excluded because every join would be ambiguous",
        "synthetic": "decoded record the answer path marks synthetic_record_not_real_course; excluded from coverage",
        "in_scope": "every other row: the denominator of the course-level sections",
        "course_rows": "every row of courses: the denominator of counts and status_column",
        "in_scope_courses": "the in-scope courses",
        "courses_in_scope": "in-scope courses (the in_scope count)",
        "duplicate_code_groups": "course codes that more than one in-scope course has; --details lists each such code "
                                 "with the course_ids that share it (null for an ID not fit to print), and gives each "
                                 "of those courses its course_id wherever it lists the course",
        "duplicate_code_rows": "in-scope courses whose code another in-scope course also has (not exclusive)",
        "by_department": "in-scope courses per department (the subject prefix of the code)",
        "status_column": "course rows by their status column: pending, indexed, failed or other; adds up to "
                         "course_rows and says nothing about data quality",
    },
    "catalog_snapshots": {
        "usable": "exactly one snapshot row, accepted by the CatalogSnapshot model, whose code and title equal the "
                  "course's: the answer path attaches such a snapshot (it may also attach one the report does not use: "
                  "see duplicate_rows and oversize)",
        "absent": "no snapshot row for the course",
        "text_not_utf8": "a snapshot row of the course holds TEXT that is not valid UTF-8: the app's catalog query "
                         "for any batch that includes the course fails as a whole, so fix these first; decided "
                         "after absent",
        "duplicate_rows": "more than one snapshot row for the course (possible only without the table's primary "
                          "key); the report uses none, while the app would attach the last valid one",
        "oversize": "snapshot longer than 100,000 characters (bytes for a BLOB); not decoded, so not counted usable, "
                    "although the app has no such limit",
        "invalid_json": f"snapshot is {_NOT_TEXT}",
        "invalid_record": "valid JSON that the CatalogSnapshot model rejects",
        "identity_mismatch": "snapshot code or title differs from the course's (a name inconsistency); not attached",
        "snapshot_rows": "every row of course_catalog_sources, by the course it names",
        "rows_for_courses_in_scope": "rows whose course_id is an in-scope course: the rows the per-course counts use",
        "rows_for_courses_out_of_scope": "rows whose course_id is in courses but excluded from scope",
        "orphan_rows": "rows whose course_id is not a course_id in courses (NULL and non-text values included)",
        "rows_with_text_not_utf8": f"{_ROWS_NOT_UTF8}. The app's catalog query fails for any batch with that course, "
                                   "in scope or not (an excluded course such as a synthetic one is still served), so "
                                   "--details lists each of these rows by its course's code",
        "usable_snapshots": "the usable snapshots",
        "retrieval_date_known": "usable snapshots with retrieved_at",
        "retrieval_date_unknown": "usable snapshots without retrieved_at; import time is never used instead",
        "retrieved_on": "earliest and latest recorded retrieval day among usable snapshots; null when none has one",
        "description_missing": "usable snapshots without description text (not exclusive)",
        "credits_missing": "usable snapshots without a whole-number credit value: the catalog lists none, a range or "
                           "a fraction (not exclusive)",
        "prereq_codes_listed": "usable snapshots that list at least one non-blank prerequisite code (not exclusive)",
        "by_department": "per department: courses_in_scope and the categories above, zero counts omitted",
        "courses_in_scope": "in-scope courses (of the department, under by_department)",
    },
    "fields": {
        "catalog_only": "no stored value, and the usable catalog snapshot has one (credits, prereqs): can be filled "
                        "from the catalog",
        "catalog_lists_none": "no stored value, and the usable catalog snapshot was compared and has none either "
                              "(credits: no whole-number value, such as a range; prereqs: no non-blank code "
                              "listed)",
        "catalog_conflict": "stored value differs from the usable catalog snapshot (credits, when the snapshot has a "
                            "value: the answer path's catalog_metadata_conflict; prereq code sets, each code in its "
                            "normalized form: the report's own comparison, with no answer-path warning). A normalized "
                            "code is a well-formed one as the app's pattern reads it, anything else upper-cased with "
                            "whitespace collapsed; blank entries are dropped",
        "catalog_consistent": "stored value equals the usable catalog snapshot (credits; prereq code sets, each code "
                              "in its normalized form, as for catalog_conflict)",
        "missing": "no stored value (None or empty list; 0 counts as a value); for credits and prereqs also no "
                   "usable catalog snapshot to compare",
        "extracted_estimate": "stored value with an evidence snippet for the field: extracted, not official",
        "course_sources_only": "stored value without field evidence; the course records source IDs, which do not say "
                               "which field they support",
        "no_recorded_source": "stored value with no field evidence, no source IDs and no catalog comparison",
        "fields": "per field of the answer path's availability list: the categories above, which add up to "
                  "courses_in_scope; credits and prereqs are not_checked when catalog_snapshots was not checked",
        "by_department": "per department: courses_in_scope; under fields, the same categories per field with zero "
                         "counts omitted (credits and prereqs left out when the catalog was not compared); and, when "
                         "the catalog was compared, catalog_description and answer_warnings for the department's "
                         "courses, zero counts omitted",
        "courses_in_scope": "in-scope courses (of the department, under by_department)",
        "catalog_comparison": "whether credits and prereqs were compared with the catalog (that needs a checked "
                              "catalog_snapshots section)",
        "catalog_description": "in-scope courses by catalog description; empty_in_usable_snapshot and "
                               "no_usable_snapshot together are the answer path's missing catalog_description when it "
                               "attaches the report's usable snapshot (it may attach a duplicate or oversize one)",
        "present": "the usable snapshot has description text",
        "empty_in_usable_snapshot": "a usable snapshot without description text",
        "no_usable_snapshot": "no usable catalog snapshot",
        "answer_warnings": "in-scope courses per warning that course_answer_evidence gives them with the report's "
                           "usable snapshot (the app may attach a duplicate or oversize one); program_seed_unverified, "
                           "which depends on how the course was reached, is not counted; a course can have several "
                           "(not exclusive)",
    },
    "requisite_documents": {
        "text_not_utf8": _NOT_UTF8,
        "usable": "decodes as CourseRequisiteDocument, matches its row's course and edition and the course's code "
                  "and title, and its content hash matches: what the course detail page would show",
        "orphan_rows": "course_id is not a course_id in courses (NULL and non-text values included)",
        "rows_for_courses_out_of_scope": "document of a course that is in courses but excluded from scope",
        "duplicate_rows": "more than one row for the same course and edition (possible only without the table's "
                          "primary key); the report uses none, while the course page would show each valid one",
        "oversize": "document longer than 200,000 characters (bytes for a BLOB), the repository's own budget",
        "invalid_json": f"document is {_NOT_TEXT}",
        "invalid_record": "valid JSON that the document model rejects (including a syntax tree that no longer "
                          "matches its clause)",
        "row_identity_mismatch": "document course_id or edition differs from its row",
        "course_identity_mismatch": "document code or title differs from the course's",
        "content_hash_mismatch": "stored content hash differs from the document's",
        "document_rows": "every row of course_requisite_documents: the denominator of counts",
        "by_catalog_year": "per edition of the row (catalog_year; a value that is not YYYY-YYYY with consecutive "
                           "years, as the app requires, is 'unrecognized'): "
                           "usable and unusable rows, which add up to the edition's rows, and statistics over its "
                           "usable documents",
        "unusable": "rows of the edition in any category other than usable",
        "courses_in_scope_covered": "in-scope courses with a usable document of the edition",
        "prerequisite": "usable documents by prerequisite clause status: parsed, unparsed (kept as text) or "
                        "not_listed (the catalog block lists none, which is not the same as no requirement)",
        "corequisite": "usable documents by corequisite clause status, as for prerequisite",
        "description_evidence": "usable documents by description evidence status: not_listed, no_keyword_match, "
                                "review_needed (a keyword such as permission appears; not an interpreted rule) or "
                                "not_captured (older documents)",
        "credit_hours_vs_course_credits": "usable documents by how the catalog's literal hours compare with the "
                                          "course's stored credits: consistent, conflict, course_credits_missing, "
                                          "range_not_compared, fractional_not_compared or not_captured",
        "captured_on": "earliest and latest capture day among the edition's usable documents",
        "in_scope_courses": "the in-scope courses",
        "with_usable_document_any_year": "in-scope courses with a usable document in at least one edition "
                                         "(not exclusive)",
        "legacy_prereqs_without_usable_document": "in-scope courses with a stored prereq code list and no usable "
                                                  "document in any edition: answers rely on the code list only "
                                                  "(not exclusive)",
        "by_department": "per department: courses_in_scope and, per edition, with_usable_document and, over those "
                         "documents, the prerequisite and corequisite clause status and credit_hours_vs_course_credits",
        "courses_in_scope": "in-scope courses (of the department, under by_department)",
        "with_usable_document": "in-scope courses of the department with a usable document of the edition",
    },
    "program_plans": {
        "text_not_utf8": _NOT_UTF8,
        "usable": "decodes as ProgramPlan, matches its row's plan ID and scope, content hash matches, and no other "
                  "usable row has the same scope or plan ID",
        "orphan_rows": "program_id is not a program_id in programs (NULL and non-text values included). The Programs "
                       "page never reaches such a plan, but course_context does not check programs and would still "
                       "show a valid source_checked one on the course page",
        "oversize": "document longer than 200,000 characters (bytes for a BLOB); not decoded (course_context has the "
                    "same budget, list_for_program has none)",
        "invalid_json": f"document is {_NOT_TEXT}",
        "invalid_record": "valid JSON that the ProgramPlan model rejects",
        "identity_mismatch": "document plan ID or scope differs from its row",
        "content_hash_mismatch": "stored content hash differs from the document's",
        "duplicate_scope_or_id": "rows that would be usable but share a scope or plan ID (possible only without the "
                                 "table's keys); the report uses none. list_for_program would list each; "
                                 "course_context reads one catalog year at a time and drops drafts and plans that do "
                                 "not name the course before its own duplicate check, so it can still show a "
                                 "source_checked plan whose twin is a draft or in another year",
        "plan_rows": "every row of program_plans: the denominator of counts",
        "usable_plans": "the usable plans",
        "coverage": "usable plans by coverage: partial or complete",
        "complete": "coverage 'complete' (the model requires source_checked and no unmodeled rule); partial is never "
                    "counted as complete",
        "partial": "coverage 'partial': the plan does not claim complete coverage (it may still model every rule)",
        "review_status": "usable plans by review status: draft or source_checked",
        "source_checked": "a person recorded comparing the document with its capture; not official correctness or "
                          "current applicability",
        "draft": "review_status 'draft': not marked source_checked (it may still record a reviewer)",
        "source_fingerprint": "usable plans that record the SHA-256 of their source HTML (recorded) or not (missing)",
        "captured_on": "earliest and latest capture day among usable plans",
        "by_program": f"usable plans per program ID and edition; {_NAMED_IDS}",
        "by_catalog_year": "usable plans of the program per edition: usable, partial, complete, draft, source_checked",
        "usable_plans_with_unlisted_program_id": "usable plans left out of by_program because their program_id is not "
                                                 "such an ID (counted, never named)",
        "programs": "rows of programs, by their usable plans",
        "program_rows": "every row of programs: the denominator of this block",
        "with_any_complete_plan": "programs with at least one complete usable plan in any edition or pathway (others "
                                  "may be partial or absent)",
        "with_only_partial_plans": "programs whose usable plans are all partial",
        "without_usable_plan": "programs with no usable plan",
        "id_unusable": "rows whose program_id is NULL, not text, or shared with another row (possible only without "
                       "the table's key); not matched to plans",
        "rows_with_text_not_utf8": _ROWS_NOT_UTF8,
    },
    "legacy_rows": {
        "program_required_courses": "legacy seed rows naming a program's courses: counted only, not verified "
                                    "program rules",
        "course_prerequisites": "legacy seed prerequisite edges: counted only, not verified prerequisite logic",
        "rows": "every row of the table: the denominator of its block",
        "rows_for_courses_in_scope": "rows whose course columns all name in-scope courses",
        "rows_for_courses_out_of_scope": "rows naming at least one course that is not in scope (excluded, missing, "
                                         "NULL or non-text)",
        "by_program": f"rows per program ID that programs has; {_NAMED_IDS}",
        "rows_for_unknown_programs": "rows whose program_id is such an ID but not in programs",
        "rows_with_unlisted_program_id": "rows whose program_id is NULL, not text, or not such an ID (counted, never "
                                         "named)",
        "courses_in_scope_with_edges": "in-scope courses that are the course_id of at least one row",
        "rows_with_text_not_utf8": _ROWS_NOT_UTF8,
    },
}


class _NotChecked(Exception):
    """A section that could not run; its code says why."""


class _Failed(Exception):
    """A section that ran into a fixed, known failure; its code says which."""


class _Undecodable:
    """A TEXT value that is not valid UTF-8 (the app cannot read it). Equal to another one only when the stored
    bytes are the same, as SQLite compares them; never equal to text, and never printed.
    中文：不是合法 UTF-8 的 TEXT 值（应用读不了）。只有存储的字节相同才和另一个相等，与 SQLite 的比较
    一致；永远不等于文本，也从不输出。"""

    __slots__ = ("raw",)

    def __init__(self, raw: bytes):
        self.raw = raw

    def __eq__(self, other):
        return isinstance(other, _Undecodable) and other.raw == self.raw

    def __hash__(self):
        return hash((_Undecodable, self.raw))

    def __repr__(self):
        return "<not UTF-8>"


def _text(data: bytes):
    # Used as text_factory: one bad value is counted for its row instead of failing the whole query.
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return _Undecodable(bytes(data))


def _undecodable(row) -> bool:
    return any(isinstance(value, _Undecodable) for value in row)


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


def _decode(value, budget, model):
    """(category, record) with category 'decoded', 'oversize', 'invalid_json' or 'invalid_record'.

    Takes what the app's model_validate_json takes: text, or a BLOB holding UTF-8 JSON text. The budget
    applies to the stored length (characters of text, bytes of a BLOB), as the requisite repository's does.
    中文：和应用的 model_validate_json 一样接受文本，或装着 UTF-8 JSON 文本的 BLOB；长度上限按存储
    长度算（文本按字符，BLOB 按字节），与先修文档仓库自己的上限一致。
    """
    if not isinstance(value, (str, bytes)):
        return "invalid_json", None  # NULL or a number (the sections count TEXT that is not UTF-8 before this).
    if len(value) > budget:
        return "oversize", None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return "invalid_json", None
    try:
        json.loads(value)
    except (ValueError, RecursionError):
        return "invalid_json", None
    try:
        return "decoded", model.model_validate_json(value)
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


def _listable_id(value) -> str | None:
    return value if isinstance(value, str) and PROGRAM_ID.fullmatch(value) else None


def _listable_plan_id(value) -> str | None:
    # The plan model also accepts an ID without a letter, so a plan's own ID is checked here as well.
    return value if isinstance(value, str) and PLAN_ID.fullmatch(value) else None


def _edition(value) -> str:
    """A requisite row's edition as the app accepts one (YYYY-YYYY, consecutive years), else 'unrecognized'."""
    if isinstance(value, str) and EDITION.fullmatch(value) and int(value[5:]) == int(value[:4]) + 1:
        return value
    return "unrecognized"


def _codes(values) -> set[str]:
    # A well-formed code in its normalized form ("cs5004" is "CS 5004", as the app's code pattern reads it); anything
    # else upper-cased with its whitespace collapsed (so "cs  5800" is "CS 5800" too); a blank entry lists nothing.
    # 中文：合格的课程代码按规范形式比较（"cs5004" 就是 "CS 5004"，和应用的代码模式一致）；其他值转成大写、去掉
    # 多余空白后比较（所以 "cs  5800" 也是 "CS 5800"）；空白项不算列出的代码。
    codes = {_listable_code(value) or " ".join(str(value).split()).upper() for value in values}
    codes.discard("")
    return codes


def field_category(course: Course, field: str, snapshot: CatalogSnapshot | None) -> str:
    """The FIELD_CATEGORIES entry for one stored field; RULES['fields'] says what each means.

    With a usable snapshot, credits and prereqs are compared first: a value only one side has, equal or
    different values, or neither side having one. Credits are compared only when the snapshot has a
    whole number; prereq code sets are compared even when the snapshot lists none. Then the field's
    own evidence, then the course's recorded sources.
    中文：有可用目录快照时先比学分和先修代码：只有一边有值、相同、不同，或两边都没有。学分只在
    快照有整数学分时才比；先修代码集合即使快照一个都没列也比。之后看该字段的抽取证据，最后看课程
    记录的来源 ID。
    """
    value = getattr(course, field)
    if snapshot is not None and field == "credits":
        if snapshot.credits is not None:
            if value is None:
                return "catalog_only"
            return "catalog_consistent" if value == snapshot.credits else "catalog_conflict"
        if value is None:
            return "catalog_lists_none"
    if snapshot is not None and field == "prereqs":
        stored, listed = _codes(value), _codes(snapshot.prereq_codes)
        if not stored:
            return "catalog_only" if listed else "catalog_lists_none"
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


def _day_range(days) -> dict:
    days = sorted(days)
    return {"earliest": days[0] if days else None, "latest": days[-1] if days else None}


def _layout(conn: sqlite3.Connection) -> dict[str, str]:
    """Each data table's state, read from PRAGMAs before the authorizer (which denies every PRAGMA) is installed.

    A generated column is computed from other columns when read, without asking the authorizer about them, so a
    table whose read columns include one is never read; neither is a view, a virtual or a shadow table.
    中文：生成列在读取时由别的列算出来，授权回调不会被问到那些列，所以要读的列里有生成列的表一概不读；
    视图、虚拟表、影子表也不读。
    """
    kinds = {row[1]: row[2] for row in conn.execute("PRAGMA main.table_list")}
    layout = {}
    for table in DATA_TABLES:
        if table not in kinds:
            layout[table] = "missing"
        elif kinds[table] != "table":
            layout[table] = "not_plain"
        else:
            hidden = {row[1]: row[6] for row in conn.execute(f"PRAGMA main.table_xinfo({table})")}
            wanted = READABLE[table]
            if any(hidden.get(column, 0) != 0 for column in wanted):
                layout[table] = "not_plain"
            elif not wanted <= hidden.keys():
                layout[table] = "column_missing"
            else:
                layout[table] = "present"
    return layout


def _prepare(conn: sqlite3.Connection, reads: _Reads, budget: dict) -> dict[str, str]:
    conn.row_factory = sqlite3.Row
    conn.text_factory = _text
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA trusted_schema=OFF")
    deadline, steps = time.monotonic() + DEADLINE_SECONDS, 0

    def bounded():
        nonlocal steps
        steps += PROGRESS_INTERVAL
        budget["exceeded"] = budget["exceeded"] or steps > MAX_VM_STEPS or time.monotonic() > deadline
        return int(budget["exceeded"])

    conn.set_progress_handler(bounded, PROGRESS_INTERVAL)
    # The authorizer and the layout check names only. A damaged file whose tables share pages, or whose table
    # b-trees were swapped (a data table's root page pointing at a user table's b-tree, say), passes both and
    # would read other tables' bytes under allowed names. integrity_check finds shared pages, tables that
    # disagree with their indexes, and a file cut short (the check itself then fails as corrupt); quick_check,
    # which release_preflight runs, does not compare indexes with their tables, so it misses a swap. A file
    # rebuilt consistently passes any check: the output filter stays the boundary.
    # 中文：授权回调和表结构检查都只看名字。页被几张表共用、或者表的 b-tree 被换过（比如数据表的根页指向用户表
    # 的 b-tree）的损坏文件两关都能过，会以允许的名字读到别的表的字节。integrity_check 能查出共用的页、和索引
    # 对不上的表，以及被截断的文件（这时检查本身报文件损坏）；发布预检用的 quick_check 不核对索引内容，查不出
    # 互换。一致地重建过的文件任何检查都能过，所以最后一道边界仍是输出过滤。
    try:
        check = conn.execute("PRAGMA integrity_check(1)").fetchone()
    except sqlite3.DatabaseError as exc:
        if (getattr(exc, "sqlite_errorcode", None) or 0) & 0xFF == sqlite3.SQLITE_CORRUPT:
            raise PreflightError("database_integrity_failed") from None
        raise  # Not a database at all, or the budget ran out: build_report says which.
    if check is None or tuple(check) != ("ok",):
        raise PreflightError("database_integrity_failed")
    layout = _layout(conn)
    conn.set_authorizer(reads)  # After the PRAGMAs: from here on only reads of READABLE columns.
    conn.execute("BEGIN")  # One read snapshot.
    return layout


class _Audit:
    def __init__(self, conn: sqlite3.Connection, reads: _Reads, layout: dict[str, str], details: bool):
        self.conn, self.reads, self.layout, self.want_details = conn, reads, layout, details
        self.sections: dict[str, dict] = {}
        self.details: dict[str, dict] = defaultdict(dict)
        self.scope: dict[str, Course] = {}  # In-scope courses by course_id.
        self.known_ids: set = set()  # Every TEXT course_id in courses, decodable or not.
        self.row_codes: dict[str, str | None] = {}  # Readable course_id -> its row's listable code, in scope or not.
        self.snapshots: dict[str, CatalogSnapshot] = {}  # Usable snapshots by course_id.
        self.documents: dict[str, set[str]] = defaultdict(set)  # course_id -> editions with a usable document.
        self.program_values: list | None = None  # Every program_id value in programs, once read.
        self.duplicate_codes: set[str] = set()  # Codes more than one in-scope course has.

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

    def unavailable(self, table) -> dict | None:
        """The not_checked marker for a table this report cannot read, or None when it can."""
        state = self.layout[table]
        return None if state == "present" else {"status": "not_checked", "code": TABLE_CODES[state]}

    def require(self, *tables):
        for table in tables:
            if marker := self.unavailable(table):
                raise _NotChecked(marker["code"])

    def require_section(self, name):
        if self.sections.get(name, {}).get("status") != "checked":
            raise _NotChecked(f"{name}_not_checked")

    def programs(self) -> list:
        """Every program_id value in programs; the caller checked that the table can be read."""
        if self.program_values is None:
            self.program_values = [row["program_id"] for row in self.rows("SELECT program_id FROM programs")]
        return self.program_values

    def note(self, section, key, item):
        if self.want_details:
            self.details[section].setdefault(key, []).append(item)

    def item(self, course: Course, **extra):
        """A --details item for an in-scope course: its code, and its course_id too when another in-scope course
        has the same code (the code alone would not say which record to fix); None for an ID not fit to print.
        中文：一门范围内课程的明细项：课程代码；另一门范围内课程代码相同时再带上 course_id（只给代码就分不清
        该修哪一条），不适合打印的 ID 记为 None。"""
        if course.primary_code in self.duplicate_codes:
            extra["course_id"] = course.course_id if COURSE_ID.fullmatch(course.course_id) else None
        return {"code": course.primary_code, **extra} if extra else course.primary_code

    def row_item(self, course_id, **extra):
        """A --details item for a row whose course is out of scope: that course's own code column, if listable."""
        code = self.row_codes.get(course_id) if isinstance(course_id, str) else None
        return None if code is None else ({"code": code, **extra} if extra else code)

    # --- sections -------------------------------------------------------------------------------

    def schema(self):
        result = {"tables": dict(self.layout), "rules": RULES["schema"]}
        if marker := self.unavailable("schema_versions"):
            result["schema_versions"] = marker
            return result
        versions = [row["version"] for row in self.rows("SELECT version FROM schema_versions")]
        expected = [version for version in versions if version in EXPECTED_VERSIONS]
        result["schema_versions"] = {
            "status": "checked",
            "denominator": {"version_rows": len(versions)},
            "expected_version_rows": len(expected),
            "other_rows": len(versions) - len(expected),
            "present": sorted(set(expected)),
            "missing": sorted(EXPECTED_VERSIONS.difference(expected)),
            "rows_with_text_not_utf8": sum(isinstance(version, _Undecodable) for version in versions),
        }
        return result

    def courses(self):
        self.require("courses")
        rows = self.rows("SELECT course_id, primary_code, primary_name, status, generated_json FROM courses")
        ids = Counter(row["course_id"] for row in rows if isinstance(row["course_id"], (str, _Undecodable)))
        self.known_ids = set(ids)  # TEXT IDs, valid UTF-8 or not (by their bytes); a NULL or a number names no course.
        # Each readable ID's own listable code, for --details items of rows whose course is out of scope.
        self.row_codes = {}
        for row in rows:
            if isinstance(row["course_id"], str):
                self.row_codes.setdefault(row["course_id"], _listable_code(row["primary_code"]))
        counts, statuses, departments = Counter(), Counter(), Counter()
        for row in rows:
            statuses[row["status"] if row["status"] in COURSE_STATUSES else "other"] += 1
            course = None
            if _undecodable(row):
                category = "text_not_utf8"
            elif ids.get(row["course_id"], 0) > 1:
                category = "duplicate_id"  # The app's lookups by ID would each pick a different row.
            else:
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
        self.duplicate_codes = set(duplicates)
        for code in duplicates:
            # The courses that share the code, so the reader can tell which records to fix; null for an ID not fit
            # to print (listed last).
            ids = [course.course_id for course in self.scope.values() if course.primary_code == code]
            shown = sorted(value for value in ids if COURSE_ID.fullmatch(value))
            self.note("courses", "duplicate_codes",
                      {"code": code, "course_ids": shown + [None] * (len(ids) - len(shown))})
        return {
            "denominator": {"course_rows": len(rows)},
            "counts": _all(COURSE_CATEGORIES, counts),
            "in_scope_courses": {"denominator": {"courses_in_scope": len(self.scope)},
                                 "duplicate_code_groups": len(duplicates),
                                 "duplicate_code_rows": sum(duplicates.values()),
                                 "by_department": dict(sorted(departments.items()))},
            "status_column": _all((*COURSE_STATUSES, "other"), statuses),
            "rules": RULES["courses"],
        }

    def catalog_snapshots(self):
        self.require_section("courses")
        self.require("course_catalog_sources")
        rows = self.rows("SELECT course_id, snapshot FROM course_catalog_sources")
        per_course, row_counts = defaultdict(list), Counter()
        for row in rows:
            if _undecodable(row):
                # Any batch with this course fails in the app, in scope or not (a synthetic course is still served).
                row_counts["rows_with_text_not_utf8"] += 1
                course = self.scope.get(row["course_id"])
                self.note("catalog_snapshots", "rows_with_text_not_utf8",
                          self.item(course) if course else self.row_item(row["course_id"]))
            if row["course_id"] not in self.known_ids:
                row_counts["orphan_rows"] += 1
            elif row["course_id"] not in self.scope:
                row_counts["rows_for_courses_out_of_scope"] += 1
            else:
                row_counts["rows_for_courses_in_scope"] += 1
                per_course[row["course_id"]].append(row["snapshot"])
        counts, departments = Counter(), defaultdict(Counter)
        for course_id, course in self.scope.items():
            stored = per_course.get(course_id, [])
            if not stored:
                category = "absent"
            elif any(isinstance(value, _Undecodable) for value in stored):
                category = "text_not_utf8"  # Breaks the app's whole catalog query, duplicates or not.
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
                self.note("catalog_snapshots", category, self.item(course))
        usable = list(self.snapshots.values())
        known = [snapshot.retrieved_at for snapshot in usable if snapshot.retrieved_at is not None]
        return {
            "denominator": {"courses_in_scope": len(self.scope)},
            "counts": _all(SNAPSHOT_CATEGORIES, counts),
            "snapshot_rows": {
                "denominator": {"snapshot_rows": len(rows)},
                **_all(("rows_for_courses_in_scope", "rows_for_courses_out_of_scope", "orphan_rows",
                        "rows_with_text_not_utf8"), row_counts)},
            "usable_snapshots": {
                "denominator": {"usable_snapshots": len(usable)},
                "retrieval_date_known": len(known),
                "retrieval_date_unknown": len(usable) - len(known),
                "retrieved_on": _day_range(value.date().isoformat() for value in known),
                "description_missing": sum(not snapshot.description for snapshot in usable),
                "credits_missing": sum(snapshot.credits is None for snapshot in usable),
                "prereq_codes_listed": sum(bool(_codes(snapshot.prereq_codes)) for snapshot in usable),
            },
            "by_department": {name: {"courses_in_scope": sum(counter.values()), **_nonzero(counter)}
                              for name, counter in sorted(departments.items())},
            "rules": RULES["catalog_snapshots"],
        }

    def fields(self):
        self.require_section("courses")
        compared = self.sections.get("catalog_snapshots", {}).get("status") == "checked"
        # Without checked snapshots the catalog categories cannot be told apart from missing: not checked.
        names = tuple(field for field in AVAILABILITY_FIELDS if compared or field not in CATALOG_FIELDS)
        table = {field: Counter() for field in names}
        departments = defaultdict(lambda: {field: Counter() for field in names})
        sizes, warnings, description = Counter(), Counter(), Counter()
        department_warnings, department_description = defaultdict(Counter), defaultdict(Counter)
        for course_id, course in self.scope.items():
            department = _department(course.primary_code)
            sizes[department] += 1
            snapshot = self.snapshots.get(course_id) if compared else None
            evidence = course_answer_evidence(course, snapshot)
            if "field_evidence_value_conflict" in evidence.warnings:  # Independent of the catalog.
                self.note("fields", "field_evidence_value_conflict", self.item(course))
            if compared:
                # What course_answer_evidence gives with the report's usable snapshot; the rule says where chat differs.
                warnings.update(set(evidence.warnings))
                department_warnings[department].update(set(evidence.warnings))
                state = ("no_usable_snapshot" if snapshot is None else
                         "present" if snapshot.description else "empty_in_usable_snapshot")
                description[state] += 1
                department_description[department][state] += 1
                if state == "empty_in_usable_snapshot":
                    self.note("fields", "catalog_description.empty_in_usable_snapshot", self.item(course))
            for field in names:
                category = field_category(course, field, snapshot)
                table[field][category] += 1
                departments[department][field][category] += 1
                if category in LISTED_FIELD_CATEGORIES:
                    self.note("fields", f"{field}.{category}", self.item(course))
        by_department = {}
        for name in sorted(sizes):
            by_department[name] = {"courses_in_scope": sizes[name],
                                   "fields": {field: _nonzero(counter) for field, counter in departments[name].items()}}
            if compared:
                by_department[name]["catalog_description"] = _nonzero(department_description[name])
                by_department[name]["answer_warnings"] = _nonzero(department_warnings[name])
        result = {
            "denominator": {"courses_in_scope": len(self.scope)},
            "fields": {field: _all(FIELD_CATEGORIES, table[field]) if field in table else dict(NOT_COMPARED)
                       for field in AVAILABILITY_FIELDS},
            "by_department": by_department,
            "rules": RULES["fields"],
        }
        if compared:
            result["catalog_comparison"] = {"status": "checked"}
            result["catalog_description"] = _all(("present", "empty_in_usable_snapshot", "no_usable_snapshot"),
                                                 description)
            result["answer_warnings"] = dict(sorted(warnings.items()))
        else:
            # The catalog categories would read as zero and the warnings as "no catalog source".
            for key in ("catalog_comparison", "catalog_description", "answer_warnings"):
                result[key] = dict(NOT_COMPARED)
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
        departments = defaultdict(lambda: {"courses_in_scope": 0, "by_catalog_year": defaultdict(
            lambda: {"with_usable_document": 0, "prerequisite": Counter(), "corequisite": Counter(),
                     "credit_hours_vs_course_credits": Counter()})})
        for row in rows:
            course_id = row["course_id"]
            edition = _edition(row["catalog_year"])
            document = None
            if _undecodable(row):
                category = "text_not_utf8"
            elif course_id not in self.known_ids:
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
                    self.note("requisite_documents", category, self.item(self.scope[course_id], catalog_year=edition))
                elif category == "text_not_utf8":  # The course page of an excluded course fails as well.
                    self.note("requisite_documents", category, self.row_item(course_id, catalog_year=edition))
                continue
            course = self.scope[course_id]
            stats = editions[edition]
            stats["usable"] += 1
            stats["courses"].add(course_id)
            stats["captured"].append(document.source.captured_at.date().isoformat())
            self.documents[course_id].add(edition)
            by_year = departments[_department(course.primary_code)]["by_catalog_year"][edition]
            by_year["with_usable_document"] += 1
            for name in ("prerequisite", "corequisite"):
                section = getattr(document.requisites, name)
                stats[name][section.status] += 1
                by_year[name][section.status] += 1
                if section.status == "unparsed":
                    self.note("requisite_documents", f"{name}_unparsed", self.item(course, catalog_year=edition))
            evidence = document.description_evidence
            stats["description_evidence"][evidence.status if evidence else "not_captured"] += 1
            comparison = credit_comparison(document.credit_hours, course.credits)
            stats["credit_hours_vs_course_credits"][comparison] += 1
            by_year["credit_hours_vs_course_credits"][comparison] += 1
            if comparison == "conflict":
                self.note("requisite_documents", "credit_hours_conflict", self.item(course, catalog_year=edition))
        legacy_only = 0
        for course_id, course in self.scope.items():
            departments[_department(course.primary_code)]["courses_in_scope"] += 1
            if course.prereqs and not self.documents.get(course_id):
                legacy_only += 1
                self.note("requisite_documents", "legacy_prereqs_without_usable_document", self.item(course))
        return {
            "denominator": {"document_rows": len(rows)},
            "counts": _all(DOCUMENT_CATEGORIES, counts),
            "by_catalog_year": {
                edition: {
                    "usable": stats["usable"], "unusable": stats["unusable"],
                    "courses_in_scope_covered": len(stats["courses"]),
                    "prerequisite": _all(PARSE_STATUSES, stats["prerequisite"]),
                    "corequisite": _all(PARSE_STATUSES, stats["corequisite"]),
                    "description_evidence": _all(("not_listed", "no_keyword_match", "review_needed", "not_captured"),
                                                 stats["description_evidence"]),
                    "credit_hours_vs_course_credits": _all(CREDIT_COMPARISONS, stats["credit_hours_vs_course_credits"]),
                    "captured_on": _day_range(stats["captured"]),
                } for edition, stats in sorted(editions.items())},
            "in_scope_courses": {"denominator": {"courses_in_scope": len(self.scope)},
                                 "with_usable_document_any_year": len(self.documents),
                                 "legacy_prereqs_without_usable_document": legacy_only},
            "by_department": {
                name: {"courses_in_scope": item["courses_in_scope"],
                       "by_catalog_year": {edition: {
                           "with_usable_document": stats["with_usable_document"],
                           "prerequisite": _all(PARSE_STATUSES, stats["prerequisite"]),
                           "corequisite": _all(PARSE_STATUSES, stats["corequisite"]),
                           "credit_hours_vs_course_credits": _all(CREDIT_COMPARISONS,
                                                                  stats["credit_hours_vs_course_credits"]),
                       } for edition, stats in sorted(item["by_catalog_year"].items())}}
                for name, item in sorted(departments.items())},
            "rules": RULES["requisite_documents"],
        }

    def program_plans(self):
        # Without programs the first category (orphan rows) cannot be decided, so nothing is counted.
        self.require("program_plans", "programs")
        values = self.programs()
        program_ids = {value for value in values if isinstance(value, str)}
        rows = self.rows("SELECT plan_id, program_id, campus, catalog_year, pathway, concentration, document, "
                         "content_hash FROM program_plans")
        counts, candidates = Counter(), []
        for row in rows:
            if _undecodable(row):
                category = "text_not_utf8"
            elif row["program_id"] not in program_ids:
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
            self.note("program_plans", category, _listable_plan_id(row["plan_id"]))
        scopes = Counter(plan.scope_key() for plan in candidates)
        ids = Counter(plan.plan_id for plan in candidates)
        usable = []
        for plan in candidates:
            if scopes[plan.scope_key()] > 1 or ids[plan.plan_id] > 1:
                counts["duplicate_scope_or_id"] += 1
                self.note("program_plans", "duplicate_scope_or_id", _listable_plan_id(plan.plan_id))
            else:
                counts["usable"] += 1
                usable.append(plan)
        by_program, unlisted = defaultdict(lambda: defaultdict(Counter)), 0
        for plan in usable:
            program, plan_id = _listable_id(plan.program_id), _listable_plan_id(plan.plan_id)
            if program is None:
                unlisted += 1
            else:
                stats = by_program[program][plan.catalog_year]
                stats["usable"] += 1
                stats[plan.coverage] += 1
                stats[plan.review_status] += 1
            self.note("program_plans", "usable_scopes", None if program is None or plan_id is None else {
                "plan_id": plan_id, "program_id": program, "campus": plan.campus,
                "catalog_year": plan.catalog_year, "pathway": plan.pathway,
                "has_concentration": bool(plan.concentration), "coverage": plan.coverage,
                "review_status": plan.review_status})
        repeated = Counter(value for value in values if isinstance(value, str))
        single = {value for value, count in repeated.items() if count == 1}
        complete = {plan.program_id for plan in usable if plan.coverage == "complete"}
        planned = {plan.program_id for plan in usable}
        for program in single - planned:
            self.note("program_plans", "programs_without_usable_plan", _listable_id(program))
        return {
            "denominator": {"plan_rows": len(rows)},
            "counts": _all(PLAN_CATEGORIES, counts),
            "usable_plans": {
                "denominator": {"usable_plans": len(usable)},
                "coverage": _all(("partial", "complete"), Counter(plan.coverage for plan in usable)),
                "review_status": _all(("draft", "source_checked"), Counter(plan.review_status for plan in usable)),
                "source_fingerprint": {"recorded": sum(bool(plan.source_html_sha256) for plan in usable),
                                       "missing": sum(not plan.source_html_sha256 for plan in usable)},
                "captured_on": _day_range(plan.captured_on.isoformat() for plan in usable),
            },
            "by_program": {
                program: {"by_catalog_year": {
                    edition: _all(("usable", "partial", "complete", "draft", "source_checked"), stats)
                    for edition, stats in sorted(editions.items())}}
                for program, editions in sorted(by_program.items())},
            "usable_plans_with_unlisted_program_id": unlisted,
            "programs": {
                "denominator": {"program_rows": len(values)},
                "with_any_complete_plan": len(complete & single),
                "with_only_partial_plans": len((planned - complete) & single),
                "without_usable_plan": len(single - planned),
                "id_unusable": len(values) - len(single),
                "rows_with_text_not_utf8": sum(isinstance(value, _Undecodable) for value in values),
            },
            "rules": RULES["program_plans"],
        }

    def legacy_rows(self):
        self.require_section("courses")
        result = {"rules": RULES["legacy_rows"]}
        for table, columns in (("program_required_courses", ("program_id", "course_id")),
                               ("course_prerequisites", ("course_id", "prereq_course_id"))):
            if marker := self.unavailable(table):
                result[table] = marker
                continue
            rows = self.rows(f"SELECT {', '.join(columns)} FROM {table}")
            course_columns = [name for name in columns if name.endswith("course_id")]
            outside = sum(any(row[name] not in self.scope for name in course_columns) for row in rows)
            block = {"status": "checked", "denominator": {"rows": len(rows)},
                     "rows_for_courses_in_scope": len(rows) - outside, "rows_for_courses_out_of_scope": outside,
                     "rows_with_text_not_utf8": sum(_undecodable(row) for row in rows)}
            if table == "course_prerequisites":
                block["courses_in_scope_with_edges"] = len(
                    {row["course_id"] for row in rows if row["course_id"] in self.scope})
            elif marker := self.unavailable("programs"):
                block["by_program"] = marker
            else:
                # Keyed only by well-formed IDs the programs table has; the rest are counted, not named.
                program_ids = {value for value in self.programs() if isinstance(value, str)}
                known, groups = Counter(), Counter()
                for row in rows:
                    program = _listable_id(row["program_id"])
                    if program is None:
                        groups["rows_with_unlisted_program_id"] += 1
                    elif program in program_ids:
                        known[program] += 1
                    else:
                        groups["rows_for_unknown_programs"] += 1
                block["by_program"] = dict(sorted(known.items()))
                block.update(_all(("rows_for_unknown_programs", "rows_with_unlisted_program_id"), groups))
            result[table] = block
        return result


def _department_of(item) -> str:
    return _department(item if isinstance(item, str) else item["code"])


def _capped(items: list, limit: int) -> dict:
    return {"items": items[:limit], "omitted": max(len(items) - limit, 0)}


def _order(item) -> tuple:
    """Sort key of a --details item: its course code first, so the records of one code stay together and a bound
    favours neither form of item (a plain code, or one with its course_id); then the whole item (edition, course_id)."""
    if isinstance(item, str):
        return item, ""
    return item.get("code") or "", json.dumps(item, sort_keys=True)


def _bounded(details: dict, limit: int) -> dict:
    """Bounded --details lists in _order; course items are listed per department, each department up to the limit."""
    output = {}
    for section, groups in sorted(details.items()):
        output[section] = {}
        for key, items in sorted(groups.items()):
            listed = sorted((item for item in items if item is not None), key=_order)
            entry = {"unlisted_malformed": len(items) - len(listed)}
            if section in COURSE_DETAIL_SECTIONS:
                departments = defaultdict(list)
                for item in listed:
                    departments[_department_of(item)].append(item)
                entry["by_department"] = {name: _capped(values, limit) for name, values in sorted(departments.items())}
            else:
                entry.update(_capped(listed, limit))
            output[section][key] = entry
    return output


def _all_checked(node) -> bool:
    """False when this block, or any block inside it, has a status other than checked."""
    if not isinstance(node, dict):
        return True
    status = node.get("status")
    if isinstance(status, str) and status != "checked":  # A data key such as a program named "status" is no status.
        return False
    return all(_all_checked(value) for value in node.values())


SECTIONS = ("schema", "courses", "catalog_snapshots", "fields", "requisite_documents", "program_plans", "legacy_rows")


def build_report(db_copy, *, details: bool = False, max_codes: int = DEFAULT_MAX_CODES) -> dict:
    if not isinstance(max_codes, int) or not 1 <= max_codes <= MAX_CODES_LIMIT:
        raise ValueError("max_codes outside 1..500")
    report = {"format_version": FORMAT_VERSION, "report": "data_coverage", "complete": False,
              "database": {"status": "failed", "code": "database_unavailable"},
              "sections": {name: {"status": "not_checked", "code": "database_unavailable"} for name in SECTIONS},
              "limitations": list(LIMITATIONS), "rules_doc": "docs/data-coverage-report.md"}
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        report["database"]["code"] = "sqlite_version_unsupported"
        return report
    inputs, reads, budget = Inputs(), _Reads(), {"exceeded": False}
    try:
        if Path(db_copy).name.lower().startswith(".env"):
            raise PreflightError("unsafe_input_path")  # The shared helper refuses only .env and .env.<name>.
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
        # immutable avoids creating shm/wal files; valid only for a stable offline copy.
        conn = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1)
    except sqlite3.Error:
        report["database"]["code"] = "database_open_failed"
        return report
    try:
        try:
            layout = _prepare(conn, reads, budget)
        except PreflightError as exc:  # The integrity check failed.
            report["database"]["code"] = exc.args[0]
            return report
        except sqlite3.Error:
            # Not a readable SQLite database, or the budget ran out: report no section at all.
            report["database"]["code"] = "sqlite_budget" if budget["exceeded"] else "database_error"
            return report
        audit = _Audit(conn, reads, layout, details)
        for name in SECTIONS:
            audit.run(name, getattr(audit, name))
            if budget["exceeded"] and audit.sections[name]["status"] == "failed":
                audit.sections[name]["code"] = "sqlite_budget"
    finally:
        conn.close()
    try:
        inputs.unchanged()
        _sidecars_absent(path)
    except (PreflightError, OSError):
        # Results read from a copy that changed underneath are not reported at all.
        report["database"]["code"] = "inputs_changed_during_check"
        return report
    report["database"] = {"status": "checked", "code": "read_only_snapshot"}
    report["sections"] = audit.sections
    report["complete"] = all(_all_checked(section) for section in audit.sections.values())
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
                        help="also list course codes (per department) and plan IDs per gap category (bounded)")
    parser.add_argument("--max-codes", type=int, default=DEFAULT_MAX_CODES,
                        help=f"items per listed category (per department for courses) with --details, "
                             f"1..{MAX_CODES_LIMIT}")
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
