# NEU-Compass · PLAN v2.1 (post-Week 6 checkpoint)

> **Updated**: 2026-05-03
> **Previous**: [docs/PLAN_v2.0.md](PLAN_v2.0.md) (Week 5 checkpoint), [docs/PLAN_v1.3.md](PLAN_v1.3.md) (original 8-week plan)
> **Purpose**: bootstrap context for the next development session.
> Read this first if you're a fresh agent picking up the project.

## 0. 5-minute bootstrap

If you (a fresh agent or a returning human) just opened this project, in
order:

1. Read **§1 Status snapshot** — what's actually done (Weeks 1-6)
2. Read **§2 Empirical findings** — measured numbers that constrain decisions
3. Skim **§3 Critical knowledge** — invariants you must not break
4. Read **§4 What's next** — Week 7 + 8 (narrower scope after Week 6)
5. (If you're going to write code) verify env:
   `wsl -d Ubuntu-24.04 -- bash -lc 'cd /mnt/h/neu-compass && uv run pytest tests/ -q'`
   should show **601 passed** in ~10s.

Week 6 has shipped end-to-end. The 8-week PLAN v1.3 is still valid for
Weeks 7-8 with the modifications in §4.

---

## 1. Status snapshot — what's done (Weeks 1-6)

### 1.1 Code surface complete

| Layer | Files | Tests | State |
|---|---|---:|---|
| Schema | `schemas/course.py` v1.1, `schemas/alias.py`, `schemas/coop.py`, `schemas/user.py` | 68 | ✅ full |
| DB | `db/init.sql`, `db/repository.py`, `db/alias_repository.py`, `db/coop_repository.py`, `db/user_repository.py`, `db/connection.py` | 104 | ✅ full |
| Scrapers | `scrapers/syllabus.py` | 18 | ✅ full |
| Scrapers | `scrapers/neu_catalog.py`, `rmp.py`, `reddit.py` | 59 | ✅ **live** (catalog scraped 6446 courses across 232 depts; RMP GraphQL verified; Reddit on PRAW with FakeReddit tests) |
| LLM | `llm/gemini_client.py` (+ `generate_text_stream`), `llm/formatter.py`, `llm/prompts/extract_v1.py`, `llm/prompts/chat_v1.py`, `llm/alias_detector.py`, `llm/review_enrichment.py` | 52 | ✅ full |
| RAG | `rag/embedder.py` (bge-m3), `rag/index.py` (FAISS), `rag/retriever.py`, `rag/query_normalizer.py`, `rag/hybrid.py` (BM25+RRF + stopword filter), `rag/hyde.py`, `rag/reranker.py` (bge-reranker-v2-m3) | 86 | ✅ full |
| Eval | `eval/test_set.json` v0.2 (42 queries), `eval/run_eval.py` (4 modes), `eval/compare_prompts.py`, `eval/ragas_runner.py` | 35 | ✅ full (calibrated on real catalog) |
| App (Streamlit) | `app/eval_dashboard.py`, `app/streamlit_app.py` (chat + streaming), `app/coop_view.py`, `app/state_manager.py`, `app/auth.py`, `app/api_client.py`, `app/streamlit_auth_ui.py` | 49 | ✅ full MVP |
| API (FastAPI) | `api/main.py` + `api/logging.py` + `api/dependencies.py` + `api/models.py` + `api/routes/` × 6 (`health`, `search`, `course`, `coop`, `chat`, `auth`) | 47 | ✅ full |

**601 tests pass in ~10s on WSL2.**

### 1.2 Operational tooling

```
scripts/
├── init_db.py                  ✅ idempotent SQLite init
├── seed_aai6600.py             ✅ real Spring 2026 syllabus → Course
├── seed_synthetic_courses.py   ✅ 6 synthetic courses (legacy; deletable now)
├── load_slang_dict.py          ✅ 39 slang entries loader (idempotent)
├── rebuild_faiss.py            ✅ ADR-0013 disaster recovery (--all / --status)
├── mark_pending_indexed.py     ✅ companion: pending → indexed after rebuild
├── migrate_schema.py           ✅ Pydantic schema_version migration runner
├── bench_path.py               ✅ ADR-0014 evidence generator (77x measured)
├── backup.sh                   ✅ rclone daily backup (PLAN §7.8)
├── smoke_rag_query.py          ✅ 7-query top-1 accuracy harness (legacy synthetic)
├── smoke_hybrid_compare.py     ✅ vector vs hybrid retriever side-by-side
├── scrape_neu_catalog.py       ✅ live full-sweep (232 depts → JSONL)
├── ingest_neu_catalog.py       ✅ JSONL → CourseRepository.upsert + cross-list aliases
├── enrich_course_via_rmp.py    ✅ RMP → Gemini → Course.evidence_snippets (default --dry-run)
├── probe_rmp.py                ✅ RMP GraphQL schema probe + fixture saver
├── probe_latency.py            ✅ /search p50/p95/p99 against test_set
└── validate_test_set.py        ✅ verify expected_course_ids exist in DB
```

### 1.3 Documentation

```
docs/
├── PLAN_v1.3.md                ✅ original 8-week plan
├── PLAN_v2.0.md                ✅ Week 5 checkpoint
├── PLAN_v2.1.md                ⬅ this file (Week 6 checkpoint)
├── annotation_guide.md         ✅ 392 lines, double-blind labeling SOP
├── pii_redaction.md            ✅ 380 lines, ops guide + k-anonymity examples
├── wsl2_setup.md               ✅ WSL + uv + GPU setup walkthrough
├── rag_smoke_results.md        ✅ 3 rounds of empirical RAG results
├── path_decision.md            ✅ auto-generated bench_path.py output
├── cloudflare_tunnel.md        ✅ named-tunnel runbook for soft-launch
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
courses             : 6469 rows  (full NEU catalog, status='indexed')
                      legacy synth-* rows deleted in Week 6 cleanup
course_aliases      : 91 rows   (47 cross_listed + 42 slang + 2 professor_attribution)
users               : 0 (populated when first NEU user logs in via OAuth)
user_unlocks        : 0
coop_experiences    : 0  ← Seed Data is a Week 7 task
schema_versions     : 1.1

~/neu-compass-data/faiss_index/
─────────────────────────────────────────────
index.faiss   ~26 MB (6469 vectors of 1024-dim float32)
id_map.json   ~180 KB

~/neu-compass-data/raw/neu_catalog/
─────────────────────────────────────────────
*.jsonl × 232  (CatalogEntry per line; resumable scrape outputs)

~/neu-compass-data/eval_results/
─────────────────────────────────────────────
baseline.json  rerank.json  (v0.2 test set runs)
```

---

## 2. Empirical findings to carry forward (Weeks 1-6)

### 2.1 ADR-0014 path strategy (77x)

| Operation | H: drive (NTFS via 9P) | WSL home (ext4) | Multiplier |
|---|---:|---:|---:|
| SQLite write p50 | 1157 ms | 15 ms | **77x** |
| SQLite query p50 | 2.47 ms | 0.01 ms | 247x |
| Sequential write 100MB | 213 MB/s | 1444 MB/s | 6.8x |

`SQLITE_PATH` and `FAISS_INDEX_PATH` **must** point at WSL home. H: is for code editing only.

### 2.2 bge-m3 score distribution is naturally compressed

7 synthetic courses, 7 differentiated queries, single 5090:
- Top-1 accuracy: 7/7
- Latency p50: 18 ms
- Score range: 0.46 – 0.70

Absolute thresholds (`if score < 0.5 reject`) **do not work** — vector scores cluster in 0.4-0.7 on related STEM text.

### 2.3 BM25 stopword filter widens the inversion gap 16x

| | gap |
|---|---:|
| vector-only (no fix possible) | -0.022 ❌ |
| hybrid without stopwords | +0.001 |
| hybrid + NLTK-style stopwords (110 words) | **+0.016** ✅ |

(`real-min - adv-max` over the 7-query smoke. Threshold-based "no clear match" rejection now feasible.)

### 2.4 Cold start is 70 seconds; production must pre-warm

First `BGEM3FlagModel.encode()` call: 70 s (model download cached after first time). FastAPI `lifespan` calls `embedder.encode(["warmup"])` at startup so user requests don't pay it. `/ready` returns `{"status": "warming"}` until done.

### 2.5 Live catalog scrape (Week 6)

| | value |
|---|---:|
| NEU departments | 232 |
| Courses ingested | 6446 (catalog) + 23 carry-over = **6469 indexed** |
| Scrape time (1 req/sec polite) | ~25 min |
| Ingest + cross-list alias linking | < 5 s |
| FAISS rebuild (full corpus on 5090) | ~22 s (203 batches @ 64 it/s) |

### 2.6 /search end-to-end latency (TestClient + warm bge-m3)

| | ms |
|---|---:|
| p50 | **40.1** |
| p95 | 45.4 |
| p99 | 46.3 |
| mean | 29.9 (±17.6) |

**PLAN §4.1 target: p50 < 300 ms → 7.5x headroom.** Bimodal distribution: alias queries ~3 ms, hybrid queries ~45 ms.

### 2.7 Eval baseline on test_set v0.2 (42 queries, real catalog)

| Mode | Recall@5 | MRR |
|---|---:|---:|
| `hybrid_with_alias` (production) | 0.601 | 0.603 |
| `+ bge-reranker-v2-m3` (pool=20→k=5) | **0.636** | 0.545 |

Per-category (production path):
| | hits | recall@5 |
|---|---|---:|
| simple (12) | 9 | 0.750 |
| medium (12) | 8 | 0.486 |
| complex (8) | 3 | 0.250 |
| boundary (6) | 6 | **1.000** |
| adversarial (4) | 0 | 0.000 — system has no rejection layer yet |

Reranker boosts R@5 by +0.035 (3 query flips: `Machine Learning`, `Apache Spark`, `VC dimension PAC`). MRR drops slightly (-0.058) — broader semantic re-ranking sometimes pushes the most specific match deeper.

### 2.8 RMP GraphQL schema verified

NEU Boston main campus school id: `U2Nob29sLTY5Ng==` (base64 `School-696`). GraphQL fields verified 2026-05-03:
- `qualityRating` (was `overallRating` historically)
- `difficultyRatingRounded` (was `difficultyRating`)
- `wouldTakeAgainPercent` at teacher level only (not per-rating)

If schema drifts again, refresh `tests/fixtures/rmp/teacher_search.json` via `scripts/probe_rmp.py --save`.

### 2.9 Reranker workaround for FlagEmbedding API drift

`FlagEmbedding.FlagReranker` calls `tokenizer.prepare_for_model` which has been removed from `transformers >= 4.30`. We bypass FlagReranker and use `AutoModelForSequenceClassification` directly with the same bge-reranker-v2-m3 weights. Sigmoid-normalized to [0, 1] so future absolute-threshold rejection becomes possible.

---

## 3. Critical knowledge — invariants not to break

### 3.1 ADR-0013: SQLite is the source of truth

- All data writes go to SQLite first.
- FAISS is a derived index; lose FAISS → run `rebuild_faiss.py --all` (or `--status pending` after fresh ingest).
- After rebuild, run `mark_pending_indexed.py` to flip `status='pending'` → `'indexed'` so retriever sees the rows.
- `courses.status` state machine: `pending → indexed | failed`.
- **Retriever filters `WHERE status='indexed'`** so pending courses cannot leak.

### 3.2 v_course_lookup view filters `review_status='approved'`

- LLM-inferred aliases land with `review_status='pending'`.
- v_course_lookup union query excludes pending.
- `query_normalizer.py` and `AliasRepository.resolve()` both go through the view.
- **Therefore unreviewed LLM aliases never affect retrieval.** Security boundary, not just hygiene.

### 3.3 Schema soft-fields require evidence_snippets

- `Course.workload_hours_per_week / difficulty_score / skill_tags / career_relevance / controversial_signals`: any non-empty value MUST have at least one matching `evidence_snippet`.
- Enforced by `Course.model_validator` — Pydantic raises ValidationError otherwise.

### 3.4 PII k-anonymity rule (k=2)

- Co-op record's (company, role, coop_term) triple must occur ≥ 2 times in the corpus + new = ≥ 2 BEFORE publish.
- Enforced server-side at `POST /coop` via `is_uniquely_identifying`. Tests pin both reject + accept paths.

### 3.5 OAuth domain whitelist is `is_email_allowed`, not substring

- `email.endswith("husky.neu.edu")` would let `attacker@husky.neu.edu.evil.com` through — **forbidden**.
- `is_email_allowed` splits on `@` and exact-matches the domain part.
- Enforced at three layers: `validate_id_token_claims` (in JWT verification), `/auth/callback` route (401 on OAuthError), and the Google `hd=` hint (UX-only).

### 3.6 /chat NDJSON wire format (Week 6 contract)

Each line is one JSON object, in order: `meta` → `token`* → (`error`?) → `done`.
- `meta` always first; carries `matched_via`, `results: SearchHitOut[]`, `retrieval_ms`.
- `token` events carry `text`. Streamlit `st.write_stream` consumes these.
- `error` events carry `detail` and TERMINATE the stream — caller renders the partial output up to that point.
- `done` always last, even on error path.

Streamlit consumer: `app.streamlit_app.stream_assistant(api, body, state)` is the canonical generator. Tests pin shape via `_FakeApi` events.

### 3.7 F1 compliance red lines (PLAN §9)

- No payment system, no commercialization, no investor money during MVP.
- API key never in chat / Slack / email / screenshot. detect-secrets pre-commit is strict.
- Google OAuth domain-restricted to husky.neu.edu / northeastern.edu.

### 3.8 Files that must NEVER be committed

- `.env` (gitignored; only `.env.example` is tracked)
- `data/courses.db`, `*.faiss`, `data/raw/*`, `data/coop_seed/*`
- detect-secrets pre-commit catches API key shapes; trust but verify.

---

## 4. What's next — Weeks 7-8 forward plan

### 4.1 Week 7: Soft launch + UGC flywheel

PLAN v1.3 §5 Week 7 still applies; updated based on Week 6 ship state:

| Task | File / Action | Notes |
|---|---|---|
| Cloudflare Tunnel deploy | runbook → live | docs/cloudflare_tunnel.md walks every command |
| Google OAuth client config | Google Cloud Console + .env | redirect URI = `https://compass.<your-zone>.com/` |
| Real Gemini integration smoke | `enrich_course_via_rmp.py --live --save` | 1-2 courses; observe Gemini bill |
| Team of 3 hits public URL ≥ 20 e2e queries | manual | This is what was deferred from Week 6 acceptance |
| Real query log analysis (structlog) | grep request.handled in JSON logs | Feeds test_set v0.3 expansion |
| Co-op UGC submission via /coop | already wired | Confirm 422 path under k=1 attempt |
| Give-to-get visibility levels | already wired in CoopRepository | Confirm UI shows level badges + "🔒 Contribute to unlock" |
| Bug fix + Schema v1.1 iteration | as needed | Track via git history |
| Seed Data ≥ 30 records | curate offline + COPY-in via SQL | PLAN §6.5 distribution: 12 quant_fintech, 8 big_tech, 5 biotech, 5 startup |

**Week 7 acceptance**: ≥ 200 real queries collected, ≥ 5 core contributors, organic contribution rate ≥ 5%.

### 4.2 Week 8: Data analysis + portfolio packaging

PLAN v1.3 §5 Week 8 still applies. Updates from Week 6 findings:

| Task | File | Notes |
|---|---|---|
| `eval/test_set.json` → 100 queries | bound by query log size | Aim for 30 simple / 30 medium / 20 complex / 10 boundary / 10 adversarial |
| Ragas eval with real Gemini judge | `eval/ragas_runner.py` already there | Faithfulness, Context Precision, Answer Relevance |
| Cross-encoder reranker tuning | `rag/reranker.py` | Currently raw bge-reranker-v2-m3; try score blending with RRF |
| roadmap_v3.md (forward) | new doc | Based on actual user signals |
| Latency tail tuning | `scripts/probe_latency.py` | If real users need < 100ms p50, batch queries / drop reranker on hot path |

### 4.3 Open TODOs (Week 6 carry-forwards)

| Priority | TODO | Where | Effort |
|---|---|---|---|
| P0 | Cloudflare deploy + team smoke | runbook | manual |
| P0 | Real Gemini smoke on 1-2 courses | `scripts/enrich_course_via_rmp.py --live` | 30 min |
| P1 | Adversarial rejection layer | thresholding `reranker.score()` < 0.4 | ~1h |
| P1 | RRF + reranker score blending | `rag/reranker.py` + eval | ~2h |
| P2 | test_set expansion to 100 queries | `eval/test_set.json` | bound by query log availability |
| P2 | 19 more Ground Truth annotated courses | `data/ground_truth/` | team task; less urgent now that catalog has 6469 |
| P2 | 30 Co-op Seed Data records | `data/coop_seed/` | team + curation |
| P2 | Reddit live smoke | needs `.env` REDDIT_CLIENT_ID/SECRET | code & tests are mock-only by design |

---

## 5. Quick reference for the next agent

### 5.1 Where to look in code for X

| You want to... | Read these files |
|---|---|
| Understand a Course's shape | `schemas/course.py` v1.1 |
| Understand a User's shape | `schemas/user.py` (Google sub claim) |
| See how to insert a course | `db/repository.py` `CourseRepository.upsert` |
| See how a user is persisted on login | `db/user_repository.py` `upsert_login` |
| Add a new alias source | `db/alias_repository.py` `add` / `add_or_skip` |
| Trace a search query end-to-end | `api/routes/search.py` → `query_normalizer` → `HybridRetriever` |
| Trace a chat query end-to-end | `api/routes/chat.py` → retrieval + `chat_v1.build_prompt` + `generate_text_stream` |
| Trace an OAuth login | `app.streamlit_auth_ui.handle_oauth_callback` → `/auth/callback` → `exchange_code_for_token` → `UserRepository.upsert_login` |
| Add a new retrieval mode | `rag/hybrid.py` (RRF pattern), `rag/reranker.py` (cross-encoder pattern) |
| Add a new metric | `eval/run_eval.py` `recall_at_k` / `reciprocal_rank` |
| Mock the LLM in tests | `tests/test_api_chat.py` `_override_stream` pattern |
| Mock RMP / Reddit / OAuth | fixture-backed `httpx.MockTransport` (rmp), `_FakeReddit` (reddit), injectable verifiers (oauth) |

### 5.2 Common gotchas

- **`uv run python`, not `python`** — outside the venv your script will see system Python.
- **`bash -lc` for WSL invocation** — `bash -c` doesn't load `~/.bashrc`, so `uv` won't be on PATH.
- **`db.connection.connect` sets `check_same_thread=False`** — required for FastAPI async handlers + TestClient (Week 6 finding). Don't change without re-running test_api_*.
- **course_id ≠ primary_code** — course_id is internal (`neu-aai-6600`); primary_code is human (`AAI 6600`). `ingest_neu_catalog.course_id_for(code)` is the canonical mapping.
- **status='indexed' filter** — retriever and BM25Corpus.from_db both filter this. After fresh ingest you must run `mark_pending_indexed.py`.
- **rebuild_faiss is non-mutating** — it builds the FAISS file but does NOT touch courses.status. Pair with mark_pending_indexed.
- **L2 normalize before FAISS** — `rag/embedder.py` does it via `normalize=True` default.
- **SQLite `?` parameter binding** — never f-string SQL; existing code is consistent, keep it that way.
- **`pytest -m live`** is opt-in for network tests (none currently exist; marker reserved). Default `pytest tests/` is offline.

### 5.3 First 30 minutes for a new agent

```bash
# Verify state
wsl -d Ubuntu-24.04
cd /mnt/h/neu-compass
git log --oneline | head -3
uv run pytest tests/ -q                           # 601 passed
uv run python scripts/probe_latency.py --warmup 1 --iterations 1  # p50 ~40 ms

# Read these in order
cat docs/PLAN_v2.1.md         # this file
cat docs/PLAN_v2.0.md         # Week 5 checkpoint (for context)
cat docs/rag_smoke_results.md  # what we measured at Week 4-5
cat docs/adr/0013*.md          # SQLite truth source invariant
cat docs/adr/0014*.md          # path strategy
cat README.md                  # general orientation

# Try the live stack (assumes catalog already ingested)
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 &
uv run streamlit run app/streamlit_app.py --server.port 8501 --server.address 0.0.0.0 &
# Open http://localhost:8501
```

### 5.4 Conventions worth preserving

- Each Pydantic model has `model_config = ConfigDict(extra="forbid")`. Keep it.
- Tests use `tests/conftest.py:empty_db` fixture (in-memory, FK on, `check_same_thread=False`). Build on it.
- API tests use `api_client` fixture (build_test_app + override get_db_conn). Keep state via `app.state.{embedder, faiss_index, bm25_corpus}`.
- Repositories take a connection in `__init__`; caller manages lifecycle. Don't hide connections.
- LLM-callable functions take an injectable `model` / `expand_fn` / `llm_fn` / `stream_fn` parameter so tests don't hit live APIs.
- ADRs use the template in `docs/adr/0000-template.md`. Keep the format consistent.
- Commit messages follow `feat(scope): ...` / `feat(weekN): ...` / `docs: ...` / `test: ...` pattern.

### 5.5 Things explicitly NOT yet done (don't assume otherwise)

- ❌ Live Gemini API calls in production (script + path ready; no real call has run yet)
- ❌ Live Cloudflare Tunnel deployment (runbook ready, manual setup)
- ❌ Real Co-op Seed Data (Week 7 task; 0 rows in DB)
- ❌ 19 Ground Truth annotated courses (less urgent now that 6469 catalog rows exist)
- ❌ Adversarial query rejection (system always returns top-K; no threshold layer)
- ❌ Live Reddit scrape (mock-only tests; needs real `.env` PRAW credentials to enable)

---

## 6. Versioning

- **PLAN v1.0**: original 8-week plan (PDF user supplied)
- **PLAN v1.2 (FINAL)**: PDF revision the user shared at session start
- **PLAN v1.3**: Week 0 critique-driven revision
- **PLAN v2.0**: Week 5 checkpoint snapshot
- **PLAN v2.1**: this file. Week 6 has shipped. Forward roadmap is Week 7-8.

The next plan should be a **v3.0** when the team-of-3 soft launch (Week 7) produces real query-log signal, OR when the eval test_set hits 100 queries.

---

## 7. Acknowledged limits + intentional tradeoffs

These are by design, not bugs:

- **No live Gemini call has been made yet** — the path is wired (`scripts/enrich_course_via_rmp.py --live`) but the user has not paid for a smoke. Deliberate: lets us deploy to Cloudflare and pull the trigger when ready.
- **No production deployment** — all "smoke tests" run locally in WSL2 + TestClient. Cloudflare Tunnel is the next manual step.
- **No real OAuth round-trip tested** — domain whitelist + JWT verification + upsert_login are all unit-tested via mocks; the real Google → ?code= → /auth/callback chain needs Cloudflare + a real OAuth client_id to verify end-to-end.
- **Adversarial queries currently produce noise output** — the retrieval layer always returns top-K even for nonsense input. PLAN §4 P1 has the rejection layer; reranker scores are sigmoid-normalized to [0, 1] so a `< 0.4` threshold becomes a one-line addition.
- **`eval/test_set.json` has 42 queries**, not 100. Real-query log expansion is gated on Week 7 traffic.
- **Streamlit `st.write_stream` works** — verified via mock `_FakeApi` in tests; live integration depends on Gemini call actually happening.
- **`synth-*` legacy course rows have been deleted** in Week 6 cleanup. `seed_synthetic_courses.py` still exists but its output is now redundant with the real catalog ingest.

---

**End of v2.1**. Open the next session with this doc as starter context.
