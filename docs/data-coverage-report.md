# OPT-03 — 数据覆盖、冲突与来源报告

2026-10-08 本地实现，10-09／10 按三轮审查修订；变更、审查与测试结果记在 [开发修改记录](development-change-log.md) 第 17 节。第 18 批（提示词 4.4）让字段类别和回答警告也用上年度先修规则，和聊天一致，见第 18 节。只新增一个离线脚本 `scripts/audit_data_coverage.py`，API、界面、数据库和部署都不变。

这份报告回答「下一批到底补哪门课、哪个字段」：不只给课程总数，而是按院系、按字段列出缺什么、和目录冲突的是哪些、来源是什么，先修文档和培养方案按年度／范围统计。

## 运行

```bash
.venv/bin/python -B scripts/audit_data_coverage.py --db-copy /explicit/offline-copy.sqlite3
.venv/bin/python -B scripts/audit_data_coverage.py --db-copy /explicit/offline-copy.sqlite3 --details --max-codes 50
```

- 输入必须是**已经存在的独立离线副本**，旁边不能有 `-wal`／`-shm`／`-journal`（指向别处的符号链接也算）。和 [发布预检](release-preflight.md) 一样：不要直接指向 NAS 或开发运行库；副本由获准操作者建立、确认不再被改写；**不要为了让检查通过去删 WAL／SHM**。
- 打开前就拒绝、只给固定原因码的情况：UNC／device 路径（`nonlocal_input_path`）；路径或上级目录里有符号链接、文件名以 `.env` 开头（不分大小写，`.envrc`、`.env.local` 都算）（`unsafe_input_path`）；不是普通文件，比如目录（`input_kind_mismatch`）；0 字节或超过 512 MiB（`input_size_budget`）；不存在（`database_copy_missing`，不会被创建）；读不了（`database_copy_unreadable`）；有旁文件（`offline_copy_sidecars_present`）；本机 SQLite 低于 3.37、没有 `PRAGMA table_list`（`sqlite_version_unsupported`）。
- 打开方式与发布预检相同：`mode=ro&immutable=1`、`query_only`、`trusted_schema=OFF`、60 秒／5 亿 VM 步的执行预算、一次 `BEGIN` 快照；开始前和结束后各算一次文件指纹，副本中途变了就整份不报（`inputs_changed_during_check`）。打不开是 `database_open_failed`，不是 SQLite 库是 `database_error`，预算用完是 `sqlite_budget`，没通过完整性检查（见下一节）是 `database_integrity_failed`。
- 报告是 stdout 上的一份 JSON。没有写文件的选项；重定向时也不要覆盖数据库或其他输入。
- 退出码：`0` 每一节、节里的每一部分都查了；`2` 报告已生成，但有的节或某一节里的一部分没查（比如某张表不存在）或失败；`1` 没能读这个副本（上面这些原因码，或参数错误、脚本自身出错 `audit_failed`），输出里只有固定的原因码。退出码 0 只说明报告完整，**不说明数据没有缺口**。

## 读什么、不读什么

读任何一行之前，脚本先跑 `PRAGMA integrity_check(1)`：结果不是 `ok`，或者检查本身就发现文件损坏（比如复制到一半、被截断的文件），都整份不报（`database_integrity_failed`）。下面的结构检查和授权回调都只认名字：一份损坏的文件，比如几张表共用页、或者表的 b-tree 被换过（`programs` 的根页指向用户表的 b-tree），两关都能过，会以允许的名字读到别的表的字节。`integrity_check` 能查出共用的页、和自己的索引对不上的表，以及被截断的文件；发布预检用的 `quick_check` 不核对索引内容，查不出两张表互换了 b-tree。但一份把别的数据一致地重建在允许名字下的文件，任何检查都能通过，所以真正的边界是输出（见下面）。这个检查会读文件的每一页（用户表也在内），但只比较结果是不是 `ok`，什么都不输出。它也报告 NOT NULL 列里的 NULL（只有损坏或手工改过的文件才会有），这样的副本同样整份不报，而不是把那一行计进去；CHECK 约束不查：SQLite 不给只读打开的库加载 CHECK 约束，所以存着应用不会写的 JSON 的行照常逐行计数。

然后用 `PRAGMA table_list` 和 `PRAGMA table_xinfo` 看下面这些表的结构（只看名字、类型和是否生成列，不读行）。名字对得上、但其实是视图、虚拟表或影子表的，或者要读的列里有生成列（读的时候由别的列算出来，比如由 `raw_text` 算出来，授权回调不会被问到那些列）的，记 `not_plain`，一概不读；缺了要读的列记 `column_missing`。名字按原样比较：表名或列名只差大小写的，也记作缺失（见「和应用的差别」）。

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

- 用户相关的表（`users`、`user_unlocks`、`user_courses`、`query_log`、`coop_experiences`、`coop_submissions`、`coop_contribution_credits`、`chat_answers`、`answer_feedback`）和 `course_aliases` 一概不查询（只有开头的完整性检查会读到它们的页，见上）；`courses.raw_text`、`search_expansion`、`metadata` 也不读。测试把这张表原样钉住，并核对实际读到的列正好是这些。
- 这些检查都是按名字做的：有人抄进允许的列里的值（比如把用户的 ID 写进 `programs.program_id`），或者一份把别的数据一致地重建在允许名字下的文件，照样会被读到。所以真正的边界是输出：输出里只有计数、固定文字，和下面说的格式合格的代码、ID、年度，以及校验过的记录里的日期（抓取、采集日期的最早和最晚一天）。
- 课程 JSON、目录快照、先修文档、培养方案的内容会被读进来做校验，但报告里只有计数。`--details` 另外列出课程代码、方案 ID 和方案范围（校区／年度／路径／有没有方向／coverage／审核状态，方向的名字不列）；引文、描述、条款原文、审核人、备注都不输出。
- 列里的值只有合格式才会出现在输出里：课程代码按代码格式规整后列出；方案 ID、项目 ID，以及重复代码旁边的课程 ID，必须是小写字母、数字和连字符，**并且至少有一个字母**（项目 ID 最多 64 个字符，方案 ID 和课程 ID 最多 100 个），所以抄进 ID 列的纯数字标识（比如账号）永远不会印出来；方案模型本身接受纯数字的方案 ID，所以可用方案的 ID 也要过这一关。年度必须是相邻两年的 `YYYY-YYYY`，和应用的要求一样。其余的只计数：明细里计入 `unlisted_malformed`，汇总里有各自的计数（见各节）。
- 和应用一样，装着 UTF-8 JSON 文本的 BLOB 照常解析。存成 TEXT 却不是合法 UTF-8 的值，应用取到它的查询会整条失败，同一查询里的其他行也拿不到（比如同一批课程的快照一个都挂不上），所以这类行应当最先修。报告把这种行单独记成一类 `text_not_utf8`：在课程、先修文档、方案三节最先判断，在目录快照一节排在 `absent` 之后；`--details` 里能读出代码或 ID 的都列出来。其他计数块另有不互斥的 `rows_with_text_not_utf8`。这种行在查重复之前就归入 `text_not_utf8`，所以两个不同的坏年度不会被当成重复行；两个坏值也只有存储的字节完全相同才相等，和 SQLite 自己的比较一致。

## 报告结构

顶层：`format_version`、`report`（固定为 `data_coverage`）、`complete`、`database`（`checked` 或 `failed` 加原因码）、`sections`、`limitations`、`rules_doc`，加 `--details` 时还有 `details`。

每一节、节里能单独没查成的部分，都有 `status`：

- `checked`：查过了。计数是 0 就是「查了、没有这一类」。
- `not_checked`：没查，`code` 说明原因：`table_missing`（表不存在）、`table_not_plain`（同名对象是视图、虚拟表，或要读的列是生成列）、`column_missing`、`courses_not_checked`（依赖的课程一节没查成）、`catalog_snapshots_not_checked`（目录快照一节没查成，学分和先修代码因此没法和目录比）、`requisite_documents_not_checked`（先修文档一节没查成，先修字段和回答警告因此没法定）、`database_unavailable`（副本没读成）。
- `failed`：查的时候失败，只给固定的原因码：`row_budget`（单表超过 20 万行，不截断）、`sqlite_budget`、`read_outside_allowlist`（副本的结构让查询碰到了允许范围以外的列）、`database_error`、`section_failed`。

`complete` 只有在任何一节、任何一部分都是 `checked` 时才为 true；某一节里有一部分 `not_checked`（比如 `programs` 表不在，`legacy_rows` 的按项目统计就没查），`complete` 也是 false，退出码 2。

每一节和节里的主要计数块都写明分母（`denominator`）；按院系、按年度、按项目的分组，`fields` 里每个字段的类别，以及 `status_column`、`catalog_description`、`answer_warnings`，没有自己的 `denominator` 键，分母见规则（每个院系以它自己的 `courses_in_scope` 为分母，每个字段的类别以全节的分母为分母）。每一节的 `rules` 给这一节输出里出现的每个名字一句规则，分母的名字也有（院系、年度、项目 ID 这类数据本身除外），测试在完整的、缺表的和有坏值的几份报告上逐层核对这一点。`counts` 下的类别、每个字段的类别互斥、相加等于分母；判断按下面表里的先后顺序，取第一个符合的。会重叠的计数在规则里注明「不互斥」（比如 `answer_warnings`，一门课可以有好几个）。测试逐块核对能相加的都相加得上；按院系的分组，每个类别加起来等于全节的数，每个院系的课程数也和 `courses` 一节的一致。

## 各节

### courses

分母：`courses` 的全部行。依次判断：

| 类别 | 规则 |
|---|---|
| `text_not_utf8` | 读的列里有不是合法 UTF-8 的 TEXT：应用取到这个值的查询整条失败 |
| `duplicate_id` | 和别的行共用同一个 `course_id`（只有没有主键的表才可能）；这几行都不用 |
| `oversize` | `generated_json` 超过 100 万字符（BLOB 按字节），不解码 |
| `invalid_json` | NULL 或数字，或不是合法 JSON（装着 UTF-8 JSON 的 BLOB 照常解析） |
| `invalid_record` | 合法 JSON，但 `Course` 模型不接受（API 读它也会失败） |
| `identity_mismatch` | `course_id`、`primary_code`、`primary_name` 列和 JSON 里的不一致（`course_id` 为 NULL 或不是文本时一定不一致）；排除在外，因为其他表按哪一个对应都说不清 |
| `synthetic` | 回答路径会标 `synthetic_record_not_real_course` 的合成记录（ID 以 `synth-` 开头，或来源是 `synthetic_seed_`）；不算覆盖 |
| `in_scope` | 其余的行，是后面各节的分母 |

`in_scope_courses` 给出同一课程代码出现在多门在范围内课程里的组数和行数（不互斥；`--details` 里凡列出这些代码，都带上 `course_id`）、每个院系的课程数；`status_column` 是 `status` 列的分布（pending／indexed／failed／other，相加等于行数，和数据质量无关）。

### catalog_snapshots

分母：在范围内的课程。`usable` 的条件就是回答路径挂快照的条件（`CatalogSourceRepository.get_batch`）：恰好一行、`CatalogSnapshot` 模型接受、代码和标题与课程一致（应用还会挂上报告不用的重复或超长快照，见「和应用的差别」）。其余依次是 `absent`、`text_not_utf8`（这门课的快照行里有不是合法 UTF-8 的 TEXT：应用给包含这门课的任何一批课程挂快照时，整条查询失败；有重复行也先归这一类）、`duplicate_rows`、`oversize`、`invalid_json`、`invalid_record`、`identity_mismatch`（名称不一致，比如课程改了名而快照没跟上）。和应用的不同见下面「和应用的差别」。

`snapshot_rows` 以快照表的全部行为分母：属于在范围内课程的行、属于被排除课程的行、没有对应课程的行（`orphan_rows`，`course_id` 为 NULL 或不是文本也算），三者相加等于行数；另有 `rows_with_text_not_utf8`（不互斥）。这些行会让应用给包含这门课的任何一批课程挂快照时整条查询失败，被排除的课也一样（比如合成课程，应用照样会读到它），所以明细里按课程代码把它们都列出来。

`usable_snapshots` 以可用快照为分母统计抓取日期：`retrieved_at` 为空就记 `retrieval_date_unknown`，**不拿导入时间或文件时间代替**；只有记录了抓取日期的才进 `retrieved_on` 的最早／最晚日期。现在的目录抓取器不记录抓取时间，所以旧数据这里应当全是 unknown。另外统计缺描述、没有整数学分（目录写的是范围、小数或没写）、列了先修代码的快照数（各自独立，不互斥）。

`by_department`：每个院系的课程数和上面各类别（省略为 0 的类别）。

### fields

分母：在范围内的课程。对 `rag/answer_evidence.py` 的 `AVAILABILITY_FIELDS` 里每个字段，每门课归到一个类别：

| 类别 | 规则 |
|---|---|
| `year_rules` | 只用于先修：这门课有可用的年度先修文档，回答路径给出那一年的规则，不用存储的代码列表，所以先修既不算缺失，也不和目录比；最先判断 |
| `catalog_only` | 课程记录没有值，可用快照有（学分、先修代码）：可以直接从目录补 |
| `catalog_lists_none` | 课程记录没有值，可用快照比过了也没有（学分：目录写的是范围、小数或没写；先修：目录没列先修代码）：目录里没有可补的 |
| `catalog_conflict` | 课程记录的值和可用快照不同（学分：快照有整数学分时；先修代码按集合比，快照一个都没列而记录有也算） |
| `catalog_consistent` | 和可用快照相同（学分；先修代码集合） |
| `missing` | 没有值（`None` 或空列表；0 是值）；对学分和先修代码，还要没有可用快照可比，所以这一类应当先去补目录快照 |
| `extracted_estimate` | 有值，并且有这个字段的抽取证据：是抽取出来的估计，不是官方事实 |
| `course_sources_only` | 有值，没有这个字段的证据，但课程记录了来源 ID；这些 ID 不说明支撑哪个字段 |
| `no_recorded_source` | 有值，没有字段证据、没有来源 ID、也没和目录比过 |

先修有可用的年度先修文档时最先归为 `year_rules`。其余的，有可用快照时先和目录比：学分只在快照有整数学分时才比，先修代码集合即使快照一个都没列也比；之后看字段证据，最后看来源 ID。先修代码按规范形式比较：合格的代码规整成 `CS 5004` 这样（`cs5004` 和 `CS 5004` 是同一个），其他值转成大写、去掉多余空白后比较（所以 `cs  5800` 也等于 `CS 5800`）；空白项不算列出的代码。所以只差空格或大小写不算冲突。`missing`、`catalog_only`、`catalog_lists_none` 加起来正好是回答路径 `missing_fields` 里的这个字段，学分的 `catalog_conflict` 正好是回答路径的 `catalog_metadata_conflict`，测试逐门课核对这两点，也直接拿聊天路径（`build_answer_evidence`）核对整节的缺口数和警告数。这两点的前提是应用挂的也是报告认可的那份快照：应用挂了报告不用的重复或超长快照时，两边会不同。先修代码集合的冲突是报告自己的比较，回答路径没有对应的警告。

另外给出：课程的目录描述（`catalog_description`：可用快照有描述、可用快照没有描述、没有可用快照；后两项就是回答路径缺的 `catalog_description`），以及 `course_answer_evidence` 对这些课会给出的警告各有几门（`answer_warnings`，一门课可以有好几个；`program_seed_unverified` 取决于这门课是怎么查到的，不计）。给它的是报告认可的快照和年度先修证据，按聊天的方式构造：这门课的可用文档（最多 3 个年度，新的在前）和不可用的行数；有不是合法 UTF-8 的行时，这门课一条年度规则都没有，和聊天的查询失败时一样。目录快照一节没查成时，学分和先修代码这两个字段、`catalog_comparison`、`catalog_description`、`answer_warnings` 都标 `not_checked`（`catalog_snapshots_not_checked`），因为那时分不清「没有快照可比」和「快照里也没有」；先修文档一节没查成时，先修和 `answer_warnings` 标 `not_checked`（`requisite_documents_not_checked`），因为那时分不清「缺先修」和「有年度规则」；其他字段照常统计。

`by_department` 每个院系给出课程数、`fields` 下每个字段的类别（省略为 0 的类别；上面标 `not_checked` 的字段不含），和目录比过时还有这个院系的 `catalog_description`，目录和年度文档都读了时还有 `answer_warnings`（同样省略为 0 的）。

「人工核对」只有培养方案有（见下面的 `source_checked`）；课程记录本身没有逐字段的人工核对标记，报告不替它编一个。

### requisite_documents

分母：`course_requisite_documents` 的全部行。`usable` 的条件和课程详情页相同（`CourseRequisiteRepository._decode`，包括它自己的 20 万长度上限）：文档模型接受（包括语法树和记录的条款一致），课程 ID／年度和所在行一致，代码和标题和课程一致，内容 hash 一致。其余依次是：`text_not_utf8`（读的四列里有不是合法 UTF-8 的 TEXT：应用取到这个值的查询整条失败，比如课程详情页查这门课的先修文档）、`orphan_rows`（`course_id` 为 NULL 或不是文本也算）、`rows_for_courses_out_of_scope`、`duplicate_rows`、`oversize`、`invalid_json`、`invalid_record`、`row_identity_mismatch`、`course_identity_mismatch`、`content_hash_mismatch`。

`by_catalog_year` 按行的年度统计（不是相邻两年的 `YYYY-YYYY` 的记 `unrecognized`，原值不输出；应用也只接受这种年度）：可用和不可用的行数（相加等于这个年度的行数）、覆盖了几门在范围内的课；可用文档的先修／同修条款 `parsed`／`unparsed`／`not_listed`（`not_listed` 不等于没有要求）、描述证据状态（没采集的记 `not_captured`）、目录学时和课程学分的比较（固定整数学时才比，范围和小数不比），这几组各自相加等于可用文档数；另有采集日期的最早／最晚。

`in_scope_courses`：有可用文档的在范围内课程数，以及**有旧先修代码列表、却没有任何年度可用文档**的课程数。后者的回答只能依赖代码列表，是 OPT-04 的输入。

`by_department`：每个院系的课程数，以及每个年度有可用文档的课程数，和这些文档的先修／同修条款解析状态、目录学时和课程学分的比较。

### program_plans

分母：`program_plans` 的全部行。依次判断：`text_not_utf8`（读的列里有不是合法 UTF-8 的 TEXT）；`orphan_rows`（`program_id` 不在 `programs` 里，NULL 或不是文本也算）；然后是 `oversize`、`invalid_json`、`invalid_record`、`identity_mismatch`（方案 ID 或范围和所在行不一致）、`content_hash_mismatch`。孤儿行要靠 `programs` 表判断，所以 **`programs` 表不在或不能读时整节 `not_checked`**，不会把没查的孤儿行算成 0；培养方案页面到不了孤儿方案，课程页却可能显示它，见「和应用的差别」。剩下的行，没有别的这样的行占着同一个范围或方案 ID 的是 `usable`；有就都算 `duplicate_scope_or_id`，不挑一个。

- `usable_plans`：可用方案的 `partial`／`complete`、`draft`／`source_checked`、有没有来源指纹，各自相加等于可用方案数；以及采集日期范围。`partial` 只表示方案没有声明覆盖完整（它也可能其实建模了全部规则），`draft` 只表示没标 `source_checked`（它也可能记录了审核人）。
- `by_program`：按项目、再按年度给出可用数、`partial`／`complete`、`draft`／`source_checked`。只列格式合格的项目 ID（见上文，至少有一个字母），其余可用方案计入 `usable_plans_with_unlisted_program_id`。
- `programs`：以 `programs` 的行为分母：至少有一份 complete 可用方案的项目（`with_any_complete_plan`：任一年度、任一路径有就算，别的年度或路径可能只有 partial 或没有，逐年度看 `by_program`）、可用方案全是 partial 的项目、没有可用方案的项目，以及 `program_id` 为 NULL、不是文本或和别的行重复的行（`id_unusable`，不和方案对应）。四项相加等于行数；另有 `rows_with_text_not_utf8`（不互斥，这种行算在 `id_unusable` 里）。
- **partial 不计作完整**。`complete` 的方案按模型规则必须是 `source_checked` 且没有未建模的规则。
- `source_checked` 只表示有人记录了把文档和采集的页面对照过，**不等于官方正确，也不等于当前适用**；hash 一致也只说明内容没被改过。

### legacy_rows

`program_required_courses` 和 `course_prerequisites` 各以行数为分母：指向在范围内课程的行、至少一端指向不在范围内课程（被排除、不存在、NULL 或不是文本）的行，相加等于行数；有旧先修边的在范围内课程数；每张表另有 `rows_with_text_not_utf8`（不互斥）。`program_required_courses` 另按项目 ID 统计（只列 `programs` 里有、格式合格的 ID），加上 ID 格式合格但 `programs` 里没有的行、ID 不合格式或不是文本的行，三者相加等于行数；`programs` 表不在时这部分 `not_checked`。这些是旧的种子数据，不是核实过的规则或先修逻辑。

### schema

`tables` 给出上面每张数据表的状态：`present`、`missing`、`not_plain`、`column_missing`。`schema_versions` 以版本行为分母：属于 1.0–1.7 的行和其他版本的行（只计数），以及 1.0–1.7 里哪些有、哪些缺（每个版本只列一次），另有 `rows_with_text_not_utf8`（不互斥，这种行算在其他版本里）；表不在时这部分 `not_checked`。

## 和应用的差别

`usable` 的条件和应用相同，只有下面这些地方不同，各节的规则里也都写明了：

1. **超长的值不解码**：快照超过 10 万字符、课程 JSON 超过 100 万字符、方案超过 20 万字符时记 `oversize`，不算可用。应用挂快照（`get_batch`）、读课程（`get`）、列方案（`list_for_program`）都没有长度上限，可能照样用；先修文档和 `course_context` 的上限与报告相同。
2. **重复行一个都不用**：只有表缺了主键或唯一约束才会出现。应用挂快照时会用最后一个有效的，课程详情页会把同一年度的几份文档都显示出来，`list_for_program` 会把重复的方案都列出来；`course_context` 一次只读一个年度，先去掉草稿和不含这门课的方案再查重复，所以孪生方案是草稿或在另一个年度时，它仍会显示那份 `source_checked` 的。同一 `course_id` 的几行课程，应用按 ID 查和批量查拿到的可能不是同一行。
3. **不是合法 UTF-8 的 TEXT 只算一行**：报告把这一行记成 `text_not_utf8`，其余照常统计；应用取到这个值的查询整条失败，影响同一查询里的其他行，被排除的课程（比如合成课程）的坏快照行也一样会让应用失败（明细里同样列出）。年度先修规则也是这样：有这种行的课，报告按聊天的结果算它一条年度规则都没有，和它同一批查询的别的课，报告照常算。这时报告比应用乐观，所以这类行要最先修。反过来，坏值在 `primary_name`、`status` 这类列时，应用答题只读 `generated_json`，可能照样给出这门课，报告却把它排除在外，这时报告比应用保守。
4. **孤儿方案不算可用**：`program_id` 不在 `programs` 里的方案，培养方案页面确实到不了；但 `course_context` 不查 `programs`，这样的方案只要有效且 `source_checked`，课程页的方案上下文照样会显示。
5. **先修代码集合的冲突**（`catalog_conflict`）是报告自己的比较，回答路径没有这个警告。
6. **名字只差大小写的表或列**（比如建表时写成 `Courses`）：报告的结构检查按原样比较名字，记作 `missing`／`column_missing`，这一部分 `not_checked`。目录快照、先修文档、方案这三张表，应用自己检查表在不在时也按原样比较名字，同样当作没有；`courses` 这类表 SQLite 和应用照样能读，这时报告比应用保守。宁可不查，不会把没查的写成查过。

## 明细（--details）

课程类的明细（课程、目录快照、字段、先修文档各节）按院系分组，**每个院系**每个类别最多列 `--max-codes` 项（默认 25，范围 1–500），按课程代码排序（同一代码的几项排在一起，再按年度和 `course_id`），`omitted` 是这个院系没列出的数量；方案和项目的明细不分院系，每个类别最多列同样的项数。包括：

- 课程：不能用的课程行（`text_not_utf8`、`duplicate_id`、`oversize`、`invalid_json`、`invalid_record`、`identity_mismatch`），以及重复代码（`duplicate_codes`）；
- 目录快照：`usable` 以外的每个类别；`rows_with_text_not_utf8`：每一行有坏值的快照，按它的课程代码列出，被排除的课程也列；
- 字段：每个字段除 `catalog_consistent` 和 `year_rules` 以外的每个类别，键名形如 `credits.missing`，也就是每一门要补、要和目录核对或要核实来源的课；可用快照没有描述的课程（`catalog_description.empty_in_usable_snapshot`）；存储值和自己的抽取证据不一致的课程（`field_evidence_value_conflict`）；
- 先修文档：在范围内课程的不可用文档（按类别，带年度），以及被排除课程的 `text_not_utf8` 行（按它自己那一行的课程代码）、先修／同修条款未解析（`prerequisite_unparsed`／`corequisite_unparsed`）、学时冲突（`credit_hours_conflict`）、只有旧先修列表的课程（`legacy_prereqs_without_usable_document`）；
- 方案：不可用的方案（按类别，含 `duplicate_scope_or_id`）、可用方案的范围（`usable_scopes`）、没有可用方案的项目（`programs_without_usable_plan`）。

同一个课程代码有不止一门在范围内的课程时（`courses` 一节的 `duplicate_code_groups`），只给代码就分不清该修哪一条，所以这些课在各处的每一项都带上 `course_id`，比如 `{"code": "DS 5220", "course_id": "c-ds5220a"}`；`duplicate_codes` 里每个代码也列出共用它的 `course_ids`。`course_id` 不合格式时是 `null`。列不合格式的值不列出，只计入 `unlisted_malformed`。没查成的节不出明细。

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
