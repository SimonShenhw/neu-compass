"""
集中配置: pydantic-settings 从 .env 读取。
红线: 所有人独立 API key, 不共享。
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === LLM ===
    gemini_api_key: str

    # === Reddit ===
    reddit_client_id: str
    reddit_client_secret: str
    reddit_user_agent: str = "neu-compass/0.1"

    # === Google OAuth (Week 6 才需要) ===
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8501/oauth/callback"

    # === Storage ===
    sqlite_path: str = str(PROJECT_ROOT / "data" / "courses.db")
    faiss_index_path: str = str(PROJECT_ROOT / "data" / "faiss_index")

    # === API base URL (Streamlit -> FastAPI hop, Week 6) ===
    api_base_url: str = "http://localhost:8000"

    # === Embedding ===
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cuda"
    embedding_dim: int = 1024  # bge-m3 维度

    # === Inference backend ===
    # `pytorch` (default, FlagEmbedding/transformers direct)
    # `onnx`    (ORT runtime + onnxruntime-gpu / -openvino EPs — Week 9 Day 1)
    # `openvino` (optimum-intel direct-to-IR — sidesteps ONNX u8 GatherND
    #            issue that blocks Intel GPU compile; see rag/openvino_backend.py)
    inference_backend: str = "pytorch"

    # ONNX path config (only used when inference_backend == "onnx")
    onnx_model_dir: str | None = None  # e.g. ~/neu-compass-data/onnx
    onnx_providers: str = "auto"  # "auto" | comma-separated EP names

    # OpenVINO path config (only used when inference_backend == "openvino")
    # See docs/tensorrt_runbook.md and rag/openvino_backend.py.
    openvino_model_dir: str | None = None  # e.g. /data/openvino (NAS) or ~/neu-compass-data/openvino
    openvino_device: str = "GPU"  # "GPU" | "CPU" | "AUTO:GPU,CPU" | "MULTI:GPU,CPU"
    openvino_cache_dir: str | None = None  # persistent dir for compiled GPU kernel cache

    enable_reranker: bool = True  # NAS deploy can set False to save ~600 MB

    # Candidate pool the hybrid retriever hands to the reranker. The 20-pair
    # cross-encoder pass IS the /search p50 on the NAS, and reranker quality
    # does not improve monotonically with pool size (arXiv:2411.11767) — env
    # RERANK_POOL_SIZE lets the NAS A/B 20 vs 10 without a code redeploy.
    # ADR-locked default stays 20 until the eval says otherwise.
    rerank_pool_size: int = 20

    # === torch.compile (Week 9 Day 2: PyTorch path acceleration) ===
    # Wraps the reranker (and best-effort the embedder backbone) with
    # torch.compile when `inference_backend=pytorch`. ~10-25% latency
    # reduction on RTX 5090; cold-start adds 5-30s for compilation.
    # Has NO effect when inference_backend=onnx (ONNX has its own graph
    # optimization). Mode options:
    #   default          — safe, 10-20% speedup, no static-shape requirement
    #   reduce-overhead  — uses CUDA Graphs, +20-30% but needs static shapes
    #                       (auto-padding to max_length=512 increases per-call
    #                       compute on short queries; benchmark before enabling)
    #   max-autotune     — slower compile (~60s), best runtime perf
    enable_torch_compile: bool = False
    torch_compile_mode: str = "default"

    # === Logging ===
    log_level: str = "INFO"
    log_format: str = "json"  # json | console

    # === API budget ===
    api_budget_alarm: float = Field(default=150.0, description="USD/month, 超出触发告警")

    # === OAuth domain whitelist ===
    allowed_email_domains: list[str] = ["husky.neu.edu", "northeastern.edu"]


settings = Settings()
