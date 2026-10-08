"""Only synthetic temporary databases; exported query rows are private and never ground truth."""

import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import get_args

import pytest

from db.query_log_repository import QueryLogRepository

ROOT = Path(__file__).resolve().parent.parent
QUERY = 'synthetic query student@example.invalid'
REASON = 'synthetic rejection reason canary'
BASE_REVIEWS = ['privacy_review_required', 'results_not_ground_truth', 'no_retrieval_snapshot',
                'missing_request_context']
FIXED_INPUT_ERROR = 'Query log export failed (input/storage); no output published.\n'
# tool: (module, function, its own private directory under data/raw, the other tool's directory)
EXPORTERS = {
    'query_log': ('scripts.export_query_log', 'export_query_log', 'query_log_review', 'feedback_review'),
    'feedback': ('scripts.export_answer_feedback', 'export_feedback', 'feedback_review', 'query_log_review'),
}


def seed(conn, *, marker=None, route='chat', mode='hybrid', query=QUERY, reason=None,
         created='2026-10-01 10:00:00', ids=('c-cs-5800',)):
    log_id = QueryLogRepository(conn).add(
        route=route, query=query, matched_via=mode, k=5, latency_ms=12.5,
        result_course_ids=list(ids), rejection_reason=reason, user_id=marker)
    conn.execute('UPDATE query_log SET created_at=? WHERE log_id=?', (created, log_id))
    conn.commit()
    return log_id


def save_db(empty_db, tmp_path, name='synthetic.sqlite3'):
    path = tmp_path / name
    target = sqlite3.connect(path)
    try:
        empty_db.backup(target)
    finally:
        target.close()
    return path


def exporter():
    from scripts.export_query_log import export_query_log
    return export_query_log


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def run_cli(*args, cwd, script='scripts/export_query_log.py'):
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
    return subprocess.run([sys.executable, str(ROOT / script), *args], cwd=cwd, env=env, capture_output=True, text=True)


def test_default_counts_only_preserves_database_and_writes_nothing(empty_db, tmp_path):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    before = db.read_bytes()
    report = exporter()(db)
    assert report['privacy_mode'] == 'counts' and report['written'] is False
    assert report['selected_row_count'] == 1 and report['exported_row_count'] == 0
    assert report['has_more'] is False and report['temporary_cleanup_incomplete'] is False
    assert report['ground_truth'] is False and report['review_state'] == 'pending'
    assert QUERY not in json.dumps(report)
    assert db.read_bytes() == before and set(tmp_path.iterdir()) == {db}


def test_counts_cover_every_origin_and_add_up_without_echoing_values(empty_db, tmp_path):
    for marker, route, mode in [(None, 'chat', 'hybrid'), (None, 'search', 'alias'),
                                ('eval:fixture-run', 'search', 'rejected'), ('eval:', 'chat', 'program'),
                                ('evaluation-run', 'search', None),
                                ('account-like-canary', 'chat', 'private-mode-canary')]:
        seed(empty_db, marker=marker, route=route, mode=mode)
    db = save_db(empty_db, tmp_path)
    report = exporter()(db, origin='all', limit=1)
    assert report['selected_row_count'] == 6
    assert report['traffic_counts'] == {'unmarked': 2, 'eval': 1, 'unknown': 3}
    assert report['route_counts'] == {'chat': 3, 'search': 3}
    assert report['retrieval_mode_counts'] == {'hybrid': 1, 'alias': 1, 'rejected': 1, 'program': 1, 'unknown': 2}
    text = json.dumps(report)
    for value in ['account-like-canary', 'private-mode-canary', 'fixture-run', QUERY]:
        assert value not in text
    assert exporter()(db)['traffic_counts'] == {'unmarked': 2}
    assert exporter()(db, origin='eval')['traffic_counts'] == {'eval': 1}


def test_metadata_export_has_no_text_marker_or_rejection_reason(empty_db, tmp_path):
    log_id = seed(empty_db, marker='eval:private-run-canary', route='search', mode='rejected', reason=REASON, ids=())
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    report = exporter()(db, out=out, origin='eval')
    assert report['privacy_mode'] == 'metadata' and report['written'] is True
    assert report['exported_row_count'] == 1 and report['has_more'] is False
    [row] = read_rows(out)
    text = out.read_text(encoding='utf-8')
    for secret in [QUERY, REASON, 'private-run-canary', 'user_id', 'rejection_reason']:
        assert secret not in text
    assert row == {
        'format_version': '1', 'log_id': log_id, 'created_at': '2026-10-01T10:00:00Z', 'route': 'search',
        'traffic_kind': 'eval', 'eval_run_sha256': hashlib.sha256(b'eval:private-run-canary').hexdigest(),
        'retrieval_mode': 'rejected', 'k': 5, 'latency_ms': 12.5, 'result_course_ids': [],
        'query_sha256': hashlib.sha256(QUERY.encode()).hexdigest(), 'review_state': 'pending',
        'ground_truth': False, 'review_requirements': BASE_REVIEWS, 'private_text': None,
    }


def test_private_text_needs_both_flags_and_matches_the_metadata_row(empty_db, tmp_path):
    seed(empty_db, reason=REASON)
    db = save_db(empty_db, tmp_path)
    meta, private = tmp_path / 'meta.jsonl', tmp_path / 'private.jsonl'
    exporter()(db, out=meta)
    report = exporter()(db, out=private, include_private_text=True, ack_private_data=True)
    assert report['privacy_mode'] == 'private_text'
    [m], [p] = read_rows(meta), read_rows(private)
    assert p.pop('private_text') == {'query': QUERY, 'rejection_reason': REASON}
    assert m.pop('private_text') is None and m == p


@pytest.mark.parametrize('options', [
    {'include_private_text': True}, {'ack_private_data': True},
    {'include_private_text': True, 'ack_private_data': True},
    {'include_private_text': 1, 'ack_private_data': 1},
])
def test_private_flags_without_output_fail_closed(empty_db, tmp_path, options):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    with pytest.raises(ValueError):
        exporter()(db, **options)
    assert set(tmp_path.iterdir()) == {db}


@pytest.mark.parametrize('options', [
    {'include_private_text': True}, {'ack_private_data': True},
    {'include_private_text': 'yes', 'ack_private_data': 'yes'},
])
def test_private_flags_must_be_paired_booleans(empty_db, tmp_path, options):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'private.jsonl'
    with pytest.raises(ValueError):
        exporter()(db, out=out, **options)
    assert not out.exists()


@pytest.mark.parametrize('route,marker,mode,extra', [
    ('search', None, 'hybrid', ['unverified_traffic_origin']),
    ('chat', None, 'hybrid', ['missing_history_content', 'unverified_traffic_origin']),
    ('chat', 'eval:run', 'context', ['missing_history_content']),
    ('search', 'eval:run', 'odd-mode', ['unknown_retrieval_mode']),
    ('search', 'eval:', 'empty', ['unverified_traffic_origin']),
])
def test_review_requirements_keep_the_gaps_query_log_cannot_fill(empty_db, tmp_path, route, marker, mode, extra):
    seed(empty_db, route=route, marker=marker, mode=mode)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    exporter()(db, out=out, origin='all')
    [row] = read_rows(out)
    assert row['review_requirements'] == BASE_REVIEWS + extra
    assert 'odd-mode' not in out.read_text(encoding='utf-8')


@pytest.mark.parametrize('options', [
    {'limit': 0}, {'limit': 1001}, {'limit': True}, {'limit': '1'},
    {'origin': 'organic'}, {'origin': 'unknown'}, {'since': '2026-02-30'}, {'since': '2026-10-2'},
    {'since': '2026-10-03', 'until': '2026-10-02'},
    {'since': '2026-10-02', 'until': '2026-10-02'}, {'until': 'private-date-canary'}, {'since': 20261001},
])
def test_invalid_selection_is_rejected_without_output(empty_db, tmp_path, options):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    with pytest.raises(ValueError):
        exporter()(db, out=tmp_path / 'review.jsonl', **options)
    assert set(tmp_path.iterdir()) == {db}


def test_window_uses_query_time_inclusive_since_exclusive_until(empty_db, tmp_path):
    seed(empty_db, created='2026-10-01 00:00:00')
    seed(empty_db, created='2026-10-01 23:59:59')
    seed(empty_db, created='2026-10-02 00:00:00')
    db = save_db(empty_db, tmp_path)
    assert exporter()(db, since='2026-10-01', until='2026-10-02')['selected_row_count'] == 2
    assert exporter()(db, until='2026-10-01')['selected_row_count'] == 0
    assert exporter()(db, since='2026-10-02')['selected_row_count'] == 1
    assert exporter()(db)['selected_row_count'] == 3


def test_limit_bounds_the_file_not_the_counts_in_stable_order(empty_db, tmp_path):
    ids = [seed(empty_db) for _ in range(3)]
    seed(empty_db, marker='eval:fixture-run')
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    report = exporter()(db, out=out, limit=2)
    assert report['selected_row_count'] == 3 and report['exported_row_count'] == 2
    assert report['has_more'] is True
    assert [row['log_id'] for row in read_rows(out)] == ids[:2]
    full = exporter()(db, out=tmp_path / 'full.jsonl', limit=3)
    assert full['exported_row_count'] == 3 and full['has_more'] is False
    assert exporter()(db, limit=1)['selected_row_count'] == 3


@pytest.mark.parametrize('column,value', [
    ('created_at', 'bad-private-time-canary'), ('created_at', '2026-10-01T10:00:00'),
    ('created_at', '2026-10-01 9:00:00'), ('created_at', b'binary-time'),
    ('route', 'other'), ('route', b'chat'), ('matched_via', b'binary-mode'), ('user_id', b'binary-marker'),
])
def test_bad_classification_field_fails_counts_and_files(empty_db, tmp_path, column, value):
    seed(empty_db)
    target = seed(empty_db)
    empty_db.execute('PRAGMA ignore_check_constraints=ON')
    empty_db.execute(f'UPDATE query_log SET {column}=? WHERE log_id=?', (value, target))
    empty_db.commit()
    db = save_db(empty_db, tmp_path)
    before = db.read_bytes()
    with pytest.raises(ValueError):
        exporter()(db, origin='all')
    out = tmp_path / 'review.jsonl'
    with pytest.raises(ValueError):
        exporter()(db, out=out, origin='all')
    assert not out.exists() and db.read_bytes() == before


@pytest.mark.parametrize('column,value', [
    ('query', ''), ('query', 'x' * 501), ('query', b'binary-query'),
    ('result_course_ids', None), ('result_course_ids', '{}'), ('result_course_ids', '[1]'),
    ('result_course_ids', '[""]'), ('result_course_ids', 'not-json'),
    ('result_course_ids', '[' + ','.join(['"c"'] * 1001) + ']'), ('result_course_ids', '["' + 'c' * 65536 + '"]'),
    ('k', 0), ('k', 51), ('k', 'five'), ('k', 2.5),
    ('latency_ms', -1.0), ('latency_ms', float('inf')), ('latency_ms', 'slow'),
    ('rejection_reason', ''), ('rejection_reason', 'r' * 1001), ('rejection_reason', b'binary-reason'),
    ('log_id', 0),
])
def test_bad_exported_field_prevents_even_partial_file(empty_db, tmp_path, column, value):
    seed(empty_db)
    target = seed(empty_db)
    empty_db.execute(f'UPDATE query_log SET {column}=? WHERE log_id=?', (value, target))
    empty_db.commit()
    db = save_db(empty_db, tmp_path)
    before = db.read_bytes()
    out = tmp_path / 'review.jsonl'
    with pytest.raises(ValueError):
        exporter()(db, out=out)
    assert not out.exists() and db.read_bytes() == before
    assert exporter()(db)['selected_row_count'] == 2  # Counting never reads these fields.


def test_bounds_accept_the_largest_and_smallest_valid_values(empty_db, tmp_path):
    first = seed(empty_db, query='q' * 500, reason='r' * 1000, ids=[f'c-{n}' for n in range(1000)])
    second = seed(empty_db, query='q', reason=None)
    empty_db.execute('UPDATE query_log SET k=50, latency_ms=0.0 WHERE log_id=?', (first,))
    empty_db.execute('UPDATE query_log SET k=1, latency_ms=NULL, result_course_ids=? WHERE log_id=?',
                     ('["' + 'c' * 65532 + '"]', second))
    empty_db.commit()
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    exporter()(db, out=out, include_private_text=True, ack_private_data=True)
    big, small = read_rows(out)
    assert len(big['result_course_ids']) == 1000 and big['k'] == 50 and big['latency_ms'] == 0.0
    assert big['private_text'] == {'query': 'q' * 500, 'rejection_reason': 'r' * 1000}
    assert small['k'] == 1 and small['latency_ms'] is None and len(small['result_course_ids'][0]) == 65532


def test_file_order_is_log_id_even_when_times_disagree(empty_db, tmp_path):
    later = seed(empty_db, created='2026-10-03 10:00:00')
    earlier = seed(empty_db, created='2026-10-02 10:00:00')
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    exporter()(db, out=out, since='2026-10-02')
    assert [row['log_id'] for row in read_rows(out)] == [later, earlier]


def test_rows_outside_the_selection_or_the_limit_are_not_read_for_export(empty_db, tmp_path):
    first = seed(empty_db)
    seed(empty_db, marker='eval:fixture-run', ids=())
    seed(empty_db, created='2026-09-30 10:00:00')
    seed(empty_db, created='2026-10-02 10:00:00')
    empty_db.execute("UPDATE query_log SET result_course_ids='not-json' WHERE log_id<>?", (first,))
    empty_db.commit()
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    report = exporter()(db, out=out, since='2026-10-01', until='2026-10-02')
    assert report['exported_row_count'] == 1 and [row['log_id'] for row in read_rows(out)] == [first]
    limited = exporter()(db, out=tmp_path / 'limited.jsonl', limit=1)
    assert limited['selected_row_count'] == 3 and limited['has_more'] is True


@pytest.mark.parametrize('kind,error', [
    ('existing', ValueError), ('database', ValueError), ('symlink', ValueError), ('dangling-symlink', ValueError),
    ('hardlink', ValueError), ('missing-parent', FileNotFoundError), ('file-parent', ValueError),
    ('wrong-suffix', ValueError),
])
def test_destination_never_overwrites_creates_parent_or_follows_alias(empty_db, tmp_path, kind, error):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    if kind == 'existing':
        out.write_bytes(b'keep-existing')
    elif kind == 'database':
        out = db
    elif kind == 'symlink':
        out.symlink_to(db)
    elif kind == 'dangling-symlink':
        out.symlink_to(tmp_path / 'link-target.jsonl')
    elif kind == 'hardlink':
        os.link(db, out)
    elif kind == 'missing-parent':
        out = tmp_path / 'not-created' / 'review.jsonl'
    elif kind == 'file-parent':
        out = db / 'review.jsonl'
    else:
        out = tmp_path / 'review.json'
    before = db.read_bytes()
    with pytest.raises(error):
        exporter()(db, out=out)
    assert db.read_bytes() == before
    if kind == 'existing':
        assert out.read_bytes() == b'keep-existing'
    assert not (tmp_path / 'not-created').exists() and not (tmp_path / 'link-target.jsonl').exists()
    assert not list(tmp_path.glob('.query-log-review-*'))


def test_other_repository_paths_are_refused(empty_db, tmp_path):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    out = ROOT / 'docs' / 'never-created-query-log.jsonl'
    with pytest.raises(ValueError):
        exporter()(db, out=out)
    assert not out.exists()


def fake_repository(tmp_path, monkeypatch, tool, root):
    """A repository under tmp_path, with the shared module and the tool pointed at it."""
    import scripts.private_export as shared
    name, function, own_name, other_name = EXPORTERS[tool]
    module = importlib.import_module(name)
    repo = tmp_path / 'repo'
    for directory in (repo / 'data/raw' / own_name, repo / 'data/raw' / other_name, repo / 'eval'):
        directory.mkdir(parents=True)
    spelled = root(repo)
    monkeypatch.setattr(shared, 'ROOT', spelled)
    monkeypatch.setattr(module, 'ROOT', spelled)
    monkeypatch.setattr(module, 'PRIVATE_DIRECTORY', spelled / 'data/raw' / own_name)
    return getattr(module, function), repo, own_name, other_name


@pytest.mark.parametrize('tool', sorted(EXPORTERS))
def test_repository_output_is_allowed_only_in_the_tools_own_private_directory(empty_db, tmp_path, monkeypatch, tool):
    export, repo, own_name, other_name = fake_repository(tmp_path, monkeypatch, tool, lambda repo: repo)
    (tmp_path / 'outside').mkdir()
    (tmp_path / 'alias').symlink_to(repo / 'data/raw', target_is_directory=True)
    (repo / 'data/raw/exit').symlink_to(tmp_path / 'outside', target_is_directory=True)
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    for out in [repo / 'data/raw' / other_name / 'review.jsonl', repo / 'data/raw/review.jsonl',
                repo / 'review.jsonl', repo / 'eval/query_log_export.jsonl',
                tmp_path / 'alias/review.jsonl', repo / 'data/raw/exit/review.jsonl']:
        with pytest.raises(ValueError):
            export(db, out=out)
        assert not out.exists()
    for cwd, relative in [(repo, 'data/raw/exit/relative.jsonl'), (repo / 'data/raw', 'exit/relative.jsonl')]:
        monkeypatch.chdir(cwd)  # Below ROOT the typed relative path has no repository part of its own.
        with pytest.raises(ValueError):
            export(db, out=relative)
    assert not list((tmp_path / 'outside').iterdir())
    assert export(db, out=repo / 'data/raw' / own_name / 'review.jsonl')['written'] is True
    assert export(db, out=tmp_path / 'alias' / own_name / 'second.jsonl')['written'] is True


@pytest.mark.parametrize('tool', sorted(EXPORTERS))
def test_repository_check_uses_file_identity_not_only_the_spelling(empty_db, tmp_path, monkeypatch, tool):
    # On WSL /mnt/<drive> a case variant or a Windows short name of the repository is the same
    # directory spelled differently, and resolve() keeps the spelling. A symlink to the repository
    # used as ROOT gives the same mismatch on any filesystem.
    def other_spelling(repo):
        spelled = tmp_path / 'repo-other-spelling'
        spelled.symlink_to(repo, target_is_directory=True)
        return spelled
    export, repo, own_name, _ = fake_repository(tmp_path, monkeypatch, tool, other_spelling)
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    for out in [repo / 'eval/query_log_export.jsonl', repo / 'review.jsonl']:
        with pytest.raises(ValueError):
            export(db, out=out)
        assert not out.exists()
    assert export(db, out=repo / 'data/raw' / own_name / 'review.jsonl')['written'] is True


def test_missing_database_or_directory_is_not_created_or_read(tmp_path):
    path = tmp_path / 'missing.sqlite3'
    with pytest.raises(OSError):
        exporter()(path)
    assert not path.exists()
    with pytest.raises(ValueError):
        exporter()(tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('change', [
    'DROP TABLE query_log', 'ALTER TABLE query_log DROP COLUMN rejection_reason',
    'CREATE TABLE copied AS SELECT * FROM query_log; DROP TABLE query_log; ALTER TABLE copied RENAME TO query_log',
])
def test_incompatible_schema_is_not_migrated(empty_db, tmp_path, change):
    seed(empty_db)
    empty_db.execute('PRAGMA foreign_keys=OFF')
    empty_db.executescript(change)
    db = save_db(empty_db, tmp_path)
    before = db.read_bytes()
    with pytest.raises(ValueError):
        exporter()(db)
    assert db.read_bytes() == before and set(tmp_path.iterdir()) == {db}


def test_wal_copy_and_an_active_writer_are_read_without_changes(empty_db, tmp_path):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    conn = sqlite3.connect(db)
    assert conn.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
    conn.close()
    before = db.read_bytes()
    assert exporter()(db, origin='all')['selected_row_count'] == 1
    # SQLite may add its -wal/-shm sidecars even for a read-only reader; the database is unchanged.
    assert db.read_bytes() == before
    assert {p.name for p in tmp_path.iterdir()} <= {db.name, f'{db.name}-wal', f'{db.name}-shm'}
    writer = sqlite3.connect(db, isolation_level=None)
    try:
        writer.execute("INSERT INTO query_log(route, query) VALUES ('search', 'committed in the WAL')")
        writer.execute('BEGIN IMMEDIATE')
        writer.execute("INSERT INTO query_log(route, query) VALUES ('search', 'not committed')")
        report = exporter()(db, origin='all')  # The reader neither waits for nor sees the open write.
    finally:
        writer.execute('ROLLBACK')
        writer.close()
    assert report['selected_row_count'] == 2


def test_counting_reads_no_text_and_every_statement_is_read_only(empty_db, tmp_path, monkeypatch):
    seed(empty_db, reason=REASON)
    db = save_db(empty_db, tmp_path)
    import scripts.export_query_log as module
    real_connect = sqlite3.connect
    statements, uris = [], []
    def traced_connect(database_uri, **kwargs):
        uris.append((database_uri, kwargs))
        conn = real_connect(database_uri, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn
    monkeypatch.setattr(sqlite3, 'connect', traced_connect)
    before = db.read_bytes()
    module.export_query_log(db)
    reads = [s for s in statements if 'FROM query_log' in s]
    assert reads == ['SELECT log_id, created_at, route, matched_via, user_id FROM query_log'
                     ' WHERE user_id IS NULL ORDER BY log_id']
    module.export_query_log(db, out=tmp_path / 'review.jsonl', origin='all')
    reads = [s for s in statements if 'FROM query_log' in s]
    assert len(reads) == 3
    assert reads[1] == 'SELECT log_id, created_at, route, matched_via, user_id FROM query_log ORDER BY log_id'
    assert reads[2].startswith('SELECT log_id, created_at, route, query, matched_via, k, latency_ms, '
                               'result_course_ids, rejection_reason, user_id FROM query_log ORDER BY log_id LIMIT ')
    assert db.read_bytes() == before
    assert len(uris) == 2 and all(uri.endswith('?mode=ro') and kwargs['uri'] is True for uri, kwargs in uris)
    assert statements.count('PRAGMA query_only=ON') == 2 and statements.count('BEGIN') == 2
    # SQLite's pragma_index_info virtual table emits commented internal trace entries.
    assert all(s.lstrip().removeprefix('-- ').split()[0].upper() in {'SELECT', 'PRAGMA', 'BEGIN'} for s in statements)
    assert not any('SELECT *' in s for s in statements)


def test_actual_cli_without_pythonpath_reports_only_counts_and_fixed_errors(empty_db, tmp_path):
    seed(empty_db, marker='eval:private-run-canary')
    db = save_db(empty_db, tmp_path)
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
    command = [sys.executable, str(ROOT / 'scripts/export_query_log.py'), '--db-path', str(db), '--origin', 'all']
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['traffic_counts'] == {'eval': 1} and result.stderr == ''
    for secret in [QUERY, 'private-run-canary', str(db)]:
        assert secret not in result.stdout
    failed = subprocess.run(command + ['--out', str(tmp_path / 'private-path-canary.jsonl'), '--include-private-text'],
                            cwd=tmp_path, env=env, capture_output=True, text=True)
    assert failed.returncode == 1 and 'private-path-canary' not in failed.stdout + failed.stderr
    assert failed.stderr == 'Query log export failed (input/storage); no output published.\n'
    assert set(tmp_path.iterdir()) == {db}


@pytest.mark.parametrize('option,value', [
    ('--origin', 'private-origin-canary'), ('--limit', 'private-number-canary'),
    ('--unknown-canary', 'private-option-canary'),
])
def test_cli_argument_failures_never_echo_supplied_values(tmp_path, option, value):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/export_query_log.py'),
        '--db-path', str(tmp_path / 'never-created.sqlite3'), option, value],
        cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2 and value not in result.stdout + result.stderr
    assert result.stderr == 'Query log export failed (arguments); no output published.\n'
    assert not (tmp_path / 'never-created.sqlite3').exists()


def test_private_file_has_owner_only_posix_permissions(empty_db, tmp_path):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    exporter()(db, out=out, include_private_text=True, ack_private_data=True)
    if os.name == 'posix':
        assert out.stat().st_mode & 0o777 == 0o600


def test_export_budget_rejects_before_creating_output(empty_db, tmp_path, monkeypatch):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    import scripts.export_query_log as module
    monkeypatch.setattr(module, 'MAX_EXPORT_BYTES', 1)
    with pytest.raises(ValueError):
        module.export_query_log(db, out=tmp_path / 'review.jsonl')
    assert set(tmp_path.iterdir()) == {db}


def test_fsync_failure_never_publishes_partial_file(empty_db, tmp_path, monkeypatch):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    def fail(descriptor):
        raise OSError('synthetic fsync failure')
    monkeypatch.setattr(os, 'fsync', fail)
    with pytest.raises(OSError):
        exporter()(db, out=tmp_path / 'review.jsonl')
    assert set(tmp_path.iterdir()) == {db}


def test_publication_race_keeps_existing_destination_and_cleans_temp(empty_db, tmp_path, monkeypatch):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    real_link = os.link
    def racing_link(source, destination):
        out.write_bytes(b'race-owner-data')
        return real_link(source, destination)
    monkeypatch.setattr(os, 'link', racing_link)
    with pytest.raises(OSError):
        exporter()(db, out=out)
    assert out.read_bytes() == b'race-owner-data'
    assert set(tmp_path.iterdir()) == {db, out}


def test_post_publish_cleanup_failure_is_reported_without_false_failure(empty_db, tmp_path, monkeypatch):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    real_unlink = Path.unlink
    def failed_cleanup(path, *args, **kwargs):
        if path.name.startswith('.query-log-review-'):
            raise OSError('synthetic cleanup failure')
        return real_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', failed_cleanup)
    report = exporter()(db, out=out)
    assert report['written'] is True and report['temporary_cleanup_incomplete'] is True
    assert read_rows(out)[0]['ground_truth'] is False
    assert len(list(tmp_path.glob('.query-log-review-*.tmp'))) == 1


def test_repeated_export_is_stable_and_never_writes_back(empty_db, tmp_path):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    first, second = tmp_path / 'first.jsonl', tmp_path / 'second.jsonl'
    exporter()(db, out=first)
    exporter()(db, out=second)
    assert first.read_bytes() == second.read_bytes()
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM query_log').fetchone()[0] == 1


@pytest.mark.parametrize('field,value', [
    ('ground_truth', True), ('ground_truth', 0), ('review_state', 'approved'), ('format_version', '2'),
    ('user_id', 'identity-canary'), ('query', 'text-canary'), ('log_id', True), ('route', 'other'),
    ('review_requirements', BASE_REVIEWS), ('eval_run_sha256', 'a' * 64), ('created_at', '2026-10-01 10:00:00'),
    ('created_at', '2026-10-1T10:00:00Z'),
    ('review_requirements', BASE_REVIEWS + ['missing_history_content', 'unverified_traffic_origin', 'no_retrieval_snapshot']),
    ('latency_ms', float('nan')), ('k', '5'),
])
def test_row_schema_rejects_identity_fields_truth_coercion_and_lost_gaps(empty_db, tmp_path, field, value):
    from schemas.query_log_export import QueryLogExportRow
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    exporter()(db, out=out)
    [data] = read_rows(out)
    QueryLogExportRow.model_validate(data)
    with pytest.raises(ValueError):
        QueryLogExportRow.model_validate({**data, field: value})


def test_private_text_cannot_be_transplanted(empty_db, tmp_path):
    from schemas.query_log_export import QueryLogExportRow
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    exporter()(db, out=out, include_private_text=True, ack_private_data=True)
    [data] = read_rows(out)
    QueryLogExportRow.model_validate(data)
    data['private_text']['query'] = 'transplanted-private-canary'
    with pytest.raises(ValueError):
        QueryLogExportRow.model_validate(data)


def test_shared_mode_vocabulary_matches_the_row_schema():
    from schemas.feedback_candidate import RetrievalMode
    from scripts.private_export import RETRIEVAL_MODES
    assert set(get_args(RetrievalMode)) == RETRIEVAL_MODES | {'unknown'}


def test_gitignore_keeps_private_outputs_and_the_old_default_out_of_commits():
    import scripts.export_query_log as module
    assert module.PRIVATE_DIRECTORY == ROOT / 'data/raw/query_log_review'
    lines = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
    assert 'data/raw/' in lines and 'eval/query_log_export.jsonl' in lines
    assert not any(line.startswith('!') and ('data/raw' in line or 'query_log' in line) for line in lines)
    if (ROOT / '.git').exists():
        for path in ['eval/query_log_export.jsonl', 'data/raw/query_log_review/review.jsonl']:
            result = subprocess.run(['git', 'check-ignore', '-q', path], cwd=ROOT)
            assert result.returncode == 0, path


def test_actual_api_rows_keep_route_mode_and_eval_origin(api_client, empty_db, tmp_path):
    from api.dependencies import get_chat_stream_fn
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: lambda prompt: iter(['synthetic answer'])
    assert api_client.post('/search', json={'query': 'CS 5800'}).status_code == 200
    assert api_client.post('/search', json={'query': 'CS 5800'}, headers={'X-Eval-Run': 'synthetic-run'}).status_code == 200
    assert api_client.post('/chat', json={'query': 'CS 5800'}, headers={'X-Eval-Run': 'synthetic-run'}).status_code == 200
    db = save_db(empty_db, tmp_path)
    report = exporter()(db, origin='all')
    assert report['traffic_counts'] == {'unmarked': 1, 'eval': 2}
    assert report['route_counts'] == {'search': 2, 'chat': 1}
    assert 'unknown' not in report['retrieval_mode_counts']
    out = tmp_path / 'review.jsonl'
    exporter()(db, out=out, origin='eval', include_private_text=True, ack_private_data=True)
    rows = read_rows(out)
    assert [(row['route'], row['traffic_kind']) for row in rows] == [('search', 'eval'), ('chat', 'eval')]
    assert all(row['private_text']['query'] == 'CS 5800' for row in rows)
    assert {row['eval_run_sha256'] for row in rows} == {hashlib.sha256(b'eval:synthetic-run').hexdigest()}
    assert empty_db.execute('SELECT COUNT(*) FROM query_log').fetchone()[0] == 3


def test_sql_selection_and_python_classification_agree_on_unusual_markers(empty_db, tmp_path):
    # Upper case and the empty string are not eval or unmarked. A NUL right after "eval:" is
    # eval for both; SQLite's length() would stop counting at the NUL.
    for marker in ['EVAL:case-variant', '', 'eval:\x00after-nul', 'eval:real-run', None]:
        seed(empty_db, marker=marker)
    db = save_db(empty_db, tmp_path)
    assert exporter()(db, origin='all')['traffic_counts'] == {'unknown': 2, 'eval': 2, 'unmarked': 1}
    assert exporter()(db, origin='eval')['traffic_counts'] == {'eval': 2}
    assert exporter()(db, origin='unmarked')['traffic_counts'] == {'unmarked': 1}


@pytest.mark.parametrize('name', ['copy #1.sqlite3', 'copy?mode=rwc.sqlite3', 'copy %41 b.sqlite3'])
def test_database_path_with_uri_characters_opens_that_file_read_only(empty_db, tmp_path, name):
    # Without percent-encoding, "#" or "?" would make SQLite open, and create, another file.
    seed(empty_db)
    folder = tmp_path / 'copies'
    folder.mkdir()
    db = save_db(empty_db, folder, name)
    assert exporter()(db, origin='all')['selected_row_count'] == 1
    assert [path.name for path in folder.iterdir()] == [name]


def test_composite_primary_key_is_refused_and_a_lowercase_integer_key_is_accepted(empty_db, tmp_path):
    seed(empty_db)
    empty_db.execute('PRAGMA foreign_keys=OFF')
    columns = ('created_at TEXT NOT NULL, route TEXT NOT NULL, query TEXT NOT NULL, matched_via TEXT, k INTEGER, '
               'latency_ms REAL, result_course_ids TEXT, rejection_reason TEXT, user_id TEXT')
    copy = ('INSERT INTO q2 SELECT log_id, created_at, route, query, matched_via, k, latency_ms, result_course_ids, '
            'rejection_reason, user_id FROM query_log; DROP TABLE query_log; ALTER TABLE q2 RENAME TO query_log;')
    empty_db.executescript(f'CREATE TABLE q2 (log_id integer primary key autoincrement, {columns}); {copy}')
    assert exporter()(save_db(empty_db, tmp_path, 'lowercase.sqlite3'))['selected_row_count'] == 1
    empty_db.executescript(f'CREATE TABLE q2 (log_id INTEGER, {columns}, PRIMARY KEY (log_id, created_at)); {copy}')
    with pytest.raises(ValueError):
        exporter()(save_db(empty_db, tmp_path, 'composite.sqlite3'))


def test_budgets_count_characters_in_source_json_and_bytes_in_output(empty_db, tmp_path, monkeypatch):
    import scripts.export_query_log as module
    first = seed(empty_db, query='é' * 400)
    empty_db.execute('UPDATE query_log SET result_course_ids=? WHERE log_id=?', ('["' + 'é' * 65532 + '"]', first))
    empty_db.commit()
    db = save_db(empty_db, tmp_path)
    flags = dict(include_private_text=True, ack_private_data=True)
    probe = tmp_path / 'probe.jsonl'
    module.export_query_log(db, out=probe, **flags)
    size = probe.stat().st_size
    assert len(read_rows(probe)[0]['result_course_ids'][0]) == 65532
    assert len(probe.read_text(encoding='utf-8')) < size  # The output budget is in UTF-8 bytes.
    monkeypatch.setattr(module, 'MAX_EXPORT_BYTES', size)
    assert module.export_query_log(db, out=tmp_path / 'exact.jsonl', **flags)['written'] is True
    monkeypatch.setattr(module, 'MAX_EXPORT_BYTES', size - 1)
    with pytest.raises(ValueError):
        module.export_query_log(db, out=tmp_path / 'over.jsonl', **flags)
    assert not (tmp_path / 'over.jsonl').exists()


def test_uppercase_suffix_is_accepted_and_the_query_hash_is_of_the_exact_text(empty_db, tmp_path):
    seed(empty_db, query='  CS 5800  ')
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.JSONL'
    assert exporter()(db, out=out)['written'] is True
    assert read_rows(out)[0]['query_sha256'] == hashlib.sha256('  CS 5800  '.encode()).hexdigest()


def test_counts_and_file_share_one_snapshot_when_a_writer_commits_between_passes(empty_db, tmp_path, monkeypatch):
    import scripts.export_query_log as module
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    setup = sqlite3.connect(db)
    assert setup.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
    setup.close()
    real_open = module.open_read_snapshot

    class WriterBetweenPasses:
        def __init__(self, conn):
            self._conn = conn

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def execute(self, sql, *args):
            if sql.startswith(module.ROW_SQL):
                writer = sqlite3.connect(db)
                writer.execute("INSERT INTO query_log(route, query) VALUES ('search', 'committed between passes')")
                writer.commit()
                writer.close()
            return self._conn.execute(sql, *args)

    monkeypatch.setattr(module, 'open_read_snapshot', lambda path: WriterBetweenPasses(real_open(path)))
    out = tmp_path / 'review.jsonl'
    report = module.export_query_log(db, out=out, origin='all')
    assert report['selected_row_count'] == report['exported_row_count'] == len(read_rows(out)) == 1
    with sqlite3.connect(db) as check:
        assert check.execute('SELECT COUNT(*) FROM query_log').fetchone()[0] == 2


@pytest.mark.parametrize('case', ['raw-eval-marker', 'query-hash', 'nested-extra', 'traffic-kind', 'mode',
                                  'empty-id', 'too-many-ids'])
def test_row_schema_enforces_its_own_formats_and_bounds(empty_db, tmp_path, case):
    from schemas.query_log_export import QueryLogExportRow
    seed(empty_db, marker='eval:run' if case == 'raw-eval-marker' else None)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    # Private text only where it is the subject: its hash check would also reject a bad query hash.
    flags = dict(include_private_text=True, ack_private_data=True) if case == 'nested-extra' else {}
    exporter()(db, out=out, origin='all', **flags)
    [row] = read_rows(out)
    QueryLogExportRow.model_validate(row)
    changes = {'raw-eval-marker': ('eval_run_sha256', 'eval:run'), 'query-hash': ('query_sha256', 'not-a-hash'),
               'traffic-kind': ('traffic_kind', 'organic'), 'mode': ('retrieval_mode', 'odd-mode'),
               'empty-id': ('result_course_ids', ['']), 'too-many-ids': ('result_course_ids', ['c'] * 1001)}
    if case == 'nested-extra':
        row['private_text']['user_id'] = 'identity-canary'
    else:
        field, value = changes[case]
        row[field] = value
    with pytest.raises(ValueError):
        QueryLogExportRow.model_validate(row)


def test_validation_errors_do_not_carry_the_query_text(empty_db, tmp_path):
    from pydantic import ValidationError
    from schemas.query_log_export import PrivateQueryText, QueryLogExportRow
    long_text = 'private-query-canary ' * 30
    with pytest.raises(ValidationError) as direct:
        PrivateQueryText(query=long_text, rejection_reason=None)
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    exporter()(db, out=out, include_private_text=True, ack_private_data=True)
    [row] = read_rows(out)
    with pytest.raises(ValidationError) as top_level:
        QueryLogExportRow.model_validate({**row, 'route': 'private-query-canary'})
    row['private_text']['query'] = long_text
    with pytest.raises(ValidationError) as nested:
        QueryLogExportRow.model_validate(row)
    for error in (direct.value, top_level.value, nested.value):
        assert 'private-query-canary' not in str(error)


@pytest.mark.parametrize('flag', ['--db-path', '--out'])
@pytest.mark.parametrize('script', ['scripts/export_query_log.py', 'scripts/export_answer_feedback.py'])
def test_symlink_loop_fails_with_the_fixed_line_and_no_path(empty_db, tmp_path, flag, script):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    loop = tmp_path / 'loop-path-canary'
    loop.symlink_to(loop)
    args = ['--db-path', str(loop)] if flag == '--db-path' else ['--db-path', str(db), '--out', str(loop / 'review.jsonl')]
    result = run_cli(*args, cwd=tmp_path, script=script)
    assert result.returncode == 1 and result.stdout == ''
    assert result.stderr.endswith(' export failed (input/storage); no output published.\n')
    assert len(result.stderr.splitlines()) == 1 and 'loop-path-canary' not in result.stderr
    with pytest.raises(OSError):
        exporter()(loop)


def test_cli_turns_deeply_nested_source_json_into_the_fixed_line(empty_db, tmp_path):
    # 32768 levels fit the 65536-character budget exactly and raise RecursionError in json.loads.
    log_id = seed(empty_db)
    empty_db.execute('UPDATE query_log SET result_course_ids=? WHERE log_id=?', ('[' * 32768 + ']' * 32768, log_id))
    empty_db.commit()
    db = save_db(empty_db, tmp_path)
    result = run_cli('--db-path', str(db), '--out', str(tmp_path / 'review.jsonl'), cwd=tmp_path)
    assert result.returncode == 1 and result.stderr == FIXED_INPUT_ERROR
    assert not (tmp_path / 'review.jsonl').exists()


def test_cli_defaults_and_a_written_file_never_echo_the_path(empty_db, tmp_path):
    seed(empty_db, marker='eval:run')
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    report = json.loads(run_cli('--db-path', str(db), cwd=tmp_path).stdout)
    assert report['origin'] == 'unmarked' and report['limit'] == 200
    assert report['traffic_counts'] == {'unmarked': 1}
    missing = run_cli(cwd=tmp_path)
    assert missing.returncode == 2
    assert missing.stderr == 'Query log export failed (arguments); no output published.\n'
    out = tmp_path / 'private-path-canary.jsonl'
    written = run_cli('--db-path', str(db), '--out', str(out), cwd=tmp_path)
    assert written.returncode == 0 and json.loads(written.stdout)['written'] is True
    assert 'private-path-canary' not in written.stdout + written.stderr
