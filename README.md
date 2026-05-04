# NEU-Compass

> 用结构化检索 + LLM 抽取破除 Northeastern 研究生**选课信息黑箱**。
> Course RAG 做流量入口,Co-op 数据做留存飞轮。

**Status**: Weeks 1-6 工程交付完成 · **601 tests / 10s on WSL2** · 全 NEU catalog **6469 课**已 ingested + indexed
**Hardware tested on**: RTX 5090 + Ubuntu 24.04 + cu128 + torch 2.10
**English**: [README.en.md](README.en.md)

---

## 一句话现状

| 维度 | 实测数字 |
|---|---:|
| `/search` p50 latency (live FAISS+BM25,6469 课) | **40.1 ms** (target <300ms,8x 余量) |
| `/search` p95 / p99 | 45.4 / 46.3 ms |
| Eval Recall@5 (`hybrid_with_alias` on test_set v0.2) | 0.601 |
| Eval Recall@5 + bge-reranker-v2-m3 | **0.636** (+0.035) |
| Boundary queries hit rate (alias / slang / no-space code) | **6/6 = 1.000** |
| BM25 stopword-filter inversion gap | +0.001 → **+0.016** (16x) |
| WSL home vs H 盘 (SQLite write) | **77x faster** (ADR-0014) |
| bge-m3 cold start | ~70 s (lifespan 预热消化) |
| 测试套件 | 601 tests / ~10 s |

实测数字都在 [docs/PLAN_v2.1.md](docs/PLAN_v2.1.md) §2 + [docs/rag_smoke_results.md](docs/rag_smoke_results.md) + [docs/path_decision.md](docs/path_decision.md),不是营销数字。

---

## 架构

```
HTTP API (FastAPI)
─────────────────────────────────────────────────────
  POST /search     alias-first → HybridRetriever
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
    └─→ HybridRetriever
          ├── vector leg: bge-m3 (warm) → FAISS IndexIDMap (6469 vectors)
          └── BM25 leg:   rank_bm25 + 110-word English stopwords filter
              ↓
            RRF fusion (k=60)
              ↓
            SQLite rehydrate (status='indexed' only)
              ↓
            (optional) bge-reranker-v2-m3 cross-encoder (sigmoid [0,1])
              ↓
            list[SearchHit]


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

### 端到端跑通整个 catalog (Week 6 后的标准路径)

```bash
cd /mnt/h/neu-compass

# 跑测试 (~10s)
uv run pytest tests/                         # 601 passed

# 抓全 NEU catalog (~25 min, 1 req/sec polite, resumable)
uv run python scripts/scrape_neu_catalog.py

# 入库 SQLite + 自动 cross-list aliases
uv run python scripts/ingest_neu_catalog.py

# 重建 FAISS (~25s on 5090) + 翻 status 'indexed'
uv run python scripts/rebuild_faiss.py --all
uv run python scripts/mark_pending_indexed.py

# 加载 slang 字典 (39 条对应 7 课)
uv run python scripts/load_slang_dict.py

# 验真实 query 跑通
uv run python eval/run_eval.py --mode hybrid_with_alias        # baseline
uv run python eval/run_eval.py --mode hybrid_with_alias --rerank  # +reranker
uv run python scripts/probe_latency.py                          # p50 ~40ms
```

### 起 API + UI

```bash
# Terminal 1: FastAPI (lifespan 预热 ~70s,然后接流量)
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000

# Terminal 2: Streamlit chat UI (走 /chat NDJSON 流)
uv run streamlit run app/streamlit_app.py --server.port 8501 --server.address 0.0.0.0

# Terminal 3 (公网, 可选): Cloudflare Tunnel
cloudflared tunnel run neu-compass   # 详见 docs/cloudflare_tunnel.md
```

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

完整 ADR: [docs/adr/](docs/adr/)

---

## 主要文档

| 文档 | 内容 |
|---|---|
| [docs/PLAN_v2.1.md](docs/PLAN_v2.1.md) | **当前 checkpoint** (Week 6 后状态 + Week 7-8 路线图) |
| [docs/PLAN_v2.0.md](docs/PLAN_v2.0.md) | Week 5 checkpoint (历史) |
| [docs/PLAN_v1.3.md](docs/PLAN_v1.3.md) | 8 周原始规划 |
| [docs/cloudflare_tunnel.md](docs/cloudflare_tunnel.md) | Cloudflare Tunnel 部署 runbook |
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
