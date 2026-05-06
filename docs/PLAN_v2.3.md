# NEU-Compass · PLAN v2.3 (Week 8 sprint plan, post Week 7 ship)

> **Updated**: 2026-05-04
> **Previous**: [docs/PLAN_v2.2.md](PLAN_v2.2.md) (Week 7 sprint, shipped — 见 §9 closeout)
> **Purpose**: Week 8 forward sprint — 公网软启动落地后的真用户 traffic 消化 +
> Week 7 留下来的 follow-ups + 走向 Week-8 portfolio packaging。
> **Read order if you're a fresh agent**: §0 → §1 → §2 → §3 → §6.

---

## 0. What changed from v2.2

v2.2 是 Week 7 sprint plan,**全 §3 task list 已落地**(详见 v2.2 §9 closeout)。
v2.3 是 Week 8 forward plan,定位转移:

1. **从"造系统"到"消化流量"**:核心 KPI 从工程交付变成"团队 ≥200 query / ≥5 contributors"
   的真 traffic 落库。这部分属于产品+协作问题,不是代码问题。
2. **从"42-query 内部 eval"到"100-query 真 query log eval"**:test_set v0.3 是 Week 8 第一
   block。v0.3 ready 后强制重 sweep ADR-0015 + 0016。
3. **Week 7 实际部署暴露了 4 类 follow-up 工程问题**(见 §3.4-§3.7)需要补:CS 5200
   prompt validator 拒绝、google.generativeai SDK EOL、OAuth secret 已暴露需 rotate、
   Streamlit chat_input WS 行为待复测。
4. **Portfolio packaging** 从 v2.2 §4 carry-over,Week 8 末交付:README overhaul +
   system diagram + canonical numbers,作为 quant interview ammunition。

---

## 1. v2.2 invariants still in force

这些 v2.2 §1 + ADRs 在 v2.3 **不变**(v2.3 §3 任何条目跟它们冲突时,v2.2 §1 先生效):

- **ADR-0013**: SQLite is the source of truth; FAISS is derived
- **ADR-0014**: SQLITE_PATH / FAISS_INDEX_PATH on WSL home (ext4, 77x penalty if H: drive)
- **ADR-0015**: Z-score blending α=0.4 (provisional, **强制 v0.3 重 sweep**)
- **ADR-0016**: Reranker reject threshold T=0.05 (provisional, **强制 v0.3 重 ROC**)
- **v_course_lookup filters `review_status='approved'`**: unreviewed LLM aliases never affect retrieval
- **Schema soft-fields require evidence_snippets**: Pydantic validator enforces
- **k=2 anonymity for Co-op**: enforced server-side at `POST /coop`
- **OAuth domain whitelist via `is_email_allowed`**: split-on-`@` exact match
- **F1 compliance red lines**: no payments, no commercialization, no investor money
- **Test discipline**: `uv run pytest tests/ -q` 必须 **631+ passed** (Week 7 ship 数);别 merge red

Cold start ~70s, bimodal latency ~3ms alias / ~47ms hybrid+rerank+blend, schema 1.1 active.
全部沿用 v2.2 §1 + Cold start 注解。

---

## 2. Week 8 sprint goals

### 2.1 KPIs (acceptance criteria)

Week 8 ships if **all four** met by EOW:

| # | KPI | How to measure | Source |
|---|---|---|---|
| 1 | test_set v0.3 ≥ 100 queries 落地 | `wc -l eval/test_set.json queries[]` | new artifact |
| 2 | ADR-0015 α + ADR-0016 T 在 v0.3 上重 sweep,出 supplement | `eval/blend_sweep_results_v03.json` + ADR-0015 footer + ADR-0016 footer | new artifacts |
| 3 | CS 5200 prompt 修订后跑通 evidence_snippets validator | `enrich_course_via_rmp.py --course-id neu-cs-5200 --live --save` 不抛 ValidationError | passing run |
| 4 | Portfolio packaging: README + system diagram + numbers 全更新到 quant-interview-ready | git diff 校验 + 第三方人读 README 5 分钟懂场景 | self-graded |

KPI 1+2 是 Week 7 §4 的 carry-over,v2.3 把它们升到 P0。
KPI 3 是 Week 7 §3.2 留尾(CS 5200 case),修了 prompt 才能扩到剩 16 课。
KPI 4 是 v2.2 §4 carry-over,quant-interview 用。

### 2.2 Carry-over from Week 7 (non-blocking on KPI 1-4)

| 项 | 状态 |
|---|---|
| Week 7 KPI 2 (≥ 200 真 query) | 等团队 traffic;**非 v2.3 阻塞** —— v2.3 不为这个等 |
| Week 7 KPI 3 (≥ 5 contributors OAuth) | 同上 |
| Co-op seed 30 条已入库 | Week 7 §3.7 done,无需重做 |
| 6469 课 indexed (含 AAI 6600 + CS 5800 enrichment) | Week 7 follow-up rebuild_faiss done |

### 2.3 Out of scope (explicit deferrals to v3.0+)

- ❌ `/course/{id}/classmates` endpoint(Week 7 已 deferred,v2.3 仍然不做)
- ❌ `UserCoursesRepository` class — DDL 已落,API 等真用户
- ❌ Two-pass selection planner(Yuang Dai 提的 AI/Senior 双版本规划)
- ❌ Reddit live scrape(`.env` PRAW 凭证未补;mock-only 测试仍权威)
- ❌ Learnable blending function(n 仍小,等真 query log 累到 ≥ 500)
- ❌ Cloudflare Access SSO 网关(双层防护过度,Week 8 软启动不做)
- ❌ 移动端 / PWA — 后端不动,前端是 Andy 的 `compass-frontend` 仓库

---

## 3. Week 8 task list (priority-ordered)

### 3.1 P0: test_set v0.3 expansion to ≥ 100 queries (KPI 1)

**前置**: Week 7 ship 后团队跑了一些 query,query log (`api.log`) 有真实样本。

```bash
# 拉真 query log
grep '"event": "search\\.' /var/log/uvicorn.log | jq -r '.query' | sort -u > /tmp/real_queries.txt
# 或 structlog json:
jq -r 'select(.event | startswith("search.")) | .query' < api.log | sort -u
```

按 PLAN v1.3 §4.1 比例补到 100:

| Category | 当前 v0.2 | 目标 v0.3 |
|---|---:|---:|
| Simple (code lookup) | 12 | **30** |
| Medium (NL with single hit) | 8 | **30** |
| Complex (multi-course / ambiguous) | 10 | **20** |
| Boundary (alias / slang / no-space code) | 6 | **10** |
| Adversarial (no good match) | 4 | **10** |

写到 `eval/test_set.json` v0.3,bump version 字段。新增 query 必须有人工 ground truth
(`expected_course_ids`)。

**Acceptance**: `eval/test_set.json` version="0.3" + queries 长度 ≥ 100 + 每条带
`expected_course_ids` (空列表 = adversarial)。

ETA: 真 query log 来了之后 ~2-3h(挑选 + 标注)。

### 3.2 P0: Re-sweep ADR-0015 + ADR-0016 on v0.3 (KPI 2)

**强制**(v2.2 §3.5 + §3.6 都标 provisional / mandatory re-sweep)。

```bash
# α grid 重扫,出新 sweep results
uv run python eval/sweep_blend_alpha.py \
    --test-set eval/test_set.json \
    --out-json eval/blend_sweep_results_v03.json

# threshold ROC 重扫
uv run python eval/sweep_reject_threshold.py \
    --test-set eval/test_set.json \
    --out-json eval/reject_threshold_sweep_v03.json
```

**Acceptance**:
- 新 ADR-0015 footer "v0.3 supplement" 注明 α 是否漂移 + 数字
- 新 ADR-0016 footer "v0.3 supplement" 同上 T
- 如果 α 漂 > 0.1 或 T 漂 > 0.02,**更新 `api/routes/search.py` 模块常量** + 重新部署
- 如果 v0.3 上有 **Pareto-improvement**(R@5 ≥ pure-rerank baseline AND MRR ≥ pure-RRF
  baseline 的同时存在的 α),原 soft-fallback 决策升格为 hard;ADR-0015 supplement
  必须显式 surface 这一点

ETA: 1.5h 含 sweep run + ADR write-up。

### 3.3 P0: CS 5200 prompt revision (KPI 3)

Week 7 §3.2 实测发现:Gemini 给 CS 5200 返回 `skill_tags` 但**未配** `evidence_snippets`
→ Pydantic validator 拒绝。这是 prompt engineering 问题,扩到剩 16 课前必修。

修改路径: `llm/prompts/extract_v1.py`

加强约束(伪代码,最终用清晰的英文 instruction + few-shot):

```python
EXTRACT_PROMPT_V1_1 = """
... existing content ...

CRITICAL — soft fields & evidence:
For EVERY non-empty value you put in:
  - difficulty_score
  - workload_hours_per_week
  - skill_tags
  - career_relevance
  - controversial_signals

You MUST include AT LEAST ONE entry in `evidence_snippets` whose `field`
attribute matches the soft field name AND whose `quote` is a verbatim
substring (≥ 10 chars) from the supplied <source> blocks.

If you cannot find supporting evidence, leave the soft field empty (null
for scalars, [] for lists). Do NOT invent.

Bad:
  {"skill_tags": ["python", "ml"], "evidence_snippets": []}    # rejected
Good:
  {"skill_tags": ["python"], "evidence_snippets": [
    {"field": "skill_tags", "quote": "Heavy use of Python for...", "source": "rmp"}
  ]}
"""
```

Also bump prompt版本 (extract_v1 → extract_v1.1, append-only history).

**Acceptance**:
- `tests/test_review_enrichment.py` 加一个测试:mock Gemini 返回非空 soft + 空 evidence →
  抛 ValidationError(已经 test 过 Pydantic validator,这条是 *integration* 层确认 prompt
  改后 Gemini 不再倒灌 bad output)
- `uv run python scripts/enrich_course_via_rmp.py --course-id neu-cs-5200 --professor "Durant Kathleen" --professor "Cobbe Richard" --live --save` 不抛 OAuthError/GeminiError/ValidationError;CS 5200 落库 schema_version=1.1 + evidence_snippets 非空

ETA: 1h prompt iter + 30 min smoke retest + 1 次 Gemini ~$0.05。

### 3.4 P1: Scale Gemini enrichment to remaining 16 courses

**前置**: §3.3 prompt 修复跑通。

按 PLAN_v1.3 §6 / Week 7 §3.2 的"剩 16 门核心课"列表。每课 ~$0.05,总 ~$0.80。

```bash
for cid in neu-cs-5200 neu-cs-6140 neu-ds-5230 neu-math-7233 neu-aly-6010 \
           neu-info-6105 neu-cs-6200 neu-aly-6140 neu-eece-5645 neu-cs-6240 \
           neu-ds-5500 neu-aly-6080 neu-aai-5015 neu-ds-5110 neu-cs-2000 \
           neu-info-6150; do
  uv run python scripts/enrich_course_via_rmp.py \
      --course-id "$cid" --professor "<填该课主授>" --live --save
done

# 全 enrich 完后重 embed
uv run python scripts/rebuild_faiss.py --all
uv run python scripts/mark_pending_indexed.py
```

**Acceptance**:
- 16 课 status='indexed' 且 `generated_json.evidence_snippets` 长度 ≥ 1
- `eval/run_eval.py --rerank --with-rejection` R@5 应该升 — 真实 enriched 数据比纯
  catalog raw_text 信息密度高。Track delta in PR description。

ETA: 1.5h 准备 prof 名表 + ~30 min 跑 + ~$0.80 budget。

### 3.5 P1: SDK migration `google.generativeai` → `google.genai`

Week 7 实测看到 deprecation warning:
`All support for the google.generativeai package has ended.`

迁移工作:
- `llm/gemini_client.py`: 把 `import google.generativeai as genai` 换成 `from google import genai`
- API 不完全 1:1,新 SDK 用 `genai.Client(api_key=...)` 而不是 `genai.configure()`
- `response_schema` 接口可能改了 — 重测 `pydantic_to_gemini_schema()` 是否还需要(新 SDK
  可能原生支持完整 JSON Schema → 我们的 strip 逻辑可以 simplify 或删)
- `tests/test_gemini_client.py` 11 个测试得重检
- `pyproject.toml` 改依赖(`google-generativeai` → `google-genai`)
- `uv lock` + `uv sync`

**Acceptance**: 所有现有 Gemini 测试仍 pass;`enrich_course_via_rmp.py --live` 一次性
smoke 不报 deprecation warning。

ETA: 2-3h(SDK 接口对齐 + 测试)。

### 3.6 P1: Ragas eval with real Gemini judge

PLAN v1.3 / v2.0 一直挂着。Week 7 真 enrich 数据落库后值得跑。

```bash
uv run python eval/ragas_runner.py --use-real-gemini --out eval/ragas_v03.json
```

指标:
- Faithfulness(答案是否有 source 支撑)
- Context Precision(top-k 召回里几个真相关)
- Answer Relevance(答案与问题语义相关性)

预算: 100 query × ~$0.01 judge call ≈ $1。

**Acceptance**: `eval/ragas_v03.json` 输出 + 在 v2.3 self-grade table 里写实测三项。

ETA: 30 min code + 30 min 跑。

### 3.7 P1: Portfolio packaging (KPI 4)

Week 8 末必交付,quant-interview 用。

| 子项 | 文件 |
|---|---|
| README overhaul (number-first hero block) | `README.md` (v2.3 第一轮已加 Week 7 ship 数,Week 8 末再加 v0.3 + Ragas 数字)|
| System diagram (PNG/SVG,不只是 ASCII) | `docs/system_architecture.png` (mermaid 转 PNG OK)|
| Canonical metrics table | `docs/portfolio_metrics.md` (latency / R@5 / MRR / cost / scale 一页 cheatsheet)|
| Postmortem 一页 | `docs/postmortem_week7.md` (Week 7 ship 8 个踩坑,源自 v2.2 §9.2)|
| `roadmap_v3.md` | `docs/roadmap_v3.md` (社交层 / classmates / learnable blending / 移动端)|

**Acceptance**: 三方人(LYU / Andy / 一个新 reviewer)读 README 5 分钟能讲清场景 +
3 个差异化数字。

ETA: 4h 含 diagram + 写作。

### 3.8 P2: rotate OAuth client secret

Week 7 实测:secret 截图在 chat 里贴过,**视为已暴露**(虽然概率低)。

Console → Credentials → 你的 OAuth client → "Reset secret" → 拿新 secret →
`.env` `GOOGLE_OAUTH_CLIENT_SECRET=...` → 重启 uvicorn。

**Acceptance**: rotate 完后用旧 secret 调 `/auth/callback` 应该 401;新 secret 应该
登录通。

ETA: 5 min。

### 3.9 P2: Streamlit chat_input WS / 视觉问题复测

Week 7 实测有报告:登录后 chat_input 看起来"灰",不确定是 Streamlit 视觉默认还是
WebSocket 没建起来(cloudflared 偶尔吃 streamlit 的 WS 升级)。

排查:
1. F12 → Network → 筛 WS → 看 `_stcore/stream` Status 是否 101
2. 如果 WS 失败,看 cloudflared config 是否需要显式 `noTLSVerify: false` /
   WS upgrade 设置 (current `originRequest` 块已有 `tcpKeepAlive`)
3. 如果 Streamlit 1.X 版本本来就 chat_input 灰,记一个 known limitation

**Acceptance**: chat_input 能输入文字 + 提交后 `/chat` 命中 → uvicorn log 见 NDJSON
stream + Streamlit `st.write_stream` 渲染 token。

ETA: 30 min - 2h(取决于是否 WS 真坏)。

### 3.10 P2: 100-query latency p99 监控

如果 KPI 2 (Week 7) 真攒到 200 query,跑一遍:
```bash
uv run python scripts/probe_latency.py --warmup 5 --iterations 200
```

如果 p99 > 100ms,考虑:
- Drop reranker 在 hot path,只做 alias + hybrid;后台异步 enrich
- 或 batch reranker 调用 (reranker 已经 batch,但 batch_size = pool_size = 20,可调)
- 或 GPU FP16 / INT8

**Acceptance**: 当前 budget 是 < 300ms。Week 7 实测 p50 ~47ms / p95 ~58ms 远低于。
如果 p99 飙升才动。

ETA: 30 min monitor + 0-2h tuning。

---

## 4. Week 9+ (provisional, 不在 Week 8 sprint scope)

照 v2.2 §4 carry-over + 新观察:

| Task | Notes |
|---|---|
| `roadmap_v3.md` 起草 | §3.7 子项 |
| 真 user_courses endpoint(POST /user_courses + GET /course/{id}/classmates)| v3.0 — 等用户量 |
| Learnable blending(per-query α 或 lightGBM)| v3.0 — 等 ≥ 500 真 query 训练 |
| Multi-vector ColBERT-style 第三检索 leg | v3.0,跟 learnable blending 一起做 |
| Reddit live PRAW + 脱敏管线 | 等 PRAW 凭证 |
| Mobile-first / PWA(Andy 仓) | 不是后端 scope |

---

## 5. Open TODOs (carry from v2.2 + new)

| Priority | TODO | Where | Source |
|---|---|---|---|
| P0 | test_set v0.3 ≥ 100 query | `eval/test_set.json` | v2.3 §3.1 |
| P0 | ADR-0015 + 0016 v0.3 supplement | `docs/adr/0015*.md` + `0016*.md` | v2.3 §3.2 |
| P0 | CS 5200 prompt revision | `llm/prompts/extract_v1.py` (→ v1.1) | v2.3 §3.3 |
| P0 | Portfolio packaging | README + diagram + metrics | v2.3 §3.7 |
| P1 | 16 课 Gemini enrich + rebuild | scripts | v2.3 §3.4 |
| P1 | google.genai SDK migrate | `llm/gemini_client.py` | v2.3 §3.5 |
| P1 | Ragas eval real Gemini judge | `eval/ragas_runner.py` | v2.3 §3.6 |
| P2 | Rotate OAuth secret | Console + .env | v2.3 §3.8 |
| P2 | Streamlit chat_input WS 复测 | F12 + cloudflared cfg | v2.3 §3.9 |
| P2 | p99 latency monitor + tune | `probe_latency.py` | v2.3 §3.10 |
| Deferred | `/course/{id}/classmates` | v3.0 | v2.2 §2.2 |
| Deferred | Learnable blending | v3.0 | v2.2 §2.2 |
| Deferred | Two-pass selection planner | v3.0 | v2.2 §2.2 |

---

## 6. Reference

### 6.1 First 30 minutes for a returning agent

```bash
# 验证状态
wsl -d Ubuntu-24.04
cd /mnt/h/neu-compass
git log --oneline | head -3                       # 最近 commit
uv run pytest tests/ -q                            # 631 passed
uv run python scripts/probe_latency.py             # p50 ~40ms hybrid-only

# 读 v2.3 (这文件) → v2.2 §9 closeout(踩坑全在那)→ ADRs 0013-0016
cat docs/PLAN_v2.3.md
cat docs/PLAN_v2.2.md
ls docs/adr/0015*.md docs/adr/0016*.md

# 起 live stack(本地或公网)
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 &
uv run streamlit run app/streamlit_app.py --server.port 8501 --server.address 0.0.0.0 &
# Windows 边: cloudflared tunnel run neu-compass (公网部署后)
```

### 6.2 Week 8 deliverable 一览

| Artifact | Path |
|---|---|
| test_set v0.3 | `eval/test_set.json` (version="0.3") |
| α grid v0.3 results | `eval/blend_sweep_results_v03.json` |
| Threshold ROC v0.3 results | `eval/reject_threshold_sweep_v03.json` |
| ADR-0015 v0.3 supplement | `docs/adr/0015-z-score-blending.md` (footer)|
| ADR-0016 v0.3 supplement | `docs/adr/0016-reranker-reject-threshold.md` (footer) |
| Prompt v1.1 | `llm/prompts/extract_v1.py` (renamed or in-place bump) |
| Ragas v0.3 results | `eval/ragas_v03.json` |
| System diagram | `docs/system_architecture.png` |
| Portfolio metrics cheatsheet | `docs/portfolio_metrics.md` |
| Postmortem | `docs/postmortem_week7.md` |
| `roadmap_v3.md` | `docs/roadmap_v3.md` |

### 6.3 Conventions worth preserving (unchanged from v2.2 §6.3)

- Pydantic models: `model_config = ConfigDict(extra="forbid")`
- Tests: build on `tests/conftest.py:empty_db` fixture + `FixtureEmbedder` + `FixtureReranker`
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
- **PLAN v2.2**: Week 7 sprint plan + closeout
- **PLAN v2.3**: this file. Week 8 forward plan.
- **Next**: v3.0 起社交层 + learnable blending(等 ≥ 500 真 query log + ≥ 30 用户)。

---

## 8. Acknowledged limits + intentional tradeoffs

- **v0.3 expansion 是 Week 8 第一阻塞项**;在它落地前,§3.2 / 3.6 都没真数据可跑。
- **CS 5200 prompt 修复后才扩 16 课**(v2.2 §3.2 已说明)— 反过来跑会浪费 ~$0.80。
- **google.genai 迁移可能引入新 bug**:旧 SDK 我们已经踩过 8 个 schema 坑,新 SDK
  接口更清爽但可能有它自己的 quirks。Week 8 §3.5 单独排,不跟其他东西并轨。
- **Portfolio packaging 是软产出**,数字真不真比文档花不花更重要。先有 v0.3 + Ragas
  数字,后写 README — 别反过来。
- **Streamlit chat_input 问题**:如果是 Streamlit 自身视觉默认就这样,不在 v2.3 范围
  内深修(切到 Andy 的 React 前端是更彻底的解);只在 §3.9 里 30 min 排查 +
  记 known limitation。

---

**End of v2.3**. Open Week 8 session with this doc + v2.2 §9 closeout 作为 starter
context。优先级:KPI 1 → KPI 2 → KPI 3 → KPI 4(P2 散件穿插不阻塞主线)。

---

## 10. Closeout (post-Week 8 + Week 9 perf, 2026-05-06)

v2.3 sprint 全部 engineering 项目 ship 完毕。Week 9 加做了 perf 优化实测(详见 `docs/perf_week9_results.md`):
- ONNX + CUDA EP backend ship-ready(startup 70s → 6s,p50 43.82 → 40.09 ms)
- torch.compile 在 Blackwell sm_120 + FlagEmbedding 1.4 上 hang(已知 incompatibility,跳过)
- TensorRT EP 在 user cu130 系统上 ABI 不兼容(等 ORT 1.26+ cu13 build)
- 测试套件 661 → 679 passed(+18:13 ONNX backend + 5 compile_mode)

**项目相位转移到 v3.0**:从 "engineering ship" 进入 "operational + signal collection"。继续读 [PLAN_v3.0.md](PLAN_v3.0.md)。
