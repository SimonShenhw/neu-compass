# ADR-0020: 词汇层 — doc2query 扩展 + 中文 BM25 通道 + 语料缩写词表

## 状态

Accepted - 2026-06-11 (生产启用;corpus 重抓取后需重跑生成→过滤→应用链)

## 背景

v0.3 eval 定位的两个结构性短板:**medium 类(语义改写)R@5 0.61** 是检索
真实前沿(用户词汇 ≠ 目录词汇);**中文查询 BM25 静默**(ASCII-only 分词,
bge-m3 论文自认 sparse 跨语言"几乎无用")。外加 q093 类缩写歧义(CRM =
Crisis Resource Management,embedding 读成客户关系管理)。

调研结论(完整 report 见 ADR-0019 §下一步):一次离线 Gemini 批处理同时
打三个问题,文档侧扩展是零 per-query 成本的永久修复。

## 设计(三件套 + 一条地基)

1. **CJK 二元分词**(地基):`rag/hybrid.tokenize` 对 CJK 连续段发射字符
   bigram(机器学习 → 机器/器学/学习),免 jieba 依赖。此前中文字符被
   静默丢弃。
2. **doc2query + 中文关键词字段**:`scripts/generate_doc_expansion.py`
   对全部 6,406 门课各生成 4 条学生式查询(禁止复用标题词)+ 2-3 条中文
   关键词 + 3-5 条主题词。`thinking_budget=0` + 6 并发:6 小时 → 25 分钟,
   成功率 6262/6270,成本 <$2。落 `courses.search_expansion` 列,
   **只进 BM25 文档,dense 嵌入刻意不动**(扩展只放大词法召回,不扰动
   向量 leg)。
3. **Doc2Query-- 过滤**:生成查询用生产 int8 reranker 对其源课程打分,
   σ<0.2 剪掉(NAS 容器内跑)。保留 8,226 / 剪掉 17,413(32% — reranker
   对 query-doc 对天生苛刻,ADR-0018 已证;关键词/中文词不过滤)。
4. **缩写词表**:同一批生成顺带挖掘缩写+语境义项,聚合为
   `data/acronym_glossary.json`(520 词条,60 个多义)。查询时
   `rag/acronyms.py` 对缩写形 token 追加**全部语料内义项**(union 检索,
   reranker 用上下文消歧);经 `HybridRetriever.query_expander` 只作用于
   检索 leg —— reranker 与拒绝门控仍看原始查询。

## 实测 (test_set v0.3 n=104, live API)

| 指标 | 前(ADR-0019 终态) | 后(本 ADR + 门控 v5) |
|---|---:|---:|
| R@5 | 0.7618 | **0.7781** |
| MRR | 0.7214 | 0.7232 |
| medium(语义改写) | 0.611 | **0.644** |
| complex | 0.650 | **0.700** |
| boundary(中文) | 0.833 | **0.917** |
| 误拒 | 0/92 | **0/92** |
| **q093(CRM 歧义)** | 救回但检索全错 | **R@5=1.0,top1 即正解** |
| p50 / p95 | 893/2942 ms | 846/1170 ms |

## 连锁反应与处置(写给未来改语料的人)

扩展字段**改变了 BM25 分数分布** → 门控 v4 系数失准:乱码 "keyboard
mash" 命中钢琴课扩展词获得词法证据,adversarial 泄漏 11/12 → 9/12。
这正是 ADR-0018 写明的"corpus 大改"重拟合触发条件。处置两步:

1. **门控 v5 重校准**(对扩展后语料):模型自己学到词法通胀 —
   w_log1p_bm25 0.96 → 0.78。修复了部分泄漏但 q041 仍漏 — 日志定位
   泄漏源不是门控(它正确拒绝,p≈0.02)而是 **ADR-0019 rescue 的 LLM
   二审**:temp=0 下 Gemini 对边界乱码的判决仍跨请求抖动。
2. **Borderline-only rescue**:rescue 仅对门控 p_answerable ∈
   [0.08, 0.4) 的"边缘拒绝"开放(`settings.rescue_min_probability`)。
   高置信拒绝(乱码 p≈0.02)不配花 LLM 二审 — 判决稳定性问题被绕开,
   p95 还从 2.9s 回落到 1.2s(省下了乱码上的 Gemini 调用)。

残留(记录为接受):q099 "Oxford PPE admissions requirements" 与 q100
"UCLA CS 188" 经灰区 rescue 放行,返回本校相关课程 — 对"问外校/外机构"
的用户展示本校等价物,产品上可辩护。adversarial 终态 10/12。

## 运维链(corpus 重抓取后重跑)

    PC : generate_doc_expansion.py --db-path ~/neu-compass-data/courses.db
    NAS: apply_doc_expansion.py filter  (容器内,int8 reranker)
    NAS: apply_doc_expansion.py apply --commit + compose restart api
    PC : apply_doc_expansion.py glossary --commit (+提交 glossary 进 repo)
    NAS: calibrate_rejection.py (门控重校准,锚点手算后 bake)
