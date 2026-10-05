# 版本化培养方案规则：05A、05B-1 与 05B-2 本地实现

本功能保存、选择和显示规则文档，**不是注册、毕业或学期规划资格判定器**。05A 建立版本化容器和三个核心片段；2026-10-01 的 05B-1 补五份普通 MS 广度/选修/出口规则及来源输入固定，05B-2 再补独立的 CS Align 与 INFO Bridge。第五批完整政策、DS Align 的适用来源和真实先修核验仍在进行。

## 身份与适用范围

一份文档的身份由 `program_id + campus + catalog_year + pathway + concentration` 确定：

- `program_id` 指现有项目家族，不以课程前缀作为唯一身份。
- `campus` 是显式校区，本批样本为 `boston`。
- `catalog_year` 是连续学年的目录版次，如 `2026-2027`，不等于自然年或 Spring/Fall 入学学期。
- `pathway` 必填，区分 `standard`、`align`、`bridge`；本地有 CS Align 和 INFO Bridge 样本，不意味着每个项目家族都有这三种路径或对应数据。
- `concentration` 单独记录；未限定共同部分与 `general` 等明确范围不混为一项。

用户仅确认 Boston。2026–2027 是本次官方对照样本，**未确认任何学生的个人适用年度、路径或 concentration**。不自动选择最新年度，不把旧生映射到最新方案，也不从课程编号推断推荐学期。

原 `Program`、`program_required_courses`、`course_prerequisites` 和 `data/program_seed/` 保留。旧 seed 的校区、年度与路径未知，仍标为未核验；没有自动升级为新规则或 verified。

## 规则与来源契约

`schemas/program_plan.py` 中的 `RequirementNode` 保留递归逻辑：

| 类型 | 含义 |
|---|---|
| `course` | 单门课程，包括尚未进入课程库的配套 lab/recitation |
| `all_of` | 所有分支均需满足（AND） |
| `any_of` | 满足任一分支（OR），不会平铺为共同必修 |
| `select` | 候选池中的组选；门数、学分、领域下限分别保存 |
| `optional` | 条件明确的可选分支；只有选择该选项时才考虑子规则，不是共同必修 |
| `condition` | 文本条件，尚未自动判定，如成绩、审批或资格限制 |
| `unmodeled` | 明示缺失部分，不以空列表暗示没有要求 |

节点拒绝不相容字段、重复候选和不可能的门数下限。领域数约束需完整、不重叠的候选领域划分；不支持用一门课同时凑多个领域。单份文档最多 120 个节点、8 层。学分可行性、重用规则、成绩、免修、先修资格、开课学期和审批均**未计算**；语法通过不代表业务条件已经核实。

05B-1 的 `select` 同时支持有限 `course_codes`、`subject_codes` 和 `course_ranges`，候选集合取并集，再排除 `excluded_course_codes`。范围仅允许同科目的有序四位数字端点，不含后缀排序、不允许重叠；不表示每个数字都有真实课程或当期开课。科目前缀不表示本科/研究生级别、先修或批准自动满足。领域下限仍只允许明确列举的有限候选，不用一个开放前缀冒充完整领域划分。`optional` 必须有非空 `activate_when` 与一个子规则，条件仍由人核实，不自动激活。

来源需显式 HTTPS 官方 graduate catalog URL、来源版次、标题、摘录、日期与说明；归档 URL 的年度和文档年度必须一致。`source_checked` 必须有对照人及日期。`complete` 只允许已对照且无 `unmodeled` 的文档，仍只是导入方的完整性声明，不是系统已证明覆盖整份 Plan of Study。

`content_hash` 是策展 JSON 的稳定语义摘要，**不是网页原文摘要**；新增能力的空默认字段不参与摘要，保持已存 05A 文档可读和幂等。非空新规则和来源指纹参与摘要。URL、字段和摘要检查不证明来源真实、网页当前有效或个人适用性。05A 只有短摘录；05B-1/05B-2 新规则另有 `source_html_sha256` 指向完整来源输入的字节摘要。

## 05A 保留的三个核心片段

文件：`data/program_plan_seed/boston_2026_2027_core_fragments.json`。三份均为 `partial`、`standard`，摘录/对照日期 2026-10-01；`checked_by=codex-source-crosscheck` 表示此次网页片段对照，不是学生、导师或项目办公室审批。

| 范围 | 已表达部分 | 未完成部分 |
|---|---|---|
| CS 普通 MS | CS 5010 与 5011、CS 5800 的 AND 核心关系 | 广度完整领域/候选、选修、总学分、成绩与其他毕业条件；Align |
| DS 普通 MS | DS 5110、算法二选一、机器学习二选一、DS 5500；核心 GPA 条件文本 | concentration、完整选修/总学分、Co-op 等；Align |
| INFO 普通 MS、general | INFO 5100 与 0 学分 INFO 5101 配套；核心成绩条件文本 | 其他 concentration（含 medical 替代）、完整选修、coursework/project/thesis 出口 |

对照来源：[普通 MSCS](https://catalog.northeastern.edu/graduate/computer-information-science/computer-science/computer-science-mscs/)、[MSDS Boston](https://catalog.northeastern.edu/graduate/university-interdisciplinary-programs/science-data-ms-bos/)、[MSIS Boston](https://catalog.northeastern.edu/graduate/engineering/multidisciplinary/information-systems-msis/)。短摘录随 JSON 保留；动态链接将来可能更新，不能替代完整归档。

这些文件没有导入任何真实运行库，不创建课程或猜测学期顺序。旧 seed 尚未修正为完整官方方案。

## 05B-1 的五份扩展规则与固定来源

新增 `data/program_plan_seed/boston_2026_2027_extended_rules.json`，全部仍为 `partial`、`standard`，不是完整个人 Plan of Study：

| 范围 | 新增内容 |
|---|---|
| CS 普通 MS | 完整列出的 25 个广度候选及三个领域；3 门/12 学分/至少 2 领域；12 学分选修的明确代码和编号范围；总学分/GPA 条件；选择 thesis 时的委员会条件与 GIEL 条件 |
| DS Computer Science | 独立 concentration；16 学分选修候选，选修 project/thesis 不变共同必修；可选 Khoury Co-op |
| DS Data Design and Visualization | 独立 CAMD concentration；两个 8 学分组选保持独立；可选 CAMD Co-op |
| DS Engineering Theory and Modeling | 独立 Engineering concentration；4 + 12 学分组选保持独立；可选 Co-op 准备与经历组合 |
| INFO general | Coursework/Project/Thesis 三选一，分别保存固定课程和两类选修学分；科目前缀及明确排除项；thesis 提交流程和可选 Co-op 条件 |

总学分、GPA、DS 不足 4 学分选修的配套项目脚注等仍是文本条件，未计算跨组重用、附加学分、批准或个人资格。INFO `general` 是本地未选 medical concentration 的范围标签，不是官方 concentration 名。Medical 替代、Bridge、GIEL 联读的完整路径不在该 scope。

CS/INFO 沿用 05A 的 ID/scope 更新内容；三个 DS concentration 有各自新 ID/scope。导入不会删除原 DS 共享核心片段，也不把它自动归到某个 concentration；若副本先导入 05A 再导入扩展文件，将有六份文档而不是五份。

本次实际 GET 三页官方目录后，保存了完整输入 HTML 和逐文件元数据至 **Git 忽略的 `data/raw/program_catalog/`**；文件按 SHA-256 命名，不提交原始抓取数据。随代码的 `boston_2026_2027_source_manifest.json` 仅保存 URL、版次、UTC 时间、长度、标题和摘要，不含网页全文。HTML 摘要针对 HTTP 解码后的正文 bytes，不是传输压缩包或策展 JSON 摘要。

`scripts/capture_program_sources.py` 仅读取通过模型校验的官方 URL，不跟随重定向，要求 HTML、标题/版次符合声明，最大 2 MB。已有同名文件不覆盖，重复内容保留原捕获时间；目录中若先保存了部分合法输入后失败，不自动删除它们。它**不解析生成 verified 规则、不写数据库**。网络/网页变化导致新的摘要时，必须人工检查并更新规则来源、日期及 manifest；重新下载不保证重现本次 bytes，也不能拿新内容覆盖旧摘要文件。

`scripts/audit_program_rule_sources.py` 在固定输入上只读核对本批候选表：CS 广度领域/门数/学分与选修区间；DS 分组选修金额/列表及可选 Co-op 代码；INFO 三出口固定课程、学分、前缀与排除项。未知或歧义结构失败，不猜测。它没有完整核验学院政策、所有脚注、个人资格、课程先修或学期安排，不能把命令成功当成整份方案 complete。

示例（在 `/mnt/h/neu-compass` 下；第一条需要网络，仅生成原始输入，不写 DB）：

```bash
.venv/bin/python scripts/capture_program_sources.py --plan-file data/program_plan_seed/boston_2026_2027_extended_rules.json --output-dir data/raw/program_catalog
.venv/bin/python scripts/audit_program_rule_sources.py --plan-file data/program_plan_seed/boston_2026_2027_extended_rules.json --source-dir data/raw/program_catalog
```

保留私有来源目录才能复核旧规则。新机器只有 Git 中的 manifest 而没有匹配 HTML/元数据时，指纹化导入会失败；应从受控归档恢复对应输入或重新对照修订，不绕过来源检查。

## 05B-2 的独立 Align / Bridge 规则

新增 `data/program_plan_seed/boston_2026_2027_pathway_rules.json`，两份文档仍为 `partial`、Boston、2026–2027；沿用现有 `cs-ms` / `info-ms` 家族，以独立 `plan_id` 和 `pathway` 区分，不覆盖普通 MS scope，也不创建新项目家族。

| 范围 | 已表达的路径差异 |
|---|---|
| CS Align | CS 5001 + 5003、CS 5002、CS 5004 + 5005、CS 5008 + 5009 的桥接组合；项目另定例外与桥接课程 B 或以上条件；独立核心 CS 5800，而不是复制普通 MS 的 CS 5010 + 5011；广度/选修组及 36–44 总学分文本条件 |
| INFO Bridge | INFO 5001、INFO 5100 + 5101、INFO 6215 的核心组合；C 或以上及具体先修可能要求更高成绩的文本条件；12 学分有限 restricted 候选与另 12 学分前缀/明确代码选修；可选 Co-op 准备 AND 经历 OR；36/37 总学分文本条件 |

对照来源：[MSCS—Align Boston](https://catalog.northeastern.edu/graduate/computer-information-science/computer-science/computer-science-mscs-align/)、[MSIS—Bridge Boston](https://catalog.northeastern.edu/graduate/engineering/multidisciplinary/information-systems-msis-bridge/)。不从桥接组合推断第一学期，不决定个人减免。INFO Bridge 不复制普通 MSIS 的 Coursework/Project/Thesis 三出口；该页选修明确排除 CSYE 6220，未列出普通 general scope 的 INFO 5200 排除项，因此两份策展规则保持不同。**没有该排除项不等于任何学生都能注册 INFO 5200**；级别、先修、审批和当期开课仍需核实。

两页实际捕获的完整输入及各自元数据另存于 Git 忽略目录，与 05B-1 合计五页、十个来源文件。`boston_2026_2027_pathway_source_manifest.json` 只含 URL/版次/UTC 时间/长度/标题/摘要。抓取、不可覆盖、私有恢复及指纹导入边界与 05B-1 相同。

离线表格审计新增 CS Align 桥接配套/独立核心、INFO Bridge 核心配套/两组选修/Co-op 结构比对；必修配套不能换成 OR，重复出现在课程标题中的同一代码不重复计数。页面标题/表格空白（含不换行空格）统一处理。它仍不自动核验成绩、减免、总学分计入和完整政策。

```bash
.venv/bin/python scripts/capture_program_sources.py --plan-file data/program_plan_seed/boston_2026_2027_pathway_rules.json --output-dir data/raw/program_catalog
.venv/bin/python scripts/audit_program_rule_sources.py --plan-file data/program_plan_seed/boston_2026_2027_pathway_rules.json --source-dir data/raw/program_catalog
```

截至 2026-10-01，曾用的 [DS Align HTML 路径](https://catalog.northeastern.edu/graduate/university-interdisciplinary-programs/data-science-align-ms-bos/)跳转至 University Interdisciplinary Programs 目录索引。本批没有取得可固定为 2026–2027 Boston DS Align 的对应页面，**没有导入检索到的旧 PDF 或复制普通 DS 规则**；这只是来源待核验，不是该项目已不存在的结论。应取得明确年度的官方页面/Plan of Study 后单独建 scope。

## 存储、API 与界面

v1.5 独立 `program_plans` 表，以 `plan_id` 为主键、完整 scope 为唯一键，外键指向现有项目家族。`plan_id` 不可移到另一 scope；同 scope 不能换另一个 ID 占位。相同 ID/scope 可更新内容，当前每个 scope 仅一份文档，**不保存全部修订历史**。读取时核对 JSON、列身份和摘要，坏记录不对外返回；写入前再次验证模型，避免绕过构造校验。

- `GET /programs` 增加可用 `plan_count` 和旧 seed 警告。
- `GET /programs/{program_id}` 保留旧响应字段，增加 `plans`、`plan_schema_available` 和警告。旧学期列表仍单独展示并标为未核验。
- `GET /programs/{program_id}/plans` 返回 `{program_id, schema_available, plans, warnings}`；可用 `campus`、`catalog_year`、`pathway` 精确筛选。无匹配返回空数组，不退到最新年度或别的路径；无项目返回 404，非法范围返回 422。
- 旧库没有 v1.5 表时返回明确的不可用状态，不在 GET 或 UI 中自动建表。
- UI 版本选择默认留空，选择后显示 scope、原逻辑树、未建模项、来源与对照状态。未知旧 seed 学期不再写成“任意学期可修”。不可信摘录、标签等作为纯文本显示。

对话另有可清空的 `program_id` 项目选择，它**不等于**校区、年度、路径或个人适用方案选择。基础课/第一学期捷径遇到同前缀多个项目时返回 409 要求选择，而不是取第一个；显式项目与检测到的前缀冲突也返回 409。

项目一旦有任何版本化记录，基础课/第一学期捷径不再使用旧 seed 推测学期安排，返回 409 并指向方案浏览。即使记录已损坏或只是 draft，也不会重新启用旧猜测。**本批未把规则树接入 LLM，也没有验证版学期安排**；因此导入后这一类请求会明确暂不可用。其他课程检索与精确引用沿用原流程；只有旧 seed 的项目仍保留未核验的原学期捷径。

06A 的分享框在当前明确选定 `source_checked` 方案时携带确切 ID、完整 scope 与内容 revision；接收方须与当前 API 再次精确核对，过期／缺失／冲突不自动改选新版。未选或 draft 仍只分享家族入口，详见 [版本化方案分享](program-plan-sharing.md)。链接定位属于公共内容选择，不能理解为个人适用性已确认；无有效完整链接时版本选择仍默认留空。

## 只在数据库副本演练导入

`scripts/sync_program_plans.py` 必须指定已有数据库和 JSON 文件。默认 SQLite `mode=ro`，不会创建拼错的数据库路径；`--commit` 才写入。

含 `source_html_sha256` 的文档还必须显式提供 `--source-dir`。导入在打开数据库前验证输入 bytes、manifest、URL/标题/版次/捕获日期一致；缺失/损坏时失败，不降级忽略指纹。无指纹的 05A 核心片段仍保持旧兼容，不能因此宣称它们也有完整来源存档。存储 Repository 自身不读文件，来源预校验由同步命令负责；人工直写必须承担相同对照责任。

先备份并另行准备**私有、已有的数据库副本**。下面 `/tmp/neu-compass-plan-rehearsal.sqlite3` 只是副本路径示例，不是运行库；本批未执行这些演练命令：

```bash
# 在 /mnt/h/neu-compass 下执行；先只读检查，不加 --commit。
.venv/bin/python scripts/sync_program_plans.py --db-path /tmp/neu-compass-plan-rehearsal.sqlite3 --plan-file data/program_plan_seed/boston_2026_2027_core_fragments.json

# 人工确认副本路径、报告与来源后，才在同一副本提交。
.venv/bin/python scripts/sync_program_plans.py --db-path /tmp/neu-compass-plan-rehearsal.sqlite3 --plan-file data/program_plan_seed/boston_2026_2027_core_fragments.json --commit

# 扩展文件需先通过上面的只读来源表格审计；默认仍只读。
.venv/bin/python scripts/sync_program_plans.py --db-path /tmp/neu-compass-plan-rehearsal.sqlite3 --plan-file data/program_plan_seed/boston_2026_2027_extended_rules.json --source-dir data/raw/program_catalog

# 人工确认后，只对已有副本提交。
.venv/bin/python scripts/sync_program_plans.py --db-path /tmp/neu-compass-plan-rehearsal.sqlite3 --plan-file data/program_plan_seed/boston_2026_2027_extended_rules.json --source-dir data/raw/program_catalog --commit

# Align/Bridge 也先只读与来源审计；确认后才在同一副本提交。
.venv/bin/python scripts/sync_program_plans.py --db-path /tmp/neu-compass-plan-rehearsal.sqlite3 --plan-file data/program_plan_seed/boston_2026_2027_pathway_rules.json --source-dir data/raw/program_catalog
.venv/bin/python scripts/sync_program_plans.py --db-path /tmp/neu-compass-plan-rehearsal.sqlite3 --plan-file data/program_plan_seed/boston_2026_2027_pathway_rules.json --source-dir data/raw/program_catalog --commit
```

整批先解析/验证文档；重复 ID/scope、未存在的项目家族或占位冲突失败。提交时 v1.5 加表与所有文档写入处于同一事务，后续失败连前面插入及本次建表一并回滚；重复导入同一文件幂等。若会用较弱版本覆盖已带来源指纹（`source_html_sha256`）或已 `source_checked` 的方案（例如导入 extended 后单独重跑 core），或用更早的抓取覆盖带指纹的较新抓取，整批拒绝（只读运行同样拒绝，一行都不写）并列出方案与原因。只想更新文件里的其他方案时，同步一份去掉这些方案的文件；确需替换它们时显式加 `--allow-downgrade`。完整性校验不通过、甚至新旧版本已校验不过（例如多了新字段）的旧行不对外展示，但仍按它 JSON 里记录的指纹、审核状态和抓取日期判断（读不出抓取日期时只按前两项）：同等或更强的版本可以覆盖修复，较弱的照样拒绝；连这三项都没有的旧行（例如 `{}`）不记录任何来源，可直接覆盖。抓取工具对以前存档过的同一份网页沿用最初的抓取日期，所以网页真的退回旧版本时，同步会以 `drops_newer_capture` 被拒；确认属实后加 `--allow-downgrade`。空 JSON 数组可用于显式的仅 v1.5 加表演练。

报告中的 `records` 是输入数，`schema_missing` 是执行前状态，`would_store` 是预计变更数，`stored` 是提交时实际变化数，`downgraded`（只在加 `--allow-downgrade` 时出现）列出被有意降级的方案。成功时 stdout 只有这份 JSON 报告，库里的告警（例如无法使用的旧行）写到 stderr；被拒或失败时 stdout 是一行说明。脚本不创建项目家族，不改旧培养方案、课程列、先修边或 FAISS/BM25，不执行网络请求，也不代替独立的 v1.3 Co-op / v1.4 课程来源迁移。

提交到副本后应检查 API 的精确范围、缺失警告、界面选择与 409 边界，再安排真实模型/浏览器验收。生产备份、迁移、同步 API/UI 发布和回滚需要另行确认，不能把测试临时库通过当成上线验收。

## 第五批后续入口

05E 已完成当前有限证据功能的整体离线复核，见 [第五批验收与缺口清单](fifth-batch-acceptance.md)。06A 本地完整方案分享范围与安全解析已经实现，最终验证见 [开发修改记录](development-change-log.md)；下一实施入口为 06B 反馈关联。下列个人／完整政策／规划事项仍是缺口，不阻塞第六批本地开发，也不表示已满足生产发布条件。

1. 05D-1 固定原 5 页／14 段落；05D-2 新增选定方案政策只读端点及详情；05D-3 新增 8 页／36 片段；05D-4 新增 5 页及有效期／年度一致性／证书例外 27 片段，当前为 18 页／77 片段（70 段落、7 完整外层列表）与原 7 个精确范围关联，见 [政策证据说明](program-policy-evidence.md)。正文内目录已排除，旧选定片段定位不变。不同章节重修表述不一致保留并要求学术部门确认，不自动选择优先级；有效期不算个人毕业日期。必须明确选择完整方案，失败无片段；不接对话，coverage 仍为 selected_fragments_only。05E 整体验收和缺口清单已完成；完整政策、其他项目例外、跨组重用、medical/GIEL 独立范围及个人批准继续待核。
2. CS Align / INFO Bridge 已有独立 partial 文档；继续核验其未建模条件，DS Align 先取得明确年度来源，不复制普通 MS 规则冒充完整方案。
3. 05C-1 已建立课程先修/共修语法、固定院系输入和离线报告，05C-2 新增独立 v1.6 存储及课程详情 API/UI，05C-3 增加 description 关键词候选证据及同年度方案上下文，05C-4 修正范围标题并保留精确学分 literal（尚未迁移运行库），见 [课程先修说明](course-requisites.md)。上下文只匹配明确课程叶子/有限候选，排除开放前缀/范围/文本推断；必须另选项目/校区/路径，不合并不同用途的成绩条件。DS 7995 等课程的范围学分不是已选学分，不自动求和或据此判定附加项目计入。完整批准/资格语义与学校政策继续未知；旧逐条先修边不代表新逻辑，新规则仍未接入 LLM 或学期规划。
4. 设计规则树回答与可靠学期安排的接入方式。没有开课/个人路径证据时仍不能生成资格保证。

自动化验证包含隔离数据库、真实离线 CLI、API 替身、来源抓取替身和五个真实 Streamlit 无头组件测试；另实际捕获五页目录并做离线课程组合/候选表审计。不涵盖完整浏览器布局、OAuth、真实 Gemini 或生产运行库。05B-2 没有新增 DDL/API 契约，已有精确路径筛选和默认留空的选择组件可以读取新文档。
