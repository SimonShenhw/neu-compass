# Live-capable 评测工具契约

这三份脚本**不是离线工具**，运行可能写实际 `query_log`、读取实际 DB／索引、下载并加载模型，甚至通过 HyDE 救援调用 Gemini。`X-Eval-Run` 仅分类流量，不是免写日志、免费或权限证明。07B 的验证全部用模拟 HTTP／内存库／替身模型，未执行现场 probe。

真正无外部调用的合成 smoke 入口见 [离线基线协议](offline-eval-profile.md)。本文件说明当前使用契约；历次修改与测试只记在 [统一修改日志](development-change-log.md)。

## 用例与样本分母

| 工具 | warmup 单位 | 正式测量计划 | 范围 |
|---|---|---|---|
| `scripts/eval_via_api.py` | `--warmup` 次第一条固定用例，默认 1；不再发送无标签的任意 “warmup query” | 用例集每条一次 | HTTP 固定标签质量＋耗时，不代表用户分布 |
| `scripts/probe_inference_latency.py` | 总序列前 `--warmup` 条，默认 3 | **`--n − --warmup`**；保留旧 n=总请求约定，默认 50−3=47 | 20 条 curated 序列循环，不带质量标签，也不自动切后端 |
| `scripts/probe_latency.py` | `--warmup` 次完整用例集，默认 3 轮 | `用例数 × --iterations`，默认 3 轮 | 真实本地 PyTorch／DB／索引＋TestClient，不含网络 round-trip |

三者 search 请求计划总数（warmup＋测量）最多 10,000，另外只有 1 次 `/ready`；串行、无自动重试、无并发或后台工作。warmup 可为 0，正式测量必须至少 1 条；HTTP k 为 1–50，查询非空且最长 500 字符。用例必须显式提供唯一 query_id、唯一 labels（负例是显式空列表），完整预检在任何模型／DB／HTTP／输出创建前执行。输入须 `.json`、≤4 MiB、合法有限 JSON；可选 version 是非空短字符串。默认用例仍 v0.2，未自动替换或改写历史标签。

所有 `/ready`、warmup、正式 `/search` 都逐次发送非空 `X-Eval-Run`。label 1–64 个 ASCII 字符，首字母或数字，后续只允许字母／数字／下划线／加号／连字符；不能含路径、空白或控制字符。实际路由把 search 标为 `eval:<label>`，不是 organic。失败请求可能还未到达记日志位置，因此“尝试数”不等于数据库行数。

远端 URL 只接受 http(s) **origin**（可含端口，不含路径、userinfo、query、fragment 或空白）；timeout 必须有限且 0 < 秒 ≤ 300。客户端关闭环境代理读取和自动 redirect，不向重定向目标转发评测 POST；需代理或 path-prefix 的现场另行明确设计，不回退到隐式环境配置。HTTP 客户端和 TestClient 都用 context manager 关闭。

## 就绪、失败和计时

就绪需要 HTTP 200、`status=ready`、两个实际整数正计数（courses_indexed／bm25_corpus）；503/ready 与 200/warming 均不能开始 warmup。响应必须是 HTTP 200、query／k 对应本次请求、合法 matched_via、显式 results 列表（≤k、无重复 ID）、完整 hit 字段及有限 score／非负有限 latency_ms。缺 latency 不补 0，缺 results 不当正确拒答；零耗时可是真实合法值，但布尔、字符串、NaN／Infinity 均不能作为数值。empty／rejected 必须无结果，alias／hybrid 必须有结果，hit 的 matched_via 与根字段一致。

任何 ready、warmup 或测量失败都立即中止；不重试、不跳过失败、不继续凑一组漂亮分位数。报告分别给 planned／attempted／completed 或 succeeded／failed／not_attempted，readiness 另计；不把未尝试称为 skipped 或成功。失败报告只含聚合计数和固定错误码，没有半套 per_query 质量报告。中途已成功样本的分位数可以保留，但 `measurement_status=aborted`，不能当完整 benchmark；样本范围始终写 `validated_measured_successes_only`。

server_latency_ms 来自验证后的服务响应；wall_latency_ms 用单调时钟计 POST 往返，**不包含后续客户端响应校验**。warmup 完全不进入正式统计；方法统一 nearest-rank，空样本 null，不凭插值或填零扩大分母。网络 probe 的 wall 与进程内 wall 不可直接混为一个指标，重复固定查询也不是独立用户样本。

`--rerank` 现在显式创建 CrossEncoderReranker、执行一次真实类型的模型预热并写 app.state.reranker；未传时明确设为 None，不能把降级路径叫完整 reranker 基线。此本地工具固定 PyTorch 构建，不是配置里 ONNX／OpenVINO／compile 的线上后端自动镜像。embedder／reranker 的初始化预热另于请求 warmup，不计 search 请求。`/ready` 不要求可选 reranker，但指定的 reranker 加载／预热失败会中止，不偷偷降级。

本地历史 p50 <300 ms 条件仅作为 `target_met` 报告：完整测量但未达阈值也退出 1；不是生产 SLA、质量提升或发布审批。返回 0 只表示所选测量完成（若有阈值也达标），质量是否好仍看独立指标；所有结果 `release_approved=false`、`production_performance_verified=false`。

## 输出和运行边界

- 退出码：0 完整；1 运行／就绪／样本失败或本地阈值未达；2 参数／输入／输出失败。未知参数不允许缩写，不回显输入值，脚本自己的异常结果仅固定 JSON 码，不打印异常文本／traceback、地址或路径。
- API eval 保留默认 `eval/api_eval_<label>.json` 和 `--out-json`，含 query、expected、retrieved 的私有明细；优先显式指定**已有受控目录中的新路径**，禁止把用户查询报告提交到 Git。这里只防覆写，不设置操作系统 ACL／留存期限，不审批数据访问。stdout 的脚本结果只输出聚合，不带明细／标签／URL／输出路径。
- inference 保留 `--out-dir` 和 `latency_probe_<label>.json`，但目录必须已经存在；不自动创建目录。旧 scalar n／server/client pXX 键仍在完整报告，n=成功的正式样本；新增完整分母字段。canonical 空分位数 null。旧 helper `_percentile([])` 的兼容 0 不用于新报告；历史文件／文字不重算。
- 目标在发请求／加载模型前用独占创建保留；已有文件、目录、symlink（含悬空）或父目录缺失均失败。不覆盖历史，不删除失败文件。执行失败写固定失败报告，下一次选新 label／路径。若磁盘写入／关闭失败可能留下空或不完整文件，返回 2；不要把它当有效 JSON，工具不会自动删它。
- 进程内 app／模型库仍可能输出自己的日志；聚合结果的去回显保护**不等于**消除运行库、服务器或第三方库日志中的查询／异常。运行前仍需核实访问／留存与费用权限。普通 pytest 会导入现有配置，独立拒绝入口的无 `.env`／网络证据不能概括为整套测试零配置。

本批没有实际 API 调用、运行库读取／迁移、NAS 或 `.env` 改动，也没有新的性能赢家结论。真实账号／凭证风险处置／备份留存／分发仍待本人确认；后续先做限流契约的本地设计与验证，再按明确目标与权限决定真实后端实验。不重复已否决的 512→256。
