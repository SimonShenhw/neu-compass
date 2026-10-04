"""Read-only selected archive-to-offline-copy consistency checks.

Explicit inputs only; no Settings/.env, network, migration, repair, export or
release approval. A matching selected subset is not complete source coverage.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.release_preflight import (  # noqa: E402
    Inputs, MANUAL_GATES, MAX_PLAN_FILES, MAX_PLANS, PreflightError, SafeParser,
    _archive, _database_checks, _existing, _invalid_number, _pairs_unique,
    _read_json, _result, _safe_check, _sidecars_absent,
)

MAX_CATALOG_FILES = 20
MAX_CATALOG_BYTES = 5_000_000
MAX_CATALOG_RECORDS = 10_000
MAX_DOCUMENT_BYTES = 200_000
LIMITATIONS = (
    'stable_offline_copy_and_backup_restore_not_proven',
    'selected_input_groups_and_matching_catalog_records_only',
    'unselected_database_rows_and_extra_schema_objects_not_reviewed',
    'catalog_jsonl_has_no_original_html_authenticity_or_capture_time_proof',
    'catalog_import_and_retrieval_times_excluded_from_content_comparison',
    'requisite_import_time_excluded_from_content_comparison',
    'partial_unparsed_and_unknown_references_are_not_eligibility',
    'policy_fragments_personal_pos_and_index_models_not_checked',
    'no_live_configuration_account_retention_or_release_verification',
    'aggregate_report_is_not_public_or_anonymized',
)


def _bytes(inputs, path, budget):
    path = inputs.track(path, budget)
    with path.open('rb') as stream:
        raw = stream.read(budget + 1)
    if len(raw) > budget:
        raise PreflightError('input_size_budget')
    if hashlib.sha256(raw).hexdigest() != inputs.files[path][1]:
        raise PreflightError('inputs_changed_during_check')
    return raw


def _json(raw):
    return json.loads(raw, object_pairs_hook=_pairs_unique, parse_constant=_invalid_number)


def _catalog_content(snapshot):
    return snapshot.model_dump(mode='json', exclude={'snapshot_id', 'imported_at', 'retrieved_at'})


def _catalog_sources(inputs, files, state):
    from db.catalog_source_repository import CatalogSourceRepository
    from scrapers.neu_catalog import CatalogEntry

    if not 1 <= len(files) <= MAX_CATALOG_FILES:
        raise PreflightError('catalog_file_count_budget')
    paths, snapshots, records = set(), {}, 0
    for path in files:
        path = _existing(path)
        if path in paths:
            raise PreflightError('duplicate_catalog_file')
        paths.add(path)
        for line in _bytes(inputs, path, MAX_CATALOG_BYTES).decode('utf-8-sig').splitlines():
            if not line.strip():
                continue
            records += 1
            if records > MAX_CATALOG_RECORDS or len(line.encode('utf-8')) > MAX_DOCUMENT_BYTES:
                raise PreflightError('catalog_record_budget')
            entry = CatalogEntry.model_validate(_json(line))
            snapshot = CatalogSourceRepository.snapshot(entry)
            prior = snapshots.get(snapshot.course_code)
            if prior is not None and (prior.snapshot_id != snapshot.snapshot_id
                                     or _catalog_content(prior) != _catalog_content(snapshot)):
                raise PreflightError('conflicting_catalog_records')
            snapshots[snapshot.course_code] = snapshot
    if not snapshots:
        raise PreflightError('empty_catalog_selection')
    state['catalog'] = snapshots
    return {'records_checked': len(snapshots), 'identical_duplicates_collapsed': records - len(snapshots)}


def _plan_sources(inputs, files, source_dir, state):
    from schemas.program_plan import ProgramPlan
    from scripts.audit_program_rule_sources import audit_plan

    if not files or source_dir is None or not 1 <= len(files) <= MAX_PLAN_FILES:
        raise PreflightError('plan_input_group_incomplete')
    directory = _existing(source_dir, directory=True)
    paths, plans = set(), []
    for path in files:
        path = _existing(path)
        if path in paths:
            raise PreflightError('duplicate_plan_file')
        paths.add(path)
        payload = _read_json(inputs, path, 1_000_000)
        if not isinstance(payload, list) or not 1 <= len(payload) <= MAX_PLANS:
            raise PreflightError('plan_count_budget')
        plans.extend(ProgramPlan.model_validate(item) for item in payload)
    if (len(plans) > MAX_PLANS or len({p.plan_id for p in plans}) != len(plans)
            or len({p.scope_key() for p in plans}) != len(plans)):
        raise PreflightError('duplicate_or_excess_plan_scope')
    for plan in plans:
        if plan.campus != 'boston' or plan.catalog_year != '2026-2027':
            raise PreflightError('unsupported_frozen_plan_scope')
        if not plan.source_html_sha256:
            raise PreflightError('plan_source_fingerprint_missing')
        _archive(inputs, directory, plan.source_html_sha256)
        audit_plan(plan, directory)
    state['plans'] = plans
    return {'plans_checked': len(plans), 'partial_plans': sum(p.coverage == 'partial' for p in plans)}


def _requisite_sources(inputs, manifest, source_dir, codes, state):
    from schemas.course_requisite_source import CourseRequisiteSource
    from scripts.audit_course_requisites import build_report

    if manifest is None or source_dir is None or not codes:
        raise PreflightError('requisite_input_group_incomplete')
    directory = _existing(source_dir, directory=True)
    payload = _read_json(inputs, manifest, 64_000)
    if not isinstance(payload, list) or not 1 <= len(payload) <= 20:
        raise PreflightError('requisite_manifest_count_budget')
    for item in payload:
        metadata = CourseRequisiteSource.model_validate(item)
        _archive(inputs, directory, metadata.sha256)
    # Reuse the importer's actual parser and selection contract, never guess edges.
    parsed = build_report(_existing(manifest), directory, list(codes))
    state['requisites'] = parsed['records']
    return {'records_checked': len(parsed['records']), 'unparsed_sections': parsed['unparsed_sections']}


def _one(conn, sql, params, *, missing='stored_document_missing'):
    rows = conn.execute(sql, params).fetchmany(2)
    if not rows:
        raise PreflightError(missing)
    if len(rows) != 1:
        raise PreflightError('ambiguous_stored_identity')
    return rows[0]


def _document(raw, model):
    if not isinstance(raw, str) or not 0 < len(raw.encode('utf-8')) <= MAX_DOCUMENT_BYTES:
        raise PreflightError('stored_document_budget_or_type')
    return model.model_validate(_json(raw))


def _catalog_imports(conn, state):
    from schemas.answer_evidence import CatalogSnapshot

    matched = skipped = titles = 0
    for expected in state['catalog'].values():
        rows = conn.execute('SELECT course_id,primary_name FROM courses WHERE primary_code=?',
                            (expected.course_code,)).fetchmany(2)
        if len(rows) != 1:
            skipped += 1  # Exact existing import behavior: unknown or ambiguous codes are skipped.
            continue
        if rows[0]['primary_name'] != expected.course_name:
            titles += 1
            continue
        row = _one(conn, 'SELECT CASE WHEN length(snapshot)<=? THEN snapshot END AS document '
                   'FROM course_catalog_sources WHERE course_id=?',
                   (MAX_DOCUMENT_BYTES, rows[0]['course_id']))
        stored = _document(row['document'], CatalogSnapshot)
        if stored.snapshot_id != expected.snapshot_id or _catalog_content(stored) != _catalog_content(expected):
            raise PreflightError('stored_catalog_content_mismatch')
        matched += 1
    if not matched:
        raise PreflightError('no_matching_catalog_records')
    return {'matched_records': matched, 'skipped_unknown_or_ambiguous': skipped,
            'skipped_title_mismatch': titles, 'matching_records_only': True}


def _plan_imports(conn, state):
    from schemas.program_plan import ProgramPlan
    from db.program_plan_repository import content_hash

    for expected in state['plans']:
        _one(conn, 'SELECT program_id FROM programs WHERE program_id=?', (expected.program_id,),
             missing='selected_program_missing')
        row = _one(conn, 'SELECT plan_id,program_id,campus,catalog_year,pathway,concentration,content_hash,'
                   'CASE WHEN length(document)<=? THEN document END AS document '
                   'FROM program_plans WHERE plan_id=?', (MAX_DOCUMENT_BYTES, expected.plan_id))
        stored = _document(row['document'], ProgramPlan)
        scope = tuple(row[key] for key in ('program_id', 'campus', 'catalog_year', 'pathway', 'concentration'))
        if row['plan_id'] != stored.plan_id or scope != stored.scope_key() or scope != expected.scope_key():
            raise PreflightError('stored_plan_identity_mismatch')
        if content_hash(stored) != row['content_hash']:
            raise PreflightError('stored_plan_digest_mismatch')
        if stored != expected or content_hash(stored) != content_hash(expected):
            raise PreflightError('stored_plan_content_mismatch')
    return {'matched_records': len(state['plans']), 'selected_scopes_only': True}


def _requisite_imports(conn, state):
    from schemas.course_requisite_document import CourseRequisiteDocument
    from db.course_requisite_repository import content_hash

    for record in state['requisites']:
        course = _one(conn, 'SELECT course_id,primary_name FROM courses WHERE primary_code=?',
                      (record['course_code'],), missing='selected_course_missing')
        if course['primary_name'] != record['course_name']:
            raise PreflightError('selected_course_title_mismatch')
        expected = CourseRequisiteDocument(course_id=course['course_id'],
            **{key: record[key] for key in ('course_code', 'course_name', 'catalog_year', 'source',
                                            'requisites', 'description_evidence', 'credit_hours')})
        row = _one(conn, 'SELECT course_id,catalog_year,content_hash,'
                   'CASE WHEN length(document)<=? THEN document END AS document '
                   'FROM course_requisite_documents WHERE course_id=? AND catalog_year=?',
                   (MAX_DOCUMENT_BYTES, expected.course_id, expected.catalog_year))
        stored = _document(row['document'], CourseRequisiteDocument)
        if (row['course_id'], row['catalog_year']) != (stored.course_id, stored.catalog_year):
            raise PreflightError('stored_requisite_identity_mismatch')
        if content_hash(stored) != row['content_hash']:
            raise PreflightError('stored_requisite_digest_mismatch')
        if (stored.model_dump(exclude={'imported_at'}) != expected.model_dump(exclude={'imported_at'})
                or content_hash(stored) != content_hash(expected)):
            raise PreflightError('stored_requisite_content_mismatch')
    return {'matched_records': len(state['requisites']), 'selected_course_editions_only': True}


def _compare(report, db_copy, state, selected):
    required = ('database_copy', 'database_integrity', 'schema_contract', 'schema_versions', 'foreign_keys')
    ready = all(any(c['name'] == name and c['status'] == 'passed' for c in report['checks']) for name in required)
    conn = None
    functions = {'catalog': _catalog_imports, 'plans': _plan_imports, 'requisites': _requisite_imports}
    names = {'catalog': 'catalog_imports', 'plans': 'plan_imports', 'requisites': 'requisite_imports'}
    try:
        if ready and state:
            path = _existing(db_copy)
            _sidecars_absent(path)
            conn = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True, timeout=1)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA query_only=ON')
            conn.execute('PRAGMA trusted_schema=OFF')
            deadline, steps = time.monotonic() + 10, 0

            def bounded():
                nonlocal steps
                steps += 10_000
                return int(steps > 50_000_000 or time.monotonic() > deadline)

            conn.set_progress_handler(bounded, 10_000)
            conn.execute('BEGIN')
        for group in functions:
            if not selected[group]:
                report['checks'].append(_result(names[group], 'not_checked', 'inputs_not_supplied'))
            elif group not in state:
                report['checks'].append(_result(names[group], 'not_checked', 'source_check_required'))
            elif not ready:
                report['checks'].append(_result(names[group], 'not_checked', 'database_checks_required'))
            else:
                _safe_check(report, names[group], lambda group=group: functions[group](conn, state))
    except Exception:
        for name in names.values():
            if not any(c['name'] == name for c in report['checks']):
                report['checks'].append(_result(name, 'not_checked', 'comparison_unavailable'))
        report['checks'].append(_result('database_comparison', 'failed', 'database_comparison_failed'))
    finally:
        if conn is not None:
            conn.close()


def run_verification(db_copy: Path, *, catalog_files=(), plan_files=(), program_source_dir=None,
                     requisite_manifest=None, requisite_source_dir=None, course_codes=()) -> dict:
    report = dict(format_version=1, machine_status='failed', release_approved=False, checks=[],
                  manual_gates=[dict(name=name, status='pending') for name in MANUAL_GATES],
                  limitations=list(LIMITATIONS))
    inputs, state = Inputs(), {}
    selected = {'catalog': bool(catalog_files), 'plans': bool(plan_files or program_source_dir),
                'requisites': bool(requisite_manifest or requisite_source_dir or course_codes)}
    if not any(selected.values()):
        report['checks'].append(_result('selected_inputs', 'failed', 'no_source_groups_selected'))
    _database_checks(report, db_copy, inputs)
    loaders = (
        ('catalog', 'catalog_sources', lambda: _catalog_sources(inputs, catalog_files, state)),
        ('plans', 'plan_sources', lambda: _plan_sources(inputs, plan_files, program_source_dir, state)),
        ('requisites', 'requisite_sources', lambda: _requisite_sources(
            inputs, requisite_manifest, requisite_source_dir, course_codes, state)),
    )
    for group, name, loader in loaders:
        if selected[group]:
            if not _safe_check(report, name, loader):
                # A future loader must not turn partial state into a comparison.
                state.pop(group, None)
        else:
            report['checks'].append(_result(name, 'not_checked', 'inputs_not_supplied'))
    _compare(report, db_copy, state, selected)

    def stable():
        inputs.unchanged()
        if any(c['name'] == 'database_copy' and c['status'] == 'passed' for c in report['checks']):
            _sidecars_absent(_existing(db_copy))

    _safe_check(report, 'input_stability', stable)
    if not any(c['status'] == 'failed' for c in report['checks']):
        report['machine_status'] = 'selected_import_checks_passed'
    return report


def cli(argv=None) -> int:
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--db-copy', required=True, type=Path)
    parser.add_argument('--catalog-file', action='append', type=Path, default=[])
    parser.add_argument('--plan-file', action='append', type=Path, default=[])
    parser.add_argument('--program-source-dir', type=Path)
    parser.add_argument('--requisite-manifest', type=Path)
    parser.add_argument('--requisite-source-dir', type=Path)
    parser.add_argument('--course-code', action='append', default=[])
    args = parser.parse_args(argv)
    try:
        report = run_verification(args.db_copy, catalog_files=args.catalog_file, plan_files=args.plan_file,
            program_source_dir=args.program_source_dir, requisite_manifest=args.requisite_manifest,
            requisite_source_dir=args.requisite_source_dir, course_codes=args.course_code)
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
        return 0 if report['machine_status'] == 'selected_import_checks_passed' else 1
    except Exception:
        print(json.dumps(dict(format_version=1, machine_status='failed', release_approved=False,
                              code='import_verification_failed')))
        return 1


if __name__ == '__main__':
    raise SystemExit(cli())
