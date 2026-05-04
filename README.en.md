# NEU-Compass

> Breaking the **course-selection black box** for Northeastern graduate students
> via structured retrieval + LLM extraction. Course RAG drives traffic; Co-op
> data is the retention flywheel.

**Status**: Weeks 1-6 engineering complete · **601 tests / 10s on WSL2** · full NEU catalog **6469 courses** ingested + indexed
**Hardware tested on**: RTX 5090 + Ubuntu 24.04 + cu128 + torch 2.10
**中文**: [README.md](README.md)

---

## TL;DR — Empirical baseline

| Metric | Measured |
|---|---:|
| `/search` p50 latency (live FAISS+BM25, 6469 courses) | **40.1 ms** (target <300ms, 8x headroom) |
| `/search` p95 / p99 | 45.4 / 46.3 ms |
| Eval Recall@5 (`hybrid_with_alias` on test_set v0.2) | 0.601 |
| Eval Recall@5 + bge-reranker-v2-m3 | **0.636** (+0.035) |
| Boundary queries hit rate (alias / slang / no-space code) | **6/6 = 1.000** |
| BM25 stopword-filter inversion gap | +0.001 → **+0.016** (16x) |
| WSL home vs H: drive (SQLite write) | **77x faster** (ADR-0014) |
| bge-m3 cold start | ~70 s (absorbed by FastAPI lifespan pre-warm) |
| Test suite | 601 tests / ~10 s |

All numbers reproducible from [docs/PLAN_v2.1.md](docs/PLAN_v2.1.md) §2 +
[docs/rag_smoke_results.md](docs/rag_smoke_results.md) +
[docs/path_decision.md](docs/path_decision.md). Not marketing figures.

---

## Architecture

```
HTTP API (FastAPI)
─────────────────────────────────────────────────────
  POST /search           alias-first → HybridRetriever
  GET  /course/{id}      Course Pydantic dump
  GET  /coop, POST /coop k=2 anonymity gated, tier-aware visibility
  POST /chat             NDJSON stream: meta → tokens → done
  POST /auth/callback    Google OAuth code → JWT verify → upsert_login
  GET  /health, /ready

         ↓                                ↑
  (Streamlit consumes)         (browser hits via Cloudflare)
  app/streamlit_app.py
  st.write_stream(stream_assistant)
  + render_auth_sidebar

Query path (alias-first → hybrid → optional rerank)
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


Data path (ADR-0013: SQLite is the source of truth)
─────────────────────────────────────────────────────
  scrapers/syllabus.py (PyMuPDF)        ─┐
  scrapers/neu_catalog.py (live)        ─┤  (232 depts, 6446 courses)
  scrapers/rmp.py (live, GraphQL)       ─┤  (NEU school id verified)
  scrapers/reddit.py (PRAW, mock-only)  ─┘
                ↓
        scripts/ingest_neu_catalog.py / enrich_course_via_rmp.py
                ↓
          llm/extract_v1.py + llm/prompts/chat_v1.py
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

## Quick start

### One-time environment setup

```bash
# 1) Admin PowerShell on Windows
wsl --install -d Ubuntu-24.04

# 2) First Ubuntu boot: set unix username + password
#    (local-only, do NOT reuse passwords from other accounts)

# 3) Verify GPU passthrough
wsl -d Ubuntu-24.04 -e nvidia-smi   # should show your GPU + CUDA version

# 4) Install uv (user-local, no sudo)
wsl -d Ubuntu-24.04
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc

# 5) Sync project deps (~6 min first time, mostly PyTorch 1.5GB)
cd /mnt/h/neu-compass
uv venv && uv sync --extra dev

# 6) Configure secrets (do NOT commit .env)
cp .env.example .env
# Edit .env: GEMINI_API_KEY / GOOGLE_OAUTH_CLIENT_ID/SECRET /
#            REDDIT_CLIENT_ID / API_BASE_URL / ...

# 7) Create runtime data directory (ADR-0014: WSL home is 77x faster)
mkdir -p ~/neu-compass-data
```

### End-to-end: full catalog ingest (Week 6+ canonical path)

```bash
cd /mnt/h/neu-compass

# Run tests (~10s)
uv run pytest tests/                          # 601 passed

# Scrape full NEU catalog (~25 min, 1 req/sec polite, resumable)
uv run python scripts/scrape_neu_catalog.py

# Ingest into SQLite + auto-link cross-list aliases
uv run python scripts/ingest_neu_catalog.py

# Rebuild FAISS (~25s on 5090) + flip status to 'indexed'
uv run python scripts/rebuild_faiss.py --all
uv run python scripts/mark_pending_indexed.py

# Load slang dictionary (39 entries across 7 courses)
uv run python scripts/load_slang_dict.py

# Verify real-query retrieval works
uv run python eval/run_eval.py --mode hybrid_with_alias
uv run python eval/run_eval.py --mode hybrid_with_alias --rerank
uv run python scripts/probe_latency.py                       # p50 ~40ms
```

### Run API + UI

```bash
# Terminal 1: FastAPI (lifespan pre-warms bge-m3 ~70s, then accepts traffic)
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000

# Terminal 2: Streamlit chat UI (consumes /chat NDJSON stream)
uv run streamlit run app/streamlit_app.py --server.port 8501 --server.address 0.0.0.0

# Terminal 3 (public URL, optional): Cloudflare Tunnel
cloudflared tunnel run neu-compass   # see docs/cloudflare_tunnel.md
```

---

## Project layout

```
neu-compass/
├── schemas/        Pydantic models (course v1.1, alias, coop, user)
├── db/             SQLite repositories (course, alias, coop, user) + connection helper
├── scrapers/       syllabus + neu_catalog (live) + rmp (live) + reddit (PRAW, mock-tested)
├── llm/            Gemini client (+ stream) + formatter + extract_v1 + chat_v1 + alias_detector + review_enrichment
├── rag/            embedder (bge-m3) + FAISS + retriever + hybrid (BM25+RRF + stopwords) + hyde + reranker (bge-reranker-v2-m3)
├── eval/           test_set v0.2 (42 q) + run_eval (4 modes) + Ragas + compare_prompts
├── app/            Streamlit pages + state_manager + auth + api_client + streamlit_auth_ui
├── api/            FastAPI: main + dependencies + models + logging + routes/{health,search,course,coop,chat,auth}
├── scripts/        init_db / seed / load_slang / scrape / ingest / rebuild_faiss / mark_indexed / probe_rmp / probe_latency / enrich_course_via_rmp / validate_test_set
├── data/           slang_dict.json + ground_truth/ (gitignored)
├── docs/           PLAN_v1.3 / v2.0 / v2.1 + ADRs + annotation_guide + pii_redaction + cloudflare_tunnel
└── tests/          601 tests / fixtures/ (real NEU + RMP HTML/JSON snapshots)
```

---

## Key decisions (ADRs)

- **[ADR-0001](docs/adr/0001-sqlite-faiss-vs-milvus.md)** SQLite + FAISS over Milvus
- **[ADR-0013](docs/adr/0013-sqlite-as-source-of-truth.md)** SQLite is the truth source; FAISS is rebuildable
- **[ADR-0014](docs/adr/0014-h-drive-code-wsl-data.md)** Code on H: + runtime data on WSL home (77x measured)

Full list: [docs/adr/](docs/adr/)

---

## Documentation

| Doc | Purpose |
|---|---|
| [docs/PLAN_v2.1.md](docs/PLAN_v2.1.md) | **Current checkpoint** (post-Week-6 + Week 7-8 forward plan) |
| [docs/PLAN_v2.0.md](docs/PLAN_v2.0.md) | Week 5 checkpoint (historical) |
| [docs/PLAN_v1.3.md](docs/PLAN_v1.3.md) | Original 8-week plan |
| [docs/cloudflare_tunnel.md](docs/cloudflare_tunnel.md) | Cloudflare Tunnel deployment runbook |
| [docs/wsl2_setup.md](docs/wsl2_setup.md) | WSL2 + uv + GPU setup, actual paths walked |
| [docs/annotation_guide.md](docs/annotation_guide.md) | Double-blind annotation SOP |
| [docs/pii_redaction.md](docs/pii_redaction.md) | 380-line operational PII redaction guide |
| [docs/rag_smoke_results.md](docs/rag_smoke_results.md) | Three rounds of measured RAG results (Week 4-5) |
| [docs/path_decision.md](docs/path_decision.md) | ADR-0014 evidence (77x) |

---

## Compliance + Security red lines

- **F1 compliance**: no commercialization, no payment, no investor money (PLAN §9)
- **Personal API keys are personal**: never share via chat / Slack / email / screenshot
- **pre-commit detect-secrets in strict mode**: any detected secret fails the commit
- **PII k-anonymity enforced**: (company, role, coop_term) triples must occur ≥ 2 times in the combined corpus before publish — server-side at `POST /coop`
- **OAuth domain whitelist**: `is_email_allowed` uses split-on-`@` exact match — substring attacks like `attacker@husky.neu.edu.evil.com` are rejected

Details: [docs/pii_redaction.md](docs/pii_redaction.md) + [PLAN v2.1 §3](docs/PLAN_v2.1.md)

---

## License

No license during MVP. F1 visa rules require this remain a non-commercial side
project; external PR contributions are paused pending legal review (see
PLAN §9.3 "before commercialization").
