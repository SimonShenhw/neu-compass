"""Probe inference latency end-to-end across backends.

Hits a running uvicorn (default http://localhost:8000) with N synthetic
+ real-shape queries and reports p50/p95/p99 of /search latency_ms. Used
to compare PyTorch vs ONNX vs ONNX+TRT vs torch.compile after switching
backends in .env per docs/tensorrt_runbook.md.

Run sequence (typical Week 9 verification):
    1. INFERENCE_BACKEND=pytorch                    → baseline
       uv run uvicorn api.main:app & sleep 75
       uv run python scripts/probe_inference_latency.py --label baseline
       kill %1

    2. INFERENCE_BACKEND=pytorch + ENABLE_TORCH_COMPILE=true   → Day 2
       uv run python scripts/probe_inference_latency.py --label pytorch+compile

    3. INFERENCE_BACKEND=onnx + ONNX_PROVIDERS=CUDAExecutionProvider  → Day 1 part 1
       uv run python scripts/probe_inference_latency.py --label onnx+cuda

    4. INFERENCE_BACKEND=onnx + ONNX_PROVIDERS=TensorrtExecutionProvider  → Day 1 part 2
       uv run python scripts/probe_inference_latency.py --label onnx+trt

Output (also written to ~/neu-compass-data/latency_probe_<label>.json):

    label               n   p50 ms   p95 ms   p99 ms   mean ms
    baseline           50    47.20    51.84    58.31    47.92
    pytorch+compile    50    36.41    41.12    45.66    37.04
    onnx+cuda          50    29.88    34.22    38.71    30.43
    onnx+trt           50    17.01    20.55    24.81    17.62

Usage:
    uv run python scripts/probe_inference_latency.py
    uv run python scripts/probe_inference_latency.py --n 100 --label trt-fp16
    uv run python scripts/probe_inference_latency.py --base-url https://api.neu-compass.me
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

# Realistic NEU-Compass query mix: short alias, code lookup, NL, multilingual.
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


def _post_search(
    base_url: str,
    query: str,
    *,
    timeout: float,
) -> dict[str, Any]:
    """One /search call. Returns the response JSON. Raises on non-200."""
    import httpx  # noqa: PLC0415

    resp = httpx.post(
        f"{base_url.rstrip('/')}/search",
        json={"query": query, "k": 5},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def _percentile(samples: list[float], p: float) -> float:
    """No external deps — interpolated percentile."""
    if not samples:
        return 0.0
    sorted_s = sorted(samples)
    k = (len(sorted_s) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_s) - 1)
    if f == c:
        return sorted_s[f]
    return sorted_s[f] + (sorted_s[c] - sorted_s[f]) * (k - f)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--n", type=int, default=50, help="Number of queries to send")
    parser.add_argument(
        "--label",
        default="probe",
        help="Label for the output JSON file (latency_probe_<label>.json)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path.home() / "neu-compass-data",
        help="Where to write the JSON dump",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=3,
        help="Discard the first K calls (model warm + caches priming)",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # === Quick liveness check ===
    try:
        import httpx  # noqa: PLC0415

        ready = httpx.get(f"{args.base_url}/ready", timeout=5.0).json()
        print(
            f"=> /ready: {ready.get('status')}  "
            f"courses_indexed={ready.get('courses_indexed')}"
        )
        if ready.get("status") != "ready":
            print(
                f"!! API not ready (status={ready.get('status')}). "
                "Wait for warmup and rerun.",
                file=sys.stderr,
            )
            return 1
    except Exception as e:
        print(f"!! Could not reach {args.base_url}/ready: {e}", file=sys.stderr)
        return 2

    # === Sample queries ===
    queries: list[str] = []
    while len(queries) < args.n:
        queries.extend(SAMPLE_QUERIES)
    queries = queries[: args.n]

    print(f"=> Probing {args.n} queries (warmup={args.warmup}) at {args.base_url}")

    server_latencies_ms: list[float] = []
    client_latencies_ms: list[float] = []
    matched_via_counts: dict[str, int] = {}
    errors = 0

    for i, q in enumerate(queries, start=1):
        t0 = time.perf_counter()
        try:
            payload = _post_search(args.base_url, q, timeout=args.timeout)
        except Exception as e:
            errors += 1
            print(f"  [{i:3d}/{args.n}] ERROR: {e}", file=sys.stderr)
            continue
        client_ms = (time.perf_counter() - t0) * 1000

        if i <= args.warmup:
            continue  # discard

        server_latencies_ms.append(payload.get("latency_ms", 0.0))
        client_latencies_ms.append(client_ms)
        mv = payload.get("matched_via", "?")
        matched_via_counts[mv] = matched_via_counts.get(mv, 0) + 1

    if not server_latencies_ms:
        print("!! No successful samples after warmup. Aborting.", file=sys.stderr)
        return 3

    # === Stats ===
    def _stats(samples: list[float], name: str) -> dict[str, float]:
        return {
            f"{name}_n": float(len(samples)),
            f"{name}_p50_ms": _percentile(samples, 0.50),
            f"{name}_p95_ms": _percentile(samples, 0.95),
            f"{name}_p99_ms": _percentile(samples, 0.99),
            f"{name}_mean_ms": statistics.mean(samples),
            f"{name}_min_ms": min(samples),
            f"{name}_max_ms": max(samples),
        }

    summary: dict[str, Any] = {
        "label": args.label,
        "base_url": args.base_url,
        "n": len(server_latencies_ms),
        "warmup_skipped": args.warmup,
        "errors": errors,
        "matched_via": matched_via_counts,
        **_stats(server_latencies_ms, "server"),
        **_stats(client_latencies_ms, "client"),
    }

    # === Print ===
    print()
    print(f"=== {args.label} ===")
    print(f"  n={summary['n']}, errors={errors}")
    print(f"  server p50 / p95 / p99 / mean (ms) : "
          f"{summary['server_p50_ms']:7.2f} / "
          f"{summary['server_p95_ms']:7.2f} / "
          f"{summary['server_p99_ms']:7.2f} / "
          f"{summary['server_mean_ms']:7.2f}")
    print(f"  client p50 / p95 / p99 / mean (ms) : "
          f"{summary['client_p50_ms']:7.2f} / "
          f"{summary['client_p95_ms']:7.2f} / "
          f"{summary['client_p99_ms']:7.2f} / "
          f"{summary['client_mean_ms']:7.2f}")
    print(f"  matched_via : {matched_via_counts}")
    print()

    # === Persist ===
    out_path = args.out_dir / f"latency_probe_{args.label}.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"=> wrote {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
