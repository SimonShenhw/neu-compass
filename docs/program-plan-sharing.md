# 06A — 版本化培养方案分享

实现日期：2026-10-02。本地功能，尚未提交或部署；修改历史与测试结果统一记录在 [开发修改记录](development-change-log.md)。这是公共内容定位契约，**不是学生个人 Plan of Study、适用年度、获批路径或选课资格证明**。

## 生产链接

培养方案详情的分享框使用 `app.deep_links.share_url`：

- 当前明确选定且 `review_status=source_checked` 的 `ProgramPlan`：分享其精确身份、完整范围和内容 revision。
- 尚未选定、清空选择或选定 draft：只分享 `?program=<program_id>` 家族入口，接收方仍须明确选择版本。
- 原有课程链接、program 家族 ID／无歧义前缀链接保留兼容。完整方案链接不接受前缀、别名或与 `course` 混用。

分享地址来自现有 `PUBLIC_BASE_URL`；不使用 OAuth redirect URI，不将 session token、OAuth state、个人记录或原 HTML 放入 URL。选择、返回列表和刷新不重写地址栏；分享框独立生产当前选择的链接。

## 完整链接契约 v1

以下八个参数必须**各出现一次**，即使重复值相同也拒绝。合计值长度最多 2048 个字符。任何保留的 plan 参数出现都进入完整链接校验，不把缺字段的链接当家族入口。

| URL 参数 | 内容／约束 |
|---|---|
| `plan_v` | 固定字符串 `1`；其他版本拒绝，不猜测兼容 |
| `program` | 确切小写 `program_id`，如 `cs-ms`；不是 `CS` 前缀 |
| `plan` | 确切 `plan_id`；同 scope 的另一个 ID 不可替代 |
| `campus` | 明确的小写校区标识，如 `boston` |
| `catalog_year` | 连续学年的目录版次，如 `2026-2027`；不是 Spring／Fall 入学学期 |
| `pathway` | `standard`、`align` 或 `bridge`；不能缺省或由家族推断 |
| `concentration` | 非空 URL 值，承载一个 JSON 字符串或字面量 `null`；见下文 |
| `plan_revision` | 当前策展文档 `content_hash` 的 64 位小写 SHA-256 |

`concentration` 使用显式 nullable JSON，而不是易被 query reader 丢弃的空值：

- 共同／未限定范围：`concentration=null` → Python `None`。
- 名为 `general` 的范围：`concentration=%22general%22` → 字符串 `general`。
- 字面名为 `null` 的范围：`concentration=%22null%22` → 字符串 `null`，**不等于**未限定范围。
- Unicode 标签同样经 JSON 字符串与 URL 编码往返；不把 `none` 等名字解释成空值。

裸标签、空字符串、数组／对象、超长或仅空白标签拒绝；不递归解码嵌套输入。不去空白或大小写归一化以猜测其他 scope。URL 参数经过宿主 query reader 解码后再校验，不能重复手工 unquote。

revision 是策展 JSON 的语义内容摘要，不是原网页 hash、签名或权限凭证；链接可由任何人构造，必须与当前 API 返回的文档重新核对。现有存储没有承诺保留每个历史 revision，因此过期链接不提供旧版重建，也不静默打开新版。

## 消费与失败关闭

主入口在 OAuth callback 处理之后、sidebar 导航 widget 之前调用 `apply_deep_link`。完整链接的处理顺序为：

1. 清旧的项目／方案选择与 pending 目标，先路由到 Programs；不把旧选择留作成功显示。
2. 校验八字段唯一性、格式与目的地。任何 `course` 参数都与完整方案冲突，包括空值；固定警告不回显任意 URL 内容。
3. 清除**目标家族**的 curriculum 缓存，再用既有客户端读取 `GET /programs/{program_id}`。不从旧 UI 缓存、前缀第一项、最新年度或旧 seed 回退；无 `/search`、`/chat` 或模型调用。
4. 对实际响应中的文档重新校验：家族与 schema 可用标识正确，最多 100 份；重复 ID／scope、坏文档或混入其他家族使自动定位失败。只接受确切 ID、五字段 scope、内容 hash 与来源对照状态一致的文档。
5. 成功后保存待选择的公共目标。方案 selectbox **实例化之前**，按本次实际输入再核对一次，才设定该 ID；变更或歧义则清空，不显示上一方案的规则或政策。

| 情况 | 行为 |
|---|---|
| 缺字段、重复、非法格式、与课程目的地冲突 | 固定提示、无方案选择；参数校验阶段不发 API 请求 |
| 确切 ID 缺失 | `missing`；不选另一个同范围文档 |
| scope 或 revision 不同 | `stale`；不打开新版，需人工重新选择 |
| 当前文档未对照 | `draft`；不按链接自动选择 |
| 坏 JSON、重复身份／范围、混入其他家族或格式错误 | `unusable`；不保留旧目标的成功缓存 |
| 无方案 schema／非暂时性 API 错误 | `unavailable`；不回到旧 seed 猜测 |
| HTTP 408／429／5xx，包括客户端映射的暂时网络失败 | 清空旧选择并提示；下次 rerun 重试，不标记为已消费 |

terminal 结果记录当前公共参数 token；相同链接的普通 rerun 不再强制导航或选回。更换完整链接后会重新校验，哪怕会话已访问过 legacy 链接。token 只覆盖有界公共方案字段与 `course` 是否存在，不保存任意 URL／OAuth state／token。

清空方案、返回家族列表或点击“刷新方案及政策证据”不重新套用同一个已消费目标；刷新只清当前家族的缓存／选择。下一次生成分享框时，未选方案就退为**明确标注的家族分享**，不是失败链接解析时的隐式替代。与目标无关的家族缓存保留。

## 边界与验收

- 精确链接只是一次明确的**内容选择**，不是个人适用性确认；当前七份样本仍 `partial`，未升级 complete。政策是否 ready 继续由已有只读 reader 独立核对，分享成功不保证政策私有输入已准备好。
- OAuth 功能未修改。原 callback 在处理 OAuth 返回时可能清 URL；本批未实现跨完整登录回调的方案目的地恢复，未用真实 Google 账号验证登录／刷新。匿名打开公共分享内容与个人登录验收分开。
- 无数据库表／迁移／seed／hash 算法改动，无生产查询日志、个人课程、索引或模型写入；测试只使用临时库与隔离 HTTP／UI fixture。
- `tests/test_program_plan_links.py` 覆盖七份真实本地样本往返、严格参数、当前响应与缓存失败关闭、API 临时恢复、同会话换链接、六个 Streamlit AppTest 组件流程，以及主入口调用顺序。
- AppTest 是真实 Streamlit 组件的**无头测试**，不是外部浏览器、线上端到端或真实 OAuth 验收。最终全套结果与 JUnit 路径见主修改日志；生产恢复、数据库副本演练、联合部署及人工登录仍须单独确认。

下一开发入口为 06B：反馈与实际回答／查询关联，真实用户与合成测试分离；不为制造 organic 数据调用生产接口或发送分发消息。
