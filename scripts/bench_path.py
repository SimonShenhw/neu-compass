"""Benchmark SQLite + FAISS-like file I/O on Windows H: drive vs WSL2 home.

Validates ADR-0014 path strategy. Decision rule (per ADR):
  - If WSL home is >20% faster on real workloads -> keep code on H:,
    runtime data in WSL home (current decision).
  - If difference is <20% -> simplify to single path, code + data on H:.

Run from inside WSL2:
    uv run python scripts/bench_path.py

Output goes to stdout + writes a markdown table to docs/path_decision.md
which the team commits as the empirical record behind ADR-0014.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Default candidates. Override via --paths.
DEFAULT_CANDIDATES: list[tuple[str, Path]] = [
    ("H_drive_NTFS", Path("/mnt/h/neu-compass-bench")),
    ("WSL_home_ext4", Path.home() / "neu-compass-bench"),
]

SQLITE_INSERT_SQL = """
CREATE TABLE IF NOT EXISTS bench (
    id INTEGER PRIMARY KEY,
    payload TEXT,
    metadata JSON
);
"""

PAYLOAD = "x" * 1024  # 1 KB row
ROWS_PER_BATCH = 1000
BATCHES = 5


def bench_sqlite(db_path: Path) -> dict[str, float]:
    """Insert + indexed query latency. Returns {writes_ms, queries_ms} per batch."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(SQLITE_INSERT_SQL)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_payload ON bench(payload)")
    conn.commit()

    write_times = []
    for batch in range(BATCHES):
        start = time.perf_counter()
        conn.executemany(
            "INSERT INTO bench (payload, metadata) VALUES (?, json(?))",
            [
                (f"{PAYLOAD}_{batch}_{i}", '{"k": ' + str(i) + "}")
                for i in range(ROWS_PER_BATCH)
            ],
        )
        conn.commit()
        write_times.append((time.perf_counter() - start) * 1000)

    query_times = []
    for batch in range(BATCHES):
        target = f"{PAYLOAD}_{batch}_500"
        start = time.perf_counter()
        rows = conn.execute("SELECT id FROM bench WHERE payload = ?", (target,)).fetchall()
        query_times.append((time.perf_counter() - start) * 1000)
        assert len(rows) == 1, f"sanity: expected 1 hit, got {len(rows)}"

    conn.close()
    db_path.unlink()

    return {
        "write_p50_ms": statistics.median(write_times),
        "write_max_ms": max(write_times),
        "query_p50_ms": statistics.median(query_times),
        "query_max_ms": max(query_times),
    }


def bench_seq_io(scratch_dir: Path, total_mb: int = 50) -> dict[str, float]:
    """Sequential write + read of a `total_mb` blob (proxies FAISS index file)."""
    scratch_dir.mkdir(parents=True, exist_ok=True)
    blob_path = scratch_dir / "bench.blob"
    blob = b"\xa5" * (1024 * 1024)  # 1 MB chunk

    start = time.perf_counter()
    with open(blob_path, "wb") as f:
        for _ in range(total_mb):
            f.write(blob)
        f.flush()
        os.fsync(f.fileno())
    write_s = time.perf_counter() - start

    start = time.perf_counter()
    with open(blob_path, "rb") as f:
        while f.read(1024 * 1024):
            pass
    read_s = time.perf_counter() - start

    blob_path.unlink()

    return {
        f"seq_write_{total_mb}MB_s": write_s,
        f"seq_read_{total_mb}MB_s": read_s,
        f"seq_write_MBps": total_mb / write_s,
        f"seq_read_MBps": total_mb / read_s,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--paths", nargs="*", default=None,
        help="Override path candidates: 'name=path' pairs, e.g. h=/mnt/h/foo wsl=/home/x/foo",
    )
    parser.add_argument("--blob-mb", type=int, default=50)
    parser.add_argument(
        "--write-decision", action="store_true",
        help="Write summary to docs/path_decision.md",
    )
    args = parser.parse_args()

    candidates: list[tuple[str, Path]]
    if args.paths:
        candidates = []
        for spec in args.paths:
            name, _, p = spec.partition("=")
            candidates.append((name, Path(p)))
    else:
        candidates = DEFAULT_CANDIDATES

    print(f"=> Benchmarking {len(candidates)} path(s)")
    print(f"   workload: {ROWS_PER_BATCH} rows x {BATCHES} batches SQLite + {args.blob_mb}MB seq I/O\n")

    results: dict[str, dict[str, float]] = {}
    for name, path in candidates:
        try:
            print(f"[{name}] {path}")
            sqlite_metrics = bench_sqlite(path / "bench.db")
            io_metrics = bench_seq_io(path, total_mb=args.blob_mb)
            results[name] = {**sqlite_metrics, **io_metrics}
            for k, v in results[name].items():
                print(f"   {k}: {v:.2f}")
        except Exception as e:
            print(f"   ERROR: {type(e).__name__}: {e}")
            results[name] = {"error": str(e)}  # type: ignore[dict-item]
        print()

    if args.write_decision and len(results) >= 2:
        _write_decision_doc(results)

    return 0


def _write_decision_doc(results: dict[str, dict]) -> None:
    """Render results to docs/path_decision.md as ADR-0014 supporting evidence."""
    out_path = PROJECT_ROOT / "docs" / "path_decision.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    metrics_seen = sorted({k for r in results.values() for k in r if "error" not in str(k)})

    lines = [
        "# Path Strategy Benchmark (ADR-0014 evidence)",
        "",
        f"Generated by `scripts/bench_path.py` on {time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        "",
        "| metric | " + " | ".join(results.keys()) + " |",
        "|---|" + "---|" * len(results),
    ]
    for metric in metrics_seen:
        row = [metric]
        for name in results:
            val = results[name].get(metric, "—")
            row.append(f"{val:.2f}" if isinstance(val, (int, float)) else str(val))
        lines.append("| " + " | ".join(row) + " |")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"=> wrote {out_path}")


if __name__ == "__main__":
    sys.exit(main())
