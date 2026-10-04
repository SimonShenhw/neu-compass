"""Probe a fixed curated query sequence against an approved live /search API.

NOT organic traffic and NOT offline: the endpoint may log queries or call LLMs.
--n keeps its historical meaning: TOTAL searches, including --warmup. Thus
--n 50 --warmup 3 measures 47 calls, not 50. No backend is switched by this tool.
See docs/live-probe-contract.md; historical benchmark files are not rewritten.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.latency_metrics import percentile  # noqa: E402
from eval.probe_contract import (  # noqa: E402
    ProbeRun, SafeParser, input_failure, integer, run_probe,
    validate_timeout, validate_url,
)

# Curated synthetic/real-shape strings, not observed user traffic or quality labels.
SAMPLE_QUERIES: tuple[str, ...] = (
    "CS 5800",
    "AAI 6600",
    "Algo",
    "easiest AI elective for ML beginner",
    "database management",
    "course on backprop",
    "应用 AI",
    "易学的 ML 课",
    "lightest workload statistics class",
    "online software engineering",
    "5200",
    "info-6105",
    "career change to data science prereq",
    "professor Durant",
    "no math heavy ML class",
    "DS 5230 vs DS 5500",
    "NLP fall 2026",
    "what is the AI policy",
    "graduate research methods",
    "evening class for working students",
)


def _percentile(samples, p):
    """Legacy helper; new canonical reports represent empty samples as null."""
    value = percentile(samples, p)
    return 0.0 if value is None else value


def main(argv=None):
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--base-url', default='http://localhost:8000')
    parser.add_argument('--n', type=int, default=50, help='TOTAL searches including warmup (historical contract).')
    parser.add_argument('--label', default='probe')
    parser.add_argument('--out-dir', type=Path, default=Path.home() / 'neu-compass-data',
                        help='Existing private directory; new latency_probe_<label>.json only.')
    parser.add_argument('--warmup', type=int, default=3, help='Initial searches excluded from measurements.')
    parser.add_argument('--timeout', type=float, default=30.)
    args = parser.parse_args(argv)
    try:
        total = integer(args.n, 1, 10_000)
        warmup = integer(args.warmup, 0, total - 1)
        base_url = validate_url(args.base_url)
        timeout = validate_timeout(args.timeout)
        run = ProbeRun(label=args.label, warmup=warmup, measured=total - warmup)
        out_path = args.out_dir / f'latency_probe_{run.label}.json'
    except Exception:
        print(json.dumps(input_failure()))
        return 2

    def execute():
        with httpx.Client(base_url=base_url, timeout=timeout, trust_env=False, follow_redirects=False) as client:
            run.ready(client)
            for i in range(total):
                run.search(client, SAMPLE_QUERIES[i % len(SAMPLE_QUERIES)], warmup=i < warmup)
        summary = run.summary()
        # Keep historical scalar keys for consumers; denominator is successful MEASURED calls.
        fields = dict(n=run.measured_succeeded, n_requested_total=total,
                      warmup_skipped=run.warmup_completed, errors=run.warmup_failed + run.measured_failed)
        for name, key in (('server', 'server_latency_ms'), ('client', 'wall_latency_ms')):
            for stat in ('n', 'p50', 'p95', 'p99', 'mean'):
                fields[f'{name}_{stat}' + ('' if stat == 'n' else '_ms')] = summary[key][stat]
            samples = run.server if name == 'server' else run.wall
            fields[f'{name}_min_ms'], fields[f'{name}_max_ms'] = min(samples), max(samples)
        return {'summary': fields}

    return run_probe(run, execute, out_path=out_path, metadata={'label': run.label})


if __name__ == '__main__':
    raise SystemExit(main())
