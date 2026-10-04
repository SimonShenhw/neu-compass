"""Sequential opt-in profiling over validated fixed queries and a caller adapter."""

import math
import time

from eval.latency_metrics import latency_summary
from eval.run_eval import run_eval, validate_test_set
from rag.profiling import collect_profile


def profile_eval(test_set, search_fn, *, k=5, warmup=1, iterations=3, trace=True, clock=None):
    entries = validate_test_set(test_set, k=k)
    frozen = {'queries': entries}
    if (type(warmup) is not int or not 0 <= warmup <= 10 or type(iterations) is not int
            or not 1 <= iterations <= 20 or type(trace) is not bool or not entries):
        raise ValueError('invalid_profile_run')
    if len(entries) * (warmup + iterations) > 10_000:
        raise ValueError('profile_call_budget')
    clock = clock or time.perf_counter_ns
    for _ in range(warmup):
        run_eval(frozen, search_fn, k=k)  # Warmup failures abort, never get discarded as successes.
    samples, reports = [], []
    for _ in range(iterations):
        def measured(query):
            start = clock()
            if type(start) is not int:
                raise ValueError('invalid_profile_clock')
            if trace:
                with collect_profile(clock=clock) as timings:
                    result = search_fn(query)
                components = timings.totals()
                accounted_ns = timings.exclusive_ns
            else:
                result, components = search_fn(query), {}
                accounted_ns = 0
            elapsed = clock() - start
            if type(elapsed) is not int or elapsed < 0:
                raise ValueError('invalid_profile_clock')
            wall = elapsed / 1_000_000
            if accounted_ns > elapsed or not math.isfinite(wall):
                raise ValueError('overlapping_profile_samples')
            samples.append(dict(wall_ms=wall, stages=components,
                                uninstrumented_ms=(elapsed - accounted_ns) / 1_000_000))
            return result

        reports.append(run_eval(frozen, measured, k=k))
    stages = {}
    names = sorted({name for sample in samples for name in sample['stages']})
    for name in names:
        active = [s['stages'][name] for s in samples if name in s['stages']]
        stages[name] = dict(samples_present=len(active), samples_absent=len(samples) - len(active),
            calls=sum(row['calls'] for row in active),
            inclusive_ms=latency_summary(row['inclusive_ms'] for row in active),
            exclusive_ms=latency_summary(row['exclusive_ms'] for row in active))
    return dict(format_version=1, measured_calls=len(samples), warmup_calls=len(entries) * warmup,
        iterations=iterations, k=k, trace_enabled=trace, quality_improvement_verified=False,
        quality_runs=[report.to_dict()['summary'] for report in reports],
        ranking_stable=all([q.retrieved for q in report.per_query] == [q.retrieved for q in reports[0].per_query]
                           for report in reports[1:]),
        wall_ms=latency_summary(sample['wall_ms'] for sample in samples), stages=stages,
        uninstrumented_ms=latency_summary(sample['uninstrumented_ms'] for sample in samples),
        limitations=['caller_adapter_determines_scope_and_may_have_side_effects',
            'not_live_distribution_or_model_quality_or_sla', 'sequential_synchronous_calls_only',
            'inclusive_stage_percentiles_are_not_additive', 'uninstrumented_time_is_not_network_latency'])
