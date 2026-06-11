# NEU-Compass

> 用结构化检索 + LLM 抽取破除 Northeastern 研究生**选课信息黑箱**。
> Course RAG 做流量入口,Co-op 数据做留存飞轮。

**Status**: Weeks 1-10 工程主线 ship 完毕 + v3.1 RAG quality 3-layer 上线 · **739 tests / 14s on WSL2** · 全 NEU catalog **6469 课**已 ingested + indexed · **公网软启动**: `https://api.neu-compass.me` + `https://compass.neu-compass.me`(origin 已搬到 UGREEN DXP 6800 Pro NAS,PC 可关机)· 项目相位 = `operational + signal-driven`(active sprint:[PLAN v3.0](docs/PLAN_v3.0.md))。Week 9 加做 ONNX Runtime backend 实测,startup 70s → 6s(详见 [perf_week9_results.md](docs/perf_week9_results.md))。v3.1 把 chat 路径从"hybrid 凑合"升级成 alias → program ontology → hybrid+reranker+reject 三层 + chat_v2 prompt(详见 [v3_1_rag_quality.md](docs/v3_1_rag_quality.md))。Week 10 把整套 stack 容器化迁到 NAS + 接通 Iris Xe iGPU(`optimum-intel` 直接 OpenVINO IR 路径,NAS 上 /search p50 **8s → 2.3s**,api RAM **17GB → 4.9GB**)。
**Hardware tested on**: RTX 5090 + Ubuntu 24.04 + cu130 + torch 2.11
**English**: [README.en.md](README.en.md)

---

## 一句话现状

| 维度 | 实测数字 |
|---|---:|
| 测试套件 — v3.1 RAG quality 后 | **739 tests / ~14 s** |
| `/search` p50 latency — PyTorch baseline (实测 RTX 5090) | **43.82 ms** |
| `/search` p50 latency — ONNX + CUDA EP (实测 RTX 5090) ⭐ | **40.09 ms** (-8.5%) |
| `/search` p99 latency PyTorch / ONNX | 117.97 / **54.74 ms** (-53.6%) |
| Lifespan startup PyTorch / ONNX ⭐ | 70 s / **6 s** (-91%) |
| **`/search` p50 — NAS Iris Xe + optimum-intel OpenVINO IR** ⭐ | **~2310 ms** (10 query smoke,reranker on) |
| **`/search` p50 — NAS pool=10 + int8 reranker (ADR-0017, live-API n=42)** ⭐ | **849 ms** (p95 1167,R@5 无损,api RSS 4.9→3.5GB) |
| **api 容器 RSS — NAS (reranker on + Iris Xe)** | **4.9 GB** (vs ONNX+CPU 17 GB) |
| **NAS 冷启 lifespan(OpenVINO compile cache 持久化)** | **13 s** (首次 ~50 s,缓存命中后 5 s) |
| Eval R@5 / MRR — `hybrid_with_alias` (α=1.0) | 0.601 / **0.603** |
| Eval R@5 / MRR — `+rerank` only (α=0.0) | **0.636** / 0.545 |
| **Eval R@5 / MRR — Z-score blend α=0.4** (ADR-0015 locked) | 0.621 / 0.575 |
| Adversarial rejection at T=0.05 sigmoid (ADR-0016) | **4/4** 命中,真 R@5 损失 -0.066 |
| Boundary queries hit rate (alias / slang / no-space code) | **6/6 = 1.000** |
| BM25 stopword-filter inversion gap | +0.001 → **+0.016** (16x) |
| WSL home vs H 盘 (SQLite write) | **77x faster** (ADR-0014) |
| Co-op seed records 入库 | **30 条 (12 quant / 8 big_tech / 5 biotech / 5 startup)** |
| Schema 版本 | **1.1** (user_courses 表 v3.0 social 预留 DDL only) |
| 测试套件 — Week 9 baseline | 679 tests / ~13 s |

实测数字 + 决策依据:[docs/PLAN_v2.2.md](docs/PLAN_v2.2.md) (Week 7 sprint) + [docs/adr/0015-z-score-blending.md](docs/adr/0015-z-score-blending.md) (α 决策) + [docs/adr/0016-reranker-reject-threshold.md](docs/adr/0016-reranker-reject-threshold.md) (T 校准) + [docs/rag_smoke_results.md](docs/rag_smoke_results.md) + [docs/path_decision.md](docs/path_decision.md)。

## Week 7 ship 状态(KPI)

| KPI | 状态 | 备注 |
|---|---|---|
| 1. 公网 URL serving FastAPI | ✅ | api.neu-compass.me 200 / 6469 indexed |
| 2. ≥ 200 真 query | 🟡 | 等团队 traffic |
| 3. ≥ 5 contributors OAuth | 🟡 1/5 | OAuth round-trip 已通过(域白名单 + JWT verify + upsert)|
| 4. ADR-0015 α 决策 | ✅ | α=0.4 锁定 + ADR-0016 阈值 0.05 校准 |

## Week 8 ship 状态

| § | 交付 | 状态 |
|---|---|---|
| 3.3 | CS 5200 prompt v1.1 强约束 evidence_snippets + 12 测试 + live smoke | ✅ |
| 3.5 | google.genai SDK migrate(google.generativeai EOL 解除)+ dict-path schema bypass | ✅ |
| 3.7 | Portfolio packaging:postmortem · system arch · metrics · roadmap v3 · runbooks | ✅ |
| Path A | UX overhaul(hero / filters)+ 后端 reliability(N+1 / readiness / chat gate)+ structured error handler | ✅ |
| 3.4 | 16 课 enrich(需主授名,scope 决策跳过)| ⏭️ |
| 3.8 | OAuth secret rotate(项目寿命短,跳过)| ⏭️ |
| 3.1 / 3.2 / 3.6 / 3.9 / 3.10 | 等真 query log 触发 / 浏览器 F12 复测 | ⬜ |

详见 [docs/PLAN_v2.3.md](docs/PLAN_v2.3.md) + [docs/PLAN_v2_3_1.md](docs/PLAN_v2_3_1.md)(hardened review)。

## Week 9 ship 状态(perf 实测)

| § | 交付 | 状态 | 实测 |
|---|---|---|---|
| Day 1 | ONNX Runtime backend(rag/onnx_backend.py + export script + 13 测试 + runbook) | ✅ ship | startup 70s → 6s,p50 -8.5% (RTX 5090 + CUDA EP) |
| Day 2 | torch.compile + latency benchmark script + 5 测试 | ✅ ship | torch.compile path **不可用**(Blackwell + FlagEmbedding hang) |
| - | TensorRT EP 路径 | ⏭️ blocked | ORT 1.25 cu12 vs user cu130 ABI mismatch,等 ORT 1.26+ |

详见 [docs/perf_week9_results.md](docs/perf_week9_results.md)(完整对比 + 4 类发现 + 部署建议)。

**项目相位 → v3.0**:engineering 主线 ship 完毕,signal-driven 模式启动。Active sprint plan: [PLAN v3.0](docs/PLAN_v3.0.md)。

## v3.1 ship 状态(RAG quality 3-layer)

| Layer | 交付 | 状态 |
|---|---|---|
| Layer 1 | [chat_v2 prompt](llm/prompts/chat_v2.py)(program-prefix discipline + foundational level)+ chat 路径加 reranker reject | ✅ ship |
| Layer 2 | [QueryFilters schema](schemas/query_filter.py) + [regex prefix extractor](llm/query_filter_extractor.py)(LLM hook ready)+ [retriever `primary_code_prefix` filter](rag/retriever.py)| ✅ ship |
| Layer 3 | schema v1.2(`programs` / `program_required_courses` / `course_prerequisites`)+ [ProgramRepository](db/program_repository.py) + [AAI MS PoC seed](data/program_seed/aai_ms.json)(23 课 + 10 prereq)+ chat 路径 program-aware shortcut | ✅ ship |
| 顺手 | `query_normalizer` re.ASCII(中文嵌入 NL 抓 course code)+ Streamlit 4 个 button bug + cross-lingual reject scoping | ✅ ship |

实测:`POST /chat "AAI 专业第一学期推荐"` → matched_via=program · 1.28ms 直查 · LLM 答出 5xxx foundational 序列(替换之前 chat_v1 路径返回的 ALY/ARTG/BINF 跨学科 noise)。详见 [docs/v3_1_rag_quality.md](docs/v3_1_rag_quality.md)。

## Week 10 ship 状态(NAS 生产部署 + Iris Xe GPU offload)

把整套 stack 从 PC(本来要 24/7 开机给域名站台)迁到 UGREEN DXP 6800 Pro NAS。**PC 终于可以关机**,公网走 Tailscale + NAS-local cloudflared,不再有"开发机当服务器"的拉扯。

| § | 交付 | 状态 | 实测 |
|---|---|---|---|
| 部署形态 | docker compose 三服务(api + ui + cloudflared)+ Cloudflare Tunnel connector 搬家到 NAS;PC 端 cloudflared 退役 | ✅ ship | 三容器 healthy, restart=0 |
| 硬件 | NAS 升 2×16GB DDR5 SODIMM 双通道(从笔记本拆装,边际成本接近零)| ✅ ship | 7.5GB → 32GB,reranker 可常驻 |
| 推理 backend | 第三条 inference path:`optimum-intel` 直接 OpenVINO IR + `OVModelForFeatureExtraction` / `OVModelForSequenceClassification`,target Iris Xe iGPU | ✅ ship | /search p50 **8s → 2.3s** (-71%) |
| 内存占用 | api 容器 RSS(OpenVINO CPU buffer → GPU)| ✅ ship | 17GB → **4.9GB** (-71%) |
| 启动 | OpenVINO GPU 编译缓存持久化 (`CACHE_DIR=/data/openvino_cache`)| ✅ ship | 冷启 70s → 13s |
| 自动化 | `scripts\deploy.ps1` 一键部署(tar-pipe 代码 + scp .env + 远程 `docker compose up -d --build` + Tailscale 健康探测)| ✅ ship | 增量 deploy ~30s |
| 拒绝层回归 | ADR-0016 (T=0.05) 在新 backend 上回归测试 | ✅ ship | gibberish query → matched_via=`rejected`, max_sigmoid 0.000 < 0.05 |

**踩坑链(完整 postmortem)**: 第一条尝试路径是 `ONNX → onnxruntime-openvino → Intel GPU plugin`,bge-m3 ONNX 里的 u8 `GatherND` 算子 Intel GPU 编译失败(`No layout format available for gathernd:bfyx, u8`)。HETERO 模式 plugin 谎报支持然后 runtime 炸;AUTO 模式启动 OK 但 reranker `score()` 命中 OpenVINO CPU plugin 的 shape-cache bug 返 500。**真正的解是绕开 ONNX 中间层** — 直接 `optimum-cli export openvino` 生成 OpenVINO IR(u8 索引在这条路径里以 int64 落地),用 optimum-intel 的 `OVModel*` 类加载,`device="GPU"` 一次过。新 backend 代码 [rag/openvino_backend.py](rag/openvino_backend.py) + 导出脚本 [scripts/export_openvino.py](scripts/export_openvino.py) + lifespan 分支 [api/main.py:`_build_openvino_stack`](api/main.py)。运行时部署 [Dockerfile](Dockerfile) + [docker-compose.yml](docker-compose.yml)。

**还能再压**(留作 signal-driven 触发):reranker 跑 20 个 query-doc pair × seq_len=512 是 p50 的 bottleneck — 三个 lever 都没拉:(a) hybrid pool 20→10 砍 ~50% 延迟,代价 recall 略降;(b) `OvReranker.reshape()` 静态 shape 编译;(c) `--weight-format int8` 量化 reranker。
**2026-06-11 更新**:lever (a) + (c) 已拉(ADR-0017)— live-API eval 实测 recall **零损失**(论文 arXiv:2411.11767 预测成立),p50 2019→**849ms**。lever (b) 仍未动;下一量级要换 late-interaction 架构,见 [docs/optimization_2026_06.md](docs/optimization_2026_06.md)。

---

## 架构

```
HTTP API (FastAPI)  · Public:  https://api.neu-compass.me
─────────────────────────────────────────────────────
  POST /search     alias-first → HybridRetriever → rerank+Z-blend+reject
                   (ADR-0015 α=0.4, ADR-0016 T=0.05)
  GET  /course/{id}  Course Pydantic dump
  GET  /coop / POST /coop  k=2 anonymity gated, tier-aware
  POST /chat       NDJSON stream: meta → tokens → done
  POST /auth/callback  Google OAuth code → JWT verify → upsert_login
  GET  /health, /ready

  ↓                                    ↑
  ↓  (Streamlit consumer)              ↑
  ↓  app/streamlit_app.py              ↑
  ↓  st.write_stream(stream_assistant) ↑
  ↓  + render_auth_sidebar             ↑

查询路径 (alias-first → program ontology → hybrid + Layer 2 prefix filter → reranker reject)
─────────────────────────────────────────────────────
  user query
    │
    ├─→ query_normalizer (regex re.ASCII → AliasRepository.resolve via v_course_lookup)
    │     ↓
    │   alias hit? → return Course directly (matched_via='alias')
    │     ↓ no
    │
    ├─→ Layer 3: program ontology shortcut (v3.1, /chat path only)
    │     IF query has program prefix (AAI/CS/...) AND foundational intent (第一学期/...)
    │     AND program is seeded in `programs` table
    │     → return program_required_courses(program_id, semester=1)
    │     (matched_via='program', deterministic SQL graph lookup)
    │     ↓ miss
    │
    ├─→ Layer 2: regex prefix extractor (v3.1)
    │     extracts {program_prefix: 'AAI'} → hard_filter primary_code LIKE 'AAI %'
    │     sanitized_query strips prefix word → embedder sees pure intent
    │     ↓
    │
    └─→ HybridRetriever (pool size = 20, prefix-narrowed when applicable)
          ├── vector leg: bge-m3 (warm) → FAISS IndexIDMap (6469 vectors)
          └── BM25 leg:   rank_bm25 + 110-word English stopwords filter
              ↓
            RRF fusion (k=60)
              ↓
            SQLite rehydrate (status='indexed' only)
              ↓
            bge-reranker-v2-m3 cross-encoder (single pass; v3.1 also gates /chat)
              ├─→ if max(sigmoid) < threshold
              │     /search:  threshold = 0.05 (ADR-0016)
              │     /chat:    threshold = 0.05 generic OR 0.0 when Layer 2 prefix
              │               filter narrowed candidates (within-prefix subset
              │               doesn't need wholesale rejection)
              │     return matched_via='rejected' + reason
              └─→ else: Z-score blend α=0.4·rrf_z + 0.6·rerank_z
                  → sort desc → top-k SearchHit (matched_via='hybrid')


数据路径 (ADR-0013: SQLite 是真相源)
─────────────────────────────────────────────────────
  scrapers/syllabus.py (PyMuPDF)        ─┐
  scrapers/neu_catalog.py (live)        ─┤  (232 dept, 6446 课)
  scrapers/rmp.py (live, GraphQL)       ─┤  (NEU school id verified)
  scrapers/reddit.py (PRAW, mock-only)  ─┘
                ↓
        scripts/ingest_neu_catalog.py / enrich_course_via_rmp.py
                ↓
          llm/extract_v1.py / chat_v1.py prompts
                ↓
          Gemini 2.5 Flash (structured output OR streaming)
                ↓
          CourseRepository.upsert() → status='pending'
                ↓
          rag/embedder.py (bge-m3, lazy load) + rag/index.py
                ↓
          mark_pending_indexed.py → status='indexed'
```

---

## 快速开始

### 一次性环境配置

```bash
# 1) Windows 管理员 PowerShell
wsl --install -d Ubuntu-24.04

# 2) Ubuntu 第一次启动: 设 unix 用户名 + 密码

# 3) 验证 GPU 直通
wsl -d Ubuntu-24.04 -e nvidia-smi  # 应看到 GPU + CUDA version

# 4) 装 uv (用户级,无 sudo)
wsl -d Ubuntu-24.04
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc

# 5) 装项目依赖 (~6 分钟首次,主要是 PyTorch 1.5GB)
cd /mnt/h/neu-compass
uv venv && uv sync --extra dev

# 6) 配置 secrets
cp .env.example .env
# 编辑 .env 填: GEMINI_API_KEY / GOOGLE_OAUTH_CLIENT_ID/SECRET /
#               REDDIT_CLIENT_ID / API_BASE_URL / ...

# 7) 创建运行时数据目录 (ADR-0014: WSL home,比 H 盘快 77x)
mkdir -p ~/neu-compass-data
```

### 端到端跑通整个 catalog (Week 7 后的标准路径)

```bash
cd /mnt/h/neu-compass

# 跑测试 (~12s)
uv run pytest tests/                         # 631 passed

# 旧 DB 升 schema 1.1 (一次性,新装跳过此步)
uv run python scripts/migrate_db_to_v1_1.py --commit

# 抓全 NEU catalog (~25 min, 1 req/sec polite, resumable)
uv run python scripts/scrape_neu_catalog.py

# 入库 SQLite + 自动 cross-list aliases
uv run python scripts/ingest_neu_catalog.py

# 重建 FAISS (~25s 纯推理 / ~85s 含 bge-m3 冷启) + 翻 status 'indexed'
uv run python scripts/rebuild_faiss.py --all
uv run python scripts/mark_pending_indexed.py

# 加载 slang 字典 (39 条对应 7 课)
uv run python scripts/load_slang_dict.py

# Co-op seed 30 条入库 (data/coop_seed/curated.json gitignored,见 template)
uv run python scripts/ingest_coop_seed.py --file data/coop_seed/curated.json --commit

# 验真实 query 跑通
uv run python eval/run_eval.py --mode hybrid_with_alias --rerank --with-rejection
# → 公网生产路径:hybrid + rerank + Z-score blend α=0.4 + reject T=0.05

uv run python eval/sweep_blend_alpha.py        # ADR-0015 9-α grid
uv run python eval/sweep_reject_threshold.py   # ADR-0016 9-T ROC
uv run python scripts/probe_latency.py         # p50 ~40ms hybrid-only
```

### 起 API + UI

**一键启动(推荐,Windows + WSL2 部署用,v3.1 加)**:

```cmd
scripts\start_stack.bat              # full stack: uvicorn + streamlit + cloudflared
scripts\start_stack.bat -Local       # 本地 only(skip cloudflared)
scripts\start_stack.bat -Pytorch     # 用 PyTorch backend(~70s 而非 ~6s)
scripts\start_stack.bat -ApiOnly     # 只起 uvicorn

scripts\stop_stack.bat               # 全停(含关 spawned -NoExit 窗口)
```

启动器会做 pre-flight check(.env / WSL distro / SQLite + FAISS / ONNX 模型 / cloudflared / 端口冲突 / Streamlit credentials.toml ensure),起三个新 PowerShell 窗口分别跑各 service,window title 用 `neu-compass : <service>` 一眼区分,uvicorn `/ready` 200 才起 cloudflared(避免 startup race 满屏红)。详见 [scripts/start_stack.ps1](scripts/start_stack.ps1) 注释。

**手动三窗口**(老路径,debug 用):

```bash
# Terminal 1: FastAPI (lifespan 预热 ~70s,加载 bge-m3 + bge-reranker)
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000

# Terminal 2: Streamlit chat UI (course search + Co-op browse,Andy Dong React 前端落地前的 product UI)
uv run streamlit run app/streamlit_app.py --server.port 8501 --server.address 0.0.0.0

# Terminal 3 (公网): Cloudflare Tunnel — 详见 docs/cloudflare_tunnel.md §11
#   实测部署:Windows 边 cloudflared,api.* + compass.* 双子域映射
cloudflared tunnel run neu-compass
```

### 公网入口

| URL | 用途 |
|---|---|
| `https://api.neu-compass.me` | FastAPI canonical (Andy 前端 / curl 调) |
| `https://compass.neu-compass.me` | Streamlit user UI(course search + chat,Andy React 前端落地前 canonical)|

Origin 自 Week 10 起跑在 NAS(Tailscale 内网 + cloudflared 容器),PC 不需要常开。NAS-side stack 在 [docker-compose.yml](docker-compose.yml),改完代码 `scripts\deploy.ps1` 一键推送 + 重建 + 健康探测。

---

## 项目结构

```
neu-compass/
├── schemas/        Pydantic models (course v1.1, alias, coop, user, program v3.1, query_filter v3.1)
├── db/             SQLite repositories (course, alias, coop, user, program v3.1) + connection
├── scrapers/       syllabus + neu_catalog (live) + rmp (live) + reddit (PRAW, mock-tested)
├── llm/            Gemini client (+ stream) + formatter + extract_v1 + chat_v1 + chat_v2 (v3.1) + query_filter_extractor (v3.1) + alias_detector + review_enrichment
├── rag/            embedder (bge-m3) + FAISS index + retriever + hybrid (BM25+RRF + stopwords) + hyde + reranker (bge-reranker-v2-m3) + onnx_backend (ORT EP) + openvino_backend (optimum-intel direct IR, Week 10)
├── eval/           test_set v0.2 (42 q) + run_eval (4 modes) + Ragas + compare_prompts
├── app/            Streamlit pages (eval_dashboard / streamlit_app / coop_view) + state_manager + auth + api_client + streamlit_auth_ui
├── api/            FastAPI: main + dependencies + models + logging + routes/{health,search,course,coop,chat,auth}
├── scripts/        init_db / seed / load_slang / scrape / ingest / rebuild_faiss / mark_indexed / probe_rmp / probe_latency / enrich_course_via_rmp / validate_test_set / export_models_onnx / export_openvino (Week 10) / start_stack / stop_stack / deploy (Week 10)
├── data/           slang_dict.json + ground_truth/ (gitignored)
├── docs/           PLAN_v1.3 / v2.0 / v2.1 + ADRs + annotation_guide + pii_redaction + cloudflare_tunnel
├── tests/          601 tests / fixtures/ (real NEU + RMP HTML/JSON snapshots)
├── Dockerfile      Week 10 — multi-stage prod image, base bookworm + intel-opencl-icd for Iris Xe
├── docker-compose.yml  Week 10 — api + ui + cloudflared 三服务, /dev/dri 直通 + render/video group_add
└── .dockerignore   Week 10 — build context exclusions
```

---

## 关键决策 (ADRs)

- **[ADR-0001](docs/adr/0001-sqlite-faiss-vs-milvus.md)** SQLite + FAISS 而非 Milvus
- **[ADR-0013](docs/adr/0013-sqlite-as-source-of-truth.md)** SQLite 是真相源, FAISS 可重建
- **[ADR-0014](docs/adr/0014-h-drive-code-wsl-data.md)** 代码 H 盘 + 运行时数据 WSL home (77x 实测)
- **[ADR-0015](docs/adr/0015-z-score-blending.md)** Z-score 混合 RRF + reranker (α=0.4) — Week 7
- **[ADR-0016](docs/adr/0016-reranker-reject-threshold.md)** Reranker 拒绝阈值 0.05 (数据校准,从 spec 0.4 下调) — Week 7
- **[ADR-0017](docs/adr/0017-nas-rerank-pool-int8.md)** NAS rerank pool 20→10 + int8 reranker (live-API 实测 p50 -58% 质量无损) — 2026-06

完整 ADR: [docs/adr/](docs/adr/)

---

## 主要文档

| 文档 | 内容 |
|---|---|
| [docs/PLAN_v3.0.md](docs/PLAN_v3.0.md) | **当前 sprint** (Week 9+ operational + signal-driven phase) |
| [docs/v3_1_rag_quality.md](docs/v3_1_rag_quality.md) | **v3.1 closeout**:chat 路径 3-layer (alias → program ontology → hybrid) 重构 + 4 个 frontend bugfix |
| [docs/perf_week9_results.md](docs/perf_week9_results.md) | Week 9 perf 实测 report(ONNX/TRT/torch.compile 4 类路径实战) |
| [docs/PLAN_v2.3.md](docs/PLAN_v2.3.md) | Week 8 sprint(shipped — 见 §10 closeout)|
| [docs/PLAN_v2_3_1.md](docs/PLAN_v2_3_1.md) | Week 8 sprint hardened review(shipped partial — 见 §10 closeout)|
| [docs/postmortem_week7.md](docs/postmortem_week7.md) | Week 7 部署 8 类踩坑 + 共同主题(portfolio 用)|
| [docs/system_architecture.md](docs/system_architecture.md) | 系统架构 5 张 mermaid 图(topology · query · data · auth · modules)|
| [docs/portfolio_metrics.md](docs/portfolio_metrics.md) | Canonical metrics cheatsheet(latency · quality · scale · cost)|
| [docs/roadmap_v3.md](docs/roadmap_v3.md) | v3.0+ roadmap(社交层 · learnable blending · ColBERT · 移动端)|
| [docs/oauth_secret_rotation.md](docs/oauth_secret_rotation.md) | OAuth client_secret rotate runbook(5 min)|
| [docs/streamlit_ws_troubleshooting.md](docs/streamlit_ws_troubleshooting.md) | Streamlit chat_input WebSocket 排查 SOP |
| [docs/tensorrt_runbook.md](docs/tensorrt_runbook.md) | ONNX Runtime / TensorRT 加速 runbook(47ms → ~17ms RTX 5090,350ms → ~80ms NAS Iris Xe)|
| [docs/PLAN_v2.2.md](docs/PLAN_v2.2.md) | Week 7 sprint (shipped — 见 §9 closeout) |
| [docs/PLAN_v2.1.md](docs/PLAN_v2.1.md) | Week 6 checkpoint (ship state) |
| [docs/PLAN_v2.0.md](docs/PLAN_v2.0.md) | Week 5 checkpoint (历史) |
| [docs/PLAN_v1.3.md](docs/PLAN_v1.3.md) | 8 周原始规划 |
| [docs/api_contract.md](docs/api_contract.md) | **HTTP API 契约** (curl + 响应 shape, 前端使用) |
| [docs/cloudflare_tunnel.md](docs/cloudflare_tunnel.md) | Cloudflare Tunnel 部署 runbook (含 Windows/WSL2 §11 实测路径) |
| [docs/wsl2_setup.md](docs/wsl2_setup.md) | WSL2 + uv + GPU 配置实测路径 |
| [docs/annotation_guide.md](docs/annotation_guide.md) | 双盲标注 SOP |
| [docs/pii_redaction.md](docs/pii_redaction.md) | PII 脱敏 380 行操作指南 |
| [docs/rag_smoke_results.md](docs/rag_smoke_results.md) | 端到端 RAG 实测 (Week 4-5) |
| [docs/path_decision.md](docs/path_decision.md) | ADR-0014 实测证据 (77x) |

---

## 红线 (合规 + 安全)

- **F1 合规**: 不商业化, 不收款, 不接受投资 (PLAN §9 红线)
- **个人 API key 独立**: 不共享, 不进对话/Slack/邮件/截图
- **pre-commit detect-secrets 严格模式**: 任何 secret 入 commit 直接 fail
- **PII k-anonymity 强制**: 三元组 (company, role, term) 必须 ≥ 2 次出现才发布,server-side 在 `POST /coop` 强制
- **OAuth 域名白名单**: `is_email_allowed` 走 split-on-`@` 精确匹配,**禁止子串攻击** (`attacker@husky.neu.edu.evil.com` 必拒)

详见 [docs/pii_redaction.md](docs/pii_redaction.md) + [PLAN v2.1 §3](docs/PLAN_v2.1.md)

---

## License

MVP 阶段不发布 license。F1 合规要求项目纯 side project, 不商业化, 不接受 contribution PR until 法律审核完成 (见 PLAN §9.3 商业化前必做)。
