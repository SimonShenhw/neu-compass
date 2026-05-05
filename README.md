# NEU-Compass

> 用结构化检索 + LLM 抽取破除 Northeastern 研究生**选课信息黑箱**。
> Course RAG 做流量入口,Co-op 数据做留存飞轮。

**Status**: Weeks 1-7 工程交付完成 · **631 tests / 12s on WSL2** · 全 NEU catalog **6469 课**已 ingested + indexed · **公网软启动**: `https://api.neu-compass.me` + `https://compass.neu-compass.me`
**Hardware tested on**: RTX 5090 + Ubuntu 24.04 + cu128 + torch 2.10
**English**: [README.en.md](README.en.md)

---

## 一句话现状

| 维度 | 实测数字 |
|---|---:|
| `/search` p50 latency (live, hybrid+rerank+blend, 6469 课) | **~47 ms** (含 reranker;target <300ms,6x 余量) |
| `/search` p95 / hybrid-only p50 | 51 ms / 40.1 ms |
| Eval R@5 / MRR — `hybrid_with_alias` (α=1.0) | 0.601 / **0.603** |
| Eval R@5 / MRR — `+rerank` only (α=0.0) | **0.636** / 0.545 |
| **Eval R@5 / MRR — Z-score blend α=0.4** (ADR-0015 locked) | 0.621 / 0.575 |
| Adversarial rejection at T=0.05 sigmoid (ADR-0016) | **4/4** 命中,真 R@5 损失 -0.066 |
| Boundary queries hit rate (alias / slang / no-space code) | **6/6 = 1.000** |
| BM25 stopword-filter inversion gap | +0.001 → **+0.016** (16x) |
| WSL home vs H 盘 (SQLite write) | **77x faster** (ADR-0014) |
| bge-m3 cold start | ~70 s (lifespan 预热消化) |
| Co-op seed records 入库 | **30 条 (12 quant / 8 big_tech / 5 biotech / 5 startup)** |
| Schema 版本 | **1.1** (user_courses 表 v3.0 social 预留 DDL only) |
| 测试套件 | **631 tests / ~12 s** |

实测数字 + 决策依据:[docs/PLAN_v2.2.md](docs/PLAN_v2.2.md) (Week 7 sprint) + [docs/adr/0015-z-score-blending.md](docs/adr/0015-z-score-blending.md) (α 决策) + [docs/adr/0016-reranker-reject-threshold.md](docs/adr/0016-reranker-reject-threshold.md) (T 校准) + [docs/rag_smoke_results.md](docs/rag_smoke_results.md) + [docs/path_decision.md](docs/path_decision.md)。

## Week 7 ship 状态(KPI)

| KPI | 状态 | 备注 |
|---|---|---|
| 1. 公网 URL serving FastAPI | ✅ | api.neu-compass.me 200 / 6469 indexed |
| 2. ≥ 200 真 query | 🟡 | 等团队 traffic |
| 3. ≥ 5 contributors OAuth | 🟡 1/5 | OAuth round-trip 已通过(域白名单 + JWT verify + upsert)|
| 4. ADR-0015 α 决策 | ✅ | α=0.4 锁定 + ADR-0016 阈值 0.05 校准 |

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

查询路径 (alias-first → hybrid → optional rerank)
─────────────────────────────────────────────────────
  user query
    │
    ├─→ query_normalizer (regex → AliasRepository.resolve via v_course_lookup)
    │     ↓
    │   alias hit? → return Course directly (matched_via='alias')
    │     ↓ no
    │
    └─→ HybridRetriever (pool size = 20)
          ├── vector leg: bge-m3 (warm) → FAISS IndexIDMap (6469 vectors)
          └── BM25 leg:   rank_bm25 + 110-word English stopwords filter
              ↓
            RRF fusion (k=60)
              ↓
            SQLite rehydrate (status='indexed' only)
              ↓
            bge-reranker-v2-m3 cross-encoder (single pass)
              ├─→ if max(sigmoid) < 0.05 (ADR-0016)
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

### 起 API + UI(本地三窗口)

```bash
# Terminal 1: FastAPI (lifespan 预热 ~70s,加载 bge-m3 + bge-reranker)
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000

# Terminal 2: Streamlit chat UI (走 /chat NDJSON 流;Week 7 后定位为 debug + OAuth landing)
uv run streamlit run app/streamlit_app.py --server.port 8501 --server.address 0.0.0.0

# Terminal 3 (公网): Cloudflare Tunnel — 详见 docs/cloudflare_tunnel.md §11
#   实测部署:Windows 边 cloudflared,api.* + compass.* 双子域映射
cloudflared tunnel run neu-compass
```

### 公网入口

| URL | 用途 |
|---|---|
| `https://api.neu-compass.me` | FastAPI canonical (Andy 前端 / curl 调) |
| `https://compass.neu-compass.me` | Streamlit debug + OAuth callback landing |

---

## 项目结构

```
neu-compass/
├── schemas/        Pydantic models (course v1.1, alias, coop, user)
├── db/             SQLite repositories (course, alias, coop, user) + connection
├── scrapers/       syllabus + neu_catalog (live) + rmp (live) + reddit (PRAW, mock-tested)
├── llm/            Gemini client (+ stream) + formatter + extract_v1 + chat_v1 + alias_detector + review_enrichment
├── rag/            embedder (bge-m3) + FAISS index + retriever + hybrid (BM25+RRF + stopwords) + hyde + reranker (bge-reranker-v2-m3)
├── eval/           test_set v0.2 (42 q) + run_eval (4 modes) + Ragas + compare_prompts
├── app/            Streamlit pages (eval_dashboard / streamlit_app / coop_view) + state_manager + auth + api_client + streamlit_auth_ui
├── api/            FastAPI: main + dependencies + models + logging + routes/{health,search,course,coop,chat,auth}
├── scripts/        init_db / seed / load_slang / scrape / ingest / rebuild_faiss / mark_indexed / probe_rmp / probe_latency / enrich_course_via_rmp / validate_test_set
├── data/           slang_dict.json + ground_truth/ (gitignored)
├── docs/           PLAN_v1.3 / v2.0 / v2.1 + ADRs + annotation_guide + pii_redaction + cloudflare_tunnel
└── tests/          601 tests / fixtures/ (real NEU + RMP HTML/JSON snapshots)
```

---

## 关键决策 (ADRs)

- **[ADR-0001](docs/adr/0001-sqlite-faiss-vs-milvus.md)** SQLite + FAISS 而非 Milvus
- **[ADR-0013](docs/adr/0013-sqlite-as-source-of-truth.md)** SQLite 是真相源, FAISS 可重建
- **[ADR-0014](docs/adr/0014-h-drive-code-wsl-data.md)** 代码 H 盘 + 运行时数据 WSL home (77x 实测)
- **[ADR-0015](docs/adr/0015-z-score-blending.md)** Z-score 混合 RRF + reranker (α=0.4) — Week 7
- **[ADR-0016](docs/adr/0016-reranker-reject-threshold.md)** Reranker 拒绝阈值 0.05 (数据校准,从 spec 0.4 下调) — Week 7

完整 ADR: [docs/adr/](docs/adr/)

---

## 主要文档

| 文档 | 内容 |
|---|---|
| [docs/PLAN_v2.3.md](docs/PLAN_v2.3.md) | **当前 sprint** (Week 8 路线 + post-Week-7 ship 路径) |
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
