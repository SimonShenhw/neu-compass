#!/usr/bin/env python3
"""Export BAAI/bge-m3 + bge-reranker-v2-m3 to OpenVINO IR.

Sister to `scripts/export_models_onnx.py` — same goal (FP16 weights for
fast inference) but exports OpenVINO IR directly via optimum-intel CLI,
bypassing the ONNX intermediate format.

Why this exists:
  ONNX export produces a u8 GatherND op that Intel GPU plugin can't
  compile (`No layout format available for gathernd: bfyx, u8`). The
  direct OpenVINO IR path uses int64 indices and compiles cleanly on
  Iris Xe / UHD / Arc GPUs.

Output structure (compatible with rag/openvino_backend.py):

  ~/neu-compass-data/openvino/
  ├── embedder/
  │   ├── openvino_model.xml    (graph topology)
  │   ├── openvino_model.bin    (FP16 weights, ~1.1GB)
  │   ├── tokenizer.json
  │   └── config.json
  └── reranker/
      └── ...

Usage:
  uv sync --extra openvino                            # one-time, adds optimum-intel
  uv run python scripts/export_openvino.py            # both models, fp16
  uv run python scripts/export_openvino.py --weight-format int8   # smaller, quantized

Setup notes:
  - First run downloads BAAI/bge-m3 (~1.1GB) + bge-reranker-v2-m3 (~570MB)
    from HuggingFace. Subsequent runs reuse the HF cache.
  - Export itself is CPU-only — no GPU needed on PC.
  - Total runtime ~5-10 min depending on HF Hub speed.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_OUT = Path.home() / "neu-compass-data" / "openvino"

MODELS = [
    ("BAAI/bge-m3", "embedder"),
    ("BAAI/bge-reranker-v2-m3", "reranker"),
]


def check_cli() -> None:
    """Verify `optimum-cli` is on PATH (installed via uv sync --extra openvino)."""
    if shutil.which("optimum-cli") is None:
        print(
            "ERROR: `optimum-cli` not found on PATH.\n"
            "Install with: uv sync --extra openvino",
            file=sys.stderr,
        )
        sys.exit(1)


def export(model_id: str, out_dir: Path, *, weight_format: str) -> None:
    """Run `optimum-cli export openvino` for one model.

    --trust-remote-code is needed for some models that ship custom code
    (bge-m3's pooling module). Safe for first-party BAAI models.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "optimum-cli", "export", "openvino",
        "--model", model_id,
        "--weight-format", weight_format,
        "--trust-remote-code",
        str(out_dir),
    ]
    print(f"\n→ exporting {model_id} → {out_dir}")
    print(f"  $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUT,
        help=f"output root dir (default: {DEFAULT_OUT})",
    )
    ap.add_argument(
        "--weight-format",
        default="fp16",
        choices=["fp16", "fp32", "int8", "int4"],
        help="weight precision (default: fp16 — good balance of size+quality)",
    )
    ap.add_argument(
        "--only",
        choices=["embedder", "reranker"],
        help="only export one of the two models (default: both)",
    )
    args = ap.parse_args()

    check_cli()

    targets = MODELS if args.only is None else [m for m in MODELS if m[1] == args.only]
    for model_id, subdir in targets:
        export(model_id, args.output / subdir, weight_format=args.weight_format)

    print(f"\n✓ Exported {len(targets)} model(s) to {args.output}")
    print("\nNext steps:")
    print(f"  1. Verify: ls {args.output}/embedder/openvino_model.xml")
    print(
        "  2. Transfer to NAS:  scripts\\deploy.ps1 -SyncData  "
        "(or tar-pipe the openvino/ subdir)"
    )
    print("  3. NAS compose env already points at /data/openvino — recreate api.")


if __name__ == "__main__":
    main()
