# ADR-0015: Z-score 混合 RRF 与 reranker 信号 (α = 0.4)

## 状态

Accepted - 2026-05-04 (provisional, n=42; mandatory re-sweep on test_set v0.3 ≥ 100 — see PLAN v2.2 §4)

## 背景

`hybrid_with_alias` 模式在 test_set v0.2 上 R@5 = 0.601 / MRR = 0.603。
加上 bge-reranker-v2-m3 cross-encoder (`--rerank` 模式) 后 R@5 升到 0.636
但 MRR 跌到 0.545 —— **MRR 倒退 -0.058**。两个 baseline 各自最强,各自最弱:
reranker 把对的课召回进 top-5 更准 (高 R@5),但 RRF 在 top-1 排位上更稳 (高 MRR)。

PLAN v2.2 §3.5 锁定方向: 在 RRF 分数与 reranker sigmoid 之间做线性混合,
α 网格扫一遍取折衷。决策需要锁定:
1. **标准化方法** (Z-score / Min-Max / 三路 RRF)
2. **α 取值** (0.0 = 纯 reranker, 1.0 = 纯 RRF)

## 决策

**Z-score 标准化 + α = 0.4 线性混合**:

```
blended[i] = α · z_rrf[i] + (1 − α) · z_rerank[i]

其中:
  z_rrf[i]    = (rrf[i]    − mean(rrf))    / std(rrf)
  z_rerank[i] = (rerank[i] − mean(rerank)) / std(rerank)
```

零方差 leg (std ≤ 1e-12) 该 leg z = 0,另一边独自决定排名。这避免了
`[0.1, 0.1, 0.1].std()` ≈ 1e-17 的浮点误差被放大成 z = ±1 的伪信号。

实现: `rag/reranker.py:zscore_blend()` (纯函数) + `rerank_blend_hits()` (SearchHit 包装)。

混合用于**排序**;**绝对阈值拒绝** (ADR §3.4 / RERANKER_REJECT_THRESHOLD = 0.4)
依然走 raw sigmoid max,不走 blended z-score —— 这两个回答的是不同问题
(排序 vs 拒绝),不能耦合。

## 数据

`eval/sweep_blend_alpha.py` on test_set v0.2 (n=38 with expected),
rerank_pool = 20:

| α    | R@5    | MRR    | simple | medium | complex | p50 ms |
|------|-------:|-------:|-------:|-------:|--------:|-------:|
| 0.0  | 0.6360 | 0.5447 | 0.79   | 0.56   | 0.25    | 48.9   |
| 0.2  | 0.6206 | 0.5724 | 0.77   | 0.53   | 0.25    | 47.9   |
| 0.3  | 0.6206 | 0.5724 | 0.77   | 0.53   | 0.25    | 48.1   |
| **0.4** | **0.6206** | **0.5746** | **0.77** | **0.53** | **0.25** | **47.2** |
| 0.5  | 0.6075 | 0.5746 | 0.77   | 0.49   | 0.25    | 48.1   |
| 0.6  | 0.6075 | 0.5833 | 0.77   | 0.49   | 0.25    | 46.8   |
| 0.7  | 0.6075 | 0.5811 | 0.77   | 0.49   | 0.25    | 47.6   |
| 0.8  | 0.6009 | 0.5855 | 0.75   | 0.49   | 0.25    | 46.2   |
| 1.0  | 0.6009 | 0.6031 | 0.75   | 0.49   | 0.25    | 47.4   |

完整结果在 `eval/blend_sweep_results.json`。

R@5 单调降, MRR 单调升,**没有内部最优点同时 Pareto-超过两个 baseline**
(R@5 ≥ 0.636 AND MRR ≥ 0.603) —— 由曲线形状决定,不是采样不密的问题。
触发 PLAN v2.2 §3.5 软备选规则:**R@5 ≥ 0.620 子集中 max MRR**。
α=0.4 胜出 (R@5 = 0.621, MRR = 0.575)。

## 拒绝的备选

- **Min-Max 标准化**: bge-reranker 的 sigmoid 分布在高分端是 bimodal,
  Min-Max 把 [0, 1] 区间硬拉伸,把 top-of-pool 的分辨力压扁。RRF 那边
  ~0.0125-0.0164 的窄区间被等比放大,放大噪声。Z-score 给的 α 语义干净:
  α=0.5 严格意味着"两个标准化信号等权重"。

- **三路 RRF (alias rank + vector rank + reranker rank)**: 把 reranker 的
  绝对置信度压成排名,直接拆掉了 §3.4 拒绝层的依据 —— 拒绝需要的是
  "max sigmoid < 0.4 → 这个 query 没好答案",rank-only 没法表达。

- **Learnable blending function** (per-query α 或线性回归): n=42 query 太
  thin,容易过拟合。延后到 v3.0 真实 query log ≥ 100 后,见 `roadmap_v3.md`。

- **直接选 α=0.0 (Pareto R@5 最强)**: R@5 高 0.015 但 MRR 输 0.030,
  对应"用户拿到的第一个结果常错"的体验,UX 比 R@5 损失更直接。

- **直接选 α=1.0 (Pareto MRR 最强)**: 反过来,MRR 强 0.028 但 R@5
  输 0.020,把 reranker 整个白训。

## 后果

- ✅ MRR 从 reranker baseline 的 0.545 涨到 0.575 (+0.030),
  R@5 从 RRF baseline 的 0.601 涨到 0.621 (+0.020) ——
  **两个方向都比单 baseline 好**,只是不到双 Pareto。
- ✅ 延迟无 regression: p50 ≈ 47ms,跟纯 reranker (48.9ms) 在噪声范围内。
  混合本身只多两次 numpy.std + 一次乘加,~0.1ms。
- ✅ §3.4 拒绝层与混合层正交,各取所需。
- ⚠️ **n=42 偏薄**: 9 个 α 中 5 个的 R@5 落在 {0.601, 0.608, 0.621, 0.636} 这 4 个值上 ——
  细粒度差异在 1/38 ≈ 0.026 的步进上失真,locked α=0.4 vs 0.3 的差距 (MRR 0.575 vs 0.572)
  在统计意义上几乎是噪声。
- ⚠️ **complex 类别 R@5 跨 α 全部 0.25 (1/4)**,与 α 无关。说明 complex query
  的瓶颈不是排序而是召回 —— rerank_pool=20 内根本没召回到对的课。Week 8
  考虑加大 pool 或单独调 complex 路径。
- ❌ test_set v0.2 是合成 + 人工标注混合,不代表真实 NEU 学生 query 分布。
  Week 7 软启动后 query log 来,Week 8 §4 强制重扫。

## 触发重新评审的条件

- **test_set v0.3 ≥ 100 query 落地后 (Week 8 强制)**:
  按 PLAN v2.2 §4,Week 8 拿真实 query log 扩到 100 后必须重 sweep。
  本 ADR 当前数字带 "provisional" 标签,Week 8 后追加 supplement 注明
  α 是否飘移。
- **rerank_pool 调整**: 当前 pool=20。如果 Week 8 加大到 50 缓解 complex
  recall,α 最优点很可能漂移。
- **加新检索 leg** (e.g. multi-vector ColBERT-style, learnable α):
  二维 sweep 退化为多维,需要新决策框架。
- **真用户 latency p99 > 100ms**: 现在 reranker 是延迟主导项 (~50ms);
  如果生产 p99 飙升到 100+,可能要在 hot path 上 drop 部分 α 配置或改 fallback
  到 hybrid 直出。
