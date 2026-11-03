"""Release requires both operator enablement and explicit request permission."""

import json
from pathlib import Path

import pytest

from api.dependencies import get_chat_stream_fn
from config import settings

ROOT = Path(__file__).resolve().parent.parent
TEXT = 'synthetic release answer'


def enable(monkeypatch, value=True):
    if 'answer_feedback_enabled' not in type(settings).model_fields:
        raise AssertionError('Missing feedback release setting')
    monkeypatch.setattr(settings, 'answer_feedback_enabled', value)


def chat(client, *, permit=None, chunks=None):
    client.app.dependency_overrides[get_chat_stream_fn] = lambda: lambda prompt: iter(chunks or [TEXT])
    body = {'query': 'CS 5800'}
    if permit is not None:
        body['allow_feedback_capture'] = permit
    response = client.post('/chat', json=body, headers={'X-Eval-Run': 'synthetic-release-06c'})
    return response, [json.loads(line) for line in response.text.splitlines() if line.strip()] if response.status_code == 200 else []


def test_setting_is_disabled_by_default_without_dotenv(monkeypatch):
    from config.settings import Settings
    monkeypatch.delenv('ANSWER_FEEDBACK_ENABLED', raising=False)
    assert Settings(gemini_api_key='synthetic', _env_file=None).answer_feedback_enabled is False


def test_legacy_request_defaults_to_no_answer_capture():
    from api.models import ChatRequest
    assert ChatRequest(query='synthetic').allow_feedback_capture is False


@pytest.mark.parametrize('operator,permit,expected', [
    (False, None, False), (False, False, False), (False, True, False),
    (True, None, False), (True, False, False), (True, True, True),
])
def test_operator_and_request_form_two_independent_gates(api_client, empty_db, monkeypatch, operator, permit, expected):
    enable(monkeypatch, operator)
    response, events = chat(api_client, permit=permit)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert ''.join(event['text'] for event in events if event['type'] == 'token') == TEXT
    assert ('feedback' in events[-1]) == expected
    assert empty_db.execute('SELECT COUNT(*) FROM chat_answers').fetchone()[0] == int(expected)
    assert empty_db.execute('SELECT COUNT(*) FROM query_log').fetchone()[0] == 1
    assert empty_db.execute('SELECT user_id FROM query_log').fetchone()[0] == 'eval:synthetic-release-06c'


@pytest.mark.parametrize('value', ['true', 'false', 0, 1, None, [], {}])
def test_request_permission_is_strict_json_boolean(api_client, empty_db, monkeypatch, value):
    enable(monkeypatch)
    before = empty_db.total_changes
    response = api_client.post('/chat', json={'query': 'CS 5800', 'allow_feedback_capture': value})
    assert response.status_code == 422 and empty_db.total_changes == before


@pytest.mark.parametrize('operator', [False, True])
def test_old_database_never_auto_migrates_for_permission(api_client, empty_db, monkeypatch, operator):
    enable(monkeypatch, operator)
    empty_db.execute('DROP TABLE answer_feedback')
    empty_db.execute('DROP TABLE chat_answers')
    empty_db.commit()
    response, events = chat(api_client, permit=True)
    assert response.status_code == 200 and events[-1] == {'type': 'done'}
    tables = {row[0] for row in empty_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'chat_answers' not in tables and 'answer_feedback' not in tables


def test_disabling_blocks_old_receipt_without_erasing_data_and_can_reenable(api_client, empty_db, monkeypatch):
    enable(monkeypatch)
    _, events = chat(api_client, permit=True)
    target = events[-1]['feedback']
    assert api_client.post('/feedback', json={**target, 'rating': 'down'}).status_code == 200
    before = empty_db.total_changes
    enable(monkeypatch, False)
    response = api_client.post('/feedback', json={**target, 'rating': 'up'})
    assert response.status_code == 503 and response.headers['cache-control'] == 'no-store'
    assert target['feedback_token'] not in response.text and empty_db.total_changes == before
    assert empty_db.execute('SELECT COUNT(*) FROM chat_answers').fetchone()[0] == 1
    assert empty_db.execute('SELECT rating FROM answer_feedback').fetchone()[0] == 'down'
    enable(monkeypatch)
    assert api_client.post('/feedback', json={**target, 'rating': 'up'}).status_code == 200
    assert empty_db.execute('SELECT COUNT(*) FROM answer_feedback').fetchone()[0] == 1


@pytest.mark.parametrize('initial,final', [(True, False), (False, True)])
def test_gate_changes_during_stream_do_not_retroactively_capture(api_client, empty_db, monkeypatch, initial, final):
    enable(monkeypatch, initial)
    def stream(prompt):
        yield TEXT[:5]
        enable(monkeypatch, final)
        yield TEXT[5:]
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: stream
    response = api_client.post('/chat', json={'query': 'CS 5800', 'allow_feedback_capture': True})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert response.status_code == 200 and events[-1] == {'type': 'done'}
    assert ''.join(event['text'] for event in events if event['type'] == 'token') == TEXT
    assert not empty_db.execute('SELECT * FROM chat_answers').fetchall()


@pytest.mark.parametrize('permit', [None, False])
def test_disabled_capture_never_attempts_answer_repository(api_client, empty_db, monkeypatch, permit):
    from db.answer_feedback_repository import AnswerFeedbackRepository
    enable(monkeypatch)
    calls = []
    def forbidden(self, **kwargs):
        calls.append(kwargs)
        raise AssertionError('No permitted capture; repository must not be called')
    monkeypatch.setattr(AnswerFeedbackRepository, 'store_completed', forbidden)
    response, events = chat(api_client, permit=permit)
    assert response.status_code == 200 and events[-1] == {'type': 'done'}
    assert not empty_db.execute('SELECT * FROM chat_answers').fetchall()
    assert calls == []


def test_permission_is_not_added_to_prompt_or_stored_context(api_client, empty_db, monkeypatch):
    enable(monkeypatch)
    prompts = []
    def stream(prompt):
        prompts.append(prompt)
        yield TEXT
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: stream
    response = api_client.post('/chat', json={'query': 'CS 5800', 'allow_feedback_capture': True})
    assert response.status_code == 200 and 'allow_feedback_capture' not in prompts[0]
    context = json.loads(empty_db.execute('SELECT request_context FROM chat_answers').fetchone()[0])
    assert 'allow_feedback_capture' not in context and context['history_turn_count'] == 0


def test_settings_repr_and_validation_strings_do_not_expose_secret_canaries():
    from config.settings import Settings
    values = dict(gemini_api_key='canary-gemini', reddit_client_id='canary-reddit-id',
        reddit_client_secret='canary-reddit-secret', google_oauth_client_id='canary-oauth-id',
        google_oauth_client_secret='canary-oauth-secret', session_secret='canary-session')
    config = Settings(**values, _env_file=None)
    for value in values.values():
        assert value not in repr(config) and value not in str(config)
    with pytest.raises(ValueError) as caught:
        Settings(**values, answer_feedback_enabled='canary-invalid-private-flag', _env_file=None)
    assert 'canary-invalid-private-flag' not in str(caught.value)
    # Masking repr/errors is not redaction of deliberate private serialization.
    assert config.model_dump()['gemini_api_key'] == values['gemini_api_key']


@pytest.mark.parametrize('text,expected', [('true', True), ('false', False)])
def test_operator_environment_parses_explicit_boolean(monkeypatch, text, expected):
    from config.settings import Settings
    monkeypatch.setenv('ANSWER_FEEDBACK_ENABLED', text)
    assert Settings(gemini_api_key='synthetic', _env_file=None).answer_feedback_enabled is expected


class CaptureSurface:
    def __init__(self, *, chosen=False, state=None):
        self.session_state = state if state is not None else {}
        self.chosen, self.captions, self.checkboxes = chosen, [], []
    def caption(self, text):
        self.captions.append(text)
    def checkbox(self, label, **kwargs):
        self.checkboxes.append((label, kwargs))
        return self.chosen


@pytest.mark.parametrize('status,headers', [
    (503, {'Cache-Control': 'no-store', 'Retry-After': '30'}),
    (401, {'WWW-Authenticate': 'Bearer'}),
    (405, {'Allow': 'GET'}),
])
def test_structured_http_errors_preserve_protocol_headers(status, headers):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.exceptions import HTTPException
    from api.exceptions import register_exception_handlers
    app = FastAPI()
    register_exception_handlers(app)
    @app.get('/synthetic-error')
    def failure():
        raise HTTPException(status, 'Synthetic error', headers=headers)
    with TestClient(app) as client:
        response = client.get('/synthetic-error')
    assert response.status_code == status and response.json()['status_code'] == status
    for name, value in headers.items():
        assert response.headers[name] == value
