# ADR-0018: 校准拒绝门控(logistic gate)替代裸 sigmoid 阈值

## 状态

Accepted - 2026-06-11 (生产启用 REJECTION_MODE=calibrated;系数随 embedder/reranker/corpus 变更需重跑校准)

## 背景

ADR-0016 的门控是 `max(reranker sigmoid) < 0.05`。它自己的校准数据就揭示了
该设计的信息上限:**可答**的理论术语 query(q018 "VC dimension PAC learning",
max σ=0.0051)分数低于**不可答**的假课程号(q040 "CS 0001",σ=0.0278)——
两个分布在 [0.005, 0.03] 区间完全交叠,任何标量阈值都无法分离。
live-API 实测(ADR-0017 eval)确认生产路径误拒 4/38 真 query
(q013/q018/q022/q029),是 R@5 0.529 vs in-process 0.62 差距的主因。

解法不是调阈值,是**补信息**。cross-encoder 低估精确术语匹配,但它脚下的
两条检索 leg 不会:q013 "graph algorithms BFS DFS" 对正确课程的 BM25 分数
实测 19.89;反过来 "CS 0001" 长得像课程号、却已经在 alias 层 miss(否则
根本到不了门控)、且无词法证据。

## 设计 (rag/rejection.py)

    P(answerable) = sigmoid( b + w1·logit(max_sigmoid) + w2·log1p(bm25_top)
                              + w3·vec_top + w4·code_pattern_miss )

- `bm25_top` / `vec_top` 来自 `HybridRetriever.last_diagnostics`(新增,
  per-request 实例属性,RRF 融合刻意抹掉的原始分数量级在这里保留)
- `code_pattern_miss`:query 含 `[A-Za-z]{2,5}\s?\d{4,5}` 形状 token 且
  到达了 hybrid 路径(= alias 已 miss)→ 大概率不存在的课程号。
  日历词("fall 2025")白名单排除
- 经 `rerank_blend_with_rejection` 的 `gate_fn` 钩子注入;`gate_fn=None`
  时保持 ADR-0016 行为逐字节不变。`REJECTION_MODE=threshold|calibrated`
  选择,代码默认 threshold,NAS compose 显式开 calibrated
- /chat 的 prefix-narrowed 不拒规则不变(两种 gate 都不跑)

## 校准 (scripts/calibrate_rejection.py, NAS 生产栈 int8+GPU+pool10)

- 数据:50 条可答(从 catalog raw_text 合成:课名式 + 术语 token 式,
  后者模拟 q018 类难正例)+ 40 条不可答(8 个 UAEval4RAG 式类别:
  假课程号/外校课程/校务/乱码/闲聊/作业管理/完全离域/不可能请求)。
  **eval/test_set.json 全程留出**,q039-q042 不进训练
- 拟合:纯 numpy 逻辑回归(镜像里没有 sklearn 依赖),标准化后拟合、
  系数折回原始空间
- 结果:**AUC 0.9795**(纯 max-sigmoid 基线 0.9605);系数方向全部符合
  设计预期(证据为正,code_miss 为负):

      bias=-4.4408, w_logit_sigmoid=0.5844, w_log1p_bm25=1.5115,
      w_vec_top=4.3305, w_code_miss=-4.5121

## 工作点:REJECT_BELOW = 0.3(非 0.5 中点,有意)

决策规则:**校准集零误拒约束下最大化不可答捕获** → 网格解出 0.3
(false-rej 0/50 / caught 31/40;0.5 处为 1/50 / 36/40)。产品不对称性:
拒掉真学生 query 的代价 > 给不可答 query 返回弱结果(chat_v2 grounding
prompt 仍会回答"目录里没有")。

Live 特征探针(held-out 边界样本)实测的概率分布:

| query | 性质 | p_answerable |
|---|---|---:|
| AAI 9999 (q039) | adversarial | 0.000 (code_miss) |
| CS 0001 (q040) | adversarial | 0.000 (code_miss) |
| 乱码 (q041) | adversarial | 0.011 |
| homework admin (q042) | adversarial | **0.246** |
| VC dimension PAC (q018) | 可答 | **0.201** |
| graph algorithms BFS (q013) | 可答 | 0.373 |

剩余不可分割重叠 = q042 (0.246) vs q018 (0.201) 一对;0.3 落在
q042 与 q013 的间隙中。q018 是已知残留误拒,记录在案。

## Held-out 实测 (test_set v0.2 n=42, live API, eval/api_eval_pool10_int8_calibrated.json)

| 指标 | ADR-0017 基线 | +校准门控 | Δ |
|---|---:|---:|---:|
| R@5 | 0.5285 | **0.5680** | **+7.5%** |
| MRR | 0.5175 | **0.5439** | **+5.1%** |
| 误拒 (真 query) | 4/38 | **1/38** | -75% |
| adversarial 捕获 | 4/4 | 4/4 | 持平 |
| p50 / p95 | 849/1167 ms | 882/1166 ms | 持平(门控纯算术) |

恢复的 query:q013 (R@5 0.5)、q022 (R@5 1.0)、q029(放行但检索仍错,
属检索质量问题非门控问题——比直接拒掉好)。

## 后果

- 已知残留:q018 类"纯理论术语 + 低 cross-encoder 分"仍误拒。下一步
  靠 eval set 扩容(UMBRELA 标注真实 query log)后重拟合,或给术语类
  query 加 HyDE 扩写再检索
- 重拟合触发条件:换 embedder / reranker / 量化精度、corpus 大改、
  test_set v0.3 落地。跑 `scripts/calibrate_rejection.py` 一条命令
- threshold 模式保留为后备:`REJECTION_MODE=threshold` 一键回滚到
  ADR-0016 行为
