"""Probe in-process /search using real local DB/index/PyTorch models.

NOT offline: default dependencies log to the configured DB; rescue may invoke
external models. No network round-trip is included. --rerank explicitly loads
and warms bge-reranker-v2-m3; without it the app runs degraded hybrid.
See docs/live-probe-contract.md for authorization and sampling boundaries.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.probe_contract import (  # noqa: E402
    ProbeRun, SafeParser, input_failure, integer, load_cases, run_probe,
)


def _build_app(*, rerank):
    """Only called after plan validation; tests replace all runtime loaders."""
    from api.main import create_app
    from config import settings
    from db.connection import connect
    from rag.embedder import BGEM3Embedder
    from rag.hybrid import BM25Corpus
    from rag.index import FaissIndex
    from rag.reranker import CrossEncoderReranker

    app = create_app(run_startup=False)
    app.state.ready = False
    app.state.faiss_index = FaissIndex.load(settings.faiss_index_path)
    app.state.embedder = BGEM3Embedder()
    app.state.embedder.encode(['warmup'])
    conn = connect(settings.sqlite_path)
    try:
        app.state.bm25_corpus = BM25Corpus.from_db(conn)
    finally:
        conn.close()
    app.state.reranker = CrossEncoderReranker() if rerank else None
    if app.state.reranker is not None:
        app.state.reranker.score('warmup', ['warmup'])
    app.state.ready = True
    return app


def main(argv=None):
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--test-set', default=str(PROJECT_ROOT / 'eval/test_set.json'))
    parser.add_argument('--warmup', type=int, default=3, help='Whole fixed-set warmup iterations.')
    parser.add_argument('--iterations', type=int, default=3, help='Whole fixed-set measured iterations.')
    parser.add_argument('--k', type=int, default=10)
    parser.add_argument('--rerank', action='store_true')
    parser.add_argument('--label', default='inprocess-probe')
    args = parser.parse_args(argv)
    try:
        data = load_cases(args.test_set, args.k)
        queries = [case['query'] for case in data['queries']]
        warmup = integer(args.warmup, 0, 10_000)
        iterations = integer(args.iterations, 1, 10_000)
        run = ProbeRun(label=args.label, warmup=warmup * len(queries),
                       measured=iterations * len(queries), k=args.k)
    except Exception:
        print(json.dumps(input_failure()))
        return 2

    def execute():
        from fastapi.testclient import TestClient
        app = _build_app(rerank=args.rerank)
        with TestClient(app) as client:
            run.ready(client)
            for _ in range(warmup):
                for query in queries:
                    run.search(client, query, warmup=True)
            for _ in range(iterations):
                for query in queries:
                    run.search(client, query)
        p50 = run.summary()['wall_latency_ms']['p50']
        return {'summary': dict(rerank_enabled=args.rerank, backend='local_pytorch',
                                timing_scope='asgi_in_process_no_network', target_p50_ms=300.,
                                target_met=p50 < 300.)}

    return run_probe(run, execute)


if __name__ == '__main__':
    raise SystemExit(main())
