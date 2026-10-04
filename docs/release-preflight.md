# 只读发布预检器（06C-2）

`scripts/release_preflight.py` 只检查**显式给出的稳定离线 SQLite 副本**和可选固定来源输入。不会读取 `.env`／导入 Settings、联网、调用部署脚本、迁移、导入来源、导出用户行、更新许可或批准发布。JSON 报告写 stdout；脚本没有写文件选项，操作者也不要把重定向输出覆盖数据库或输入。

本工具是 [联合发布清单](joint-release-acceptance.md) 的机器检查部分，不代替清单中的人工门槛。`release_approved` 始终 false；通过不代表已获得真实库／账号／部署操作权限。

## 输入和执行

不要直接指向 NAS／开发运行库。先由获准操作者建立、保管本地一致离线副本，确认它不再被应用／其他进程改写；UNC／device 路径在文件探测前就拒绝，不指向远程挂载目录。只复制活跃 WAL 库的主文件可能丢失事务；**不要为了让预检通过删除 WAL／SHM／journal**。备份与恢复方法、目标权限、一致性证据需要人工确认，本脚本不生成副本或做 checkpoint。

最小调用（示例路径必须替换为已确认的副本）：

```bash
.venv/bin/python -B scripts/release_preflight.py \
  --db-copy /explicit/offline-copy.sqlite3
```

完整检查本仓库明确选定的培养方案／政策输入：

```bash
.venv/bin/python -B scripts/release_preflight.py \
  --db-copy /explicit/offline-copy.sqlite3 \
  --plan-file data/program_plan_seed/boston_2026_2027_extended_rules.json \
  --plan-file data/program_plan_seed/boston_2026_2027_pathway_rules.json \
  --program-source-dir /explicit/frozen-program-archive \
  --policy-bundle data/program_policy_seed/boston_2026_2027_evidence.json \
  --policy-source-dir /explicit/frozen-policy-archive
```

两类归档目录均须已经存在并包含所选输入指纹对应的 `.html` 与 `.json` sidecar。不递归扫描目录、发现生产路径、默认加载私有 raw 或重新抓最新网页。可省略整个来源组，报告为 not_checked；只给组内一部分则失败。政策检查要求同一次调用的方案来源检查先通过，并要求每个选定方案都有精确政策 link。

方案适配器仅用于已开发的 **Boston／2026–2027** 固定范围及既有 CS／DS／INFO 路径；其他校区／年度／不支持的路径固定失败，不能把 Boston 页面改一个 scope 就借给 Seattle 或下一年度。扩展须另加来源与适配器核验，不自动推断。

`-B` 避免 Python 导入生成 bytecode 缓存；本地专项的独立进程还阻断了配置导入、`.env` 读取、网络／外部进程和磁盘写打开。普通 pytest 的已有全局 fixture 会导入 API/config，**不能把整套 pytest 宣称为不加载配置**。

## 检查结果的含义

| 检查 | 能证明的有限事实 | 不能证明 |
|---|---|---|
| database_copy | 已有普通文件、预算内、无旁文件／符号链接／junction／`.env*` 输入；不创建缺失库 | 是正确目标、获准副本、从完整一致备份得到 |
| database_integrity | `PRAGMA quick_check(1)` 返回 ok | 完整 integrity_check、业务数据／索引语义或恢复演练 |
| schema_contract | 当前 `db/init.sql` 所需 table／index／view／trigger 的定义匹配；CHECK／DEFAULT／FK／唯一约束也参与定义比较 | 数据内容齐全、生产版本正确、额外对象安全；通用 SQL 等价判断 |
| schema_versions | v1.0–v1.7 必需版本行存在 | 只凭版本号就可用；伪造最新版本不能掩盖缺表或约束漂移 |
| foreign_keys | 检查时未发现 FK violation | 应用写连接均启用 foreign_keys、JSON 文档／hash／用户规则都有效 |
| plan_sources | 选定文档通过既有固定页面身份／指纹／候选表核对，保留 partial 数量 | 全部课程／core／政策已建模、摘要语义正确、个人 POS 或毕业资格 |
| policy_sources | 选定片段位置／hash、方案内容 hash／精确范围、所属学院及每个选定方案的 link 通过既有核对 | 完整政策、个人适用性、所有历史／当前方案都覆盖 |
| input_stability | 受检文件前后私有指纹一致，结束仍无 DB 旁文件 | 期间任何瞬时修改都能检测、跨文件原子快照、未来仍不会变化 |

定义比较只忽略**未加引号部分**的大小写／空白／注释与 CREATE 的 IF NOT EXISTS；引号内字面量保留。语义等价但写法不同的 DDL 也可能失败，由人工评审，不自动修复。额外对象只报数量且明确未审查；不据此放行发布。

当前 schema 定义只在 `:memory:` 参考库执行，**不会在目标副本执行 init.sql**。目标用 `mode=ro&immutable=1`、query_only、trusted_schema=OFF、BEGIN 和 SQLite 执行预算读取；immutable 只适用于确实稳定且无旁文件的离线副本，不拿来绕过活跃库的锁／WAL。若副本意外改变，结果失败，不重试成 pass。

来源核对重用纯离线 audit 函数，不输出它们包含原文／段落／URL／方案身份的详细报告。归档有界 JSON 拒绝重复 key、NaN／Infinity、超预算、缺文件或链接输入；字节一致不等于来源真实，仍须持有人确认。

预算：DB ≤512 MiB；最多 10 个方案文件、总计 100 份方案，每文件 ≤1 MB；政策 bundle ≤300 KB；每份 HTML ≤2 MB、sidecar ≤16 KB；schema 对象 ≤1000、每定义 ≤128 KB；副本 SQLite 检查共用 10 秒／5000 万 VM 步预算。超预算固定失败，不自动扩大或截断为成功。大型有效副本需要另行评估，不在本批豁免。

## 报告、退出码与隐私

- `checks` 各自有 passed／failed／not_checked 与固定 code，只有有限计数／布尔 facts。没有 DB 路径／hash、用户行、账号、token／密钥、SQL 定义、来源原文、URL、方案 ID 或异常字符串。
- `manual_gates` 全部 pending：凭证风险处置、目标与权限、一致备份恢复、联合 API/UI 身份和实际配置、私有输入与模型／索引身份、留存／访问、真实账号、完整政策／个人 POS、分发授权。CLI 没有把这些标成 passed 的参数。
- `limitations` 保留“归档不证明已导入 DB”等缺口；未传的来源、课程先修归档、FAISS／ID map／模型／运行内容不检查。不统计 organic 或把反馈升级为真值。
- 退出 **0**：仅本次**请求的机器检查**通过，可能仍有 not_checked，所有人工门槛仍 pending，release_approved=false；不是 deploy-ready。
- 退出 **1**：至少一个机器检查失败或预检异常；退出 **2**：参数不合法。错误不回显未知参数／私有路径／异常详情，不打印 traceback。`--help` 只显示静态说明。
- 聚合计数和运行证据也不自动成为公开／匿名数据；受控保存报告，不上传或贴真实输入内容。密钥／配置显式 dump 仍不能公开；06C-1 的凭证轮换尚需持有人确认。

本批专项使用临时合成库和独立合成归档；另用临时空 schema 库联合核对现有固定输入，七份方案（均 partial）与十八页政策／七个精确 links 通过。该空库没有导入来源或真实用户行；不是运行库／真实备份副本验收，不证明生产输入齐全。具体修改与测试证据统一记在 [开发修改记录](development-change-log.md)。
