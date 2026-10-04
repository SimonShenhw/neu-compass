"""Opt-in context-local synchronous component timers; no logging or payloads.

Nested stages record inclusive and exclusive time separately. Collectors are
per sample, not singletons. Parallel/background workloads are not benchmarks.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import inspect
import threading
import time

STAGES = frozenset({'alias_resolution', 'sqlite_filter', 'embedding', 'vector_search',
    'vector_hydrate', 'vector_retrieval', 'bm25_search', 'hybrid_filter', 'fusion',
    'hybrid_hydrate', 'candidate_texts', 'rerank_score'})
_current = ContextVar('retrieval_profile', default=None)


class Trace:
    def __init__(self, clock=None):
        self.clock = clock or time.perf_counter_ns
        self.records = []
        self.local = threading.local()
        self.lock = threading.Lock()
        self.closed = False
        self.exclusive_ns = 0

    @contextmanager
    def stage(self, name):
        if name not in STAGES:
            raise ValueError('unknown_profile_stage')
        stack = getattr(self.local, 'stack', None)
        if stack is None:
            stack = self.local.stack = []
        start = self.clock()
        if type(start) is not int:
            raise ValueError('invalid_profile_clock')
        frame = [start, 0]
        stack.append(frame)
        try:
            yield
        finally:
            duration = self.clock() - start
            stack.pop()
            if type(duration) is not int or duration < frame[1] or duration < 0:
                raise ValueError('invalid_profile_clock')
            if stack:
                stack[-1][1] += duration
            with self.lock:
                self.exclusive_ns += duration - frame[1]
                self.records.append((name, duration / 1_000_000, (duration - frame[1]) / 1_000_000))

    def totals(self):
        totals = {}
        for name, inclusive, exclusive in self.records:
            row = totals.setdefault(name, dict(calls=0, inclusive_ms=0., exclusive_ms=0.))
            row['calls'] += 1
            row['inclusive_ms'] += inclusive
            row['exclusive_ms'] += exclusive
        return totals


@contextmanager
def collect_profile(*, clock=None):
    trace = Trace(clock)
    token = _current.set(trace)
    try:
        yield trace
    finally:
        trace.closed = True
        _current.reset(token)


@contextmanager
def stage(name):
    trace = _current.get()
    if trace is None or trace.closed:
        yield
        return
    if name not in STAGES:
        raise ValueError('unknown_profile_stage')
    with trace.stage(name):
        yield


def profiled(name):
    if name not in STAGES:
        raise ValueError('unknown_profile_stage')

    def decorate(function):
        if inspect.iscoroutinefunction(function):
            raise ValueError('async_profile_not_supported')
        @wraps(function)
        def wrapped(*args, **kwargs):
            trace = _current.get()
            if trace is None or trace.closed:
                return function(*args, **kwargs)  # No clock or sample creation when disabled.
            with trace.stage(name):
                return function(*args, **kwargs)
        return wrapped
    return decorate
