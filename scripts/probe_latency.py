"""Measure /search latency end-to-end (Week 6 PLAN §4.1 acceptance: p50 < 300ms).

Builds the FastAPI app with REAL state — live FAISS index + bge-m3
embedder + BM25 corpus from the production SQLite path — and runs the
full eval/test_set.json through FastAPI TestClient. Reports p50 / p95 /
p99 / mean.

TestClient calls the ASGI app in-process (no HTTP socket round-trip), so
the number reflects retrieval + middleware + Pydantic serialization, but
NOT network. For end-to-end including LAN, run uvicorn locally and use
ab / wrk against the public URL.

Run:
    uv run python scripts/probe_latency.py
    uv run python scripts/probe_latency.py --warmup 5 --iterations 3 --k 10
    uv run python scripts/probe_latency.py --rerank
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--test-set", default=str(PROJECT_ROOT / "eval" / "test_set.json"),
    )
    p.add_argument("--warmup", type=int, default=3,
                   help="Warmup iterations (excluded from stats).")
    p.add_argument("--iterations", type=int, default=3,
                   help="Measurement iterations.")
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--rerank", action="store_true",
                   help="Wire bge-reranker-v2-m3 into app.state and pass through.")
    args = p.parse_args()

    test_set = json.loads(Path(args.test_set).read_text(encoding="utf-8"))
    queries = [q["query"] for q in test_set["queries"]]
    print(f"=> {len(queries)} queries × {args.iterations} iterations after {args.warmup} warmup")

    # Lazy imports — depend on the project being on sys.path (handled above)
    from fastapi.testclient import TestClient

    from api.dependencies import get_db_conn
    from api.main import create_app
    from config import settings
    from db.connection import connect
    from rag.embedder import BGEM3Embedder
    from rag.hybrid import BM25Corpus
    from rag.index import FaissIndex

    app = create_app(run_startup=False)

    print("=> loading FAISS")
    faiss_index = FaissIndex.load(settings.faiss_index_path)
    print(f"   index: {faiss_index.count} vectors")

    print("=> warming bge-m3 (first encode triggers ~70s model load)")
    embedder = BGEM3Embedder()
    embedder.encode(["warmup"])

    print("=> building BM25 corpus")
    bm25_conn = connect(settings.sqlite_path)
    try:
        bm25_corpus = BM25Corpus.from_db(bm25_conn)
        print(f"   bm25 corpus: {bm25_corpus.count} docs")
    finally:
        bm25_conn.close()

    app.state.embedder = embedder
    app.state.faiss_index = faiss_index
    app.state.bm25_corpus = bm25_corpus
    app.state.ready = True

    # Production get_db_conn opens a fresh conn per request — don't
    # override it. SQLite default check_same_thread=True is fine because
    # each request gets its own conn in its own threadpool worker.
    try:
        client = TestClient(app)

        print(f"=> warmup")
        for _ in range(args.warmup):
            for q in queries:
                r = client.post("/search", json={"query": q, "k": args.k})
                if r.status_code != 200:
                    print(f"   WARN: warmup got {r.status_code} for {q!r}")

        print(f"=> measuring")
        timings_ms: list[float] = []
        errors = 0
        for _ in range(args.iterations):
            for q in queries:
                t0 = time.perf_counter()
                r = client.post("/search", json={"query": q, "k": args.k})
                elapsed = (time.perf_counter() - t0) * 1000
                if r.status_code != 200:
                    errors += 1
                else:
                    timings_ms.append(elapsed)

        if not timings_ms:
            print("ERROR: no successful timings recorded", file=sys.stderr)
            return 2

        timings_ms.sort()
        n = len(timings_ms)
        p50 = timings_ms[int(n * 0.5)]
        p95 = timings_ms[max(0, int(n * 0.95) - 1)]
        p99 = timings_ms[max(0, int(n * 0.99) - 1)]
        mean = statistics.mean(timings_ms)
        std = statistics.stdev(timings_ms) if n > 1 else 0.0

        print()
        print(f"=== /search latency ({n} requests, {errors} errors) ===")
        print(f"  p50:  {p50:>7.1f} ms")
        print(f"  p95:  {p95:>7.1f} ms")
        print(f"  p99:  {p99:>7.1f} ms")
        print(f"  mean: {mean:>7.1f} ms (±{std:.1f})")
        print()
        target = 300.0
        verdict = "PASS" if p50 < target else "FAIL"
        print(f"  PLAN §4.1 target: p50 < {target:.0f} ms  →  {verdict}")
    finally:
        # Nothing process-wide to clean up — per-request conns are owned
        # by FastAPI's dependency lifecycle.
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
