# 06B-2 — 离线反馈候选导出与审查入口

2026-10-03 本地实现；变更与测试结果统一记在 [开发修改记录](development-change-log.md)。本工具没有公开读取端点，不操作生产库、不迁移表、不导入评测集，也不发布用户原文。

只读快照、新文件发布、仓库内目录限制和来源分类的代码，2026-10-07 起与 [查询日志导出](query-log-export.md) 共用，在 `scripts/private_export.py`；本工具的行为没有变。

06C-1 的运营／请求双门控只控制后续在线保存／评价，关闭不会删除或禁止显式受控离线读取已有记录。本文的私有库／文件授权和人工隐私审查仍独立成立；旧记录不能凭 ID／日期推断曾勾选保存许可，新功能也没有独立同意审计账本。联合启用与回退边界见 [发布验收准备](joint-release-acceptance.md)。

## 默认行为与命令

`scripts/export_answer_feedback.py` 必须指定**已有**、具备 v1.7 反馈表和原 query_log 的数据库。连接使用 SQLite URI `mode=ro` 与 `query_only=ON`，在同一读事务中取快照；不建库、不 migration、不执行 DML。拼错路径或不兼容 schema 直接失败。只处理有当前评价的回答，不导出未投票回答；这不改变未投票回答本身的留存风险。

不传 `--out` 时，只在 stdout 输出候选数量、选定窗口内的来源／当前选项计数、limit、has_more 等报告。这里的数量是**本次选中并验证的记录数**，不是全部反馈或不同用户数量；即使空库也不能据此断言产品没有使用者。

下面路径是示例，必须由操作者先准备并确认副本／私有目录；本批只在合成临时库运行同类命令，没有读取真实用户数据：

```bash
# 从 /mnt/h/neu-compass 运行；默认 counts-only，未带 eval 标记不等于真人。
.venv/bin/python scripts/export_answer_feedback.py \
  --db-path /tmp/neu-compass-feedback-copy.sqlite3

# 显式新文件，仍只输出元数据；目录须已存在，不会自动 mkdir。
.venv/bin/python scripts/export_answer_feedback.py \
  --db-path /tmp/neu-compass-feedback-copy.sqlite3 \
  --since 2026-10-01 --until 2026-10-04 --limit 200 \
  --out data/raw/feedback_review/metadata-2026-10-03.jsonl

# 仅在确认访问控制、原文审查授权与留存策略后开启私有文本。
.venv/bin/python scripts/export_answer_feedback.py \
  --db-path /tmp/neu-compass-feedback-copy.sqlite3 --origin all \
  --include-private-text --ack-private-data \
  --out /tmp/neu-compass-private-review/candidates-2026-10-03.jsonl
```

原文开关和确认开关必须**一起**提供，且必须指定输出文件。任一孤立开关或把原文写 stdout 的请求都会失败。成功 stdout 不包含查询／回答、源行 ID、marker 或输出路径；CLI 格式／存储错误给固定提示，不回显异常原文、参数值或 Pydantic 输入。

## 来源、窗口和一致性

- `--origin unmarked` 是默认：原 `query_log.user_id IS NULL`，仅表示没有 `X-Eval-Run`，**不证明真人或 organic**。`eval` 仅匹配非空 `eval:<run>`；`eval:` 空值和其他 marker 是 `unknown`，只由 `all` 纳入。来源从原查询关联，不取反馈请求 header，也不重新运行 search／chat。
- 文件保留 `traffic_kind`，评测组仅提供完整 marker 的 SHA-256，不导出 raw user_id／run 名。哈希仍能跨样本关联，不能当匿名化证明。后续分组隔离评测流量，不能靠去掉 header 把合成记录变成真实样本。
- `--since YYYY-MM-DD` 包含当日 UTC 00:00:00，`--until` 不包含当日 UTC 00:00:00；两者按 **feedback.updated_at** 选择，覆盖评价修正而不是按查询日期筛选。存储时间必须是有效的 SQLite UTC 秒级时间，输出规范化成 `YYYY-MM-DDTHH:MM:SSZ`。
- `limit` 默认 200、范围 1–1000；按 updated_at、answer_id 稳定排序，多看一行设置 has_more。has_more 不代表已审核后续记录；当前没有游标／自动分页，需缩小时间窗口或显式调整 limit，不能把截断子集当全量覆盖。
- LEFT JOIN 检查实际关联；被选中行有孤立回答／查询、非 chat 来源、坏文本 hash、时间次序错误、非白名单上下文字段、重复 JSON key 或坏类型时，**整次失败，不跳过坏行制造“干净样本”**。只验证本次选中行，不保证筛选／limit 之外的全库完整性。
- 请求上下文仍遵守 06B 的 8192 字符上限；额外导出预算为结果 ID JSON ≤65536 字符／1000 项，整份候选 JSONL ≤32 MiB。超限需缩小选择，不截断文本、ID 或上下文。回答仍 ≤64000 字符、查询 ≤500 字符，不另给合法课程 ID 发明短长度限制。

## 文件契约与写入边界

每行由 strict `FeedbackCandidate` 校验。核心字段为：

| 字段 | 含义与限制 |
|---|---|
| format_version、answer_id、query_log_id | 格式版本 1 与原关联身份，仅用于受控追溯；不提供线上投票能力 |
| source_revision | 对本次规范化来源／内容 hash／prompt／当前评价／时间／上下文／检索模式信息的 SHA-256；元数据与原文两种导出得到相同指纹，相关来源变化则变化；不是签名或防篡改认证 |
| query_sha256、answer_sha256、request_context_sha256 | 精确查询／回答 hash 与规范化白名单上下文 hash；保存回答 hash 在导出时重验。原文模式再验三者，防止移植另一查询／回答 |
| rating | 每个回答的当前 up／down，不是事件数、身份数或正确性标签 |
| traffic_kind、eval_run_sha256 | 原来源分类及仅评测组的 hash；unknown 不以 raw marker 代替 |
| retrieval_mode、result_course_ids | 原检索模式及返回课程 ID，不是正确课程集合；未知模式固定 unknown 并提示人工审查，不回显未知字符串 |
| 四个 created／updated 时间 | UTC 秒级来源时间；修正评价保留 created，更新 updated |
| context_status、history_turn_count、context_course_count | 全部白名单键存在才 recorded，缺任意键是 missing；没有记录的计数为 null，**不是 0** |
| review_state、ground_truth、review_requirements | 固定 pending／false；保留隐私、主观反馈、无检索快照、缺上下文／历史、未验证来源等缺口，不接受 approved 或真值提升 |
| private_text | 默认 null；双开关才含原 query、answer 和白名单 request_context。**不含完整历史**；原文／筛选值本身可能有 PII 或用户输入的秘密 |

元数据不导出回答／查询／筛选原文、原 user_id、凭证 hash／token、OAuth／session 字段；SQL 也不 SELECT 凭证 hash、过期值或任意额外列。这里的元数据仍有来源 ID、内容 hash、时间与兴趣线索，**不是公开或匿名数据**。不给 raw 导出做自动脱敏保证；需要最小留存和受控访问。

所有选中行先验证并检查总预算，之后才创建输出。只允许新 `.jsonl` 文件，拒绝已有文件、symlink／hardlink、数据库路径和缺失父目录。仓库内只允许 `data/raw/feedback_review/`（Git／Docker 已忽略 data/raw）；仓库外明确路径由操作者负责私有目录与备份治理，gitignore 不保护外部文件。

采用同目录私有临时文件，写完／flush／fsync 后以**不覆盖的 hard link** 发布；竞争创建目标也失败，不暴露半写的最终文件。文件系统不支持 hard link 时失败，没有覆盖型 fallback。POSIX 新文件权限为 0600，Windows／共享盘 ACL 仍须人工核实，不宣称跨平台权限已验收。临时文件正常会清理；发布后清理失败时报告 `temporary_cleanup_incomplete=true` 且 written=true，不能误称没有输出；异常终止也可能遗留私有 `.feedback-review-*.tmp`，须纳入受控清理／备份检查。本工具不清理用户既有文件。

只读连接不等于对正在写入的生产 WAL 文件做物理冻结；需要稳定副本时先按现有备份流程准备一致副本，不给活库随意加 immutable 标记。

## 样本审查顺序

1. **隐私先行**：先看元数据／来源缺口，再决定是否获准打开私有原文；原文、PII、筛选值、capability 不进入 Git、公开 issue、聊天截图或模型日志。需要脱敏的样本先在受控位置处理，保留受控追溯记录，不用公开 hash 宣称匿名。
2. **来源与上下文**：记录 answer_id＋source_revision，确认原来源、prompt version 和时间。history_turn_count >0 或 null 表示缺历史内容；即使为 0 也缺当时索引／证据快照，不能直接声明全量可重放。缺条件的样本先 hold，不凭邻近 query 猜内容。
3. **区分主观与事实**：分别判断是否有用、课程／培养方案事实是否有官方依据、是否违反筛选、是否需要澄清／拒答。up 可以事实错，down 可以事实对；返回课程 ID 不自动成为 expected IDs，也不把 down 自动作为拒答门标签。
4. **独立候选与防泄漏**：需要成为 eval 样本时，另行审核题目、标准答案、来源版本、资格边界与标签理由；按相同 query／context、近重复、eval run、对话来源及 prompt version 规划分组，训练／调参／测试不能随机拆散同源内容。本导出没有全部对话身份或完整历史，不能承诺已完成分组去重。
5. **先审查后接入**：单独的受控审查记录仅引用 ID／revision、hold／exclude／需脱敏、缺口与理由，不粘贴原文。确需接入评测时再设计独立审批／标准答案文件；本批没有 review-state 写回、自动生成 ground truth、训练、v0.5、门控重校准或 RMP 富化。

空白审查条目可使用以下框架；这不是已审查实例，也不进入自动评测读取路径：

```text
answer_id / source_revision:
原来源与时间窗口:
隐私处置: hold / exclude / 私有脱敏后另审
上下文缺口与是否可独立提问:
主观有用性与事实正确性分别核查:
官方依据、版本与资格限制:
同源分组 / 重复风险:
需要谁确认、哪些条件仍缺:
```

反馈捕获／七天凭证与留存的区别见 [回答反馈说明](answer-feedback.md) 和 [PII 边界](pii_redaction.md)。生产启用、真实账号验证与分发仍需单独确认。
