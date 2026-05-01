# NEU-Compass · PLAN v2.0 (post-Week 5 checkpoint)

> **Updated**: 2026-04-30
> **Previous**: [docs/PLAN_v1.3.md](PLAN_v1.3.md) (the original 8-week plan)
> **Purpose**: bootstrap context for the next development session.
> Read this first if you're a fresh agent picking up the project.

## 0. 5-minute bootstrap

If you (a fresh agent or a returning human) just opened this project, in
order:

1. Read **§1 Status snapshot** — what's actually done
2. Read **§2 Empirical findings** — the real numbers we found, that constrain decisions
3. Skim **§3 Critical knowledge** — invariants you must not break
4. Read **§4 What's next** — the actual roadmap
5. (If you're going to write code) verify env: `wsl -d Ubuntu-24.04 -- bash -c 'cd /mnt/h/neu-compass && uv run pytest tests/ -q'` should show 413 passed

The 8-week PLAN v1.3 is still valid for Weeks 6-8 with the modifications in §4.

---

## 1. Status snapshot — what's done (Weeks 1-5)

### 1.1 Code surface complete

| Layer | Files | Tests | State |
|---|---|---:|---|
| Schema | `schemas/course.py` v1.1, `schemas/alias.py`, `schemas/coop.py` | 53 | ✅ full |
| DB | `db/init.sql`, `db/repository.py`, `db/alias_repository.py`, `db/coop_repository.py`, `db/connection.py` | 89 | ✅ full |
| Scrapers | `scrapers/syllabus.py` | 18 | ✅ full |
| Scrapers | `scrapers/neu_catalog.py`, `rmp.py`, `reddit.py` | 16 | 🟡 **scaffold** (Pydantic + tests; live impl pending) |
| LLM | `llm/gemini_client.py`, `llm/formatter.py`, `llm/prompts/extract_v1.py`, `llm/alias_detector.py` | 41 | ✅ full |
| RAG | `rag/embedder.py` (bge-m3), `rag/index.py` (FAISS), `rag/retriever.py`, `rag/query_normalizer.py`, `rag/hybrid.py` (BM25+RRF), `rag/hyde.py` | 76 | ✅ full |
| Eval | `eval/test_set.json` (5 queries), `eval/run_eval.py`, `eval/compare_prompts.py`, `eval/ragas_runner.py` | 35 | ✅ full (test_set is 5/100 target) |
| App | `app/eval_dashboard.py` | 7 | ✅ skeleton (full Streamlit MVP in Week 6) |
| API | — | — | 🔴 not started (Week 6) |

**413 tests pass in 8s on WSL2.**

### 1.2 Operational tooling

```
scripts/
├── init_db.py              ✅ idempotent SQLite init
├── seed_aai6600.py         ✅ real Spring 2026 syllabus → Course
├── seed_synthetic_courses.py ✅ 6 differentiated synthetic courses (CS/DS/MATH/INFO)
├── load_slang_dict.py      ✅ 39 slang entries loader (idempotent)
├── rebuild_faiss.py        ✅ ADR-0013 disaster recovery
├── migrate_schema.py       ✅ Pydantic schema_version migration runner
├── bench_path.py           ✅ ADR-0014 evidence generator (77x measured)
├── backup.sh               ✅ rclone daily backup (PLAN §7.8)
├── smoke_rag_query.py      ✅ 7-query top-1 accuracy harness
└── smoke_hybrid_compare.py ✅ vector vs hybrid retriever side-by-side
```

### 1.3 Documentation

```
docs/
├── PLAN_v1.3.md            ✅ original 8-week plan (still authoritative for §0-§4)
├── PLAN_v2.0.md            ⬅ this file
├── annotation_guide.md     ✅ 392 lines, double-blind labeling SOP
├── pii_redaction.md        ✅ 380 lines, ops guide + k-anonymity examples
├── wsl2_setup.md           ✅ WSL + uv + GPU setup walkthrough
├── rag_smoke_results.md    ✅ 3 rounds of empirical RAG results
├── path_decision.md        ✅ auto-generated bench_path.py output
└── adr/
    ├── 0000-template.md
    ├── 0001-sqlite-faiss-vs-milvus.md
    ├── 0013-sqlite-as-source-of-truth.md
    └── 0014-h-drive-code-wsl-data.md
```

### 1.4 What lives in the runtime DB now

```
~/neu-compass-data/courses.db (WSL home, ext4)
─────────────────────────────────────────────
courses             : 7 rows (1 real AAI 6600 + 6 synthetic)
                      all status='indexed' after rebuild_faiss
course_aliases      : ~45 rows (6 manual AAI + 39 slang dict)
users               : 0
user_unlocks        : 0
coop_experiences    : 0  ← Seed Data is a Week 6/7 task
schema_versions     : 1.1

~/neu-compass-data/faiss_index/
─────────────────────────────────────────────
index.faiss   ~30 KB (7 vectors of 1024-dim float32)
id_map.json   ~250 B
```

---

## 2. Empirical findings to carry forward

### 2.1 ADR-0014 path strategy (77x)

| Operation | H: drive (NTFS via 9P) | WSL home (ext4) | Multiplier |
|---|---:|---:|---:|
| SQLite write p50 | 1157 ms | 15 ms | **77x** |
| SQLite query p50 | 2.47 ms | 0.01 ms | 247x |
| Sequential write 100MB | 213 MB/s | 1444 MB/s | 6.8x |

**Operational impact**: SQLITE_PATH and FAISS_INDEX_PATH **must** point at WSL home for any non-trivial dataset. H: drive is fine for code editing only.

### 2.2 bge-m3 score distribution is naturally compressed

7 courses, 7 differentiated queries, single 5090:

```
Top-1 accuracy:    7/7
Latency p50:       18 ms
Score range:       0.46 - 0.70
Score gap (best vs adversarial): 0.20 (NOT large)
```

**Operational impact**: Absolute thresholds (`if score < 0.5 reject`) **do not work**. Vector scores cluster in a 0.4-0.7 band on related STEM text.

### 2.3 The 0.485 > 0.463 inversion

Vector-only retrieval put adversarial query "quantum cryptography" at 0.485, **higher than** legitimate "graph algorithms BFS DFS" at 0.463.

After hybrid (BM25 + vector RRF):

```
                       vector-only    hybrid (RRF k=60)
real-min - adv-max     -0.022 ❌      +0.001 ✓ (barely)
```

**Status**: hybrid fixes the inversion technically but margin is tiny.

### 2.4 BM25 stopword filtering is the next quick win

The 0.001 hybrid margin is small because BM25 doesn't filter "and"/"the"/"of". Adversarial "ancient roman history" still gets meaningful BM25 score from common words. Filtering NLTK stopwords would widen the margin substantially.

**Estimated work**: 10 lines in `rag/hybrid.py:tokenize`.

### 2.5 bge-m3 cold start is 70 seconds

First `BGEM3FlagModel.encode()` call after Python process start: 70 s.

**Operational impact for Week 6**: FastAPI startup hook **must** call `embedder.encode(["warmup"])` before accepting traffic, or first user query times out.

### 2.6 rebuild_faiss(N) ≈ 73s + N × ~50ms

Mostly model load. Embedding 100 docs after warm-up is ~5s.

**Operational impact**: rebuild_faiss is for cron + disaster recovery, never the user request path.

---

## 3. Critical knowledge — invariants not to break

### 3.1 ADR-0013: SQLite is the source of truth

- All data writes go to SQLite first.
- FAISS is a derived index; lose FAISS → run rebuild_faiss.py from SQLite.
- `courses.status` state machine: `pending → indexed | failed`.
- **Retriever filters `WHERE status='indexed'`** so pending courses cannot leak.
- New course or content update: status resets to 'pending' via `CourseRepository.upsert()`.

### 3.2 v_course_lookup view filters review_status='approved'

- LLM-inferred aliases land with `review_status='pending'` (PLAN §3 design).
- v_course_lookup union query excludes pending.
- `query_normalizer.py` and `AliasRepository.resolve()` both go through the view.
- **Therefore unreviewed LLM aliases never affect retrieval.** This is a security boundary, not just hygiene.

### 3.3 Schema soft-fields require evidence_snippets

- `Course.workload_hours_per_week / difficulty_score / skill_tags / career_relevance / controversial_signals`: any non-empty value MUST have at least one matching `evidence_snippet`.
- Enforced by `Course.model_validator` — Pydantic raises ValidationError otherwise.
- Synthetic seed courses leave these empty (no real reviews).

### 3.4 PII k-anonymity rule (k=2)

- Co-op record's (company, role, coop_term) triple must occur ≥ 2 times in the corpus before publish.
- Helper: `schemas.coop.is_uniquely_identifying`.
- **Enforce in the API layer (Week 6) before write.**

### 3.5 F1 compliance red lines (PLAN §9)

- No payment system, no commercialization, no investor money during MVP.
- API key never in chat / Slack / email / screenshot. detect-secrets pre-commit is strict.
- Google OAuth domain-restricted to husky.neu.edu / northeastern.edu.

### 3.6 Files that must NEVER be committed

- `.env` (gitignored; only `.env.example` is tracked)
- `data/courses.db`, `*.faiss`, `data/raw/*`, `data/coop_seed/*`
- detect-secrets pre-commit catches API key shapes; trust but verify with `git diff --cached` before push.

---

## 4. What's next — Weeks 6-8 forward plan

PLAN v1.3 §5 is still authoritative for the structure. v2.0 modifies based on findings.

### 4.1 Week 6: API + UI MVP (was: Week 6 §5)

**Modifications from v1.3**:
- Add **FastAPI startup hook** to pre-warm bge-m3 (§2.5 above).
- Add **BM25 stopword filtering** before any user-facing search (§2.4 above).
- `app/eval_dashboard.py` already shipped; only the Chat UI is new.

| Task | File | Notes |
|---|---|---|
| FastAPI app + structlog logging | `api/main.py` + `api/logging.py` | startup hook MUST warm embedder |
| `/search` endpoint | `api/routes/search.py` | use HybridRetriever; pass query through normalizer first |
| `/course/{course_id}` endpoint | `api/routes/course.py` | rehydrate Course; redact based on user tier (Co-op fields) |
| `/upload-coop` endpoint (Week 7 alt) | `api/routes/coop.py` | run is_uniquely_identifying() before persist |
| Streamlit state_manager.py | `app/state_manager.py` | PLAN §7.6 SOP already specified |
| Streamlit Chat UI + Course Detail | `app/streamlit_app.py` | st.write_stream for Gemini streaming |
| Evidence Snippets bubble component | UI component in app/ | clicking bubble shows source quote |
| Co-op progressive unlock UI | `app/coop_view.py` | use CoopRepository.list_visible_to_user() |
| Google OAuth wiring | `app/auth.py` | restrict to NEU domains; persist user record |
| Cloudflare Tunnel config | (no source file; runbook only) | for soft-launch URL |
| **BM25 stopword filtering** ⬅ NEW | `rag/hybrid.py:tokenize` | NLTK stopwords list; ~10 lines |

**Acceptance for Week 6** (modified):
- Team of 3 hits the public URL and runs ≥20 end-to-end queries.
- OAuth properly rejects non-NEU email.
- p50 search latency < 300ms after warm-up (new constraint based on §2.5/§2.6).
- BM25 stopword filtering: real-min - adv-max gap > 0.005 (was 0.001 before fix).

### 4.2 Week 7: Soft launch + UGC (largely unchanged)

PLAN v1.3 §5 Week 7 stands. Modifications:
- Use `CoopRepository.list_visible_to_user()` for the give-to-get gate; this is already implemented.
- Run `is_uniquely_identifying()` server-side on every Co-op submission.
- Cloudflare Tunnel logs go through structlog (Week 6 deliverable).

### 4.3 Week 8: Wrap-up + portfolio (largely unchanged)

PLAN v1.3 §5 Week 8 stands. Add:
- Test_set expansion: take real query log → backfill `eval/test_set.json` toward the 100-query target.
- Run Ragas eval with real Gemini judge → publish numbers.
- `roadmap_v2.md` based on actual data findings.

### 4.4 Open TODOs (Week 5 carry-forwards)

| Priority | TODO | Where | Effort |
|---|---|---|---|
| P0 | Live impl of `scrapers/neu_catalog.py` | NEU CPS catalog URL probe | 4-6 hours |
| P0 | Live impl of `scrapers/rmp.py` | RMP GraphQL schema verify | 3-4 hours |
| P0 | Live impl of `scrapers/reddit.py` | PRAW with real credentials | 2 hours |
| P1 | BM25 stopword filtering | `rag/hybrid.py` | 30 min |
| P1 | FastAPI startup pre-warm hook | `api/main.py` | 30 min |
| P1 | Cross-encoder reranker | `rag/reranker.py` (new) | 4 hours, v2 territory |
| P2 | test_set expansion to 100 queries | `eval/test_set.json` | bound by data availability |
| P2 | 19 more Ground Truth annotated courses | `data/ground_truth/` | team task |
| P2 | 30 Co-op Seed Data records | `data/coop_seed/` | team + curation |

---

## 5. Quick reference for the next agent

### 5.1 Where to look in code for X

| You want to... | Read these files |
|---|---|
| Understand a Course's shape | `schemas/course.py` v1.1 |
| See how to insert a course | `db/repository.py` `CourseRepository.upsert` |
| Add a new alias source | `db/alias_repository.py` `add` |
| Trace a query end-to-end | `rag/retriever.py` `Retriever.search` (3-step) |
| Add a new retrieval mode | `rag/hybrid.py` (RRF pattern), `rag/hyde.py` (wrapper pattern) |
| Add a new metric | `eval/run_eval.py` `recall_at_k` / `reciprocal_rank` |
| See how Pydantic + SQLite serialize | `db/repository.py` `_serialize` / `_row_to_course` |
| See how to mock the LLM | `tests/test_gemini_client.py` `_FakeModel` pattern |

### 5.2 Common gotchas

- **`uv run python`, not `python`** — outside the venv your script will see system Python.
- **Course code regex normalizes** — `"cs5800"` → `"CS 5800"` automatically. Don't pre-format.
- **SQLite FK is per-connection** — `db/connection.py:connect` always sets `PRAGMA foreign_keys = ON`. Don't bypass it.
- **course_id ≠ primary_code** — course_id is internal UUID-like (e.g. `neu-aai-6600`); primary_code is human (e.g. `AAI 6600`).
- **status='indexed' filter** — retriever and BM25Corpus.from_db both filter this. If your test seems to "lose" a course, it's likely still pending.
- **L2 normalize before FAISS** — `rag/embedder.py` does it via the `normalize=True` default. Don't add to FAISS without it; IndexFlatIP isn't actually computing cosine without normalization.
- **Chinese terminal cp936** — scripts use `sys.stdout.reconfigure(utf-8)`. Don't break this.
- **Don't commit uv.lock changes silently** — review `git diff uv.lock` carefully; deps should not creep without intent.

### 5.3 First 30 minutes for a new agent

```bash
# Verify state
wsl -d Ubuntu-24.04
cd /mnt/h/neu-compass
git log --oneline | head -16
uv run pytest tests/ -q                   # 413 passed
uv run python scripts/smoke_rag_query.py  # 7/7 top-1

# Read these in order
cat docs/PLAN_v2.0.md         # this file
cat docs/rag_smoke_results.md  # what we measured
cat docs/adr/0013*.md          # SQLite truth source invariant
cat docs/adr/0014*.md          # path strategy
cat README.md                  # general orientation
```

### 5.4 Conventions worth preserving

- Each Pydantic model has `model_config = ConfigDict(extra="forbid")`. Keep it.
- Tests use `tests/conftest.py:empty_db` fixture for in-memory SQLite. Build on it.
- Repositories take a connection in __init__; caller manages lifecycle. Don't hide connections.
- LLM-callable functions take an injectable `model` / `expand_fn` / `generate_fn` parameter so tests don't hit live APIs.
- Scaffold modules raise `NotImplementedError` with a clear message about what's pending. Don't silently no-op.
- ADRs use the template in `docs/adr/0000-template.md`. Keep the format consistent.

### 5.5 Things explicitly NOT yet done (don't assume otherwise)

- ❌ Live Gemini API calls (no real LLM extraction has run)
- ❌ Live NEU Catalog / RMP / Reddit scraping (3 scaffold modules)
- ❌ FastAPI server (Week 6)
- ❌ Streamlit Chat UI (Week 6; eval_dashboard skeleton only)
- ❌ Google OAuth wiring (Week 6)
- ❌ Cloudflare Tunnel deployment (Week 6)
- ❌ Real Co-op Seed Data (Week 6/7, team task)
- ❌ 19 of 20 Ground Truth courses annotated (team task; only AAI 6600 is real)
- ❌ Cross-encoder reranker (v2 territory)

---

## 6. Versioning

- **PLAN v1.0**: original 8-week plan (PDF user supplied)
- **PLAN v1.2 (FINAL)**: PDF revision the user shared at session start
- **PLAN v1.3**: my Week 0 critique-driven revision (`docs/PLAN_v1.3.md`)
- **PLAN v2.0**: this file. Snapshot at end of Week 5 + forward roadmap.

The next plan should probably be a **v2.1** when Week 6 ships, or **v3.0** if Week 6's findings warrant rethinking Weeks 7-8.

---

## 7. Acknowledged limits + intentional tradeoffs

These are by design, not bugs:

- **Synthetic course descriptions** are deliberately written with differentiated vocabulary so bge-m3 can pull them apart. Real NEU syllabi will be tighter — expect score range to compress further.
- **eval/test_set.json has 5 queries**, not 100. The 100 needs real data we don't have yet.
- **No actual production deployment** — all "smoke tests" run locally in WSL2.
- **No real Gemini API calls in tests**. Mocked everywhere. Only `seed_aai6600.py` build_course() uses Pydantic to construct from human-curated data.
- **Cold-start latency is 70s** and we accept that for MVP. Production fix is FastAPI startup hook + worker pre-warming, slated for Week 6.

---

**End of v2.0**. Open the next session with this doc as starter context.
