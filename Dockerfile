# syntax=docker/dockerfile:1.7
#
# NEU-Compass production image. The same image serves both the FastAPI
# backend and the Streamlit UI — `command:` in docker-compose.yml picks
# which entrypoint each container runs.
#
# Built for NAS deploy (UGREEN DXP 6800 Pro: i5-1235U + Iris Xe 80EU,
# dual-channel DDR5). ONNX Runtime with OpenVINO EP + Intel iGPU drivers
# replaces the PyTorch+CUDA path that runs on the dev box. The runtime
# stage installs Intel compute-runtime (intel-opencl-icd +
# intel-level-zero-gpu) so OpenVINO can target Iris Xe via /dev/dri
# instead of falling back to CPU (8x latency penalty observed pre-fix).
# See docs/tensorrt_runbook.md §1.2 for EP choice.
#
# Base: bookworm (Debian 12), NOT trixie. Trixie dropped intel-opencl-icd
# and intel-level-zero-gpu from the archive; bookworm has them in
# non-free-firmware. Keep both stages on the same Debian version to avoid
# libc / libstdc++ mismatches across the venv copy.

FROM python:3.12-slim-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./

# Image-slim exclusions (ADR-0023). The NAS runs ONLY the OpenVINO path —
# the locked CUDA torch (+ its nvidia-*/triton train, ~6GB installed) and
# the scraper/eval-only heavies never execute in this image. uv's
# --no-install-package skips them WITHOUT touching uv.lock, so the PC dev
# venv resolution is completely unaffected. torch itself is replaced by
# the CPU wheel below (optimum-intel imports torch unconditionally; the
# tokenizers only pack tensors with it).
ARG SLIM_EXCLUDES="--no-install-package torch --no-install-package triton \
    --no-install-package nvidia-cublas-cu12 --no-install-package nvidia-cuda-cupti-cu12 \
    --no-install-package nvidia-cuda-nvrtc-cu12 --no-install-package nvidia-cuda-runtime-cu12 \
    --no-install-package nvidia-cudnn-cu12 --no-install-package nvidia-cufft-cu12 \
    --no-install-package nvidia-cufile-cu12 --no-install-package nvidia-curand-cu12 \
    --no-install-package nvidia-cusolver-cu12 --no-install-package nvidia-cusparse-cu12 \
    --no-install-package nvidia-cusparselt-cu12 --no-install-package nvidia-nccl-cu12 \
    --no-install-package nvidia-nvjitlink-cu12 --no-install-package nvidia-nvshmem-cu12 \
    --no-install-package nvidia-nvtx-cu12 \
    --no-install-package playwright --no-install-package pymupdf \
    --no-install-package ragas --no-install-package deepeval \
    --no-install-package datasets"
# pyarrow is NOT excludable: it's a hard dependency of streamlit itself —
# st.write_stream imports streamlit/dataframe_util which does
# `import pyarrow` unconditionally. Excluding it (ADR-0023 v1) crashed the
# UI container's chat path with ModuleNotFoundError on the FIRST prod use
# (eval drives the API directly and never caught it). ~150MB, worth it.

# Install locked runtime deps. We skip the `onnx` extra here because we want
# onnxruntime-openvino (Intel-flavor) instead of the generic onnxruntime that
# the extra pulls in. PC dev still uses the `onnx` extra + onnxruntime-gpu.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev $SLIM_EXCLUDES

COPY . .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev $SLIM_EXCLUDES

# CPU torch BEFORE optimum-intel: optimum's torch dependency is then already
# satisfied, so the CUDA wheel never enters the image. ~200MB vs ~6GB.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --no-cache torch --index-url https://download.pytorch.org/whl/cpu

# Layer in OpenVINO-native inference deps LAST. These are added via
# `uv pip install` (not the lock) because they're platform-specific —
# PC dev still uses onnxruntime-gpu via the `onnx` extra. Must run AFTER the
# final `uv sync` so that sync doesn't prune them as out-of-lock extras.
#
# We use `optimum-intel[openvino]` for direct OpenVINO IR inference (NOT
# onnxruntime-openvino which routes via ONNX intermediate and breaks on
# Intel GPU compile for bge-m3's u8 GatherND op). See rag/openvino_backend.py.
# NO upper bound on purpose (2026-06-12 lesson): pinning optimum<2 DOWNGRADED
# the resolution to an old 1.x whose onnx model_patcher imports
# `_attention_scale` from torch.onnx.symbolic_opset14 — removed in current
# torch — and the api crash-looped at boot. The working production stack is
# optimum 2.x INFERENCE path (the PC-side 2.x incompatibility was the
# optimum-onnx EXPORT path with transformers 4.57, a different code path).
# These install outside uv.lock, so drift risk exists either way; if a
# future rebuild breaks here, pin to the exact versions of the last good
# image rather than guessing a range. Known-good as of 2026-06-12:
#   optimum 2.2.0 / optimum-intel 2.0.0 / torch 2.12.0+cpu / transformers 4.57.6
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --no-cache \
        "optimum-intel[openvino]>=1.21" \
        "optimum>=1.20"

# --- Runtime ---
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Add non-free + non-free-firmware components so we can pull Intel's
# OpenCL ICD. Then install:
#   - intel-opencl-icd       — OpenCL driver for Intel GPU (Iris Xe / UHD)
#   - ocl-icd-libopencl1     — OpenCL ICD loader (transitively pulled, listed for clarity)
#   - libgomp1, curl, ca-certificates — original deps (OpenMP, healthcheck, TLS)
#
# Note: we'd prefer intel-level-zero-gpu (OneAPI standard, what OpenVINO
# 2024+ prefers) but Debian bookworm/trixie don't ship it. OpenCL path is
# functional on Iris Xe + Alder Lake and gives nearly the same perf as
# Level Zero for our inference workload.
RUN sed -i 's/^Components: main$/Components: main contrib non-free non-free-firmware/' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
        intel-opencl-icd \
        ocl-icd-libopencl1 \
        libgomp1 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app /app

# api: 8000, ui: 8501. cloudflared talks to these by service name on the
# compose network, not via host ports.
EXPOSE 8000 8501

# Default command runs the API. docker-compose.yml overrides for the UI service.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
