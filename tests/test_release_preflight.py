"""Offline synthetic copies only; a machine pass never grants release authority."""

import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'scripts/release_preflight.py'


def preflight():
    if not SCRIPT.exists():
        pytest.fail('release_preflight_not_implemented', pytrace=False)
    from scripts.release_preflight import run_preflight
    return run_preflight


def copy_db(empty_db, tmp_path):
    target = tmp_path / 'synthetic.sqlite3'
    with sqlite3.connect(target) as conn:
        empty_db.backup(conn)
        conn.execute('PRAGMA journal_mode=DELETE')
    return target


def check(report, name):
    return next(item for item in report['checks'] if item['name'] == name)


def test_existing_copy_is_unchanged_and_never_approved(empty_db, tmp_path):
    db = copy_db(empty_db, tmp_path)
    before = db.read_bytes()
    report = preflight()(db)
    assert report['machine_status'] == 'requested_checks_passed'
    assert report['release_approved'] is False
    assert all(item['status'] == 'pending' for item in report['manual_gates'])
    assert check(report, 'plan_sources')['status'] == 'not_checked'
    assert check(report, 'policy_sources')['status'] == 'not_checked'
    assert db.read_bytes() == before and set(tmp_path.iterdir()) == {db}


@pytest.mark.parametrize('name', ['absent.sqlite3', '.env'])
def test_missing_or_forbidden_input_is_not_created(tmp_path, name):
    path = tmp_path / name
    report = preflight()(path)
    assert report['machine_status'] == 'failed'
    assert check(report, 'database_copy')['status'] == 'failed'
    assert not path.exists() and not list(tmp_path.iterdir())


@pytest.mark.parametrize('suffix', ['-wal', '-shm', '-journal'])
def test_sidecars_fail_without_opening_copy(empty_db, tmp_path, suffix):
    db = copy_db(empty_db, tmp_path)
    sidecar = Path(str(db) + suffix)
    sidecar.write_bytes(b'synthetic-private-sidecar')
    before = {item.name: item.read_bytes() for item in tmp_path.iterdir()}
    report = preflight()(db)
    assert check(report, 'database_copy')['code'] == 'offline_copy_sidecars_present'
    assert {item.name: item.read_bytes() for item in tmp_path.iterdir()} == before


def test_fake_latest_version_does_not_mask_missing_schema(empty_db, tmp_path):
    db = copy_db(empty_db, tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute('DROP TABLE answer_feedback')
    report = preflight()(db)
    assert check(report, 'schema_versions')['status'] == 'passed'
    assert check(report, 'schema_contract')['status'] == 'failed'
    assert report['machine_status'] == 'failed' and report['release_approved'] is False


def test_bad_database_errors_do_not_echo_contents(tmp_path):
    db = tmp_path / 'private-path-canary.sqlite3'
    db.write_bytes(b'private-database-canary invalid SQLite')
    text = json.dumps(preflight()(db))
    assert 'private-path-canary' not in text and 'private-database-canary' not in text
    assert 'failed' in text and set(tmp_path.iterdir()) == {db}


@pytest.fixture
def sources(tmp_path):
    from db.program_plan_repository import content_hash
    from schemas.program_plan import ProgramPlan

    program_dir, policy_dir = tmp_path / 'program', tmp_path / 'policy'
    program_dir.mkdir()
    policy_dir.mkdir()
    heading = 'Data Design and Visualization Concentration—College of Arts, Media and Design'
    program_html = ('<h1>Data Science, MS (Boston)</h1><p>2026-2027 Edition</p>'
        '<div id="textcontainer"><ul><li>Data Design and Visualization—College of Arts, Media and Design</li>'
        '<li>Computer Science—Khoury College of Computer Sciences</li></ul></div>'
        f'<h2>{heading}</h2><table class="sc_courselist">'
        '<tr><td>Complete 4 semester hours</td></tr><tr><td>DS 5110</td></tr>'
        '<tr><td>Optional Co-op</td></tr><tr><td>EEAM 6964</td></tr></table>'
        '<h2>Computer Science Concentration—Khoury College of Computer Sciences</h2>'
        '<table class="sc_courselist"><tr><td>Complete 4 semester hours</td></tr><tr><td>DS 5110</td></tr>'
        '<tr><td>Optional Co-op</td></tr><tr><td>EEAM 6964</td></tr></table>').encode()
    program_hash = hashlib.sha256(program_html).hexdigest()
    plan = dict(plan_id='synthetic-ds-camd', program_id='ds-ms', campus='boston',
        catalog_year='2026-2027', pathway='standard', concentration='data-design-visualization',
        coverage='partial', review_status='source_checked', checked_by='synthetic-reviewer', checked_on='2026-10-02',
        source_url='https://catalog.northeastern.edu/graduate/university-interdisciplinary-programs/science-data-ms-bos/',
        source_title='Data Science, MS (Boston), 2026-2027 Edition', source_catalog_year='2026-2027',
        source_excerpt='synthetic-source-text-canary', source_html_sha256=program_hash,
        captured_on='2026-10-01', notes='synthetic incomplete rules, not eligibility',
        requirements=dict(kind='all_of', label='Synthetic partial', children=[
            dict(kind='select', label='Selection', min_credits=4, course_codes=['DS 5110']),
            dict(kind='optional', label='Co-op', activate_when='If independently approved',
                children=[dict(kind='course', label='Experience', course_code='EEAM 6964')]),
            dict(kind='unmodeled', label='Unknown policy')]))
    program_meta = dict(url=plan['source_url'], catalog_year='2026-2027', captured_at='2026-10-01T10:00:00Z',
        sha256=program_hash, byte_count=len(program_html), page_title='Data Science, MS (Boston)')
    (program_dir / f'{program_hash}.html').write_bytes(program_html)
    (program_dir / f'{program_hash}.json').write_text(json.dumps(program_meta))
    plan_file = tmp_path / 'plans.json'
    plan_file.write_text(json.dumps([plan]))
    policy_text = 'synthetic-private-policy-paragraph-canary'
    policy_html = ('<h1>Synthetic Policy</h1><p>2026-2027 Edition</p>'
        f'<div id="textcontainer"><h2>Standing</h2><p>{policy_text}</p></div>').encode()
    policy_hash = hashlib.sha256(policy_html).hexdigest()
    policy_meta = dict(url='https://catalog.northeastern.edu/graduate/arts-media-design/academic-policies-procedures/synthetic/',
        catalog_year='2026-2027', captured_at='2026-10-01T10:00:00Z', sha256=policy_hash,
        byte_count=len(policy_html), page_title='Synthetic Policy')
    (policy_dir / f'{policy_hash}.html').write_bytes(policy_html)
    (policy_dir / f'{policy_hash}.json').write_text(json.dumps(policy_meta))
    bundle = dict(checked_by='synthetic-reviewer', checked_on='2026-10-02',
        policies=[dict(policy_id='synthetic-policy', authority='camd', source=policy_meta,
            fragments=[dict(fragment_id='synthetic-fragment', paragraph_index=0, heading='Standing',
                paragraph_sha256=hashlib.sha256(policy_text.encode()).hexdigest(),
                summary='synthetic-private-summary-canary', limitation='not complete policy')])],
        links=[dict(plan_id=plan['plan_id'], program_id='ds-ms', campus='boston', catalog_year='2026-2027',
            pathway='standard', concentration='data-design-visualization', home_college='camd',
            plan_content_sha256=content_hash(ProgramPlan.model_validate(plan)), policy_ids=['synthetic-policy'])])
    bundle_file = tmp_path / 'bundle.json'
    bundle_file.write_text(json.dumps(bundle))
    return dict(plan_files=[plan_file], program_source_dir=program_dir,
                policy_bundle=bundle_file, policy_source_dir=policy_dir)


def snapshot(directory):
    return {str(path.relative_to(directory)): path.read_bytes() for path in directory.rglob('*') if path.is_file()}


def test_all_sources_pass_with_partial_limits_and_no_private_output(empty_db, tmp_path, sources):
    db = copy_db(empty_db, tmp_path)
    before = snapshot(tmp_path)
    report = preflight()(db, **sources)
    assert report['machine_status'] == 'requested_checks_passed'
    assert check(report, 'plan_sources')['facts'] == {'plans_checked': 1, 'partial_plans': 1}
    assert check(report, 'policy_sources')['facts']['selected_fragments_only'] is True
    text = json.dumps(report)
    for value in ['canary', str(tmp_path), 'synthetic-ds-camd', 'synthetic-reviewer', 'Synthetic Policy', 'sha256']:
        assert value not in text
    assert snapshot(tmp_path) == before and report['release_approved'] is False


@pytest.mark.parametrize('sql', [
    'DROP INDEX idx_chat_answers_expires',
    'DROP VIEW v_course_lookup',
    'DROP TRIGGER trg_courses_updated_at',
    'DROP TABLE answer_feedback',
    'ALTER TABLE query_log ADD COLUMN unexpected TEXT',
    "UPDATE schema_versions SET version='missing' WHERE version='1.6'",
])
def test_schema_changes_fail_without_repair(empty_db, tmp_path, sql):
    db = copy_db(empty_db, tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute(sql)
    before = db.read_bytes()
    report = preflight()(db)
    assert report['machine_status'] == 'failed' and report['release_approved'] is False
    assert db.read_bytes() == before


@pytest.mark.parametrize('clause', [
    'rating TEXT NOT NULL',
    "rating INTEGER NOT NULL CHECK(rating IN ('up','down'))",
    "rating TEXT NOT NULL CHECK(rating IN ('up','other'))",
])
def test_matching_columns_or_versions_do_not_mask_constraint_drift(empty_db, tmp_path, clause):
    db = copy_db(empty_db, tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute('DROP TABLE answer_feedback')
        conn.execute(f'CREATE TABLE answer_feedback(answer_id TEXT NOT NULL PRIMARY KEY, {clause}, '
            'created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, '
            'FOREIGN KEY(answer_id) REFERENCES chat_answers(answer_id) ON DELETE CASCADE)')
    assert check(preflight()(db), 'schema_contract')['code'] == 'schema_definition_mismatch'


def test_foreign_key_orphan_never_exposes_row_id(empty_db, tmp_path):
    db = copy_db(empty_db, tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO answer_feedback(answer_id, rating) VALUES (?, 'down')", ('private-row-id-canary',))
    report = preflight()(db)
    assert check(report, 'foreign_keys')['code'] == 'foreign_key_violation'
    assert 'private-row-id-canary' not in json.dumps(report)


@pytest.mark.parametrize('name', ['private_extension_canary', 'sqlitex_private_extension_canary'])
def test_extra_objects_are_counted_but_not_approved(empty_db, tmp_path, name):
    db = copy_db(empty_db, tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute(f'CREATE TABLE {name}(value TEXT)')
    report = preflight()(db)
    assert check(report, 'schema_contract')['facts']['extra_objects_not_reviewed'] == 1
    assert report['release_approved'] is False and name not in json.dumps(report)


def test_sql_normalization_preserves_literals_and_checks():
    preflight()
    from scripts.release_preflight import _canonical_sql
    assert _canonical_sql("CREATE TABLE IF NOT EXISTS t (v TEXT -- note\n DEFAULT 'A B');") == _canonical_sql("create table t(v text default 'A B');")
    assert _canonical_sql("create table t(v text default 'A B')") != _canonical_sql("create table t(v text default 'a b')")
    assert _canonical_sql("create table t(v text default '-- /* private */')") != _canonical_sql("create table t(v text default '')")


@pytest.mark.parametrize('kind', ['directory', 'empty', 'oversized', 'symlink', 'env'])
def test_invalid_db_inputs_preserved(empty_db, tmp_path, monkeypatch, kind):
    preflight()
    import scripts.release_preflight as module
    db = copy_db(empty_db, tmp_path)
    path = db
    if kind == 'directory':
        path = tmp_path
    elif kind == 'empty':
        db.write_bytes(b'')
    elif kind == 'oversized':
        monkeypatch.setattr(module, 'MAX_DB_BYTES', 1)
    elif kind == 'symlink':
        path = tmp_path / 'link.sqlite3'
        path.symlink_to(db)
    else:
        path = tmp_path / '.env'
        path.write_text('SYNTHETIC_SECRET=private-env-canary')
    before = snapshot(tmp_path)
    report = preflight()(path)
    assert check(report, 'database_copy')['status'] == 'failed'
    assert 'private-env-canary' not in json.dumps(report) and snapshot(tmp_path) == before


@pytest.mark.parametrize('kind', ['missing_dir', 'missing_files', 'duplicate_files', 'too_many_files',
    'empty', 'duplicate_json', 'nonfinite', 'duplicate_scope', 'fingerprint', 'unsupported', 'html',
    'sidecar', 'missing_archive', 'oversized', 'symlink_archive', 'table_rule', 'campus', 'edition'])
def test_plan_inputs_fail_closed(empty_db, tmp_path, sources, kind):
    db = copy_db(empty_db, tmp_path)
    selected = {key: value for key, value in sources.items() if key in ('plan_files', 'program_source_dir')}
    file = sources['plan_files'][0]
    data = json.loads(file.read_text())
    digest = data[0]['source_html_sha256']
    html = sources['program_source_dir'] / f'{digest}.html'
    if kind == 'missing_dir':
        selected['program_source_dir'] = None
    elif kind == 'missing_files':
        selected['plan_files'] = []
    elif kind in ('duplicate_files', 'too_many_files'):
        selected['plan_files'] *= 2 if kind == 'duplicate_files' else 11
    elif kind == 'empty':
        file.write_text('[]')
    elif kind == 'duplicate_json':
        file.write_text('[{"plan_id":"private-json-canary","plan_id":"duplicate"}]')
    elif kind == 'nonfinite':
        file.write_text('[NaN]')
    elif kind == 'duplicate_scope':
        file.write_text(json.dumps([*data, {**data[0], 'plan_id': 'different-id'}]))
    elif kind == 'fingerprint':
        data[0]['source_html_sha256'] = None
        file.write_text(json.dumps(data))
    elif kind == 'unsupported':
        data[0]['program_id'] = 'unsupported'
        file.write_text(json.dumps(data))
    elif kind in ('campus', 'edition'):
        if kind == 'campus':
            data[0]['campus'] = 'seattle'
        else:
            data[0]['catalog_year'] = data[0]['source_catalog_year'] = '2027-2028'
        file.write_text(json.dumps(data))
    elif kind == 'html':
        html.write_bytes(b'private-html-canary')
    elif kind == 'sidecar':
        (sources['program_source_dir'] / f'{digest}.json').write_text('{"sha256":"wrong"}')
    elif kind == 'missing_archive':
        html.unlink()
    elif kind == 'oversized':
        file.write_text(' ' * 1_000_001)
    elif kind == 'symlink_archive':
        other = tmp_path / 'other.html'
        html.rename(other)
        html.symlink_to(other)
    else:
        # Hash-consistent archives are still rejected when curated amounts drift.
        data[0]['requirements']['children'][0]['min_credits'] = 8
        file.write_text(json.dumps(data))
    before = snapshot(tmp_path)
    report = preflight()(db, **selected)
    assert check(report, 'plan_sources')['status'] == 'failed'
    assert report['machine_status'] == 'failed' and 'canary' not in json.dumps(report)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('kind', ['missing_dir', 'missing_bundle', 'no_plans', 'hash', 'scope', 'college',
    'html', 'position', 'duplicate_json', 'unlinked_plan'])
def test_policy_inputs_fail_without_source_text(empty_db, tmp_path, sources, kind):
    db = copy_db(empty_db, tmp_path)
    selected = dict(sources)
    file = sources['policy_bundle']
    data = json.loads(file.read_text())
    if kind == 'missing_dir':
        selected['policy_source_dir'] = None
    elif kind == 'missing_bundle':
        selected['policy_bundle'] = None
    elif kind == 'no_plans':
        selected['plan_files'] = []
        selected['program_source_dir'] = None
    elif kind in ('hash', 'scope', 'college'):
        key, value = {'hash': ('plan_content_sha256', '0' * 64),
            'scope': ('campus', 'seattle'), 'college': ('home_college', 'khoury')}[kind]
        data['links'][0][key] = value
        file.write_text(json.dumps(data))
    elif kind == 'html':
        digest = data['policies'][0]['source']['sha256']
        (sources['policy_source_dir'] / f'{digest}.html').write_bytes(b'private-policy-html-canary')
    elif kind == 'position':
        data['policies'][0]['fragments'][0]['paragraph_index'] = 1
        file.write_text(json.dumps(data))
    elif kind == 'duplicate_json':
        file.write_text('{"coverage":"private-policy-json-canary","coverage":"duplicate"}')
    else:
        plans = json.loads(sources['plan_files'][0].read_text())
        # Second supported scope intentionally has no link in the supplied bundle.
        second = {**plans[0], 'plan_id': 'another-plan', 'concentration': 'computer-science'}
        sources['plan_files'][0].write_text(json.dumps([*plans, second]))
    before = snapshot(tmp_path)
    report = preflight()(db, **selected)
    assert check(report, 'policy_sources')['status'] == 'failed'
    if kind == 'unlinked_plan':
        assert check(report, 'plan_sources')['status'] == 'passed'
        assert check(report, 'policy_sources')['code'] == 'selected_plans_missing_policy_links'
    assert report['machine_status'] == 'failed' and 'canary' not in json.dumps(report)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('kind', ['plan', 'db', 'sidecar'])
def test_inputs_changed_during_audit_are_not_a_pass(empty_db, tmp_path, sources, monkeypatch, kind):
    from scripts import audit_program_rule_sources as auditor
    db = copy_db(empty_db, tmp_path)
    original = auditor.audit_plan

    def changed(plan, directory):
        report = original(plan, directory)
        if kind == 'plan':
            sources['plan_files'][0].write_text('["synthetic-change"]')
        elif kind == 'db':
            with sqlite3.connect(db) as conn:
                conn.execute("INSERT INTO query_log(route, query) VALUES('chat', 'private-new-row-canary')")
        else:
            Path(str(db) + '-wal').write_bytes(b'synthetic-late-sidecar')
        return report

    monkeypatch.setattr(auditor, 'audit_plan', changed)
    selected = {key: sources[key] for key in ('plan_files', 'program_source_dir')}
    report = preflight()(db, **selected)
    assert check(report, 'input_stability')['status'] == 'failed'
    assert report['machine_status'] == 'failed'


def cli_args(db, sources=None):
    args = ['--db-copy', str(db)]
    if sources:
        for path in sources['plan_files']:
            args += ['--plan-file', str(path)]
        for key, option in [('program_source_dir', '--program-source-dir'),
                            ('policy_bundle', '--policy-bundle'), ('policy_source_dir', '--policy-source-dir')]:
            args += [option, str(sources[key])]
    return args


@pytest.mark.parametrize('kind', ['pass', 'bad_db', 'missing_arg', 'unknown_arg'])
def test_real_cli_off_cwd_exit_codes_and_private_errors(empty_db, tmp_path, kind):
    db = copy_db(empty_db, tmp_path)
    args = cli_args(db)
    expected = 0
    if kind == 'bad_db':
        db.write_bytes(b'private-bad-db-canary')
        expected = 1
    elif kind == 'missing_arg':
        args = []
        expected = 2
    elif kind == 'unknown_arg':
        args += ['--session-secret=private-argument-canary']
        expected = 2
    before = snapshot(tmp_path)
    run = subprocess.run([sys.executable, '-B', str(SCRIPT), *args], cwd=tmp_path,
        text=True, capture_output=True, timeout=30)
    assert run.returncode == expected and run.stderr == ''
    report = json.loads(run.stdout)
    assert report['release_approved'] is False
    assert 'canary' not in run.stdout and str(tmp_path) not in run.stdout
    assert snapshot(tmp_path) == before


def test_special_characters_in_database_path_are_uri_encoded(empty_db, tmp_path):
    db = copy_db(empty_db, tmp_path)
    target = tmp_path / '副本 ?#&.sqlite3'
    db.rename(target)
    assert preflight()(target)['machine_status'] == 'requested_checks_passed'


@pytest.mark.parametrize('path', ['//private-server-canary/share/copy.sqlite3', '\\\\private-server-canary\\share\\copy.sqlite3'])
def test_unc_inputs_rejected_before_filesystem_access(path, monkeypatch):
    function = preflight()
    calls = []

    def unexpected(self, *args, **kwargs):
        calls.append(True)
        raise AssertionError('unexpected_filesystem_probe')

    monkeypatch.setattr(Path, 'stat', unexpected)
    report = function(Path(path))
    assert check(report, 'database_copy')['code'] == 'nonlocal_input_path'
    assert not calls and 'private-server-canary' not in json.dumps(report)


def test_fresh_process_forbids_env_network_external_commands_and_all_disk_writes(empty_db, tmp_path, sources):
    db = copy_db(empty_db, tmp_path)
    code = '''
import importlib.abc, json, os, pathlib, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'config', 'api', 'app', 'dotenv'}:
            raise RuntimeError('forbidden_config_import')
sys.meta_path.insert(0, Block())
def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'}:
        raise RuntimeError('forbidden_external_action')
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
from scripts.release_preflight import cli
raise SystemExit(cli(sys.argv[2:]))
'''
    before = snapshot(tmp_path)
    run = subprocess.run([sys.executable, '-B', '-c', code, str(ROOT), *cli_args(db, sources)],
        cwd=tmp_path, text=True, capture_output=True, timeout=30)
    assert run.returncode == 0 and run.stderr == ''
    report = json.loads(run.stdout)
    assert all(item['status'] == 'passed' for item in report['checks'])
    assert snapshot(tmp_path) == before and 'canary' not in run.stdout


def test_copy_connection_is_query_only_and_never_gets_ddl_or_dml(empty_db, tmp_path, monkeypatch):
    preflight()
    import scripts.release_preflight as module
    db = copy_db(empty_db, tmp_path)
    connect = sqlite3.connect
    statements, connections = [], []

    def tracked(database, *args, **kwargs):
        conn = connect(database, *args, **kwargs)
        connections.append((database, kwargs))
        if database != ':memory:':
            conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(module.sqlite3, 'connect', tracked)
    assert preflight()(db)['machine_status'] == 'requested_checks_passed'
    assert len(connections) == 2 and connections[1][0] == ':memory:'
    assert '?mode=ro&immutable=1' in connections[0][0] and connections[0][1]['uri'] is True
    assert 'PRAGMA query_only=ON' in statements and 'BEGIN' in statements
    assert all(sql.split()[0].upper() in {'PRAGMA', 'BEGIN', 'SELECT'} for sql in statements)
