# NEU-Compass

> 用结构化检索 + LLM 抽取破除 Northeastern 研究生**选课信息黑箱**。
> Course RAG 做流量入口，Co-op 数据做留存飞轮。

**Status**: Week 1-5 dev surface 全交付 · 16 commits · **413 tests / 8s on WSL2**
**Hardware tested on**: RTX 5090 + Ubuntu 24.04 + cu128 + torch 2.10
**English**: [README.en.md](README.en.md)

---

## 一句话现状

| 维度 | 实测数字 |
|---|---:|
| Recall@5 (alias-only) | 1.0 (5/5) |
| Top-1 accuracy (7-course semantic) | 7/7 |
| End-to-end query latency | 14-29 ms |
| WSL home vs H drive (SQLite write) | **77x faster** |
| bge-m3 cold start | ~70 s |
| Test suite | 413 tests / 8 s |

实测都在 [docs/rag_smoke_results.md](docs/rag_smoke_results.md) + [docs/path_decision.md](docs/path_decision.md)，不是营销数字。

---

## 架构

```
查询路径
─────────────────────────────────────────────────────
  user query
    │
    ├─→ query_normalizer (regex → AliasRepository.resolve)
    │     ↓
    │   alias hit? → return Course直接
    │     ↓ no
    │
    └─→ HybridRetriever
          ├── vector leg: bge-m3 → FAISS IndexIDMap
          └── BM25 leg:   rank_bm25
              ↓
            RRF fusion (k=60)
              ↓
            SQLite rehydrate (status='indexed' only)
              ↓
            list[SearchHit]


数据路径 (ADR-0013: SQLite 是真相源)
─────────────────────────────────────────────────────
  scrapers/syllabus.py (PyMuPDF)        ─┐
  scrapers/neu_catalog.py (scaffold)    ─┤
  scrapers/rmp.py (scaffold)            ─┤
  scrapers/reddit.py (scaffold)         ─┘
                ↓
          llm/extract_v1.py prompt
                ↓
          Gemini 2.5 Flash + Pydantic structured output
                ↓
          CourseRepository.upsert() → status='pending'
                ↓
          rag/embedder.py (bge-m3, lazy load)
                ↓
          FAISS index → courses.status='indexed'
```

---

## 快速开始

### 一次性环境配置

```bash
# 1) Windows 管理员 PowerShell
wsl --install -d Ubuntu-24.04

# 2) Ubuntu 第一次启动: 设 unix 用户名 + 密码 (本机用,不要复用其他账号)

# 3) 验证 GPU 直通
wsl -d Ubuntu-24.04 -e nvidia-smi  # 应该看到你的 GPU + CUDA version

# 4) 装 uv (用户级,无 sudo)
wsl -d Ubuntu-24.04
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc

# 5) 装项目依赖 (~6 分钟首次,主要是 PyTorch 1.5GB)
cd /mnt/h/neu-compass
uv venv && uv sync --extra dev

# 6) 配置 secrets (你自己创建 .env,不要 commit)
cp .env.example .env
# 编辑 .env 填: GEMINI_API_KEY / REDDIT_CLIENT_ID 等
# (运行时数据路径已经在 .env 里指向 ~/neu-compass-data/)

# 7) 创建运行时数据目录 (ADR-0014: WSL home,比 H 盘快 77x)
mkdir -p ~/neu-compass-data
```

### 端到端冒烟测试

```bash
cd /mnt/h/neu-compass

# 跑测试 (~8s)
uv run pytest tests/

# 初始化 + 种数据 + 建 FAISS (~80s 首次,模型 load 主导)
uv run python scripts/seed_aai6600.py
uv run python scripts/seed_synthetic_courses.py
uv run python scripts/load_slang_dict.py
uv run python scripts/rebuild_faiss.py

# 跑真实查询
uv run python scripts/smoke_rag_query.py        # 7/7 top-1 accuracy
uv run python scripts/smoke_hybrid_compare.py   # vector vs hybrid

# 跑 alias-mode eval
uv run python eval/run_eval.py --mode alias_only
```

---

## 项目结构

```
neu-compass/
├── schemas/        Pydantic 模型 (course v1.1, alias, coop)
├── db/             SQLite repositories + connection helper
├── scrapers/       syllabus (full) + neu_catalog/rmp/reddit (scaffold)
├── llm/            Gemini client + formatter + extract prompt + alias detector
├── rag/            embedder (bge-m3) + FAISS index + retriever + hybrid + hyde
├── eval/           test_set + run_eval + Ragas runner + compare_prompts
├── app/            Streamlit pages (eval_dashboard 骨架; MVP UI 待 Week 6)
├── api/            FastAPI 入口 (待 Week 6)
├── scripts/        init_db / seed / rebuild / migrate / bench / smoke
├── data/           slang_dict.json + ground_truth/ (gitignored)
├── docs/           PLAN / ADRs / annotation_guide / pii_redaction
└── tests/          413 tests
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
| [docs/PLAN_v2.0.md](docs/PLAN_v2.0.md) | **下阶段路线图** (Week 6-8 + carry-forwards) |
| [docs/PLAN_v1.3.md](docs/PLAN_v1.3.md) | 8 周原始规划 |
| [docs/wsl2_setup.md](docs/wsl2_setup.md) | WSL2 + uv + GPU 配置实测路径 |
| [docs/annotation_guide.md](docs/annotation_guide.md) | 双盲标注 SOP (Day 6-13 团队用) |
| [docs/pii_redaction.md](docs/pii_redaction.md) | PII 脱敏 380 行操作指南 |
| [docs/rag_smoke_results.md](docs/rag_smoke_results.md) | 端到端 RAG 实测三轮数字 |
| [docs/path_decision.md](docs/path_decision.md) | ADR-0014 实测证据 (77x) |

---

## 红线 (合规 + 安全)

- **F1 合规**: 不商业化, 不收款, 不接受投资 (PLAN §9 红线)
- **个人 API key 独立**: 不共享, 不进对话/Slack/邮件/截图
- **pre-commit detect-secrets 严格模式**: 任何 secret 入 commit 直接 fail
- **PII k-anonymity 强制**: 三元组 (company, role, term) 必须 ≥2 次出现才发布
- **NEU 域名限定**: Google OAuth 只接受 husky.neu.edu / northeastern.edu

详见 [docs/pii_redaction.md](docs/pii_redaction.md) + [PLAN §9](docs/PLAN_v1.3.md#9-法律与合规清单f1-红线具体化)

---

## License

MVP 阶段不发布 license。F1 合规要求项目纯 side project, 不商业化, 不接受 contribution PR until 法律审核完成 (见 PLAN §9.3 商业化前必做)。
