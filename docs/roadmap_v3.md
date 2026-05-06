# NEU-Compass · Roadmap v3 (post Week 8)

> **Updated**: 2026-05-05 (Week 8 起草,PLAN v2.3 §3.7 子项)
> **Read order**: PLAN v2.3 (Week 8 落地) → 本文 (v3.0+ 中长期)
> **目的**: 把 v2.x sprint plan 里反复 deferred 的"等用户量 / 等 query log / 等团队产能"事项归到一个文档,跟当前 sprint 解耦。

---

## 0. 触发条件 (gating signals)

v3.0 不是日历驱动而是**信号驱动**。任何一条触发就启动 v3 sprint plan:

| Signal | 阈值 | 当前状态 |
|---|---:|---|
| 真 query log 累计 | ≥ 500 | 0 (Week 7 ship 后等 traffic) |
| 真 OAuth 用户 | ≥ 30 | 1/5 |
| Co-op UGC 提交 | ≥ 10 | 0 (seed 30 都是 curated) |
| Adversarial 在野样本 | ≥ 20 | 0 |
| Ragas baseline 跑通 | 1 次 | pending Week 8 §3.6 |

任意 ≥ 2 条触发,起 PLAN v3.0;否则继续 v2.x 演进。

---

## 1. 社交层 (Course Buddies)

PLAN_v1.3 / v2.x 一直把 "find course buddies" 列为产品北极星,但工程交付一路 deferred 等真用户。
v2.2 §3.6 已落 schema (`user_courses` 表 + indexes,DDL only)。v3.0 启动 API + UI。

### 1.1 数据模型(已就位)

```sql
-- db/init.sql (Week 7 §3.6 已落)
CREATE TABLE user_courses (
    id, user_id, course_id, term, status, visibility, created_at, updated_at
)
-- visibility: private | classmates | public
-- status:     planning | enrolled | completed
```

### 1.2 v3.0 endpoint plan

| Endpoint | k-anonymity | 备注 |
|---|---:|---|
| `POST /user_courses` | n/a | 单用户写自己的 plan |
| `GET /user_courses/me` | n/a | 自己的列表 |
| `GET /course/{id}/classmates` | **k=3** | 比 Co-op 的 k=2 更严 — 选课 social 比职业历史更敏感 |
| `POST /classmates/connect` | n/a | 双向接受才暴露 contact |
| `GET /classmates/recommendations` | k=3 | "跟你重叠 ≥ 2 门课的同学" |

### 1.3 不在 v3.0

- 私聊 / DM:超出 F1 合规边界(社交平台嫌疑)
- 评分 / review:有 honor code 风险,且 RMP 已经覆盖
- 课程推荐:跟 search 路径混淆,留到 v4.0

### 1.4 决策需要 ADR

- ADR-0017 (待写): 选课 social 的 k=3 vs k=2 trade-off,visibility 三档语义
- ADR-0018 (待写): connect 流程的双向 confirm 模式 vs LinkedIn 单向 follow

---

## 2. Learnable blending (RRF + reranker α)

ADR-0015 锁的 α=0.4 是 9 个值的 grid + soft fallback。
n=42 测试集 5/9 个 R@5 落在 4 个相同值上 — 统计粒度饱和。
真 query log ≥ 500 后做 learnable α。

### 2.1 候选模型

| 方案 | 输入特征 | 输出 | 复杂度 |
|---|---|---|---|
| **per-query α scalar (lightGBM)** | query length, has_course_code, dept tokens, BM25 max score, vector max score | 标量 α ∈ [0, 1] | 中 (1k 训练样本够) |
| Per-pair learning-to-rank (XGBoost) | (query, doc) 特征对 | rank score | 高 (5k+ 训练样本) |
| Pure-encoder (MLP on [z_rrf, z_rerank, query_emb]) | embedding-rich | 单分数 | 高 (需 GPU 推理 latency) |

倾向: lightGBM scalar α (推理 < 0.5ms,可解释,5090 cold start 可省)。

### 2.2 训练数据需求

需要 (query, doc, relevance) 三元组 × ≥ 500 query × top-20 doc = 10k pairs。
真 query log + click log + 双盲标注 (按 `docs/annotation_guide.md`) 拼出来。

### 2.3 不在 v3.0

- Cross-encoder fine-tuning: bge-reranker-v2-m3 已经够强,fine-tune ROI 低
- Multi-task 同时学 reject threshold:阈值跟 α 各自回答不同问题 (ADR-0015 / 0016 §3.4)

---

## 3. Multi-vector / ColBERT-style 第三检索 leg

### 3.1 动机

complex query 类别在 v0.2 上跨所有 α 都 R@5 = 0.25 (1/4) — 召回瓶颈不是排序。
rerank_pool=20 之外的对的课根本进不来。

### 3.2 候选

- 加大 rerank_pool 到 50/100 — 简单但 latency 线性涨
- ColBERT v2 的 token-level late interaction — 召回升,latency 接受 (~30ms 增量)
- HyDE 第二次 vector retrieve — 对长 query 有效,但 Gemini 调用成本 + latency

倾向: 先加大 pool 到 50 (Week 8 §3.10 提议), 再评估 ColBERT。

### 3.3 决策依赖

- v0.3 test_set complex 类别样本量 ≥ 20 (现在 10) 才能信号显著
- p95 latency 余量 (现在 51ms,target 300ms,有空间)

---

## 4. Reddit live + 脱敏管线

scrapers/reddit.py 已经 mock-tested + PRAW 接口稳。等 `.env` 加上 PRAW 凭证后启用。

### 4.1 v3.0 启用条件

- PRAW client_id / secret 拿到(申请 Reddit dev 账户,~ 1 工作日)
- `docs/pii_redaction.md` 380 行 SOP 跑通一次实测
- structured logging + rate limit (Reddit API 60 req/min)

### 4.2 价值

- 长尾课程的 controversial_signals (Gemini-only 数据 + RMP 覆盖不全的课)
- `r/NEU` `r/CPS` 提到的 instructor reputation
- 选课时令暗号 (e.g. "this section is the easy one") — slang 字典扩充

---

## 5. Mobile-first / PWA

后端不动,前端是 Andy Dong 的 `compass-frontend` 仓库 (v3.0 时假设已建)。
本 roadmap 不深入 — 只列出后端需要 surface 的:

- ETag / If-None-Match 支持(`/course/{id}` cache 友好)
- Server-Sent Events 替代 NDJSON(SSE 浏览器原生,React 友好)
- 跨域 CORS(从 `compass.neu-compass.me` 扩到 PWA 自己的 origin)

---

## 6. 运维 / observability 升级

| 项 | 状态 | v3.0 plan |
|---|---|---|
| structlog JSON access log | ✅ | 接 Loki / OpenObserve |
| `/health`, `/ready` | ✅ | 加 `/metrics` Prometheus 格式 |
| Cloudflare Access SSO 网关 | ❌ | 双层防护 (CF Access + app/auth) — v3.0 真用户量上来后 |
| systemd unit (cloudflared 开机自启) | ❌ | Week 7 没做 — Windows 边目前手起 |
| Grafana 看板 (R@5 / latency / cost) | ❌ | 等 200+ 真 query 数据 |

---

## 7. 已知 deferred (v2.x 反复决定不做)

| 项 | Source | 不做的理由 |
|---|---|---|
| Two-pass selection planner (Yuang Dai 提的 AI vs Senior 双版本) | v2.2 §2.2 | 需要 UGC 累积才有 senior signal |
| Streamlit user-UI 重启 | v2.2 §3.3 | Andy 的 React 前端覆盖 |
| Per-category reject threshold | ADR-0016 §拒绝的备选 | n=42 太薄,需要分类决策树 |
| Top-3 average sigmoid 替代 max | ADR-0016 §拒绝的备选 | 跨 query 信号弱化,小样本噪声更大 |

---

## 8. 决策框架

v3.0 设计每个新功能时,过这 5 个 gate:

1. **F1 合规**: 商业化嫌疑?支付?投资?— 任一是 → 不做
2. **k-anonymity**: 涉及用户数据交叉吗?有 k 阈值吗?
3. **真数据驱动**: 用 ≥ 500 真 query log 验证过假设吗?还是凭"应该"?
4. **Latency budget**: 加上后 p95 < 300ms 吗?
5. **测试可重现**: 能加 ≥ 5 个 deterministic 测试吗?

任一 fail → ADR + 决策 + 重新设计。

---

## 9. 修订历史

- 2026-05-05: 初版 (PLAN v2.3 §3.7,Week 8 portfolio packaging,起草)
- v3.0 启动后: 起 `PLAN_v3.0.md` (sprint plan),本文转为长期 roadmap
