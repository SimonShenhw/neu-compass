"""Tests for app.eval_dashboard — pure utility functions.

The Streamlit `render()` body is NOT exercised here (would need Streamlit's
test runtime). We cover the I/O helpers + summary builder.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.eval_dashboard import history_summary, load_results


# === load_results ===

def test_load_results_missing_dir(tmp_path: Path) -> None:
    assert load_results(tmp_path / "does-not-exist") == []


def test_load_results_empty_dir(tmp_path: Path) -> None:
    (tmp_path / "results").mkdir()
    assert load_results(tmp_path / "results") == []


def test_load_results_sorted_newest_first(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    import time

    older = results_dir / "older.json"
    older.write_text(json.dumps({"summary": {"recall_at_5": 0.5}}), encoding="utf-8")

    time.sleep(0.05)  # ensure mtime difference

    newer = results_dir / "newer.json"
    newer.write_text(json.dumps({"summary": {"recall_at_5": 0.8}}), encoding="utf-8")

    rows = load_results(results_dir)
    assert len(rows) == 2
    assert rows[0][0].name == "newer.json"
    assert rows[1][0].name == "older.json"


def test_load_results_skips_invalid_json(tmp_path: Path) -> None:
    """Corrupt JSON in results dir shouldn't crash the dashboard."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "bad.json").write_text("not valid json {{{", encoding="utf-8")
    (results_dir / "good.json").write_text(
        json.dumps({"summary": {"recall_at_5": 0.7}}), encoding="utf-8",
    )
    rows = load_results(results_dir)
    assert len(rows) == 1
    assert rows[0][0].name == "good.json"


# === history_summary ===

def test_history_summary_extracts_metrics(tmp_path: Path) -> None:
    fake_results = [
        (tmp_path / "r2.json", {
            "summary": {"recall_at_5": 0.8, "mrr": 0.7,
                         "total_queries": 10, "queries_with_expected": 8},
        }),
        (tmp_path / "r1.json", {
            "summary": {"recall_at_5": 0.5, "mrr": 0.4,
                         "total_queries": 10, "queries_with_expected": 8},
        }),
    ]
    rows = history_summary(fake_results)
    assert len(rows) == 2
    assert rows[0]["file"] == "r2"
    assert rows[0]["recall_at_5"] == 0.8
    assert rows[0]["mrr"] == 0.7
    assert rows[1]["recall_at_5"] == 0.5


def test_history_summary_handles_missing_summary(tmp_path: Path) -> None:
    """Older / partial result files without `summary` key shouldn't crash."""
    fake = [(tmp_path / "x.json", {})]
    rows = history_summary(fake)
    assert rows[0]["recall_at_5"] == 0.0
    assert rows[0]["mrr"] == 0.0


# === Module imports without Streamlit running ===

def test_module_import_does_not_trigger_streamlit() -> None:
    """`import app.eval_dashboard` from a test must not blow up because
    Streamlit isn't running. The render() body must be guarded."""
    import app.eval_dashboard  # noqa: F401
    # If we got here, the guard worked.
