# NEU-Compass · PLAN v2.3.1 (Week 8 sprint plan, hardened)

> **Updated**: 2026-05-05
> **Previous**: [docs/PLAN_v2.3.md](PLAN_v2_3.md)
> **Purpose**: v2.3 review-driven hardening。同 sprint 范围,但 KPI / 顺序 /
> statistical rigor / quant-readiness 几处补强。
> **Read order if you're a fresh agent**: §0 → §1 → §2 → §3.0 → §3 → §6。

---

## 0. What changed from v2.3

v2.3 是 Week 8 forward sprint plan,基本骨架仍然成立。v2.3.1 是 review-driven
hardening,**不改 sprint 范围,只改优先级 / acceptance criteria / 顺序**:

1. **新 §3.0 (P0): OAuth secret rotate 提前并升级**。v2.3 §3.8 标 P2 排在最后,
   但自承"截图在 chat 里贴过 → 视为已暴露",这是 *known compromise*,不是待办。
   5 min 的事,放在 sprint 第一个 commit 之前做。
2. **新 KPI 5 (P0 traffic-driving)**:v2.3 §0 narrative 说"从造系统到消化流量",
   但 §2.2 把真 traffic 项目全 demote 成 non-blocking → narrative 与 KPI 表自相
   矛盾。v2.3.1 加 KPI 5,把"消化流量"做成 explicit outreach action,不再被动等。
3. **§3.1 加真 query 不够时的三档 fallback decision tree**。原文档前置假设"团队
   跑了一些 query"但 §2.2 又说"不为这个等",EOW 真 query 不足时无决策路径。
4. **§3.4 ↔ §3.5 顺序对调 + smoke gate**:先 SDK 迁移 + 单课 diff 验证 schema 稳定,
   再批 enrich 16 课。原顺序在 SDK 迁移后可能让 16 课重 enrich = $0.80 + 时间浪费。
5. **§3.2 statistical rigor 升级**:paired bootstrap CI 替代 ad-hoc "α 漂 > 0.1"
   阈值。决策规则改为"α* CI lower > 现行 α point estimate"才升 hard。
6. **§3.3 加 regression eval**:prompt v1.1 必须对 3 门 hold-out 已 indexed 课重
   跑,验证 evidence 加严没让 soft fields 主动留空率退化 > 15%。
7. **§3.6 加 judge bias 控制**:Gemini-judge-Gemini = self-preference bias,quant
   interview 必问。要求至少一项: 30 条人工 cohen's κ / cross-judge with
   Claude/GPT / explicit limitation acknowledgment。
8. **§3.7 portfolio framing quant-specific 化**:加 counterfactual table /
   latency budget derivation / failure mode catalog 三件套。
9. **§2.4 新增 budget & quota table**;**§2.5 新增 risk register**。
10. **§1 invariant 加一条**: Week 8 末 `pytest -q` ≥ **660** passed (从 631 floor
    升,反映 §3.3 / §3.4 / §3.6 应配套加测试)。

---

## 1. v2.2 invariants still in force

这些 v2.2 §1 + ADRs 在 v2.3.1 **不变**(v2.3.1 §3 任何条目跟它们冲突时,v2.2 §1
先生效):

- **ADR-0013**: SQLite is the source of truth; FAISS is derived
- **ADR-0014**: SQLITE_PATH / FAISS_INDEX_PATH on WSL home (ext4, 77x penalty if H: drive)
- **ADR-0015**: Z-score blending α=0.4 (provisional, **强制 v0.3 重 sweep + bootstrap CI**)
- **ADR-0016**: Reranker reject threshold T=0.05 (provisional, **强制 v0.3 重 ROC + bootstrap CI**)
- **v_course_lookup filters `review_status='approved'`**: unreviewed LLM aliases never affect retrieval
- **Schema soft-fields require evidence_snippets**: Pydantic validator enforces
- **k=2 anonymity for Co-op**: enforced server-side at `POST /coop`
- **OAuth domain whitelist via `is_email_allowed`**: split-on-`@` exact match
- **F1 compliance red lines**: no payments, no commercialization, no investor money
- **Test discipline (v2.3.1 升级)**: `uv run pytest tests/ -q` 必须 **Week 8 EOW
  ≥ 660 passed**(631 floor 仅 Week 7 ship 数;新 §3.3/3.4/3.6 应带测试自然抬到 660+)

Cold start ~70s, bimodal latency ~3ms alias / ~47ms hybrid+rerank+blend, schema 1.1 active。
全部沿用 v2.2 §1 + Cold start 注解。

---

## 2. Week 8 sprint goals

### 2.1 KPIs (acceptance criteria)

Week 8 ships if **all five** met by EOW:

| # | KPI | How to measure | Source | New in v2.3.1? |
|---|---|---|---|---|
| 1 | test_set v0.3 ≥ 100 queries 落地 | `wc -l eval/test_set.json queries[]` | new artifact | |
| 2 | ADR-0015 α + ADR-0016 T 在 v0.3 上重 sweep,含 paired bootstrap 95% CI | `eval/blend_sweep_results_v03.json` + ADR footers | new artifacts | rigor 升级 |
| 3 | CS 5200 prompt 修订后跑通 evidence_snippets validator + 3 课 hold-out regression 通过 | `enrich_course_via_rmp.py --course-id neu-cs-5200 --live --save` 不抛 ValidationError + `diff_prompt_versions.py` | passing run | regression 加项 |
| 4 | Portfolio packaging quant-ready: README + diagram + canonical metrics + counterfactual table + latency budget derivation + failure mode catalog | git diff + 第三方人读 README 5 分钟懂场景 + 1 quant 朋友审 metrics 30 min | self-graded | framing 升级 |
| 5 | **Traffic-driving (NEW)**: ≥ 30 真 query log + ≥ 3 distinct OAuth contributors by EOW,via explicit outreach action | grep query log + 数 OAuth callback 表 distinct user_id | live data | NEW |

KPI 5 替代了 v2.3 §2.2 的"non-blocking 等待"姿态。具体 outreach action(必须写
进 daily standup):

- DM 至少 5 个 LYU / Andy 圈同学,带链接 + 一行场景描述
- AAI 5015 / CS 6140 课程群 broadcast 一次(group chat 转发)
- README 带 "Try it" 区块 + 3 个 example queries(降低进入门槛)

如果 EOW KPI 5 仍未达,**记入 v3.0 retrospective 并 explicit 标注 "social activation
是非工程问题, 工程交付不为它阻塞"**。但 v2.3.1 不允许"等"作为 KPI 5 的实施路径。

### 2.2 Carry-over from Week 7 (non-blocking on KPI 1-4, 但被 KPI 5 部分接管)

| 项 | 状态 |
|---|---|
| Week 7 KPI 2 (≥ 200 真 query) | KPI 5 是其 30-query MVP 版本;v3.0 才上 200 |
| Week 7 KPI 3 (≥ 5 contributors OAuth) | KPI 5 是其 3-contributor MVP 版本 |
| Co-op seed 30 条已入库 | Week 7 §3.7 done,无需重做 |
| 6469 课 indexed (含 AAI 6600 + CS 5800 enrichment) | Week 7 follow-up rebuild_faiss done |

### 2.3 Out of scope (explicit deferrals to v3.0+)

- ❌ `/course/{id}/classmates` endpoint
- ❌ `UserCoursesRepository` class — DDL 已落,API 等真用户
- ❌ Two-pass selection planner(Yuang Dai 提的 AI/Senior 双版本规划)
- ❌ Reddit live scrape(`.env` PRAW 凭证未补;mock-only 测试仍权威)
- ❌ Learnable blending function(n 仍小,等真 query log 累到 ≥ 500)
- ❌ Cloudflare Access SSO 网关(双层防护过度,Week 8 软启动不做)
- ❌ 移动端 / PWA — 后端不动,前端是 Andy 的 `compass-frontend` 仓库

### 2.4 Budget & quota (NEW in v2.3.1)

| 项 | calls | 单价 | 小计 | RPM 风险 |
|---|---:|---:|---:|---|
| §3.3 CS 5200 prompt iter | ~10 | $0.05 | $0.50 | 低 |
| §3.3 hold-out regression (3 课) | 3 | $0.05 | $0.15 | 低 |
| §3.4 SDK migrate smoke (1 课) | 1 | $0.05 | $0.05 | 低 |
| §3.5 16 课 enrich | 16 | $0.05 | $0.80 | 串行 OK; 并发 >10 可能撞 free tier 15 RPM |
| §3.6 Ragas judge (Gemini) | 100 | $0.01 | $1.00 | 100 sequential calls < 60s, free tier 安全 |
| §3.6 Cross-judge (Claude/GPT, 选做) | 100 | $0.015 | $1.50 | 与 Gemini 解耦 |
| **Total (Gemini-only path)** | | | **~$2.50** | |
| **Total (含 cross-judge)** | | | **~$4.00** | |

F1 个人预算约束: < $10 Week 8 上限,留 $6+ buffer 给 retry / debug / 1.5x 预估膨胀。

### 2.5 Risk register (NEW in v2.3.1)

| Risk | Likelihood | Impact | Mitigation | Owner check |
|---|---|---|---|---|
| 真 query 数 < 30 EOW | M | KPI 1+2+5 同时 miss | §3.1 fallback 三档决策 | 周三 mid-week |
| google.genai SDK schema 输出与旧 SDK 不一致 | M | 16 课需重 enrich, +$0.80 | §3.4 单课 diff smoke gate | §3.4 step 2 |
| Prompt v1.1 evidence 约束太严, soft fields 主动留空率上升 | M-H | 信息密度下降, R@5 退化 | §3.3 hold-out 3 课 regression eval, gate ≤ 15% drop | §3.3 acceptance |
| Gemini-judge-Gemini self-preference bias | H | KPI 4 portfolio 数字面试不可信 | §3.6 cross-judge OR human cohen's κ | §3.6 acceptance |
| OAuth secret 已暴露被滥用 | L-M | Account takeover, NEU 域钓鱼 | §3.0 立刻 rotate (P0, sprint 第一动作) | sprint 启动前 |
| Cold start 70s 在 live demo 时 | H | quant interview demo 体验差 | §3.10 加 demo warm-up 流程 + cron pre-warm (cost 0) | demo 前 |
| Streamlit chat_input WS 仍坏 | L | 软启动用户输入失败 | §3.8 30 min 排查; fallback 切 Andy React 前端 | §3.8 |
| paired bootstrap 显示 α 改动不显著 | M | ADR-0015 不能升 hard, 仍 provisional | 接受现状, 标 v3.0 待 ≥ 500 query 重判 | §3.2 acceptance |

---

## 3. Week 8 task list (priority-ordered)

### 3.0 P0 (sprint 第一动作): Rotate OAuth client secret (升级自 v2.3 §3.8)

**理由**: secret 已 known-compromised(自承截图在 chat 贴过)。在任何 sprint 工作
之前先做完。

```
Console → Credentials → 你的 OAuth client → "Reset secret"
→ 拿新 secret
→ .env 更新 GOOGLE_OAUTH_CLIENT_SECRET=...
→ 重启 uvicorn
→ 旧 secret 调 /auth/callback 应该 401
→ 新 secret 登录通
```

**Acceptance**:
- 旧 secret 验证 401(命令: 用旧 secret 模拟一次 callback,记 status code)
- 新 secret 完整登录流程通(Google → callback → JWT 签发 → /me 返回 email)
- secret 不再以明文出现在任何 git history(`git log -p | grep -i 'GOCSPX'` 无新增)
- (可选)在 .env.template 加注释 `# DO NOT commit / DO NOT screenshot`

ETA: 5-10 min。

### 3.1 P0: test_set v0.3 expansion to ≥ 100 queries (KPI 1, with fallback)

**前置**: Week 7 ship 后团队跑了一些 query,query log 有真实样本。

```bash
# 拉真 query log
grep '"event": "search\\.' /var/log/uvicorn.log | jq -r '.query' | sort -u > /tmp/real_queries.txt
# 或 structlog json:
jq -r 'select(.event | startswith("search.")) | .query' < api.log | sort -u | wc -l
# 记 N_real := 真 query 数
```

**Fallback decision tree (NEW in v2.3.1)**:

```
N_real >= 70:
  → 真:synth = 70:30, synth 用 LLM 生成但标 source="llm_synth_v0.3"
  → KPI 1 达成
  → §3.2 sweep 全 100 query 跑
  → ADR-0015/0016 supplement 标注 "30% synthetic" 限定

30 <= N_real < 70:
  → 真:synth = N_real : (100 - N_real), 但 §3.2 sweep 仅在真 query 子集跑
  → KPI 1 标 "soft pass (mixed source)"
  → KPI 2 carry to Week 9

N_real < 30:
  → 不出 v0.3, KPI 1+2 全 carry to Week 9
  → Week 8 主线 pivot 到 §3.4/3.5/3.6/3.7
  → KPI 5 (traffic-driving) 升 critical, 不 ship 不收工
```

按 PLAN v1.3 §4.1 比例补到 100:

| Category | 当前 v0.2 | 目标 v0.3 |
|---|---:|---:|
| Simple (code lookup) | 12 | **30** |
| Medium (NL with single hit) | 8 | **30** |
| Complex (multi-course / ambiguous) | 10 | **20** |
| Boundary (alias / slang / no-space code) | 6 | **10** |
| Adversarial (no good match) | 4 | **10** |

写到 `eval/test_set.json` v0.3,bump version 字段。新增 query 必须有人工 ground
truth (`expected_course_ids`)。Synthetic query 必须有 `source="llm_synth_v0.3"`
字段并 explicit 排除在 ADR-0015 sweep 主分析外(进 sensitivity supplement)。

**Acceptance**:
- `eval/test_set.json` version="0.3"
- queries 长度 ≥ 100
- 每条带 `expected_course_ids`(空列表 = adversarial)
- 每条带 `source` 字段(`real_log` / `manual_seed` / `llm_synth_v0.3`)
- 真 query 数 ≥ 30 (即 fallback tree 不落入第三档)

ETA: 真 query log 来了之后 ~2-3h(挑选 + 标注);如果走 fallback 第二档加 1h LLM gen + dedup。

### 3.2 P0: Re-sweep ADR-0015 + ADR-0016 on v0.3 with paired bootstrap CI (KPI 2)

**强制**(v2.2 §3.5 + §3.6 都标 provisional / mandatory re-sweep)。**v2.3.1 新增
statistical rigor**: 必须出 paired bootstrap 95% CI,否则 module 常量不动。

```bash
# α grid 重扫
uv run python eval/sweep_blend_alpha.py \
    --test-set eval/test_set.json \
    --alpha-grid 0.0,0.2,0.4,0.6,0.8,1.0 \
    --bootstrap-resamples 1000 \
    --out-json eval/blend_sweep_results_v03.json

# threshold ROC 重扫
uv run python eval/sweep_reject_threshold.py \
    --test-set eval/test_set.json \
    --threshold-grid 0.01,0.03,0.05,0.07,0.10 \
    --bootstrap-resamples 1000 \
    --out-json eval/reject_threshold_sweep_v03.json
```

**新决策规则 (v2.3.1 替代 v2.3 §3.2 ad-hoc 阈值)**:

```
仅当 α* 的 R@5 bootstrap CI lower bound > α=0.4 的 R@5 point estimate
   AND  α* 的 MRR  bootstrap CI lower bound > α=0.4 的 MRR  point estimate
→ 升 ADR-0015 hard, 更新 api/routes/search.py 模块常量, 重新部署

否则:
→ 保持 α=0.4 provisional, ADR-0015 supplement 报告 CI overlap
→ 标记 "等 v0.4 (≥500 真 query) 重判"
```

T 同理(把 0.02 换成 "T* CI lower > 现行 T point estimate")。

如果 sweep harness 还没 bootstrap support,Week 8 第一天先加(参考
`scipy.stats.bootstrap` 或手写 numpy.random.choice,~1h 含测试)。

**Acceptance**:
- ADR-0015 v0.3 supplement 含: 6 档 α 的 R@5 / MRR mean ± 95% CI 表
- ADR-0016 v0.3 supplement 同上 T
- 升 hard / 保 provisional 的决策 explicit, 有 CI 数字支撑
- 如果 v0.3 上 **Pareto-improvement** AND 通过 CI 检验, 原 soft-fallback 决策升 hard
- 在 `eval/metrics_history.json` 追加一条记录(NEW): `{date, version, alpha, T,
  R@5_mean, R@5_ci, MRR_mean, MRR_ci}` — 给 v0.4 baseline 用

ETA: 1.5h sweep run + 1h ADR write-up + 0-1h bootstrap implementation。

### 3.3 P0: CS 5200 prompt revision + hold-out regression eval (KPI 3)

Week 7 §3.2 实测发现:Gemini 给 CS 5200 返回 `skill_tags` 但**未配** `evidence_snippets`
→ Pydantic validator 拒绝。

修改路径: `llm/prompts/extract_v1.py` → `extract_v1_1.py`(append-only history)

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

**新增 v2.3.1 regression eval**:

prompt 加严 evidence 约束的典型副作用:Gemini "play safe"主动留空 soft fields,
信息密度下降。仅靠 CS 5200 单课 + mock unit test 不能保护。

```bash
# 对 3 门已 indexed hold-out 课用 v1.1 重跑, 对比 soft field 非空率
uv run python scripts/diff_prompt_versions.py \
    --courses neu-aai-6600,neu-cs-5800,neu-cs-6140 \
    --baseline-prompt v1.0 \
    --candidate-prompt v1.1 \
    --metric soft_field_nonempty_rate \
    --out eval/prompt_v1_1_regression.json

# Gate: 任一课 nonempty rate 跌 > 15% → 不通过, prompt 需进一步迭代
```

如果 `diff_prompt_versions.py` 不存在,Week 8 第一天先写(~1h, 输入两组
generated_json,按 schema soft fields 列表逐 field 算 non-null 比例,输出 diff table)。

**Acceptance**:
- `tests/test_review_enrichment.py` 加测试: mock Gemini 非空 soft + 空 evidence → ValidationError
- CS 5200 live enrich 不抛 OAuthError/GeminiError/ValidationError, schema_version=1.1 + evidence_snippets 非空
  - 命令: `uv run python scripts/enrich_course_via_rmp.py --course-id neu-cs-5200 --professor "Durant Kathleen" --professor "Cobbe Richard" --live --save`
- **NEW**: 3 门 hold-out 课 soft field nonempty rate 跌幅每课 ≤ 15%
- **NEW**: `eval/prompt_v1_1_regression.json` 落库供 portfolio 引用

ETA: 1h prompt iter + 1h diff_prompt_versions.py(如缺) + 30 min smoke + 3 课 hold-out ~$0.15。

### 3.4 P1: SDK migration `google.generativeai` → `google.genai` **(顺序前置, v2.3.1 改动)**

**v2.3.1 改动**: 原 v2.3 §3.5,提到 §3.5 之前。理由:新 SDK `response_schema` /
sampling default 可能让输出 generated_json 微差。如果 16 课先用旧 SDK enrich 完,
再迁移发现新 SDK schema 漂,16 课 ~$0.80 全要重跑。

迁移工作:

- `llm/gemini_client.py`: `import google.generativeai as genai` → `from google import genai`
- 新 SDK 用 `genai.Client(api_key=...)` 而不是 `genai.configure()`
- `response_schema` 接口可能改了 — 重测 `pydantic_to_gemini_schema()` 是否还需要
  (新 SDK 可能原生支持完整 JSON Schema → strip 逻辑可 simplify 或删)
- `tests/test_gemini_client.py` 11 个测试得重检
- `pyproject.toml` 改依赖(`google-generativeai` → `google-genai`)
- `uv lock` + `uv sync`

**新增 v2.3.1 smoke gate (在跑 §3.5 之前必须通过)**:

```bash
# 在 branch sdk-migrate 上做迁移
git checkout -b sdk-migrate

# 先把当前 SDK 在 cs5800 的输出存为 baseline (Week 7 已 enrich, 从 SQLite dump)
uv run python scripts/dump_generated_json.py --course-id neu-cs-5800 \
    --out data/cs5800_old_sdk_baseline.json

# 完成迁移后, 同一门已 indexed 课用新 SDK 重 enrich (单课, $0.05)
uv run python scripts/enrich_course_via_rmp.py \
    --course-id neu-cs-5800 --live --save \
    --output /tmp/cs5800_new_sdk.json

# 与旧 SDK baseline diff
diff <(jq -S 'del(.timestamp, .request_id)' /tmp/cs5800_new_sdk.json) \
     <(jq -S 'del(.timestamp, .request_id)' data/cs5800_old_sdk_baseline.json) \
     | head -100

# Gate 决策:
# - diff 仅 timestamp / 顺序差异     → 通过, §3.5 用新 SDK 批 enrich
# - diff 含 schema 字段差异          → 暂缓迁移, §3.5 用旧 SDK + suppress warning
# - diff 含 soft field 取值变化       → 重新 calibrate prompt v1.1 阈值, gate 重审
```

**Acceptance**:
- 所有现有 Gemini 测试仍 pass
- `enrich_course_via_rmp.py --live` 一次性 smoke 不报 deprecation warning
- 新旧 SDK 单课 diff 只有 timestamp 差异(允许), 无 schema / 取值差异
- merge `sdk-migrate` branch 仅在 smoke gate 通过后

ETA: 2-3h SDK 接口对齐 + 测试 + 30 min smoke gate。如果 gate 失败, 回滚 branch,
继续走旧 SDK,§3.5 不阻塞。

### 3.5 P1: Scale Gemini enrichment to remaining 16 courses **(顺序后置, v2.3.1 改动)**

**前置**:
- §3.3 prompt v1.1 hold-out regression 通过
- §3.4 SDK 迁移 smoke gate 通过(或 explicit 决定继续走旧 SDK)

按 PLAN_v1.3 §6 / Week 7 §3.2 的"剩 16 门核心课"列表。每课 ~$0.05,总 ~$0.80。

**v2.3.1 新增 prof 名表预备**:

prof 名字来源(避免临时手忙脚乱查):

```
1. NEU course catalog (https://catalog.northeastern.edu) — 课程页 instructor 字段
2. Banner / MyNortheastern course schedule — 当前/历史学期 instructor
3. Department faculty page (e.g. khoury.northeastern.edu/people/) — 验证 spelling
4. RateMyProfessor — 反查关联确认
```

跑之前先一次性把 16 课 prof 名整理到 `data/prof_assignments_week8.csv`(列:
`course_id, primary_prof, secondary_profs`)。

```bash
for cid in $(awk -F, 'NR>1 {print $1}' data/prof_assignments_week8.csv); do
  prof=$(awk -F, -v c="$cid" '$1==c {print $2}' data/prof_assignments_week8.csv)
  uv run python scripts/enrich_course_via_rmp.py \
      --course-id "$cid" --professor "$prof" --live --save
done

# 全 enrich 完后重 embed
uv run python scripts/rebuild_faiss.py --all
uv run python scripts/mark_pending_indexed.py
```

16 课列表(同 v2.3): `neu-cs-5200 neu-cs-6140 neu-ds-5230 neu-math-7233 neu-aly-6010
neu-info-6105 neu-cs-6200 neu-aly-6140 neu-eece-5645 neu-cs-6240 neu-ds-5500
neu-aly-6080 neu-aai-5015 neu-ds-5110 neu-cs-2000 neu-info-6150`。

**Acceptance**:
- 16 课 status='indexed' 且 `generated_json.evidence_snippets` 长度 ≥ 1
- `eval/run_eval.py --rerank --with-rejection` R@5 在 v0.3 上的数字与 enrich 前对比
  (track delta in PR description)
- `data/prof_assignments_week8.csv` checked in 供 v3.0 reproduce

ETA: 1h prof 名表 + 30 min 跑(串行 80s walltime,稳过 RPM)+ ~$0.80。

### 3.6 P1: Ragas eval with judge bias control (KPI 4 dependency)

PLAN v1.3 / v2.0 一直挂着。Week 7 真 enrich 数据落库后值得跑。**v2.3.1 新增 judge
bias 控制**: Gemini 同时是 enrichment source + judge → self-preference bias,
quant interview 必问。

```bash
# 主 run: Gemini 作 judge
uv run python eval/ragas_runner.py \
    --use-real-gemini \
    --out eval/ragas_v03_gemini_judge.json
```

指标:
- Faithfulness(答案是否有 source 支撑)
- Context Precision(top-k 召回里几个真相关)
- Answer Relevance(答案与问题语义相关性)

**v2.3.1 加 bias 控制 — 至少一项**:

**(a) 30 query 人工 cohen's κ (推荐, 最便宜最可信)**

```bash
# 从 100 query 随机抽 30
uv run python eval/sample_for_human_label.py \
    --n 30 --seed 42 \
    --out eval/human_label_subset_30.json

# 你自己 label faithfulness ∈ {0, 1}, 顺便挑 5 条做 second-rater 自检
# 然后:
uv run python eval/cohen_kappa.py \
    --human eval/human_label_subset_30.json \
    --judge eval/ragas_v03_gemini_judge.json \
    --metric faithfulness \
    --out eval/judge_human_agreement.json

# Gate: cohen's κ < 0.6 → judge 数字标注 "low agreement, interpret with caution"
#       cohen's κ ≥ 0.6 → judge 数字 portfolio 可用
```

**(b) Cross-judge with Claude/GPT (备选, $1.5)**

```bash
uv run python eval/ragas_runner.py \
    --judge claude-sonnet-4-6 \
    --out eval/ragas_v03_claude_judge.json

# inter-judge correlation
uv run python eval/inter_judge_pearson.py \
    --gemini eval/ragas_v03_gemini_judge.json \
    --claude eval/ragas_v03_claude_judge.json
# Gate: Pearson r ≥ 0.7 → judge 数字稳健
```

**(c) Explicit limitation acknowledgment (兜底, $0)**

如果 (a)(b) 都做不了, `docs/portfolio_metrics.md` 必须含一节 "Judge bias caveat":
explicit 说明 same-model judge 的 self-preference 风险, 援引 [Liu et al. 2023
G-Eval] 等先验研究的 ~5-10% upward bias 经验值, 数字 portfolio 减相应 margin
后报告。

**Acceptance**: `eval/ragas_v03_gemini_judge.json` 输出 + (a)(b)(c) 至少一项落地 +
v2.3.1 self-grade table 写实测三项 Ragas 数字 + bias 控制结论。

ETA: 主 run 1h(code 30 + 跑 30); (a) 加 1h(人工 label 是 bottleneck);(b) 加 30 min。

### 3.7 P1: Portfolio packaging — quant-interview-ready (KPI 4)

**v2.3.1 framing 升级**: v2.3 §3.7 列的是 generic SWE portfolio。Quant infra/ML
面试(Citadel / JS / HRT / TwoSigma / DRW / Optiver 等)对 retrieval / ML 系统
评估严谨度审查比 SWE 面试苛刻得多。Week 8 末必交付下面 5+3 件:

**Generic engineering portfolio (5 件, 同 v2.3)**:

| 子项 | 文件 |
|---|---|
| README overhaul (number-first hero block) | `README.md` |
| System diagram (PNG/SVG, 不只是 ASCII) | `docs/system_architecture.png` (mermaid 转 PNG OK) |
| Canonical metrics table | `docs/portfolio_metrics.md` |
| Postmortem 一页 | `docs/postmortem_week7.md` (Week 7 ship 8 个踩坑, 源自 v2.2 §9.2) |
| `roadmap_v3.md` | `docs/roadmap_v3.md` (社交层 / classmates / learnable blending / 移动端) |

**Quant-specific framing (NEW in v2.3.1, 3 件)**:

`docs/portfolio_metrics.md` 必须含以下三节,每节独立一页:

**§A. Counterfactual table** (展示 trade-off shape, 不是 sweep)

| α | R@5 (95% CI) | MRR (95% CI) | p95 latency | Gemini cost / 100q |
|---:|---|---|---:|---:|
| 0.0 (pure rerank) | x.xxx ± xx | x.xxx ± xx | xx ms | $x.xx |
| 0.2 | ... | ... | ... | ... |
| 0.4 (current) | ... | ... | ... | ... |
| 0.6 | ... | ... | ... | ... |
| 0.8 | ... | ... | ... | ... |
| 1.0 (pure RRF) | ... | ... | ... | ... |

数字直接来自 §3.2 sweep 的 `eval/blend_sweep_results_v03.json`。文末写一段 (≤ 200
字)你对这张表的 first-principle 解读: "α=0.4 选这里因为 reranker 信号在 head 强
tail 弱, α 太小 (≤ 0.2) tail query 退化, 太大 (≥ 0.6) head query 失去 reranker 信号"。

**§B. Latency budget derivation** (first principle, 不是 post-hoc)

```
User-perceived budget       : 1000 ms (Nielsen 1993, "1s 是流畅交互上限")
  - Network round trip      :  50 ms (cloudflared US tunnel,东亚访问会更高)
  - Frontend render         : 100 ms (Streamlit st.write_stream initial buffer)
  - Server budget           : 850 ms ↓
    - Cold tail (DB conn)   :  20 ms
    - Embedding model fwd   :  60 ms (BGE-large CPU; GPU ~10ms 但本地 vs 部署各价)
    - FAISS top-50 ANN      :  15 ms
    - SQL alias lookup      :   3 ms
    - Reranker (CrossEncoder, k=20): 250 ms  ← bottleneck
    - Z-score blend         :   2 ms
    - Headroom              : 500 ms ← buffer for tail / GC / contention

Hard budget for sustainable load : 300 ms p95
  Current p95 measured              : 58 ms ✓ 5x headroom
  When does this break?
    - k > 50 reranker pool: linear blow-up; mitigation = cascade (BM25 → 50 → rerank top 20)
    - Concurrent load > 20 req/s: GPU contention if 移到 GPU; CPU-bound 目前 OK
    - Cold start: 70s 首 query (§3.10 warm-up procedure 兜底)
```

**§C. Failure mode catalog** (5 个 adversarial / edge case 你的系统输给 baseline)

| # | Query | Your system top-1 | BM25 baseline top-1 | Why your system wrong | Fix budget (eng-month) |
|---|---|---|---|---|---|
| 1 | (一个 alias 没覆盖的口语化 query) | wrong | right | reranker 把字面相似的 advanced 课排前 | 0.2 — 加 alias |
| 2 | ... | ... | ... | ... | ... |
| ... | | | | | |

这个表 quant 面试官会读得最仔细 — 因为它 demonstrate 你**承认系统的失败**而不是
只 cherry-pick 漂亮数字。这是 quant 文化(risk-aware, downside-first)的直接 mapping。

**Acceptance**:
- 三方人(LYU / Andy / 一个新 reviewer)读 README 5 分钟能讲清场景 + 3 个差异化数字
- **NEW**: 一个 quant-side 朋友 / mentor 读 `portfolio_metrics.md` §A/B/C 30 min 后,
  能问出至少 1 个 follow-up question (说明数字勾起兴趣而不是糊弄)
- 所有数字直接 traceable 到 `eval/*.json` artifacts(无 hardcoded)

ETA: 4h diagram + 写作 + 2h §A/B/C 三节深度内容(其中 §B 1h, §C 1h)。

### 3.8 P2: Streamlit chat_input WS / 视觉问题复测 (原 v2.3 §3.9)

Week 7 实测有报告:登录后 chat_input 看起来"灰",不确定是 Streamlit 视觉默认还是
WebSocket 没建起来(cloudflared 偶尔吃 streamlit 的 WS 升级)。

排查:
1. F12 → Network → 筛 WS → 看 `_stcore/stream` Status 是否 101
2. 如果 WS 失败,看 cloudflared config 是否需要显式 `noTLSVerify: false` /
   WS upgrade 设置(current `originRequest` 块已有 `tcpKeepAlive`)
3. 如果 Streamlit 1.X 版本本来 chat_input 灰, 记 known limitation 进 §8

**Acceptance**: chat_input 能输入文字 + 提交后 `/chat` 命中 → uvicorn log 见 NDJSON
stream + Streamlit `st.write_stream` 渲染 token。

ETA: 30 min - 2h(取决于是否 WS 真坏)。

### 3.9 P2: 100-query latency p99 监控 (原 v2.3 §3.10)

**v2.3.1 修矛盾**: v2.3 §3.10 前置是 "如果 KPI 2 (Week 7) 真攒到 200 query", 但
v2.3 §2.2 又说"不为这个等"。v2.3.1 解开: 这条改成 KPI 5 attached, 即如果 KPI 5
ship (≥ 30 真 query + 3 contributors), latency probe 跑 100 iterations 而非 200,
记 p50/p95/p99 baseline 进 §3.7 §B latency table。

```bash
uv run python scripts/probe_latency.py --warmup 5 --iterations 100
```

如果 p99 > 100ms, 考虑:
- Drop reranker 在 hot path,只做 alias + hybrid;后台异步 enrich
- batch reranker 调用调优(reranker 已经 batch, batch_size = pool_size = 20, 可调)
- GPU FP16 / INT8

**Acceptance**: 当前 budget 是 < 300ms。Week 7 实测 p50 ~47ms / p95 ~58ms 远低于。
p99 数字写入 `docs/portfolio_metrics.md` §B latency budget table。

ETA: 30 min monitor + 0-2h tuning。

### 3.10 P2: Cold start warm-up procedure (NEW in v2.3.1)

**理由**: cold start ~70s 在 §1 invariants 里, quant interview live demo 时 70s
等模型 load 体验 < 0。0 成本临时 fix:

**Option A: docker / supervisor healthcheck**

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/search?q=test&k=1"]
  interval: 5m
  timeout: 10s
  start_period: 90s
```

**Option B: cron pre-warm** (WSL 或 Windows 都行)

```cron
*/5 * * * * curl -s "http://localhost:8000/search?q=warmup&k=1" > /dev/null
```

**Option C: demo 前 manual warm-up** (零基础设施)

demo 前 2 min 自己手打 1 个 query 触发 load。在 §3.7 README "Try it" 区块 explicit
注一句 "first query takes ~70s due to cold start; subsequent queries < 60ms"。

**Acceptance**: 三个 option 至少一个落地。Option C 最低成本, 适合 Week 8 末
portfolio demo 用; Option A/B 适合 v3.0 真有 traffic 时上。

ETA: 5 min Option C; 30 min Option A 或 B。

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
| ADR-0015/0016 升 hard 决策(若 v0.3 CI 检验未过) | v3.0 用 ≥ 500 真 query 重判 |
| Cold start 真治本(model 预 load / mmap / lazy import) | v3.0 |

---

## 5. Open TODOs (carry from v2.3 + v2.3.1 重排)

| Priority | TODO | Where | Source |
|---|---|---|---|
| **P0** | **Rotate OAuth secret** | **Console + .env** | **v2.3.1 §3.0 (从 v2.3 §3.8 升级)** |
| P0 | test_set v0.3 ≥ 100 query (with fallback) | `eval/test_set.json` | v2.3.1 §3.1 |
| P0 | ADR-0015 + 0016 v0.3 supplement (paired bootstrap CI) | `docs/adr/0015*.md` + `0016*.md` | v2.3.1 §3.2 |
| P0 | CS 5200 prompt revision + hold-out regression | `llm/prompts/extract_v1_1.py` + `eval/prompt_v1_1_regression.json` | v2.3.1 §3.3 |
| P0 | KPI 5 traffic-driving (≥30 真 query, ≥3 contributors) | live data + outreach action | v2.3.1 §2.1 NEW |
| P0 | Portfolio packaging quant-ready | README + diagram + metrics + counterfactual + latency + failure modes | v2.3.1 §3.7 |
| P1 | google.genai SDK migrate (with smoke gate) | `llm/gemini_client.py` | v2.3.1 §3.4 (前置) |
| P1 | 16 课 Gemini enrich + rebuild | scripts + `data/prof_assignments_week8.csv` | v2.3.1 §3.5 (后置) |
| P1 | Ragas eval with judge bias control | `eval/ragas_v03_*.json` + cohen's κ OR cross-judge OR limitation note | v2.3.1 §3.6 |
| P2 | Streamlit chat_input WS 复测 | F12 + cloudflared cfg | v2.3.1 §3.8 |
| P2 | p99 latency monitor + tune | `probe_latency.py` | v2.3.1 §3.9 |
| P2 | Cold start warm-up procedure | docker healthcheck / cron / manual | v2.3.1 §3.10 NEW |
| Deferred | `/course/{id}/classmates` | v3.0 | v2.2 §2.2 |
| Deferred | Learnable blending | v3.0 | v2.2 §2.2 |
| Deferred | Two-pass selection planner | v3.0 | v2.2 §2.2 |
| Deferred | Cold start 真治本 | v3.0 | v2.3.1 §4 NEW |

---

## 6. Reference

### 6.1 First 30 minutes for a returning agent

```bash
# 验证状态
wsl -d Ubuntu-24.04
cd /mnt/h/neu-compass
git log --oneline | head -3                       # 最近 commit
uv run pytest tests/ -q                           # ≥ 631 (v2.2 ship floor); EOW Week 8 → ≥ 660
uv run python scripts/probe_latency.py            # p50 ~40ms hybrid-only

# 读 v2.3.1 (这文件) → v2.3 (上一版,看为啥某些事重排) → v2.2 §9 closeout (踩坑) → ADRs 0013-0016
cat docs/PLAN_v2.3.1.md
cat docs/PLAN_v2.3.md
cat docs/PLAN_v2.2.md
ls docs/adr/0015*.md docs/adr/0016*.md

# 起 live stack(本地或公网)
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 &
uv run streamlit run app/streamlit_app.py --server.port 8501 --server.address 0.0.0.0 &
# Windows 边: cloudflared tunnel run neu-compass (公网部署后)

# Sprint 第一动作: rotate OAuth secret (§3.0), 在任何其他 commit 之前
```

### 6.2 Week 8 deliverable 一览 (v2.3.1)

| Artifact | Path | Source section |
|---|---|---|
| Rotated OAuth secret in .env | `.env` (not committed) | §3.0 |
| test_set v0.3 | `eval/test_set.json` (version="0.3") | §3.1 |
| α grid v0.3 results + bootstrap CI | `eval/blend_sweep_results_v03.json` | §3.2 |
| Threshold ROC v0.3 results + bootstrap CI | `eval/reject_threshold_sweep_v03.json` | §3.2 |
| ADR-0015 v0.3 supplement | `docs/adr/0015-z-score-blending.md` (footer) | §3.2 |
| ADR-0016 v0.3 supplement | `docs/adr/0016-reranker-reject-threshold.md` (footer) | §3.2 |
| Metrics history append | `eval/metrics_history.json` | §3.2 |
| Prompt v1.1 | `llm/prompts/extract_v1_1.py` | §3.3 |
| Prompt regression report | `eval/prompt_v1_1_regression.json` | §3.3 |
| SDK migration smoke diff | `/tmp/cs5800_new_sdk.json` vs `data/cs5800_old_sdk_baseline.json` | §3.4 |
| Prof assignments table | `data/prof_assignments_week8.csv` | §3.5 |
| Ragas v0.3 results (Gemini judge) | `eval/ragas_v03_gemini_judge.json` | §3.6 |
| Judge bias artifact (一项) | `eval/judge_human_agreement.json` OR `eval/ragas_v03_claude_judge.json` OR limitation note in metrics.md | §3.6 |
| System diagram | `docs/system_architecture.png` | §3.7 |
| Portfolio metrics cheatsheet | `docs/portfolio_metrics.md` (含 §A/B/C) | §3.7 |
| Postmortem | `docs/postmortem_week7.md` | §3.7 |
| `roadmap_v3.md` | `docs/roadmap_v3.md` | §3.7 |
| Latency baseline (post traffic) | append to `portfolio_metrics.md` §B | §3.9 |

### 6.3 Conventions worth preserving (unchanged from v2.2 §6.3)

- Pydantic models: `model_config = ConfigDict(extra="forbid")`
- Tests: build on `tests/conftest.py:empty_db` fixture + `FixtureEmbedder` + `FixtureReranker`
- API tests: `api_client` fixture + override `get_db_conn`
- Repositories take `connection` in `__init__`; caller manages lifecycle
- LLM-callable functions accept injectable `model` / `expand_fn` / `llm_fn` / `stream_fn`
- ADRs: follow `docs/adr/0000-template.md`
- Commits: `feat(scope): ...` / `feat(weekN): ...` / `docs: ...` / `test: ...`

### 6.4 v2.3.1 指挥棒 (NEW): EOW self-grade 5-row 表

Sprint 末快速自评(填进 closeout):

| KPI | Status | 数字 | 备注 |
|---|---|---|---|
| 1 v0.3 ≥ 100 query | ✓/✗/partial | N=___ (real=___, synth=___) | fallback 第几档 |
| 2 ADR-0015/0016 supplement w/ CI | ✓/✗ | α* CI vs α=0.4 CI overlap? | 升 hard / 保 provisional |
| 3 prompt v1.1 + regression | ✓/✗ | 3 课 nonempty rate Δ | 最大跌幅 |
| 4 portfolio quant-ready | ✓/✗ | quant 朋友 follow-up 数 | 数字傲娇还是糊弄 |
| 5 traffic-driving | ✓/✗ | 真 query=___ contrib=___ | outreach action 完成度 |

---

## 7. Versioning

- **PLAN v1.0**: original 8-week plan
- **PLAN v1.2 (FINAL)**: PDF revision shared at session start
- **PLAN v1.3**: Week 0 critique-driven revision
- **PLAN v2.0**: Week 5 checkpoint
- **PLAN v2.1**: Week 6 checkpoint (ship state)
- **PLAN v2.2**: Week 7 sprint plan + closeout
- **PLAN v2.3**: Week 8 forward plan
- **PLAN v2.3.1**: this file. Review-driven hardening of v2.3.
- **Next**: v3.0 起社交层 + learnable blending(等 ≥ 500 真 query log + ≥ 30 用户)。

---

## 8. Acknowledged limits + intentional tradeoffs

- **v0.3 expansion 是 Week 8 第一阻塞项 — but with explicit fallback** (§3.1)。
- **CS 5200 prompt 修复后才扩 16 课** + hold-out regression eval(§3.3 → §3.5),
  反过来跑会浪费 ~$0.80。
- **google.genai 迁移可能引入新 bug**: smoke gate 落 §3.4, 不通过则 explicit 走旧
  SDK + suppress warning,不阻塞 §3.5。
- **Portfolio packaging 是软产出**: 数字真不真比文档花不花更重要。先有 v0.3 + Ragas
  数字 + bias 控制结论, 后写 README — 别反过来。
- **Streamlit chat_input 问题**: §3.8 30 min 排查 + 记 known limitation; 切 React
  前端是 v3.0 工作不在本周。
- **Cold start ~70s**: Week 8 不真治本, 仅 §3.10 加 warm-up procedure 兜 demo。v3.0
  再做 model 预 load / mmap。
- **Judge bias**: §3.6 至少做一项, 但 cohen's κ < 0.6 / Pearson r < 0.7 不否决 ship,
  只标 caution。
- **paired bootstrap CI 可能显示 α=0.4 vs α* 不显著**: 这是 100 query small-sample
  正常结果, 不否决 v0.3 ship, 只 keep provisional。
- **KPI 5 traffic-driving 是非工程问题**: outreach action 是必做但 outcome 不
  100% 可控。EOW 不达标允许标 "soft fail with clear reason", 但禁止"等"作为实施
  路径。

---

**End of v2.3.1**. Open Week 8 session 顺序: §3.0 (rotate) → §1 invariant 复读 →
§2.1 KPI 矩阵贴墙 → §3.1 (or fallback tree 决策) → §3.2 / §3.3 并发 → §3.4 → §3.5
→ §3.6 → §3.7 (Week 8 末三天集中)。P2 散件穿插不阻塞主线。

---

## 10. Closeout (post-Week 8 + Week 9 perf, 2026-05-06)

**Sprint partial ship**:
- ✅ KPI 1-4 全 ship(详见 v2.3 §10 closeout + Week 9 perf)
- 🟡 KPI 5 traffic-driving:**outreach action 未启动**,真 query log 仍 0/30。User 接受 "等真 traffic" 作为实施路径(违反 v2.3.1 §2.1 explicit ban,但 reality wins)
- ⏭️ §3.0 OAuth secret rotate:**主动跳过**(user feedback memory:项目频繁重建,旧凭证随 project 废弃自然失效)

**v2.3.1 加严的 acceptance(bootstrap CI / hold-out regression / counterfactual)** 大部分 inherit 进 v3.0,等真 v0.3 数据来了再激活。

**项目相位转移到 v3.0**:engineering 主线 ship 完毕,signal-driven 模式启动。继续读 [PLAN_v3.0.md](PLAN_v3.0.md)。
