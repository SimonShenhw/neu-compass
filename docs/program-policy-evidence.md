# 学校／学院政策证据（05D-1／05D-2／05D-3／05D-4）

这一层是离线、有限范围的来源证据，不是学生资格、成绩、毕业或排课引擎。当前仅关联已存在的 Boston、2026–2027、7 个完整方案范围；未选择个人 catalog term，也不增加 DS Align 或把学院政策自动套给任意课程。

## 本批范围

`data/program_policy_seed/boston_2026_2027_source_requests.json` 当前固定 18 个官方 HTML 章节；`boston_2026_2027_evidence.json` 保存 77 个选定片段（70 段落、7 完整外层列表）的零基位置、最近标题、规范化文字 SHA-256、人工对照摘要与限制，并记录审核者／日期。05D-1 原有 5 页／14 段落保留；05D-3 增量请求 `boston_2026_2027_credit_source_requests.json` 只抓新增 8 页；05D-4 增量请求 `boston_2026_2027_validity_source_requests.json` 只抓新增 5 页，另从既有 CAMD 存档选入 3 段，不重新捕获旧输入。原 HTML 与抓取 sidecar 位于被 Git 忽略的 `data/raw/program_policy_catalog/`，不是可提交的公共规则文本。

| 来源层级 | 本批选定证据 | 未据此推导的结论 |
|---|---|---|
| [学校 Minimum Cumulative GPA](https://catalog.northeastern.edu/graduate/academic-policies-procedures/minimum-gpa/) | 学位累计 GPA、通用 probation、重修表述 | 不把每门课最低成绩写成 B，不代替更具体项目／学院规定 |
| [Khoury Academic Probation and Dismissal](https://catalog.northeastern.edu/graduate/computer-information-science/academic-policies-procedures/academic-probation-and-dismissal/) | 学院 probation、prerequisite／Align bridge 的 standing GPA、core GPA 分开核对 | 不将 eligible for dismissal 写成必然 dismissal，不把 GPA 计入等同于学位学分计入 |
| [CAMD Master’s Degree Policies](https://catalog.northeastern.edu/graduate/arts-media-design/academic-policies-procedures/masters-degrees/) | 学院硕士底线、院外 elective 批准／上限、catalog term 变更 | 不替换 MSDS 项目学分，不按课程前缀判断学院，不自动升级个人年度 |
| [Engineering Academic Standing Policy](https://catalog.northeastern.edu/graduate/engineering/academic-policies-procedures/academic-standing-policy/) | full-time／part-time 与 8 学分条件、夏季评估时点 | progression／申诉列表未结构化，不计算个人学分或身份，不输出 dismissal 结论 |
| [Engineering Course Selection](https://catalog.northeastern.edu/graduate/engineering/academic-policies-procedures/course-selection/) | advisor／开课可用性、prerequisite／本科课计入限制、petition | 不据通用文字删掉 INFO Bridge 列明课程，不保证每年开课，不把申请途径当已批准 |

所有 evidence 的 `coverage` 固定为 `selected_fragments_only`，没有 `complete` 或 `eligible` 字段。`source_checked` 是此样本人工对照记录，不是完整政策覆盖或大学认证。Boston 是关联方案的范围；学校 Course Substitutions 明确分地区流程，样本只选 Massachusetts 一组，不把这一页或其他通用学院页面宣称为 Boston 独占。

## 05D-3：重修、替代、转入与共享

以下 8 页新增 36 个片段，并只追加到原 7 个方案的学校／home-college 关联；原方案 seed、scope 和内容 hash 没有改变。

| 新来源 | 保留的范围／条件 | 不自动推导 |
|---|---|---|
| [学校 Retaking Courses](https://catalog.northeastern.edu/graduate/academic-policies-procedures/retaking-courses/) | nonrepeatable 最近成绩与原记录；repeatable 注册学期描述另行处理 | 不取最高成绩，不抹旧记录，不自动加学位学分 |
| [学校 Course Substitutions](https://catalog.northeastern.edu/graduate/academic-policies-procedures/course-substitutions/) | 批准后替代、Massachusetts advisor／项目／原部门协商流程 | 不套其他地区流程，不把通用要求替代等同成绩补救替代 |
| [学校 Transfer and Other Advanced Standing Credit](https://catalog.northeastern.edu/graduate/academic-policies-procedures/transfer-other-advanced-standing-credit/) | 目标单位裁量、硕士外校条件／advanced-standing 嵌套列表、时间基点、T／GPA | 不把额度当必批、不计算整数上限、不统一不同期限 |
| [学校 Course Credit Sharing](https://catalog.northeastern.edu/graduate/academic-policies-procedures/course-credit-sharing/) | credential 范围、学院批准、时间、具体 credential 条件和例外整个列表 | 不作为同一方案内 core／breadth／elective 重用许可 |
| [Khoury Retaking Courses](https://catalog.northeastern.edu/graduate/computer-information-science/academic-policies-procedures/repeating-courses/) | 单课重修次数／advisor、原记录、repeatable 区别 | 不混成两门课额度或 Engineering 一次重修 |
| [Khoury Transfer of Credit](https://catalog.northeastern.edu/graduate/computer-information-science/academic-policies-procedures/transferring-to-ccis/) | 入学前外校限额及全部条件、开始修课后申请／匹配／committee、在读期间预先批准及 load 条件 | 院外条款与跨学院项目／后续批准流程的关系待学院解释，不删 DS-CS 候选课 |
| [Khoury Credit Sharing](https://catalog.northeastern.edu/graduate/computer-information-science/academic-policies-procedures/credit-sharing/) | 已完成 NEU 学位范围、二次硕士录取与共享分开、学分比例／官方例子／延期、免修不转学分 | 不混课程比例与学分比例，不对个人拒录、不四舍五入成额度，不把免修当获学分 |
| [Engineering Course Retake / Course Substitution](https://catalog.northeastern.edu/graduate/engineering/academic-policies-procedures/course-repeat-substitution-policy/) | good standing／probation 分开、重修前批准／旧课排除、非 core／不能重修的替代、联合批准和 good-standing 限制 | 不套到 CAMD／Khoury，不把本页补救限制扩成所有课程要求替代禁令 |

CAMD 方向只追加学校通用片段，仍保留自身已核 Master’s Degree Policies；本批没有取得新的 CAMD 转入／重修项目例外，不能据“没有选到页面”判定不存在或借用另外两个学院。学校规则和更具体学院／项目表述保持独立，存在不同用途或需解释的条款时明确记录未知，不自动决定优先级。

### 段落与整个列表的定位契约

- `source_kind` 为 `paragraph`（默认）或 `list`；其他类型拒绝。旧字段 `paragraph_index`／`paragraph_sha256` 和返回的 `source_paragraph` 保留，含义是**声明种类**内零基位置、规范化文字指纹及原文块；旧省略种类的段落输入继续可读。
- 段落仍按原 `p` 顺序编号；列表独立按正文内外层 `ul`／`ol` 编号，嵌套列表完整留在父块中，不另建片段、不只摘上限句。列表中的 `p` 仍保留既有段落索引；同一数字的 paragraph／list 不冲突，同种重复位置拒绝。
- 每类最多 300 块、每块最多 20,000 字符；空／超预算块拒绝而非截断，非唯一正文容器拒绝。05D-4 修正正文容器内部导航：先排除 `nav`、`footer`、`role=navigation`、`.onthispage` 整个节点，再编号／找最近标题／读取父列表文字；普通链接与仅有 `notinpdf` 的真实内容仍保留。原 13 页／50 片段的已选位置与指纹核对不受影响。捕获同时检查列表预算，当前仍要求正文有段落，不声称支持任意网页结构。
- 全部 HTML／sidecar 校验后，按种类、位置、标题、文字 hash 核对；即使人为重算归档 SHA，也不能让与既有片段不符的嵌套条件通过。列表是完整原文证据，**不是已经结构化的条件树**；文字空白规范化不保存项目符号／缩进，需核原 HTML 才能检查页面原布局。
- API 继续 no-store／精确范围／失败整组无片段；UI 标明“列表块”而非“段落”，原文保持纯文本，重读坏源不保留成功内容。API 与 UI 需一起发布新字段支持；本批未执行发布。

## 05D-4：有效期、年度一致性与项目例外

新增 5 页共 24 个片段，并从既有 CAMD 原输入新增 3 段，合计增加 27 片段。学校三页只追加到所有既有方案；Engineering 两页只追加到三个 Engineering 范围；CAMD 的 leave／有效期／延期仍仅用于 DS Data Design and Visualization 的 home-college 证据。未新增／修改方案 seed 或 scope。

| 来源 | 保留的范围／条件 | 未据此推导 |
|---|---|---|
| [学校 Time Limit for Course Credit](https://catalog.northeastern.edu/graduate/academic-policies-procedures/time-limit-for-course-credit/) | 项目内取得或获准转入学分最长七年，相关 graduate office 可批准延期 | 不把有效期、transfer 受理窗口和 credential 共享期限合并，不推算个人毕业日期 |
| [学校 Master's Degree](https://catalog.northeastern.edu/graduate/academic-policies-procedures/regulations-masters-programs/) | approved program、最低 30 学分、本科层级限制；NEU 取得且未用于 NEU 学位的既有学分；条件性考试／thesis 与 office 提交日程 | 不替换项目总学分，不混外校取得学分转入，不认定个人获批或所有路径必须 thesis |
| [学校 All Graduate Degree Programs](https://catalog.northeastern.edu/graduate/academic-policies-procedures/regulations-degree-programs/) | major 与 concentration 同年度；选后来新增方向须整体转年度；nonrepeatable 重修表述 | 不自动升级个人年度，不把不同章节重修文字解释成唯一优先级 |
| [Engineering Program Completion](https://catalog.northeastern.edu/graduate/engineering/academic-policies-procedures/program-completion/) | 满意完成全部项目／部门要求；计入学位课程累计 GPA 3.000、required core 至少 C、项目额外要求 | 不合并 standing GPA／core／先修用途，不算毕业资格 |
| [Engineering Certificate Policies](https://catalog.northeastern.edu/graduate/engineering/academic-policies-procedures/certificates-policies-procedures/) | 在读 GSE 申请时点与 good standing、课程完成时点、申请不等于批准；course eligibility／petition；disciplinary 8 学分与完整 16 学分例外、SEIS 16 学分；跨证书／PlusOne／本科已用与额外课的区别 | 不把指定证书／General Mechanical concentration 例外扩大到所有项目，不按前缀判断 SEIS 或个人适用，不等同同一方案内跨组重复计入 |
| [既有 CAMD Master’s Degree Policies](https://catalog.northeastern.edu/graduate/arts-media-design/academic-policies-procedures/masters-degrees/) | 完整 leave 段及 medical 例外；学分七年；延期 petition、剩余要求计划、逐门内容未变确认、部门向 CAMD 建议批准 | 推荐不是最终批准，medical 例外不是自动延期，不推算个人 deadline 或提供医疗／移民判断 |

特别记录：All Graduate Degree Programs 写最多两门 nonrepeatable、同一门最多重修一次；Minimum Cumulative GPA 写两门或六学分取较大者；Khoury Retaking 写同一课程可重修两次。原文和各自用途分开展示，三个对应限制字段均提示表述不一致、须向学术部门确认；没有自动取宽／严规则，也没有替用户判定适用优先级。

证书页的境内／国际身份分支列表未选入；完整学院政策、个人校区／身份／获批证书、每门课实际计入记录仍未知。保持 `selected_fragments_only`，不是完整证书或个人注册指南。

## 精确关联与来源检查

每个 `PlanPolicyLink` 同时指定 `plan_id`、家族、校区、年度、路径、concentration、当前方案 `content_hash`、home college 与选定 policy IDs。方案文本或审核日期变化会让既有关联失效，需重新核对，不能只复用稳定 ID。

- MSCS 普通／Align：从通过字节核对的项目页 breadcrumb 检查 Khoury 名称与链接。
- MSIS 普通 general／Bridge：同样检查 Engineering breadcrumb。
- MSDS 三个方向：独立检查项目 overview 中对应方向的学院映射列表，不从 `DS` 前缀或共用 core 推断。官方项目页明确方向所属学院及 home-college 政策关系，见 [Data Science, MS (Boston)](https://catalog.northeastern.edu/graduate/university-interdisciplinary-programs/science-data-ms-bos/)。
- 政策 URL 必须是声明 authority 下的官方 graduate policy 子章节，来源年度与关联年度一致；archive URL 的年度也要一致。不接受跳转、其他 host、非 HTML 或超预算输入。
- 离线审计先验证所有政策 HTML／sidecar 的完整 SHA、字节长度、URL、标题、年度、完整捕获时间，再核每个选定段落的位置、标题和文字指纹，以及关联方案的原始存档、完整 scope 与 revision。导航／页脚不能当正文段落；重复身份／位置／scope 拒绝。

学校通用政策、学院政策、项目 core／bridge 成绩、课程先修最低成绩仍彼此独立。这里没有自动决定优先级、取成绩阈值最大值、合并期限、共享候选池或求和。

SHA 一致只证明本地输入一致，不证明来源真实性，也不证明人工摘要语义正确；摘要与限制须对照对应原段落复核。审计输出的 `source_paragraph` 只来自选定输入，不是已执行规则。退出 0 表示有限证据一致，不代表全部学院政策已核完。

## 抓取与只读审计

在 `/mnt/h/neu-compass` 下执行。抓取只添加不可变私有输入，重复内容保留首次捕获时间；已有 HTML／sidecar 冲突时保留已有内容，不覆盖。抓取不会自动生成 checked 摘要或修改方案文件。

```bash
.venv/bin/python scripts/capture_program_policy_sources.py \
  --request-file data/program_policy_seed/boston_2026_2027_source_requests.json \
  --output-dir data/raw/program_policy_catalog

.venv/bin/python scripts/audit_program_policy_sources.py \
  --bundle-file data/program_policy_seed/boston_2026_2027_evidence.json \
  --plan-file data/program_plan_seed/boston_2026_2027_extended_rules.json \
  --plan-file data/program_plan_seed/boston_2026_2027_pathway_rules.json \
  --policy-source-dir data/raw/program_policy_catalog \
  --program-source-dir data/raw/program_catalog
```

审计不联网，不打开 SQLite，无 `--commit`；全部核对成功后才向 stdout 输出 JSON。坏输入退出 1，只向 stderr 报错，不产生部分“已核验”报告。私有存档缺失时失败，不重新抓取／使用最新页面／绕过指纹。

当前公开 bundle 固定于本次抓取内容；未来页面变化会产生新的字节指纹，需人工审核新的 paragraph 位置和摘要，再更新 bundle。只重跑抓取不更新公共证据文件。

## 05D-2：选定方案的只读 API／详情

新增公开只读端点：`GET /programs/{program_id}/plans/{plan_id}/policies`。它仅接受该家族当前可用的确切方案 ID，不从家族前缀、别的路径、同 scope 的其他 ID 或旧 JSON seed 推测。未知家族／方案、旧库没有方案表或坏方案记录返回 404，不加载政策文件，也不自动建表。

有效方案返回独立 `ProgramPolicyView`：`plan_id`、完整 `scope`、当前 `plan_content_sha256`、`status`、固定有限 `coverage`、`warnings`；只有 `ready` 才包含 `link`、政策对照者／日期、精确选定政策与段落原文。其他状态不能携带可用证据。HTTP 200 的这些证据状态使用 `Cache-Control: no-store`，不是 `/ready` 健康检查结果。

| 状态 | 含义 | 显示／回退行为 |
|---|---|---|
| `ready` | 选定来源与段落、方案 revision／范围、home-college 关联的一致性核对通过 | 只展示选定片段；不表示个人政策条件达标或完整政策已核完 |
| `not_linked` | 这个确切方案 ID 没有显式关联 | 无片段；不找同家族／方向或最新年度来替代 |
| `draft` | 当前方案未完成来源对照 | 不读取政策来源，也不复用旧证据 |
| `stale` | 关联 scope、方案内容 hash 或审核日期不再对应当前方案 | 无片段；须重新核对关联，而不是按 ID 自动跟随版本 |
| `unavailable` | bundle／政策／项目源缺失或不可读取 | 无片段；不会抓取网页、补文件或使用缓存 |
| `unusable` | bundle、来源或段落校验失败 | 无片段；不输出整组关联中的部分“可信”资料 |

`ProgramPolicyReader` 每次有界只读加载 bundle，并核对本次所选方案的所有关联政策及其项目原存档；不核对未选定学院的原始文件。bundle 的整体模型仍须有效，重复／错误声明会阻止所有选择，但未关联到当前方案的原始页面缺失不会阻塞当前证据。与整批离线审计不同，这不是对全部 7 个方案的覆盖证明。

无有效完整分享链接时，详情浏览默认不选方案、不请求政策。用户手动选定完整范围，或 06A 的完整链接按当前 API 精确核对后选择，才加载；客户端再次核对方案 ID、scope、当前内容 hash、来源字段／原段落指纹与审核状态。公共链接选择不是个人适用性确认。API 的新版本不能被套给旧界面缓存中的方案，失败时只显示固定警告，原规则树及旧 seed 浏览仍保留。

新增“刷新方案及政策证据”按钮：清除**当前家族**的 curriculum 缓存和方案选择，重新加载后必须明确选择一次，不自动恢复旧选择，也不重新应用同一个已消费的完整分享链接。清空选择、重复／失效 ID 或重复 scope 都不再显示政策；故障或无效 JSON 不保留此前成功的内容。06A 可分享当前选定且已对照方案的完整 scope／revision；未选或 draft 仍为家族入口，见 [版本化方案分享](program-plan-sharing.md)。政策 reader／状态与私有来源契约不因链接成功改变。

摘要、限制、原段落、标题、reviewer 等一律作为纯文本，只有已由 schema 核验的官方 URL 使用固定 Markdown 链接。页面分别标明学校与 home college，显示捕获时间、来源 HTML SHA、段落位置／标题／SHA 和审核记录，不合并条件、不排序成绩阈值、不计算 GPA／计入学分／资格。

### 文件配置与私有输入

- `PROGRAM_POLICY_BUNDLE_PATH`：默认项目 `data/program_policy_seed/boston_2026_2027_evidence.json`，只是可核对样本，不是个人适用默认值。
- `PROGRAM_POLICY_SOURCE_DIR`：默认 `<SQLITE_PATH 所在目录>/raw/program_policy_catalog`。
- `PROGRAM_CATALOG_SOURCE_DIR`：默认 `<SQLITE_PATH 所在目录>/raw/program_catalog`。

后两项显式设置时覆盖默认；默认跟随已解析的 SQLite 数据目录，不硬编码开发机路径。`SQLITE_PATH` 若为相对路径，仍沿用其按启动 cwd 解析的既有行为，不另设一套 raw 相对路径。API 只读这些目录，UI 不读取本地原 HTML。原始存档仍被 Git／Docker build 忽略，未来发布必须显式准备已核对的输入／目录；缺少时返回 `unavailable`。本批未拷贝私有存档到 NAS、未部署或改 compose。

## 未接入／后续

05D-1 建立独立源证据，05D-2 新增独立只读端点和详情，05D-3 扩展选定政策与列表源支持，05D-4 补有效期／年度一致性／项目例外并排除正文内目录；四批均没有修改 `ProgramPlan` 字段、已有方案 JSON seed／hash 或 v1.5／v1.6 数据库。政策不会进入旧培养方案导入、LLM 检索／回答、课程先修或学期规划。未写运行库、索引、query_log 或部署。

已补重修／替代／转入／跨 credential 共享／学分有效期与部分项目例外的有限片段。05E 已完成 [第五批整体离线验收及缺口清单](fifth-batch-acceptance.md)，有限证据功能阶段收束；06A 本地完整方案分享已经实现，最终验证见 [开发修改记录](development-change-log.md)，下一入口为 06B 反馈关联，不是宣布完整政策已核完。完整学院政策、其他项目例外、同一方案内跨组重复计入、个人 catalog term／POS／批准、实际课程和 section availability 仍需独立核验；没有这些证据不能接成资格保证或自动学期安排。部署、私有来源恢复／数据库副本演练仍须单独确认。
