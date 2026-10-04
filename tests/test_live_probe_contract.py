"""Live-capable scripts tested only with mocks and owned temporary databases."""

import importlib
import json
from pathlib import Path
import subprocess
import sys

import httpx
import pytest


def ready_body():
    return {'status': 'ready', 'courses_indexed': 3, 'bm25_corpus': 3}


def search_body(query='CS 5800', k=5):
    return {'query': query, 'k': k, 'matched_via': 'alias', 'latency_ms': 4.,
            'results': [{'course_id': 'c-cs-5800', 'primary_code': 'CS 5800',
                         'primary_name': 'Algorithms', 'score': 1., 'matched_via': 'alias'}]}


def test_shared_probe_contract_exists():
    assert importlib.util.find_spec('eval.probe_contract') is not None


def mock_client(monkeypatch, module, handler):
    original = httpx.Client
    clients = []
    def factory(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        client = original(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client
    monkeypatch.setattr(getattr(module, 'httpx', httpx), 'Client', factory)
    for method in ('get', 'post'):
        def request(url, _method=method, **kwargs):
            with original(transport=httpx.MockTransport(handler)) as client:
                return client.request(_method, url, **kwargs)
        monkeypatch.setattr(httpx, method, request)
    return clients


def test_inference_tags_warmup_and_measurement_and_closes_client(tmp_path, monkeypatch, capsys):
    import scripts.probe_inference_latency as module
    calls = []
    def handle(request):
        calls.append(request)
        if request.url.path == '/ready':
            return httpx.Response(200, json=ready_body())
        data = json.loads(request.content)
        return httpx.Response(200, json=search_body(**data))
    clients = mock_client(monkeypatch, module, handle)
    monkeypatch.setattr(sys, 'argv', ['probe', '--n', '4', '--warmup', '1', '--label', 'mock-probe',
                                     '--out-dir', str(tmp_path)])
    assert module.main() == 0
    assert len(calls) == 5 and all(r.headers['X-Eval-Run'] == 'mock-probe' for r in calls)
    report = json.loads((tmp_path / 'latency_probe_mock-probe.json').read_text())
    assert report['warmup_completed'] == 1 and report['measured_succeeded'] == 3
    assert clients and all(client.is_closed for client in clients)


def test_api_eval_ready_body_must_be_ready_before_warmup(tmp_path, monkeypatch, capsys):
    import scripts.eval_via_api as module
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={**ready_body(), 'status': 'warming'})
    mock_client(monkeypatch, module, handle)
    monkeypatch.setattr(sys, 'argv', ['eval', '--out-json', str(tmp_path / 'failed.json')])
    assert module.cli() == 1
    assert len(calls) == 1
    report = json.loads(capsys.readouterr().out)
    assert report['measurement_status'] == 'aborted' and report['warmup_attempted'] == 0


def fixed_cases(tmp_path):
    data = {'version': 'synthetic-test', 'queries': [
        {'query_id': 'p', 'query': 'CS 5800', 'expected_course_ids': ['c-cs-5800']},
        {'query_id': 'n', 'query': 'nohits', 'expected_course_ids': []}]}
    path = tmp_path / 'cases.json'
    path.write_text(json.dumps(data))
    return path


def fixed_response(request):
    if request.url.path == '/ready':
        return httpx.Response(200, json=ready_body())
    data = json.loads(request.content)
    body = search_body(**data)
    if data['query'] == 'nohits':
        body.update(matched_via='rejected', results=[])
    return httpx.Response(200, json=body)


@pytest.mark.parametrize('body,status', [
    ({**ready_body(), 'status': 'warming'}, 200), (ready_body(), 503),
    (ready_body(), 302), ({'status': 'ready'}, 200), ([], 200),
    ({**ready_body(), 'courses_indexed': 0}, 200),
    ({**ready_body(), 'bm25_corpus': True}, 200),
    ({**ready_body(), 'courses_indexed': '3'}, 200)])
def test_ready_requires_status_body_and_real_nonempty_counts(body, status):
    from eval.probe_contract import validate_ready
    with pytest.raises(ValueError):
        validate_ready(httpx.Response(status, json=body))


@pytest.mark.parametrize('kind', [
    'missing_latency', 'nan', 'infinity', 'negative', 'bool_latency', 'string_latency',
    'missing_results', 'null_results', 'duplicate_id', 'bad_id', 'missing_score',
    'nan_score', 'bad_hit_via', 'bad_name', 'wrong_query', 'wrong_k', 'bool_k',
    'too_many', 'nonempty_rejected', 'empty_alias', 'bad_via', 'http_error', 'bad_json'])
def test_bad_search_sample_never_becomes_zero_latency_or_correct_rejection(kind):
    from eval.probe_contract import validate_search
    body, status = search_body(), 200
    if kind == 'missing_latency':
        del body['latency_ms']
    elif kind in {'nan', 'infinity', 'negative', 'bool_latency', 'string_latency'}:
        body['latency_ms'] = {'nan': float('nan'), 'infinity': float('inf'), 'negative': -1,
                              'bool_latency': True, 'string_latency': '4'}[kind]
    elif kind == 'missing_results':
        del body['results']
    elif kind == 'null_results':
        body['results'] = None
    elif kind == 'duplicate_id':
        body['results'] *= 2
    elif kind == 'bad_id':
        body['results'][0]['course_id'] = ' '
    elif kind == 'missing_score':
        del body['results'][0]['score']
    elif kind == 'nan_score':
        body['results'][0]['score'] = float('nan')
    elif kind == 'bad_hit_via':
        body['results'][0]['matched_via'] = 'private-via-canary'
    elif kind == 'bad_name':
        body['results'][0]['primary_name'] = None
    elif kind == 'wrong_query':
        body['query'] = 'private-query-canary'
    elif kind == 'wrong_k':
        body['k'] = 10
    elif kind == 'bool_k':
        body['k'] = True
    elif kind == 'too_many':
        body['results'] = [{**body['results'][0], 'course_id': str(i)} for i in range(6)]
    elif kind == 'nonempty_rejected':
        body['matched_via'] = 'rejected'
    elif kind == 'empty_alias':
        body['results'] = []
    elif kind == 'bad_via':
        body['matched_via'] = 'private-via-canary'
    elif kind == 'http_error':
        status = 500
    # httpx's encoder rejects nonfinite floats before our response validator.
    # Raw bytes deliberately simulate receiving a malformed remote JSON body.
    response = httpx.Response(status, content=(b'private-bad-json-canary' if kind == 'bad_json'
                                               else json.dumps(body).encode()))
    with pytest.raises(ValueError) as error:
        validate_search(response, 'CS 5800', 5)
    assert 'canary' not in str(error.value)


@pytest.mark.parametrize('label', ['', ' ', '../private-canary', 'private/canary',
                                   'private\\canary', '汉字', 'x\nsecret', 'x' * 65])
def test_eval_tag_is_bounded_nonempty_safe_ascii(label):
    from eval.probe_contract import validate_label
    with pytest.raises(ValueError) as error:
        validate_label(label)
    assert 'canary' not in str(error.value)


@pytest.mark.parametrize('url', ['ftp://localhost', 'http://', 'http://u:private-canary@localhost',
                                 'http://localhost/path', 'http://localhost/?token=private-canary',
                                 'http://localhost/#private-canary', 'http://localhost:0',
                                 'http://localhost:65536', 'http://local host', 'http://localhost\\path'])
def test_only_explicit_http_origins_no_credentials_or_query_tokens(url):
    from eval.probe_contract import validate_url
    with pytest.raises(ValueError) as error:
        validate_url(url)
    assert 'canary' not in str(error.value)


@pytest.mark.parametrize('timeout', [0, -1, True, float('nan'), float('inf'), 301, '30'])
def test_timeout_requires_finite_bounded_seconds(timeout):
    from eval.probe_contract import validate_timeout
    with pytest.raises(ValueError):
        validate_timeout(timeout)


@pytest.mark.parametrize('kwargs', [dict(warmup=-1, measured=1), dict(warmup=True, measured=1),
                                   dict(warmup=0, measured=0), dict(warmup=0, measured=1.5),
                                   dict(warmup=2, measured=9999), dict(warmup=0, measured=10001),
                                   dict(warmup=0, measured=1, k=51)])
def test_plans_cannot_start_with_bad_denominator_or_over_budget(kwargs):
    from eval.probe_contract import ProbeRun
    with pytest.raises(ValueError):
        ProbeRun(label='mock', **kwargs)


@pytest.mark.parametrize('failure_at', [1, 2, 3])
def test_api_failure_aborts_and_keeps_truthful_counts_without_partial_quality(
    tmp_path, monkeypatch, capsys, failure_at,
):
    import scripts.eval_via_api as module
    posts = []
    def handle(request):
        if request.url.path == '/search':
            posts.append(request)
            if len(posts) == failure_at:
                raise httpx.ConnectError('private-exception-url-token-canary', request=request)
        return fixed_response(request)
    clients = mock_client(monkeypatch, module, handle)
    path = tmp_path / 'failed.json'
    assert module.cli(['--test-set', str(fixed_cases(tmp_path)), '--out-json', str(path)]) == 1
    stdout = capsys.readouterr().out
    report = json.loads(stdout)
    artifact = json.loads(path.read_text())
    assert len(posts) == failure_at and clients[0].is_closed
    assert report['measurement_status'] == 'aborted' and report['quality_complete'] is False
    assert report['search_calls_attempted'] == failure_at
    assert report['warmup_failed'] == int(failure_at == 1)
    assert report['measured_failed'] == int(failure_at > 1)
    assert report['measured_succeeded'] == max(0, failure_at - 2)
    assert report['measured_not_attempted'] == 2 - max(0, failure_at - 1)
    assert report['wall_latency_ms']['n'] == max(0, failure_at - 2)
    assert artifact['per_query'] == [] and 'standard_recall_at_k' not in artifact['summary']
    assert 'canary' not in stdout + path.read_text()


def test_api_complete_quality_artifact_but_stdout_only_aggregates(tmp_path, monkeypatch, capsys):
    import scripts.eval_via_api as module
    clients = mock_client(monkeypatch, module, fixed_response)
    path = tmp_path / 'new.json'
    assert module.cli(['--test-set', str(fixed_cases(tmp_path)), '--out-json', str(path),
                       '--warmup', '2', '--label', 'mock+run']) == 0
    stdout = capsys.readouterr().out
    summary = json.loads(stdout)
    artifact = json.loads(path.read_text())
    assert summary['quality_complete'] and summary['standard_recall_at_k'] == 1
    assert summary['rejection_accuracy'] == 1 and summary['negative_queries'] == 1
    assert summary['warmup_completed'] == 2 and summary['measured_succeeded'] == 2
    assert len(artifact['per_query']) == 2 and artifact['summary']['label'] == 'mock+run'
    assert summary['production_performance_verified'] is summary['release_approved'] is False
    assert all(word not in stdout for word in ('CS 5800', 'nohits', 'localhost', 'mock+run', str(path)))
    assert clients[0].is_closed


@pytest.mark.parametrize('kind', ['existing', 'missing_parent', 'symlink', 'exclusive_race'])
def test_output_rejected_before_client_or_loader_without_overwriting(tmp_path, monkeypatch, capsys, kind):
    import scripts.eval_via_api as module
    import eval.probe_contract as contract
    path = tmp_path / 'target.json'
    if kind in {'existing', 'exclusive_race'}:
        path.write_text('owned-original-canary')
    elif kind == 'missing_parent':
        path = tmp_path / 'missing' / 'target.json'
    else:
        path.symlink_to(tmp_path / 'nonexistent.json')
    if kind == 'exclusive_race':
        monkeypatch.setattr(contract, 'validate_output', lambda candidate: Path(candidate))
    calls = []
    def forbidden(**kwargs):
        calls.append(True)
        raise AssertionError('unexpected_http')
    monkeypatch.setattr(module.httpx, 'Client', forbidden)
    assert module.cli(['--test-set', str(fixed_cases(tmp_path)), '--out-json', str(path)]) == 2
    assert not calls and 'canary' not in capsys.readouterr().out
    if kind in {'existing', 'exclusive_race'}:
        assert path.read_text() == 'owned-original-canary'
    elif kind == 'missing_parent':
        assert not path.parent.exists()
    else:
        assert path.is_symlink() and not path.exists()


@pytest.mark.parametrize('module_name,args', [
    ('scripts.eval_via_api', ['--k', '51']),
    ('scripts.eval_via_api', ['--timeout', 'nan']),
    ('scripts.eval_via_api', ['--label', '../private-canary']),
    ('scripts.eval_via_api', ['--warmup', '10000']),
    ('scripts.probe_inference_latency', ['--n', '0']),
    ('scripts.probe_inference_latency', ['--n', '3', '--warmup', '3']),
    ('scripts.probe_inference_latency', ['--timeout', 'inf']),
    ('scripts.probe_inference_latency', ['--base-url', 'http://u:private-canary@localhost']),
    ('scripts.probe_latency', ['--iterations', '0']),
    ('scripts.probe_latency', ['--iterations', '10000']),
    ('scripts.probe_latency', ['--warmup', '-1']),
    ('scripts.probe_latency', ['--k', '51'])])
def test_cli_bad_parameters_never_load_models_or_make_requests(
    tmp_path, monkeypatch, capsys, module_name, args,
):
    module = importlib.import_module(module_name)
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('unexpected_runtime')
    if module_name.endswith('probe_latency'):
        monkeypatch.setattr(module, '_build_app', forbidden)
    else:
        monkeypatch.setattr(module.httpx, 'Client', forbidden)
    if module_name.endswith('eval_via_api'):
        args += ['--out-json', str(tmp_path / 'new.json')]
    elif module_name.endswith('probe_inference_latency'):
        args += ['--out-dir', str(tmp_path)]
    entry = module.cli if module_name.endswith('eval_via_api') else module.main
    assert entry(args) == 2 and not calls
    assert 'canary' not in capsys.readouterr().out and not list(tmp_path.iterdir())


@pytest.mark.parametrize('kind', ['empty', 'too_long', 'missing_labels', 'bad_version', 'nonfinite_json'])
@pytest.mark.parametrize('module_name', ['scripts.eval_via_api', 'scripts.probe_latency'])
def test_all_cases_validated_before_setup_or_output(tmp_path, monkeypatch, capsys, kind, module_name):
    path = fixed_cases(tmp_path)
    data = json.loads(path.read_text())
    if kind == 'empty':
        data['queries'] = []
    elif kind == 'too_long':
        data['queries'][1]['query'] = 'x' * 501
    elif kind == 'missing_labels':
        del data['queries'][1]['expected_course_ids']
    elif kind == 'bad_version':
        data['version'] = ['private-metadata-canary']
    else:
        data['unused'] = float('nan')
    path.write_text(json.dumps(data))
    module = importlib.import_module(module_name)
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('unexpected_runtime')
    args = ['--test-set', str(path)]
    if module_name.endswith('probe_latency'):
        monkeypatch.setattr(module, '_build_app', forbidden)
        entry = module.main
    else:
        monkeypatch.setattr(module.httpx, 'Client', forbidden)
        args += ['--out-json', str(tmp_path / 'new.json')]
        entry = module.cli
    assert entry(args) == 2 and not calls and not (tmp_path / 'new.json').exists()


def test_session_order_and_budget_cannot_be_bypassed():
    from eval.probe_contract import ProbeRun
    client = httpx.Client(base_url='http://mock', transport=httpx.MockTransport(fixed_response))
    with client:
        run = ProbeRun(label='mock', warmup=1, measured=1)
        with pytest.raises(ValueError):
            run.search(client, 'CS 5800')
        run.ready(client)
        with pytest.raises(ValueError):
            run.search(client, 'CS 5800', warmup='true')
        with pytest.raises(ValueError):
            run.search(client, 'CS 5800')
        with pytest.raises(ValueError):
            run.complete()
        run.search(client, 'CS 5800', warmup=True)
        with pytest.raises(ValueError):
            run.search(client, 'CS 5800', warmup=True)
        run.search(client, 'CS 5800')
        run.complete()
        with pytest.raises(ValueError):
            run.search(client, 'CS 5800')
    assert run.summary()['search_calls_attempted'] == 2


@pytest.mark.parametrize('ticks', [[True, True], [float('nan'), 1], [2, 1]])
def test_invalid_wall_clock_is_a_failed_sample_not_zero(ticks):
    from eval.probe_contract import ProbeFailure, ProbeRun
    run = ProbeRun(label='mock', warmup=0, measured=1, clock=iter(ticks).__next__)
    with httpx.Client(base_url='http://mock', transport=httpx.MockTransport(fixed_response)) as client:
        run.ready(client)
        with pytest.raises(ProbeFailure):
            run.search(client, 'CS 5800')
    assert run.summary()['measured_failed'] == 1 and run.summary()['wall_latency_ms']['p50'] is None


@pytest.mark.parametrize('rerank', [False, True])
def test_local_real_loader_wiring_uses_only_owned_db_and_fake_models(
    empty_db, tmp_path, monkeypatch, capsys, rerank,
):
    import scripts.probe_latency as module
    import api.main as api_main
    import config
    import db.connection as connection
    import rag.embedder as embedder_module
    import rag.index as index_module
    import rag.reranker as reranker_module
    from api.dependencies import get_db_conn, get_hyde_rescue_fn
    from tests.conftest import build_test_app, FixtureEmbedder, FixtureReranker

    prepared = build_test_app(empty_db)
    original_factory = api_main.create_app
    apps, closed, warms, scores, loads = [], [], [], [], []
    def factory(**kwargs):
        assert kwargs == {'run_startup': False}
        app = original_factory(**kwargs)
        app.dependency_overrides[get_db_conn] = lambda: empty_db
        app.dependency_overrides[get_hyde_rescue_fn] = lambda: None
        apps.append(app)
        return app
    class Conn:
        def execute(self, *args, **kwargs):
            return empty_db.execute(*args, **kwargs)
        def close(self):
            closed.append(True)
    class Embedder(FixtureEmbedder):
        def encode(self, texts, **kwargs):
            warms.append(texts)
            return super().encode(texts, **kwargs)
    class Reranker(FixtureReranker):
        def score(self, query, candidates):
            scores.append((query, candidates))
            return super().score(query, candidates)
    fake_db, fake_index = tmp_path / 'never-open.sqlite', tmp_path / 'never-load-index'
    monkeypatch.setattr(config.settings, 'sqlite_path', fake_db)
    monkeypatch.setattr(config.settings, 'faiss_index_path', fake_index)
    monkeypatch.setattr(api_main, 'create_app', factory)
    def connect(path):
        assert path == fake_db
        return Conn()
    def load(path):
        assert path == fake_index
        loads.append(True)
        return prepared.state.faiss_index
    monkeypatch.setattr(connection, 'connect', connect)
    monkeypatch.setattr(index_module.FaissIndex, 'load', load)
    monkeypatch.setattr(embedder_module, 'BGEM3Embedder', Embedder)
    monkeypatch.setattr(reranker_module, 'CrossEncoderReranker', Reranker)
    data = {'queries': [
        {'query_id': 'alias', 'query': 'CS 5800', 'expected_course_ids': ['c-cs-5800']},
        {'query_id': 'semantic', 'query': 'graph algorithms BFS DFS', 'expected_course_ids': ['c-cs-5800']}]}
    path = tmp_path / 'cases.json'
    path.write_text(json.dumps(data))
    args = ['--test-set', str(path), '--warmup', '1', '--iterations', '2', '--k', '5', '--label', 'local-mock']
    if rerank:
        args.append('--rerank')
    assert module.main(args) == 0
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report['warmup_completed'] == 2 and report['measured_succeeded'] == 4
    assert report['rerank_enabled'] is rerank and report['timing_scope'] == 'asgi_in_process_no_network'
    assert closed == loads == [True] and warms[0] == ['warmup']
    assert (apps[0].state.reranker is not None) is rerank
    if rerank:
        assert scores[0] == ('warmup', ['warmup']) and len(scores) > 1
    else:
        assert scores == []
    markers = [row[0] for row in empty_db.execute('SELECT user_id FROM query_log')]
    assert len(markers) == 6 and set(markers) == {'eval:local-mock'}
    assert not fake_db.exists() and not fake_index.exists()


def test_local_setup_failure_has_no_false_pass_or_raw_exception(monkeypatch, capsys):
    import scripts.probe_latency as module
    def fail(**kwargs):
        raise RuntimeError('private-loader-error-canary')
    monkeypatch.setattr(module, '_build_app', fail)
    assert module.main(['--warmup', '0', '--iterations', '1']) == 1
    stdout = capsys.readouterr().out
    report = json.loads(stdout)
    assert report['measurement_status'] == 'aborted' and report['search_calls_attempted'] == 0
    assert 'target_met' not in report and 'canary' not in stdout


def test_threshold_miss_returns_failure_without_fabricating_incomplete_run(capsys):
    from eval.probe_contract import ProbeRun, run_probe
    run = ProbeRun(label='mock', warmup=0, measured=1)
    def execute():
        with httpx.Client(base_url='http://mock', transport=httpx.MockTransport(fixed_response)) as client:
            run.ready(client)
            run.search(client, 'CS 5800')
        return {'summary': {'target_met': False}}
    assert run_probe(run, execute) == 1
    report = json.loads(capsys.readouterr().out)
    assert report['measurement_status'] == 'complete' and report['target_met'] is False


@pytest.mark.parametrize('module_name', ['eval_via_api', 'probe_inference_latency', 'probe_latency'])
@pytest.mark.parametrize('args', [['--unknown=private-token-canary'], ['--label', '../private-path-canary'],
                                 ['--warmup', '-1']])
def test_fresh_cli_rejection_off_cwd_blocks_env_network_models_and_writes(tmp_path, module_name, args):
    root = Path(__file__).resolve().parent.parent
    code = '''
import importlib.abc, os, pathlib, runpy, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'config', 'api', 'dotenv', 'torch', 'transformers', 'FlagEmbedding'}:
            raise RuntimeError('forbidden_import')
sys.meta_path.insert(0, Block())
def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'sqlite3.connect', 'subprocess.Popen', 'os.system'}:
        raise RuntimeError('forbidden_external_action')
    if event == 'open':
        path, mode, flags = args
        if isinstance(path, (str, bytes)):
            name = pathlib.Path(os.fsdecode(path)).name.lower()
            if name == '.env' or name.startswith('.env.'):
                raise RuntimeError('forbidden_env')
        if (mode and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise RuntimeError('forbidden_write')
sys.addaudithook(audit)
script = sys.argv[1]
sys.argv = sys.argv[1:]
runpy.run_path(script, run_name='__main__')
'''
    result = subprocess.run([sys.executable, '-B', '-c', code, str(root / 'scripts' / f'{module_name}.py'), *args],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and not result.stderr and 'canary' not in result.stdout
    assert json.loads(result.stdout)['release_approved'] is False and not list(tmp_path.iterdir())


@pytest.mark.parametrize('failure', ['warmup_latency', 'measured_latency', 'ready_json'])
def test_inference_malformed_body_stops_with_explicit_zero_or_partial_population(
    tmp_path, monkeypatch, capsys, failure,
):
    import scripts.probe_inference_latency as module
    calls = []
    def handle(request):
        calls.append(request)
        if failure == 'ready_json' and request.url.path == '/ready':
            return httpx.Response(200, content=b'private-ready-canary')
        response = fixed_response(request)
        if request.url.path == '/search':
            search_count = len(calls) - 1
            if search_count == (1 if failure == 'warmup_latency' else 3):
                body = response.json()
                del body['latency_ms']
                return httpx.Response(200, json=body)
        return response
    clients = mock_client(monkeypatch, module, handle)
    assert module.main(['--n', '5', '--warmup', '1', '--out-dir', str(tmp_path)]) == 1
    stdout = capsys.readouterr().out
    report = json.loads(stdout)
    assert len(calls) == {'ready_json': 1, 'warmup_latency': 2, 'measured_latency': 4}[failure]
    assert report['measured_succeeded'] == int(failure == 'measured_latency')
    assert report['server_latency_ms']['p50'] == (4. if failure == 'measured_latency' else None)
    assert report['quality_complete'] is False and clients[0].is_closed and 'canary' not in stdout


def test_warmup_latency_not_in_measured_nearest_rank_denominator(tmp_path, monkeypatch, capsys):
    import scripts.probe_inference_latency as module
    latencies = iter([1000., 1., 2., 3., 4.])
    def handle(request):
        response = fixed_response(request)
        if request.url.path == '/search':
            body = response.json()
            body['latency_ms'] = next(latencies)
            response = httpx.Response(200, json=body)
        return response
    mock_client(monkeypatch, module, handle)
    assert module.main(['--n', '5', '--warmup', '1', '--out-dir', str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['n_requested_total'] == 5 and report['n'] == report['server_n'] == 4
    assert report['server_p50_ms'] == 2 and report['server_p95_ms'] == report['server_p99_ms'] == 4
    assert report['server_min_ms'] == 1 and report['server_max_ms'] == 4


@pytest.mark.parametrize('stage', ['write', 'close'])
def test_export_failure_returns_one_fixed_result_even_after_completed_requests(tmp_path, monkeypatch, capsys, stage):
    from eval.probe_contract import ProbeRun, run_probe
    run = ProbeRun(label='mock', warmup=0, measured=1)
    class BrokenFile:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            if stage == 'close':
                raise OSError('private-close-canary')
        def write(self, value):
            if stage == 'write':
                raise OSError('private-write-canary')
    monkeypatch.setattr(Path, 'open', lambda *args, **kwargs: BrokenFile())
    def execute():
        with httpx.Client(base_url='http://mock', transport=httpx.MockTransport(fixed_response)) as client:
            run.ready(client)
            run.search(client, 'CS 5800')
    assert run_probe(run, execute, out_path=tmp_path / 'target.json') == 2
    stdout = capsys.readouterr().out
    report = json.loads(stdout)
    assert len(stdout.splitlines()) == 1 and report['measured_succeeded'] == 1
    assert report['measurement_status'] == 'artifact_failed' and 'canary' not in stdout


def test_incomplete_callback_cannot_export_partial_quality(tmp_path, capsys):
    from eval.probe_contract import ProbeRun, run_probe
    run = ProbeRun(label='mock', warmup=0, measured=2)
    def execute():
        with httpx.Client(base_url='http://mock', transport=httpx.MockTransport(fixed_response)) as client:
            run.ready(client)
            run.search(client, 'CS 5800')
        return {'summary': {'standard_recall_at_k': 1}, 'per_query': [{'query': 'private-partial-canary'}]}
    path = tmp_path / 'partial.json'
    assert run_probe(run, execute, out_path=path, wrapped=True) == 1
    stdout = capsys.readouterr().out
    artifact = json.loads(path.read_text())
    assert artifact['per_query'] == [] and 'standard_recall_at_k' not in artifact['summary']
    assert json.loads(stdout)['measured_succeeded'] == 1 and 'canary' not in stdout + path.read_text()


@pytest.mark.parametrize('module_name', ['eval_via_api', 'probe_inference_latency'])
def test_fresh_remote_complete_mock_run_blocks_config_env_models_network_and_unowned_writes(tmp_path, module_name):
    root = Path(__file__).resolve().parent.parent
    cases_path = fixed_cases(tmp_path)
    output = tmp_path / ('api.json' if module_name == 'eval_via_api' else 'latency_probe_probe.json')
    code = '''
import importlib.abc, json, os, pathlib, sys
root, module_name, cases_path, output = sys.argv[1:]
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'config', 'api', 'dotenv', 'torch', 'transformers', 'FlagEmbedding'}:
            raise RuntimeError('forbidden_import')
sys.meta_path.insert(0, Block())
def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'sqlite3.connect', 'subprocess.Popen', 'os.system'}:
        raise RuntimeError('forbidden_external_action')
    if event == 'open':
        path, mode, flags = args
        if isinstance(path, (str, bytes)):
            name = pathlib.Path(os.fsdecode(path)).name.lower()
            if name == '.env' or name.startswith('.env.'):
                raise RuntimeError('forbidden_env')
        if (mode and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            if pathlib.Path(path).resolve() != pathlib.Path(output).resolve():
                raise RuntimeError('forbidden_write')
sys.addaudithook(audit)
sys.path.insert(0, root)
import httpx, importlib
original, clients, requests = httpx.Client, [], []
def handler(request):
    requests.append(request)
    if request.headers.get('X-Eval-Run') not in {'api', 'probe'}:
        raise RuntimeError('missing_eval_marker')
    if request.url.path == '/ready':
        body = dict(status='ready', courses_indexed=3, bm25_corpus=3)
    else:
        data = json.loads(request.content)
        body = dict(**data, matched_via='rejected', results=[], latency_ms=4.)
    return httpx.Response(200, json=body)
def factory(**kwargs):
    assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
    client = original(transport=httpx.MockTransport(handler), **kwargs)
    clients.append(client)
    return client
httpx.Client = factory
module = importlib.import_module('scripts.' + module_name)
args = (['--test-set', cases_path, '--out-json', output] if module_name == 'eval_via_api'
        else ['--n', '3', '--warmup', '1', '--out-dir', str(pathlib.Path(output).parent)])
result = (module.cli(args) if module_name == 'eval_via_api' else module.main(args))
assert result == 0 and clients[0].is_closed and len(requests) == 4
raise SystemExit(result)
'''
    result = subprocess.run([sys.executable, '-B', '-c', code, str(root), module_name, str(cases_path), str(output)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and not result.stderr
    summary = json.loads(result.stdout)
    assert summary['measurement_status'] == 'complete' and summary['measured_succeeded'] == 2
    assert summary['release_approved'] is False and output.exists()
    assert {path.name for path in tmp_path.iterdir()} == {cases_path.name, output.name}
