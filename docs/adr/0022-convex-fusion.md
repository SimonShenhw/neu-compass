# ADR-0022: 凸组合融合替代 RRF + α 在 v0.3 重确认

## 状态

Accepted - 2026-06-11 (生产 FUSION_MODE=convex / FUSION_WEIGHT=0.7;
回滚 = 改回 rrf,代码默认仍为 rrf)

## 背景

ADR-0001 时代选了 RRF(免归一化、稳健),但 Bruch et al.(TOIS 2023,
arXiv:2210.11934)系统性证明:调参后的归一化分数凸组合在域内外都优于
RRF — rank-only 视角丢掉了"自信的稠密命中 vs 勉强入池的噪声"这一
分数量级信息。同时 ADR-0015 的 α=0.4 锁定在 n=42 上,欠一次 v0.3 重扫。

## 设计

`rag/hybrid.convex_combination`:每查询对两条 leg 各自 min-max 归一化
(池内),fused = w·norm(vec) + (1-w)·norm(bm25);单 leg 缺席记 0,
退化池(单元素/全等)归一为 1.0。`FUSION_MODE` / `FUSION_WEIGHT` env
可配,代码默认 rrf(零行为变化,NAS compose 显式切换)。

## Sweep (NAS 容器离线,61 条 fusion 敏感查询 = v0.3 去除 alias 直达与
adversarial;pair 级 sigmoid 缓存,6 配置 × 3α 一遍模型)

| 配置 | R@5 | MRR |
|---|---:|---:|
| RRF 最优 (α=0.4) | 0.6735 | 0.5907 |
| convex w=0.5, α=0.4 | 0.6735 | 0.6189 |
| convex w=0.6, α=0.4 | 0.6817 | 0.6221 |
| **convex w=0.7, α=0.4 (chosen)** | **0.6899** | **0.6317** |

整个 convex w≥0.4 平台在 MRR 上全面压过 RRF(+0.03~0.04)— 方向与
Bruch 一致且跨配置稳定,虽然单点差异仍在 n=61 噪声边缘。
**α=0.4 重扫后依然最优** — ADR-0015 的 v0.3 复核义务完成,无需改动。

## Live 验证 (test_set v0.3 n=104, eval/api_eval_v03_convex.json)

| 指标 | RRF(ADR-0020 终态) | convex w=0.7 |
|---|---:|---:|
| R@5 | 0.7781 | **0.7889** |
| MRR | 0.7232 | **0.7449** |
| boundary(中文) | 0.917 | **1.000** (12/12) |
| medium | 0.644 | 0.661 |
| complex | 0.700 | 0.675(噪声内) |
| 误拒 / adversarial | 0/92 · 10/12 | 0/92 · 10/12(持平) |
| p50 / p95 | 846/1170 ms | 844/1171 ms |

门控无需重校准:门控特征(bm25_top/vec_top)是 leg 原始分数,与融合
方式无关;blend 的 z-score 归一化对融合分数同样适用。

## 后果

- 一天内第四次验证了"测量基建先行"的回报:sweep 30 行配置循环 +
  eval_via_api 终验,全程数据驱动
- fusion_weight=0.7 与 ADR-0015 的 α=0.4 是两个独立旋钮(融合层 vs
  rerank blend 层),命名上注意区分
- 复扫触发条件:换 embedder / corpus 大改 / test_set v0.4 落地(与
  ADR-0017/0018 同一组触发器)
