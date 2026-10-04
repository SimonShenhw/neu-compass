# 06B — 回答与查询绑定的 👍／👎 反馈

2026-10-02 本地实现，2026-10-03 补默认关闭与请求许可；尚未提交、部署或迁移真实运行库。修改与测试历史统一记在 [开发修改记录](development-change-log.md)，本页说明当前契约与发布边界，不另起变更日志。

## 绑定什么

每次成功的 `/chat` 请求继续按原机制写一条 `query_log`。`log_query` 仅在该次 INSERT 与 commit 成功后返回准确 `log_id`，失败返回 None，不能用最大 ID、最近一条记录或客户端传来的行号猜测。

运营开关 `ANSWER_FEEDBACK_ENABLED` 默认 false；即使有 v1.7 表也不启用。`POST /chat` 的 `allow_feedback_capture` 默认 false、只接受 JSON bool；只有运营启用且该请求明确 true，再满足上游流**正常结束**、回答非空且不超过 64000 个字符、关联查询及新表可用，才将逐 token 拼接的完整回答保存到私有 `chat_answers`，并在最后一个 NDJSON `done` 事件附带凭证。记录包含原查询外键、回答原文／SHA-256、prompt version、请求的筛选／项目／上下文课程 ID、历史轮数及凭证过期时间；**不另存完整对话历史、OAuth token 或账号身份**。许可不进入 prompt／既有上下文白名单，也没有新增同意账本；它不是真人／身份／法律同意证明。上下文没有全部历史／当时检索索引快照，不是任意追问可独立重放的评测包。

原 `meta`／`token`／`error` 顺序和旧客户端消费方式保留；`done.feedback` 是可选扩展，示意为：

```json
{"type":"done","feedback":{"answer_id":"<32位小写hex>","answer_sha256":"<回答SHA-256>","feedback_token":"<43字符随机凭证>"}}
```

运营关闭／请求未允许、没有反馈表、查询日志失败、空回答、超长回答或上游异常时，仍以旧的 `{"type":"done"}` 收束，不因反馈存储失败改变原回答。许可／开关在流开始决定是否收集，并在完成前再核对；不能结束时才回溯开启收集。上游报错的部分文本仍可展示，但没有可评价目标。超长回答继续流式输出，只停止反馈捕获；空 token 不积累在缓冲中。

保存发生在发出完成事件**之前**，不是浏览器收到回答的确认协议。若网络恰在最后一段丢失，服务端可能已有完整行，但客户端未收到有效 done，就没有按钮／凭证；不能声称每个保存行都被真人完整阅读。当前 FastAPI 请求级连接在流结束后关闭，这一生命周期已用独立临时数据库及真实 dependency generator 检查。

## 凭证与提交

`POST /feedback` 的 body 必须且只允许四个字段：

| 字段 | 约束 |
|---|---|
| `answer_id` | 服务端完成回答的 32 位小写 hex ID |
| `answer_sha256` | 与服务端保存原文、UI 实际收到的回答一致的 64 位小写 hash |
| `feedback_token` | 32 个随机 bytes 生成的 43 字符 URL-safe capability；不能放 URL |
| `rating` | 严格 `up` 或 `down`，不接受 bool／数字／自由文本 |

客户端不能提交 `log_id`、`user_id`、query、来源标签或评论。原始随机 token 仅通过 no-store 完成响应交给当前 UI，数据库只存 SHA-256；比较使用 constant-time digest 检查。有效期为服务端签发后 **7 天**。凭证授权评价该回答，不是身份／真人证明；匿名访问也可评价，泄漏凭证的人同样能改这一个回答的评价，因此不能把凭证放分享地址、公开日志、导出或 Git。

运营关闭时 `POST /feedback` 固定 503/no-store，不使用既有 receipt 修改评价、不删除已有数据；启用后服务端核对确切 ID、回答 hash、存储原文一致性、token hash 与过期时间。未知目标、错误／串用／过期凭证或坏记录均返回固定 404；格式错误 422；schema／存储故障 503。成功返回 `{answer_id, rating}`，不回传查询、回答、账号或 token。`/chat` 与成功的 `/feedback` 都声明 `Cache-Control: no-store`。

`answer_feedback` 每个回答只有**一条当前评价**：相同重试不改行／时间，换成另一选项更新同一行。不是不同用户数量、投票总数或每次点击的事件账本；当前不提供撤回／中立选项，也不公开 aggregate 或原文读取接口。评价不是注册资格、课程事实正确性或标准答案；尤其不能把 👎 自动转成拒答门标签、正确课程 ID 或训练真值。

## UI 与旧历史

- `stream_assistant` 每轮先清旧凭证，对实际 token 文本计算 hash；只有 meta 后的正常 done 与严格 receipt 匹配才保留。中断、错误、旧 done、坏 receipt 或文本不匹配不会挪用上一轮目标。
- 加入消息历史及显示按钮前再次核对原文 hash，只给 assistant 消息绑定。旧历史、用户消息或后来改过的回答没有按钮；不会按邻近 user 消息猜查询 ID。
- 历史里的 👍／👎 仅在**显式点击**时调用接口。普通 rerun 不提交；已保存选项禁用，可点击另一项修改。只有响应身份／选项都与本次点击一致才标成功，错误／坏 JSON／另一目标响应保留原状态并给固定提示。
- 清空对话或登出同时移除消息与临时 receipt/meta/error；不会把此凭证放入 `_recent_history` 发给 LLM，也不改现有 OAuth 功能。

06C-1 在 chat_input 前始终告知提问原文仍写原查询日志；UI 本地启用时展示默认不勾选的会话保存选择，解释即使不投票也保存、TTL 不等于删除。每次请求明确传 bool；服务端仍独立核对。取消只停后续保存，清对话／登出也清 UI 勾选状态，不删除服务器数据；UI 关闭不显示投票控件，也不接受未允许请求的意外 receipt。API/UI 需成套发布／回退，不能为了旧 API 接受而删字段重试；详见 [联合发布验收准备](joint-release-acceptance.md)。

三项 Streamlit AppTest 检查实际无头组件点击／rerun／失败重试流程；另有隔离 FastAPI 流→消息→HTTP 客户端→反馈存储回路。它们不是外部浏览器、真实 Google 登录或 NAS 端到端验收。

## 来源分离与隐私

反馈通过外键关联**原查询**的来源，保留既有 `query_log.user_id` 约定：`eval:<X-Eval-Run>` 是评测标记，NULL 是未带该标记的访问。之后反馈请求没有 header 也不会把评测改为 organic；点击反馈不再调用 `/search`／`/chat`，也不新增 query_log 行。

NULL 只是“没有评测 header”，不是验证过的真实人类。脚本／演练必须设置 `X-Eval-Run`，真实分布与有用性仍需生产使用、去噪和人工审核；本轮没有读取生产 organic 数量。测试全在临时库、模型替身与隔离 HTTP 内执行，没有制造线上数据。

新的私有回答可能包含用户输入的个人信息或模型复述，`request_context` 的用户筛选值也可能有敏感内容。双门控启用且捕获成功时，没有投票的完整回答同样会被保存，不能只将已评价部分纳入隐私治理。**7 天只限制凭证有效期，不自动清除任何数据**。启用前须确认访问控制、最小留存／清理、前端告知和脱敏策略，含备份／导出治理；本批没有自动脱敏、purge、公开导出或个人删除接口，不宣称满足某个法律／学校制度。

删除 query_log 行会按外键级联删除关联回答与评价；删除回答也级联评价，防止孤立标签。这里只定义数据库关系并用临时库测试，没有执行真实删除。不得为了评测方便提交 raw query／answer、token 或可识别记录。

## v1.7 与显式副本演练

`db/init.sql` 增加独立的 `chat_answers`／`answer_feedback` 和 schema version 1.7；不改原 query_log 列、用户课程、课程／方案、索引或既有 migration。请求与 UI **不自动建表**：旧库聊天可继续，反馈明确不可用。

迁移入口 `scripts/migrate_answer_feedback.py` 必须传已有数据库，默认 `mode=ro`。只有显式 `--commit` 才在同一事务加表／版本；前置 telemetry schema 必须存在，已有不兼容列、主键、唯一查询或级联外键拒绝；失败回滚，不替换原库、不导入合成行、不生成拼错路径。

示例仅针对已备份且经人工确认的**数据库副本**；本批未对真实库或私有副本运行下面的写入命令：

```bash
# 在 /mnt/h/neu-compass 下；路径必须事先准备，不是生产库。
.venv/bin/python scripts/migrate_answer_feedback.py --db-path /tmp/neu-compass-feedback-rehearsal.sqlite3

# 仅在人工确认副本／报告／留存边界后执行。
.venv/bin/python scripts/migrate_answer_feedback.py --db-path /tmp/neu-compass-feedback-rehearsal.sqlite3 --commit
```

默认只读、commit 幂等、事务失败回滚、旧记录保留、缺路径失败和无 PYTHONPATH 的实际 CLI 都在临时库中验证。生产加表、联合 API/UI 发布、存储权限与回滚仍需单独确认。

06B-2 的 [离线反馈候选导出／样本审查](feedback-review-export.md) 已本地实现：默认 counts-only、已有库 mode=ro，显式写新文件仍默认元数据；原文需双开关确认，排除凭证并保留原来源与追问上下文缺口。输出固定 pending／非 ground truth，不自动接入评测，未使用真实数据。06C-1 的默认关闭、页面告知与 [联合发布／登录清单](joint-release-acceptance.md) 也已本地实现；下一段为只读预检器，真实生产／账号操作仍需单独确认。
