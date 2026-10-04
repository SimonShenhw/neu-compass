"""Selected archive-to-copy comparisons must never repair or approve a release."""

import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'scripts/verify_release_imports.py'


def verifier():
    if not SCRIPT.exists():
        pytest.fail('release_import_verifier_not_implemented', pytrace=False)
    from scripts.verify_release_imports import run_verification
    return run_verification


def by_name(report, name):
    return next(item for item in report['checks'] if item['name'] == name)


@pytest.fixture
def imported(tmp_path):
    verifier()
    from scripts.release_rehearsal_fixtures import build_inputs
    from scripts.rehearse_release import _apply
    workspace = tmp_path / 'owned-fixture'
    workspace.mkdir()
    inputs = build_inputs(workspace)
    for version in ('1.3', '1.4', '1.5', '1.6', '1.7'):
        _apply(version, inputs, inputs.db, commit=True)
    return inputs


def selection(inputs):
    return dict(catalog_files=[inputs.catalog_dir / 'synthetic.jsonl'],
                plan_files=[inputs.plan_file], program_source_dir=inputs.program_dir,
                requisite_manifest=inputs.requisite_manifest,
                requisite_source_dir=inputs.requisite_dir,
                course_codes=['CS 5004', 'CS 5800'])


def snapshot(directory):
    return {str(path.relative_to(directory)): path.read_bytes()
            for path in directory.rglob('*') if path.is_file()}


def test_selected_imports_pass_without_writes_or_approval(imported):
    before = snapshot(imported.root)
    report = verifier()(imported.db, **selection(imported))
    assert report['machine_status'] == 'selected_import_checks_passed'
    assert all(item['status'] == 'passed' for item in report['checks'])
    assert report['release_approved'] is False
    assert all(item['status'] == 'pending' for item in report['manual_gates'])
    assert snapshot(imported.root) == before


def test_schema_and_counts_do_not_hide_missing_plan(imported):
    with sqlite3.connect(imported.db) as conn:
        conn.execute('DELETE FROM program_plans WHERE plan_id=(SELECT min(plan_id) FROM program_plans)')
    before = snapshot(imported.root)
    report = verifier()(imported.db, **selection(imported))
    assert by_name(report, 'schema_contract')['status'] == 'passed'
    assert by_name(report, 'plan_imports')['status'] == 'failed'
    assert report['machine_status'] == 'failed' and snapshot(imported.root) == before


def test_recomputed_plan_digest_does_not_mask_content_drift(imported):
    from schemas.program_plan import ProgramPlan
    from db.program_plan_repository import content_hash
    with sqlite3.connect(imported.db) as conn:
        plan_id, raw = conn.execute('SELECT plan_id,document FROM program_plans LIMIT 1').fetchone()
        payload = json.loads(raw)
        payload['notes'] = 'private-changed-content-canary'
        plan = ProgramPlan.model_validate(payload)
        conn.execute('UPDATE program_plans SET document=?,content_hash=? WHERE plan_id=?',
                     (plan.model_dump_json(), content_hash(plan), plan_id))
    before = snapshot(imported.root)
    report = verifier()(imported.db, **selection(imported))
    assert by_name(report, 'plan_imports')['status'] == 'failed'
    assert 'canary' not in json.dumps(report) and snapshot(imported.root) == before


def test_absent_source_groups_are_not_a_success(imported):
    report = verifier()(imported.db)
    assert report['machine_status'] == 'failed'
    for name in ('catalog_sources', 'plan_sources', 'requisite_sources',
                 'catalog_imports', 'plan_imports', 'requisite_imports'):
        assert by_name(report, name)['status'] == 'not_checked'


def test_content_and_private_report_contract(imported):
    report = verifier()(imported.db, **selection(imported))
    assert len(report['checks']) == 12
    assert by_name(report, 'catalog_imports')['facts']['matched_records'] == 2
    assert by_name(report, 'plan_sources')['facts']['partial_plans'] == 2
    assert by_name(report, 'requisite_sources')['facts']['unparsed_sections'] == 1
    assert by_name(report, 'requisite_imports')['facts']['matched_records'] == 2
    for value in ['canary', str(imported.root), 'synthetic-ds-', 'example.invalid',
                  'sha256', 'Design', 'Instructor permission', 'CREATE TABLE', 'catalog.northeastern.edu']:
        assert value not in json.dumps(report)


@pytest.mark.parametrize('group', ['catalog', 'plans', 'requisites'])
def test_one_selected_group_does_not_claim_other_groups_checked(imported, group):
    keys = {'catalog': ('catalog_files',), 'plans': ('plan_files', 'program_source_dir'),
            'requisites': ('requisite_manifest', 'requisite_source_dir', 'course_codes')}[group]
    options = {key: value for key, value in selection(imported).items() if key in keys}
    report = verifier()(imported.db, **options)
    assert report['machine_status'] == 'selected_import_checks_passed'
    name = {'catalog': 'catalog', 'plans': 'plan', 'requisites': 'requisite'}[group]
    assert by_name(report, name + '_imports')['status'] == 'passed'
    assert sum(c['status'] == 'not_checked' for c in report['checks']) == 4


@pytest.mark.parametrize('kind', [
    'catalog_missing', 'catalog_content', 'catalog_id', 'catalog_duplicate_json',
    'plan_hash', 'plan_scope', 'plan_invalid', 'plan_duplicate_json',
    'requisite_missing', 'requisite_hash', 'requisite_content', 'requisite_duplicate_json',
    'requisite_identity', 'requisite_description', 'requisite_hours', 'oversized_document',
])
def test_selected_stored_corruption_never_repaired_or_echoed(imported, kind):
    from schemas.course_requisite_document import CourseRequisiteDocument
    from db.course_requisite_repository import content_hash
    group = kind.split('_', 1)[0]
    if kind == 'oversized_document':
        group = 'catalog'
    table, column = {'catalog': ('course_catalog_sources', 'snapshot'),
                     'plan': ('program_plans', 'document'),
                     'requisite': ('course_requisite_documents', 'document')}[group]
    with sqlite3.connect(imported.db) as conn:
        rowid, raw = conn.execute(f'SELECT rowid,{column} FROM {table} ORDER BY rowid LIMIT 1').fetchone()
        payload = json.loads(raw)
        digest = None
        if kind.endswith('_missing'):
            conn.execute(f'DELETE FROM {table} WHERE rowid=?', (rowid,))
        elif kind.endswith('_hash'):
            conn.execute(f'UPDATE {table} SET content_hash=? WHERE rowid=?', ('0' * 64, rowid))
        elif kind == 'plan_scope':
            conn.execute('UPDATE program_plans SET campus=? WHERE rowid=?', ('private-campus-canary', rowid))
        else:
            if kind == 'catalog_content':
                payload['description'] = 'private-catalog-description-canary'
            elif kind == 'catalog_id':
                payload['snapshot_id'] = 'private-snapshot-id-canary'
            elif kind == 'plan_invalid':
                payload['requirements'] = {'kind': 'private-invalid-rule-canary'}
            elif kind == 'requisite_identity':
                payload['course_id'] = 'private-rebound-id-canary'
            elif kind == 'requisite_content':
                # Valid structure and a recomputed digest still differs from the frozen page.
                payload['requisites']['prerequisite'] = {'status': 'not_listed'}
                document = CourseRequisiteDocument.model_validate(payload)
                digest = content_hash(document)
            elif kind == 'requisite_description':
                payload['description_evidence'] = None
                digest = content_hash(CourseRequisiteDocument.model_validate(payload))
            elif kind == 'requisite_hours':
                payload['credit_hours'] = None
                digest = content_hash(CourseRequisiteDocument.model_validate(payload))
            raw = json.dumps(payload)
            if kind.endswith('_duplicate_json'):
                raw = raw[:-1] + ',"course_name":"private-duplicate-canary"}' if group != 'plan' else (
                    raw[:-1] + ',"notes":"private-duplicate-canary"}')
            if kind == 'oversized_document':
                payload['description'] = 'private-oversized-canary' + ' ' * 200_001
                raw = json.dumps(payload)
            conn.execute(f'UPDATE {table} SET {column}=? WHERE rowid=?', (raw, rowid))
            if digest is not None:
                conn.execute(f'UPDATE {table} SET content_hash=? WHERE rowid=?', (digest, rowid))
    before = snapshot(imported.root)
    report = verifier()(imported.db, **selection(imported))
    assert by_name(report, group + '_imports')['status'] == 'failed'
    assert report['machine_status'] == 'failed' and report['release_approved'] is False
    assert 'canary' not in json.dumps(report) and snapshot(imported.root) == before


def test_import_timestamps_and_json_formatting_are_not_content_drift(imported):
    with sqlite3.connect(imported.db) as conn:
        for table, column in [('course_catalog_sources', 'snapshot'), ('course_requisite_documents', 'document')]:
            rows = conn.execute(f'SELECT rowid,{column} FROM {table}').fetchall()
            for rowid, raw in rows:
                payload = json.loads(raw)
                payload['imported_at'] = '2025-01-01T00:00:00Z'
                if table == 'course_catalog_sources':
                    payload['retrieved_at'] = '2024-01-01T00:00:00Z'
                conn.execute(f'UPDATE {table} SET {column}=? WHERE rowid=?',
                             (json.dumps(payload, indent=2, sort_keys=True), rowid))
    before = snapshot(imported.root)
    assert verifier()(imported.db, **selection(imported))['machine_status'] == 'selected_import_checks_passed'
    assert snapshot(imported.root) == before


@pytest.mark.parametrize('kind', ['unknown', 'ambiguous', 'title'])
def test_catalog_importer_skips_are_visible_and_all_skipped_fails(imported, kind):
    catalog = imported.catalog_dir / 'synthetic.jsonl'
    entry = json.loads(catalog.read_text().splitlines()[0])
    if kind == 'unknown':
        entry['course_code'] = 'CS 9999'
    elif kind == 'title':
        entry['course_name'] = 'Private mismatched title canary'
    else:
        with sqlite3.connect(imported.db) as conn:
            metadata, generated = conn.execute(
                "SELECT metadata,generated_json FROM courses WHERE course_id='design'").fetchone()
            conn.execute('INSERT INTO courses(course_id,primary_code,primary_name,metadata,generated_json) '
                         'VALUES(?,?,?,?,?)',
                         ('duplicate-synthetic-course', 'CS 5004', 'Design', metadata, generated))
    if kind == 'unknown':
        catalog.write_text(catalog.read_text() + json.dumps(entry) + '\n')
    else:
        catalog.write_text(json.dumps(entry) + '\n')
    options = {'catalog_files': [catalog]}
    report = verifier()(imported.db, **options)
    if kind == 'unknown':
        facts = by_name(report, 'catalog_imports')['facts']
        assert facts['matched_records'] == 2 and facts['skipped_unknown_or_ambiguous'] == 1
        catalog.write_text(json.dumps(entry) + '\n')
        report = verifier()(imported.db, **options)
    assert by_name(report, 'catalog_imports')['code'] == 'no_matching_catalog_records'
    assert report['machine_status'] == 'failed'


@pytest.mark.parametrize('kind', ['duplicate_file', 'conflict', 'duplicate_key', 'nonfinite',
                                 'empty', 'oversize', 'too_many_records'])
def test_catalog_source_errors_fail_closed(imported, monkeypatch, kind):
    import scripts.verify_release_imports as module
    catalog = imported.catalog_dir / 'synthetic.jsonl'
    options = selection(imported)
    if kind == 'duplicate_file':
        options['catalog_files'] *= 2
    elif kind == 'conflict':
        entry = json.loads(catalog.read_text().splitlines()[0])
        entry['description'] = 'private-conflicting-archive-canary'
        catalog.write_text(catalog.read_text() + json.dumps(entry) + '\n')
    elif kind == 'duplicate_key':
        catalog.write_text('{"course_code":"private-key-canary","course_code":"CS 5004"}\n')
    elif kind == 'nonfinite':
        catalog.write_text('{"credits":NaN}\n')
    elif kind == 'empty':
        catalog.write_text(' \n')
    elif kind == 'oversize':
        monkeypatch.setattr(module, 'MAX_CATALOG_BYTES', 1)
    else:
        monkeypatch.setattr(module, 'MAX_CATALOG_RECORDS', 1)
    before = snapshot(imported.root)
    report = verifier()(imported.db, **options)
    assert by_name(report, 'catalog_sources')['status'] == 'failed'
    assert by_name(report, 'catalog_imports')['status'] == 'not_checked'
    assert report['machine_status'] == 'failed' and snapshot(imported.root) == before
    assert 'canary' not in json.dumps(report)


def test_identical_catalog_records_collapse_like_importer(imported):
    catalog = imported.catalog_dir / 'synthetic.jsonl'
    catalog.write_text(catalog.read_text() * 2)
    report = verifier()(imported.db, **selection(imported))
    assert by_name(report, 'catalog_sources')['facts']['identical_duplicates_collapsed'] == 2
    assert report['machine_status'] == 'selected_import_checks_passed'


@pytest.mark.parametrize('kind', ['plan_no_dir', 'plan_no_files', 'plan_duplicate', 'plan_scope',
    'plan_rule', 'plan_html', 'plan_sidecar_key', 'requisite_no_dir', 'requisite_no_manifest',
    'requisite_no_codes', 'requisite_duplicate_codes', 'requisite_html', 'requisite_sidecar_key',
    'requisite_manifest_key'])
def test_archive_groups_and_semantic_audits_fail_closed(imported, kind):
    options = selection(imported)
    group = kind.split('_', 1)[0]
    if kind == 'plan_no_dir':
        options['program_source_dir'] = None
    elif kind == 'plan_no_files':
        options['plan_files'] = []
    elif kind == 'plan_duplicate':
        options['plan_files'] *= 2
    elif kind in ('plan_scope', 'plan_rule'):
        plans = json.loads(imported.plan_file.read_text())
        if kind == 'plan_scope':
            plans[0]['campus'] = 'seattle'
        else:
            plans[0]['requirements']['children'][0]['min_credits'] = 8
        imported.plan_file.write_text(json.dumps(plans))
    elif kind == 'requisite_no_dir':
        options['requisite_source_dir'] = None
    elif kind == 'requisite_no_manifest':
        options['requisite_manifest'] = None
    elif kind == 'requisite_no_codes':
        options['course_codes'] = []
    elif kind == 'requisite_duplicate_codes':
        options['course_codes'] *= 2
    elif kind == 'requisite_manifest_key':
        imported.requisite_manifest.write_text('[{"url":"private-url-canary","url":"duplicate"}]')
    else:
        directory = imported.program_dir if group == 'plan' else imported.requisite_dir
        if kind.endswith('_html'):
            next(directory.glob('*.html')).write_bytes(b'private-html-canary')
        else:
            sidecar = next(directory.glob('*.json'))
            raw = sidecar.read_text()
            sidecar.write_text(raw[:-1] + ',"url":"private-sidecar-canary"}')
    before = snapshot(imported.root)
    report = verifier()(imported.db, **options)
    assert by_name(report, group + '_sources')['status'] == 'failed'
    assert by_name(report, group + '_imports')['status'] == 'not_checked'
    assert report['machine_status'] == 'failed' and snapshot(imported.root) == before
    assert 'canary' not in json.dumps(report)


@pytest.mark.parametrize('kind', ['schema', 'wal', 'shm', 'journal', 'symlink_db', 'symlink_source', 'env_source'])
def test_unsafe_or_unavailable_copy_and_sources_are_not_touched(imported, kind):
    db, options = imported.db, selection(imported)
    if kind == 'schema':
        with sqlite3.connect(db) as conn:
            conn.execute('DROP INDEX idx_chat_answers_expires')
    elif kind in ('wal', 'shm', 'journal'):
        Path(str(db) + '-' + kind).write_bytes(b'private-sidecar-canary')
    elif kind == 'symlink_db':
        db = imported.root / 'linked.sqlite3'
        db.symlink_to(imported.db)
    elif kind == 'symlink_source':
        source = imported.root / 'linked.jsonl'
        source.symlink_to(options['catalog_files'][0])
        options['catalog_files'] = [source]
    else:
        source = imported.root / '.env'
        source.write_text('SYNTHETIC_SECRET=private-env-canary')
        options['catalog_files'] = [source]
    before = snapshot(imported.root)
    report = verifier()(db, **options)
    assert report['machine_status'] == 'failed' and snapshot(imported.root) == before
    assert 'canary' not in json.dumps(report)
    if kind in ('schema', 'wal', 'shm', 'journal', 'symlink_db'):
        assert all(by_name(report, name)['status'] == 'not_checked'
                   for name in ('catalog_imports', 'plan_imports', 'requisite_imports'))


@pytest.mark.parametrize('kind', ['db', 'source', 'late_wal'])
def test_mutation_during_comparison_cannot_be_a_pass(imported, monkeypatch, kind):
    import scripts.verify_release_imports as module
    original = module._plan_imports

    def changed(conn, state):
        result = original(conn, state)
        if kind == 'db':
            with sqlite3.connect(imported.db) as other:
                other.execute("UPDATE courses SET search_expansion='private-mutated-canary'")
        elif kind == 'source':
            imported.plan_file.write_text(imported.plan_file.read_text() + ' ')
        else:
            Path(str(imported.db) + '-wal').write_bytes(b'private-late-wal-canary')
        return result

    monkeypatch.setattr(module, '_plan_imports', changed)
    report = verifier()(imported.db, **selection(imported))
    assert by_name(report, 'input_stability')['status'] == 'failed'
    assert report['machine_status'] == 'failed' and 'canary' not in json.dumps(report)


def cli_args(db, options):
    args = ['--db-copy', str(db)]
    for key, flag in [('catalog_files', '--catalog-file'), ('plan_files', '--plan-file'),
                      ('course_codes', '--course-code')]:
        for value in options.get(key, []):
            args += [flag, str(value)]
    for key, flag in [('program_source_dir', '--program-source-dir'),
                      ('requisite_manifest', '--requisite-manifest'),
                      ('requisite_source_dir', '--requisite-source-dir')]:
        if options.get(key) is not None:
            args += [flag, str(options[key])]
    return args


@pytest.mark.parametrize('kind', ['pass', 'bad_copy', 'missing_arg', 'commit', 'output', 'abbreviation'])
def test_real_cli_off_cwd_exit_codes_and_no_private_output(imported, tmp_path, kind):
    args, expected = cli_args(imported.db, selection(imported)), 0
    if kind == 'bad_copy':
        imported.db.write_bytes(b'private-bad-copy-canary')
        expected = 1
    elif kind == 'missing_arg':
        args, expected = [], 2
    elif kind in ('commit', 'output', 'abbreviation'):
        args += {'commit': ['--commit'], 'output': ['--out=private-output-canary'],
                 'abbreviation': ['--db=private-path-canary']}[kind]
        expected = 2
    before = snapshot(imported.root)
    run = subprocess.run([sys.executable, '-B', str(SCRIPT), *args], cwd=tmp_path,
                         text=True, capture_output=True, timeout=30)
    assert run.returncode == expected and run.stderr == ''
    report = json.loads(run.stdout)
    assert report['release_approved'] is False
    assert 'canary' not in run.stdout and str(imported.root) not in run.stdout
    assert snapshot(imported.root) == before


def test_fresh_cli_forbids_configuration_network_processes_and_disk_writes(imported, tmp_path):
    code = '''
import importlib.abc, json, os, pathlib, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'config', 'api', 'app', 'dotenv'}:
            raise RuntimeError('forbidden_config_import')
sys.meta_path.insert(0, Block())
allowed_db = pathlib.Path(sys.argv[2]).as_uri() + '?mode=ro&immutable=1'
def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'}:
        raise RuntimeError('forbidden_external_action')
    if event == 'sqlite3.connect' and args[0] not in {':memory:', allowed_db}:
        raise RuntimeError('forbidden_sqlite_connection')
    if event == 'open':
        path, mode, flags = args
        if isinstance(path, (str, bytes)):
            name = pathlib.Path(os.fsdecode(path)).name.lower()
            if name == '.env' or name.startswith('.env.'):
                raise RuntimeError('forbidden_env_read')
        if (mode and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise RuntimeError('forbidden_disk_write')
sys.addaudithook(audit)
sys.path.insert(0, sys.argv[1])
from scripts.verify_release_imports import cli
raise SystemExit(cli(sys.argv[3:]))
'''
    before = snapshot(imported.root)
    run = subprocess.run([sys.executable, '-B', '-c', code, str(ROOT), str(imported.db),
                          *cli_args(imported.db, selection(imported))],
                         cwd=tmp_path, text=True, capture_output=True, timeout=30)
    assert run.returncode == 0 and run.stderr == ''
    report = json.loads(run.stdout)
    assert all(item['status'] == 'passed' for item in report['checks'])
    assert report['release_approved'] is False and snapshot(imported.root) == before


def test_copy_connections_are_immutable_query_only_and_zero_dml(imported, monkeypatch):
    import scripts.verify_release_imports as module
    original = sqlite3.connect
    targets, statements, changes = [], [], []

    class CountConnection(sqlite3.Connection):
        def close(self):
            if not self.in_memory:
                changes.append(self.total_changes)
            return super().close()

    def tracked(database, *args, **kwargs):
        conn = original(database, *args, factory=CountConnection, **kwargs)
        conn.in_memory = database == ':memory:'
        targets.append((database, kwargs))
        if not conn.in_memory:
            conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(module.sqlite3, 'connect', tracked)
    assert verifier()(imported.db, **selection(imported))['machine_status'] == 'selected_import_checks_passed'
    disk = [item for item in targets if item[0] != ':memory:']
    assert len(disk) == 2 and all('?mode=ro&immutable=1' in item[0] and item[1]['uri'] for item in disk)
    assert changes == [0, 0]
    assert statements.count('PRAGMA query_only=ON') == 2 and statements.count('BEGIN') == 2
    assert all(sql.split()[0].upper() in {'PRAGMA', 'BEGIN', 'SELECT'} for sql in statements)


def test_special_characters_in_copy_path_are_uri_encoded(imported):
    target = imported.root / '副本 ?#&.sqlite3'
    imported.db.rename(target)
    assert verifier()(target, **selection(imported))['machine_status'] == 'selected_import_checks_passed'


@pytest.mark.parametrize('kind', ['title', 'ambiguous'])
def test_partial_catalog_skips_do_not_claim_full_archive_imported(imported, kind):
    catalog = imported.catalog_dir / 'synthetic.jsonl'
    records = [json.loads(line) for line in catalog.read_text().splitlines()]
    if kind == 'title':
        records[0]['course_name'] = 'Private mismatched title canary'
        catalog.write_text('\n'.join(json.dumps(item) for item in records) + '\n')
    else:
        with sqlite3.connect(imported.db) as conn:
            conn.execute("INSERT INTO courses(course_id,primary_code,primary_name,metadata,generated_json) "
                         "SELECT 'duplicate-course',primary_code,primary_name,metadata,generated_json "
                         "FROM courses WHERE course_id='design'")
    before = snapshot(imported.root)
    report = verifier()(imported.db, catalog_files=[catalog])
    facts = by_name(report, 'catalog_imports')['facts']
    assert report['machine_status'] == 'selected_import_checks_passed'
    assert facts['matched_records'] == 1 and facts['matching_records_only'] is True
    assert facts['skipped_title_mismatch' if kind == 'title' else 'skipped_unknown_or_ambiguous'] == 1
    assert snapshot(imported.root) == before


@pytest.mark.parametrize('path', ['//private-server-canary/share/copy.sqlite3',
                                 '\\\\private-server-canary\\share\\copy.sqlite3'])
def test_unc_copy_refused_before_filesystem_probe(path, monkeypatch):
    function = verifier()
    calls = []

    def forbidden(self, *args, **kwargs):
        calls.append(True)
        raise AssertionError('unexpected_filesystem_probe')

    monkeypatch.setattr(Path, 'stat', forbidden)
    report = function(Path(path))
    assert by_name(report, 'database_copy')['code'] == 'nonlocal_input_path'
    assert not calls and 'canary' not in json.dumps(report)


def test_linked_parent_directory_rejected_without_source_read(imported):
    link = imported.root / 'linked-parent'
    link.symlink_to(imported.catalog_dir, target_is_directory=True)
    before = snapshot(imported.root)
    report = verifier()(imported.db, catalog_files=[link / 'synthetic.jsonl'])
    assert by_name(report, 'catalog_sources')['code'] == 'unsafe_input_path'
    assert report['machine_status'] == 'failed' and snapshot(imported.root) == before


def test_unselected_corrupt_rows_do_not_become_selected_coverage_claim(imported):
    with sqlite3.connect(imported.db) as conn:
        conn.execute("INSERT INTO program_plans(plan_id,program_id,campus,catalog_year,pathway,concentration,document,content_hash) "
                     "VALUES('private-unselected-plan-canary','ds-ms','boston','2025-2026','standard','','{}',?)",
                     ('0' * 64,))
    before = snapshot(imported.root)
    report = verifier()(imported.db, **selection(imported))
    assert report['machine_status'] == 'selected_import_checks_passed'
    assert by_name(report, 'plan_imports')['facts']['selected_scopes_only'] is True
    assert 'unselected_database_rows_and_extra_schema_objects_not_reviewed' in report['limitations']
    assert 'canary' not in json.dumps(report) and snapshot(imported.root) == before


def test_private_parser_exception_never_exposed(imported, monkeypatch):
    import scripts.verify_release_imports as module

    def fail(*args, **kwargs):
        raise ValueError('private-source-exception-canary')

    monkeypatch.setattr(module, '_catalog_sources', fail)
    report = verifier()(imported.db, **selection(imported))
    assert by_name(report, 'catalog_sources')['code'] == 'check_failed'
    assert report['machine_status'] == 'failed' and 'canary' not in json.dumps(report)


def test_failed_loader_cannot_leave_partial_state_for_comparison(imported, monkeypatch):
    import scripts.verify_release_imports as module

    def fail(inputs, files, state):
        state['catalog'] = {}
        raise ValueError('private-partial-loader-canary')

    monkeypatch.setattr(module, '_catalog_sources', fail)
    report = verifier()(imported.db, **selection(imported))
    assert by_name(report, 'catalog_sources')['status'] == 'failed'
    assert by_name(report, 'catalog_imports')['status'] == 'not_checked'
    assert by_name(report, 'plan_imports')['status'] == 'passed'
    assert report['machine_status'] == 'failed' and 'canary' not in json.dumps(report)
