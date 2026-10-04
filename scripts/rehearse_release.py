"""Rehearse v1.3-v1.7 only in a newly owned, automatically cleaned temp directory.

No existing DB/input/workspace arguments, Settings/.env, network, deployments,
or approval. Synthetic results do not verify production backups or HTTP gates.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.answer_feedback_repository import AnswerFeedbackRepository
from db.catalog_source_repository import CatalogSourceRepository
from db.course_requisite_repository import CourseRequisiteRepository
from db.program_plan_repository import ProgramPlanRepository
from db.repository import CourseRepository
from schemas.answer_feedback import AnswerFeedbackRequest
from scripts.migrate_answer_feedback import migrate as migrate_feedback
from scripts.migrate_coop_submissions import migrate as migrate_coop
from scripts.release_preflight import MANUAL_GATES, PreflightError, SafeParser, _existing, _safe_check, run_preflight
from scripts.release_rehearsal_fixtures import COURSES, QUERY_MARKER, build_inputs
from scripts.sync_catalog_sources import sync_sources
from scripts.sync_course_requisites import sync_requisites
from scripts.sync_program_plans import sync_plans

VERSIONS = ('1.3', '1.4', '1.5', '1.6', '1.7')
TABLES = {
    '1.3': ('coop_submissions', 'coop_contribution_credits'),
    '1.4': ('course_catalog_sources',), '1.5': ('program_plans',),
    '1.6': ('course_requisite_documents',), '1.7': ('chat_answers', 'answer_feedback'),
}
STORES = {'1.4': CatalogSourceRepository, '1.5': ProgramPlanRepository, '1.6': CourseRequisiteRepository}


class StopRehearsal(Exception):
    pass


class InjectedStoreFailure(Exception):
    pass


def _require(value, code):
    if not value:
        raise PreflightError(code)


def _read_connection(path):
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    conn.execute('PRAGMA query_only=ON')
    return conn


def logical_fingerprint(path, *, tables=None):
    """Private artifact check, not a public DB hash or a generic content audit."""
    conn = _read_connection(path)
    try:
        conn.execute('BEGIN')
        objects = list(conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' ORDER BY type,name"))
        names = tables if tables is not None else [name for kind, name, _, _ in objects if kind == 'table']
        rows = {}
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            rows[name] = list(conn.execute(f'SELECT * FROM {quoted} ORDER BY rowid'))
        if tables is not None:
            objects = [row for row in objects if row[2] in tables]
        payload = json.dumps([objects, rows], sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        return hashlib.sha256(payload.encode()).hexdigest()
    finally:
        conn.close()


def _source_fingerprint(inputs):
    paths = [inputs.plan_file, inputs.requisite_manifest]
    for directory in (inputs.catalog_dir, inputs.program_dir, inputs.requisite_dir):
        paths.extend(sorted(directory.iterdir()))
    return [(path, hashlib.sha256(path.read_bytes()).hexdigest()) for path in paths]


def _backup_new(source, target):
    _require(not target.exists() and not target.is_symlink(), 'rollback_copy_already_exists')
    reader = _read_connection(source)
    writer = None
    try:
        writer = sqlite3.connect(target)
        reader.backup(writer)
    finally:
        if writer is not None:
            writer.close()
        reader.close()


def _apply(version, inputs, db, *, commit):
    if version == '1.3':
        return migrate_coop(db, commit=commit)
    if version == '1.4':
        return sync_sources(db, inputs.catalog_dir, commit=commit)
    if version == '1.5':
        return sync_plans(db, inputs.plan_file, commit=commit, source_dir=inputs.program_dir)
    if version == '1.6':
        return sync_requisites(db, inputs.requisite_manifest, inputs.requisite_dir,
            [code for _, code, _ in COURSES], commit=commit)
    if version == '1.7':
        return migrate_feedback(db, commit=commit)
    raise PreflightError('unknown_rehearsal_layer')


def _expected_failure(function, kind):
    try:
        function()
    except kind:
        return
    except Exception:
        raise PreflightError('unexpected_injected_failure_type') from None
    raise PreflightError('injected_failure_not_observed')


def _version_rollback(version, inputs):
    target = inputs.root / f'rollback-version-{version}.sqlite3'
    main_before = logical_fingerprint(inputs.db)
    _backup_new(inputs.db, target)
    conn = sqlite3.connect(target)
    try:
        conn.execute("CREATE TRIGGER synthetic_version_guard BEFORE INSERT ON schema_versions "
            f"WHEN NEW.version='{version}' BEGIN SELECT RAISE(ABORT,'synthetic_version_failure'); END")
        conn.commit()
    finally:
        conn.close()
    before = logical_fingerprint(target)
    _expected_failure(lambda: _apply(version, inputs, target, commit=True), sqlite3.IntegrityError)
    _require(logical_fingerprint(target) == before, 'version_failure_not_fully_rolled_back')
    _require(logical_fingerprint(inputs.db) == main_before, 'rollback_changed_main_fixture')
    return {'ddl_and_version_rollback_verified': True, 'prior_layers_preserved': True}


def _store_rollback(version, inputs):
    target = inputs.root / f'rollback-store-{version}.sqlite3'
    _backup_new(inputs.db, target)
    before = logical_fingerprint(target)
    cls, table = STORES[version], TABLES[version][0]
    original = cls.store
    calls, partial = 0, False

    def fail_second(self, *args, **kwargs):
        nonlocal calls, partial
        calls += 1
        if calls == 2:
            raise InjectedStoreFailure('synthetic_second_store_failure')
        result = original(self, *args, **kwargs)
        partial = (self._conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 1
            and self._conn.execute('SELECT 1 FROM schema_versions WHERE version=?', (version,)).fetchone() is not None)
        return result

    with patch.object(cls, 'store', fail_second):
        _expected_failure(lambda: _apply(version, inputs, target, commit=True), InjectedStoreFailure)
    _require(calls == 2 and partial, 'partial_store_failure_not_exercised')
    _require(logical_fingerprint(target) == before, 'partial_store_not_fully_rolled_back')
    return {'partial_write_observed': True, 'ddl_version_and_rows_rolled_back': True}


def _feedback_rollback(inputs):
    target = inputs.root / 'rollback-feedback-sanity.sqlite3'
    _backup_new(inputs.db, target)
    before = logical_fingerprint(target)
    observed = False

    def failed_sanity(self):
        nonlocal observed
        names = {row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        observed = (set(TABLES['1.7']).issubset(names)
            and self.conn.execute("SELECT 1 FROM schema_versions WHERE version='1.7'").fetchone() is not None)
        return False

    with patch.object(AnswerFeedbackRepository, 'schema_available', failed_sanity):
        _expected_failure(lambda: _apply('1.7', inputs, target, commit=True), ValueError)
    _require(observed and logical_fingerprint(target) == before, 'feedback_postddl_rollback_not_verified')
    return {'postddl_failure_observed': True, 'schema_and_version_rolled_back': True}


def _dry_run(inputs):
    before = inputs.db.read_bytes()
    for version in VERSIONS:
        result = _apply(version, inputs, inputs.db, commit=False)
        if version in STORES:
            _require(result['schema_missing'] and result['would_store'] == 2 and result['stored'] == 0,
                'dry_run_import_expectation_failed')
        else:
            _require(set(result) == set(TABLES[version]), 'dry_run_missing_table_expectation_failed')
    _require(inputs.db.read_bytes() == before, 'dry_run_changed_database_bytes')
    return {'layers_checked': 5, 'database_bytes_unchanged': True}


def _commit_layer(version, inputs, core_tables, core_before):
    result = _apply(version, inputs, inputs.db, commit=True)
    if version in STORES:
        _require(result['stored'] == result['would_store'] == 2, 'first_import_count_mismatch')
    else:
        _require(set(result) == set(TABLES[version]), 'first_migration_missing_table_mismatch')
    conn = _read_connection(inputs.db)
    try:
        _require(conn.execute('SELECT 1 FROM schema_versions WHERE version=?', (version,)).fetchone() is not None,
            'committed_version_missing')
        for table in TABLES[version]:
            count = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            _require(count == (2 if version in STORES else 0), 'committed_table_row_count_mismatch')
    finally:
        conn.close()
    _require(logical_fingerprint(inputs.db, tables=core_tables) == core_before, 'legacy_rows_or_schema_changed')
    return {'version_committed': True, 'legacy_state_preserved': True, 'imported_records': 2 if version in STORES else 0}


def _verify_imports(inputs):
    conn = _read_connection(inputs.db)
    conn.row_factory = sqlite3.Row
    try:
        courses = [CourseRepository(conn).get(cid) for cid, _, _ in COURSES]
        snapshots = CatalogSourceRepository(conn).get_batch(courses)
        _require(len(snapshots) == 2 and all(s.description and s.description.startswith('Synthetic')
            and s.retrieved_at is None for s in snapshots.values()), 'catalog_content_unusable')
        plans = ProgramPlanRepository(conn).list_for_program('ds-ms')
        _require(len(plans) == 2 and all(p.coverage == 'partial' for p in plans), 'plan_content_or_partial_lost')
        repo = CourseRequisiteRepository(conn)
        design, algo = repo.list_for_course('design'), repo.list_for_course('algo')
        _require(len(design.documents) == len(algo.documents) == 1
            and design.unusable_records == algo.unusable_records == 0, 'requisite_content_unusable')
        clause = design.documents[0].requisites
        _require(clause.prerequisite.rule.kind == 'any_of'
            and [c.course_code for c in clause.prerequisite.rule.children] == ['CS 5001', 'CS 5010']
            and clause.corequisite.rule.course_code == 'CS 5005', 'requisite_logic_or_external_refs_changed')
        _require(algo.documents[0].requisites.prerequisite.status == 'unparsed'
            and algo.documents[0].requisites.prerequisite.rule is None, 'unknown_clause_promoted_to_rule')
        _require(all(d.campus is None for d in (design.documents[0], algo.documents[0])), 'course_campus_invented')
    finally:
        conn.close()
    return {'catalog_records': 2, 'partial_plans': 2, 'requisite_records': 2, 'unparsed_sections': 1,
            'or_corequisite_and_unknown_references_preserved': True}


def _feedback_repository(inputs):
    conn = sqlite3.connect(inputs.db)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        repo = AnswerFeedbackRepository(conn)
        receipt = repo.store_completed(query_log_id=41, answer_text='synthetic-private-answer-canary',
            prompt_version='synthetic-rehearsal', request_context={'k': 1, 'history_turn_count': 0})
        request = AnswerFeedbackRequest(**receipt.model_dump(), rating='down')
        repo.vote(request)
        conn.commit()
        before = list(conn.execute('SELECT * FROM answer_feedback'))
        changes = conn.total_changes
        repo.vote(request)
        _require(conn.total_changes == changes and list(conn.execute('SELECT * FROM answer_feedback')) == before,
            'same_vote_was_not_noop')
        repo.vote(AnswerFeedbackRequest(**receipt.model_dump(), rating='up'))
        conn.commit()
        _require(conn.execute('SELECT COUNT(*) FROM answer_feedback').fetchone()[0] == 1
            and conn.execute('SELECT rating FROM answer_feedback').fetchone()[0] == 'up', 'vote_correction_not_latest_single_row')
        _require(conn.execute('SELECT user_id FROM query_log WHERE log_id=41').fetchone()[0] == QUERY_MARKER
            and conn.execute('SELECT COUNT(*) FROM query_log').fetchone()[0] == 2, 'original_eval_log_changed_or_duplicated')
    finally:
        conn.close()
    return {'same_vote_no_dml': True, 'correction_keeps_one_latest_vote': True, 'original_eval_log_preserved': True}


def _repeat(inputs):
    before, connect, changes = logical_fingerprint(inputs.db), sqlite3.connect, []

    class CountConnection(sqlite3.Connection):
        def close(self):
            changes.append(self.total_changes)
            super().close()

    def counted(*args, **kwargs):
        kwargs['factory'] = CountConnection
        return connect(*args, **kwargs)

    with patch.object(sqlite3, 'connect', counted):
        for version in VERSIONS:
            result = _apply(version, inputs, inputs.db, commit=True)
            if version in STORES:
                _require(result['stored'] == result['would_store'] == 0, 'repeat_import_not_noop')
            else:
                _require(result == [], 'repeat_migration_still_missing_tables')
    _require(len(changes) == 5 and sum(changes) == 0, 'repeat_migration_or_import_performed_dml')
    _require(logical_fingerprint(inputs.db) == before, 'repeat_changed_logical_state_or_timestamps')
    return {'layers_replayed': 5, 'dml_changes': 0, 'logical_rows_and_timestamps_unchanged': True}


def _postflight(inputs):
    report = run_preflight(inputs.db, plan_files=[inputs.plan_file], program_source_dir=inputs.program_dir)
    _require(report['machine_status'] == 'requested_checks_passed' and report['release_approved'] is False,
        'post_migration_preflight_failed')
    return {'schema_and_foreign_keys_checked': True, 'plan_source_checked': True, 'policy_sources_not_checked': True}


def _names():
    names = ['synthetic_inputs', 'dry_run_preserves_baseline']
    for version in VERSIONS:
        names.append(f'rollback_version_{version}')
        if version in STORES:
            names.append(f'rollback_partial_store_{version}')
        if version == '1.7':
            names.append('rollback_feedback_postddl')
        names.append(f'commit_layer_{version}')
    return names + ['imported_content', 'repository_feedback', 'repeat_all_layers', 'post_migration_preflight',
                    'source_inputs_unchanged', 'owned_workspace_cleaned']


def _step(report, name, function):
    if not _safe_check(report, name, function):
        raise StopRehearsal()


def _temporary_parent():
    # Passing dir explicitly avoids tempfile's writable-directory probe files
    # before mkdtemp has created the owned workspace. No cwd fallback.
    candidate = tempfile.tempdir
    if candidate is None:
        candidate = (os.environ.get('TEMP') or os.environ.get('TMP')) if sys.platform == 'win32' else (os.environ.get('TMPDIR') or '/tmp')
    _require(candidate is not None, 'local_temporary_parent_unavailable')
    return _existing(Path(os.fsdecode(candidate)), directory=True)


def run_rehearsal() -> dict:
    report = dict(format_version=1, machine_status='failed', synthetic_only=True, release_approved=False,
        production_backup_restore_verified=False, checks=[],
        manual_gates=[dict(name=name, status='pending') for name in MANUAL_GATES],
        limitations=['synthetic_pages_not_official_source_evidence', 'stages_not_one_atomic_release_transaction',
            'http_operator_shutdown_gate_requires_companion_test', 'no_policy_or_index_model_or_live_account_check',
            'no_real_copy_or_backup_restore_or_deployment_verification'])
    try:
        with tempfile.TemporaryDirectory(prefix='neu-release-rehearsal-', dir=_temporary_parent()) as temporary:
            state = {}

            def create():
                state['inputs'] = build_inputs(Path(temporary))
                return {'base_schema_version': '1.2'}

            _step(report, 'synthetic_inputs', create)
            inputs = state['inputs']
            source_before = _source_fingerprint(inputs)
            conn = _read_connection(inputs.db)
            try:
                core_tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT GLOB 'sqlite_*' AND name!='schema_versions' ORDER BY name")]
            finally:
                conn.close()
            core_before = logical_fingerprint(inputs.db, tables=core_tables)
            _step(report, 'dry_run_preserves_baseline', lambda: _dry_run(inputs))
            for version in VERSIONS:
                _step(report, f'rollback_version_{version}', lambda: _version_rollback(version, inputs))
                if version in STORES:
                    _step(report, f'rollback_partial_store_{version}', lambda: _store_rollback(version, inputs))
                if version == '1.7':
                    _step(report, 'rollback_feedback_postddl', lambda: _feedback_rollback(inputs))
                _step(report, f'commit_layer_{version}', lambda: _commit_layer(version, inputs, core_tables, core_before))
            _step(report, 'imported_content', lambda: _verify_imports(inputs))
            _step(report, 'repository_feedback', lambda: _feedback_repository(inputs))
            _step(report, 'repeat_all_layers', lambda: _repeat(inputs))
            _step(report, 'post_migration_preflight', lambda: _postflight(inputs))

            def source_stable():
                _require(_source_fingerprint(inputs) == source_before, 'source_inputs_changed')
                _require(logical_fingerprint(inputs.db, tables=core_tables) == core_before, 'legacy_state_changed_after_replay')
                return {'inputs_and_legacy_state_unchanged': True}

            _step(report, 'source_inputs_unchanged', source_stable)
        report['checks'].append(dict(name='owned_workspace_cleaned', status='passed', code='checked', facts={}))
    except StopRehearsal:
        pass
    except Exception:
        report['checks'].append(dict(name='owned_workspace', status='failed', code='rehearsal_workspace_failed', facts={}))
    present = {item['name'] for item in report['checks']}
    for name in _names():
        if name not in present:
            report['checks'].append(dict(name=name, status='not_checked', code='earlier_check_failed', facts={}))
    if all(item['status'] == 'passed' for item in report['checks']):
        report['machine_status'] = 'rehearsal_checks_passed'
    return report


def cli(argv=None) -> int:
    parser = SafeParser(description=__doc__)
    parser.parse_args(argv)
    try:
        report = run_rehearsal()
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
        return 0 if report['machine_status'] == 'rehearsal_checks_passed' else 1
    except Exception:
        print(json.dumps(dict(machine_status='failed', synthetic_only=True, release_approved=False, code='rehearsal_failed')))
        return 1


if __name__ == '__main__':
    raise SystemExit(cli())
