"""Export bge-m3 + bge-reranker-v2-m3 to ONNX format (torch.onnx native).

One-time setup per machine. Outputs go to `~/neu-compass-data/onnx/` by
default. ONNX files are LARGE (~2.3 GB embedder + ~1.2 GB reranker) and
are NOT committed to git — see docs/tensorrt_runbook.md.

History: this script first used `optimum.exporters.onnx.main_export`,
but optimum 2.x split that into a separate `optimum-onnx` package whose
0.1.0 release pinned an internal `transformers.modeling_utils.get_parameter_dtype`
import that doesn't exist in transformers 4.57+. Going through torch.onnx
directly avoids the entire optimum dep tree — only needs `transformers`
+ `torch` + `onnx` (already in our base + onnx extra).

Usage:
    uv sync --extra onnx                                        # one-time install
    uv run python scripts/export_models_onnx.py                 # FP16 GPU, default
    uv run python scripts/export_models_onnx.py --dtype fp32    # CPU fallback
    uv run python scripts/export_models_onnx.py --output /custom/path
    uv run python scripts/export_models_onnx.py --skip-embedder

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


def _device_dtype(device: str, dtype: str) -> tuple[str, "object"]:
    """Resolve --device/--dtype CLI args into (torch_device, torch_dtype)."""
    import torch  # noqa: PLC0415

    torch_dtype = {"fp32": torch.float32, "fp16": torch.float16}[dtype]
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu" and dtype == "fp16":
        # FP16 on CPU is usually 2-3x SLOWER than FP32 on CPU (no AVX-VNNI
        # acceleration in PyTorch's default CPU kernels). Warn + downgrade.
        print(
            "warning: FP16 on CPU is slower than FP32. Forcing dtype=fp32. "
            "Use --device cuda to keep fp16, or --dtype fp32 to silence this."
        )
        torch_dtype = torch.float32
    return device, torch_dtype


def export_embedder(output_dir: Path, *, device: str, dtype: str) -> None:
    """Export bge-m3 → ONNX. Output is the raw XLM-RoBERTa backbone forward
    (input_ids + attention_mask → last_hidden_state); CLS pool + L2 normalize
    happen at runtime in rag.onnx_backend.OnnxEmbedder.encode."""
    import torch  # noqa: PLC0415
    from transformers import AutoModel, AutoTokenizer  # noqa: PLC0415

    output_dir.mkdir(parents=True, exist_ok=True)
    torch_device, torch_dtype = _device_dtype(device, dtype)

    print(f"=> Loading {EMBEDDER_MODEL} ({torch_device}, {dtype})")
    tokenizer = AutoTokenizer.from_pretrained(EMBEDDER_MODEL)
    model = AutoModel.from_pretrained(EMBEDDER_MODEL).eval().to(torch_device)
    if torch_dtype == torch.float16:
        model = model.half()

    # Dummy input for tracing. Use 2 sequences of different (padded) length so
    # ONNX captures dynamic axes correctly. Max length 512 is the hard cap
    # we use at inference; tracing with smaller doesn't constrain runtime.
    dummy = tokenizer(
        ["hello world", "what is CS 5800"],
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    ).to(torch_device)

    onnx_path = output_dir / "model.onnx"
    print(f"=> torch.onnx.export → {onnx_path}")
    with torch.no_grad():
        torch.onnx.export(
            model,
            (dummy["input_ids"], dummy["attention_mask"]),
            str(onnx_path),
            input_names=["input_ids", "attention_mask"],
            output_names=["last_hidden_state"],
            dynamic_axes={
                "input_ids": {0: "batch", 1: "seq"},
                "attention_mask": {0: "batch", 1: "seq"},
                "last_hidden_state": {0: "batch", 1: "seq"},
            },
            opset_version=17,
            do_constant_folding=True,
        )

    tokenizer.save_pretrained(output_dir)
    print(f"   ✓ embedder ONNX + tokenizer in {output_dir}\n")


def export_reranker(output_dir: Path, *, device: str, dtype: str) -> None:
    """Export bge-reranker-v2-m3 → ONNX. Output is logits (batch, 1);
    sigmoid happens at runtime in rag.onnx_backend.OnnxReranker.score."""
    import torch  # noqa: PLC0415
    from transformers import (  # noqa: PLC0415
        AutoModelForSequenceClassification,
        AutoTokenizer,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    torch_device, torch_dtype = _device_dtype(device, dtype)

    print(f"=> Loading {RERANKER_MODEL} ({torch_device}, {dtype})")
    tokenizer = AutoTokenizer.from_pretrained(RERANKER_MODEL)
    model = (
        AutoModelForSequenceClassification.from_pretrained(RERANKER_MODEL)
        .eval()
        .to(torch_device)
    )
    if torch_dtype == torch.float16:
        model = model.half()

    # Cross-encoder dummy: tokenize (query, candidate) pairs together.
    dummy = tokenizer(
        ["query a", "query b"],
        ["candidate text one", "candidate text two"],
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    ).to(torch_device)

    onnx_path = output_dir / "model.onnx"
    print(f"=> torch.onnx.export → {onnx_path}")
    with torch.no_grad():
        torch.onnx.export(
            model,
            (dummy["input_ids"], dummy["attention_mask"]),
            str(onnx_path),
            input_names=["input_ids", "attention_mask"],
            output_names=["logits"],
            dynamic_axes={
                "input_ids": {0: "batch", 1: "seq"},
                "attention_mask": {0: "batch", 1: "seq"},
                "logits": {0: "batch"},
            },
            opset_version=17,
            do_constant_folding=True,
        )

    tokenizer.save_pretrained(output_dir)
    print(f"   ✓ reranker ONNX + tokenizer in {output_dir}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.home() / "neu-compass-data" / "onnx",
        help="Output dir (will create subdirs `embedder/` and `reranker/`)",
    )
    parser.add_argument(
        "--dtype",
        choices=("fp32", "fp16"),
        default="fp16",
        help="Precision. fp16 needs CUDA; fp32 is universal but ~2x bigger/slower.",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "cpu"),
        default="auto",
        help="auto = CUDA if available, else CPU.",
    )
    parser.add_argument("--skip-embedder", action="store_true")
    parser.add_argument("--skip-reranker", action="store_true")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    if not args.skip_embedder:
        export_embedder(args.output / "embedder", device=args.device, dtype=args.dtype)
    if not args.skip_reranker:
        export_reranker(args.output / "reranker", device=args.device, dtype=args.dtype)

    print(
        "=> All done.\n"
        "Set in .env to switch the API to ONNX backend:\n"
        f"    INFERENCE_BACKEND=onnx\n"
        f"    ONNX_MODEL_DIR={args.output}\n"
        "\n"
        "Then restart uvicorn. /ready will show `status=ready` once the\n"
        "ORT sessions are loaded + warmed.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
