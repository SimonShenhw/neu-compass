"""One finite-sample nearest-rank latency convention for all new reports."""

import math
import statistics


def percentile(samples, p):
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
        raise ValueError('invalid_percentile')
    values = list(samples)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values):
        raise ValueError('invalid_latency_sample')
    if not values:
        return None
    values.sort()
    return float(values[max(0, math.ceil(len(values) * p) - 1)])


def latency_summary(samples):
    values = list(samples)
    percentiles = {f'p{int(p * 100)}': percentile(values, p) for p in (.5, .95, .99)}
    return dict(n=len(values), method='nearest_rank', **percentiles,
                mean=statistics.mean(values) if values else None)
