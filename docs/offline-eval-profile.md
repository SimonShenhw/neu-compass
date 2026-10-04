# 07A — 离线评测契约与分阶段计时

本批验证的是“标签和指标是否可比较、计时是否完整且不重复相加”，不是提高召回的实验、线上 SLA 或 v0.5 真实用户分布评测。修改／失败／测试结果只记 [统一开发日志](development-change-log.md)。没有改模型、pool、融合权重、拒答门或已被实测否决的 512→256；也没有跑 static-shape 编译或付费调用。

## 指标与输入契约

`eval.run_eval` 在调用 search_fn 前检查全部 query ID／文本／显式标签；缺标签不再默认为负例，重复 ID／标签、非法 k／返回值失败，不去重坏排名后悄悄放行。直接 metric helper 的重复标签按集合计数，不能出现 >1 的覆盖率。search_fn 异常仍中止，不能把错误当空列表／正确拒答或移出分母。

| 字段 | 定义与分母 |
|---|---|
| `recall_at_5` | 历史兼容字段：实际返回列表前 5 的 unique hits / min(unique labels, 5)，不是标准 recall 或 R-precision；无正例仍保留旧 0 默认 |
| `capped_recall_at_k` | 相同 capped coverage，但用报告明确的 k；无正例为 null |
| `standard_recall_at_k` | unique hits@k / 全部标签数量；8 个相关项命中 5 个为 5/8，不通过改分母声称 100% 标准召回 |
| `mrr` | 首个相关项在完整返回列表中的倒数排名，维持既有语义；不是截断 MRR@k |
| 负例统计 | 显式空标签单独统计 negative_queries／correct_rejections／false_positives／rejection_accuracy；不混入正例召回分母 |

k≠5 时新 canonical 字段与文字使用实际 k，旧字段仍只计算返回列表的前 5；不能把 k=10 的得分写进旧 @5 字段。比较必须固定标签、k 和返回深度，不将不同配置的旧字段直接拼成趋势。既有 dashboard 的旧列仍读取兼容字段，应按历史 capped 指标解释；不是新标准召回的图表。

历史 JSON 和测试集没改写。当前默认 `eval/test_set.json` 是 v0.2／42 条（38 正、4 负），v0.4 文件另有 116 条；默认文件不等于最新测试集，也不等于真实分布。新 schema 的严格校验适用于复跑；历史异常输入／分位数结果不自动修正。有效、标签唯一且 k=5 的历史 metric 语义保持。

## 可运行基线与单变量矩阵

新增 `scripts/profile_offline_search.py`，只能选静态 `--trace`，没有 DB／来源／模型／URL／out／k 参数。它读取项目 schema，在**内存**建 3 门明确合成课程与 3 维 FAISS 索引；真实 aliases／SQLite 筛选、BM25、RRF、回填、融合拒答执行，嵌入／重排为确定替身。5 个用例：alias、semantic、multi-label、filtered、negative。与完整 API 的区别包括缺 Layer 2 自适应抽取／calibrated gate／HyDE／HTTP、真实文本／模型与硬件；不能称完整生产路径。

| Run ID | 唯一变量 | 值 | 固定配置 | 预期／验收 |
|---|---|---|---|---|
| fixture-off | 采集阶段计时 | false | 同一 3 门合成课程／确定向量／RRF 60／blend .4／threshold .05／k5；1 次全组 warmup、3 次全组测量；无随机抽样 | 15 个测量调用、5 个 warmup，无阶段数据；排名／指标与 on 相同 |
| fixture-on | 采集阶段计时 | true | 同上，代码、顺序与替身不变 | 同样 15 次；覆盖真实组件、缺失阶段计数明确、独占耗时不重叠、质量不变；不要求时间必须更快 |

可在项目根目录或使用脚本绝对路径执行：

```bash
.venv/bin/python -B scripts/profile_offline_search.py
.venv/bin/python -B scripts/profile_offline_search.py --trace
```

库级 `profile_eval(test_set, search_fn, **config)` 的 JSON 配置 stub 与既有 JSON 评测文件风格一致（不是 CLI 自动加载配置；固定 CLI 只开放 trace）：

```json
{"k": 5, "warmup": 1, "iterations": 3, "trace": false}
```

两条 stdout JSON，不写／覆盖报告。CPU／FAISS／BM25 使用本机已有依赖，无 GPU 工作、无模型下载、0 外部 API 调用／费用；内存库／索引随进程结束释放，不持久化语料。预计短时本地运行，实际耗时依机器／库启动而变；不是长实验。为实际配置估算 GPU／付费成本需另给目标与授权，本轮不借矩阵自动开跑。

这是后续复跑矩阵，不称预注册；本轮已按测试先行验证机制。验收是固定不变量与语义，不对微秒级时间设 pass 阈值。正常／失败输出无查询、课程 ID、路径／hash、原文、账号、SQL 或 traceback；未知参数值不回显。`synthetic_only=true`、`production_performance_verified=false`、`quality_improvement_verified=false`、`release_approved=false`。

退出 0 只表示固定测量完整执行，不是质量阈值通过／生产放行；golden fixture 的质量、样本数和排名不变量由回归测试断言。退出 1 是执行失败，2 是参数错误。分析先运行 off 基线，再运行 on，只核同一固定配置；没有 GPU 并行／checkpoint 或恢复任务。

## 计时与分析计划

`rag.profiling` 用 ContextVar 为每个测量样本开独立采集器；正常调用默认没有采集器，decorator 不读时钟／不创建样本，context stage 仍有很小包装开销，**不宣称零开销**。不使用共享 last_timing 字段，不记录输入，不持久化／打印，不改 API 请求／响应、prompt 或日志字段。同步 TestClient→API worker 的继承场景有测试；并行／异步／background workload 不属于本 harness 的性能契约。

阶段白名单包括 alias_resolution、sqlite_filter、embedding、vector_search、vector_retrieval、vector_hydrate、bm25_search、hybrid_filter、fusion、hybrid_hydrate、candidate_texts、rerank_score。部分阶段仅在调用方包裹时可见；CLI 的 candidate_texts 包裹自己的批量 SQL，API 的该批量 SQL／prefix 抽取／门控／救援等仍可能在未计时部分，不能标成“已单独测量”。

- 每条采集 inclusive（包含子阶段）与 exclusive（扣掉直接子阶段）。例如 vector_retrieval 包含 embedding／vector_search，汇总总成本用 exclusive；两个 SQL 过滤调用不合并成假“一次”。整数纳秒先做总账，避免浮点相减出现负 residual；外层 wall 小于累计独占阶段或时钟非法失败，不 clamp 成假零。
- `eval.profile_eval` 在 warmup 前冻结标签，串行 warmup 完整用例，失败就中止；warmup 不进统计。测量每轮重新算质量、明确 ranking_stable，排名不同不只展示第一次。任何失败中止，不生成成功报告或丢掉失败样本。
- 阶段不存在时用 samples_absent 计数，只对实际出现的样本算分位数；不把 alias 的 embedding／rerank 补零。uninstrumented = wall − 独占总账，是未包裹逻辑／包装／时钟等残余，不是网络延迟或自动发现的某个瓶颈。
- 新分位数统一 nearest-rank，索引 max(0, ceil(n×p)−1)，p0 最小值／p1 最大值；空样本 null，拒绝负值／NaN／Infinity。三份既有脚本改用同一函数，未来报告标 method，不重算历史文件。少量样本 p95／p99 往往等于最大值。
- 本轮分析先核两变体质量／结果等同，再核组件覆盖／exclusive 账目／样本数量。wall 与阶段 p50／p95／p99 可供机械检查，但分位数不能相加；重复同一用例不是独立用户样本，不做显著性／置信区间／速度提升结论，不从替身时长挑生产优化赢家。

`profile_eval` 是 caller-supplied adapter 的库：适配器可能有 I/O／写日志／模型调用，不能把库名“offline”当沙箱。只有新增固定 fixture CLI 有独立进程证据：阻断 config／api／app／dotenv／真实模型库、`.env`、网络／外部进程、所有磁盘写打开，SQLite 只允许内存。普通 pytest 与真实 API companion 会导入现有配置，不混为零配置 CLI。

旧 live probes 在 07A 只统一分位数；07B 已用 MockTransport／临时 TestClient 修正 eval 标签、`--rerank` 实际接线、warmup／失败／缺 latency 与就绪验证，见 [live-capable 工具契约](live-probe-contract.md)。**没有实际执行现场 probe**；这些工具本身并非离线沙箱，不得据此制造 organic、擅改 NAS、启用保存或重复尝试已否决的 512→256。
