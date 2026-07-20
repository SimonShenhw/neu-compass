"""Run the retrieval test set against a LIVE /search endpoint.

Why this exists (2026-06 optimization sprint): run_eval.py rebuilds the
retrieval stack in-process, which (a) needs working torch locally and
(b) measures a pipeline that is NOT the production path — it skips the
alias tier, Layer 2 prefix extraction, and the deployed backend entirely.
This script instead drives the deployed API (PC over Tailscale → NAS),
so R@5 / MRR / latency describe exactly what users get.

为什么需要这个脚本(2026-06 优化冲刺):run_eval.py 在进程内重建整套检索
栈,这样做 (a) 本地需要装好能跑的 torch,(b) 测的是一条根本不是生产
路径的流水线 —— 它完全跳过了别名(alias)层、Layer 2 前缀抽取,以及
实际部署的后端。这个脚本改为直接驱动已部署的 API(PC 通过 Tailscale
连到 NAS),这样 R@5 / MRR / 延迟描述的就是用户实际拿到的体验。

Usage (from project root, PC side):
    uv run python scripts/eval_via_api.py --base-url http://simonshen:8000 \
        --label pool20_fp16
    uv run python scripts/eval_via_api.py                  # localhost:8000

用法(项目根目录,PC 端):
    uv run python scripts/eval_via_api.py --base-url http://simonshen:8000 \
        --label pool20_fp16
    uv run python scripts/eval_via_api.py                  # localhost:8000

Output: text summary + eval/api_eval_<label>.json with per-query rows.
A/B workflow: change NAS config (e.g. RERANK_POOL_SIZE=10 in .env, or
OPENVINO_MODEL_DIR=/data/openvino_int8), `docker compose up -d api`,
re-run with a new --label, diff the JSONs.

输出:文本摘要 + eval/api_eval_<label>.json(含逐条查询的明细行)。
A/B 工作流:改动 NAS 配置(例如 .env 里的 RERANK_POOL_SIZE=10,或者
OPENVINO_MODEL_DIR=/data/openvino_int8)、执行 `docker compose up -d api`、
换一个新的 --label 重新跑一遍,然后 diff 两份 JSON。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Must come after the sys.path.insert above (E402 suppressed accordingly) —
# eval.run_eval only becomes importable once PROJECT_ROOT is on sys.path.
# 中文:必须写在上面 sys.path.insert 之后(因此抑制了 E402 告警)——
# eval.run_eval 只有在 PROJECT_ROOT 被加入 sys.path 之后才能被导入。
from eval.run_eval import run_eval  # noqa: E402


def _percentile(sorted_vals: list[float], pct: float) -> float:
    # Nearest-rank percentile on an already-sorted list — no interpolation,
    # good enough for eval reporting and avoids pulling in numpy just for
    # this one function.
    # 中文:对已排序列表取"最近秩"(nearest-rank)分位数 —— 不做插值,
    # 对评测报告而言已经足够,也省得为了这一个函数专门引入 numpy 依赖。
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, int(len(sorted_vals) * pct))
    return sorted_vals[idx]


def cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument(
        "--test-set",
        default=str(PROJECT_ROOT / "eval" / "test_set.json"),
    )
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--label", default="api", help="Tag for the output JSON filename")
    ap.add_argument("--out-json", default=None, help="Override output path")
    ap.add_argument(
        "--timeout", type=float, default=60.0,
        help="Per-request timeout (NAS cold path can take ~10s)",
    )
    args = ap.parse_args()

    test_set = json.loads(Path(args.test_set).read_text(encoding="utf-8"))
    base_url = args.base_url.rstrip("/")
    out_path = Path(
        args.out_json or PROJECT_ROOT / "eval" / f"api_eval_{args.label}.json"
    )

    server_latencies: list[float] = []
    wall_latencies: list[float] = []
    matched_via_counts: Counter[str] = Counter()

    # X-Eval-Run tags every request in the server's query_log as
    # 'eval:<label>' so eval traffic never pollutes organic-query mining
    # (the v0.5 real-distribution work depends on this split staying clean).
    # 中文:X-Eval-Run 会把这次的每个请求在服务端 query_log 里标记成
    # 'eval:<label>',这样评测流量就绝不会污染"真实自然查询"的挖掘工作
    # (v0.5 的真实分布研究依赖这个切分保持干净)。
    with httpx.Client(
        base_url=base_url, timeout=args.timeout,
        headers={"X-Eval-Run": args.label},
    ) as client:
        ready = client.get("/ready")
        if ready.status_code != 200:
            print(f"!! {base_url}/ready -> {ready.status_code}; aborting")
            return 1
        # One uncounted warmup so first-hit effects don't skew p95.
        # 中文:先做一次不计入统计的预热(warmup)请求,避免"第一次调用"
        # 的额外开销拉偏 p95。
        client.post("/search", json={"query": "warmup query", "k": args.k})

        def search_fn(q: str) -> list[str]:
            t0 = time.perf_counter()
            r = client.post("/search", json={"query": q, "k": args.k})
            wall_ms = (time.perf_counter() - t0) * 1000
            r.raise_for_status()
            body = r.json()
            wall_latencies.append(wall_ms)
            server_latencies.append(float(body.get("latency_ms", 0.0)))
            matched_via_counts[body.get("matched_via", "?")] += 1
            return [hit["course_id"] for hit in body.get("results", [])]

        report = run_eval(test_set, search_fn, k=args.k)

    sorted_server = sorted(server_latencies)
    sorted_wall = sorted(wall_latencies)
    summary = {
        "label": args.label,
        "base_url": base_url,
        "test_set_version": test_set.get("version", "unknown"),
        "k": args.k,
        "recall_at_5": round(report.recall_at_5, 4),
        "mrr": round(report.mrr, 4),
        "queries_with_expected": report.queries_with_expected,
        "matched_via": dict(matched_via_counts),
        "server_latency_ms": {
            "p50": round(_percentile(sorted_server, 0.50), 1),
            "p95": round(_percentile(sorted_server, 0.95), 1),
            "mean": round(statistics.mean(server_latencies), 1)
            if server_latencies else 0.0,
        },
        "wall_latency_ms": {
            "p50": round(_percentile(sorted_wall, 0.50), 1),
            "p95": round(_percentile(sorted_wall, 0.95), 1),
        },
    }

    out_path.write_text(
        json.dumps(
            {"summary": summary, "per_query": report.to_dict()["per_query"]},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"\n=== eval_via_api [{args.label}] @ {base_url} ===")
    print(f"  R@5  = {summary['recall_at_5']}")
    print(f"  MRR  = {summary['mrr']}")
    print(f"  matched_via = {summary['matched_via']}")
    print(
        f"  server latency p50/p95 = "
        f"{summary['server_latency_ms']['p50']} / "
        f"{summary['server_latency_ms']['p95']} ms"
    )
    print(f"  wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
