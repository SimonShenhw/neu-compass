"""Centralized configuration: pydantic-settings reads from .env.
Hard rule: everyone uses their own independent API key — never shared.

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
    # 中文:大语言模型(LLM)相关配置。
    gemini_api_key: str

    # === Reddit (scraper-only; NEVER runs in the prod containers) ===
    # 中文:Reddit 配置(仅供爬虫脚本使用,绝不在生产容器中运行)。
    # Empty defaults on purpose: these previously had no default, which
    # forced Reddit credentials into the NAS api+ui .env forever just so
    # `Settings()` could import — the only consumer is scrapers/reddit.py
    # on the dev box, which validates presence itself.
    # 中文:故意给空字符串默认值。这几个字段以前没有默认值,导致 NAS 上
    # api+ui 的 .env 里永远得塞着 Reddit 凭证,仅仅是为了让 `Settings()`
    # 能被 import —— 而唯一的使用方是开发机上的 scrapers/reddit.py,
    # 它自己会校验这些字段是否真的存在。
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "neu-compass/0.1"

    # === Google OAuth (Week 6 才需要) ===
    # 中文:Google OAuth 配置(从第 6 周开始才需要)。
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8501/oauth/callback"

    # === Storage ===
    # 中文:存储路径配置。
    sqlite_path: str = str(PROJECT_ROOT / "data" / "courses.db")
    faiss_index_path: str = str(PROJECT_ROOT / "data" / "faiss_index")

    # === API base URL (Streamlit -> FastAPI hop, Week 6) ===
    # 中文:API 基础 URL(第 6 周起,Streamlit -> FastAPI 之间的跳转地址)。
    api_base_url: str = "http://localhost:8000"

    # === Embedding ===
    # 中文:嵌入模型相关配置。
    # (No embedding_dim knob here: the real constant is
    # rag/embedder.py EMBEDDING_DIM — a settings field nobody read was
    # actively misleading and got removed in the 2026-06 debt sweep.)
    # 中文:这里不放 embedding_dim 开关:真正的常量在 rag/embedder.py 的
    # EMBEDDING_DIM —— 一个没人读、反而容易误导人的 settings 字段,已在
    # 2026-06 的技术债清理中删除。
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cuda"

    # === Inference backend ===
    # 中文:推理后端选择。
    # `pytorch` (default, FlagEmbedding/transformers direct)
    # `onnx`    (ORT runtime + onnxruntime-gpu / -openvino EPs — Week 9 Day 1)
    # `openvino` (optimum-intel direct-to-IR — sidesteps ONNX u8 GatherND
    #            issue that blocks Intel GPU compile; see rag/openvino_backend.py)
    # 中文:`pytorch`(默认,直接用 FlagEmbedding/transformers)。
    # 中文:`onnx`(ORT 运行时 + onnxruntime-gpu / -openvino 执行提供者 —— 第 9 周 Day 1)。
    # 中文:`openvino`(optimum-intel 直接转 IR —— 绕开阻塞 Intel GPU 编译的
    # ONNX u8 GatherND 问题;见 rag/openvino_backend.py)。
    inference_backend: str = "pytorch"

    # ONNX path config (only used when inference_backend == "onnx")
    # 中文:ONNX 路径配置(仅当 inference_backend == "onnx" 时生效)。
    onnx_model_dir: str | None = None  # e.g. ~/neu-compass-data/onnx
    # 中文:例如 ~/neu-compass-data/onnx
    onnx_providers: str = "auto"  # "auto" | comma-separated EP names
    # 中文:"auto" 或逗号分隔的执行提供者(EP)名称列表

    # OpenVINO path config (only used when inference_backend == "openvino")
    # See docs/tensorrt_runbook.md and rag/openvino_backend.py.
    # 中文:OpenVINO 路径配置(仅当 inference_backend == "openvino" 时生效)。
    # 中文:详见 docs/tensorrt_runbook.md 与 rag/openvino_backend.py。
    openvino_model_dir: str | None = None  # e.g. /data/openvino (NAS) or ~/neu-compass-data/openvino
    # 中文:例如 /data/openvino(NAS 上)或 ~/neu-compass-data/openvino
    openvino_device: str = "GPU"  # "GPU" | "CPU" | "AUTO:GPU,CPU" | "MULTI:GPU,CPU"
    # 中文:"GPU" | "CPU" | "AUTO:GPU,CPU" | "MULTI:GPU,CPU" 之一
    openvino_cache_dir: str | None = None  # persistent dir for compiled GPU kernel cache
    # 中文:已编译 GPU 内核缓存的持久化目录

    enable_reranker: bool = True  # NAS deploy can set False to save ~600 MB
    # 中文:NAS 部署可设为 False 以节省约 600 MB 内存

    # Candidate pool the hybrid retriever hands to the reranker. The 20-pair
    # cross-encoder pass IS the /search p50 on the NAS, and reranker quality
    # does not improve monotonically with pool size (arXiv:2411.11767) — env
    # RERANK_POOL_SIZE lets the NAS A/B 20 vs 10 without a code redeploy.
    # ADR-locked default stays 20 until the eval says otherwise.
    # 中文:混合检索器交给重排器的候选池大小。20 对的交叉编码器打分本身
    # 就是 NAS 上 /search p50 耗时的大头,且重排质量并不会随池子变大而
    # 单调提升(arXiv:2411.11767)—— 环境变量 RERANK_POOL_SIZE 让 NAS
    # 能在不重新部署代码的前提下做 20 vs 10 的 A/B。ADR 锁定默认值为 20,
    # 除非评测结果证明应该改。
    rerank_pool_size: int = 20

    # Rejection gate flavor (ADR-0018):
    #   threshold  — ADR-0016 behavior: max(sigmoid) < 0.05 rejects (default)
    #   calibrated — logistic gate fusing sigmoid + BM25/vector evidence +
    #                code-pattern miss (rag/rejection.py). Opt-in via env
    #                REJECTION_MODE=calibrated after a calibration run.
    # Literal so a compose typo can't silently revert prod to the
    # threshold gate (routes compare with bare ==).
    # 中文(ADR-0018):拒答门的模式选择:
    #   threshold  —— ADR-0016 的行为:max(sigmoid) < 0.05 即拒答(默认)
    #   calibrated —— 融合 sigmoid + BM25/向量证据 + 代码模式缺失信号的
    #                逻辑回归门(rag/rejection.py)。需先跑一次校准,
    #                再通过环境变量 REJECTION_MODE=calibrated 开启。
    # 中文:用 Literal 类型是为了让 compose 文件里的拼写错误不会静默地把
    # 生产环境退回 threshold 门(路由层用裸 == 比较,拼错就永远不等于)。
    rejection_mode: Literal["threshold", "calibrated"] = "threshold"

    # HyDE rescue pass (ADR-0019): when the gate rejects, one Gemini call
    # second-opinions the query — garbage stays rejected (REJECT verdict),
    # plausible course queries get a HyDE expansion + retrieval retry.
    # Costs 1 LLM call + 1 retrieval pass ONLY on would-be-rejected queries
    # (~12% of traffic measured on test_set v0.3). Opt-in: HYDE_RESCUE=true.
    # 中文(ADR-0019):HyDE 补救环节。拒答门拒绝一个查询时,用一次 Gemini
    # 调用给它"复议":确实是垃圾的查询仍维持拒答(REJECT 判定),看起来像
    # 选课问题的查询则做 HyDE 扩写 + 重新检索。只对本来就会被拒答的查询
    # 多花 1 次 LLM 调用 + 1 次检索(在 test_set v0.3 上约占流量的 12%)。
    # 默认关闭,需显式设置 HYDE_RESCUE=true 才开启。
    hyde_rescue: bool = False

    # Rescue only fires for BORDERLINE rejections (calibrated gate's
    # p_answerable in [this, REJECT_BELOW)). High-confidence garbage
    # (p≈0.02 gibberish) gets no LLM second opinion — Gemini's verdict
    # proved flaky exactly there, and the gate was never in doubt.
    # 中文:补救只对"临界拒答"生效(即校准门给出的 p_answerable 落在
    # [此值, REJECT_BELOW) 区间内)。高置信度的垃圾查询(p≈0.02 的乱码)
    # 不会拿到 LLM 复议 —— 恰恰是在这个区间里 Gemini 的判断被证明不稳定,
    # 而拒答门本身其实从未犹豫过。
    rescue_min_probability: float = 0.08

    # Reranker tokenizer truncation length. 512 is the model max, but
    # catalog raw_text (description-only) rarely needs it — the June
    # optimization doc predicted 1.5-2x on the rerank pass at 256. Env-
    # overridable (RERANKER_MAX_LENGTH) so the NAS can A/B without a
    # redeploy; re-run eval_via_api before locking a lower value in.
    # 中文:重排器分词器的截断长度。512 是模型上限,但目录 raw_text
    # (仅描述文本)很少用得到这么长 —— 6 月的优化文档预测截到 256 能让
    # 重排阶段快 1.5-2 倍。可通过环境变量 RERANKER_MAX_LENGTH 覆盖,
    # 让 NAS 不重新部署也能 A/B;调低数值前请先重跑 eval_via_api 验证。
    reranker_max_length: int = Field(default=512, ge=64, le=512)

    # ADR-0020: query-time acronym expansion from the corpus-mined glossary
    # (data/acronym_glossary.json). Zero-cost no-op when the file is absent,
    # so True is a safe default everywhere.
    # 中文(ADR-0020):基于语料挖掘出的缩写词表(data/acronym_glossary.json)
    # 做查询期缩写扩写。词表文件不存在时是零成本的空操作,所以到处都能
    # 安全地把默认值设为 True。
    acronym_expansion: bool = True

    # ADR-0022: hybrid fusion flavor. "rrf" = rank-only (historic default);
    # "convex" = score-aware min-max combination (Bruch TOIS'23), with
    # FUSION_WEIGHT = the vector leg's share. Switch only on sweep evidence.
    # Literal + bounds so an env typo (FUSION_MODE casing, FUSION_WEIGHT=7)
    # fails LOUDLY at boot instead of silently reverting to RRF / 500ing
    # every non-alias query after a "successful" deploy.
    # 中文(ADR-0022):混合融合的模式。"rrf" = 只看名次(历史默认值);
    # "convex" = 分数感知的 min-max 组合(Bruch, TOIS'23),
    # FUSION_WEIGHT 表示向量路占的权重份额。只有在扫描实验有证据支持时
    # 才切换。用 Literal 加取值范围约束,是为了让环境变量的拼写错误
    # (FUSION_MODE 大小写写错、FUSION_WEIGHT=7 之类)在启动时就大声报错,
    # 而不是悄悄退回 RRF,或者在一次"成功"部署之后让所有非 alias 查询
    # 全部 500。
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
    # 中文(第 9 周 Day 2:PyTorch 路径加速):当 inference_backend=pytorch
    # 时,用 torch.compile 包装重排器(并尽力包装嵌入器主干)。在 RTX 5090
    # 上大约能降低 10-25% 延迟;代价是冷启动多花 5-30 秒编译时间。对
    # inference_backend=onnx 没有任何效果(ONNX 有自己的图优化)。模式:
    #   default          —— 安全,提速 10-20%,不要求静态形状
    #   reduce-overhead  —— 用 CUDA Graphs,提速 20-30% 但需要静态形状
    #                       (自动 padding 到 max_length=512 会增加短查询
    #                       每次调用的计算量;开启前请先做基准测试)
    #   max-autotune     —— 编译更慢(约 60 秒),运行时性能最好
    enable_torch_compile: bool = False
    torch_compile_mode: str = "default"

    # === Logging ===
    # 中文:日志配置。
    log_level: str = "INFO"
    log_format: str = "json"  # json | console
    # 中文:json 或 console

    # === OAuth domain whitelist ===
    # 中文:OAuth 邮箱域名白名单。
    allowed_email_domains: list[str] = ["husky.neu.edu", "northeastern.edu"]

    # === Session tokens (ADR-0021, replaces the X-User-Id stub) ===
    # Empty secret = mechanism off (anonymous-only) so fresh checkouts run.
    # Generate: python -c "import secrets; print(secrets.token_urlsafe(48))"
    # 中文(ADR-0021,取代原先的 X-User-Id 占位方案):会话令牌配置。
    # secret 为空字符串 = 该机制关闭(仅支持匿名),这样刚 checkout 出来的
    # 代码也能直接跑起来。生成方式:
    # python -c "import secrets; print(secrets.token_urlsafe(48))"
    session_secret: str = ""
    session_max_age_seconds: int = 604800  # 7 days
    # 中文:7 天


settings = Settings()
