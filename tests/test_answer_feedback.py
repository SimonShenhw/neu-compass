"""Feedback belongs to an actual completed answer, not a caller-chosen log row."""

import hashlib
import json
import sqlite3

import pytest

from api.dependencies import get_chat_stream_fn
from db.query_log_repository import QueryLogRepository
from llm.gemini_client import GeminiError


@pytest.fixture(autouse=True)
def enable_feedback_for_this_test_module(monkeypatch):
    # The production default stays OFF; these existing cases exercise opt-in.
    from config import settings
    monkeypatch.setattr(settings, 'answer_feedback_enabled', True)


def chat(client, chunks=('回答 ', 'CS 5800'), *, headers=None, **extra):
    client.app.dependency_overrides[get_chat_stream_fn] = lambda: lambda prompt: iter(chunks)
    response = client.post('/chat', json={'query': 'CS 5800', 'allow_feedback_capture': True, **extra}, headers=headers or {})
    assert response.status_code == 200
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def receipt(client, **kwargs):
    events = chat(client, **kwargs)
    assert events[-1]['type'] == 'done'
    return events[-1]['feedback']


def test_completed_answer_is_bound_to_the_exact_committed_query(api_client, empty_db):
    from llm.prompts.chat_v4 import PROMPT_VERSION
    from db.program_repository import ProgramRepository
    from schemas.program import Program
    ProgramRepository(empty_db).upsert_program(Program(program_id='cs-ms',prefix='CS',full_name='Synthetic CS'))
    empty_db.commit()
    events = chat(api_client, program_id='cs-ms', history=[{'role':'user','content':'private-history'}])
    target = events[-1]['feedback']
    text = ''.join(e['text'] for e in events if e['type'] == 'token')
    row = empty_db.execute('SELECT a.*, q.query, q.route FROM chat_answers a JOIN query_log q ON q.log_id=a.query_log_id').fetchone()
    assert row['answer_text'] == text and row['query'] == 'CS 5800' and row['route'] == 'chat'
    assert row['answer_sha256'] == target['answer_sha256'] == hashlib.sha256(text.encode()).hexdigest()
    assert row['prompt_version'] == PROMPT_VERSION and row['answer_id'] == target['answer_id']
    assert target['feedback_token'] not in str(dict(row))
    assert row['feedback_token_hash'] == hashlib.sha256(target['feedback_token'].encode()).hexdigest()
    context = json.loads(row['request_context'])
    assert context['program_id'] == 'cs-ms' and context['history_turn_count'] == 1
    assert 'private-history' not in row['request_context']
    assert set(target) == {'answer_id','answer_sha256','feedback_token'}


def test_vote_retry_and_correction_are_one_row_not_extra_queries(api_client, empty_db):
    target = receipt(api_client)
    for rating in ['up','up','down','down']:
        response = api_client.post('/feedback', json={**target,'rating':rating})
        assert response.status_code == 200 and response.json() == {'answer_id':target['answer_id'],'rating':rating}
        assert response.headers['cache-control'] == 'no-store'
    assert empty_db.execute('SELECT COUNT(*) FROM answer_feedback').fetchone()[0] == 1
    assert empty_db.execute('SELECT rating FROM answer_feedback').fetchone()[0] == 'down'
    assert QueryLogRepository(empty_db).count() == 1


@pytest.mark.parametrize('field,value', [('answer_id','0'*32),('feedback_token','x'*43),('answer_sha256','0'*64)])
def test_unknown_or_wrong_receipt_is_indistinguishable_and_does_not_write(api_client, empty_db, field, value):
    target = receipt(api_client); target[field] = value
    before = empty_db.total_changes
    response = api_client.post('/feedback',json={**target,'rating':'up'})
    assert response.status_code == 404 and 'feedback_token' not in response.text
    assert empty_db.total_changes == before


def test_receipt_cannot_be_transferred_to_another_answer(api_client, empty_db):
    first, second = receipt(api_client), receipt(api_client, chunks=('different',))
    assert first['answer_id'] != second['answer_id']
    response = api_client.post('/feedback',json={**second,'feedback_token':first['feedback_token'],'rating':'down'})
    assert response.status_code == 404 and not empty_db.execute('SELECT * FROM answer_feedback').fetchall()


def test_eval_origin_is_derived_from_original_query_not_feedback_headers(api_client, empty_db):
    target = receipt(api_client, headers={'X-Eval-Run':'synthetic-06b'})
    response = api_client.post('/feedback',json={**target,'rating':'up'})
    assert response.status_code == 200
    row = empty_db.execute('SELECT q.user_id FROM answer_feedback f JOIN chat_answers a USING(answer_id) JOIN query_log q ON q.log_id=a.query_log_id').fetchone()
    assert row['user_id'] == 'eval:synthetic-06b' and QueryLogRepository(empty_db).count() == 1


@pytest.mark.parametrize('chunks', [(), ('',), ('  ',), ('x'*64001,)])
def test_empty_or_oversized_answer_finishes_without_feedback(api_client, empty_db, chunks):
    events = chat(api_client, chunks)
    assert events[-1] == {'type':'done'}
    assert empty_db.execute('SELECT COUNT(*) FROM chat_answers').fetchone()[0] == 0


@pytest.mark.parametrize('error', [GeminiError('synthetic failure'), RuntimeError('synthetic failure')])
def test_partial_generation_failure_never_creates_a_votable_answer(api_client, empty_db, error):
    def fail(prompt):
        yield 'partial'
        raise error
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: fail
    response = api_client.post('/chat',json={'query':'CS 5800','allow_feedback_capture':True})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert any(e['type']=='error' for e in events) and events[-1] == {'type':'done'}
    assert not empty_db.execute('SELECT * FROM chat_answers').fetchall()


def test_query_log_failure_keeps_chat_but_has_no_guessable_feedback(api_client, empty_db, monkeypatch):
    def fail(self, **kwargs):
        raise sqlite3.OperationalError('synthetic telemetry failure')
    monkeypatch.setattr(QueryLogRepository,'add',fail)
    assert chat(api_client)[-1] == {'type':'done'}
    assert not empty_db.execute('SELECT * FROM chat_answers').fetchall()


def test_legacy_database_does_not_auto_migrate(api_client, empty_db):
    empty_db.execute('DROP TABLE answer_feedback'); empty_db.execute('DROP TABLE chat_answers'); empty_db.commit()
    assert chat(api_client)[-1] == {'type':'done'}
    response = api_client.post('/feedback',json={'answer_id':'a'*32,'answer_sha256':'a'*64,'feedback_token':'a'*43,'rating':'up'})
    assert response.status_code == 503
    tables = {r[0] for r in empty_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'chat_answers' not in tables and 'answer_feedback' not in tables


@pytest.mark.parametrize('field,value', [
    ('rating','neutral'),('rating',True),('rating',1),('answer_id','../query'),
    ('answer_id','A'*32),('answer_sha256','A'*64),('feedback_token',' '),
    ('feedback_token','x'*44),('feedback_token',123),('user_id','forged'),
    ('log_id',1),('query','forged'),('comment','private text'),('traffic_type','organic')])
def test_strict_feedback_body_has_no_free_text_or_client_chosen_origin(api_client, empty_db, field, value):
    target = receipt(api_client)
    before = empty_db.total_changes
    response = api_client.post('/feedback',json={**target,'rating':'up',field:value})
    assert response.status_code == 422 and empty_db.total_changes == before
    assert target['feedback_token'] not in response.text and 'private text' not in response.text


@pytest.mark.parametrize('field', ['answer_id','answer_sha256','feedback_token','rating'])
def test_each_feedback_field_is_required(api_client, empty_db, field):
    data = {**receipt(api_client),'rating':'up'}; data.pop(field)
    assert api_client.post('/feedback',json=data).status_code == 422


def test_expired_receipt_and_corrupt_answer_fail_closed(api_client, empty_db):
    target = receipt(api_client)
    empty_db.execute('UPDATE chat_answers SET expires_at=0'); empty_db.commit()
    assert api_client.post('/feedback',json={**target,'rating':'up'}).status_code == 404
    empty_db.execute("UPDATE chat_answers SET expires_at=9999999999,answer_text='corrupted'"); empty_db.commit()
    assert api_client.post('/feedback',json={**target,'rating':'up'}).status_code == 404
    assert not empty_db.execute('SELECT * FROM answer_feedback').fetchall()


def test_identical_retry_does_not_even_change_the_saved_timestamp(api_client, empty_db):
    target = receipt(api_client)
    api_client.post('/feedback',json={**target,'rating':'up'})
    empty_db.execute("UPDATE answer_feedback SET updated_at='test-marker'"); empty_db.commit()
    assert api_client.post('/feedback',json={**target,'rating':'up'}).status_code == 200
    assert empty_db.execute('SELECT updated_at FROM answer_feedback').fetchone()[0] == 'test-marker'
    assert api_client.post('/feedback',json={**target,'rating':'down'}).status_code == 200
    assert empty_db.execute('SELECT updated_at FROM answer_feedback').fetchone()[0] != 'test-marker'


def test_retention_delete_cascades_without_orphan_labels(api_client, empty_db):
    target = receipt(api_client)
    api_client.post('/feedback',json={**target,'rating':'up'})
    empty_db.execute('DELETE FROM query_log'); empty_db.commit()
    assert not empty_db.execute('SELECT * FROM chat_answers').fetchall()
    assert not empty_db.execute('SELECT * FROM answer_feedback').fetchall()
    assert api_client.post('/feedback',json={**target,'rating':'up'}).status_code == 404


def test_capture_failure_rolls_back_only_the_new_answer_and_keeps_chat(api_client, empty_db, monkeypatch):
    from db.answer_feedback_repository import AnswerFeedbackRepository
    original = AnswerFeedbackRepository.store_completed
    def fail(self, **kwargs):
        original(self, **kwargs)
        raise sqlite3.OperationalError('secret capture error')
    monkeypatch.setattr(AnswerFeedbackRepository,'store_completed',fail)
    events = chat(api_client)
    assert events[-1] == {'type':'done'} and not any(e['type']=='error' for e in events)
    assert not empty_db.execute('SELECT * FROM chat_answers').fetchall()
    assert QueryLogRepository(empty_db).count() == 1


def test_failed_vote_commit_never_claims_success(api_client, empty_db, monkeypatch):
    from db.answer_feedback_repository import AnswerFeedbackRepository
    target = receipt(api_client)
    original = AnswerFeedbackRepository.vote
    def fail(self, request):
        original(self,request)
        raise sqlite3.OperationalError('private storage detail')
    monkeypatch.setattr(AnswerFeedbackRepository,'vote',fail)
    response = api_client.post('/feedback',json={**target,'rating':'up'})
    assert response.status_code == 503 and 'private storage detail' not in response.text
    assert not empty_db.execute('SELECT * FROM answer_feedback').fetchall()


def test_repository_rejects_search_and_duplicate_query_ids(empty_db):
    from db.answer_feedback_repository import AnswerFeedbackRepository
    repo = AnswerFeedbackRepository(empty_db)
    def save(log_id):
        return repo.store_completed(query_log_id=log_id,answer_text='synthetic',prompt_version='test',request_context={})
    query_repo = QueryLogRepository(empty_db)
    search_id = query_repo.add(route='search',query='test',matched_via='alias',k=1,latency_ms=1)
    with pytest.raises(ValueError): save(search_id)
    log_id = query_repo.add(route='chat',query='test',matched_via='alias',k=1,latency_ms=1)
    first = save(log_id)
    with pytest.raises(sqlite3.IntegrityError): save(log_id)
    assert repo.schema_available() and len(first.feedback_token) == 43


def test_sql_feedback_foreign_key_and_rating_constraints(empty_db):
    with pytest.raises(sqlite3.IntegrityError):
        empty_db.execute("INSERT INTO answer_feedback(answer_id,rating) VALUES (?,'up')",('a'*32,))
    with pytest.raises(sqlite3.IntegrityError):
        empty_db.execute("INSERT INTO answer_feedback(answer_id,rating) VALUES (NULL,'up')")


def test_stream_request_connection_lives_through_answer_commit(tmp_path):
    from fastapi.testclient import TestClient
    from api.dependencies import get_db_conn
    from db.connection import connect
    from tests.conftest import INIT_SQL_PATH, build_test_app
    path = tmp_path / 'stream.sqlite3'
    conn = connect(path); conn.executescript(INIT_SQL_PATH.read_text())
    app = build_test_app(conn); conn.close()
    lifecycle = []
    def connection():
        current = connect(path)
        lifecycle.append('open')
        try: yield current
        finally:
            lifecycle.append('close'); current.close()
    app.dependency_overrides[get_db_conn] = connection
    with TestClient(app) as client:
        target = receipt(client, headers={'X-Eval-Run':'connection-test'})
        assert lifecycle == ['open','close']
        assert client.post('/feedback',json={**target,'rating':'up'}).status_code == 200
    check = connect(path)
    try: assert check.execute('SELECT COUNT(*) FROM answer_feedback').fetchone()[0] == 1
    finally: check.close()


def legacy_copy(tmp_path):
    from tests.conftest import INIT_SQL_PATH
    path = tmp_path / 'legacy copy.sqlite3'
    conn = sqlite3.connect(path)
    sql = INIT_SQL_PATH.read_text().split('-- BEGIN ANSWER_FEEDBACK_V1_7',1)[0]
    conn.executescript(sql)
    conn.execute("INSERT INTO query_log(route,query) VALUES ('chat','kept original')"); conn.commit(); conn.close()
    return path


def test_migration_dry_run_then_commit_and_idempotence(tmp_path):
    from scripts.migrate_answer_feedback import migrate
    path = legacy_copy(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert migrate(path) == ['answer_feedback','chat_answers']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert migrate(path,commit=True) == ['answer_feedback','chat_answers']
    assert migrate(path,commit=True) == []
    conn = sqlite3.connect(path)
    try:
        assert conn.execute('SELECT query FROM query_log').fetchone()[0] == 'kept original'
        assert conn.execute("SELECT COUNT(*) FROM schema_versions WHERE version='1.7'").fetchone()[0] == 1
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
    finally: conn.close()


def test_migration_failure_is_atomic_and_does_not_create_missing_path(tmp_path, monkeypatch):
    import scripts.migrate_answer_feedback as migration
    path = legacy_copy(tmp_path)
    original = migration.migration_sql()
    monkeypatch.setattr(migration,'migration_sql',lambda: original+'\nINVALID SQL;')
    with pytest.raises(sqlite3.Error): migration.migrate(path,commit=True)
    conn = sqlite3.connect(path)
    try:
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name IN ('chat_answers','answer_feedback')").fetchall()
        assert not conn.execute("SELECT * FROM schema_versions WHERE version='1.7'").fetchall()
        assert conn.execute('SELECT COUNT(*) FROM query_log').fetchone()[0] == 1
    finally: conn.close()
    missing = tmp_path / 'does-not-exist.sqlite3'
    with pytest.raises(FileNotFoundError): migration.migrate(missing,commit=True)
    assert not missing.exists()


def test_actual_cli_runs_without_pythonpath_and_defaults_to_readonly(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    path = legacy_copy(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    env = os.environ.copy(); env.pop('PYTHONPATH',None)
    script = Path(__file__).resolve().parent.parent / 'scripts/migrate_answer_feedback.py'
    result = subprocess.run([sys.executable,str(script),'--db-path',str(path)],cwd=tmp_path,env=env,capture_output=True,text=True)
    assert result.returncode == 0 and 'Read-only dry-run' in result.stdout
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize('constraint',['columns','foreign-key','primary-key','unique-query'])
def test_existing_incompatible_tables_fail_dry_run_without_being_modified(tmp_path,constraint):
    from scripts.migrate_answer_feedback import migrate, migration_sql
    path = legacy_copy(tmp_path)
    conn = sqlite3.connect(path)
    sql = migration_sql()
    if constraint == 'columns': sql = sql.replace('request_context JSON NOT NULL','not_context JSON NOT NULL').replace('json_valid(request_context)','json_valid(not_context)')
    if constraint == 'foreign-key': sql = sql.replace('FOREIGN KEY (query_log_id) REFERENCES query_log(log_id) ON DELETE CASCADE','CHECK (query_log_id > 0)')
    if constraint == 'primary-key': sql = sql.replace('answer_id TEXT NOT NULL PRIMARY KEY CHECK','answer_id TEXT CHECK')
    if constraint == 'unique-query': sql = sql.replace('query_log_id INTEGER NOT NULL UNIQUE','query_log_id INTEGER NOT NULL')
    conn.executescript(sql); conn.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError): migrate(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize('change', ["expires_at='invalid'","feedback_token_hash="+"'"+'界'*64+"'", "answer_text=x'FF'"])
def test_corrupt_storage_is_not_a_500_or_a_saved_vote(api_client,empty_db,change):
    target = receipt(api_client)
    empty_db.execute('UPDATE chat_answers SET '+change); empty_db.commit()
    assert api_client.post('/feedback',json={**target,'rating':'up'}).status_code == 404
    assert not empty_db.execute('SELECT * FROM answer_feedback').fetchall()


def test_chat_returns_credentials_only_in_no_store_completed_event(api_client):
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: lambda p: iter(['synthetic'])
    response = api_client.post('/chat',json={'query':'CS 5800','allow_feedback_capture':True},headers={'X-Eval-Run':'headers-test'})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert response.headers['cache-control']=='no-store'
    assert 'feedback' not in events[0] and 'log_id' not in events[0]
    assert events[-1]['feedback']['feedback_token'] not in json.dumps(events[:-1])
