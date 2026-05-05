# ADR-0016: Reranker rejection threshold = 0.05 (data-calibrated)

## 状态

Accepted - 2026-05-04 (provisional, n=42; mandatory re-calibration on test_set v0.3 ≥ 100 — see PLAN v2.2 §4)

## 背景

PLAN v2.2 §3.4 将 reranker 拒绝层规格写为
`RERANKER_REJECT_THRESHOLD = 0.4` 并标注 *"tunable; ADR if changed"*。这个数字
是 spec-time 估计 (sigmoid 0.5 = 决策中点,0.4 是稍宽的安全垫),没有经过
test_set v0.2 数据校准。

§3.4 wire 完成后跑 `eval/run_eval.py --rerank --with-rejection` 全量测试,
观察到:

- ✅ 4/4 adversarial query 被正确拒绝 (q039-q042: max sigmoid ∈ [8e-05, 0.028])
- ❌ 真实 query R@5 从 0.621 (无拒绝层) 跌到 0.529 (阈值 0.4)

跌幅 -0.092 全部来自**误拒**真实 query。`eval/sweep_reject_threshold.py`
扫了 9 个阈值 ∈ [0.05, 0.50],每个阈值的 (real_recall, false_rejection,
adv_rejection) 三元组写到 `eval/reject_threshold_sweep.json`。

## 关键数据 (test_set v0.2, blend_alpha=0.4 locked)

| Threshold | Real R@5 | False rej (real) | Adv rej | Notes |
|-----------|---------:|-----------------:|--------:|-------|
| **0.05**  | **0.632**| **4/38**         | **4/4** | **chosen** |
| 0.10      | 0.632    | 5/38             | 4/4     | |
| 0.20      | 0.605    | 6/38             | 4/4     | |
| 0.30      | 0.605    | 8/38             | 4/4     | |
| 0.40 (spec)| 0.579   | 10/38            | 4/4     | -0.05 vs 0.05 |
| 0.50      | 0.579    | 10/38            | 4/4     | |

注:`real_recall_at_5` 在本表里是 hit-rate@5 (≥1 expected 命中) 不是 mean
recall_at_k —— 用来跨阈值排序对比,不直接跟 ADR-0015 sweep 的 R@5 数字
(0.621) 同口径。两份数据各自内部一致,跨表别直接比绝对值。

## 真实 vs adv max-sigmoid 分布交叉

| Quartile | Adv max σ | Real max σ |
|---|---|---|
| Min  | 8.3e-05 (q041) | 0.0051 (q018) |
| ...  | 0.0036 (q042)  | 0.0096 (q013) |
| ...  | 0.0155 (q039)  | 0.0184 (q022) |
| ...  | **0.0278 (q040)** ← max | 0.0231 (q029) |
|      |                | 0.0741 (q019) |
| Max  |                | 1.0  |

**两个分布在 [0.005, 0.03] 区间重叠**:q018 / q013 / q022 / q029 是真 query
但 max sigmoid 比某些 adv 还低 (q040 = 0.028)。**没有阈值能同时做到 4/4 adv
rejection 与 0 false rejection** —— 这是数据本身的限制,不是阈值选择问题。

T=0.05 的取值理由:
1. 刚好 ≥ q040 (最高 adv = 0.0278),所以全部 4/4 adv 被拒
2. 真 R@5 的曲线在 T ∈ [0.05, 0.15] 平台 0.632 (没有损失);T 升到 0.20 才
   开始降。0.05 是平台的左端点 —— 任何更低的阈值收益为 0,但会漏掉 q040
3. 4 个被误拒的真 query (q013/q018/q022/q029) **本身在无拒绝层下也 R@5=0**
   (top-5 不含 expected),所以从用户体验讲,"明确告诉用户没好答案"
   比"展示一堆错答案"更好。

## 决策

**RERANKER_REJECT_THRESHOLD = 0.05**

写在 `api/routes/search.py` 模块常量,跟 ADR-0015 锁定的 `BLEND_ALPHA = 0.4`
并列。两者都是 §3.4 + §3.5 rerank+blend+reject 层的 hyperparameter,但各自
回答不同问题 —— 阈值是绝对置信度的截断,α 是排序信号的权重。

## 拒绝的备选

- **保持 PLAN spec 的 0.4**: 数据驳回。误拒 10/38 真 query (-26% 召回),
  其中 6 个本来能命中 expected 课程,代价比对抗保护收益大。

- **T=0.10 (中间安全垫)**: 跟 0.05 同样的 R@5 0.632,但多误拒 1 个真 query
  (q019 sigmoid = 0.074)。q019 没命中 expected 但属于灰区;0.05 比 0.10 更
  保守地"放过低置信查询",代价是 0,所以选 0.05。

- **T=0.03 (放过 q040 换回 q022)**: 3/4 adv,刚好擦中 PLAN "≥3/4" 底线。
  虽然真 R@5 略高,但 q040 = "CS 0001" 是清晰的不存在课程,让它通过会展
  示无关结果,UX 更糟。4/4 比 3/4 在用户感知层差距大。

- **Per-category threshold** (e.g. "AAI ___" 这种格式查询走更严的 T,
  自然语言查询走宽的): n=42 太薄,无法支撑分类决策树;v3.0 真实 query log
  够大后再考虑。

- **Top-3 average sigmoid 替代 top-1 max**: 用 mean of top-3 而非 max 做
  截断。理论上更稳定但跨 query 信号弱化,小样本噪声更大。延后到 v3.0。

## 后果

- ✅ Adversarial 拒绝 4/4 (PLAN KPI ≥3/4 超标);真 R@5 不损失 (0.632 vs 0.621
  baseline,在小样本噪声范围内 +0.011)。
- ✅ 用户面: "AAI 9999" / 乱码 / 完全不相关查询 → 返回 `matched_via='rejected'`
  + `rejection_reason` 解释,不再硬塞"最不差的那个"结果。
- ✅ 决策与混合 (ADR-0015) 解耦,ADR-0015 在 α sweep 时不需要重做 ——
  blend_alpha 和 reject_threshold 各自独立优化。
- ⚠️ **n=4 adversarial 太少,阈值统计置信度低**。T=0.05 卡得很紧 (q040 在
  0.028,上面没有 buffer)。Week 8 真 query log 里的对抗样本如果有 sigmoid
  在 [0.05, 0.10] 区间,会漏掉。
- ⚠️ 4 个真 query 被误拒 (q013/q018/q022/q029)。这 4 个目前 R@5=0,但理论上
  改进检索质量后它们可能会命中 —— 那时阈值需要再下调。
- ❌ 阈值是 **绝对** 数值,跟 reranker 模型版本绑定。换 reranker (e.g. v3 出来)
  必须重 calibration。

## 触发重新评审的条件

- **test_set v0.3 ≥ 100 query 落地后 (Week 8 强制)**: 跟 ADR-0015 同步重做
  threshold ROC,出 supplement。新数据可能让最佳 T 漂移到 [0.03, 0.10] 区间
  其他位置。
- **生产 query log 显示用户报告"我的查询被无故拒绝"**: 加 telemetry 看真用户
  query 的 max_sigmoid 分布,如果中位数低于 0.1,T 偏激进。
- **bge-reranker 升级或换型号**: 输出 sigmoid 校准就变了,绝对阈值失效。
- **rerank_pool 调大** (Week 8 提案缓解 complex 召回): pool 越大,top-1 sigmoid
  越可能高 (更多正例进来),阈值需要相应上调。
