"""Streamlit page: retrieval eval metrics over time.

Reads JSON results from `eval/results/` (created via
`run_eval.py --out-json eval/results/<timestamp>.json`).

Run:
    uv run streamlit run app/eval_dashboard.py

PLAN §5 Week 5 deliverable. Lightweight; serves as a model for the
larger Streamlit MVP coming Week 6.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_RESULTS_DIR = PROJECT_ROOT / "eval" / "results"


def load_results(results_dir: Path) -> list[tuple[Path, dict]]:
    """Load all eval JSON files in `results_dir`. Returns sorted newest first."""
    if not results_dir.exists():
        return []
    files = sorted(
        results_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    out: list[tuple[Path, dict]] = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            out.append((f, data))
        except Exception:
            continue
    return out


def history_summary(results: list[tuple[Path, dict]]) -> list[dict]:
    """Flatten the (path, data) list into a per-run row for tabular display."""
    rows = []
    for path, data in results:
        summary = data.get("summary", {})
        rows.append({
            "file": path.stem,
            "recall_at_5": summary.get("recall_at_5", 0.0),
            "mrr": summary.get("mrr", 0.0),
            "queries_total": summary.get("total_queries", 0),
            "queries_with_expected": summary.get("queries_with_expected", 0),
        })
    return rows


def render(results_dir: Path = DEFAULT_RESULTS_DIR) -> None:
    """Render the dashboard. Imported lazily so import-time doesn't trigger
    Streamlit's session machinery (matters for the test that just imports
    this module)."""
    import streamlit as st  # noqa: PLC0415

    st.set_page_config(page_title="NEU-Compass Eval Dashboard", layout="wide")
    st.title("NEU-Compass · Retrieval Eval Dashboard")

    results = load_results(results_dir)
    if not results:
        st.warning(
            f"No eval results found at `{results_dir}`. "
            "Run `uv run python eval/run_eval.py --out-json "
            f"{results_dir}/run_001.json`"
        )
        return

    latest_path, latest_data = results[0]
    summary = latest_data.get("summary", {})

    # === Latest run ===
    st.header(f"Latest run: `{latest_path.stem}`")
    col1, col2, col3 = st.columns(3)
    col1.metric("Recall@5", f"{summary.get('recall_at_5', 0.0):.3f}")
    col2.metric("MRR", f"{summary.get('mrr', 0.0):.3f}")
    col3.metric(
        "Queries (with expected / total)",
        f"{summary.get('queries_with_expected', 0)} / {summary.get('total_queries', 0)}",
    )

    # === Per-query breakdown ===
    st.subheader("Per-query breakdown (latest run)")
    per_q = latest_data.get("per_query", [])
    if per_q:
        st.dataframe(per_q, use_container_width=True)
    else:
        st.info("No per-query records in latest result file.")

    # === History ===
    if len(results) > 1:
        st.subheader("History (latest 10 runs)")
        history = history_summary(results[:10])
        st.dataframe(history, use_container_width=True)
        # Trend chart: Recall@5 + MRR
        try:
            import pandas as pd  # noqa: PLC0415
            df = pd.DataFrame(history).set_index("file")
            st.line_chart(df[["recall_at_5", "mrr"]])
        except ImportError:
            st.info("(pandas not available; skipping trend chart)")


# __main__ only (streamlit sets the main script's __name__): the old
# sys.argv clause executed render() whenever this module was merely
# IMPORTED under a running streamlit process — see coop_view double-render.
if __name__ == "__main__":
    render()
