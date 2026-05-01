# NEU-Compass

> Breaking the **course-selection black box** for Northeastern graduate students
> via structured retrieval + LLM extraction. Course RAG drives traffic; Co-op
> data is the retention flywheel.

**Status**: Weeks 1-5 dev surface complete · 16 commits · **413 tests / 8s on WSL2**
**Hardware tested on**: RTX 5090 + Ubuntu 24.04 + cu128 + torch 2.10
**中文**: [README.md](README.md)

---

## TL;DR — Empirical baseline

| Metric | Measured |
|---|---:|
| Recall@5 (alias-only) | 1.0 (5/5) |
| Top-1 accuracy (7-course semantic) | 7/7 |
| End-to-end query latency | 14-29 ms |
| WSL home vs H: drive (SQLite write) | **77x faster** |
| bge-m3 cold start | ~70 s |
| Test suite | 413 tests / 8 s |

All numbers reproducible from [docs/rag_smoke_results.md](docs/rag_smoke_results.md)
and [docs/path_decision.md](docs/path_decision.md). Not marketing figures.

---

## Architecture

```
Query path
─────────────────────────────────────────────────────
  user query
    │
    ├─→ query_normalizer (regex → AliasRepository.resolve)
    │     ↓
    │   alias hit? → return Course directly
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


Data path (ADR-0013: SQLite is the source of truth)
─────────────────────────────────────────────────────
  scrapers/syllabus.py (PyMuPDF, full impl)        ─┐
  scrapers/neu_catalog.py (scaffold)               ─┤
  scrapers/rmp.py (scaffold)                       ─┤
  scrapers/reddit.py (scaffold)                    ─┘
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

# 6) Configure secrets (create .env yourself; do NOT commit)
cp .env.example .env
# Edit .env: GEMINI_API_KEY / REDDIT_CLIENT_ID / etc.
# Runtime data paths in .env already point at ~/neu-compass-data/

# 7) Create runtime data directory (ADR-0014: WSL home is 77x faster than H:)
mkdir -p ~/neu-compass-data
```

### End-to-end smoke test

```bash
cd /mnt/h/neu-compass

# Run tests (~8s)
uv run pytest tests/

# Initialize + seed + build FAISS (~80s first run, model load dominates)
uv run python scripts/seed_aai6600.py
uv run python scripts/seed_synthetic_courses.py
uv run python scripts/load_slang_dict.py
uv run python scripts/rebuild_faiss.py

# Run real queries
uv run python scripts/smoke_rag_query.py        # 7/7 top-1 accuracy
uv run python scripts/smoke_hybrid_compare.py   # vector vs hybrid

# Run alias-mode eval
uv run python eval/run_eval.py --mode alias_only
```

---

## Project layout

```
neu-compass/
├── schemas/        Pydantic models (course v1.1, alias, coop)
├── db/             SQLite repositories + connection helper
├── scrapers/       syllabus (full) + neu_catalog/rmp/reddit (scaffold)
├── llm/            Gemini client + formatter + extract prompt + alias detector
├── rag/            embedder (bge-m3) + FAISS index + retriever + hybrid + hyde
├── eval/           test_set + run_eval + Ragas runner + compare_prompts
├── app/            Streamlit pages (eval_dashboard skeleton; MVP UI in Week 6)
├── api/            FastAPI entrypoint (Week 6)
├── scripts/        init_db / seed / rebuild / migrate / bench / smoke
├── data/           slang_dict.json + ground_truth/ (gitignored)
├── docs/           PLAN / ADRs / annotation_guide / pii_redaction
└── tests/          413 tests
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
| [docs/PLAN_v2.0.md](docs/PLAN_v2.0.md) | **Forward roadmap** (Weeks 6-8 + carry-forwards) |
| [docs/PLAN_v1.3.md](docs/PLAN_v1.3.md) | Original 8-week plan |
| [docs/wsl2_setup.md](docs/wsl2_setup.md) | WSL2 + uv + GPU setup, actual paths walked |
| [docs/annotation_guide.md](docs/annotation_guide.md) | Double-blind annotation SOP (Day 6-13 team use) |
| [docs/pii_redaction.md](docs/pii_redaction.md) | 380-line operational PII redaction guide |
| [docs/rag_smoke_results.md](docs/rag_smoke_results.md) | Three rounds of measured RAG results |
| [docs/path_decision.md](docs/path_decision.md) | ADR-0014 evidence (77x) |

---

## Compliance + Security red lines

- **F1 compliance**: no commercialization, no payment, no investor money (PLAN §9)
- **Personal API keys are personal**: never share via chat / Slack / email / screenshot
- **pre-commit detect-secrets in strict mode**: any detected secret fails the commit
- **PII k-anonymity enforced**: (company, role, term) triples must occur ≥ 2 times before publish
- **NEU domain restriction**: Google OAuth only accepts husky.neu.edu / northeastern.edu

Details: [docs/pii_redaction.md](docs/pii_redaction.md) + [PLAN §9](docs/PLAN_v1.3.md)

---

## License

No license during MVP. F1 visa rules require this remain a non-commercial side
project, and external PR contributions are paused pending legal review (see
PLAN §9.3 "before commercialization").
