"""Export bge-m3 + bge-reranker-v2-m3 to ONNX format.

One-time setup per machine. Outputs go to `~/neu-compass-data/onnx/`
by default. ONNX files are LARGE (~2.3 GB embedder + ~1.2 GB reranker)
and are NOT committed to git — see docs/tensorrt_runbook.md for the
full pipeline (export → optional TensorRT engine build → API config).

Usage:
    uv sync --extra onnx                                   # one-time install
    uv run python scripts/export_models_onnx.py            # both models, FP32
    uv run python scripts/export_models_onnx.py --fp16     # FP16 (RECOMMENDED)
    uv run python scripts/export_models_onnx.py --output /custom/path
    uv run python scripts/export_models_onnx.py --skip-embedder --fp16

After export, set in .env:
    INFERENCE_BACKEND=onnx
    ONNX_MODEL_DIR=~/neu-compass-data/onnx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

EMBEDDER_MODEL = "BAAI/bge-m3"
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"


def _export_one(model_id: str, output_dir: Path, *, fp16: bool, task: str) -> None:
    """Drive optimum.exporters.onnx.main_export for one model.

    Lazy import so this script is even runnable from a venv without optimum
    installed yet — the import error tells the user to `uv sync --extra onnx`.
    """
    try:
        from optimum.exporters.onnx import main_export  # noqa: PLC0415
    except ImportError as e:
        print(
            "ERROR: `optimum` not installed. Run:\n"
            "    uv sync --extra onnx\n"
            f"(detail: {e})",
            file=sys.stderr,
        )
        raise SystemExit(1) from e

    output_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"=> Exporting {model_id} → {output_dir}\n"
        f"   task={task}  fp16={fp16}"
    )
    main_export(
        model_name_or_path=model_id,
        output=output_dir,
        task=task,
        # FP16 export requires GPU at export time. If user has no GPU, they
        # should run this on a machine with one or use the CPU-FP32 path.
        device="cuda" if fp16 else "cpu",
        dtype="fp16" if fp16 else "fp32",
        # Pin opset to a known-compatible version (TRT 10 supports opset 17-21).
        opset=17,
    )
    print(f"   ✓ {model_id} done\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.home() / "neu-compass-data" / "onnx",
        help="Output directory (will create subdirs `embedder/` and `reranker/`)",
    )
    parser.add_argument(
        "--fp16",
        action="store_true",
        help="Export in FP16 precision. Requires CUDA GPU. Saves ~50%% disk + ~50%% RAM at inference.",
    )
    parser.add_argument(
        "--skip-embedder",
        action="store_true",
        help="Skip bge-m3 export (e.g. you already have it).",
    )
    parser.add_argument(
        "--skip-reranker",
        action="store_true",
        help="Skip bge-reranker-v2-m3 export.",
    )
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    if not args.skip_embedder:
        _export_one(
            EMBEDDER_MODEL,
            args.output / "embedder",
            fp16=args.fp16,
            task="feature-extraction",
        )
    if not args.skip_reranker:
        _export_one(
            RERANKER_MODEL,
            args.output / "reranker",
            fp16=args.fp16,
            task="text-classification",
        )

    print(
        "=> All done.\n"
        "Set in .env to switch the API to ONNX backend:\n"
        f"    INFERENCE_BACKEND=onnx\n"
        f"    ONNX_MODEL_DIR={args.output}\n"
        "\n"
        "Then restart uvicorn. /ready will show `status=ready` once the\n"
        "ORT sessions are loaded + warmed.\n"
        "\n"
        "For TensorRT engine build (further latency reduction), see:\n"
        "    docs/tensorrt_runbook.md  §3 (trtexec)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
