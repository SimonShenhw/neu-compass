"""
集中配置: pydantic-settings 从 .env 读取。
红线: 所有人独立 API key, 不共享。
"""

from pathlib import Path
from typing import Literal

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

    # === Reddit (scraper-only; NEVER runs in the prod containers) ===
    # Empty defaults on purpose: these previously had no default, which
    # forced Reddit credentials into the NAS api+ui .env forever just so
    # `Settings()` could import — the only consumer is scrapers/reddit.py
    # on the dev box, which validates presence itself.
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
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
    # (No embedding_dim knob here: the real constant is
    # rag/embedder.py EMBEDDING_DIM — a settings field nobody read was
    # actively misleading and got removed in the 2026-06 debt sweep.)
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cuda"

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

    # Rejection gate flavor (ADR-0018):
    #   threshold  — ADR-0016 behavior: max(sigmoid) < 0.05 rejects (default)
    #   calibrated — logistic gate fusing sigmoid + BM25/vector evidence +
    #                code-pattern miss (rag/rejection.py). Opt-in via env
    #                REJECTION_MODE=calibrated after a calibration run.
    # Literal so a compose typo can't silently revert prod to the
    # threshold gate (routes compare with bare ==).
    rejection_mode: Literal["threshold", "calibrated"] = "threshold"

    # HyDE rescue pass (ADR-0019): when the gate rejects, one Gemini call
    # second-opinions the query — garbage stays rejected (REJECT verdict),
    # plausible course queries get a HyDE expansion + retrieval retry.
    # Costs 1 LLM call + 1 retrieval pass ONLY on would-be-rejected queries
    # (~12% of traffic measured on test_set v0.3). Opt-in: HYDE_RESCUE=true.
    hyde_rescue: bool = False

    # Rescue only fires for BORDERLINE rejections (calibrated gate's
    # p_answerable in [this, REJECT_BELOW)). High-confidence garbage
    # (p≈0.02 gibberish) gets no LLM second opinion — Gemini's verdict
    # proved flaky exactly there, and the gate was never in doubt.
    rescue_min_probability: float = 0.08

    # Reranker tokenizer truncation length. 512 is the model max, but
    # catalog raw_text (description-only) rarely needs it — the June
    # optimization doc predicted 1.5-2x on the rerank pass at 256. Env-
    # overridable (RERANKER_MAX_LENGTH) so the NAS can A/B without a
    # redeploy; re-run eval_via_api before locking a lower value in.
    reranker_max_length: int = Field(default=512, ge=64, le=512)

    # ADR-0020: query-time acronym expansion from the corpus-mined glossary
    # (data/acronym_glossary.json). Zero-cost no-op when the file is absent,
    # so True is a safe default everywhere.
    acronym_expansion: bool = True

    # ADR-0022: hybrid fusion flavor. "rrf" = rank-only (historic default);
    # "convex" = score-aware min-max combination (Bruch TOIS'23), with
    # FUSION_WEIGHT = the vector leg's share. Switch only on sweep evidence.
    # Literal + bounds so an env typo (FUSION_MODE casing, FUSION_WEIGHT=7)
    # fails LOUDLY at boot instead of silently reverting to RRF / 500ing
    # every non-alias query after a "successful" deploy.
    fusion_mode: Literal["rrf", "convex"] = "rrf"
    fusion_weight: float = Field(default=0.5, ge=0.0, le=1.0)

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

    # === OAuth domain whitelist ===
    allowed_email_domains: list[str] = ["husky.neu.edu", "northeastern.edu"]

    # === Session tokens (ADR-0021, replaces the X-User-Id stub) ===
    # Empty secret = mechanism off (anonymous-only) so fresh checkouts run.
    # Generate: python -c "import secrets; print(secrets.token_urlsafe(48))"
    session_secret: str = ""
    session_max_age_seconds: int = 604800  # 7 days


settings = Settings()
