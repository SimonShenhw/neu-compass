# Co-op 私有收集与人工审核

本地开发版本，自 2026-09-30 第三批开始；尚未部署生产。

## 状态与权限

`pending → approved → published`，或 `pending → rejected`。

- `POST /coop` 需要已存在用户的签名会话，HTTP 201 / `accepted=true` **只表示私有收集**。返回 `status`、`duplicate`、`contribution_credited` 和服务端 `contribution_count`。
- 同一用户的同一 company/role/term 规范化键仅收集一条。NFKC、大小写与空白变体等价；重试不替换原内容。纠错需要联系审核员，而不是重复上传刷贡献。
- 审核批准必须提供完整脱敏替换 JSON、审核人和审计说明。批准后不足两个不同登录用户仍保持 approved，不公开、不记功。
- 同组已审核记录达到两个不同登录用户后，一次事务公开该组待发布记录，并按「用户 + 审核后的组键」最多奖励一次。多条原记录泛化到同组也不能多次记功。
- `GET /coop` 仅展示策展种子和当前仍满足门槛的 published UGC，再按原有贡献数执行字段解锁；pending/rejected/旧的未审核 UGC 都不展示。
- 种子不证明存在第二个真实贡献者，不用于凑人数；策展种子的隐私检查仍由策展人员负责。
- 删除账号会删除其队列与奖励账本条目；公开读取重新检查群组人数，剩余单条会隐藏。其他用户已获得的贡献数本批不追溯扣回。
- 同向重复审核是无操作；终态不能反向修改。已公开记录的撤回/改稿和拒绝后的申诉编辑入口不在本批实现范围内。

## 数据库升级（发布前必须做，不能覆盖运行库）

先备份**当前运行数据库**，并在其副本演练。以下路径只是示例，不是生产目标；命令默认只读。

```bash
.venv/bin/python scripts/migrate_coop_submissions.py --db-path /path/to/runtime-copy.db
.venv/bin/python scripts/migrate_coop_submissions.py --db-path /path/to/runtime-copy.db --commit
```

迁移只应用 `db/init.sql` 内标记的 v1.3 DDL，增加 `coop_submissions`、`coop_contribution_credits`、索引与版本记录。不替换旧表、不导入开发数据、不重算旧贡献数、不自动公开旧 UGC。已有数据库必须显式指定；拼错路径不会创建新库。迁移幂等，并以单一事务执行。

新 API 在缺少审核表时对 `/coop` 返回 503，不回退旧的未经审核公开路径。`/ready` 只表示检索栈已就绪，不能单独证明本次审核迁移完成；发布验收还需确认匿名 GET `/coop` 返回 200 与 JSON 数组。

## 本地运维审核

此命令使用主机/数据库文件访问权限，不新增公网管理员接口，也不把“审核人字符串”当成已验证的登录身份。仅可信运维人员可运行。

```bash
# 只列 ID 和审核状态，不打印公司、经历正文或贡献者 ID
.venv/bin/python scripts/review_coop.py --db-path /path/to/runtime-copy.db --list

# 显式查看原始待审内容：可能包含 PII，不粘贴到公共日志或聊天
.venv/bin/python scripts/review_coop.py --db-path /path/to/runtime-copy.db --show coop-EXAMPLE

# 默认只读 dry-run；真正批准需加 --commit
.venv/bin/python scripts/review_coop.py --db-path /path/to/runtime-copy.db \
  --approve coop-EXAMPLE --redacted-file /private/redacted-upload.json \
  --reviewer curator --audit "Removed identifiers; reviewed salary bucket"

# 拒绝同样默认 dry-run；确认后才加 --commit
.venv/bin/python scripts/review_coop.py --db-path /path/to/runtime-copy.db \
  --reject coop-EXAMPLE --reviewer curator --audit "Needs further redaction"
```

脱敏文件遵循 `CoopUploadRequest` 完整替换语义，例如：

```json
{
  "company": "Generalized employer bucket",
  "role": "Software Engineer",
  "coop_term": "Summer 2025",
  "interview_summary": "Two interview rounds",
  "salary_range_usd": "$30-35/hr"
}
```

未提供的可选字段会变成空值，不保留原字段；不能指定 contributor、is_seed_data 或 visibility_level。审核后以替换内容重新计算组键和内容分层。服务端不会自动判断自由文本是否真正脱敏、薪资是否合理分桶，审核人必须核查。

## 隐私与剩余限制

- 两个登录账号不保证是两个自然人；多人一致填写相同三元组也不代表自由文本已匿名。此门槛不是隐私充分证明。
- 私有队列仅表示不经公开 API 返回，**没有额外静态加密**。数据库、WAL、备份、脱敏临时文件和 `--show` 输出都需要私有权限与保留/清理策略；本批未新增自动保留期限或清理任务。
- 应用提交日志只记录内部 ID、状态和重试标志，不记录公司、岗位、学期或自由文本；普通审核错误也不回显原始校验输入。
- 旧 UGC 保存在原表供后续人工处理，本批不会删除、自动审核、自动迁移或退还历史贡献数。上线前要检查其数量和处置方案。
- 脚本不代替真实 OAuth、浏览器提交流程与生产副本演练；这些仍需部署前验证。
