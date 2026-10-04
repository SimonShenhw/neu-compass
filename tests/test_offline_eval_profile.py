"""Offline evaluation contracts and opt-in component timing, not live quality."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent


def cases():
    return {'queries': [
        {'query_id': 'p', 'query': 'positive', 'expected_course_ids': ['a', 'b']},
        {'query_id': 'n', 'query': 'negative', 'expected_course_ids': []},
    ]}


def test_duplicate_labels_cannot_inflate_metric():
    from eval.run_eval import recall_at_k
    assert recall_at_k(['a'], ['a', 'a'], k=1) == 1.0


def test_nonfive_k_has_truthful_legacy_and_canonical_fields():
    from eval.run_eval import run_eval
    data = {'queries': [{'query_id': 'q', 'query': 'query', 'expected_course_ids': ['target']}]}
    report = run_eval(data, lambda _: ['a', 'b', 'c', 'd', 'e', 'target'], k=10)
    summary = report.to_dict()['summary']
    assert summary['k'] == 10 and summary['capped_recall_at_k'] == 1
    assert summary['standard_recall_at_k'] == 1 and summary['recall_at_5'] == 0


def test_bad_labels_fail_before_search_side_effects():
    from eval.run_eval import run_eval
    data = cases()
    del data['queries'][1]['expected_course_ids']
    calls = []
    with pytest.raises(ValueError):
        run_eval(data, lambda query: calls.append(query) or [])
    assert calls == []


def test_nearest_rank_boundary_is_shared_by_latency_scripts():
    from scripts.eval_via_api import _percentile
    assert _percentile([1., 2., 3., 4.], .5) == 2.


def test_profile_components_exist_without_loading_models():
    if not (ROOT / 'eval/profile_eval.py').exists():
        pytest.fail('offline_profile_not_implemented', pytrace=False)
    from eval.profile_eval import profile_eval
    report = profile_eval(cases(), lambda query: ['a'] if query == 'positive' else [],
                          warmup=1, iterations=2)
    assert report['measured_calls'] == 4 and report['warmup_calls'] == 2
    assert report['quality_improvement_verified'] is False


@pytest.mark.parametrize('kind', ['duplicate_id', 'missing_labels', 'duplicate_labels', 'empty_id',
                                 'empty_query', 'bad_label', 'bad_queries', 'bad_entry'])
def test_invalid_test_sets_never_call_search(kind):
    from eval.run_eval import run_eval
    data = cases()
    if kind == 'duplicate_id':
        data['queries'][1]['query_id'] = 'p'
    elif kind == 'missing_labels':
        del data['queries'][1]['expected_course_ids']
    elif kind == 'duplicate_labels':
        data['queries'][0]['expected_course_ids'] = ['a', 'a']
    elif kind == 'empty_id':
        data['queries'][1]['query_id'] = ' '
    elif kind == 'empty_query':
        data['queries'][1]['query'] = ' '
    elif kind == 'bad_label':
        data['queries'][1]['expected_course_ids'] = [None]
    elif kind == 'bad_queries':
        data['queries'] = {}
    else:
        data['queries'][1] = 'private-invalid-entry-canary'
    calls = []
    with pytest.raises(ValueError) as error:
        run_eval(data, lambda query: calls.append(query) or [])
    assert calls == [] and 'canary' not in str(error.value)


@pytest.mark.parametrize('k', [0, -1, True, 1.5, 101])
def test_invalid_k_never_calls_search(k):
    from eval.run_eval import run_eval
    calls = []
    with pytest.raises(ValueError):
        run_eval(cases(), lambda query: calls.append(query) or [], k=k)
    assert calls == []


@pytest.mark.parametrize('result', [None, 'private-result-canary', ['a', 'a'], [None], [' ']])
def test_bad_search_results_are_not_deduplicated_or_counted_as_rejections(result):
    from eval.run_eval import run_eval
    with pytest.raises(ValueError) as error:
        run_eval(cases(), lambda _: result)
    assert 'canary' not in str(error.value)


def test_capped_coverage_and_standard_recall_are_distinct():
    from eval.run_eval import run_eval
    data = {'queries': [dict(query_id='multi', query='query', expected_course_ids=list('abcdefgh'))]}
    report = run_eval(data, lambda _: list('abcde'))
    assert report.recall_at_5 == report.capped_recall_at_k == 1
    assert report.standard_recall_at_k == 5 / 8
    assert report.to_dict()['summary']['metric_definitions']['recall_at_5'] == 'legacy_capped_coverage_at_5'


def test_negatives_have_separate_denominator_and_undefined_positive_metrics():
    from eval.run_eval import run_eval
    data = {'queries': [dict(query_id='a', query='a', expected_course_ids=[]),
                        dict(query_id='b', query='b', expected_course_ids=[])]}
    summary = run_eval(data, lambda query: [] if query == 'a' else ['x']).to_dict()['summary']
    assert summary['queries_with_expected'] == 0 and summary['negative_queries'] == 2
    assert summary['correct_rejections'] == summary['false_positives'] == 1
    assert summary['rejection_accuracy'] == .5 and summary['standard_recall_at_k'] is None
    assert summary['capped_recall_at_k'] is None and summary['quality_status'] == 'no_positive_queries'


@pytest.mark.parametrize('module', ['scripts.eval_via_api', 'scripts.probe_inference_latency'])
def test_latency_script_wrappers_share_exact_convention(module):
    import importlib
    function = importlib.import_module(module)._percentile
    assert function([4., 1., 3., 2.], .5) == 2.
    assert function([1., 2., 3., 4.], .95) == 4.


@pytest.mark.parametrize('samples,p', [([float('nan')], .5), ([float('inf')], .5),
                                     ([-1], .5), ([True], .5), ([1], -1), ([1], 1.1)])
def test_bad_latency_values_cannot_form_a_report(samples, p):
    from eval.latency_metrics import percentile
    with pytest.raises(ValueError):
        percentile(samples, p)


def test_empty_and_small_sample_percentiles_are_explicit():
    from eval.latency_metrics import latency_summary, percentile
    assert latency_summary([])['p50'] is None and latency_summary([])['n'] == 0
    assert percentile([7], .5) == percentile([7], 1) == 7
    assert percentile([1, 2, 3, 4], 0) == 1 and percentile([1, 2, 3, 4], .5) == 2


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def advance(self, ms):
        self.now += int(ms * 1_000_000)


def test_nested_stage_exclusive_time_is_not_double_counted():
    from rag.profiling import collect_profile, stage
    clock = Clock()
    with collect_profile(clock=clock) as trace:
        with stage('vector_retrieval'):
            clock.advance(2)
            with stage('embedding'):
                clock.advance(3)
            clock.advance(5)
    totals = trace.totals()
    assert totals['vector_retrieval']['inclusive_ms'] == 10
    assert totals['vector_retrieval']['exclusive_ms'] == 7
    assert totals['embedding']['exclusive_ms'] == 3
    assert sum(row['exclusive_ms'] for row in totals.values()) == 10


def test_disabled_instrumentation_never_reads_clock_or_changes_function(monkeypatch):
    import rag.profiling as module
    def forbidden():
        raise AssertionError('unexpected_clock')
    monkeypatch.setattr(module.time, 'perf_counter_ns', forbidden)
    @module.profiled('embedding')
    def function(value):
        return value
    with module.stage('vector_search'):
        assert function('same-result') == 'same-result'


def test_exception_and_nested_collectors_restore_previous_context():
    from rag.profiling import collect_profile, stage
    clock = Clock()
    with collect_profile(clock=clock) as outer:
        with stage('embedding'):
            clock.advance(1)
        with pytest.raises(RuntimeError):
            with collect_profile(clock=clock) as inner:
                with stage('vector_search'):
                    clock.advance(2)
                    raise RuntimeError('synthetic-stage-error')
        with stage('embedding'):
            clock.advance(3)
    assert outer.totals()['embedding']['exclusive_ms'] == 4
    assert 'vector_search' not in outer.totals()
    assert inner.totals()['vector_search']['exclusive_ms'] == 2
    with stage('fusion'):
        clock.advance(100)
    assert 'fusion' not in outer.totals()


def test_unknown_stage_and_async_decorator_are_rejected():
    from rag.profiling import collect_profile, profiled, stage
    with collect_profile():
        with pytest.raises(ValueError):
            with stage('private-stage-canary'):
                pass
    async def function():
        pass
    with pytest.raises(ValueError):
        profiled('embedding')(function)


@pytest.mark.parametrize('bad_clock', [lambda: float('nan'), lambda: True, iter([2, 1]).__next__])
def test_invalid_stage_clock_fails_without_fabricating_zero(bad_clock):
    from rag.profiling import collect_profile, stage
    with pytest.raises(ValueError):
        with collect_profile(clock=bad_clock):
            with stage('embedding'):
                pass


def test_warmup_excluded_stage_absence_and_residual_are_explicit():
    from eval.profile_eval import profile_eval
    from rag.profiling import stage
    clock, calls = Clock(), []
    def search(query):
        calls.append(query)
        clock.advance(1)
        if query == 'positive':
            with stage('embedding'):
                clock.advance(3)
        clock.advance(2)
        return ['a'] if query == 'positive' else []
    report = profile_eval(cases(), search, warmup=1, iterations=2, clock=clock)
    assert len(calls) == 6 and report['measured_calls'] == 4 and report['warmup_calls'] == 2
    embedding = report['stages']['embedding']
    assert embedding['samples_present'] == embedding['samples_absent'] == 2
    assert embedding['exclusive_ms']['n'] == 2 and embedding['exclusive_ms']['mean'] == 3
    assert report['uninstrumented_ms']['mean'] == 3 and report['wall_ms']['mean'] == 4.5


@pytest.mark.parametrize('warmup,iterations', [(-1, 1), (True, 1), (11, 1), (0, 0), (0, 21), (0, True)])
def test_invalid_profile_plan_has_no_adapter_calls(warmup, iterations):
    from eval.profile_eval import profile_eval
    calls = []
    with pytest.raises(ValueError):
        profile_eval(cases(), lambda query: calls.append(query) or [], warmup=warmup, iterations=iterations)
    assert calls == []


@pytest.mark.parametrize('failure_call', [1, 3])
def test_warmup_or_measurement_failure_aborts_instead_of_dropping_sample(failure_call):
    from eval.profile_eval import profile_eval
    calls = []
    def search(query):
        calls.append(query)
        if len(calls) == failure_call:
            raise RuntimeError('synthetic-adapter-failure')
        return []
    with pytest.raises(RuntimeError):
        profile_eval(cases(), search, warmup=1, iterations=3)
    assert len(calls) == failure_call


def test_rank_instability_is_visible_not_averaged_away():
    from eval.profile_eval import profile_eval
    calls = []
    data = {'queries': [dict(query_id='q', query='q', expected_course_ids=['a'])]}
    def search(_):
        calls.append(True)
        return ['a'] if len(calls) == 1 else ['b']
    report = profile_eval(data, search, warmup=0, iterations=2)
    assert report['ranking_stable'] is False
    assert [run['capped_recall_at_k'] for run in report['quality_runs']] == [1, 0]


@pytest.mark.parametrize('trace', [False, True])
def test_fixed_fixture_uses_actual_kernel_and_no_query_writes(trace):
    from scripts.profile_offline_search import run_fixture
    report = run_fixture(trace=trace)
    assert report['synthetic_only'] is True and report['production_performance_verified'] is False
    assert report['release_approved'] is False and report['real_model_calls'] == report['query_dml_changes'] == 0
    assert report['measured_calls'] == 15 and report['warmup_calls'] == 5 and report['ranking_stable']
    assert all(run['standard_recall_at_k'] == 1 and run['rejection_accuracy'] == 1 for run in report['quality_runs'])
    if trace:
        assert {'alias_resolution', 'embedding', 'vector_search', 'bm25_search', 'fusion',
                'hybrid_hydrate', 'sqlite_filter', 'hybrid_filter', 'candidate_texts', 'rerank_score'} <= set(report['stages'])
        assert report['stages']['embedding']['samples_absent'] == 3
        assert report['stages']['hybrid_filter']['samples_present'] == 3
    else:
        assert report['stages'] == {}


@pytest.mark.parametrize('query', ['CS 5800', 'graph algorithms BFS DFS', 'ancient roman history'])
def test_real_api_fixture_keeps_wire_shape_ranking_and_eval_marker(api_client, empty_db, query):
    from rag.profiling import collect_profile
    body = {'query': query, 'k': 5}
    first = api_client.post('/search', json=body, headers={'X-Eval-Run': 'offline-profile-companion'})
    with collect_profile() as trace:
        second = api_client.post('/search', json=body, headers={'X-Eval-Run': 'offline-profile-companion'})
    assert first.status_code == second.status_code == 200
    before, after = first.json(), second.json()
    before.pop('latency_ms')
    after.pop('latency_ms')
    assert before == after and 'stages' not in after
    assert 'alias_resolution' in trace.totals()
    markers = [row[0] for row in empty_db.execute('SELECT user_id FROM query_log')]
    assert markers and all(value == 'eval:offline-profile-companion' for value in markers)


def test_fresh_fixture_cli_blocks_config_network_model_loads_and_disk_writes(tmp_path):
    code = '''
import importlib.abc, os, pathlib, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'config', 'api', 'app', 'dotenv', 'FlagEmbedding', 'torch', 'transformers'}:
            raise RuntimeError('forbidden_import')
sys.meta_path.insert(0, Block())
def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'}:
        raise RuntimeError('forbidden_external_action')
    if event == 'sqlite3.connect' and args[0] != ':memory:':
        raise RuntimeError('forbidden_database')
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
from scripts.profile_offline_search import cli
raise SystemExit(cli(['--trace']))
'''
    run = subprocess.run([sys.executable, '-B', '-c', code, str(ROOT)], cwd=tmp_path,
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0 and run.stderr == ''
    report = json.loads(run.stdout)
    assert report['synthetic_only'] and report['release_approved'] is False
    assert not list(tmp_path.iterdir())
    for private in ('fixture-graph', 'filtered neural', str(ROOT), 'sha256', 'source_excerpt'):
        assert private not in run.stdout


@pytest.mark.parametrize('args', [['--db-copy=private-path-canary'], ['--out=private-output-canary'], ['--tr']])
def test_fixture_cli_rejects_arbitrary_inputs_without_echo(tmp_path, args):
    run = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/profile_offline_search.py'), *args],
                         cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert run.returncode == 2 and run.stderr == '' and 'canary' not in run.stdout
    assert json.loads(run.stdout)['release_approved'] is False and not list(tmp_path.iterdir())


def test_outer_clock_cannot_hide_overlapping_or_inconsistent_stage_duration():
    from eval.profile_eval import profile_eval
    from rag.profiling import stage
    values = iter([0, 10, 40, 20])
    def search(_):
        with stage('embedding'):
            pass
        return ['a']
    with pytest.raises(ValueError, match='overlapping_profile_samples'):
        profile_eval({'queries': [cases()['queries'][0]]}, search, warmup=0, iterations=1, clock=values.__next__)


def test_profile_freezes_labels_before_adapter_can_mutate_original_input():
    from eval.profile_eval import profile_eval
    data = cases()
    def search(query):
        data['queries'][0]['expected_course_ids'] = ['private-mutated-label-canary']
        return ['a'] if query == 'positive' else []
    report = profile_eval(data, search, warmup=1, iterations=2)
    assert [run['standard_recall_at_k'] for run in report['quality_runs']] == [.5, .5]
    assert 'canary' not in json.dumps(report)


def test_integer_nanoseconds_do_not_create_negative_float_residual():
    from eval.profile_eval import profile_eval
    from rag.profiling import stage
    clock = Clock()
    def search(_):
        for value in (341235, 95334333, 3244435):
            with stage('embedding'):
                clock.now += value
        return ['a']
    report = profile_eval({'queries': [cases()['queries'][0]]}, search, warmup=0, iterations=1, clock=clock)
    assert report['uninstrumented_ms']['mean'] == 0


def test_api_eval_cli_validates_labels_before_http_warmup(tmp_path, monkeypatch):
    import scripts.eval_via_api as module
    data = cases()
    del data['queries'][1]['expected_course_ids']
    path = tmp_path / 'invalid.json'
    path.write_text(json.dumps(data))
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('unexpected_http')
    monkeypatch.setattr(module.httpx, 'Client', forbidden)
    monkeypatch.setattr(sys, 'argv', ['eval_via_api', '--test-set', str(path)])
    assert module.cli() == 2
    assert calls == []
