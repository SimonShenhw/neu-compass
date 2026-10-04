"""Joint release rehearsal never targets an existing user database."""

import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'scripts/rehearse_release.py'


def rehearsal():
    if not SCRIPT.exists():
        pytest.fail('release_rehearsal_not_implemented', pytrace=False)
    from scripts.rehearse_release import run_rehearsal
    return run_rehearsal


@pytest.fixture(scope='module')
def successful_report():
    return rehearsal()()


def test_rehearsal_pass_never_grants_release_authority(successful_report):
    report = successful_report
    assert report['machine_status'] == 'rehearsal_checks_passed'
    assert report['synthetic_only'] is True and report['release_approved'] is False
    assert all(item['status'] == 'pending' for item in report['manual_gates'])


def by_name(report, name):
    return next(item for item in report['checks'] if item['name'] == name)


def test_every_required_check_executed_with_no_private_output(successful_report):
    from scripts.rehearse_release import _names
    report = successful_report
    assert [item['name'] for item in report['checks']] == _names()
    assert len(report['checks']) == 22 and all(item['status'] == 'passed' for item in report['checks'])
    text = json.dumps(report)
    for private in ['canary', 'example.invalid', 'sha256', 'feedback_token', 'synthetic-ds-', '/tmp/', 'CREATE TABLE']:
        assert private not in text
    assert report['production_backup_restore_verified'] is False
    assert 'http_operator_shutdown_gate_requires_companion_test' in report['limitations']


@pytest.mark.parametrize('version', ['1.3', '1.4', '1.5', '1.6', '1.7'])
def test_each_layer_has_commit_and_ddl_rollback_evidence(successful_report, version):
    rollback = by_name(successful_report, f'rollback_version_{version}')
    assert rollback['facts']['ddl_and_version_rollback_verified'] is True
    assert rollback['facts']['prior_layers_preserved'] is True
    commit = by_name(successful_report, f'commit_layer_{version}')
    assert commit['facts']['version_committed'] is True and commit['facts']['legacy_state_preserved'] is True
    assert commit['facts']['imported_records'] == (2 if version in ('1.4', '1.5', '1.6') else 0)


@pytest.mark.parametrize('version', ['1.4', '1.5', '1.6'])
def test_partial_write_is_observed_before_batch_rollback(successful_report, version):
    assert by_name(successful_report, f'rollback_partial_store_{version}')['facts'] == {
        'partial_write_observed': True, 'ddl_version_and_rows_rolled_back': True}


def test_postddl_sanity_replay_and_unknown_content_not_upgraded(successful_report):
    assert by_name(successful_report, 'rollback_feedback_postddl')['facts']['postddl_failure_observed'] is True
    content = by_name(successful_report, 'imported_content')['facts']
    assert content['partial_plans'] == 2 and content['unparsed_sections'] == 1
    assert content['or_corequisite_and_unknown_references_preserved'] is True
    repeat = by_name(successful_report, 'repeat_all_layers')['facts']
    assert repeat['layers_replayed'] == 5 and repeat['dml_changes'] == 0
    assert repeat['logical_rows_and_timestamps_unchanged'] is True


@pytest.mark.parametrize('kind', ['early_exception', 'missed_injection', 'legacy_mutation', 'same_value_dml', 'source_mutation'])
def test_bad_rehearsal_never_becomes_green_and_cleans_owned_files(tmp_path, monkeypatch, kind):
    import tempfile
    rehearsal()
    import scripts.rehearse_release as module
    sentinel = tmp_path / 'existing.sqlite3'
    sentinel.write_bytes(b'existing-user-file-canary')
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    if kind == 'early_exception':
        def fail(inputs):
            raise ValueError('private-exception-canary')
        monkeypatch.setattr(module, '_dry_run', fail)
        expected = 'dry_run_preserves_baseline'
    elif kind in ('missed_injection', 'same_value_dml'):
        original = module._apply

        def changed(version, inputs, db, *, commit):
            if kind == 'missed_injection' and version == '1.3' and commit:
                return list(module.TABLES[version])
            result = original(version, inputs, db, commit=commit)
            if kind == 'same_value_dml' and version == '1.3' and commit and result == []:
                conn = sqlite3.connect(db)
                try:
                    conn.execute("UPDATE schema_versions SET notes=notes WHERE version='1.3'")
                    conn.commit()
                finally:
                    conn.close()
            return result

        monkeypatch.setattr(module, '_apply', changed)
        expected = 'rollback_version_1.3' if kind == 'missed_injection' else 'repeat_all_layers'
    elif kind == 'legacy_mutation':
        original = module.sync_sources

        def mutated(db, archive, *, commit=False):
            result = original(db, archive, commit=commit)
            if commit and db.name == 'synthetic.sqlite3':
                conn = sqlite3.connect(db)
                try:
                    conn.execute("UPDATE courses SET search_expansion='private-mutation-canary'")
                    conn.commit()
                finally:
                    conn.close()
            return result

        monkeypatch.setattr(module, 'sync_sources', mutated)
        expected = 'commit_layer_1.4'
    else:
        original = module.sync_plans

        def changed_source(db, file, *, commit=False, source_dir=None):
            result = original(db, file, commit=commit, source_dir=source_dir)
            if commit and db.name == 'synthetic.sqlite3':
                file.write_text(file.read_text(encoding='utf-8') + '\n', encoding='utf-8')
            return result

        monkeypatch.setattr(module, 'sync_plans', changed_source)
        expected = 'source_inputs_unchanged'
    report = module.run_rehearsal()
    assert report['machine_status'] == 'failed' and report['release_approved'] is False
    assert by_name(report, expected)['status'] == 'failed'
    if kind == 'same_value_dml':
        assert by_name(report, expected)['code'] == 'repeat_migration_or_import_performed_dml'
    assert 'canary' not in json.dumps(report)
    assert list(tmp_path.iterdir()) == [sentinel] and sentinel.read_bytes() == b'existing-user-file-canary'


def test_workspace_creation_failure_is_private_and_not_approved(monkeypatch):
    rehearsal()
    import scripts.rehearse_release as module

    def denied(*args, **kwargs):
        raise OSError('private-workspace-canary')

    monkeypatch.setattr(module.tempfile, 'TemporaryDirectory', denied)
    report = module.run_rehearsal()
    assert report['machine_status'] == 'failed' and report['release_approved'] is False
    assert 'private-workspace-canary' not in json.dumps(report)
    assert all(item['status'] == 'not_checked' for item in report['checks'] if item['name'] != 'owned_workspace')


@pytest.mark.parametrize('kind', ['nonempty', 'symlink'])
def test_fixture_builder_refuses_existing_or_linked_workspaces(tmp_path, kind):
    from scripts.release_rehearsal_fixtures import build_inputs
    from scripts.release_preflight import PreflightError
    root = tmp_path
    sentinel = tmp_path / 'existing.sqlite3'
    sentinel.write_bytes(b'untouched-canary')
    if kind == 'symlink':
        root = tmp_path / 'link'
        root.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises((PreflightError, ValueError, OSError)):
        build_inputs(root)
    assert sentinel.read_bytes() == b'untouched-canary'
    assert set(p.name for p in tmp_path.iterdir()) == ({'existing.sqlite3'} if kind == 'nonempty' else {'existing.sqlite3', 'link'})


def test_rehearsal_avoids_tempfile_default_writable_probes(monkeypatch):
    rehearsal()
    import scripts.rehearse_release as module

    def forbidden():
        raise AssertionError('default_tempdir_probe_forbidden')

    monkeypatch.setattr(module.tempfile, 'tempdir', None)
    monkeypatch.setattr(module.tempfile, '_get_default_tempdir', forbidden)
    assert module.run_rehearsal()['machine_status'] == 'rehearsal_checks_passed'


@pytest.mark.parametrize('kind', ['existing', 'dangling_symlink'])
def test_internal_backup_never_overwrites_or_follows_existing_target(tmp_path, kind):
    from scripts.rehearse_release import _backup_new
    from scripts.release_preflight import PreflightError
    source = tmp_path / 'unused-source.sqlite3'
    target = tmp_path / 'target.sqlite3'
    other = tmp_path / 'must-not-be-created.sqlite3'
    if kind == 'existing':
        target.write_bytes(b'private-existing-file-canary')
    else:
        target.symlink_to(other)
    with pytest.raises(PreflightError, match='rollback_copy_already_exists'):
        _backup_new(source, target)
    assert not source.exists() and not other.exists()
    if kind == 'existing':
        assert target.read_bytes() == b'private-existing-file-canary'
    else:
        assert target.is_symlink()


def test_fresh_cli_blocks_config_network_and_writes_outside_owned_temp(tmp_path):
    code = '''
import importlib.abc, json, os, pathlib, sys
from urllib.parse import unquote, urlsplit
roots = []
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'config', 'api', 'app', 'dotenv'}:
            raise RuntimeError('forbidden_configuration_import')
sys.meta_path.insert(0, Block())
def inside(value):
    path = pathlib.Path(os.fsdecode(value)).resolve()
    return any(path == root or root in path.parents for root in roots)
def audit(event, args):
    if event == 'tempfile.mkdtemp':
        path = pathlib.Path(args[0]).absolute()
        if not path.name.startswith('neu-release-rehearsal-'):
            raise RuntimeError('unexpected_temp_workspace')
        roots.append(path)
    if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'}:
        raise RuntimeError('forbidden_external_action')
    if event == 'open':
        path, mode, flags = args
        if isinstance(path, (str, bytes)):
            name = pathlib.Path(os.fsdecode(path)).name.lower()
            if name == '.env' or name.startswith('.env.'):
                raise RuntimeError('forbidden_env_read')
        if (mode and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            if not isinstance(path, (str, bytes)) or not inside(path):
                raise RuntimeError('write_outside_owned_workspace')
    if event == 'sqlite3.connect':
        database = os.fsdecode(args[0])
        if database != ':memory:':
            path = unquote(urlsplit(database).path) if database.startswith('file:') else database
            if not inside(path):
                raise RuntimeError('database_outside_owned_workspace')
sys.addaudithook(audit)
sys.path.insert(0, sys.argv[1])
from scripts.rehearse_release import cli
raise SystemExit(cli([]))
'''
    sentinel = tmp_path / 'outside-owned.sqlite3'
    sentinel.write_bytes(b'private-outside-canary')
    run = subprocess.run([sys.executable, '-B', '-c', code, str(ROOT)], cwd=tmp_path,
        text=True, capture_output=True, timeout=60)
    assert run.returncode == 0 and run.stderr == ''
    report = json.loads(run.stdout)
    assert report['machine_status'] == 'rehearsal_checks_passed' and report['release_approved'] is False
    assert 'canary' not in run.stdout and '/tmp/' not in run.stdout
    assert list(tmp_path.iterdir()) == [sentinel] and sentinel.read_bytes() == b'private-outside-canary'


@pytest.fixture
def migrated_api(tmp_path):
    from fastapi.testclient import TestClient
    from api.dependencies import get_chat_stream_fn
    from db.answer_feedback_repository import AnswerFeedbackRepository
    from schemas.answer_feedback import AnswerFeedbackRequest
    from scripts.rehearse_release import VERSIONS, _apply
    from scripts.release_rehearsal_fixtures import build_inputs
    from tests.conftest import build_test_app

    inputs = build_inputs(tmp_path)
    for version in VERSIONS:
        _apply(version, inputs, inputs.db, commit=True)
    conn = sqlite3.connect(inputs.db, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        repo = AnswerFeedbackRepository(conn)
        target = repo.store_completed(query_log_id=41, answer_text='synthetic-preexisting-answer',
            prompt_version='4.0', request_context={'k': 1, 'history_turn_count': 0})
        repo.vote(AnswerFeedbackRequest(**target.model_dump(), rating='down'))
        conn.commit()
        app = build_test_app(conn, seed=False)
        app.dependency_overrides[get_chat_stream_fn] = lambda: lambda prompt: iter(['synthetic-migrated-answer'])
        with TestClient(app) as client:
            yield client, conn, target
    finally:
        conn.close()


@pytest.mark.parametrize('enabled,permit,captured', [(False, False, False), (False, True, False), (True, False, False), (True, True, True)])
def test_migrated_database_actual_chat_preserves_history_and_obeys_gate(migrated_api, monkeypatch, enabled, permit, captured):
    from config import settings
    if 'answer_feedback_enabled' not in type(settings).model_fields:
        pytest.fail('feedback_setting_missing', pytrace=False)
    client, conn, _ = migrated_api
    monkeypatch.setattr(settings, 'answer_feedback_enabled', enabled)
    logs = list(conn.execute('SELECT * FROM query_log ORDER BY log_id'))
    courses = list(conn.execute('SELECT * FROM courses ORDER BY course_id'))
    response = client.post('/chat', json={'query': 'CS 5800', 'allow_feedback_capture': permit},
        headers={'X-Eval-Run': 'synthetic-migrated-gate-06c3'})
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert ''.join(e['text'] for e in events if e['type'] == 'token') == 'synthetic-migrated-answer'
    assert ('feedback' in events[-1]) is captured
    assert conn.execute('SELECT COUNT(*) FROM chat_answers').fetchone()[0] == 1 + int(captured)
    assert conn.execute('SELECT COUNT(*) FROM answer_feedback').fetchone()[0] == 1
    assert list(conn.execute('SELECT * FROM query_log WHERE log_id<=42 ORDER BY log_id')) == logs
    assert conn.execute('SELECT COUNT(*) FROM query_log').fetchone()[0] == 3
    assert conn.execute('SELECT user_id FROM query_log WHERE log_id>42').fetchone()[0] == 'eval:synthetic-migrated-gate-06c3'
    assert list(conn.execute('SELECT * FROM courses ORDER BY course_id')) == courses


def test_migrated_database_disabled_vote_keeps_existing_receipt_and_reenable(migrated_api, monkeypatch):
    from config import settings
    if 'answer_feedback_enabled' not in type(settings).model_fields:
        pytest.fail('feedback_setting_missing', pytrace=False)
    client, conn, target = migrated_api
    before = list(conn.execute('SELECT * FROM answer_feedback'))
    changes = conn.total_changes
    monkeypatch.setattr(settings, 'answer_feedback_enabled', False)
    denied = client.post('/feedback', json={**target.model_dump(), 'rating': 'up'})
    assert denied.status_code == 503 and denied.headers['cache-control'] == 'no-store'
    assert target.feedback_token not in denied.text and conn.total_changes == changes
    assert list(conn.execute('SELECT * FROM answer_feedback')) == before
    assert conn.execute('SELECT COUNT(*) FROM chat_answers').fetchone()[0] == 1
    monkeypatch.setattr(settings, 'answer_feedback_enabled', True)
    assert client.post('/feedback', json={**target.model_dump(), 'rating': 'up'}).status_code == 200
    assert conn.execute('SELECT rating FROM answer_feedback').fetchone()[0] == 'up'
    assert conn.execute('SELECT COUNT(*) FROM answer_feedback').fetchone()[0] == 1


def test_owned_temporary_files_cleaned_without_touching_existing_files(tmp_path, monkeypatch):
    import tempfile
    sentinel = tmp_path / 'existing-private-canary.sqlite3'
    sentinel.write_bytes(b'unchanged-private-canary')
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    assert rehearsal()()['machine_status'] == 'rehearsal_checks_passed'
    assert list(tmp_path.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b'unchanged-private-canary'


@pytest.mark.parametrize('value', ['--db-path=private-db-canary', '--commit=private-argument-canary'])
def test_cli_rejects_targets_or_commit_options_without_echo(tmp_path, value):
    rehearsal()
    run = subprocess.run([sys.executable, '-B', str(SCRIPT), value], cwd=tmp_path,
        text=True, capture_output=True, timeout=30)
    assert run.returncode == 2 and run.stderr == '' and 'canary' not in run.stdout
    assert json.loads(run.stdout)['release_approved'] is False
    assert not list(tmp_path.iterdir())
