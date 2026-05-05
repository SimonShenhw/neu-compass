# NEU-Compass · PLAN v2.2 (Week 7 sprint plan, post team-sync)

> **Updated**: 2026-05-03
> **Previous**: [docs/PLAN_v2.1.md](PLAN_v2.1.md) (Week 6 checkpoint), [docs/PLAN_v2.0.md](PLAN_v2.0.md) (Week 5), [docs/PLAN_v1.3.md](PLAN_v1.3.md) (original 8-week plan)
> **Purpose**: Week 7 execution plan after 0502 team brainstorm. Tightens scope, locks blending experiment design, defers social endpoints to post-MVP.
> **Read order if you're a fresh agent**: §0 → §1 → §2 → §3.

---

## 0. What changed from v2.1

v2.1 was a Week 6 status snapshot. v2.2 is a **forward-looking sprint plan** with three pivots driven by the 0502 team brainstorm:

1. **Scope contraction**: Streamlit user UI is frozen. FastAPI becomes the canonical surface; Andy Dong owns the web frontend. We become a Backend-as-a-Service for the team.
2. **Locked retrieval experiment**: MRR regression observed in v2.1 §2.7 (-0.058 vs hybrid baseline) is addressed via Z-score blending of RRF and reranker sigmoid. Grid search on α ∈ {0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0}.
3. **Social schema preparation, not implementation**: `user_courses` table DDL is added now; `/course/{id}/classmates` endpoint is deferred until real users exist.

The 0502 team brainstorm (LYU + Andy Dong + Yuang Dai + me) reaffirmed "find course buddies + selection assist + social" as the product north star, with **MVP-first** consensus. v2.2 reflects this: ship the Search-as-a-Service core in Week 7, leave room for social layer in v3.0.

---

## 1. v2.1 invariants still in force

These do **not** change in v2.2. If anything in §3 contradicts them, §1 wins.

- **ADR-0013**: SQLite is the source of truth; FAISS is derived
- **ADR-0014**: `SQLITE_PATH` and `FAISS_INDEX_PATH` on WSL home (ext4), not H: drive (77x penalty)
- **v_course_lookup filters `review_status='approved'`**: unreviewed LLM aliases never affect retrieval
- **Schema soft-fields require evidence_snippets**: Pydantic validator enforces
- **k=2 anonymity for Co-op**: enforced server-side at `POST /coop`
- **OAuth domain whitelist via `is_email_allowed`**: exact match on `@domain`, not substring
- **F1 compliance red lines**: no payments, no commercialization, no investor money, OAuth domain-restricted to husky.neu.edu / northeastern.edu
- **Test discipline**: `uv run pytest tests/ -q` must show **601+ passed** at all times. Don't merge red.

Cold start (70s on first BGEM3 encode), bimodal latency (~3ms alias, ~45ms hybrid), SQLite parameter binding via `?`, status='indexed' filter — all still apply. See v2.1 §3 for full details.

---

## 2. Week 7 sprint goals

### 2.1 KPIs (acceptance criteria)

Week 7 ships if **all four** are met by EOW:

| # | KPI | How to measure | Source |
|---|---|---|---|
| 1 | Public URL serving FastAPI | `curl https://compass.<your-zone>.com/health` returns 200 | Cloudflare Tunnel |
| 2 | ≥ 200 real queries logged | `grep request.handled api.log \| jq -s length` | structlog JSON |
| 3 | ≥ 5 core contributors hitting URL | unique `user_id` in user_repository | OAuth flow |
| 4 | Blending experiment closed with α decision | `eval/blend_sweep_results.json` + ADR-0015 | new artifact |

KPIs 1-3 are unchanged from v2.1 §4.1. KPI 4 is new and replaces the vague "RRF + reranker score blending" P1 in v2.1 §4.3.

### 2.2 Out of scope (explicit deferrals)

These were tempting after the 0502 brainstorm but are **deferred to v3.0**:

- ❌ `/course/{id}/classmates` endpoint and any social discovery API
- ❌ "Search result decision dashboard" UI work — Andy Dong's territory
- ❌ Full 19-course Gemini enrichment (Week 7 limits to 3 courses, see §3.2)
- ❌ Dynamic filter UI on search results — frontend concern
- ❌ Two-pass selection planner (AI version + Senior version per Yuang Dai's ask) — needs UGC accumulation first
- ❌ Reddit live scrape (mock-only tests remain authoritative until `.env` PRAW credentials exist)
- ❌ Learnable blending function — sample size (42 queries) too small, deferred to v3.0 with note in `roadmap_v3.md`

---

## 3. Week 7 task list (priority-ordered)

### 3.1 P0: Cloudflare Tunnel deploy + team smoke (KPIs 1, 2, 3)

| Task | File / Action | Owner | ETA |
|---|---|---|---|
| Cloudflare named tunnel up | `docs/cloudflare_tunnel.md` runbook | me | 2-3h |
| Google OAuth client config | Cloud Console + `.env` | me | 30 min |
| `compass.<your-zone>.com/` → localhost:8000 | tunnel route config | me | 15 min |
| Team smoke instructions sent to LYU/Andy/Yuang | Slack/Lark message + 5 example queries | me | 15 min |
| Real query logging verification | `grep request.handled` after first hour of traffic | me | passive |

**Definition of done**: at least one teammate other than me successfully completes an OAuth round-trip and submits a `/search` query via the public URL, recorded in structlog with their `user_sub`.

### 3.2 P0: Real Gemini smoke on 3 courses

This replaces v2.1 §4.3 P0 ("Real Gemini smoke on 1-2 courses") and explicitly caps the scope. **Do not** run `--live` against the full 19-course core set in Week 7.

| Course | Why this one | Budget |
|---|---|---|
| AAI 6600 | Already seeded synthetically; canonical comparison case | ~$0.05 Gemini |
| CS 5800 | High-volume RMP data, tests scraper at scale | ~$0.05 Gemini |
| CS 5200 | Known controversial (per Reddit), tests `controversial_signals` extraction | ~$0.05 Gemini |

Total: under $0.20. Verify `evidence_snippets` schema validator catches malformed LLM output. Verify `difficulty_score` and `workload_hours_per_week` populate. If prompt template needs revision, iterate then expand to remaining 16 courses **only after Week 7 ships**.

```bash
uv run python scripts/enrich_course_via_rmp.py --live --save --course-id neu-aai-6600
uv run python scripts/enrich_course_via_rmp.py --live --save --course-id neu-cs-5800
uv run python scripts/enrich_course_via_rmp.py --live --save --course-id neu-cs-5200
```

### 3.3 P0: FastAPI as canonical surface (team handoff)

The 0502 brainstorm assigned web frontend to Andy Dong. Decision: freeze further Streamlit user-UI work. `app/streamlit_app.py` becomes a **debug-only** harness; `app/eval_dashboard.py` remains my Eval surface.

| Task | File | Why |
|---|---|---|
| Add OpenAPI descriptions to all `/search`, `/course`, `/coop`, `/chat` routes | `api/routes/*.py` | Andy needs Swagger to build UI without me |
| Write `docs/api_contract.md` | new doc | curl examples + response shapes for every endpoint |
| Tag `streamlit_app.py` as internal-only | top-level docstring + README | prevent confusion |
| Confirm `/openapi.json` is reachable via Cloudflare | smoke test | Andy's first stop |

**No backwards-incompat changes to API**. Andy starts building against current contract; we evolve via additive endpoints only.

### 3.4 P1: Adversarial rejection layer

Carry-forward from v2.1 §4.3 P1. Implementation is now decoupled from blending (see §3.5).

```python
# api/routes/search.py — pseudocode, single source of truth
RERANKER_REJECT_THRESHOLD = 0.4  # tunable; ADR if changed

reranked_hits, meta = rerank_search_hits(
    query=request.q,
    hits=hybrid_hits,
    top_k=5,
    blend_alpha=BLEND_ALPHA,        # see §3.5
    reject_threshold=RERANKER_REJECT_THRESHOLD,
)
if meta["rejected"]:
    return SearchResponse(hits=[], rejected=True, reason=meta["reason"])
```

**Rejection uses raw sigmoid max**, not blended score. Blending only affects ordering of accepted results. This separation is non-negotiable — they answer different questions.

ETA: 1h implementation + 30 min eval to confirm adversarial query category goes from 0/4 to ≥ 3/4 (i.e. system correctly returns empty for nonsense input).

### 3.5 P1: Blending experiment + α grid search (KPI 4)

**Decision locked**: Z-score normalization, NOT Min-Max, NOT three-path RRF.

Rationale (full discussion in `docs/adr/0015-z-score-blending.md`, draft after sweep completes):
- Min-Max amplifies the narrow RRF score range (0.0164→0.0125 spread becomes [0,1]) and compresses the bge-reranker double-peak distribution where it matters most (top-of-pool discrimination)
- Three-path RRF flattens reranker's absolute confidence into rank, breaking the rejection threshold layer (§3.4)
- Z-score gives clean α semantics: α=0.5 strictly means "equal weight on both standardized signals"

**Sweep plan**:

```python
# eval/sweep_blend_alpha.py — new script (~50 LoC)
ALPHAS = [0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0]
# α=0.0 → pure reranker (current rerank.json baseline, R@5=0.636 / MRR=0.545)
# α=1.0 → pure RRF (current hybrid_with_alias baseline, R@5=0.601 / MRR=0.603)

for alpha in ALPHAS:
    results = run_eval(mode="hybrid+rerank+blend", blend_alpha=alpha)
    # log: R@5, MRR, per-category recall, p50/p95 latency
```

**Acceptance**: write ADR-0015 declaring final α value. Target: **R@5 ≥ 0.636 AND MRR ≥ 0.603** (Pareto-improve both baselines). If no α achieves this, document the tradeoff and pick α to maximize MRR subject to R@5 ≥ 0.620.

ETA: 2h coding + 30 min sweep run + 1h ADR write-up.

### 3.6 P2: Schema preparation for social layer (DDL only)

The 0502 brainstorm reaffirmed "find course buddies" as core. We prepare the data layer now so Week 8+ frontend work is unblocked, **without writing endpoints or repositories**.

```sql
-- db/init.sql — additive, idempotent
CREATE TABLE IF NOT EXISTS user_courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    course_id TEXT NOT NULL,
    term TEXT NOT NULL,                  -- e.g. "fall_2026"
    status TEXT NOT NULL DEFAULT 'planning',  -- planning | enrolled | completed
    visibility TEXT NOT NULL DEFAULT 'private', -- private | classmates | public
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (course_id) REFERENCES courses(course_id),
    UNIQUE(user_id, course_id, term)
);

CREATE INDEX IF NOT EXISTS idx_user_courses_course ON user_courses(course_id, term);
CREATE INDEX IF NOT EXISTS idx_user_courses_user ON user_courses(user_id);
```

**Explicitly NOT in v2.2**:
- No `UserCoursesRepository` class
- No `/course/{id}/classmates` endpoint
- No UI affordance ("add to my plan" button)

These wait for v3.0 when (a) real users exist and (b) k-anonymity rules for classmate visibility have been designed (likely k=3 for course matchmaking, looser than k=2 for Co-op).

ETA: 30 min DDL + migration test.

### 3.7 P2: Co-op Seed Data ≥ 30 records

Unchanged from v2.1 §4.1. Distribution per PLAN §6.5: 12 quant_fintech, 8 big_tech, 5 biotech, 5 startup. Curate offline, COPY-in via SQL, verify k=2 holds. Only relax to UGC after Seed Data is in.

---

## 4. Week 8 (provisional, refined after Week 7 traffic)

Largely unchanged from v2.1 §4.2. Updates:

| Task | File | Notes |
|---|---|---|
| `eval/test_set.json` → 100 queries | bound by Week 7 query log | Aim 30 simple / 30 medium / 20 complex / 10 boundary / 10 adversarial |
| **Re-run α grid search on test_set v0.3** | `eval/sweep_blend_alpha.py` | Locked Week 7 α may shift; document delta in ADR-0015 supplement |
| Ragas eval with real Gemini judge | `eval/ragas_runner.py` | Faithfulness, Context Precision, Answer Relevance |
| Latency tail tuning | `scripts/probe_latency.py` | If real users need < 100ms p50, batch queries / drop reranker on hot path |
| **Portfolio packaging**: README + system diagram + numbers | `README.md` overhaul | Quant interview ammunition |
| `roadmap_v3.md` | new doc | Social layer, learnable blending, mobile-first considerations |

The Week 7 α decision is provisional. Week 8 re-sweep on the larger test set is mandatory — locking parameters on n=42 is statistically thin.

---

## 5. Open TODOs by priority (carry-forwards + new)

| Priority | TODO | Where | Source |
|---|---|---|---|
| P0 | Cloudflare deploy + team smoke | runbook | v2.1 |
| P0 | 3-course Gemini live smoke (capped) | `enrich_course_via_rmp.py` | v2.2 §3.2 |
| P0 | OpenAPI descriptions + api_contract.md | `api/routes/*.py` + new doc | v2.2 §3.3 |
| P1 | Adversarial rejection layer | `api/routes/search.py` | v2.1 |
| P1 | Z-score blending + α sweep | `rag/reranker.py` + `eval/sweep_blend_alpha.py` | v2.2 §3.5 |
| P1 | ADR-0015 (blending decision) | `docs/adr/0015-*.md` | v2.2 §3.5 |
| P2 | `user_courses` DDL only | `db/init.sql` | v2.2 §3.6 |
| P2 | 30 Co-op Seed records | `data/coop_seed/` | v2.1 |
| P2 | test_set expansion to 100 | `eval/test_set.json` | v2.1, gated on Week 7 traffic |
| P2 | 19 more Ground Truth annotations | `data/ground_truth/` | v2.1, lower urgency |
| P3 | Reddit live smoke | needs `.env` PRAW creds | v2.1 |
| P3 | RMP enrichment for remaining 16 core courses | post-Week-7 | v2.2 §3.2 |
| Deferred | `/course/{id}/classmates` endpoint | v3.0 | §2.2 |
| Deferred | Learnable blending | v3.0 | §3.5 |
| Deferred | Two-pass selection planner | v3.0 | §2.2 |

---

## 6. Reference

### 6.1 First 30 minutes for a returning agent

```bash
# Verify state
wsl -d Ubuntu-24.04
cd /mnt/h/neu-compass
git log --oneline | head -3
uv run pytest tests/ -q                           # 601+ passed
uv run python scripts/probe_latency.py --warmup 1 --iterations 1  # p50 ~40 ms

# Read in order
cat docs/PLAN_v2.2.md         # this file (sprint plan)
cat docs/PLAN_v2.1.md         # Week 6 checkpoint (status)
cat docs/adr/0013*.md docs/adr/0014*.md  # invariants
ls docs/adr/0015*.md 2>/dev/null && cat docs/adr/0015*.md  # if Week 7 closed it

# Start the live stack
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 &
# (Streamlit app is debug-only now; use eval_dashboard for evals)
uv run streamlit run app/eval_dashboard.py --server.port 8502 &
```

### 6.2 Where to look for the Week 7 deliverables

| Artifact | Path |
|---|---|
| Cloudflare runbook | `docs/cloudflare_tunnel.md` |
| API contract doc (new) | `docs/api_contract.md` |
| Blending sweep script (new) | `eval/sweep_blend_alpha.py` |
| Blending sweep results (new) | `eval/blend_sweep_results.json` |
| Blending decision ADR (new) | `docs/adr/0015-z-score-blending.md` |
| Real Gemini smoke output | `data/gemini_smoke_logs/*.json` |
| user_courses DDL | `db/init.sql` (additive) |

### 6.3 Conventions worth preserving (unchanged from v2.1 §5.4)

- Pydantic models: `model_config = ConfigDict(extra="forbid")`
- Tests: build on `tests/conftest.py:empty_db` fixture
- API tests: `api_client` fixture + override `get_db_conn`
- Repositories take `connection` in `__init__`; caller manages lifecycle
- LLM-callable functions accept injectable `model` / `expand_fn` / `llm_fn` / `stream_fn`
- ADRs: follow `docs/adr/0000-template.md`
- Commits: `feat(scope): ...` / `feat(weekN): ...` / `docs: ...` / `test: ...`

---

## 7. Versioning

- **PLAN v1.0**: original 8-week plan
- **PLAN v1.2 (FINAL)**: PDF revision shared at session start
- **PLAN v1.3**: Week 0 critique-driven revision
- **PLAN v2.0**: Week 5 checkpoint
- **PLAN v2.1**: Week 6 checkpoint (ship state)
- **PLAN v2.2**: this file. Week 7 sprint plan after 0502 team brainstorm.
- **Next**: v3.0 after Week 7 soft-launch produces real query-log signal AND test_set hits 100.

---

## 8. Acknowledged limits + intentional tradeoffs (delta from v2.1 §7)

New in v2.2:
- **α decision in Week 7 is provisional**, n=42 test set is thin. Re-sweep on test_set v0.3 in Week 8 is mandatory; ADR-0015 will get a supplement.
- **Streamlit user-UI is frozen**, not deleted. `app/streamlit_app.py` remains as a debug harness for me; product UI is Andy's `compass-frontend` repo (not yet created).
- **Social schema lands without API surface**. `user_courses` table DDL exists in v2.2; queryability waits for v3.0. This is intentional — no point shipping endpoints with no users behind them.
- **3-course Gemini smoke is the budget cap for Week 7**, not 19. Validate prompt + schema first; scale only after Week 7 ships.

Carried from v2.1 §7:
- No production deployment until Cloudflare Tunnel is live
- No real OAuth round-trip tested until tunnel + real client_id exist
- `eval/test_set.json` at 42 queries until traffic enables expansion
- Adversarial query rejection: PLAN-level decision exists; Week 7 implements

---

**End of v2.2**. Open the next session with this doc + v2.1 as starter context.

---

## 9. Closeout (post-sprint, 2026-05-04)

Week 7 sprint **engineering 全交付**;KPI 2+3 是流量门槛,等团队 traffic。

| KPI | 状态 | 落地证据 |
|---|---|---|
| 1. 公网 URL serving FastAPI | ✅ | `https://api.neu-compass.me/{health,ready,search,...}` 200 / 6469 indexed |
| 2. ≥ 200 真 query | 🟡 0/200 | 等 LYU/Andy/Yuang/+1 contributors 跑 traffic |
| 3. ≥ 5 contributors OAuth | 🟡 1/5 | 自己 northeastern.edu OAuth round-trip 成功(`auth.callback.success` log)|
| 4. ADR-0015 α 决策 | ✅ | α=0.4 锁定 + ADR-0016 阈值 0.05 校准 |

**§3 task list 全部 done(含 P0/P1/P2)**:

| § | 任务 | 交付 |
|---|---|---|
| §3.1 | Cloudflare Tunnel 部署 | api.* + compass.* 双子域,Windows cloudflared,runbook §11 addendum |
| §3.2 | Real Gemini smoke 3 课 | AAI 6600 ✓ / CS 5800 ✓ rich (20 evidence + diff/workload) / CS 5200 validator 拦下(prompt 待 v2.3 修);Gemini SDK 加 schema cleaner + 16384 token budget |
| §3.3 | OpenAPI + api_contract.md | 8 routes 全 summary+description+responses;`docs/api_contract.md` 150+ 行 curl 契约;Streamlit 标 internal-only |
| §3.4 | Adversarial rejection | `rerank_blend_with_rejection` 单 reranker pass + API wired;ADR-0016 把 PLAN spec 0.4 数据校准下调到 0.05(4/4 adv 拒绝 + 真 R@5 -0.066 vs no-rejection baseline)|
| §3.5 | Z-score blending + α sweep | `zscore_blend` + α 网格 9 个值 + ADR-0015 锁定 0.4(soft fallback,无 Pareto-improvement;n=42 thin)|
| §3.6 | user_courses DDL only | schema 1.1 + `migrate_db_to_v1_1.py` + 7 deterministic 测试(idempotent + cascade + UNIQUE triple + trigger)|
| §3.7 | Co-op Seed 30 records | `template.example.json` + `ingest_coop_seed.py` + curated-v1 adapter(salary 10-wide bucket);**12/8/5/5 完美匹配 PLAN 目标分布**;全 visibility level 2 (premium) 因均含 salary |

**部署期间踩坑记录**(都已修 + 文档化,留给 v2.3+ 后人):

1. **OAuth 客户端创建**: Google Auth Platform 新 UI 把 OAuth consent screen 改名 "OAuth 同意屏幕 / 受众群体",branding/scopes/test users 拆三页。Test users 必须含开发者邮箱(否则 400)。
2. **`hd=husky.neu.edu` 锁死后缀**: `app/auth.py` 原本写死单域 hint,northeastern.edu 邮箱无法登录;移除该参数,server-side `is_email_allowed` 双白名单仍生效。
3. **redirect URI 路径前缀失效**: 原设计 `compass.<zone>.com/api/*` 把 path-prefix 转给 FastAPI — 但 cloudflared 不支持 strip prefix,uvicorn 收到 `/api/health` 报 404。改用**双子域** `api.* / compass.*`,FastAPI 不需任何 prefix 改动。
4. **Streamlit 在子路径下相对路径加载 JS 失败白屏**: `redirect_uri=/oauth/callback` 触发 Streamlit HTML 引用 `./static/...` → 浏览器解析为 `/oauth/static/...` → 404 → 白屏。改 redirect URI 到根路径 `/`,handle_oauth_callback 仍读 `?code=`(与路径无关)。
5. **uvicorn 设置缓存**: 改 `.env` 后只重启 streamlit,uvicorn 还用旧 redirect_uri 换 token 给 Google → invalid_grant。两边都得重启才能保 .env 一致。
6. **DB schema drift**: 运行时 DB 是 2026-04-30 旧 init.sql 建的,缺 `coop_experiences.industry/coop_term/...` 列。`migrate_db_to_v1_1.py` ALTER TABLE 补齐,idempotent 安全重跑。
7. **Gemini SDK schema 拒绝**: Pydantic 生成的 JSON Schema 有 `minLength` / `pattern` / `anyOf` 字段,该版 google-generativeai 的 Schema proto 不收。`pydantic_to_gemini_schema()` 解 $ref + 剥不兼容字段 + 平 anyOf 到 nullable + prune dangling required + context-aware (`title` 既是 metadata 也可能是 properties 名)。
8. **测试 flake**: 两个 trigger 测试用 `time.sleep(1.1)` 等 SQLite CURRENT_TIMESTAMP 跨秒,在重负载下偶发失败。改用 deterministic pattern (seed `'2020-01-01'` 旧 timestamp + assert ≠) — 无 sleep,无 flake。

后续(不阻塞 ship):
- Week 8 § revision: 见 [PLAN_v2.3.md](PLAN_v2.3.md)
- 安全:rotate OAuth client secret(截图在 chat 暴露过)
- SDK 迁移:`google.generativeai` 已 EOL,改 `google.genai`
- Streamlit chat_input 视觉 / WS:观察是否需要 `--server.enableCORS=false` 或 cloudflared WS 升级配置

测试套件: 624 → 631 passed(+7 user_courses schema test + 6 rerank_blend_with_rejection + 3 API rejection 路径 - 重叠);schema_versions: 1.0 + 1.1。
