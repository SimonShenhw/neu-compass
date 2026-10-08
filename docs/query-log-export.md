# OPT-01 — 查询日志的私有导出

2026-10-07 本地实现，10-08 按两路审查修正；变更与测试结果记在 [开发修改记录](development-change-log.md) 第 15 节。本工具不操作生产库、不迁移表、不导入评测集，也不发布用户原文。

旧版 `scripts/export_query_log.py` 有四个问题：

- 用普通连接打开库，路径写错会建出一个空库；
- `SELECT *` 导出全部列，含查询原文和原始 `user_id`；
- 默认写到 `eval/query_log_export.jsonl`，这个路径没有被 Git 忽略；
- 已有文件会被直接覆盖。

现在它和 [反馈候选导出](feedback-review-export.md) 遵守同一套规则，只读快照、写入和来源分类的代码共用 `scripts/private_export.py`。

## 默认行为与命令

必须指定**已有**的数据库，里面要有原来的 `query_log` 表：真正的 INTEGER 主键 `log_id`，以及导出用到的列。连接用 SQLite URI `mode=ro` 加 `query_only=ON`，统计和导出在同一个读事务里完成；不建库、不迁移、不写入。路径写错、给的是目录、路径里有 symlink 循环，或者表结构不对，都直接失败。库要放在本地磁盘上：`\\server\share` 这样的 UNC 路径打不开，先把副本复制到本地。

| 参数 | 输出 |
|---|---|
| 只有 `--db-path` | stdout 一行统计，不写文件 |
| 加 `--out 新文件.jsonl` | 元数据 JSONL：没有查询原文、拒答原因和原始来源标记 |
| 再加 `--include-private-text --ack-private-data` | 元数据加 `private_text`（查询原文和拒答原因） |

两个原文开关必须一起给，而且必须有 `--out`；只给一个、或者想把原文打到 stdout，都会失败。成功的 stdout 不含查询原文、来源标记、未知的模式字符串或输出路径。失败只打印固定的一行，不回显参数值或异常原文。

下面的路径是示例；本批只在合成的临时库上跑过，没有读真实用户数据：

```bash
# 从 /mnt/h/neu-compass 运行；默认只统计，unmarked 不等于真人。
.venv/bin/python scripts/export_query_log.py \
  --db-path /tmp/neu-compass-copy.sqlite3 --origin all

# 元数据文件；目录须已存在，工具不会 mkdir。
mkdir -p data/raw/query_log_review
.venv/bin/python scripts/export_query_log.py \
  --db-path /tmp/neu-compass-copy.sqlite3 --since 2026-10-01 --until 2026-10-08 \
  --out data/raw/query_log_review/metadata-2026-10-07.jsonl

# 原文：先确认访问控制、原文审查的授权和留存安排。目录同样要先建好。
mkdir -p -m 700 /tmp/neu-compass-private-review
.venv/bin/python scripts/export_query_log.py \
  --db-path /tmp/neu-compass-copy.sqlite3 \
  --include-private-text --ack-private-data \
  --out /tmp/neu-compass-private-review/query-log-2026-10-07.jsonl
```

WSL 重启时会清空 `/tmp`，上面两个 `/tmp` 下的文件只是临时的；要保留的话，换成另一个操作者控制的私有目录。

在容器里跑时，仓库目录是镜像里的 `/app`，镜像里没有 `data/raw/`。输出要写到操作者控制的目录；写进挂载的数据目录的话，它可能被同步或备份带走，要一起管。

## 统计

- `selected_row_count` 是本次选择（来源 + 时间窗口）的全部行数，**不受 `--limit` 限制**。
- `traffic_counts`、`route_counts`、`retrieval_mode_counts` 各自加起来都等于 `selected_row_count`，可以互相核对；只列出现过的取值。
- 统计只读 `log_id`、`created_at`、`route`、`matched_via`、`user_id` 五列，不读查询原文和拒答原因。
- 行数是请求数，不是人数，空结果也不能说明没有人用。
- 和反馈导出的区别：反馈导出的计数只覆盖本次选中、最多 `limit` 条的候选；这里的计数覆盖整个选择，`limit` 只限制写进文件的行数。

## 来源、窗口和一致性

- `--origin unmarked` 是默认：`user_id IS NULL`，只表示请求没带 `X-Eval-Run`，**不证明是真人**。`eval` 只匹配非空的 `eval:<run>`（区分大小写）；`eval:` 空值、空字符串和其他值都算 `unknown`，只有 `all` 会选进来。SQL 的选择和逐行分类用的是同一条规则，含 NUL 字符的标记也一致。
- `eval` 也只是自报的：任何客户端都能带 `X-Eval-Run` 头。要确认是自己跑的评测，用 `eval_run_sha256` 对照自己的评测名称。
- `--since YYYY-MM-DD` 含当天 UTC 00:00:00，`--until` 不含，都按 `query_log.created_at`；`--since` 不早于 `--until` 时直接失败。存储时间必须是 SQLite 的 UTC 秒级格式，输出成 `YYYY-MM-DDTHH:MM:SSZ`。
- 文件按 `log_id` 升序，最多 `--limit` 行（默认 200，范围 1–1000）；选择里还有更多时 `has_more=true`。没有游标，只能缩小时间窗口，而窗口按整天算：同一天、同一来源超过 1000 行时，后面的行导不出来。
- 被选中的行字段不对时，**整次失败，不跳过坏行**：
  - 统计阶段检查时间格式、route、来源标记和检索模式的类型；
  - 导出阶段另外检查查询原文（1–500 字）、结果 ID（JSON 数组，≤1000 个非空字符串，≤65536 字符）、k（空值或 1–50）、耗时（空值或有限的非负数）和拒答原因（空值或 1–1000 字）。
- 只验证本次选中的行：窗口外、来源不符，或排在 `limit` 之后的行不读这些字段，不保证全库完整。

## 文件契约

每行由 strict 的 `QueryLogExportRow`（`schemas/query_log_export.py`）校验，多一个字段也会失败。

| 字段 | 含义与限制 |
|---|---|
| format_version、log_id | 格式版本 1 与原行 ID，仅用于受控追溯 |
| created_at、route | UTC 秒级时间；search 或 chat |
| traffic_kind、eval_run_sha256 | 来源分类；只有 eval 组给完整标记的 SHA-256，不导出原始 `user_id` |
| retrieval_mode | 已知模式之一，否则固定为 unknown，不回显未知字符串 |
| k、latency_ms | 请求的 k 和检索耗时；耗时不是聊天总耗时 |
| result_course_ids | 当时返回的课程 ID，不是正确的课程集合 |
| query_sha256 | 查询原文的 SHA-256。短查询靠猜就能对上，不是匿名化 |
| review_state、ground_truth | 固定 pending／false |
| review_requirements | 固定带 privacy_review_required、results_not_ground_truth、no_retrieval_snapshot、missing_request_context（query_log 不记筛选条件）；chat 加 missing_history_content（不记对话历史）；非 eval 加 unverified_traffic_origin；未知模式加 unknown_retrieval_mode |
| private_text | 默认 null；两个开关都给才有 `query` 和 `rejection_reason`。原文可能含 PII 或用户输入的秘密 |

元数据文件仍有行 ID、内容哈希、时间和课程线索，**不是公开或匿名数据**。

## 写入边界

- 先验证要写的全部行、检查 32 MiB 的总预算（按 UTF-8 字节算），之后才创建文件。
- 只接受新的 `.jsonl` 文件（后缀不分大小写），拒绝已有文件、symlink／hardlink、数据库路径，以及不存在或不是目录的父目录。
- 仓库内只允许 `data/raw/query_log_review/`（Git 和 Docker 都忽略 `data/raw/`）。旧的默认路径 `eval/query_log_export.jsonl` 和反馈导出的目录都会被拒绝。
  - 判断「在不在仓库里」时，既看路径文字，也看文件身份：WSL 的 `/mnt/<盘符>` 不分大小写，换个大小写或用 Windows 短文件名写的仓库路径，文字不同，其实是同一个目录。
  - 父目录按输入的写法和解析后的位置各查一次，经 symlink 进出仓库都会被发现。
  - 仓库外的路径由操作者负责私有目录、备份和清理。
- 同目录的私有临时文件 `.query-log-review-*.tmp` 写完、fsync 后，用**不覆盖的 hard link** 发布；文件系统不支持 hard link 时直接失败，不会退回到覆盖式写入。
- POSIX 文件系统上权限是 0600。WSL 的 `/mnt/<盘符>`（比如上面示例里的 `/mnt/h/neu-compass`）通常不保存 POSIX 权限，实际由 Windows ACL 决定；Windows 和共享盘的 ACL 都要人工核实。
- 发布后临时文件删不掉时报告 `temporary_cleanup_incomplete=true`，written 仍是 true；异常终止也可能留下临时文件，要纳入清理检查。

## Git 忽略与留存

- `.gitignore` 加了 `eval/query_log_export.jsonl`。新工具不再写这里，这一条只防止旧版本留下的副本被误提交；本地如果有这个文件，先确认还要不要，再按留存规则处理。
- Git 忽略只管提交，不是访问控制、脱敏或留存：被忽略的文件照样留在磁盘、备份和同步盘里。query_log 本身的保留期和清理仍由运维负责，见 [PII 边界](pii_redaction.md)。
- 只读连接不会冻结正在写入的 WAL 文件；需要稳定副本时，先按现有备份流程准备一致的副本。
- 导出期间有写入方时：
  - WAL 模式（生产库是这个模式）：读到的是开始读时已经提交的内容，不会等写入方，也看不到它没提交的改动；
  - 回滚日志模式：写入方持有锁时，导出最多等 5 秒，然后失败；导出读着的时候，写入方要提交得等导出读完，等不及就会报 database is locked。
- WAL 模式的库即使只读打开，SQLite 也会在库文件旁边建 `-wal`／`-shm` 两个辅助文件，关闭后可能留下；库文件本身不变。两个导出工具都是这样。放在只读目录里、旁边又没有这两个文件的 WAL 副本读不了，导出会以固定的一行失败；把副本放在可写的目录里。
