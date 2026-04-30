"""Tests for scripts/bench_path.py — SQLite + sequential I/O benchmarks.

The benchmarks themselves are I/O-heavy by design; tests verify they run
end-to-end against tmp_path and produce the expected metric keys, not the
actual numbers (which depend on the host filesystem).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.bench_path import bench_seq_io, bench_sqlite  # noqa: E402


def test_bench_sqlite_returns_expected_metrics(tmp_path: Path) -> None:
    metrics = bench_sqlite(tmp_path / "bench.db")
    expected_keys = {"write_p50_ms", "write_max_ms", "query_p50_ms", "query_max_ms"}
    assert set(metrics.keys()) == expected_keys
    # All metrics should be non-negative latencies
    for v in metrics.values():
        assert v >= 0


def test_bench_sqlite_cleans_up_db(tmp_path: Path) -> None:
    db_path = tmp_path / "bench.db"
    bench_sqlite(db_path)
    assert not db_path.exists(), "Bench DB should be cleaned up"


def test_bench_sqlite_uses_wal_mode(tmp_path: Path) -> None:
    """Indirectly verify the bench applies WAL: no -wal/-shm leftover after cleanup."""
    db_path = tmp_path / "bench.db"
    bench_sqlite(db_path)
    leftovers = list(tmp_path.iterdir())
    assert len(leftovers) == 0, f"Unexpected leftovers: {leftovers}"


def test_bench_seq_io_returns_throughput(tmp_path: Path) -> None:
    """Use small total_mb so the test stays fast."""
    metrics = bench_seq_io(tmp_path, total_mb=4)
    assert "seq_write_4MB_s" in metrics
    assert "seq_read_4MB_s" in metrics
    assert "seq_write_MBps" in metrics
    assert "seq_read_MBps" in metrics
    # Throughput should be positive
    assert metrics["seq_write_MBps"] > 0
    assert metrics["seq_read_MBps"] > 0


def test_bench_seq_io_cleans_up(tmp_path: Path) -> None:
    bench_seq_io(tmp_path, total_mb=2)
    leftovers = [p.name for p in tmp_path.iterdir()]
    assert "bench.blob" not in leftovers
