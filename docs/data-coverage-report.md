# OPT-03 — 数据覆盖、冲突与来源报告

2026-10-08 本地实现；变更与测试结果记在 [开发修改记录](development-change-log.md) 第 17 节。只新增一个离线脚本 `scripts/audit_data_coverage.py`，API、界面、数据库和部署都不变。

这份报告回答「下一批到底补哪门课、哪个字段」：不只给课程总数，而是按院系、按字段列出缺什么、和目录冲突的是哪些、来源是什么，先修文档和培养方案按年度／范围统计。

## 运行

```bash
.venv/bin/python -B scripts/audit_data_coverage.py --db-copy /explicit/offline-copy.sqlite3
.venv/bin/python -B scripts/audit_data_coverage.py --db-copy /explicit/offline-copy.sqlite3 --details --max-codes 50
```

- 输入必须是**已经存在的独立离线副本**，旁边不能有 `-wal`／`-shm`／`-journal`。和 [发布预检](release-preflight.md) 一样：不要直接指向 NAS 或开发运行库；副本由获准操作者建立、确认不再被改写；**不要为了让检查通过去删 WAL／SHM**。不存在的路径不会被创建，UNC／device 路径、符号链接、`.env*` 在打开前就拒绝。
- 打开方式与发布预检相同：`mode=ro&immutable=1`、`query_only`、`trusted_schema=OFF`、一次 `BEGIN` 快照、60 秒／5 亿 VM 步的执行预算；开始前和结束后各算一次文件指纹，副本中途变了就整份不报。
- 报告是 stdout 上的一份 JSON。没有写文件的选项；重定向时也不要覆盖数据库或其他输入。
- 退出码：`0` 每一节都查了；`2` 报告已生成，但有的节没查（表不存在）或失败；`1` 没能读这个副本（参数错误、文件不存在、不是 SQLite 库、副本中途变了等），输出里只有固定的原因码。退出码 0 只说明报告完整，**不说明数据没有缺口**。

## 读什么、不读什么

脚本给连接装了 SQLite 授权回调：只有下面这些列能读，其余一律拒绝，包括 SQL 函数、写语句、`ATTACH`、`PRAGMA`，以及经由视图或触发器的读取。

| 表 | 列 |
|---|---|
| `sqlite_master` | `type`、`name` |
| `schema_versions` | `version` |
| `courses` | `course_id`、`primary_code`、`primary_name`、`status`、`generated_json` |
| `course_catalog_sources` | `course_id`、`snapshot` |
| `course_requisite_documents` | `course_id`、`catalog_year`、`document`、`content_hash` |
| `programs` | `program_id` |
| `program_plans` | `plan_id`、`program_id`、`campus`、`catalog_year`、`pathway`、`concentration`、`document`、`content_hash` |
| `program_required_courses` | `program_id`、`course_id` |
| `course_prerequisites` | `course_id`、`prereq_course_id` |

- 用户相关的表（`users`、`user_unlocks`、`user_courses`、`query_log`、`coop_experiences`、`coop_submissions`、`coop_contribution_credits`、`chat_answers`、`answer_feedback`）和 `course_aliases` 一概不读；`courses.raw_text`、`search_expansion`、`metadata` 也不读。
- 课程 JSON、目录快照、先修文档、培养方案的内容会被读进来做校验，但报告里只有计数。`--details` 另外列出课程代码、方案 ID 和方案范围（校区／年度／路径／方向／coverage／审核状态）；引文、描述、条款原文、审核人、备注都不输出。列不合格式（比如坏行的课程代码列）的值不列出，只计入 `unlisted_malformed`。
- 名字叫 `courses` 之类、但其实是视图的对象，按「表不存在」处理，不去读它。

## 报告结构

顶层：`format_version`、`complete`（每一节都 checked 时为 true）、`database`（`checked` 或 `failed` 加原因码）、`sections`、`limitations`、`rules_doc`，加 `--details` 时还有 `details`。

每一节都有 `status`：

- `checked`：查过了。计数是 0 就是「查了、没有这一类」。
- `not_checked`：没查，`code` 说明原因：`table_missing`（表不存在，或同名对象不是表）、`courses_not_checked`（依赖的课程一节没查成）、`database_unavailable`（副本没读成）。
- `failed`：查的时候失败，只给固定的原因码：`row_budget`（单表超过 20 万行，不截断）、`sqlite_budget`、`read_outside_allowlist`（副本的结构让查询碰到了允许范围以外的列）、`database_error`、`section_failed`。

每一节都写明分母（`denominator`），并在 `rules` 里给每个类别一句规则。同一分母下的类别互斥、相加等于分母；判断按表里的先后顺序，取第一个符合的。

## 各节

### courses

分母：`courses` 的全部行。依次判断：

| 类别 | 规则 |
|---|---|
| `oversize` | `generated_json` 超过 100 万字符，不解码 |
| `invalid_json` | 不是文本，或不是合法 JSON |
| `invalid_record` | 合法 JSON，但 `Course` 模型不接受（API 读它也会失败） |
| `identity_mismatch` | `course_id`、`primary_code`、`primary_name` 列和 JSON 里的不一致；排除在外，因为其他表按哪一个对应都说不清 |
| `synthetic` | 回答路径会标 `synthetic_record_not_real_course` 的合成记录；不算覆盖 |
| `in_scope` | 其余的行，是后面各节的分母 |

另外给出同一课程代码出现在多门在范围内课程里的组数和行数（不互斥）、`status` 列的分布、每个院系的课程数。

### catalog_snapshots

分母：在范围内的课程。`usable` 的条件和回答路径挂快照的条件相同（`CatalogSourceRepository.get_batch`）：恰好一行、`CatalogSnapshot` 模型接受、代码和标题与课程一致。其余是 `absent`、`duplicate_rows`（多行，一行都不用）、`oversize`、`invalid_json`、`invalid_record`、`identity_mismatch`（名称不一致，比如课程改了名而快照没跟上）。

快照行另有一个分母：没有对应课程的行（`orphan_rows`）、属于被排除课程的行。

可用快照里统计抓取日期：`retrieved_at` 为空就记 `retrieval_date_unknown`，**不拿导入时间或文件时间代替**；只有记录了抓取日期的才进 `retrieved_on` 的最早／最晚日期。现在的目录抓取器不记录抓取时间，所以旧数据这里应当全是 unknown。另外统计缺描述、缺学分、列了先修代码的快照数。

### fields

分母：在范围内的课程。对 `rag/answer_evidence.py` 的 `AVAILABILITY_FIELDS` 里每个字段，每门课归到一个类别：

| 类别 | 规则 |
|---|---|
| `catalog_only` | 课程记录没有值，可用快照有（学分、先修代码） |
| `catalog_conflict` | 课程记录的值和可用快照不同（学分；先修代码按集合比，快照没列而记录有也算） |
| `catalog_consistent` | 和可用快照相同（学分；先修代码集合） |
| `missing` | 没有值（`None` 或空列表；0 是值），快照也没有 |
| `extracted_estimate` | 有值，并且有这个字段的抽取证据：是抽取出来的估计，不是官方事实 |
| `course_sources_only` | 有值，没有这个字段的证据，但课程记录了来源 ID；这些 ID 不说明支撑哪个字段 |
| `no_recorded_source` | 有值，没有字段证据、没有来源 ID、也没和目录比过 |

先比目录（只有学分和先修代码，并且可用快照里有值时），再看字段证据，最后看来源 ID。`missing` 加 `catalog_only` 正好是回答路径 `missing_fields` 里的这个字段，学分的 `catalog_conflict` 正好是回答路径的 `catalog_metadata_conflict`，测试逐门课核对这两点。

另外给出：可用快照有没有描述（`catalog_description`），以及 `course_answer_evidence` 对这些课会给出的警告各有几门（`answer_warnings`）。目录快照一节没查成时，这三项都标 `not_checked`，因为那时目录相关的类别会全是 0，看起来像「查了、没冲突」。按院系的明细省略为 0 的类别。

「人工核对」只有培养方案有（见下面的 `source_checked`）；课程记录本身没有逐字段的人工核对标记，报告不替它编一个。

### requisite_documents

分母：`course_requisite_documents` 的全部行。`usable` 的条件和课程详情页相同（`CourseRequisiteRepository._decode`）：文档模型接受（包括语法树和记录的条款一致），课程 ID／年度和所在行一致，代码和标题和课程一致，内容 hash 一致。其余依次是：`orphan_rows`、`rows_for_courses_out_of_scope`、`duplicate_rows`、`oversize`、`invalid_json`、`invalid_record`、`row_identity_mismatch`、`course_identity_mismatch`、`content_hash_mismatch`。

按年度统计：可用和不可用的行数、覆盖了几门在范围内的课；先修／同修条款的 `parsed`／`unparsed`／`not_listed`（`not_listed` 不等于没有要求）；描述证据状态（没采集的记 `not_captured`）；目录学时和课程学分的比较（固定整数学时才比，范围和小数不比）；采集日期的最早／最晚。

另外：有可用文档的在范围内课程数，以及**有旧先修代码列表、却没有任何年度可用文档**的课程数。后者的回答只能依赖代码列表，是 OPT-04 的输入。

### program_plans

分母：`program_plans` 的全部行。`usable`：方案模型接受、方案 ID 和范围与所在行一致、内容 hash 一致，并且没有别的可用行占着同一个范围或方案 ID（有就都算 `duplicate_scope_or_id`，不挑一个）。`programs` 表存在时，`program_id` 不在其中的行是 `orphan_rows`。

可用方案统计 `partial`／`complete`、`draft`／`source_checked`、有没有来源指纹、采集日期范围；按项目和年度给出同样的计数。`programs` 小节给出：有完整方案的项目数、只有 partial 方案的项目数、没有可用方案的项目数。

- **partial 不计作完整**。`complete` 的方案按模型规则必须是 `source_checked` 且没有未建模的规则。
- `source_checked` 只表示有人记录了把文档和采集的页面对照过，**不等于官方正确，也不等于当前适用**；hash 一致也只说明内容没被改过。

### legacy_rows

`program_required_courses` 和 `course_prerequisites` 只计行数、指向被排除或不存在课程的行数、按项目的行数（只用 `programs` 表里有的 ID）、有旧先修边的课程数。这些是旧的种子数据，不是核实过的规则或先修逻辑。

### schema

列出上面这些数据表在不在（按名字、类型必须是 table），以及 `schema_versions` 里 1.0–1.7 哪些有、哪些缺，其他版本行只计数。

## 明细（--details）

每个缺口类别最多列 `--max-codes` 项（默认 25，范围 1–500），排好序，`omitted` 是没列出的数量。包括：坏的课程行、重复代码、每个快照类别、每个字段的 `missing`／`catalog_only`／`catalog_conflict`、不可用和未解析的先修文档、学时冲突、只有旧先修列表的课程、不可用的方案、可用方案的范围、没有可用方案的项目。没查成的节不出明细。

## 不能证明什么

`limitations` 固定列出：

- 离线副本是否一致、是否是对的那份，脚本证明不了；
- 目录 URL 与 hash 的检查不证明存档真实，也不证明正在开课；
- `source_checked` 是有人对照过采集内容，不是官方正确或当前适用；
- 抽取的估计不是官方事实；
- 课程级的来源 ID 不说明支撑哪个字段；
- 未知的抓取日期保持未知；
- 旧种子行不是核实过的规则；
- 没读查询热度，所以不给富化优先级。

## 不在本批

- 用真实查询热度挑 RMP 富化对象：要读 `query_log`，需要另行授权，并先区分评测流量、去噪。本脚本不读查询，也不给优先级。
- 不修任何数据，不重新抓目录，不核对来源存档（存档核对见发布预检的 `--plan-file`／`--policy-bundle`）。
- 不在线上库上跑；对生产数据做一份报告，需要用户先建好离线副本并同意。
