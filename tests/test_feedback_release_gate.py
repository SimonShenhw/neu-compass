"""Release requires both operator enablement and explicit request permission."""

import ast
import hashlib
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


@pytest.mark.parametrize('enabled,chosen,expected', [(False, True, False), (True, False, False), (True, True, True), (True, 'true', False)])
def test_capture_control_shows_notice_and_fails_closed(monkeypatch, enabled, chosen, expected):
    from app.answer_feedback_view import CAPTURE_NOTICE, CAPTURE_OPT_IN_KEY, QUERY_LOG_NOTICE, render_feedback_capture_control
    enable(monkeypatch, enabled)
    st = CaptureSurface(chosen=chosen, state={CAPTURE_OPT_IN_KEY: True})
    assert render_feedback_capture_control(st) is expected
    assert st.captions[0] == QUERY_LOG_NOTICE
    if enabled:
        assert CAPTURE_NOTICE in st.captions and st.checkboxes[0][1]['value'] is False
        assert '不点击' in CAPTURE_NOTICE and '不会自动删除' in CAPTURE_NOTICE
    else:
        assert not st.checkboxes and CAPTURE_OPT_IN_KEY not in st.session_state
        from app.answer_feedback_view import CAPTURE_OFF_NOTICE  # noqa: PLC0415
        assert st.captions == [QUERY_LOG_NOTICE, CAPTURE_OFF_NOTICE]  # The query log has no answer column.


def test_malformed_ui_selection_is_not_reused(monkeypatch):
    from app.answer_feedback_view import CAPTURE_OPT_IN_KEY, render_feedback_capture_control
    enable(monkeypatch)
    st = CaptureSurface(state={CAPTURE_OPT_IN_KEY: 'true'})
    assert render_feedback_capture_control(st) is False
    assert CAPTURE_OPT_IN_KEY not in st.session_state


@pytest.mark.parametrize('action_name', ['logout', 'clear_conversation'])
def test_clearing_ui_clears_permission_not_just_receipts(action_name):
    from app import state_manager
    from app.answer_feedback_view import CAPTURE_OPT_IN_KEY
    state = {}
    state_manager.init_state(state)
    state[CAPTURE_OPT_IN_KEY] = True
    getattr(state_manager, action_name)(state)
    assert CAPTURE_OPT_IN_KEY not in state


@pytest.mark.parametrize('operator,permit', [(False, True), (True, False), (True, None), (True, 'true')])
def test_unsolicited_stream_receipt_is_ignored_without_two_gates(monkeypatch, operator, permit):
    from app.streamlit_app import stream_assistant
    enable(monkeypatch, operator)
    receipt = dict(answer_id='a'*32, answer_sha256=hashlib.sha256(TEXT.encode()).hexdigest(), feedback_token='t'*43)
    class API:
        def chat_stream(self, body):
            yield {'type': 'meta', 'results': []}
            yield {'type': 'token', 'text': TEXT}
            yield {'type': 'done', 'feedback': receipt}
    state = {'last_chat_feedback': receipt}
    result = ''.join(stream_assistant(API(), {'query': 'synthetic', 'allow_feedback_capture': permit}, state))
    assert result == TEXT and state['last_chat_feedback'] is None


def test_disabled_ui_does_not_offer_vote_buttons_or_call_api(monkeypatch):
    from app.answer_feedback_view import render_answer_feedback
    enable(monkeypatch, False)
    class Surface:
        def columns(self, count):
            raise AssertionError('Disabled UI must not offer vote controls')
    render_answer_feedback(Surface(), {'role': 'assistant', 'content': TEXT,
        'feedback': dict(answer_id='a'*32, answer_sha256=hashlib.sha256(TEXT.encode()).hexdigest(), feedback_token='t'*43)},
        key_prefix='disabled')


def capture_widget(monkeypatch):
    from streamlit.testing.v1 import AppTest
    enable(monkeypatch)
    script = '''
import streamlit as st
from app.answer_feedback_view import render_feedback_capture_control
from app.state_manager import init_state, clear_conversation, logout
init_state(st.session_state)
st.button('Clear', key='clear', on_click=clear_conversation, args=(st.session_state,))
st.button('Logout', key='logout', on_click=logout, args=(st.session_state,))
allowed = render_feedback_capture_control(st)
st.text(str(allowed))
'''
    app = AppTest.from_string(script).run(timeout=45)
    assert not app.exception
    return app


@pytest.mark.parametrize('action', ['clear', 'logout'])
def test_real_capture_widget_defaults_off_and_clear_reverts_selection(monkeypatch, action):
    app = capture_widget(monkeypatch)
    assert app.checkbox[0].value is False and app.text[0].value == 'False'
    app.checkbox[0].check().run(timeout=45)
    assert not app.exception and app.text[0].value == 'True'
    app.run(timeout=45)
    assert app.text[0].value == 'True'
    next(button for button in app.button if button.key == action).click().run(timeout=45)
    assert not app.exception and app.checkbox[0].value is False and app.text[0].value == 'False'


def test_real_operator_disable_then_reenable_does_not_restore_ui_permission(monkeypatch):
    app = capture_widget(monkeypatch)
    app.checkbox[0].check().run(timeout=45)
    enable(monkeypatch, False)
    app.run(timeout=45)
    assert not app.exception and not app.checkbox and app.text[0].value == 'False'
    enable(monkeypatch)
    app.run(timeout=45)
    assert not app.exception and app.checkbox[0].value is False and app.text[0].value == 'False'


def test_main_entry_binds_control_before_input_and_includes_explicit_permission():
    tree = ast.parse((ROOT / 'app/streamlit_app.py').read_text(encoding='utf-8-sig'))
    render = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'render')
    control = next(node for node in ast.walk(render) if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
        and node.value.func.id == 'render_feedback_capture_control')
    assert isinstance(control.targets[0], ast.Name) and control.targets[0].id == 'capture_allowed'
    chat_input = next(node for node in ast.walk(render) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == 'chat_input')
    assert control.lineno < chat_input.lineno
    bodies = [node for node in ast.walk(render) if isinstance(node, ast.Dict)
        and any(isinstance(key, ast.Constant) and key.value == 'allow_feedback_capture' for key in node.keys)]
    assert len(bodies) == 1
    value = next(value for key, value in zip(bodies[0].keys, bodies[0].values)
        if isinstance(key, ast.Constant) and key.value == 'allow_feedback_capture')
    assert isinstance(value, ast.Name) and value.id == 'capture_allowed'


@pytest.mark.parametrize('permit', [False, True])
def test_actual_main_widget_request_and_isolated_api_capture_agree(api_client, empty_db, monkeypatch, permit):
    import httpx
    from streamlit.testing.v1 import AppTest
    import app.api_client as api_module
    import app.cookie_session as cookies
    import app.discover_view as discover
    import app.program_view as programs
    import app.streamlit_app as main
    import app.streamlit_auth_ui as auth
    from app.answer_feedback_view import CAPTURE_OPT_IN_KEY
    enable(monkeypatch)
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: lambda prompt: iter([TEXT])
    requests = []
    original = api_module.ApiClient
    def transport(request):
        if request.method == 'POST':
            body = json.loads(request.content)
            requests.append((request.url.path, body))
            response = api_client.post(request.url.path, json=body,
                headers={'X-Eval-Run': 'synthetic-main-06c'})
        else:
            response = api_client.get(request.url.path, params=dict(request.url.params))
        return httpx.Response(response.status_code, content=response.content,
            headers={'content-type': response.headers.get('content-type', 'application/json')})
    monkeypatch.setattr(api_module, 'ApiClient', lambda **kwargs: original(
        base_url='https://synthetic-main.test', transport=httpx.MockTransport(transport), **kwargs))
    monkeypatch.setattr(auth, 'handle_oauth_callback', lambda: None)
    monkeypatch.setattr(auth, 'render_auth_sidebar', lambda: None)
    monkeypatch.setattr(cookies, 'restore_login_from_cookie', lambda: False)
    monkeypatch.setattr(cookies, 'flush_pending_cookie', lambda: None)
    monkeypatch.setattr(discover, 'render_discover', lambda st: None)
    monkeypatch.setattr(programs, 'get_programs_cached', lambda st: [])
    monkeypatch.setattr(main, '_render_filters_sidebar', lambda st, state: {})
    app = AppTest.from_string('from app.streamlit_app import render\nrender()').run(timeout=45)
    assert not app.exception and not requests
    control = next(item for item in app.checkbox if item.key == CAPTURE_OPT_IN_KEY)
    assert control.value is False
    if permit:
        control.check().run(timeout=45)
        assert not app.exception
    app.chat_input[0].set_value('CS 5800').run(timeout=45)
    assert not app.exception and len(requests) == 1
    assert requests[0][0] == '/chat' and requests[0][1]['allow_feedback_capture'] is permit
    assert empty_db.execute('SELECT COUNT(*) FROM query_log').fetchone()[0] == 1
    assert empty_db.execute('SELECT user_id FROM query_log').fetchone()[0] == 'eval:synthetic-main-06c'
    assert empty_db.execute('SELECT COUNT(*) FROM chat_answers').fetchone()[0] == int(permit)
    assistant = app.session_state['messages'][-1]
    assert assistant['content'] == TEXT and ('feedback' in assistant) == permit
    app.run(timeout=45)
    assert not app.exception and len(requests) == 1


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
