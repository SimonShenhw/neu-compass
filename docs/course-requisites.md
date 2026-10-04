# 课程先修 / 共修：05C-1 解析与 05C-2 存储展示

05C-1 建立保守的语法提取和离线报告，05C-2 新增独立 v1.6 存储、课程详情读取和明确年度选择的页面组件。它们**不是个人注册资格、成绩比较、学期规划或完整政策判定器**。`Course` v1.1 与 `course_prerequisites` 旧边不改，结构化规则未接入 LLM 回答；没有迁移真实运行库。

## 数据契约与边界

`CatalogEntry` 新增可空 `requisites`，类型为 `schemas/course_requisites.py` 的 `CatalogRequisites`。新爬取保存结构；旧 JSONL 缺字段时为 `None`，只表示没有结构化记录，不从旧 `prereqs` 列表反推 AND/OR。旧代码不能读取新增字段时，需要同步更新读取端，不静默删除结构来声称已兼容。

每份结构独立保存 `prerequisite` 与 `corequisite`，语法版本为 `1`：

| 状态 | 含义 |
|---|---|
| `not_listed` | 该课程块未列出这一段；不是已证明没有要求 |
| `parsed` | 整段符合已支持的语法；不是要求已满足 |
| `unparsed` | 原段存在但不能完整识别；保留整段文本/失败原因，不返回成功解析的一部分 |

`raw_text` 仅统一空白（含不换行空格），不删重复代码、不改关系、成绩或括号。完整输入 HTML 另按 bytes 固定；原段格式/链接需查看对应来源，不把 normalized text 当成原字节副本。

节点只有课程、AND（`all_of`）、OR（`any_of`）。课程叶保留 `minimum_grade`、原文明确的 `academic_level` 标记和 `concurrent_allowed`；括号保留嵌套逻辑，分号和 `and` 为 AND，`or` 为 OR。同一括号层同时出现 AND 和 OR 时不假设优先级，整段标 `ambiguous_precedence`，需要对照人处理。重复分支保留，包括同课程不同成绩/level 的分支；不合并成最宽松条件。

`Corequisite(s)` 是独立共修段，不能改成提前完成的先修课。`concurrent_allowed` 只记录**先修段中明确写出的**“may be taken concurrently”，支持该说明出现在成绩前/后。共修段本身的含义来自 section，不靠给其中每个叶都设置该 flag；flag 为 false 也不抵消共修段。

本语法支持规范课程代码、列出的成绩符号、`(Graduate)` / `(Undergraduate)` 与明确并修说明。它不解释未支持的转学代码、分数测验、自由文本批准、未识别资格短语或混合逻辑；空段、重复 section、可辨认但不合规的标签也保留为未解析。来源中自指课程不自动删除/“修正”，报告会警告。

最大规则树 120 个节点、10 层；解析输入上限 8,000 字符，并有括号/课程标记预算；原文段字段上限 20,000 字符。超出模型上限的数据会失败，不截断后宣称成功。领域/项目选修模型与课程先修模型分开：培养方案桥接 B 条件、课程块 C- 门槛等不能互相覆盖，应在后续资格工作中分别考虑。

描述段内的 “requires admission” / “permission of instructor”、学院/大学政策、个人路径、成绩/转学/减免、实际开课、注册限制等**不在本解析范围**。`parsed` 只表示这一段语法被保留，不是整门课或全部政策已经核验。

## 固定输入与范围

2026-10-01 实际 GET 并固定三个 **2026–2027 Edition** 院系页面：[CS](https://catalog.northeastern.edu/course-descriptions/cs/)、[DS](https://catalog.northeastern.edu/course-descriptions/ds/)、[INFO](https://catalog.northeastern.edu/course-descriptions/info/)。这些页没有声明 Boston 或某个学生的培养路径，因此报告 `campus=null` 并明确警告；不能凭用户想覆盖 Boston 就给课程原文补出 Boston 适用性。

公开元数据在 `data/course_requisite_sources/catalog_2026_2027_manifest.json`，包含明确 URL、版次、UTC 捕获时间、正文长度、标题和 SHA-256。三个完整 HTML 与各自元数据在 **Git 忽略的 `data/raw/course_requisites/`**，按 SHA 命名，不提交网页全文。摘要校验只证明输入/元数据一致，不证明不可篡改真实性或个人适用性。

`scripts/capture_course_requisites.py` 要求显式小写院系列表、连续版次和输出目录；仅接受确切官方 HTTPS HTML，不跟随重定向，限制解码正文 2 MB，校验 heading/版次/课程块。已有同名原文或冲突元数据不覆盖，相同内容保留第一次捕获时间；后续失败可能保留此前已生成的合法输入，不宣称整批文件写入原子回滚。它只抓取来源，不自动生成 verified 规则、不写 DB。

在 `/mnt/h/neu-compass` 下：

```bash
# 需要网络，只生成忽略目录中的来源输入。
.venv/bin/python scripts/capture_course_requisites.py --dept cs --dept ds --dept info --catalog-year 2026-2027 --output-dir data/raw/course_requisites

# 离线，只核对输入并将显式选择的课程结构输出到 stdout。
.venv/bin/python scripts/audit_course_requisites.py --manifest-file data/course_requisite_sources/catalog_2026_2027_manifest.json --source-dir data/raw/course_requisites --course-code "CS 5004" --course-code "DS 5500" --course-code "INFO 6105"
```

转移机器需要受控恢复相同 HTML/sidecar；仅 Git 中的 manifest 不足以复核。重抓不同 bytes 时，先人工检查来源/版次与新结果，再修订公开元数据，不拿新内容覆盖旧摘要文件或跳过检查。

## 离线报告与退出码

`scripts/audit_course_requisites.py` 要求显式 manifest、来源目录和课程列表；不访问网络、不打开数据库、不写报告文件。所有 manifest 输入先校验 SHA/长度/URL/标题/版次/原始 UTC 时间等一致性；重复院系、混合年度、缺失/重复课程、坏来源或选中课程块身份无法识别都失败，不取第一项或只输出剩余成功项。

每条记录含课程代码/名称、年度、未知校区、来源 URL/bytes 摘要/捕获时间、两个 requisite section 和限制警告。错误退出码为：

- `0`：选中课程全部找到，来源一致，没有未解析段；`not_listed` 仍是未知，不是无要求。
- `2`：来源一致、课程找到，但存在 `unparsed`；完整部分报告在 stdout，需要人工复核，不代表全部语法成功。
- `1`：输入/来源/课程身份失败，stderr 给错误，stdout 不输出部分 JSON。

因此 **exit 0 不是个人资格通过**。本次固定输入中的 13 门代表课程做了离线检查，含 CS 5001/5004/5008/5010/5800/6240/5400、DS 5110/5500、INFO 5100/6205/6105/7405；独立预设断言重点核对配套、CS 桥接嵌套组、DS 三组选一加一门必修、INFO 并修许可和未列段。不是三个院系全部课程或全部政策验收。

## 05C-2 独立年度文档与 v1.6

`schemas/course_requisite_document.py` 的 `CourseRequisiteDocument` 保存现有 course ID、精确课程代码/名称、Catalog 年度、完整来源元数据、两个 requisite section、导入 UTC 时间和 `coverage=courseblock_clauses_only`。校区字段只能为 `null`，不会给院系页补猜 Boston。文档年度/部门须与来源一致；`parsed` 树会按语法版本 1 重新解析原文检查一致性，不能把 OR 改成 AND 再重新算 hash 冒充正常文档。`unparsed` 仍允许保存，且必须保留原文、原因和空树。

独立表 `course_requisite_documents` 的主键是 `(course_id, catalog_year)`，外键仅指向**被描述课程**；引用的 lab/先修课程即使不在课程库中，也不会因此删除。相同 scope 更新当前文档，不覆盖其他年度；**不保存同年度全部修订历史**。内容摘要包含来源元数据和逻辑，但不包含导入时间；重复同内容导入不重写记录或原导入时间。

Repository 不自动 DDL、不提交事务、不读本地来源文件。写入前重新校验完整模型，拒绝 `model_copy`/字段修改绕过构造检查；课程 ID/代码/名称须与已有行精确对应。读取再次验证身份、原文/树、摘要；坏记录隔离并计入 `unusable_records`，课程后来更名时也不把旧文档自动绑到新名称。直接调用 Repository 的操作方需承担和同步命令相同的来源核验责任。

## 只在已有私有数据库副本导入

`scripts/sync_course_requisites.py` 要求显式已有 DB、manifest、来源目录与课程列表，默认 SQLite `mode=ro`。数据库拼错不会创建文件。完整来源核验在打开数据库前完成；每个选中源课程必须匹配库中**唯一代码和精确名称**，未知、歧义或更名不跳过、不改 Course 来凑匹配。

`--commit` 才执行独立 v1.6 加表/版本标记和全部选中记录写入，处于同一事务；后续失败会回滚新增表、版本标记和前面写入。需要已有 `courses` / `schema_versions` 基础结构，不负责修复任意坏库。它不重写课程 JSON、metadata、raw_text、状态、search expansion、旧边、旧来源快照、项目/别名或索引，也不访问网络。

先备份并另行准备**私有、已有的数据库副本**。下面路径只是示例，本批没有对真实副本或运行库执行这些命令（只在测试临时库验证）：

```bash
# 在 /mnt/h/neu-compass 下；先完成上面的来源报告，再只读检查副本。
.venv/bin/python scripts/sync_course_requisites.py --db-path /tmp/neu-compass-requisite-rehearsal.sqlite3 --manifest-file data/course_requisite_sources/catalog_2026_2027_manifest.json --source-dir data/raw/course_requisites --course-code "CS 5004" --course-code "DS 5500" --course-code "INFO 6105"

# 人工确认副本路径、唯一代码/精确名称、报告和来源后，才在同一副本提交。
.venv/bin/python scripts/sync_course_requisites.py --db-path /tmp/neu-compass-requisite-rehearsal.sqlite3 --manifest-file data/course_requisite_sources/catalog_2026_2027_manifest.json --source-dir data/raw/course_requisites --course-code "CS 5004" --course-code "DS 5500" --course-code "INFO 6105" --commit
```

同步 JSON 报告给出 `records`、`unparsed_sections`、执行前的 `schema_missing`、`committed`、`would_store` 和 `stored`。同步 exit 0 只表示本次只读检查/写入成功；允许保留未知条款，因此它与离线审计的 exit 0/2 **含义不同**。有 unparsed 的文档也可显式提交，报告会计数、页面显示未知，不能据 exit 0 宣称全部语法或个人资格通过。晚期失败 exit 1，没有事务提交。

## 课程详情 API 与年度选择页面

- `GET /course/{id}` 保留旧字段，新增 `course_requisites` 列表状态。持久化 `schema_version` 仍为 Course 的 `1.1`，不是 DB 的 `1.6`。
- `GET /course/{id}/requisites?catalog_year=2026-2027` 支持精确连续年度筛选；不传年度返回所有可用文档，但不自动选一份。无匹配返回空列表，不回退最新版本/旧边；未知课程 404，非法或不连续年度 422。
- 状态包含 `schema_available`、`has_any_stored_records`、`documents`、`unusable_records` 和限制警告。`has_any_stored_records` 包括其他年度/损坏原始记录，防止筛选无结果后重新启用旧资格图。
- 缺表仅返回不可用，不在 GET/UI 自动迁移；缺文档明确提示未知。损坏记录不对外返回，也不算“没有要求”；坏表结构明确不可用，不自动修复。
- 页面选择默认留空，选择后展示原 AND/OR、成绩、level/并修说明、分开的共修、未解析整段、source URL/SHA/UTC 时间。原文/原因/树为纯文本，不把来源字段变成任意 HTML/链接。年度不等于个人适用性；页面不生成资格/学期安排。
- 有任何结构化记录或已存在但不可读的表结构时，页面不回退旧平铺图（即使没选年度、记录未列段/未解析或全部损坏）。缺表/没有任何记录/旧 API 时，仅保留标明“未核验，仅供导航”的旧图和按钮，不把 `required` 边变成共同必修断言。

API 为兼容旧客户端继续返回旧 `prerequisites` 列表；**新的限制并不替旧客户端自动保证正确解读**，发布需同步更新读取端。结构化规则只用于详情，不接入 chat/prompt/第一学期捷径，因此原回答输入的旧逻辑警告仍有效。

## 05C-3 描述关键词证据（不是批准或资格规则）

`description_evidence` 是课程年度文档的新增可选字段，来源仍为**同一份已验证的课程块 HTML**。报告/显式同步从所有 `p.cb_desc` 逐段记录完整文本，只统一空白，不从旧 `Course.raw_text` 或只含第一段的历史 JSONL 补猜。常规 `CatalogEntry`、旧课程描述和来源快照 hash 不变。`coverage=courseblock_clauses_only` 仍限定结构化先修/共修树；新增描述是未解释的文本证据，不扩张为完整政策覆盖。

状态明确区分：

- 字段 `null`：旧文档未捕获描述证据，不自动升级为已检查。
- `not_listed`：所记录课程块没有非空 description 段；条件未知。
- `no_keyword_match`：完整记录的描述没有匹配当前有限关键词，**不是没有资格条件**。
- `review_needed`：出现 permission/consent、approval/approved、admission/admitted、eligible/eligibility、restriction、registration/enrollment 或 qualification 等关键词候选。候选引用段落索引与标记，整段保持；**不提取强制性、不判断否定/批准是否生效、不把“可申请”当作已获许可**。

候选有意保留假阳性：CS 6240 的“可申请教师许可”、CS 5500/5600 的 MS admission 或 transition courses、CS 6954 的 eligible，以及 INFO 7225 教学描述中的 financial approval process，用途不同。后者是教学内容，不会变成注册批准条件。没有关键词也可能存在未覆盖的条件表述。模型检查段落、候选索引/标记/状态一致性；最多 30 段、单段 20,000 字符、总计 60,000 字符，超限整体失败，不截断后声称完整。

API 返回证据，页面把候选和所有段落作纯文本展示，来源指纹/年度/捕获时间仍取课程来源。审计的 `unparsed_sections` 和 exit 0/2 仍只统计先修/共修语法；描述候选可能随 exit 0 返回，**exit 0 不是批准、描述语义全部解析或资格通过**。同步 exit 0 的含义也仍只是检查/写入成功。

### 旧文档摘要与显式更新

仅新增空默认 `description_evidence=null` 不参与内容 hash，保持独立重构的旧 05C-2 摘要可读、幂等和原导入时间；非空证据全部参与摘要。显式来源同步可把同年度旧文档更新为已捕获描述，第一次有变化、重复零变化；不在 GET/页面自动重抓或写库。仍用现有 v1.6 JSON 表，未增加 v1.7、不重写旧课程/边/索引。Repository 不复核本地 HTML 真实性，调用方仍需承担来源预核验责任。

## 同年度培养方案上下文（读取时关联）

详情和年度接口的 `program_contexts` 是**读取时**独立状态，不写进课程文档或课程来源 hash。只为可用课程文档年度，查同年度 `program_plans`；验证原 plan ID、完整 scope、模型和内容摘要后，仅返回 `source_checked` 且明确以 `course` 叶子或未排除的有限 `course_codes` 候选列出本课程的方案。开放科目前缀、编号范围、文本标签不匹配；可选分支仍保留其激活条件，有限候选不变成共同必修。

状态含 `schema_available`、`plans`、`unusable_records`、`unreviewed_records`、`warnings`。坏记录计数针对同年度行，无法安全恢复其相关性；无匹配不是没有项目/学校政策。缺表/坏表/坏记录/草稿明确区分，不自动迁移、修复或回退旧 seed/其他年度。表约束损坏导致重复 ID/scope 时整组上下文隔离，不取第一份。未选课程年度或无可用课程文档时，不猜一个方案年度。

页面另设默认留空的项目／校区／路径／concentration 选择，年度切换不会自动沿用路径；同时列出不同 scope，不推断个人 Boston/Align/Bridge 适用性。选择后展示**完整方案片段**（含分组、可选、未建模和来源），不是将所有条件套到本课。项目成绩条件与课程先修成绩用途可能不同，不取较高值覆盖原文，也不判断个人成绩或入学 Spring/Fall 适用性。例如 CS Align 桥接每门 B 条件与课程先修 C- 应保留各自作用；INFO Bridge 核心 C 的毕业条件与单课先修可能更高也不能合并。

05C-3 在已有 2026-2027 固定输入核对 17 门课程与 7 份方案片段；另确认 Align 的 B/项目决定例外、INFO Bridge 的核心 C/先修可能更高原文，未抓新的学校政策。无匹配的 INFO 6105/7405/7225 仍未知。当时样本 DS 4996 的 `(1-4 Hours)` 不受标题解析支持，报告整体失败；未用其他课程冒充 DS 4996。该范围标题限制已由下面 05C-4 修正，仍不代表 DS 4996 的个人资格已核验。

## 05C-4 范围／小数标题学分证据

`schemas/catalog_credit_hours.py` 的 `CatalogCreditHours` 记录 `raw_text`（原标题括号内学分文本，仅统一空白）、`kind=fixed/range` 和精确 `minimum/maximum`。小数使用 `Decimal`，JSON 返回十进制字符串，例如 `"1"`、`"4"`、`"3.5"`，不经浮点舍入。支持整数/零/小数、`Hour/Hours`、`-`/`–`/`—` 范围分隔符；保留等端点范围为 range，不改写成固定值。原文／类型／上下限须一致，沿用当前 0–12 边界、最长 100 字符；反向范围、负数、超限、多段范围、OR/分数/指数、TBA、错误单位或其他未知写法拒绝，不截断、不自动补值。

纯课程块解析器现在接受范围标题、保留精确代码/名称（包括代码后缀和名称内部句点），不再丢弃这类课程。`CatalogEntry.credit_hours` 是新增可选证据，旧 JSONL 默认为 `null`。既有 `credits` **仍是整数或 null**：只对明确固定且为整数的 literal 赋值（含 0）；小数和所有范围都为 null，不取端点/平均数，不把接近整数的小数舍入。新 JSONL 若同时提供矛盾的固定 `credits` 和 literal，模型拒绝。

院系批量解析继续逐块跳过坏标题；显式离线报告只要选中标题不合法，就整批失败而非部分成功。范围可识别不意味着先修语法全部可解析：仍保留未列段／未知整段／完整树各自状态，不放宽外部课程代码或资格语法。同步仍先验证来源和所有身份再开数据库、默认只读、显式 `--commit` 原子写入；坏范围在开 DB 前失败。

年度文档新增可选 `credit_hours`，来自同一份已验证课程块。旧 05C-2/05C-3 的空默认字段不入内容摘要，独立重构旧 hash 验证可读/幂等、不重写原记录；非空 evidence 整体入 hash。使用既有 v1.6 JSON 表，无新迁移，不在 GET/页面自动捕获。读取/写入重新检查 raw literal 与上下限，重新算 hash 也不能把 `1-4` 偷改成 `1-5`。

课程详情／年度 API 原字段保持，新增 literal 只在年度文档中返回。页面在明确选年后区分“未捕获”“目录固定值”和“目录范围”，显示原文、实际班次学分未声明、不确认个人学位计入。**旧详情若有整数，也不能视作该范围的选定班次学分**。不重写 Course 的整数 credits，不做范围筛选、学分求和或学期规划，不把目录范围当成可任意选择的学分值。

常规新抓取 JSONL 会带 literal；普通摄取仍写 Course v1.1 和 v1.4 的旧整数/null 字段，本批没有执行生产摄取。v1.4 快照格式与固定课程既有 hash 不变，**v1.4 不保存精确范围／小数 evidence，也不能区分仅 literal 改动**；完整 literal 通过独立 v1.6 命令保存，不宣称全部旧客户端已自动支持新字段。API/UI 发布需同步更新。

固定 2026-2027 输入的全部 **35 个范围标题**（CS 13、DS 10、INFO 12）逐项对照原始上下限，再与前批 17 门固定课程合并为 **52 份文档**进行只读契约检查，未开 DB／重新抓取。DS 4996 确认为 Experiential Education Directed Study、`1-4 Hours`；description 的 approved/restricted 保留候选，但未列先修／共修段依旧未知，不推断可注册。DS 7995 的 Project `1-4 Hours` 也保留范围，不自动替培养方案的附加学分条款选一个值。合并报告中 **1 个 unparsed**：CS 4992 原先修含旧式外部代码 `CIS 310M`，整段保留，未输出部分树，审计 CLI 应 exit 2 而非声称全部语法通过。

## 兼容与下一入口

旧 `CatalogEntry.prereqs`、`Course.prereqs`、v1.4 来源快照和其 hash 不变；常规课程摄取仍只写旧平铺字段，**新树通过独立显式命令导入，不随普通摄取自动更新**。旧边仍不能表达 OR / 成绩 / 共修，旧回答警告继续有效。OR 是任选规则，不等于把各条边改成 `recommended`；05C-1 仅修正旧回填说明，行为不变。

05C-2 的年度存储、原子导入和选择展示，05C-3 的 description 候选证据与同年度方案上下文，以及 05C-4 的范围标题与 literal 证据均在本地完成；仍未解释批准/资格语义或覆盖完整学校政策。政策层已扩展至 05D-4；05E 再复核冻结的 52 门样本与七份方案，保留唯一 unparsed 和未知，见 [第五批验收与缺口清单](fifth-batch-acceptance.md)。有限证据功能阶段收束，下一入口为第六批本地分享／反馈；DS Align 明确年度来源继续待核验。规则树回答和可靠学期安排后续单独接入；生产备份副本演练、真实浏览器/模型验收与发布需另行确认。

自动测试使用合成小 HTML、已有 2026-05-03 历史快照、隔离数据库、临时来源目录/真实离线 CLI 和真实 Streamlit 无头选择组件；历史 fixture 不自动升级为当前 edition。05C-3 增加原文否定/可选/假阳性、旧摘要兼容、同年度精确关联/草稿/损坏隔离、两级选择清空和纯文本展示；05C-4 再补 literal 范围/精确小数/坏标题与上下限、旧 JSONL/两代摘要、隔离摄取/只读同步/未知保留、API 和真实学分展示组件回归。固定真实输入只读检查累计 52 门课程/7 份方案（不打开 DB），不是全部院系政策或个人资格核验。不包含真实 Gemini、OAuth、完整浏览器/应用布局、生产数据库或课程索引验收。
