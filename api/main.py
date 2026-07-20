"""FastAPI app factory + lifespan pre-warm.

FastAPI 应用工厂 + lifespan 预热。

The pre-warm hook addresses docs/PLAN_v2.0.md §2.5: bge-m3 cold start is
~70s the first time `BGEM3FlagModel.encode()` is called. If the API
receives a user request before that completes, the request hangs until
the model loads. The lifespan calls `embedder.encode(["warmup"])` so the
load happens during startup, not under user latency.

预热钩子解决的是 docs/PLAN_v2.0.md §2.5 里的问题：首次调用
`BGEM3FlagModel.encode()` 时 bge-m3 冷启动约需 70 秒。如果 API 在此完成前
收到用户请求，该请求就会一直挂起直到模型加载完毕。lifespan 会调用
`embedder.encode(["warmup"])`，让加载发生在启动阶段，而不是拖慢用户请求
延迟。

ADR-0013 invariant: BM25 corpus and FAISS index are derived from SQLite.
Lifespan reads SQLite once at startup to build the BM25 in-memory; if
courses change at runtime (Week 6 has none — courses come from offline
seeds), restart the API to refresh.

ADR-0013 不变式：BM25 语料与 FAISS 索引都是从 SQLite 派生出来的。lifespan
在启动时读一次 SQLite 来构建内存版 BM25；若运行期间课程发生变化
（Week 6 阶段不存在这种情况 —— 课程都来自离线种子数据），需要重启 API
才能刷新。

Test path: `create_app(run_startup=False)` skips the heavy lifespan;
tests populate app.state with fakes manually. See tests/_api_helpers.py.

测试路径：`create_app(run_startup=False)` 会跳过这个重量级 lifespan；
测试代码手动往 app.state 填充假对象。参见 tests/_api_helpers.py。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI

from api.exceptions import register_exception_handlers
from api.logging import RequestLogMiddleware, configure_logging
from api.routes import auth, chat, coop, course, health, program, search
from config import settings
from db.connection import connect
from rag.embedder import BGEM3Embedder
from rag.hybrid import BM25Corpus
from rag.index import FaissIndex
from rag.reranker import CrossEncoderReranker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Heavy startup: load FAISS, build BM25, warm embedder + reranker.

    重量级启动流程：加载 FAISS、构建 BM25、预热嵌入器 + reranker。

    Inference backend dispatch (PLAN Week 9 Day 1):
      - settings.inference_backend == 'pytorch' (default) → PyTorch path
        (FlagEmbedding bge-m3 + transformers cross-encoder), ~70s cold start.
      - settings.inference_backend == 'onnx' → ONNX Runtime path with
        auto-detected execution provider (TensorRT > CUDA > OpenVINO > CPU).
        Requires `uv sync --extra onnx` + `scripts/export_models_onnx.py` run.
        ~3x speedup on RTX 5090 with TRT EP; viable on Intel iGPU NAS via
        OpenVINO EP. See docs/tensorrt_runbook.md.

    推理后端分发（PLAN Week 9 Day 1）：
      - settings.inference_backend == 'pytorch'（默认）→ PyTorch 路径
        （FlagEmbedding bge-m3 + transformers 交叉编码器），冷启动约 70 秒。
      - settings.inference_backend == 'onnx' → ONNX Runtime 路径，自动探测
        执行提供者（TensorRT > CUDA > OpenVINO > CPU）。需要先跑
        `uv sync --extra onnx` + `scripts/export_models_onnx.py`。在 RTX
        5090 上用 TRT EP 约有 3 倍加速；在 Intel 集显 NAS 上可通过
        OpenVINO EP 使用。详见 docs/tensorrt_runbook.md。

    Reranker is optional (settings.enable_reranker=False saves ~600 MB RAM
    for NAS deploy). /search degrades to bare hybrid+RRF when reranker is
    None — rejection layer (ADR-0016) becomes inactive in that mode.

    Reranker 是可选的（settings.enable_reranker=False 可为 NAS 部署省下
    约 600 MB 内存）。reranker 为 None 时，/search 会降级为纯
    hybrid+RRF —— 该模式下拒答层（ADR-0016）会失效。
    """
    log = configure_logging()
    log.info(
        "api.startup.begin",
        sqlite_path=settings.sqlite_path,
        faiss_index_path=settings.faiss_index_path,
        inference_backend=settings.inference_backend,
        enable_reranker=settings.enable_reranker,
    )

    # 1) FAISS — cheap (read from disk).
    # 中文：1）FAISS —— 代价很低（从磁盘读取）。
    faiss_index = FaissIndex.load(settings.faiss_index_path)
    log.info("api.startup.faiss_loaded", count=faiss_index.count)

    # 2) BM25 corpus from SQLite snapshot — cheap (≤1k docs in ~10ms).
    # 中文：2）从 SQLite 快照构建 BM25 语料 —— 代价很低（≤1000 篇文档约 10ms）。
    conn = connect(settings.sqlite_path)
    try:
        bm25_corpus = BM25Corpus.from_db(conn)
        log.info("api.startup.bm25_loaded", count=bm25_corpus.count)
    finally:
        conn.close()

    # 3) Embedder + (optional) reranker — backend-dispatched.
    # 中文：3）嵌入器 +（可选）reranker —— 按后端分发构建。
    embedder, reranker = _build_inference_stack(log)

    app.state.embedder = embedder
    app.state.faiss_index = faiss_index
    app.state.bm25_corpus = bm25_corpus
    app.state.reranker = reranker
    app.state.ready = True
    log.info("api.startup.ready")

    try:
        yield
    finally:
        log.info("api.shutdown")


def _build_inference_stack(log: Any) -> tuple[Any, Any]:
    """Construct (embedder, reranker) per settings.inference_backend.

    按 settings.inference_backend 构建 (embedder, reranker)。

    Returns (embedder, reranker | None). Both are warmed once (a dummy
    encode/score call) so the first user request doesn't pay the JIT/load
    cost. PyTorch path is the established 70s cold-start; ONNX path is
    typically faster but TRT EP first-build is one-off ~30-60s.

    返回 (embedder, reranker | None)。两者都会预热一次（跑一次假的
    encode/score 调用），这样第一个真实用户请求就不用承担 JIT/加载开销。
    PyTorch 路径是已知的 70 秒冷启动；ONNX 路径通常更快，但 TRT EP 首次
    构建有一次性的约 30-60 秒开销。
    """
    if settings.inference_backend == "onnx":
        return _build_onnx_stack(log)
    if settings.inference_backend == "openvino":
        return _build_openvino_stack(log)
    return _build_pytorch_stack(log)


def _build_pytorch_stack(log: Any) -> tuple[Any, Any]:
    """PyTorch inference path. Optionally wraps both models with
    torch.compile (Week 9 Day 2) when settings.enable_torch_compile
    is set. Compilation cost (~5-30s extra cold start) is paid in the
    lifespan warmup loop below.

    PyTorch 推理路径。当 settings.enable_torch_compile 打开时，可选择用
    torch.compile 包一层两个模型（Week 9 Day 2）。编译开销（额外约
    5-30 秒冷启动）在下面的 lifespan 预热循环里付掉。
    """
    compile_mode = (
        settings.torch_compile_mode if settings.enable_torch_compile else None
    )

    embedder = BGEM3Embedder(
        device=settings.embedding_device,
        compile_mode=compile_mode,
    )
    # Two warmup encodes when compiling: first triggers the JIT, second
    # exercises the compiled path so subsequent /search requests are fast.
    # 中文：开启编译时做两次预热 encode：第一次触发 JIT，第二次跑一遍已编译
    # 路径，这样后续 /search 请求才会是快的。
    embedder.encode(["warmup"])
    if compile_mode:
        embedder.encode(["warmup pass two"])
    log.info(
        "api.startup.embedder_warm",
        backend="pytorch",
        torch_compile=compile_mode or "off",
    )

    if not settings.enable_reranker:
        log.info("api.startup.reranker_disabled", backend="pytorch")
        return embedder, None

    reranker = CrossEncoderReranker(compile_mode=compile_mode)
    reranker.score("warmup", ["warmup"])
    if compile_mode:
        reranker.score("warmup", ["warmup pass two"])
    log.info(
        "api.startup.reranker_warm",
        backend="pytorch",
        torch_compile=compile_mode or "off",
    )
    return embedder, reranker


def _build_onnx_stack(log: Any) -> tuple[Any, Any]:
    """ONNX Runtime backend — requires `uv sync --extra onnx` + exported models.

    ONNX Runtime 后端 —— 需要先 `uv sync --extra onnx` 并导出好模型。

    Fails loudly (RuntimeError) if ONNX_MODEL_DIR is unset or models missing —
    silently falling back to PyTorch would mask a config error and ship the
    slow path to production.

    若 ONNX_MODEL_DIR 未设置或模型缺失，直接大声报错（RuntimeError）——
    悄悄退回 PyTorch 会掩盖配置错误，还会把慢速路径带上生产环境。
    """
    from pathlib import Path  # noqa: PLC0415

    from rag.onnx_backend import (  # noqa: PLC0415
        OnnxEmbedder,
        OnnxReranker,
        default_providers,
    )

    if not settings.onnx_model_dir:
        raise RuntimeError(
            "INFERENCE_BACKEND=onnx but ONNX_MODEL_DIR not set. "
            "Run `uv run python scripts/export_models_onnx.py --fp16` and set "
            "ONNX_MODEL_DIR=<output path> in .env. "
            "See docs/tensorrt_runbook.md."
        )

    onnx_dir = Path(settings.onnx_model_dir).expanduser()
    embedder_path = onnx_dir / "embedder" / "model.onnx"
    reranker_path = onnx_dir / "reranker" / "model.onnx"

    if not embedder_path.exists():
        raise RuntimeError(
            f"ONNX embedder not found at {embedder_path}. "
            "Run `uv run python scripts/export_models_onnx.py --fp16` first."
        )

    providers = (
        default_providers()
        if settings.onnx_providers == "auto"
        else [p.strip() for p in settings.onnx_providers.split(",") if p.strip()]
    )
    log.info("api.startup.onnx_providers", providers=providers)

    embedder = OnnxEmbedder.from_path(
        str(embedder_path),
        tokenizer_id=settings.embedding_model,
        providers=providers,
    )
    embedder.encode(["warmup"])
    log.info("api.startup.embedder_warm", backend="onnx")

    if not settings.enable_reranker:
        log.info("api.startup.reranker_disabled", backend="onnx")
        return embedder, None

    if not reranker_path.exists():
        raise RuntimeError(
            f"ONNX reranker not found at {reranker_path}. "
            "Either run the exporter again or set ENABLE_RERANKER=false."
        )

    reranker = OnnxReranker.from_path(
        str(reranker_path),
        providers=providers,
    )
    reranker.score("warmup", ["warmup"])
    log.info("api.startup.reranker_warm", backend="onnx")
    return embedder, reranker


def _build_openvino_stack(log: Any) -> tuple[Any, Any]:
    """OpenVINO IR backend via optimum-intel — Intel iGPU friendly path.

    经 optimum-intel 的 OpenVINO IR 后端 —— 对 Intel 核显友好的路径。

    Loads models exported by `scripts/export_openvino.py` (`optimum-cli
    export openvino`) and runs them through `OVModelForFeatureExtraction`
    / `OVModelForSequenceClassification`. Targets Intel iGPU by default
    (Iris Xe on NAS); override via OPENVINO_DEVICE env var.

    加载由 `scripts/export_openvino.py`(`optimum-cli export openvino`)
    导出的模型，通过 `OVModelForFeatureExtraction` /
    `OVModelForSequenceClassification` 运行。默认目标是 Intel 核显（NAS
    上的 Iris Xe）；可通过 OPENVINO_DEVICE 环境变量覆盖。

    Why a separate backend from ONNX:
      bge-m3's ONNX export has u8 GatherND that Intel GPU plugin can't
      compile (`No layout format available`). The optimum-intel direct
      export uses int64 indices and compiles cleanly. See
      rag/openvino_backend.py docstring + ravi9's BGE recipe gist.

    为什么要单独做一个后端而不是复用 ONNX：
      bge-m3 的 ONNX 导出里有 u8 类型的 GatherND，Intel GPU 插件编译不了
      (报 `No layout format available`)。optimum-intel 的直接导出用的是
      int64 索引，能干净地编译通过。详见 rag/openvino_backend.py 的
      docstring 以及 ravi9 的 BGE 配方 gist。
    """
    from pathlib import Path  # noqa: PLC0415

    from rag.openvino_backend import OvEmbedder, OvReranker  # noqa: PLC0415

    if not settings.openvino_model_dir:
        raise RuntimeError(
            "INFERENCE_BACKEND=openvino but OPENVINO_MODEL_DIR not set. "
            "Run `uv run python scripts/export_openvino.py` and set "
            "OPENVINO_MODEL_DIR=<output path> in .env."
        )

    ov_dir = Path(settings.openvino_model_dir).expanduser()
    embedder_dir = ov_dir / "embedder"
    reranker_dir = ov_dir / "reranker"

    if not (embedder_dir / "openvino_model.xml").exists():
        raise RuntimeError(
            f"OpenVINO embedder IR not found at {embedder_dir}/openvino_model.xml. "
            "Run `uv run python scripts/export_openvino.py` first."
        )

    log.info(
        "api.startup.openvino_config",
        device=settings.openvino_device,
        cache_dir=settings.openvino_cache_dir or "(none)",
    )

    embedder = OvEmbedder.from_path(
        str(embedder_dir),
        tokenizer_id=settings.embedding_model,
        device=settings.openvino_device,
        cache_dir=settings.openvino_cache_dir,
    )
    embedder.encode(["warmup"])
    log.info("api.startup.embedder_warm", backend="openvino", device=settings.openvino_device)

    if not settings.enable_reranker:
        log.info("api.startup.reranker_disabled", backend="openvino")
        return embedder, None

    if not (reranker_dir / "openvino_model.xml").exists():
        raise RuntimeError(
            f"OpenVINO reranker IR not found at {reranker_dir}/openvino_model.xml. "
            "Either run the exporter again or set ENABLE_RERANKER=false."
        )

    reranker = OvReranker.from_path(
        str(reranker_dir),
        device=settings.openvino_device,
        cache_dir=settings.openvino_cache_dir,
        max_length=settings.reranker_max_length,
    )
    reranker.score("warmup", ["warmup"])
    log.info("api.startup.reranker_warm", backend="openvino", device=settings.openvino_device)
    return embedder, reranker


def create_app(*, run_startup: bool = True) -> FastAPI:
    """Build the FastAPI app. `run_startup=False` skips lifespan for tests
    that populate app.state with fakes.
    构建 FastAPI 应用。`run_startup=False` 会跳过 lifespan，供那些手动往
    app.state 填充假对象的测试使用。"""
    app = FastAPI(
        title="NEU-Compass API",
        version="0.1.0",
        description="Course RAG + Co-op API. Internal MVP — F1 compliance, not commercial.",
        lifespan=lifespan if run_startup else None,
    )

    app.add_middleware(RequestLogMiddleware)
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(search.router)
    app.include_router(course.router)
    app.include_router(coop.router)
    app.include_router(chat.router)
    app.include_router(auth.router)
    app.include_router(program.router)

    return app


# Module-level instance for `uvicorn api.main:app` runs.
# 中文：模块级实例，供 `uvicorn api.main:app` 这种启动方式使用。
app = create_app()


__all__ = ["app", "create_app", "lifespan"]
