"""Fail-closed contracts for live-capable probes; importing performs no I/O.

工具仍可能写服务端 query_log／调用模型；本模块不是离线沙箱或运行授权。
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import nullcontext
import json
import math
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from eval.latency_metrics import latency_summary
from eval.run_eval import validate_test_set


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps(input_failure()))
        raise SystemExit(2)


def input_failure(code='invalid_arguments'):
    return dict(measurement_status='not_started', code=code,
                release_approved=False, production_performance_verified=False)


def integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('invalid_probe_count')
    return value


def validate_label(label):
    if not isinstance(label, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_+\-]{0,63}', label) is None:
        raise ValueError('invalid_eval_run_label')
    return label


def validate_url(base_url):
    if not isinstance(base_url, str) or any(c.isspace() or ord(c) < 32 for c in base_url):
        raise ValueError('invalid_probe_origin')
    parts = urlsplit(base_url)
    if (parts.scheme not in {'http', 'https'} or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.path not in {'', '/'} or parts.query or parts.fragment
            or '\\' in base_url):
        raise ValueError('invalid_probe_origin')
    if parts.port is not None and not 1 <= parts.port <= 65535:
        raise ValueError('invalid_probe_origin')
    return base_url.rstrip('/')


def finite_number(value, *, nonnegative=True):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or (nonnegative and value < 0)):
        raise ValueError('invalid_probe_number')
    return float(value)


def validate_timeout(value):
    value = finite_number(value)
    if not 0 < value <= 300:
        raise ValueError('invalid_probe_timeout')
    return value


def load_cases(path, k):
    integer(k, 1, 50)  # HTTP SearchRequest is narrower than the offline harness.
    path = Path(path)
    if path.suffix.lower() != '.json' or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('invalid_probe_input_file')
    def reject_constant(value):
        raise ValueError('invalid_json_constant')
    data = json.loads(path.read_text(encoding='utf-8'), parse_constant=reject_constant)
    entries = validate_test_set(data, k=k)
    if (not entries or any(len(entry['query']) > 500 for entry in entries)
            or 'version' in data and (not isinstance(data['version'], str)
                                     or not data['version'].strip() or len(data['version']) > 128)):
        raise ValueError('invalid_http_eval_queries')
    return {**data, 'queries': entries}


def validate_ready(response):
    if response.status_code != 200:
        raise ValueError('not_ready')
    body = response.json()
    if (not isinstance(body, dict) or body.get('status') != 'ready'
            or any(type(body.get(key)) is not int or body[key] <= 0
                   for key in ('courses_indexed', 'bm25_corpus'))):
        raise ValueError('invalid_ready_response')


def validate_search(response, query, k):
    if response.status_code != 200:
        raise ValueError('search_http_failed')
    body = response.json()
    if (not isinstance(body, dict) or body.get('query') != query
            or type(body.get('k')) is not int or body['k'] != k
            or body.get('matched_via') not in {'alias', 'hybrid', 'empty', 'rejected'}
            or not isinstance(body.get('results'), list) or len(body['results']) > k
            or not isinstance(body.get('rejection_reason'), (str, type(None)))):
        raise ValueError('invalid_search_response')
    finite_number(body.get('latency_ms'))  # Missing is NOT zero; bool/NaN also fail.
    ids = []
    for hit in body['results']:
        if (not isinstance(hit, dict)
                or any(not isinstance(hit.get(key), str) or not hit[key].strip()
                       for key in ('course_id', 'primary_code', 'primary_name'))
                or hit.get('matched_via') != body['matched_via']):
            raise ValueError('invalid_search_hit')
        finite_number(hit.get('score'), nonnegative=False)
        ids.append(hit['course_id'])
    if len(ids) != len(set(ids)) or bool(ids) != (body['matched_via'] in {'alias', 'hybrid'}):
        raise ValueError('invalid_search_ranking')
    return body


def validate_output(path):
    path = Path(path)
    if path.exists() or path.is_symlink() or not path.parent.is_dir():
        raise ValueError('output_must_be_new_with_existing_parent')
    return path


class ProbeFailure(Exception):
    """Fixed message only; source request/exception is never printed."""


class ProbeRun:
    def __init__(self, *, label, warmup, measured, k=5, clock=None):
        self.label = validate_label(label)
        self.k = integer(k, 1, 50)
        self.warmup_planned = integer(warmup, 0, 10_000)
        self.measured_planned = integer(measured, 1, 10_000)
        if warmup + measured > 10_000:
            raise ValueError('probe_search_call_budget')
        self.clock = clock or time.perf_counter
        self.readiness_attempted = self.readiness_succeeded = 0
        self.warmup_attempted = self.warmup_completed = self.warmup_failed = 0
        self.measured_attempted = self.measured_succeeded = self.measured_failed = 0
        self.status, self.code, self.failed_phase = 'not_started', None, None
        self.server, self.wall, self.matched_via = [], [], Counter()

    @property
    def headers(self):
        return {'X-Eval-Run': self.label}

    def abort(self, code, phase):
        self.status, self.code, self.failed_phase = 'aborted', code, phase

    def ready(self, client):
        if self.readiness_attempted or self.status == 'aborted':
            raise ValueError('probe_already_started')
        self.readiness_attempted = 1
        try:
            validate_ready(client.get('/ready', headers=self.headers))
        except Exception:
            self.abort('readiness_failed', 'readiness')
            raise ProbeFailure('readiness_failed') from None
        self.readiness_succeeded = 1
        self.status = 'running'

    def search(self, client, query, *, warmup=False):
        if (self.status != 'running' or self.readiness_succeeded != 1
                or type(warmup) is not bool
                or not isinstance(query, str) or not query.strip() or len(query) > 500):
            raise ValueError('invalid_probe_sequence')
        phase = 'warmup' if warmup else 'measured'
        if (warmup and (self.warmup_attempted >= self.warmup_planned or self.measured_attempted)
                or not warmup and (self.warmup_completed != self.warmup_planned
                                   or self.measured_attempted >= self.measured_planned)):
            raise ValueError('invalid_probe_sequence')
        setattr(self, phase + '_attempted', getattr(self, phase + '_attempted') + 1)
        try:
            started = finite_number(self.clock())
            response = client.post('/search', json={'query': query, 'k': self.k}, headers=self.headers)
            elapsed = finite_number((finite_number(self.clock()) - started) * 1000)
            body = validate_search(response, query, self.k)
        except Exception:
            setattr(self, phase + '_failed', getattr(self, phase + '_failed') + 1)
            self.abort('search_sample_failed', phase)
            raise ProbeFailure('search_sample_failed') from None
        if warmup:
            self.warmup_completed += 1
        else:
            self.measured_succeeded += 1
            self.server.append(body['latency_ms'])
            self.wall.append(elapsed)
            self.matched_via[body['matched_via']] += 1
        return [hit['course_id'] for hit in body['results']]

    def complete(self):
        if (self.status != 'running' or self.warmup_completed != self.warmup_planned
                or self.measured_succeeded != self.measured_planned):
            raise ValueError('incomplete_probe')
        self.status = 'complete'

    def summary(self):
        result = {key: getattr(self, key) for key in (
            'readiness_attempted', 'readiness_succeeded', 'warmup_planned', 'warmup_attempted',
            'warmup_completed', 'warmup_failed', 'measured_planned', 'measured_attempted',
            'measured_succeeded', 'measured_failed')}
        result.update(measurement_status=self.status, code=self.code, failed_phase=self.failed_phase,
                      warmup_not_attempted=self.warmup_planned - self.warmup_attempted,
                      measured_not_attempted=self.measured_planned - self.measured_attempted,
                      search_calls_planned=self.warmup_planned + self.measured_planned,
                      search_calls_attempted=self.warmup_attempted + self.measured_attempted,
                      k=self.k, percentile_method='nearest_rank', matched_via=dict(self.matched_via),
                      server_latency_ms=latency_summary(self.server), wall_latency_ms=latency_summary(self.wall),
                      latency_sample_scope='validated_measured_successes_only',
                      quality_complete=False, release_approved=False, production_performance_verified=False)
        return result


def run_probe(run, execute, *, out_path=None, wrapped=False, metadata=None):
    """Reserve a NEW artifact before setup/HTTP; failed files retain aggregates.

    stdout 不输出逐条数据／地址／路径。失败文件也保留，下一次须选新路径。
    """
    try:
        context = validate_output(out_path).open('x', encoding='utf-8') if out_path else nullcontext(None)
        with context as output:
            details = {}
            try:
                details = execute() or {}
                run.complete()
            except ProbeFailure:
                pass  # ready/search already recorded phase and counts.
            except Exception:
                run.abort('probe_runtime_failed', 'setup_or_evaluation')
            if run.status != 'complete':
                details = {}  # Never export partial quality after a completeness failure.
            summary = {**details.get('summary', {}), **run.summary()}
            summary['quality_complete'] = run.status == 'complete' and bool(details.get('per_query'))
            artifact_summary = {**(metadata or {}), **summary}
            artifact = ({'summary': artifact_summary, 'per_query': details.get('per_query', [])}
                        if wrapped else artifact_summary)
            if output:
                output.write(json.dumps(artifact, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
        # Do not print success before the artifact's close/flush has succeeded.
        print(json.dumps(summary, sort_keys=True, allow_nan=False))
        return 0 if run.status == 'complete' and summary.get('target_met', True) else 1
    except Exception:
        summary = run.summary()
        summary.update(measurement_status='artifact_failed', code='output_failed', quality_complete=False)
        print(json.dumps(summary, sort_keys=True, allow_nan=False))
        return 2
