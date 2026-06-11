# ADR-0017: NAS 生产配置 rerank pool 20→10 + reranker int8 量化

## 状态

Accepted - 2026-06-11 (provisional, n=42 via live-API eval; test_set v0.3 ≥ 100 后复测 — 同 ADR-0015/0016 的既有 caveat)

## 背景

Week 10 NAS 部署后 `/search` p50 ~2.3s,瓶颈 100% 在 reranker:20 个
(query, doc) pair × seq 512 的 cross-encoder 前向跑在 Iris Xe 上。
README "还能再压"一节列了三个 lever 没拉;2026-06 optimization sprint
的文献调研给了其中两个直接依据:

- **Pool size**: [Drowning in Documents (ReNeuIR @ SIGIR 2025)](https://arxiv.org/abs/2411.11767)
  — cross-encoder 质量不随候选池单调上升,先到峰值后因噪声候选反降。
  top-20 → top-10 大概率质量无损、rerank 延迟减半。
- **int8**: 蒸馏/量化文献([arXiv:2507.08336](https://arxiv.org/pdf/2507.08336))
  + optimum-intel 的 NNCF int8 路径(`export_openvino.py --weight-format int8`
  钩子早已存在,从未启用)。

测量工具是本 sprint 新增的 `scripts/eval_via_api.py` — 直接打**部署中的**
API(PC over Tailscale → NAS),测的是含 alias tier / Layer 2 prefix /
拒绝层 / OpenVINO backend 的真实生产路径。此前 `run_eval.py` in-process
模式测不到这条路径(review 指出的 "eval path ≠ production path" 缺口)。

## 关键数据 (test_set v0.2 n=42, live API, 2026-06-11)

| 配置 | R@5 | MRR | p50 | p95 | api RSS |
|---|---:|---:|---:|---:|---:|
| pool 20 + fp16 (Week 10 现状) | 0.5285 | 0.5175 | 2019 ms | 2860 ms | ~4.9 GB |
| pool 10 + fp16 | 0.5285 | **0.5219** | 948 ms | 1356 ms | ~4.9 GB |
| **pool 10 + int8 (chosen)** | **0.5285** | 0.5175 | **849 ms** | **1167 ms** | **3.5 GB** |

- R@5 三配置**完全相同**;MRR 差异 ±0.004 在 n=42 噪声内
  (paired 检测在该样本量只能分辨 ≥0.10 量级差异,Urbano SIGIR'19)。
- matched_via 分布三配置一致:13 alias / 21 hybrid / 8 rejected。
- 8 rejected = 4 correct (q039-q042 adversarial) + 4 false
  (q013/q018/q022/q029) — 后者正是 ADR-0016 校准时已知并接受的 4/38
  trade-off(两分布在 [0.005, 0.03] sigmoid 区间重叠),**非新回归**。
- int8 拒绝层回归:gibberish → max_sigmoid 0.000 < 0.05,校准无漂移。
- 综合:**p50 -58%,p95 -59%,RAM -1.4GB,质量零损失**。

## 决策

1. NAS compose `RERANK_POOL_SIZE: "10"`(经由本 sprint 新增的
   `settings.rerank_pool_size`,代码默认仍为 ADR-0015 锁定的 20 —
   PC dev 路径不受影响)。
2. NAS compose `OPENVINO_MODEL_DIR: /data/openvino_int8`:
   - `openvino_int8/reranker/` — NNCF int8_asym per-channel (149/149 层),
     openvino_model.bin 1.1GB → 570MB。导出在 NAS 容器内跑
     (`docker run ... optimum-cli export openvino --weight-format int8`),
     PC venv 不碰(export 毒化 venv 的坑见 project memory / Week 10 记录)。
   - `openvino_int8/embedder` → 软链 `../openvino/embedder`(embedder 保持
     fp16;查询编码不是瓶颈,且 embedder 量化影响的是索引/查询一致性,
     收益不值得风险)。

## 后果

- `/search` 生产 p50 进入 <1s 区间;Streamlit 体感从"明显等待"变为"可接受"。
- 下一个量级的延迟改善需要架构换代(answerai-colbert-small late
  interaction,doc 端离线预计算),见 docs/optimization_2026_06.md §三。
- n=42 的统计警告继续有效:test_set v0.3 (≥100, 由真实 query log +
  UMBRELA 标注扩充) 落地后,本 ADR 与 0015/0016 一起复测。
- eval 基线文件:`eval/api_eval_pool20_fp16.json` /
  `api_eval_pool10_fp16.json` / `api_eval_pool10_int8.json`。
