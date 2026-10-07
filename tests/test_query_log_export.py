"""Only synthetic temporary databases; exported query rows are private and never ground truth."""

import hashlib
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


def seed(conn, *, marker=None, route='chat', mode='hybrid', query=QUERY, reason=None,
         created='2026-10-01 10:00:00', ids=('c-cs-5800',)):
    log_id = QueryLogRepository(conn).add(
        route=route, query=query, matched_via=mode, k=5, latency_ms=12.5,
        result_course_ids=list(ids), rejection_reason=reason, user_id=marker)
    conn.execute('UPDATE query_log SET created_at=? WHERE log_id=?', (created, log_id))
    conn.commit()
    return log_id


def save_db(empty_db, tmp_path):
    path = tmp_path / 'synthetic.sqlite3'
    with sqlite3.connect(path) as target:
        empty_db.backup(target)
    return path


def exporter():
    from scripts.export_query_log import export_query_log
    return export_query_log


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


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


@pytest.mark.parametrize('relative', ['eval/query_log_export.jsonl', 'docs/never-created-query-log.jsonl'])
def test_old_default_and_other_repository_paths_are_refused(empty_db, tmp_path, relative):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    out = ROOT / relative
    before = out.read_bytes() if out.exists() else None
    with pytest.raises(ValueError):
        exporter()(db, out=out)
    assert (out.read_bytes() if out.exists() else None) == before


def test_repository_output_is_allowed_only_in_its_own_private_directory(empty_db, tmp_path, monkeypatch):
    import scripts.export_query_log as module
    import scripts.private_export as shared
    repo = tmp_path / 'repo'
    own, other = repo / 'data/raw/query_log_review', repo / 'data/raw/feedback_review'
    own.mkdir(parents=True)
    other.mkdir(parents=True)
    (tmp_path / 'outside').mkdir()
    (tmp_path / 'alias').symlink_to(repo / 'data/raw', target_is_directory=True)
    (repo / 'data/raw/exit').symlink_to(tmp_path / 'outside', target_is_directory=True)
    monkeypatch.setattr(shared, 'ROOT', repo)
    monkeypatch.setattr(module, 'PRIVATE_DIRECTORY', own)
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    for out in [other / 'review.jsonl', repo / 'data/raw/review.jsonl', repo / 'review.jsonl',
                tmp_path / 'alias' / 'review.jsonl', repo / 'data/raw/exit/review.jsonl']:
        with pytest.raises(ValueError):
            module.export_query_log(db, out=out)
        assert not out.exists()
    assert module.export_query_log(db, out=own / 'review.jsonl')['written'] is True
    assert module.export_query_log(db, out=tmp_path / 'alias/query_log_review/second.jsonl')['written'] is True


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
