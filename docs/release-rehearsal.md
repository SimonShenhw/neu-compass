# 隔离联合发布演练（06C-3）

`scripts/rehearse_release.py` 用**新建的自有临时目录**生成合成 v1.2 库与来源，串行运行已有 v1.3–v1.7 迁移／导入器。它不是生产迁移命令、备份恢复器或发布批准工具。

```bash
.venv/bin/python -B scripts/rehearse_release.py
```

只接受静态 `--help`；**没有 db／输入／workspace／commit／keep／out 参数**。不能把真实库或私有来源指给这个命令。JSON 仅写 stdout，临时目录结束清理，不持久化合成输入；重定向报告也需自行选择受控新文件，不覆盖用户文件。实际发布仍按 [联合清单](joint-release-acceptance.md) 和 [已有副本只读预检](release-preflight.md) 的授权／副本要求执行。

## 演练内容

起点是从当前 init.sql 的 v1.3 标记前部分创建的合成 v1.2 库，不是所有历史 DB 版本的迁移矩阵。保留合成用户、贡献数／Co-op／解锁、选课、两条 eval 查询、课程原富化字段／检索状态／扩展词、别名、旧专业课程关系和先修边。

| 层 | 实际调用的已有函数 | 成功与故障证据 |
|---|---|---|
| 1.3 私有 Co-op | migrate_coop_submissions.migrate | 只增队列／credit 表；版本写入触发失败后 DDL／版本回滚，旧 UGC 不动；不审核／公开／发奖励 |
| 1.4 目录来源 | sync_catalog_sources.sync_sources | 两条快照入库；版本失败与第一条已写、第二条失败分别回滚；不覆盖 Course JSON／富化／索引状态 |
| 1.5 培养方案 | sync_program_plans.sync_plans | 两份 partial 文档入库；两类失败分别回滚；不升级旧 guessed seed，不改 coverage |
| 1.6 课程条件 | sync_course_requisites.sync_requisites | 两份文档入库，OR／共修及未入课程表的引用保留，一处 unparsed 不变成规则；两类失败分别回滚 |
| 1.7 回答反馈 | migrate_answer_feedback.migrate | 表／版本可加；版本失败与 post-DDL schema 自检失败回滚；不假装 schema 本身已开启运营保存 |

总计 **22 个演练检查**：生成、五层 dry-run、九个故障点、五次分层提交、内容解码、仓库投票、全层重放、结束预检、输入／旧状态一致性和自有目录清理。成功顺序与检查名固定；失败停止后续步骤，后续保留 not_checked，不能漏跑也称绿。

每个故障只发生在当前阶段前状态的**新 SQLite backup 副本**中。副本已有目标或悬空链接拒绝，不覆盖；guard／注入只落临时库，恢复方法在 finally／mock context 中复原。版本失败覆盖 DDL；三个来源的第二条失败明确确认第一条行与版本已在未提交事务中出现，再核对回滚后的完整逻辑状态。反馈 post-DDL 故障确认两表与版本已出现再失败。

这是**分层事务回滚**，不是整个 release 的一个事务。若 1.6 失败，先前已提交的 1.3–1.5 不应消失；生产恢复／代码回退／后续新用户行如何保留需另做真实副本与授权验收。临时测试目录清理不是生产数据删除／回退方案。

## 不只看计数

- 核对每层版本／表／实际记录和全部原 core 表、行、schema 定义的私有逻辑指纹；指纹／行／SQL 不出报告。原 query_log ID／eval 标记不被重新创建，课程富化与旧边不被改写。
- 用实际 repositories 解码目录、方案和课程条件，确认内容可读、partial／unparsed 与 OR／共修／未知引用未丢失。三个导入器的返回 stored=2 本身不够证明成功。
- 重放全部五层：stored／would_store=0、迁移 missing 空；另外用临时 Connection 子类统计五个实际连接的 total_changes，须全为 0，再核对完整逻辑状态／时间字段不变。即使 `UPDATE notes=notes` 没改逻辑值，也不能当成无 DML。
- 底层 receipt 投票验证同票重试无 DML、修正只留一条最新评价、原查询不追加且 eval 来源保留。此处是**仓库行为**，绕过 HTTP 运营开关仅用于合成测试，不是业务启用；CLI 不声称已验证关闭接口。
- 最后调用 06C-2 预检，核 schema／FK／合成方案归档，并确认 release_approved=false。政策输入在此演练 not_checked，索引／模型／实际运行数据也不检查。

## 关闭反馈的接口证据

`tests/test_release_rehearsal.py` 的 companion 场景使用五层迁移／导入完成的另一个临时库与**已有回答／评价**，进入实际 FastAPI routes。模型／向量和 streaming 明确替身，不访问 Gemini／真实账号／运行库。

四种运营 bool × 请求许可 bool 核对正常聊天、原 41／42 查询行不变、新查询保持 eval、新回答保存数 0／1；关闭期间既有回答／评价还在。既有 receipt 在关闭时改票返回 503／no-store、无 DML／token 回显，重新启用同一有效 receipt 可修正，仍仅一条评价。该测试不等于现场 API/UI 配置、用户告知、真实登录或浏览器 cookie 验收。

## 隔离与报告

CLI 不导入 Settings／config／api／app，不读 `.env`、调用外网／外部进程或发现生产路径。系统临时父目录显式传给 TemporaryDirectory，避免 stdlib 在自有目录建立前先创建可写探测文件；缓存父目录或 Windows TEMP／TMP、非 Windows TMPDIR／`/tmp` 必须是已有本地非链接目录，没有 cwd 回退。仅生成／修改／清理自己的随机新目录，不作为恶意并发下的通用文件系统沙箱。

专项的新解释器审计同时阻断配置导入／`.env`、socket connect／DNS／subprocess／system、自有目录之外的写打开，并检查 SQLite connect 只能落自有目录或 `:memory:`；外部 canary 文件不变。`-B` 不生成 bytecode。普通 pytest 已有全局 fixtures 会导入配置，不能把全套 pytest 称为不加载 `.env`；接口 companion 场景也不属于零配置 CLI。

合成页面使用 official-shaped URL 是为满足已有模型契约，**不是抓到的官网证据**；source_checked／checked_by 也是合成 fixture 标签，不核验真实 Plan of Study、policy 或招生适用年度。本批没有读取／重抓真实归档来替换这些 fixture，更没有导入运行库。

退出 **0** 仅本轮合成演练完整通过；退出 **1** 演练失败；退出 **2** 参数错误。固定状态／code／计数／布尔，无临时路径、私有逻辑 hash、账号、原文、capability token、SQL、未知参数值或异常细节；没有 traceback 或假通过证书。报告仍须受控保存，不自动公开。

`synthetic_only=true`、`production_backup_restore_verified=false`、`release_approved=false` 始终保留，九个人工门槛仍 pending。凭证风险处置、真实备份恢复、保留／访问责任、账号及部署／分发授权均未由演练解锁。具体代码修改和测试结果只记入 [统一开发日志](development-change-log.md)。
