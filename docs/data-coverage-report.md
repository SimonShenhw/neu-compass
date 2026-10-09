# OPT-03 — 数据覆盖、冲突与来源报告

2026-10-08 本地实现，10-09 按两路审查修订；变更、审查与测试结果记在 [开发修改记录](development-change-log.md) 第 17 节。只新增一个离线脚本 `scripts/audit_data_coverage.py`，API、界面、数据库和部署都不变。

这份报告回答「下一批到底补哪门课、哪个字段」：不只给课程总数，而是按院系、按字段列出缺什么、和目录冲突的是哪些、来源是什么，先修文档和培养方案按年度／范围统计。

## 运行

```bash
.venv/bin/python -B scripts/audit_data_coverage.py --db-copy /explicit/offline-copy.sqlite3
.venv/bin/python -B scripts/audit_data_coverage.py --db-copy /explicit/offline-copy.sqlite3 --details --max-codes 50
```

- 输入必须是**已经存在的独立离线副本**，旁边不能有 `-wal`／`-shm`／`-journal`（指向别处的符号链接也算）。和 [发布预检](release-preflight.md) 一样：不要直接指向 NAS 或开发运行库；副本由获准操作者建立、确认不再被改写；**不要为了让检查通过去删 WAL／SHM**。
- 打开前就拒绝、只给固定原因码的情况：UNC／device 路径（`nonlocal_input_path`）；路径或上级目录里有符号链接、文件名以 `.env` 开头（不分大小写，`.envrc`、`.env.local` 都算）（`unsafe_input_path`）；不是普通文件，比如目录（`input_kind_mismatch`）；0 字节或超过 512 MiB（`input_size_budget`）；不存在（`database_copy_missing`，不会被创建）；读不了（`database_copy_unreadable`）；有旁文件（`offline_copy_sidecars_present`）；本机 SQLite 低于 3.37、没有 `PRAGMA table_list`（`sqlite_version_unsupported`）。
- 打开方式与发布预检相同：`mode=ro&immutable=1`、`query_only`、`trusted_schema=OFF`、60 秒／5 亿 VM 步的执行预算、一次 `BEGIN` 快照；开始前和结束后各算一次文件指纹，副本中途变了就整份不报（`inputs_changed_during_check`）。打不开是 `database_open_failed`，不是 SQLite 库是 `database_error`，预算用完是 `sqlite_budget`。
- 报告是 stdout 上的一份 JSON。没有写文件的选项；重定向时也不要覆盖数据库或其他输入。
- 退出码：`0` 每一节、节里的每一部分都查了；`2` 报告已生成，但有的节或某一节里的一部分没查（比如某张表不存在）或失败；`1` 没能读这个副本（上面这些原因码，或参数错误、脚本自身出错 `audit_failed`），输出里只有固定的原因码。退出码 0 只说明报告完整，**不说明数据没有缺口**。

## 读什么、不读什么

读任何一行之前，脚本先用 `PRAGMA table_list` 和 `PRAGMA table_xinfo` 看下面这些表的结构（只看名字、类型和是否生成列，不读行）。名字对得上、但其实是视图、虚拟表或影子表的，或者要读的列里有生成列（读的时候由别的列算出来，比如由 `raw_text` 算出来，授权回调不会被问到那些列）的，记 `not_plain`，一概不读；缺了要读的列记 `column_missing`。

之后连接装上 SQLite 授权回调：只有下面这些列能读，其余一律拒绝，包括 SQL 函数、写语句、`ATTACH`、`PRAGMA`，以及经由视图或触发器的读取。

| 表 | 列 |
|---|---|
| `schema_versions` | `version` |
| `courses` | `course_id`、`primary_code`、`primary_name`、`status`、`generated_json` |
| `course_catalog_sources` | `course_id`、`snapshot` |
| `course_requisite_documents` | `course_id`、`catalog_year`、`document`、`content_hash` |
| `programs` | `program_id` |
| `program_plans` | `plan_id`、`program_id`、`campus`、`catalog_year`、`pathway`、`concentration`、`document`、`content_hash` |
| `program_required_courses` | `program_id`、`course_id` |
| `course_prerequisites` | `course_id`、`prereq_course_id` |

- 用户相关的表（`users`、`user_unlocks`、`user_courses`、`query_log`、`coop_experiences`、`coop_submissions`、`coop_contribution_credits`、`chat_answers`、`answer_feedback`）和 `course_aliases` 一概不读；`courses.raw_text`、`search_expansion`、`metadata` 也不读。测试把这张表原样钉住，并核对实际读到的列正好是这些。
- 课程 JSON、目录快照、先修文档、培养方案的内容会被读进来做校验，但报告里只有计数。`--details` 另外列出课程代码、方案 ID 和方案范围（校区／年度／路径／有没有方向／coverage／审核状态，方向的名字不列）；引文、描述、条款原文、审核人、备注都不输出。
- 列里的值只有合格式才会出现在输出里：课程代码按代码格式规整后列出；方案 ID 和项目 ID 必须是小写字母、数字和连字符（项目 ID 最多 64 个字符）。其余的只计数：明细里计入 `unlisted_malformed`，汇总里有各自的计数（见各节）。
- 和应用一样，装着 UTF-8 JSON 文本的 BLOB 照常解析。存成 TEXT 却不是合法 UTF-8 的值只算它所在那一行（`invalid_json`，ID 列则当作对不上任何 ID），不会让整节失败。注意应用读到这种行时整条查询都会失败（比如同一批课程的快照一个都挂不上），所以这类行应当最先修。

## 报告结构

顶层：`format_version`、`report`（固定为 `data_coverage`）、`complete`、`database`（`checked` 或 `failed` 加原因码）、`sections`、`limitations`、`rules_doc`，加 `--details` 时还有 `details`。

每一节、节里能单独没查成的部分，都有 `status`：

- `checked`：查过了。计数是 0 就是「查了、没有这一类」。
- `not_checked`：没查，`code` 说明原因：`table_missing`（表不存在）、`table_not_plain`（同名对象是视图、虚拟表，或要读的列是生成列）、`column_missing`、`courses_not_checked`（依赖的课程一节没查成）、`catalog_snapshots_not_checked`（目录快照一节没查成，学分和先修代码因此没法和目录比）、`database_unavailable`（副本没读成）。
- `failed`：查的时候失败，只给固定的原因码：`row_budget`（单表超过 20 万行，不截断）、`sqlite_budget`、`read_outside_allowlist`（副本的结构让查询碰到了允许范围以外的列）、`database_error`、`section_failed`。

`complete` 只有在任何一节、任何一部分都是 `checked` 时才为 true；某一节里有一部分 `not_checked`（比如 `programs` 表不在，`legacy_rows` 的按项目统计就没查），`complete` 也是 false，退出码 2。

每一组计数都写明分母（`denominator`），每一节的 `rules` 给这一节输出里出现的每个名字一句规则（院系、年度、项目 ID 这类数据本身除外），测试逐层核对这一点。`counts` 下的类别、每个字段的类别互斥、相加等于分母；判断按下面表里的先后顺序，取第一个符合的。其他计数块各自写明分母，会重叠的在规则里注明「不互斥」，测试逐块核对能相加的都相加得上。

## 各节

### courses

分母：`courses` 的全部行。依次判断：

| 类别 | 规则 |
|---|---|
| `duplicate_id` | 和别的行共用同一个 `course_id`（只有没有主键的表才可能）；这几行都不用 |
| `oversize` | `generated_json` 超过 100 万字符（BLOB 按字节），不解码 |
| `invalid_json` | NULL 或数字、不是合法 UTF-8 的 TEXT，或不是合法 JSON |
| `invalid_record` | 合法 JSON，但 `Course` 模型不接受（API 读它也会失败） |
| `identity_mismatch` | `course_id`、`primary_code`、`primary_name` 列和 JSON 里的不一致（`course_id` 为 NULL 或不是文本时一定不一致）；排除在外，因为其他表按哪一个对应都说不清 |
| `synthetic` | 回答路径会标 `synthetic_record_not_real_course` 的合成记录（ID 以 `synth-` 开头，或来源是 `synthetic_seed_`）；不算覆盖 |
| `in_scope` | 其余的行，是后面各节的分母 |

`in_scope_courses` 给出同一课程代码出现在多门在范围内课程里的组数和行数（不互斥）、每个院系的课程数；`status_column` 是 `status` 列的分布（pending／indexed／failed／other，相加等于行数，和数据质量无关）。

### catalog_snapshots

分母：在范围内的课程。`usable` 的条件就是回答路径挂快照的条件（`CatalogSourceRepository.get_batch`）：恰好一行、`CatalogSnapshot` 模型接受、代码和标题与课程一致。其余是 `absent`、`duplicate_rows`、`oversize`、`invalid_json`、`invalid_record`、`identity_mismatch`（名称不一致，比如课程改了名而快照没跟上）。和应用不同的两处见下面「和应用的差别」。

`snapshot_rows` 以快照表的全部行为分母：属于在范围内课程的行、属于被排除课程的行、没有对应课程的行（`orphan_rows`，`course_id` 为 NULL 或不是文本也算），三者相加等于行数。

`usable_snapshots` 以可用快照为分母统计抓取日期：`retrieved_at` 为空就记 `retrieval_date_unknown`，**不拿导入时间或文件时间代替**；只有记录了抓取日期的才进 `retrieved_on` 的最早／最晚日期。现在的目录抓取器不记录抓取时间，所以旧数据这里应当全是 unknown。另外统计缺描述、没有整数学分（目录写的是范围、小数或没写）、列了先修代码的快照数（各自独立，不互斥）。

### fields

分母：在范围内的课程。对 `rag/answer_evidence.py` 的 `AVAILABILITY_FIELDS` 里每个字段，每门课归到一个类别：

| 类别 | 规则 |
|---|---|
| `catalog_only` | 课程记录没有值，可用快照有（学分、先修代码）：可以直接从目录补 |
| `catalog_lists_none` | 课程记录没有值，可用快照比过了也没有（学分：目录写的是范围、小数或没写；先修：目录没列先修代码）：目录里没有可补的 |
| `catalog_conflict` | 课程记录的值和可用快照不同（学分：快照有整数学分时；先修代码按集合比，快照一个都没列而记录有也算） |
| `catalog_consistent` | 和可用快照相同（学分；先修代码集合） |
| `missing` | 没有值（`None` 或空列表；0 是值）；对学分和先修代码，还要没有可用快照可比，所以这一类应当先去补目录快照 |
| `extracted_estimate` | 有值，并且有这个字段的抽取证据：是抽取出来的估计，不是官方事实 |
| `course_sources_only` | 有值，没有这个字段的证据，但课程记录了来源 ID；这些 ID 不说明支撑哪个字段 |
| `no_recorded_source` | 有值，没有字段证据、没有来源 ID、也没和目录比过 |

有可用快照时先和目录比：学分只在快照有整数学分时才比，先修代码集合即使快照一个都没列也比；之后看字段证据，最后看来源 ID。`missing`、`catalog_only`、`catalog_lists_none` 加起来正好是回答路径 `missing_fields` 里的这个字段，学分的 `catalog_conflict` 正好是回答路径的 `catalog_metadata_conflict`，测试逐门课核对这两点。先修代码集合的冲突是报告自己的比较，回答路径没有对应的警告。

另外给出：课程的目录描述（`catalog_description`：可用快照有描述、可用快照没有描述、没有可用快照；后两项就是回答路径缺的 `catalog_description`），以及 `course_answer_evidence` 对这些课会给出的警告各有几门（`answer_warnings`，一门课可以有好几个）。目录快照一节没查成时，学分和先修代码这两个字段、`catalog_comparison`、`catalog_description`、`answer_warnings` 都标 `not_checked`（`catalog_snapshots_not_checked`），因为那时分不清「没有快照可比」和「快照里也没有」；其他字段照常统计。

`by_department` 每个院系给出课程数和 `fields` 下每个字段的类别（省略为 0 的类别；没和目录比时不含学分和先修代码）。

「人工核对」只有培养方案有（见下面的 `source_checked`）；课程记录本身没有逐字段的人工核对标记，报告不替它编一个。

### requisite_documents

分母：`course_requisite_documents` 的全部行。`usable` 的条件和课程详情页相同（`CourseRequisiteRepository._decode`，包括它自己的 20 万长度上限）：文档模型接受（包括语法树和记录的条款一致），课程 ID／年度和所在行一致，代码和标题和课程一致，内容 hash 一致。其余依次是：`orphan_rows`（`course_id` 为 NULL 或不是文本也算）、`rows_for_courses_out_of_scope`、`duplicate_rows`、`oversize`、`invalid_json`、`invalid_record`、`row_identity_mismatch`、`course_identity_mismatch`、`content_hash_mismatch`。

`by_catalog_year` 按行的年度统计（不是 `YYYY-YYYY` 格式的记 `unrecognized`，原值不输出）：可用和不可用的行数（相加等于这个年度的行数）、覆盖了几门在范围内的课；可用文档的先修／同修条款 `parsed`／`unparsed`／`not_listed`（`not_listed` 不等于没有要求）、描述证据状态（没采集的记 `not_captured`）、目录学时和课程学分的比较（固定整数学时才比，范围和小数不比）、采集日期的最早／最晚，这几组各自相加等于可用文档数。

`in_scope_courses`：有可用文档的在范围内课程数，以及**有旧先修代码列表、却没有任何年度可用文档**的课程数。后者的回答只能依赖代码列表，是 OPT-04 的输入。

`by_department`：每个院系的课程数，以及每个年度有可用文档的课程数和这些文档的先修条款解析状态。

### program_plans

分母：`program_plans` 的全部行。第一类 `orphan_rows`（`program_id` 不在 `programs` 里，NULL 或不是文本也算）要靠 `programs` 表判断，所以 **`programs` 表不在或不能读时整节 `not_checked`**，不会把没查的孤儿行算成 0。`usable`：方案模型接受、方案 ID 和范围与所在行一致、内容 hash 一致，并且没有别的这样的行占着同一个范围或方案 ID（有就都算 `duplicate_scope_or_id`，不挑一个）。

- `usable_plans`：可用方案的 `partial`／`complete`、`draft`／`source_checked`、有没有来源指纹，各自相加等于可用方案数；以及采集日期范围。
- `by_program`：按项目、再按年度给出可用数、`partial`／`complete`、`draft`／`source_checked`。只列格式合格的项目 ID，其余可用方案计入 `usable_plans_with_unlisted_program_id`。
- `programs`：以 `programs` 的行为分母：至少有一份 complete 可用方案的项目（`with_any_complete_plan`：任一年度、任一路径有就算，别的年度或路径可能只有 partial 或没有，逐年度看 `by_program`）、可用方案全是 partial 的项目、没有可用方案的项目，以及 `program_id` 为 NULL、不是文本或和别的行重复的行（`id_unusable`，不和方案对应）。四项相加等于行数。
- **partial 不计作完整**。`complete` 的方案按模型规则必须是 `source_checked` 且没有未建模的规则。
- `source_checked` 只表示有人记录了把文档和采集的页面对照过，**不等于官方正确，也不等于当前适用**；hash 一致也只说明内容没被改过。

### legacy_rows

`program_required_courses` 和 `course_prerequisites` 各以行数为分母：指向在范围内课程的行、至少一端指向不在范围内课程（被排除、不存在、NULL 或不是文本）的行，相加等于行数；有旧先修边的在范围内课程数。`program_required_courses` 另按项目 ID 统计（只列 `programs` 里有、格式合格的 ID），加上 ID 格式合格但 `programs` 里没有的行、ID 不合格式或不是文本的行，三者相加等于行数；`programs` 表不在时这部分 `not_checked`。这些是旧的种子数据，不是核实过的规则或先修逻辑。

### schema

`tables` 给出上面每张数据表的状态：`present`、`missing`、`not_plain`、`column_missing`。`schema_versions` 以版本行为分母：属于 1.0–1.7 的行和其他版本的行（只计数），以及 1.0–1.7 里哪些有、哪些缺；表不在时这部分 `not_checked`。

## 和应用的差别

`usable` 的条件和应用相同，只有下面几处不同，规则里也都写明了：

- **超长的值不解码**：快照超过 10 万字符、课程 JSON 超过 100 万字符、方案超过 20 万字符时记 `oversize`，不算可用。应用挂快照（`get_batch`）、读课程（`get`）、列方案（`list_for_program`）都没有长度上限，可能照样用；先修文档和 `course_context` 的上限与报告相同。
- **重复行一个都不用**：只有表缺了主键或唯一约束才会出现。应用挂快照时会用最后一个有效的，课程详情页会把同一年度的几份文档都显示出来，`list_for_program` 会把重复的方案都列出来（`course_context` 则一个都不用）；同一 `course_id` 的几行课程，应用按 ID 查和批量查拿到的可能不是同一行。
- **不是合法 UTF-8 的 TEXT 只算一行**：应用读到这种行时整条查询失败，影响同一查询里的其他行。
- 先修代码集合的冲突（`catalog_conflict`）是报告自己的比较，回答路径没有这个警告。

## 明细（--details）

课程类的明细（课程、目录快照、字段、先修文档各节）按院系分组，**每个院系**每个类别最多列 `--max-codes` 项（默认 25，范围 1–500），排好序，`omitted` 是这个院系没列出的数量；方案和项目的明细不分院系，每个类别最多列同样的项数。包括：不能用的课程行（含 `duplicate_id`）和重复代码；每个快照类别；每个字段的 `missing`／`catalog_only`／`catalog_conflict`；可用快照没有描述的课程；存储值和自己的抽取证据不一致的课程（`field_evidence_value_conflict`）；不可用和条款未解析的先修文档、学时冲突、只有旧先修列表的课程；不可用的方案、可用方案的范围、没有可用方案的项目。列不合格式的值不列出，只计入 `unlisted_malformed`。没查成的节不出明细。

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
