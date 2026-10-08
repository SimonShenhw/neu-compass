"""Only synthetic temporary databases; private candidates are not ground truth."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from db.answer_feedback_repository import AnswerFeedbackRepository
from db.query_log_repository import QueryLogRepository
from schemas.answer_feedback import AnswerFeedbackRequest

ROOT = Path(__file__).resolve().parent.parent
QUERY = 'synthetic query student@example.invalid'
ANSWER = 'synthetic answer private-answer-canary'
CONTEXT = {
    'k': 5, 'term': None, 'credits': None, 'delivery_mode': None,
    'professor': 'private-professor-canary', 'program_id': None,
    'context_course_ids': [], 'history_turn_count': 0,
}


def seed(conn, *, marker=None, rating='down', history=0, context=None):
    log_id = QueryLogRepository(conn).add(
        route='chat', query=QUERY, matched_via='hybrid', k=5, latency_ms=1.0,
        result_course_ids=['c-cs-5800'], user_id=marker)
    receipt = AnswerFeedbackRepository(conn).store_completed(
        query_log_id=log_id, answer_text=ANSWER, prompt_version='4.0',
        request_context=context if context is not None else {**CONTEXT, 'history_turn_count': history})
    if rating is not None:
        AnswerFeedbackRepository(conn).vote(AnswerFeedbackRequest(**receipt.model_dump(), rating=rating))
    conn.execute("UPDATE query_log SET created_at='2026-10-01 10:00:00' WHERE log_id=?", (log_id,))
    conn.execute("UPDATE chat_answers SET created_at='2026-10-01 10:00:01' WHERE answer_id=?", (receipt.answer_id,))
    conn.execute("UPDATE answer_feedback SET created_at='2026-10-01 10:00:02', updated_at='2026-10-02 10:00:00' WHERE answer_id=?", (receipt.answer_id,))
    conn.commit()
    return receipt


def save_db(empty_db, tmp_path):
    path = tmp_path / 'synthetic.sqlite3'
    with sqlite3.connect(path) as target:
        empty_db.backup(target)
    return path


def exporter():
    from scripts.export_answer_feedback import export_feedback
    return export_feedback


def read_one(path):
    lines = path.read_text(encoding='utf-8').splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def test_default_dry_run_counts_only_preserves_database(empty_db, tmp_path):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    before = db.read_bytes()
    report = exporter()(db)
    assert report['candidate_count'] == 1 and report['written'] is False
    assert report['privacy_mode'] == 'metadata' and report['has_more'] is False
    assert report['ground_truth'] is False and report['review_state'] == 'pending'
    assert QUERY not in json.dumps(report) and ANSWER not in json.dumps(report)
    assert db.read_bytes() == before and set(tmp_path.iterdir()) == {db}


def test_metadata_export_never_contains_text_credentials_or_marker(empty_db, tmp_path):
    receipt = seed(empty_db, marker='eval:private-run-canary')
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    exporter()(db, out=out, origin='eval')
    candidate = read_one(out)
    text = out.read_text(encoding='utf-8')
    for secret in [QUERY, ANSWER, CONTEXT['professor'], 'private-run-canary', receipt.feedback_token,
                   hashlib.sha256(receipt.feedback_token.encode()).hexdigest(), 'feedback_token', 'user_id']:
        assert secret not in text
    assert candidate['answer_id'] == receipt.answer_id
    assert candidate['traffic_kind'] == 'eval' and candidate['private_text'] is None
    assert candidate['eval_run_sha256'] == hashlib.sha256(b'eval:private-run-canary').hexdigest()
    assert candidate['review_state'] == 'pending' and candidate['ground_truth'] is False
    assert candidate['result_course_ids'] == ['c-cs-5800']
    assert candidate['feedback_updated_at'] == '2026-10-02T10:00:00Z'


def test_private_text_requires_ack_and_has_same_source_revision(empty_db, tmp_path):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    meta, private = tmp_path / 'meta.jsonl', tmp_path / 'private.jsonl'
    exporter()(db, out=meta)
    exporter()(db, out=private, include_private_text=True, ack_private_data=True)
    m, p = read_one(meta), read_one(private)
    assert m['source_revision'] == p['source_revision']
    assert p['private_text'] == {'query': QUERY, 'answer': ANSWER, 'request_context': CONTEXT}
    assert 'feedback_token' not in private.read_text(encoding='utf-8')


@pytest.mark.parametrize('options', [
    {'include_private_text': True}, {'ack_private_data': True},
    {'include_private_text': True, 'ack_private_data': True},
])
def test_private_flags_without_output_fail_closed(empty_db, tmp_path, options):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    with pytest.raises(ValueError):
        exporter()(db, **options)
    assert set(tmp_path.iterdir()) == {db}


@pytest.mark.parametrize('options', [{'include_private_text': True}, {'ack_private_data': True}])
def test_private_flags_must_be_paired(empty_db, tmp_path, options):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'private.jsonl'
    with pytest.raises(ValueError):
        exporter()(db, out=out, **options)
    assert not out.exists()


@pytest.mark.parametrize('origin,expected', [
    ('unmarked', {'unmarked': 1}), ('eval', {'eval': 1}),
    ('all', {'unmarked': 1, 'eval': 1, 'unknown': 2}),
])
def test_origin_is_exact_original_query_marker(empty_db, tmp_path, origin, expected):
    for marker in [None, 'eval:fixture', 'eval:', 'account-like-canary']:
        seed(empty_db, marker=marker)
    seed(empty_db, rating=None)
    db = save_db(empty_db, tmp_path)
    report = exporter()(db, origin=origin)
    assert report['traffic_counts'] == expected
    assert report['candidate_count'] == sum(expected.values())


@pytest.mark.parametrize('context,history_flag', [({}, True), ({**CONTEXT, 'history_turn_count': 2}, True), (CONTEXT, False)])
def test_context_missing_is_not_zero_and_history_is_not_replayable(empty_db, tmp_path, context, history_flag):
    seed(empty_db, context=context)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    exporter()(db, out=out)
    row = read_one(out)
    assert ('missing_history_content' in row['review_requirements']) == history_flag
    assert 'no_retrieval_snapshot' in row['review_requirements']
    assert 'privacy_review_required' in row['review_requirements']
    assert 'unverified_traffic_origin' in row['review_requirements']
    assert row['history_turn_count'] == context.get('history_turn_count')
    assert row['context_status'] == ('recorded' if context else 'missing')


@pytest.mark.parametrize('options', [
    {'limit': 0}, {'limit': 1001}, {'limit': True}, {'limit': '1'},
    {'origin': 'organic'}, {'since': '2026-02-30'}, {'since': '2026-10-2'},
    {'since': '2026-10-03', 'until': '2026-10-02'},
    {'since': '2026-10-02', 'until': '2026-10-02'}, {'until': 'private-date-canary'},
])
def test_invalid_selection_is_rejected_without_output(empty_db, tmp_path, options):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    with pytest.raises(ValueError):
        exporter()(db, out=tmp_path / 'review.jsonl', **options)
    assert set(tmp_path.iterdir()) == {db}


def test_window_uses_vote_updated_time_inclusive_since_exclusive_until(empty_db, tmp_path):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    assert exporter()(db, since='2026-10-02', until='2026-10-03')['candidate_count'] == 1
    assert exporter()(db, until='2026-10-02')['candidate_count'] == 0
    assert exporter()(db, since='2026-10-03')['candidate_count'] == 0


def test_limit_has_more_and_stable_order_no_unvoted_rows(empty_db, tmp_path):
    targets = [seed(empty_db).answer_id for _ in range(3)]
    seed(empty_db, rating=None)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    report = exporter()(db, out=out, limit=2)
    assert report['candidate_count'] == 2 and report['has_more'] is True
    assert [json.loads(line)['answer_id'] for line in out.read_text().splitlines()] == sorted(targets)[:2]
    assert exporter()(db, limit=3)['has_more'] is False


@pytest.mark.parametrize('column,value', [
    ('a.answer_text', 'tampered-private-canary'), ('a.answer_sha256', 'z' * 64),
    ('a.request_context', '{"feedback_token":"private-credential-canary"}'),
    ('a.request_context', '[]'), ('a.request_context', '{"history_turn_count":true}'),
    ('a.request_context', '{"history_turn_count":13}'),
    ('a.request_context', '{"context_course_ids":[1]}'),
    ('a.request_context', '{"program_id":""}'),
    ('a.created_at', 'bad-private-time-canary'),
    ('q.result_course_ids', '{}'), ('q.result_course_ids', '[1]'), ('q.result_course_ids', '[""]'),
    ('q.result_course_ids', '[' + ','.join(['"c"'] * 1001) + ']'),
    ('q.route', 'search'), ('q.query', 'x' * 501),
])
def test_bad_selected_row_prevents_even_partial_file(empty_db, tmp_path, column, value):
    seed(empty_db)
    target = seed(empty_db)
    table, field = column.split('.')
    name = {'a': 'chat_answers', 'q': 'query_log'}[table]
    if table == 'a':
        empty_db.execute(f'UPDATE {name} SET {field}=? WHERE answer_id=?', (value, target.answer_id))
    else:
        empty_db.execute(f'UPDATE {name} SET {field}=? WHERE log_id=(SELECT query_log_id FROM chat_answers WHERE answer_id=?)', (value, target.answer_id))
    empty_db.commit()
    db = save_db(empty_db, tmp_path)
    before = db.read_bytes()
    out = tmp_path / 'review.jsonl'
    with pytest.raises(ValueError):
        exporter()(db, out=out)
    assert not out.exists() and db.read_bytes() == before


def test_orphan_feedback_is_not_silently_omitted(empty_db, tmp_path):
    target = seed(empty_db)
    empty_db.execute('PRAGMA foreign_keys=OFF')
    empty_db.execute('DELETE FROM chat_answers WHERE answer_id=?', (target.answer_id,))
    empty_db.commit()
    db = save_db(empty_db, tmp_path)
    with pytest.raises(ValueError):
        exporter()(db, out=tmp_path / 'review.jsonl', origin='all')


def test_existing_vote_survives_receipt_expiry_for_review(empty_db, tmp_path):
    seed(empty_db)
    empty_db.execute('UPDATE chat_answers SET expires_at=0')
    empty_db.commit()
    db = save_db(empty_db, tmp_path)
    assert exporter()(db)['candidate_count'] == 1


def test_unknown_retrieval_mode_is_a_flag_not_raw_export(empty_db, tmp_path):
    seed(empty_db)
    empty_db.execute("UPDATE query_log SET matched_via='private-mode-canary'")
    empty_db.commit()
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    exporter()(db, out=out)
    row = read_one(out)
    assert row['retrieval_mode'] == 'unknown'
    assert 'unknown_retrieval_mode' in row['review_requirements']
    assert 'private-mode-canary' not in out.read_text()


@pytest.mark.parametrize('kind', ['existing', 'database', 'symlink', 'hardlink', 'missing-parent', 'wrong-suffix'])
def test_destination_never_overwrites_creates_parent_or_follows_alias(empty_db, tmp_path, kind):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    if kind == 'existing':
        out.write_bytes(b'keep-existing')
    elif kind == 'database':
        out = db
    elif kind == 'symlink':
        out.symlink_to(db)
    elif kind == 'hardlink':
        os.link(db, out)
    elif kind == 'missing-parent':
        out = tmp_path / 'not-created' / 'review.jsonl'
    else:
        out = tmp_path / 'review.md'
    before = db.read_bytes()
    with pytest.raises((OSError, ValueError)):
        exporter()(db, out=out)
    assert db.read_bytes() == before
    if kind == 'existing':
        assert out.read_bytes() == b'keep-existing'
    assert not (tmp_path / 'not-created').exists()


def test_repository_output_must_be_in_private_ignored_subdirectory(empty_db, tmp_path):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    out = ROOT / 'docs' / 'never-created-feedback-candidates.jsonl'
    with pytest.raises(ValueError):
        exporter()(db, out=out)
    assert not out.exists()


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / 'missing.sqlite3'
    with pytest.raises(OSError):
        exporter()(path)
    assert not path.exists()


def test_legacy_schema_is_not_migrated(empty_db, tmp_path):
    empty_db.execute('DROP TABLE answer_feedback')
    empty_db.execute('DROP TABLE chat_answers')
    empty_db.commit()
    db = save_db(empty_db, tmp_path)
    before = db.read_bytes()
    with pytest.raises(ValueError):
        exporter()(db)
    assert db.read_bytes() == before


def test_actual_cli_without_pythonpath_reports_only_counts_and_fixed_errors(empty_db, tmp_path):
    target = seed(empty_db)
    db = save_db(empty_db, tmp_path)
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
    command = [sys.executable, str(ROOT / 'scripts/export_answer_feedback.py'), '--db-path', str(db)]
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['candidate_count'] == 1 and result.stderr == ''
    for secret in [QUERY, ANSWER, target.answer_id, target.feedback_token]:
        assert secret not in result.stdout
    failed = subprocess.run(command + ['--since', 'private-invalid-date-canary'], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert failed.returncode != 0 and 'private-invalid-date-canary' not in failed.stdout + failed.stderr


def test_private_file_has_owner_only_posix_permissions(empty_db, tmp_path):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    exporter()(db, out=out)
    if os.name == 'posix':
        assert out.stat().st_mode & 0o777 == 0o600


def test_connection_uri_and_trace_are_read_only_and_select_no_credentials(empty_db, tmp_path, monkeypatch):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    import scripts.export_answer_feedback as module
    real_connect = sqlite3.connect
    statements, uris = [], []
    def traced_connect(database_uri, **kwargs):
        uris.append((database_uri, kwargs))
        conn = real_connect(database_uri, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn
    monkeypatch.setattr(module.sqlite3, 'connect', traced_connect)
    before = db.read_bytes()
    module.export_feedback(db, out=tmp_path / 'review.jsonl')
    assert db.read_bytes() == before
    assert len(uris) == 1 and uris[0][0].endswith('?mode=ro') and uris[0][1]['uri'] is True
    assert 'PRAGMA query_only=ON' in statements
    # SQLite's pragma_index_info virtual table emits a commented internal
    # "-- PRAGMA index_info=..." trace entry as well as the caller's SELECT.
    assert all(s.lstrip().removeprefix('-- ').split()[0].upper() in {'SELECT', 'PRAGMA', 'BEGIN'} for s in statements)
    content_sql = '\n'.join(s for s in statements if 'FROM answer_feedback f' in s)
    assert 'feedback_token' not in content_sql and 'expires_at' not in content_sql and 'SELECT *' not in content_sql


def test_invalid_json_duplicates_are_not_silently_replaced(empty_db, tmp_path):
    seed(empty_db)
    empty_db.execute('UPDATE chat_answers SET request_context=?', ('{"history_turn_count":1,"history_turn_count":0}',))
    empty_db.commit()
    db = save_db(empty_db, tmp_path)
    with pytest.raises(ValueError):
        exporter()(db, out=tmp_path / 'review.jsonl')
    assert set(tmp_path.iterdir()) == {db}


def test_export_budget_rejects_before_creating_output(empty_db, tmp_path, monkeypatch):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    import scripts.export_answer_feedback as module
    monkeypatch.setattr(module, 'MAX_EXPORT_BYTES', 1)
    with pytest.raises(ValueError):
        module.export_feedback(db, out=tmp_path / 'review.jsonl')
    assert set(tmp_path.iterdir()) == {db}


def test_fsync_failure_never_publishes_partial_file(empty_db, tmp_path, monkeypatch):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    import scripts.export_answer_feedback as module
    def fail(descriptor):
        raise OSError('synthetic fsync failure')
    monkeypatch.setattr(os, 'fsync', fail)
    with pytest.raises(OSError):
        module.export_feedback(db, out=tmp_path / 'review.jsonl')
    assert set(tmp_path.iterdir()) == {db}


def test_publication_race_keeps_existing_destination_and_cleans_temp(empty_db, tmp_path, monkeypatch):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    import scripts.export_answer_feedback as module
    real_link = os.link
    def racing_link(source, destination):
        out.write_bytes(b'race-owner-data')
        return real_link(source, destination)
    monkeypatch.setattr(os, 'link', racing_link)
    with pytest.raises(OSError):
        module.export_feedback(db, out=out)
    assert out.read_bytes() == b'race-owner-data'
    assert set(tmp_path.iterdir()) == {db, out}


def test_post_publish_cleanup_failure_is_reported_without_false_failure(empty_db, tmp_path, monkeypatch):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    import scripts.export_answer_feedback as module
    real_unlink = Path.unlink
    def failed_cleanup(path, *args, **kwargs):
        if path.name.startswith('.feedback-review-'):
            raise OSError('synthetic cleanup failure')
        return real_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', failed_cleanup)
    report = module.export_feedback(db, out=out)
    assert report['written'] is True and report['temporary_cleanup_incomplete'] is True
    assert read_one(out)['ground_truth'] is False
    assert len(list(tmp_path.glob('.feedback-review-*.tmp'))) == 1


@pytest.mark.parametrize('field,value', [
    ('rating', 'up'), ('prompt_version', 'next'), ('source_marker', 'account-other-canary'),
    ('request_context', json.dumps({**CONTEXT, 'history_turn_count': 1})),
])
def test_source_revision_changes_when_review_relevant_source_changes(empty_db, tmp_path, field, value):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    first, second = tmp_path / 'first.jsonl', tmp_path / 'second.jsonl'
    exporter()(db, out=first, origin='all')
    with sqlite3.connect(db) as conn:
        table = 'answer_feedback' if field == 'rating' else 'query_log' if field == 'source_marker' else 'chat_answers'
        column = 'user_id' if field == 'source_marker' else field
        conn.execute(f'UPDATE {table} SET {column}=?', (value,))
    exporter()(db, out=second, origin='all')
    assert read_one(first)['source_revision'] != read_one(second)['source_revision']


def test_repeated_export_is_stable_and_output_never_imports_back(empty_db, tmp_path):
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    first, second = tmp_path / 'first.jsonl', tmp_path / 'second.jsonl'
    exporter()(db, out=first)
    exporter()(db, out=second)
    assert first.read_bytes() == second.read_bytes()
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM answer_feedback').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM query_log').fetchone()[0] == 1


@pytest.mark.parametrize('field,value', [
    ('ground_truth', True), ('ground_truth', 0), ('review_state', 'approved'),
    ('feedback_token', 'credential-canary'), ('user_id', 'identity-canary'),
    ('query_log_id', True), ('rating', True), ('format_version', '2'),
    ('review_requirements', []), ('eval_run_sha256', 'a' * 64),
])
def test_candidate_schema_rejects_credential_fields_truth_coercion_and_lost_gaps(empty_db, tmp_path, field, value):
    from schemas.feedback_candidate import FeedbackCandidate
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    exporter()(db, out=out)
    data = read_one(out)
    with pytest.raises(ValueError):
        FeedbackCandidate.model_validate({**data, field: value})


@pytest.mark.parametrize('change', ['query', 'answer', 'request_context', 'history_turn_count', 'context_course_count'])
def test_private_text_and_context_counters_cannot_be_transplanted(empty_db, tmp_path, change):
    from schemas.feedback_candidate import FeedbackCandidate
    seed(empty_db)
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    exporter()(db, out=out, include_private_text=True, ack_private_data=True)
    data = read_one(out)
    if change in ('query', 'answer'):
        data['private_text'][change] = 'transplanted-private-canary'
    elif change == 'request_context':
        data['private_text'][change]['professor'] = 'changed'
    else:
        data[change] = 1
    with pytest.raises(ValueError):
        FeedbackCandidate.model_validate(data)


@pytest.mark.parametrize('option,value', [('--origin', 'private-origin-canary'), ('--limit', 'private-number-canary'), ('--unknown-canary', 'private-option-canary')])
def test_cli_argument_failures_never_echo_supplied_values(tmp_path, option, value):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/export_answer_feedback.py'),
        '--db-path', str(tmp_path / 'never-created.sqlite3'), option, value],
        cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2 and value not in result.stdout + result.stderr
    assert not (tmp_path / 'never-created.sqlite3').exists()


def test_actual_api_completed_answer_and_vote_export_preserve_eval_origin(api_client, empty_db, tmp_path, monkeypatch):
    from api.dependencies import get_chat_stream_fn
    from config import settings
    # Enable only this explicit opt-in integration fixture, never the suite.
    monkeypatch.setattr(settings, 'answer_feedback_enabled', True)
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: lambda prompt: iter([ANSWER])
    response = api_client.post('/chat', json={'query': 'CS 5800', 'allow_feedback_capture': True}, headers={'X-Eval-Run': 'synthetic-export-roundtrip'})
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    target = events[-1]['feedback']
    assert api_client.post('/feedback', json={**target, 'rating': 'up'}).status_code == 200
    db = save_db(empty_db, tmp_path)
    out = tmp_path / 'review.jsonl'
    assert exporter()(db)['candidate_count'] == 0
    exporter()(db, out=out, origin='eval', include_private_text=True, ack_private_data=True)
    row = read_one(out)
    assert row['answer_id'] == target['answer_id'] and row['traffic_kind'] == 'eval'
    assert row['private_text']['answer'] == ANSWER and row['private_text']['query'] == 'CS 5800'
    assert row['context_status'] == 'recorded' and row['history_turn_count'] == 0
    assert row['ground_truth'] is False and target['feedback_token'] not in out.read_text()
    assert empty_db.execute('SELECT COUNT(*) FROM query_log').fetchone()[0] == 1


@pytest.mark.parametrize('column,value', [('user_id', b'invalid-marker'), ('matched_via', b'invalid-mode')])
def test_binary_source_fields_fail_closed_instead_of_losing_provenance(empty_db, tmp_path, column, value):
    seed(empty_db)
    empty_db.execute(f'UPDATE query_log SET {column}=?', (value,))
    empty_db.commit()
    db = save_db(empty_db, tmp_path)
    with pytest.raises(ValueError):
        exporter()(db, origin='all', out=tmp_path / 'review.jsonl')
    assert set(tmp_path.iterdir()) == {db}


def test_original_query_identity_requires_real_integer_primary_key(empty_db, tmp_path):
    seed(empty_db)
    empty_db.execute('PRAGMA foreign_keys=OFF')
    empty_db.execute('CREATE TABLE saved_query_log AS SELECT * FROM query_log')
    empty_db.execute('DROP TABLE query_log')
    empty_db.execute('ALTER TABLE saved_query_log RENAME TO query_log')
    empty_db.commit()
    db = save_db(empty_db, tmp_path)
    before = db.read_bytes()
    with pytest.raises(ValueError):
        exporter()(db, out=tmp_path / 'review.jsonl')
    assert db.read_bytes() == before and set(tmp_path.iterdir()) == {db}
