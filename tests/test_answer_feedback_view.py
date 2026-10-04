"""Receipt/answer binding, explicit-click UI and real headless widget reruns."""

import copy
import hashlib
import json

import httpx
import pytest

from app.answer_feedback_view import bind_feedback_receipt, render_answer_feedback
from app.api_client import ApiClient, ApiError
from app.state_manager import add_message, clear_conversation, init_state, logout
from app.streamlit_app import stream_assistant

TEXT = '这是一条合成回答。CS 5800'
RECEIPT = dict(answer_id='a'*32,answer_sha256=hashlib.sha256(TEXT.encode()).hexdigest(),feedback_token='t'*43)


@pytest.fixture(autouse=True)
def enable_feedback_for_this_test_module(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, 'answer_feedback_enabled', True)


def message():
    return dict(role='assistant',content=TEXT,feedback=copy.deepcopy(RECEIPT))


class StreamApi:
    def __init__(self, events): self.events = events
    def chat_stream(self, body): yield from self.events


def events():
    return [{'type':'meta','results':[]},{'type':'token','text':TEXT},{'type':'done','feedback':RECEIPT}]


def test_stream_receipt_reaches_only_the_matching_completed_message():
    state = {}; init_state(state)
    content = ''.join(stream_assistant(StreamApi(events()),{'query':'synthetic','allow_feedback_capture':True},state))
    assert state['last_chat_feedback'] == RECEIPT
    add_message(state,role='assistant',content=content,feedback=state['last_chat_feedback'])
    assert state['messages'][-1]['feedback'] == RECEIPT


@pytest.mark.parametrize('kind',['interrupted','error','no-meta','bad-hash','bad-receipt','legacy'])
def test_bad_or_incomplete_stream_cannot_reuse_previous_receipt(kind):
    data = copy.deepcopy(events())
    if kind == 'interrupted': data.pop()
    if kind == 'error': data.insert(-1,{'type':'error','detail':'synthetic error'})
    if kind == 'no-meta': data.pop(0)
    if kind == 'bad-hash': data[-1]['feedback']['answer_sha256'] = 'f'*64
    if kind == 'bad-receipt': data[-1]['feedback'] = {'feedback_token':'old-secret'}
    if kind == 'legacy': data[-1].pop('feedback')
    state = {'last_chat_feedback':RECEIPT}
    list(stream_assistant(StreamApi(data),{'query':'synthetic','allow_feedback_capture':True},state))
    assert state['last_chat_feedback'] is None


@pytest.mark.parametrize('receipt,text', [(None,TEXT),({},TEXT),(RECEIPT,'changed'),(RECEIPT,''),(RECEIPT,None),({**RECEIPT,'user_id':'x'},TEXT)])
def test_invalid_or_transplanted_receipt_is_not_bound(receipt, text):
    assert bind_feedback_receipt(receipt,text) is None


@pytest.mark.parametrize('action',[clear_conversation,logout])
def test_clearing_private_chat_also_clears_pending_credentials(action):
    state = {}; init_state(state)
    add_message(state,role='assistant',content=TEXT,feedback=RECEIPT)
    state.update(last_chat_feedback=RECEIPT,last_chat_meta={'private':'x'},last_chat_error='old')
    action(state)
    assert state['messages'] == []
    assert not {'last_chat_feedback','last_chat_meta','last_chat_error'} & state.keys()


def test_user_message_cannot_acquire_an_assistant_receipt():
    state = {}; init_state(state)
    add_message(state,role='user',content=TEXT,feedback=RECEIPT)
    assert 'feedback' not in state['messages'][0]


def fake_api(monkeypatch, *, response=None, error=None):
    import app.answer_feedback_view as view
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def submit_answer_feedback(self, body):
            calls.append(copy.deepcopy(body))
            if error is not None: raise error
            return response if response is not None else {'answer_id':body['answer_id'],'rating':body['rating']}
    monkeypatch.setattr(view,'ApiClient',Client)
    return calls


class Surface:
    def __init__(self, click=None):
        self.click = click; self.session_state = {}; self.buttons=[]; self.warnings=[]; self.successes=[]
    def caption(self, text): pass
    def columns(self,n): return [self]*n
    def button(self,label,*,key,disabled=False):
        self.buttons.append(key)
        return key.endswith('-'+str(self.click)) and not disabled
    def warning(self,text): self.warnings.append(text)
    def success(self,text): self.successes.append(text)


def test_no_click_no_write_and_success_only_changes_the_clicked_message(monkeypatch):
    calls = fake_api(monkeypatch)
    first, second = message(),message()
    st = Surface()
    render_answer_feedback(st,first,key_prefix='first')
    assert len(st.buttons)==2 and not calls
    st.click = 'up'; render_answer_feedback(st,first,key_prefix='first')
    assert first['feedback_rating']=='up' and 'feedback_rating' not in second
    st.click = None; render_answer_feedback(st,first,key_prefix='first')
    assert len(calls)==1


@pytest.mark.parametrize('error',[ApiError(404,'private-detail'),ApiError(503,'private-detail'),ValueError('private-detail')])
def test_failure_keeps_previous_vote_and_never_echoes_private_details(monkeypatch,error):
    calls = fake_api(monkeypatch,error=error)
    msg = message(); msg['feedback_rating'] = 'up'
    st = Surface('down'); render_answer_feedback(st,msg,key_prefix='vote')
    assert len(calls)==1 and msg['feedback_rating']=='up' and not st.successes
    assert st.warnings and 'private-detail' not in ''.join(st.warnings)


@pytest.mark.parametrize('response',[{'answer_id':'b'*32,'rating':'up'},{'answer_id':'a'*32,'rating':'down'},{}])
def test_malformed_or_other_message_response_is_not_ui_success(monkeypatch,response):
    fake_api(monkeypatch,response=response)
    st = Surface('up'); msg = message()
    render_answer_feedback(st,msg,key_prefix='vote')
    assert not st.successes and 'feedback_rating' not in msg and st.warnings


def test_legacy_invalid_and_user_history_have_no_feedback_buttons(monkeypatch):
    calls = fake_api(monkeypatch)
    st = Surface('up')
    for msg in [dict(role='assistant',content=TEXT),{**message(),'content':'changed'},{**message(),'role':'user'}]:
        render_answer_feedback(st,msg,key_prefix='vote')
    assert not st.buttons and not calls


def test_api_client_sends_only_the_scoped_receipt_and_vote():
    requests=[]
    def transport(request):
        requests.append(request)
        return httpx.Response(200,json={'answer_id':'a'*32,'rating':'down'})
    with ApiClient(base_url='https://synthetic.test',transport=httpx.MockTransport(transport)) as api:
        result = api.submit_answer_feedback({**RECEIPT,'rating':'down'})
    assert result['rating']=='down' and len(requests)==1
    request = requests[0]
    assert request.method=='POST' and request.url.path=='/feedback' and not request.url.query
    assert json.loads(request.content)=={**RECEIPT,'rating':'down'}


def widget(monkeypatch, *, error=None, msg=None):
    from streamlit.testing.v1 import AppTest
    calls = fake_api(monkeypatch,error=error)
    script = f"""
import streamlit as st
from app.answer_feedback_view import render_answer_feedback
if 'message' not in st.session_state:
    st.session_state['message'] = {msg or message()!r}
render_answer_feedback(st, st.session_state['message'], key_prefix='history-0')
"""
    app = AppTest.from_string(script).run(timeout=45)
    assert not app.exception
    return app,calls


def test_real_widget_rerun_has_no_write_until_click_and_correction_is_one_target(monkeypatch):
    app,calls = widget(monkeypatch)
    assert not calls and len(app.button)==2
    app.button[0].click().run(timeout=45)
    assert not app.exception and calls[-1]['rating']=='up'
    app.run(timeout=45)
    assert len(calls)==1 and app.button[0].disabled
    app.button[1].click().run(timeout=45)
    assert not app.exception and len(calls)==2 and calls[-1]['rating']=='down'
    assert {c['answer_id'] for c in calls} == {'a'*32}


def test_real_widget_failed_click_can_retry_without_claiming_saved(monkeypatch):
    app,calls = widget(monkeypatch,error=ApiError(503,'private detail'))
    app.button[0].click().run(timeout=45)
    assert not app.exception and len(calls)==1 and app.warning and not app.success
    assert 'feedback_rating' not in app.session_state['message']
    fake_api(monkeypatch)
    app.button[0].click().run(timeout=45)
    assert not app.exception and app.session_state['message']['feedback_rating']=='up'


def test_real_widget_legacy_and_changed_message_do_not_offer_buttons(monkeypatch):
    app,calls = widget(monkeypatch,msg={**message(),'content':'different'})
    assert not app.exception and not app.button and not calls


def test_complete_isolated_api_stream_message_click_storage_roundtrip(api_client,empty_db,monkeypatch):
    from api.dependencies import get_chat_stream_fn
    import app.answer_feedback_view as view
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: lambda p: iter([TEXT[:5],TEXT[5:]])
    response = api_client.post('/chat',json={'query':'CS 5800','allow_feedback_capture':True},headers={'X-Eval-Run':'ui-roundtrip-06b'})
    data = [json.loads(line) for line in response.text.splitlines()]
    state = {}; init_state(state)
    content = ''.join(stream_assistant(StreamApi(data),{'query':'CS 5800','allow_feedback_capture':True},state))
    add_message(state,role='assistant',content=content,feedback=state['last_chat_feedback'])
    def transport(request):
        response = api_client.post(request.url.path,json=json.loads(request.content))
        return httpx.Response(response.status_code,json=response.json())
    monkeypatch.setattr(view,'ApiClient',lambda **kwargs: ApiClient(
        base_url='https://synthetic.test',transport=httpx.MockTransport(transport),**kwargs))
    st = Surface('down'); st.session_state = state
    render_answer_feedback(st,state['messages'][0],key_prefix='roundtrip')
    row = empty_db.execute('SELECT f.rating,a.answer_text,q.query,q.user_id FROM answer_feedback f '
        'JOIN chat_answers a USING(answer_id) JOIN query_log q ON q.log_id=a.query_log_id').fetchone()
    assert st.successes and row['rating']=='down' and row['answer_text']==TEXT
    assert row['query']=='CS 5800' and row['user_id']=='eval:ui-roundtrip-06b'
    assert state['messages'][0]['feedback_rating']=='down'
