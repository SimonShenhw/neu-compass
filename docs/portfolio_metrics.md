# NEU-Compass · Canonical Metrics Cheatsheet

> **Updated**: 2026-05-05 (Week 7 ship 后,Week 8 v0.3 / Ragas 数字落地后追加 supplement)
> **Use case**: portfolio review / quant interview "数字 hero" / 简历 footnote 的 single-source-of-truth。
> **Convention**: 每条数字必须 traceable 到一个 `eval/*.json` artifact / git commit / ADR — 见末列。

---

## 1. Latency (生产实测,单机 RTX 5090 + WSL2)

| 指标 | 数字 | 测量条件 | Source |
|---|---:|---|---|
| `/search` p50 | **~47 ms** | hybrid + rerank + Z-blend α=0.4 + reject T=0.05;6469 课 indexed | `scripts/probe_latency.py --warmup 5 --iterations 100` |
| `/search` p95 | 51 ms | 同上 | 同上 |
| `/search` p99 | <60 ms | 同上,余量足 (target 300 ms) | 同上 |
| `/search` hybrid-only p50 | 40.1 ms | 不走 rerank | `scripts/probe_latency.py --no-rerank` |
| Alias hit early-exit p50 | ~3 ms | "AAI 6600" 直命中 | 实测,样本量小 |
| bge-m3 cold start | ~70 s | 首次 encode;lifespan 预热消化 | `api/main.py` startup |
| Gemini structured call (3-course) | ~$0.05/课 | response_schema + max_tokens=16384 | `data/gemini_smoke_logs/` |

**Headroom**: target < 300 ms p50 → 实测 ~47 ms = **6x 余量**。Week 8 加 reranker pool 到 50 缓解 complex 召回不会击穿预算。

---

## 2. Retrieval quality (test_set v0.2, n=42 — provisional, Week 8 重测)

### 三种模式 baseline

| 模式 | α | R@5 | MRR | simple R@5 | medium R@5 | complex R@5 |
|---|---:|---:|---:|---:|---:|---:|
| `hybrid_with_alias` (RRF only) | 1.0 | 0.601 | **0.603** | 0.75 | 0.49 | 0.25 |
| `+rerank` (cross-encoder only) | 0.0 | **0.636** | 0.545 | 0.79 | 0.56 | 0.25 |
| **Z-blend (locked production)** | **0.4** | **0.621** | **0.575** | 0.77 | 0.53 | 0.25 |

**MRR 为什么倒退**: pure rerank R@5 升 (+0.035) 但 MRR 跌 (-0.058) — reranker 把对的课召回进 top-5 更准,RRF 在 top-1 排位上更稳。
α=0.4 是 soft fallback 折衷:R@5 ≥ 0.620 子集中 max MRR (ADR-0015 §3.5)。

### Boundary / adversarial

| 类别 | hit rate | 备注 |
|---|---:|---|
| Boundary (alias / slang / no-space code) | **6/6 = 1.000** | "Algo" / "5800" / "AAI6600" 全命中 |
| Adversarial rejection at T=0.05 | **4/4 = 1.000** | "CS 0001" / 乱码 / 无关 query 全拒 (ADR-0016) |
| Real-query R@5 with rejection layer | 0.632 | T=0.05 (vs no-rejection baseline 0.621,+0.011 噪声范围) |
| False rejection on real queries | 4/38 | q013/q018/q022/q029,本身 R@5=0 不是损失 |

### BM25 调优

| 改动 | 数字 | Source |
|---|---:|---|
| stopword filter (110 word) inversion gap | +0.001 → **+0.016 (16x)** | `tests/test_hybrid.py` + `eval/run_eval.py` |
| RRF k 参数 | 60 | 业界默认,未做 sweep |

---

## 3. Storage / scale

| 指标 | 数字 | 备注 |
|---|---:|---|
| Catalog 课程数 (NEU graduate) | **6469** | 232 dept,scrape_neu_catalog.py 全量 |
| Co-op seed records | **30 条** | 12 quant / 8 big_tech / 5 biotech / 5 startup,完美匹配 PLAN 目标分布 |
| FAISS index size | ~26 MB | IndexIDMap + 1024 dim float32 |
| SQLite db size (含 enrichment) | ~80 MB | 6469 课 + 30 coop + aliases + reviews |
| Schema version (active) | **1.1** | user_courses 表 v3.0 social 预留 DDL only |
| WSL home vs H drive (SQLite write 1k INSERT) | **77x faster** | ADR-0014 实测,`docs/path_decision.md` |

---

## 4. Engineering discipline

| 指标 | 数字 | 备注 |
|---|---:|---|
| Test suite | **631 tests** | 对应 ~30 test files |
| Test runtime (WSL2 + RTX 5090) | **~12 s** | `uv run pytest tests/ -q` |
| Flake rate | **0** | Week 7 修了最后一个 sleep-based test (#8 postmortem) |
| Schema migrations active | 1 (`migrate_db_to_v1_1.py`) | idempotent,跑多次安全 |
| ADRs locked | 16 (0001-0016) | 0013/0014 invariant + 0015/0016 Week 7 |
| Pre-commit hooks | detect-secrets 严格模式 | secret 进 commit 直接 fail |

---

## 5. Cost (Week 7 实付 + Week 8 预算)

| 项 | 数字 | Why |
|---|---:|---|
| Gemini Week 7 (3-course smoke) | **< $0.20** | AAI 6600 / CS 5800 / CS 5200,16384 max_tokens |
| Gemini Week 8 plan (16 课) | ~$0.80 | §3.4 扩剩 16 门核心课,prompt v1.1 修复后 |
| Cloudflare Tunnel | **$0** | 免费 tier ≤ 50 RPS 充裕 |
| Domain (`neu-compass.me`) | $9.18 / 年 | CF Registrar 外购 |
| Hosting | $0 | 自有硬件 (RTX 5090 + Ubuntu 24.04) |
| **API budget alarm** | $150 / 月 | `.env` `API_BUDGET_ALARM=150` |

总月运营成本 ≈ $1 (Gemini 增量) + $0.76 (域名摊销)。

---

## 6. Compliance / red lines (F1)

| 项 | 状态 |
|---|---|
| 不商业化 / 不收款 / 不接受投资 | ✅ 项目无任何支付路径,文档红线 |
| OAuth 域名白名单 husky.neu.edu / northeastern.edu | ✅ `is_email_allowed` split-on-`@` 精确匹配 |
| k=2 anonymity for Co-op (`POST /coop`) | ✅ server-side 强制,`tests/test_coop_anonymity.py` 11 条 |
| PII redaction 380 行操作指南 | ✅ `docs/pii_redaction.md` |
| pre-commit detect-secrets | ✅ 严格模式 |

---

## 7. KPI ship state (Week 7,2026-05-04)

| KPI | 状态 | 落地证据 |
|---|---|---|
| 1. 公网 URL serving FastAPI | ✅ | `https://api.neu-compass.me/{health,ready,search,...}` 200 |
| 2. ≥ 200 真 query | 🟡 0/200 | 等团队 traffic |
| 3. ≥ 5 contributors OAuth round-trip | 🟡 1/5 | 自己 northeastern.edu round-trip ✓ |
| 4. ADR-0015 α + ADR-0016 T 决策 | ✅ | α=0.4 (provisional) + T=0.05 数据校准 |

---

## 8. Pending (Week 8 落地后追加)

待补 — PLAN v2.3 §3.1 / §3.2 / §3.6:

- [ ] test_set v0.3 ≥ 100 queries 真 query log 落地
- [ ] α v0.3 supplement (是否漂移)
- [ ] T v0.3 supplement (是否漂移)
- [ ] Ragas: Faithfulness / Context Precision / Answer Relevance (real Gemini judge)
- [ ] 16 课 Gemini enrich 后 R@5 / MRR delta
- [ ] p99 latency (200+ real queries 后)

---

## 9. Quick-cite footnotes

简历 / cover letter 用的"single-line claim + 出处":

> "Hybrid retrieval (BM25 + dense + cross-encoder reranker, Z-score blended at α=0.4) over **6469 NEU graduate courses** delivers **R@5 = 0.621 / MRR = 0.575** at **p50 ~47ms** — see [ADR-0015](adr/0015-z-score-blending.md), [docs/portfolio_metrics.md](portfolio_metrics.md)."

> "Adversarial query rejection layer at sigmoid T=0.05 (data-calibrated from PLAN spec 0.4) achieves **4/4 adversarial rejection** with no real-query recall loss (vs. spec threshold's -26% recall) — see [ADR-0016](adr/0016-reranker-reject-threshold.md)."

> "Production stack: FastAPI (canonical) + Streamlit (debug) on Cloudflare Tunnel,
> WSL2 + RTX 5090, **631 tests in ~12 s, zero flake**. See [docs/system_architecture.md](system_architecture.md) + [docs/postmortem_week7.md](postmortem_week7.md)."

每条都可点击进 source ADR / 实测脚本 / postmortem。
