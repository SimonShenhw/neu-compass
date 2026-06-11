# ADR-0019: HyDE rescue pass — 门控拒绝后的 LLM 二审 + 检索重试

## 状态

Accepted - 2026-06-11 (生产启用 HYDE_RESCUE=true;与 ADR-0018 v4 门控配套)

## 背景

ADR-0018 v4 门控把误拒降到 2/92,但残留的两条是证据门控在原理上够不到的:

- q018 "VC dimension PAC learning theory" — cross-encoder 对"纯术语 query ×
  正确课程描述"打 0.005([Match Your Words, ECIR'22](https://arxiv.org/abs/2112.05662):
  神经 ranker 对训练中罕见的术语系统性失灵)
- q093 "CRM 认知偏差 团队决策" — embedding 把 CRM 读成客户关系管理
  (实际是 Crisis Resource Management,缩写歧义)

文献同时警告 HyDE **不能全局应用**([Weller et al., EACL'24](https://arxiv.org/abs/2309.08541):
扩写伤害强检索器,只在弱信号区间有收益;[SIGIR'25](https://arxiv.org/abs/2505.12694) /
[Not All Queries Need Rewriting](https://arxiv.org/html/2603.13301) 同向)。
被门控拒绝的查询恰好就是那个弱信号区间 → **rescue 只在拒绝后触发**,
主路径 847ms p50 一毫秒不涨。

## 设计 (rag/hyde.py `rescue_expand` + api/routes/common.py `attempt_hyde_rescue`)

门控拒绝后:

1. **确定性守卫(不问 LLM)**:query 含课程号形状 token(`query_has_code_pattern`)
   → 直接维持拒绝。到达门控 = alias 层已 miss = 课不存在;live 实测
   Gemini 会把 "AAI 9999" 判成合理查询并编出描述,守卫堵住该回归
2. **一次 Gemini 调用做二审**(temperature=0,判定必须确定;0.3 时
   "time travel paradox engineering" 的判决在多次运行间翻转):
   - 判定不是找课查询(乱码/作业/校务/闲聊/虚构主题)→ 输出 REJECT,
     维持拒绝 — 垃圾查询拿不到第二次机会
   - 是 → 输出假设课程描述(英文,按上下文展开缩写 — 同时打 q093 的
     缩写歧义和中文查询的跨语言对齐)
3. **重检索**:`原query\n\n描述` 进 hybrid(HyDE prepend-original 模式,
   embedder 看到分布对齐的扩写,BM25 看到展开的词汇)
4. **重排序用原始 query**(不是 HyDE 文本)— 返回排序仍反映用户真实所问;
   rejection 关闭(LLM 判决已替代证据门控回答"可答性")
5. 任何失败(LLM 错误/空检索)降级回原拒绝,绝不 500

成本:仅 would-be-rejected 查询(v0.3 实测 ~12% 流量)付 1 次 Flash 调用
+ 1 次检索,该类查询延迟 3-9s(原来是立即返回"无匹配"— 用户拿到结果
比拿到拒绝值得等)。

## v0.3 held-out 实测 (live API, eval/api_eval_v03_hyde_rescue.json)

| 指标 (n=104) | v4 门控 | +rescue |
|---|---:|---:|
| R@5 | 0.7563 | **0.7618** |
| MRR | 0.7105 | **0.7214** |
| 误拒(92 可答) | 2 | **0** ✅ |
| adversarial 捕获 (12) | 11/12 | 11/12* |
| p50 / p95 | 847/1120 ms | 893/2942 ms(p95 含 rescue 的 LLM 调用) |

q018 被救回且 **top-1 即正确课程**(RR=1.0);q093 救回但检索仍未中
(缩写歧义要靠检索侧解,见下一步)——用户至少看到候选而非被拒。

*已知泄漏:q100 "UCLA CS 188 reinforcement learning" 持续返回 NEU 自己的
RL 课(记录为合理产品行为,非缺陷)。q104 "time travel" 在 prompt 加
现实性约束(虚构/投机主题例示)后稳定拒绝。

## 回滚

`HYDE_RESCUE=false` 即回到 ADR-0018 纯门控行为;`REJECTION_MODE=threshold`
再退一级回 ADR-0016。三层独立开关。

## 下一步(调研 agent 排序的 top 杠杆,本 ADR 不含)

1. 门控加特征:IDF 加权词面覆盖率 + reranker 分数分布(std/top-gap)
   ([TMLR'24 abstention](https://arxiv.org/pdf/2402.12997)) — 数小时,零运行时成本
2. **离线 Gemini 批处理:doc2query 扩展 + 中文双语字段**,用自有 int8
   reranker 过滤幻觉([Doc2Query--](https://arxiv.org/abs/2301.03266)) —
   一次性成本,同时打 medium 0.61 天花板和中文词法静默,预期最大收益
3. 语料缩写词表 + 多义 union 检索([GLADIS](https://arxiv.org/abs/2302.01860)) —
   确定性解 q093 类,query 时零 LLM
