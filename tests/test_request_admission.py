"""Admission and UI failures: mocks/temporary state only, never live traffic."""

import importlib.util
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

import httpx
import pytest


def test_admission_contract_exists():
    assert importlib.util.find_spec('api.admission') is not None


def test_429_is_safe_and_exposes_bounded_retry_hint_without_reposting():
    from app.api_client import ApiClient, ApiError
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={'detail': 'private-overload-canary', 'error_type': 'rate_limited'},
                              headers={'Retry-After': '7'})
    with ApiClient(base_url='http://mock', transport=httpx.MockTransport(handler)) as api:
        with pytest.raises(ApiError) as error:
            api.search('synthetic')
    assert error.value.retry_after_seconds == 7 and error.value.error_type == 'rate_limited'
    assert 'canary' not in str(error.value) and len(calls) == 1


def test_chat_eof_without_done_is_not_a_complete_answer():
    from app.api_client import ApiClient
    from app.streamlit_app import stream_assistant
    def handler(request):
        return httpx.Response(200, content=b'{"type":"token","text":"partial"}\n')
    state = {'last_chat_feedback': {'stale': True}}
    with ApiClient(base_url='http://mock', transport=httpx.MockTransport(handler)) as api:
        chunks = list(stream_assistant(api, {'query': 'synthetic'}, state))
    assert chunks[0] == 'partial' and state['last_chat_error'] is not None
    assert state['last_chat_feedback'] is None and len(chunks) == 2


class Clock:
    def __init__(self, now=0.):
        self.now = now
    def __call__(self):
        return self.now


def make_guard(*, capacity=8, refill=1., inflight=2, clock=None):
    from api.admission import AdmissionGuard, AdmissionPolicy
    return AdmissionGuard(AdmissionPolicy(capacity, refill, inflight), clock=clock or Clock())


@pytest.mark.parametrize('kwargs', [dict(capacity=0), dict(capacity=True), dict(capacity=1.5),
                                   dict(capacity=10001), dict(max_inflight=0), dict(max_inflight=True),
                                   dict(max_inflight=101), dict(refill_per_second=0),
                                   dict(refill_per_second=True), dict(refill_per_second=float('nan')),
                                   dict(refill_per_second=float('inf')), dict(refill_per_second=.001),
                                   dict(refill_per_second=1001)])
def test_policy_is_finite_bounded_and_rejects_wrong_types(kwargs):
    from api.admission import AdmissionPolicy
    with pytest.raises(ValueError):
        AdmissionPolicy(**kwargs)


def test_fractional_refill_retry_rounding_and_long_idle_capacity():
    from api.admission import Denial, Lease
    clock = Clock()
    guard = make_guard(capacity=1, refill=.25, clock=clock)
    first = guard.acquire()
    assert isinstance(first, Lease)
    first.release()
    clock.now = 1
    denial = guard.acquire()
    assert isinstance(denial, Denial) and denial.status_code == 429 and denial.retry_after_seconds == 3
    assert guard.snapshot() == {'active': 0, 'tokens': .25}
    clock.now = 4
    second = guard.acquire()
    assert isinstance(second, Lease) and guard.snapshot() == {'active': 1, 'tokens': 0.}
    second.release()
    clock.now = 1000000
    third = guard.acquire()
    assert isinstance(third, Lease) and guard.snapshot()['tokens'] == 0
    third.release()


def test_busy_does_not_spend_token_and_release_is_idempotent():
    guard = make_guard(capacity=4, inflight=1)
    lease = guard.acquire()
    assert guard.acquire().status_code == 503
    assert guard.snapshot() == {'active': 1, 'tokens': 3.}
    lease.release()
    lease.release()
    assert guard.snapshot()['active'] == 0
    next_lease = guard.acquire()
    assert guard.snapshot() == {'active': 1, 'tokens': 2.}
    next_lease.release()


def test_atomic_threaded_admission_and_release_never_exceed_bound():
    from api.admission import Lease
    guard = make_guard(capacity=100, inflight=3)
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: guard.acquire(), range(36)))
        leases = [result for result in results if isinstance(result, Lease)]
        assert len(leases) == 3 and guard.snapshot() == {'active': 3, 'tokens': 97.}
        assert all(result.status_code == 503 for result in results if not isinstance(result, Lease))
        list(pool.map(lambda lease: lease.release(), leases * 8))
    assert guard.snapshot()['active'] == 0


async def forbidden_receive():
    raise AssertionError('denial_must_not_read_body')


def scope(path='/chat', method='POST', headers=()):
    return {'type': 'http', 'method': method, 'path': path, 'headers': list(headers)}


@pytest.mark.asyncio
async def test_stream_slot_is_held_after_headers_and_final_body_until_cleanup():
    from api.admission import AdmissionMiddleware
    guard = make_guard(capacity=4, inflight=1)
    headers_sent, finish_body, body_sent, finish_cleanup = [asyncio.Event() for _ in range(4)]
    calls, first_messages, denied_messages = [], [], []
    async def upstream(scope, receive, send):
        calls.append(scope['path'])
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        headers_sent.set()
        await finish_body.wait()
        await send({'type': 'http.response.body', 'body': b'done', 'more_body': False})
        body_sent.set()
        await finish_cleanup.wait()
    async def first_send(message):
        first_messages.append(message)
    async def denied_send(message):
        denied_messages.append(message)
    middleware = AdmissionMiddleware(upstream, guard=guard)
    task = asyncio.create_task(middleware(scope(), forbidden_receive, first_send))
    try:
        await asyncio.wait_for(headers_sent.wait(), 5)
        assert guard.snapshot()['active'] == 1
        await middleware(scope('/search'), forbidden_receive, denied_send)
        assert denied_messages[0]['status'] == 503 and calls == ['/chat']
        finish_body.set()
        await asyncio.wait_for(body_sent.wait(), 5)
        assert guard.snapshot()['active'] == 1
        finish_cleanup.set()
        await asyncio.wait_for(task, 5)
        assert guard.snapshot()['active'] == 0
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['exception', 'cancel', 'send_failure', 'disconnect'])
async def test_lease_released_on_aborted_asgi_lifecycle(failure):
    from api.admission import AdmissionMiddleware
    guard = make_guard()
    entered = asyncio.Event()
    async def receive():
        return {'type': 'http.disconnect'}
    async def send(message):
        if failure == 'send_failure':
            raise OSError('private-send-canary')
    async def upstream(scope, receive, send):
        entered.set()
        if failure == 'cancel':
            await asyncio.Event().wait()
        elif failure == 'exception':
            raise RuntimeError('private-handler-canary')
        elif failure == 'disconnect':
            assert (await receive())['type'] == 'http.disconnect'
        else:
            await send({'type': 'http.response.body', 'body': b'x'})
    task = asyncio.create_task(AdmissionMiddleware(upstream, guard=guard)(scope(), receive, send))
    await asyncio.wait_for(entered.wait(), 5)
    if failure == 'cancel':
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif failure == 'exception':
        with pytest.raises(RuntimeError):
            await task
    elif failure == 'send_failure':
        with pytest.raises(OSError):
            await task
    else:
        await task
    assert guard.snapshot()['active'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('path,method', [('/health', 'GET'), ('/ready', 'GET'), ('/auth/callback', 'POST'),
                                       ('/feedback', 'POST'), ('/coop', 'POST'), ('/courses/x', 'GET'),
                                       ('/search', 'GET'), ('/chat', 'OPTIONS')])
async def test_operational_readonly_and_other_endpoints_are_not_this_guard_scope(path, method):
    from api.admission import AdmissionMiddleware
    def forbidden_clock():
        raise AssertionError('not_guarded')
    guard = make_guard(clock=forbidden_clock)
    calls = []
    async def upstream(scope, receive, send):
        calls.append(True)
    await AdmissionMiddleware(upstream, guard=guard)(scope(path, method), forbidden_receive, forbidden_receive)
    assert calls == [True] and guard.snapshot()['active'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('headers', [[], [(b'x-eval-run', b'private-eval-canary')],
                                    [(b'authorization', b'Bearer private-token-canary')],
                                    [(b'x-user-id', b'private-user-canary'), (b'x-forwarded-for', b'private-ip-canary')],
                                    [(b'cf-connecting-ip', b'private-proxy-canary')]])
async def test_headers_never_create_or_bypass_bucket_and_denial_is_private(headers):
    from api.admission import AdmissionMiddleware
    guard = make_guard(capacity=1)
    calls, messages = [], []
    async def upstream(scope, receive, send):
        calls.append(True)
    async def send(message):
        messages.append(message)
    middleware = AdmissionMiddleware(upstream, guard=guard)
    await middleware(scope('/search'), forbidden_receive, send)
    await middleware(scope('/chat/', headers=headers), forbidden_receive, send)
    assert calls == [True] and messages[0]['status'] == 429
    body = json.loads(messages[1]['body'])
    assert set(body) == {'detail', 'error_type', 'status_code'} and body['error_type'] == 'rate_limited'
    assert dict(messages[0]['headers'])[b'cache-control'] == b'no-store'
    assert dict(messages[0]['headers'])[b'retry-after'] == b'1'
    assert 'canary' not in str(messages) and set(guard.snapshot()) == {'active', 'tokens'}


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', [True, -1, float('nan'), float('inf'), 'private-clock-canary'])
async def test_bad_clock_fails_closed_without_calling_handler_or_echo(bad):
    from api.admission import AdmissionMiddleware
    guard = make_guard(clock=lambda: bad)
    calls, messages = [], []
    async def upstream(*args):
        calls.append(True)
    async def send(message):
        messages.append(message)
    await AdmissionMiddleware(upstream, guard=guard)(scope(), forbidden_receive, send)
    assert not calls and messages[0]['status'] == 503 and 'canary' not in str(messages)
    assert guard.snapshot()['active'] == 0


def test_backwards_clock_keeps_state_and_can_release_existing_lease():
    clock = Clock(3)
    guard = make_guard(clock=clock)
    lease = guard.acquire()
    before = guard.snapshot()
    clock.now = 2
    with pytest.raises(ValueError):
        guard.acquire()
    assert guard.snapshot() == before
    lease.release()
    assert guard.snapshot()['active'] == 0


def test_disabled_factory_allocates_no_guard_or_clock(monkeypatch):
    import api.main as module
    monkeypatch.setattr(module.settings, 'request_guard_enabled', False)
    def forbidden(*args, **kwargs):
        raise AssertionError('disabled_guard_constructed')
    monkeypatch.setattr(module, 'AdmissionGuard', forbidden)
    app = module.create_app(run_startup=False)
    assert app.state.admission_guard is None
    assert all(item.cls.__name__ != 'AdmissionMiddleware' for item in app.user_middleware)


def test_settings_default_off_and_explicit_environment_policy_parsing(monkeypatch):
    from config.settings import Settings
    for field in ('REQUEST_GUARD_ENABLED', 'REQUEST_GUARD_CAPACITY',
                  'REQUEST_GUARD_REFILL_PER_SECOND', 'REQUEST_GUARD_MAX_INFLIGHT'):
        monkeypatch.delenv(field, raising=False)
    assert Settings(gemini_api_key='synthetic', _env_file=None).request_guard_enabled is False
    monkeypatch.setenv('REQUEST_GUARD_ENABLED', 'true')
    monkeypatch.setenv('REQUEST_GUARD_CAPACITY', '3')
    monkeypatch.setenv('REQUEST_GUARD_REFILL_PER_SECOND', '.5')
    monkeypatch.setenv('REQUEST_GUARD_MAX_INFLIGHT', '1')
    config = Settings(gemini_api_key='synthetic', _env_file=None)
    assert (config.request_guard_enabled, config.request_guard_capacity,
            config.request_guard_refill_per_second, config.request_guard_max_inflight) == (True, 3, .5, 1)


@pytest.mark.parametrize('key,value', [('request_guard_capacity', 0), ('request_guard_capacity', True),
                                     ('request_guard_max_inflight', 101), ('request_guard_max_inflight', True),
                                     ('request_guard_refill_per_second', float('nan')),
                                     ('request_guard_refill_per_second', True),
                                     ('request_guard_enabled', 'private-flag-canary')])
def test_settings_invalid_policy_fails_without_echo(key, value):
    from config.settings import Settings
    with pytest.raises(ValueError) as error:
        Settings(gemini_api_key='synthetic', _env_file=None, **{key: value})
    assert 'canary' not in str(error.value)


@pytest.mark.parametrize('status,error_type', [(429, 'rate_limited'), (503, 'service_busy'),
                                             (503, 'service_unavailable'), (504, 'upstream_error'), (408, None)])
@pytest.mark.parametrize('operation', ['get', 'post', 'chat'])
def test_ui_transient_statuses_safe_bounded_retry_and_no_automatic_requests(status, error_type, operation):
    from app.api_client import ApiClient, ApiError
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={'detail': 'private-html-token-canary', 'error_type': error_type},
                              headers={'Retry-After': '11'})
    with ApiClient(base_url='http://mock', transport=httpx.MockTransport(handler)) as api:
        with pytest.raises(ApiError) as error:
            if operation == 'get':
                api.health()
            elif operation == 'post':
                api.submit_answer_feedback({'synthetic': True})
            else:
                list(api.chat_stream({'query': 'synthetic'}))
    assert error.value.status_code == status and error.value.retry_after_seconds == 11
    assert 'canary' not in str(error.value) and len(calls) == 1


@pytest.mark.parametrize('value,expected', [('0', 0), ('3', 3), (' 7 ', 7), ('3600', 3600),
                                          ('3601', None), ('99999', None), ('-1', None), ('1.5', None),
                                          ('Infinity', None), ('', None), ('Wed, 21 Oct 2015 07:28:00 GMT', None),
                                          ('private-header-canary', None), (None, None)])
def test_retry_after_is_only_a_bounded_delta_seconds_hint(value, expected):
    from app.api_client import _retry_seconds
    assert _retry_seconds(value) == expected


@pytest.mark.parametrize('exception', [httpx.ReadTimeout, httpx.ConnectError, httpx.ReadError])
@pytest.mark.parametrize('operation', ['get', 'post'])
def test_nonstream_transport_failure_hides_exception_and_never_retries(exception, operation):
    from app.api_client import ApiClient, ApiError
    calls = []
    def handler(request):
        calls.append(request)
        raise exception('private-network-query-token-canary', request=request)
    with ApiClient(base_url='http://mock', transport=httpx.MockTransport(handler)) as api:
        with pytest.raises(ApiError) as error:
            api.health() if operation == 'get' else api.upload_coop({'synthetic': True})
    assert error.value.status_code == (504 if exception is httpx.ReadTimeout else 503)
    assert 'canary' not in str(error.value) and error.value.__cause__ is None and len(calls) == 1


@pytest.mark.parametrize('failure', ['timeout', 'read', 'eof', 'done', 'server_error'])
def test_partial_stream_keeps_tokens_closes_and_never_attaches_feedback_or_replays(failure):
    from app.api_client import ApiClient
    from app.streamlit_app import stream_assistant
    calls, closed = [], []
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"type":"meta","results":[]}\n{"type":"token","text":"partial"}\n'
            if failure == 'timeout':
                raise httpx.ReadTimeout('private-timeout-canary')
            if failure == 'read':
                raise httpx.ReadError('private-read-canary')
            if failure == 'done':
                yield b'{"type":"done"}\n'
            if failure == 'server_error':
                yield b'{"type":"error","detail":"synthetic server failure"}\n'
        def close(self):
            closed.append(True)
    def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=Stream())
    state = {'last_chat_feedback': {'old': True}}
    with ApiClient(base_url='http://mock', transport=httpx.MockTransport(handler)) as api:
        chunks = list(stream_assistant(api, {'query': 'synthetic'}, state))
    assert chunks[0] == 'partial' and state['last_chat_feedback'] is None
    assert bool(state['last_chat_error']) == (failure != 'done')
    assert len(calls) == 1 and closed == [True] and 'canary' not in ''.join(chunks)


def seeded_guard_app(conn, guard):
    from tests.conftest import build_test_app
    from api.main import create_app
    from api.dependencies import get_db_conn, get_hyde_rescue_fn
    prepared = build_test_app(conn)
    app = create_app(run_startup=False, admission_guard=guard)
    for key in ('embedder', 'faiss_index', 'bm25_corpus', 'reranker', 'ready'):
        setattr(app.state, key, getattr(prepared.state, key))
    app.dependency_overrides[get_db_conn] = lambda: conn
    app.dependency_overrides[get_hyde_rescue_fn] = lambda: None
    return app


def test_actual_guarded_routes_reject_before_db_and_keep_health_request_ids(empty_db):
    from fastapi.testclient import TestClient
    from api.dependencies import get_chat_stream_fn
    clock = Clock()
    # Use the same fake clock explicitly for refill after the rejection.
    guard = make_guard(capacity=1, clock=clock)
    app = seeded_guard_app(empty_db, guard)
    streams = []
    def stream(prompt):
        streams.append(True)
        return iter(['synthetic answer'])
    app.dependency_overrides[get_chat_stream_fn] = lambda: stream
    with TestClient(app) as client:
        first = client.post('/search', json={'query': 'CS 5800', 'k': 5}, headers={'X-Eval-Run': 'admission-test'})
        assert first.status_code == 200
        before = empty_db.total_changes
        denied = client.post('/chat', content='private-denied-body-canary',
                             headers={'X-Eval-Run': 'admission-test'})
        assert denied.status_code == 429 and denied.headers['x-request-id']
        assert denied.headers['retry-after'] == '1' and denied.headers['cache-control'] == 'no-store'
        assert 'canary' not in denied.text and empty_db.total_changes == before and not streams
        assert client.get('/health').status_code == client.get('/ready').status_code == 200
        assert guard.snapshot()['active'] == 0
        clock.now = 1
        second = client.post('/chat', json={'query': 'CS 5800'}, headers={'X-Eval-Run': 'admission-test'})
        assert second.status_code == 200 and '"type": "done"' in second.text and streams == [True]
    assert guard.snapshot()['active'] == 0
    assert [row[0] for row in empty_db.execute('SELECT user_id FROM query_log')] == ['eval:admission-test'] * 2
    assert empty_db.execute('SELECT COUNT(*) FROM chat_answers').fetchone()[0] == 0


def test_real_route_503_busy_has_no_dependencies_or_query_log(empty_db):
    from fastapi.testclient import TestClient
    from api.dependencies import get_db_conn
    guard = make_guard(inflight=1)
    app = seeded_guard_app(empty_db, guard)
    calls = []
    def forbidden():
        calls.append(True)
        raise AssertionError('denied_dependency_called')
    app.dependency_overrides[get_db_conn] = forbidden
    held = guard.acquire()
    with TestClient(app) as client:
        result = client.post('/search', json={'query': 'private-query-canary'})
    held.release()
    assert result.status_code == 503 and result.json()['error_type'] == 'service_busy'
    assert result.headers['retry-after'] == '1' and result.headers['x-request-id']
    assert not calls and 'canary' not in result.text and guard.snapshot()['active'] == 0
    assert empty_db.execute('SELECT COUNT(*) FROM query_log').fetchone()[0] == 0


def test_fresh_guard_import_and_lifecycle_no_env_db_models_network_or_writes(tmp_path):
    root = Path(__file__).resolve().parent.parent
    code = '''
import asyncio, importlib.abc, os, pathlib, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'config', 'dotenv', 'torch', 'transformers', 'FlagEmbedding', 'fastapi'}:
            raise RuntimeError('forbidden_import')
sys.meta_path.insert(0, Block())
def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'sqlite3.connect', 'subprocess.Popen', 'os.system'}:
        raise RuntimeError('forbidden_external')
    if event == 'open':
        path, mode, flags = args
        if isinstance(path, (str, bytes)):
            name = pathlib.Path(os.fsdecode(path)).name.lower()
            if name == '.env' or name.startswith('.env.'):
                raise RuntimeError('forbidden_env')
        if (mode and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise RuntimeError('forbidden_write')
sys.addaudithook(audit)
sys.path.insert(0, sys.argv[1])
from api.admission import AdmissionGuard, AdmissionMiddleware, AdmissionPolicy
guard = AdmissionGuard(AdmissionPolicy(1, 1., 1), clock=lambda: 0)
calls, messages = [], []
async def app(scope, receive, send):
    calls.append(True)
async def receive():
    raise RuntimeError('forbidden_body_read')
async def send(message):
    messages.append(message)
async def run():
    middleware = AdmissionMiddleware(app, guard=guard)
    scope = dict(type='http', method='POST', path='/chat')
    await middleware(scope, receive, send)
    await middleware(scope, receive, send)
asyncio.run(run())
assert calls == [True] and messages[0]['status'] == 429 and guard.snapshot()['active'] == 0
print('guard_isolated_ok')
'''
    result = subprocess.run([sys.executable, '-B', '-c', code, str(root)], cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and result.stdout.strip() == 'guard_isolated_ok' and not result.stderr
    assert not list(tmp_path.iterdir())


def test_unknown_unhashable_stream_type_does_not_crash_main_consumer():
    from app.api_client import ApiClient
    from app.streamlit_app import stream_assistant
    data = '[]\nnull\n{"type": []}\n{"type":"token","text":"valid"}\n{"type":"done"}\n'
    state = {}
    with ApiClient(base_url='http://mock', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=data.encode()))) as api:
        assert list(stream_assistant(api, {'query': 'synthetic'}, state)) == ['valid']
    assert state['last_chat_error'] is None


def test_factory_enabled_builds_policy_without_loading_models(monkeypatch):
    import api.main as module
    from api.admission import AdmissionMiddleware
    for key, value in [('request_guard_enabled', True), ('request_guard_capacity', 4),
                       ('request_guard_refill_per_second', .5), ('request_guard_max_inflight', 1)]:
        monkeypatch.setattr(module.settings, key, value)
    app = module.create_app(run_startup=False)
    policy = app.state.admission_guard.policy
    assert (policy.capacity, policy.refill_per_second, policy.max_inflight) == (4, .5, 1)
    assert any(item.cls is AdmissionMiddleware for item in app.user_middleware)
    assert app.user_middleware[0].cls.__name__ == 'RequestLogMiddleware'


@pytest.mark.parametrize('failure', ['429', '503', 'timeout', 'stream_timeout'])
def test_actual_main_widget_safe_failure_partial_text_and_rerun_without_repost(monkeypatch, failure):
    from streamlit.testing.v1 import AppTest
    import app.api_client as api_module
    import app.cookie_session as cookies
    import app.discover_view as discover
    import app.program_view as programs
    import app.streamlit_app as main
    import app.streamlit_auth_ui as auth
    from config import settings
    monkeypatch.setattr(settings, 'answer_feedback_enabled', False)
    requests, closed = [], []
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"type":"meta","results":[]}\n{"type":"token","text":"partial answer"}\n'
            raise httpx.ReadTimeout('private-widget-stream-canary')
        def close(self):
            closed.append(True)
    def handler(request):
        if request.method == 'GET':
            return httpx.Response(200, json={'status': 'ready', 'courses_indexed': 3, 'bm25_corpus': 3})
        requests.append(request)
        assert request.url.path == '/chat'
        if failure == 'timeout':
            raise httpx.ReadTimeout('private-widget-request-canary', request=request)
        if failure == 'stream_timeout':
            return httpx.Response(200, stream=Stream())
        return httpx.Response(int(failure), json={'detail': 'private-widget-response-canary',
                             'error_type': 'rate_limited' if failure == '429' else 'service_busy'},
                             headers={'Retry-After': '9'})
    original = api_module.ApiClient
    monkeypatch.setattr(api_module, 'ApiClient', lambda **kwargs: original(
        base_url='http://synthetic-widget', transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(auth, 'handle_oauth_callback', lambda: None)
    monkeypatch.setattr(auth, 'render_auth_sidebar', lambda: None)
    monkeypatch.setattr(cookies, 'restore_login_from_cookie', lambda: False)
    monkeypatch.setattr(cookies, 'flush_pending_cookie', lambda: None)
    monkeypatch.setattr(discover, 'render_discover', lambda st: None)
    monkeypatch.setattr(programs, 'get_programs_cached', lambda st: [])
    monkeypatch.setattr(main, '_render_filters_sidebar', lambda st, state: {})
    app = AppTest.from_string('from app.streamlit_app import render\nrender()').run(timeout=45)
    assert not app.exception and not requests
    app.chat_input[0].set_value('synthetic query').run(timeout=45)
    assert not app.exception and len(requests) == 1
    assistant = app.session_state['messages'][-1]
    assert assistant['role'] == 'assistant' and '⚠️' in assistant['content']
    assert 'canary' not in assistant['content'] and 'feedback' not in assistant
    if failure in {'429', '503'}:
        assert '9 秒后' in assistant['content'] and '手动重试' in assistant['content']
    if failure == 'stream_timeout':
        assert 'partial answer' in assistant['content'] and closed == [True]
    app.run(timeout=45)
    assert not app.exception and len(requests) == 1 and app.session_state['messages'][-1] == assistant
