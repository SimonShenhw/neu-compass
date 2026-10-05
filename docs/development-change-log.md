# 开发修改记录

本文件持续记录 2026-09-30 项目检阅之后的改动。每批包含范围、文件、验证和发布状态；未完成项不记作已完成。

## 推进顺序

| 批次 | 范围 | 状态 |
|---|---|---|
| 01 | 发布验收：readiness、失败退出、UI 与分享解析检查 | 本地完成并验证；未部署 |
| 02 | 检索分支：显式筛选一致性、专业前缀与拒答规则 | 本地完成并验证；未部署 |
| 03 | Co-op：待审核收集、不同贡献者门控、去重奖励 | 本地完成并验证；未迁移运行库、未部署 |
| 04 | 回答依据：官方课程描述、来源与数据缺失提示 | 本地完成并验证；未回填运行库、未部署 |
| 05 | 培养方案与先修语义：版本、校区、AND/OR 条件 | 本地有限证据阶段收束：05A 至 05D-4 已验证，05E 整体离线复核完成并列明缺口。7 份路径文档仍 partial；课程 52 门样本保留 1 个 unparsed，政策 18 页／77 片段须显式选定方案，未接对话或资格计算。DS Align／完整政策／个人 POS／实际班次继续待核；未导入运行库，不等于完整方案或生产验收 |
| 06 | 分享上线、反馈关联、登录全链路与小范围分发 | 06A／06B／06B-2／06C-1 至 06C-4 本地完成并验证；06C-4 组合专项 241／最终全套 2288 项通过，新增 77 项。三组显式来源→副本文档只读核验；合成迁移与本地比对不等于真实备份恢复、完整来源或生产审批。凭证处置、真实账号、生产部署、留存及分发仍需本人确认 |
| 07 | 独立评测、耗时拆分、限流与性能实验 | 07A／07B／07C 本地完成并验证；07C 专项 100／最终全套 2574 项通过，新增 100 项。单进程总量门禁、并发 503 与限流 429 严格 Retry-After、前端友好提示与断流保护；默认关闭、无 IP 追踪。真实性能实验／现场 probe 尚未启动，下一批次 08 |
| 08 | 增量更新、索引版本、生产依赖锁定、CI 与恢复演练 | 本地完成并验证；全套通过，未部署 |

## 01 — 发布验收修正（2026-09-30）

### 范围与原因

- 修改前的 `/ready` 在未就绪时仍返回 HTTP 200，`curl -f` 和状态码检查可能误判成功。
- 远端 compose 命令接 `tail` 管道，可能以 `tail` 的成功退出码掩盖 compose 失败。
- readiness 超时原来只打印警告，随后仍显示部署完成；验收也没有检查 UI 和分享链接解析。

### 修改文件

| 文件 | 修改 |
|---|---|
| `api/routes/health.py` | 未就绪返回 HTTP 503，保留 warming JSON 与计数字段；就绪仍为 200，liveness `/health` 不变；OpenAPI 声明 503 |
| `scripts/deploy.ps1` | 移除远端 `tail` 管道，前台显示 compose 输出并保留失败码；校验 ready JSON、非空索引、UI 200/ok、CS-5800 分享解析；超时退出 1；新增可配置验收超时；使用 UTF-8 BOM，防止 Windows PowerShell 5 误读新增中文注释 |
| `tests/test_api_health.py` | 覆盖缺失组件、空索引、未设置 ready、可选 reranker 降级和 OpenAPI 契约 |
| `tests/test_deploy_script.py` | 模拟 SSH、HTTP、时间与等待，验证失败退出、瞬时故障重试和全部验收步骤；增加 Windows PowerShell 5 兼容回归；不执行任何真实网络操作 |

### 验证记录

- 修改前基线：本地 HEAD `bb2f6e3`，工作树干净，991 项测试通过。
- 回归有效性：新增健康接口断言在旧实现上得到 8 failed / 5 passed；修复后该文件 13 passed。
- 部署离线场景：PowerShell 7 和 Windows PowerShell 5 均通过 12 个场景，覆盖成功、瞬时 503 恢复、compose 失败、200/warming、空索引、空 BM25、非法 JSON、持续 503、网络失败、UI 异常、解析路由缺失和空匹配。
- 最终全套测试：`wsl.exe -d Ubuntu-24.04 -e bash -lc 'cd /mnt/h/neu-compass && .venv/bin/python -m pytest tests/ -q'` → **1012 passed, 6 warnings in 31.02s**。新增 21 项回归全部执行，无跳过；6 个警告仍为现有 SWIG / HTTP 422 常量弃用警告。
- PowerShell 7 与 Windows PowerShell 5 的脚本语法检查通过；`git diff --check` 通过。
- Ruff 未执行：现有 WSL 虚拟环境与离线工具缓存均无 Ruff，本批未为 lint 安装新依赖；不宣称仓库 lint-clean。
- PowerShell 测试在有 PowerShell 的环境执行；没有 PowerShell 时 pytest 明确跳过，不以跳过冒充验证。
- 离线测试只为测试子进程设置 ExecutionPolicy Bypass，不修改机器或用户的执行策略。

### 发布状态与边界

- 仅本地修改；未提交、未推送、未部署 NAS，未修改生产数据库。
- 部署验收均为 GET；不调用 `/search`、`/chat`，不写 `query_log`、不消耗 Gemini 配额。
- UI 健康与 API 分享解析不等于浏览器端分享流程验证；真实 OAuth、Git SHA 版本校验、自动回滚及异机备份仍待后续批次。
- 本批不修改培养方案、检索排序、Co-op 隐私规则或模型参数。

## 02 — 检索筛选与拒答契约（2026-09-30）

### 范围与原因

- chat 的上下文和培养方案捷径未应用显式筛选，且先截断再查找；符合条件但排在后面的课程可能被漏掉。
- 精确课程查询带筛选时原来绕过别名层，可能被混合检索/拒答门误处理，或用其他课程替代已被排除的明确所指。
- chat 的专业前缀会关闭两种拒答门；专业范围不代表主题相关。HyDE 重试还会丢掉从查询提取的前缀。

### 修改文件

| 文件 | 修改 |
|---|---|
| `rag/filters.py`（新增）、`rag/retriever.py` | 集中 SQLite 筛选契约；保留 term/credits/mode 精确匹配、professor LIKE、indexed 状态与 CS/CSYE 前缀边界，所有值参数绑定 |
| `api/routes/common.py` | 捷径复用同一 SQL，保留输入顺序；无显式筛选时保留原直接查找行为，有筛选时只接受 indexed 课程 |
| `api/routes/chat.py` | 上下文、别名、培养方案先筛选再取 k；已知所指被排除时返回 empty，不换成无关混合结果；专业前缀不绕过拒答门；HyDE 保留实际生效的全部筛选；刷新路由说明 |
| `api/routes/search.py` | 带筛选的精确引用仍走别名捷径；已知所指被排除返回 empty；全悬空别名仍按原逻辑回退混合检索 |
| `tests/test_retrieval_contract.py`（新增）、`tests/test_api_search.py` | 四种捷径、单项/组合筛选、先筛选后截断、pending 排除、两种拒答门、HyDE 约束保持、SQL 参数绑定与前缀边界回归 |

### 验证记录

- 修复前，新增契约与更新后的 search 断言得到 **47 failed / 18 passed**，确认回归能识别旧行为。
- 核心修改后的检索专项套件：**140 passed, 5 warnings in 5.92s**；随后补充 6 项 SQL/高置信拒答回归。
- 最终全套：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no` → **1067 passed, 6 warnings in 30.08s**，无跳过；相对第一批新增 55 项测试。
- `git diff --check` 通过；Ruff 仍不可用，未安装新工具、不宣称 lint-clean。

### 发布状态与边界

- 仅本地修改；未提交、推送、部署或写生产数据库，未调用真实 Gemini。
- 未改融合权重、拒答阈值、校准系数或模型参数。培养方案成员资格仍来自已声明的课程关系，不以专业代码前缀误删跨院系课程。
- 校准跨语言接纳测试使用替身，只证明调用契约；**不代表真实模型质量改善**。部署前仍需真实模型的中英专业前缀、相关查询与无关查询评测，不能沿用旧产物的质量指标作为本批结果。
- 培养方案版本/校区、先修语义、耗时分解与真实用户数据评测仍在后续批次。

## 03 — Co-op 收集、审核与去重奖励（2026-09-30）

### 范围与原因

- 首条独有经历原来返回 422，无法形成待审积累；重复行/策展种子却能被当作第二个贡献者，错误满足公开门槛。
- 每次接受上传都会直接增加贡献数；同一用户重试或修改自由文本可反复获得奖励，UI 也在每次 201 后自行加一。
- 原来公开列表直接读取全部经历，没有独立的待审/审核/发布状态，也没有失败时完整回滚和并发去重保障。

### 当前行为

- `POST /coop` 改为私有收集：201 / accepted=true 表示已存储，不表示已公开；新增审核状态、重复标志、该记录是否获得奖励和服务端贡献数。
- 同用户同 company/role/term 的规范化键去重，覆盖 NFKC、大小写、空白变体；重试返回原记录、不替换内容、不加贡献数。
- `pending → approved → published` 或 `pending → rejected`。批准必须提供完整脱敏替换内容、审核人、审计说明；只有两个不同登录用户的同组经历均已审核才公开。种子、空身份、同用户重复行不能凑人数。
- 审核、组内发布、唯一奖励账本和贡献数更新在同一事务内执行。重复同向审核不改变奖励；不同原记录泛化到同一组时，每用户最多奖励一次。
- GET 仅返回策展种子与当前仍满足人数门槛的已发布 UGC，并保留原字段解锁规则。旧未审核 UGC 不再公开，但原数据与历史贡献数不删除、不重算。账号删除后重新检查公开资格，剩余单条隐藏。
- UI 直接使用服务端贡献数，明确提示私有待审/等待群组/重复/拒绝，不把 HTTP 201 宣称为解锁成功。

### 修改文件

| 文件 | 修改 |
|---|---|
| `db/init.sql` | 新增 schema v1.3 私有审核表、不同用户/组奖励账本、状态与唯一性约束、索引；原表保持不变 |
| `db/coop_submission_repository.py`（新增） | 私有收集去重、完整脱敏替换审核、不同贡献者门控、事务内发布/奖励、同向审核幂等；保存点不提交调用方事务 |
| `db/coop_repository.py` | 新增安全公开读取；每次读取重新检查群组；明确原始读取只供可信运维，并纠正用内容分层隐藏问题记录的注释 |
| `schemas/coop.py` | 门槛按不同非种子贡献者计数；规范化组键与分层函数共用；薪资文本长度上限 |
| `api/dependencies.py`、`api/models.py`、`api/routes/coop.py` | 审核表缺失时 503；上传只进队列、返回真实状态/贡献数；拒绝空白必填字段及客户端伪造审核状态；公开字段仍分层；提交日志不写私有经历字段 |
| `app/coop_view.py` | 移除本地贡献数加一，使用服务端状态；更新待审/重复提示与页面说明，不再显示未经验证的合规保证 |
| `scripts/migrate_coop_submissions.py`（新增） | 显式已有 DB 路径，默认只读；--commit 才做原子、幂等加表迁移；不替换运行库 |
| `scripts/review_coop.py`（新增） | 运维本地 list/show/approve/reject；审核默认 dry-run，需显式 --commit；批准需完整脱敏 JSON 与审计；无公网管理员/私有队列接口 |
| `scripts/deploy.ps1`、`tests/test_deploy_script.py` | 增加匿名只读 GET `/coop` 验收：必须 200 且有效 JSON 数组（允许空数组）；避免检索 ready 掩盖审核表未迁移；不自动迁移运行库 |
| `tests/test_coop_moderation.py`、`tests/test_coop_submission_repository.py`、`tests/test_coop_review_cli.py`（新增） | API 隐私边界、审核状态机、真实离线命令、并发连接去重、失败回滚、唯一奖励与只读/幂等迁移 |
| `tests/test_api_coop.py`、`tests/test_coop_schema.py`、`tests/test_coop_view.py`、`tests/test_init_sql.py` | 更新上传语义断言，补不同贡献者证据、UI 不虚加贡献数和 v1.3 DDL 契约；保留认证与字段分层回归 |
| `docs/coop-moderation.md`（新增）、`docs/pii_redaction.md` | 写明私有收集/公开边界、升级与审核命令、存储限制；同步不同贡献者规则；移除不合法且无效的 level=99 紧急 SQL |

### 验证记录

- 修改前新增核心边界断言：**4 failed**，分别识别首条被拒、种子凑人数、重试逻辑和旧未审核 UGC 公开。
- 审核/仓储/接口/原分层/DDL 首轮专项：**107 passed, 3 warnings in 5.12s**；随后补命令、迁移、完整 API 流程及发布验收。
- 最终全套：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no` → **1120 passed, 5 warnings in 48.24s**，无跳过；相对第二批新增 **53 项**回归。
- 两个独立 SQLite 连接的并发提交/并发审核均通过；重复审核不多记功。模拟第二条公开插入失败、第二个用户记功失败均回滚整个本次审核/公开/奖励，已提交的先前审核状态保留。
- 审核命令以真实 Python 子进程执行，只接触测试临时 DB；覆盖默认只读、两人审核后发布、重复审核、拒绝、缺审计/缺替换内容/不存在 ID 的失败退出，以及普通输出不带原私有正文。
- 迁移只读检查不改变测试数据库字节；提交迁移幂等，用户和种子保留，外键检查为空；拼错路径不会创建 DB。
- PowerShell 7 和 Windows PowerShell 5 均执行通过 **15 个离线验收场景**，新增 Co-op 503、非法 JSON、非数组响应三个失败场景；有效空数组通过。
- `git diff --check` 通过；PowerShell 脚本解析 0 错误，UTF-8 BOM 保留。Ruff 仍未安装/执行，不宣称 lint-clean。

### 发布状态与剩余边界

- 仅本地修改；**未提交、未推送、未部署、未迁移任何真实运行库或生产数据库**，没有执行真实 SSH/HTTP/Gemini/OAuth。
- 上线前必须备份运行 DB、在副本演练 v1.3 加表迁移，检查旧 UGC 的人工处置方案，并同步更新 API 与 UI。部署工具只验收，不替你执行迁移；真实浏览器和生产流程未验收。
- 两个账号不是两个自然人的证明，也不是自由文本已匿名的证明；仍需人工脱敏。待审表不经公开 API 返回，但没有额外静态加密或自动保留/清理策略；文件、WAL、备份与审核临时文件仍须私有保护。
- 策展种子仍单独显示，不能把“种子继续展示”解释为已证明其群组匿名性。
- 已公开记录的单条撤回/改稿、拒绝后的申诉入口、上传同意的结构化留痕和历史贡献追溯仍未实现。旧 `visibility_level=99` 指令违反 CHECK，内容分层也不等于撤回；本批移除误导指令，不宣称已有紧急单条下架功能。
- 本批未改检索参数、培养方案或生产数据；下一批仍为「回答依据与数据缺失提示」。

## 04 — 回答来源与缺失信息（2026-09-30 至 2026-10-01）

### 范围与原因

- 目录描述原来仅存于检索 `raw_text`，没有传给回答提示词；其中还可能混有大纲、评论或生成扩展，不能直接标成官方。
- 回答拿到工作量、难度等值却拿不到支持引文和来源；缺失字段被省略，容易被误解为没有要求。v3 还包含凭课程编号判断首学期适合度的规则。
- 原详情证据只显示引文与泛称 confidence，没有解释支持值及其与事实可信度的区别；聊天历史不保存来源/缺失结构。

### 当前行为

- 独立保存可追踪的目录快照，明确部门页 URL、课程身份、内容摘要 ID、导入时间及未知抓取日期。不把旧混合文本或来源 ID 自动升级为官方证据，也不宣称快照是实时核验。
- 新增 v4 提示词，保留 v3 不变。回答输入显式携带目录描述、支持引文、支持值、来源和缺失项；禁用课程编号难度捷径，要求保留冲突、说明 seed 未核验及先修 AND/OR 未知。
- chat meta、回答输入和详情共用 `answer_evidence` 契约；数值 0 不算缺失。聊天历史和实时卡片保留相同来源语义，关键警告直接显示，详情显示完整来源/缺失列表。
- 来源回填命令默认只读；`--commit` 才对显式数据库做事务内加表/回填。它不重跑普通目录摄取、不改变课程任何列或索引；失配/歧义跳过，坏存档或写入失败整批回滚。

### 修改文件

| 文件 | 修改 |
|---|---|
| `schemas/answer_evidence.py`（新增） | 读取阶段的目录快照与回答证据模型；严格官方 URL 和部门匹配，不改持久化 Course v1.1 |
| `db/catalog_source_repository.py`（新增）、`db/init.sql` | 独立 v1.4 来源表；稳定内容摘要、课程代码/名称绑定、批量读取、无表/坏快照降级；不从 raw_text 猜来源 |
| `rag/answer_evidence.py`（新增） | 统一缺失字段和来源/日期/学分冲突/支持值冲突/先修语义/seed/合成记录警告 |
| `llm/prompts/chat_v4.py`（新增） | 明确证据规则与未知值，引用/JSON 数据隔离；目录及引文摘录截断、省略计数，优先不同支持字段；不静默改 v3 |
| `api/models.py`、`api/routes/chat.py`、`api/routes/course.py` | 附来源/缺失 DTO 与 prompt_version；提示词/meta 共用读取结果；更新接口说明 |
| `scripts/ingest_neu_catalog.py` | 新摄取同时保留显式目录来源；缺表/不合法来源在课程 upsert 前失败；原摄取重写字段的行为不用于回填 |
| `scripts/sync_catalog_sources.py`（新增） | 显式已有 DB + 存档路径，默认只读；完整预校验、唯一代码/精确名称匹配、原子加表回填、幂等、原内容比对；不创建拼错路径的数据库 |
| `app/answer_evidence_view.py`（新增）、`app/streamlit_app.py` | 来源/缺失/关键警告展示；保存到聊天历史，历史与实时共用；坏历史快照不生成链接；支持值/来源 ID/引文以纯文本显示，注明抽取置信度不是事实概率 |
| `tests/test_answer_grounding.py`、`tests/test_catalog_sources.py`、`tests/test_chat_v4_prompt.py`、`tests/test_answer_evidence_view.py`（新增） | API/提示词共用证据、历史目录 HTML 摄取、只读/真实 CLI/幂等/回滚、坏来源隔离、缺失与冲突、证据摘录、历史 UI 辅助函数回归 |
| `docs/answer-grounding.md`（新增）、本文件 | 说明来源边界、副本演练命令、迁移与模型/浏览器验证限制；持续记录本批文件与验证 |

### 验证记录

- 修改前，3 个核心新断言得到 **3 failed, 3 warnings in 2.20s**，识别 chat/详情没有来源 DTO、提示词未显式表达空值。
- 核心修改后，新增断言 + 既有 chat/详情/v3/UI 专项 **53 passed, 4 warnings in 4.58s**。扩展来源、回填与 v4 约束后 **40 passed, 3 warnings in 8.53s**；加入 UI 合约与引文预算后 **61 passed, 3 warnings in 8.87s**。
- 最终全套：`wsl.exe -d Ubuntu-24.04 -e bash -lc 'cd /mnt/h/neu-compass && .venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no'` → **1172 passed, 5 warnings in 51.95s**，无跳过；相对第三批新增 **52 项**回归。警告仍为 SWIG 类型与 HTTP 422 常量弃用警告。
- 最终补充的回归验证了部门不匹配的旧历史快照不显示链接，以及回填判断幂等时同时比较内容而不只相信摘要 ID。
- 来源回填测试逐列比较完整 `courses` 行：JSON、raw_text、search expansion、状态及其余列均保留；默认只读时测试数据库字节不变，重复回填保留原导入时间，失败连新增 schema 一起回滚。
- 使用仓库内历史目录 HTML fixture 验证解析到摄取来源链路，不等于检查当前官方目录。真实 CLI 测试只访问临时 DB 与存档；没有运行真实网络或模型请求。
- 本批未执行 Ruff，不宣称仓库 lint-clean。真实 Gemini 的遵循程度与浏览器布局不在 helper/替身测试覆盖范围。
- tracked diff 与本批新增文件的空白检查通过；没有为检查而暂存或提交文件。

### 发布状态与剩余边界

- **未提交、未推送、未部署、未迁移或回填任何真实运行库**；HEAD 仍为 `bb2f6e3`，本地保留前四批修改。没有改模型权重、拒答参数或培养方案 seed。
- 读取兼容没有 v1.4 来源表的旧库，不自动迁移；现有课程没有有效快照时继续明确提示缺失。实库覆盖率未测，不宣称已有官方来源全面覆盖。
- URL/摘要检查不证明存档内容真实或当前有效；来源表只保留当前单份快照，历史 JSONL 需另外保存。抓取时间未知不以导入时间替代。
- 现有先修代码和方案 seed 仍不能保证毕业/注册资格；完整 syllabus 的逐字段来源对应仍未建模。新提示词不是事实核验器，也不是注入防护证明。
- 上线前需在备份副本核验存档、匹配/跳过统计与升级流程，再做真实模型与浏览器验证；第三批 Co-op v1.3 迁移仍是独立步骤。
- 下一批：用户于 2026-10-01 确认先覆盖 **Boston**。入学 Spring/Fall 与培养方案 Catalog 年度是不同维度，不能用“有两个入学学期”替代适用版本。只读检查确认 `Program`/当前表没有适用版本和校区字段，先修只有逐条边；`find_by_prefix` 当前取首个匹配方案，不具备多版本选择。年度/项目路径明确前，不把 cs/ds/info-ms 旧 seed 标为核验完成，也不实施第五批数据重写。

## 05 — Boston 官方初步对照（2026-10-01；实现尚未开始）

### 适用范围和版本区分

- 用户已确认先覆盖 Boston。工作对照样本选用官网当前 **2026–2027 Edition**，仅用于核验项目数据；不等于用户已经确认个人适用年度，也不自动将旧生迁移到最新方案。
- 入学年份、入学学期（Spring/Fall）、Catalog 版次、校区、普通 MS / Align / Bridge 路径要分开记录，不以自然年的两个入学批次替代版本。
- 当前三个项目招生页均列 Fall/Spring：[MSCS Boston](https://graduate.northeastern.edu/programs/mscs-computer-science/master-of-science-in-computer-science-boston/)、[MSDS Boston](https://graduate.northeastern.edu/programs/ms-data-science/master-of-science-in-data-science-boston/)、[MSIS Boston](https://graduate.northeastern.edu/programs/msis-information-systems/master-of-science-in-information-systems-boston/)。这是招生入口信息，不证明课程每个学期都开，也不等于培养方案不随年度变化。

### 已发现的差异与实现约束

| 项目 | 本地 seed / 结构的问题 | 官方对照与后续要求 |
|---|---|---|
| CS | `cs_ms.json` 把 Align 桥接课程放进通用 `cs-ms`，CS 5500/5600 标成 core；未表达广度领域选择，缺 recitation 配套关系 | 当前[普通 MSCS](https://catalog.northeastern.edu/graduate/computer-information-science/computer-science/computer-science-mscs/)把 CS 5010 + 5011、CS 5800 列为 core，CS 5500/5600 位于可选广度区域；[Align](https://catalog.northeastern.edu/graduate/computer-information-science/computer-science/computer-science-mscs-align/)是独立方案。需区分路径与组选条件，不能把广度候选变成人人必修 |
| DS | `ds_ms.json` 的通用 core 与当前目录不一致；专业只按 DS 前缀，未表达跨院系及 concentration 的不同选择 | 当前[MSDS Boston](https://catalog.northeastern.edu/graduate/university-interdisciplinary-programs/science-data-ms-bos/)的 core 存在 CS 5800 **或** EECE 7205、CS 6140 **或** EECE 5644 的选择；需保留 OR 与 concentration，不能把两条任选项变成同时必修 |
| INFO | `info_ms.json` 的通用 core 和单一 capstone 标记不能表达当前的路径；缺 lab 配套 | 当前[MSIS Boston](https://catalog.northeastern.edu/graduate/engineering/multidisciplinary/information-systems-msis/)包含 INFO 5100 + 5101，另有可选 concentration 替代与 coursework/project/thesis 分支；不能把所有候选或 exit 路径合成一个共同必修列表 |

以上为 2026-10-01 网页读取与本地 seed 的**初步差异核对**，不是整份 Plan of Study 逐条验收。来源尚未制作完整、版本冻结的本地存档；当前链接将来可能更新，后续导入应保存版次与来源内容，不只留 URL。

### 下一步验收入口

1. 先建立显式方案身份：项目、路径、Boston、Catalog 年度、来源与核验状态；未核验旧 seed 保留 unknown，不批量盖 verified。
2. 表达 AND/OR、组选学分、配套 lab、可选毕业出口和 concentration，再按官方源逐条对照；入学/推荐学期不靠课程编号猜测。
3. 查询需明确方案，多个相同前缀候选不能继续用 `LIMIT 1` 任意选一份。个人适用年度未提供时展示版本选择/限制，不给注册资格保证。
4. 新规则通过隔离数据库、版本选择、嵌套条件与旧数据兼容回归后，再另行安排副本迁移演练和发布。

本段只新增范围与检阅记录；未修改第五批的 schema、seed、API 或运行库，不将“对照已开始”记成“第五批实现完成”。

以上是开始实现前的历史检查点。后续本地实现和验证记录见 05A；初步对照不是整份方案已验收的声明。

## 05A — 版本化规则、显式选择与歧义保护（2026-10-01）

### 范围与当前行为

- 独立保存项目家族、校区、Catalog 年度、普通 MS/Align/Bridge 路径及 concentration；不改旧 `Program` 模型、不把旧 seed 自动盖章核验。用户只确认 Boston，2026–2027 仍是对照样本，不是个人适用性确认。
- 递归规则保留 AND、OR、组选门数/学分/领域数、文本条件和未建模项；没有抓到的配套 lab 仍以课程代码保留，不因课程库缺行而静默删除。**这是规则文档，不是资格/学分/毕业判定器。**
- 只新增 CS、DS、INFO 普通 MS 三份核心片段；全部标 `partial`，由 `codex-source-crosscheck` 对照短来源摘录，不代表人工 Plan of Study 审批。Align、Bridge、完整广度/选修/concentration/出口及真实先修语义尚未完成；旧 seed 文件未重写。
- API 精确筛选版本，没有匹配就为空，不自动改到最新年度/别的路径。旧库缺 v1.5 时明确不可用，不自动建表；不合法来源、身份或摘要的文档不对外返回。
- UI 方案选择默认留空，清楚展示 scope、原规则、来源和未建模项；旧学期仍单独标为未核验，`semester=null` 不再宣称“任意学期可修”。聊天项目选择可清空，只区分家族，不代替年度/校区选择。
- 同前缀多个家族不再任取第一项，基础课/第一学期请求返回 409 让用户明确选择；选择与检测到的前缀冲突也返回 409。项目已有版本化记录但无核验学期安排时，不再使用旧猜测顺序，即使文档损坏也不恢复旧捷径。
- 规则树目前只供浏览，**尚未接入 LLM 或核验版学期规划**；导入后上述意图会明确暂不可用，不把读取片段误当成功能完备。精确课程引用/其他检索仍走原流程，只有旧 seed 的家族保留原未核验学期捷径。

### 修改文件

| 文件 | 修改 |
|---|---|
| `schemas/program_plan.py`（新增） | 显式 scope、来源版次/对照状态、递归规则与字段组合校验；节点/深度上限；完整性声明约束 |
| `db/program_plan_repository.py`（新增）、`db/init.sql` | 独立 v1.5 表，scope 唯一和 ID 身份不可重绑；摘要/内容幂等、坏记录隔离、读取不自动 DDL；当前每 scope 一份文档，不保留所有修订 |
| `scripts/sync_program_plans.py`（新增） | 显式已有 DB 与规则文件；默认只读；`--commit` 时加表/整批写入原子回滚；不创建项目家族、不改课程/旧方案/索引 |
| `data/program_plan_seed/boston_2026_2027_core_fragments.json`（新增） | 三份普通 MS 核心片段；CS 配套关系、DS 两处 OR、INFO 0 学分 lab 和文本条件；缺失部分显式保留 |
| `db/program_repository.py` | 同前缀多匹配抛 `ProgramAmbiguous`，不使用 `LIMIT 1` 任意选择；原 CRUD 保留 |
| `api/models.py`、`api/routes/chat.py` | 可选 `program_id`；不存在项目 404、歧义/前缀冲突 409；已有 scoped 记录禁止旧猜测学期捷径；同步说明，不改 v4 提示词 |
| `api/routes/program.py` | 列表/详情增加方案与旧 seed 警告；新增 `/programs/{id}/plans` 精确范围接口；无表兼容、未知学期措辞修正 |
| `app/program_plan_view.py`（新增）、`app/program_view.py` | 默认不选最新版本，显示原逻辑树/来源/片段限制；纯文本展示不可信字段；旧 seed 与版本化规则分开 |
| `app/streamlit_app.py` | 聊天项目家族选择与请求传递；不是自动个人年度选择，项目加载失败时课程对话仍可用 |
| `tests/test_program_plan_contract.py`、`tests/test_program_plan_rules.py`、`tests/test_program_plan_storage.py`（新增） | API 范围/歧义/旧库兼容、嵌套与组选、节点预算、坏来源/身份、真实只读 CLI/幂等/回滚/数据保留 |
| `tests/test_program_plan_view.py`、`tests/test_program_plan_widgets.py`（新增）、`tests/test_init_sql.py` | helper 与两个真实 Streamlit 无头选择组件回归、未知学期、不可信链接/文本，以及 v1.5 DDL 契约 |
| `docs/program-plans.md`（新增）、本文件 | 规则/适用性边界、API/409 行为、副本演练说明、05B 入口与逐批修改记录 |

### 验证记录

- 修改前旧 seed 警告、前缀歧义与显式项目选择三个新断言：**3 failed, 3 warnings in 18.22s**；修复后连同既有接口/仓储专项 **48 passed, 4 warnings in 6.10s**。
- 规则/存储/接口扩展专项 **59 passed, 3 warnings in 9.61s**；加入 UI 辅助函数与既有 API/DDL 回归后 **115 passed, 3 warnings in 10.85s**。
- 新增文档损坏仍禁用旧顺序、显式前缀冲突、歧义不调用模型/混合检索及两个真实 Streamlit 无头组件测试。首轮全套 **1 failed, 1246 passed, 5 warnings in 85.91s**；失败发生于新测试读取不存在的依赖 override，不是请求断言。改为显式注入禁止调用替身后，接口与组件专项 **19 passed, 3 warnings in 23.39s**。
- 最终全套：`wsl.exe -d Ubuntu-24.04 -e bash -lc 'cd /mnt/h/neu-compass && .venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no'` → **1247 passed, 5 warnings in 81.23s**，无跳过；相对第四批新增 **75 项**回归。五个警告仍为 SWIG 类型和 HTTP 422 常量弃用警告。
- 临时 DB 验证默认只读时文件字节不变；提交只增加 v1.5 和规则文档，已有项目/课程/旧 seed 数据保留；重复幂等；晚期失败回滚新增表和前面写入；拼错路径不创建文件；scope 占位/重绑失败。
- 两个 Streamlit `AppTest` 使用真实选择控件验证默认留空、选中显示 DS 的 OR 树、家族选中/清空后重跑，无浏览器、HTTP、OAuth 或 Gemini 请求；不等于完整应用布局与登录验收。
- 官方目录在本次网页读取中对照片段，短摘录保存在 JSON；不宣称完整源页面已冻结归档或整份 Plan of Study 已核验。本批未执行 Ruff，不宣称 lint-clean。
- tracked diff 与全部 33 个未跟踪文件的空白检查通过；没有为检查而暂存或提交文件。最终文档补记后再次检查本批记录，无空白错误。

### 发布状态与 05B 入口

- **未提交、未推送、未部署、未导入/迁移任何真实运行库**。HEAD 仍为 `bb2f6e3`，前四批本地改动保留；没有写课程索引、生产 `query_log` 或调用真实模型/登录流程。
- v1.5 导入只在测试临时库执行；与第三批 v1.3、第四批 v1.4 迁移分别演练，不自动替换运行库。上线前先准备私有备份副本，检查来源/统计/范围与 409 变化，再做真实浏览器/模型验收并单独确认发布。
- 摘录对照状态、URL/摘要校验和 `complete` 声明均不是来源真实性/个人适用性证明；当前存储没有全部修订历史，分享链接没有保存选中的完整 plan scope。
- 下一步仍在第五批：冻结完整来源，补普通 MS 广度/选修/concentration/出口；Align、Bridge 独立核验；真实课程先修/共修 AND/OR 与审批条件单独建模。可靠回答与学期安排接入需有明确规则/开课证据，不跳到第六批分发。

## 05B-1 — 普通 MS 扩展规则与来源输入固定（2026-10-01）

### 范围与当前行为

- 本次仍是 Boston、2026–2027 对照样本，个人年度/路径未确认。只扩展普通 MS 数据；**没有把第五批整体验收完成，也没有开始 Align/Bridge 或真实课程先修实现。**
- `select` 候选集合可表达明确代码、科目前缀、同科目数字范围和排除项；范围端点不变成两门必修，也不表示每个编号都有真实课程。领域计数仍要求完整有限候选，不对开放前缀猜领域；全部排除的有限池/小区间被拒绝。
- 新增必须带触发说明的 `optional` 单子分支，可选 Co-op / thesis 委员会 / GIEL 条件不再冒充共同必修。条件只是显示，不自动计算资格或激活分支。
- 新增五份扩展文档，全部保持 `partial`：CS 广度 25 代码/三个领域、组选与选修范围；DS 三个 concentration 分别保存 16、8+8、4+12 学分组选及不同学院的可选 Co-op；INFO general 的 Coursework/Project/Thesis OR、固定课程、两类选修池/排除项与提交流程。
- 总学分/GPA、DS 小于 4 学分选修的配套项目脚注、Co-op 准备等为文本/可选条件；重复计入、具体先修、批准、个人资格和实际开课仍未计算。INFO medical/GIEL 联读完整范围留待独立核验，不混进 general。
- 旧核心片段文件原样保留；CS/INFO 扩展文档沿用原 ID/scope，三个 DS concentration 使用独立 ID/scope。导入不会删除旧 DS 共享核心文档，不自动给它分配 concentration。
- 来源输入实际 GET 后按字节摘要固定在 Git 忽略目录。指纹化导入必须提供对应原始 HTML/元数据，缺失/损坏在 DB 打开前失败；不能用重新下载的不同 bytes 冒充旧输入。摘要和 HTTPS 获取不等于个人适用性或完整政策核验。
- 兼容旧 05A 文档摘要：新增字段为空时不改变稳定内容摘要，读取不把既有文档误判损坏；新非空规则/来源指纹参与摘要。

### 修改文件

| 文件 | 修改 |
|---|---|
| `schemas/program_plan.py`、`app/program_plan_view.py` | 增加编号范围、开放前缀/排除项、optional 条件与对应显示；拒绝错误组合、重复/重叠范围和空池；显示来源字节摘要 |
| `db/program_plan_repository.py` | 新空默认字段的摘要兼容；旧 05A JSON 保持可读、重复存储不重写原文档 |
| `schemas/program_source.py`（新增） | 官方来源元数据、2 MB 限制、标题/版次与 SHA/URL/日期/长度对应的离线核验；不宣称身份真实性 |
| `scripts/capture_program_sources.py`（新增） | 显式输出目录，只 GET 校验过的官方 HTML、不跟随重定向；按摘要保存不可覆盖的原始输入和 UTC 元数据；不写 DB |
| `scripts/audit_program_rule_sources.py`（新增） | 固定来源候选表与本批五个 scope 的独立只读比对；未知/歧义表格失败；只核对候选/分组，不自动完整政策核验 |
| `scripts/sync_program_plans.py` | 指纹文档需 `--source-dir` 并在任何 DB 操作前预核验；旧无指纹核心文件保持兼容；仍默认只读、写入事务与回滚不变 |
| `data/program_plan_seed/boston_2026_2027_extended_rules.json`（新增） | 五份普通 MS 扩展规则，来源指纹、分组选修、毕业出口、可选条件和未建模边界；不改旧 seed |
| `data/program_plan_seed/boston_2026_2027_source_manifest.json`（新增） | 三页来源的公开 URL/版次/UTC 时间/长度/标题/摘要；不含网页原文 |
| `tests/test_program_plan_extended.py`、`tests/test_program_sources.py`（新增） | 新规则正/负语义、版本化数据、来源替身、损坏/缺失拒绝、真实临时库 CLI、候选表解析与错配检出 |
| `tests/test_program_plan_storage.py`、`tests/test_program_plan_contract.py`、`tests/test_program_plan_widgets.py` | 旧摘要兼容/幂等、API 不平铺新规则、真实 Streamlit 扩展 INFO 出口/排除/可选分支展示 |
| `docs/program-plans.md`、本文件 | 同步数据覆盖、固定输入/私有恢复、离线审计、副本导入与下一段边界 |
| `data/raw/program_catalog/`（6 个生成文件，Git 忽略） | 三份原始 HTML 与各自元数据；由摄取脚本生成，未纳入 Git、不覆盖旧输入、不影响 DB |

### 验证记录

- 新增四个范围/前缀排除/optional 核心断言，修改前 **4 failed in 12.98s**；实现后连同 05A 六个专项文件 **79 passed, 3 warnings in 30.93s**。
- 规则负例、来源捕获/验证及存储专项 **65 passed in 14.73s**；补离线表格错配、API 与真实组件后 **90 passed, 3 warnings in 43.87s**。随后补全部排除小区间边界，包含于最终全套。
- 实际只读 GET 三页官网并固定输入：CS **46,741 bytes**、DS **67,213 bytes**、INFO **45,991 bytes**；UTC 捕获时间为 **2026-10-01 13:05:55**。URL/完整摘要见 manifest；对应 HTML 在私有原始数据目录，不放进修改记录。
- 首次来源候选表审计有 INFO 布局识别失败：固定 project/thesis 课程出现在选修组前。修正为明确允许固定前导课程、选修组仍独立解析后，**五份文档离线表格比对全部通过**。CS 领域归属/候选/最低数与选修区间、DS 组选及 Co-op 代码、INFO 三出口课程/学分/排除均对应；不等于 GPA/审批/所有政策已机器验收。
- 真实 CLI 只导入测试临时库：默认只读字节不变，首次提交五份文档，重跑零变更；项目家族行保留。带指纹但缺目录/坏源时在写入前失败；测试不调用生产 API 或数据库。
- 来源抓取使用 HTTP 替身测试拒绝重定向（不会访问目标）、非 HTML、404、错误年度和超限；同内容保留原时间/bytes，冲突元数据保留不覆盖。捕获失败可能保留已经生成的合法输入，不宣称整批原始文件原子回滚。
- 一份按旧 05A 字段形状和旧算法人工构造的持久化 JSON/hash 能原样读出，重复 store 返回未变更；API 保留 OR、前缀排除、范围与 optional。新增真实 Streamlit 无头组件显示 INFO 三出口和排除项；不等于真实浏览器端布局/登录验收。
- 首轮全套 **1 failed, 1304 passed, 5 warnings in 106.11s**，唯一失败是已有 Streamlit 无头组件超过 20 秒等待上限，无规则/接口断言失败。保留原 20 秒配置单跑 **3 passed in 24.34s**；据此将这组功能测试的有界等待预算调整为 45 秒，断言不变后重跑全套。等待不足是当前判断，不宣称已证实特定系统根因或应用延迟达标。
- 最终确认全套：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/program-tests-05b1.xml` → **1305 passed, 5 warnings in 86.60s**，无跳过；相对 05A 新增 **58 项**回归。JUnit 报告为 Git 忽略的生成产物，用于跨工具会话复核；用户追加继续时先前运行的最终输出不可恢复，因此未将其当成成功，另行确认本次结果。
- tracked diff 与全部 40 个未跟踪文件的空白检查通过；本批不执行 Ruff，不宣称 lint-clean。

### 发布状态与下一段

- **未提交、未推送、未部署、未导入/迁移真实运行库**；HEAD 仍为 `bb2f6e3`，此前本地改动保留。只新增来源 GET 与原始归档，没有调用真实 Gemini/OAuth、写生产 query_log 或修改 FAISS/BM25。
- 原始 HTML/对应元数据不在 Git 中，转移机器需要从受控备份恢复；manifest 本身不足以导入指纹化规则。以后网页变化需人工再对照和修订来源，不跳过摘要检查。当前来源与规则文档都不构成不可篡改的真实性证明。
- 仍未把规则树接入 LLM/学期规划；05A 的 409 边界不变。v1.5 加表无需额外新表版本，但新 optional/范围规则需要同步升级读取端；旧代码不能解释新树时不得静默平铺。
- 仍待：Align/Bridge 独立核验；medical/GIEL 完整范围、学院政策与重复计入；真实课程先修/共修 AND/OR 和批准；可靠回答及学期安排。下一段继续第五批，不跳到分发或生产部署。

## 05B-2 — CS Align / INFO Bridge 独立路径规则（2026-10-01）

### 范围与当前行为

- 继续 Boston、2026–2027 对照样本，个人适用年度/路径仍未确认。新增两份独立 scope，沿用 `cs-ms` / `info-ms` 家族，不覆盖普通 MS 文档、不改旧 seed，全部保持 `partial`。
- [CS Align](https://catalog.northeastern.edu/graduate/computer-information-science/computer-science/computer-science-mscs-align/)桥接保留 CS 5001 + 5003、CS 5002、CS 5004 + 5005、CS 5008 + 5009 的主课/配套关系；桥接 B 或以上与项目另定例外是文本条件，不计算个人免修。核心只列 CS 5800，不误继承普通 MS 的 CS 5010 + 5011。广度、选修、36–44 总学分/GPA 与可选 thesis 委员会条件分别保留；不复制普通方案的 GIEL 分支。
- [INFO Bridge](https://catalog.northeastern.edu/graduate/engineering/multidisciplinary/information-systems-msis-bridge/)核心保留 INFO 5001、INFO 5100 + 5101、INFO 6215，以及 C 或以上/具体先修可能要求更高成绩的文本条件；12 学分 restricted 有限池与 12 学分其他选修独立保存，Co-op 为准备 AND 经历 OR。总学分 36/37 与 GPA 条件仍由人核实。
- INFO Bridge 不误继承普通 general 的 Coursework/Project/Thesis 三出口或 INFO 5200 排除项；其页面明确排除 CSYE 6220，两份规则保持实际差异。没有排除项**不保证个人注册资格**，未核实具体先修、开课、批准或级别限制。
- 两页实际来源固定在 Git 忽略目录，策展 JSON 和公开 manifest 保留字节摘要。离线审计新增必修配套/独立核心、选修池与 Co-op 组合检查；统一表格空白，重复出现在课程标题的主课代码不重复计数。审计成功不是成绩、免修、全政策或完整毕业验收。
- [DS Align 旧 HTML 路径](https://catalog.northeastern.edu/graduate/university-interdisciplinary-programs/data-science-align-ms-bos/)本次跳转至目录索引，未取得对应 2026–2027 Boston 页面；检索到的旧 PDF 不作为当前版次导入，也不复制普通 DS 规则。来源待核验不等于项目已不存在。

### 修改文件

| 文件 | 修改 |
|---|---|
| `data/program_plan_seed/boston_2026_2027_pathway_rules.json`（新增） | CS Align 与 INFO Bridge 独立 partial 文档、核心/配套/选修/可选条件与指纹；不改普通 MS scope |
| `data/program_plan_seed/boston_2026_2027_pathway_source_manifest.json`（新增） | 两页 URL/版次/UTC 时间/长度/标题/摘要，不含网页全文 |
| `scripts/audit_program_rule_sources.py` | 扩展两个路径适配器；必修配套拒绝 OR/缺失，Bridge 选修/排除/Co-op 结构独立核对；处理不换行空白和重复代码引用 |
| `tests/test_program_pathways.py`（新增） | 16 项范围/配套/不误继承回归；来源负例、API 精确路径筛选、409、真实临时库 CLI 只读/增量/幂等、两个真实 Streamlit 组件 |
| `docs/program-plans.md`、本文件 | 更新数据覆盖与差异、离线来源审计、副本导入例子、DS Align 来源待核验与后续边界 |
| `data/raw/program_catalog/`（新增 4 个生成文件，Git 忽略） | 两页完整 HTML 和各自元数据；连同 05B-1 合计五页、十个来源文件，未入 Git |

### 验证记录

- 新路径来源审计的两个正例在扩展前 **2 failed in 13.03s**（无对应 scope adapter）；实现后连同既有来源专项 **33 passed in 7.02s**。
- 新增负例会拒绝配套 AND 改 OR、丢 CS 5003、Align 核心误用 CS 5010、Bridge restricted 混入 INFO 5200、复制普通 INFO 5200 排除项、Co-op 经历 OR 改 AND。
- 路径/来源/API 契约/既有组件专项：`.venv/bin/python -m pytest tests/test_program_pathways.py tests/test_program_sources.py tests/test_program_plan_contract.py tests/test_program_plan_widgets.py -q --tb=short --show-capture=no` → **68 passed, 3 warnings in 35.97s**。
- 实际 GET 两页来源：CS Align **48,856 bytes**、INFO Bridge **40,194 bytes**，UTC 捕获时间 **2026-10-01 21:53:01**（美国东部时间 17:53）。完整摘要见 pathway manifest；对应原始输入已固定，**两份文档的实际离线课程组合/候选表比对通过**。
- 隔离 CLI 默认只读时临时库 bytes 不变；提交两份路径文档后重跑零变化，原两份普通 MS JSON 和两个项目家族不变。API 精确筛选路径、不回退到普通 MS；第一学期请求仍 409，不将桥接课当成学期安排。
- 两个真实 Streamlit 无头组件默认未选择，显式选择后显示 Align/Bridge、2026–2027、AND 与配套 lab/recitation；不代表完整浏览器、OAuth、真实 Gemini 或生产验收。
- 最终确认全套：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/program-tests-05b2.xml` → **1321 passed, 5 warnings in 94.84s**，无跳过；相对 05B-1 新增 **16 项**回归。JUnit 报告是 Git 忽略的生成产物，复核为 tests=1321、errors=0、failures=0、skipped=0；五个警告仍为 SWIG 类型与 HTTP 422 常量弃用警告。
- tracked diff 与全部 **43 个未跟踪文件**空白检查通过；没有为检查暂存文件。本批未执行 Ruff，不宣称 lint-clean。

### 发布状态与下一段

- **未提交、未推送、未部署、未导入/迁移真实运行库**；HEAD 复核仍为 `bb2f6e3`，此前本地改动保留。本批不新增 DDL/API 契约，现有 v1.5 存储、精确路径筛选和选择组件读取新文档；生产库和旧逐条先修边未改。
- 原始来源仍需私有备份恢复；公开 manifest 不能代替匹配 HTML/元数据。规则树未接入 LLM 或学期规划，仍不计算学生个人资格。
- 下一入口：真实课程先修/共修 AND/OR 与批准条件的独立来源和表示；DS Align 先取得明确年度来源。Medical/GIEL、学院政策、跨组重用/学分计入也待核验，不将本批完成写成第五批整体验收完成。

## 05C-1 — 课程先修 / 共修语法与固定来源报告（2026-10-01）

### 范围与当前行为

- 旧爬虫只提取先修 anchor 代码，AND/OR、括号、成绩和共修丢失；旧 `required` 边不能还原逻辑。新增独立结构化语法和来源报告，**不是注册资格、成绩比较、学期规划或完整政策判定器**。
- `CatalogEntry.requisites` 在新爬取中分别保存 prerequisite/corequisite；旧 JSONL 无字段时为 `None`，不从平铺代码反推规则。状态区分 `not_listed` / `parsed` / `unparsed`；未列出不是没有要求，语法识别不是已满足要求。
- 保留括号嵌套 AND/OR、最低成绩、明确 Graduate/Undergraduate 标记和并修许可；分号/and 为 AND，or 为 OR，同层混合不猜优先级。重复 OR 分支不删、不合并成绩或学生 level；共修段不变成提前完成的先修。
- 不支持的批准/考试/转学代码/条件、空段、重复 section 或可辨认但不合规标签保留整段和原因，不返回看起来成功的部分树；树/输入有界。normalized text 只统一空白，完整字节另归档。
- 实际固定 [CS](https://catalog.northeastern.edu/course-descriptions/cs/)、[DS](https://catalog.northeastern.edu/course-descriptions/ds/)、[INFO](https://catalog.northeastern.edu/course-descriptions/info/) 2026–2027 三页院系输入。它们没有声明 Boston/个人培养路径，报告明确 `campus=null`，不补猜校区适用性；描述段内批准、学院/学校政策、个人成绩/减免和开课仍未评估。
- 离线报告明确课程列表，先验证全部来源和身份，缺失/重复课程失败；语法未解析时输出报告但 exit 2，完整语法 exit 0，坏来源/身份 exit 1 且无部分 JSON stdout。都不打开 DB、不写报告文件、不访问网络；exit 0 不是个人资格通过。
- **没有持久化新树、修改 DDL/API/UI/LLM 或重写旧边**。`Course` v1.1、旧平铺字段、v1.4 来源快照和内容 hash 保持兼容；常规摄取仍不将新树存进运行库，旧逻辑不可用警告继续有效。

### 修改文件

| 文件 | 修改 |
|---|---|
| `schemas/course_requisites.py`（新增） | 课程/AND/OR 树、成绩/level/并修标记、三状态/整段原文/原因契约；120 节点/10 层；没有资格求值 |
| `scrapers/course_requisites.py`（新增）、`scrapers/neu_catalog.py` | 保守完整段解析、重复/坏标签拒绝冒充成功、未知整段保留；CatalogEntry 新可空字段；旧代码提取和课程描述不改 |
| `schemas/course_requisite_source.py`（新增） | 独立院系 URL/年度/标题/UTC/bytes 指纹契约与归档验证；不冒充培养方案校区 scope |
| `scripts/capture_course_requisites.py`（新增） | 显式院系/年度/输出目录，不重定向、2 MB 限制、不可覆盖输入和元数据；仅抓取，不写 DB |
| `scripts/audit_course_requisites.py`（新增） | 只读离线显式课程报告、完整来源预校验、身份/歧义失败、未解析/未列段/自指警告与退出码；不自动导入旧边 |
| `data/course_requisite_sources/catalog_2026_2027_manifest.json`（新增） | 三页公开来源元数据，不包含 HTML 全文，不声明 Boston 适用性 |
| `tests/test_course_requisites.py`、`tests/test_course_requisite_sources.py`（新增） | 语法/成绩/嵌套/并修/未知/预算/坏模型、历史兼容、固定来源/不覆盖/失配失败、真实只读 CLI 等回归 |
| `scripts/backfill_prereq_edges.py` | 仅修正 docstring 中“把 OR 改成 recommended”的错误建议；旧边写入行为不变，本批未运行回填 |
| `docs/course-requisites.md`（新增）、`docs/program-plans.md`、本文件 | 记录覆盖/未知状态、院系范围、捕获/离线命令、私有恢复、当前尚未接入的边界与下段入口 |
| `data/raw/course_requisites/`（6 个生成文件，Git 忽略） | 三页实际 HTML 与元数据，由新脚本固定；原始来源不入 Git，不写课程/索引 |

### 验证记录

- 新结构与共修分离两个断言在修改前 **2 failed in 13.62s**（CatalogEntry 无 requisites）。首轮实现 **1 failed, 18 passed in 14.14s**，定位为成绩正则未正确识别 C- 的结尾边界；修正后 **19 passed in 1.61s**。
- 语法负例、成绩符号、版本兼容与来源快照专项 **89 passed in 7.18s**；增加固定来源/报告/真实 CLI 与坏标签后 **124 passed in 11.27s**；最后补 plural 坏标签、DS 四分支、重复/混合 manifest 与 CLI 无部分成功输出，**130 passed in 13.64s**。
- 实际捕获三页：CS **202,210 bytes**、DS **62,583 bytes**、INFO **87,360 bytes**；UTC 捕获时间 **2026-10-01 22:05:34**（美国东部时间 18:05）。URL/完整字节摘要在公开 manifest，HTML/sidecar 在私有忽略目录。
- 固定来源上生成 13 门课程报告，全部找到且无 `unparsed`；独立预设断言核对 CS 5001/5004/5008/5010、INFO 5100 的配套，CS 5004 的两组重复 OR 与 AND，DS 5500 的三组选一加 DS 5110，INFO 6105/7405 的 B- 与明确并修，以及 CS 5800/DS 5110 未列先修段。另有 CS 6240/5400 与 INFO 6205 报告；这不是三个院系全部课程或个人资格验收。
- 首次自选样本含当前页不存在的 INFO 6210，报告按设计整体失败、不返回其余成功项；改用实际在页中的 INFO 6105/7405 后完成上述检查，没有用相似编号替代缺失记录。
- 合成来源测试拒绝重定向/404/非 HTML/错误年度/院系/超限/无课程块；同 bytes 重抓保留原时间和输入，元数据冲突不覆盖；坏 bytes/sidecar/manifest 时间、缺文件、重复课程/院系、混合年度均失败。
- 真实临时目录 CLI 验证 exit 0、未解析 exit 2 保留原文和空树、缺课程 exit 1 无部分 JSON stdout；调用前后所有输入文件字节不变，不创建 DB。自指不自动修正，旧 CatalogSnapshot hash 保持一致。
- 最终确认全套：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/course-requisite-tests-05c1.xml` → **1412 passed, 5 warnings in 92.98s**，无跳过；相对 05B-2 新增 **91 项**回归。Git 忽略的 JUnit 报告复核为 tests=1412、errors=0、failures=0、skipped=0；五个警告仍为 SWIG 类型和 HTTP 422 常量弃用警告。
- tracked diff 与全部 **52 个未跟踪文件**的空白检查通过；没有为检查暂存文件。本批未运行 Ruff，不宣称 lint-clean。

### 发布状态与下一段

- **未提交、未推送、未部署、未导入/迁移真实运行库**；HEAD 仍为 `bb2f6e3`，此前全部本地改动保留。本批真实网络只有三页官方 GET，没有调用 Gemini/OAuth、写 query_log 或课程索引。
- 来源 HTML/元数据仍需私有受控恢复；公开 manifest 不能单独复核输入。新解析用于报告/新抓取 JSONL，不把旧结构自动升级为可信规则。
- 下一小批：独立年度来源存储、幂等/副本迁移与明确状态读取，再展示原逻辑树；描述中的批准/政策与项目更高成绩条件继续核验。DS Align 明确年度来源、medical/GIEL 完整范围与可靠规划仍待，不将第五批整体标完成。

## 05C-2 — 年度先修文档存储与课程详情展示（2026-10-01）

### 范围与当前行为

- 新增独立 `(course_id, catalog_year)` 文档存储，院系来源的校区仍为 `null`；不猜 Boston/个人路径，不自动选择最新年度。同 scope 保存当前修订，**没有同年度全部修订历史**；其他年度不被覆盖。
- 保存完整来源元数据、两类 section 和原文/树；parsed 树须与语法版本 1 对原文的结果一致，不能把 OR 改成 AND 再重算摘要。摘要不包含导入时间，重复同内容保持原记录/时间。写入重新校验模型；直接 Repository 不读归档，调用方需承担来源预核验。
- 显式同步命令默认只读；完整来源预核验在 DB 打开前完成，库中唯一代码/精确名称不符则整批失败，不重写课程来凑来源。`--commit` 只事务内增加 v1.6 表/版本标记与选中记录；晚期失败连新增表、版本标记和先前记录一起回滚。
- 新增详情 `course_requisites` 和 `/course/{id}/requisites` 精确年度接口；旧字段保持。缺表/缺文档/损坏/坏表结构明确区分，不自动 DDL、不回退最新版本；状态保留其他年度/损坏 raw 记录存在性，避免空筛选恢复旧资格图。
- 页面默认未选择，选年后显示 AND/OR、最低成绩、level、并修许可、独立共修、未解析整段和来源指纹/UTC 时间。原文/树为纯文本，恶意 HTML 不作 markup；课程身份失配/不可信来源不显示为证据链接。
- 有任何结构化记录（包括未列段/未解析/损坏）或已存在的表结构损坏时，不再显示旧平铺图；缺表/没有记录/旧接口时，旧图仅标“未核验，仅供导航”。API 旧 `prerequisites` 为兼容仍返回，旧客户端需同步升级，不能理解为自动获得新逻辑。
- **不判断个人注册/成绩/减免/开课或完整政策，不接入 LLM/prompt/第一学期安排**。旧 Course v1.1、原课程字段、旧边、v1.4 来源、项目/别名与索引不变；生产迁移/发布未做。

### 修改文件

| 文件 | 修改 |
|---|---|
| `schemas/course_requisite_document.py`（新增） | 课程/年度/完整来源/未知校区/覆盖边界和导入时间契约，parsed 原文/树一致性；读取列表状态 |
| `db/course_requisite_repository.py`（新增）、`db/init.sql` | 独立 v1.6 表，现有课程精确身份、语义摘要/幂等、坏记录隔离/计数、所有年度原始存在性；无 auto-DDL/自动提交 |
| `scripts/sync_course_requisites.py`（新增） | 显式已有 DB/manifest/来源/课程；默认 mode=ro，来源先验证、代码唯一/精确名称、显式原子迁移/存储；不改原课程/边/索引 |
| `scripts/audit_course_requisites.py` | 报告增加完整 `source` 元数据，直接来自已验证的归档，供独立同步使用；既有报告字段/只读行为保留 |
| `api/models.py`、`api/routes/course.py` | 详情结构化状态与精确年度接口；404/422/无表兼容/损坏隔离；Course schema_version 仍 1.1 |
| `app/course_requisite_view.py`（新增）、`app/streamlit_app.py` | 默认留空年度选择，安全文本原逻辑/未知状态/来源；存在结构化记录时禁止旧图回退，无记录仅旧导航警告 |
| `tests/test_course_requisite_storage.py`、`tests/test_course_requisite_contract.py`、`tests/test_course_requisite_view.py`（新增）、`tests/test_init_sql.py` | 独立存储/范围/摘要/原文树坏记录、只读/原子/真实 CLI/未知持久化，API 年度/旧库/状态，helper/两个真实无头组件与 v1.6 DDL |
| `docs/course-requisites.md`、`docs/program-plans.md`、本文件 | 更新当前接入范围、v1.6 私有副本命令、两种 CLI 退出码差异、旧客户端/图限制与下一入口 |

### 验证记录

- 详情状态、年度接口与旧库不自动建表三个新增断言在实现前 **3 failed, 3 warnings in 15.45s**；实现后连同原课程 API、语法、来源与 DDL 专项 **129 passed, 3 warnings in 10.51s**。
- 存储/来源/接口首轮 **66 passed, 4 warnings in 16.64s**；额外警告来自故意绕过模型的非法 campus 值，后续用 `pytest.warns` 明确断言并捕获，仍验证 store 拒绝，没有全局忽略警告。
- 扩展 API 与 UI 后 **55 passed, 3 warnings in 28.87s**，包含两个真实 Streamlit `AppTest`：默认留空、切换/清空年度、AND/OR/成绩/并修/共修展示、未解析原文不作为 markup，以及旧图被挡住。随后新增 unparsed 真实 CLI 提交、同年度更新和课程更名隔离，包含于最终全套。
- 只读同步时临时库 bytes 不变；首次显式迁移/导入、重复零变化；逐列比较 courses/旧边/旧来源/项目/必修/别名保持不变；引用课程不在库中也不丢 lab。晚期注入失败回滚新表/版本标记/先前插入，拼错路径不创建文件，坏来源在任何 DB 打开前失败。
- 真实 CLI 用隔离库验证默认只读、显式提交、重复幂等，以及 unparsed 可保存为明确未知。同步 exit 0 是写入/检查成功，不等于离线语法审计 exit 0；报告 `unparsed_sections`、空树和原文保留，不宣称资格通过。
- 坏列年度/JSON 年度/课程标题/摘要/标量 JSON 均隔离；即使重新计算摘要，原文 OR 与树 AND 不符仍拒绝。已有课程后来更名时旧文档隔离、不自动改名绑定；原始存在性仍挡住旧图回退。
- 对 05C-1 固定实际输入中的 **13 门课程**重新运行新文档身份/来源/原文树契约，全部通过；本检查不打开 DB，没有重新网络 GET，不将语法一致性当成完整政策/个人适用性验收。
- 最终确认全套：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/course-requisite-tests-05c2.xml` → **1470 passed, 5 warnings in 119.05s**，无跳过；相对 05C-1 新增 **58 项**回归。Git 忽略的 JUnit 报告复核为 tests=1470、errors=0、failures=0、skipped=0；五个警告仍为 SWIG 类型和 HTTP 422 常量弃用警告。
- tracked diff 与全部 **59 个未跟踪文件**空白检查通过；没有为检查暂存文件。本批未执行 Ruff，不宣称 lint-clean。

### 发布状态与下一段

- **未提交、未推送、未部署、未迁移/导入真实运行库**；HEAD 仍为 `bb2f6e3`，此前本地改动保留。本批只有固定输入读取和隔离测试，没有真实外网请求、Gemini/OAuth、生产 query_log/课程/索引写入。
- v1.6 只在测试临时库演练；已有私有备份副本的真实迁移、API/UI 同步发布、浏览器/模型验收和回滚需要另行确认。原始 HTML/sidecar 仍不在 Git，manifest 不足以独立恢复。
- 下一入口：description 中的批准/资格与学院/学校/项目更高门槛的独立证据和表示；保持未知。规则树回答、可靠学期规划、DS Align 明确来源及 medical/GIEL 完整范围仍待，第五批整体未完成。

## 05C-3 — 描述批准／资格证据与同年度项目上下文（2026-10-02）

### 范围与当前行为

- 从同一份已验证 HTML 的所有 `p.cb_desc` 保留完整段落，新增可选 `description_evidence`。关键词候选保留否定、可选许可及教学假阳性，**未解释为强制注册规则或已获批准**；不改先修/共修树、不根据背景决定减免。
- 区分旧字段 null（未捕获）、未列 description、有限关键词未匹配、候选待复核；没有匹配不表示无条件。段落/索引/标记/状态重新一致性校验，超限整批失败、不截断；完整来源与年度沿用已验证归档，不从旧 raw_text 补猜。
- 仅新增空默认字段不影响独立重构的 05C-2 内容摘要；非空证据参与 hash。旧记录读取/幂等不重写，显式来源同步才更新同年度记录。仍为 v1.6 JSON 存储，无新表/版本，不改旧课程/来源/边/索引。
- 详情的 `program_contexts` 读取时关联同年度方案，不混入课程来源 hash。只用已对照方案的显式叶子/有限未排除候选；开放前缀/范围/标签不推断。保留所有校区/路径/concentration 和可选条件，不指定个人适用性。
- 缺表/坏表/同年度坏记录/未对照方案状态明确；坏数据隔离，重复身份/scope 不取第一项。无关联不是无项目政策，不回退其他年度/旧 seed。无可用课程文档时不猜方案年份。
- 页面先选课程年度，再手动选关联方案（均默认空，清空后不带回旧选择）；描述、自由文本 scope、规则、notes/摘录均纯文本。项目桥接/毕业成绩与先修成绩分开，**不取最大成绩覆盖原文、不生成注册资格或学期安排**。
- 学校/学院完整政策、DS Align 适用来源、medical/GIEL 范围及个人 Spring/Fall 适用性仍未知；第五批整体不记作完成。本批没有接入 chat/LLM/prompt。

### 修改文件

| 文件 | 修改 |
|---|---|
| `schemas/course_description_evidence.py`、`scrapers/course_description_evidence.py`（新增） | 全描述段落、有限关键词/候选、四种未捕获/未知状态、原文一致性与预算；不解析资格语义 |
| `schemas/course_program_context.py`（新增） | 同年度显式列课匹配、已对照方案和完整 scope，拒绝重复身份/错年度/错课程/草稿 |
| `schemas/course_requisite_document.py` | 新可选描述证据与独立读取上下文；上下文只能对应可用课程文档年度 |
| `scripts/audit_course_requisites.py`、`scripts/sync_course_requisites.py` | 从已验证课程块生成并显式保存证据；原 CLI 退出码和只读/原子边界不变 |
| `db/course_requisite_repository.py` | 旧空默认 hash 兼容，非空证据入摘要；读取时关联上下文，不写课程来源/旧行 |
| `db/program_plan_repository.py` | 精确同年度扫描、scope/内容摘要验证、坏记录/草稿/坏表/重复隔离，显式课程匹配 |
| `app/course_requisite_view.py`、`api/routes/course.py` | 描述候选与全段文本、独立方案选择与全片段/来源；原先修与项目门槛分开，不默认个人路径 |
| `tests/test_course_qualification_evidence.py`、`tests/test_course_program_context.py`（新增） | 原文/否定/假阳性/预算、旧 hash、显式只读/幂等、上下文关联与隔离、API/安全文本/真实两级组件 |
| `docs/course-requisites.md`、`docs/program-plans.md`、本文件 | 当前覆盖、CLI 成功不等于资格、旧文档语义、范围学分已知限制和下一入口 |

### 验证记录

- 新增描述报告/旧库上下文两个断言在实现前 **2 failed in 16.46s**；实现后连原存储/API/UI **60 passed, 3 warnings in 39.27s**。
- 扩展首轮 **1 failed, 56 passed, 3 warnings in 21.71s**：超大记录测试使用非 JSON 被表约束先挡住，改用合法超大 JSON 检查读取预算（不是放宽约束）。随后包含课程来源/存储/API/UI、原方案存储/接口专项 **191 passed, 3 warnings in 47.03s**。
- 补纯文本 scope/规则安全后，两个本批测试文件 **64 passed, 3 warnings in 22.10s**。包含原文否定、可选申请、approval 教学假阳性、未捕获与未匹配、非法标记/索引/超限、独立重构旧摘要可读且零重写、非空证据初次更新/重复零变化。
- 隔离数据库实际验证：完整来源预核验、默认只读 bytes 不变、显式同步描述、原课程/边/来源/项目/别名逐表保持。上下文读取随方案变化即时更新但不改课程 document/hash；坏来源/scope/digest、草稿、坏表与重复身份明确未知，无 latest/seed 回退。
- 真实 Streamlit 无头组件验证默认只有空年度；选年后方案仍为空，另选路径才显示条件；清空年度/再选不会带回之前方案，原文/自由 scope/notes/规则 HTML 和 Markdown 链接不作 markup，旧图仍被挡住。不是完整浏览器/应用布局验收。
- 只读复核固定输入 **17 门课程、7 份方案片段**（未打开 DB/未重新抓取）：原 13 门加 CS 5500/5600/6954、INFO 7225。核对 admission、可申请许可、eligible、教学 approval 假阳性；确认原 Align B/项目决定例外和 INFO Bridge 核心 C/单课先修可能更高文本，不推断个人适用性或完整政策。
- 首次额外样本 DS 4996 的 `(1-4 Hours)` 超出既有标题解析，报告整体失败而非部分成功；没有将其他课程改名替代 DS 4996。单独改用实际 CS 6954 检查 eligible 描述，范围学分支持留下一批，不宣称已核验 DS 4996。
- 最终确认全套：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/course-requisite-tests-05c3.xml` → **1534 passed, 5 warnings in 120.20s**，无跳过；相对 05C-2 新增 **64 项**回归。Git 忽略的 JUnit 复核为 tests=1534、errors=0、failures=0、skipped=0，本批两个文件共 64 项；五个警告仍为 SWIG 类型与 HTTP 422 常量弃用警告。
- tracked diff 与全部 **64 个未跟踪文件**空白检查通过，没有为检查暂存。尝试改动文件 Ruff 正确性检查时 `.venv/bin/ruff` 不存在，宿主 PATH 也未找到 Ruff；未安装/修复环境，不宣称 lint-clean。

### 发布状态与下一段

- **未提交、未推送、未部署、未迁移/导入真实运行库**；HEAD 仍为 `bb2f6e3`，此前本地改动保留。本批固定输入读取和隔离测试，无新的外网 GET、Gemini/OAuth、生产 query_log/课程/索引写入。
- 同步只在测试临时库验证；运行库/真实私有副本导入、API/UI 联合发布及回滚需单独确认。HTML/sidecar 仍为私有忽略输入，公开 manifest 不能独立恢复。
- 下一小批：范围学分标题身份与固定来源回归，避免带范围的课程无法报告；继续保留完整批准/学校政策未知。规则树回答、可靠规划与生产发布不自动进入本批。

## 05C-4 — 范围学分标题身份与精确 literal 证据（2026-10-02）

### 范围与当前行为

- 修正 `1-4 Hours` 等范围标题导致整门课程被漏掉的问题，支持 `-`/`–`/`—`、小数、零与单复数 Hour；保留代码/后缀、名称内部句点和原标题学分文本，不用相近课程替代身份。
- 新增 `CatalogCreditHours` 的 fixed/range、精确 Decimal 上下限与原文一致性。JSON 小数为字符串，不经浮点舍入；现有 0–12 和 100 字符边界不扩张。反向/负数/超限/多段/未知语法/TBA/错误单位拒绝，不把坏标题变成“学分未知但身份成功”。
- 旧 `CatalogEntry.credits` 仍为整数/null，仅明确固定整数可赋值；范围（含等端点）与非整数都为 null，不取端点/平均数或舍入。新 JSONL 的 literal 若与 credits 矛盾则拒绝；旧 JSONL 没有 literal 时仍为未捕获。
- 年度文档新增可选 `credit_hours`，只来自同一已验证课程块；旧 05C-2/3 空默认 hash 独立重构可读/幂等、不重写原记录，非空 literal 入摘要。写入/读取重新核对原文与上下限，坏文档即使重算 hash 仍隔离。
- API/UI 先明确选年才展示原文、固定值或范围，明确班次和个人学位计入未确认。旧详情若有整数，不视为此范围的选定值；不改 Course v1.1 整数字段，不增加范围筛选、求和/学期安排或资格计算。
- 仍用独立 v1.6 JSON 表，无新迁移；显式同步默认只读，选中坏标题整批失败并在 DB 打开前拒绝。v1.4 快照与固定课程既有 hash 不变，v1.4 **不保存/区分精确 literal**；完整证据靠独立年度同步，不宣称普通摄取或旧客户端已经得到全部新语义。
- 学校/学院完整政策、DS Align 来源与个人批准/适用性仍未知；范围标题识别不会放宽外部先修代码、删除未知分支或使第五批整体完成。

### 修改文件

| 文件 | 修改 |
|---|---|
| `schemas/catalog_credit_hours.py`（新增） | 有界 literal 文本、精确 Decimal fixed/range、原文/上下限一致性与安全整数投影 |
| `scrapers/neu_catalog.py` | 范围标题身份识别、可选 credit_hours、新 JSONL 与旧 credits 一致性；不改 description/先修/共修/跨列逻辑 |
| `schemas/course_requisite_document.py`、`db/course_requisite_repository.py` | 独立可选证据、两代空默认内容摘要兼容；未知/原始存在性边界不变 |
| `scripts/audit_course_requisites.py`、`scripts/sync_course_requisites.py` | 同一已验证课程块生成/保存 literal、范围与小数限制警告，保留只读/原子与两类退出码含义 |
| `app/course_requisite_view.py`、`api/routes/course.py` | 年度详情固定/范围/未捕获区分与原文展示、旧整数不作选定值警告；端点说明 |
| `tests/test_catalog_credit_hours.py`（新增）、`tests/test_course_qualification_evidence.py` | 范围/零/精确小数/坏标题与字段、JSONL/旧 v1.4 摘要、两代文档 hash、隔离摄取/同步/真实 CLI/API/真实组件；旧摘要测试明确排除本批不存在于旧版的字段 |
| `docs/course-requisites.md`、`docs/program-plans.md`、本文件 | literal JSON 契约、旧整数/快照/客户端限制、35 个范围及未知条款、当前验收和下一入口 |

### 验证记录

- 范围标题与离线报告两个新增断言在实现前 **2 failed in 13.32s**；实现后连历史 scraper/描述/来源专项 **86 passed in 9.58s**。
- 扩展首轮 **1 failed, 175 passed, 3 warnings in 41.01s**：测试误把 credits 当实体列，实际在 metadata/generated_json；改为检查两份 JSON 的 null，没有改 DB/仓库结构。随后范围/历史 scraper/旧来源/描述/先修/独立存储/API/UI/上下文专项 **318 passed, 3 warnings in 51.98s**。
- 再补后缀/非断行空白/名称句点、范围与旧式外部先修整段未知、真实同步 CLI 后，本批文件 **69 passed, 3 warnings in 28.38s**。
- 测试确认 fixed 零/整数不变，小数不截断、不将接近整数的小数用 float 舍入；范围不同分隔符/等端点保持 range 与旧 credits=null。反向/错误单位/超限/TBA/多段和原文/模型篡改拒绝，正常院系解析只跳过坏块，显式报告选中坏块无部分成功。
- 独立重构旧 JSONL/v1.4 固定源 hash、05C-2 和含 description 的 05C-3 文档摘要，旧记录可读且重复不重写；非空范围增加内容变更。故意改上限且重算 hash 仍隔离，保留 raw 存在性，不恢复旧资格图。
- 隔离库验证普通摄取的 Course v1.1、metadata/generated_json、v1.4 credits 都为 null；范围精确信息不假装已进 v1.4。显式年度同步默认只读 bytes 不变，首次写入/重复零变化/新范围仅更新独立文档；逐表检查原课程/旧边/旧来源/项目/别名保持不变，坏范围在开 DB 前拒绝。
- 真实离线报告 CLI 的范围成功 exit 0、选中另一坏标题 exit 1 且无部分 JSON/无输入文件改动；真实同步 CLI 可保存范围与 unparsed 原文，exit 0 仅为同步成功，`unparsed_sections=1`、整段/空树保留。API 原整数字段不变，无年度回退；真实 Streamlit 无头组件验证选年才显示范围、实际班次未知、不出现固定值/旧图、清空后不留文本。
- 已有 2026-2027 三份归档仅只读：全部 **35 个范围标题**逐项核对（CS 13、DS 10、INFO 12），与前批 17 门合并 **52 份年度文档契约**全部通过；未打开 DB、未重新 GET。DS 4996 精确名称和 `1-4 Hours`、approved/restricted 候选、未列先修/共修确认；DS 7995 `1-4 Hours` 保留而非自动算计入。
- 合并报告 **1 个 unparsed**：CS 4992 原先修含 `CIS 310M` 旧式外部代码，整段保留、空树、不放宽或部分解析；范围身份全部找到不等于全部先修语法成功，审计应 exit 2。
- 最终确认全套：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/course-requisite-tests-05c4.xml` → **1603 passed, 5 warnings in 173.26s**，无跳过；相对 05C-3 新增 **69 项**回归。Git 忽略的 JUnit 复核为 tests=1603、errors=0、failures=0、skipped=0，本批文件 69 项；五个警告仍为 SWIG 类型与 HTTP 422 常量弃用警告。
- tracked diff 与最终全部 **66 个未跟踪文件**空白检查通过；未暂存。当前项目 `.venv/bin/ruff` 和宿主命令仍不可用，本批未安装或运行 Ruff，不宣称 lint-clean。

### 发布状态与下一段

- **未提交、未推送、未部署、未迁移/导入真实运行库**；HEAD 仍为 `bb2f6e3`，此前全部本地改动保留。只有固定归档读取和隔离测试，无新外网 GET、Gemini/OAuth、生产 query_log/课程/索引写入。
- 不重抓/改写历史输入、不自动回填已有课程整数或重建索引；新增 range 课程只有以后显式抓取/导入才进入课程库。实际私有副本演练、API/UI 联合发布、浏览器/模型验收与回滚仍需单独确认。
- 下一入口：分 scope 核验学校/学院政策证据，继续保留个人资格未知；DS Align 年度来源仍待，规则树回答、可靠规划和生产发布不自动进入本批。

## 05D-1 — 学校／学院政策的有限证据与精确范围关联（2026-10-02）

### 范围与原因

- 上批已有课程先修、描述与范围学分，但完整院校政策仍未知。直接把通用累计 GPA／学分规则当个人条件，会混淆学院、项目 core、bridge 单课成绩与课程先修的不同用途。
- 官方 MSDS overview 按 concentration 指定三个 home colleges，不是所有 DS 课程／学生都归 Khoury；学校与 Khoury 的 probation 期限、Engineering 的学分与夏季评估条件也不能自动合并。
- 这批先建立独立、离线、有限片段的政策证据。当前仍以 Boston、2026–2027 的既有方案样本为范围，用户个人 catalog term／入学年／POS 未确认。Engineering 提及 fall／spring orientation 也没有被当作所有项目招生季节的证据。

### 已完成的有限范围

- 显式抓取 5 个官方 graduate policy 章节：学校 Minimum Cumulative GPA；Khoury Academic Probation and Dismissal；CAMD Master’s Degree Policies；Engineering Academic Standing Policy 与 Course Selection。原 HTML／sidecar 共 10 个不可变私有文件，捕获时间 **2026-10-02 14:42:02–03 UTC**；不是历史归档覆盖，也没有将原网页加入 Git。
- 公开 evidence bundle 保存 **14 个选定段落**的原文位置／标题／文字 SHA、人工对照摘要和明确限制，记录 reviewer／日期；coverage 仅 `selected_fragments_only`。不会因页面 hash 相符自动声称摘要语义正确、完整学院政策已核完或个人适用性已确定。
- 精确关联现有 **7 个范围**：CS 普通与 Align、DS 三方向、INFO 普通 general 与 Bridge。关联同时固定 `plan_id`、家族／校区／年度／路径／concentration、方案当前 content hash、home college 与政策 IDs；修改方案内容／scope／审核后，旧关联必须重新核对。
- Home college 从已验证的项目原 HTML 核对：CS／INFO 的 breadcrumb 名称及 href，DS overview 的具体方向／学院映射；不从课程前缀或共同 core 猜。仅大学通用政策与该 link 声明 home college 的政策可关联，不借用别的学院。政策页未声明 Boston 独占，Boston 只表示关联方案范围。
- 来源检查覆盖完整 bytes／sidecar、URL／authority 子章节、标题、年度、捕获时间和段落位置／最近标题／文字 SHA。导航／页脚、重复身份／位置、错年度／错学院／旧 revision、draft 方案、未知范围、坏源均拒绝；失败 CLI 只有 stderr，不输出部分已核验 JSON。
- 学校／学院／项目／课程条件保持独立；不求和、取成绩阈值最大值、合并 probation 期限、判断院外课程或批准，不生成 eligible／graduation_ready。CAMD 学院 30 学分底线不改 MSDS 的 32；Engineering 通用 prerequisite 规则不删 INFO Bridge 的既有课程；standing GPA 计入不等于学位学分计入。

### 修改文件

| 文件 | 修改 |
|---|---|
| `schemas/program_policy.py`（新增） | 独立请求／段落／有限证据／精确关联模型，URL authority 与年度边界、离线源验证、有限 home-college 来源核对 |
| `scripts/capture_program_policy_sources.py`（新增） | 显式官方 HTML、无跳转／预算控制、不可变私有输入、重复保留首次时间；检查两份已有输入后才补缺失半份，不覆盖冲突 |
| `scripts/audit_program_policy_sources.py`（新增） | 不联网／不开 DB 的整批证据审计；方案内容 revision 与来源／home college 双核；全部成功后才输出 JSON |
| `data/program_policy_seed/boston_2026_2027_source_requests.json`、`boston_2026_2027_evidence.json`（新增） | 5 个显式来源、14 个有限片段与 7 个固定 scope/revision 关联；不是完整规则 seed |
| `tests/test_program_policy_evidence.py`（新增） | 67 项模型、预算、来源替身、不可变存档、篡改、同 SHA 重算后的错页面、精确范围／home college、只读真实 CLI 与公共 bundle 契约 |
| `docs/program-policy-evidence.md`（新增）、`docs/program-plans.md`、本文件 | 边界、官方来源、离线命令、覆盖限制、关联失效条件、当前验收和下一批入口 |

### 验证记录

- 新模块实现前专项 collection 因模块不存在失败；这是新功能 RED，不称旧实现已有政策测试缺陷。初版实现后 **18 passed in 0.92s**。
- 扩展政策／历史项目来源／存储／路径专项 **119 passed, 3 warnings in 49.30s**；补齐独立 home-college 检查、同 hash 重算错页面、复核日期与预算后，本批文件 **67 passed in 4.77s**，无跳过。持久 JUnit `data/raw/program-policy-focused-05d1.xml` 复核 tests=67、errors=0、failures=0、skipped=0。
- 测试同时覆盖旧年度／别的学院／未知引用／完整覆盖伪称、重复片段／scope、真实原始输入损坏与 sidecar 时间篡改、正文位置／标题／文字指纹；哪怕重新计算 SHA，页面身份／版次错误也拒绝。修改完整方案内容会使关联失效，draft 即使重新算关联 hash 也拒绝；关联审核不能早于项目复核。
- 独立合成输入检查捕获重复不改首次时间／bytes，坏 HTTP／跳转／MIME／超限不写输入；sidecar 冲突且 HTML 缺失时也不补写。只读审计真实 CLI 成功 exit 0、损坏 exit 1 且无 stdout，逐文件 bytes 不变；显式禁止 SQLite／HTTP client 的测试仍可完整审计。
- 对本次 **5 个真实官方页面**和此前 5 个项目原存档运行实际审计 CLI，exit 0；确认 **5 policies、14 fragments、7 exact plan links**，coverage 仍是 `selected_fragments_only`。不会把段落／关联一致性通过写成完整政策／资格通过。
- 最终全套回归：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/program-policy-tests-05d1.xml` → **1670 passed, 5 warnings in 134.72s**，无跳过。相对 05C-4 新增 **67 项**；持久 JUnit 复核 tests=1670、errors=0、failures=0、skipped=0，本批文件 67 项全部执行。五个警告仍为已有 SWIG 类型和 HTTP 422 常量弃用警告。
- tracked diff 与最终全部 **73 个未跟踪文件**空白检查通过；未暂存。项目虚拟环境／宿主均无 Ruff，本批未安装或运行，不宣称 lint-clean。

### 发布状态与下一段

- **未提交、未推送、未部署、未迁移／导入真实运行库**；HEAD 仍为 `bb2f6e3`，之前全部本地改动保留。本批只有上述官方 HTML GET、不可变输入添加和隔离／只读验证，没有 Gemini／OAuth、生产 query_log、课程或索引写入。
- 没有修改 `ProgramPlan` 字段、已有方案 seed／content hash、v1.5／v1.6、API／UI／对话；证据与旧方案导入保持分离，避免只读来源检查被误认为运行库已更新。
- 下一入口 **05D-2**：在明确选择的完整方案范围内只读展示政策证据与缺失／版本变化警告，再逐条补足完整政策及项目例外。DS Align 明确年度来源、个人 catalog term／POS／批准、跨组重复计入、实际 section availability 仍待，不能据此自动安排学期或保证资格；生产发布继续单独确认。

## 05D-2 — 选定方案的政策只读详情与失效警告（2026-10-02）

### 范围与原因

- 上批政策证据只有离线审计，方案详情看不到这些有限片段；直接把全部学院资料塞进家族浏览会混淆范围，也可能把旧界面缓存的方案套上后端新版本证据。
- 原方案选择组件没有返回选定文档，记录失效后仍可能保留旧 widget key，触发 KeyError。需要默认留空、清空／刷新后不自动恢复，明确完整 scope 才请求政策。
- 当前仍是 Boston、2026–2027 的样本，不认定用户个人 catalog term。没有追加政策网页或新培养方案，没有把任何规则并入资格判断或 LLM。

### 已完成

- 新增独立公开 GET `/programs/{program_id}/plans/{plan_id}/policies`：先核该家族当前可用的精确方案，再只读加载关联证据。未知／跨家族／旧表缺失／坏方案返回 404，不猜旧 seed、不自动 DDL；缺失、draft、无关联、范围／revision 变化、损坏各有明确状态，无可用片段。
- HTTP 200 政策状态均使用 `Cache-Control: no-store`；客户端不缓存政策。`ready` 只是选定归档／段落／关联核对通过，不是系统健康或个人资格通过；schema 禁止其他状态携带政策、关联和审核记录。
- 有界只读 loader 复用冻结输入验证，核对完整方案内容 hash、scope／审核日期、项目原源与 home college，并只读该方案所有关联政策。失效时整组抑制，不给部分可信资料；未选定学院的原始存档缺失不阻塞当前范围，整体 bundle 声明仍须完整有效。
- UI 必须先选择完整方案，随后重新验证响应 ID／scope／revision、审核和原文指纹；选空不请求。来源、时间／SHA、审核者、摘要／限制与原段落可展开查看；学校通用与 home-college 条件分别展示，所有不可信文本不进入 Markdown／HTML。
- 失效／重复 ID／重复 scope 清空相关选择，不取最后一份或最新方案。新增“刷新方案及政策证据”按钮，仅清除当前家族 curriculum 缓存和选择，重载后需明确重新选择；后端版本变化、断网、404、非法 JSON、坏源均不留下此前成功的政策。
- 默认 bundle 在项目公开数据目录；两个原始存档目录跟随解析后的 `SQLITE_PATH` 父目录，可显式环境覆盖，不硬编码开发机路径；SQLite 配置为相对路径时仍沿用原 cwd 解析语义。不自动抓取或补文件；Git／Docker 忽略的私有原存档未复制或发布。旧方案 seed、字段／hash、v1.5／v1.6、课程／先修／索引均保持不变。

### 修改文件

| 文件 | 修改 |
|---|---|
| `schemas/program_policy_view.py`（新增） | 完整 scope、带原段落的有限证据和六种状态；ready 关联／年度／学院／指纹核对，其他状态禁止可用证据 |
| `rag/program_policy_evidence.py`（新增） | 独立文件只读 loader，无 DB／HTTP／缓存／写入；复用源核验，精确选定关联、全部成功才返回 |
| `api/routes/program.py`、`api/dependencies.py` | 精确当前方案 GET、独立 reader 注入、no-store、未知／坏方案隔离；旧 listing／curriculum／plans 响应不变 |
| `config/settings.py`、`.env.example` | 三个只读证据路径配置；存档默认跟随 SQLite 数据目录，不改运行 `.env` 或 compose |
| `app/api_client.py` | 单个选定方案的公共 GET，URL 编码、复用现有超时／网络错误处理，不缓存政策 |
| `app/program_plan_view.py`、`app/program_view.py` | 返回明确选定文档、清空失效／歧义选择；选中才加载政策，手动刷新只清当前家族缓存／选择 |
| `app/program_policy_view.py`（新增） | 响应复核、固定警告与纯文本证据；展示有限范围及不确定性，不展示旧成功响应或合并规则 |
| `tests/test_program_policy_view.py`（新增） | 67 项独立源／状态／wire／API／客户端／纯文本／真实无头组件回归，隔离 DB／HTTP／临时输入 |
| `docs/program-policy-evidence.md`、`docs/program-plans.md`、本文件 | 状态、只读端点、路径／私有输入部署限制、刷新／scope 边界、验收与下一入口 |

### 验证记录

- 实现前新增回归 **3 failed, 3 warnings in 15.13s**：未返回所选方案、失效 ID KeyError、政策端点不存在；初版实现后含历史方案显示／政策源专项 **79 passed, 3 warnings in 7.65s**。
- 补充独立源／wire／API／客户端边界后，含历史政策、方案显示／契约与客户端专项 **175 passed, 3 warnings in 10.15s**；再加入原文文本注入和完整 browser-panel 无头行为，本批及历史 widget 专项 **70 passed, 3 warnings in 24.15s**，无跳过。持久 JUnit `data/raw/program-policy-view-focused-05d2.xml` 为 tests=70／errors=0／failures=0／skipped=0，本批 **67 项**与历史 widget 3 项全部执行。
- 三个真实 Streamlit 无头测试覆盖首次 None 无政策 GET、显式选择、None 清空后不残留、重新选择重新读取、按钮刷新清选择并重取方案；接口中断及私有源缺失不回用成功响应；后台方案更新不能覆盖旧 UI 版本，刷新后须重新选择且旧政策关联仍标 stale。不是完整桌面浏览器／OAuth 验收。
- 模型／reader 检查六种状态、全 scope／内容 revision／审核日期、目录／sidecar／原文篡改、预算／不可读／未知关联；声明为 unavailable 却含片段、换学院／链接／source hash、complete／eligible 伪称均拒绝。显式禁止 SQLite／HTTP 仍可读取；文件 bytes 不变，重复请求会发现后续坏源而不复用旧结果。
- 真实替身 API 只读 SQL、总写入计数、旧方案 JSON／hash 与临时文件 bytes 均不变；列举／详情／plans 契约与聊天 409 保留。未知／跨家族／损坏方案不调用 reader，旧库未自动建表，源缺失的有效方案返回 200／unavailable／空片段，不是假 ready。
- 只读核对本地已存 **7 个真实范围**均 ready：CS 普通／Align 和 DS-CS 各 2 页／5 片段；DS-CAMD 为 2 页／6 片段；DS-Engineering 与 INFO 普通／Bridge 各 3 页／9 片段。只是分别验证既有 **5 页／14 个不同片段**的关联，不把跨方案复用次数当新增来源；无新 GET／DB。
- 最终全套回归：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/program-policy-view-tests-05d2.xml` → **1737 passed, 5 warnings in 144.30s**，无跳过。相对 05D-1 新增 **67 项**；持久 JUnit 复核 tests=1737、errors=0、failures=0、skipped=0，本批文件 67 项全部执行。五个警告仍为已有 SWIG 类型和 HTTP 422 常量弃用警告。
- tracked diff 与最终全部 **77 个未跟踪文件**空白检查通过；未暂存。Ruff 在宿主／虚拟环境仍不可用，未安装或运行，不宣称 lint-clean。

### 发布状态与下一段

- **未提交、未推送、未部署、未迁移／导入真实运行库**；HEAD 仍为 `bb2f6e3`，之前全部本地改动保留。只有本地源只读核对、隔离数据库／HTTP 替身与无头组件，没有外网 GET、Gemini／OAuth、生产 query_log／课程／索引写入。
- 运行库没有版本化方案时仍是旧 seed 浏览，政策端点不自动导入；部署时须明确准备已核对私有输入与目录，并联合发布 API/UI。这些未执行，不把临时库／组件通过当上线验收。
- 下一入口 **05D-3**：继续核验重修／课程替代／转学分／学分计入与具体项目例外，保持学院和用途独立。DS Align 年度来源、个人 catalog term／POS／批准、完整政策与实际 section availability 仍待；不自动推进个人资格、可靠排课或生产发布。

## 05D-3 — 重修／替代／转入／共享片段与完整列表源证据（2026-10-02）

### 范围与原因

- 官方转入和共享政策的重要条件位于 `ul`／`ol`，旧读取器仅核验 `p`；只摘额度段落会漏掉学位层级、审批、时间、未复用限制和例外。需要保留整个外层列表及嵌套条件，同时不移动旧段落索引。
- 学校通用要求、Khoury 重修／transfer／completed-degree sharing 和 Engineering 成绩补救替代分别有不同用途；不能把百分比取最小、共享当跨组重复计入、免修当获得学分，或把 Boston 套到其他地区流程。
- 仍是 Boston、2026–2027 的有限样本，个人 catalog term 未确认。只扩展政策层及原 7 个精确关联，不新建培养方案，不计算个人批准、成绩、学分／资格。

### 已完成

- 浏览官方 2026–2027 学校／学院入口及相关章节，显式捕获新增 **8 页**：学校 Retaking、Course Substitutions、Transfer and Other Advanced Standing Credit、Course Credit Sharing；Khoury Retaking、Transfer of Credit、Credit Sharing；Engineering Course Retake / Course Substitution。捕获时间 **2026-10-02T19:33:36.989351Z–19:33:37.457623Z**，原 HTML／sidecar 只增不覆盖；旧 5 页的首次捕获记录保留。
- 新增 **36 片段**，当前 bundle 为 **13 页／50 片段（46 段落、4 整个外层列表）／7 个精确方案关联**。来源 URL／title／edition／bytes／时间／完整 SHA 与片段位置／heading／文字 hash 固定，摘要及限制逐条对照；不是新增 7 份方案或完整政策。
- `source_kind` 明确 paragraph／list，默认 paragraph；保留 `paragraph_index`／`paragraph_sha256`／`source_paragraph` 兼容字段，按声明种类独立索引。嵌套列表留在父块内，旧 `p` 顺序不变，同种重复位置拒绝；空／超预算列表拒绝而非丢弃或截断。列表是原文块，不是条件树，规范化文字不保存页面缩进／项目符号。
- 捕获也验证列表预算；离线审计和 reader 使用种类＋位置核对并只在全部成功后输出。API 既有精确 scope／revision、no-store 和失败无片段保持，UI 用“列表块”区分段落、纯文本显示原文、坏源重读后不保留成功证据。无需改变 API 路径或数据库 schema；未来须联合发布 API/UI。
- Boston 仅选择学校替代页的 Massachusetts 组：保留 advisor 与项目／原课程部门的审批；没有套另一地区 Provost 流程。Engineering 的补救用途、非 core／不能重修、联合批准及 good-standing 限制均独立于通用项目要求替代。
- 转入与共享保留不同来源／起算点／用途；Khoury completed-degree 共享的课程比例录取门槛、学分比例额度／官方例子、延期和无学分 waiver 分开；不改原候选池、先修或成绩。Khoury 院外条款与在读批准／跨学院项目的适用关系明确待学院解释，不自动解冲突。CAMD 没有新院级例外来源，不借用其他学院政策。

### 修改文件

| 文件 | 修改 |
|---|---|
| `schemas/program_policy.py` | 段落／外层列表独立定位与预算、种类字段、同种去重、选定块源核对；旧段落索引不变 |
| `schemas/program_policy_view.py` | 原文指纹错误描述涵盖段落／列表；原 transport 字段／六状态保留 |
| `scripts/audit_program_policy_sources.py`、`rag/program_policy_evidence.py` | 使用已核种类＋位置输出原文，失败无部分证据；无 DB／网络／写入 |
| `app/program_policy_view.py` | 原文展开标识 p／l 与段落／列表块，仍纯文本、不缓存或合并规则 |
| `data/program_policy_seed/boston_2026_2027_credit_source_requests.json`（新增） | 显式 8 页增量抓取入口，避免重复抓旧 5 页 |
| `data/program_policy_seed/boston_2026_2027_source_requests.json`、`boston_2026_2027_evidence.json` | 合并 13 页声明／50 片段，扩展原 7 个精确 scope／revision 的学校及 home-college 引用；方案 hash 不变 |
| `tests/test_program_policy_credit.py`（新增） | 43 项列表源／预算／条件／wire／只读 reader／audit／API／纯文本及真实无头组件回归，不依赖私有真实存档 |
| `tests/test_program_policy_evidence.py` | 公共样本计数扩展为 13／50／7，仍核请求集合、有限覆盖及精确方案 hash |
| `docs/program-policy-evidence.md`、`docs/program-plans.md`、本文件 | 当前来源／用途边界、兼容定位字段、修改与验证记录、下一入口 |

### 验证记录

- 实现前新增测试初跑 **14 failed、10 passed、3 warnings in 16.70s**：没有列表读取／种类字段、capture 忽略大列表、reader／界面／新公共片段尚不可用；API 测试辅助调用同时修正为现有 `store`。这是回归基线，不是验收通过。
- 初版功能及数据后专项 **158 passed, 3 warnings in 25.76s**；补嵌套条件重算归档 SHA 仍被片段指纹拒绝、旧段落索引、reviewed qualifiers、failure wire 和真实组件后，最终专项 **180 passed, 3 warnings in 26.09s**，无跳过。持久 JUnit `data/raw/program-policy-credit-focused-05d3.xml` 复核 tests=180、errors=0、failures=0、skipped=0，本批 **43 项**全部执行。
- 真实无头组件显式选中才显示完整列表；后续原输入条件篡改，下一次运行只显示失效提示，原列表不保留。不是完整桌面浏览器／OAuth 验收。
- 真实离线 CLI 审计通过 **13／50／7**，stderr 为空，全部输入 hash 前后相同；4 个列表定位分别是 university-transfer、university-credit-sharing、khoury-transfer、khoury-credit-sharing 的 l0。所有 7 个真实方案分别 reader ready：CS 普通／Align 与 DS-CS 为 9 页／33 片段，DS-CAMD 为 6／18，DS-Engineering 与 INFO 普通／Bridge 为 8／29。跨方案复用次数不当新增来源数。
- 最终全套回归：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/program-policy-credit-tests-05d3.xml` → **1780 passed, 5 warnings in 137.71s**，无跳过；持久 JUnit 复核 tests=1780、errors=0、failures=0、skipped=0，相对 05D-2 新增 **43 项**全部执行。五个警告仍是既有 SWIG 类型及 HTTP 422 常量弃用。
- 最终 tracked diff 与全部 **79 个未跟踪文件**空白检查通过；未暂存。宿主／虚拟环境 Ruff 不可用，本批未安装或运行，不宣称 lint-clean；本批五个 Python 功能源文件内存编译语法检查通过。

### 发布状态与下一段

- **未提交、未推送、未部署、未迁移／导入真实运行库**；HEAD 仍为 `bb2f6e3`，此前本地改动全部保留。新增真实操作仅官方只读页面访问、8 页不可变私有输入添加和本地只读审计；测试库、HTTP 替身和组件隔离，没有 Gemini／OAuth、生产 query_log／课程／索引写入。
- `ProgramPlan` 字段、原方案 seed／content hash、v1.5／v1.6 和运行 `.env`／compose 不变，私有 raw 没有复制到 NAS。来源存档仍被 Git／Docker 忽略，发布须明确准备输入，缺失只返回 unavailable。
- 下一入口 **05D-4**：核验课程学分有效期及剩余项目例外，继续区分同一方案内跨组计入与不同 credential 共享。DS Align 年度来源、个人 catalog term／POS／批准、完整政策和实际 section availability 仍待；不据片段一致性生成个人资格或可靠学期安排。

## 05D-4 — 学分有效期、年度一致性与项目例外证据（2026-10-02）

### 范围与原因

- 学分有效期、转入受理窗口与不同 credential 共享的期限用途不同，不能统一成个人毕业日期。延期申请／部门推荐不等于相关办公室最终批准。
- 新官方页正文中的 `.onthispage` 目录位于 `#textcontainer` 内，旧解析会将其作为列表，且导航标题／嵌套文字能污染真实证据；须先排除明确导航节点，保留普通链接与仅有 `notinpdf` 的实际政策。
- 学校 All Graduate Degree Programs、Minimum Cumulative GPA 与 Khoury 的重修表述不一致，不能自行选宽／严或自动决定优先级。Engineering 证书共享额度依项目类别、指定证书／concentration 和课程批准，不通用于所有 Engineering／DS。
- 仍仅针对既有 Boston、2026–2027 的七个方案样本，个人 catalog term／POS 未确认，不扩成完整政策或资格／学期安排引擎。

### 已完成

- 浏览官方当前年度学校／学院入口并显式捕获新增 **5 页**：学校 Time Limit for Course Credit、Master's Degree Regulations、All Graduate Degree Programs；Engineering Program Completion、Certificate Policies and Procedures。捕获时间 **2026-10-02T19:47:25.439688Z–19:48:13.876430Z**，原 HTML／sidecar 不可覆盖，旧 13 页首次元数据保留。
- 两次默认抓取发生 `RemoteProtocolError`，已有合法输入保留；Windows／WSL 单次 GET 检查成功后，本批通过现有 capture 函数、禁用 keep-alive 的独立连接完成全部 5 页。没有据此认定已查明网络根因，也未修改抓取器或自动摘要代码。
- 新页新增 **24 片段**，既有 CAMD 存档另选入 leave／七年有效期／延期流程 **3 段**，共增加 **27 片段**。当前为 **18 页／77 片段（70 段落、7 整个外层列表）／7 个精确方案关联**；不是 18 份培养方案或完整政策。
- 学校新增三页关联所有七个范围；Engineering 两页只关联三个 Engineering 范围；CAMD 新段只随自身 home-college 政策。原方案 seed、scope、内容 hash 不变，原 13 份 source 元数据和原 50 片段的位置／标题／文字 hash／摘要均保留；两个既有重修限制字段追加跨章节差异提示。
- 解析器在正文容器内排除 `nav`、`footer`、`role=navigation`、`.onthispage` 整个节点后才找标题、编号或读取父列表；不删除普通链接或仅 `notinpdf` 的真实条款。Engineering 证书列表选定位置为 l0／l2／l5，不包含目录。
- 七年学分有效期与 office 批准延期分别保留；CAMD petition 需剩余要求完成计划、逐门内容未变确认，部门建议不是最终批准；leave 整段保留 medical 例外但不推导自动延期。major／concentration 同一年度及后来方向整体转年度不意味着个人自动升级。
- 学校硕士 30 学分通用底线不替换项目要求；在 NEU 取得且尚未用于 NEU 学位的学分与外校取得 transfer 分开。条件性考试／thesis 不套所有路径。Engineering 学位计入课程 GPA、core 最低 C 和 standing／先修用途分开。
- Engineering 证书的在读申请时点、good standing／PhD 分支、课程完成时点、eligible course／petition、disciplinary 8 学分及完整 16 学分例外、SEIS 16 学分、跨证书／PlusOne／本科已用与额外课区别分别保留；不按前缀分型或证明个人获批。证书页境内／国际身份列表未选入，不提供个人移民／医疗判断。

### 修改文件

| 文件 | 修改 |
|---|---|
| `schemas/program_policy.py` | 排除正文内部明确导航，避免标题／列表位置／父列表文字污染；普通真实内容与旧选定定位保留 |
| `data/program_policy_seed/boston_2026_2027_validity_source_requests.json`（新增） | 显式 5 页增量入口，不重抓 CAMD 或其他旧来源 |
| `data/program_policy_seed/boston_2026_2027_source_requests.json`、`boston_2026_2027_evidence.json` | 18 页声明／77 有限片段／7 原范围关联，延期／审批／例外与重修不一致限制明确化 |
| `tests/test_program_policy_validity.py`（新增） | 33 项导航／嵌套污染／普通链接保留、增量范围、方案 revision、摘要条件／冲突／完整例外与纯文本未知期限回归 |
| `tests/test_program_policy_evidence.py`、`tests/test_program_policy_credit.py` | 更新总体 18／77／7 计数；原 05D-3 四列表断言限定在该批八页内，不放宽旧覆盖要求 |
| `docs/program-policy-evidence.md`、`docs/program-plans.md`、本文件 | 有效期与项目例外、目录排除契约、本批修改／验证及 05E 收束入口 |

### 验证记录

- 实现前新增测试 **31 failed、2 passed、3 warnings in 15.82s**：导航污染已复现，新政策／关联尚未加入；这是回归基线，不是通过。
- 首次专项命令误用不存在的 widget 文件，产出 tests=0 的 JUnit，未当成通过；更正为 `test_program_plan_widgets.py` 后第一轮 **1 failed、212 passed、3 warnings in 32.83s**。跨证书摘要补上中文“研究生证书”标签后，最终专项 **213 passed, 3 warnings in 33.43s**。持久 JUnit `data/raw/program-policy-focused-tests-05d4.xml` 复核 tests=213、errors=0、failures=0、skipped=0，本批 **33 项**全部执行。
- 真实只读审计 CLI exit 0，核对 **18／77／7**；全部七个当前方案 reader 为 ready：CS 普通／Align 与 DS-CS **12 页／43 片段**，DS-CAMD **9／31**，DS-Engineering 与 INFO 普通／Bridge **13／53**。审计／reader 前后 **49 个输入文件** hash 未变，未打开数据库或抓新网页。
- 原 13 份来源元数据、50 片段位置／标题／hash／摘要与七个关联 scope／方案 revision 对照未变；最终全部 77 片段再次匹配来源。4 个本批涉及 Python 文件内存编译语法检查通过；宿主 Ruff 未找到、WSL 虚拟环境无 Ruff，本批未安装或运行，不宣称 lint-clean。
- 最终全套：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/program-policy-validity-tests-05d4.xml` → **1813 passed, 5 warnings in 152.13s**，无跳过；JUnit 复核 tests=1813、errors=0、failures=0、skipped=0，新增 **33 项**全部执行。五个警告仍为既有 SWIG 类型和 HTTP 422 常量弃用。
- tracked diff 与当时全部 **81 个未跟踪文件**空白检查通过，未暂存；05E 收束后会再检查最终文档。

### 发布状态与下一段

- **未提交、未推送、未部署、未迁移／导入真实运行库**；HEAD 仍为 `bb2f6e3`，之前全部本地修改保留。新增真实操作仅官方只读访问、5 页私有不可变输入添加及离线审计／reader；无 Gemini／OAuth、生产 query_log／课程／索引写入。
- `ProgramPlan` 字段、原方案 JSON、v1.5／v1.6、运行 `.env`／compose 不变；私有来源没有复制到 NAS，仍被 Git／Docker 忽略；未准备输入的发布环境只会返回 unavailable，不能将本地 ready 当线上验收。
- 下一入口 **05E**：第五批整体离线验收及缺口清单，收束既有功能后进入第六批分享／反馈；不无限补政策或宣布完整核验。DS Align 年度来源、完整学院政策及其他项目例外、跨组计入、个人 catalog term／POS／批准、实际 section availability 仍待。私有来源恢复、数据库副本演练及真实部署仍需单独确认。

## 05E — 第五批整体离线复核与缺口清单（2026-10-02）

### 范围与原因

- 在继续扩大来源片段前先收束既有第五批功能：确认培养方案、课程年度证据和学校／home-college 政策各自有限范围一致，明确哪些未知不应由测试 exit 0 或 ready 掩盖。
- 用户在本轮验收过程中再次要求继续推进，本轮因此在完成 05D-4 后接着执行 05E。没有将继续开发视为生产迁移、账号登录或分发消息授权。

### 已完成与产物

- 两次真实项目表格审计 CLI 均 exit 0：5 份普通 scope＋CS Align／INFO Bridge 2 份；课程组合、候选／分组选修与可选分支核对，7 份 coverage 均为 partial。
- 固定 3 个院系原输入，独立枚举全部 35 个范围标题（CS 13／DS 10／INFO 12），与既有 17 门固定样本合并 52 门；真实课程审计 CLI **exit 2**，52 份年度文档重新按当前契约校验、35 份原 literal 精确匹配、campus 仍 null。
- 唯一 unparsed 为 CS 4992 prerequisite 的旧式外部代码 `CIS 310M`，`reason=unsupported_syntax`，完整原文保留、rule=null；没有丢分支、替换旧代码或将部分报告计作全部语法通过。首次临时复核脚本误访问 `failure_reason`，按实际 `reason` 字段纠正后完成检查，没有为脚本错误改 schema。
- 7 份当前方案的政策 reader 全部 ready；纯函数明确匹配核对 CS 5004／DS 5110／DS 7995 的分别范围。DS 4996、INFO 6105／7405／7225 无有限明确匹配，仍未知，不用开放前缀／编号区间推断归属。不是 DB 导入、个人项目确认或毕业规则求和。
- 整体复核 **62 个原输入文件** hash 前后不变，没有新 GET、数据库连接或输入写入。新增显式冻结课程选择清单，避免未来重新枚举改了验收样本；已有完整来源为项目 5 页＋院系 3 页＋政策 18 页，共 26 份 HTML／26 份 sidecar，仍不随 Git／Docker 发布。
- 新增 [第五批验收与缺口清单](fifth-batch-acceptance.md)：层级结果、退出码／coverage 的含义、可重演命令、生产恢复／副本与联合发布门槛、人工 OAuth／个人 POS、DS Align／跨组／section／旧代码未知，以及下一段 06A 完整方案分享范围、06B 反馈关联。

### 修改文件与验证

| 文件 | 修改 |
|---|---|
| `docs/fifth-batch-acceptance.md`（新增） | 有限阶段验收快照、可重演入口、发布／个人语义缺口及实施顺序；不是另一份变更日志 |
| `data/course_requisite_sources/acceptance_2026_2027_course_codes.json`（新增） | 冻结 52 门验收课程，显式传给现有 CLI，不是运行库导入名单 |
| `docs/program-plans.md`、`docs/program-policy-evidence.md`、`docs/course-requisites.md`、本文件 | 指向统一阶段验收，区分功能收束与完整政策／个人资格／生产发布，后续切到第六批 |

- 本批不改功能代码、schema、API 或原证据输入，使用本轮 05D-4 完整实现快照：**1813 passed、5 warnings、0 errors／failures／skips**，持久 JUnit 已核对。没有把文档更新算作新增测试，也没有声称再次跑了一套新测试。
- 新增冻结清单后实际重演课程 CLI，仍为 **exit 2／52 门／1 个 unparsed**；连同选择清单共 **63 输入文件** hash 未变。最终 tracked diff 与全部 **83 个未跟踪文件**空白检查通过；无暂存。Ruff 没有安装／运行，不宣称 lint-clean。

### 发布状态与下一段

- 未提交、未推送、未部署、未迁移／导入生产运行库；HEAD `bb2f6e3`，此前全部本地修改保留。05E 只有固定输入只读核对和文档／验收选择清单添加，无账号、模型、消息、查询日志或索引写入。
- 第五批的**本地有限证据功能阶段**收束，不把 7 份方案或学校政策标 complete；已经列明的个人／来源／批准／实际班次缺口继续保留。
- 下一入口 **06A**：本地实现选定完整方案的分享范围与安全解析，兼容已有 course／program 家族链接；缺失、冲突、旧版本明确提示，不按前缀第一份或最新年度猜测。随后 06B 反馈关联；真实恢复／数据库副本／生产发布及个人账号测试需单独确认，分发消息不自动发送。

## 06A — 精确方案范围与内容版本分享（2026-10-02）

### 范围与原因

- 05E 收束后切到第六批：旧 `?program=` 只定位家族，不能表达已选校区／Catalog 年度／路径／方向，也不能区分同 ID 的内容修订。本批同时补分享生产与消费两侧，不只产生接收方无法精确还原的 URL。
- 公共链接定位方案内容，不决定学生适用年度、入学学期、获批路径或个人资格。七份原文档仍 partial；不增加新 seed、政策片段、课程归属或学期推测。

### 已实现

- v1 完整链接含八个唯一必填参数：格式版、家族、方案 ID、校区、Catalog 年度、pathway、concentration、当前内容 SHA-256。空 concentration 使用非空字面量 `null`；具名方向使用 JSON 字符串，名为 `null`／`none` 的方向与 Python None 分开。大小写、空白、缺失、重复、错版、超预算和 plan＋course 冲突不猜测或归一化。
- 先清旧选择，绕过并移除**目标家族**的 session curriculum 缓存，使用既有 GET 获取当前文档；其他家族缓存保留。校验完整响应、确切 ID／scope／hash／对照状态，不按前缀第一项、同 scope 其他 ID、最新年度或旧 seed 回退。
- pending 目标在 selectbox 创建前按实际文档再次校验；重复 ID／scope、另一家族、坏文档、变更 revision 或 stale 目标不显示旧规则／政策。固定失败提示不回显 URL 任意内容或 API detail。
- 仅对当前公共参数 token 防重复消费，不保存任意 URL／OAuth state／token。同链接 rerun／清空／刷新不选回；同会话换完整链接可重新定位。408／429／5xx 不烧掉目标，下一 rerun 可重试；404、坏 JSON 等 terminal 结果只处理一次。
- 当前明确选定且 source_checked 才生成完整分享；未选／draft 明确退为家族入口。legacy course／program ID／无歧义前缀链接保持兼容，不改 URL 同步或 callback 逻辑。

### 修改文件

| 文件 | 修改 |
|---|---|
| `app/program_plan_links.py`（新增） | 严格公共 URL 模型、nullable concentration、精确当前文档解析、公共 token 与前置 widget 选择消费 |
| `app/deep_links.py` | 兼容旧生产／消费入口；完整链接先校验再 fresh GET、目标缓存隔离、临时恢复与失败关闭 |
| `app/program_plan_view.py`、`app/program_view.py` | widget 创建前重验、排除外家族、当前选择完整分享与未选／draft 家族说明、返回／刷新清 pending |
| `app/streamlit_app.py` | 更正 callback 清 URL 的注释：只在处理 OAuth 返回时；无 OAuth 功能变更 |
| `tests/test_program_plan_links.py`（新增） | 85 项参数／七 scope／缓存／API／pending／隐私／入口顺序回归，含 6 个实际 Streamlit AppTest 无头组件流程 |
| `docs/program-plan-sharing.md`（新增）、`docs/adr/0029-deep-links.md` | v1 契约与安全边界；ADR 保留历史 991 测试／现场结果，另加本地扩展并纠正 OAuth 描述 |
| `docs/program-plans.md`、`docs/program-policy-evidence.md`、`docs/fifth-batch-acceptance.md`、本文件 | 更新当前分享入口；05E 的 1813 结果明确为历史快照，修改记录仍只有本文件 |

### 验证记录

- 新模块未实现时 **54 failed in 15.52s**（缺模块／新生产参数），为 RED 基线，不是通过。首轮 **2 failed／98 passed** 暴露暂时 API 失败仍残留旧目标 widget，清理目标 key 后修正。
- 实际 AppTest 后的 **2 failed／181 passed** 暴露 query reader 在 rerun 丢弃空 concentration，导致完整链接失效；查本地 Streamlit 安装源码确认 parse_qs 行为后改为显式 nullable JSON，而不是放宽缺字段。后一轮 **1 failed／185 passed** 为 AppTest 列表值与字符串预期的断言格式，纠正后通过。
- 最终专项 **198 passed, 3 warnings in 25.10s**，JUnit `data/raw/program-plan-link-focused-06a.xml` 已独立核对 tests=198、errors=0、failures=0、skipped=0；本批 **85 项**全部执行。包含生产链接→当前 FastAPI GET→UI 选择的隔离回路，临时 DB `total_changes` 无变化；没有实际调用 search／chat／模型。
- 最终全套：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/program-plan-link-tests-06a.xml` → **1898 passed, 5 warnings in 137.26s**。JUnit 独立复核 tests=1898、errors=0、failures=0、skipped=0，本批 **85 项**全部执行；1813 → 1898 为本地实现测试增长，不是线上版本变更。五个警告仍为既有 SWIG 类型与 HTTP 422 常量弃用。
- 本批 6 个 Python 文件内存语法解析通过；tracked diff 和全部 **86 个未跟踪文件**空白检查通过，无暂存。检查时共 33 个 tracked 修改、86 个 individual 未跟踪文件，包含此前全部本地成果；新增 tracked 修改为 deep links 与 ADR 扩展，不将旧批文件误计为本批新增。
- 当前宿主无 Ruff、WSL 虚拟环境也无 Ruff，本批未安装／运行，不宣称 lint-clean。两份 JUnit 在 Git 忽略的 `data/raw/` 下，只作本地验证产物；没有将其当成生产／外部浏览器验收。

### 发布状态与下一段

- **未提交、未推送、未部署、未迁移／导入真实运行库**；HEAD 仍为 `bb2f6e3`，此前全部 dirty 修改保留。只在隔离测试库执行 fixture；未改生产 query_log、个人课程、索引、运行 `.env`／compose，也未抓官方网页或调用 Gemini。
- 没改 API 路由／持久 schema、v1.5／v1.6、原七份方案／来源输入或内容 hash 算法。分享 ready 不代表政策输入齐备、来源完整或个人条件满足；发布仍需私有输入恢复、副本演练与 API/UI 联合验收。
- 测试为临时 FastAPI／HTTP fixture 与 Streamlit AppTest，不宣称真实浏览器或真实 Google OAuth 全链路。跨完整 OAuth 返回保留分享目的地未实现；需要个人账号的登录／刷新核验仍未执行。
- 下一入口 **06B**：👍／👎 反馈绑定实际回答／查询，区分真实用户与合成测试，不制造 organic 样本。真实生产发布、账号验证和分发消息仍需单独确认。

## 06B — 完成回答／原查询绑定的 👍／👎（2026-10-02）

### 范围与原因

- 接着 06A 推进反馈关联。旧 `/chat` 已写 query_log，但没有返回准确记录身份、保存完成回答或提供反馈端点／按钮；凭邻近消息、最新 log 行或客户端行号无法可靠定位真实回答。
- 采用 ADR-0028 的原查询关联目标，但不把可猜的 log_id 放 meta 当投票权限：meta 在回答完成前出现。本批在完整生成且存储成功后的 done 下发随机 receipt，绑定确切回答／原查询；👍／👎 是主观有用性，不是课程正确性、个人资格或 eval 标准答案。

### 已实现

- `QueryLogRepository.add` 返回精确 lastrowid；`log_query` 只在 commit 成功后返回 ID，失败 None，原 search／chat 行数和 eval 标记语义保留。
- 正常非空且 ≤64000 字符的完成回答才可捕获；私有存文本／hash、原查询外键、prompt version、有界请求筛选／项目／上下文 ID 与历史轮数，不另存完整历史或账号。原查询／新 schema／捕获失败、空／超长或上游异常没有 receipt，不打断原回答；缓冲不积累空 token。保存成功后才在 no-store done 发布 receipt，不出现在 meta。
- 新 `POST /feedback` 仅接受确切 ID／回答 hash／随机凭证及 up/down；原 token 不入 DB、仅 hash，7 天可用，串用／过期／坏目标固定 404，格式 422，schema／存储故障 503。保存原文 hash 也重验，坏字段类型不成为 500 或成功评价。
- 每回答一条当前评价；相同重试不改行／时间，另一选项更新，不制造额外查询。来源通过原 query_log 外键关联，后续没有评测 header 不会把 eval 改 organic；NULL 只是未带评测标记，不证明真人。
- 流消费、加入历史、显示按钮分别核对实际回答文本；中断／错误／旧 done／坏 receipt 不复用上一轮。只对 assistant 显式点击提交，rerun 不写，错响应／失败不标成功；清对话／登出清消息与临时 receipt/meta/error。匿名可评价，但凭证不是独立用户计数／身份认证。
- 独立 v1.7 加两张私有表，原 schema／课程／方案／来源／索引不变；请求不自动加表。显式迁移已有数据库，默认 mode=ro，仅 --commit 一事务加表／版本；检查旧列／主键／唯一查询／级联外键，拒绝不兼容表，失败回滚，不创建拼错路径或替换原库。

### 修改文件

| 文件 | 修改 |
|---|---|
| `schemas/answer_feedback.py`（新增） | strict receipt／请求／响应、回答大小与七天凭证有效期 |
| `db/answer_feedback_repository.py`（新增）、`db/init.sql` | 私有完成回答、准确 query FK、token hash、幂等最新评价、级联与 v1.7 契约 |
| `db/query_log_repository.py`、`api/routes/common.py` | commit 后准确 log ID 或 None，不猜最新行 |
| `api/routes/chat.py`、`api/routes/feedback.py`（新增）、`api/main.py` | 正常完成后 best-effort 捕获／no-store receipt、专用反馈路由与注册、旧 NDJSON 兼容 |
| `app/answer_feedback_view.py`（新增）、`app/api_client.py` | 严格原文绑定、显式点击、成功响应再验、固定失败／重试提示 |
| `app/streamlit_app.py`、`app/state_manager.py` | 收完才能挂 receipt，assistant 历史入口／按钮、清对话／登出清临时私有状态 |
| `scripts/migrate_answer_feedback.py`（新增） | 必须已有数据库，默认只读、显式事务 migration、独立 CLI 导入路径 |
| `tests/test_answer_feedback.py`（新增）、`tests/test_answer_feedback_view.py`（新增）、`tests/test_init_sql.py` | 52＋29=81 项新反馈回归，含 3 个实际 AppTest、隔离完整 API/UI 回路、真实 dependency 连接生命周期和临时 CLI／迁移验证 |
| `tests/test_course_qualification_evidence.py` | 将硬编码“不存在 1.7”改为仅允许新增 1.6、其他版本／schema 结构不变；拆成已有／没有反馈 schema 两个场景，新增 1 个集成 case，不放宽旧同步边界 |
| `docs/answer-feedback.md`（新增）、`docs/adr/0028-optimization-extension-review.md`、`docs/pii_redaction.md`、本文件 | 功能／权限／来源／隐私契约；说明不直接暴露 log_id 的原因，原 ADR 线上数字保持历史快照 |

### 验证记录

- 实现前首轮 **15 failed, 3 warnings in 16.12s**：14 个反馈缺失／表不存在回归，以及 1 个 fixture 未 seed 项目导致 404；补测试家族后验证真实功能，不为 fixture 改生产项目选择逻辑。第一份组合回归 **58 passed, 4 warnings in 5.08s**。
- 完整 UI／迁移回归首轮 **174 passed, 4 warnings in 25.75s**；补旧表约束、坏存储类型、no-store 完成事件和隔离完整 API/UI 回路后，最终专项 **183 passed, 4 warnings in 26.61s**。JUnit `data/raw/answer-feedback-focused-06b.xml` 独立复核 tests=183、errors=0、failures=0、skipped=0，新增 **52 服务端＋29 UI=81 项**全部执行。
- 临时库实际检查原 query→完成文本→凭证→UI 历史→显式 click→真实反馈路由→存储；eval:ui-roundtrip-06b 保留且查询只一条。独立文件 DB／yield dependency 验证 stream 后保存未被提前关闭连接，反馈在下一请求仍能关联。
- 实际 migration CLI 在无 PYTHONPATH／非项目 cwd 的临时库默认只读成功；dry-run 文件 hash 不变，commit 幂等、注入 SQL 失败事务回滚、原查询保留、缺路径不创建。列／主键／唯一查询／外键不兼容 dry-run 失败且文件 hash 不变。没有使用真实数据或运行库执行迁移命令。
- 第一轮全套 **1 failed, 1978 passed, 5 warnings in 142.78s**：原课程资格测试将“不存在 1.7”硬编码为只新增 1.6 的证明；新反馈 init schema 已有 1.7，导致与合法新版本冲突。改为前后版本精确比较（仅允许原 1.6 迁移）及其余 schema 结构逐行不变，分别在已有／没有反馈表的临时库验证；课程资格模块 **31 passed in 1.65s**，保留旧原文／课程行／只读／幂等检查，不为通过改生产同步实现。
- 最终全套：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/answer-feedback-tests-final-06b.xml` → **1980 passed, 5 warnings in 142.76s**。JUnit 独立复核 tests=1980、errors=0、failures=0、skipped=0；反馈 52＋29=81 项及两种同步 schema 状态全部执行，新增集成 case 1 项，合计 **82 cases**（1898 → 1980）。五个警告仍为既有 SWIG 类型与 HTTP 422 常量弃用。首轮失败报告与最终报告保留为不同文件，没有将失败结果覆盖或称为通过。
- 本批涉及 **16 个 Python 文件**内存语法解析通过；tracked diff 与全部 **94 个 individual 未跟踪文件**空白检查通过、无暂存。最终共 **37 个 tracked 修改／94 个未跟踪文件**，前批成果保留。当前宿主和 WSL 虚拟环境都无 Ruff，本批未安装／运行，不宣称 lint-clean。新增／更新文档相对文件链接全部存在。

### 发布状态与下一段

- **未提交、未推送、未部署、未迁移／导入真实运行库**；HEAD `bb2f6e3`，全部前批 dirty 产物保留。本轮只有代码／文档与临时 fixture／DB／MockTransport／AppTest，无新外网、真实 Gemini／Google OAuth、生产 query_log／课程／索引或分发消息写入。
- 新功能会私有保存没有点击反馈的完整回答及有界请求上下文，也可能有 PII；七天只使 token 过期，**不是自动数据清理**。本批没有自由文本评论、自动脱敏／purge、公开导出或个人删除接口。访问控制、前端告知、最小留存、备份／导出处理需生产启用前确认，不能因为只收 👍／👎 就宣称无隐私风险。
- 原检索／拒答算法、prompt version、模型配置与课程／方案 seed 不变；没有新质量评测或性能测量，不引用 ADR 旧检索数字作本次验证。来源字段不证明真人，反馈不直接作为 v0.5 ground truth；真实反馈数量没有检查。
- 下一入口 **06B-2**：离线反馈候选导出与样本审查，默认只读／排除凭证／保留来源，标明上下文与隐私限制；然后安排联合发布清单与需本人参与的登录全链路。生产迁移、真实账号和分发仍须单独确认。

## 06B-2 — 只读反馈候选导出／样本审查入口（2026-10-03）

### 范围与原因

- 接续 06B：完成回答与最新评价已能关联原查询，但原 `export_query_log.py` 会创建 DB／输出目录并覆盖原文文件，不适合直接复用为私有回答反馈入口。本批保留旧脚本行为，新增独立只读工具，不改生产 DB／API／UI／prompt 或反馈有效期。
- 仅输出待人工审查的候选，不把 👍／👎 当标准答案、down 当拒答标签或返回课程 ID 当 expected IDs。真实流量、真实原文审查和 v0.5 质量评测没有发生。

### 已实现

- 强制已有路径，SQLite URI mode=ro＋query_only，在单一读事务检查现有原查询整数主键与反馈关联 schema；不建库／迁移／commit／DML。默认 stdout 只有有限候选统计，不输出原文／行 ID／来源 marker／路径。
- 显式 --out 才写新 JSONL，仍默认元数据。私有 query／answer／白名单 request_context 要同时传 --include-private-text 与 --ack-private-data；不含完整历史、token／token hash、OAuth／session 或 raw user_id。异常 CLI 参数与数据错误固定提示，不泄漏值／Pydantic 输入。
- 原查询区分 unmarked／eval／unknown，默认 unmarked **不是验证过真人**；完整非空 eval marker 仅给组 hash，后续无 header 的评价不改变来源。按评价 updated_at 的 UTC 日期闭开窗口，稳定排序、1–1000 limit、has_more 明示截断；不声称全量／独立用户数量。
- strict 候选包含原 ID、内容／上下文 hash、来源 revision、prompt version、当前评价、时间和课程线索。重新检查回答原文 hash、真正 chat 关联、来源字段类型、JSON 重复键／白名单／大小、时间顺序；被选坏行令整次失败，不跳过。原文和元数据的 source_revision 一致，相关来源变化会改变指纹，指纹不是认证签名。
- 固定 review_state=pending／ground_truth=false；缺任意上下文键标 missing，缺计数为 null 而不是 0。历史 >0／未知、没有检索快照、未验证来源、隐私／主观标签等缺口保留。私有文本移植或删掉审核缺口不能通过候选模型。
- 所有候选先验证与 32 MiB 预算检查，才写同目录私有临时文件，fsync 后用不覆盖 hard link 发布；已有文件／symlink／hardlink／缺父目录／非 JSONL 拒绝，竞争创建不会覆盖，失败不暴露半写最终文件。正常清理 staging，发布后清理失败如实报告；POSIX 设置 0600，Windows／共享盘 ACL 仍需核实。
- 仓库内只允许 Git／Docker 已忽略的 data/raw/feedback_review；外部明确路径的权限、留存、备份与异常残留由操作者负责。元数据可关联，不能公开或宣称匿名化；七天是投票凭证 TTL，不是导出／源数据留存期。
- 提供隐私→来源／上下文→主观与事实分离→同源／重复隔离→独立审批的审查顺序和空白记录框架；没有审批写回、自动脱敏／清理、自动 ground truth 或新的评测读取路径。

### 修改文件

| 文件 | 修改 |
|---|---|
| `schemas/feedback_candidate.py`（新增） | strict 待审查候选、上下文白名单、缺口／时间／私有文本 hash 一致性，不接受自动真值或凭证字段 |
| `scripts/export_answer_feedback.py`（新增） | 只读快照、来源／日期／预算、默认统计／元数据、成对原文开关、固定错误、新文件原子不覆盖发布 |
| `tests/test_feedback_candidate_export.py`（新增） | 临时合成 DB、原文／凭证 canary、来源／坏关联／坏类型、revision、预算、权限、fsync／竞争／清理失败、实际 CLI 与隔离 API→反馈→导出 |
| `docs/feedback-review-export.md`（新增） | 使用契约、私有输出边界、不可重放缺口和人工样本审查框架，不另起变更日志 |
| `docs/answer-feedback.md`、`docs/pii_redaction.md`、本文件 | 当前入口与留存／元数据风险、统一变更历史；旧批次测试数字保持历史记录 |

### 验证记录

- RED 基线 **53 failed in 15.19s**，缺新导出模块／实际 CLI；JUnit `data/raw/feedback-export-red-06b2.xml` 独立核对 tests=53、failures=53、errors=0、skipped=0，不记为通过。
- 首轮功能组合 **134 passed, 3 warnings in 27.49s**；JUnit `data/raw/feedback-export-focused-first-06b2.xml` 核对 53 个新 case 全部执行。扩展安全边界后 **1 failed／192 passed in 29.05s**，是 trace 测试包装器参数名 uri 与 SQLite uri=True 冲突；更名后 **1 failed／192 passed in 31.50s**，隔离诊断确认 SQLite 索引虚表 trace 另发 `-- PRAGMA index_info=...`。只规范化该注释前缀后仍限制 SELECT／PRAGMA／BEGIN，保留 mode=ro／query_only／文件 hash／无凭证 SELECT 检查，不放宽生产写入权限。
- 加来源二进制坏类型回归后的 **195 passed, 3 warnings in 29.84s**（`data/raw/feedback-export-focused-verified-06b2.xml`）；最后补原 query_log 必须真实整数主键的回归，最终专项 **196 passed, 3 warnings in 30.24s**，JUnit `data/raw/feedback-export-focused-final-verified-06b2.xml` 独立复核 tests=196、errors=0、failures=0、skipped=0，新增 **86 项**全部执行。首轮失败报告保持不同文件，没有覆盖后冒充通过。
- 最终全套：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/feedback-export-tests-06b2.xml` → **2066 passed, 5 warnings in 155.96s**。JUnit 独立复核 tests=2066、errors=0、failures=0、skipped=0，新增 86 项全部执行（1980 → 2066）。五个警告仍为既有 SWIG 类型与 HTTP 422 常量弃用；专项与全套为独立进程／临时 fixture，可并行运行，耗时不是生产性能测量。报告都在 Git 忽略的 data/raw 下，不当作线上验收。
- 实际 CLI 从非项目 cwd、移除 PYTHONPATH 的合成临时库分别导出元数据／双开关私有中文原文，核对 stdout 无 ID／凭证、原文 UTF-8、两模式 revision 一致、POSIX 0600 与 DB 文件 hash 不变。人工审查框架为空白模板，未处理真实样本；所有临时路径／canary 仅用于验证。
- 最终 3 个新增 Python 文件内存 AST 解析、4 份相关文档相对文件链接、tracked diff 与全部 98 个 individual 未跟踪文件空白检查通过；37 个 tracked 修改／98 个未跟踪文件，前批成果保留，无暂存。未安装／运行 Ruff，不宣称 lint-clean。

### 发布状态与下一段

- **未提交、未推送、未部署、未迁移／导入真实运行库、未导出／审查真实原文**；HEAD 仍为 `bb2f6e3`。没有调用外网／Gemini／Google OAuth，没有生产 query_log／课程／索引或分发消息写入；所有 DB、HTTP、原文 canary 均为隔离测试 fixture。
- 工具／框架可用不代表已有有价值的真人反馈，NULL 不证明真人、has_more 不证明全量覆盖、hash 不证明匿名化、pending 不等于已审核。不能据此解锁真实分布评测、门控重校准或宣称 v0.5 改善。
- 下一入口 **06C**：整理联合 API/UI 发布与留存／副本演练／回滚验收准备，列清需本人参与的真实登录／刷新、生产启用和小范围分发；缺新权限／人工确认的外部动作不执行。

## 06C-1 — 默认关闭／明确保存许可与联合发布验收准备（2026-10-03）

### 范围与原因

- 原 06B 在表可用、完整回答捕获成功时就保存，即使未点击反馈；只有文档提醒留存，没有独立运营关闭或前端保存选择。发布准备先补实际门控／告知，不只写“上线前确认”。默认行为改为**不新增完整回答保存**；原 query_log 仍记录，不假装所有原文日志都关闭。
- 本批只做本地实现、隔离演练与待执行清单，不决定真实保存期限，不自动 purge／备份恢复／迁移／发布，也不代用户登录 Google 或发分发消息。

### 安全事件与处置

- 首轮 RED 的缺字段 monkeypatch 异常展开 Settings repr，**包含配置敏感值**。已告知用户工具历史无法撤回，应由持有人轮换可能出现的 API key、OAuth secret、session 签名密钥；不在记录里重复任何值。未自动撤销／更换真实凭证或重启服务。
- `config/settings.py` 对密钥及 client ID 字段加 repr=False，对 Settings 校验字符串加 hide_input_in_errors；新增 canary 检查 repr／str／校验字符串，但显式 model_dump／errors() 仍有私有值，不宣称通用脱敏。
- 本次忽略目录 `data/raw/feedback-release-red-06c1.xml` 定点清除 failure／error 的异常消息和全文、system-out／err 文本，保留八个 case 与失败计数；不是抹去失败或声称历史输出安全。测试 gate helper 缺字段时改为固定错误，不再让 monkeypatch 把配置对象拼入异常。没有清理其他文件或读取／修改运行密钥内容来做轮换。

### 已实现

- `ANSWER_FEEDBACK_ENABLED` 默认 false，示例环境也 false；Settings 由 API/UI 启动各自加载，真实环境变更需成套重启。v1.7 schema 本身不启用保存。后端独立开关阻断捕获和既有 receipt 的评价；关闭 503/no-store，不删除／修改已保存记录。
- `/chat` 增加 `allow_feedback_capture`，只接受 JSON bool，省略／false 不新增完整回答。API 需运营 true＋请求 true＋原完整捕获条件；开始决定是否收集，结束前再核对开关。正常 token／原查询日志／eval 标记保留，字段不进 prompt／既有 request_context 白名单，没有新同意账本或身份／法律同意认证。
- UI 在输入前告知原查询日志仍记录；本地运营启用后才显示默认未勾选的会话保存选择，并解释不投票也保存、七天非删除、取消／清对话／登出不删服务器数据。普通输入、sample／pending／追问用同一生成路径，每个请求显式 bool。
- 清对话／登出清勾选许可和 receipt；运营关闭清 UI 旧选择、不提供投票按钮，重新启用不恢复旧勾选。流消费也要求本请求许可与当前本地开关，否则忽略意外 receipt，原回答文本仍显示。
- 原 UI→新 API 默认不捕获；新 UI→不支持新字段的旧 API 预期拒绝，不能删除许可字段自动重试掩盖差异。需要 API/UI 联合发布／回退，配置关闭不是 DB 删除或全会话 token 撤销。
- 测试发现统一 HTTP 错误处理丢弃异常 headers，导致 disabled 503 的 no-store 消失；修复为保留 headers，新增 Cache-Control／Retry-After、WWW-Authenticate、Allow 三类协议回归，结构化 JSON／原状态码保留。
- 新建联合发布清单，明确 ref／镜像、私有输入恢复、一致副本、分层迁移、留存／访问控制、关闭与启用验收、真实浏览器登录／刷新、回退及分发权限。`deploy.ps1 -DryRun` 仍有 SSH 预检查，不当作零网络本地检查；health 不证明反馈／数据／OAuth，通过 AppTest 不证明真实账号。

### 修改文件

| 文件 | 修改 |
|---|---|
| `config/settings.py`、`.env.example` | 默认关闭运营开关；敏感字段 repr 与校验字符串保护，不改实际 .env |
| `api/models.py`、`api/routes/chat.py`、`api/routes/feedback.py` | strict 请求许可、双门控／完成再验、关闭评价固定 503/no-store |
| `api/exceptions.py` | 结构化错误响应保留原异常 headers，不丢缓存／认证／方法／重试语义 |
| `app/answer_feedback_view.py`、`app/streamlit_app.py`、`app/state_manager.py` | 输入前告知、默认未选会话许可、显式请求字段、意外 receipt 防护、关闭／清对话／登出重置 |
| `tests/test_feedback_release_gate.py`（新增） | 47 项门控／坏 bool／旧库／关闭保留／流切换／配置 canary／控件重置／协议 headers；含三个许可控件 AppTest 场景和两个实际主 render→隔离 API 场景 |
| `tests/test_answer_feedback.py`、`tests/test_answer_feedback_view.py`、`tests/test_feedback_candidate_export.py` | 原反馈 52／UI 29／导出 86 case 改为各自显式启用／许可 fixture，不在全套全局放开；原 hash／失败／来源／幂等／私有边界保留 |
| `docs/joint-release-acceptance.md`（新增）、`docs/answer-feedback.md`、`docs/feedback-review-export.md`、`docs/pii_redaction.md`、本文件 | 当前契约、待执行发布／留存／账号清单、凭证事件与私有边界；不另起变更日志 |

### 验证记录

- RED **8 failed, 3 warnings in 14.98s**，缺运营／请求字段；报告 errors=0／failures=8／skipped=0，错误细节因上述安全问题定点清理，失败事实保留。不是通过结果。
- 首轮组合 **186 passed, 3 warnings in 33.55s**（`data/raw/feedback-release-focused-first-06c1.xml`），包含八个初始门控 case 与原三家族反馈／导出、旧 stream 逻辑。
- 扩展后 **1 failed, 238 passed, 3 warnings in 36.27s**（`data/raw/feedback-release-focused-06c1.xml`）：暴露统一 exception handler 丢 headers，不是放宽 no-store 断言。改生产 handler 传原 headers，并加三类专门回归。
- 最终专项 **259 passed, 3 warnings in 39.11s**（`data/raw/feedback-release-focused-verified-06c1.xml`），JUnit 独立核对 tests=259、errors=0、failures=0、skipped=0；新增 **47 项**、原反馈 52／UI 29／导出 86、stream 11、cookie 17、auth UI 2、结构化错误 15 全部执行。两个完整主 UI 场景分别默认未选／主动选择，确认生产 body 显式 false／true→临时 FastAPI 保存数 0／1、eval 来源不变、rerun 不追加查询；OAuth／cookie 在该场景中明确替身，不混作真实登录。
- 最终全套：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/feedback-release-tests-06c1.xml` → **2113 passed, 5 warnings in 146.45s**。JUnit 独立复核 tests=2113、errors=0、failures=0、skipped=0，新增 47 项全部执行（2066 → 2113）。五个警告仍为既有 SWIG 类型与 HTTP 422 常量弃用；不是生产质量／性能／登录验收。失败与最终报告不同文件，均在 Git 忽略的 data/raw 下；RED 报告仅安全清理细节，计数未改。
- 最终 12 个涉及 Python 文件内存 AST、5 份相关文档相对链接、tracked diff 与全部 100 个 individual 未跟踪文件空白检查通过；38 个 tracked 修改／100 个未跟踪文件，无暂存，所有前批成果保留。未运行／安装 Ruff，不宣称 lint-clean。

### 发布状态与下一段

- **未提交、未推送、未部署、未迁移／导入真实运行库、未登录真实账号、未修改运行 .env 或轮换真实密钥**；HEAD 仍为 `bb2f6e3`。无新增外网／Gemini／Google OAuth 调用或生产数据／分发写入；测试导入会加载本地配置，安全事件的展示风险不能被“仅本地测试”抵消。
- DB/schema／源输入／课程／方案／检索和 prompt version 未改；导出仍严格待审查，关闭在线反馈不删除或禁止显式受控离线读取。旧记录不能反推保存许可，七天不是留存政策，账号／token／真实分布仍未知。
- 下一入口 **06C-2**：只读发布预检器，对明确的已有副本与固定输入列出可验证事实及人工门槛，不凭脚本 pass 自动部署、启用保存或证明真实登录；凭证风险处置、真实留存与账号核验需本人参与。

## 06C-2 — 显式离线副本与固定来源的只读发布预检器（2026-10-03）

### 范围与原因

- 将联合发布清单里能做的机器核对落成独立 CLI；不把版本行、旧 healthy／域名 200、临时 fixture pass 或候选归档一致性当作生产审批。
- 只用已有本地稳定离线副本及显式选定的方案／政策文件，不发现运行库、不读 `.env`／导入 Settings、不联网或调用 deploy，不自动迁移／导入／恢复／清理或批准启用反馈。缺真实副本不妨碍本地实现与合成测试，也不假装真实副本已验收。

### 已实现

- 新 `scripts/release_preflight.py` 与 CLI。缺失／空／超预算／链接／`.env*`／UNC 或 device 输入拒绝；UNC 在文件探测前拒绝。已有 DB 带 WAL／SHM／journal 时不打开，不删除旁文件去制造成功。明确要求一致且不再变化的本地副本，不直接碰活跃库。
- 副本 URI 使用 `mode=ro&immutable=1`，query_only／trusted_schema=OFF／BEGIN；quick_check、schema 定义、必需版本行和 FK 检查共享 SQLite 时间／VM 步预算。当前 init.sql 只在 `:memory:` 参考库执行，不在受检副本执行 DDL／DML。
- 核对所需 table／index／view／trigger 定义，CHECK／DEFAULT／FK／唯一约束纳入比较，版本 v1.0–v1.7 行不能掩盖缺表或约束漂移。未加引号的大小写／空白／注释与 IF NOT EXISTS 可归一，引号内字面量保留；不是通用 SQL 等价证明，差异不自动修复。
- 额外 schema 对象只报数量、仍未审查。自检改内部名前缀过滤为 GLOB，使下划线按字面量处理；相近的 `sqlitex` 普通对象不会被 LIKE 的单字符通配符漏计，也不把额外对象判为安全。
- 固定方案组重用既有纯离线页面身份／指纹／候选表核对，只支持已开发 Boston／2026–2027 范围与既有路径；其他校区／年度／适配器失败，不借 Boston 页面验证 Seattle 或下一年。按数量、文件大小、scope／ID 去重；保留 partial 数量，不改文档 coverage、seed 或规则。
- 政策组需同次方案来源通过，再核片段位置／hash、精确方案内容 hash／范围／所属学院；额外补选定方案必须全部有 link，防止“已存在的 links 都正确”被误写为所选方案全覆盖。仍 selected_fragments_only，不合并政策或算资格。
- JSON 重复 key、NaN／Infinity、缺文件、大小超限、链接归档、篡改 hash／候选学分／scope 等固定失败；受检文件私有 hash 前后核对，末尾再验旁文件，发现变化不重试成 pass。不输出这些 hash／路径，不声称能捕获所有瞬时修改或证明跨文件原子一致性。
- JSON stdout 只留状态／固定 code／有限计数／布尔与限制；不输出用户行、账号、SQL、异常内容、来源段落／URL、方案 ID、凭证或 token。参数错误也不回显未知参数值／traceback；没有导出文件或批准参数。
- `release_approved` 永远 false，九类人工门槛一律 pending；退出 0 仅表示本次**请求的机器检查**通过，没传来源仍 not_checked，不能自动部署／启用保存。课程先修来源、DB 内容是否已导入、索引／模型、实际配置／账号／备份恢复／留存／分发不由此证明。

### 修改文件

| 文件 | 修改 |
|---|---|
| `scripts/release_preflight.py`（新增） | 独立只读 CLI、稳定离线副本／schema／版本／FK／固定来源核对、预算与固定安全报告、始终不审批 |
| `tests/test_release_preflight.py`（新增） | 67 项合成副本／独立来源／拒绝场景、实际 CLI／进程隔离／只读 trace 和隐私回归 |
| `docs/release-preflight.md`（新增） | 输入组、调用示例、检查范围／不能证明事项、预算、退出码／人工门槛与私有报告说明；不是另起修改日志 |
| `docs/joint-release-acceptance.md`、本文件 | 联合清单接机器预检，更新当前进度与后续隔离演练入口；所有修改继续统一在本文件记录 |

### 验证记录

- RED **8 failed in 0.93s**（`data/raw/release-preflight-red-06c2.xml`）：实现不存在时固定失败，errors=0／failures=8／skipped=0，没有展开配置或敏感对象。本批 RED 不包含真实凭证，不清除失败细节或计数。
- 初始 **8 passed in 0.72s**；扩展 **62 passed in 5.44s**；校区／年度边界 **64 passed in 5.01s**；UNC 前置拒绝 **66 passed in 5.04s**；最终专项 **67 passed in 5.27s**（`data/raw/release-preflight-focused-complete-06c2.xml`）。最终 JUnit 独立核对 tests=67、errors=0、failures=0、skipped=0，67 项全部执行，不以 skipped 冒充。
- 包含一个新解释器实际 CLI→全组预检场景：导入拦截器拒绝 config／api／app／dotenv，审计 hook 拒绝 `.env`、socket connect／DNS、外部进程／system 与全部磁盘写打开，`-B` 不生成 bytecode；临时副本与独立合成方案／政策归档逐文件字节不变，机器项全 pass、人工项仍 pending。另用 SQLite trace 核对目标仅 PRAGMA／BEGIN／SELECT，唯一 DDL 在内存参考库。
- 四种实际 CLI 的异 cwd 场景核对 0／1／2 退出码、JSON、空 stderr 与未知参数／私有 canary 不回显；坏库、伪版本、缺索引／view／trigger、CHECK／类型漂移、孤儿 FK、额外对象、输入变化、组不完整和所有选定方案缺 link 均未修库／写来源。
- 另一次现有固定输入联合核对（`-B`、临时空 schema 库）：两个明确的方案文件与既有 `program_catalog`／`program_policy_catalog`、政策 bundle 只读核对，八个机器项通过，所需 schema 对象 **47**、版本行 **8**、方案 **7（partial=7）**、政策页 **18**、精确 links **7**，前后私有指纹一致／末尾无 DB 旁文件。JSON 只有固定状态与计数，没有来源原文／URL／hash／身份；所有人工门槛仍 pending、release_approved=false。临时空库由测试准备／清理，无来源导入或真实用户行，不是开发／生产运行库或真实备份验收；未补抓归档。
- 扩展期间全套 **2175 passed, 5 warnings in 148.31s**（`data/raw/release-preflight-tests-06c2.xml`，收集新增 62 项）；下一轮 **2179 passed, 5 warnings in 143.62s**（`data/raw/release-preflight-tests-verified-06c2.xml`，收集新增 66 项）。各次报告不同文件，不用前两轮代替最终结果。
- 最终全套：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/release-preflight-tests-final-06c2.xml` → **2180 passed, 5 warnings in 142.86s**；JUnit 独立核对 tests=2180、errors=0、failures=0、skipped=0，新模块 **67 项**全部执行（2113 → 2180）。警告仍为既有 SWIG 类型与 HTTP 422 常量弃用；不是生产质量／性能／真实登录或留存验收。所有 JUnit 位于忽略的 data/raw，不提交私有运行报告。
- 两个新增 Python 文件内存 AST、三份相关 MD 相对链接、tracked diff 与全部 **103 个 individual 未跟踪文件**空白检查通过；**38 个 tracked 修改／103 个未跟踪文件**，无暂存，HEAD 未变，前批成果保留。未运行／安装 Ruff，不宣称 lint-clean。

### 发布状态与下一段

- **未提交、未推送、未部署、未迁移／导入真实运行库、未真实副本验收或账号登录、未读写运行 .env 或轮换凭证**；HEAD 仍 `bb2f6e3`，原 dirty 成果保留。没有新外网／Gemini／Google OAuth／NAS／生产用户或分发写入；全套 pytest 的既有配置导入不是预检器的零配置／零外部动作验证，不能混淆。
- 06C-1 凭证风险仍需持有人确认处置；本工具 pass 不能代替轮换、撤销、实际留存／权限或备份恢复。七天仍非留存删除，反馈不自动转真值，organic／真实分布未知。
- 下一入口 **06C-3**：继续隔离的分层迁移／来源导入／重复幂等与关闭回归演练，明确合成副本和真实恢复的区别；不自动得到生产副本、部署、真实账号或分发授权。

## 06C-3 — 自有临时副本的分层迁移／来源导入／幂等与关闭回归演练（2026-10-03）

### 范围与原因

- 06C-2 只读预检能核 schema 与选定归档，但不会执行迁移，也不证明来源已入 DB。将现有五个迁移／导入函数串成可重复的隔离演练，核对阶段原子性、原用户数据保护、实际内容与重放，而不是只检查单脚本返回计数。
- 不接触已有运行库、生产副本或真实归档；合成 v1.2 库由当前 init.sql 的 v1.3 标记前部分创建，不是所有历史版本矩阵或真实备份恢复。新 CLI 没有 DB／输入／workspace／commit／keep／out 参数，不能把目标扩大为真实系统。

### 已实现

- 新 `scripts/rehearse_release.py` 在新建自有临时目录内调用已有 Co-op 1.3、catalog_sources 1.4、program_plans 1.5、course_requisites 1.6、feedback 1.7 函数；新 fixture 模块生成两门课程、两份 partial 方案、两份课程条件及原用户／UGC／解锁／选课／查询／旧关系数据。模拟页面虽用模型要求的 official-shaped URL，明确不是官网捕获或真实 POS 核验。
- 固定 **22 个检查**：生成、组合 dry-run、五次提交、**九个故障点**、来源内容解码、底层投票、全层重放、结束预检、源输入／旧状态与自有目录清理。失败停止，剩余 not_checked，机器通过仍 synthetic_only=true／production_backup_restore_verified=false／release_approved=false，人工门槛全部 pending。
- 五层 dry-run 不改变库字节。每层显式提交后核版本行、实际表／记录及全部原 core 表／行／schema 私有逻辑指纹，课程 JSON／富化／检索状态／扩展词、旧关系、用户贡献／Co-op／解锁、选课、原查询 ID／eval 标记不改。没有新审批／公开／奖励、seed 升级、索引或模型写入。
- 五个版本故障在新 SQLite backup 副本上安装版本 INSERT guard，确认 DDL／版本回滚、前面层仍在。三个来源故障实际观察第一条及新版本已在事务中出现，再让第二条失败，核对 DDL／版本／行全部回滚。反馈另确认两表／版本已建立后 schema 自检失败回滚。临时 guard／patch 复原，不落运行库；分层事务不等于整个 release 一次原子回滚。
- 实际 repositories 解码两条目录描述、两份 partial 方案、两份条件；OR／共修与未入课程表的引用保留，一处 instructor-permission unparsed 没变成通过规则、课程 campus 没凭方案补上。返回 stored=2 不单独当成功证据。
- 五层重复执行 stored／would_store=0、missing 空，五个实际 Connection 的 total_changes 总计 **0**，完整逻辑状态／时间字段不变。额外反例 `UPDATE notes=notes` 即使值不变也失败，不把无可见差异当无 DML。
- 合成底层 receipt 同票重试无 DML、纠正只留最新一条，原 eval 查询不追加。该仓库检查不验证运营开关；另有**迁移后临时 DB→实际 FastAPI routes** 的四组合聊天／已有 receipt 关闭投票和重新启用测试，模型／向量／streaming 明确替身，查询全部 synthetic eval。
- CLI 隔离守卫禁止 Settings／config／api／app／dotenv、`.env`、socket／DNS／外部进程／system、自有目录外写打开；SQLite 只能接自有目录或内存。首次严格守卫拦住 stdlib 在 mkdtemp 前的可写探测（owned roots=0，写入被拦），修复为显式本地临时父目录，不放宽守卫；没有 cwd 回退。已有或悬空链接的 backup 目标拒绝，不覆盖。
- 默认结束清理自有随机目录，外部文件字节不变。JSON 只含固定状态／code／计数／布尔，无临时路径／hash／SQL／原文／身份／token／未知参数／异常细节；没有可批准发布参数或真实备份通过证书。

### 修改文件

| 文件 | 修改 |
|---|---|
| `scripts/rehearse_release.py`（新增） | 自有临时目录联合演练、九点故障注入、分层保护／零 DML 重放／内容与预检，固定安全报告 |
| `scripts/release_rehearsal_fixtures.py`（新增） | 明确合成的 v1.2／来源／旧用户及课程状态生成；拒绝非空或链接 workspace，不读真实库／归档 |
| `tests/test_release_rehearsal.py`（新增） | 31 项检查、坏演练反例、目标／探测／越界保护、fresh CLI 守卫、迁移后真实 routes 关闭／许可／重新启用场景 |
| `docs/release-rehearsal.md`（新增）、`docs/joint-release-acceptance.md`、本文件 | 调用、有限证明／分层回滚／CLI 与 HTTP companion 区别、未执行生产项及下一入口；修改仍统一记本文件 |

### 验证记录

- RED **4 failed in 0.75s**（`data/raw/release-rehearsal-red-06c3.xml`）：实现不存在时固定失败，errors=0／failures=4／skipped=0，没有展开配置或真实凭证。
- 首轮 **2 failed, 2 passed in 18.97s**（`data/raw/release-rehearsal-focused-first-06c3.xml`）：五层计数通过后内容校验拒绝目录描述为空，定位为**新合成 fixture 用错 CSS class**，按现有 parser 改为 cb_desc，不放宽描述断言，也不改生产 parser。修正后 **4 passed in 6.56s**（`data/raw/release-rehearsal-focused-second-06c3.xml`）。
- 扩展 **2 failed, 26 passed, 3 warnings in 23.38s**（`data/raw/release-rehearsal-focused-06c3.xml`）：链接 workspace 已正确拒绝但测试漏接 PreflightError；fresh CLI 严格守卫发现 tempfile 默认父目录可写探测，诊断只报 owned roots=0／退出 1／stderr 空，不打印路径。修正测试异常类与实际目录创建方式，并加默认探测禁止回归，**29 passed, 3 warnings in 11.69s**（`data/raw/release-rehearsal-focused-verified-06c3.xml`）。失败报告保留，不替换为成功或清除计数。
- 最终组合专项 **211 passed, 3 warnings in 58.57s**（`data/raw/release-rehearsal-focused-final-06c3.xml`）；JUnit 独立核对 tests=211、errors=0、failures=0、skipped=0，新演练 **31**／原预检 **67**／目录来源 **22**／方案存储 **15**／课程条件存储 **29**／运营与许可 **47** 全执行。含五个迁移后实际 HTTP 场景（四组合聊天＋关闭旧 receipt／重新启用），不是现场 API／UI／账号证明。
- 最终全套：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/release-rehearsal-tests-06c3.xml` → **2211 passed, 5 warnings in 155.67s**。JUnit 独立核对 tests=2211、errors=0、failures=0、skipped=0，新增 **31 项**均执行（2180 → 2211）。五个警告仍为既有 SWIG 类型与 HTTP 422 常量弃用；不是真实性／性能／生产备份／留存或真实登录验收。所有报告在忽略的 data/raw，不提交私有运行证据。
- 三个新 Python 文件内存 AST、三份相关 MD 相对链接及 tracked／全部 **107 个 individual 未跟踪文件**空白检查通过；**38 个 tracked 修改／107 个未跟踪文件**，无暂存，HEAD 仍 `bb2f6e3`，前批成果保留。未运行／安装 Ruff，不宣称 lint-clean。

### 发布状态与下一段

- **未提交、未推送、未部署、未迁移／导入真实运行库、未真实备份恢复或账号登录、未修改运行 .env 或轮换凭证**。CLI 无配置导入／越界写／外部调用有 fresh 进程证据；普通 pytest 的现有全局 fixture 与 HTTP companion 会导入配置，不能混作零配置 CLI。实际 Config／API／UI 成套开关与告知仍需现场确认。
- 原五个迁移／导入器、schema、真实 seed／归档、Course／索引／检索、prompt version、线上保存策略均未修改。只在自有合成副本验证过程，不授予真实库授权，不把 unparsed／partial 升级，不删除生产用户行、不自动分发；七天仍非留存删除，真人／organic 与真实分布未知。06C-1 凭证风险处置仍待持有人确认。
- 下一入口 **06C-4**：补**入库后来源一致性的通用只读核验**，区分“选定归档正确”“schema 可用”与“给定副本已导入相同文档”。工具实现与合成测试可先行，真实副本、备份／留存责任、账号／生产部署／分发仍需本人明确目标与授权。

## 06C-4 — 入库后来源一致性的显式只读核验（2026-10-03）

### 范围与原因

- 06C-2 的归档／schema pass、06C-3 的特定合成内容断言，不足以证明给定副本已经导入相同文档。新增通用的选定输入→已有离线副本比对，不调用导入器／迁移器，也不从代码／配置中自动找真实库或归档。
- 本批仅用自建合成库与来源测试。没有读取开发运行库／生产库／真实备份、导入真实归档、补抓官网、使用真实账号或更新运行配置；既有 dirty 工作树保留。完整性核验与目标授权、备份恢复、真实性／完整政策／个人 POS 是不同门槛。

### 已实现

- 新 `scripts/verify_release_imports.py`：显式 `--db-copy` 加至少一组目录 JSONL、方案文件＋归档目录、课程 manifest＋归档目录＋course code；三组可同检。未提供组的来源／入库检查均 not_checked，组不完整失败，全不选失败，没有 commit／out／批准或参数简写。
- 复用既有本地非链接路径／大小／旁文件／私有输入指纹和 schema 参考核对。完整 DB 结构／版本／FK／quick_check 全通过才做文档比对；来源失败则该组不比对，不因坏库或缺表自动修复。三组全选的正常路径为 12 个机器检查；所有人工门槛 pending，release_approved 恒 false。
- 目录由现有 snapshot 函数重建身份与语义内容。只核原导入器唯一 code／精确 title 匹配的课程，缺行、快照 ID 或实际内容漂移失败；相同重复折叠、冲突失败。未知／多义和标题不符明确计数，全跳过失败；部分跳过仍只能声明 matching_records_only，不能冒充全归档覆盖或补出原 HTML／捕获时间。
- 方案来源重用冻结 HTML／sidecar 与候选表审计，仍只支持既有 Boston／2026–2027 适配器。核 program 存在、选定 ID／列 scope／文档 scope／来源 scope、实际摘要与完整预期内容；内容被改且摘要重算也失败，partial、来源／审核字段不升级。
- 课程条件重用实际离线块解析器，按精确课程身份／年度重建预期文档；列身份、实际摘要和来源内容都核对。OR／共修、未知引用、unparsed、description_evidence、credit_hours 保留；不借旧先修边补逻辑，不给课程声明校区，不计算个人资格。
- 语义规范化不依赖 JSON 顺序／格式；目录不比较 imported_at／retrieved_at，课程条件不比较 imported_at，与已有内容幂等契约一致，明确不是时间真实性核验。所有输入／DB 文档严格拒绝重复 key、非有限数与超预算，不信已有摘要、不丢坏行、不输出异常／私有行或改写摘要。
- 两个目标连接 immutable＋mode=ro＋query_only＋trusted_schema OFF，显式只读事务和 SQL 时间／步数预算；参考 DDL 只在内存，目标 total_changes=0。结束核受检文件私有 hash 与旁文件，不创建库／导出／缓存或读 .env。`-B` 独立进程守卫拒绝配置导入、外网／外部进程、全部磁盘写打开，SQLite 只允许显式只读目标或内存；普通 pytest 全局配置导入不能混作 CLI 行为。
- 不审查未选 DB 行／额外 schema 对象／政策片段／索引／模型／完整用户语义。固定 stdout JSON 只含状态／code／有限计数／布尔与限制，没有路径、hash、原文、URL、身份、SQL、token、未知参数值或 traceback；聚合报告仍不自动公开或匿名化。

### 修改文件

| 文件 | 修改 |
|---|---|
| `scripts/verify_release_imports.py`（新增） | 三组输入加载／离线审计、选定行身份／真实语义／摘要比对、只读／预算／稳定性和固定报告 |
| `tests/test_release_import_consistency.py`（新增） | 77 项合成实际导入、缺行／重算摘要篡改、输入／路径／旁文件拒绝、选择覆盖边界、变化／CLI／独立守卫／零 DML 及半成品来源状态回归 |
| `docs/release-import-consistency.md`（新增） | 输入组／调用、选定与全覆盖区别、排除时间字段、预算／退出码／有限证明；不是另起修改日志 |
| `docs/joint-release-acceptance.md`、本文件 | 联合清单接来源一致性工具，统一记录修改与验证；真实人工门槛仍待确认 |

### 验证记录

- 初始 RED **4 errors in 0.96s**（`data/raw/release-import-red-06c4.xml`）：实现不存在由合成 fixture 前置检查固定报错；JUnit tests=4／errors=4／failures=0／skipped=0，没有展开 Settings 或真实凭证。不能把 setup errors 记成四个断言失败。
- 初始 **4 passed in 1.90s**（`data/raw/release-import-focused-first-06c4.xml`）；扩展 **2 failed, 67 passed in 31.28s**（`data/raw/release-import-focused-expanded-06c4.xml`）。两处为新测试夹具：超限字符串不合法 JSON，先被原 json_valid CHECK 拒绝；重复课程用了不存在的 data 列。改为合法超大 JSON／实际 metadata 与 generated_json，未改原 schema、导入器或放宽核验断言，失败报告保留。
- 第一轮组合 **240 passed, 3 warnings in 55.44s**（`data/raw/release-import-focused-final-06c4.xml`）：JUnit 独立核对 tests=240／errors=0／failures=0／skipped=0，本批新增 76 项全部执行。后续增加半成品加载器反例，不把此轮冒充最终结果。
- 防御性 RED **1 failed, 76 deselected in 14.48s**（`data/raw/release-import-loader-red-06c4.xml`）：模拟未来来源加载器先写 state 再异常，发现失败组仍进入比对（failed 而非 not_checked）。修为来源检查失败主动丢弃该组 state，保留其他独立组结果；没有放宽失败到 pass。deselected 不记成 skipped 或已执行。
- 最终组合专项 **241 passed, 3 warnings in 53.75s**（`data/raw/release-import-focused-verified-06c4.xml`）：JUnit 独立核对 tests=241／errors=0／failures=0／skipped=0；新核验 **77**、已有预检 **67**、迁移演练 **31**、目录来源 **22**、方案存储 **15**、课程条件存储 **29** 均执行，没有 skipped 冒充验证。
- 完整回归：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/release-import-tests-06c4.xml` → **2288 passed, 5 warnings in 167.91s**。JUnit 独立核对 tests=2288／errors=0／failures=0／skipped=0，新模块 **77 项**全部执行（2211 → 2288）。警告仍为既有 SWIG 类型三项、HTTP 422 常量两项；不是性能／真实账号／生产恢复／来源真实性或留存验收。报告均在忽略的 data/raw，不提交私有运行证据。
- 两个新 Python 文件内存 AST、三份相关 MD 相对链接、tracked diff 和全部 **110 个 individual 未跟踪文件**空白检查通过；**38 个 tracked 修改／110 个未跟踪文件**，无暂存、HEAD 未变。原有成果保留，未运行／安装 Ruff，不宣称 lint-clean。

### 发布状态与下一段

- **未提交、未推送、未部署、未迁移／导入真实库、未真实备份恢复或账号登录、未修改运行 .env 或轮换凭证**；HEAD 仍 `bb2f6e3`，原五层迁移／schema／seed／归档、检索／prompt／线上策略未修改。06C-1 凭证风险处置仍待持有人确认，不由任何工具 pass 代替。
- 本批仅补本地核验能力，不证明真实副本已通过或开放运行库授权。留存／访问、真实账号、API/UI 配置、部署与分发仍需本人确认；七天仍非删除期限，反馈不自动成为真值，organic／真实分布未知。
- 下一入口 **07A**：转入既定第七批的**离线评测契约与耗时拆分基线**，先区分固定离线用例／合成 smoke 与真实用户分布，保留 X-Eval-Run 边界；不把缺 organic 样本当成已解锁 v0.5 真实分布评测或门控重校准，也不自动调用付费模型／开长实验或部署。

## 07A — 评测契约修正与默认关闭的组件计时（2026-10-03）

### 范围与原因

- 已有 metric 直接用重复 expected 累加，`recall_at_k(['a'], ['a','a'], k=1)` 实际得到 2；缺标签被当空负例，k 改变仍把结果写进旧 recall_at_5。三份延迟脚本分别使用不同索引／插值，偶数 4 样本 p50 在 API 脚本取第 3 项。这些会破坏后续基线对比，先修机制，不改模型或凭结果重校门控。
- 采用 experiment-design 的固定基线／单变量与先定义分析边界：只比较同一合成 kernel 的 trace off/on。不是优化候选 sweep、预注册、真实分布或生产性能实验，不重复已经被实测否决的 512→256，不做 static-shape 或付费／长 GPU 工作。

### 已实现

- `eval/run_eval.py` 在 search 调用前校验全体 query ID／文本／显式 labels／k；坏标签、缺标签、重复 ID／标签、非法返回值固定失败。helper 用集合防 >1，harness 对重复排名失败，不悄悄去重／丢错／将异常当正确拒答。
- 明确 capped coverage 与标准召回分别报数，新增实际 k、quality_status、负例独立分母／correct_rejections／false_positives。旧 recall_at_5 继续算返回列表前 5 的 capped coverage，不把 k10 的值塞进 @5；标准召回分母为所有标签，MRR 仍首个相关项在完整返回列表中的排名。无正例 canonical 指标 null，旧兼容 0 不作质量证据；历史有效 k5 数字、数据和归档未重算／改写。
- 新 `eval/latency_metrics.py` 统一 nearest-rank：max(0, ceil(n×p)−1)，4 项 p50 为第 2 项；空样本 null、NaN／Infinity／负值拒绝。三份既有 eval／probe 脚本接同一函数，未来报告／文字说明方法；原插值历史数字不强行等同。API 评测 CLI 另外在 HTTP warmup 前验证 labels。
- 新 `rag/profiling.py` 通过 ContextVar 显式采集，普通请求无采集器、decorator 不读时钟／不建样本；context wrapper 有小开销，不宣称零开销。阶段名白名单固定，不采查询／文本／ID，不用共享 last_timing、不日志／持久化、不改 API 请求／响应／prompt／遥测字段。
- 在真实 aliases、Retriever 的 SQLite filter／embedding／FAISS／回填、BM25、RRF／convex、hybrid filter／回填、三个 rerank scoring 入口加计时；只是包裹原调用，不改输入、排名、阈值、cache／pool 或模型。inclusive／exclusive 分开，父阶段扣直接子阶段；总账用整数 ns 计算，拒绝时钟／外层 wall 与独占阶段不一致，避免浮点 residual 被 clamp 成假零。当前没有独立覆盖 prefix／gate／HyDE／所有 API SQL；未包裹成本保持 uninstrumented。
- 新 `eval/profile_eval.py` 冻结标签后串行 warmup，再按固定顺序测量每轮质量与 wall／阶段；warmup 不进分位数，warmup／测量失败立即中止，不丢样本。每阶段只汇总出现的调用，记录 absent，不给 alias 的 embedding 补零；展示每轮指标和 ranking_stable，不以第一次遮住波动。residual 不是网络成本，inclusive 分位数不可相加。适配器可能有外部副作用，库本身不构成 offline 沙箱。
- 新 `scripts/profile_offline_search.py` 只接受 trace 开关，读取 schema 但只创建内存库／3 维合成 FAISS。3 门假课程、5 个 alias／semantic／multi／filtered／negative 用例，真实 BM25／RRF／筛选／回填／拒答，嵌入及重排替身；1 次全组 warmup＋3 次测量（5／15 次），无随机抽样、外部模型／HTTP／query_log，查询阶段 total_changes=0。退出 0 仅测量完整执行，golden 不变量另由测试确认，报告不审批／不证明速度或质量提高。
- 新协议文档含单变量矩阵、固定 JSON stub、可运行 off/on 命令、0 GPU／0 外部 API 费用及不持久化预算、样本与失败分析计划。独立进程阻断配置、.env、网络／外部进程、真实模型库、所有磁盘写打开，只允许 SQLite 内存；普通 pytest 和真实 routes companion 的配置导入不混作 CLI。

### 修改文件

| 文件 | 修改 |
|---|---|
| `eval/run_eval.py` | labels／返回／k 契约，capped 与 standard 指标、固定 @5 兼容／负例分母／文字说明；CLI setup 前验证 |
| `eval/latency_metrics.py`、`eval/profile_eval.py`（新增） | 统一分位数，固定输入／warmup／多轮质量／wall／阶段的顺序测量与完整账目 |
| `rag/profiling.py`（新增） | context-local、默认关闭、固定名、嵌套 inclusive／exclusive、异常复原与整数 ns |
| `rag/retriever.py`、`rag/hybrid.py`、`rag/query_normalizer.py`、`rag/reranker.py` | 原真实组件的计时包裹，不修改检索／模型逻辑；此前改动保留 |
| `scripts/profile_offline_search.py`（新增） | 只用内存与明确替身的实际 kernel 命令；stdout 聚合报告，无目标／导出／网络参数 |
| `scripts/eval_via_api.py`、`scripts/probe_latency.py`、`scripts/probe_inference_latency.py` | 统一未来分位数方法，API eval 的 k／metric 文字与 warmup 前校验，独立脚本异 cwd import 支持；未运行 live probes |
| `tests/test_offline_eval_profile.py`（新增） | 64 项契约／计时／固定 kernel／实际 API 透明性／eval marker／独立 CLI 隔离与拒绝场景 |
| `docs/offline-eval-profile.md`（新增）、本文件 | 基线／实验边界／分析契约／下一入口；修改仍只在本文件记历史 |

### 验证记录

- RED **5 failed in 12.89s**（`data/raw/offline-profile-red-07a.xml`）：重复标签实际值 2、缺 k 字段、坏标签未阻止调用、4 样本 p50=3，以及新 profiling 未实现；JUnit tests=5／errors=0／failures=5／skipped=0，无真实配置对象展开。
- 初始 **22 passed, 3 warnings in 1.30s**（`data/raw/offline-profile-focused-first-07a.xml`）：新增 5＋既有 metric 17。首次固定 CLI smoke 返回固定失败 JSON，安全诊断只报 AttributeError 与文件／行，定位为新夹具把既有 FaissIndex.add 两参数顺序用反；按实际签名修正，并对照实际筛选键 primary_code_prefix，不改变组件接口或放宽 golden 断言。
- 扩展 **77 passed, 3 warnings in 5.47s**（`data/raw/offline-profile-focused-expanded-07a.xml`）：新 60＋原 metric 17；含实际 kernel 的 off/on、三种临时 API 分支、context 的 clock／嵌套／异常复原、无配置／外部／磁盘写的 fresh CLI 等。
- 组合专项 **266 passed, 4 warnings in 9.17s**（`data/raw/offline-profile-focused-final-07a.xml`）：JUnit tests=266／errors=0／failures=0／skipped=0，新 **64 项**全执行，另涵盖 metric／Retriever／hybrid／reranker／normalizer／API search／检索契约／dashboard。包含冻结 labels、防时钟总账矛盾、整数 ns 无负 residual、HTTP warmup 前校验；其后将报告未证明字段统一为 quality_improvement_verified=false，最终全套覆盖该命名。
- 三个实际临时 API 场景（alias／semantic／adversarial）off/on 响应除原 latency_ms 外完全相同，没有新增 stages 字段；query_log 两次请求均 eval:offline-profile-companion，未制造 organic。是临时 DB、替身模型与 TestClient，不是现场 API／账号／真实召回或速度证据。
- 四个当前固定输入严格校验通过：v0.2 **42（38 正／4 负）**、v0.3 **104（92／12）**、v0.3.1 **116（104／12）**、v0.4 **116（104／12）**。只读审阅，未调用 search／读用户日志／重抓或改写标签；默认 test_set.json 仍旧 v0.2，不自动切最新文件。
- 最终完整回归：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/offline-profile-tests-07a.xml` → **2352 passed, 5 warnings in 167.23s**。JUnit 独立核对 tests=2352／errors=0／failures=0／skipped=0，新 **64 项**均执行（2288 → 2352），最终 quality_improvement_verified 字段与所有旧模块回归通过。警告仍为既有 SWIG 三项／HTTP 422 常量两项，不是新增真实模型调用或性能证据；报告在忽略的 data/raw。
- 13 个本批 Python 文件内存 AST、协议与统一日志相对链接、tracked diff 和全部 **116 个 individual 未跟踪文件**空白检查通过；**45 个 tracked 修改／116 个未跟踪文件**，无暂存，HEAD 仍 bb2f6e3。已有 dirty 成果保留，未运行／安装 Ruff，不宣称 lint-clean。

### 发布状态与下一段

- **未提交、未推送、未部署、未读取／迁移真实 DB、未真实账号／NAS／外部模型调用、未改 .env 或轮换凭证**；HEAD `bb2f6e3`，原脏工作树保留。历史 eval 文件未改；新样本／API companion 均明确合成或 eval。没有性能胜出／SLA、真实分布或 live 参数重校结论。
- 06C-1 凭证风险处置、实际备份／留存／访问／账号／部署／分发仍需本人确认，机器测试不能代替。默认关闭的 stage hooks 也没有获得真实系统采样授权。
- 下一入口 **07B**：先修已看到的 live probe 安全契约：缺 X-Eval-Run、probe_latency 的 --rerank 未接实际组件、ready／warmup／错误／缺 latency 处理与完整采样分母。用 MockTransport／临时 TestClient 实现并验证，不发真实请求或写 organic；之后再讨论限流与真后端／static-shape 的授权实验，不重新试 512→256。

## 07B — Live probe 的流量标记、失败分母与实际接线（2026-10-03）

### 范围与原因

- `probe_latency.py` 与 `probe_inference_latency.py` 没有 X-Eval-Run，执行会被服务器当成 anonymous／organic；前者的 --rerank 参数只是存在，没有创建／预热或接入 reranker。并非这批已运行造成污染，本轮未执行现场 probe。
- API eval 只检查 ready HTTP 码，inference probe 只检查 JSON status；warmup 状态／响应未完整验证。缺 latency 被补 0，缺 results 被当空列表，错误请求被丢掉后还能给出成功统计。本轮先修工具契约，不改变线上检索／门控或调参。
- 已有文件 write_text 会覆盖上次产物，异常消息可能包含 URL／响应／输入；新增防覆写和固定结果码，保留失败证据，不删除历史报告。三份工具仍 live-capable，X-Eval-Run 不是禁写日志、付费豁免或运行授权。

### 已实现

- 新 `eval/probe_contract.py` 是仅标准库的契约模块（复用现有纯评测／分位数模块），导入无网络／配置／模型／DB 或输出 I/O。完整用例、HTTP k／查询长度、有限 JSON／version、4 MiB 输入预算、样本分母／10,000 search 总预算先验证，再创建输出或 runtime。非 JSON 文件拒绝，空负例须明确 labels=[]，坏标签不成为正确拒答。
- label 有界、安全 ASCII／非空；所有 ready、warmup、测量逐次传 X-Eval-Run。远端仅 http(s) origin，无凭证／路径／query／fragment，有限 timeout ≤300 秒；httpx 关闭环境代理与自动 redirect，单个 context-managed 客户端，不创建一次性 client 或隐式重试。
- ready 必须 HTTP 200＋ready body＋实际正整数双计数；200/warming、503/ready、坏 JSON／计数均中止。search 验证 HTTP 200、query／k 一致、合法分支、显式 results／唯一 course_id／≤k、完整 hit／有限 score、非负有限 latency；不缺省补 0／空列表，分支与结果内容一致。
- ProbeRun 串行区分 warmup 与正式测量，记录各自 planned／attempted／completed 或 succeeded／failed／not_attempted，readiness 另列。失败即停、不重试或凑样本，保留已成功测量的分位数但明确 aborted／仅 validated_measured_successes；空样本 null，不显示半套 quality 或 per_query。时钟不有限／倒退亦失败，不伪造 0。
- server 是响应耗时，wall 是 POST 到返回（客户端响应校验不算进 wall）；warmup 不进正式统计，统一 nearest-rank。API eval 默认 warmup 第一条固定用例一次，可显式设置；inference 保留旧 --n=总 search 约定，50−3=47 正式样本；本地 probe 的 warmup／iterations 均完整用例轮数，不将重复查询解释成独立用户分布。
- 本地 `_build_app` 在预检后加载 PyTorch embedder／FAISS／BM25；--rerank 真正构造 CrossEncoderReranker、score 预热、接 app.state。关闭时明确 None；加载／预热失败不静默降级。model 初始预热另于请求 warmup，不计请求数。TestClient 用 context manager，实际 DB dependency 在现场仍是运行路径，测试中明确 override 只用内存库。
- API eval 保留旧质量字段与 per_query 格式，并接本批完整账目／canonical 指标；inference 完整报告保留旧 scalar keys（n、server/client pXX／mean／min／max 等），新增明确总计划。旧 _percentile 空 0 helper 仅兼容，不用于新 canonical 报告；历史用例／报告／方法说明不重算。
- 输出目标须已有父目录中的新文件，独占创建在请求／模型加载前完成；已有文件、目录、symlink／悬空、创建竞争均拒绝，不覆盖、自动建目录或删除。失败报告保留，下一次用新路径／label；写／close 出错返回 2，且等 close/flush 成功后才打印完成，避免同时输出成功和失败。无法写完时可能留空／部分文件，不冒充有效报告或自动恢复。
- 脚本自己的 stdout 只聚合（不含 query／ID／URL／路径／label），不回显参数或原异常；API eval 文件含私有明细，访问／留存／Git 排除需持有人管理，工具未设 ACL。实际 app／模型／服务器仍可能日志输入，去回显不等于屏蔽其他组件日志。退出 0 完整、1 执行失败或本地 p50 目标未达、2 输入／输出失败；target_met 不是生产 SLA，release_approved／production_performance_verified 均 false。

### 修改文件

| 文件 | 修改 |
|---|---|
| `eval/probe_contract.py`（新增） | 预检、响应契约、eval header、状态机／完整分母、固定失败／stdout、独占输出与不导出半套质量 |
| `scripts/eval_via_api.py` | 在任何 HTTP／输出前严格预检，真实 ready／warmup／响应验证，保留完整质量报告；固定聚合输出、无覆写 |
| `scripts/probe_inference_latency.py` | 全请求标签、统一持有并关闭 client、total n 与 measured 分母、错误即停／无缺失补零、旧完整 scalar keys；不创建输出目录 |
| `scripts/probe_latency.py` | lazy 构建、真实 reranker 预热／state 接线、关闭明确降级、实际 ready／响应／轮数、完整计数／失败退出、关闭 TestClient |
| `tests/test_live_probe_contract.py`（新增） | 122 项 mock／pure 契约／临时实际 route／fresh CLI 隔离／失败与文件保护回归 |
| `tests/test_offline_eval_profile.py` | 坏标签仍在 client 构造前失败；CLI 由抛 ValueError 改固定 JSON＋返回 2，相应断言不再要求 traceback |
| `docs/live-probe-contract.md`（新增）、`docs/offline-eval-profile.md`、本文件 | 当前运行／采样／输出边界、旧协议入口更新；修改历史仍只在本文件 |

### 验证记录

- 初始 RED **3 failed in 12.83s**（`data/raw/live-probe-red-07b.xml`）：契约／可传 argv 的测试入口未实现，仅证明新接口缺口；不混为真实缺陷复现。随后兼容旧 CLI 的语义 RED **3 failed in 12.55s**（`data/raw/live-probe-red-semantic-07b.xml`）：缺新模块、inference 请求实际缺 X-Eval-Run、API eval 对模拟 200/warming 实际返回 0。均只 MockTransport，无真实请求／运行数据。
- 初始组合 **84 passed, 3 warnings in 5.44s**（`data/raw/live-probe-first-07b.xml`），新初始 3＋07A 64＋原 metric 17；旧 HTTP warmup 前校验测试保留效果，仅改 CLI 错误接口断言。
- 扩展首次 **187 passed／3 failed, 3 warnings in 22.62s**（`data/raw/live-probe-expanded-07b.xml`）：三项 NaN／Infinity 夹具在 httpx.Response(json=...) 的编码器被拒绝，未进入新 validator；换原始 JSON bytes 模拟远端坏响应，不放宽断言。修正与扩展后 **202 passed, 3 warnings in 12.71s**（`data/raw/live-probe-expanded-fixed-07b.xml`），其后加 completeness 防半套质量的新案例。
- 组合专项首条命令误写 test_retrieval_contracts／test_dashboard 文件名，pytest **no tests ran in 0.04s**、退出 1，不记作 skipped 或已验证。对照 rg 文件清单修正为实际 test_retrieval_contract／test_eval_dashboard；最终 **401 passed, 4 warnings in 17.36s**（`data/raw/live-probe-focused-verified-07b.xml`）。JUnit 独立核对 tests=401／errors=0／failures=0／skipped=0，新 **122 项**全部执行，含 07A／metric／API readiness／search／Retriever／hybrid／reranker／normalizer／检索契约／dashboard。
- 两个真实 route companion 只在内存库／FAISS＋替身模型执行：--rerank on/off，各 2 warmup＋4 measured，6 行 query_log 全为 eval:local-mock，fake 路径没有实际打开／创建；on 确认 score 的初始化预热和正式 semantic 评分均调用，off 没有 reranker 调用，BM25 构建连接关闭。无 Gemini rescue（测试明确 override None），不是现场速度／召回结论。
- fresh CLI off-cwd 的三工具 9 组拒绝场景阻断配置／.env／模型／DB／网络／外部进程及全部写打开，均返回固定 2；两个 remote complete MockTransport 进程同样阻断这些资源，只允许各自新 JSON 写入，确认四次模拟 HTTP 均带标记且 client 已关闭。整个普通 pytest／实际 app 测试仍导入配置，不称全套零 .env。
- 最终完整回归：`.venv/bin/python -m pytest tests/ -q --tb=short --show-capture=no --junitxml=data/raw/live-probe-tests-07b.xml` → **2474 passed, 5 warnings in 172.29s**。JUnit 独立核对 tests=2474／errors=0／failures=0／skipped=0，新 **122 项**全执行（2352 → 2474）。警告为既有 SWIG 三项、HTTP 422 常量两项；不是现场模型／账号／性能或发布验收。报告均在忽略的 data/raw，不作为生产报告或私有数据提交。
- 四个实际固定输入（v0.2 42／38 正；v0.3 104／92 正；v0.3.1 与 v0.4 各 116／104 正）严格 HTTP eval 预检通过，历史 labels／评测归档未改。6 个相关 Python 文件内存 AST、三份 MD 相对链接、tracked diff 与全部 **119 个 individual 未跟踪文件**空白检查通过。**45 个 tracked 修改／119 个未跟踪文件**，无暂存、HEAD 未变；原有成果保留，未运行／安装 Ruff，不宣称 lint-clean。

### 发布状态与下一段

- **未提交、未推送、未部署、未现场 API／真实 DB／NAS／外部模型调用、未改 .env 或轮换凭证**；HEAD `bb2f6e3`，此前脏工作树成果保留。原 API wire schema／检索／prompt／门控／历史 labels 与评测归档没有改变，没有生产速度／真实用户分布的结论。
- 06C-1 凭证风险处置、真实账号／备份恢复／访问留存／分发仍需本人确认；新增工具及测试通过不授予现场跑分、开模型／付费采样或替持有人审批。
- 下一入口 **07C**：请求限流／并发保护及 UI 的 429／超时处理契约，先按本地、模拟时钟／客户端、临时库验证，不自动更改生产参数或部署；真后端／static-shape 仍需明确目标与运行权限，不重试 512→256，也不把缺 organic 当成已解锁 v0.5 门控重校。

## 07C — 请求门禁、并发保护与前端失败提示契约（2026-10-03）

### 范围与原因

- 突发流量或慢请求堆积时，无界并发会导致进程内存暴涨、CPU 耗尽及下游模型/DB 争抢。生产单机需要确定性的本地过载保护。
- 避免传统限流依赖客户端 IP（反向代理／Cloudflare 下易伪造或多用户共享出网 IP 导致误伤）或外部集中缓存（Redis 破坏免配置单机架构）。
- 前端原网络错误提示粗糙，未区分 429（请求超频）与 503（服务繁忙），且 stream 断流时容易把截断的半成品回答误作完成，导致误导或关联无效反馈凭证。

### 已实现

- 新增纯标准库单进程门禁 `api.admission`（无需外部 Redis，不加载 Settings/DB/模型）：
  - `AdmissionPolicy` 约束 capacity (1–10000), refill_per_second (0.01–1000), max_inflight (1–100)，类型严格拦截布尔值与非有限数。
  - Token Bucket 算法保证突发速率受限，`max_inflight` 严格控制 ASGI 生命周期内同时活跃的请求数。
  - 并发打满先返回 503 `service_busy`，`Retry-After: 1`，不扣减 token。
  - 有并发名额但 token < 1 时返回 429 `rate_limited`，动态计算 `Retry-After = ceil((1 - tokens) / refill_per_second)`。
  - 单调时钟异常或倒退时安全失败关闭，返回 503 `service_unavailable`。
  - 仅对 `POST /search` 和 `POST /chat`（含尾斜杠）拦截，只读健康检查/认证/Co-op/静态资源完全旁路；不识别 IP、不记录 query、不排队，无外部依赖。
  - `Lease` 在纯 ASGI `await self.app(scope, receive, send)` 的 `finally` 块释放，保证涵盖流式输出的完整生命周期，不会在响应头发出后提前释放。
- 配置与错误处理：
  - `config/settings.py` 增加 `REQUEST_GUARD_*` 参数，默认 `request_guard_enabled=False`，配置默认示例在 `.env.example`。
  - `api/exceptions.py` 统一映射 429 为 `rate_limited`。
  - `api/main.py` 的 `create_app` 支持 `admission_guard` 注入，解耦测试与运行环境。
- 前端交互与断流保护：
  - `app/api_client.py` 适配 429 与 503，安全解析 0–3600 的 `Retry-After` delta-seconds；底层 HTTP client 显式禁用重试与重定向。
  - stream 消费中若网络异常或未收到 done/error 就遇到 EOF，主动补充 `incomplete_stream` 错误事件。
  - `app/streamlit_app.py` 遇到 stream 错误立即中断并友好提示“仅生成部分回答”，清空未完成回答的反馈关联，不挂 receipt；前端适配 429 频繁请求与 503 繁忙提示。
- 文档：
  - `docs/request-admission.md` 详述机制边界与不变原则。

### 修改文件

| 文件 | 修改 |
|---|---|
| `api/admission.py`（新增） | 纯标准库单进程门禁、Token bucket + max_inflight、503/429 严格 Retry-After、ASGI 全生命周期租约释放 |
| `config/settings.py` | 新增 REQUEST_GUARD_* 开关与参数校验，拦截布尔值与越界参数 |
| `.env.example` | 增补门禁配置示例与安全注释，明确默认关闭，不改动运行 .env |
| `api/main.py` | create_app 注入 AdmissionGuard，注册 AdmissionMiddleware 针对 search/chat 门禁 |
| `api/exceptions.py` | 统一错误映射支持 429 rate_limited 结构化响应 |
| `app/api_client.py` | ApiError 适配 error_type 与 retry_after_seconds；429 提示与 Retry-After delta-seconds 解析；stream 断流补全错误事件 |
| `app/streamlit_app.py` | stream 错误中断阻断与未完成回答反馈清理；429 与 503 页面友好提示 |
| `docs/request-admission.md`（新增） | 保护范围、准入与失败契约、前端行为与单进程边界说明 |
| `tests/test_request_admission.py`（新增） | 100 项纯契约、时钟倒退、并发打满 503、限流 429、租约释放、实际 App 路由拦截、客户端解析与断流补全回归 |
| 本文件 | 记录 07C 范围、修改、验证与全量回归状态；推进至下一批次 08 |

### 验证记录

- 专项测试：`tests/test_request_admission.py` 包含 100 项测试，执行结果 **100 passed, 3 warnings in 36.92s**。
- 组合回归与全套执行：`.venv/bin/python -m pytest tests/ -q --tb=short -p no:cacheprovider` → **2574 passed, 5 warnings in 258.71s**。无失败、无跳过；相对 07B 新增 100 项测试全部执行（2474 → 2574）。警告仍为既有 3 个 SWIG 类型弃用和 2 个 HTTP 422 常量弃用。
- 内存 AST 与空白检查通过；工作树保留原有 45 个 tracked 修改，未运行/安装 Ruff，不宣称 lint-clean。

### 发布状态与下一段

- **未提交、未推送、未部署、未修改生产运行 .env**；HEAD 仍 `bb2f6e3`。
- 本门禁为单进程内存状态，多 worker／分布式下无全局配额；默认保持关闭，上线启用须结合容量压测评估。
- 下一入口 **08**：增量更新、索引版本、生产依赖锁定、CI 与恢复演练。

## 08 — 增量更新、索引版本、生产依赖锁定、CI 与恢复演练（2026-10-04）

### 范围与原因

- 原 FAISS 索引持久化只有裸二进制 `index.faiss` 与 `id_map.json`，缺少版本元数据（嵌入模型标识、向量维度、记录数、创建时间戳与 SHA-256 校验和清单），加载时如文件损坏易导致 C++ 崩溃，且缺少写出时的原子文件替换（`staging + os.replace`）。
- 原 `scripts/rebuild_faiss.py` 仅支持全量清空重建；在课程库存在大量不变记录时，重跑重型模型（如 BAAI/bge-m3）的嵌入耗时巨大，缺乏增量比对更新能力。
- 生产环境构建规范与依赖锁定检查缺少自动化测试；`pyproject.toml` 中的 `[tool.hatch.build.targets.wheel].packages` 遗漏了 `"db"` 模块，打 wheel 包时存在仓储层缺失风险；需确认 Dockerfile 使用 `--frozen` 且遵循 ADR-0023 生产瘦身原则（保留必要的 `pyarrow`）。
- 灾难恢复演练原仅为脚本注释，缺乏纯沙箱端到端灾难恢复验证 CLI，且仓库缺失 GitHub Actions 自动化 CI 规范。

### 当前行为与实现

- **08A 索引清单与版本元数据**：
  - `rag/index.py` 的 `save()` 统一生成并持久化 `index_manifest.json`，包含 `manifest_version`（1.0）、`embedding_model`、`dimension`、`count`、`created_at` 以及两份数据文件的 SHA-256 校验和；默认启用 `atomic=True` 同级临时目录 staging 后原子替换。
  - `load()` 严格在调用 `faiss.read_index` 前先读取并验证清单，支持 `expected_model` 模型比对、维度/计数一致性校验；`verify_checksums=True` 时在反序列化前完成 SHA-256 完整性核验；对缺失清单的历史索引安全降级兼容。
  - 提供 `FaissIndex.get_manifest()` 与 `FaissIndex.verify_integrity()` 轻量级只读核查接口。
- **08B 增量更新与索引核验 CLI**：
  - 新增 `scripts/verify_index_manifest.py`，支持独立核验 FAISS 目录的结构完备性、清单格式、SHA-256 哈希及预期模型，提供 `--json` 机器可读输出与标准运维返回码（0/1）。
  - 扩展 `scripts/rebuild_faiss.py` 支持 `--incremental` 增量模式：基于 SQLite 目标集合与现有索引的差集，自动剔除已删除或非 indexed 课程（`remove()`），仅对增量课程调用 `embedder.encode()`，在索引缺失或损坏时安全降级为全量重建；支持 `--model-name` 参数注入清单。
- **08C 生产依赖锁定与 Wheel 规范**：
  - 修复 `pyproject.toml` 的 wheel 打包配置，将 `"db"` 加入 `tool.hatch.build.targets.wheel.packages`。
  - 新增 `tests/test_production_dependencies.py`，断言 `uv.lock` 存在且完整覆盖 `pyproject.toml` 的所有依赖；验证 wheel 目录包含全部业务包；验证 Dockerfile 使用 `uv sync --frozen` 并保持 ADR-0023 瘦身排他约束；执行生产运行时核心模块的 smoke 导入。
- **08D 灾难恢复演练与 CI 流水线**：
  - 新增 `scripts/rehearse_recovery.py`，提供完全沙箱化的灾难恢复演练能力：自动创建独立临时环境，模拟备份源（SQLite 快照 + FAISS 索引），验证还原后 SQLite 的 `PRAGMA integrity_check`、`PRAGMA foreign_key_check` 与 schema 结构；验证 FAISS 还原/自动重建、SHA-256 清单核对，以及向量检索与 SQLite 的端到端只读跨库检验，演练完成后自动清理现场并支持结构化报告。
  - 新增 `.github/workflows/ci.yml`，编排 GitHub Actions CI 流水线：执行 `uv lock --check`、依赖冻结安装、生产依赖与打包验证、灾难恢复沙箱演练及全量离线回归测试。

### 修改文件

| 文件 | 修改 |
|---|---|
| `rag/index.py` | 增加 SHA-256 计算、`index_manifest.json` 元数据清单、原子写入 `atomic=True`、加载模型与哈希校验、无清单兼容、`get_manifest` 与 `verify_integrity` |
| `scripts/verify_index_manifest.py`（新增） | 独立 FAISS 索引清单与 SHA-256 校验 CLI，支持模型预期与 JSON 输出 |
| `scripts/rebuild_faiss.py` | 增加 `--incremental` 增量比对更新模式、`--model-name` 清单模型标识，支持自动降级全量与向后兼容返回字典 |
| `pyproject.toml` | `[tool.hatch.build.targets.wheel].packages` 补全 `"db"` 模块，避免 wheel 打包缺漏 |
| `scripts/rehearse_recovery.py`（新增） | 完全沙箱化端到端灾难恢复演练 CLI，执行 SQLite 完整性/外键检查、FAISS 恢复/重建、向量检索与跨库验证 |
| `.github/workflows/ci.yml`（新增） | GitHub Actions 自动化 CI 流水线，覆盖依赖锁定核对、离线全量测试与恢复演练 |
| `tests/test_faiss_index.py` | 扩展 10 项针对清单生成、模型不匹配拦截、SHA-256 篡改检测、原子与非原子保存、无清单降级的专项测试 |
| `tests/test_verify_index_manifest.py`（新增） | 覆盖索引校验 CLI/API 的有效索引、模型失配、文件缺失、哈希篡改、历史索引降级与 subprocess 场景（7 项） |
| `tests/test_rebuild_faiss.py` | 扩展 4 项针对增量新增、增量剔除、损坏索引自动回退全量与清单模型持久化的测试 |
| `tests/test_production_dependencies.py`（新增） | 覆盖 uv.lock 依赖覆盖率、wheel 打包模块完备性、Dockerfile 规范与核心模块导入（11 项） |
| `tests/test_recovery_rehearsal.py`（新增） | 覆盖灾难恢复沙箱演练全流程、强制重建索引、损坏索引自动回退、损坏数据库拦截与 CLI 调用（6 项） |
| 本文件 | 记录 08 批次范围、文件变更、验证记录与项目阶段状态 |

### 验证记录

- **08 专项测试集合**：包含 `test_faiss_index.py`、`test_verify_index_manifest.py`、`test_rebuild_faiss.py`、`test_production_dependencies.py`、`test_recovery_rehearsal.py` 共 5 个文件，运行结果 **65 passed, 3 warnings in 9.51s**。
- **沙箱灾难恢复演练实测**：`python scripts/rehearse_recovery.py --json` 在 WSL 环境下运行通过，耗时约 0.4s，SQLite `integrity_check=ok`, `foreign_key_check=ok`，5 门课程还原与向量检索端到端验证通过，退出码 0。
- **全量回归验证**：运行 `.venv/bin/python -m pytest tests/ -q --tb=short -p no:cacheprovider`：
  - 最终结果：**2612 passed, 5 warnings in 184.95s (0:03:04)**。
  - 相比 07C（2574 项）净新增 **38 项**回归测试（2574 → 2612），全部通过，0 失败、0 跳过。
  - 5 个警告仍为 3 个已知的 Python 3.12 SWIG 类型弃用警告以及 2 个 FastAPI/AnyIO HTTP 422 常量弃用警告。
- **依赖锁定核对**：`/home/shen_haowei/.local/bin/uv lock --check` 返回 `Resolved 220 packages in 4ms`，完全同步。

### 发布状态与全阶段收束

- 本地代码与配置修改完成并通过全套离线验证；**未提交、未推送、未部署 NAS，未修改生产数据库**。
- 01 至 08 批次规划的所有功能开发、契约校验、测试套件扩充与自动化演练工具已全部完成并闭环沉淀。

## 09 — 全项目审查修复（2026-10-04）

### 范围与原因

- 2026-10-03 对 01–08 批次（约 2.4 万行，全部未提交）做了一次完整审查，确认 14 条问题，其中最严重的三条是：CI 在 GitHub 上必然失败；导入培养方案后，部分 /chat 提问直接返回 409；生产镜像里有三个包没有锁版本。本批次逐条修复并核验，不新增功能。

### 已实现（按审查编号）

1. **CI 缺密钥**：`.github/workflows/ci.yml` 在 job 级注入占位 `GEMINI_API_KEY`（不是真实密钥）。
2. **导入方案后 /chat 返回 409**：项目已有版本化方案、但没有核验过的学期安排时，不再报错，而是退回 hybrid 检索，并附加提示码 `program_schedule_unverified`。提示词升为 `chat_v4` 4.1，新增「检索提示（DATA）」段和对应规则：这些候选课只能作为相关课程介绍，不能说成官方第一学期安排，并引导用户去 Programs 页。前端在回答下方显示提示，提示码随消息历史保存（只保存不超过 64 字符的短码，最多 10 个；界面只显示已知的提示码）。真正的冲突（所选项目与问题前缀不一致、前缀对应多个项目）仍返回 409，但说明改成中文，界面用 🧭 提示呈现，不再显示「⚠️ Chat failed」。
3. **生产镜像依赖未锁**：Dockerfile 用 `ARG` 把 CPU torch（2.12.0）、optimum（2.2.0）、optimum-intel（2.0.0）钉成 `==`，构建时把实际解析结果写到 `/app/runtime-freeze.txt`。测试断言 uv.lock 之外的每个安装都精确锁版本，并要求构建生成这份冻结清单。
4. **增量重建保留过期向量**：索引为每门课记录文本指纹（SHA-256），随 id_map 一起持久化；`--incremental` 会重新嵌入文本有变化的课程。遇到模型不一致、没有清单、缺指纹、索引损坏或撕裂时，自动退回全量重建，并在返回结果和 CLI 输出里给出原因（`fallback_reason`）。
5. **方案链接遇到暂时性故障**：遇到 408/429/≥500 时，不再改导航和已选项目；同一链接只提示一次，并清掉对应缓存以便重试。只有成功或确定性失败才算处理完毕。
6. **索引保存不是整组原子替换**：没有改成整组切换，仍是逐文件 `os.replace`（清单最后写）。但清单钉住了两个数据文件的校验和，`load(verify_checksums=True)` 会在 `read_index` 之前严格校验（两个哈希缺一不可），所以撕裂状态会被拒绝，不会静默加载错位的映射；增量重建遇到这种情况会退回全量。
7. **未迁移 v1.3 时 GET /coop 返回 503**：审核表缺失时，公开列表退回「只返回策展种子」并记日志，响应头带 `X-Coop-Moderation: available|missing`。`deploy.ps1` 验收时，这个头不是 `available` 就判失败，并提示先执行 v1.3 迁移。审核表缺失时上传仍被拒绝。
8. **生产启动不校验索引清单**：API 启动时以 `expected_model=settings.embedding_model`、`verify_checksums=True` 加载索引；没有清单的历史索引仍能加载，但会记 warning。
9. **别名层叠加筛选后返回空**：查询带「类似 / 替代 / 除了 / like / similar…」这类找替代课的意图、且所指课程被筛选排除时，退回 hybrid；直接询问该课程时，仍如实返回空。/search 与 /chat 行为一致。
10. **热路径未经真实模型评测**：见下方验证记录（差分评测、生产 /search 代理、真实 Gemini 抽查）。
11. **有结构化先修时看不到先修信息**：只有一个 Catalog 年度时默认展开，并注明「不代表你的适用年度」。即使有结构化先修，也保留「相关先修课程跳转（仅导航）」，只是不再画成「必修」关系图。
12. **课程详情在事件循环里同步查库**：课程详情、课程先修和培养方案相关的 6 个只读路由改为同步 `def`，放到线程池执行，不再阻塞事件循环。实测 course_context 约 1.4 ms，暂不加缓存。
13. **迁移脚本重复样板**：新增 `db/schema_blocks.py`。`schema_block()` 统一解析 `-- BEGIN/END` 标记，标记缺失、重复、顺序错或区块为空时报错；`begin_schema_migration()` 统一执行「PRAGMA + BEGIN IMMEDIATE + 区块 SQL」并保持事务打开，连接已在事务中时直接拒绝（避免 executescript 悄悄提交调用方的写入）。5 个迁移/同步脚本和演练夹具都改用这两个函数。提交与回滚仍由各脚本负责，因为迁移脚本建表后立即提交，而 sync 脚本要在同一事务里继续写数据。
14. **save() 两个分支重复构建清单**：合并为 `_write_set()`；有测试比较原子与非原子保存产出的清单，二者一致。

### 修改文件

| 文件 | 修改 |
|---|---|
| `.github/workflows/ci.yml` | job 级占位 `GEMINI_API_KEY`（#1） |
| `Dockerfile` | 三个 uv.lock 之外的包钉版本，生成 `/app/runtime-freeze.txt`（#3） |
| `api/routes/chat.py` | 方案降级与提示码、409 中文说明、别名层找替代时退回 hybrid（#2 #9） |
| `llm/prompts/chat_v4.py` | 提示词 4.1：检索提示段与规则（#2） |
| `app/state_manager.py`、`app/answer_evidence_view.py`、`app/streamlit_app.py` | 提示码保存与显示、409 用 🧭 呈现、先修跳转（#2 #11） |
| `api/routes/search.py`、`rag/query_normalizer.py` | `asks_for_alternatives()` 与退回 hybrid（#9） |
| `rag/index.py` | 文本指纹、严格校验和、`_write_set()` 去重（#4 #6 #14） |
| `scripts/rebuild_faiss.py` | 增量重建按指纹重嵌、退回全量并给出原因（#4） |
| `api/main.py` | 启动时校验模型与校验和（#8） |
| `app/deep_links.py`、`app/program_plan_links.py` | 暂时性失败不改导航、只提示一次（#5） |
| `db/coop_repository.py`、`api/routes/coop.py`、`scripts/deploy.ps1` | 缺审核表时只返回种子、`X-Coop-Moderation` 头、部署验收（#7） |
| `app/course_requisite_view.py` | 单年度默认展开、先修导航（#11） |
| `api/routes/course.py`、`api/routes/program.py` | 只读路由改为同步 `def`（#12） |
| `db/schema_blocks.py`（新增）及 5 个迁移/同步脚本、`scripts/release_rehearsal_fixtures.py` | 区块解析与迁移事务收拢（#13） |
| `tests/` 下 18 个文件（新增 `test_schema_blocks.py`） | 覆盖以上修复；原先断言 409 的方案用例改为断言降级与提示码 |
| 本文件 | 记录 09 |

### 验证记录

- **全量回归**：`2672 passed, 5 warnings`，0 失败、0 跳过（审查前 2612，净增 60 项）；5 个警告与 08 相同。
- **CI 模拟**：在不含 `.env` 的全新拷贝（跟踪文件 + 未被忽略的未跟踪文件）上，按 CI 顺序执行 `uv lock --check`、生产依赖测试（13 项）、恢复演练（exit 0）和全量离线回归，全部通过。注意：模拟沿用本地 venv，没有执行 `uv sync --frozen` 安装步骤。
- **#10 差分评测**：eval v0.4 的 116 条 /search 查询，HEAD（`bb2f6e3`）与当前代码在同一份 DB 副本、同一组确定性夹具模型下，输出 116/116 完全一致。
- **#10 生产代理**：向线上 /search（真实模型，带 `X-Eval-Run` 标记）发 8 条带专业前缀的中文查询，全部走 hybrid、没有误拒（例如「AAI 强化学习」→ AAI 6900/6610/6740），无意义的对照查询被拒。
- **#10 真实 Gemini 抽查**（v4.1 提示词，3 条）：回答正常；「CS 专业第一学期选什么课」按提示说明了没有官方第一学期安排。
- **v1.4 回填演练**（DB 副本）：6469 条中存入 6467 条，2 条因标题不一致被跳过。
- **ruff 0.5.0**（F/E9/B，仅改动文件）：本批新增代码无告警；剩余 5 条均为改动前已有。

### 发布状态与下一段

- **未提交、未推送、未部署 NAS，未修改生产数据库**。
- 遗留：
  - optimum-intel 的传递依赖（openvino 等）仍未锁版本；下次构建后读 `/app/runtime-freeze.txt`，再决定钉哪些。
  - /chat 没有回答质量评测集；v4.1 提示词对首字延迟的影响未测。
  - 回答里引用 64 位 snapshot_id，显得冗长（来自 v4 的「引用 snapshot_id」规则），待定。
  - 索引发布在崩溃后仍可能留下撕裂状态（会被拒绝加载，需要重建），没有做整组原子切换。
- 上线前：在生产库的备份副本上按 v1.3 → v1.7 的顺序演练迁移。

## 10 — 上线记录；钉住 lock 之外的传递依赖（2026-10-05）

### 范围与原因

- 01–09 已于 2026-10-04 合并进 main（merge commit `1c1b601`），19:13 UTC 起在 NAS 上线。线上库按 v1.3 → v1.7 迁移完成，结果与生产快照演练逐项一致，原有数据未变。上线后评测（v0.4，116/116 成功）：R@5 0.8609 / MRR 0.9362（09-14 基线 0.8628 / 0.9293），alias/hybrid/rejected 仍是 31/75/10，server p50/p95 871.7/1251.2 ms。
- 09 遗留的「openvino 等传递依赖未锁」在这次上线中真的发生了。对比 7 月镜像（`ed8e7971fcc0`）和新镜像（`57464a30d708`）的完整包清单，只有 8 个包版本不同，全部来自 lock 之外的两层 `uv pip install`：openvino 2026.2.1 → 2026.4.1（openvino-tokenizers 同步升级）、nncf 3.2.0 → 3.4.0、ninja、pydot、pyparsing、setuptools 70.2.0 → 78.1.0，以及 torch 2.12.1+cpu → 2.12.0+cpu（08 钉的 2.12.0 抄自 6 月的记录，7 月镜像实际是 2.12.1）。用夹具模型时代码输出 116/116 不变，所以 R@5 的微降（全部来自 q083 的第 5 名）是真实模型分数的漂移，最可能来自 openvino 升级。本批把这些包钉住，以后用同一份代码重建镜像，得到的是同一套依赖。

### 已实现

1. 新增 `runtime-constraints.txt`：9 个包的精确版本（setuptools、openvino、openvino-tokenizers、openvino-telemetry、nncf、ninja、pydot、pyparsing、tabulate），逐字抄自线上镜像的 `/app/runtime-freeze.txt`。setuptools 是因为 torch 2.12.0+cpu 要求 `<82`，torch 那层会从 PyTorch CPU 源另取一个版本；其余是 optimum-intel 2.0.0 不设上限的依赖。
2. Dockerfile 的两层 `uv pip install` 都加上 `--constraint runtime-constraints.txt`，注释更新为 2026-10-04 的已知可用组合。torch、optimum、optimum-intel 仍由 ARG 精确钉住，取值不变（与线上一致）。
3. 测试：新增 `test_out_of_lock_transitive_packages_are_constrained_exactly`，要求每条 lock 之外的安装都读约束文件、文件里每行都是 `name==version`、已知会浮动的 9 个包都在且不重复。顺带修正提取安装命令的辅助函数：先去掉注释行再匹配（之前会把注释里出现的 `uv pip install` 字样也当成命令）。

### 修改文件

| 文件 | 修改 |
|---|---|
| `runtime-constraints.txt`（新增） | lock 之外传递依赖的精确版本 |
| `Dockerfile` | 两层 `uv pip install` 读约束文件；注释更新 |
| `tests/test_production_dependencies.py` | 新增约束文件测试；提取命令时跳过注释行 |
| 本文件 | 记录 10 |

### 验证记录

- `tests/test_production_dependencies.py`：14 passed。变异检查：6 种改坏方式（任一层去掉 `--constraint`、约束写成范围、漏掉一个包、重复一行、torch 顶层改成 `>=`）都被测试拦下，原文件通过。
- 解析演练（`uv pip compile`，只解析不安装，Python 3.12 / manylinux x86_64）：torch 层只用 PyTorch CPU 源，解析出 torch 2.12.0+cpu 与 setuptools 78.1.0；optimum-intel 层走 PyPI、其余包固定为线上版本，解析出的 9 个包与线上镜像完全一致。对照组：不带约束时，今天解析出的结果也相同。所以本批不改变下次构建的结果，只防止以后漂移。
- 镜像未重建、未重新部署：线上镜像本来就是这套版本，下次部署时自动生效。

### 发布状态与下一段

- 线上运行的仍是 `1c1b601` 构建的镜像；本批只改构建约束，合并后不需要单独部署。
- 2026-10-04 约 21:55 UTC，NAS 非正常停机（没有关机记录，原因不明），22:14 UTC 自动重启，服务随之恢复、没有报错。UGOS 重启后把项目目录改回 root:root，下次部署前要先 `sudo chown -R shenhaowei:docker /volume1/docker/neu-compass`。
- 仍遗留（与 09 相同，本批未处理）：单独重跑 v1.5 的 core 会把 2 份方案降级；v1.6 验收清单里有 35 门占位课；验证器对旧库的 ALTER 漂移和 0 字节输入过严；`rehearse_recovery.py` 用 `hash()` 做种子；回答引用 64 位 snapshot_id 显得冗长；/chat 还没有回答质量评测集。

## 11 — v1.5 防降级与恢复演练确定性（2026-10-05）

### 范围与原因

- 处理 09/10 遗留里两条确定性的小问题：
  1. v1.5 的 core 与 extended 两层共用 2 个 plan_id（`cs-ms-boston-2026-2027-standard`、`info-ms-boston-2026-2027-standard-general`）。extended 版本带来源指纹，规则也更全（CS 13 个节点对 6 个，INFO 28 对 6）。按 core → extended → pathway 跑一次没有问题；但之后单独重跑 core，会用无指纹的旧版本悄悄覆盖这 2 份（dry-run 只显示 would_store=2，不报错）。10-04 上线时是靠人记住「不要重放 core」避开的。
  2. `scripts/rehearse_recovery.py` 的假嵌入器用内置 `hash()` 做随机种子。Python 对字符串哈希按进程加盐，所以每次运行的向量都不同，报告里的 top_search_hit 也跟着变（不影响通过与否）。

### 已实现（三轮审查后的最终行为）

1. `db/program_plan_repository.py`：
   - `provenance_downgrade(prior, incoming)` 有三条规则，按顺序取第一条作为原因：
     1. 旧的有来源指纹（`source_html_sha256`）、新的没有 → `drops_source_fingerprint`；
     2. 旧的是 `source_checked`、新的不是 → `drops_source_review`（只保护 `source_checked`；draft 换 draft、draft 升级都放行）；
     3. 两边都有指纹、指纹不同、新的抓取日期更早 → `drops_newer_capture`（同一指纹不算；旧行读不出抓取日期时这条不适用）。指纹不同、日期相同或更晚属于重新抓取，放行。
   - 旧行一侧只用 `_recorded()` 从原始 JSON 读这三项（`RecordedProvenance`），不做整份方案校验：内容哈希对不上、或新旧版本校验不过（`extra="forbid"`、校验收紧）的行，照样按它记录的来源判断，较弱的版本不能悄悄覆盖，同等或更强的可以修复。不是 JSON 对象的文档（`[]`、`null`、数字、双重编码）和 `{}` 不记录来源，可以直接覆盖。指纹字段只要非空就算有指纹（形状意外时宁可拒绝）；日期也接受 `2026-10-01T00:00:00` 这种写法。
   - `store(plan, *, allow_downgrade=False)` 默认拒绝降级，抛 `PlanDowngradeError(ValueError)`（带 `.downgrades`，可 pickle/copy，保留 `__notes__`）。`list_for_program()` 的完整性校验抽成 `_verified()`，行为不变。
2. `scripts/sync_program_plans.py`：
   - 第一次写入前，在同一事务里预检查整份文件：先按行的列值做 `validate_slot()`（与 `store()` 一致，换绑错误不被掩盖，dry-run 与 commit 判断相同），再判断降级；有降级就整份拒绝、一行都不写，并列出全部方案与原因。dry-run 同样拒绝。
   - CLI：`--allow-downgrade` 有意放行（报告里带 `downgraded`）；拒绝时打印一行说明、退出码 1，提示「同步一份去掉这些方案的文件，或确认后加 `--allow-downgrade`（例如网页确实退回了旧版本）」；structlog 改写到 stderr，成功时 stdout 只有 JSON 报告。
3. `scripts/rehearse_recovery.py` 和 `tests/test_rebuild_faiss.py` 的假嵌入器改用 SHA-256 派生种子，跨进程稳定。
4. `docs/program-plans.md`：导入说明写明以上规则、只更新部分方案的做法、网页回退时的处理和输出约定。

### 修改文件

| 文件 | 修改 |
|---|---|
| `db/program_plan_repository.py` | 三条规则、`RecordedProvenance` / `_recorded()` / `recorded()`、`store(allow_downgrade=)`、`_verified()`、可 pickle 的 `PlanDowngradeError` |
| `scripts/sync_program_plans.py` | 整份文件预检查（先 `validate_slot`）、`--allow-downgrade`、拒绝提示、日志写 stderr |
| `scripts/rehearse_recovery.py` | 种子改用 SHA-256 |
| `tests/test_program_plan_storage.py` | 22 个新测试：整份拒绝（连非降级方案也不写）、`--allow-downgrade`、规则与优先级（含 `RecordedProvenance`）、抓取日期比较、损坏 / 校验不过 / 篡改 / 任意形状的旧行、draft 重放与编辑、范围错误优先、pickle/copy、CLI 拒绝与 stdout |
| `tests/test_program_sources.py` | 按真实层顺序：core → extended（合成存档）→ 再跑 core 被拒、库内容不变，extended 重放仍为 0 |
| `tests/test_recovery_rehearsal.py` | 跨进程（`PYTHONHASHSEED` 分别为 1、2），单独、批量、换序编码的向量都一致，3 段文本互不相同；CLI 演练测试补上 `timeout` 和 `cwd` |
| `tests/test_rebuild_faiss.py` | 测试内的假嵌入器同样改种子 |
| `docs/program-plans.md` | 导入说明 |
| 本文件 | 记录 11 |

### 验证记录

- 全量回归：`2697 passed, 5 warnings`，0 失败（10 之后为 2673，本批新增 24 项；5 个警告与之前相同）。
- 变异检查 40/40 被测试拦下。每个变异体在 /tmp 下各自独立的仓库副本里并行跑，真实工作区从未改动。覆盖：三条规则的删除、反向、改比较符、改顺序、去掉条件；旧行读取的各种退化（整份校验、遇到异常形状崩溃、读错日期字段、缺审核状态当成 source_checked、去掉保护分支）；`store()` 与预检查的各种退化（不拦、只在 dry-run 拦、只记第一条、先写其余再报错、跳过 `validate_slot`）；CLI（忽略参数、日志回到 stdout）；`__reduce__`；种子的 4 种退化（`hash()`、常数、批内位置、文本长度）。
- ruff 0.5.0（F/E9/B）：7 个改动的代码和测试文件没有新增告警（两个测试文件各 1 条，改动前就有）。
- 三轮只读审查，每轮 2 路（语义 / 测试质量），都没有 CRITICAL/HIGH：
  - 第 1 轮 8 条（中 1、中低 1、低 4、小 2）：整份拒绝没有测试钉住、损坏的带指纹行被悄悄覆盖、拒绝提示照着做不了、异常不能 pickle、不比较抓取新旧、种子测试太弱、CLI 警告混进 stdout、原因优先级没钉住。第 2 轮全部处理（用户 10-05 同意按推荐做：损坏行按记录的来源判断；不加跳过参数，只把提示改准确）。
  - 第 2 轮：校验不过的行会让防线失效、预检查与 `store()` 判断范围的依据不同、日期规则在网页回退时会误拦（保留规则，写清处理办法）、`__reduce__` 丢 `__notes__`，以及若干测试缺口。第 3 轮全部处理。
  - 第 3 轮：draft 一侧没有测试、旧行日期字段没钉住、`_recorded()` 的保护分支没有测试、`{}` 用例分辨力不够、日期写法和非字符串指纹两处读取缺口、测试日期依赖种子等。本轮全部处理，第 3 轮审查者构造的 10 个存活变异也都纳入上面的 40 个，全部被拦下。没有再开第 4 轮。

### 已知、未处理（均为低）

- structlog 默认渲染器按 stdout 是否终端决定颜色：stdout 是终端、stderr 重定向到文件时，文件里会带颜色码。
- 被拒或失败时的一行说明仍写 stdout（文档写明的是「成功时」stdout 只有 JSON）。
- 双重编码或包在数组里的文档按「不记录来源」处理，可以被直接覆盖（`model_dump_json` 不会写出这种文档）。
- 预检查提前做 `validate_slot()` 后，同一文件里同时有「换绑范围」和「项目未导入」两种错误时，先报的错误可能与以前不同（都是整份失败；CLI 只打印异常类型）。

### 发布状态

- 改的是导入工具与演练脚本，不在线上请求路径上；合并后不需要单独部署，下次部署时随镜像生效，生产库也不用重跑任何迁移。在那之前，NAS 镜像里仍是旧脚本（没有防降级），所以新镜像部署前仍不要单独重跑 v1.5 的 core。

