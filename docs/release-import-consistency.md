# 入库后来源一致性只读核验（06C-4）

`scripts/verify_release_imports.py` 核对**显式选定输入与已有稳定离线 SQLite 副本**的内容。它补足 [结构／归档预检](release-preflight.md) 与 [合成迁移演练](release-rehearsal.md) 之间的缺口：schema、版本或入库计数正确，不代表给定副本存着相同的文档。

不是迁移、同步、修复、备份恢复、官网抓取或发布批准命令。真实副本仍需 [联合清单](joint-release-acceptance.md) 中的目标、访问与动作范围确认；本批仅使用自建合成输入测试，没有读取运行库或真实备份。

## 输入与调用

```bash
.venv/bin/python -B scripts/verify_release_imports.py \
  --db-copy /controlled/offline-copy.sqlite3 \
  --catalog-file /controlled/selected-catalog.jsonl
```

路径仅为占位符，不自动发现项目 DB、来源目录、环境变量配置或生产地址。至少选择一组：

| 组 | 参数 | 核对范围 |
|---|---|---|
| 目录快照 | 一个或多个 `--catalog-file` | 按现有导入器从 JSONL 重建快照；只对唯一 code＋精确 title 匹配的课程检查 DB 内容 |
| 培养方案 | 一个或多个 `--plan-file`，以及 `--program-source-dir` | 冻结 HTML／sidecar、已有候选表审计、选定 plan ID／scope／文档／摘要 |
| 课程条件 | `--requisite-manifest`、`--requisite-source-dir`，一个或多个 `--course-code` | 重用现有离线课程块解析器，重建课程／年度文档；核条件、描述证据、学时及来源身份 |

三组可以一起选；未提供组的来源与入库检查都为 `not_checked`，不靠未选组凑 pass。不完整组失败，来源失败时对应入库检查未执行；全部没选失败。只有完整 schema／版本／FK／完整性检查通过才比对 DB，不因一个坏库而自动迁移。政策片段目前没有独立入库比对契约，**不在本工具中检查**。

## 比对契约

- 重用现有规范化模型和摘要函数，但不调用迁移器或 repository 的 store／同步方法。直接读取选定行，防止 read wrapper 丢弃坏文档、打印私有 ID 后被当成“没有匹配”。
- 目录使用 `CatalogSourceRepository.snapshot` 重建预期身份及内容。匹配行必须存在，快照 ID 和语义字段都一致；不只信已有 snapshot ID。同一 code 的相同快照允许折叠，冲突失败。无唯一课程／标题不符按原导入器跳过，成功报告明确跳过计数；**全跳过失败，部分跳过也只证明 matching_records_only**，不证明整份归档都入库。该旧 JSONL 本来没有原 HTML 或捕获时间，不能补出真实性。
- 方案核实际 program 存在、选定 ID 的列 scope＝文档 scope＝来源 scope、实际文档摘要＝存储摘要，再核文档等于选定输入。重算过摘要的篡改仍失败。来源审计沿用目前 Boston／2026–2027 及既有路径适配器，不扩展到未支持年度／校区。`partial` 不升级。
- 课程条件按明确 course code＋精确 title 找唯一 course ID，查该 ID／年度的行；列身份、文档、存储摘要、从原 HTML 重建的预期内容都一致。OR、共修、未知引用、`unparsed`、描述证据和 hours 保留，不重建旧先修边，不推导个人资格。
- JSON 格式／key 顺序可以不同；严格拒绝重复 key、NaN／Infinity 和超限文档。目录比对排除 imported_at／retrieved_at，课程条件比对排除 imported_at，这与既有导入内容契约一致；**不是导入时间或真实性核验**。方案的审核／来源字段仍参与完整内容比对。
- 每个来源／入库组失败即停止该组，无部分成功计数可冒充整组 pass；其他独立组可以留下自己的结果。未选 DB 行、额外 schema 对象、用户行语义、政策完整性、个人 POS、班次、索引／模型不由此证明。

## 只读、预算与报告

复用 06C-2 的本地路径、非链接输入、大小、DB 旁文件与私有指纹保护；UNC／设备网络形式、`.env` 类文件、symlink／junction（含父路径）拒绝。`-wal`／`-shm`／`-journal` 存在即拒绝，不从活跃库自行取副本或忽略 WAL 后声称一致。

两个目标连接都为 `mode=ro&immutable=1`、query_only、trusted_schema OFF、显式只读事务；参考 DDL 仅在内存库执行。SQL 有十秒／五千万步预算，目标无 DDL／DML、零 total_changes，不创建 DB／旁文件／缓存／报告。受检文件检查前后核私有 hash，结束再核旁文件；不能证明跨文件原子一致性或抵御恶意并发瞬时变更，操作者必须提供稳定离线副本。

DB 上限 512 MiB；目录最多 20 文件、每个 5 MB、总共 10,000 非空记录、单记录／DB 文档 200 KB；方案最多 10 文件、每个 1 MB、总共 100 文档；课程 manifest 64 KB／20 页、选定课程最多 100，HTML 2 MB／sidecar 16 KB。未知格式失败，不自动修正或续抓。`-B` 禁止 Python bytecode 写入；普通 Python 的 import 缓存不是本工具的导出功能，但可用 `-B` 明确避免。

只输出 JSON 到 stdout：固定状态／code、有限计数／布尔、限制和 pending 人工门槛。没有路径、hash、原文、URL、账号、SQL、未知参数值、异常详情或 token。不接受 `--commit`／`--out`／简写参数；自行保存报告仍须选择受控新文件，聚合报告不自动匿名化或公开。

退出 **0** 仅表示本次选择的机器检查通过；**1** 检查失败；**2** 参数错误。`release_approved=false` 始终保留，九类人工门槛始终 pending，不能自动放行部署、保存、凭证轮换、真实账号或分发。独立进程测试禁止配置导入、`.env`、网络／外部进程、所有磁盘写打开，并限制 SQLite 只连接显式只读目标或内存；普通 pytest 全局 fixtures 的配置导入不等于 CLI 行为。

具体修改、RED／失败／最终测试证据仍只记入 [统一开发修改日志](development-change-log.md)。
