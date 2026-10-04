"""Evaluate fixed labels against an explicitly chosen live /search endpoint.

NOT offline: requests can log queries and invoke HyDE/LLM. Use only after
target/data/cost approval. This fixed set is not organic traffic.
See docs/live-probe-contract.md before running.
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
    ProbeRun, SafeParser, input_failure, integer, load_cases, run_probe,
    validate_timeout, validate_url,
)
from eval.run_eval import run_eval  # noqa: E402


def _percentile(sorted_vals, pct):
    """Legacy helper only; new reports use null for empty samples."""
    value = percentile(sorted_vals, pct)
    return 0.0 if value is None else value


def cli(argv=None):
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--base-url', default='http://localhost:8000')
    parser.add_argument('--test-set', default=str(PROJECT_ROOT / 'eval/test_set.json'))
    parser.add_argument('--k', type=int, default=5)
    parser.add_argument('--label', default='api')
    parser.add_argument('--out-json', default=None, help='New private per-query artifact; never overwritten.')
    parser.add_argument('--timeout', type=float, default=60.)
    parser.add_argument('--warmup', type=int, default=1, help='First fixed query, K calls before measurement.')
    args = parser.parse_args(argv)
    try:
        data = load_cases(args.test_set, args.k)
        base_url = validate_url(args.base_url)
        timeout = validate_timeout(args.timeout)
        run = ProbeRun(label=args.label, warmup=integer(args.warmup, 0, 10_000),
                       measured=len(data['queries']), k=args.k)
        out_path = Path(args.out_json) if args.out_json else PROJECT_ROOT / 'eval' / f'api_eval_{run.label}.json'
    except Exception:
        print(json.dumps(input_failure()))
        return 2

    def execute():
        with httpx.Client(base_url=base_url, timeout=timeout, trust_env=False, follow_redirects=False) as client:
            run.ready(client)
            for _ in range(run.warmup_planned):
                run.search(client, data['queries'][0]['query'], warmup=True)
            return run_eval(data, lambda query: run.search(client, query), k=run.k).to_dict()

    return run_probe(run, execute, out_path=out_path, wrapped=True,
                     metadata={'label': run.label, 'test_set_version': data.get('version', 'unknown')})


if __name__ == '__main__':
    raise SystemExit(cli())
