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

## 12 — 回答引用改用普通说法；回答链接白名单（2026-10-05）

### 范围与原因

- 处理 09/10 遗留的「回答引用 64 位 snapshot_id 显得冗长」。10-05 在本地界面实测（本机代理给每条请求加 `X-Eval-Run: ui-audit-20261005` 后转发到线上 API，不计入真实用户查询）：问「CS 5800 难吗」，回答末尾印出 `snapshot_id: catalog:` 加 64 位摘要，还有两个 `rmp_review_UmF0…` 形式的评价 ID；课程详情面板里快照 ID 整串显示，下面还列了 50 个评价 ID。原因是 v4 规则要求「引用 catalog_url 和 snapshot_id」「把工作量等归因到 source_id」。
- 新规则会让模型写 Markdown 链接，而回答原样按 Markdown 渲染；评价引文是第三方用户写的内容，也会进提示词。所以同一批里给回答文本加上链接白名单。

### 已实现

1. **提示词 4.2**（`llm/prompts/chat_v4.py`；v3 与其余规则不变）：
   - 只改提示词输入的投影：目录快照去掉 `snapshot_id`；引文的 `source_id` 换成 `source_kind`（英文标签）；`source_review_ids` 换成 `recorded_sources`，只列来源类型、不给条数。meta 与课程详情里的 `answer_evidence` 不变，ID 仍可追溯。
   - 不给条数是第 1 轮审查后改的：ID 列表是抽取模型自己写的，没有去重也没有校验；RMP 评价按任课老师抓取（每人最多 25 条），不按课程筛选。给出总数，模型容易写成「这门课有 50 条评价」。
   - 来源类型标签（第 2 轮审查后定稿）：
     - RMP 写成「按姓名匹配到这门课任课老师的 RateMyProfessors 评价，可能是关于别的课」。抓取时按姓名搜索、取第一个匹配，可能是同名的另一位老师。
     - `catalog_` 来源写成「抽取时用的课程文本，可能混有目录以外的文字，不是记录的目录快照」。不再说「旧」：它不一定比快照旧。
   - 规则：
     - 来源用普通说法写，例如「RateMyProfessors 上对任课老师的评价，可能是关于这位老师教的其他课」。
     - 目录写成指向 `catalog_url` 的 Markdown 链接：中文回答用「NEU 官方课程目录」，英文回答用「NEU course catalog」；这个链接不得用于别的页面；再用一句白话说明这些内容来自目录的存档副本，不是实时核对。
     - 引文本身没有写出来的数值（例如每周小时数、难度分）是抽取时估计的，要这样说，不能说成「评价里报告的」。
     - `recorded_sources` 只是抽取步骤自报用过的来源类型，不核实任何字段，也不支撑学分、学期、先修这类目录事实。
     - 只允许写 `catalog_url`；不写内部 ID、哈希、字段名、提示码；学生可以在课程详情面板里看到记录来源；「培养方案」页没有 URL，不加链接。
   - 这些规则的来历：
     - 「这个链接不得用于别的页面」和「培养方案页不加链接」来自第一次真实模型试跑：第一版 4.2 把「Programs 页面」链接到了目录 URL。
     - 「学生可以在课程详情面板里看到记录来源」是第 1 轮审查后改的。原来写的是「界面会在回答下方显示」，不对：回答下方的卡片不列来源。
     - 按语言给链接标签、存档副本那句、估计值那条，来自第 1 轮审查后的真实模型复核（见验证记录）。
2. **来源类型**：`rag.answer_evidence.source_kind()` 按 ID 前缀把来源归到 `rmp_review` / `reddit` / `syllabus` / `synthetic` / `catalog_derived` 几类，未知前缀一律归为 `other`；提示词和界面各自给出英文、中文标签。
3. **详情面板**（`app/answer_evidence_view.py`）：
   - 快照只显示摘要前 12 位，完整 ID 放在悬停提示里；整个 ID 不是 `catalog:` 加 64 位小写十六进制时显示「格式异常」，不回显。说明文字和悬停提示都会渲染 Markdown，旧代码会原样印出任意 ID。
   - 导入、抓取时间显示到分钟（`_when()`）：带时区的转成 UTC 并标「UTC」，不带时区的按原样显示、不标时区。
   - 记录来源改成按类型汇总（例如「RateMyProfessors 教师评价 50 条」），重复的 ID 只算一次；原始 ID（同样去重）直接写进「来源 ID（N）」折叠区本身；每条引文标出来源类型（`render_field_evidence()`）。
4. **回答链接白名单**（`answer_markdown()`，见 `docs/answer-grounding.md`；能挡住普通情况，有已知缺口，见下面「已知、未处理」1–3）：
   - 只有官方目录院系页链接可点，判断用与快照 URL 校验同一个正则（`schemas.answer_evidence.OFFICIAL_CATALOG_URL`）。
   - 其余行内链接去掉目标；图片改为链接；`]:` 转义，引用式定义失效；其余自动链接和裸 URL 去掉协议头。
   - 反复处理到文本不再变化，防止拆掉一个结构后两边拼成新链接。
   - 历史消息（`_render_message_text`，只处理助手文本）和流式输出（`render_streamed_answer`，每次对已到达的全文过滤，取代 `st.write_stream`）都经过过滤；聊天历史里存的仍是原文。

### 修改文件

| 文件 | 修改 |
|---|---|
| `llm/prompts/chat_v4.py` | 4.2：去掉 ID 的投影、`recorded_sources` 只列类型、来源类型标签（RMP 写明按姓名匹配、可能是别的课）、引用规则（链接标签按语言、存档副本说明、估计值不说成评价报告） |
| `rag/answer_evidence.py` | `SOURCE_KIND_PREFIXES`、`source_kind()` |
| `schemas/answer_evidence.py` | 官方目录 URL 正则提成 `OFFICIAL_CATALOG_URL`（快照校验行为不变） |
| `app/answer_evidence_view.py` | 中文来源标签、`source_summary()`（去重）、`snapshot_digest()`、`_when()`、短快照与折叠的来源 ID（去重）、`render_field_evidence()` 的来源类型、`answer_markdown()`、`render_streamed_answer()` |
| `app/streamlit_app.py` | 历史与流式回答都经过过滤（`_render_message_text`、`render_streamed_answer`）；文档串同步 |
| `app/api_client.py`、`api/routes/chat.py`、`llm/gemini_client.py`、`README.md`、`README.en.md`、`docs/streamlit_ws_troubleshooting.md`、`Dockerfile` | 只改文档串、说明和注释：流式渲染不再走 `st.write_stream` |
| `tests/test_chat_v4_prompt.py`、`tests/test_answer_grounding.py` | 快照有描述、无描述两种情况下 ID 都不进提示词（ID 去掉前缀后的部分也不能出现），但 meta 保留；投影每一层的键集合（记录、证据、目录、每条引文）；`recorded_sources` 只有类型（8 个 ID，其中 1 个重复）；规则措辞（先归一化空白；含按语言的链接标签、存档副本、估计值；「回答下方」一类的旧说法不得再出现）；标签表覆盖全部来源类型 |
| `tests/test_answer_evidence_view.py` | 短快照与异常 ID 不回显（含合法摘要前后多出字符）；时间显示；来源汇总与去重；ID 只在折叠区里（替身的折叠区改成独立的 surface）；标签表；28 个链接白名单用例（每个都验证处理两次结果不变）；流式每次渲染都已过滤；历史只过滤助手文本；用 AppTest 跑真实的 `render()`（实时回答经过 `render_streamed_answer`，历史存原文，从历史渲染的每一次都是过滤后的文字，学生自己的文字原样显示），取代原来只查源码字符串的检查 |
| `docs/answer-grounding.md`、本文件 | 契约与过滤说明；记录 12 |

### 验证记录

- 全量回归：`2751 passed, 5 warnings`，0 失败（11 之后为 2697；本批审查前新增 47 项、当时 2744，第 1 轮审查后又补 7 项）；5 个警告与之前相同。第 2 轮之后的最终版本又跑了一次，仍是 2751 passed：第 2 轮只改了已有测试，没有新增。
- 相关的 7 个测试文件（`pytest -q tests/test_chat_v4_prompt.py tests/test_answer_grounding.py tests/test_answer_evidence_view.py tests/test_streamlit_app.py tests/test_answer_feedback_view.py tests/test_feedback_release_gate.py tests/test_request_admission.py`）：审查前 266 passed，审查后 273 passed。之前写的「目标测试 186 passed」没有记下是哪几个文件，无法核对，作废。
- **真实 Gemini 对比（第 1 轮审查前的 4.2）**：设置与线上 /chat 相同（gemini-2.5-flash、temperature 0.2、16384 tokens、默认思考）。证据取自线上 `GET /course/{id}`（只读，不进查询日志），5 个问题（中英文、alias/hybrid、带 `program_schedule_unverified` 提示），同一份证据分别用 4.1 和 4.2 生成提示词。
  - 4.1：5 条回答都有内部 ID，合计 8 个 64 位快照 ID、1 个 base64 评价 ID。
  - 4.2 第一版：0 个 ID，但有 1 条把「Programs页面」链接到目录 URL。改规则后再跑 5 题 × 2 次：10 条回答 0 个内部 ID，没有错配链接，培养方案页只提文字、不加链接。
  - 「难度数值不一致」「先修 AND/OR 未知」「抓取日期未知」「不是官方第一学期安排」这些说明都还在；回答大多更短。
  - 中文回答的链接标签有 5/8 仍是英文「NEU course catalog」，可以接受。
- **真实 Gemini 复核（第 1 轮审查后、第 2 轮修改前的 4.2）**：设置同上（`generate_text_stream` 的默认参数），证据只用线上 `GET /course`（Tailscale 直连，带 `X-Eval-Run: prompt42-check-20261005`）。5 门课里只有 CS 5800 同时有 RMP 和目录快照。5 个问题 × 2 次，另用 4.1 跑 5 次对照，共 15 次调用。
  - 内部 ID：4.2 是 0/10；4.1 对照 4/5 泄露，说明检测器本身能抓到。
  - 链接：9 个，全部指向本课自己的目录页；没有错误目标，没有链到培养方案，也没有字面写 `catalog_url`。
  - 评价条数：0/10。
  - RMP 归属：8/8 归给任课老师，但 0/8 提到评价可能是关于别的课。
  - 看起来像回退的一处：7 条引用了目录的回答，没有一条说明「存档副本、抓取日期未知、不是实时核对」；4.1 对照 4 条里有 2 条说了。
  - 另外：中文回答的链接标签仍是英文；有 2 处把抽取时估计的数字说成评价里报告的（4.1 也一样）；库里 CS 5200 的 `primary_name` 是一句描述，被当成课程名打了出来（数据问题）。
  - 第 2 轮修改（按语言的链接标签、存档副本那句、估计值那条、RMP 示例带上提醒）就是针对这几条，改后的复核见下一条。
- **真实 Gemini 复核（最终的 4.2）**：工作区 `chat_v4.py` 的 SHA-256 与复核时记录的一致（`32a7183b…`）。同样 5 题 × 2 次、同样的证据和设置，共 10 次调用。
  - 内部 ID：0/10。
  - 链接：都指向本课目录页；中文回答 6/6 用「NEU 官方课程目录」，英文用「NEU course catalog」。
  - 评价条数：0/10。
  - 「存档副本、不是实时核对」：引用了目录的 8 条全都说了（上一轮 0/7）。
  - RMP「可能是关于别的课」：用到评价的 8 条里 6 条说了（上一轮 0/8）。
  - 先修「且/或」未知 2/2；「不是官方第一学期安排」2/2，指向侧边栏的培养方案页、不加链接。
  - 估计值：大多写成「估计/推断」，有的还分开写了「评论里是 5.0/5、抽取的估计是 4.0」。只有 CS 5200 的 2 条英文回答写成「reviews reported an estimated 4.0」，还没提和引文的冲突。
  - 新问题：多门课的回答会对每门课重复一次存档副本那句（最多 3 次）；个别回答直接把「与教师姓名匹配」写进句子，读起来别扭。见「已知、未处理」14。
- **真实渲染器检查**（Streamlit 1.57.0，本地临时页面）：34 个构造的 Markdown 用例。原文渲染后有 32 个产生可点的站外链接或图片（含 `javascript:`、协议相对地址、嵌套方括号、引用式定义，以及目标在下一行的定义）；过滤后只剩官方目录链接和按设计保留的 `mailto:`。这个结论只针对这 34 个用例，之后在真实渲染器上又确认了 3 类问题，见「已知、未处理」。另外，原文里裸写的目录 URL 会把句尾的「。」「）」并进链接、导致链接打不开，过滤后是准确的链接。
- **变异检查**：每个变异体在 /tmp 下的独立仓库副本里并行跑（副本没有 `.env`，和 CI 一样注入占位 `GEMINI_API_KEY`），真实工作区从不改动。
  - 审查前 36/36 被拦下。覆盖：来源类型判断；提示词投影里的三处 ID 与类型标签；版本号与 4 条规则；白名单的完整匹配（行内、裸 URL、自动链接、http、放宽的正则）；过滤的每一步（图片、反复处理、引用定义、句尾标点、目标、大小写、自动链接、裸 URL、NUL、`www.`）；流式渲染与返回值；历史只过滤助手；实时路径退回 `write_stream`；快照 ID 校验、悬停提示、完整摘要；来源汇总、折叠、引文的来源类型。
  - 但第 1 轮的测试质量审查者另做了 19 个变异体（含 2 个对照），17 个探针存活：历史渲染退回原样、实时路径绕过过滤、历史里存了过滤后的文字、快照 ID 只匹配开头、无描述快照的 ID 进提示词、来源 ID 打在折叠区外、标签互换、`catalog` 前缀放宽、条数截断、时间不转时区或改格式、规则删掉一句或加回旧说法。也就是说，上面列的「历史只过滤助手」「快照 ID 校验」「折叠」等，当时只钉住了单个函数，没有钉住接线和边界。
  - 补测试后用 27 个变异体复核：覆盖上面这些类别，加上第 1 轮之后的新代码（去重、标签、条数字段、规则句、无时区时间、悬停提示、学生文字、流式返回值），其中 1 个是对照。27/27 被拦下；未改动的副本基线全部通过。
  - 第 2 轮之后的提示词修改再做 12 个变异体：存档副本那句、估计值规则、两个提示词标签和一个界面标签改回旧版、示例去掉提醒、`recorded_sources` 句改回旧版、引文多一个带去前缀 ID 的键、记录多一个键、「below the answer」说法、链接标签规则改回旧版，外加 1 个对照。12/12 被拦下。
- ruff 0.5.0（F/E9/B，`--isolated`）：11 个改动的 `.py` 文件在 HEAD 和工作区都是 0 条。

### 审查

- **第 1 轮：2 路只读审查**。一路看语义与接线，一路看测试质量与文档。两路都不派生子 agent、不找过滤器的新绕过、报告里不引用攻击串。没有 CRITICAL。
  - 语义：1 中、9 低。中＝`recorded_sources` 的条数会误导模型（见「已实现」1）。低：规则说来源显示在回答下方（不对）；`course_id` 和 409 澄清文字仍会进提示词；示例链接把字段名当链接目标；流式不再补全未闭合的 Markdown；过滤器对正常写法的副作用；两张标签表要手动同步；折叠区的写法依赖传进来的是模块本身；文档串还写着 `st.write_stream`；详情面板里的抽取字段按 Markdown 渲染、不经过滤（本批之前就有）。
  - 测试与文档：1 高、4 中，其余低。高＝历史渲染这一步没有任何测试：把 `render()` 里的调用改回原样，217 项全过。中：实时路径只查源码字符串；快照 ID 整串匹配没钉住；无描述快照的 ID 没测；折叠没钉住。低：标签只钉住一部分；条数钉得弱；时间显示；规则措辞的测试；文档里几处不准确（「目标测试 186」无从核对、`answer-grounding.md` 的说法、修改文件表、变异总结）；10 个文件以外还写着 `st.write_stream`。都用变异或读代码核实过。
  - 处理：高、中和大部分低项都已改（见「已实现」「修改文件」和上面的变异复核）；没改的写进下面「已知、未处理」6–12。
- **第 2 轮：1 路只读审查**，只看第 1 轮之后的改动：没有 CRITICAL、HIGH、MEDIUM，8 条低。
  - 都已处理：
    - RMP 标签不该断言「就是这门课的老师」（按姓名取第一个匹配）；
    - 示例丢了「可能是别的课」这句提醒；
    - `recorded_sources` 那句说过头；
    - 「旧」目录派生文本的「旧」是时间断言；
    - 键集合只钉了两层，ID 去前缀后的部分没查；
    - 过期说法只禁了一种原话；
    - README 两处写法不一致、Dockerfile 注释的理由；
    - AppTest 测试的说明写过头（AppTest 会把实时那遍和紧接着的重跑合并进一棵树）。
  - 前 4 条改的是提示词，见「已实现」1。

### 已知、未处理

10-05 深夜在真实渲染器（Streamlit 1.57.0）上又确认了白名单的 3 类问题（下面 1–3，只按类别记录，不写具体构造）。用户选择先按现状提交、以后单独处理。所以这个白名单能挡住模型平常会写出的普通链接、图片和裸网址，但不能当安全边界用。要利用 2、3，需要有人把文字写进会被检索到的第三方内容（例如评价），模型还得照着原样输出；线上 4.1 完全没有过滤。

1. **耗时是平方级**：「反复处理到不再变化」的循环每轮只拆一层，层层嵌套的长输入要跑很多轮（约 4.8 万字符的构造输入单次约 3.2 秒，长度翻倍耗时约 ×4）；匹配链接目标的正则里有三个相邻的空白量词，对很长的空白串单遍就是平方级；流式输出每到一块又对已到达的全文重跑一次。正常回答只有一两千字符，没有实测到卡顿；回答长度受输出上限（16384 tokens）约束，但这个量级的输入在上限之内。
2. **解码后才识别的裸网址**：渲染器（remark-gfm）识别裸网址时，看的是已经解码过反斜杠转义和字符实体的文字；过滤器检查的是解码前的原文。用实体或反斜杠转义写出网址的一部分，过滤后仍可能显示成可点链接（真实渲染器上 7 个探针中 6 个）。
3. **`:help[…]` 指令把标签再渲染一次**：Streamlit 的 `:help[…]` 文本指令会把标签解码后的文字再按 Markdown 渲染一次，放进悬停提示框；过滤器放行的、整段转义过的链接写法，在提示框里会变成可点链接（悬停实测）。
4. 回答里的代码片段中的 URL 也会被去掉协议头（有意不去猜代码边界）；邮箱地址仍可能显示成邮件链接。
5. 中文回答的链接标签有时是英文。
6. 课程记录里的 `course_id`（例如 `neu-cs-5800`）仍在提示词里。409 澄清文字（含方案 ID 列表）作为助手消息存进历史，下一轮会经 `_recent_history` 进提示词。这两处都是本批之前就有的。
7. 规则里的示例链接写成 `[NEU 官方课程目录](catalog_url)`。模型如果照抄字段名，过滤后只剩方括号里的标签、没有链接。真实试跑 10 次没有出现；为了不动已经验证过的写法，没改。
8. 流式输出不再补全未闭合的 Markdown（`st.write_stream` 会补），输出过程中会短暂看到 `**` 或半截网址，最终显示和历史一致。这是有意的：补全会把半截链接变成可点链接。
9. 过滤器对正常写法也有副作用：
   - 裸写的目录 URL 两侧套了粗体或斜体记号时，记号会被并进 URL，链接失效；
   - 目录 URL 带页内锚点时链接失效；
   - 反引号里的目录 URL 会多出尖括号；
   - 代码里的 `]:` 会显示出反斜杠。

   规则要求的 `[标签](catalog_url)` 写法不受影响。以后的单遍实现会一起处理。
10. 引文去掉 `source_id` 之后，模型分不出几条引文是不是来自同一条评价，可能把一条评价说成「多位学生」。
11. 课程详情面板里的抽取字段（教师、考核构成、职业方向、AI 政策等）仍按 Markdown 直接渲染、不经过滤（本批之前就有）。这些字段来自离线抽取，源头里有第三方评价，和回答文本是同一类风险，留给以后的单遍实现一起处理。
12. 请求失败（例如 409、429）时，实时界面直接显示服务端的说明文字，从历史重新渲染时才经过过滤。这段文字来自自家 API，而且随后马上会被重跑后的历史显示替换，无害。
13. 数据问题：线上库里 CS 5200 的 `primary_name` 是一句描述（"Introduces relational database management systems…"），回答会把它当课程名写出来。不是提示词的问题，要在数据侧修。
14. 最终 4.2 的真实模型复核里还看到几处措辞问题，都不算错，没有再改提示词，免得又要重新复核：
    - 多门课的回答会对每门课重复一次存档副本那句。以后可以改成「每个回答说一次」。
    - CS 5200 的 2 条英文回答写成「reviews reported an estimated 4.0」，也没提评分与引文冲突（这是 4.1 就有的规则，不是本批新加的）。
    - 个别回答把「与教师姓名匹配」直接写进句子。
    - 回答会写出任课老师的姓名。姓名来自课程记录，4.2 之前也会写，详情面板本来就显示。

以后的处理方向（设计已定，草稿没有入库、也没有运行）：改成单遍、线性的处理。先把官方目录链接换成占位符；其余文字里的反斜杠全部翻倍，网址开头插入不可见、不断行的连接字符，再一次性给渲染器会解释的几种记号（实体、HTML 开头、链接和图片的开头、公式、指令）前面加反斜杠；最后还原占位符。只插字符、不删字符，渲染出的文字就是检查过的文字，1–3 一起解决。代价是模型写的反斜杠、公式、实体和颜色指令会原样显示，其他链接显示成 Markdown 原文。验证打算用 CommonMark 解析器（markdown-it-py，已在 uv.lock）当判定器，再加线性耗时测试。

### 发布状态

- 用户 10-05 深夜选择按现状提交（方案 2）：上面 1–3 留到以后单独的一批。
- 第 2 轮之后的提示词修改 10-05 深夜一度停在中途（用户叫停），10-06 补完：全量 2751 passed、12 个变异 12/12、最终版的真实模型复核（见验证记录）。随 PR 提交。
- 提示词在服务端，合并后要等下次部署才生效（部署前先 `chown` NAS 项目目录）。在那之前，线上回答仍是 4.1 的写法。

## 13 — 学生端界面、真实回答评测与 4.3、CS 5200 名称、回答过滤单遍重写（2026-10-06）

### 范围与原因

- 用户 10-06 选了 4 项，按顺序在分支 `feat/student-facing-polish`（从 main `78b1cf1` 拉出）上做，攒成一个 PR：前端打磨；提示词小修和评测脚本；CS 5200 的名称；回答过滤器单遍重写（12「已知、未处理」1–3）。
- 第 4 项之后，工作区里出现一份 10-06 的检阅记录（`docs/optimization-roadmap-2026-10-06.md`，未跟踪、不在本批提交里）。其中 FIX-02、FIX-03 是本分支自己新写的评测代码的问题，核实成立后一起修了（下面第 5 部分）。FIX-01（聊天错误把异常原文发给客户端）是之前就有的，不在本分支范围，没动。

### 已实现

1. **学生端界面**（`9993eed`）。起因：10-05 的前端评估发现课程详情被来源说明淹没，首页文案是开发者口吻，手机上输入框在约 2.5 屏以下（375×812 实测 y=2009 px，在聊天列末尾内联显示）。
   - `st.chat_input` 改在页面主体里调用，Streamlit 会把它固定在窗口底部（在列里调用时是内联的）。隐私说明和项目选择移到聊天列顶部，仍在输入框之前（发布门槛的 AST 测试要求这个顺序）。
   - 回答第一个问题时不再渲染落地内容；Co-op 页不重复游客横幅。
   - 课程详情移到 `app/course_detail_view.py`：学生关心的在上（描述及其来源、一行提示、评价里的估计、先修、考核/主题/技能/职业方向/老师、项目匹配、AI 政策），完整来源、缺失字段和引文收进一个「来源与说明」折叠区。抽取字段（老师、考核名称、职业方向、AI 政策）用转义过的单行 HTML 显示（`plain_text_html()` / `labelled_line_html()`；markdown-it 判定每行都是 html_block），不再按 Markdown 渲染。这处理了 12「已知、未处理」11。
   - 回答下方的卡片把重要提示合成一行（`SHORT_WARNING_LABELS`、`notice_line()`），不再每条一个说明。
   - 先修视图：解析出的规则在前，长说明、学分证据、描述关键词和来源收进「先修的来源与说明」，同年份培养方案上下文单独折叠；说明文字一条没删。
   - 首页、隐私说明、项目选择、Co-op 页改成学生口吻，06C-1 的事实都保留（测试钉住「不点击」「不会自动删除」等）；查询日志说明不再提一个界面上没有的开关；Co-op 投稿按纯文本显示。
2. **真实回答评测与提示词 4.3**（`ae9b226`）。10-05 的真实模型复核是仓库外的一次性脚本，现在做成一条命令。
   - `eval/answer_checks.py`：只看回答和提示词提供了什么的纯函数。硬检查：内部 ID/字段名/提示码、指向本课目录页以外的链接、多于一条的评价条数、评价没归给老师。给人看的信号：缺少的说明（存档副本、没有目录、且/或、培养方案）、估计值说成评价报告、链接标签语言、重复的存档副本句。修了 agent 版的一个检测错误："professor" 会匹配到 "RateMyProfessors" 里面，任何提到 RMP 的回答都被当成归给了老师。
   - `scripts/eval_answers_live.py`：证据只用线上 `GET /course/{id}`（带 `X-Eval-Run`），提示词按 `api/routes/chat.py` 的方式构造，回答用 `/chat` 同一个 `generate_text_stream` 和默认参数；调用有上限，错误里的密钥会被遮掉；写 `results.json`、每个回答一个文件和 `summary.md`；`--dry-run` 只生成提示词，`--rescore` 重评已保存的回答。
   - 4.3（4.2 从未部署）：只有用到目录描述时才说一次存档副本那句，每个回答一次（4.2 是每门课一次；4.3 初稿连没有目录的课也说）；没有目录的课要说明；抽取的数字旁边写「估计」，不能写成评价报告的；数值冲突时给出两个数并说要核实。处理了 12「已知、未处理」14 的前两条。
3. **CS 5200 名称**（`a9608ba`）。线上库里 CS 5200 的名称是它自己描述的第一句，大概是 2026-06 之前的富化把整段模型输出写回造成的；`sync_catalog_sources.py` 只在名称与目录标题一致时才挂快照，所以 CS 5200 一直没有快照，回答把那句话当成课程名（12「已知、未处理」13）。
   - `scripts/repair_course_names.py`（新增）：只读报告名称与存档目录标题不一致的课程；`--commit` 只修「像一句话结尾、并且原样出现在这门课自己的描述或 raw_text 里」的名称，其他不一致只列出、不改。一个事务、显式的库和存档、不联网，库不存在时不创建。本地开发库报出 CS 5200（可修）和 AAI 6600（其他不一致：存的是 syllabus seed 的标题，目录是 "Applied Artificial Intelligence"，等用户定）。
   - `CourseRepository.rename()`：改名称列和 Course JSON，**不改 status**。这是「内容改了就设 pending」的唯一有意例外：两个索引都不读名称（FAISS 只嵌 raw_text，BM25 用 raw_text + search_expansion）；设成 pending 会让这门课从检索里消失，而 `rebuild_faiss.py --incremental --status pending` 还会把其他课全部删出索引（目标集只剩 pending）。
   - 富化合并的测试里让模型把描述句当名称返回，断言目录名称保留。生产步骤写在 `docs/answer-grounding.md`。
4. **回答过滤单遍重写**（`app/answer_evidence_view.py`；取代 12 的白名单，处理 12「已知、未处理」1–3）。一遍线性处理；除了保留的目录链接（还原成 `[标签](URL)` / `<URL>`，去掉标题和 URL 两边的尖括号），只插入字符：
   - 官方目录院系页链接（`[标签](URL)`、`<URL>`、裸 URL，允许页内锚点）先换成占位符；标签同样转义；标签不能跨方括号。
   - 其余文字的反斜杠全部翻倍，模型自己写的转义原样显示，不能把网址的一部分藏起来躲过后面的步骤或渲染器的解码。
   - 每个 `http(s)://`、`www.`（不分大小写）的首字母后插一个 word joiner（U+2060：不可见、不产生换行点），渲染器的裸网址识别找不到它们。代码围栏后面紧跟的 `math` 信息串也在 `m` 后插一个：审查发现，回答里只要还有一对 `$…$`（转义过的也算，Streamlit 只用正则看原文决定要不要加载 KaTeX），Streamlit 就会把 ```` ```math ```` 代码块渲染成公式。
   - 在会开启其他结构的字符前加反斜杠：实体（`&#`、`&` 加字母）、HTML/自动链接（`<` 加字母或 `/!?`）、链接目标与引用式定义/脚注（`](`、`]:`）、图片（`![`，以及保留的目录链接前的 `!`）、公式（`$`）、指令/短代码（`:` 后面跟名字）。名字前的 `:` 后面再插一个 word joiner：真实渲染器检查发现，Streamlit 在解码后的文字里把 `:smile:`、`:material/…:`、`:streamlit:` 这类短代码换成 emoji、图标或它的 logo 图片（内嵌的 data URI SVG，不发请求），那时反斜杠已经没了。「名字」是除 ASCII 空白和标点以外的任何字符；这个类是逐个写出来的，因为 Python 的 `\s` 还包括 U+001C–U+001F、U+0085，渲染器不把它们当空白（审查发现）。
   - 还原占位符。模型写的两个占位符私用区字符（U+E000/U+E001）先换成 U+FFFD，伪造不了占位符。
   - 每个开启符都被转义，渲染器显示的就是检查过的文字：解码转义或实体、把指令标签再渲染一次，都产生不了链接。
   - 流式输出（`render_streamed_answer`）最多每 0.1 秒渲染一次已到达全文的过滤结果（时钟可注入），结尾再渲染一次，流中途出错时也一样（`finally`）。以前每个 token 都对全文重跑一次，是平方级的。
5. **评测脚本的运行状态与按句判断**（10-06 检阅记录的 FIX-02、FIX-03，核实成立）。
   - 原来退出码只看硬失败：5 次调用全部出错、0 条回答被检查，仍然返回 0，`--rescore` 也是 0。现在每次运行记录 `planned_calls` 和状态：`complete`（计划的每次调用都有回答且检查过）、`incomplete`（有调用失败、调用上限提前停止，或没有回答可检查）、`dry run`。退出码：0 完整且没有硬失败（或空跑），1 有硬失败（优先于不完整），2 准备阶段、参数或输入出错，3 不完整。`--rescore` 保留原来那次运行的错误；没有 `planned_calls` 的旧报告把实际调用次数当作计划。`summary.md` 的标题行写出状态。
   - 审查后：`--questions` 先校验形状（非空列表、必需的键、lang/route 取值、非空的 course_ids）；第一次调用模型之前先为全部问题构造提示词和上下文（`prepare()`），坏数据不会让运行在花了钱之后才失败；`--runs`、`--max-calls` 至少为 1；API 不可达或返回非 200、返回的不是 JSON 或不是课程、问题文件或 `--rescore` 文件缺失或格式不对，都是 2（原来有几种会带着 traceback 以 1 退出，和「有硬失败」混在一起）。上下文和提示词一起存到 `prompts/<qid>.context.json`（空跑也存）。
   - 原来的分句不认英文句号，前一句的 "estimated" 会让后一句被说成评价报告的数值也算「估计」；RMP 归属看整篇回答，别处无关的 "professor" 也算归给了老师。现在用 `sentences()` 分句（英文句号后跟空白或结尾才分，4.0、U.S. 这种连续缩写和 e.g.、approx.、Dr. 里的点不算；单个大写字母后的句号算结束，"Part A." 不再把两句连起来），估计值和存档副本句都按句判断；`review_attribution()` 把连续的评价句算一段，每段自己要提到老师，或用他/她指代（其他、他们、他人不算），网站名本身（"Rate My Professors"）不算；**每一段**都要有「可能是别的课」的提示，在段内或紧接着的下一句。
   - 审查后的其他检查修正：评价条数不再把课程代码的数字（"CS 5800 students"）和隔着介词的短语（"3 options for students"）当条数；「评价方式」「评价标准」「成绩评价」「考核评价」是考核方式，不算引用评价；链接标签里的 "Programming" 不再被当成链到培养方案页；链接检测不分大小写（`HTTPS://`、`WWW.`），自动链接认任何协议；存档副本/抓取日期的说明只在回答真的链接了目录时才要求（4.3 只在用到目录描述时要求）；「没有目录描述」那句即使提到「副本」也不算重复的存档副本句。

6. **审查后的界面修正**（第 1 轮 2 路审查，见「审查」）：
   - 课程名、主题、技能、方案名进 HTML 卡片时（`course_header_html`、`topic_pills_html`、`result_card_html`、`program_context_html`、入门推荐卡片）也去掉换行。原来只转义、保留换行，值里的一个空行就会结束 HTML 块，后面的内容按 Markdown 解析，包括链接；这些值也来自模型抽取（CS 5200 的名称就是模型写进去的）。第 1 部分说「抽取字段不再按 Markdown 渲染」，对这几处原来并不成立。（培养方案页的三个卡片也是这样，这一轮漏了，第 2 轮补上，见第 7 部分。）
   - 先修行（`prereq_label_md`）里的课程代码和名称按纯文字放进 Markdown：新的 `literal_markdown()` 把连续空白变成一个空格、转义每个 ASCII 标点、插入和回答一样的 word joiner。这处是本分支之前就有的。
   - 首页 Co-op 预览的锁提示按这一行实际有什么、这位访客还缺什么来写（原来对每个 1 级以上的行都说「面试细节和薪资」，1 级行没有薪资，已解锁的人也会看到；第 2 轮又发现 2 级的行不一定有面试细节，见第 7 部分）；游客说明补上「行业」（0 级也返回行业）；Co-op 页说明写明列表里也有整理的示例记录，不只是同学的分享。
   - `/chat` 的两条 409 提示改用新的选择框名称「你的项目（可选）」（原来写的是改名前的「对话项目」）；名称提成 `SELECTOR_LABEL`，测试保证两边一致。
   - 请求被拒（例如 409 要求先选项目）时，实时显示的说明也经过 `answer_markdown`，和从历史里重新渲染时一样。

7. **第 2 轮审查后的修正**（1 路只读审查，见「审查」）。前三条是本分支之前就有的代码，和第 6 部分是同一类问题：外面来的文字直接进了会渲染 Markdown 的地方。
   - 登录失败提示（OAuth 回调的 `error` 参数，网址谁都能写）原样放进 `st.warning`，后者会渲染 Markdown。现在只显示格式正确的错误码（1–64 个小写字母和 `_`，放在代码片段里），其他情况显示固定文字（`oauth_error_message()`）。
   - 分享链接（`?course=`、`?program=`）的引用原来只去掉反引号就放进代码片段，而代码片段跨不过空行或新的块，换行后面的部分会按 Markdown 渲染。现在先把连续空白折成一个空格。
   - 先修图（graphviz）的标签只转义了引号：graphviz 把紧挨引号的反斜杠当成转义的引号，所以以反斜杠结尾的标签会一直连到后面的源码；两个反斜杠算不算一对，不同版本不一样。现在反斜杠换成 `/`，不依赖版本。
   - 培养方案页的方案卡片、课程表头部和课程表行改用 `_one_line()`；方案说明（`program_view`）和方案范围那行里的 concentration（自由文本；`scope_label(plan, markdown=True)`，校区、目录年份、路径都是校验过的固定格式）用 `literal_markdown()`。
   - 证据面板里未知的字段名（证据片段的字段名是模型写的）、缺失字段和提示码按纯文字显示（`_label()`）；已知的仍显示中文标签。
   - Co-op 锁提示：`derive_visibility` 只要有薪资就是 2 级，不管有没有面试细节，所以只有 1 级的行才说「有面试细节」（首页预览和 Co-op 页；原来 2 级也说，薪资之外什么都没有的行，连已解锁的人也会看到）。「审核通过后解锁」改成「公开后解锁」：贡献在经验公开时才计入（同一公司、职位和学期至少有 2 位不同的同学分享），审核通过本身不解锁。改了横幅、游客说明、两处锁提示和 Co-op 说明。
   - 评测检查：以介词开头的连字符词（"in-depth"）不算介词，"12 in-depth reviews" 又算条数了；「无法…目录」不算「没有目录」，用这种说法的第二句存档副本句又算重复了；「没有目录描述」那句里的「存档」「副本」不算抓取日期/存档副本的说明；"Ph.D." 里的点不分句。
   - 评测脚本：`qid` 是输出文件名，只能是 1–64 个字母、数字、`_`、`-`，且不重复（原来带路径分隔符的能通过校验，花了前面几题的调用之后才在写文件时崩）；输出目录和全部提示词、上下文在第一次调用模型之前建好、写好（`save_prompts()`，在 `main` 的准备阶段里），`--out` 是个已有的文件之类建不了的情况是 2（原来是 traceback、退出码 1）；`--rescore` 先检查报告的形状（缺键、回答不是文字、上下文缺字段或多字段都是 2），打分放在 try 外面，检查代码本身出错时保留 traceback，不再被说成「准备阶段的错误」。
   - 名称修复工具只接住 `CourseNotFound`，不再接住整个 `LookupError`（那样会把 `KeyError`、`IndexError` 一类 bug 也当成普通失败）；事务照样回滚。
   - 真实渲染器检查脚本：标题里的指令、图标、彩色文字也计数，只有代码块里的跳过（原来标题里所有带样式的元素都被当成 Streamlit 自己的，标题里的指令会漏数）。
   - 代码说明：`literal_markdown()` 的文档串写明邮箱仍可能成邮件链接；代价列表补上复制出的 math 信息串也带 word joiner。

8. **第 3 轮审查后的修正**（1 路只读审查，只看第 7 部分的改动，见「审查」）：
   - Co-op 页每条记录旁的等级标签：2 级原来写「含面试细节和薪资」，和第 7 部分去掉的锁提示是同一个说法，而且所有人都看得到。现在写「含薪资区间」。
   - 第 7 部分的抓取日期判断有两处回退，改成：说日期或「不是实时」的措辞（新加了「没有记录…抓取日期」的语序）在哪句都算；单独的「存档」「副本」「snapshot」只在不是「没有目录描述」的分句里才算（按 `；`/`;` 分句，用 `；` 把两条说明连成一句时也认得出）。原来「目录的抓取日期没有记录」这类说明被一起排除了，报成缺少说明。存档副本句的计数用同样的分句。
   - 「无法在目录中找到」重新算作「没有目录」（第 7 部分只排除了「无法」，把这种说法也排除了），「无法实时核对目录」仍不算。
   - 评测脚本：`qid` 不分大小写也要唯一（在 Windows、WSL 的 `/mnt`、macOS 这类不分大小写的文件系统上，"Q1" 和 "q1" 会写到同一些文件）；`--rescore` 读到的报告除了键，还检查类型（文字、整数、布尔，上下文里的网址和键是文字列表、估计值是数字），有检查结果却没有回答的记录也算格式不对，这些都是 2，不再在后面带着 traceback 退出。
   - 分享链接对应多门课时，提示里的课程代码（来自数据库）也按纯文字放进去。
   - 真实渲染器检查脚本：标题里的背景色、闪烁效果、小字（`:small[]` 是带内联样式的 span）也计数。用一个临时的对照页（未过滤的指令放在标题和正文里）确认过：旧规则漏掉标题里的背景色、小字和图标，新规则 12 个都认出，普通标题、带代码的标题、段落和代码块都没有误报。
   - 测试：登录失败后网址参数要被清掉；「无论」那一例；Co-op 页说明的新句子；修复工具出 bug 时先真的写库再抛错，这样「事务回滚」才真的测到。
   - 先修图标签的说明改准：两个反斜杠算不算一对，不同版本的 graphviz 不一样，换成 `/` 不依赖版本（第 7 部分写成了「不当成一对」）。

### 修改文件

| 文件 | 修改 |
|---|---|
| `app/streamlit_app.py` | 输入框在主体里调用；隐私说明和项目选择在聊天列顶部；回答第一个问题时不渲染落地内容；Co-op 页不重复横幅；详情面板改调 `render_course_detail()`；被拒请求的实时说明经过过滤 |
| `app/course_detail_view.py`（新增） | 课程详情的顺序与「来源与说明」折叠区；抽取字段用转义的单行 HTML |
| `app/answer_evidence_view.py` | `SHORT_WARNING_LABELS`、`notice_line()`、`render_course_overview()`、`show_description`；单遍 `answer_markdown()`、`literal_markdown()`；节流的 `render_streamed_answer()`；未知字段名和代码按纯文字（`_label()`） |
| `app/streamlit_auth_ui.py`、`app/deep_links.py` | 登录失败提示只显示格式正确的错误码（`oauth_error_message()`）；分享链接的引用折成一行 |
| `app/program_view.py`、`rag/prereq_graph.py` | 培养方案页卡片留在一行、方案说明用纯文字；先修图标签里的反斜杠 |
| `app/ui_theme.py` | `plain_text_html()`、`labelled_line_html()`、`_one_line()` 及样式；横幅、匹配标记、空状态文案；先修行用纯文字 |
| `app/answer_feedback_view.py`、`app/program_plan_view.py`、`app/discover_view.py`、`app/coop_view.py`、`app/course_requisite_view.py` | 学生口吻的文案（事实不变）；先修说明折叠；Co-op 纯文本显示、行业与可见范围中文标签；锁提示按行、按等级保证的内容，「公开后解锁」；`SELECTOR_LABEL`；方案范围用纯文字 |
| `api/routes/chat.py` | 409 提示里的选择框名称 |
| `eval/answer_checks.py`（新增） | 回答检查；`sentences()`、`review_attribution()` |
| `scripts/eval_answers_live.py`（新增） | 真实回答评测命令；`run_status()`、`exit_code()`、`validate_questions()`、`prepare()`、`save_prompts()`、`load_report()`、参数校验 |
| `scripts/answer_render_check.py`、`scripts/answer_render_check.js`（新增） | 真实渲染器检查页和浏览器控制台脚本（只输出计数），见验证记录 |
| `llm/prompts/chat_v4.py` | 4.3 |
| `scripts/repair_course_names.py`（新增）、`db/repository.py` | 名称修复工具；`CourseRepository.rename()` |
| `tests/test_chat_layout.py`、`tests/test_course_detail_view.py`、`tests/test_discover_view.py`、`tests/ui_recorder.py`、`tests/test_answer_checks.py`、`tests/test_eval_answers_live.py`、`tests/test_repair_course_names.py`、`tests/test_program_view.py`（均新增） | 见下面验证记录 |
| `tests/test_answer_evidence_view.py` | 12 的 28 个白名单用例、「过滤两次不变」、旧的流式与历史用例换成：精确输出、markdown-it-py 判定、随机拼接的片段、纯文字原样显示、线性耗时、节流/拆开的链接/快流/中途出错的流式用例、中性写法的历史用例；AppTest 用例的输入换成中性写法 |
| `tests/test_answer_grounding.py`、`tests/test_chat_v4_prompt.py`、`tests/test_coop_view.py`、`tests/test_course_requisite_view.py`、`tests/test_feedback_release_gate.py`、`tests/test_program_plan_view.py`、`tests/test_program_plan_contract.py`、`tests/test_review_enrichment.py`、`tests/test_ui_theme.py`、`tests/test_streamlit_auth_ui.py`、`tests/test_deep_links.py`、`tests/test_prereq_graph.py` | 跟着文案、4.3、名称保护和两轮审查后的修正更新 |
| `docs/answer-grounding.md`、本文件 | 过滤、评测状态、名称修复的生产步骤；记录 13 |

### 验证记录

- 全量回归（都是 0 失败，5 个警告与之前相同）。各提交收集到的测试数：main 2751，`9993eed` 2766，`ae9b226` 2786，`a9608ba` 2798，`b65f94f` 2859，`4d979be` 2872（这几个由第 1 轮的审查者用 collect-only 逐个核对过）；第 1 轮审查后的两个修复提交 `eceaceb` 2889、`21d9872` 2908；第 2 轮审查后的 `d1d48f2` 2933、`4cf4061` 2947；第 3 轮审查后的 `7a3334d` 2951（这五个和对照的 `486a409` 都在 `git archive` 出来的独立副本里单独跑了全量，都是 0 失败）。之前写的「第 4 部分后 2855」是那时中途跑的一次，不对应任何提交，作废。
- **过滤器的判定**（`tests/test_answer_evidence_view.py`，全部中性写法，不含针对性的构造）：
  - 34 个精确输出用例（审查前 29 个；第 1 轮后加了 2 个 math 代码块、非 ASCII 指令名、U+001C 后的指令名，第 2 轮加了信息串前是 tab 的 math 代码块）：普通格式不变；目录链接（含锚点、尖括号、标题、标签转义）保留；其他链接、图片、自动链接、裸网址、定义、脚注、实体、HTML、公式、指令、短代码、math 代码块、反斜杠按原样显示；代价也钉住（代码里的转义和尖括号、邮件链接）。
  - markdown-it-py（CommonMark 加 GFM 表格和删除线，接受任何链接目标）当独立判定器：没有图片和原始 HTML；链接只有目录页（或邮件）；链接以外的可见文字里没有 `http(s)://`、`www.`，代码里只允许保留的目录网址。用在精确用例、按固定种子随机拼接的 6000 个 Markdown 片段组合、流式的每一次渲染上。
  - 审查发现这个判定器看不见 Streamlit 独有的语法：短代码、指令、公式、脚注它都不认识，引用式定义它会直接吞掉（不进 token）。所以只要精确用例表被重写，那 4 类转义就没有别的测试守着（审查者的 4 个变异体都只被精确用例拦下）。现在判定器另外检查：`env` 里没有引用式定义；没有信息串是 math 的代码块；解码后的文字里没有 Streamlit 短代码；源文本里每个 `$`、每个后面可能跟指令名的 `:` 都已转义。片段里也加上了代码围栏、`math`、几个短代码名和中文名字。
  - 不含格式字符的 6000 个随机组合：解析后的可见文字去掉 word joiner 等于原文。
  - 线性耗时：21 种重复单元各 20 万字符（约为最长回答的三倍；审查后加了两种代码围栏形状），每个 < 2 秒。审查后的代码在本机最慢的是全是 `$` 的输入：5 万 / 20 万 / 80 万字符约 8 / 33 / 140 ms（4 次测量；审查前是 6.6 / 28.6 / 115.5 ms），20 万字符离 2 秒的上限约 60 倍余量。
- **真实渲染器检查**（Streamlit 1.57.0，Claude 内置浏览器 Chromium 152）。检查页和控制台脚本已入库（`scripts/answer_render_check.py`、`.js`，用法见文档串），可以重跑，例如升级 Streamlit 之后。每个用例直接 `st.markdown(answer_markdown(...))`，脚本只输出计数。最终一次（10-07，第 2 轮修改之后；第 3 轮改了检查脚本后又跑了一次，结果相同）：851 个用例 = 34 个精确用例的输入 + 400 个随机片段组合（种子 7）+ 411 个纯文字（400 个种子 107 的组合，外加 11 个直接写出的短代码/指令/公式/箭头）+ 6 个 math 代码块。
  - 94 个链接：92 个目录页、1 个邮件、1 个 Streamlit 自己给标题加的页内锚点（`#…`，没有文字），其他 0。
  - 图片/嵌入 0、KaTeX 0；回答产生的指令、图标、提示框、彩色文字 0。排除的只有 Streamlit 自己的东西：代码高亮、代码块旁的复制按钮、标题里的普通 span 和锚点；指令、图标、彩色文字、背景色、闪烁效果、小字这几类在标题里也计数（第 2、3 轮改的，原来标题里所有带样式的元素都排除；第 3 轮用对照页确认新规则能认出标题和正文里的这些指令，见「已实现」8）。链接和代码以外的文字里没有网址开头；代码里只有保留的目录网址。
  - 411 个纯文字用例里 410 个显示的文字（去掉 word joiner）等于原文；剩下 1 个是 Streamlit 把 `->` 画成了箭头。
  - 这项检查找到过两处：第一次检查时 `:smile:`、`:material/home:`、`:streamlit:` 还会变成 emoji、图标和 logo 图片（于是加了「名字前的 `:` 后面插 word joiner」）；第 1 轮审查后加的 5 个 math 代码块里，修之前有 3 个（普通、引用里、列表里）渲染成了 KaTeX，修之后 0 个。第 2 轮加的「信息串前是 tab」那一例渲染成普通代码，代码块的语言类和空格那例一样是 `language-m`（渲染器跳过了 tab，word joiner 把语言名截在了 `m`），所以这一例确实测到了 tab 的情况。
- **真实模型复核（4.3）**：证据只用线上 `GET /course`（带 `X-Eval-Run`），5 题 × 2 次，设置与 /chat 相同，共 3 轮。最终 4.3：硬失败 0、估计值说成评价报告 0、用到 RMP 的 8 条全部提醒「可能是别的课」；1 条没说明 CS 5200 没有目录描述，1 条多说了一次存档副本句。这些数字是用 `ae9b226` 时的检查算的；第 5 部分的按句判断更严，没有重新算：那几轮的输出在 WSL 的 `/tmp` 里，WSL 10-06 15:22 重启后已经没了，重跑要新的模型调用，没做。
- **变异检查**（每个变异体在 /tmp 下由 `git archive HEAD` 加工作区改动组成的独立副本里并行跑，注入占位 `GEMINI_API_KEY`；先确认导入解析到副本、未改动的副本基线通过；真实工作区从不改动）：
  - 第 1 部分 25/25；第 2 部分 17/17；第 3 部分 9/9。
  - 第 4 部分 35 个：翻倍、word joiner、大小写、`www.`、每一种开启符（含只认字母的 `<`、只认 ASCII 的指令名、`!` 加占位符）、占位符私用区字符、标签转义、三种目录链接的保留、锚点、放宽成任意 https、标签允许方括号、标题、节流的每个分支（每块都渲染、第一块不渲染、没有最后一次、出错时没有最后一次、渲染原文）、历史不过滤/连学生的也过滤、实时路径退回 `st.write_stream`、换成别的不可见字符、所有冒号都转义、短代码冒号后不插 word joiner、名字那一项排到最后（`]:名字` 就拿不到 word joiner）。第一遍 32/33，「标签允许方括号」存活，补了一个精确用例（目录链接前面有一段链接形状的文字）后 33/33；加短代码处理后连同新的 2 个共 35/35。「插 word joiner 和插反斜杠换顺序」是等价变异，没算进去。
  - 第 5 部分 20/20：状态总是 complete、退出码忽略不完整、硬失败不优先、计划不乘 runs、去掉参数校验、计划等于已答数、没有空跑状态、summary 不写状态、不认英文句号、不认缩写、不认单个大写字母、归属看整篇、去掉代词、「其他」当代词、提醒在哪都算、提醒不认下一句、连续评价句不合并、一段归属就够、估计值看整篇、存档副本句看整篇。
  - 审查后一轮 42/42（12 个测试文件）：math 代码块不插 word joiner、名字类改回 Python `\s`、指令名只认 ASCII、`literal_markdown` 不转义、HTML 卡片保留换行、先修行用原文、预览锁提示不看已解锁、三处转义 HTML 行去掉 `unsafe_allow_html`、输入框改成 `chat_col.chat_input`、被拒请求实时不过滤、409 用旧名称、游客说明去掉行业、Co-op 说明只说同学分享；条数穿过介词、课程代码算条数、「评价方式」「成绩评价」算评价、网站名算老师、一段有提醒就够、Programming 算培养方案、裸网址分大小写、自动链接只认 http、没链接目录也要求抓取日期、无目录句算存档副本句、单个大写字母不分句、不校验问题文件、`main` 不先 `prepare()`、`--rescore` 的错误不接住、不存上下文、标题行不写状态、「他们」算一个人、去掉英文代词、approx 结束句子；修复工具不接住 `CourseNotFound`、只有句号算句末。
  - 另把过滤器的 6 个变异体（不插 word joiner、`]:` 不转义、`$` 不转义、指令不转义、短代码冒号后不插 word joiner、math 代码块）在**去掉精确用例**的情况下再跑一遍：6/6 被判定器那几组测试拦下。审查前这类变异体只被精确用例拦下。
  - 第 2 轮审查后 45/45（16 个测试文件）：
    - 界面：登录错误码原样回显、回调不用检查过的提示、错误码格式放宽；分享链接的引用不折行；方案卡片、课程表头部、课程表行保留换行；方案说明原样；方案范围不转义、`markdown=True` 不生效；`_label()` 退回原样，字段名、提示码、缺失字段各自绕过 `_label()`；2 级的行也说面试细节（首页预览、Co-op 页）；横幅、两处锁提示、游客说明写回「审核通过」；先修图保留反斜杠；math 信息串前不认 tab；先修行的代码、只有 ID 时原样；入门推荐卡片的代码不转义、去掉 `unsafe_allow_html`。
    - 评测：连字符词当介词、「无法」算「无」、「没有目录」那句算抓取日期说明、Ph.D. 分句、「考核评价」「评价标准」算评价、"!" 不分句；qid 不查格式、允许重复；建目录挪到准备阶段之后、提示词边调用边写；`--rescore` 的 try 包住打分、不查回答类型、上下文允许多余字段、不查报告的键；不查 lang、notices、course_id 元素；修复工具接住整个 `LookupError`。
    - 第一遍 44/44。全量回归随后有 2 个失败：`test_program_pathways.py` 用 AppTest 读说明文字的原文，整行转义后 `2026-2027` 成了 `2026\-2027`（显示不变）。于是改成只转义 concentration（`scope_label(plan, markdown=True)`），把这个测试文件加进变异检查的列表，重跑方案范围的 2 个变异体（含新加的一个）：2/2。
  - 第 3 轮审查后 14/14（同样 16 个测试文件）：Co-op 2 级标签写回「含面试细节和薪资」；说日期的措辞也只在不是「没有目录」的句子里算；去掉「没有记录…抓取日期」的语序；不按 `；` 分句；去掉「无法在目录中找到」；「无论」算「无」；qid 分大小写；`--rescore` 不查上下文的类型、允许有检查结果没有回答、不查报告的类型、布尔值算整数；分享链接对应多门课时第一门、其余几门的代码原样放进去；登录失败后不清网址参数。
- ruff 0.5.0（F/E9/B，`--isolated`）：本分支改动的 `.py` 文件在 main 和工作区都是 0 条。按仓库自己的 ruff 配置分别比较第 2 轮、第 3 轮前后：新增的只有代码库里本来就大量存在的两类提示（中文全角标点 RUF001–003、`# noqa: PLC0415` 被判为多余的 RUF100）；测试里两处 UP027 已改掉。

### 审查

- **第 1 轮：2 路只读审查**（语义与正确性 / 测试与文档）。都不派生子 agent、不改仓库、不调线上和模型，报告里不写构造输入。两路都没有 CRITICAL、HIGH，都没找到能让过滤后的回答在 Streamlit 1.57 里变成链接、图片或 HTML 的写法。
  - 语义（5 中、11 低）：
    - 中（都已修）：math 代码块会渲染成 KaTeX（「已实现」4）；课程名、主题、技能等进 HTML 卡片时保留换行，空行后的内容按 Markdown 解析（「已实现」6；先修行那处是本分支之前就有的）；`counts_fail` 把 "CS 5800 students" 一类当成评价条数；`rmp_fail` 把「评价方式」当成引用评价，把带空格的 "Rate My Professors" 当成老师；准备阶段的几种错误以 1 退出（「已实现」5）。
    - 低（已修）：Python 的 `\s` 比渲染器的空白宽；"Programming" 被当成链到培养方案页；两条说明的判断和 4.3 矛盾（没用目录也要求抓取日期说明，「没有目录描述」那句被算成重复的存档副本句）；一段有提醒就整篇算有；链接检测分大小写；单个大写字母后不分句；409 提示用的是改名前的选择框名称；几处说明的事实（游客也能看到行业、首页预览的锁提示、列表里也有示例记录）；`--dry-run` 不存上下文；修复工具的文档串与代码不符、`CourseNotFound` 没被接住。
    - 低（记录、未改）：流式节流没有尾沿渲染（「已知、未处理」2）；修复时存档条目只按课程代码对应、不再用它自己的描述核对身份（课程代码就是身份，接受）。
  - 测试与文档（5 中、15 低）：
    - 中（都已处理）：判定器看不见 Streamlit 独有的语法（已加检查，见验证记录）；没有测试检查转义 HTML 行的 `unsafe_allow_html=True`，三处去掉都不会失败（测试替身现在记录这个参数，详情面板、Co-op 列表、首页预览都断言了）；输入框固定的测试只查「不在 `with` 里」，改成 `chat_col.chat_input` 也会通过（现在还查调用对象是 `st`，AppTest 再查它落在 bottom 块而不是 main）；退出码 2 的说明只部分成立；修复工具测试的文档串还写着「留成 pending」。
    - 低（都已处理，除最后一条）：节流默认值、代词和缩写的例外、上下文标志只测了一个方向、「什么都没查」的保护、`main` 里的密钥遮盖、summary 里状态的位置、各提交的测试数（见验证记录）、「只插入字符」对保留的目录链接不成立、Streamlit 的排版替换不止箭头、math 代码块（同语义的中）、非 ASCII 指令名、真实渲染器检查无法复现（检查页已入库）、「说明文字一条没删」没钉住（先修说明的 6 条都加了断言）、修复工具的其他句末标点；多门课的同一数值仍合并判断（「已知、未处理」7）。
  - 新增和修改后的行为另做了一轮变异检查（见验证记录）。
- **第 2 轮：1 路只读审查**（只看第 1 轮的修改 `486a409..21d9872` 和文档；同样不派生子 agent、不改仓库、不联网）。0 CRITICAL、1 HIGH、4 MEDIUM、11 LOW，全部核对过代码、都成立，都已处理（「已实现」7）。仍没找到能让过滤后的回答变成链接、图片、KaTeX 或指令的写法。
  - 高：登录失败提示原样回显网址参数。中：分享链接的引用跨行；培养方案页卡片保留换行；证据面板的未知字段名；2 级的行不一定有面试细节。高和第一个中是本分支之前就有的代码。
  - 低：说明和方案范围的说明文字、先修图标签的反斜杠、「审核通过后」的说法、连字符介词、「无法」、「没有目录」那句满足了抓取日期说明、Ph.D. 分句、`--out` 和 qid、`--rescore` 的 try 范围、`LookupError` 太宽、渲染检查脚本漏数标题里的指令、几处文档；另有 6 处修复没被测试钉住（tab 的 math 代码块、先修行的代码和 ID、入门推荐卡片、问题文件的 lang/notices/course_id 元素、「考核评价」「评价标准」、"!" 分句），都补了测试。
  - 审查者没法检查的：真实渲染器（没有浏览器，由我跑了，见验证记录）、生产的 Co-op 数据（本地种子都是 0 级）。
- **第 3 轮：1 路只读审查**（只看第 7 部分的改动，`git diff 21d9872`）。0 CRITICAL、0 HIGH、1 MEDIUM、7 LOW，核对后都成立，都已处理（「已实现」8）。
  - 中：Co-op 页的等级标签仍说 2 级「含面试细节」。
  - 低：抓取日期判断的两处回退、「无法在目录中找到」、`--rescore` 只查键不查类型、qid 大小写、深链提示里的课程代码、检查脚本在标题里的覆盖、4 处测试钉不住（网址参数清除、「无论」、Co-op 说明、修复工具的回滚）。
  - 审查者没法检查的：graphviz 对两个反斜杠的处理（没有 `dot`；它认为新版会配对，所以改了说明的写法，见上）、真实渲染器、生产的 Co-op 数据。

### 已知、未处理

1. 过滤的代价（有意的）：模型写的反斜杠、实体、公式、`:red[...]` 这类指令和 `:smile:` 这类短代码原样显示；其他链接显示成 Markdown 原文，复制出的非目录网址、`:名字` 和代码围栏的 math 信息串带着不可见的 word joiner；代码里看得到插入的反斜杠，目录网址在代码里带尖括号；表格里的 `\|` 会变成分列；math 代码块显示成普通代码；Streamlit 的排版替换仍然生效（`->`、`<-`、`<->`、`--`、`>=`、`<=`、`~=` 会变成 → ← ↔ — ≥ ≤ ≈），以标点开头的少数 emoji 短代码（`:+1:`）仍会变成 emoji；邮箱地址仍可能显示成邮件链接。12「已知、未处理」4、9 由此更新：代码里的网址不再去掉协议头；目录 URL 两侧的粗体/斜体记号和页内锚点不再弄坏链接；反引号里的尖括号和代码里看得到的转义仍在。
2. 流式输出仍不补全未闭合的 Markdown（12「已知、未处理」8，有意）。节流没有尾沿渲染：上一次渲染后 0.1 秒内到的那几块，要等下一块到了或回答结束才显示，模型中途停顿时显示会落后那么久；结尾一定会补上。
3. 评测检查仍是启发式的，硬失败只是提示要有人读那条回答。按句判断会有误判，例如：前一句说「由某老师授课」、后一句只说「评价说讲得清楚」而不用代词，会被判成没有归属；人名里单独的首字母（"John A. Smith"）会把句子分开。存档副本/抓取日期的说明只在回答链接了目录时才要求，所以用了目录描述却没加链接的回答不会被提醒（第 2 轮审查指出，按 4.3 的写法接受）。「没有目录」的判断也会被「目录的抓取日期没有记录」这类句子满足（「目录……没有」），没说明哪门课没有目录也可能不被报出。
4. 4.3 的真实复核数字没有用第 5 部分的检查重算（见验证记录）。
5. AAI 6600 的名称（syllabus seed 标题 vs 目录 "Applied Artificial Intelligence"）等用户定；修复工具只列出、不改。
6. 10-06 检阅记录里的 FIX-01（聊天错误把异常原文发给客户端）和 OPT-01–06 不在本分支范围。
7. FIX-03 只做了分句和归属：「没写出来的估计值」仍按整个回答合并判断，不分课程和字段，多门课恰好有同一个数值时会互相影响（检阅记录里的「多课同数值」）。
8. 单元测试的判定器（markdown-it-py）只是近似 Streamlit 的渲染器；真实渲染器检查要手动跑（`scripts/answer_render_check.py`）。

### 发布状态

- 本分支的提交随一个 PR 提交，合并由用户点。最后一个代码提交 `7a3334d` 的全量：2951 passed、0 failed（main 2751）。
- 界面、过滤器和提示词 4.3 都要等下次部署才生效（部署前先 `chown` NAS 项目目录）。
- 生产数据没有动。下次部署时按 `docs/answer-grounding.md` 跑：`repair_course_names.py` 报告 → 核对 → `--commit` → `sync_catalog_sources.py`；不用重建索引、不用重启。

## 14 — 10-07 上线；聊天错误不再透出异常原文；AAI 6600 用目录名称（2026-10-07）

### 上线记录（main `4ae60a3` = PR #2–#5，2026-10-07 11:37 UTC 起）

- 部署前：NAS 约 37 小时前重启过，UGOS 又把项目目录改回 root:root（2569 个条目）。用户跑了 `sudo chown -R shenhaowei:docker /volume1/docker/neu-compass`，之后没有不属于 shenhaowei 的条目。
- 步骤和 10-04 相同，构建与切换分开，构建失败不会影响线上：
  1. 线上库一致性备份 `runtime-data/backups/prerelease-20261007-113628.db`（quick_check ok；courses 6469、users 2、coop_experiences 30、query_log 1499、course_catalog_sources 6467）。给运行中的镜像打回退标签 `neu-compass:rollback-20261007`（`57464a30d708`，即 10-04 的镜像）。
  2. 上传代码，排除规则同 `deploy.ps1`。打包出来的 221 个文件逐个在 NAS 上核对 sha256，全部一致；`.env` 的哈希相同，没有覆盖。
  3. 构建新镜像 `d8f97df9d1a4`，用时 41 秒。依赖与 10-04 的线上完全相同：openvino 2026.4.1、torch 2.12.0+cpu、transformers 4.57.6、optimum 2.2.0、optimum-intel 2.0.0。镜像里的提示词是 4.3。
  4. 切换后 API、UI 健康。只读探针：ready 6469/6469、Co-op 审核表可用、方案 2/4/2、政策 12 条、CS 5004 先修文档。日志里只有旧索引缺 manifest 的警告，和 10-04 一样。
- 评测：`eval_via_api`、同一测试集、带评测标记，116/116 完成。

  | 指标 | 10-07 | 10-04 |
  |---|---|---|
  | R@5 | 0.8647 | 0.8609 |
  | MRR | 0.9309 | 0.9362 |
  | alias / hybrid / 拒答 | 31 / 75 / 10 | 31 / 75 / 10 |
  | 服务端 p50 / p95 | 824 / 1127 ms | 872 / 1251 ms |

  逐题比，8 题的前 5 名内部换了位置：q012、q083 变好（q083 回到了 09-14 的结果），q013、q025 变差，另外 4 题分数不变。两次之间 /search 的检索代码没有改过（只动了 `rag/answer_evidence.py` 和 `rag/prereq_graph.py`），依赖也相同，所以记作运行之间的波动。/chat 检查：200、hybrid、带 `program_schedule_unverified` 提示、提示词 4.3。
- 课程名修复（13 第 3 部分）：生产库上的报告和本地开发库一致，只有 CS 5200 可修，AAI 6600 是「其他不一致」。`--commit` 修了 CS 5200 → `sync_catalog_sources.py` 预演 matched 6468、标题不一致 1、would_store 1 → 写入 1 份快照 → 重跑写入 0。线上 CS 5200 现在叫 "Database Management Systems"，`answer_evidence.catalog` 有了目录快照；AAI 6600 仍然没有。
- 公网 UI 只读冒烟（打开首页和 `?course=CS-5200`，没有提问）：新文案、底部固定的输入框、新的详情面板，CS 5200 显示目录描述和「存档副本」说明。
- 回退方式：把 `neu-compass:rollback-20261007` 重新标成 latest，再 `docker compose up -d`。名称修复只改了 `primary_name`，旧代码照样能读。

### 范围与原因

- 13 合并后，用户 10-07 让我对三件待定的事按推荐处理。定下来的是：FIX-01 作为这一批；AAI 6600 用目录名称；10-06 的检阅记录（`docs/optimization-roadmap-2026-10-06.md`）原样入库，和 FIX-01 的修复同时提交，因为仓库是公开的，记录里写着这个问题。
- FIX-01 核实成立：聊天流出错时，`GeminiError` 的消息原样进了 NDJSON 的 `error.detail`，同样的文字也写进了 `chat.stream_failed` 日志。这条消息是 `Gemini API call failed: <类型>: <上游异常原文>`，结构化输出失败时还带着最多 500 字的响应原文。其他异常发的是 `类型: 原文`，并用 `log.exception` 记了整个 traceback。
- 同类的还有两处，一起改了：`gemini_error_handler`（非流式接口的 502）回的是 `LLM upstream failure: <原文>`；HyDE 救援失败的 `rescue.failed` 日志记了 `str(e)[:200]`。

### 已实现

1. `llm/gemini_client.py`：
   - `GeminiError` 加了 `kind`，八个抛出点各自标上，默认是 `error`。可能的值：
     - `call_failed`：调用失败；
     - `invalid_response`：响应不符合 schema；
     - `stream_init_failed`：第一段文字之前的任何失败，不论是调用本身出错，还是在还没有 chunk 带文字时迭代出错。SDK 要到第一次迭代才发请求，所以真实环境里大多是后一种；
     - `stream_interrupted`：已经出过文字之后失败；
     - `empty_stream`、`empty_response`：没有生成任何文字。
   - 消息原文不变，跑富化脚本的人仍然看得到。
   - 新的 `error_log_fields(exc)`：只返回异常类型（`exc_type`）、`kind`、上游异常的类型（`cause_type`）、HTTP 状态码（`upstream_status`）和状态名（`upstream_reason`），从不包含消息。
     - 状态码取 google.genai 错误的 `.code`，或 httpx 风格的 `.response.status_code`，布尔值不算。
     - 状态名只认 `RESOURCE_EXHAUSTED` 这种全大写的写法。响应体不是 JSON 时，google.genai 在同一个属性里放的是 "Bad Gateway" 这类原因短语，这种不记。
     - 它自己从不抛异常：它在 except 块里运行，再出一个错会把聊天流截断。
2. `/chat` 流：
   - `error` 事件改成 `{"type": "error", "error_type": …, "detail": 固定的中文提示}`。`error_type` 有三类：
     - `upstream_error`：调用或流失败；
     - `no_answer`：模型没给出文字，即安全拦截或空回答，照原样再问多半没用，提示换个问法；
     - `internal_error`：其他错误。
   - `chat.stream_failed` 只记 `error_log_fields` 和已经发出的 token 数（`tokens_sent`），这样分得清「一个字都没出」和「中途断开」。
   - 意外错误改成 `log.error("chat.stream_unhandled", …)`，不再用 `log.exception`：渲染出来的 traceback 末尾就是消息。除了上面那些字段，还记 `frames`：最内 6 层的 `文件名:行号 函数名`，用 `error_frames()`，不读源码行，自己也从不抛异常。
   - 已经流出来的部分回答、最后的 `done`、出错时不发反馈凭证，这些都不变；UI 照旧把 `detail` 接在部分回答后面。
3. `gemini_error_handler`：502 的 detail 改成固定的英文，和 500 的写法一致；另记一条 `gemini_error` 日志（路径、方法、`error_log_fields`），日志里的 `request_id` 就是响应头的 `x-request-id`。
4. `rescue.failed`：只记 `error_log_fields`。GeminiError 以外的错误（数据库、reranker）另外记 `frames`。
5. `app/auth.py`：ID token 校验失败的 OAuthError 只写异常类型。google-auth 的消息可能引用 token 本身或 audience 的值，而这段文字既进 401 的 detail，也进 `auth.callback.rejected` 日志。
6. `scripts/repair_course_names.py` 新增 `--use-catalog-title CODE`（可重复），用于由人决定的改名：
   - 把点名的「其他不一致」也改成存档里的目录标题，报告里单列为 `named_repairs`。
   - 点名的代码不在存档里，在打开库之前就失败。在库里不是正好一门课，在写入之前失败，连句子那一类修复也不写。
   - 已经一致的算 matched，所以重跑不会改任何东西。
   - 脚本自己检查出的失败（`NameRepairError`：代码不在存档里、库里不是正好一门课、存档里同一代码有两个标题）会打印消息，里面只有课程代码和数量；其他错误仍只打印类型。
   - AAI 6600 存的是 syllabus seed 的 "Introduction to Artificial Intelligence"，目录标题是 "Applied Artificial Intelligence"。用目录标题有两个理由：目录是官方来源；回填要求名称和目录标题一致，改了之后这门课才挂得上目录快照。
7. 文档：
   - `docs/api_contract.md`：error 事件的新格式和三类 `error_type`，以及日志里记什么。
   - `docs/answer-grounding.md`：新选项、AAI 6600 的决定和生产步骤。
   - `docs/optimization-roadmap-2026-10-06.md`：原样入库。FIX-02、FIX-03、FIX-04 已在 13 里做了，FIX-01 是这一批；OPT-01–06 还没做。
8. 审查后的修正（见「审查」）。上面这些里，有几处是审查后才改成现在这样的。
   - 第 1 轮（2 路，中途叫停）：
     - 文字之前的失败都算 `stream_init_failed`；
     - `no_answer`；
     - `tokens_sent`、`upstream_reason`；
     - `error_log_fields` 从不抛异常，日志字段名用 `exc_type`（和全局处理器的 `unhandled_exception` 一致）；
     - rescue 的 `frames`；
     - OAuth 的校验消息；
     - 修复工具打印自己的错误消息。
   - 第 2 轮（1 路）：
     - 模块说明和 /docs 的接口说明补上 `no_answer`；
     - `no_answer` 的判断改用 `error_log_fields` 算好的 kind，原来直接读 `e.kind`，读出错时会在 except 块里再抛一次；
     - `chat.feedback_capture_failed` 的字段名也统一成 `exc_type`；
     - 没有任何文字时，提示前不再加空行（UI 存下的这一轮会作为历史发回给模型）；
     - 修复工具列出没找到的代码时用 `repr()`，多出来的空格或小写字母看得见。

### 修改文件

| 文件 | 修改 |
|---|---|
| `llm/gemini_client.py` | `GeminiError.kind`；`error_log_fields()` |
| `api/routes/chat.py` | 固定的 error 事件（`STREAM_ERROR_DETAIL`，三类）；日志只记安全字段、`tokens_sent` 和调用位置；模块和接口说明 |
| `api/exceptions.py`、`api/routes/common.py` | 502 的固定 detail 和 `gemini_error` 日志；`error_frames()`；`rescue.failed` |
| `app/auth.py` | ID token 校验失败只写类型 |
| `scripts/repair_course_names.py` | `--use-catalog-title`；`NameRepairError` |
| `app/streamlit_app.py` | 没有文字时错误提示前不加空行 |
| `tests/test_error_logging_pipeline.py`、`tests/test_chat_error_page.py`（均新增）、`tests/test_api_chat.py`、`tests/test_api_errors.py`、`tests/test_hyde_rescue.py`、`tests/test_gemini_client.py`、`tests/test_repair_course_names.py`、`tests/test_streamlit_app.py`、`tests/test_app_auth.py`、`tests/test_answer_feedback.py` | 见验证记录 |
| `docs/api_contract.md`、`docs/answer-grounding.md`、`docs/optimization-roadmap-2026-10-06.md`（入库）、本文件 | 见上 |

### 验证记录

- 测试里的上游文字是三段占位：像凭证的值、网址、请求正文。断言它们既不在响应里，也不在日志里。日志分两层检查：
  - 用 structlog 的 `capture_logs()` 断言每条日志调用的完整字段：多一个 `exc_info` 或一个带消息的字段都会失败。structlog 25.5 的 `capture_logs()` 是原地改 processor 列表的，已经缓存的 logger 也抓得到。第一版用的是自己写的替身记录器，理由写成了「抓不到已缓存的 logger」，审查指出这个理由不成立，替身删了。
  - `tests/test_error_logging_pipeline.py` 走真实的日志管线：`configure_logging()` 之后，用 caplog 收下请求期间任何 logger（structlog 或 stdlib，含 exc_info）写出的每一行。在这一层断言占位文字一处都没有、事件正好记了一次、日志里的 `request_id` 等于响应头的 `x-request-id`。覆盖聊天流两类失败和 502。
- 原来有两个测试钉着「原文出现在 detail 里」（`"quota" in detail`、`"rate limit" in detail`），改成断言固定文字、并且原文不出现。UI 的错误事件测试改用新格式，另加一个经 ApiClient（MockTransport）读 `/chat` 错误事件的端到端测试：部分回答保留、接固定提示、不保留反馈凭证、只 POST 一次。
- `tests/test_chat_error_page.py`：用 AppTest 跑真实页面，搭法照 `test_request_admission.py` 的页面测试。
  - 覆盖三类错误事件，有部分文字和没有文字两种情况。
  - 断言存下的这一轮正好是「部分文字 + 固定提示」，并经过回答过滤只显示一次，不保留反馈凭证。
  - 之后两次 rerun 都不再 POST /chat。
  - 从示例问题按钮发出的问题也一样：只 POST 一次。把 `pop("pending_query")` 换成 `get` 的变异体（每次 rerun 都重新发问）原来所有测试都杀不掉，现在被这个测试杀掉。
- 全量（worktree；未提交的只有文档，测试不读它们）：审查前 `081fb30` 2977 passed，第 1 轮修正后 `5132021` 2994 passed，第 2 轮修正后 `e15a84f` 3006 passed，都是 0 失败（5 个警告与之前相同）。
- 变异检查（每个变异体在 /tmp 下由 `git archive HEAD` 加 worktree 改动组成的独立副本里跑）：
  - 第一版 31/31：两个分支的 detail 换成消息、每条日志加上消息、`log.exception`、去掉或写全路径的 frames、意外错误标成 upstream、502 的 detail 换成消息、502 不记日志、`error_log_fields` 加消息/丢 kind/丢 cause_type/任一处收布尔值/不看 response、每个 kind 字符串、默认 kind、kind 不存，以及名称选项的 5 个。
  - 审查修正后 23/23：先出文字与否两个方向、`_attr` 只接 AttributeError、kind 直接读或不检查、状态名不校验或前缀匹配或丢掉、旧字段名、`no_answer` 从不或漏一类、`tokens_sent` 不计数或不记、意外错误加 `exc_info`、经 stdlib logger 或另一个 structlog logger 写消息、`error_frames(limit=0)` 返回全部或取最外层、rescue 从不或总是记 frames、CLI 不打印消息、存档冲突抛普通 ValueError、OAuth 消息带回原文。审查者自己加的 7 个变异体里有 4 类存活（`exc_info`、其他 logger、帧数的两种），这些现在都在里面、都被杀了。
  - 第 2 轮修正后 13/13：
    - `no_answer` 直接读 `e.kind`；
    - `feedback_capture_failed` 写回旧字段名；
    - 点名代码只在 0 门课时报错、只在 `--commit` 时检查；
    - 先认点名再认句子；
    - 只列第一个没找到的代码、不用 `repr()`；
    - 空存档抛普通 ValueError；
    - kind 只要不是 None 就收；
    - `error_frames` 只接 ValueError；
    - 示例按钮的问题用 `get` 读；
    - 总加空行、从不记下已出过文字。
  - 其中 9 个是第 2 轮审查者报告存活的：C1、G1、E1、U3、R1–R5。
  - 它报告的另外 2 个当作等价，没有放进来：`lookup_lines=True` 输出完全一样；错误事件后 `continue`，ApiClient 在错误事件处就已经停了。

### 审查

- **第 1 轮：2 路只读审查**（语义与正确性 / 测试与文档；不派生子 agent、不改仓库、不联网），用户因额度在中途叫停。两路的部分结果（审查者原话的中文整理）保存在仓库外面。
  - 语义（0 CRITICAL、0 HIGH、1 MEDIUM、7 LOW）：
    - 中：真实 SDK 的流要到第一次迭代才发请求，原来的写法把「一个字没出就失败」也标成 `stream_interrupted`。审查者用 google-genai 1.75 加 mock transport 离线复现过。已修，见「已实现」1。
    - 低：
      - `error_log_fields` 自己可能抛异常；
      - 修复工具只打印异常类型；
      - 空回答也提示「稍后再问」；
      - 漏了状态名、token 数和 rescue 的调用位置；
      - OAuth 那条已知问题写得不全；
      - UI 测试还是旧事件；
      - 几处小问题：字段名不一致、`limit=0`、读源码行。
    - 都已处理。另有一条记录未改：栈很深时，最内 6 帧可能一个我们自己的帧都没有（意外错误基本出在我们自己的代码里，接受）。
  - 测试与文档（0 CRITICAL、0 HIGH、2 MEDIUM、8 LOW）：
    - 中：意外错误那个测试没断言完整字段，加上 `exc_info=True` 的变异体能存活；替身记录器只看得到一个模块的 logger，经别的 logger 写出的消息测不到。
    - 低：
      - 替身记录器的理由不成立；
      - request id 的说法没有测试；
      - 「最内 6 帧」没有测试；
      - UI 测试是旧事件；
      - 空回答的提示；
      - 修复工具的消息；
      - rescue 的调用位置；
      - `error_log_fields` 读属性时可能抛异常（未核实）。
    - 都已处理，见验证记录。roadmap 文件检查过：没有凭证、IP、主机名、邮箱、人名，21 个链接都在，FIX-04 的问题在 main 的修改记录里本来就公开写着。
  - 叫停时没做完的有四项：「rerun 不重复 POST」、修复工具 CLI 的边界情况、给名称选项多加变异体、真实 Streamlit 页面。都在第 2 轮补完了。
- **第 2 轮：1 路只读审查**，看 `081fb30..5132021` 并补完第 1 轮没做完的四项，同样不派生子 agent、不改仓库、不联网。
  - 结果：0 CRITICAL、0 HIGH、0 MEDIUM、6 LOW，都核对过、成立，都已处理（「已实现」8）。
  - 低：
    - 两处接口说明漏了 `no_answer`；
    - `no_answer` 的判断没有用上加固过的读法；
    - 三处文字不准：抛出点是八个、`feedback_capture_failed` 的字段名、「第一个 chunk」的说法；
    - 修复工具五处边界没有测试：库里有两门同代码的课、只读运行时点名一门不存在的课、既是句子又被点名、多个没找到的代码、空存档；
    - 两处加固没有测试：kind 不是字符串、`error_frames` 读 traceback 时出错；
    - 示例问题按钮的路径没有页面测试（这段是原来就有的代码）。
  - 四项补查：
    - 用 AppTest 在真实页面上试过三类错误事件和示例问题按钮，都只 POST 一次，显示也对：经过回答过滤，没有 `st.error`/`st.warning`，没有反馈凭证。
    - CLI 碰到带空格、小写或重复的代码时行为正确。
    - 它自己设计了 13 个变异体，11 个存活。其中 9 个是上面这些测试缺口，已补；2 个是等价的。
  - 审查者没法检查的：生产上的上线事实、真实 SDK 的行为（不联网）、真实浏览器。

### 已知、未处理

1. OAuth：「域名不允许」那条带着用户自己的邮箱，这段文字也写进 `auth.callback.rejected` 日志（info 级）。Google 返回的 `error_description` 原样进 401。都没改。
2. 全局的 `unhandled_exception_handler` 和 `RequestLogMiddleware` 仍用 `log.exception` 记完整 traceback。它们只写日志、不发给客户端，聊天流里的意外错误也不经过它们。`query_log.write_failed` 仍记 sqlite 错误文字的前 120 字。
3. `kind` 只覆盖 `llm/gemini_client.py` 自己抛的错误。如果以后打开 SDK 的重试，SDK 自己的重试日志会把异常文字写进同一份日志（现在没开）。
4. 意外错误只记最内 6 帧；栈很深时可能看不到我们自己的那一帧。

### 发布状态

- 这一批随一个 PR 提交，合并由用户点。最后一个代码提交 `e15a84f` 的全量：3006 passed、0 failed（main 2951）。
- 聊天错误、502、rescue 日志、OAuth 消息的改动都要等下次部署才生效。NAS 重启过的话，部署前先 `chown` 项目目录。
- 生产数据：10-07 上线时已经修了 CS 5200（见上线记录）。AAI 6600 还没改，下次部署之后按 `docs/answer-grounding.md` 做：
  1. `repair_course_names.py --use-catalog-title "AAI 6600"` 出报告，核对；
  2. 加 `--commit`；
  3. `sync_catalog_sources.py` 预演，确认 AAI 6600 变成 matched、`would_store` 是 1；
  4. 再加 `--commit`。

  不用重建索引，也不用重启。

## 15 — 查询日志导出改用私有导出的统一契约（OPT-01，2026-10-07／08）

### 范围与原因

- PR #6 合并（main `da9cf87`）后，用户说继续推进。按 10-06 检阅记录的顺序，这一批做 OPT-01。只改离线导出工具、它的数据模型和文档；不改 API、UI 和库结构，不碰生产数据，也不部署。
- 读代码核实，检阅记录里的四条都成立：
  - 旧 `scripts/export_query_log.py` 用 `db.connection.connect()`，也就是普通的 `sqlite3.connect(path)`，路径写错会建出一个空库；
  - `SELECT *` 导出全部列，含查询原文和原始 `user_id`；
  - 默认写 `eval/query_log_export.jsonl`，`git check-ignore` 确认这个路径没被忽略；
  - `open("w")` 直接覆盖已有文件。

  仓库里没有代码读这份输出。
- 反馈候选导出（06B-2）已经有更严格的规则。这一批把那套规则搬进共用模块，两个工具都用它。

### 已实现

1. `scripts/private_export.py`（新）：从 `scripts/export_answer_feedback.py` 原样搬出来的共用契约。
   - 打开已有的库：`resolve(strict=True)`、必须是文件、URI `mode=ro`、`query_only=ON`，一个 `BEGIN` 读快照。
   - 规范的 UTC 日期和秒级时间；严格 JSON，重复键失败；结果 ID 列表（≤1000 个非空字符串，≤65536 字符）。
   - 来源分类 `traffic_kind()`：NULL 是 unmarked，非空的 `eval:<run>` 是 eval，其余是 unknown；SQL 里的 `origin_clauses()` 与它一致。
   - 检索模式不在已知集合里时记成 unknown，不原样输出。
   - `query_log_compatible()`：导出用到的列都在，并且有真正的 INTEGER 主键 `log_id`。
   - 输出目标只接受新的 `.jsonl`，拒绝已有文件、symlink、hardlink，以及不存在或不是目录的父目录。仓库内只允许各工具自己的被忽略目录。
   - 发布：同目录的 0600 临时文件写完、fsync，再用不覆盖的 hard link 发布。
   - 参数解析出错时只打印一行固定文字。
2. `scripts/export_query_log.py`（重写），参数和反馈导出一致：
   - 只给 `--db-path`：stdout 一行统计。`selected_row_count` 覆盖整个选择（来源 + 时间窗口），不受 `--limit` 限制；`traffic_counts`、`route_counts`、`retrieval_mode_counts` 各自加起来都等于它。统计只读 `log_id`、`created_at`、`route`、`matched_via`、`user_id` 五列。
   - `--out`：新的元数据 JSONL，按 `log_id` 升序，最多 `--limit` 行（1–1000）；`has_more` 表示选择里还有更多。没有查询原文、拒答原因和原始来源标记。
   - `--include-private-text --ack-private-data`（两个都要，并且要有 `--out`）：再加 `private_text`，即查询原文和拒答原因。
   - 被选中的行字段不对时整次失败；要写的行全部验证完、检查完 32 MiB 预算之后才创建文件。
   - 仓库内只允许 `data/raw/query_log_review/`；旧的默认路径和反馈导出的目录都会被拒绝。
3. `schemas/query_log_export.py`（新）：strict 的 `QueryLogExportRow`，多一个字段就失败。
   - 每行固定是 pending，不是 ground truth。
   - 带上 query_log 补不上的缺口：不记筛选条件、chat 不记对话历史、没有检索快照、非 eval 来源未经验证、未知模式。
   - 原文模式下，查询原文必须对得上 `query_sha256`。
4. `scripts/export_answer_feedback.py` 改用共用模块，搬过去时 SQL、提示文字和输出都不变。它的测试只改了两处：`module.os.fsync`、`module.os.link` 改成直接 patch `os`，因为模块不再 import os。
5. `.gitignore` 加了 `eval/query_log_export.jsonl`。新工具不再写这里，这一条只防旧版本留下的副本被误提交。
6. 文档：`docs/query-log-export.md`（新）；`docs/feedback-review-export.md` 加一段，说明共用模块和审查后的加固；`docs/pii_redaction.md` 加第 9 节。
7. 审查后的修正（见「审查」）：
   - 「在不在仓库里」「在不在私有目录里」都按路径文字或文件身份判断：对父目录和它的每一级上级做 `os.path.samestat`。父目录按输入的写法和解析后的位置各查一次。
   - symlink 循环在共用的 `_resolved()` 里统一成 `OSError(ELOOP)`，用 `from None` 丢掉带路径的原消息，两个 CLI 都只打印固定的一行。
   - `origin_clauses()` 的 eval 子句改成 `substr(c,1,5)='eval:' AND c<>'eval:'`，对含 NUL 的标记也和 `traffic_kind()` 一致，两个工具都用它。
   - 行 schema：结果 ID 必须是非空字符串、最多 1000 个；两个模型都设了 `hide_input_in_errors`，校验错误不带输入值。
   - 文档：WAL 与回滚日志模式的区别、eval 是自报的、UNC 路径、按整天的窗口导不全的情况、大小写和短文件名、第三个示例先建目录、WSL 重启会清空 `/tmp`、空窗口和倒置窗口直接失败。模块说明改成「不建库（WAL 库旁边可能多出 -wal／-shm）」。
   - 测试：B 的 21 个探针按测试文件现有的写法改写进来，另加这几处修复的测试。仓库目录的测试对两个导出工具都跑；旧默认路径放进假仓库里测，不再受本地有没有旧文件影响。

### 修改文件

| 文件 | 修改 |
|---|---|
| `scripts/private_export.py`（新） | 两个私有导出共用的契约，含审查后的三处加固 |
| `scripts/export_query_log.py` | 重写：默认只统计、元数据文件、成对开关的原文 |
| `schemas/query_log_export.py`（新） | `QueryLogExportRow`、`PrivateQueryText` |
| `scripts/export_answer_feedback.py` | 改用共用模块 |
| `.gitignore` | 旧的默认输出路径 |
| `tests/test_query_log_export.py`（新）、`tests/test_feedback_candidate_export.py` | 见验证记录 |
| `docs/query-log-export.md`（新）、`docs/feedback-review-export.md`、`docs/pii_redaction.md`、本文件 | 见上 |

### 验证记录

- 只用合成的临时库，没有打开任何真实的库。
- `tests/test_query_log_export.py`（132 个用例）覆盖：
  - 默认只统计：库的字节不变，目录里不多文件，报告里没有查询原文、来源标记和未知模式字符串。
  - 统计覆盖三类来源，加起来对得上，`--limit` 不影响统计。大写的 `EVAL:`、空字符串、紧跟在 `eval:` 后面的 NUL：SQL 的选择和逐行分类一致。
  - 元数据文件逐字段核对；原文文件除 `private_text` 外与元数据完全相同。
  - 开关不成对、不是布尔值、没有 `--out` 都失败，不留文件。
  - 时间窗口的两端；文件按 `log_id` 排序，时间顺序和 ID 顺序相反时也是；limit 与 `has_more`。
  - 坏字段：
    - 分类字段（时间、route、来源标记、模式类型）坏了，统计和导出都失败。
    - 导出字段（原文、结果 ID、k、耗时、拒答原因、`log_id`）坏了，导出失败、不留文件，统计照常。
    - 窗口外、来源不符和排在 limit 之后的行不读这些字段。
  - 边界值都能通过：500 字、1000 字、1000 个 ID、65536 字符（按字符算，不是字节）、k 为 1 和 50、耗时 0 和空值。
  - 输出目标：
    - 已有文件、库文件本身、symlink、悬空 symlink、hardlink、父目录不存在、父目录是文件、后缀不对，异常类型逐个钉住；`.JSONL` 可以。
    - 两个导出工具在仓库内都只能写自己的目录：另一个工具的目录、经 symlink 进出仓库、经仓库内 symlink 的相对路径（从仓库根目录和从 `data/raw` 出发各测一次），都被拒绝。
    - ROOT 换一种写法（模拟 WSL 上的大小写和短文件名）时，按文件身份也认得出仓库。
  - 库：不存在不创建；给目录失败；路径里带 `#`、`?`、`%` 时打开的就是那个文件，不多建文件；缺表、缺列、没有主键、复合主键都失败，不迁移；小写的 integer 主键可以。
  - trace：只有 SELECT／PRAGMA／BEGIN，URI 是 `mode=ro`；统计那条 SELECT 只有五列，导出那条是显式列表，没有 `SELECT *`。
  - CLI（不带 PYTHONPATH 的子进程）：
    - 默认 origin 是 unmarked、limit 是 200，`--db-path` 必填；
    - 成功时不回显输出路径；
    - 参数错误、输入错误、symlink 循环（两个工具，`--db-path` 和 `--out` 各一）、深层嵌套 JSON 的 RecursionError，都只打印固定的一行，不回显值。
  - 写入：0600 权限；输出预算按 UTF-8 字节算，正好等于上限时可以；fsync 失败；发布竞争；发布后清理失败。
  - schema：拒绝身份字段、真值、丢失或重复的缺口、不规范时间、NaN、字符串 k、两种哈希格式、嵌套的多余字段、来源和模式之外的值、空 ID、1001 个 ID；原文不能移植；三处校验错误都不带输入值。
  - 快照：WAL 副本上，统计和导出两遍之间有写入方提交，两遍都看不到它。
  - 其他：哈希覆盖原文的首尾空格；`.gitignore` 的两条规则；真实的 `/search`、`/chat` 写出的行分类正确；WAL 副本和导出期间有写入方（见下）。
- `tests/test_feedback_candidate_export.py`（88 个用例）：除了上面说的两处 patch，坏结果 ID 里加了空字符串和 1001 个两种（见下面的变异检查）。
- 两个导出测试文件：最终 220 passed（`d74dde8` 时 194）。
- 全量：最终 3140 passed、0 failed；`d74dde8` 3113 passed（那次在加 WAL 用例之前开始跑）；main 3006。
- 变异检查：每个变异体都在 /tmp 下由 `git archive HEAD` 加 worktree 改动组成的独立副本里跑。
  - 第一版 92/92 被杀：
    - 共用模块 37 个：日期和时间的规范与类型检查、空窗口、JSON 预算差一、重复键、ID 上限差一、空 ID、来源前缀、长度和类型、两条 SQL 子句、未知模式原样输出、模式类型、词表缺项、读写 URI、库路径非严格、目录当库、去掉 query_only 或 BEGIN、主键和列检查、目标的每条规则、link 换成 replace、去掉 fsync、临时文件不删、清理失败不报告、parser 回显、忽略 until。
    - 查询导出 35 个：私有目录、统计读原文、`SELECT *`、route 和时间不查、各个缺口、eval 哈希、原文总带或从不带、丢拒答原因、哈希算错、计数、来源列、窗口两端、limit 加一、`has_more` 的两种错法、预算、`privacy_mode`、schema 检查用错列、去掉排序、两个计数互换、CLI 文字、普通 argparse、ValueError 不捕获、布尔 limit、开关不成对或不要 `--out`、开关类型、统计模式读整行、临时文件前缀、两个 Counter 记错键。
    - schema 16 个；反馈导出 3 个（临时文件前缀、来源子句丢失、普通 argparse）；`.gitignore` 1 个。
  - 审查修正后 123/123，组成：
    - 上面 92 个，其中 9 个的锚点随修改后的代码更新；
    - B 报告存活的 22 个真实缺口，加上它的快照变异体 b17（原来只靠 trace 杀掉）；
    - 每处修正一个：只看路径文字、不查上级目录、eval 子句改回 `length()`、RuntimeError 漏出、schema 不查空 ID、不限 ID 个数、两个模型的错误带回输入值。
  - 第一次跑是 120/123。存活的 3 个都是真实缺口：
    - 共用的结果 ID 检查上限差一、放行空 ID：查询导出现在有 schema 兜底，反馈导出没有，它的测试也没覆盖这两种值；
    - 不把 `--out` 转成绝对路径：当前目录在仓库更深一层时，经指向仓库外的 symlink 写出的相对路径会漏过检查。B 的探针是从仓库根目录跑的，身份检查兜住了。

    补了反馈导出的两个坏值和从 `data/raw` 出发的相对路径后，这 3 个重跑都被杀。
- WAL 实测：
  - WAL 模式的库在只读打开时，SQLite 也会在库旁边建 `-wal`（0 字节）和 `-shm`，关闭后留下；库文件本身不变。反馈导出原来就是这样。
  - 导出期间有写入方时，读到的是已提交的内容，不等待，也看不到没提交的。
  - 这些写进了文档，并加了测试。
- ruff 0.5.0（F/E9/B）对改动的文件：干净。

### 审查

两路只读审查，看 `main..d74dde8`：A 看语义与隐私，B 看测试、变异体与文档。两路都不派生子 agent、不改仓库、只用合成的临时库、不联网，都完整跑完。两路的进度文件和 B 的探针、变异脚本放在仓库外。

- **A（语义与隐私）**：0 CRITICAL、0 HIGH、1 MEDIUM、5 LOW，另有两条文档措辞。都核对过、成立，都已处理。
  - 中：WSL 的 `/mnt/h` 不分大小写，换了大小写或用 8.3 短文件名写的仓库路径，不会被「仓库内只能写私有目录」拦下。审查者在自己的副本里把文件写进了被跟踪的 `eval/` 和 `docs/`。我在 worktree 上核实过：大小写不同的路径存在，`samefile` 为真，`realpath` 保留输入的大小写。Windows 原生的 Python 不受影响。反馈导出原来就是这样。已修（「已实现」7）。
  - 低：
    - Python 3.12 上，symlink 循环让 `Path.resolve()` 抛 RuntimeError，两个 CLI 都没接住，打印出带路径的 traceback；
    - 含 NUL 的来源标记：SQLite 的 `length()` 数到 NUL 为止，`--origin eval` 和 `--origin all` 的 eval 数对不上。接口写不出这种值，也不泄露任何东西；
    - 「导出不会等写入方」只在 WAL 模式成立；
    - 行 schema 单独用时，接受空 ID 和超过 1000 个 ID；
    - eval 标记是自报的头，任何客户端都能带。按文档处理，见「已知、未处理」5。
  - 文档措辞：「先验证全部选中行」应是要写的行；`PrivateQueryText` 的校验错误里带着查询原文，CLI 不显示，但 Python 调用方记日志时会带出去。
  - 它核对过没问题的：
    - 反馈导出的行为不变：逐句对照，另跑了 7 种库 × 18 组参数共 126 个 CLI 用例的差分，退出码、stdout、stderr、输出字节和目录内容全部一致；
    - 路径里带 `?`、`#`、`%`、空格时也不建库；
    - 统计和文件来自同一个快照；
    - WAL 副本；发布不覆盖；
    - 接口实际写出的行，两个阶段都能通过（按建表以来的历史核对过）。
- **B（测试、变异体与文档）**：0 CRITICAL、0 HIGH、3 MEDIUM，其余是 LOW。都核对过、成立，都已处理。
  - 中：
    - 大小写绕过，同 A；
    - 库路径的 URI 编码没有测试。去掉编码的变异体能存活，而它会把 `copy #1.sqlite3` 里的 `#` 当成 URI 片段，读写打开并新建另一个空库；
    - CLI 的默认值没有测试：`--origin`、`--limit` 的默认值和 `--db-path` 必填。
  - 低：
    - symlink 循环，同 A；
    - 反馈导出自己的目录规则，重构后几乎没测；
    - 行 schema 的几条约束没测：两种哈希的格式、嵌套的多余字段、来源和模式的取值。我原来说的「schema 的每个校验都做了变异」不准确；
    - 标记的大小写、空字符串和 NUL；
    - 预算按字节还是字符算、上限算不算在内；
    - 深层嵌套 JSON 的 RecursionError；
    - `--out` 成功时不回显路径；
    - 复合主键；`.JSONL`；经 symlink 的相对 `--out`；
    - 哈希覆盖原文的首尾空格；
    - 文档：按整天的窗口导不全、只读目录里的 WAL 副本、模块说明里的「不建任何文件」、UNC 路径、第三个示例没建目录、空窗口和倒置窗口的报错；
    - 一个测试在本地有旧输出文件时，走的是「文件已存在」那条路。
  - 它自己设计了 25 个变异体，23 个在两个测试文件上存活。其中 22 个是真实缺口；b06 与原代码等价（SQLite 总把类型名报成大写）。它写的 21 个探针在 `d74dde8` 上全部通过，并能杀掉那 22 个。另有 3 个它判为等价的：去掉 `fchmod`（mkstemp 本来就是 0600）、去掉 `busy_timeout`（connect 默认就是 5 秒）、去掉 fsync 前的 flush。
  - 它核对过没问题的：
    - 同一快照：两遍之间提交的写入，两遍都看不到；
    - 反馈导出的行为不变；
    - 文档和代码一致：四个旧问题、参数表、五列统计、来源和窗口、预算、发布方式、权限、两个忽略文件；
    - 规模：20 万行统计 9.8 秒，1000 行导出 1.5 秒。
- 两路都没法检查的：真实 uvicorn／cloudflared 对头里 NUL 的处理、macOS、NAS／SMB 共享、容器里运行、Linux 上的 Python 3.13+、真实的库。

### 已知、未处理

1. WAL 模式的库只读打开会留下 `-wal`／`-shm` 辅助文件，库本身不变，见验证记录。
2. 时间窗口只按整天，没有游标；同一天、同一来源超过 1000 行时导不全。
3. query_log 本身没有保留期和自动清理，仍由运维负责。
4. 0600 只在 POSIX 文件系统上成立；WSL 的 `/mnt/<盘符>` 和 Windows 上由 ACL 决定。
5. eval 行不带 `unverified_traffic_origin`，和反馈导出的格式一致；但 `X-Eval-Run` 是自报的，任何客户端都能带。文档要求用 `eval_run_sha256` 对照自己的评测名称再确认，格式没有改。

### 发布状态

- 这一批随一个 PR 提交，合并由用户点。
- 只是离线工具，不部署也能在本地副本上用；镜像里的脚本要等下次部署才更新。生产上要导出时，先按备份流程准备一致的副本，在副本上跑。
- 本批没有动生产数据。AAI 6600 仍按 14 的「发布状态」，等下次部署后再做。

## 16 — 页面缓存会过期、失败 30 秒后重试，Co-op 预览按访客分开（OPT-02，2026-10-08）

### 范围与原因

- PR #7 合并（main `751c6b1`）后，用户说继续推进。FIX-02／03／04 第 13 批已做完，按 10-06 检阅记录的顺序，这一批做 OPT-02。只改 Streamlit 前端：API、数据库和部署都不变，不碰生产数据。
- 读代码核实，检阅记录说的都成立，另外多找到两处：
  - 首页课程总数（`_ready_info`）和 Co-op 预览（`_coop_teaser_cache`）加载失败时，空结果在这个标签页里一直保留。API 冷启动的 70–100 秒里 `/ready` 返回 503，这段时间打开页面的人要重新加载页面才看得到课程总数；
  - 项目列表和课程表失败时完全不缓存，落地页一次 rerun 里有三处读项目列表，后端卡住时每次 rerun 都要依次等超时（每次 8 秒）；
  - 成功的结果永不过期；
  - Co-op 预览按访客等级裁剪，缓存却不分身份：登出或换账号后还会沿用上一个身份的列表。

### 已实现

1. `app/view_cache.py`（新）：页面只读内容的按标签页缓存。
   - 成功的结果用 5 分钟，失败记 30 秒；时钟用 `time.monotonic`，测试替换 `view_cache.clock`。
   - 重新获取失败、并且失败可能自己恢复（`transient()`：408、429、5xx，包括连接失败和下面的非 JSON 响应）时，给出同一范围上次的成功结果；没有才把错误交给页面。明确的答复（401、403、404 等其他 4xx）丢掉上次的成功结果，把错误交给页面。
   - 每条记录带范围：`public`、`guest`，或 `session:<token 的 SHA-256>`；记录绝不给另一个范围用，回退也不行。
   - 第一次失败时页面拿到请求本身的 `ApiError`；30 秒内重复显示的是按状态码、提示文字和错误类型重新构造的，不留原异常对象，也不带过时的 Retry-After 秒数。
   - 2xx 但内容不是 JSON 时，`fetch()` 抛出的 `ValueError` 按 502（`invalid_response`）处理。
   - `expire_all()` 把所有记录标成过期，上次的成功结果留着，作回退和比较方案用。`begin_run()`／`served_fallback()` 记下这一次运行有没有给出回退内容。
2. 用到它的四处：hero 的 `/ready`（`app/streamlit_app.py`）、Co-op 预览（`app/discover_view.py`，按访客范围）、`get_programs_cached`／`get_curriculum_cached`（`app/program_view.py`）。方案分享链接自己的 GET 成功后用 `view_cache.store()` 记下（`app/deep_links.py`）；`logout()` 删掉 Co-op 预览的记录（`app/state_manager.py`）。
3. 侧边栏每个页面都有「🔄 刷新页面内容」（`view_cache.REFRESH_LABEL`），`on_click` 回调里调 `expire_all()`。只针对这些 GET；回调不动聊天历史、待发的问题和各组件的选择，不重发提问、Co-op 投稿或回答评价。
4. 落地页有区块因为可能自己恢复的原因加载不了时，显示一行说明并指向刷新按钮；明确的答复（比如会话过期时 `/coop` 的 401）只隐藏区块，不说会重试。某次运行显示了回退内容时，页面结尾在侧边栏刷新按钮下面说明「显示的是上次加载的版本」。
5. 课程表重新获取到的 `plans` 和上次加载的不同时，清除这个项目的方案选择，并提示一次「方案有更新，请重新选择」；相同（只是其他字段变了也算相同）则保留；没有选择时不提示。清除是把 `program-plan-{id}` **设成 None**，不是删掉键：删掉的键不通知浏览器，浏览器继续显示旧选项，下一次 rerun 又把它送回来。同样的改法也用在项目刷新按钮、选择框发现旧选择已失效时，以及方案分享链接清除或替换选择的四处；选择框加了同一句话的 placeholder。
6. 文档：`docs/view-cache.md`（新）；`docs/program-policy-evidence.md`、`docs/program-plan-sharing.md` 各加一段；`docs/adr/0029-deep-links.md` 加一句更新说明。

第 1 条的「只有暂时性失败才回退」和非 JSON 响应、第 4 条的回退说明和「明确答复不说会重试」、第 5 条的「设成 None」和「没有选择时不提示」，都是审查后改的（见「审查」）。

### 修改文件

| 文件 | 修改 |
|---|---|
| `app/view_cache.py`（新） | 缓存本身 |
| `app/streamlit_app.py` | hero 走缓存、刷新按钮、每次运行开始时清零、页面结尾的回退说明 |
| `app/discover_view.py` | Co-op 预览按访客范围缓存；缺区块的说明只针对暂时性失败；说明里的按钮名取自 `REFRESH_LABEL` |
| `app/program_view.py` | 两个取数函数走缓存；方案变了就清除选择并提示；项目刷新按钮设成 None |
| `app/program_plan_view.py` | 失效的选择设成 None；placeholder |
| `app/program_plan_links.py`、`app/deep_links.py` | 链接清除选择时设成 None；暂时性失败的判断改用 `view_cache.transient` |
| `app/state_manager.py` | 登出删掉 Co-op 预览的记录 |
| `tests/test_view_cache.py`（新）、`tests/test_home_cache_page.py`（新）、`tests/test_discover_view.py`、`tests/test_deep_links.py`、`tests/test_program_plan_links.py`、`tests/test_program_plan_view.py`、`tests/test_program_policy_view.py`、`tests/ui_recorder.py` | 见验证记录 |
| `docs/view-cache.md`（新）、`docs/program-policy-evidence.md`、`docs/program-plan-sharing.md`、`docs/adr/0029-deep-links.md`、本文件 | 见上 |

### 验证记录

- 只用模拟 API（`httpx.MockTransport`、替身 `ApiClient`）和替换过的时钟，没有连真实的 API 或库。
- `tests/test_view_cache.py`（新）覆盖：
  - 缓存本身：两个有效期的边界、时钟倒退、文档写的 30 秒／5 分钟和单调时钟；第一次失败给原错误、之后给重新构造的错误（各种状态码的字段一致，不带 Retry-After 秒数）；连续两次失败都抛出；非 JSON 响应按 502；其他异常不缓存；记录里没有异常对象。
  - 回退：暂时性失败回退到同一范围上次的成功结果，明确答复（401、403、404、422）不回退、丢掉上次结果；`transient()` 的取值逐个钉住；范围之间绝不互用；格式不对的记录重新获取；`store()`、`peek()` 按范围；`expire_all()` 不删上次结果。
  - `served_fallback()` 只算这一次运行：成功不算、失败后回退算、失败仍有效时的读取算、没有上次结果的失败不算，记在 `state` 里而不是课程表的容器里。
  - 视图（`Recorder`）：Co-op 预览的恢复与身份、项目页错误的有效期、落地页的说明只针对暂时性失败、一个精选课程表失败不影响已加载的卡片；方案选择的各条规则：内容／增删／顺序变了清除并提示一次、只改了其他字段保留、没有选择（含键存在但为 None）不提示、没有上次结果时清除、项目刷新按钮清除但不提示、项目刷新后取数失败显示错误而不是旧课程表；清除都是设成 None。
- `tests/test_home_cache_page.py`（新，真实页面上的 AppTest，模拟 API 加替换时钟）覆盖：
  - API 预热：30 秒内不重复请求，过了就重试；冷启动跨两三个 30 秒窗口（按 15／30／45／60／90 秒逐步）一直不出 traceback，恢复后 5 分钟内不再请求。
  - 刷新按钮：重新获取缓存内容，不重发提问、评价、Co-op 投稿；登录、登出也不重发提问；故障时刷新显示上次的内容并在侧边栏说明，恢复后说明消失；侧边栏刷新保留没变的方案选择；每个页面的侧边栏都有这个按钮，文字和落地页说明里的按钮名一致。
  - 2xx 非 JSON：已有内容时保持页面、显示上次内容和说明；第一次加载时显示不带数字的页面和缺区块说明。
  - 会话过期（`/coop` 401）：不再显示会员看到的列表，也不说会重试。
  - Co-op 预览跟着 token 走；真实选择框：方案变了才复位、没有选择时方案变了不提示、placeholder 与 None 选项的文字一致；`/ready` 返回意外内容时显示不带数字的 hero。
- `tests/test_discover_view.py`、`tests/test_deep_links.py` 加了自动生效的夹具：缓存没命中时用会失败的 `ApiClient` 替身，不再可能发到 `API_BASE_URL`。`tests/test_program_plan_links.py` 的两处缓存预置改用 `view_cache.store()`；断言从「键被删掉」改成「键还在、值为 None」。
- 真实浏览器（内置浏览器，本地 Streamlit 跑真实的 `_render_curriculum`，进程内模拟 API）：
  - `14f0b5c`：选好方案，服务端改方案、时钟拨过 5 分钟后，页面提示已清除、服务端是 None，浏览器里的选择框仍显示旧方案；再点一次无操作的 rerun，服务端又变回旧方案，修订后的内容直接按旧选择显示，没有提示。复现了审查 A 的结论。
  - 修复后：同样的步骤，选择框复位成 placeholder，rerun 后仍是 None；项目刷新按钮这条路径也一样。
- 这 8 个测试文件：248 passed（`14f0b5c` 时 209）。全量：`14f0b5c` 3194 passed；审查修复后 3233 passed。修复后第一次全量抓到两处这 8 个文件之外的测试：`tests/test_program_plan_view.py` 的替身 `FakeSurface.selectbox` 不接受新加的 `placeholder` 参数（6 个用例报 TypeError），替身补上这个参数；`tests/test_program_policy_view.py` 有一个用例断言失效的选择被删掉，改成断言设成 None。
- 变异检查：每个变异体在 /tmp 下由 `git archive HEAD` 加 worktree 改动组成的独立副本里跑，跑这 8 个测试文件。
  - 审查前：48/48 被杀（第一次 43/46，3 个存活都是测试缺口：重新构造的错误跟重新构造的错误比较；两行落地页各自的失败标记没测。补测试后又加了 2 个）。
  - 审查后 88/88，组成：
    - 上面 48 个，其中 12 个的锚点随修改后的代码更新；
    - B 报告存活的 12 个真实缺口，另加它的 `peek()` 范围；
    - 每处修复几个：明确答复也回退、`transient()` 的各个边界、非 JSON 漏出或不算暂时性、回退计数的三个位置、不清零、不显示说明、按钮名各改各的、各处「设成 None」改回删掉键、去掉 placeholder、侧边栏刷新改成删掉缓存或顺手清掉方案选择。
  - 第一次跑是 84/88。存活的 4 个都是测试缺口：只有课程表回退时计数记错了地方、精选课程表 404 时仍说会重试、选择框发现旧选择已失效时改回删掉键、分享链接清理时改回删掉键。补了测试后，这 4 个重跑都被杀。
- ruff 0.5.0（F/E9/B）对改动的文件：干净；没有 CR、没有权限位改动。

### 审查

两路只读审查，看 `751c6b1..14f0b5c`：A 看正确性、Streamlit 语义与身份，B 看测试、变异体与文档。两路都不派生子 agent、不改仓库、只用模拟 API，都完整跑完。进度文件、探针和变异脚本放在仓库外。

- **A（正确性与身份）**：0 CRITICAL、1 HIGH、4 LOW、1 处文档字符串。都核对过、成立，都已处理。
  - 高：清除方案选择用的是删掉键，真实浏览器里的选择框不会复位，下一次 rerun 时浏览器把旧选项送回来（按显示文字匹配），旧选择被悄悄沿用到修订后的方案上，页面上还说已清除。AppTest 读的是服务端状态，看不出来。A 在浏览器里复现并验证了改成设成 None 的修法；我在浏览器里重新复现、修复后再核对过（见验证记录）。同样的写法在项目刷新按钮和分享链接里原来就有，一并改了。
  - 低：
    - 没有选择时也提示「已清除」：真实的 Streamlit 会把未选择的选择框登记成 None，「键存在」不等于选过；
    - 刷新时重新获取失败，页面毫无变化，用户会以为已经刷新了；
    - 404、401 也回退到上次的内容：同步后被删的项目一直显示旧课程表，会话过期后一直显示会员的列表，落地页还一直说会重试；
    - 2xx 非 JSON 的响应：以前缓存的成功结果不重新获取，现在 5 分钟后会，这种响应会让每个页面都出 traceback；
    - `apply_deep_link` 的说明写成「失败记 30 秒」，其实只对 `?program=` 成立。
  - 它核对过没问题的：有效期的计算、`expire_all`、格式不对的记录、范围隔离；14 种状态码 × 5 种错误类型 × 5 种 Retry-After 下重新构造的错误和原错误只差文档写的「稍后」；刷新按钮不会重发 POST、不会重新套用已消费的分享链接；没有缓存键和组件键冲突；`/programs`、`/programs/{id}`、`/ready` 确实不看调用者，`/coop` 按调用者裁剪；没有路径能把一位访客的 Co-op 预览给另一位看；政策证据在回退内容下仍按方案 hash 重新核对。
- **B（测试、变异体与文档）**：0 CRITICAL、0 HIGH、2 MEDIUM、11 LOW。都核对过、成立，都已处理；代码行为在它的 14 个探针里都和文档一致，问题都在测试和文档。
  - 中：
    - 超过一个 30 秒窗口的故障没测：去掉 `has_value` 检查的变异体能存活，那时第二次失败返回 None，搜索页会在故障期间崩溃；
    - 项目刷新按钮之后取数失败的情况没测：改成「标成过期」的变异体能存活，那时会显示旧规则树而不是错误。
  - 低：只比较 `plans` 没测；落地页一个课程表失败时已加载的卡片没断言；项目刷新按钮单独提示「方案有更新」没测；侧边栏刷新对页面的效果只通过直接调用 `expire_all()` 测；有效期和时钟没钉住；记录里存异常对象没测；按钮文字和落地页说明里的按钮名可以各改各的；两个测试文件缓存没命中时会发出真实请求（它在自己的监听端口上记到了 GET）；路线图的「登录态切换不重复 POST」没有测试；几处文档不准（`apply_deep_link` 之外还有 ADR 0029、「各组件的选择都不动」、「只有项目刷新按钮会无条件清除选择」、「失败时隐藏区块」、回退内容可能很旧、格式不对的 200 会缓存 5 分钟）；两处旧测试直接塞原始字典当缓存。
  - 它自己设计了 93 个变异体，79 个被杀，存活的 14 个中 12 个是真实缺口，另 2 个价值很低（`peek()` 不看范围，只有测试用；分享链接里原有的一行删除，真实 Streamlit 里几乎等价）。这些都已补测试，并加进了审查后的变异检查。
  - 它核对过没问题的：两个新文件单独跑、放在 22 个 UI 测试文件的前后、倒序、同一进程跑三遍都通过；所有替换都由 `monkeypatch` 撤销；文档里的缓存表、范围、有效期、回退、登出、只缓存 `ApiError`、错误重建、不重发 POST、政策证据不缓存、已消费链接不重新套用、冷启动时长，都和代码一致；路线图 OPT-02 的每一项都已实现。
- 两路都没法检查的：真实 API 和库、真实时序；B 没有用真实浏览器（A 和我各在浏览器里看过方案选择框，其他组件只经过 AppTest）。

### 已知、未处理

1. 聊天页的项目选择框（`chat_program_id`）在所选项目已不在列表里时仍是删掉键，原有行为，没有改成设成 None；项目被删的情况很少。
2. 分享链接的 `?course=` 和方案链接自己的 GET 不走缓存，确定结果之前每次 rerun 都请求一次，后端卡住时每次最多等 8 秒。
3. 5 分钟和 30 秒是经验值，没有按真实流量测过；API 没有数据版本号，成功的缓存只能按时间过期。
4. 回退的内容可能很旧（故障持续多久就旧多久），侧边栏的说明只说是上次加载的版本。
5. 浏览器里组件状态的问题只能手动在浏览器里看；AppTest 和 `Recorder` 只能钉住「设成 None 而不是删掉」这一机制。

### 发布状态

- 本地分支 `fix/home-cache-recovery`，没有 push，没有 PR；按用户的要求，等他要了再开。合并由用户点。
- 只改前端，下次部署时一起生效；本批没有动生产数据。AAI 6600 仍按 14 的「发布状态」。

## 17 — 数据覆盖、冲突与来源报告（OPT-03，2026-10-08／10）

### 范围与原因

- OPT-02 之后，按路线图做 OPT-03：回答「下一批到底补哪些数据」，而不只知道课程总数。路线图的第一步是显式副本上的只读审计器，默认只输出汇总，不改课程或来源。验收要求：每类计数可回溯到明确分母与规则；坏 JSON、缺 schema、无来源、重复代码、冲突、未知日期和 partial 各有夹具；无写入、无网络、默认无用户原文；能区分「未检查」和「检查后没有问题」。
- 只新增一个离线脚本：API、界面、数据库和部署都不变。没有在任何真实库上跑过：对生产数据出报告，要用户先建好一份一致的离线副本并同意。
- 10-08 写完（`81c4395`），两路审查当晚回来、原样存档。10-09 先把分支 rebase 到第 16 批的审查修复 `9fd3c61` 之上（两批改的文件不重叠，没有冲突；`81c4395` 变成 `8c0e987`），再逐条复现、修复（`3e26027`）。
- 10-09 上午第二轮两路审查（看 `9fd3c61..3e26027`）回来、原样存档；下午和晚上逐条复现、修复，见「审查」的第二轮。
- 10-09 晚第三轮审查（看 `5c1b8e5`）：A3 两次被 API 的安全过滤拦下，没有最终报告，结论留在它的进度文件里；它没看完的部分另起一路 A3b 来看；B3 完整跑完。三份记录原样存档，10-10 逐条复现、修复，见「审查」的第三轮。

### 已实现

1. `scripts/audit_data_coverage.py`（新）：对显式给出的离线 SQLite 副本出一份 JSON 报告，分七节：`schema`、`courses`、`catalog_snapshots`、`fields`、`requisite_documents`、`program_plans`、`legacy_rows`。
   - 打开方式和发布预检相同，复用它的路径、旁文件和指纹函数：`mode=ro&immutable=1`、`query_only`、`trusted_schema=OFF`、时间／VM 步预算、一次 `BEGIN`，前后核对指纹。另外拒绝所有以 `.env` 开头的文件名，要求 SQLite 不低于 3.37。
   - 读任何一行之前，先跑 `PRAGMA integrity_check(1)`，不是 `ok`、或者检查本身就报文件损坏，都整份不报（`database_integrity_failed`）；再用 `PRAGMA table_list`／`table_xinfo` 看表结构：视图、虚拟表、影子表，或要读的列里有生成列的，记 `not_plain`，不读；缺列记 `column_missing`。之后装 SQLite 授权回调，只放行列出的列，SQL 函数、PRAGMA、经由视图或触发器的读取都拒绝。用户表和 `courses.raw_text` 从不查询（只有完整性检查会读到它们的页，不输出任何东西）。
   - 这些检查都按名字，抄进允许的列里的值照样会被读到，所以输出只有计数、固定文字、格式合格的代码、ID、年度（相邻两年的 `YYYY-YYYY`），以及校验过的记录里的日期；ID 还必须至少有一个字母，纯数字的标识（比如账号）印不出来。
   - 文本工厂把不是合法 UTF-8 的 TEXT 换成一个标记（只有字节相同才相等）。应用取到这种值的查询整条失败，所以这种行在每节单独记成 `text_not_utf8`，在明细里能找到（被排除课程的坏行也按它自己的代码列出），这样的 `course_id` 仍按字节当作同一门课的键；其他计数块另有不互斥的 `rows_with_text_not_utf8`。装着 UTF-8 JSON 的 BLOB 和应用一样照常解析；长度上限按存储长度算（BLOB 按字节）。
   - 每一节、节里能单独没查成的部分都有 `status`：`checked`、`not_checked` 加原因码、`failed` 加固定码。`complete` 要求任何一处都是 `checked`；退出码 0／2／1。
   - 每一节和主要的计数块写明分母，按院系、年度、项目的分组和字段表的分母写在规则里；每节的 `rules` 给输出里出现的每个名字一句规则，分母的名字也有。`counts` 下的类别和每个字段的类别互斥、相加等于分母，其他块的规则注明不互斥。
   - `usable` 用应用自己的模型、内容 hash 和身份核对。字段类别和 `rag/answer_evidence.py` 一致：`missing`、`catalog_only`、`catalog_lists_none` 加起来正好是 `missing_fields`，学分冲突正好是 `catalog_metadata_conflict`；先修代码按规范形式比较（`CS5004` 就是 `CS 5004`）。和应用的差别写在规则和文档里：超长的值不解码、重复行一个都不用、坏 UTF-8 只算一行、孤儿方案不算可用、先修代码集合是报告自己的比较、名字只差大小写的表或列记作缺失（宁可不查）。
   - 抓取日期未知就写未知，不用导入时间代替；hash 和 `source_checked` 不算官方正确或当前适用；partial 方案不算完整。
   - 默认只有计数；`--details` 列出课程代码（按院系分组，每个院系各自限量）、方案 ID 和方案范围。字段明细列出除 `catalog_consistent` 以外的每个类别；两门在范围内的课共用一个代码时，这个代码的每一项都带上 `course_id`，`duplicate_codes` 也列出共用它的 `course_ids`；每个院系内按课程代码排序。列里不合格式的值只计数，不列出。按院系的统计包括字段类别、目录描述、回答警告、先修和同修条款的解析状态、学时比较。
2. `docs/data-coverage-report.md`（新）：运行方法、各原因码、读哪些列、报告结构、各节规则、和应用的差别、明细、不能证明什么；`docs/answer-grounding.md` 加一句指向它。

第 1 条中，下面这些是审查后改的（见「审查」）。第一轮：
- 先读表结构；
- 文本工厂和 BLOB 的读法；
- `.env` 文件名和 SQLite 版本的检查；
- 看每一处的 `complete`；
- 每个块的分母和规则；
- `duplicate_id` 和 `catalog_lists_none` 两个类别；
- 按院系分组的明细；
- 项目 ID 不合格式就不列出。

第二轮：
- 读行之前的 `quick_check`；
- ID 至少要有一个字母；
- `text_not_utf8` 和 `rows_with_text_not_utf8`，标记按字节比较；
- 先修代码按规范形式比较；
- 分母名的规则，几条规则的措辞；
- 按院系的目录描述、回答警告、同修和学时比较，更多的明细类别，共用代码旁的 `course_id`。

第三轮：
- 完整性检查从 `quick_check` 换成 `integrity_check`，检查本身报文件损坏也算没通过；
- 年度要求相邻两年；
- `duplicate_codes` 带上共用代码的 `course_ids`，明细按课程代码排序；
- 不是合法 UTF-8 的 `course_id` 仍是键，被排除课程的坏行在明细里按它自己的代码列出；
- 空白的目录先修代码不算列出的代码；
- 规则和文档里关于分母、和应用的差别、完整性检查读什么的说法。

### 修改文件

| 文件 | 修改 |
|---|---|
| `scripts/audit_data_coverage.py`（新） | 报告本身 |
| `tests/test_audit_data_coverage.py`（新） | 见验证记录 |
| `docs/data-coverage-report.md`（新）、`docs/answer-grounding.md`、本文件 | 见上 |

### 验证记录

- 只用测试自己建的临时库（`db/init.sql` 加合成数据），没有打开任何真实库。
- 修复前，用仓库外审查目录里的一个复现脚本，在 `8c0e987` 上把两路报告的每条结论都复现了一遍；修复后用同一个脚本再跑：
  - 生成列 `generated_json AS (raw_text)`：修复前，`raw_text` 里的课程 JSON 被解码、算在范围内，`complete: true`；修复后 `courses` 是 `not_checked`（`table_not_plain`）。同名的 FTS5 虚拟表原来就会失败（`read_outside_allowlist`），现在同样是 `table_not_plain`。
  - 无主键的 `courses` 里两行同一个 `course_id`：修复前 `in_scope` 是 3、分母是 2，最后一行胜出；修复后两行都是 `duplicate_id`。
  - 一门课、一份快照、一份文档、一个方案存成 BLOB：修复前报告可用 7／2／2／2，应用实际给出 8／3／3／3；修复后两边都是 8／3／3／3。
  - 只删 `programs`、`course_prerequisites`、`program_required_courses`、`schema_versions` 中的一张：修复前退出码都是 0；修复后都是 2，`programs` 不在时 `program_plans` 整节 `not_checked`。
  - `programs` 里的自由文本和 5,000 字符的 ID：修复前原样出现在默认输出里；修复后不出现。
  - NULL 键：修复前，NULL `course_id` 的快照行算作「被排除课程的行」，项目按不同的 ID 数算（2）；修复后快照行算孤儿行，项目 3 行里 2 行是 `id_unusable`。
  - 仓库自己的目录夹具（210 门课，都有可用快照）：修复前学分 `missing` 26、先修 `missing` 127，其实全是目录本身没写；修复后这些都是 `catalog_lists_none`，`missing` 为 0。
  - `snapshot_rows`：修复前 9 行里只说明了 2 行的去处；修复后是 7＋1＋1。
  - 30 个院系各 20 门课、`--max-codes 25`：修复前明细只列到前两个院系；修复后每个院系都列。
  - 一个不是合法 UTF-8 的 `generated_json`：修复前 `courses` 整节 `database_error`，后面四节 `not_checked`；修复后只算这一行。
  - 超过 10 万字符的合法快照：修复前后都是 `oversize`，应用照样挂上。这是有意保留的差别，写进了文档，也有测试钉住。
- 测试文件：`81c4395` 时 71 个（审查目录的 README 原来写 72，是数错了），修复后 124 个。覆盖：
  - 计数、分母和规则：每节输出里的每个名字都有规则，规则里也没有多余的名字；每个块能相加的都相加得上（三种数据各跑一遍）。
  - 没查与查了：每张表单独删掉，`complete` 都是 false，对应部分有原因码；生成列、FTS5 虚拟表、视图、缺列；目录快照一节没查成时，学分和先修代码是 `not_checked`。
  - 和应用一致：文本和 BLOB 两种存法下，可用的课程、快照、文档、方案数都等于仓库实际给出的数；缺失和学分冲突逐门课对照 `course_answer_evidence`；超长快照这一处差别也钉住了。
  - 规则的每个分支：
    - 身份的每一个组成部分：`course_id` 列、代码列、快照代码、文档 `course_id`、文档代码、方案 ID、校区；
    - 合成记录的两种认法，未知的 status；
    - 按范围和按 ID 的重复方案，方案的坏 JSON、坏记录和超长；
    - 描述证据的三种状态，同修条款未解析；
    - 一端在范围外的旧先修边，重复和 NULL 的项目 ID；
    - 不是合法 UTF-8 的值，跨多行的日期范围。
  - 隐私与只读：
    - 允许读的列按文档原样钉住，并核对文档里的表、实际读到的列都正好是这些；
    - 授权回调装在 PRAGMA 之后、`BEGIN` 之前，一次 PRAGMA 都没经过它；
    - 新进程里的文件写入、网络、子进程、`.env*`、第二个数据库、加载扩展，即使代码自己吞掉了异常，也会在 stderr 留下记号。
  - 输入与原因码：目录、0 字节、各种 `.env` 名字、悬空的旁文件链接、读不了、打不开、SQLite 太旧、不是 SQLite 库；行数预算的边界、VM 步按间隔计数、脚本自身出错时的退出码。
- 全量：`81c4395` 时 3264 passed；rebase 到 `9fd3c61` 之上、审查修复后 3357 passed（第 16 批的 3233 加这里的 124）。
- 变异检查：每个变异体在 /tmp 下由 `git archive HEAD` 加 worktree 改动组成的独立副本里，跑这个测试文件。
  - 审查前：81/81 被杀（第一次 79/80，存活的是审计中途预算用完时那一节的原因码，补了测试；后来又加了 1 个）。
  - 审查后 176/176 被杀（第一次 161/162，没杀的那个是变异体本身写坏了：删掉一行留下空的 `if` 块，改成 `pass` 后被杀）。组成：
    - 审查前的 81 个，按修改后的代码改写；
    - B 报告存活的非等价变异体，逐个对应到新代码，名字后面括号里是它的编号；
    - 每处修复几个。
- ruff 0.5.0（F/E9/B）对改动的 .py 文件：干净；没有 CR、没有权限位改动。

第二轮修复：
- 修复前，用两路审查自己的探针在 `3e26027` 上把每条结论都复现了一遍（A2 七个、B2 六个）；修复后在改过的工作区上再跑同一批探针：
  - `programs`、`program_required_courses` 的根页指向用户表 b-tree 的副本：修复前每张表都是 `present`、`complete: true`、退出码 0，默认输出里有 3 个合成的用户 ID；修复后 `database_integrity_failed`、退出码 1，输出里没有任何 ID。
  - 一份快照存成不是合法 UTF-8 的 TEXT：修复前它的 `catalog_snapshots` 一节和明细，与把它换成 `'{not json'` 的副本完全相同，而应用的 `get_batch` 对包含这门课的整批都失败；修复后它单独记成 `text_not_utf8`，明细里能找到。一份方案存成这样，修复后也是 `text_not_utf8`。
  - 同一门课两个不同的坏年度（主键还在）：修复前 `duplicate_rows: 2`；修复后两行都是 `text_not_utf8`，`duplicate_rows: 0`。
  - 存储的先修代码写成 `CS5004`、`cs5004`，目录写 `CS 5004`：修复前 `catalog_conflict`；修复后 `catalog_consistent`。
  - 分母的名字：修复前 7 个没有规则（14 处里的 8 处）；修复后都有。
  - 孤儿方案出现在课程页、`course_context` 先去草稿再查重复、规则全部建模的 partial 方案和记了审核人的 draft 方案、名字只差大小写的表：报告的做法不变（前两项是有意保留的差别，最后一项宁可不查），规则和文档改成照实说。
- 另外我自己发现一处：改成「ID 至少要有一个字母」之后，方案模型本身仍接受纯数字的方案 ID，而可用方案和重复方案的明细直接用模型里的 ID，没有过这一关。现在三处都过，测试里加了这两种情况，以及一门纯数字 ID 的课和别的课共用代码时 `course_id` 记为 null。
- 测试文件：124 个 → 170 个。新加的覆盖：
  - 页被共用的副本在读任何一行之前就被拒绝；纯数字的 ID（项目、方案、可用和重复的方案、课程）只计数、不列出；ID、年度、课程代码的格式边界（前缀、长度、开头的连字符、首尾空格）；
  - 每一节的 `text_not_utf8`、每个块的 `rows_with_text_not_utf8`；和重复快照同时出现时仍归 `text_not_utf8`；坏值按字节比较；
  - 先修代码的规范形式；方案的路径、方向、年度列各自都比；
  - 院系合计；分母名的规则；
  - 预算的边界（60 秒、5 亿步、按间隔计数）、SQLite 3.37.0、BLOB 解码、课程 JSON 的预算、某节的 `database_error`、命令行的 `--max-codes` 0／500／501；
  - 没有快照时的明细、重复的项目 ID、`present` 去重、孤儿方案在课程页可见；
  - 新进程守卫在四种情形下跑（查完、表缺失、某节失败、参数错误），看得到 ATTACH 和被吞掉的动作；FTS5 和视图分开测。
- 全量：3403 passed（第 16 批的 3233 加这里的 170）。第一次跑全量时，变异检查正同时占着 16 个进程，`tests/test_answer_evidence_view.py` 里一个 Streamlit 测试超过了它自己的 45 秒上限；机器空下来后，单独重跑这个文件和再跑全量都通过。
- 变异检查：239/239 被杀，第一次就全杀。组成：审查后的 176 个（9 个的锚点按新代码改写）；第二轮新加 63 个，每处修复一个或几个，加上 B2 存活的 29 个非等价变异体按新代码改写（名字后面括号里是审查者的编号）。另外把 11 个副作用变异体单独对新进程守卫跑一遍：11/11 都由守卫自己发现。
- ruff 0.5.0（F/E9/B）：干净；没有 CR、没有权限位改动。

第三轮修复：
- 修复前，用审查者自己的探针在 `5c1b8e5` 上把每条结论都复现了一遍（A3 进度文件里的四条、A3b 的七条、B3 的六个探针）；修复后在改过的工作区上再跑同一批探针：
  - `programs` 和用户表互换 b-tree 的副本（每页只用一次，NOT NULL 列都有值）：修复前 `quick_check` 通过，默认输出里有两个字母开头的合成用户 ID，退出码 0；修复后 `database_integrity_failed`，输出里没有 ID。
  - 截掉一半或最后一页的副本：修复前 `database_error`；修复后 `database_integrity_failed`。
  - 年度 `0012-3456`：修复前作为年度列出；修复后记 `unrecognized`。
  - `duplicate_codes`：修复前只列代码；修复后带上共用它的 `course_ids`。
  - 课程行和快照行共用一个不是合法 UTF-8 的 `course_id`：修复前快照行算孤儿行；修复后算被排除课程的行。
  - 合成课程的坏快照行、坏先修文档行：修复前只计数、明细里找不到；修复后按它的代码列出（没有课程行的孤儿行计入 `unlisted_malformed`）。
  - 目录先修代码只有空白项：修复前算 `catalog_only`，`prereq_codes_listed` 是 1；修复后是 `catalog_lists_none` 和 0。目录 `["CS 5800", ""]` 对记录 `["CS 5800"]`：修复前 `catalog_conflict`，修复后 `catalog_consistent`。
  - `--max-codes 3` 时，两门课共用的 CS 5001 排在所有单独的代码后面、被截掉；修复后排在前面。
  - 名字只差大小写的表、坏的 `primary_name`、应用挂了报告不用的快照、`course_context` 一次只读一个年度：报告的做法不变，规则和文档改成照实说。
- 测试文件：170 个 → 210 个。新加的覆盖：
  - 互换 b-tree 的副本、两种截短的副本；NOT NULL 列里的 NULL 让整份不报（已知限制），只读打开时 CHECK 约束不查；
  - 年度要相邻两年；`duplicate_codes` 的 `course_ids`；每个列表都给共用代码的课带上 `course_id`，只和被排除课程共用的代码不算共用；共用代码旁的课程 ID 整个核对，100 个字符也能列出；以数字开头、但有字母的 ID；
  - 每张表里任何一列的坏 UTF-8 都最先判断（在孤儿、范围、重复之前），BLOB 不算坏 UTF-8；坏的 `course_id` 仍是键；被排除课程的坏行列出，代码列不合格式时不列；
  - 空白的目录代码；目录一侧的代码也规整；`catalog_lists_none` 列出；没和目录比时院系块里没有目录的部分；院系的目录描述省略 0；明细按课程代码排序；
  - 相加测试：按院系的每个类别加起来等于全节的数，每个院系的课程数和 `courses` 一节一致；规则检查也在缺表和有坏值的报告上跑；
  - 预算在完整性检查之前装好；
  - 新进程守卫在 13 种情形下跑：原来的四种，加上完整性检查不过、不是 SQLite 库、打开时预算用完、副本中途变了、有旁文件、副本不存在、某节的 `sqlite3.Error`、行数预算、脚本自身出错。
- 全量：3443 passed（第 16 批的 3233 加这里的 210）。
- 变异检查：293/293 被杀，第一次就全杀（16 个进程，31 分钟）。组成：第二轮之后的 239 个（其中 9 个的锚点按第三轮的代码改写，意图不变）；第三轮新加 54 个：A3 四条结论 7 个，B3 存活的 39 个非等价变异体按新代码改写，按代码排序 2 个，A3b 和 B3-M1 的修复 6 个（名字后面括号里是审查者的编号）。跑的途中又把一行过长的代码折了行，这一行上的两个变异体折行后重跑：2/2。副作用变异体单独对新进程守卫跑一遍：20/20 都由守卫自己发现（第三轮加了 9 个，每个拒绝或失败分支一个）。
- ruff 0.5.0（F/E9/B）：干净；没有 CR、没有权限位改动。
- B3 量过：测试文件（170 个测试时）跑一次在临时目录里留下约 158 MB，每份种子副本约 2 MB；pytest 默认保留最近三次。

### 审查

两路只读审查，看 `14f0b5c..81c4395`：A 看正确性、隐私和与应用的一致，B 看测试、变异体与文档。两路都不派生子 agent、不改仓库、只用自己建的临时库，都完整跑完。进度文件、探针和变异脚本放在仓库外。两份报告的每一条我都在 `8c0e987` 上复现过，都成立，都已处理。

- **A（正确性与隐私）**：0 CRITICAL、0 HIGH、4 MEDIUM、4 LOW。
  - 中：
    - 生成列能绕过授权回调：SQLite 算生成列时不问回调它读了哪些列，也不检查里面的函数。所以精心构造的副本里，`raw_text` 会被读出来、算进报告。生成列只能读同一张表，碰不到用户表。改成读行之前先看表结构，见「已实现」。
    - 没有主键时，同一 `course_id` 的几行被重复计数，最后一行悄悄胜出。改成 `duplicate_id`，一行都不用。
    - `usable` 比应用严：BLOB 里的 JSON 算坏 JSON；快照、课程 JSON、方案有应用没有的长度上限；重复行应用会用。改成和应用一样读 BLOB，上限按存储长度算；超长和重复行保留报告自己的做法，在规则和文档里写清和应用的差别。
    - 节里有一部分没查，也是 `complete: true`、退出码 0：`programs` 不在时孤儿行记 0、孤儿方案算可用；旧数据表或 `schema_versions` 不在时也一样。改成看每一处的 `status`：`programs` 不在时方案一节整个 `not_checked`，`schema_versions` 不在时给出 `not_checked` 标记。同一类的小问题：目录快照没查成时，学分和先修代码的目录类别记 0；现在这两个字段整个标 `not_checked`。
  - 低：
    - 项目 ID、方向名原样输出：现在只列格式合格的 ID，方向只说有没有；
    - NULL 键：现在算孤儿行或 `id_unusable`；
    - 几处文档和代码不符：目录比较那句话、`.env*`、指向当时还不存在的第 17 节、README 的测试数；
    - `with_complete_plan` 读起来像项目整体完整：改名 `with_any_complete_plan`，规则写明是任一年度或路径。
  - 它核对过没问题的：
    - 除上面两处外，各类别相加得上；缺失和学分冲突与回答路径一致；
    - 授权回调在 SQLite 3.45.1 上拒绝 `count(*)`、`rowid`、`sqlite_master.sql`、视图、LIKE、PRAGMA、ATTACH、递归查询、COMMIT；虚拟表都失败关闭；
    - 文件名不能注入连接参数；不写、不建旁文件、不建库、拒绝符号链接、不联网，原因码都是固定文字；
    - 20 万行、219 MB 的副本 12.7 秒跑完。
- **B（测试、变异体与文档）**：0 CRITICAL、0 HIGH、3 MEDIUM、6 LOW；另外它自己写的 140 个变异体里，71 个非等价的存活。
  - 中：
    - 嵌套的 `not_checked` 不影响 `complete`，同 A；
    - 学分和先修的 `missing` 把「目录比过、本来就没写」和「没有可用快照」混在一起：加了 `catalog_lists_none`；
    - 「每个计数都有分母和规则」只对顶层 `counts` 成立：现在每个块都有，`snapshot_rows` 相加得上，测试逐层检查。
  - 低：
    - 明细是按字母顺序取的样本，排在后面的院系永远列不到：改成按院系分组，另外列出缺描述的快照、存储值与自己证据不一致的课程，先修解析状态也按院系给出；
    - 隐私测试拿脚本自己的允许列表来比：改成钉住文档里的表，视图测试断言回调确实被调用了；
    - 新进程守卫看不到被吞掉的尝试和不在名单里的动作：改成先往 stderr 写记号，名单放宽；
    - 一个坏 UTF-8 值让整节失败：用文本工厂解决；
    - 几处文档遗漏：数据库级的原因码和上限、`.env*`、顶层 `report` 键、第 17 节；
    - `usable` 和应用并不完全相同：文档改写，`answer-grounding.md` 那句也改了。
  - 存活的变异体：每个非等价的都补了测试，并收进审查后的变异检查。
  - 它核对过没问题的：
    - 各测试确实因测试名所说的原因失败；`field_category`、学分比较和 JSON 解码的变异体都被杀；
    - 倒序、乱序、和相邻测试文件交替、8 进程并行、逐个单独跑都通过；
    - 文档里的预算、列表、原因码、类别顺序、限制和明细内容与代码一致；
    - 路径处理正确：符号链接、上级目录的链接、`.env.local`、悬空的 `-wal` 链接、目录、0 字节。
- 两路都没法检查的：真实的库；SQLite 3.45.1／Python 3.12.3 以外的版本（BLOB 上的 `json_valid()`、生成列的行为可能不同）；Windows 的 UNC／junction 路径。

第二轮：两路只读审查，看 `9fd3c61..3e26027`：A2 看正确性、隐私和与应用的一致，B2 看测试、变异体、文档和报告有没有用。条件和第一轮相同（不派生子 agent、不改仓库、只用自己建的临时库），两路都完整跑完。两份报告的每一条我都用它们自己的探针在 `3e26027` 上复现过，都成立，都已处理。

- **A2（正确性与隐私）**：0 CRITICAL、0 HIGH、1 MEDIUM、5 LOW、1 NIT。
  - 中：构造或损坏的副本能让允许的名字读到用户表的数据。把 `programs`、`program_required_courses` 的根页指向用户表的 b-tree，结构检查和授权回调看到的都是允许的名字，于是合成的用户 ID 出现在默认输出里，退出码 0；`PRAGMA quick_check` 能查出这种被引用两次的页。改成读行之前先跑 `quick_check(1)`，不是 `ok` 就整份不报；文档写明这些检查都按名字，真正的边界是输出过滤。另外 ID 至少要有一个字母才会列出。
  - 低：
    - 孤儿方案：`course_context` 不查 `programs`，有效且 `source_checked` 的孤儿方案课程页照样显示。写进规则和「和应用的差别」。
    - `duplicate_scope_or_id` 的规则说 `course_context` 一个都不用；其实它先去掉草稿再查重复，孪生方案是草稿时仍会显示那份 `source_checked` 的。规则改成照实说。
    - 所有坏 UTF-8 值共用一个标记，同一门课两个不同的坏年度被算成重复行。标记改成带上原始字节，只有字节相同才相等；这种行现在也在查重复之前单独归类。
    - 先修代码集合没按代码格式规整，`CS5004` 和 `CS 5004` 算冲突。改成按规范形式比较。
    - 坏 UTF-8 的行（应用读到时整条查询失败）和普通坏行分不开：同 B2 的中，见下。
  - NIT：名字只差大小写的表或列记作缺失，宁可不查。保留，写进规则、文档和「已知、未处理」。
  - 它核对过没问题的：
    - WITHOUT ROWID 和 STRICT 表、提到 `raw_text` 的表达式索引和部分索引：计数不变，`raw_text` 没被读；未知模块的虚拟表记 `not_plain`；
    - BOM、控制字符、重复键、大整数、NaN、各种嵌套深度：报告和应用的判断一致；6000 门随机课程上缺失和学分冲突与回答路径 0 处不同；
    - 输出里的每个值都追过：只有格式合格的代码、ID、年度、校验过的范围字段、计数和固定文字。
- **B2（测试、变异体、文档与有用程度）**：0 CRITICAL、0 HIGH、1 MEDIUM、8 LOW；它自己写的 172 个变异体里，127 个被杀，29 个非等价的存活。
  - 中：应用整条查询都会失败的坏 UTF-8 行在报告里找不到：它们落进 `invalid_json`、`orphan_rows`、`identity_mismatch` 这些普通类别，和真的坏 JSON 分不出来。新加类别 `text_not_utf8`（课程、先修文档、方案最先判断，目录快照排在 `absent` 之后），其他块另有不互斥的 `rows_with_text_not_utf8`，明细里能找到。
  - 低：
    - L1 共用标记造成的假重复：同 A2；
    - L2 文档和规则的说法：快照和应用的差别不止「两处」、漏了孤儿方案、`partial` 和 `draft` 的规则说过了头、分母的名字没有规则。都改了，测试也查分母的名字；
    - L3 相加测试不查院系合计：加上了，三节的院系合计都要等于全节的数，每个年度按院系的可用文档数也要加得上；
    - L4 新进程守卫只看正常路径、看不到 ATTACH：守卫现在也在表缺失、某节失败、参数错误时跑，并包装 `sqlite3.connect` 装上语句跟踪，看得到 ATTACH；
    - L5 格式和身份的边界没测：前缀匹配、长度、开头的连字符、`strip`、方案的路径／方向／年度列都加了测试；
    - L6 其他缺的针对性测试：预算边界、BLOB 解码、课程预算、SQLite 3.37.0、某节的 `database_error`、CLI 的 501、没有快照时的明细、重复的项目 ID、`present` 去重；
    - L7 报告有没有用：两门课共用的代码在明细里带上 `course_id`；按院系补了目录描述、回答警告、同修和学时比较；字段明细列出除 `catalog_consistent` 以外的每个类别；
    - L8 FTS5 测试和视图测试拆开。
  - 存活的变异体：29 个非等价的都补了测试，按新代码改写后收进变异检查。它的 G34 就是 L1 的修法；G32 的 `fields.categories` 已经删掉，改成一个把它加回来的变异体。
  - 它核对过没问题的：改过的代码里 `_layout`、`_all_checked`、`_text` 和 `.env` 检查的变异体全被杀；各测试确实因测试名说的原因失败；倒序、乱序、重复跑、和相邻测试文件一起跑、并行跑都通过；文档里的原因码、类别顺序、上限、列的表、限制和明细内容与代码一致。
- 两路都没法检查的：真实的库；SQLite 3.45.1／Python 3.12.3 以外的版本；Windows 的 UNC／junction 路径。A2 只用构造的结构演示了页被共用，没验证复制到一半的文件会不会出现这种情况。

第三轮：看 `5c1b8e5`。A3 看正确性、隐私和与应用的一致，B3 看测试、变异体、文档和报告有没有用；条件和前两轮相同（不派生子 agent、不改仓库、只用自己建的临时库）。A3 两次被 API 的安全过滤拦下（第二次是我让它接着看剩下的部分时；接着看会重新载入它的全部记录，所以没有再试），没有最终报告，结论在它的进度文件里；它没看完的部分另起 A3b，用一份不含改写表结构的探针的独立提示来看。每一条我都用审查者自己的探针在 `5c1b8e5` 上复现过，都成立，都已处理。

- **A3（正确性与隐私；进度文件里的四条，都是低）**：
  - 互换两张表的 b-tree（每页只用一次）能过 `quick_check(1)`，字母开头的用户 ID 于是进了默认输出（它自己评为低到中）。`integrity_check` 查得出表和自己的索引对不上，改用它；但一份一致地重建过的文件任何检查都能过，所以文档写明真正的边界是输出过滤。
  - 截短的副本让检查本身报 SQLITE_CORRUPT，原来记成 `database_error`；现在是 `database_integrity_failed`。
  - 年度只看 `\d{4}-\d{4}`，`0012-3456` 这样的会出现在默认输出里：现在和应用一样要求相邻两年。文档里输出的内容也补上了日期。
  - `duplicate_codes` 只列代码，规则却说带 `course_id`：现在列出共用它的 `course_ids`。
- **A3b（A3 没看完的部分）**：0 CRITICAL、0 HIGH、0 MEDIUM、6 LOW、1 NIT。
  - F1 文档说名字只差大小写的表应用照样能读，其实目录快照、先修文档、方案这三张表应用自己也当作没有：文档改成照实说。
  - F2 不是合法 UTF-8 的 `course_id` 即使 `courses` 里有同样的键也算孤儿行：现在按字节当作同一个键。
  - F3 被排除的课程（比如合成课程）的坏快照行不归任何类别、明细里找不到，而应用照样会读到这门课、整批失败：现在按它的代码列出，先修文档的这种行也列出。
  - F4 坏值在 `primary_name`、`status` 时报告排除这门课，应用照样给出：这时报告更保守，规则和文档改成照实说。
  - F5 `fields` 里几处说和回答路径一致，应用挂了报告不用的快照时并不一致：改成「用报告认可的快照」，指向重复和超长两处差别，并写明 `program_seed_unverified` 不计。
  - F6 空白的目录代码算作列出的代码，「照原样比较」的说法也不准：空白项不算，说法改成「转成大写、去掉多余空白后比较」。
  - NIT F7 `duplicate_scope_or_id` 的规则漏了 `course_context` 一次只读一个年度：补上。
  - 它核对过没问题的：830 份随机混合的副本（每个读的列都放坏 UTF-8，加上 NULL 键、BLOB、重复、孤儿、坏 hash、合成和改名的课）上每节都查了，测试里的相加检查全过，独立重算的 15 个计数都对得上；分类顺序；几条关于应用行为的规则；`complete` 和退出码。
- **B3（测试、变异体、文档与有用程度）**：0 CRITICAL、0 HIGH、1 MEDIUM、7 LOW、几条 NIT；它自己写的 103 个变异体里，64 个被杀，39 个非等价的存活。
  - 中 M1：范围外或孤儿课程的坏 UTF-8 行只计数，`--details` 里找不到（同 A3b 的 F3）。现在能读出代码的都列出，读不出的计入 `unlisted_malformed`。
  - 低：
    - L1 `duplicate_codes` 不带 `course_id`：同 A3 的第四条；
    - L2 按院系截断时，带 `course_id` 的项按 JSON 文本排在所有单独的代码后面，最先被截掉：改成按课程代码排序；
    - L3 坏值在应用不读的列时报告比应用严：同 A3b 的 F4；
    - L4 新进程守卫只跑四条路径，其他拒绝和失败分支里的副作用看不到：守卫现在跑 13 种情形，每个这样的分支各有一个副作用变异体；
    - L5 几处第二轮的行为没有测试：见「验证记录」第三轮的测试清单；
    - L6 文档说「每一组计数都写明分母」「按院系的合计也加得上」，比代码和测试说得多：文档改成照实说；测试补上按院系逐类相加，原来那条目录的院系检查是同义反复，改成和 `courses` 一节比；
    - L7 `_codes` 的退路不是「照原样」：同 A3b 的 F6。
  - NIT：`answer-grounding.md` 那句改成 `missing`、`catalog_only`、`catalog_lists_none` 合起来才是 `missing_fields`；采集日期范围不算在相加的那几组里；`test_null_ids_name_nothing` 打开明细、加了一行 NULL 方案 ID；文档写明完整性检查读每一页，但什么都不输出；临时目录的大小记在验证记录里。
  - 它没法检查的一条我补查了：完整性检查也报告 NOT NULL 列里的 NULL，这样的副本整份不报（写进文档，测试钉住）。CHECK 约束 SQLite 不给只读打开的库加载：同一份文件读写打开时两种检查都报 CHECK 失败，只读打开时都是 `ok`。所以存着应用不会写的 JSON 的行照常逐行计数，和 SQLite 版本无关。
  - 存活的变异体：39 个非等价的都补了测试，按新代码改写后收进变异检查。
  - 它核对过没问题的：本节记的测试数；64 个被杀的变异体都是针对它的测试先失败；第二轮的测试改动只加强、没有放松；倒序、乱序、重复跑、并行跑、和相邻文件一起跑都通过；文档里的原因码、类别顺序、上限、读的列、限制和明细内容与代码一致。
- 三路都没法检查的：真实的库；SQLite 3.45.1／Python 3.12.3 以外的版本；Windows 的 UNC／junction 路径。

### 已知、未处理

1. 超长的值（快照 10 万、课程 JSON 100 万、方案 20 万字符）不解码。应用对快照、课程和 `list_for_program` 没有上限，所以这几类报告可能少算；给应用加上限不在本批。
2. 缺键的副本里，重复行报告一个都不用，和应用不同：应用用最后一个有效的，或者都显示；`course_context` 先去掉草稿再查重复。
3. 不是合法 UTF-8 的 TEXT：报告把那一行单独记成 `text_not_utf8`，明细里能找到（被排除课程的坏行也列出），其余照常统计；应用读到它时整条查询失败，同一查询里的其他行也拿不到。这时报告比应用乐观，文档里提示这类行最先修。坏值在应用答题不读的列（`primary_name`、`status`）时正相反：报告排除这门课，应用照样给出。
4. `--details` 没有按院系筛选的参数；每个院系每类最多 500 项。
5. 没在真实数据上跑过；只在 SQLite 3.45.1／Python 3.12.3 上测过；Windows 路径只靠共用的发布预检逻辑。
6. 不读查询热度，所以不给富化优先级。这是路线图的后续，需要另行授权。
7. 孤儿方案：报告不算可用，课程页的方案上下文却会显示有效且 `source_checked` 的孤儿方案。要不要让应用也查 `programs`，不在本批。
8. 名字只差大小写的表或列：报告记作缺失、这一部分不查。目录快照、先修文档、方案这三张表应用自己也当作没有；`courses` 这类表应用照样能读，这时报告比应用保守。宁可不查，不会把没查的写成查过。
9. 检查都按名字：一份结构完好、只是有人把别的数据抄进允许的列里的副本，报告照样会读。完整性检查查得出页被共用、表和索引对不上、文件被截断，查不出一份一致地重建过的文件。最后一道边界是输出只列格式合格的值。
10. NOT NULL 列里有 NULL 的副本（只有损坏或手工改过的文件才会有）整份不报，不按行计数。
11. 先修代码的 `catalog_conflict` 也包括「目录一个代码都没列、记录里有」（规则写明了），所以目录文本没被解析成代码的课也会落进来；要分开，可以再加一个子计数，不在本批。

### 发布状态

- 本地分支 `feat/data-coverage-report`，已在第 16 批的 `9fd3c61` 之上，两批在同一个分支；没有 push，没有 PR，等用户要了再开（两批一个 PR）。合并由用户点。
- 只新增离线脚本，和部署无关；本批没有动生产数据，也没在真实库上跑过。

## 18 — 聊天回答用上按 Catalog 年度的先修规则（OPT-04 第一步，提示词 4.4，2026-10-09）

### 范围与原因

- OPT-03 之后按路线图做 OPT-04 的第一步。课程详情面板早就显示按年度记录的先修／共修文档（`course_requisite_documents`：AND/OR 树、最低成绩、可并修、未解析的条款），聊天却只拿到平铺的 `prereqs` 代码列表和 `prerequisite_logic_unavailable`，所以记录里明明有「CS 5001 或 CS 5004（B- 以上），并且 DS 5110」这样的规则，回答也说不出来。这一步把这些规则作为有来源的说明接进聊天；把精确的培养方案身份（校区／Catalog 年度／路径）加进请求是下一步，不在本批。
- 分支 `feat/chat-structured-requisites`，从第 17 批的 `3e26027` 开出；第 17 批的第二轮审查修复 `5c1b8e5` 提交后，快进到它上面（两边改的文件不重叠），再让 OPT-03 的报告和 4.4 对齐。
- 10-10 第 17 批的第三轮审查修复 `7ad7e65` 提交后，本批 rebase 到它上面。报告脚本、它的测试、`docs/data-coverage-report.md`、`docs/answer-grounding.md` 四个文件有冲突，两边的改动都保留；第三轮新加的一个测试（空白的目录先修代码）在本批里要先删掉 CS 5200 的年度文档，否则它的先修归 `year_rules`，不再和目录比。
- 没有用真实模型检查回答（要付费调用，需要另行授权），没有用真实数据，没有部署。

### 已实现

1. 证据（`schemas/answer_evidence.py`、`rag/answer_evidence.py`）：`CourseAnswerEvidence` 新增 `requisites`（没查时为 `None`，旧调用方和已存历史的输出不变）。
   - `RequisiteEvidence`：`storage`（`available`／`schema_missing`／`schema_unusable`）、`editions`（可用文档，按年度从新到旧，最多 `MAX_REQUISITE_EDITIONS` = 3 份；新的在前只是限量，不替学生选年度）、`editions_omitted`、`unusable_records`。每份 `RequisiteEdition` 有年度、官方院系页 `catalog_url`、页面保存时间 `captured_at`，以及先修、共修两段：状态、规则树（只有 `parsed` 有）、最多 `CLAUSE_LIMIT` = 600 字符的原文和截断标记、未解析原因；未解析的一段另带整段原文的 SHA-256 `clause_sha256`（审查 A18-F3 加的，不进提示词）。模型校验年度不重复且从新到旧、表不可用时没有文档、只有超过上限才有省略数、每段的状态和内容一致（未解析的一段原文可以为空：课程块的标签后面没有条款时解析器就这样存，审查 A18-F1 改的）、没截断的原文和摘要一致。
   - `requisite_evidence(course, documents, unusable)`：文档的课程 ID、代码、名称和被回答的课一致才用；同一年度不止一份（只有缺键的副本里才会有）时这一年度一份都不用，计入 `unusable_records`。证据块表达不了的文档也计入这里并记一条日志，一份记录不会让整个回答失败（审查 A18-F1 改的）。
   - `course_answer_evidence(..., requisites=...)`：有可用年度文档时，`prereqs` 不算缺失，也不再有 `prerequisite_logic_unavailable`。新提示码：`requisites_differ_by_catalog_year`（列出的年度规则不同；未解析的一段按整段原文的摘要 `clause_sha256` 比，第 600 字以后才不同也算，审查 A18-F3 改的）、`requisite_clause_unparsed`（有一段没解析）、`structured_requisites_unusable`（有文档不可用，或表读不了）。没有可用年度文档时和 4.3 相同，只是有不可用的文档或表读不了时多一个 `structured_requisites_unusable`（审查 A18-F5 改的说法）。
   - `build_answer_evidence` 用新的 `CourseRequisiteRepository.read_batch`：一次回答的所有课用两次查询读完，核对和课程详情接口相同（课程行的代码和名称、年度、内容 hash、规则树）；读出错时回答照常给出：整批查询失败就逐门课再读，只有自己的行读不了的课是 `schema_unusable`、按旧逻辑，其他课照常（审查 A18-F4 改的）。
2. 提示词 4.4（`llm/prompts/chat_v4.py`）：
   - **历史措辞更新说明**：下条保留首次实现的记录；第二轮已改为引用任何年度（包括最新记录）都提醒 live 页面，原文为空或仅有空白均保留。第三轮进一步明确 live 提醒每个回答只说一次、不按课程／规则重复。旧的「最新一份以外」和「原文为空」不是当前契约。
   - 每门课的 `catalog_requisites`：每个年度一项（年度、`catalog_url`、`captured_at`、先修、共修），`editions_not_shown` 是没列出的份数。规则树写成 `all_of`／`any_of`／课程叶，只带原文写明的最低成绩、可并修和 level；不给未解析原因（内部代码）、原文摘要和来源摘要。
   - 有年度规则时去掉 `recorded_metadata.prereqs` 和目录快照的 `prereq_codes`：课程页在年度规则旁边也不显示旧的平铺图。
   - 规则：只有学生在对话里说了 Catalog 年度，才把那一年的规则当成学生的，入学学期不是 Catalog 年度；没说时，各年度相同就说明覆盖哪几年，不同就简短说明并问学生；学生说的年度这里没有时，说明这些记录里没有那一年的规则，不拿别的年度代替（审查 A18-U1 加的）；`all_of`／`any_of`、嵌套、成绩、可并修、level 照原样，共修不是要先修完的课；`not_listed` 不证明没有要求，`unparsed` 照记录给出原文（原文为空表示标签后面没有条款）并说要核对；不说学生有资格、满足了要求或能注册；`structured_requisites_unusable` 时不能把任何年度当成没有要求；引用方式和目录描述相同，存档副本那句每个回答仍只说一次；链接打开的是院系页现在的样子，引用最新一份以外的年度时要说明页面可能已是更新年份的规则（审查 B18-L4 加的）。
3. 接口和界面：`/chat` 的 meta 和 `GET /course/{course_id}` 带同一份 `answer_evidence.requisites`。证据面板给新提示码配了完整和简短两种文字，简要卡片里也显示；卡片多一行「先修规则：已存 Catalog … 的课程块原文」，只读通过校验的数据块。课程详情面板去掉了「此规则未用于对话回答」，改成说明对话回答最多引用最近 3 个已记录年份的规则、更早的只计数（审查 A18-F6 改的），课程先修列表的 `warnings` 去掉了 `structured_requisites_not_used_by_chat`。
4. 评测：`eval/answer_checks.py` 不许回答印出新提示码；`scripts/eval_answers_live.py` 从课程详情接口的 `answer_evidence.requisites` 构造和聊天相同的证据，年度文档的 URL 算允许的链接，只有确实给了平铺列表的课才要求说明 AND/OR 不明。
5. OPT-03 报告和聊天对齐（`scripts/audit_data_coverage.py`）：报告的字段类别和 `answer_warnings` 也调用 `course_answer_evidence`，原来不给年度规则，所以有可用年度文档的课，报告仍算先修缺失、仍算 `prerequisite_logic_unavailable`，和聊天不一致。现在：
   - `requisite_documents` 一节在 `fields` 之前运行，给每门在范围内的课按聊天的方式构造年度先修证据：报告的可用文档和这门课不可用的行数交给 `requisite_evidence`，结果和 `read_batch` 加 `requisite_evidence` 相同：重复行也逐行核对后交给 `requisite_evidence`，同一年度只有一行通过时用它，几行都通过时这一年都不用（审查 A18-F2／B18-M1 改的：原来在解码前就把重复行都排除，只有一行有效时和聊天不同）；这门课有不是合法 UTF-8 的行时给 `schema_unusable`，和聊天的查询失败时一样。
   - 先修的新类别 `year_rules`，最先判断：有可用年度文档时，回答给出那一年的规则，不用存储的代码列表，所以先修既不算缺失，也不和目录比；`missing`、`catalog_only`、`catalog_lists_none` 加起来仍正好是聊天的 `missing_fields`。明细不列这一类。
   - 先修文档一节没查成时，先修和 `answer_warnings` 标 `not_checked`（新原因码 `requisite_documents_not_checked`）。表不存在时除外：那时聊天一条年度规则都没有、和 4.3 相同，所以照常统计（审查 A18-F7 改的：运行库还没有这张表，原来报告在运行库的副本上会丢掉这两项）。
6. 文档：`docs/answer-grounding.md` 的 4.4 一条和 OPT-03 那句话；`docs/course-requisites.md` 文末「聊天回答中的年度规则」；`docs/program-plans.md` 一句；`docs/data-coverage-report.md` 的字段类别、原因码和 UTF-8 那一处差别。

### 修改文件

| 文件 | 修改 |
|---|---|
| `schemas/answer_evidence.py` | `RequisiteEvidence`、`RequisiteEdition`、`RequisiteSectionEvidence` 和两个上限；`CourseAnswerEvidence.requisites` |
| `db/course_requisite_repository.py` | `RequisiteBatch`、`read_batch`；列表警告去掉 `structured_requisites_not_used_by_chat` |
| `rag/answer_evidence.py` | `requisite_edition`、`requisite_evidence`、新提示码与缺口规则；`build_answer_evidence` 读年度文档 |
| `llm/prompts/chat_v4.py` | 4.4 |
| `app/answer_evidence_view.py`、`app/course_requisite_view.py` | 新提示码的文字、简要卡片、「先修规则」一行；详情面板的说明 |
| `eval/answer_checks.py`、`scripts/eval_answers_live.py` | 见「已实现」第 4 条 |
| `scripts/audit_data_coverage.py` | 见「已实现」第 5 条 |
| `tests/test_chat_structured_requisites.py`（新）、`tests/test_audit_data_coverage.py`、`tests/test_chat_v4_prompt.py`、`tests/test_answer_grounding.py`、`tests/test_course_requisite_view.py` | 见验证记录 |
| `docs/answer-grounding.md`、`docs/course-requisites.md`、`docs/program-plans.md`、`docs/data-coverage-report.md`、本文件 | 见上 |

### 验证记录

- 只用测试自己建的临时库和记录提示词的模型替身；没有真实模型调用，没有打开真实库。
- `tests/test_chat_structured_requisites.py`（新，32 个，审查后 44 个）覆盖：
  - 缺口和提示码：有年度规则时两项缺口都不成立；年度从新到旧、超过 3 份只计数；规则不同才标（嵌套相同不算，只有共修变了也算，未解析的一段按原文比）；未解析的先修或共修都标；
  - 原文：未解析的保留原文、没有规则树；600 字符的边界，截断时规则树仍完整；
  - 不用的文档：核对不过的计数、不使用；文档的代码或名称和被回答的课不同、课程 ID 不同、没有课程行、文档不是文本；每门课只拿自己的文档；同一年度两份时一份都不用；没有表或表读不了时回到 4.3 的回答；模型拒绝不一致的数据块；
  - 提示词：规则用提示词解释过的词写出，未解析原因不进提示词，有年度规则时没有平铺列表，`editions_not_shown` 进提示词，规则的 12 句关键句逐条钉住；
  - 接口和界面：聊天 meta、课程详情和提示词用同一份年度规则；规则读不了时聊天照常回答；新提示码有文字、不许印出；证据卡片只从通过校验的数据块里取年度；在线评测从课程详情构造出和聊天相同的提示词。
  - 审查后新加：空条款照记录给出，聊天和课程详情不再返回 500；证据块表达不了的文档只丢这一份、下一份补上；长的未解析条款按整段比较；SQLite 读不了的值（在课程行或文档行）只影响自己那门课；B18 的 15 个存活变异体各有测试（重复年度时的省略数、同一规则换种写法、较早年度的不同和未解析、别的课的文档、课程行的代码和名称、证据模型的几个上限、没有年度时不显示年度那一行）；提示词新钉住 7 句（空原文、学生说的年度没有记录、链接是现在的页面、各年度相同、照原样保留、不在内的几项、读不了时不当成没有要求）。
- `tests/test_audit_data_coverage.py`：170 个 → 175 个（rebase 到第三轮修复之后是 210 个 → 215 个，审查后 221 个）。种子数据里 CS 5800、CS 5200、AAI 6600 有可用的年度文档，它们的先修从 `catalog_consistent`／`catalog_only`／`missing` 变成 `year_rules`，`prerequisite_logic_unavailable` 从 4 门变成 2 门，新提示码 `requisite_clause_unparsed` 1 门、`structured_requisites_unusable` 5 门；明细和按院系的数相应改了。新加：
  - 和聊天对照：直接用聊天的 `build_answer_evidence`（每门课一批），逐门课核对缺口和学分冲突，并在四种情形下（原样、存成 BLOB、两个年度规则不同、一行文档不是合法 UTF-8）核对整节的 `answer_warnings`、每个字段的缺口数和 `year_rules` 的数；
  - `year_rules` 最先判断、只用于先修，没有可用年度时照旧；
  - 先修文档表缺失时，先修和 `answer_warnings` 照常统计、和聊天（每门课 `schema_missing`）一致；表是视图或缺列时这两项是 `requisite_documents_not_checked`；学分和目录描述照常。
- `tests/test_chat_v4_prompt.py`、`tests/test_answer_grounding.py`：版本号和新键。
- `tests/test_course_requisite_view.py`：审查后加 1 个，课程页的说明只说聊天拿得到的年度。
- `tests/test_audit_data_coverage.py` 审查后新加：和聊天对照的情形加了重复年度只有一行有效、两行都有效、空条款；先修文档表是视图或缺列时先修不算、表不存在时照常算；表读不了时目录比较照常统计，快照也没查成时两个标记以目录在前。
- 全量：3440 passed（第 17 批 `5c1b8e5` 的 3403，加新测试文件的 32 个和报告测试新加的 5 个）。rebase 到 `7ad7e65` 之后：3480 passed（第 17 批 7ad7e65 的 3443 加这里的 37）。审查修复后：3499 passed（3480 加审查后新加的 19 个：聊天先修 12 个、报告 6 个、课程页 1 个）。
- 变异检查：每个变异体在 /tmp 下由 `git archive HEAD` 加 worktree 改动组成的独立副本里跑。
  - 4.4 本身：52 个，跑上面的聊天、提示词、依据、证据面板和在线评测 5 个测试文件。在 `3e26027` 上第一次就 52/52；快进到 `5c1b8e5`、加上对齐之后重跑，仍是 52/52（8 个进程：证据面板的测试里有一个 45 秒上限的 Streamlit AppTest，负载太高时会超时，超时会把变异体误算成被杀）。
  - rebase 到 `7ad7e65` 之后重跑：4.4 的 52 个 52/52（8 个进程）；OPT-03 对齐的 20 个 20/20。
  - OPT-03 对齐：20 个，跑报告的测试文件：不给年度规则、`year_rules` 不判断或对所有字段都判断、没有年度也算、警告不带年度规则、`fields` 排回 `requisite_documents` 之前、坏 UTF-8 的课仍有年度规则或只算不可用、不可用的行不计数、可用文档丢掉、原因码写错、年度文档没查成时仍统计先修或警告、按院系的描述和警告各自的条件、两个 `not_checked` 标记的先后、明细列出 `year_rules`、规则缺失。20/20 被杀，第一次就全杀。
  - 审查修复后重跑（8 个进程）：4.4 的变异体从 52 个加到 88 个（审查修复的 F01–F13、E25、R07–R10，以及 B18 存活变异体按新代码改写的 G01–G17 和 L4 那句的 G18；测试文件加上课程页的），88/88；OPT-03 对齐的从 20 个加到 26 个（A21–A26），第一次 22/26：A15–A18（目录描述和目录比较的条件、两个 `not_checked` 标记的先后）原来靠「先修文档表不存在」造出年度规则没查成的情形，A18-F7 之后表不存在照常统计，就分不出这四个了；改用读不了的表（视图、缺列）补了测试后 26/26。E06、E15–E18、E20–E23、R05、A08、A09 按新代码重新定位。
- ruff 0.5.0（F/E9/B）对改动的 .py 文件：干净；没有 CR、没有权限位改动。

### 审查

两路只读审查，看 `7ad7e65..3b7d4d3`：A18 看正确性和与课程详情、OPT-03 报告的一致，B18 看测试、变异体、文档和有用程度。两路都不派生子 agent、不改仓库、只用自己建的临时库，都完整跑完；进度文件、探针和变异脚本放在仓库外。两份报告的每一条我都核对过，都成立，都已处理（A18 未证实的一条也处理了）：行为上的问题用审查者自己的探针在 `3b7d4d3` 上复现，修复后同一批探针不再复现；B18 的 15 个存活变异体按新代码改写后，在补测试之前的代码上确实都存活；文档的几处对照了代码。

- **A18（正确性与一致）**：0 CRITICAL、1 HIGH、0 MEDIUM、6 LOW，另有 1 条未证实。
  - 高 F1：课程块里「Prerequisite(s):」标签后面没有条款时，解析器存的是 `unparsed`、原文为空（`empty_clause`），课程详情面板照常显示；新的证据块却要求未解析的一段原文非空，于是 `/chat` 和 `GET /course/{course_id}` 返回 500，OPT-03 报告的先修文档一节整节失败。这是本批引入的回归。改成和已存的 `RequisiteSection` 同样的规则（原文不是 `None` 即可，可以为空），提示词说明空原文的意思；证据块表达不了的文档计为不可用，不再让整个回答失败。
  - 低：
    - F2 缺键的副本里同一年度两行、只有一行有效时，聊天用那一行，报告一行都不用：改成报告跟着聊天，见 B18 的中。A18 建议反过来让聊天也整年不用；没采纳，因为课程详情接口（`list_for_course`）本来也用那一行，聊天和课程页保持一致。
    - F3 未解析的条款按截到 600 字的原文比较，第 600 字以后才不同的两个年度不算不同：改成按整段原文的 SHA-256 比较。
    - F4 一次回答里有一门课的课程行或年度文档有 SQLite 读不了的值（不是合法 UTF-8），整批查询失败，所有课都拿不到年度规则：改成整批失败后逐门课再读，只有自己的行读不了的课算 `schema_unusable`。
    - F5 文档说没有可用年度文档时和 4.3 完全相同，其实有不可用的文档或表读不了时多一个 `structured_requisites_unusable`：文档改成照实说。
    - F6 课程页的说明说聊天会按年份引用这些规则，选了聊天拿不到的更早年度时也这样说：改成最多引用最近 3 个已记录年份。
    - F7 先修文档表不存在时报告把先修和 `answer_warnings` 标 `not_checked`，可运行库现在还没有这张表，那时聊天和 4.3 相同：改成表不存在时照常统计；表是视图或缺列时仍是 `not_checked`。
  - 未证实 U1：学生说了一个这里没有记录的 Catalog 年度时，提示词没说怎么办：加了一句，说明这些记录里没有那一年的规则，不拿别的年度代替。
  - 它核对过没问题的：`read_batch` 和 `list_for_course` 用同一个解码，BLOB、整数和类型不对的 hash 两边判断一样，文档不会混到别的课；从新到旧、最多 3 份和省略数；聊天的四种检索路线都从 `CourseRepository` 取课；有可用年度时的缺口和提示码；4.4 的规则块只在 JSON 数据里，规则叶只带 `RequisiteNode` 的字段，内部代码和摘要都不进提示词，每句规则和文档一致；聊天历史保留整个数据块；证据卡片只读通过校验的数据块；在线评测构造出和聊天相同的证据和提示词，测试不联网。
- **B18（测试、变异体、文档与有用程度）**：0 CRITICAL、1 HIGH、1 MEDIUM、4 LOW；它自己写的 52 个变异体里，37 个被杀，15 个非等价的存活（每个都跑过全量 3480 个测试）。
  - 高 H1：同 A18 的 F1。
  - 中 M1：同 A18 的 F2，变更记录和代码注释都说两边结果一样。报告的年度规则现在把重复行也逐行核对后交给 `requisite_evidence`，和 `read_batch` 加 `requisite_evidence` 相同；`duplicate_rows` 的计数不变。和聊天对照的测试加了这几种情形。
  - 低：
    - L1 两处文档和代码不符：第一处同 A18 的 F5；第二处 `course-requisites.md` 说证据不给未解析原因，其实证据块里有，只是不进提示词：改成照实说。
    - L2 一门课的标题不是合法 UTF-8 时，同一回答的所有课都丢了年度规则（同 A18 的 F4，这里经由课程行的标题）；`data-coverage-report.md` 还说聊天只读 `generated_json`：现在给年度规则时还读课程行的代码和名称，文档改成照实说。
    - L3 15 个存活的变异体：每个都补了测试，按新代码改写后收进变异检查（G01–G17，其中两个是同一处的变体）。
    - L4（有用程度）每个年度的链接都是同一个院系页，打开的是现在的页面，可能已经是更新年份的规则：提示词加一句，引用最新一份以外的年度时说明这一点；文档同步。
  - 它核对过没问题的：本节记的测试数和文件表；12 句关键句都在；没有 CR，权限位只有新测试文件的 100644；报告和聊天逐门课对照，在 BLOB、5 个年度、只有较早年度有未解析的一段、hash 坏的文档、两行都有效的重复年度、不是合法 UTF-8 的行这些情形下一致；`year_rules` 最先判断，两个 `not_checked` 标记设得对、先后对，`complete` 和退出码对；BOM、NaN、单独的代理字符报告和应用都拒绝。
- 两路都没法检查的：真实模型（不许付费调用）；真实数据里有没有空条款和缺键的副本；那一行在真实浏览器里的样子。B18 还指出 `eval/answer_checks.py` 没有针对 4.4 的检查，见「已知、未处理」；它的环境没有 ruff，我这边查过。

### 已知、未处理

1. 没有用真实模型检查 4.4 的回答（要付费调用，需要用户另行授权）。提示词里的年度规则是否被模型照原样说出，只有记录提示词的替身测过。
2. 请求里没有 Catalog 年度、校区、路径字段；学生没说年度时，回答只能说明覆盖哪几年或问学生。聊天页要不要加 Catalog 年度选择，等用户决定（现在加，或和下一步的培养方案身份一起）。
3. 培养方案的规则（`program_plans`）还没接进聊天；不判断个人资格，不做学期安排。
4. 一门课的课程行或年度文档有不是合法 UTF-8 的值时，这门课拿不到年度规则（`schema_unusable`，回答照常、按旧逻辑）；批量查询失败后逐门课再读，同一次回答里的其他课不受影响（审查 A18-F4 改的：原来整批都拿不到）。OPT-03 的报告按每门课单独算，标出的也是那一门课。
5. 每门课最多给 3 个年度，更早的只计数。
6. `eval/answer_checks.py` 还没有针对 4.4 的检查：回答没写 Catalog 年度、说学生能注册，都标不出来。这里的检查都是用真实回答调出来的，要等用户授权付费调用、拿到 4.4 的真实回答再加（审查 B18 提的）。
7. 年度规则的链接是院系页现在的样子：来源地址只能是院系页本身（`CourseRequisiteSource` 只接受这种地址），没有各年度存档页的地址。第二轮收口后，引用任何年度规则（包括最新记录）都要求提醒一次，不能用 newest 证明页面还是那一年的规则；要链接到存档页，得先核实存档地址、放宽来源和链接的校验，不在本批。

### 发布状态

- 本地分支 `feat/chat-structured-requisites`，在第 17 批的 `7ad7e65` 之上；没有 push，没有 PR，等用户要了再开。合并由用户点。
- 改了聊天提示词（4.4）、证据契约和界面，下次部署时一起生效；部署由用户决定。本批没有动生产数据。

### 第二轮审查收口（批次 A，2026-10-11 开始，2026-10-12 收口）

**范围与原因**：按用户指定的 `ROUND_PLAN_2026-10-11.md` 执行本轮 A，以 `1c2bb26` 为起点。读取 A18b、B18b 原始报告与 progress 后在独立副本复现；原报告不是本轮新审查，未新开审查 agent。原始输出和本轮 WORKLOG 在仓库外保存，不公开合成输入之外的真实数据。

**审查**：A18b 原报告为 0 CRITICAL／0 HIGH／1 MEDIUM／6 LOW 和一条 minor；B18b 为 0 CRITICAL／0 HIGH／0 MEDIUM／6 LOW。合并后的十项按下列方式收口：

1. 报告课程级覆盖与遗留清单改按实际提供给聊天的年度规则（`editions` 非空）判断；重复年度和年度状态仍按行统计。有效+坏 hash 的重复、有效+非 UTF-8 行这两种方向都与聊天一致，并核对 `--details` CLI 输出。
2. 4.4 要求引用任何记录年度时提醒链接打开当前目录，可能已显示更新年份，不再豁免最新记录；不改版本号，因为 4.4 未部署。
3. 回答检查器在实时链接提醒里去掉否定的「不是存档副本」，不误计为第二条存档说明；真正重复、同句肯定来源、分号和链接带 URL 的情况继续保留。
4. 同步报告规则文字、三份说明文档和 evidence docstring：课程身份列、缺表／缺列／视图、重复年度、partial 证据范围均照实际行为写；不全局替换快照／方案仍然成立的重复行规则。
5. 课程页按解码后有效文档的年度分组：同年只有一份有效则保留，两份有效则全部弃用并计入 unusable。两个课程 GET 入口返回 200，与聊天的年度与不可用计数一致，其他年份保留。
6. 提示词解释 `requisites_differ_by_catalog_year`：截断文本相同也不能说规则相同；「各年相同」分支要求该提示不存在，完整证据与摘要不改。
7. 课程页隐藏聊天专用的最近三年摘要和三条短警告，完整年度选择器、规则面板和来源折叠区的完整警告保留；聊天卡片照常显示其使用年份。
8. 三条新短标签改为先修/共修；只描述旧先修列表逻辑的标签不改。
9. 对原来存活的九个非等价变异补测试：真实合成损坏页的 DatabaseError（R22/R23）、failed section（R36）、两句提示（R33/B32）、digest／reason 约束（R05/B62/B63）和坏 eval 证据块（B67）。原代码在这些点已正确，不把补测试冒充产品修复；B21 的排序变异继续按消费者会排序而视为等价。
10. 仅改提示词说明空或 whitespace-only 原文；不改存档原文、摘要或解析器。两个空标签的换行原文通过独立夹具验证。

**修改文件**：`scripts/audit_data_coverage.py`、`db/course_requisite_repository.py`、`llm/prompts/chat_v4.py`、`eval/answer_checks.py`、`app/answer_evidence_view.py`、`app/course_detail_view.py`、`schemas/answer_evidence.py`、`tests/test_batch18_review2.py`（新）、`tests/test_audit_data_coverage.py`、`tests/test_chat_structured_requisites.py`、三份说明文档及本文件。仓库外另外更新变异框架、必要锚点和本轮验证记录；原始报告／probe 输出不覆盖。

**验证记录**：

- 修复前旧包重核：88/88 + 26/26，全部有明确 FAILED 测试身份，0 SUSPECT／0 survivor／0 ERROR；不是只看 pytest 退出码。分类器 7 个合成用例通过，逐条杀死测试表在仓库外保存。
- 原始 A18b probes：12 passed、1 failed，失败为重复年度课程页；B18b probes：21 passed，其中部分断言验证旧缺陷而非新验收。中英重复说明、截断差异和 SQLite 数据页探针另有输出。
- 新保护测试在未改产品代码的副本使九个原 survivor 全部被明确测试杀死（9/9）。初版 whitespace 夹具调用了会规范化空白的 parser，已更正；更正后的测试在 `1c2bb26` 失败于缺少提示句，不将夹具错误计为产品缺陷。
- 定向九文件：539 passed、18 warnings（xdist 6 workers，包含重复的 SWIG 弃用提示）；最终新回归文件单跑：33 passed、3 warnings。此后未再改产品实现。
- 全量离线：3532 passed、5 warnings，522.20 秒；三条 SWIG 与两条 HTTP 422 名称弃用提示。与变异并行运行，不把此耗时当成性能基准。
- 修复后变异：107/107 + 29/29，全部有明确 FAILED 测试身份，0 SUSPECT／0 survivor／0 ERROR；136 项逐条杀死测试表与各项完整 pytest 输出保存在仓库外，未以退出码代替失败身份。
- 改动 Python 文件 ruff 0.5.0 F/E9/B 通过；14 个改动文件无 CR，`git diff --check` 通过。文档实际本地目标存在；行内代码里的 `[标签](URL)` 示例不当作真实链接检查。

**已知、未处理与发布状态**：本节既有七条边界继续保留；纯启发式检查不证明真实回答质量。本轮没有模型调用、生产数据操作、真实账号／浏览器验收或部署；尚未合并，等待用户指定评审。批次 C／D 以及合并和部署不因本轮测试自动完成。

### 第三轮审查收口（2026-10-12）

**范围与原因**：第三轮审查的对象是 `f2ebf2c`，审查员 A18c 加主评审一遍，报告在仓库外（`REVIEW_2026-10-12.md` 的 A 节）。修复由用户按那份清单执行，主评审复核后补本节记录并提交。

**审查**：A18c 的结论是 0 CRITICAL／0 HIGH／0 MEDIUM／5 LOW，另有一条本批之前就存在的问题；主评审另报一条 LOW（按年度的课程覆盖仍按行计）。第二轮的十项确认是在代码里修好的，不只是加了测试。逐条处理如下：

1. 按年度的课程覆盖：`by_catalog_year[年度].courses_in_scope_covered` 和院系的 `with_usable_document` 改为每个年度单独用 `requisite_evidence` 判断。只有这一年恰好一行通过核对和证据投影、这门课的行也都读得出来时，才算覆盖。所有记录过的年度都算，不受聊天最多 3 个年度的限制。逐行质量和条款状态仍按行计。规则文字，以及 `docs/data-coverage-report.md` 里 `year_rules`、`in_scope_courses`、`by_catalog_year`、`by_department` 的说明，同步改了。
2. `fields.by_department.answer_warnings` 的规则文字补回「目录核对过」这个条件：目录核对完成，且（年度规则已检查或先修文档表不存在）时才输出。文档同步。
3. 回答检查器认得的实时链接写法扩大了：
   - 链接可以写成 link、URL、链接，也可以是官方目录的 Markdown 链接或裸 URL；
   - 动词加了 goes to、takes you to、shows、看到、显示；时间词加了 today、目前、最新；
   - 否定加了 instead of、isn't、is not、并非、（非…），以及「那份」「这份」这类限定词。
   - 20 种合规写法各有测试；真正重复两次的说明仍计 2。`docs/answer-grounding.md` 写明这只是有限的表达式识别。
4. 文字跟上实际行为：
   - `answer-grounding.md` 和 `schemas/answer_evidence.py` 的注释改成「空或只有空白」；
   - 本节「已实现」加了一条历史措辞说明；
   - `structured_requisites_unusable` 的完整标签和卡片上的年份行改成「先修/共修」。
5. 删掉已经没有地方读的 `self.documents`；提示词改成 "say so once per answer (not once per course or rule)"。
6. A18c 的 8 个存活变异体各补了测试：
   - 检查器模式里的 rather than、而非、points to、url 各有独立用例；
   - 卡片默认显示年份行；
   - 课程页的来源折叠区保留三条完整警告；
   - "Never say those years have the same rule…" 这句钉住了。
7. 本批之前就有的问题：课程详情的身份查询挪进了 `try`。`primary_name` 不是合法 UTF-8 时，`GET /course/{id}` 和 `/requisites` 返回 200，先修列表为空并带 `structured_requisite_schema_unusable`，和聊天给的 `schema_unusable` 一致。
8. 变异包：第 2 轮的 9 个变异体原来是运行时从审查员的临时文件夹读的，现在直接写进包里。

**修改文件**：`scripts/audit_data_coverage.py`、`db/course_requisite_repository.py`、`llm/prompts/chat_v4.py`、`eval/answer_checks.py`、`app/answer_evidence_view.py`、`schemas/answer_evidence.py`、`tests/test_batch18_review3.py`（新）、`tests/test_batch18_review2.py`、`tests/test_audit_data_coverage.py`、`tests/test_chat_structured_requisites.py`、`docs/answer-grounding.md`、`docs/data-coverage-report.md` 及本文件。

**验证记录**：

- 新回归测试：
  - 初版 36 个在 `f2ebf2c` 上跑，23 个失败、13 个通过；通过的是第 6 条那些原本行为就对的保护测试，靠对应的撤回变异体证明它们能抓到问题。
  - 最终 41 个全过。
- 定向 9 个文件（清单在仓库外的工作记录里）：577 passed，之后又加了 4 个不同写法的用例。
- 全量离线：3573 passed、5 warnings。用户那次 658.79 秒，是和变异测试一起跑的；主评审在独立快照上又跑了一次，3573 passed，284 秒。
- 变异：129/129 + 34/34，每个都有明确的失败测试，0 SUSPECT，0 存活。A18c 的 8 个和第 2 轮的 9 个都在包里，全部被杀死。
- ruff 0.5.0（F/E9/B）通过；13 个改动文件都没有 CR，`git diff --check` 通过。

**已知、未处理与发布状态**：同上一轮。检查器仍然只认有限的写法，别的自然语言写法可能漏判或误判。没有调用模型，没有动生产数据，没有用真实账号或浏览器验收，也没有部署；只在本地提交，未合并。

## 19 — 代码精简 SIM-01：一模一样的小函数只留一份（2026-10-11）

### 范围与原因

- 用户 2026-10-11 的代码精简计划（`docs/code-simplification-plan-2026-10-11.md`，和检阅路线 `docs/project-review-and-roadmap-2026-10-11.md` 一起放在 main 的工作区，还没有入库）建议的第一批：先合并明确重复的小型纯函数，不改任何行为。
- 分支 `refactor/sim01-shared-helpers`，从 main 的 `751c6b1` 开出。第 16–18 批还在 `feat/data-coverage-report`、`feat/chat-structured-requisites` 两个分支上、没有合并，所以这一节排在 19。这一批改的文件和它们没有重叠：第 18 批改过的 `schemas/answer_evidence.py` 这次不动。
- 只合并函数体、报错文字和调用方式都完全一样的副本。看起来像、但报错文字或对空值的处理不同的，原样保留，见「已知、未处理」。

### 已实现

1. 逐行 L2 归一化：PyTorch／FlagEmbedding（`rag/embedder.py`）、ONNX（`rag/onnx_backend.py`）、OpenVINO（`rag/openvino_backend.py`）三个后端各有一份一模一样的 `_l2_normalize`，现在只留 `rag/vectors.py` 的 `l2_normalize`（只依赖 numpy）。三个后端用原来的私有名字导入它，调用处不变；`scripts/rehearse_recovery.py` 和 6 个测试文件照旧从 `rag.embedder` 导入 `_l2_normalize`。
2. 课程代码：`schemas/program_plan.py` 的 `normalize_code` 和 `CourseRequisiteDocument.canonical_code` 的函数体和报错（`Invalid course code`）完全一样，现在都用 `schemas/course.py` 的 `canonical_course_code`（放在 `COURSE_CODE_PATTERN` 旁边）。`program_plan.normalize_code` 这个名字保留，`schemas/course_program_context.py` 照旧从那里导入。
3. 规范 UTC 时间：`FeedbackCandidate` 和 `QueryLogExportRow` 的 `utc_timestamp` 函数体完全一样，现在都调用 `schemas/feedback_candidate.py` 的 `canonical_utc_timestamp`；`query_log_export` 本来就从那里导入 `text_sha256` 和两个类型。字段、装饰器、报错文字都不变。

### 修改文件

| 文件 | 修改 |
|---|---|
| `rag/vectors.py`（新） | `l2_normalize` |
| `rag/embedder.py`、`rag/onnx_backend.py`、`rag/openvino_backend.py` | 删掉各自的副本，以 `_l2_normalize` 导入共用的 |
| `schemas/course.py` | 新增 `canonical_course_code` |
| `schemas/program_plan.py`、`schemas/course_requisite_document.py` | 用 `canonical_course_code`；`normalize_code` 成为它的别名 |
| `schemas/feedback_candidate.py`、`schemas/query_log_export.py` | 新增 `canonical_utc_timestamp`，两个校验器调用它 |
| `tests/test_shared_normalizers.py`（新） | 见验证记录 |
| 本文件 | 本节 |

### 验证记录

- 先写行为特征测试 `tests/test_shared_normalizers.py`，在没改动的 `751c6b1` 上跑，33 个全过：
  - 三个后端的归一化对同一组输入给出相同结果：float32、形状不变、零行保持为零、整数输入、空输入、一维输入报错、不改原数组；
  - 培养方案和先修文档对同一组课程代码（大小写、首尾空白、制表符、结尾字母，以及 9 种不合格的写法）给出相同结果和相同报错；
  - 两份导出 schema 对同一组时间文本（合法、能解析但写法不规范、根本不是时间）给出相同结果，写法不规范时报错文字也相同。
- 合并之后同一批 33 个仍全过；另加 2 个：每个旧名字都指向唯一的定义；新进程里导入 `rag.vectors` 不加载 torch、ONNX Runtime、OpenVINO 等模型运行时。共 35 个。
- 导入了这几个模块的 62 个测试文件：2027 passed（6 个进程）。
- 全量：3175 passed（main `751c6b1` 上是 3140，加这里的 35 个）。
- 变异检查：13 个，跑新测试文件和 `tests/test_embedder.py`：零行不再保护、不转 float32、按列归一化、导入时加载 torch；课程代码不去空白、不转大写、报错文字改了、去掉空格；时间只解析不核对写法、时间报错文字改了；三处调用改成不校验。13/13 被杀，第一次就全杀。
  - 审查更正：「导入时加载 torch」那个（V04）其实是在收集测试时就失败了。这个 venv 里 `import torch` 本来就失败（缺 `libcudnn.so.9`），onnxruntime、OpenVINO 也没装，所以它不是被「不加载模型运行时」那条断言杀死的。审查后换成了替身变异，见「审查」。
- ruff 0.5.0（F/E9/B）对改动的 .py 文件：干净；没有 CR、没有权限位改动。
- 只用测试自己建的数据；没有真实模型调用，没有打开真实库，没有在真实的 ONNX／OpenVINO 后端上跑（三个后端现在调用的是同一个函数对象，函数体也和原来一样）；没有改任何模型参数。

### 审查

2026-10-12，一路只读审查（SIMr1，同时看 SIM-02），看 `751c6b1..9a80be5`，不派生子 agent，不改仓库；主评审也看了一遍。报告在仓库外。

- **结论**：0 CRITICAL、0 HIGH、0 MEDIUM、2 LOW、1 处零碎，行为和 main 一致。
  - 每份删掉的副本和共用的那份，函数体和报错文字都相同；装饰器和校验模式没动。
  - 所有别名和导入方都还能解析，包括 CI 会跑的 `scripts/rehearse_recovery.py`；改过的模块里已经没有地方再读 `COURSE_CODE_PATTERN` 或 `datetime`。
  - 新文件 `rag/vectors.py` 会进 Docker 镜像。
  - 它重跑了 33 个特征测试（在 main 上）、62 个相关测试文件（2027）、全量（3175）和 13 个变异体，数字都对得上。
- **都成立，都已处理**：
  1. 低：测试只把校验函数当普通函数调用，没测它挂在模型字段上。把 `schemas/feedback_candidate.py` 装饰器里的 `'feedback_updated_at'` 删掉，3175 个测试照样通过；这个缺口在本批之前就有。现在 `tests/test_shared_normalizers.py` 对两份导出 schema 的 5 个时间字段各有一个模型层面的用例：用真实导出器写出一行，能通过校验；把其中一个字段换成不规范的写法，就必须报 `Canonical UTC timestamp required`。
  2. 低：变异体 V04 没证明它看起来证明的东西（见验证记录里的更正）。现在换成替身变异：导入 `rag.vectors` 时往 `sys.modules` 里放一个假的 `torch`，由「不加载模型运行时」那条断言杀死。
  3. 零碎：`schemas/query_log_export.py` 第 7 行的 import 有 103 个字符，超过 100 列，拆成了多行。同一文件第 72、74 行也是 103 个字符，main 上就有，不是本批带来的，没动。
- **审查后的验证**：
  - `tests/test_shared_normalizers.py` 有 40 个用例（原 35 个，加 5 个模型层面的）；相关的 4 个测试文件 272 passed。
  - 变异 18/18，每个都由明确的失败测试杀死：原来的 13 个（V04 换成替身），加 5 个新的：从装饰器里分别删掉 4 个反馈时间字段，去掉查询日志导出的 `created_at` 校验器。
  - 全量：3180 passed（3175 加 5）。
  - ruff 0.5.0（F/E9/B）干净；没有 CR，`git diff --check` 通过。

### 已知、未处理

1. 看起来相同、但没合并的：`Course._normalize_code`（报错会带出原值）、`RequisiteNode.canonical_code`（允许空值，报错是 `Invalid requisite course code`）、`CatalogSnapshot.normalize_code`（报错是 `Invalid catalog course code`；第 18 批的分支改过这个文件，等它合并后再看）；先修文档和来源的时间校验（只要求带时区并转成 UTC，报错文字也不同）。要合并它们，得先决定报错文字统一成哪一种，这会改行为，不在纯重构里做。
2. `EMBEDDING_DIM = 1024` 在三个后端各写一次（ONNX、OpenVINO 的注释写明照抄 `rag.embedder`）；计划没列，这次没动。
3. SIM-02（共享检索决策）是第 20 节；SIM-03 起还没开始。

### 发布状态

- 分支 `refactor/sim01-shared-helpers`，从 main 的 `751c6b1` 开出。审查修复后 rebase 到第 18 批的 `637144c` 之上：只有本文件冲突，第 16–19 节按编号排好。rebase 后全量：3613 passed（3573 加这里的 40 个）。随一个 PR 提交，合并由用户点。
- 纯重构，行为不变，不需要单独部署。本批没有动生产数据。

## 20 — 共享检索决策（SIM-02，2026-10-12）

### 范围与原因

从 main `751c6b1` 单独开 `refactor/sim02-retrieval-decision`。第 16–19 节在各自待合并分支上，本节按本轮安排保留编号 20，不代表那些批次已经合并或部署。

`/search` 与 `/chat` 重复维护候选文本读取、calibrated gate、重排融合和临界拒答的 HyDE 救援。抽出共同决策，保持两条接口原有行为；不改变阈值、候选池、融合参数或请求级状态的生命周期。

### 已实现

1. 三个常量移到 `api/routes/common.py`，原值与说明不变。search 保留同名导入；chat 直接从 common 导入，不再依赖 search 模块导出。
2. `RetrievalDecision`：最终 hits、rejected、rejection_reason、rescued 和首次重排 meta。救回后清除最终拒答状态，首次门控元数据仍保留，不把第一次拒答伪装成门控接受。
3. `rerank_with_gate_and_rescue`：一批候选文本、显式传入的初次 diagnostics、原始 query 重排、原有门控概率判断、原有 `attempt_hyde_rescue`。每 pass 只评分一次，救援失败维持初次拒答原因；有效 hard_filters、pool_size 与 top_k 不丢失、不互换。
4. 两条路由的差异不抽走：search 无 reranker 时截断、拒答时早退并记录 max_sigmoid／n_candidates；chat 仅在非空 hybrid 且有 reranker 时进入共享决策，拒答后继续输出 meta／token／done。context／alias／program 入口、空候选与筛选排除仍走原路径；两个 hyde_rescued 事件名各自保留，响应 hybrid 与遥测 hyde_rescued 仍分开。
5. `HybridRetriever` 依赖仍每请求新建，不改成全局单例。共享决策不从 hybrid 读取可被重试覆盖的 last_diagnostics；门构造函数传参，保留既有测试在路由替换 build_gate_fn 的边界。

### 修改文件

| 文件 | 修改 |
|---|---|
| `api/routes/common.py` | 三常量、结果对象与共享决策 |
| `api/routes/search.py` | 调用共享决策；保留拒答日志／早退／遥测／降级 |
| `api/routes/chat.py` | 从 common 导入；保留入口 guard／流式／遥测 |
| `tests/test_retrieval_decision_parity.py`（新） | 抽取前先通过、抽取后保持不变的 46 项路由特征测试 |
| `tests/test_retrieval_decision_helper.py`（新） | 显式诊断、首次 meta、None-only 救援、guard、兼容与请求实例隔离 |
| `tests/test_retrieval_decision_rescue_rules.py`（新，审查后加） | 救援规则、日志字段和耗时；阈值门不需要检索器诊断 |
| `docs/adr/0016-reranker-reject-threshold.md` | 常量所在的模块（审查后改） |
| 本文件 | 范围、验证与未完成边界 |

### 验证记录

- 只用合成内存 SQLite、模型替身和 TestClient。初版特征测试的计时字段／预期排序错误先修正为现有契约，不改产品实现，不把夹具错误当作产品缺陷。
- 抽取前 46 passed、3 warnings；冻结 SHA-256 为 `189f94067cd3b939e8e27999a6a044657b4c7b7a7988a03290948b25b7bd6f54`。抽取后哈希核对通过、测试未改一行；连同既有六文件为 227 passed、5 warnings。helper 单测另有 8 passed、3 warnings。
- 覆盖 alias／context／program、普通 hybrid、无 reranker、空候选、阈值／校准拒答、救援成功／拒绝／异常／空检索／高置信度跳过／无概率属性／code guard、筛选排除／替代课程锚点、k 大于配置池、原 query 与缩写／HyDE 扩写、文本回退；核对 HTTP／NDJSON、query_log、事件名与调用次数。
- 全量离线：3194 passed、5 warnings，285.32 秒；三条 SWIG 与两条 HTTP 422 名称弃用提示。此分支从 main 开，不包含 16–18／SIM-01，测试总数不能与 A 的 3532 直接比较。
- 具名变异：15/15，全部记录明确的 FAILED 测试身份，0 survivor／0 SUSPECT／0 ERROR；门控、高置信度跳过、概率默认值、显式诊断、原 query、救援筛选／pool／top_k、None-only 契约、拒答状态／原因、两条遥测与 chat 入口 guard 均有对应变异。逐条表与完整输出在仓库外保留。
- 改动的 5 个 Python 文件 ruff 0.5.0 F/E9/B 通过；6 个文件无 CR，`git diff --check` 和实际本地文档目标检查通过。
- 10 次预热、75 次测量的替身端点：search median 4.103→3.530ms、p95 4.675→4.085ms；chat median 5.419→4.579ms、p95 6.368→5.164ms。after 在全量／变异结束后执行，没有明显变慢；单轮 sanity check，不宣称统计显著改善或生产性能提升。

### 审查

作者先自行逐段对照了路由和依赖的生命周期，保留了行为对照表和冻结测试。2026-10-12 做了一轮只读审查（审查员 SIMr1，和 SIM-01 一起审；主评审另外核对过），报告在仓库外。

**结论**：没有 CRITICAL 或 HIGH。在 9,904 个场景下和 main 对照了响应、NDJSON、`query_log`、替身调用和去掉耗时以后的全部日志事件，0 处差异；记录里的数字都复现了。问题出在测试强度上，还有一处很小的行为差异：

1. **MEDIUM**：共享函数现在替两条路由管着几条救援规则，测试没有钉住。审查员写的 23 个变异体里有 13 个在作者的 6 个测试文件下存活，其中 6 个连全量都抓不到：
   - 去掉 `rescue_fn is not None` 判断，或者改了它的运算优先级；
   - 救援候选池从 `max(k, RERANK_POOL_SIZE)` 变成 `RERANK_POOL_SIZE`；
   - 救回结果的顺序被打乱；
   - 门槛写死成 0.25。

   处理：新增 `tests/test_retrieval_decision_rescue_rules.py`，覆盖：
   - HyDE 关闭时不尝试救援；
   - 门槛从 settings 读取；
   - k 大于候选池时，救回的结果保持第二轮的完整顺序和分数；
   - `search.rejected` 的字段和耗时、两条 `hyde_rescued` 事件的 `count`，以及 chat 的 `retrieval_ms` 在重排前取值。

   冻结的特征测试文件一行没改。
2. **LOW**：日志和耗时字段以前没有测试，上面的新文件用假时钟覆盖了。
3. **LOW**：两条路由原来在阈值模式下也会读 `hybrid.last_diagnostics`；抽取前只有 calibrated 模式读。换成没有这个属性的检索器，抽取前返回 200，抽取后返回 500。生产不受影响，因为 `HybridRetriever` 在 `__init__` 里把它设成了 `None`。
   - 处理：两条路由改成 `getattr(hybrid, "last_diagnostics", None)`。阈值模式下和抽取前完全一样；calibrated 模式下，这种检索器现在拿到 0 而不是抛异常。没有哪个真实的检索器缺这个属性。
   - 新测试在 `989ae58` 上失败 4 个，在 main 和修复后都通过。
4. **LOW，零碎**：`search.py` 的 `_elapsed_ms` 前面补了一个空行；ADR-0016 改成常量在 `api/routes/common.py`；去掉了本节前面多出来的 `---` 分隔线。

**修复后的验证**：
- 新文件 18 passed（在 main 上也是 18 passed）；连同既有测试文件共 253 passed；冻结测试的哈希不变。
- 全量离线：3212 passed、5 warnings（原来的 3194 加新增的 18 个），342 秒，在独立快照上跑。
- 变异 30/30，每个都有明确的失败测试，0 SUSPECT，0 存活。原来的 15 个之外，新加了审查员的 13 个存活变异体，以及两个"读诊断信息不加 getattr"的变异体。
- ruff 0.5.0（F/E9/B）通过；没有 CR，`git diff --check` 通过。

### 已知、未处理

1. 不处理 SAFE-02 的错误文字／日志字段，也不处理 SIM-03/04、OPT-04 第二步或 OPT-06。
2. chat 的 retrieval_ms 原来在重排前计时，本批保留；统一计时语义会是行为修改，应另批处理。
3. 真模型、真实库、真实浏览器／账号、NAS 负载与生产流量未核验。

### 发布状态

- 分支 `refactor/sim02-retrieval-decision`，从 main 的 `751c6b1` 开出；审查和修复都已完成。之后 rebase 到 SIM-01 之上（第 18 批 → SIM-01 → 本批）：只有本文件冲突，第 16–20 节按编号排好；冻结的特征测试文件哈希不变。rebase 后全量：3685 passed（3613 加这里的 72 个）。随一个 PR 提交，合并由用户点。
- 纯重构，行为不变，不需要单独部署；没有生产数据修改或付费模型调用。

## 21 — SAFE-02：安全错误出口（2026-10-12）

### 上线记录（main `9dff227`，2026-10-12 22:42 UTC 起）

以下引用仓库外 `release_2026-10-12/DEPLOY_RECORD.md`，**不是本批重新执行的线上验证**：PR #6–#11 已上线，#8 包含 OPT-02／03，#9 为 OPT-04 第一步，#10／#11 为 SIM-01／02。新镜像 `442834b18ae0`；回退标签 `neu-compass:rollback-20261012` 指向原镜像 `d8f97df9d1a4`；预发布备份 `runtime-data/backups/prerelease-20261012-224114.db`。备份不能用来直接覆盖仍在写入的生产库。

- ready 6469/6469、Co-op 30 条；培养方案 cs-ms 2／ds-ms 4／info-ms 2／aai-ms 0；政策 12 条。
- test_set_v04 116 条加预热：R@5 0.8628、MRR 0.9341，服务端 p50 822.8 ms／p95 1131.9 ms；和 10-07 的差异记作运行波动，不宣称性能提升。
- `/chat` 检查：CS 第一学期问题为 hybrid 5 条、正常结束，有 `program_schedule_unverified`；CS 5004 先修引用 2026-2027 记录，CS 5001 C- AND CS 5002 C-，CS 5005 单列共修。第一条终端结果曾被脚本吞掉，以 API 日志为依据；另一次乱码重跑是 PowerShell 编码问题，不算产品结果。
- AAI 6600 改为 `Applied Artificial Intelligence` 并补目录快照；命名修复和快照各 1 条，复跑快照新增 0。CS 5200 名称未变。
- 公网只读页面显示 6,469 门课、游客、四个项目、推荐和 Co-op 预览／刷新入口；**用户本人浏览器验收见 D4：仍需真实账号登录／刷新／登出、CS 5004 聊天与详情、AAI 6600 名称核对**。

### 范围与原因

这是有意改变错误响应文字与日志字段的修复，不是纯重构。从 main `9dff227` 独立开 `fix/safe02-error-exits`。合成标记经真实 OAuth exchange、TestClient、ApiClient、AppTest 与 JSON／console 日志证明原有出口缺口。成功请求、检索／门控和聊天流协议保持；状态码的有意变化只有一类：Google 的畸形响应原来会变成未捕获的 500，现在是 401。具体是四种：200 但内容不是 JSON；200 但 JSON 不是对象；4xx 的 JSON 错误体不是对象；email claim 不是字符串。不改主页面编排或 `llm/gemini_client.py` 的日志契约。

### 已实现

| 边界 | 有意的行为变化 |
|---|---|
| 未捕获异常 | middleware 消化、单个安全错误事件和固定 500，共用响应构造函数；兜底不渲染 traceback |
| 日志管道 | 消耗 exc_info，转成类型／原因类型／最多六帧，原因类型不把 Starlette 重抛留下的包装当成原因；第三方 stdlib 任意消息改固定事件，保留级别、logger 名、时间戳、请求关联和安全定位；项目成功事件不删字段 |
| OAuth | 七种 reason、固定公开消息、安全上游状态／错误码与有界小写域名；不展示 Google 描述或完整邮箱；Google 网络故障仍 401 |
| 回显 | 课程／项目 404、delivery_mode 422 不带输入；歧义 409 保留选择，不附异常文字；422 字段名仅接受安全字符且最多 64 字符 |
| 关联 | x-request-id 仅接受安全字符且最多 64 字符，其他换 UUID4；只进头，不增加响应体字段 |
| 遥测／反馈 | query_log 写失败不记录异常原文；反馈存储 503 新增安全诊断 |
| 客户端／登录页 | 5xx／非 JSON 错误文字固定，畸形 2xx JSON 转 502 invalid_response；登录失败固定文字，畸形身份响应（OAuth 回调和 cookie 恢复共用 `valid_identity`）不抛异常或写入半登录状态 |
| 聊天流 | meta 行在响应开始前构造，出错时走 middleware 的安全 500，不在流头之后抛出 |
| 发布配置 | Streamlit 默认只显示类型；完整详情仅可本地显式开启 |

`error_frames` 抽到小模块 `api/error_fields.py`，避免日志导入路由造成循环；common 保留同名导入，原调用路径和 `file.py:LINE function` 格式保留。新 safe_error_fields 独立处理隐式 context，不改变 Gemini 辅助函数。taxonomy 值不改，只补正确说明。

### 修改文件

- 生产：`api/error_fields.py`（新）、`api/logging.py`、`api/exceptions.py`；auth／chat／common／course／feedback／program／search 路由；`app/auth.py`、`app/api_client.py`、`app/streamlit_auth_ui.py`、`app/state_manager.py`、`app/cookie_session.py`（后两个是审查后的修复）；`.streamlit/config.toml`。
- 测试：`tests/test_safe_error_exits.py`（新）；`test_api_auth_route.py`、`test_api_errors.py`、`test_app_auth.py`、`test_app_api_client.py`。
- 文档：本文件、`api_contract.md`、`pii_redaction.md`。两份尚未入库的路线／精简计划只在 main 本地刷新状态，没有混入公开提交。

### 验证记录

- 仅内存 SQLite、占位 key、MockTransport、模型替身及 AppTest，没有读取真实凭证／生产库或付费模型调用。
- 首版 41 项新增测试在未改产品的基线上为 **39 failed／2 passed**；原本正确的是安全 extra 字段名与有效 request ID。另补六项兜底／字段白名单／域名边界测试，合计 47 项。
- 最终 47 项在独立 git archive 的未修改 main 上 **45 failed／2 passed，6 warnings，40.21 秒**；强化后的兜底测试真正覆盖隐式 context，不依赖 Starlette 的 cause 改写。
- 初次十文件定向回归 **157 passed，21 warnings，50.53 秒**（六 worker，包含首版 41 项）；补齐 47 项后的同十文件串行 **163 passed，6 warnings，42.47 秒**。随后 context 测试补强与提示兼容修复见下文，最终产品树另跑全量。
- 有意更新的旧期望：OAuth 拒绝夹具改显式 reason；API OAuth／CourseNotFound detail 改固定文字；Google 400 不再显示 Code expired；ApiClient 500 不再显示服务端纯文本。普通安全 extra 字段名、taxonomy、既有 Gemini／聊天错误、URL OAuth warning 和 verifier 类型诊断保持。
- 首轮全量 **1 failed／3731 passed，7 warnings，534.62 秒**：通用 5xx 提示覆盖了已有 invalid_response 安全固定提示。保留 `502 + invalid_response` 原固定文字后再跑全量，没有放宽缓存测试或改变缓存行为。
- 具名变异最终 **29/29**：25 项首轮有效杀死、三项串行复核、一个新增提示兼容变异，每项都有明确 FAILED 身份。原轮 S18 存活、S21／S23 SUSPECT 均保留记录；S18 补强真正的 context 测试，后两项是框架匹配源码 timeout 参数造成误判，串行复核为 AssertionError／KeyError。本包分类器只匹配实际 pytest E 行，真实超时仍为 SUSPECT。共享框架未改，不混称一次完整 29 项重跑。
- 最后一次变异运行的未变异基线（新增测试／API errors／auth／缓存四文件）**162 passed，5 warnings，35.86 秒**；三项串行复核的基线为 87 passed。
- 最终产品树全量离线 **3732 passed，7 warnings，551.13 秒**（main 原 3685 加新增 47）；警告为三项 SWIG 类型及四次 HTTP 422 名称弃用。没有实时浏览器／账号／NAS 或模型性能验证。
- 改动 18 个 Python 文件 Ruff 0.5.0 F/E9/B 通过；22 个改动文件 CR=0、`git diff --check` 通过，7 个真实本地 Markdown 目标有效。main 两份未跟踪计划文档 CR=0、49 个目标有效，未纳入本批提交。

### 审查

作者先自检：逐项对照 O1–O11、真实日志处理顺序及 middleware 边界。2026-10-13 做了一轮独立只读审查（审查员 A21；主评审另外核对过），报告在仓库外。

**结论**：没有 CRITICAL 或 HIGH。调查列出的泄漏路径都已关闭，并在按 Dockerfile `CMD` 启动的真实 uvicorn 上实测确认：39 个探针在 `9dff227` 上有 9 个响应体带出标记，本批只剩文档允许的 2 处回显；没有数据库记录带标记；成功请求的日志事件两边一致。处理如下：

1. **MEDIUM**：`cause_type` 把框架包装当成了原因。经过真实 middleware 时，没有 cause 的错误记成 `EndOfStream`（Starlette 在 `except anyio.EndOfStream` 里 `from None` 重抛）；流头之后的错误记成 `ExceptionGroup`（`collapse_excgroups()` 在 `except` 里重抛）。
   - 处理：`api/error_fields.py` 跳过这两种包装，显式和隐式原因不变，S18 的 `from None` 期望也保留。只尊重 `__suppress_context__` 的方案修不好流头之后的情况，还会让 S18 失败，所以没有采用。
   - 新测试：仓库错误经 middleware 不再有 `cause_type`；流头之后的错误，有 cause 时报 `ValueError`，没有时不报。
2. **LOW**：`/chat` 的 meta 行在生成器里、`try` 之前构造。出错时 200 头已经发出，uvicorn 会打印带原文的完整 traceback。处理：meta 在返回 `StreamingResponse` 之前构造并序列化，出错走 middleware 的安全 500。新测试覆盖分数转换失败和序列化失败两种情况。文档写明流头之后的异常仍会有 uvicorn traceback。
3. **LOW**：审查员的 14 个额外变异体里有 7 个在相关测试下存活。放到全量下仍有 6 个存活：显式 `exception=` 参数、`log.exception` 的定位、第三方事件的请求关联和定位、Google 非对象错误体、`request.unhandled` 的 status／error_type。非法 request ID 换成常量的那个，只被长度检查顺带抓到。处理：新增对应测试。
4. **LOW**：cookie 恢复在 `/auth/me` 返回畸形 200 时会 `KeyError` 或写入半登录状态（main 上本来就有，与回调同类）。处理：抽出 `state_manager.valid_identity()`，回调和 cookie 恢复共用；畸形响应不登录，保留 cookie，和 API 故障时一样（新测试）。
5. **LOW**：第三方 `stdlib.*` 事件没有 logger 名和时间戳。处理：加上；logger 名是代码里写死的。
6. **LOW，文档**：Google 200 但内容不是 JSON 从 500 变成 401 没有记录，已补到上面「范围与原因」和 API 契约。Streamlit 进程日志和 Python `warnings` 仍会打印原文，已写进「已知、未处理」。`app/auth.py` 一处注释没写完，已修。

**修复后的验证**：
- `tests/test_safe_error_exits.py` 现为 62 项（原 47 项加 15 项）。整个文件放到 `2871822` 上是 **12 failed／50 passed**：失败的是 F1 两项、meta 两项、第三方事件来源一项、cookie 恢复七项；补的旧行为测试在修复前就通过。
- 十二文件定向 **384 passed**（六 worker）。
- 全量离线 **3747 passed，7 warnings，301 秒**（原来的 3732 加新增 15 项），在独立快照上跑。
- 变异 **55/55**，每个都有明确的 FAILED 测试：作者的 29 个（S18、S23 改锚到修复后的代码），审查员的 14 个，以及新增的 12 个。
  - 用 12 个 worker 跑时，登录回调的 AppTest 冷启动超过 30 秒，35 个记为 SUSPECT。换成 6 个 worker、再换成 2 个 worker 复核后全部杀死，没有存活。
  - 新增变异体里，「接受负数 contribution_count」首轮存活（回调测试原来也没有这一项），补了一个参数后杀死。
- ruff 0.5.0（F/E9/B）通过；没有 CR，`git diff --check` 通过。

**第二轮复查**（2026-10-13 晚，审查员 A21 复审修复提交）：修复都解决了对应的问题，没有回归。修复前后，成功请求的日志事件、10 个成功响应体（包括两个聊天流）、query_log 和状态码都一致。剩下 3 个 LOW，已处理：
1. 异常组嵌套时（collapse 拆开多层单成员组），外层的组仍被当成原因。处理：递归检查成员。
2. 新代码有 8 个分支没有测试管，例如把所有异常组都当包装、`session_token` 不检查类型、接受空的 user_id／email。处理：补 16 项测试，其中 7 个原因场景、9 个身份形状。
3. 状态码变化少算了：其实有四种 Google 畸形响应从 500 变成 401。处理：改了上面「范围与原因」和 API 契约的说法。

**第二轮复查后的验证**：
- 本文件现为 78 项（又加 16 项）；放到 `88d0ef4` 上只有嵌套那一项失败（1 failed／77 passed）。
- 全量离线 **3763 passed，7 warnings，340 秒**，在独立快照上跑。
- 受影响的变异体 **20/20**，每个都有明确的 FAILED 测试，0 SUSPECT（4 个 worker）。包括：作者的 S18、S23、S28；审查员第一轮的 E09；N01–N03 和 N09–N12；审查员第二轮的 X01–X08；以及新增的「不递归」。
- ruff 0.5.0（F/E9/B）通过；没有 CR，`git diff --check` 通过。

### 已知、未处理

1. 成功查询原文／query_log 留存、auth.callback.success 的 Google sub 不改；路径／uvicorn access query string 仍可能含个人信息，不宣称所有日志匿名或无 PII。
2. 已发流头以后的异常不能改成此 500：只记一条安全的 `unhandled_exception`，但 uvicorn 自己的 handler 不经过 root 过滤器，仍会打印带原文的 traceback。聊天的 meta 已挪到响应开始前，模型流错误转成流内事件，目前没有已知的生产路径会走到这里。Python `warnings` 和 Streamlit 进程日志（UI 未捕获异常）也仍打印原文，浏览器只显示类型。启动脚本其他打印不在本批治理范围。
3. OPT-02 只读核对：真实空结果有一次页面覆盖，但跨 rerun／TTL 的强度仍可补；同 token 贡献权限变化不立即过期 Co-op teaser，须另批行为修改。
4. SIM-03 叠在本批之后（第 22 节），SIM-04 等其合并；OPT-04 第二步、OPT-06、学生端拓展不做。
5. 未做真人账号、NAS、公网、负载或生产效果验收；部署记录与本批离线结果分开。

### 发布状态

- 分支 `fix/safe02-error-exits`，起点 main `9dff227`；实现、独立审查和审查后的修复都已完成，均为本地提交（准确 hash 另记仓库外）。尚未推送、PR、合并或部署。
- 本批有 API／UI／发布配置行为变化，审查合并后需重新发布镜像才能线上生效。

## 22 — 前端主入口职责拆分（SIM-03，2026-10-13）

### 范围与原因

按本轮方案第 0–3 步，从 main `9dff227` 独立开分支。目标是主入口负责页面编排，不改现有功能、状态、文案、widget key、请求或 rerun 语义。本批自身的改动不含 SAFE-02 的错误行为变化（rebase 后叠在 SAFE-02 之上），也不做 SIM-04 转义工具整理或第 4 步流式抽取。

### 已实现

| 块 | 去向／保留边界 |
|---|---|
| 两个历史纯函数 | `app/chat_view.py`；main 保留 `_recent_history`／`_context_course_ids` 同名导入。保留原 slice、4000 字符截断、最新带证据助手、顺序／重复／畸形输入行为 |
| R17 详情栏 | `course_detail_view.render_selected_course`；客户端调用时导入，原正文 renderer 仍在原模块，不新增缓存 |
| R14 落地页 | `discover_view.render_landing`；通过模块全局调用原 render_discover，示例列表由 main 传入，显示条件留 main，不把按钮塞进原发现函数 |
| R15 历史展示 | `chat_view.render_chat_history`；仍在聊天列，接收 main 当前的两个 renderer、badge 和 chip 列表，保持旧替换点和所有 key |
| R0–R13／R16／R18 | 启动／认证／cookie／缓存／导航／筛选／固定输入／隐私许可／项目 selector／整个提交块／三处收尾保留原处 |

main 的 `_format_evidence`、`_render_evidence_block`、`_render_message_text`、`stream_assistant`、`_summarize_results`、`FALLBACK_NOTICE` 保留为原定义／常量；`_render_filters_sidebar` 仍在 main，通过 main 全局名、两个位置参数调用。没有新造不必要的兼容包装。运行时的认证、cookie、program cache、stream renderer 查找保持。

main 809→701 行，render 389→308 行；这是减少主入口内联职责，不宣称整个项目总行数下降。迁出代码在原页面列／container 中运行，反馈仍在对应 chat_message 外，privacy／selector 仍在输入前。不存在「清空对话」控件，本批也不新增。

### 修改文件

- `app/chat_view.py`（新）：纯 helper 和历史展示。
- `app/streamlit_app.py`：保留编排／兼容名称／时序，委托三块。
- `app/course_detail_view.py`、`app/discover_view.py`：各追加一个小 wrapper，旧正文／发现函数不改。
- `tests/test_page_orchestration.py`（新）：先通过、后冻结的行为特征测试；`tests/test_page_feedback_keys.py`（新）：变异后补强完整反馈 key，另在 archive main 上通过。
- 本文件：验证与发布边界。仓库外另有中文 WORKLOG、AST 对照、替身测量和具名变异日志。

### 验证记录

- 占位 key、合成状态、MockTransport／AppTest；新测试有 send guard，替身失效会失败，不会真正联网。没有读真实凭证或生产库。
- 初版新测试有四处搭法／预期错误（landing click pass、AppTest 中断片段、CSS 类名），在未改产品的 main 上修正，仅改测试，不把它们算产品缺陷。
- main 原产品上新测试 **22 passed，3 warnings，18.18 秒**；冻结 SHA-256 `5fa6bfb2ce72c5401e226289646d184d698909839d0ca7376a8d8817f831cbd2`。抽取后未改一行，hash 一致。
- 覆盖纯 helper 的窗口／截断／原 slice 语义、冷 landing 四示例、空详情、历史课程切换／错误前缀／带 token／每次重取、单／多课追问／pending、history-before-query／context、重复课程 key、chip guard、项目 ID、主入口替换点和文本过滤。
- 13 文件定向 **559 passed，18 warnings，51.47 秒**（六 worker）；rebase 前（基于 `9dff227`）全量 **3707 passed，5 warnings，305.13 秒**，为 main 3685 + 新增 22。rebase 后的数字见「审查」一节。
- 既有三处 AST 钉子和旧测试不改。额外 AST 对照 **15/15**：迁出的纯函数、历史（仅依赖名替换）、landing（仅 import／参数名）、详情（仅 import 位置）一致；整个 R16 和九个未迁出函数完全相同。
- 首轮具名变异 16/17，反馈 prefix 存活：旧页面用例只查 key 后缀。另补 1 项精确 key／改票／rerun 用例，在 archive main 上 1 passed；两新增文件为 23 passed。原冻结 22 项不改，不把测试余项当产品缺陷。
- 最终具名变异 **17/17**（首轮有效 16 + P15 串行复核），均有真实 FAILED 身份，0 存活／SUSPECT／ERROR，不混称一次完整重跑。结构顺序、提交 rerun、证据／chip／反馈 key、context、assistant filter、late client／stream lookup、filters patch、截断／顺序／重复等各有对应负例。模块级绑定变异也有禁止联网的保护。
- 每场景预热 15、测 100 次的 Python／Recorder 替身：landing median 0.010250→0.010970ms、p95 0.012010→0.012490ms；history 0.021550→0.021536／0.047411→0.025290ms；detail 0.030026→0.030760／0.055841→0.058762ms。未明显变慢；量级小、单轮噪声大，不宣称统计或生产性能改善。
- rebase 前（基于 `9dff227`）补强后的最终全量 **3708 passed，5 warnings，368.52 秒**，main 3685 + 两新增文件 23 项；警告为三项 SWIG 类型与两次 HTTP 422 名称弃用。
- 6 个改动 Python 文件 Ruff 0.5.0 F/E9/B 通过；7 个改动文件 CR=0、diff 检查通过，1 个真实本地 Markdown 目标有效。原冻结文件 hash 不变。

### 审查

作者逐项对照块表、九条顺序、六个 patch seam、三个 AST 钉子。2026-10-13 做了一轮独立只读审查（审查员 B22；主评审另外核对过），报告在仓库外。冻结测试和差分对比都是有限的等价性证据，不宣称覆盖所有浏览器／并发／真实账号场景。

**结论**：纯重构成立，没有 CRITICAL 或 HIGH。差分对比在两棵树上跑了 98 个 AppTest 场景、439 步，逐步比较原始 ForwardMsg 流、元素树、每个 API 调用和请求体、`session_state`、脚本运行和 rerun 次数。96 个场景逐字节一致，另 2 个只在异常栈里多一层新模块的帧；同一棵树自己对比 0 处差异；17 个「运行前替换名字」的场景也一致。计划 B3 的规则全部满足。处理如下：

1. **MEDIUM，测试缺口（不拦合并）**：新测试管住了 key、请求、chip 条件、替换点和只过滤助手文本，但没管搬出去的块渲染在哪个容器、一轮里的顺序、展开和 HTML 开关、历史里的提示和卡片数、空状态和首页布局。审查员的 58 个变异体里，有 29 个明显改变页面，却在 rebase 前的全量（3708 项）下全部存活（主评审复跑）；rebase 后 SAFE-02 新增和修改的测试也杀不掉（审查员在 rebase 后复核，58 个的结果与之前完全相同）。处理：放到 SIM-04 第 0 步，补布局快照，AST 检查改成看最近一层 `with`。
2. **LOW**：异常栈里会出现新模块的帧（`chat_view.py`、`course_detail_view.py`），这是差分对比里唯一的差别。叠在 SAFE-02 之后，浏览器只显示错误类型。
3. **LOW**：原有三条 AST 检查只读 `render()`，现在管的代码少了；例如在 `render_chat_history` 里加 `st.chat_input` 不会被发现。处理：和第 1 条一起放到 SIM-04 第 0 步。
4. **LOW**：四个在调用时才查找的名字（`render_retrieval_notices`、`render_answer_feedback`、`empty_detail_html`、`render_course_detail`）实现正确，但没有测试固定，记在这里。
5. **LOW，文档**：搬走的 docstring 丢了理由，`discover_view` 两处说明过时。处理：恢复理由（4000 字符截断的原因、上下文 id 每次都带也无副作用、「查看」key 带序号的原因、追问走 context 档），补上 `pending_query`，改了调用方说明；只改注释和 docstring，代码不变。
6. **INFO**：按项目自己的 ruff 配置，兼容导出那行有 E402。这行必须在 `sys.path` 插入之后，所以加 `noqa` 说明，不挪位置。
7. **main 上本来就有**：GET /course 返回 200 但内容不是 JSON 时整页报错；叠上 SAFE-02 后变成固定提示。

**rebase 后的验证**：
- 用 `rebase_stack.sh` rebase 到 SAFE-02（含两轮审查修复）之后。只有本文件冲突；本批改动的文件和 rebase 前逐字节相同；本文件等于 SAFE-02 的版本加第 22 节；冻结测试的哈希不变。
- 差分对比在 SAFE-02 之上重跑：基线是 SAFE-02 第一轮修复，对照是本批加文档修复，98 个场景、439 步，0 处差异；同一棵树自己对比也是 0。原来只在异常栈上不同的 2 个场景也一致了：浏览器只显示错误类型；详情接口返回 200 但内容不是 JSON 时，显示固定提示，不再报错。之后 SAFE-02 的第二轮修复只改原因判断和测试，不碰页面。
- 改动的三个 Python 文件去掉 docstring 后 AST 与修复前相同；ruff 0.5.0（F/E9/B）通过，没有 CR，`git diff --check` 通过。
- 全量离线 **3786 passed，7 warnings，262 秒**（SAFE-02 的 3763 加本批 23 项），在独立快照上跑。

### 已知、未处理

1. 不搬第 4 步流式编排、不做 SIM-04/05、OPT-04 第二步、OPT-06 或学生端拓展。
2. 本批叠在 SAFE-02 之后。SAFE-02 改了 5xx 和 404 的文字，所以新增的课程错误测试只钉中文前缀。
3. 登录／cookie／deep-link／pending-nav 的更多真实页面验收、筛选清除、真实清对话控件等原余项不在本批实现。
4. 本批只有 AppTest、源码对照和 Python 替身测量，没有真实浏览器／账号／NAS／生产模型或性能验收。
5. 两份本地未跟踪计划文档仍未决定公开入库，本批不加入。

### 发布状态

- 分支 `refactor/sim03-page-orchestration`，起点 main `9dff227`，已 rebase 到 SAFE-02 两轮审查修复之后（第 21 节在前，本节在后）。实现、独立审查和文档修复都已完成，均为本地提交（准确 hash 在仓库外）。尚未推送、PR、合并或部署。
- 合并顺序：先 SAFE-02，再本批。
- 纯重构，不需要独立数据迁移；部署与合并仍由用户另行决定，SIM-04 必须等本批合并后再开。

## 23 — 纯文本渲染工具与布局验收补强（SIM-04，2026-10-14）

### 上线记录（main `9771b05`，2026-10-14 11:04 UTC 起）

以下引用仓库外该次发布记录，不是本批新做的线上探针。PR #13 合并时一起带入 PR #12，SAFE-02 两轮修复与 SIM-03 审查后的版本进入 main；该树离线全量 3786 passed。API、UI、backup 换到镜像 `104522031348`，前一镜像 `442834b18ae0` 保留为 `rollback-20261014`；预发布数据库备份 quick_check 通过，未用备份覆盖生产库。

该次记录：ready 6469/6469、Co-op 30 条、培养方案与政策探针通过；404／422 固定提示、401 与 request ID 校验、UI `showErrorDetails=type` 生效，切换后没有 traceback。真实检索评测 116/116 成功，R@5 0.8647、MRR 0.9293、服务端 p50 822.5ms／p95 1143.0ms；四条排序变化记作运行波动；这次发布没有改检索逻辑。CS 5004 先修聊天正常以 done 结束并引用 2026 年目录；公网游客首页与详情空态正常。用户本人的登录／刷新／登出及问一次带先修问题的验收仍未完成。本批没有重新访问 NAS、公网或调用真实模型。

### 范围与原因

从已合并 SIM-03 的 main `9771b05` 开独立分支，先完成更新方案的第 0 步，再整理文本工具。保留现有功能、文本输出、调用顺序、widget key 和错误提示，不将测试余项、渲染策略变更或缓存行为塞进纯重构。

### 已实现

1. 补齐上轮 B-M1／B-L2：按容器冻结有序元素、完整 key／文案、HTML 开关、按钮宽度、avatar 与 expander 状态；历史含 1／4 门课、提示、有效合成反馈回执，另补 3 门展开边界；首页和详情空／200／404 各有快照。最近一层 `with` 归属必须是 chat_col／detail_col；迁出块不能创建 chat_input 或反馈权限请求字典；404 钉完整文字。
2. 将 `literal_markdown`、`_one_line`、`plain_text_html`、`labelled_line_html` 原样搬到 `app/text_render.py`。仅依赖标准库 html／re，不导入 UI、schema、RAG 或 FAISS。URL 开头正则与 WORD_JOINER 保留一份来源，原回答过滤器通过导入继续使用。
3. 旧 evidence 模块保留 literal_markdown 别名；ui_theme 保留三个 HTML helper 的同名别名。deep_links、program_plan_view、program_view、ui_theme 四个只为 literal 转义的 import 改到纯模块，原惰性导入位置不变。
4. 可选的 answer_markdown／CSS 抽取没有做；回答过滤、流式 renderer、页面编排和全局 CSS 不改。九类相似但不同的策略有意保留，包括 CR／LF、空白折叠、标点、链接、长度上限、分隔符和 plain／Markdown 使用位置。

### 修改文件

- `app/text_render.py`（新）：四个纯函数；URL 开头正则与 WORD_JOINER 两项供原过滤器共享，ASCII 标点正则只用于 literal helper。
- `app/answer_evidence_view.py`、`app/ui_theme.py`：兼容别名；未迁出 renderer 原样保留。
- `app/deep_links.py`、`app/program_plan_view.py`、`app/program_view.py`：各只改一个 import。
- `tests/test_aaa_page_layout.py`、`tests/test_text_render_contract.py`、`tests/test_text_render_imports.py`（新）与 `tests/fixtures/page_layout/` 九个快照。
- `scripts/regenerate_page_layout.py`、`tests/page_layout_support.py`（新）：显式快照核对／生成入口及共用合成 backend。
- `tests/test_page_orchestration.py`：backend 移入共用 helper；原编排断言保留。
- 本文件。中文 WORKLOG、完整输出、变异及结构对照在仓库外，不随公开提交。

### 验证记录

以下为 10-14 原提交的验收；10-15 修复后的验证另记「审查」小节，不混用两版测试和快照的冻结哈希。

- 未改产品时布局与精确文本输出 **62 passed／3 warnings**；最终冻结版本在完整基线上 **3848 passed／7 warnings／269.09 秒**，即 main 3786 + 新增 62。冻结两测试与六快照的 SHA-256，抽取后保持一致；当时没有自动更新快照入口。
- 原审查中在全量存活的 29 个变异，采用 `tests/` 全量范围、3 worker，先完整绿色基线再逐个 `pytest -x`；**29/29 killed**，逐项有真实 FAILED 身份，原始错误行复核无真实超时。布局测试文件先收集是为了全范围 fail-fast，不删除或跳过测试。
- 四个移入函数完整 AST 相同；未迁出的 evidence／theme 函数保持 AST，唯一例外是先修 helper 的明确 import 变化；主入口、chat、detail、discover 完整文件不变，三页面只改 import；CSS、共享常量和正则不变。结构对照全部通过。
- 新进程依赖隔离、旧别名身份与四个调用方 import 契约另补 7 项。这些是新模块的新增契约，不声称旧 main 已能从不存在的新模块导入。
- 首次定向启动命令未将占位 key 传给第二条命令，出现 Settings 缺参；原错误日志保留，修正启动命令后重跑，没有修改源码或冻结断言来迎合失败。
- 新模块三次冷进程导入均未加载 RAG／FAISS，旧路径三次均加载；相同合成输入显示结果一致。此项只说明依赖边界，不代表整页或生产性能改善。
- 正确重跑的 14 文件定向 **333 passed／18 warnings／55.67 秒**（6 worker）；最终串行全量 **3855 passed／7 warnings／322.27 秒，退出码 0**，main 3786 + 新增 69。7 个警告是 3 个 SWIG 类型与 4 次 HTTP 422 名称弃用。
- 9 个改动 Python 文件 Ruff 0.5.0 F/E9/B 通过；16 个改动文件无 CR，diff whitespace 与本地文档目标检查通过。全量前后同进程封存 16 文件哈希一致；原两测试／六快照的冻结哈希在抽取、全量和变异后均一致。后续只补文档结果，不改已验收的产品或测试。
- 新包 **20/20 killed**（6 worker，5 文件定向绿色基线）：17 项转义／依赖隔离／兼容路径变异，另 3 项是迁出块禁止 input／反馈权限请求字典的架构护栏负例，包括死代码，不混称全部都是可见行为变化。各有实际 FAILED 测试身份，复核无真实超时。与第 0 步的 29 项分开运行和记录，不声称一次 49 项整包复测。

### 审查

10-14 独立审查：0 CRITICAL／0 HIGH，1 项 MEDIUM 测试覆盖缺口及 9 项 LOW，没有发现产品代码缺陷。108 个 AppTest 场景／466 步及精确函数输出交叉检查未见行为差异；这不是线上或真实浏览器验收。

10-15 评审后修复只动测试、生成工具和记录，不改产品目录。补长对话（8 条、alias／context／program、6 门证据）、空结果带提示及单门拒答、发现区位置、详情 500 完整安全提示、二次提交 POST→详情 GET 顺序。固定 public_base_url，快照增加完整 new_element／add_block 元数据（含对齐、宽高），路径相对 chat／detail；共用合成 backend，生成器进仓库，默认只核对，显式 --write 才更新。新进程用标准库允许列表并调用全部四个 helper，运行三条惰性转义路径，补常量身份／禁止重复定义及 8 个 URL 边界。旧冻结文件和原日志作为历史证据保留，新结果单独封存，不将旧数字称为本次重跑。

10-15 验证：未改产品的 main 副本上新测试及原编排测试 **96 passed／3 warnings**，原 6 快照投影保持 185 个节点不变（首页只新增合成 discover 标记），9 快照重复生成逐字节一致。当前分支外部 PUBLIC_BASE_URL 被改写时，16 文件定向 **465 passed／9 warnings／69.08 秒**；串行全量 **3867 passed／7 warnings／381.65 秒**，退出码 0。6 个 Python 文件 Ruff F/E9/B 通过，16 文件 UTF-8／LF 与 whitespace 检查通过，全量前后哈希一致。暂存检查随后只清理两个新文件的 EOF 空行，完整 AST 不变；清理后的精确提交另经三组完整绿色基线复验，均为 **3867 passed／7 warnings**（366.71／330.97／398.77 秒），新代码哈希独立封存。

指定的三组变异均在完整 `tests/` 范围、最多 3 worker 运行：原布局组 **29/29**，审查布局组 **16/16**；文本／依赖组并发轮 **8/9 killed、1 项真实 AppTest 超时**。该超时不计 killed，原始日志保留；待并发结束后，用同一精确提交、原 45 秒阈值、单 worker 在完整范围复测 I09，明确被 deep 模式依赖断言拦截（到失败前 3742 passed），不是超时。最终 **54 项均有实际 FAILED 身份，0 存活／未解决超时／ERROR**；不混称首次并发一次 54/54。M26 是共享定义单一来源契约，I05–I10 是冷进程依赖边界，不将全部变异称为可见界面变化。完整 ID、三组基线、原并发超时和串行复测日志均在仓库外逐项链接。

可选的更广 AST 写法分析不在本次修复范围，不声称测试与有限结构证据穷尽所有浏览器场景。

### 已知、未处理

1. 不合并近似但不同的 escaping 策略；不搬可选 answer filter／CSS，不做 SIM-05、OPT-02 行为余项、OPT-04 第二步、OPT-06 或学生端拓展。
2. 保留 literal／answer filter 的既有显示代价，包括 word joiner、邮箱可能成为邮件链接等，不以工具迁移顺便改变渲染规则。
3. 仅 AppTest、精确字符串、新进程与 AST 验证；没有新增渲染依赖或改变渲染策略，未重跑真实浏览器渲染器，不宣称 DOM／真实账号或生产验收完成。
4. 两份 main 未跟踪计划文档是否公开入库仍由用户决定，不随本批加入。

### 发布状态

- 分支 `refactor/sim04-text-render`，起点 main `9771b05`。实现、评审后修复及轻量复核已完成；PR #14 已于 2026-10-15 合入 main（合并提交 `6e1a01d`）。轻量复核的 LOW-1 文件清单遗漏由第 24 节同批补正。部署计划随 B 一起进行，仍需另行授权，不把合并视为已部署。本地提交与准确 hash 另记仓库外工作记录。
- 无数据迁移；新模块须随代码发布后才会在线上生效。本批离线结果不是当前线上采用结果。

## 24 — 空结果验收与贡献数变化后的预览缓存（OPT-02，2026-10-15）

### 范围与原因

从已合并 SIM-04 的 origin/main `6e1a01d` 开独立分支，补齐 OPT-02 的空成功、同 token 下贡献数变化两项。空成功原本就按成功处理，本次补特征测试；贡献数变化是有意的行为修复，不混入文本工具重构、API 等级规则或其他缓存策略。

### 已实现

1. 游客范围仍固定；登录范围改为 token 摘要＋完整贡献数。缺失计数按 0；畸形计数独立为 c?，不和真实计数共用。预览在同一处捕获 token 和计数用于该次请求／缓存范围。
2. 保留 300 秒成功／30 秒失败 TTL，不改投稿结果处理、登录、登出或 API；空列表／空字典成功不算故障、不算回退，也不显示缺内容提示。
3. 补缓存层、视图层与 AppTest；覆盖计数升降、同 token 登录更新、投稿响应中的服务端计数、不变计数不重取、变范围后的失败不回退旧内容，以及 rerun 不重复 POST。
4. 按 SIM-04 轻量复核 LOW-1 补齐第 23 节文件清单与合并状态；不改该批产品代码、测试或快照。

### 有意的行为变化

只有一项：同一个 token 下，本地已知贡献数变化后，Co-op 预览下一次读取重新 GET /coop；旧范围的列表不再显示，也不作为失败时的回退。按完整计数分范围，因此 2→3 也会重取，不在客户端复制服务端等级规则。

### 修改文件

- `app/view_cache.py`、`app/discover_view.py`：范围及调用方读值，未改 API／TTL；评审后只改了预览 docstring 的措辞。
- `tests/test_view_cache.py`、`tests/test_home_cache_page.py`：空成功和贡献数边界。评审后补了三条测试：缓存层和视图层的「先有内容、后来取到空」，以及预览的「缺键按 0」。页面测试不再读私有的缓存记录，一条测试改名。
- `docs/view-cache.md`、本文件：契约、验收及发布边界；顺带更正第 23 节的文件清单。

### 验证记录

- 在未改产品的起点上先复现：**23 failed／108 passed／6 warnings／34.11 秒，退出码 1**。空成功、计数不变、游客等特征测试原本就对；23 项失败属于待修复的贡献数范围与预览刷新路径，不当作产品回归。新增 38 项，未删原测试。
- 修复后 8 文件定向 **211 passed／6 warnings／37.84 秒**（2 worker；SWIG 警告每个 worker 各报一次，串行为 3 个）；串行全量 **3905 passed／7 warnings／374.82 秒**，均退出码 0。7 个全量警告仍为 3 个 SWIG 与 4 处 HTTP 422 弃用。
- 两份测试从失败复现起冻结，修复后未调整断言；4 个非文档代码文件在全量前后、变异后哈希一致。除目标两函数外的函数／类 AST、模块导入与常量均保持原样。
- A 的 9 份布局快照默认核对全部 match，没有 --write；其测试、helper、生成器与快照均没有差异。API、DB、配置、RAG／LLM、登录、投稿处理与 sidebar 实现不改。
- 11 个具名变异以两文件定向范围、2 worker 运行，先跑完整串行定向基线 **131 passed／3 warnings／22.64 秒**；随后 **11/11 killed**，逐项核对真实 FAILED 身份，0 存活／实际超时／ERROR。不混称本批变异在完整 tests/ 上运行。
- 4 Python 文件 Ruff 0.5.0 F/E9/B 通过；6 文件 UTF-8／LF、whitespace、边界和新增内容扫描通过，新增邮箱仅已知合成测试地址。私有 WORKLOG、完整输出、冻结哈希与逐项变异报告不随公开提交。
- **评审后修复（10-16）：**
  - 8 文件定向 **214 passed**（4 worker）；
  - 串行全量 **3908 passed／7 warnings／260.59 秒**，退出码 0；
  - A 的 9 份快照核对 match，Ruff 通过；
  - 两个产品文件去掉 docstring 后，AST 与 `22643d0` 相同。
- **评审后的变异：**
  - 审查员存活的 D17、D18b（取到空却留着旧内容、或当回退）被两条「先有内容、后来取到空」的测试杀掉；
  - D01（预览没有「缺键按 0」）被新的调用方测试杀掉；
  - 作者的 11 个变异重跑仍为 11/11；
  - D26（`login()` 也删预览）按 Q5 不加测试，仍存活，见「已知、未处理」第 4 条。

### 审查

作者按方案 B2–B7 核对特征测试与失败复现、scope／调用方配对、失败回退隔离和不重复 POST，并对 API 字段裁剪与模拟数据语义作源码对照。

10-15 两个只读独立审查：0 CRITICAL／0 HIGH／1 MEDIUM／5 LOW，产品代码没有缺陷。
- **页面差分：** 在 `6e1a01d` 与 `22643d0` 上各跑 21 个 AppTest 场景，用真实的 OAuth 回调、cookie 恢复和登出按钮。唯一的行为差别是同 token 下已知贡献数变化后多出的那一次 GET /coop。请求和缓存范围用的值 0 次不一致。
- **数字复现：** 两边各自复现了红色基线、定向、全量和快照的数字。作者的 11 个变异在 8 文件和全量范围上都被杀掉。
- **MEDIUM：** 空成功只测了「一直是空」，没测「先有内容、后来取到空」。把旧内容当新成功留着（D17），或当回退显示（D18b），这两个变异在全量上都存活。已补缓存层和视图层两条测试。
- **LOW：**
  - 预览自己的「缺键按 0」没有测试（已补）；
  - 页面测试读私有缓存记录（已改为只看页面上的锁提示）；
  - 预览 docstring 写错了不再沿用的是哪份列表（已改）；
  - 文档漏写客户端不知道的几种变化（已补，见「已知、未处理」第 1 条）；
  - `login()` 若也删预览没有测试管（不加，见第 4 条）。

以上是本地离线验证，不是生产或真实账号验收。

### 已知、未处理

1. 范围只跟着本标签页知道的变化走：登录、cookie 恢复、投稿响应。下面这些都要到下一次获取才体现，最多 5 分钟，可手动刷新重取：
   - 审核员发布；
   - 别的标签页里的投稿或登录；
   - 账号被删，这时 `/coop` 按 0 级回 200，不是 401；
   - token 过期。

   不轮询，不逐次 rerun 请求 /auth/me；sidebar 显示仍沿用登录／投稿更新路径。不会泄露：每次获取都以服务端为准。
2. pending 投稿本身不增加贡献；测试响应的新计数模拟服务端此前审核发布的旧贡献，不能解释成发帖立即获奖。
3. 不做 OPT-06、学生端新功能或生产／真实浏览器／账号验收；main 两份未跟踪计划文档不加入本批。
4. 同一个 token、同一个贡献数重新登录时，`login()` 要是也删掉预览，没有测试管。现有路径碰不到这种情况：OAuth 每次都发新 token，cookie 恢复只在未登录时跑。代价最多是多一次 GET；按 Q5，不加额外的过期路径。

### 发布状态

分支 `fix/opt02-empty-and-contribution`，起点 `6e1a01d`。实现、独立审查和评审后修复已完成；推送、开 PR 随后进行，合并由用户操作。仅 UI 需要部署，计划与 A 一起，须另行授权。没有数据迁移；会话中的旧 token-only 缓存首次读取时因范围不同自然重取。没有真实数据／NAS／模型调用，不把本地测试称为已经上线。

## 25 — 离线完整链路评测与检查器身份（OPT-06，2026-10-16–17）

### 范围与原因

从 origin/main `6e1a01d` 独立推进 C，不混入 B 的缓存修复。第一轮分 C-1、C-2 两个提交，第二轮按检查器／路由另做修复提交；本节预计编号 25，合并前按最终合并顺序调整。只改评测工具、测试和记录，线上运行路径不变。

### 第一轮实现（保留历史；现行契约见第二轮修复和第 17 轮）

1. C-1 的未陈述数值保留课程＋字段身份，只做 workload／difficulty；同句归属，单课可直接归属，不跨句继承。课程或字段判不出时保留未解析信号。
2. 汇总和 Markdown 表列出 unattributed；新增课号超出证据、来源数值分歧未完整说明两个信号，不加入 HARD_FAILURES。
3. 记录 CHECKER_VERSION 和检查器／关键源文件 SHA-256，固定证据结果标明 live_api 或 live_model；旧结果缺层级时重评标 legacy_unknown，不臆测原始来源。
4. --rescore 必须给 --out 新目录，原 results.json／summary.md 永不覆盖；记录 rescore_of 路径、原文件哈希、前后检查器版本。旧上下文仍能读取，估计项身份标 unavailable，错误记录和原运行分母保留。
5. C-2 建立独立内存世界：10 门 Synthetic 课程、主题向量 FAISS＋真实 BM25／融合和真实 /chat 路由；课程别名、年度规则、共享 CS 前缀的两个项目、版本方案和数值冲突都来自合成 seed。所有种子时间固定，world_sha256 对实际种子行规范化后计算。
6. 固定 32 用例／8 类，合计 36 轮；逐轮记录实际请求、路由、结果、notices、prompt 哈希、回答和错误。上下文从实际 prompt＋全部 meta 证据构造，并与固定证据工具多课对拍。
7. 多轮直接使用 UI 的 history／context helpers，按 UI 的方式保留部分回答、错误提示与已收到的证据。HTTP 409／404 和断流都保留在分母；意外异常保留为 harness_error 并继续后面的用例。
8. 检索和生成分开计分，按类别列分母；R@k／MRR 只对 hybrid 类并列 n。输出有意包含坏回答与失败脚本，用于检查检测器；complete 只表示计划全部执行，绝不表示回答全对。
9. 离线层固定 offline_synthetic、真实 API／模型调用 0、production_quality_verified=false；不允许与其他层级混合汇总。只有 --out 的薄 CLI 独占创建新文件，不接受地址、模型或库路径。
10. 调用接缝遗漏时拒绝真实库；验证只有 eval 标记的 query_log 新增，其他表逐行不变。子进程 audit 钩子实测禁止网络、真实 SQLite、模型导入、.env 读取和输出文件之外的写入。

### 有意的行为变化

- `test_case_is_built_like_chat_and_the_context_reflects_the_evidence` 和 `test_an_estimate_in_one_sentence_does_not_cover_a_number_in_the_next` 从合并数值升级到课程／字段三元组；保留原有语义断言。
- 旧的重评调用方测试改为提供新目录，并从新目录核对结果；未删错误保留、无需联网和检查器 bug 保留 traceback 的断言。
- summarize 新增按 kind 和身份未解析计数；新结果增加身份字段；原地 --rescore 改为新目录输出。
- C-2 复现并补正中文紧邻／小写课号归属，检查器版本升至 2.1-route-identity；不跨句继承。顺手补齐错误行的 Markdown 表格列数和关键辅助脚本／schema／history helper 的源文件哈希。

### 修改文件

- `eval/answer_checks.py`、`scripts/eval_answers_live.py`：检查器和固定证据工具。
- `tests/test_opt06_answer_identity.py`、`tests/test_eval_answers_live.py`、`tests/test_answer_checks.py`：复现、兼容和不可覆盖契约。
- `eval/route_world.py`、`eval/route_cases_v1.json`、`eval/route_eval.py`、`scripts/eval_route_offline.py`、`tests/test_route_eval_offline.py`：合成世界、用例、路由评测、薄 CLI 与隔离测试。
- 本文件；完整日志、测试冻结哈希和 WORKLOG 在仓库外保留。

### 验证记录

- C-1 正式红色基线：六文件 15 failed／184 passed／3 warnings；实现后相同冻结测试 199 passed／3 warnings。
- 显式六文件构成的 C-1 隔离副本串行全量 3883 passed／7 warnings／257.73 秒，退出码 0；五个 Python 文件前后哈希与当时工作区一致。提前预写的 C-2 测试不在 C-1 副本或 C-1 提交中。
- M01–M05、M14 六个具名变异在六文件定向范围全部 killed，逐项有真实 FAILED 身份，不称为全量变异。Ruff F/E9/B、UTF-8／LF、差异检查和运行代码边界检查通过。
- C-2 接口／课号边界红色检查 9 failed／7 errors；原有三份测试和新路由测试分别冻结。实现后的十一文件定向 476 passed／4 warnings／39.06 秒；补齐身份元数据后的精确副本绿色基线另为 476 passed／4 warnings／30.73 秒。
- 最终串行全量 **3899 passed／7 warnings／365.04 秒，退出码 0**。四份冻结测试哈希不变；全量启动与结束的十个非文档文件 SHA-256 一致，随后仅填补本节验收记录。七个警告为三项 SWIG 类型及四次 HTTP 422 名称弃用，不是测试失败。
- M01–M14 在上述十一文件定向范围、6 worker 下 **14/14 killed**，逐项核对原始日志中的实际 FAILED 测试身份；无存活、未解决超时或仅 setup ERROR。此包不是 tests/ 全范围变异，也不与先前 C-1 六项相加称作二十种。
- 九个 Python 文件 Ruff F/E9/B 通过，默认布局快照核对 9/9 相同（没有 --write）。十一文件 UTF-8／LF、whitespace、公开差异中的私有路径／地址／凭据模式检查通过；运行目录、共享夹具与历史评测数据对基线无差异。
- 独立运行薄 CLI：32 cases planned＝attempted＝completed，36 turns planned＝attempted；结果在仓库外。测试只验证合成链路与计分，不作为真实模型质量。

### 审查

第一轮离线验收数字保留为历史证据。10-17 独立审查为 0 CRITICAL／1 HIGH／7 MEDIUM：向量路径退化不改变判定，k=2 偏离 UI 默认，失败历史和 UI 不同，CLI 不检查契约失败，隔离触发可被 HTTP 500 隐藏。此前第 5／7／8／10 条的覆盖表述过强，不能由 3899 测试及原 14 个变异推出这些保证；本批暂不合并。

第二轮先修检查器：旧上下文未知课程身份为 null，不冒充已知空证据；新无结果上下文仍是显式空集合。补跨句、字段匹配／最近提示／唯一字段兜底、未知课程、简写课号、非估计单位、冲突英文句末、同分句记录归属和多引文冲突测试。恢复坏文件测试的 --out 与“未创建输出目录”断言；保留旧 unstated_values 路径与新三元组双覆盖。检查器升为 2.2-review-identity。四文件红色基线 11 failed／87 passed，冻结相同断言实现后 98 passed／3 warnings／5.37 秒；这只是检查器定向，不代表整批返工验收。

### 第二轮修复（数字和部分契约已由第 17 轮更新，以下一节为准）

1. 世界为 28 门 Synthetic 课程，42 用例／48 轮。真实 FAISS、BM25、融合／门控／路由与合成主题向量、语义＋词重叠重排替身组合；替身不读期望答案。新增 3 条向量专属查询，实际融合入口的 BM25 列表为空，记录向量／BM25 排名轨迹；补小写别名、中英 hybrid、追问加筛选、409 后恢复、救援成功与课号保护、部分回答泄露。
2. 固定 UI 默认 k=10；候选池、缩写扩展、融合与门控配置按生产代码默认值读取，α／阈值使用 shared common 常量。配置逐项记录 value、source、production_default；合成词表替换真实词表，依赖替身、反馈关闭和逐轮脚本救援标为 harness_pin。deployment_verified=false，不读 NAS 实时配置或 .env。
3. route_contract 不含流错误；stream_contract 单独检查 error_type／rescue_calls。每轮 expected_generation 明确 verdict、必须与禁止的信号；坏回答触发预期信号算契约相符，不强行升级成硬失败。部分回答硬失败另列，不混进完整回答 checked。
4. UI 错误历史使用真实规则：有已输出文字时追加空行＋⚠️，无文字时直接 ⚠️，不写“提示：”。与实际 stream_assistant generator 对拍两种情形，不再依赖方案转述。
5. 预期之外 HTTP 单列 unexpected_http。执行完整性与契约成功分开；CLI 输出 route pass/fail、stream fail、mismatch。退出码为 0 全部预期相符、1 契约／预期／隔离失败、2 准备错误、3 不完整。--out 必须在仓库外且为新文件。
6. 同时封住 dependencies.connect／db.connection.connect、生成和救援函数，审计钩子保护原始 SQLite、网络、进程、模型／真实数据读取和文件变更。只注册一次、上下文启停并恢复 bytecode 与原依赖；被禁止尝试立即阻止并计数，真实调用计数字段表示接缝调用尝试，不再是假定 0。
7. 账目使用显式校验，不依赖 assert。正常运行 query_log 行数等于实际 HTTP 200 轮次；投影异常发生在响应之后也保留真实 HTTP 状态与请求。非法访问可能在 query_log 已插入后触发 500：这种不一致写入 accounting_errors 并令整轮失败，保留报告，不能以异常掩盖计数或报成功。
8. expected 的键、类型、路由枚举、结果与生成预期严格校验；每项判定有独立负例。新增 git_dirty 和检索、依赖、UI、配置、审计守卫关键源文件身份；旧报告／原始结果不覆盖。

两位只读复核另外发现 4 项 MEDIUM／P2 和 2 项 LOW，全部补独立失败测试后修复：周工时同时支持前置“每周”和后置 weekly，完整日期过滤不再误删连字符工时区间，检查器升为 2.3-review-ranges；SQLite authorizer 拒绝 ATTACH／DETACH，FAISS 原生文件入口及项目模型加载／推理接缝按尝试计数并拒绝，覆盖缓存模块绕过导入检查的情况；同对象重入在替换 cleanup stack 之前拒绝；HTTP 500／503／非 JSON 的历史复用实际 ApiClient 安全转换，保留 Retry-After 提示。关键源码身份增加 API client、db.connection 和模型 backend。另补非法枚举类型／非整数 k 的准备错误契约。

单变量对照固定世界、用例、重排器与 k，仅改变查询向量路径。向量专属正确候选数为正常 3/3、常数 1/3、反主题 0/3、禁用 0/3；正常 Recall@10=1、MRR=0.30556，常数 Recall@10=1/3，其余 0。它证明合成评测能检测这些退化，不代表真实模型质量或性能提升。hybrid 与 vector_required 子集分别记录 n 与 k。（第 17 轮更正：常数组的 1/3 和两个 MRR 取决于 FAISS 对并列分数的排序，不是真实的候选丢失或排序质量；检测能力来自轨迹检查，见下一节。）

新增 `eval/route_guard.py` 与 `tests/test_opt06_review_checker.py`、`test_opt06_review_routes.py`、`test_opt06_review_integrity.py`、`test_opt06_review_guards.py`、`test_opt06_review_followup.py`、`test_opt06_review_native.py`、`test_opt06_review_validation.py`；更新原世界／用例／评测／CLI／检查器和相关测试。原冻结路由测试中的数量、字段名、指标名及错误历史断言按审查确认的契约有意升级；历史冻结证据保留在仓库外，不沿用第一轮覆盖结论。

第二轮最终验收：18 文件定向 **557 passed／4 warnings／84.63 秒**，串行全量 **3980 passed／7 warnings／414.07 秒，exit 0**。全量前后 16 个非文档文件哈希一致，8 个最终冻结测试文件核对通过；新增准备校验文件只追加双候选提示测试，原七项红色断言的源码前缀哈希另核对。15 个 Python 文件 Ruff F/E9/B 通过，默认九布局快照全部相同，没有 --write。七个全量警告仍为三项 SWIG 类型和四次 HTTP 422 名称弃用。17 个变更文件 UTF-8／LF、whitespace 和公开差异有限模式扫描通过；运行目录、共享夹具、历史评测 JSON 对第二轮起点无差异。

指定去重后的 56 个变异 ID 加 11 个守卫／复核变异，在上述 18 文件定向范围、6 worker 下 **67/67 killed**。精确副本绿色基线另为 **557 passed／4 warnings／28.89 秒**；67 项逐一核对原始日志中的实际 FAILED 身份，无存活、仅 setup ERROR 或未解决超时，不称全 tests/ 变异或 67 种互不相同的故障类。中间轮 59/60 的 E06 存活曾暴露最近字段测试没有两个可识别提示；保留原断言、补双向 hours／difficulty 后，最终 E06 有实际字段选择断言失败。中间日志不覆盖，也不与最终 67 项相加。

独立薄 CLI 工作区版为 42 用例全部完成／48 轮，route／stream 各 pass 48、fail 0，generation mismatch=0；query_log=实际 HTTP 200=44，其他表不变，受控接缝非法尝试计数全 0。39 个完整回答含 5 个故意硬失败；stream_error=4、no_answer=1、not_applicable=4，另列 partial_hard_fail=1，均符合显式脚本预期。提交后的干净版本 CLI 和四组向量对照单独封存，不覆盖工作区报告。完整 ID、红绿基线、两位只读复核与修复、最终源码／报告身份和日志入口都在仓库外 WORKLOG。

### 第 17 轮评审与修复（2026-10-17–18，现行契约）

第二轮之后又做了两份只读审查：路由侧 0 CRITICAL／0 HIGH／4 MEDIUM（另 5 LOW），检查器侧 0／0／1 MEDIUM（另 4 LOW）。评审方修复后，又做了六份只读复核，每份只看上一次的修复：
- 第三份：0／0／0，另 4 LOW、7 NIT；
- 第四份：0／0／0，另 4 LOW、6 NIT。4 条 LOW 是新规则带来的信号回退，NIT 是路由侧的遗留和文档；
- 第五份：0／0／0，另 5 LOW、6 NIT。LOW 是检查器信号的回退或遗留；NIT 是没钉住的规则、量表、课号、路由侧的校验和 compose 读取，以及文档；
- 第六份：0／0／0，另 5 LOW、6 NIT，都是检查器信号的回退、遗留和文档；
- 第七份：0／0／0，另 9 LOW、5 NIT。这一份只把相对上一版的回退算作 LOW：8 条是第六份修复里的新规则在普通句子上越界（其中三条出自第六份原样建议的改法），1 条是文档；
- 第八份（这一批的最后一份）：0／0／0，另 9 LOW、5 NIT，都是第七份修复里的规则边缘，各附一行改法，复核方已在副本上试过；评审方照改后没有再复核，靠全部探针、变异和全量验证。

六份复核都不改硬失败。LOW 和 NIT 都已处理，写在下面各条里。第三份的 LOW-4 只修了能修的部分；剩下的部分、第五份的一条校验 NIT、第六份的两处句型、第七份退回上一版的两条写法和其他没修的 NIT 都写在「已知、未处理」。新发现由评审方修复，单独提交：

1. **并列名次（MEDIUM）。** 主题向量是二值的，FAISS 对完全相同的分数按实现决定的顺序排。第二轮 9 条 must_exclude 里有 6 条、两个 MRR 和常数组的「1/3」都取决于插入顺序。
   - must_exclude 只留筛选和前缀排除的 3 条；
   - 新增 top_group：结果前 |组| 名必须正好是这一组，组内不计顺序；新增 k_exceeded；
   - 向量和 BM25 轨迹都按整组比较；
   - hybrid、向量专属、词专属三组指标都按整组计算（`relevant=top_group_or_required`），所以都是 1.0。它们是契约检查，不是质量数字；
   - 新测试把 FAISS 插入顺序倒过来、再打乱三种，判定和指标必须逐项相同。
2. **BM25 一路（MEDIUM）。** 新增 5 条词专属用例（BFS DFS、transactions、sensors、query optimization、geometry recognition），检查融合入口的 BM25 排名。
   - 最后一条里 BM25 把含两个查询词的 DS 9019 排在只含一个的 DS 9010 前面，和语料顺序相反；
   - BM25 返回空、倒序或所有命中同分，都会有用例失败，不管 FAISS 怎么排并列；
   - 每个 hybrid 轮次写明 result_count，结果被截短就报 result_count_mismatch；
   - 用例集现为 2.2-synthetic-ui10-counts，共 47 个用例、53 轮（第二轮的「42 用例／48 轮」是当时的数字）。
3. **配置来源（MEDIUM）。**
   - source 改为 code_default，旁边列出 `docker-compose.yml` 写的部署值和是否不同。目前有 5 项不同：候选池、拒答方式、HyDE 救援、融合方式和融合权重；`profile=code_defaults`；测试钉住这 5 项；
   - compose 只读 api 服务的 environment，映射和列表两种写法都认（列表也可以和键同缩进），键和服务名可以带引号，去掉引号、注释和 BOM，`${VAR:-x}` 取默认值；留给宿主环境的（映射写法的空值、null、~、`$VAR`、`${VAR}`、空默认值）记为未写，列表写法的 `- KEY=` 是空字符串；布尔值按 pydantic 的读法比较；
   - value 从路由实际使用的模块值回读，code_default 独立读取，两者不一致就是隐藏的钉值；
   - 补记 rescue_min_probability；
   - convex 融合和校准门不在这个离线档里。
4. **隔离守卫（MEDIUM＋LOW）。**
   - 每条审计规则补一条在合成世界里的「拒绝并计数」测试；每个拒绝集合的每个成员另有单独的测试；
   - 路由吞掉被拒的访问时，整轮仍然失败；
   - 新增拒绝：socket.bind／sendto／gethostbyname、进程派生、修改文件权限和时间、加载 SQLite 扩展；
   - 合成世界存续期间，新的 SQLite 连接只能用 `sqlite3.connect` 打开，打开后同样不能 ATTACH。用 `sqlite3.dbapi2.connect`、`sqlite3.Connection(...)`、`_sqlite3.connect` 或提前保存的函数新开连接，会被拒绝并计数。原因是 SQLite 用自己的 VFS 读附加的文件，文件读取规则看不到；
   - 配置里的真实库和索引路径受保护，不管指向哪里。
5. **路由评测的 LOW。**
   - 缺少融合轨迹时报 trace_missing，不再给出误导性的原因；
   - 追问轮的历史必须原样进入 prompt，否则报 history_not_in_prompt；
   - 以下都是准备错误：用例级的未知键、缺少 query、同时必须出现又禁止的课号（含 top_group 与 must_exclude 重叠）、同一列表里重复的课号或 notice、比 k 长的 top_group、旗标缺少对应的轨迹检查、hybrid 轮次缺 result_count、空的 vector_top_any 或 bm25_top_any、bm25_empty 和 bm25_top_any 同时出现、result_count 少于必须出现的课数或不等于 exact_ids 的长度；
   - CLI：未预期的异常退出 3，隔离违规退出 1；控制台行加上 isolation 和 accounting_errors；准备错误给出一行原因；
   - 路由评测的源码身份增加别名、上下文、筛选、门控和各仓储模块。
6. **检查器（MEDIUM＋LOW）。**
   - **记录归属：** 看数字前最近的来源。来源可以是记录、评价、论坛上的说法或别人（同学、有人、老师、旁听生、很多人、Reddit、commenter 等）、估计，也可以是记录缺口。
     - 说记录里没有这个数的记录词是缺口，不是来源。三种写法：
       - 记录词前有否定，中间只隔着数值或填充词（「未记录」「没有工作量记录」「没有该课程的工作量记录」「no recorded」「no workload in the record」「missing from the record」「not listed in the record」）；
       - 分句里的否定词后面是数值、数据词或什么都没有（「记录里没有工作量」「记录里没有每周学习时间」「记录里没有评价数据」「记录里没有。」「the record has no weekly hours」「the record doesn't report hours」「the record is silent on hours」）。也可以是：
         - 并列的第二个宾语，后面到分句结尾或转折词（「记录里没有评价和工作量数据，」「the record doesn't list exams or workload;」）。第二项以动词开头时是另一个谓语，不算（「has no reviews and lists the workload:」；「有关」不是动词）；跟在别的宾语后面的评分类词也不算（「no student reviews or ratings」）；
         - 补语说的也是数值（「no information about how many hours it takes」）；补语里的 office hours、lab hours、exam scores 不算；
         - 下一个分句以「也没有」「and no」「nor」接着说，宾语（连同并列的第二个宾语）里有评分以外的数值词（「记录里没有评价，也没有工作量数据」「也没有评分和工作量数据」；「, and no ratings」不算）；
         - 记录词的动词后面紧跟冒号时，冒号后面仍是同一分句（「记录显示：没有工作量数据」）；
       - 数值后面跟着「未知、缺失、不详、是空的」或 unknown、as unknown（「记录中工作量未知」「工作量一栏是空的」）；
     - 否定别的东西是记录说的内容，不是缺口：「记录显示没有期末考试，每周 12 小时」「记录显示没有数据结构的先修要求」「the record lists no data science prereq and 12 hours」「the record has no reviews but lists 12 hours」「the record has no details on the final exam but lists 12 hours」仍算记录。
       - 「数据结构」「数据库」「data science」「评分标准」这类复合词不算数据词；只修饰课程类名词的数值词也不算（「数值分析先修要求」「数值分析的先修要求」「评分比例」「data processing prereq」）；中间隔着「和、或」，或不是紧挨着「先修、前置」的「的」时不算修饰（「没有工作量和先修要求」「没有工作量方面的要求」是缺口）；
       - 学生、评价类词只在引出数据词、每周时间或估计时才算（「没有学生的评价数据」「没有学生每周学习时间的数据」「no reviewer estimates of hours」是缺口，「没有学生评分」不是）；
       - report、cover、track 在动词否定后面（doesn't track、not report）、数值词前面（中间可隔 on、about、the 之类），或不紧跟 no 时在分句末尾的代词前面才算（「doesn't track this course's workload」「doesn't cover it」是缺口，「no tracks」不是）；statistics 只在 on、about、for、of 前面算填充词（「no statistics on workload」是缺口，「no statistics course」不是）；
     - 只抹掉否定词和它的宾语，所以缺口里的「提到」「mention」不算报告，紧跟在后面的「有同学提到」仍算；
     - 「学生评价记录」算评价；
     - 单独的「说、表示、称、提到」不算来源：「记录明确表示 12 小时」「记录里提到 12 小时」仍算记录，「记录是 6，评价说 12」算评价；「名称」里的「称」不算；
     - 论坛（论坛、帖子、forum）在这几种情况下才算来源：
       - 后面紧跟报告动词、中间没有否定（「论坛上有人说」「the forum says」；「the forum does not mention」不算）；
       - 写成 forum posts／users 这类说法，或跟在「据」「according to」后面（论坛前面至多隔一个词）；
       - 数字就在同一分句里，离论坛不超过 20 个字，中间没有否定和连词，而且这个分句里论坛前面没有记录词（「论坛上的讨论显示每周 12 小时」「the forum consensus is 12 hours」）。转折词（while、but、而）也开始一个新分句，所以「the record lists 6 while the forum consensus is 12」里的论坛算来源。
       - 其他提到论坛的地方不算：「课程论坛很活跃，」「助教会在论坛上答疑，」「the TA answers questions on the course forum;」「论坛上没有人提到工作量，」「记录显示每周需要在论坛发帖并投入 12 小时」「the course has a discussion forum and takes 12 hours」；
     - 被否定的来源词不算来源，中间可以隔着「具体的、可用的、公布的、这方面的」这类词：「记录显示没有学生评价，每周 12 小时」「there are no available reviews」仍算记录；「没时间的同学说」仍算来源；
     - 来源只挡住记录归属；算不算报告仍看报告词，所以「有同学说」「Reddit users think」这类没有报告词的说法算 unattributed；
     - 旧上下文仍用 20 字符窗口。
   - **简写课号：** 补「或、以及、跟」、全角逗号、&、vs 和 Oxford 式「, and」。以下情况不当课号：
     - 后面跟着级别：-level、级、系列、以上、+，或区间「5000- or 6000-level」「5000–6000-level」「5000～6000 级」「5000 至 6000 级」。区间要有连字符、破折号或「至、到」；整千的数字之间用裸的 or、and、to、through、和、与、及、或、、、斜杠也算（「5000 or 6000-level」「5000/6000 级」）。所以「5200 or 6000-level」里的 5200 仍算课号；后面是「Level 2」这样的编号时不算级别；
     - 表示级别的完整课号：写成「CS 6100-level」的任何课号，以及后面跟着级别词、「以上」、不接课号的加号或带破折号、「至、到」区间的整千课号（「any CS 6000-level elective」「CS 6000 级」「CS 6000 以上」「CS 6000+」「CS 5000–6000-level」）。非整千的课号照算（「CS 5800 级别的课」「CS 5100 Level 2 sections」）；整千也可能是真课号（CS 3000、DS 3000），所以后面跟着裸连接词、接另一个课号的加号或「以下」时也照算（「CS 3000 + CS 3800」「DS 3000 and 4000-level」「CS 3000 以下」）；
     - 2010–2039 的数字后面跟着学期、目录、届或年份区间（2026–27）。DS 2001 这样的 20xx 课号保留。
   - **非估计数字：** 补「个学分」、-credit、第 N、N 周／月／日、N 个作业／项目、days/weeks/projects/exams、数字后的 GPA、序数词和月份名。月份名只认完整拼写和缩写，区分大小写，所以「Maybe 12」「Decent 12」仍算估计。
   - **引文冲突：**
     - 补「每周约／大约 N 小时」和 every week；
     - 上课类词（含 lab、recitation、实验课、习题课）只有在同一分句里紧挨着数字、且中间和它前面都没有「之外、不含、outside、besides」这类词时，这个数字才算上课时间，不算工作量；
     - 换行算分句结束（「Lecture: MWF」下一行「Homework: 10 hours/week」）；只有以这个数字开头的行（前面至多一个 about、约之类的词），在上一行只是标签或折行（没有每周数字，也不是「标签：值」）时才接着上一行，所以单独成行的标签或折行仍和数字在同一分句（「Lectures:」下一行「3 hours a week」），「Lectures: 3 hours a week」下一行「10 hours a week outside class」不是；
     - 指作业的说法不算上课：复合词（lab reports、实验课的报告、lecture notes、lecture prep），以及和作业并列的 lab／实验课（homework and labs）。其他上课类词和作业并列（「上课和作业每周约 10 小时」「Lectures and homework: 10 hours」）仍是含上课的总数，不比较；
     - 本身就是作业时间的小时数不算上课（「10 hours a week of homework」「10 hours a week on the project」「每周 10 小时作业」）；
     - 难度值要和「难度」在同一分句，不能是门数、小时数（含「3 - 5 hours」这样的小时区间）或量表，只取 1–5。量表只认 0 或 1 开头的写法（「Difficulty (1-5): 2」里的 1）；「Difficulty: 4-5」「难度 4～5 分」读第一个值。句末的英文句号不算小数点（「Difficulty: 3.」）。
   - **代码身份：** code_identity 增加 `llm/gemini_client.py`、`schemas/answer_evidence.py`、`schemas/course.py`；git_dirty 只看已跟踪文件；git status 失败时保留 git_commit。
   - 检查器版本升为 2.5-review-gaps。本批几次修复之间的判定有差别，但中间状态都没有发布，所以版本号以合并时这一版为准，没有逐次升版。
7. **测试：** 新增 `tests/test_opt06_review_round17_checker.py` 和 `test_opt06_review_round17_routes.py`。按上面的契约有意更新了两处：
   - `test_opt06_review_guards.py` 的退化测试：常数组不再断言丢失候选，只断言轨迹检查；指标分母改为 11／3／5；
   - `test_opt06_review_routes.py` 的来源标签。

第 17 轮验收（评审方，副本上）：20 文件定向（串行）**973 passed／4 warnings／50.73 秒**，串行全量 **4437 passed／7 warnings／335.74 秒，exit 0**；七个警告仍为三项 SWIG 类型和四次 HTTP 422 名称弃用。10 个 Python 文件 Ruff F/E9/B 通过，默认九布局快照全部相同，没有 --write。CLI 47 个用例、53 轮全部完成：路由 53／0、流式 53／0；生成侧 checked 44、hard_fail 5、stream_error 4、no_answer 1、not_applicable 4、partial_hard_fail 1；query_log 49 行，等于 HTTP 200 的 49 轮；隔离计数全为 0；三组指标 n=11／3／5，都是 1.0；配置差异正好是第 3 条的 5 项。路由探针：FAISS 插入顺序 64 种、BM25 顺序 23 种，判定和指标逐项相同；常数、倒序、截短和取样后丢掉 BM25 的打分各有用例失败。检查器探针：各份复核和评审方的 879 条，在 `fc15101` 和七次修复后的树上逐条比较，和前一版不同的都是有意的修复，旧上下文的结果不变。变异：第一次修复 178／182（另 4 个等价或被遮蔽），第一次跟进 134／134，之后依次 115／117、141／143、133／135、153／155、166／168（各有 2 个等价）。

### 已知、未处理

- 真实 API、真实模型和本机真实索引层不在本批，不读取真实数据。
- 同句课程／字段归属、冲突数值和课号检查只是有限文本信号，不证明答案正确，不自动跨句推断。
- 检查器的文本规则仍是有限启发式：
  - 记录归属看数字前最近的来源词，不做句法分析：「The record notes that others say it is fine and lists 12 hours」这种嵌套从句会算给别人；人名词表以外的说话人（如「主任称」）不算来源；
  - 缺口看否定词后面的词表：「没有提到难度」算缺口，「does not say how hard it is」不算；缺口也不分字段，说难度缺失（含「no ratings」）同样会挡住后面的工作量数字；
  - 缺口的几种句型之外仍会漏判或误判：
    - 「There's nothing in the record about workload」这种否定在记录词前、数值在后面的写法不算缺口；「Per the record: the workload is unknown」这种冒号前没有动词的写法，冒号结束分句，也不算缺口；「neither … nor」不算否定；
    - 记录词前的否定和记录词之间只要是填充词就算缺口，所以「Not that the record says much, but it lists 12 hours」算 unattributed；「the record lists difficulty 3, and not much else」仍算记录；
    - 「doesn't report that, but it lists 12」里的代词宾语算缺口，又因为缺口不分字段，后面的数字也挡住了；「no student estimates; it lists 12」同样算缺口；
    - 不修饰课程类名词的复合词（词表以外）仍可能误算成数据词；
  - 论坛离数字超过 20 个字、或中间隔着连词时不算来源，这类长句里论坛给的数字会算给前面的记录；反过来，「requires weekly forum posts and takes 12 hours」这种只是提到论坛帖子的写法会算来源；
  - 有报告词表以外动词的来源（「有同学说」「学长觉得」「Reddit users think」）只算 unattributed，不算 AS REVIEWER-REPORTED；两者都是要人看的信号；
  - 来源词后面紧跟否定（「RMP 上没有这门课的数据」）仍会挡住前面的记录归属；论坛后面跟着报告动词时，不看动词说的是什么（「置顶帖子提到了考试安排，每周 12 小时」算报告）；
  - 上课类词离数字超过 25 个字符就不看，所以「Lectures plus homework come to 10 hours a week」这类总数仍按工作量比较；含上课的总数（「每周 10 小时（含上课）」）不比较；标签和数字之间隔着空行时不再接成一个分句；
  - 非整千数字之间的裸 to、or 不算区间，所以「5200 to 6000-level」里的 5200 算课号；整千的完整课号后面跟着裸连接词的区间（「CS 5000 or 6000-level」）或另一个完整课号的级别（「CS 6000 or CS 7000-level」）时仍算课号，因为 CS 3000、DS 3000 这样的整千课号是真课；「CS 6000 及以上」「CS 6000 and above」也仍算课号；
  - 「Difficulty (1-5): 2」「Difficulty 0-5: 4」这类先写量表的引文读不到真正的难度值（宁可读不到，也不把量表当成值）；
  - 两段式日期（12/4、12-4）仍可能被当成估计；
  - 多课回答里一个课号都没写的句子，不检查冲突；
  - good 标签只承诺显式 expected_generation，不证明全部事实正确。
- 合成世界不代表真实检索质量；离线层固定 production_quality_verified=false。当前 hybrid 指标 n=11、向量专属 3、词专属 5，按整组计算，只是契约检查，不外推到真实课程分布。
- 离线档用的是代码默认值，不是 compose 里的部署配置（候选池 10、校准门、HyDE 救援、convex 0.7）；convex 融合和校准门没有被这份评测覆盖。compose 读取只认块写法，不认 flow 写法（`{KEY: v}`）和锚点。
- 轨迹只在 RRF 融合的入口取样。融合之后才出现的排序错误（例如融合在取样后丢掉 BM25 一路），只能靠 top_group、must_include 和 result_count 间接发现；能不能发现取决于 FAISS 怎么排并列分数，换 FAISS 版本可能变。
- 几条 NIT 没改，都不影响判定：重评结果里 code_files_sha256 和 answer_checks_sha256 并存；合成词表的 GPH 没有用例用到；summarize_reports 只校验证据层级，不按世界分组；所有轮次共用一个连接，也没有每轮超时；别名轮次的 must_include 不在 exact_ids 里、或 exact_ids 和 must_exclude 重叠时仍能通过校验（这样的用例永远过不了，但已有的打分测试正是用这两种写法检查 required_hit_missing 和 forbidden_hit_present）。
- 合成来源 URL 仍使用 NEU 域名：生产 schema 明确只接受官方目录 URL，本批不放宽或绕过校验。Synthetic 名称、标题、未核验说明与离线证据层标记保留，禁止任何网络访问；此 NIT 如需彻底替换，须另定来源 schema 契约。
- partial／no_answer／HTTP 决策分开列出；部分回答保留 checks 供查看，但不计入完整回答 checked 分母。已执行的预期失败脚本不等于 harness_error。
- 隔离针对项目已知接缝、Python audit 事件和合成连接；不是 OS 沙箱，不能阻止任意恶意 native／ctypes 调用、预先保存的其他原函数引用和合成世界之前就打开的 SQLite 连接，也看不到复制到受保护路径之外的数据库副本。当前零计数仅代表这些受控接缝没有触发非法尝试。

### 发布状态

分支 `feat/opt06-offline-route-eval`，原起点 `6e1a01d`，合并前已 rebase 到 origin/main `d97b382`（B 的第 24 节在前）。评审方的第 17 轮修复单独提交。本批只改评测工具和测试，不需要部署；文件虽随以后镜像打包，运行时不导入 eval。

## 26 — 脚本索引与两个调试脚本的删除（H，2026-10-19）

### 范围与原因

10-17 的只读脚本盘点（SIM-05）结论是：不合并辅助函数，加一份索引；两个一次性的调试脚本可以删。用户 10-19 确认：`scripts/enrich_course_via_rmp.py`、`eval/ragas_runner.py`、`scripts/seed_program.py` 都还在用，两个调试脚本删掉。从已合并 C 的 origin/main `d7c5530` 开分支。本批只加一份文档、删两个没人用的脚本，不改任何代码。

### 已实现

1. 新增 `scripts/README.md`：按用途分 7 组，列出 `scripts/` 和 `eval/` 下的全部 84 个脚本（75 个 Python、9 个非 Python）。每个写一行：用途、主要参数、会碰什么、状态。开头另写了几条：
   - 写库的脚本大多要加 `--commit`，不传 `--db-path` 时用配置里的库；
   - 哪些会碰线上：`deploy.ps1`，以及指向线上地址时的 `eval_via_api.py`、`probe_inference_latency.py`、`eval_answers_live.py`（都带 `X-Eval-Run` 评测标记）；
   - 测线上性能用 `eval_via_api.py`，不用 `eval/run_eval.py`；
   - `start_stack.ps1` 不加 `-Local` 会起接公网域名的 cloudflared 隧道。
2. 删除 `scripts/debug_aai_lookup.py`、`scripts/debug_print_chat.py`：05-08 的一次性排查，仓库里没有任何引用，也没有测试。
3. 和盘点的差别：
   - `eval/ragas_runner.py` 从「历史」挪到「评测和测量」，因为用户确认还在用；
   - 加上 C 新增的 4 个文件（`eval/route_world.py`、`eval/route_eval.py`、`eval/route_guard.py`、`scripts/eval_route_offline.py`）；
   - `seed_program.py` 和 `sync_program_plans.py` 各写一句分工：前者从 `data/program_seed/` 写方案和它的必修课、先修，后者写经过来源核对的结构化方案文档；
   - 盘点没覆盖的 9 个非 Python 脚本单列一组，内容取自各自文件开头的说明。

### 验证记录

- 删除前 `git grep` 两个文件名：仓库里 0 处引用。
- 用仓库外的核对脚本对照 worktree：
  - 每个文件恰好一行，没有指向不存在文件的行；
  - 表里列出的参数在对应文件里都存在；
  - 副作用标注和代码里的静态迹象逐条对过。对不上的 18 处都看过了，都不是错标：有的写法出现在合成库、临时库或内存里的参考 schema 里；有的联网、调模型发生在导入的模块里或服务端（HyDE）；有的只是文字里提到 Gemini；还有两处表里已经换了说法（登录 NAS、cloudflared 隧道）。`release_preflight.py` 是只读打开副本，表里补了「只读打开」。
- 串行全量 **4437 passed／7 warnings／334.76 秒**，退出码 0。和 C 合并后的 main 一样多：删掉的两个脚本本来就没有测试。7 个警告仍是 3 个 SWIG 和 4 处 HTTP 422 弃用。

### 已知、未处理

1. 「会碰什么」一列是按代码写法静态整理的，可能有出入，README 开头写明了。
2. 上线脚本用 tar 覆盖代码目录，不删多出来的文件，所以 NAS 上仍留着这两个调试脚本。它们不会被导入，不影响运行。

### 发布状态

分支 `docs/scripts-index`，起点 `d7c5530`。只加文档、删两个没人用的脚本，不需要部署。`scripts/README.md` 会随下一次上线上传到 NAS，不影响运行。

## 27 — 明确选择方案的聊天规则解释（F／OPT-04 第二步，2026-10-19）

### 范围与四条决定

从 origin/main `d7c5530` 单独推进；H（PR #18）10-19 先合并、占第 26 节，本分支合并前 rebase 到它上面。用户选择 F0 的四个默认项：年份并进方案；聊天仅可选 source_checked；无法确认的选择返回点名方案选择框的固定 409 并清选择；模型只用文字说明方案，来源链接在证据面板，回答链接白名单不变。

方案仅解释规则，不筛选或增加检索课程，不判断个人适用性、注册、毕业、累计学分、重复计入或学期安排。不改索引、门控、阈值、DDL、持久化 Course 或方案 seed；不做 G、H 或真实模型层。

### 已实现

1. PlanSelection 是请求和 PlanLink 的唯一范围定义，保持严格类型、extra=forbid、完整 scope 和内容 hash；plan 缺项目或家族不符是 422。服务端先核对存储身份／内容、范围唯一性、revision 和 source_checked，再检索；六种结果只有 selected 继续，其余固定 409，不自动采用同范围新版或旧 seed。
2. 纯 placement 按课程叶子、候选、排除、开放池排序后最多四处，并记录省略数；保留 OR 祖先、可选激活文字、最低门数／学分／领域和领域归属。任何显式提及都会抑制该课的开放池标签；开放范围不等于匹配，未提及也不表示禁止。
3. 先按明确方案年份取可用课程块，再做上限：命中时仅该年度、其余年度计数；缺年时保留原三份上限并标 requisite_year_not_recorded。无方案时不新增 null／0 字段，旧 meta 不新增 plan_context；只归一化耗时和必然升级的 prompt_version，53 轮 meta／课程块冻结哈希对拍。
4. 4.5 新增独立 Selected program plan JSON 块，放在历史块之前，不打断历史／新问题、notices／课程和课程／Answer 的旧解析边界。标签至多 300 字符，规则树至多 12,000 字符；超限整棵树省略，不截取部分规则。数据块另带检索课程在规则里的位置（和 meta 同一份 PlanContext，按检索顺序；自己另有 12,000 字符预算，超限整份省略）和项目全名，规则按这些位置的词来写：被方案点名的课没有开放池位置，不说它也能算进前缀／范围池。不给模型来源 URL、excerpt、HTML 摘要、reviewer 或 revision。明确部分规则、未知条件、独立成绩条件、不可双重计入和无资格／学期推断。所选方案的年度只叫「所选方案那一年的课程块」，不说成学生本人的规则；学生说的是另一年时，列出了就按那一年说明，没列出就说这里没有给出那一年，不说没有记录或不适用。
5. meta 的 PlanContext 一份对应本轮检索课程，包含经校验的来源和有界 placement，不重复方案树。获准保存反馈时，请求上下文只新增 plan_id 和 plan_content_sha256。409 在检索、query_log 和反馈之前返回，无新增记录；新日志事件只有固定 outcome 和有界 plan ID，不回显问题或选择范围。
6. 项目下的方案选择默认空，不单独放年份框。项目变化、列表 revision 变化、方案选择的 409 都在下一次创建组件前设 None，不 pop；409 只置待重置标记，不修改已创建组件。项目冲突等其他 409 不清选择；方案选择的 409 还会让这个项目缓存的方案列表过期，下一轮重新获取，不会在 5 分钟缓存内反复送出同一个过期版本（列表接口暂时不可用时会照缓存的设计显示上次的列表，侧边栏有提示，这时可能再碰到同一个 409）；是过期不是删掉，上一份仍是培养方案页比较的基准，列表没变时那一页的选择不受影响。五条 409 文字都说明这个问题还没有回答、方案选择已清除。列表 revision 更新提示一次。来源／位置在回答证据面板以安全文字显示；旧消息布局不变，不给模型新增可点击方案链接。

### 修改文件

- 新 `schemas/plan_selection.py`；更新 API models、ProgramPlanRepository、CoursePlacement／PlanContext／年度证据 schema 与构建器、4.5 提示词和路由。
- 新 `app/chat_plan_view.py`；更新聊天请求／历史／状态和证据说明；PlanLink 继承共享选择。新警告 `requisite_year_not_recorded` 加进答案检查的提示码列表，回答里印出它会是 `ids_fail` 硬失败，所以检查器版本升为 `2.6-plan-year`。
- 六份新测试（第六份 `tests/test_chat_plan_review.py` 来自评审）与未选方案哈希 fixture；`test_chat_plan_ui.py` 的 409 测试改用真实的方案 409 文字，固定装置拆出可复用的 `plan_curricula`；三个旧测试只把版本号 4.4 升到 4.5（年度规则、答案依据、提示词版本各一处），其余断言不动；C 的代码身份测试按新增的 9 个方案路径文件把 29 改成 38，并把其中 3 个加进必须包含的子集。共享离线页面替身补“家族无版本方案”的只读响应，不放宽编排断言。离线／固定证据工具补齐新关键源文件身份。
- 本节、program-plans.md，以及评审后补的 answer-grounding.md（4.5 和 plan_context）、course-requisites.md（方案已接入聊天）、answer-feedback.md（保存的上下文多了方案 ID 和内容版本）；`scripts/eval_answers_live.py` 的 `build_case` 说明它没有方案路径。命令、原始红绿日志、冻结哈希、具名变异与审查交接保存在仓库外 WORKLOG。

### 验证与审查

准备阶段九快照一致、47 用例／53 轮 C CLI 全部契约相符；核心和旧分享链接 110 项通过，新功能四文件 48 项通过，独立分支探针另行冻结。

开工前的漂移核对（F1）：PlanLink、scope_label、课程上下文和页面缓存接缝都还在原处；`normalize_code` 已是公共课程代码规范化的别名；新数据块放在历史块之前，C 的三个解析边界没有插进别的内容，解析器不用改。D19 里「原型在七份策展 seed 上的输出」重跑后和 D19 记录的逐字节相同（这是原型的输出；实现按设计另有关系名、300 字标签、四处上限和抑制开放池）。SAFE-02 的前提（日志有可扩展的统一字段白名单）不成立：普通 structlog 事件没有白名单，所以新事件 `chat.plan_selection` 用测试钉住精确字段集，并禁止出现问题原文。

收尾（10-19）：
- 串行全量第一轮 **3 failed／4492 passed**：三个旧测试写死了提示词 4.4 和 29 个代码文件，都不在 17 文件定向里（见上一节的修改文件）。改完以后串行全量 **4495 passed／7 warnings／398.24 秒**，退出码 0；7 个警告仍是 3 个 SWIG 和 4 处 HTTP 422 弃用。
- 17 文件定向 **565 passed／4 warnings／132.20 秒**；Ruff F/E9/B 通过；九快照默认核对 9/9 match，没有 --write；C 的离线 CLI 47 用例／53 轮 complete、退出码 0，路由 53／0，隔离计数全为 0。
- 55 个按函数选的具名变异 **55/55 killed**，每个都有具名的 FAILED 测试；范围是 10 个测试文件，不称全量变异。
- 两个只读独立审查在本地提交 `f9b4f0d` 以后进行。A19（正确性与各条路径是否一致）：1 HIGH、3 MEDIUM、6 LOW、6 NIT；B19（测试、文档与用处）：2 MEDIUM、10 LOW。两边都确认服务端核对、409 路径、隐私、检索不受影响和七份 seed 上的位置都成立；问题集中在模型拿到什么、页面在 409 之后怎么恢复、以及缺测试。
- 评审修复（10-19；用户定了把位置和项目全名放进提示词）：
  - HIGH：选了方案时，学生说出另一个已记录的年度，旧规则会让模型说「没有那一年的规则」或「不适用于你」。改成说明这里按方案的年度、那一年没有给出，并且不把方案年度说成学生本人的规则。
  - MEDIUM（两边都报）：位置原来只在证据面板，模型只拿到整棵规则树，Align 树里 CS 5800 既是核心课又在选修课号范围里。现在位置进入数据块，规则按位置的词写。
  - 方案选择的 409 之后，缓存里的旧版本会让学生在 5 分钟内反复撞同一个 409；项目冲突的 409 也会悄悄清掉方案。已按上面第 6 条修。
  - 证据卡片的年度那行在读不出、没有记录、只有方案年度时说法不对，已改；规则 1 和方案里才有的课号冲突，补一句只在说明规则时点名；选择框说明、「该组至少」、未写到的课那句按 B19 的建议改了措辞。
  - 两位审查的存活变异（A19 20 个、B19 27 个，B13 等价）交给新测试文件；新测试从两位审查的建议测试改写而来，并补了修复代码本身的测试。
- 评审修复后的验收（10-19）：Ruff F/E9/B 通过、没有 CR；新测试文件 38 passed；22 文件定向 **977 passed／4 warnings／101.14 秒**；九快照 9/9 match；C 的离线 CLI 47 用例／53 轮 complete、路由 53／0、隔离计数全为 0；串行全量 **4533 passed／7 warnings／396.86 秒**（警告和以前相同）。变异：两位审查留下的存活变异（其中 7 个的锚点被修复改写，按新代码重新锚定）加修复代码的 34 个，一共 80 个，**80/80 killed**；A10（删掉提示词里的草稿检查）第一轮活下来，因为不传 context 时 PlanContext 自己也拒绝草稿，补了「草稿配同一 ID 的合格 context 也要拒绝」以后杀死。
- 复核第 1 轮（10-19，A19、B19 续上，看 rebase 后的 `9feacc5..b1c0d89`）：A19 的 HIGH 和三个 MEDIUM、B19 的两个 MEDIUM 都确认修好，没有挡 PR 的问题。两人在 35 个路由用例和七份 seed 上核对过，提示词里的位置和 meta 完全相同、数据块里没有 URL。新发现三个 LOW，已修：
  - 方案 409 之后原来是删掉这个项目缓存的方案列表，培养方案页拿不到上一份来比较，列表没变也会清掉那一页的选择并提示「有更新」。改成让这一条过期（新的 `view_cache.expire`），上一份留作比较基准。
  - 方案那一年没有记录、照旧列出最近年份时，学生说的那一年可能就在里面，「这里没有给出」那句改成只用于没列出的年份。
  - 证据卡片在方案那一年的规则存了但没通过核对时也写「没有课程块规则记录」，改成「没有可用的课程块规则」。
  - 另外两处提示词措辞（「只有项目能确认」；指向「📘 所选方案与课程位置」），两处文档和一处注释不再把模型行为说成已验证，课程页那句「对话回答最多引用最近 3 个年份」补上选了方案时的情况。
- 复核第 1 轮修复后的验收（10-19）：Ruff F/E9/B 通过、没有 CR；22 文件定向 **978 passed／4 warnings**；C 的离线 CLI 47 用例／53 轮 complete、路由 53／0、隔离计数全为 0；串行全量 **4534 passed／7 warnings**（多出的 1 个是新加的 409 测试，警告和以前相同）。九快照 9/9 match 是在最后一处提示词措辞改动之前跑的；那处改动只动提示词文字和一个测试。受影响的 16 个变异（重新锚定的 2 个、新加的 5 个，以及 409 处理、卡片那一行和提示词规则的旧变异）**16/16 killed**；之后的措辞改动没有落在任何变异的锚点上。第一次验收时，新写的「panel under the answer」碰到了旧测试禁止的位置说法，改成只给面板名字。
- 复核第 2 轮（10-19，最后一轮，B19 看 `b1c0d89..49f3803`）：三条都确认修好，五条方案 409 之后都会重新获取列表，列表真变了仍会清掉培养方案页的选择并提示，新测试在修复前的树上失败；没有挡 PR 的问题。唯一的 NIT（列表接口暂时不可用时可能再碰到同一个 409）已写进上面第 6 条。

### 已知、未处理

- 没有真实模型抽查，**模型是否遵守 4.5 未用真实模型验证**；AppTest 不等于真实浏览器、账号或线上验收。
- 方案与课程块都只是记录文档，不证明个人适用、真实开课或注册核验的版本；partial／unmodeled／condition 不自动补全或计算。
- 规则树和课程位置各自 12,000 字符预算；超限需用户到培养方案页或证据面板核对，不自动扩大检索。05D 政策片段、个人草案、规划器不接入。
- C 回归仍用代码默认配置，不覆盖 compose 的 convex／校准门，不外推真实模型或部署质量。
- `scripts/eval_answers_live.py` 和答案检查都没有方案路径：问题不带方案，检查也不认识方案块里的字段名和方案里才有的课号（会算成证据外课号）。以后用真实模型评测选了方案的回答（OPT-06 第二阶段）时要先补。
- 评审里留着没做的（都已失败时保守，或只影响说法）：
  - 同一份坏文档，培养方案页只藏它，聊天选择框什么都不给，06A 分享解析整个项目不可用；三处都不会用坏数据，但说法不同。
  - 超过 200,000 字符的合法方案会出现在列表里，选了却总是 409「无法确认」；现有 seed 最大约 20 KB。
  - 证据面板的「📘 所选方案与课程位置」默认折叠、标题不写方案名，里面仍用项目 ID 和 concentration 标识；选了方案以后的页面布局没有快照，只有一个测试钉住它在「📎 相关课程」之前。
  - `PlanSelection.catalog_year` 等用 `\d`，会接受全角等非 ASCII 数字，路由会答 409「已变化」，没有坏处；`ProgramPlan.program_id` 没有格式限制，现有 ID 都符合。
  - 没选方案时，规则里那句「program rules are not covered by course blocks」比 4.4 弱了一点，没有测试钉住；课程详情页仍显示最新三年，聊天按方案只用一年，详情页没说明这一点。
  - 提示词里的 context 检查只比方案 ID 和课程集合，不比内容版本；路由只用一个对象，所以只是理论上的缺口。证据面板里「本组选明确排除」的说法没改。
  - 几个 NIT：未选方案的哈希测试同时接受 4.4 和 4.5（版本另有测试钉住）；页面坏上下文测试用的字典缺 14 个字段（证据测试覆盖了只有 URL 坏的完整上下文）；列表 revision 按整个项目算，草稿或别的路径变了也会清掉没变的选择（按 D19 设计，提示文字可以说得更准）；`code_identity()` 没收 `app/program_view.py` 和 `app/text_render.py`。

### 发布状态

分支 `feat/selected-plan-chat`。评审修复后 push、开 PR，由用户合并；合并后单独上线（不等 G），上线日期和授权由用户定，上线后跑 P6 评测和 8 个问题的 4.5 真实模型抽查。浏览器验收由用户做。

## 28 — 课程对比页第一版（G，2026-10-19）

### 范围与原因

学生在课程详情中挑选最多四门课，并排查看已有信息。不用模型选课，不计算总分，不判断个人资格。用户要求现在开始 G；F 尚未合并，所以从 `origin/main` 的 `38529f4` 开独立分支，不引入 F 的待复核代码。§27 预留给 F；合并前按实际合并顺序核对编号，并在 F 合并后 rebase、重新全量。F 已于 10-19 合并（PR #19，§27），本分支随后 rebase 到 `56a03d6`。

### 已实现

1. 标签页内保存有序课程 ID，去重、最多四门。登出清空；清空对话、搜索或打开详情不清空。只存 ID，不存详情、不写数据库。
2. 详情标题下加「➕ 加入对比」；已加入时显示计数并禁用，满额时提示先移出一门。搜索结果及聊天历史里的「查看」不新增按钮。
3. 导航末尾追加「⚖️ 课程对比 · Compare」，原来三个页面索引不变。空列表说明入口；非空列表可清空、逐门移出、返回搜索页查看详情，不重发聊天请求。
4. 每次渲染每门一次既有 `get_course`，最多四次 GET，共用当前会话的 ApiClient，不加缓存或新 API。一个请求失败只影响自己的列，仍可移出。每字段一组等宽列，后续行不随描述长短错位。
5. 固定展示：课程头、目录描述／存档与抓取日期、学生评价里的估计、年度先修／共修摘要、主题、考核、旧培养方案关系及未核验说明、缺失字段、操作。抽取字段复用 HTML 转义 helper，描述和先修摘要用纯文本；未知缺失字段也转义。零值估计不隐藏；缺失不解释为零或无要求。
6. 先修摘要使用完整 `course_requisites` 列表，不使用聊天里最多三年的块或旧平铺边；验证格式、来源、身份及重复年度。已解析条款比较规则树，未解析条款比较完整原文，共修单独参与；不默认个人适用年度，不把 not_listed 当没有要求。
7. 评审修复（10-19，见下面「审查」）：
   - 每个格子的标签和两个按钮都写上这一列的课号，失败的列写 id。手机宽度下 Streamlit 会把四列叠起来，表头离得很远，不写就分不清是哪门课。
   - 只针对某一格的提醒放进那一格：估计值不一致放估计那格，主题没有来源放主题那格，目录学分不一致、测试数据放表头下面。描述那一行的整行提醒照旧。
   - 取课时核对返回内容：不是对象，或者 `course_id`／`primary_code`／`primary_name` 不是字符串，这一列就算失败，写「服务返回了无法识别的内容」。每个格子再单独兜底：一个字段类型不对，只有这一格写「这一项的数据格式不对」，别的格子和别的列照常。
   - 失败的列写出是哪门课。有失败的列时多一个「🔄 重新加载」按钮，只重跑页面，不清列表。页面上说明列表只在这个会话里，刷新、登录或退出以后要重新加入。
   - 本课程最新一份年度文档的标题学分是范围时，表头下面写出年度和范围，说明实际班次学分未声明；同年度有冲突记录时不写。
   - 先修的两句提示补上「不表示没有先修或共修要求」。没有 `answer_evidence` 时说「目录存档情况没有记录」，不说没有存档。抓取日期改用详情页的格式。空页面说明去「🔍 课程搜索」页加课。

### 修改文件

`app/state_manager.py`、`app/course_detail_view.py`、`app/streamlit_app.py`；新建 `app/compare_view.py`。新建状态／页面测试，更新既有编排测试的页面结尾调用数；只更新 `detail-200` 快照（标题后新增一个按钮，其余节点仅同级索引位移）。评审修复只改 `app/compare_view.py`，新建 `tests/test_compare_review.py`，`tests/test_compare_view.py` 抽出 `make_backend` 并跟着新标签和新措辞改了三处断言；`docs/course-requisites.md` 加了一句对比页。本节之外的 API／检索／模型／数据库代码不变。

### 验证记录

- 基底九快照 9/9 一致，离线合成路由 47 用例／53 轮通过；先测后改，状态首轮 6 failed／3 passed，页面首轮 23 failed。原始状态与页面断言保留，后来仅追加边界测试。
- 最终 12 文件定向 **501 passed／3 warnings／34.13 秒**；Ruff F／E9／B 通过；串行全量 **4477 passed／7 warnings／459.42 秒**，退出码 0。基底 main 为 4437，本批新增 40；F 尚未合并，不拿它的 4533 作为此分支基线。警告仍为 3 个 SWIG 和 4 处 HTTP 422 弃用。
- 九快照 9/9 match；仅 `detail-200` 的新增按钮已逐行审核，并独立移除该节点、还原索引后与基底 JSON 完全相同，其余八份字节相同。导航不在快照范围，由 AppTest 精确验证四项顺序。
- C CLI 最终仍为 **47／53 complete**，route 53／0，预期错配、隔离计数和账目错误均为 0，退出码 0；仍是代码默认配置的合成离线层，不是部署配置或真实质量验收。
- **35 个具名变异**：最终在全部 40 项新测试上重跑，34 项由框架确认 killed；G18 实际触发 KeyError，但框架把失败堆栈里 `app.run(timeout=45)` 的参数名保守判成 SUSPECT。单 worker 串行重跑，具名测试、明确 KeyError、无实际超时均已核对，作为第 35 项失败证据单列，原始 runner 的 `34/35`、exit 1 和 SUSPECT 不改写。首轮 G13 页脚变异存活，揭示只搜 CSS 类名不足；追加完整实际页脚断言后已杀死。没有把只有超时的结果当 killed。
- 三项仓库外独立探针通过：原始 404 消息按纯文字显示且其他列正常、手动 rerun 从失败恢复、合成的 on_click 登出按钮调用 `logout` 以后下一次运行不再读取详情（产品里的登出按钮在侧边栏里直接调用并 rerun，AppTest 里侧边栏打了桩）。没有真实网络。
- 最终文件白名单、UTF-8／LF、原始断言、布局变化及完整代码／测试 SHA-256 核对通过；全量开始后没有改 Python 或快照，只补结果文档。红绿日志、原始变异 FAILED 名、串行复核、工具和文件哈希留在独立 WORKLOG。
- 评审修复以后（10-19 晚，基底仍是 `38529f4`，rebase 之前）：13 文件定向 **525 passed／3 warnings／35.44 秒**；Ruff F／E9／B 在分支改过的 8 个 Python 文件上通过；九快照 9/9 match；C CLI 仍为 47／53 complete，route 53／0，隔离计数为 0；串行全量 **4504 passed／7 warnings／408.86 秒**，退出码 0，比 `b8551ba` 的 4477 多出的 27 项就是新测试文件。
- 修复的变异 84 个：对比页原有的具名变异 21 个（其中 2 个改了锚点）；两位审查的存活变异 22 个（29 个去掉 2 个等价、5 个两人重复的，锚到修复后的代码）；审查时已杀死、所在函数改过的 9 个；修复代码本身的 32 个。**84/84 killed**，没有只靠超时判定的。
- rebase 到 `56a03d6` 以后（`cd84ac3`）：只有 change log 要解决；其他文件里 G 的增删行前后逐字节相同。13 文件定向 **528 passed**；Ruff 通过；九快照 9/9；C CLI 47／53 complete；串行全量 **4601 passed／7 warnings／493.14 秒**，退出码 0，等于 main 的 4534 加上 G 的 67。
- 复核以后的第二个修复：变异 10 个，**10/10 killed**。其中学分提示和会话说明原有的变异 6 个（2 个改了锚点），B20 存活的 2 个，年度文字 2 个。13 文件定向 **529 passed**；Ruff 通过；九快照 9/9；C CLI 47／53 complete，route 53／0，隔离计数为 0；串行全量 **4602 passed／7 warnings／483.25 秒**，退出码 0。全量开始以后只补了本节的数字。

### 审查

两个只读独立审查在本地提交 `b8551ba` 之后进行（10-19），另由协调方在副本上复现了全部数字和 35 个变异。
- A20（正确性与各条路径是否一致）：没有 CRITICAL、HIGH；2 MEDIUM、4 LOW、3 NIT。比较逻辑和 16 种先修组合都与详情页一致，所有字段的恶意值都被转义；F＋G 叠在一起的测试在 F 的两个末端上都通过。
- B20（测试、文档与用处）：把手机宽度那条定为 HIGH（从 Streamlit 1.57 的源码推断，没有在真实浏览器上看）；3 MEDIUM、5 LOW、几条 NIT 和 3 条文档意见。
- 两边都报的：手机宽度下列会叠起来，格子和按钮不写课号；测试没有把每一列的表头和这一列的字段对上（两人共 45 个变异，活下来 29 个，其中 2 个等价）；只针对某一格的提醒放在描述那一行。
- 修复见「已实现」第 7 条。新测试文件 `tests/test_compare_review.py` 从两位审查的建议改写而来：按列核对、整句断言放在对应的行、404 原文转义、503 固定文字、无法识别的返回、单格兜底、重新加载、范围学分、详情面板的计数。
- 复核第 1 轮（最多两轮，10-19 晚，在 rebase 后的 `cd84ac3` 上）：两人都说没有挡 PR 的问题。各自上一轮的问题都已修好，或已列为已知；所有存活变异都被针对改动的断言杀死。手机那条按同样的源码规则看已经解决，真实手机仍要用户看。F 和 G 在同一棵树上，状态、登出、导航都不冲突，A20 的 286 项定向测试全过。
  - 新报的只有 B20 的 1 个 LOW 和几条 NIT。LOW 是范围学分的两处保护没有测试：别的课的文档、同年度两份记录。两人的 NIT：提示不写年度、会话说明漏了「登录、退出」、本节缺 rebase 后的数字和新基底。这些都在第二个修复提交里改了（补两项测试、提示写出年度、改说明和文档）。
  - 其余列为下面的已知 10–12。第二个修复只动措辞、测试和文档，没有开复核第 2 轮。

### 已知、未处理

1. 可选 G4 对比分享链接留到第二版；现有 `?course=`、`?program=` 和一次性深链语义不变。
2. 每次 rerun 最多四次同步详情 GET；不加缓存，所以响应时间受服务端影响；四个各自超时可能顺序累积。这版不新增重试或请求并行。
3. 对比只展示旧 `program_context`，明确未核验；不把 F 里的聊天方案选择变成个人学位适用或排名。
4. AppTest 验证容器结构，不等于真实浏览器、窄屏可读性或无障碍验收。每格写课号是按 Streamlit 的窄屏规则推断后加的，没有在真实手机上看过。
5. 对比列表只在 Streamlit 会话里：刷新浏览器、Google 登录跳转、退出都会清空，页面上已写明。
6. 先修那一行只说记录了哪些年份、各年是否相同，不说每一段的状态；每段状态留到第二版。「清空对比」一键清空、没有撤销；「旧 seed 关系」等说法和全站一致，以后一起改。
7. 从对比页点「查看详情」回到搜索页，聊天里选的项目和 F 的方案选择会被 Streamlit 清掉（没渲染的组件会被清理）；从培养方案页往返也一样，不是 G 新引入的。
8. 详情页把课程加载失败的错误原文按 Markdown 显示（对比页已转义）；不在 G 的范围，以后和别的显示加固一起改。
9. 超过四门的旧会话（现在已经加不进第五门）在第五门的详情里会显示「（5/4）」。
10. 单格兜底不记日志（`app/` 没有 logger），所以如果是代码出错、恰好是那四类异常，线上只会显示「这一项的数据格式不对」，查不到原因；测试里每一格都有内容断言，能抓到。兜底之前已经画出来的内容会留在提示上面；只有接口返回的数据格式不对时才会这样。
11. 学分提示只看最新一份本课程年度文档，只在它是范围时提示；固定但不是整数的标题学分（如 1.5 Hours）和表头整数不一致时不提示，真实记录里有没有这种情况没有核对。
12. 学分提示用的是最新一年的标题学分，提示里写出了年度，但那一年不一定是学生适用的年度；详情页要学生先选年度才显示学分证据。

### 发布状态

分支 `feat/course-compare`，10-19 晚 rebase 到 F 合并后的 `56a03d6`。复核第 1 轮通过以后 push、开 PR，由用户合并。G 只改页面，上线另行授权，可以等下一次上线一起上。没有使用真实模型、账号、运行数据库或 NAS。

## 29 — 运行日志里不再记学生问题的原文（K／Z5，2026-10-19）

### 范围与原因

成功请求的结构化日志里记着学生问题的原文：`chat.retrieved`、`search.hybrid` 等记整句，`rescue.*`、`chat.context_path` 等截到 80 个字。`query_log` 表本来就存原文，导出要两个开关一起给才带原文，所以日志里是多出来的一份副本，而且是最常被翻看、粘贴的那一份。用户 10-19 在三个选项里选了「只记哈希和长度」（留着、截短、只记哈希和长度）。G 先合并（PR #20，§28），所以本节是 §29。

### 已实现

1. 新模块 `api/query_fields.py`：`query_fields(text, name="query")` 返回 `{name}_hash`（16 位十六进制）和 `{name}_len`（字符数）。
   - 哈希是 HMAC-SHA256。密钥用 `SESSION_SECRET` 加固定标签派生，和会话令牌的签名分开。学生的问题短、好猜，普通哈希挡不住「猜一句、算一下」，所以用带密钥的。
   - 有密钥的人对 `query_log.query` 算同样的哈希，就能找到对应的日志行；做法写在 `docs/pii_redaction.md` 第 11 节。
   - 没配 `SESSION_SECRET`（本地开发、测试）时用每个进程随机的密钥：同一进程里一致，对不上 `query_log`。
   - 问题和密钥里不成对的代理字符都不会让日志调用抛异常（编码都用 `surrogatepass`）。环境变量里解不开的字节会变成代理字符，原来严格编码密钥的话，每个 `/search`、`/chat` 都会 500；正常密钥的结果不变。
2. 16 处日志调用改成只记哈希和长度，共 17 个事件名：
   - `/search` 7 处、8 个事件名：`search.alias_anchor_filtered_fallback`、`search.alias_hit`／`search.alias_filtered_empty`（共用一处）、`search.prefilter_applied`、`search.hybrid_empty`、`search.rejected`、`search.hyde_rescued`、`search.hybrid`；
   - `/chat` 5 个：`chat.hyde_rescued`、`chat.retrieved`、`chat.context_path`、`chat.alias_anchor_filtered_fallback`、`chat.prefilter_applied`；
   - HyDE 救援 4 个：`rescue.code_pattern_guard`、`rescue.declined`、`rescue.empty_retrieval`、`rescue.accepted`。

   两个 `prefilter_applied` 记的是去掉专业前缀以后那一句，字段名是 `sanitized_query_hash`、`sanitized_query_len`。其余都对原问题算，和 `query_log.query` 是同一段文字。
3. 新事件 `query_log.written`：`log_query()` 写入成功以后记一条，只有行号 `query_log_id`，两条路由共用这一处；写入失败时不记，照旧只有 `query_log.write_failed`。同一个请求的日志行都带着同一个 `request_id`，所以用它就能把日志和 `query_log` 那一行对上，不用密钥，换 `SESSION_SECRET` 以后也照样能用。这是 B21 的建议，用户 10-20 定了要加。
4. `query_log`、导出、接口响应和别的日志字段都不变，日志里只是多了 `query_log.written`。
5. 评审修复（10-20，见「审查」）：
   - 静态检查扩到 `bind`／`new`／`bind_contextvars` 和 `print`，事件名必须是常量，问题文字的来源扩到 `retrieval_query`、救援拼出来的文字、历史消息等；检查规则本身也有正反两组测试。
   - 运行时检查改用 parity 测试的场景，14 个请求走遍 17 个事件的每条路径。每个场景都检查：日志事件里（连请求上下文里绑定的字段）、`print` 输出里、经过真实 `configure_logging()` 渲染出来的日志行里都没有问题原文；每个哈希都等于 `query_log` 那一行按文档算法算出的值；`query_log.written` 的行号就是那一行的 `log_id`。
   - 另补：第三方库 INFO 日志由 root 过滤器替换的测试，写入失败时不记行号，密钥里有坏字节，长度算上首尾空格。子进程测试只给最小的环境变量。
   - `docs/pii_redaction.md` 第 11 节重写：对照方法（先用 `request_id` 和 `query_log.written`，只有哈希时用容器里的完整命令）、能看日志又能提问的人可以问一遍再比哈希、回退和旧日志、本地开发、测试实际钉住了什么。
6. 复核后的小修（10-20，见「审查」里的复核），只改测试和文档：
   - 静态检查再补上 `log.log`（事件名是第二个参数）、`fatal`、structlog 的异步写法（`ainfo` 等）、`bind_threadlocal`、`warnings.warn`、`builtins.print` 和写 `sys.stdout`／`sys.stderr` 的调用。`**` 展开的键必须看得出来：字典字面量、`dict(...)`、已知的辅助函数，或人工核对过的两处错误字典。
   - 事件表和代码对照：代码里展开 `query_fields(...)` 的事件必须正好是表里的 17 个。
   - 新场景：`/chat` 的前几轮对话里也放了标记字符串。新测试：提交失败时也不记行号。
   - 文档：第 11 节的容器命令改成顶格写，可以直接复制，测试说明跟着更新；`docs/api_contract.md` 补上 `sanitized_query_*`；本节两处变异计数改正。

### 修改文件

新建 `api/query_fields.py`、`tests/test_log_query_fields.py`；改 `api/routes/search.py`、`api/routes/chat.py`、`api/routes/common.py` 里的日志调用，`log_query()` 加 `query_log.written`；`tests/test_retrieval_decision_rescue_rules.py` 里两个测试原来钉着 `query` 字段，改成期望哈希和长度；`docs/pii_redaction.md` 加第 11 节。评审修复又改了 `api/query_fields.py`（密钥编码、说明）、`api/routes/common.py`（新事件）、`tests/test_log_query_fields.py`（重写）和这两份文档。复核后的小修只改了 `tests/test_log_query_fields.py`、`docs/pii_redaction.md`、`docs/api_contract.md` 和本节。

### 验证记录

- 新测试 15 项是和代码一起写的，没有先跑一遍红。改用 31 个变异来证明测试有效：16 个把调用改回记原文，都被静态检查抓到；5 个对错误的文字算哈希，都被路由测试抓到；10 个削弱哈希函数，都被单元测试抓到。**31/31 killed**。
- 第一遍 12 文件定向有 3 项失败：`tests/test_retrieval_decision_rescue_rules.py` 有两个测试钉着旧的 `query` 字段，其中一个按路由参数化成两项。改掉这个字段正是本批的目的，测试改成期望哈希和长度以后通过。
- Ruff F／E9／B 通过；九快照 9/9；C CLI 47／53 complete，route 53／0，隔离计数为 0。
- 串行全量 **4549 passed／7 warnings／485.08 秒**，退出码 0，等于 main 的 4534 加上新的 15 项。上面那两个测试是在这次全量开始以后才改完的，所以在本地提交 `02217c5` 上又跑了一遍：12 文件定向 **308 passed**、Ruff 通过、串行全量 **4549 passed／7 warnings／509.25 秒**，退出码 0。
- 评审修复以后：
  - 变异 66 个：协调方原来的 31 个（H2 换了锚点）；两位审查的 29 个，即 A21 的 13 个和 B21 的 B01–B16，第一轮活了 25 个（B17 实际等价、B18 和 A13 相同，没再跑）；再加 6 个针对修复本身的（不记 `query_log.written`、行号记错、带上原文、写入失败也记；密钥严格编码、用 `surrogateescape`）。第一遍 **64/66**：A09（`search.alias_filtered_empty` 改个字段名）和 B13（`chat` 锚点回退只对前 40 个字算哈希）活下来，因为测试没要求每个该有的事件都带哈希字段，场景里的问题也太短，截不截都一样。测试补上这两点（场景里的问题都长于 80 个字）以后，第二遍 **66/66 killed**，每个都由对应的测试抓到，没有一个是靠超时算的。
  - rebase 以前（`56a03d6` 加修复）：新测试文件 65 项；12 文件定向 **358 passed**；Ruff 通过；九快照 9/9；C CLI 47／53 complete，route 53／0，隔离计数为 0，输出和 main（`56a03d6`）的一次运行只差合成用户名里的运行号；串行全量 **4599 passed／7 warnings／443.74 秒**，退出码 0，等于 main 的 4534 加 K 的 65 项。
- rebase 到 `deaf750`（G 合并以后）：只有这份变更记录要合，结果是 main 的文件加本节。K 别的文件逐个比过，加减的行和 rebase 前完全相同；评审修复放回去以后也逐字节相同。rebase 以后：新测试 65 项；12 文件定向 **358 passed**；Ruff 通过；九快照 9/9；C CLI 同上，和 rebase 前的输出只差运行号；串行全量 **4667 passed／7 warnings／477.72 秒**，退出码 0，等于 main 的 4602 加 K 的 65 项。
- 复核后的小修：
  - 变异 77 个：上面 66 个重跑，加 11 个针对复核指出的写法（`warnings.warn`、`log.log`、`fatal`、异步写法、写 stdout、`builtins.print`、`**dict(...)`、`**extra`、换个名字记历史消息、提交以前就记行号、事件表里没有的新哈希事件）。**77/77 killed**，每个都由对应的检查抓到。A10（事件改名）现在先被事件表对照抓到，其余 65 个和上一轮由同一个测试抓到。
  - 新测试文件 84 项；12 文件定向 **377 passed**；Ruff 通过；九快照 9/9；C CLI 同上，和上一次的输出只差运行号；串行全量 **4686 passed／7 warnings／432.88 秒**，退出码 0，等于 main 的 4602 加 K 的 84 项。

### 审查

两路只读审查在本地提交 `02217c5` 之后进行（10-19 晚），协调方复现了要点。两人都说产品改动本身是对的，没有 CRITICAL、HIGH：
- A21 用真实日志配置（JSON 和控制台两种）发了 60 个请求，走遍各条路由、救援、流错误和各种错误响应。日志里都没有问题原文；16 处调用的哈希都等于那一行 `query_log` 的值；响应、`query_log` 行和事件名和改之前完全一样。
- B21 也走了真实 JSON 管道，结论相同；文档里的对照片段能找对行，也不打印原文。

问题都出在测试、文档和上线检查上：
- **MEDIUM（两人都报）：** 测试看不到 `bind`／`bind_contextvars`／`print`，`capture_logs()` 也不收请求上下文里的字段。往路由里加一句 `bind_contextvars(query=req.query)`，全部测试照样通过，线上日志里却会出现原文。已修：静态检查扩大，运行时检查合并 contextvars、看 `print`、看渲染出来的行。
- **MEDIUM（B21）：** 上线检查里有一步拿问题原文去日志里找请求（P6c），K 以后会静默找到 0 条。上线工具不在仓库里，下次上线前改成按 `request_id`／`query_log.written` 找。
- **LOW：** 17 个事件名里有 6～7 个没有运行时检查（已修，14 个场景走遍）；坏字节的密钥会让每个请求 500（已修）；文档把「没有密钥就确认不了」说过头了，还缺操作步骤（已修）；第三方 INFO 日志的过滤没有测试（这是旧代码，已补测试）。
- **NIT：** 「16 个事件」其实是 16 处调用、17 个事件名；检查规则的自测是另写了一遍；子进程测试把整个环境传过去；长度没测首尾空格。都已修。
- **建议（B21）：** 多记 `query_log_id`。用户 10-20 定了要加，见「已实现」第 3 条。
- 两人的变异：A21 13 个，活 12 个；B21 18 个，活 15 个（其中 1 个实际等价）。修复后的结果见「验证记录」。

复核第 1 轮（最多两轮；10-20，对 rebase 以后的 `35108a4..99fa4d2`）：
- 两人第一轮的问题，仓库里的都修好了。B21 的 M1 在上线工具里，等下一套上线工具：新版 P6c 已经写好，按哈希找请求，还没在 NAS 上跑过。
- rebase 只动了这份变更记录；G 的页面测试和 K 的测试一起跑，218 项都通过。
- `query_log.written` 只带行号，写入失败和错误响应时都不出现；响应、`query_log` 行和原有事件名都没变。
- 渲染日志行的测试有效：单独跑、换成控制台格式、排在别的配置日志的测试前面或后面，都能抓到泄漏。
- 两人另写的变异：A21 20 个，活 3 个；B21 7 个，全被运行时检查抓到。

新问题没有 CRITICAL、HIGH、MEDIUM：
- **LOW（B21）：** 静态检查还认不出 `log.log`、`fatal`、异步写法、别名、`sys.stdout.write`、`**dict(...)` 和 `**extra`，运行时检查只在 17 个事件的路径上抓得到。已修，别名和名字里没有 log 的 logger 除外（「已知」第 5 条）。
- **NIT（A21）：** `warnings.warn(问题)` 两道检查都看不到（已修）；提交失败时会不会记行号没有测试（已修）；场景没走到的路径上的间接泄漏抓不到（「已知」第 5 条）。A21 还建议从代码里读出事件表，改成了和代码对照。
- **NIT（B21）：** 没有带历史消息的场景（已修）；第 11 节的命令缩在列表里，从原始文件复制会出错（已修）；本节两处变异计数（已修）；`api_contract.md` 漏了 `sanitized_query_*`（已修）。
- 这些只改测试和文档，所以没有开第二轮。

### 已知、未处理

1. 哈希和长度仍是私有的可关联数据：同一句话的哈希总是相同，能看出同一个问题问了几次；不能当成匿名数据公开。能看日志、又能提问的人，可以把猜的那句问一遍，再找相同的哈希，所以日志的访问要和 `query_log` 一样管住。
2. 换 `SESSION_SECRET` 以后，旧日志里的哈希就对不上 `query_log` 了，`query_log.written` 不受影响；这版不另设日志专用密钥。
3. `query_log` 的留存、删除和备份不变；Google sub 成功事件、请求路径和 uvicorn access log 的查询字符串也不在这批。
4. 没有单独的对照脚本，`docs/pii_redaction.md` 第 11 节写了完整命令。
5. 静态检查只是一道绊线：把问题赋给别的名字再记、给 `log.info` 起别名、用名字里没有 log 的 logger，它都看不出来。靠的是运行时那 15 个场景，而场景只走 17 个哈希事件的路径：`/chat` 的方案捷径、方案课表未核对、流式出错、409 和检索结果为空这些路径上，这类间接泄漏抓不到。新加的哈希事件会被事件表对照逼着加场景。
6. 上线以前写下的日志行还在旧容器的日志里，容器重建以后才会消失；回退到这一版之前的镜像，日志里会重新出现问题原文。

### 发布状态

分支 `fix/log-query-hash`，基底 `deaf750`：G 合并以后 rebase 过来，只有这份变更记录要合。随下一次上线生效，上线要另外授权；不改配置、数据库或 NAS。上线检查里按问题原文去日志找请求的那一步，要先改成按 `request_id` 或 `query_log.written` 找。

## 30 — 会话内选课草案第一版与课程读日志隐私（I，2026-10-19 至 10-20）

### 范围与原因

从 F 合并后的 `origin/main` `56a03d6` 开独立分支，按 D1–D8 默认实现会话内、解释型草案。初始版本不含 G；中途审查后按用户要求 rebase 到 G 合并后的 `deaf750`，保留 G 的状态与完整 §28，I 改为 §30，§29 给独立 K 批次。不是学位、成绩、先修或注册资格审核，不写 `user_courses`，不把清单交给聊天或模型。

设计稿同时要求“不改 API”和“清单不进日志”，但既有 resolver 记录 ref 原文、middleware 记录具体课程路径。内存探针复现后，用户明确授权先做最小脱敏再推进。因此本批还修复这些应用日志出口，路由参数、响应与数据库契约不变；学生问题原文的 K 批次仍独立。

### 已实现

1. `schemas/plan_draft.py`：最多 20 门规范化课号，零学分与未知分开；course／AND／OR／组选／optional／文字条件／未建模七种节点的同形结果树与原因。门数、学分、领域逐项合并；开放池只可能计入，未知学分上界用既有 schema 的 12，不据此声称已满足。输出的学分差是已知确定学分距目标的差，不冒充必须补修学分。
2. 重复计入按路径区分规则组：先去掉全部可能重用的确定候选，再重算；依赖重用才能满足则不确定。OR 的互斥出口不当成同时要求，不自动替学生选出口或分配课程。optional 后代仅列出，不计算状态、不占用重用统计；partial 根不会显示 met，总结排除根与 optional 后代。
3. 开放池只排除整份方案里的必修课号（`course` 叶子）和任何位置的排除项；别组的有限候选可以在本组范围里算“可能计入”（H3，见下）。初版从 F 提取的全局点名判断 `explicitly_named`（包括排除名单）现在只给 F 的 placement 用，草案不再调用；不误用最多四条的 placement 输出作为完整匹配。F 原有顺序、输出与 omitted 保持不变；309 个输入逐项对拍一致。
4. 培养方案页在 05D 之后、旧 seed 之前显示草案，仅 source_checked 可用。输入核对、无匹配／歧义／失败／无效字段提示，原始输入和来源文字安全显示；只有点击加入才取数据，每批最多 20 次 resolve＋20 次详情 GET。普通 rerun 不重复取；换方案保留课程、重新计算；登出、换账号、清空时连未提交的输入框文本一起清掉。新会话空白，不存 cookie 或磁盘。
5. 学分是加入时的课程记录，不承诺班次或个人学位计入；未知数据明确标记。每门课只提供既有课程页深链供查看年度先修，不判断先修，不分享清单。
6. 日志隐私：resolver 不再发 ref 原文；课程读取路径只记模板，最终事件白名单过滤正常／异常下游的课程 ID、代码、来源等数据，只保留计数、状态、耗时、request_id 与安全错误类型／栈位置。独立 UI 进程的 HTTPX 源 logger 也会去掉课程读 URL 的 ref、具体路径与 fragment，保留方法和状态，不改已有 handler／传播配置；其他 URL 与聊天／搜索原文策略不变。

### 修改文件

日志：`api/logging.py`、`api/routes/resolve.py`、`app/api_client.py`。草案：`schemas/plan_draft.py`、`schemas/course_program_context.py`、`app/plan_draft_view.py`、`app/state_manager.py`、`app/program_view.py`。六个新测试模块、一个合成 seed 支持模块及十份完整输出的 fixture，加本节；没有改真实 seed、数据库、检索、提示词、聊天、05D 规则或分享链接含义。

### 验证记录

以下为初次开发、基底 `56a03d6` 的历史记录，不冒充 rebase 和中途审查修复后的结果：定向 **609 passed／5 warnings／45.95 秒**、Ruff F/E9/B 15 文件通过、九快照 9/9、C CLI 47 用例／53 轮 complete，路由 53／0、错配／隔离／账目错误全零。最终串行全量 **4622 passed／7 warnings／426.01 秒**，exit 0；首轮 4619 passed／7 warnings／488.79 秒也保留。警告为 SWIG 类型元数据和 HTTP 422 名称弃用，没有关闭警告或升级依赖。

计算、状态、页面与隐私均先写失败测试。60 个具名变异首轮 59/60，唯一幸存是“仅排除名单点名”的覆盖缺口；补前缀排除／optional 范围排除的合法方案用例后，串行复核该 ID 及文字条件／未建模的合法 partial 后代，共 3/3。去重 60/60，不把 63 次执行说成 63 个不同变异，不用超时或 collection error 充当击杀。补测只动测试，无产品／seed／快照改动。所有红绿日志、逐 ID 失败测试、哈希及范围清单保留在独立 WORKLOG。

10 份策展文档的快照含合成输入，不是实际学生记录或真实学分声明；同 ID 的片段与扩展文档按文件名区分。相对基底精确 17 文件，五组红色基线原始断言哈希保留；最终跑测前后 387 份代码／规则／测试 fixture 哈希相同。两轮冻结间仅 `tests/test_plan_draft.py` 变化，原有九份布局 fixture 始终与基底逐字节相同。

### 审查

2026-10-20 收到 `REVIEW_I_progress.md` 中途只读检查，不是最终评审。H1 的 uvicorn 独立访问日志、H2 的交叉列课、M1/M2 的缺项与排除语义，以及 L1–L8／NIT 纳入修复；H3 明确需要 D4 设计决定，本轮不擅自改变 F 的 placement 或全局点名规则。修复后仍需复核，不把本地验收称为最终审查通过。

2026-10-20 晚第 21 轮正式评审：两路只读，都在 `7bf4584` 上（A22 看草案计算和页面，B22 看隐私、日志、测试和文档）。两人都没有 CRITICAL／HIGH／MEDIUM，共 8 条 LOW、9 条 NIT。A22 自己写的规则推导在 13,000 份草案上和产品逐节点一致，没有一个根显示满足；F 的 13,230 条 placement 输出和 `99550d2` 逐字节相同。B22 按生产命令起 uvicorn，两种日志格式各 65 个课程读请求，日志里没有课号、课程 ID、ref 或问题原文；交替和同时在跑的请求里，K 的字段都在。修复见「第 21 轮评审修复」；按用户的话，修完先给用户看，复核另定。

2026-10-21 复核第 1 轮：还是这两人，看 `7bf4584..da7d9e0`，都没有 CRITICAL／HIGH／MEDIUM。第 21 轮的 LOW 里，只有 B22 LOW-1 修了一半，其余都修好了。新发现三条 LOW：
- A22 R-1：照目录的交叉列课写法输入 `CS 7140/EECE 7397`，会加成两门课。一个组同时列了这两个课号时，同一门课算两次，组可能显示 ✅。用空格分开输入，修复前就是这样。
- B22 R1：环境变量 `UVICORN_ROOT_PATH` 同样会让课程 ID 和 ref 进日志，守护测试查不到。
- B22 R2：冻结的标准库模块的栈帧里带空格，会让整条 `frames` 被丢掉。

另有若干 NIT。修复见「第 21 轮复核第 1 轮的修复」。

2026-10-21 复核第 2 轮，也是最后一轮：还是这两人，看 `da7d9e0..b77909f`，都没有 CRITICAL／HIGH／MEDIUM。
- B22：R1、R2 都修好了。它试了四种设 root path 的写法：compose 的环境变量、Dockerfile 的 `ENV`、CMD 的 `--root-path`、compose 的 `command`。守护测试都能查到。冻结模块的帧在四种真实异常里都留下了。
- A22：R-1 在同一批里两种顺序都认得出，草案里已有的课的另一个课号也认得出。剩一个 LOW（N2-1）：只有一条记录点了另一条的名字时，先加点了名的那门、下一批再加另一门，两门都会留下。这是因为草案不记每门课的交叉列出候选。

按复核最多两轮的规矩，这条只改文档：上面那句限定为“同一批里”，并写进「已知、未处理」。两人新提的 NIT 也写进那里。

### 中途审查修复（基底 deaf750）

- H1：`configure_logging()` 在 uvicorn.access 源 logger 幂等安装过滤器，模板化课程读路径并删除查询串，保留方法／协议／状态和非课程日志。真正使用默认 uvicorn 配置经本地 Unix socket 起合成服务验证，不只测 structlog 或伪造 LogRecord；另有“已经配置后仍可补装”的幂等测试。不改 Dockerfile 或 `--no-access-log`。诊断白名单保留固定格式 catalog_year，任意年度文本仍丢弃；隐私说明同步到 `docs/pii_redaction.md`。
- H2：多个 resolver 候选中恰有一个主课号等于规范化输入时选它；零个或多个精确主课号仍拒收。先检查全部候选，再只截断展示；不靠前十项判断唯一。其他候选只说明“可能交叉列出”，不从别名响应断言具体关系，方案按哪一课号计入仍请项目核实。用真实 resolver、内存库和 ingest 同形别名测试 CS 7140／EECE 7397 两个方向，不读真实库。
- M1/M2：父级缺项保留 select／OR 组标签和差额；OR 自身也保留各出口的组标签，不摊平为共同必修，缺项去重。总结不再分别计 OR 下各出口；排除的课算文档已提及，不再说“方案里没有写到”。有限候选／范围判定和节点状态不改变，H3 未借此改动。
- L1–L4：不确定门数不写“还差 0 门”；空批次返回 none、不报重复；提交前按已有＋待核对数量检查剩余额度，准确提示超出几门、不先花 GET。整个读取循环有 spinner，首次连接／传输错误后停止并写明剩余未核对数量，已成功课程保留；单门 HTTP 503 等响应或坏字段仍不阻断别的课，不自动重试。
- L5–L8 与 NIT：每个移除按钮和单课链接写课号，输入支持课号内的 `-`／`_`；表单保留输入，登出／换账号／清空仍会清掉。根即使 coverage=complete 也不标 met，子节点规则仍按原逻辑计算；根说明挤掉的原因计入 omitted。去掉空操作符多余空格和“开放池”行话，未知学分不在两行重复展示。§30 与 G 的冲突已解决。
- 新增 41 项审查测试：首次 24 failed／11 passed；修复后首批 35 passed。真实 MSIS OR 出口核对又复现一条漏项（1 failed／36 passed），补修并加差额测试。旧规则正向断言改为检查合法 partial 容器内的子节点，不因根永远 unknown 就删除 met／missing／unknown 检查；M2 的旧反向断言按明确授权修正。变异另发现有限候选的“排除课不能计入”缺独立断言，补合法根／子节点两例；AppTest 输入值不能证明浏览器提交清空配置，再补一条实际表单协议断言。两次补强只加测试，不改产品判定。
- 十份固定合成输出逐字段审核后更新：只改缺项、对应省略计数、原因文字、被排除项归属和汇总；课程输入／学分、身份、树结构、各节点状态、counted／possible 与阈值差额全部不变。九份既有页面布局以 G 合并后的版本为基线，不重写。

第一版修复后定向 749 passed／5 warnings；变异揭示缺口后，主动中止尚未完成的全量（2955 passed，不算完整验收），保留原日志。新增排除规则两例后重新冻结 393 份代码／规则／fixture，原 392 份哈希不变：定向 751 passed／5 warnings／82.59 秒，串行全量 **4730 passed／7 warnings／591.91 秒**，exit 0。全量前后 393 哈希相同。

全量结束后仅新增一条表单协议测试（没有 autouse 或全局运行期修改），产品及所有既有测试／fixture 不变；最终定向 **752 passed／5 warnings／65.84 秒**、协议单测 1 passed、Ruff F/E9/B 通过。最终冻结 394 哈希、本轮精确 11 文件／8 Python；未重跑 4731 项全量，不声称最终 clean 提交另跑过完整套件。九快照 9/9、C CLI 47 用例／53 轮 complete，route 53／0、错配／隔离／账目错误全零；仍是默认配置的合成离线层。

具名变异首轮 **86/88**，I12（排除资格）与 IR20（表单清空配置）存活原始日志保留；补独立断言后各在单 worker、成功基线上具名失败，去重 **88/88**、90 次执行。实际超时、语法或收集错误不算击杀；六个未改函数变异不重跑，新容量保护下等价的 I43 不冒充 killed。原 35 红测函数体、G 的十个 helper AST／DEFAULTS、F helper、Dockerfile 与九快照另有完整性证明。本轮命令、逐 ID 失败、补测与封存结果在独立 `WORKLOG_REVIEW_R1.md`。

### I＋K 集成复验（2026-10-20，基底 99550d2）

用户确认本轮只做集成，H3 由另一边实现。I 的四个本地提交 rebase 到 K 合并后的 `99550d2`；两次冲突只在文档，保留 K 的完整 §29、I 的 §30，以及隐私第 10／11 节。19 份 I 非文档文件与 7 份 K 非文档文件逐字节保持，不混入 H3 或其他产品修改。

`docs/pii_redaction.md` 第 11 节补充课程读路径的例外，不再笼统说路径和查询串都照旧。新增六项集成回归：同一客户端两种顺序交替请求课程读取与 search／chat，实际 JSON 管道仍保留问题哈希／字符长度和 query_log 行号；课程路径仍为模板，课程读取不写 query_log。另检查课程白名单不会因 K 放过问题元数据、请求清掉调用方的遗留上下文。本轮仅新增测试与两份文档，不改日志实现、检索、模型、真实 seed 或 F 的 placement。

Rebase 基线 234 passed／3 warnings／54.31 秒。集成测试首轮 6 passed／3 warnings／4.73 秒；随后第一次定向 27 failed：K 的日志测试只收到 `request.handled`，因为集成测试替换的路由 logger 被缓存，之后的 capture_logs 收不到路由事件；原日志保留。改为只在测试内使用局部 logger 后（只改这个测试），Ruff 通过、定向 **863 passed／5 warnings／91.21 秒**；九快照 9/9 与 C CLI 47 用例／53 轮 complete 在改测试前已跑，不受这处影响。13 个集成具名变异 13/13，第 13 个专门拦“删掉 logger 隔离”；旧 I 的 88、K 的 77 不充作本轮重跑。冻结 397 份源码／规则／fixture 后，集成改动由另一边按冻结内容提交为 `cb5c413`，397 项逐字节一致；最终全量与封存和 H3 合在一起做，见「最终验收」。详细过程在独立 `WORKLOG_INTEGRATION_K.md`，不覆盖 R1 的历史验收结果。

### H3：别组多修的有限候选可以在范围里可能计入（2026-10-20，基底 `fbc5347`）

中途审查 H3：草案把方案里任何位置点名过的课都挡在所有开放池外，多修的一门广度候选落在选修编号范围里也帮不了选修，于是出现保守的假“还缺”。用户 10-20 定按提案改（D4 同步）；由另一边在独立 worktree 的 `feat/plan-draft-h3` 上写成单个提交 `08c9947`，cherry-pick 进本分支为 `f67f96a`。不改 F 的 placement、API、日志、检索或真实 seed。

- 开放池不收的课只剩两类：整份方案里的 `course` 叶子，以及任何位置的排除项（`_blocked_codes`）。本组自己的有限候选只按确定计入算，不进本组的开放池。别组的有限候选在本组范围里只算可能计入，最多让本组变成“不确定”，不会变成 ✅。
- 这门课已被另一个同时生效的组算进去时，每个组合成一行原因：“X、Y 已算进『组名』；能不能同时算这一组，要项目确认。”通用的“范围内可能计入”一行只列其余的课。本组已满足时不加这一行。
- OR 下的互斥出口不算“另一个组”（沿用 `coactive`）；重复计入的原有检查不变。

修改文件：`schemas/plan_draft.py`；新增 `tests/test_plan_draft_h3.py`（6 项）；重新生成 `tests/fixtures/plan_draft_seed.json`。

开发时验证（`fbc5347`＋H3，不含上一小节的集成测试）：6 项新测试改前 4 项失败（多修的广度课、审查里的 MSCS 例子、范围那一行、OR 出口）；另 2 项守原有行为（范围里的必修课不进池、已满足的组不加原因），改前也通过。改后定向 12 个模块 253 passed／3 warnings／39.67 秒，Ruff F/E9/B 2 文件通过，九快照 9/9，串行全量 4821 passed／7 warnings／511.31 秒，exit 0；基底不含 H3 时收集 4815 项，加 H3 的 6 项为 4821。具名变异 9/9，每个都由具名失败的测试击杀；其中“排除项不再挡住”和“本组候选也进开放池”两条由原有测试抓到。

seed 快照只在三个选修组有变化：possible 多了别组的有限候选（两份 CS 方案各多 CS 6140、CS 6240，一份 INFO 方案多 INFO 6205），各加一行“已算进”原因。任何节点的状态、counted、差额和汇总计数都没变。

### 最终验收（2026-10-20，`f67f96a`＝集成＋H3）

在 `f67f96a` 的 archive 副本上跑，不在 worktree 里跑。定向 20 个模块（草案、隐私、集成、K 日志、错误管道、G 对比页、页面编排）**433 passed／5 warnings／33.60 秒**；Ruff F/E9/B 相对 `99550d2` 的 20 个 Python 文件通过，改动文件没有 CR；九快照 9/9；C CLI complete，47 用例／53 轮，route 53／0，stream、错配、隔离和账目错误全零，和 K 那次的输出相比只差每次运行不同的评测用户 ID。串行全量 **4827 passed／7 warnings／297.47 秒**，exit 0（4815＋集成 6＋H3 6）。21 份非文档文件的哈希在副本建好时、全量前和全量后都相同；本节文档提交后，非文档文件仍与验收副本逐字节相同。警告仍是 SWIG 类型元数据与 HTTP 422 名称弃用。

具名变异只算具名失败：H3 的 9 个在合起来的树上 9/9；新写 6 个 I×K 交界变异（课程白名单放进问题字段、白名单只管 resolve、不清调用方上下文、上下文存原始课程路径、课程前缀误配 `/chat`、白名单丢掉 `catalog_year`），只用六项集成测试就 6/6；用户的 13 个集成变异在最终树上重跑 13/13；R1 那组锚在 `schemas/plan_draft.py` 的 41 个里，`I11` 的锚点被 H3 改写（同一处由 H3 的变异覆盖），其余 40 个用全部草案测试模块重跑 40/40。其他旧 I 与 K 变异所在的函数没改，不重跑。命令、日志和哈希在独立 `WORKLOG_WRAPUP.md`。

### 第 21 轮评审修复（2026-10-20 晚，基底 `7bf4584`）

改产品的四处，用户同意后做：
- A22 L-A：课数和学分两项都没达到、又有开放池时，“范围内可能计入”那一行原来会写两遍；现在每组只写一次，位置仍在第一个没达到的目标后面，所以十份 seed 快照不变。
- A22 L-B：「、」和 `/` 也算分隔符（页面自己就用「、」连列表）。顺带两条同一函数里的 NIT：输入先做 NFKC，全角字母、数字和空格能认；`-`／`_` 只在一个词开头连接院系和编号，所以 `neu-cs-6130` 这类内部 ID 只报一条格式错误。
- A22 L-C：resolver 只返回一个匹配、但主课号和输入的不同（改号、改名的别名）时，照旧按主课号加入，并多一行提示，写法同 H2：“输入的 X 对应主课号 Y，按 Y 核对；方案按哪个课号算，请向项目核实。”
- B22 LOW-2(b)：课程读白名单原来只看字段名；现在也看值的形状：计数只收数字（不收布尔），异常类型只收标识符，栈帧只收 `文件:行 函数`，形状不对的字段整条丢掉。今天所有调用点记的都是合规的值，正常日志不变；以后有人把课程 ID 列表塞进 `courses` 也不会进日志。

文档：B22 LOW-1，`docs/pii_redaction.md` 第 10 节写明课程读判断假定 API 挂在根路径（生产命令没有 `--root-path`），并加一条测试核对 Dockerfile 和 compose；同节补上值检查和并发两句。

只补测试：A22 L-D（只含 optional 分支的 AND／OR 组在根以下不显示满足；被排除的课不进缺项；OR 父级保留课程出口的课号；重复计入原因只列同时生效的组；“另有 n 项未展开”两行和两条说明文字；格式警告最多 10 条），B22 LOW-2(a)（显式传入的 `path=` 也被模板覆盖）、LOW-3（每门课的链接逐字等于它自己的 `?course=` 链接）、LOW-4（两个请求同时在跑：先开始的那个在另一个还卡在响应前时记日志并结束，两种先后顺序各一项，判断必须按各自请求）。

修改文件：`schemas/plan_draft.py`、`app/plan_draft_view.py`、`api/logging.py`、`docs/pii_redaction.md`；新增 `tests/test_plan_draft_final_review.py`（24 项）；`tests/test_plan_draft_k_integration.py` 加并发测试（2 项）。

验证：26 项新测试在修复前的 `7bf4584` 上 9 失败／17 通过，失败的 9 项正好是上面四处产品改动（范围行 1、输入写法 5、页面「、」1、换课号提示 1、值形状 1），通过的 17 项是补测试缺口的（行为本来就对）、两种原来就能认的写法和变异后补的两项转义测试（见下）。修复后定向 21 个模块 **459 passed／5 warnings／46.25 秒**；Ruff F/E9/B 5 个改动的 Python 文件通过，没有 CR；九快照 9/9；C CLI complete，47 用例／53 轮，route 53／0，stream、错配、隔离和账目错误全零，和收尾那次的输出相比只差每次运行不同的评测用户 ID。在 worktree 里串行全量 **4853 passed／7 warnings／421.16 秒**，exit 0（4827＋26）；7 个改动文件的哈希在全量前后相同，之后只填了本节的结果。警告仍是 SWIG 类型元数据与 HTTP 422 名称弃用。并发测试单独连跑 20 次，两种先后顺序 20 次都通过。

具名变异只算具名失败：56 个，其中本轮新代码 13 个，另 43 个是评审报告存活的和锚在本轮改过的函数里的旧变异体（用户 R1 25、用户 IK 1、收尾 IK 1、A22 13、B22 3），6 个 worker，实际超时算 SUSPECT。第一遍 55/56，存活的是用户 R1 的 I50（格式警告不转义）：「/」成了分隔符以后，原测试的输入 `[x](https://elsewhere.example)` 先被拆开，碎片本来就成不了链接，测试也就查不出不转义。补了两种一个词就能成链接的写法（`[x](https:elsewhere.example)`、`<https:elsewhere.example>`）后单独重跑，I50 被新测试具名杀掉，合计 56/56。锚点被本轮改掉的 3 个不跑：用户 R1 的 IR33 和 H3 的 M07 由新变异体 R13、R06 覆盖同一处；A22 的 A19 删的是全角逗号，现在输入先做 NFKC，全角逗号已变成半角，单删它是等价的，NFKC 本身由 R01 测。B22 的 M08 等价（`catalog_year` 是 TEXT NOT NULL，总是字符串）；M09（把课程 ID 列表记进 `courses`）这种值现在会被值检查丢掉，值检查由 R09–R12 测，不单独跑。其他旧变异体所在的函数没改，不重跑。命令、日志和哈希在独立 `WORKLOG_R21FIX.md`。

### 第 21 轮复核第 1 轮的修复（2026-10-21，基底 `da7d9e0`）

- A22 R-1（改产品，用户 10-21 选了「修」）：`_add` 核对时，下面两种情况都不加入，只留先加入的那门，也不再为它取详情。
  - 一门课的 H2 候选（「可能交叉列出」）里有草案里已经有的课；
  - 它被本批先加入的课的 H2 候选点过名。

  不加入时提示一行：“X 和 Y 可能是同一门交叉列出的课，只按 Y 计入；如果是两门不同的课，请向项目核实。”两条记录里只有一条点了另一条的名字时，同一批里也能认出来；分两批加入时只认得出一种先后顺序（见「已知、未处理」）。
- B22 R1（只改测试和文档，照 LOW-1 的定法）：
  - 守护测试不分大小写地查 `root-path`／`root_path`，所以 compose 里的 `UVICORN_ROOT_PATH` 也会被查到。
  - `docs/pii_redaction.md` 第 10 节写明：uvicorn 也从这个环境变量读 root path；NAS 上的 `.env` 也不能设；仓库里的测试看不到 `.env`，上线时要核对。
- B22 R2（改的是第 21 轮修复加的值检查）：栈帧的文件部分也收 `<frozen 模块名>`，例如 `<frozen os>:685 __getitem__`；其他带空格的写法照旧丢掉。第 21 轮修复说“栈帧只收 `文件:行 函数`”，当时没想到冻结模块的帧。

修改文件：`app/plan_draft_view.py`、`api/logging.py`、`docs/pii_redaction.md`、`tests/test_plan_draft_final_review.py`（7 项新测试，改 1 项）。

验证：
- 7 项新测试在 `da7d9e0` 上 6 失败／1 通过：
  - 交叉列课 5 项，两门都被加入；
  - 冻结帧 1 项，`frames` 被丢掉；
  - 通过的那项守的是：不相干的课和单个精确匹配照常加入。
- 改过的根路径测试在 `da7d9e0` 上也通过，因为那里本来就没有 root path；它能不能查到环境变量，由下面的配置变异体证明。
- 修复后：
  - 定向 21 个模块 **466 passed／5 warnings／47.10 秒**；
  - Ruff F/E9/B 3 个改动的 Python 文件通过，没有 CR；
  - 九快照 9/9；
  - C CLI complete，47／53，route 53／0，和第 21 轮修复那次比只差评测用户 ID。

在 worktree 里串行全量 **4860 passed／7 warnings／430.94 秒**，exit 0（4853＋7）。5 个改动文件的哈希在全量前后相同，之后只填了本节的结果。警告仍是 SWIG 类型元数据与 HTTP 422 名称弃用。并发测试没改，没有再连跑 20 次。

具名变异只算具名失败，6 个 worker，实际超时算 SUSPECT。结果 **35/35**，没有 SUSPECT。35 个里：
- 本轮新写 13 个：
  - 交叉列课 R14–R21；
  - 冻结帧和 frames 的形状 R22、R23、R26；
  - 部署配置 R24、R25：R24 在 compose 里设 `UVICORN_ROOT_PATH`，R25 在 Dockerfile 里加 `--root-path`。B22 用旧测试试过，会放过 R24；改过的根路径测试能查到它。
- 锚在 `_add`、`_course_read_value` 里的旧变异体 22 个：用户 R1 16 个、A22 2 个、第 21 轮修复 4 个。

第 21 轮修复的 R12 锚点被本轮改了，不跑，由 R26 顶替。命令、日志和哈希在独立 `WORKLOG_R22FIX.md`。

### 已知、未处理

- 未读取生产数据库或未指定副本；真实课程学分覆盖率没有统计，不虚报完整性。
- 浏览器刷新／新标签页／真实账号、手机布局仍需人工验收；AppTest 的新会话不等于真实浏览器已验收。
- 学分来自加入时记录，不自动刷新；每批最多 40 次同步只读请求，失败要手动重试，不新增缓存或并发层。
- 只保护本批应用日志出口；不声称清理了历史日志，也未检查 NAS／反向代理／隧道等基础设施访问日志。其他 API 的日志策略与 K 批次不在此处更改。
- 第二版再考虑详情页加入按钮、草案进聊天、先修判断、持久化及分享，均不在本批范围。
- H3 之后仍偏保守：必修课号（`course` 叶子，包括 OR 各出口和 optional 后代里的）和任何位置的排除项不进任何开放池，多修这类课时仍可能显示“还缺”。“已算进”一行只提示要项目确认，不判断能否双计；F 的 placement 未改。
- 课程读脱敏假定 API 挂在根路径（第 21 轮 B22 LOW-1、复核 R1）。`--root-path` 和环境变量 `UVICORN_ROOT_PATH` 都不能设。仓库里的测试核对 Dockerfile 和 compose；NAS 上的 `.env` 要在上线时核对。以后要用 root path 或子路径，先改成按路由路径判断。
- 交叉列课只能靠 resolver 的候选认出来，下面两种情况两个课号照样会算两次：
  - 两条记录都没点对方的名字；
  - 只有一条点了名，又是先加点了名的那门、下一批再加另一门（复核第 2 轮 A22 N2-1）。

  要堵上，得让草案为每门课记下它的交叉列出候选，那是改草案的数据结构。
- 第 21 轮留下的 NIT，都不会让一组显示满足：只按门数满足、学分未知的组显示 ✅，课程却只列在“可能计入／学分未知”下；D3 把满足改成 ❔ 时，开放池课程的“已算进”和范围行不再出现；两个同名且同时生效的组共用一行“已算进”；详情 404 也提示“暂时无法核对”；OR 有一个 optional 出口时按设计显示 ⬜。日志方面：只有在 DEBUG 级别，UI 的 HTTP 库才会打印重定向的 `Location`，而 UI 不会触发重定向；只是长得像课程路径的 404 不算课程读，保留原路径。
- 复核第 1 轮留下的 NIT，都只多出看得见的提示，不改状态：
  - 句末的「.」「。」，或复制来的零宽空格，会让最后一个课号报格式错误（修复前就这样）；
  - 「CS 5001/5003」会加入 CS 5001，把「5003」报成格式错误；
  - NFKC 之后，分隔符里的「，」「；」永远匹配不到（无害）；
  - 重复提交一个别名，会再查一次，并提示「没有新增课程」；
  - 上标数字会并进编号（照样是无效输入），带圈数字现在能认。
- 复核第 1 轮留下的日志方面的 NIT：
  - 长得像标识符的值（如 `cs5800`）仍能通过异常类型字段的形状检查，但没有调用点在那里记这种值；
  - 源文件名里带空格的栈帧，照旧会让 `frames` 被丢掉，生产容器里没有这种路径；
  - 重叠请求的测试失败时，被卡住的请求最多 10 秒后才结束；这只在测试失败时发生，线程是 daemon。
- 复核第 2 轮留下的 NIT：
  - 旧课号和改号后的新课号一起输入时，留下先输入的那个；提示里写的是“交叉列出”，其实是改号；
  - 草案已满 20 门时，输入其中一门的另一个课号，会先被“草案最多 20 门”拦下，轮不到交叉列课的检查；
  - “上线时核对 `.env`”还没有写进上线工具，下次上线时加一步只数个数、不打印内容的检查。

### 发布状态

分支 `feat/session-plan-draft`，初始基底 `56a03d6`；中途审查修复先 rebase 到 `deaf750`，本次集成再 rebase 到 `99550d2`。日志修复分步提交，功能及审查修复在独立 worktree 离线验收；详细红绿过程、失败保留、逐 ID 变异证据、命令和哈希在独立 WORKLOG 与交审材料。集成改动 `cb5c413` 与 H3 `f67f96a`（cherry-pick 自 `feat/plan-draft-h3` 的 `08c9947`）由另一边按用户要求代为提交；收尾记录 `7bf4584` 只改文档。第 21 轮评审修复和复核第 1 轮的修复，也由另一边按用户的话代做，各自单独提交。I 未 push／开 PR／合并／部署，本轮未使用真实模型、账号、NAS 或生产库。K 已作为基底纳入。第 21 轮正式评审在 `7bf4584` 上做完，复核第 1 轮在 `da7d9e0` 上，第 2 轮（最后一轮）在 `b77909f` 上，见「审查」。最后这份记录只改文档。不把作者本地验收称为独立复核或 I 已上线。

## 31 — 跨页保留选择、登出改成回调、先修树里重复的课、草案输入（L，2026-10-21）

### 范围与原因

用户 10-21 在线上做 F＋G 浏览器验收时记了两条观察：跨页回来以后项目选择变回「不指定」；登出以后侧栏高亮和正文一度不一致。另外，协调方看验收截图时发现，CS 5008 的先修树里每个 OR 分支都把同一门课写了两遍。再加上 §30 复核第 1 轮留下的草案输入 NIT。用户选「按默认做」，由协调方来写。

查到的原因：
- **跨页丢选择：** Streamlit 会删掉一轮里没渲染的组件的状态。搜索页的 `chat_program_id`、`chat_plan_id`，培养方案页的 `program-plan-{program_id}`，都是只在本页渲染的组件键，所以去过别的页再回来就没了（§28 已知第 7 条）。
- **登出高亮：** 侧栏的「Log out」排在导航单选框前面，点了以后在分支里 `st.rerun()`。Streamlit 1.57 把 `st.rerun()` 当成这一轮正常跑完（`exec_code.py` 里 `premature_stop = False`），后端于是删掉了还没渲染的 `nav_page`，下一轮回到默认的 Search。浏览器却还记着原来的选项：侧栏显示 Compare，正文是 Search；再点任何按钮，浏览器把旧值送回来，正文又跳回 Compare。这一点用一个 30 行、结构相同的本地脚本在内置浏览器里复现了；改成 `on_click` 回调以后侧栏和正文一致。
- **先修重复：** 目录原文就是这么写的。本地存的 2026-2027 官方快照里，CS 5008 写的是「( CS 5001 with a minimum grade of C- or CS 5001 with a minimum grade of C- ); ( CS 5002 … or CS 5002 … )」。按解析出的规则数，CS、DS、INFO 三份快照里有 8 门课这样写，验收清单里占 5 门：CS 5004、CS 5008、INFO 6105、INFO 6205、INFO 7405。第一次我用正则数成 6 门、3 门，A23 指出后改用解析器重数。

### 已实现

1. **L-1 跨页保留选择。** `app/state_manager.py` 新增 `keep_choices()`，`app/streamlit_app.py` 的 `render()` 在 `init_state` 之后、任何组件之前调用它。它把上面三类选择键原样赋值一次，这是 Streamlit 文档里多页面保留组件状态的写法。原有的清除都照旧：方案更新、409、换项目、刷新按钮、分享链接替换都是设成 None；选中的项目已经不在列表里时照旧删键。所以清掉的选择不会被旧值顶回来；回到页面时重新获取到的方案变了，照样清除并提示一次。
2. **L-2 登出。**
   - `app/streamlit_auth_ui.py` 的登出改成按钮的 `on_click` 回调 `_log_out()`：排队清 cookie，再调 `logout()`。回调在下一轮之前执行，那一轮从头就按登出状态渲染，组件照常渲染，所以导航不会被删。
   - `logout()` 和换账号时的 `login()` 新增 `clear_choices()`：把项目和方案选择设成 None。设 None 而不是删键，这样浏览器里的选择框也会复位。页面留在原来那一页；搜索过滤器照旧保留。
   - 浏览器检查时发现：设成 None 的项目选择框显示的是 Streamlit 的默认占位「Choose an option」。现在 `render_chat_program_selector` 传了 `placeholder="不指定"`，和方案选择框的做法一样。
3. **L-3 先修树里重复的课。** `app/course_requisite_view.py` 的 `rule_lines` 只改显示：同一组里完全相同的课程叶子（课号、最低成绩、level、能否并修都一样）只显示一次，并在这一组后面写「（目录原文在这一组里把同一门课列了不止一次，这里只显示一次）」。原文展开框、存下的规则树、对比页和交给聊天的数据都不变。
4. **L-4 草案输入。** `app/plan_draft_view.py` 的 `parse_course_codes`：
   - 去掉复制来的隐形字符：U+00AD 软连字符、U+200B–U+200F（零宽字符和左右方向标记）、U+2060、U+FEFF。软连字符和方向标记是 A23 审查时补上的；源码里用 `\N{…}` 字符名写，不写成真字符；
   - 「。」也算分隔符；
   - 课号末尾的「.」不算进课号。

   §30 复核第 1 轮的这条 NIT 就此解决：句末的「.」「。」或复制来的零宽空格，原来会让最后一个课号报格式错误。
5. **A23 审查以后的修复**（第二个提交，见「审查」）：
   - **cookie 恢复登录不再 `st.rerun()`**（LOW-2，原有问题）。恢复在侧边栏、hero 和任何组件之前，这一轮剩下的部分本来就按已登录渲染。原来的重跑会在页面导航之前结束这一轮；服务器丢掉会话、浏览器还留着页面时（断线超过 120 秒，或者重启、上线），会重现 L-2 那种侧栏和正文不一致，那次点击也会丢。
   - **补一项用真实 cookie flush 的登出测试**（LOW-3）：别的页面测试都把 `flush_pending_cookie` 换成了空函数，删掉 `render()` 里那次 flush 的变异原来能过全量。
   - 文档：`docs/view-cache.md` 写明有两处照旧删键（NIT-1）；门数改成 8（NIT-2）。

### 修改文件

- 产品代码：`app/state_manager.py`、`app/streamlit_app.py`、`app/streamlit_auth_ui.py`、`app/program_plan_view.py`、`app/course_requisite_view.py`、`app/plan_draft_view.py`；`app/cookie_session.py` 第一个提交只改注释，审查修复去掉了恢复登录后的重跑。
- 文档：`docs/view-cache.md`、`docs/course-requisites.md`、本节。
- 测试：新建 `tests/test_page_state_l.py`，24 项（第一个提交 19 项，审查修复加了 5 项），大部分走真实页面的 AppTest。

API、检索、提示词、数据库和快照都没改。

### 验证记录

- **新测试：** 19 项全过。同一份测试放在 `ca41bdc` 的副本上跑，18 项失败，原因都对：选择是 None、导航回到 Search、先修行没合并、课号报格式错误等。通过的 1 项本来就是防回归的：选了「不指定」去别的页再回来，仍然是「不指定」。
- **定向和静态检查：** 46 个定向测试文件 **1136 passed**；Ruff F／E9／B 在 8 个改过的 Python 文件上通过；没有 CR。
- **快照和离线评测：** 九快照 9/9 match；C CLI 47／53 complete，route 53／0，隔离计数为 0。
- **串行全量：** 第一遍 **4879 passed**（=4860＋19）；最终文件上 **4879 passed／7 warnings／434.35 秒**，退出码 0，11 个改动文件在全量前后一致。全量开始以后只补了本节的数字和一句措辞。
- **变异 51/51 killed**，没有只靠超时判定的：
  - L 自己的 22 个；
  - 锚点落在 L 改过的函数里的旧变异体 29 个：`render` 20 个，`login`／`logout` 5 个，`parse_course_codes` 3 个，`render_chat_program_selector` 1 个。
  - 旧变异体是从评审目录里 51 个能加载的工具里收集的。另有 3 个工具加载不了，它们在 L 改过的函数里没有变异体。
  - r21 的 R02、R03 锚在被 L 改写的分隔符正则上，由新的 L20、L21 顶替。
- **内置浏览器检查（本机）：** L 的真实页面接一个返回合成数据的本机假 API，用一个本次检查自己造的 cookie 走恢复登录，没有真实网络、账号或数据。
  - 搜索页选项目和方案 → 培养方案页打开课程表、选方案、往草案里加「CS 5800.」（直接加进，没有格式错误）→ 点 CS 5008 的「查看」回到搜索页：项目、方案都在，CS 5008 的先修树按上面那样合并显示，侧栏和正文都是 Search。
  - 回到培养方案页：方案选择和草案都还在。
  - 登录后在对比页登出：侧栏和正文都是对比页，cookie 已清除；回到搜索页，项目选择显示「不指定」（修占位文字之前显示的是「Choose an option」）。

- **A23 审查以后的修复：**
  - 新测试 24 项全过。同样的测试放在 `2fc5cf1` 上跑，恢复登录那项（`[True] == []`，也就是重跑了）和新加的 3 种隐形字符失败；真实 flush 那项在 `2fc5cf1` 上就通过，它钉的是原来就对、只是没测到的行为。
  - 46 个定向测试文件 **1141 passed**；Ruff F／E9／B 通过。
  - 变异 **13/13 killed**：`parse_course_codes` 里的新旧变异体重跑一遍，L16、L17 改锚到新字符集；新加 L23 恢复登录又重跑、L24 `render()` 去掉 flush、L25 不去软连字符、L26 不去方向标记。L 全部 26 个新变异体和 29 个旧变异体都被杀，没有只靠超时判定的。
  - 串行全量 **4884 passed／7 warnings／433.97 秒**，退出码 0，比 4879 多的 5 项就是新测试；全量前后改动文件一致。全量开始以后只补了这个数字。

### 审查

第 22 轮，一路只读审查 A23，在 `2fc5cf1` 上做（10-21）。没有 CRITICAL、HIGH、MEDIUM，3 LOW、3 NIT，不挡合并。A23 对照 Streamlit 1.57 源码核过：L-1 不报错、不报警告，每一轮都把值送给浏览器，原有的清除都照旧生效；L-2 的回调和原来的分支等价，只少了半路重跑；L-3 只改显示、只合并完全相同的叶子；L-4 拿 43 种输入和 `ca41bdc` 比，没有一个原来能用的输入变了。
- **LOW-1：** 极快的第二次点击如果在 `keep_choices()` 之前打断这一轮，不在当前页的选择仍会丢（A23 用探针强制做出来了）。没修，记进已知：A23 建议另存一份影子值，但影子值会过时，可能在「方案改版、必须重选」以后把旧选择悄悄带回来，这比偶尔要重选一次更糟。
- **LOW-2：** cookie 恢复登录的 `st.rerun()`，见「已实现」第 5 条，已修。
- **LOW-3：** 真实 flush 的登出测试，见「已实现」第 5 条，已补。A23 另提到：跨页时培养方案页的 `drop_changed_choice` 只在同一页内测过，因为 `plan_curricula` 把 `get_curriculum_cached` 换成了替身，记进已知。
- **NIT：** 「清除都是设成 None」不完全对（NIT-1）；门数是 8 不是 6（NIT-2）；软连字符和方向标记（NIT-3）。都已改。

**复核第 1 轮**（A23，10-21，在 `ab0167a` 的新副本上）：LOW-2、LOW-3 和三条 NIT 都修好了，LOW-1 同意记进已知。没有新的 CRITICAL、HIGH、MEDIUM、LOW。
- A23 用探针核过恢复登录的三种情况，每种都只跑一轮、不重跑：200 直接显示登录后的侧栏和首页，没有游客横幅；401 是游客页，同一轮清掉 cookie；503 是游客页，cookie 保留。
- 新 NIT 一条：本节「修改文件」还写着 19 项。已改成 24 项，复核到此结束。

### 已知、未处理

- 只保留这三类选择。详情面板里的先修年度和同年度方案的选择框，去过别的页回来仍会复位。草案输入框里还没提交的文字也是。
- 刷新浏览器以后，选择照样清空：它们只在 Streamlit 会话里。
- 极快的第二次点击如果在 `keep_choices()` 之前打断这一轮，不在当前页的选择仍会丢（A23 LOW-1）。原因和取舍见「审查」。
- 培养方案页的「方案有更新」跨页的情况（离开期间重新获取、回来提示一次）只在同一页内有测试（A23 LOW-3 的附带意见）。
- AppTest 只看得到服务端状态。浏览器那一侧只在本机合成环境里看过，线上要等用户的浏览器验收。
- 「CS 5001/5003」仍会加入 CS 5001、把「5003」报成格式错误；「CS 5800.CS 5004」这种中间没有空格的写法也仍报错。都只多一条提示。

### 发布状态

分支 `fix/page-state-l`，基底 `ca41bdc`，也就是 10-21 上线的 main。第一个提交 `2fc5cf1` 是 L 本身，第二个提交是 A23 审查的修复，第三个提交只改本节（复核记录和复核的 NIT）。没有使用真实模型、账号、NAS 或生产库。L 只改页面，上线另行授权，可以等下一次上线一起上。

## 32 — 小范围试用准备：数据与隐私页、到期清理、每天的模型调用上限、删除账号（T，2026-10-21）

### 范围与原因

10-21 下午的新一轮，用户定主线做小范围试用准备，由协调方来写。用户定的政策：
- **P1 给谁用：** 先给 10–20 个认识的 NEU 研究生，私聊或小群发链接，不公开发帖。
- **P2 告知：** 加「数据与隐私」页。
- **P3 留多久：** 提问原文留 90 天，到期换成带密钥的哈希，行保留；勾选保存的回答和评价也是 90 天，到期删除。
- **P4 怎么删：** 登录用户在页面上删除账号和投稿，页面上留用户的 NEU 邮箱。删号以后，同一组公开的投稿只剩一个投稿人时，撤回剩下那份。
- **P5 费用和滥用：** 模型调用每天最多 200 次；打开限流。
- **P6 反馈：** 打开 👍／👎，保存默认不勾选。
- **P7 看数据：** 每周一次只读统计。

开关和上线另要授权。本节只改代码、配置和文档，没有上线。

### 已实现

1. **「数据与隐私」页**（`app/privacy_view.py`）：导航末尾加第 5 页「🔒 数据与隐私 · Privacy」，前四页的位置和深链序号不变。
   - 分四段：记了什么、谁能看、留多久、怎么删。每句话都对应代码现在的做法。
   - 天数、反馈开关和联系邮箱取自 UI 的设置（`QUERY_LOG_RETENTION_DAYS`、`ANSWER_FEEDBACK_ENABLED`、`PRIVACY_CONTACT_EMAIL`），所以清理关着时页面不会承诺清理。
   - 写明问题、这次对话最近几轮和检索到的课程信息会发给 Google Gemini；网站经 Cloudflare 转发，连接在 Cloudflare 那里解密，所以 Cloudflare 能看到传输的内容；公开的 Co-op 经验按贡献等级给访客看。
   - 用户 10-21 确认 Gemini 的 key 是付费档，页面照 Google 的 Gemini API 附加条款（2026-03-23 生效、04-28 更新，核过原文）写了付费档的做法：不拿这些内容改进 Google 的产品；会保留一段有限的时间，只用来发现和防止违规使用、维护安全，以及法律或监管要求的披露；可能临时存放或缓存在 Google 或其代理设有设施的任何国家；具体仍以 Google 的条款为准。
   - 换过哈希的那一行还留着时间、搜到的课程和检索方式；Co-op 要两个不同投稿人的投稿通过审核才一起公开；运行日志里登录只记学校域名和贡献数；账号那一行还记着第一次和最近一次登录的时间（删账号时一起删）。这几句是 A24 审查和复核以后改准的。
   - 提问和保存的回答都不记账号（真实用户的 `user_id` 本来就是空），页面照实写：删账号删不到它们，只能等到期。
   - 聊天里勾选「允许保存」旁边的说明（`capture_notice`）也读 `QUERY_LOG_RETENTION_DAYS`：设了天数就写「保存的回答和评价 N 天后删除，每日备份里最多再留大约两周」，和隐私页一致；设成 0 时照旧说不会自动删除（A24 M1）。
   - 聊天顶部的提示后面加了一句「留多久、怎么删，见左侧「🔒 数据与隐私」。」。九个页面快照重新生成，逐个核对过，只有这一句变了。
   - 只用纯文字，每句经过 `literal_markdown`。
2. **提问原文到期换哈希**（`db/query_log_retention.py`）：`created_at` 早于期限、还没换过的行，`query` 换成 `redacted:<16 位十六进制>:<字符数>`，别的列都不动。
   - 哈希就是 K 的 `query_hash`。派生和计算拆进新的 `api/query_hash.py`，它不读设置；`api/query_fields.py` 改成调用它，哈希值不变，K 的测试照过。
   - 只有完全符合这个形状的文字才算已经换过，所以第二遍不会再改。SQLite 的 `length()`、`substr()`、`GLOB` 遇到 NUL 就停，所以还要求字节数等于字符数，「标记＋NUL＋原文」骗不过去（A24 L2）。
   - 分批处理，每批一个短的写事务；每条 UPDATE 都核对读到的原文，中间被改过的行留给下一批，按改过的原文换。一整批一行也没换成时，这次就停，留给下一次。
   - 没有 `SESSION_SECRET` 时不换：随机密钥会毁掉原文，留下的哈希又什么也对不上。
   - 磁盘上的旧字节：`db/connection.py` 的每个连接都打开 `secure_delete`，换掉和删掉的内容用零覆盖；不然备份边车按页复制，会把旧字节带进之后的每一份备份（A24 L3：编译默认关闭时，40 条里有 39 条原文还在库文件里）。代价是删改时多一点 CPU、离线脚本批量删除多写一些 WAL，读和锁不变。跑完以后做一次 WAL checkpoint（`TRUNCATE`），失败了不算这次失败。它最多等 100 毫秒：等旧快照上的读者（备份边车、每周统计、导出）时，SQLite 会挡住新的写入，按连接默认的 5 秒等，API 的写入会失败（A24 复核 LOW-R1）。等不到就放弃，WAL 里的旧帧留到下一次运行截断，或者最后一个连接关闭；SQLite 自己的自动 checkpoint 不截断文件。
3. **保存的回答到期删除**（同一模块的 `delete_expired_answers`）：`chat_answers` 里超过同一期限的回答，连同评价一起删除。
   - 先删评价再删回答，所以不靠外键级联也不会留下孤立的评价。
   - 没有 v1.7 表的旧库跳过这一步。
4. **在哪里跑**（`api/query_log_retention_task.py`，接在 `api/main.py` 的 lifespan 上）：API 进程里的一个后台线程，启动时一次，之后每 24 小时一次。每次先换哈希，再删回答，最后 checkpoint。
   - 原先的设计是放在备份边车里，那样要把能伪造登录的 `SESSION_SECRET` 交给备份容器，所以改在 API 里跑。
   - `QUERY_LOG_RETENTION_DAYS` 为 0（代码默认）时关闭。没有密钥时只跳过换哈希，删回答照跑（它不需要密钥）：启动时记一条 `query_log.retention_skipped`，之后每次的日志里 `replaced` 是 null（A24 L4）。
   - 某一次失败只记 `query_log.retention_failed` 和异常类型，下一次再试，不会让 API 停下。日志里只有计数。
   - 手动命令 `scripts/redact_query_log.py`：`--dry-run` 只数，不要密钥；真跑要 `SESSION_SECRET`（没有时整个拒绝），跑完也 checkpoint；只输出计数。
5. **每天的模型调用上限**（`api/model_budget.py`；设置 `MODEL_DAILY_CALL_LIMIT`，代码默认 0，不限）：API 每次真正调 Gemini 之前占一个名额。回答生成算一次；HyDE 救援只有过了课号规则、真去调模型才算；经过 API 的评测流量也算。`scripts/` 里的离线脚本直接调模型，不占名额（A24 L7）。
   - 按 UTC 日期计数，存在数据库同目录的 `model_budget.json`，原子写入，有进程锁，重启不归零。
   - 文件读不了就从 0 开始；写不了照样在内存里限制，只警告一次。
   - 用完以后，`/chat` 在 meta 后面发固定的 `daily_limit` 错误事件和 done，不调模型；UI 把这句提示当作回答显示。提示写了恢复时间：UTC 零点，也就是波士顿时间晚上 8 点（冬令时晚上 7 点）；原来写的「明天」不对。救援抛 `ModelBudgetExhausted`，`attempt_hyde_rescue` 保留原来的拒答，记 `rescue.skipped reason=model_daily_limit`。
   - 只有一个 API 进程，所以用进程锁就够了；这不是多进程或按用户的配额。
6. **删除账号和投稿**（`POST /auth/delete-account`，`db/account_deletion.py`）：要 Bearer，body 正好是 `{"confirm": "delete"}`。一个事务里做完：
   - 先删这个账号公开的 Co-op 经验，以及任何人对它们的解锁记录（外键只会把投稿人置空，内容会匿名留在公开列表里）；
   - **k=2：** 同一组（公司、职位、学期）公开的投稿如果因此只剩一个投稿人，剩下那份撤回到 `approved`，从公开列表撤下（连同解锁记录）。之后同组再有通过审核的投稿，会一起重新公开，不重复记功；已经给的记功不收回。这是用户 10-21 选的；
   - 最后删 `users` 这一行，级联删掉它的解锁记录、计划课程、全部 Co-op 投稿（任何审核状态）和贡献记功。
   - 要求外键打开、调用方不在事务里；任何一步失败都整体回滚。返回各表删了几行，日志 `account.deleted` 只有这些计数。
   - 删完以后，同一个 token 调 `/auth/me` 或再删一次都是 401。
   - 页面上只有登录用户看得到：先勾选「我知道删除以后不能恢复」，按钮才能点。按钮用 `on_click` 回调：删完清 cookie、登出，并提示已删除；401 时也登出，提示登录已经失效。没收到服务器的回复（超时、连不上、网关错误，也就是 502／503／504）时，服务器可能已经删完了，所以只说不确定删没删，请刷新看看：变成游客就是删掉了（A24 L5）；别的错误才说什么也没删。
7. **compose：**
   - api：保留 90 天，每天 200 次，打开反馈，打开限流（容量 20，每秒补 0.5，同时最多 4 个；没在 NAS 上量过，估算写在 `docs/request-admission.md`）；
   - ui：保留 90 天，打开反馈，联系邮箱是用户的 NEU 邮箱；
   - 测试钉住 api 和 ui 的保留天数、反馈开关一致。
8. **每周只读统计**（`scripts/weekly_stats.py`）：只读快照，输出最近 N 天（默认 7 天）的这些计数：
   - 每天的提问数，按路由和流量分；
   - unmarked 提问的检索方式；
   - 👍／👎 和新保存的回答；
   - 账号数和 Co-op 队列；
   - 今天的模型调用次数。

   不输出原文、邮箱或 ID。在 NAS 上跑也算碰 NAS，要先问用户。
9. **设置的校验：** 两个整数设置不收布尔值（在代码里传 True 会被当成 1）；保留天数是 0–3650，上限是 0–100000；联系邮箱只收不含 Markdown 符号的普通地址。联系邮箱留空（照 `.env.example` 原样取消注释）等于没设，原来会让设置加载失败、程序起不来（B24 的笔记）。
10. **登录日志**（`api/routes/auth.py`）：`auth.callback.success` 原来记 Google 账号 ID（sub）。API 日志按大小轮转、没有时限，删账号也删不到，所以现在只记学校域名和贡献数（A24 L1）。`docs/oauth_secret_rotation.md`、`docs/api_contract.md` 和 `pii_redaction.md` 第 12 节跟着改了。

### 修改文件

- 新建：`api/query_hash.py`、`api/query_log_retention_task.py`、`api/model_budget.py`、`db/query_log_retention.py`、`db/account_deletion.py`、`app/privacy_view.py`、`scripts/redact_query_log.py`、`scripts/weekly_stats.py`。
- 改：`api/query_fields.py`、`api/main.py`、`api/dependencies.py`、`api/routes/chat.py`、`api/routes/common.py`、`api/routes/auth.py`、`api/models.py`、`app/streamlit_app.py`、`app/answer_feedback_view.py`、`app/api_client.py`、`config/settings.py`、`db/connection.py`（审查以后的修复：`secure_delete`，另给一个只有类型注解用到的名字补了 `TYPE_CHECKING` 导入，Ruff 第一次查这个文件时报了 F821）、`docker-compose.yml`、`.env.example`。
- 文档：`docs/api_contract.md`、`docs/request-admission.md`、`docs/query-log-export.md`、`docs/pii_redaction.md` 第 12 节、`docs/answer-feedback.md`、`docs/oauth_secret_rotation.md`、`scripts/README.md`、本节。
- 测试：
  - 新建 `test_query_log_retention.py`、`test_model_budget.py`、`test_privacy_view.py`、`test_account_deletion.py`、`test_weekly_stats.py`，提交 T 时共 111 项，审查以后的修复加到 139 项，复核第 1 轮以后 141 项，B24 的报告以后 142 项；
  - `test_compare_view.py` 的导航列表和 `test_page_orchestration.py` 的页面结尾数加上了隐私页；
  - 审查以后的修复：`test_api_auth_route.py` 加了 1 项（登录日志）；`test_feedback_release_gate.py` 改成用 `capture_notice`；
  - 九个页面快照只改了聊天提示那一句。快照用的保留天数是 0，所以勾选说明在快照里还是原来那句。

数据库结构、检索和提示词都没改。

### 验证记录

- **新测试：** 111 项全过。同样的测试放在基底的副本上，五个新测试文件都在收集时失败，因为新模块还不存在。
- **定向和静态检查：**
  - 定向测试 **958 passed**。第一次跑时，K 的日志静态检查（`test_log_query_fields.py`）抓到删除账号的日志用了 `**counts`，键名看不出来；改成逐个写出键名，测试再钉住日志里的计数和返回的一样。
  - Ruff F／E9／B 在 26 个改过的 Python 文件上通过，没有 CR。隐形字符检查只标出 `docs/api_contract.md` 开头的 BOM，基底里本来就有。
- **快照和离线评测：** 九个快照 9/9 match；C 的离线 CLI 47／53 complete，route 53／0，隔离计数为 0。
- **变异：190 个，杀掉 189 个**，被杀的都是对口的测试，没有只靠超时判定的。
  - 新写 112 个。编号是 T01–T118；T34、T49、T50、T59、T75、T117 在写进工具之前就当成等价拿掉了，当时没把是哪几个、为什么记下来，现在找不回了（B24 指出）。以后拿掉的变异体，在工具里写一句理由。
  - 锚点落在 T 改过的函数里的旧变异体 78 个：自动收集到 69 个；另外手动补了 9 个。其中 7 个是 K 的哈希变异体，锚点随派生代码搬进了 `api/query_hash.py`；还有 2 个来自两个加载不了的旧工具，它们各自只有一个落在 `chat` 里，手抄过来。
  - 第一遍存活 3 个：
    - 每周统计的窗口起点（`>=` 改成 `>`）：补了一行正好落在窗口第一秒的数据以后被杀；
    - L 的 L24（`render()` 去掉 cookie flush）：第一遍的副本建在快进到 L 之前，换到现在的基底以后，被 L 自己的真实 flush 测试杀掉。第一遍的副本对 T 自己的页面变异体也一样是旧的；B24 在真实的 `86dae4e` 上重跑了 T83–T86 和 T116，原因照旧，都被杀；
    - K 的 B17（问题文字里的孤立代理字符用 replace 编码）：照 K 当时的结论算等价，因为带孤立代理字符的请求在校验时就是 422。
- **串行全量：** **4995 passed／7 warnings／550.40 秒**，退出码 0。比 main 的 4884 多出的 111 项就是新测试；全量前后 44 个改动文件一致。全量开始以后只补了本节的数字，没有测试读本文件。

- **第 23 轮审查以后的修复**（A24 的报告，加上 B24 停下时笔记里的发现）：
  - 改过的 7 个测试文件 **197 passed**。同样的测试放在 T 的提交 `86dae4e` 上跑，22 项失败，原因都对：删除没收到回复的五种情况、登录日志、勾选说明跟着天数走（90 天和 30 天两项；0 天那项在 `86dae4e` 上本来就过）、`test_feedback_release_gate.py` 的 4 项（改成调用新函数）、每日上限提示的恢复时间、空的联系邮箱 2 项、隐私页的措辞、带 NUL 的标记、没有密钥时也删回答、`secure_delete`、跑完以后磁盘上的旧文字（任务 2 项：原文在库文件里，或者还在 WAL 的旧帧里；手动命令 1 项）。其余新加的测试在 `86dae4e` 上就通过，它们钉的是原来就对、只是没测到的行为，是给 B24 存活的变异体补的（见下）。
  - 定向测试 **1002 passed**；Ruff F／E9／B 在 29 个改过的 Python 文件上通过，没有 CR；隐形字符只有 `docs/api_contract.md` 开头基底就有的 BOM。快照 9/9 match；C 的离线 CLI 47／53 complete，route 53／0，隔离计数为 0。
  - **变异 72/72 killed**，被杀的都是对口的测试，没有只靠超时判定的。第一遍 71/72：F09（checkpoint 用 `PASSIVE` 代替 `TRUNCATE`）存活，因为那条测试先把库 checkpoint 干净了，WAL 里本来就没有旧文字；生产上 WAL 文件不截断，很久以前的旧帧会一直留着，补了「原文还在 WAL 的旧帧里」那一种以后被杀。F15 第一遍是因为多出来的警告让等待提前结束、报 IndexError 才失败的；等待条件改成只数 `query_log.retention` 以后，用这条测试的三个变异体（F15、T33、T35）重跑，都由对口的断言杀掉。
    - 新写 32 个：F01–F31，以及 T76b（T76 改锚到新的那句）；
    - B24 的 14 个：它定向跑时存活的 11 个里，B12 不跑，算等价（`query_log.route` 从建表那次提交 `ac9d246` 起就有 `CHECK (route IN ('search', 'chat'))`，走不到那个分支），其余 10 个都补了测试；另外是 sim03 的 P02／P05／P09（B24 改锚成 B14–B16；sim03 的工具加载不了，T 第一遍变异漏了它们，本节原来也没写）和改锚的 IK11（B17：第一遍记成杀掉，其实是因为 `data` 这个名字没了、报 NameError 才失败的）；
    - 锚点落在这次改过的代码里的旧变异体 26 个（T 自己的 24 个，加上 batch15 和 safe02 各 1 个）。这次收集把模块级和类里的语句也算进来，T 第一遍的收集只看函数（B24 指出 `query_fields.py` 模块级的 IK12、H3、H6 因此既没算受影响也没算被顶替；它们测的行为由 T02、T03 覆盖）。T28、T76 的锚点这次改掉了，由 F13 和 T76b 顶替。三个加载不了的旧工具（fix_a、sim03、k3）在这次改过的文件里没有变异体。
  - 串行全量 **5024 passed／7 warnings／466.11 秒**，退出码 0。比 4995 多出的 29 项就是这次新加的测试；相对 `6395ee5` 的 48 个改动文件在全量前后一致。全量开始以后只补了这个数字。

- **复核第 1 轮以后的修复**（第三个提交：A24 复核的 LOW-R1 和三条 NIT，加上 Gemini 付费档那句）：
  - 改过的 2 个测试文件和上一轮的 7 个一起 **199 passed**。新加和改过的测试放在 `d06d059` 上跑，3 项失败，原因都对：checkpoint 等了 5.35 秒（要求 2 秒以内）；登录那两句；Gemini 付费档那句。
  - 定向测试 **1004 passed**；Ruff F／E9／B 通过，没有 CR；快照 9/9 match；C 的离线 CLI 47／53 complete，route 53／0，隔离计数为 0。
  - **变异 22/22 killed**，都是对口的测试：新写 10 个（F32–F40，以及 F23c：F23 改锚到新的那句）；锚点落在这次改过的代码里的旧变异体 12 个（T 的 6 个、上一轮的 6 个）。上一轮的 F10 锚点还在，但后面多了 `finally:`，变出来的代码不合语法，改锚成 F40。
  - 串行全量 **5026 passed／7 warnings／478.20 秒**，退出码 0。比 5024 多的 2 项就是这次新加的测试；48 个改动文件在全量前后一致。全量开始以后只补了这个数字。

- **B24 的报告和复核第 2 轮以后的修补**（第四个提交，只改测试和措辞）：
  - 改过的 2 个测试文件和之前的 5 个一起 **200 passed**。放在 `4115247` 上跑，只有 Gemini 措辞那项失败，原因对；新补的磁盘测试（G02、G07）、导出那句和 0.75 秒的上限在 `4115247` 上就通过：它们钉的是原来就对、只是没测到的行为。
  - 定向测试 **1005 passed**；Ruff F／E9／B 通过，没有 CR。
  - **变异 27/27 killed**，都是对口的测试：新写 8 个（B24 的 G02、G07 和 G03、G04，Gemini 措辞的 H01–H03，以及 H04：F36 改锚到新的那句）；锚点落在这次改过的代码里的旧变异体 19 个（F10 照上一轮的理由不跑，由 F40 顶替）。
  - 串行全量 **5027 passed／7 warnings／463.13 秒**，退出码 0。比 5026 多的 1 项就是新加的 G07 测试；48 个改动文件在全量前后一致。全量开始以后只补了这个数字。

### 审查

第 23 轮，两路只读审查，在 `86dae4e` 上做（10-21 夜），都不派子 agent：A24 看隐私和正确性，B24 看测试、变异和文档。

A24 交了报告：没有 CRITICAL、HIGH，1 MEDIUM、8 LOW、若干 NIT。A24 在自己的副本里用合成库和真实代码做了三组探针，核过：K 的哈希逐字节没变；换哈希分批、核对原文、不会重复换；先删评价再删回答；API 只有两处调 Gemini，都先占名额；删账号覆盖了所有带用户 ID 的列，k=2 撤回在它试过的边界情况里都对。
- **MEDIUM-1：** 勾选「允许保存」旁边的说明还写着「数据、备份和导出不会自动删除」，和隐私页、90 天删除矛盾，而且就在同意的地方。已修，见「已实现」第 1 条。
- **LOW-1：** 登录日志记 Google 账号 ID，删账号删不到。已修，见第 10 条。
- **LOW-2：** 「标记＋NUL＋原文」会被当成已经换过。已修，见第 2 条。
- **LOW-3：** 旧字节还留不留在库文件里，取决于 SQLite 的 `secure_delete` 编译默认值。已修，见第 2 条；上线时还要在容器里核对一次。
- **LOW-4：** 没有密钥时，连不需要密钥的删回答也跳过了。已修，见第 4 条。
- **LOW-5：** 删除超时被说成「什么也没删」。已修，见第 6 条。
- **LOW-6：** 页面把换过哈希的那一行说窄了。已修，见第 1 条。
- **LOW-7：** 离线脚本直接调模型、不占名额；匿名请求大约六分钟就能用完全站一天的 200 次（B24 后来指出，够格救援的 `/chat` 一次占两个名额，最快大约三分钟）。写进了 `docs/request-admission.md` 和 `api/model_budget.py`，没改代码，见「已知」。
- **LOW-8：** 联系邮箱写在 compose 里，push 以后就进了公开仓库。要用户定，见「已知」。
- **NIT：** 「两份投稿」应该是两个不同投稿人；谁能看、Cloudflare 能看到内容；名额在调用之前就占掉；`model_budget.json` 没有 fsync；换了 `SESSION_SECRET` 以后标记就对不上；`daily_limit` 说「明天」不对。都改了文字。Gemini key 是哪一档要问用户，见「已知」。

B24 中途停下了（用户 10-21 夜叫停了所有审查），还没有报告。它停下时的笔记里已经有下面这些，修复一并处理了：
- 空的联系邮箱让设置加载失败（第 9 条）；
- 它自己写的变异体有 11 个在定向测试上存活，都补了测试，或者说明了为什么等价（见「验证记录」）；
- 变异收集的三处缺口：IK11 是因为 NameError 才失败的；sim03 的工具加载不了，它的三个变异体没跑；`query_fields.py` 模块级的锚点漏掉了（见「验证记录」）；
- 每周统计只读打开 WAL 库也会留下 `-wal`／`-shm` 文件，写进了它的文档字符串和 `docs/query-log-export.md`。

修复是第二个提交 `d06d059`。

**复核第 1 轮**（A24，10-21 深夜，在 `d06d059` 的新副本上）：第 23 轮的问题全部修好（L7 照约定只改文档）。A24 用探针核过：带 NUL 的标记现在会换掉；编译默认关闭 `secure_delete` 时，库文件、WAL 和在线备份里都没有旧文字（原文在库文件里、只在 WAL 帧里，两种都试了）；没有密钥时只删回答，别的不动；删除的几种提示和实际知道的一致（500 照旧说什么也没删是对的：提交以前的错误都会回滚，提交以后只记计数、返回）；没有哪行日志还带账号 ID 或邮箱。修复带出 1 LOW、3 NIT，都在第三个提交里处理了：
- **LOW-R1：** `TRUNCATE` checkpoint 碰上旧快照上的读者时，会等满连接的 5 秒，期间挡住新的写入；A24 量到一次插入 5.01 秒后报 database is locked。改成只在 checkpoint 时等 100 毫秒，见「已实现」第 2 条。
- **NIT-R1：** 「库忙时留给 SQLite 下一次自动 checkpoint」不对，自动 checkpoint 不截断文件。改了 `checkpoint()` 的文档字符串、`docs/query-log-export.md` 和本节。
- **NIT-R2：** `secure_delete` 对所有连接生效的代价，记进了文档。
- **NIT-R3：** 登录那两句补上了贡献数和登录时间；删除说明也写上了登录时间。

B24 续上以后、还没开始审修复，用户 10-21 深夜第二次叫停了所有审查；10-22 第三个提交以后接着审。

**B24 的报告**（10-22，审 `86dae4e` 和两个修复提交）：没有 CRITICAL、HIGH。它在 `86dae4e` 上找到 1 MEDIUM（和 A24 的 M1 相同）、5 LOW：它自己写的 17 个变异体有 11 个在定向测试上存活；IK11 是 NameError 才失败的；收集漏了 sim03 的工具和模块级的锚点；空的联系邮箱让两个服务都起不来；每周统计会留下 `-wal`／`-shm`。这些 `d06d059` 都已经覆盖了，B24 对照代码和测试核过，不只看本节。两个修复提交里它新查出 2 LOW、若干 NIT，第四个提交都处理了：
- **LOW G02：** 手动命令里，checkpoint 挪到删回答之前，没有测试会失败：那条磁盘测试没有保存的回答。测试改成带一条保存的回答。
- **LOW G07：** 只删回答、没换原文的那次运行（没有密钥，或者没有到期的原文），没有测试去查磁盘上的文件，`if replaced: checkpoint()` 这样的变异体能存活。补了一条测试。
- **NIT：** 勾选说明里「已经导出的文件不会自动删除」没钉住；100 毫秒只钉到 2 秒以内（改成 0.75 秒，等 1 秒的就会失败）；「最快约六分钟」其实约三分钟；本节的测试数没更新；`answer-feedback.md` 那句加粗的话没跟着改；`api_contract.md` 和本节的删账号步骤顺序和代码不一样。都改了。T 的六个变异体编号、收集只认 `mutate*.py` 文件名、CLI 测试的一秒窗口，写进了上面的验证记录和下面的「已知」。

B24 还核过这些：每一轮红和绿的原因都对；它读了每个变异体的失败输出（190＋72＋22，加上重跑），被杀的都对口，两次误杀（IK11、F15 的第一遍）都已经更正；8 个跟时间有关的测试，在负载下 3 路并行跑了 18 遍都过；本节的数字除了 139 都对得上；列出的文档和代码一致。

**复核第 2 轮**（A24，10-22，在 `4115247` 上）：LOW-R1 和三条 NIT 都修好了。
- 有读者拿着旧快照时，checkpoint 0.103 秒就放弃，后面到的写入 0.104 秒就提交了（之前是等 5.01 秒以后报 database is locked）。
- 等待时间在每条路径上都还原；只有还原本身失败时会留着短的那个，两个调用方都马上关连接，没有影响。没有读者时照样截断。
- 新的 NIT-G：Gemini 那句比条款说得窄三处：存放地点漏了「或其代理」，把存放地点和保留期绑在一起，「维护服务安全」比 safety and security 窄。第四个提交改了。

复核两轮到这里都用完了。

### 已知、未处理

- **上线后第一次启动就会清理：** 90 天以前的提问原文当场换成哈希，换了就改不回来，只有每日备份里还留大约两周。依赖旧原文的导出或评测，要在上线前做完。
- 经过 API 的评测流量也占每天的名额：跑一次真实评测（几十个问题）会用掉当天的一部分。`scripts/` 里的离线脚本直接调模型，不占名额，也不受这个上限管。
- 名额全站共用：匿名请求连着发，最快大约三分钟就能用完一天的 200 次（够格救援的 `/chat` 一次占两个名额：救援一个、回答一个；一次只占一个的大约六分钟），之后到 UTC 零点之前所有人都只拿到 `daily_limit`（A24 L7；B24 指出三分钟）。要防，得先有按身份的配额。
- 限流的数值是估的，没在 NAS 上量过。被挡下的请求不写 query_log，所以每周统计看不到；要看就得数 API 日志里的 429／503。
- 每天的上限只在一个 API 进程里有效；开多个 worker 或多个实例时会各算各的。
- 清理只碰数据库。备份里的原文和回答最多再多留大约两周；已经写进 Docker、代理或隧道日志的内容不受影响。上线以前写下的登录日志行还记着账号 ID，要等轮转掉或者容器重建才会消失。
- 没有 `SESSION_SECRET` 时不换哈希（删回答照跑）。生产一定有它（登录要用），上线时要核对。
- `secure_delete` 现在由每个连接自己打开，不依赖编译默认值；上线时在容器里核对一次它真的生效（`PRAGMA secure_delete` 返回 1）。
- 提问和保存的回答不记账号，所以想删某一条时挑不出是哪一条，只能等到期，或者写邮件说明。
- **联系邮箱（A24 L8）：** 用户 10-21 定了留在 compose，push 以后进公开仓库（每个提交的作者信息里本来就有这个邮箱，隐私页上线以后也公开显示它）。
- **Gemini 的档位：** 用户 10-21 确认是付费档，页面照付费档的条款写了。换成免费档的 key 时要改这句：免费档的内容会被拿去改进 Google 的产品，也可能有人工审阅。
- checkpoint 碰上正在读库的备份、统计或导出时，这次不截断 WAL，旧帧要等下一次运行或者最后一个连接关闭才清掉（A24 复核 NIT-R1）；备份不受影响。
- 旧变异体的收集只认 `mutate*.py` 这样的文件名，评审员用别的名字写的工具（`mutants_*.py`、`mut_*.py`、`b19_mutate.py`）收不进来。B24 静态扫过，落在 `chat()`／`render()` 里的锚点大多和收进来的重复，风险低。
- CLI 的测试用真实的当前时间：2027-01-18 18:00:00 UTC 前后约一秒，`recent` 那行正好到期，期望和结果可能对不上；`test_rescue_takes_a_place_only_when_it_calls_the_model` 的两次调用如果正好跨过 UTC 零点也会失败（B24 NIT）。
- 隐私页写的是实际做法，不是法律意义上的承诺。上线前要请用户读一遍。

### 发布状态

分支 `feat/trial-readiness`，基底是合并 L（#23）以后的 main `6395ee5`：先在 L 的第一个提交 `2fc5cf1` 上写，L 合并以后快进过来，两边没有重叠的文件。第一个提交 `86dae4e` 是 T 本身，第二个提交 `d06d059` 是第 23 轮审查的修复，第三个提交 `4115247` 是复核第 1 轮的修复和 Gemini 付费档那句，第四个提交是 B24 的报告和复核第 2 轮之后的修补（测试和措辞，没有再审）。没有使用真实模型、账号、NAS 或生产库。上线要另外授权；上线时要在容器里核对这些设置（只数不打印），并重新问 P6、P7 跑不跑。

## 33 — 新前端的后端准备：会话 cookie、跨站防护、CORS 和公开接口（R2a，2026-10-22）

### 范围与原因

10-22 用户定了：前端换成 React；R2（接口层和登录）由协调方来写，分两批，先后端（R2a，本节），再前端（R2b）。新前端的 Google 登录照旧回站点根路径。

新前端是在浏览器里直接调 API 的单页应用：compass 子域名上的页面调 api 子域名，同一个站点、两个来源。这一批给它准备后端：登录态放进 API 自己的 HttpOnly cookie，前端脚本碰不到令牌；带 cookie 的写请求要过跨站检查；CORS 只放行设好的来源；再加三个前端要用的公开接口。

生产没有设 `WEB_ORIGINS`，所以这批代码上线以后，现有的行为都不变：没有 CORS，也没人用 cookie 模式。compose 只给 api 服务加了联系邮箱（见第 9 条）。

### 已实现

1. **搬模块，不改行为：** `app/auth.py` 搬到 `api/google_oauth.py`，`app/session_tokens.py` 搬到 `api/session_tokens.py`，内容照搬。
   - `app/` 里的这两个文件改成转发同一批对象的壳，给 Streamlit 版用到它退役为止。
   - `api/` 里原来从 `app/` 导入的三处（`dependencies.py`、`exceptions.py`、`routes/auth.py`）改成从新模块导入。一条测试扫描 `api/` 下的每个文件，钉住不再导入 `app`，切换以后删 `app/` 不会让 API 坏掉。
2. **会话 cookie**（`api/session_cookie.py`）：`/auth/callback` 的请求体多一个可选字段 `session`。
   - `"token"`（默认）：和以前一样，令牌在返回体的 `session_token` 里。Streamlit 和脚本照旧用它。
   - `"cookie"`：令牌放进 cookie `__Host-nc_api_session`（HttpOnly、Secure、SameSite=Lax、Path=/、不带 Domain、Max-Age 等于 `SESSION_MAX_AGE_SECONDS`），返回体里的 `session_token` 是 null。用的是和 Bearer 同一种签名令牌。
   - `__Host-` 前缀让浏览器强制 Secure、Path=/、不带 Domain，别的子域名设不了同名 cookie。compass 和 api 是同一个站点，所以 SameSite=Lax 的 cookie 在前端的请求里照样会带上。
   - 没有 `SESSION_SECRET` 时两种模式都签不出令牌，也就不设 cookie。
   - cookie 模式要来自 `WEB_ORIGINS`、带 `X-NEU-Compass: 1`（和第 5 条同一个判断），不管原来带没带 cookie；不然回同样的固定 403，而且在 code 交给 Google 之前就拒绝。
   - 挡登录劫持（别的网站把浏览器登录成它选的账号）的第一道是严格的 Content-Type（第 12 条）：别的来源要发 JSON 请求体，得先过 CORS 预检。这个检查是第二道：哪天第一道没了（较早的 FastAPI 会把不带 Content-Type 的请求体照样按 JSON 读），别的网站用一个简单的 POST 就能做到。第一版这里写的理由（「FastAPI 照样按 JSON 解析」）对锁定的 FastAPI 0.136.1 不成立，审查指出以后改了（见「审查」）。
   - token 模式不查（Streamlit 从服务器端调，没有 Origin）。
3. **身份**（`get_current_user_id`）：有非空的 `Authorization` 头时和以前完全一样，无效（包括不是 `Bearer …` 的头）就 401，这时不看 cookie。没有这个头、或者它是空的时候才看 cookie：有效就是它的用户，无效或过期就当游客。cookie 是浏览器自己带的，坏 cookie 不能让公开接口都变成 401。
4. **cookie 失效和登出：**
   - `GET /auth/me`：cookie 坏了、过期了，或者它的账号已经不在了，401 的同时让 cookie 过期，浏览器就不再带它。
   - `POST /auth/delete-account`：用 cookie 删号成功以后，让 cookie 过期；cookie 坏了、过期了，或者账号已经不在，401 的同时也让它过期，和 `/auth/me` 一样。用 Bearer 删号时不动 cookie。
   - 让 cookie 过期的那条 `Set-Cookie` 也带着 Secure 和 Path=/、不带 Domain：浏览器对 `__Host-` 的名字只认这样的，不然删不掉。测试逐条核对这几个属性。
   - 新加 `POST /auth/logout`：回 204，让 cookie 过期；从前端发来、没有 cookie 时也是 204。它只清 cookie，不吊销令牌（见「已知」）。
   - 登出也要来自 `WEB_ORIGINS`、带 `X-NEU-Compass: 1`，带不带 cookie 都查，不然回同样的固定 403，什么也不过期。别的网站提交的表单不带 SameSite=Lax 的 cookie，第 5 条的中间件不拦它，可回答里让 cookie 过期的头照样能把人登出（A25 L1）。
5. **跨站防护**（`api/csrf.py`，纯 ASGI 中间件）：只查写请求（GET、HEAD、OPTIONS 以外），而且只查带了会话 cookie、没带非空 `Authorization` 头的请求。
   - 要求正好一个 `Origin`，它在 `WEB_ORIGINS` 里，并且正好一个 `X-NEU-Compass: 1`。不满足就回固定的 403 `{"detail": "Cross-site request refused.", "error_type": "csrf_rejected", "status_code": 403}`，不回显 Origin，不缓存。
   - 别的来源的网页要带这个自定义头，得先过 CORS 预检，而 CORS 只给 `WEB_ORIGINS` 放行，所以它发不出能过检查的请求。
   - Bearer 请求不查：浏览器从来不会自己带 Bearer。没带 cookie 的请求（比如游客提问）也不查，值是空的 cookie 不算会话。
   - 带的是哪种凭证，和身份解析一样，用 Starlette 自己的请求头和 cookie 来读，两边不会不一致。空的 `Authorization` 头不算 Bearer（身份解析这时会转而用 cookie），所以照样要查；`=` 两边有空格、放在第二个 Cookie 头里的会话 cookie，Starlette 认得出，这里也认得出。
   - `WEB_ORIGINS` 为空时，带 cookie 的写请求一律拒绝。
6. **CORS：** 只有 `WEB_ORIGINS` 不空时才加 Starlette 的 `CORSMiddleware`：只放行这些来源，允许带凭证，方法是 GET、POST、OPTIONS，请求头是 `Content-Type` 和 `X-NEU-Compass`，暴露 `x-request-id` 和 `Retry-After`，预检缓存 600 秒。没设就完全不加，和以前一样。
7. **中间件的顺序**（从外到内）：CORS → 请求日志 → 跨站防护 → 限流 → 防缓存头（第 13 条）→ 路由。CORS 在最外面，限流的 429 和 503、跨站防护的 403、请求日志兜底的 500 都带 CORS 头，前端读得到；跨站防护在限流外面，被拒的请求不占名额。
8. **`GET /auth/login-url?state=`：** `state` 要是 16–128 个 `A–Z`、`a–z`、`0–9`、`_`、`-`，不合格就 422，也不回显它。测试钉住了两头（16、128 能过，15、129 不过）和带 `_` 的（R2b 照这个生成 state，base64url 里有 `_`）。
   - 用现有的 `authorize_url(state_token=state)` 拼出 Google 的登录地址，和 Streamlit 的登录链接一样。API 不存 state，生成和核对都在前端（R2b）。
   - Google 的 client ID、client secret 和 `SESSION_SECRET` 缺一样就回 503（`service_unavailable`），返回体是固定的，测试整个钉住：没有 client secret，每次回调都会在 Google 那边失败；没有 `SESSION_SECRET` 就签不出令牌，登录了也没用。client secret 是审查以后补的（A25 N4）。
   - uvicorn 的访问日志记这个地址时去掉查询串，state 不进日志（A25 N3；课程读那几条原来就这样）。
9. **`GET /privacy`：** 「数据与隐私」页的内容按 API 自己的设置生成：开头一句、四段（标题和纯文字的句子，按页面顺序）、删号会删掉什么，以及提问框旁边的两段说明。回答反馈关着时，勾选说明是 null。
   - 文字搬进了 `api/privacy_text.py`（`privacy_sections`、`DELETE_WHAT`、`BACKUP_COPIES`、`capture_notice`、开头那句，以及聊天提示的前半句），`app/` 里的两个文件改成从那里导入。搬家前后在 24 种设置组合下逐字节比过，Streamlit 页显示的完全一样。
   - 聊天提示指向隐私页的后半句（「见左侧「🔒 数据与隐私」」）是 Streamlit 的版面用语，留在 `app/`。接口只返回前半句，指向由前端自己加。
   - 这样页面上写的就是保存数据的这个 API 实际用的设置。compose 里的联系邮箱原来只给了 ui 服务，现在 api 服务也加上了，不然上线以后接口返回的页面会少「写邮件到 …」那一句；钉住两边一致的那条测试也加上了它。
10. **`GET /config`：** 返回 `{"answer_feedback_enabled", "login_available"}`。`login_available` 是「Google 的 client ID、client secret 和 `SESSION_SECRET` 都有」，和 `login-url` 回不回 503 用的是同一个函数（`login_configured()`）。
11. **设置 `WEB_ORIGINS`**（`config/settings.py`）：JSON 列表，默认空。
    - 每一项只能是小写的 `http` 或 `https`、主机和可选的端口，不带路径、查询或结尾的斜杠，也不能是 `*`（带凭证的 CORS 不许用通配）。不合格的设置起不来。
    - 写法要和浏览器在 `Origin` 里发的一模一样，不然永远对不上：浏览器发的都是小写；主机的每一段不以 `-` 开头或结尾；端口是 1–65535、不带前导零，而且不写默认端口（https 的 `:443`、http 的 `:80`）。端口这几条和 `-` 是审查以后补的（A25 N2）。
    - 不设或者 `[]` 就是没有 CORS。`WEB_ORIGINS=` 后面什么都不写不是 JSON 列表，API 起不来（`.env.example` 原来说「空」就是没有 CORS，改了）。
    - `.env.example` 加了一行注释掉的例子（本机开发用的 `http://127.0.0.1:5173`）。
12. **严格的 Content-Type**（A25 L2）：`create_app` 里明写 `strict_content_type=True`。这是 FastAPI 0.136.1 的默认值，明写出来是怕升级或改动时悄悄关掉。
    - JSON 请求体要带 JSON 的 Content-Type：不带、`text/plain` 或表单都回 422，什么也不读。
    - 别的来源要发 JSON 的 Content-Type 得先过 CORS 预检，而预检只给 `WEB_ORIGINS` 放行。所以它是挡借 cookie 的跨站写请求的第一道，第 2、4、5 条的来源检查是第二道。
    - 测试钉住：两种登录模式下，不带 Content-Type 和 `text/plain` 的请求体都是 422，不调交换函数；从前端自己的来源发来也一样。
13. **按身份的回答不进共享缓存**（`api/private_cache.py`，A25 L3）：
    - `get_current_user_id` 每次调用都给请求做个记号，在任何 401 之前。小中间件给这些请求的响应写上 `Cache-Control: private, no-store`，游客的回答和 401 也写。
    - 用到它的接口是 `GET /coop`、`GET /auth/me`、`POST /coop`、`POST /auth/delete-account`。
    - RFC 9111 只禁止共享缓存复用带 `Authorization` 的回答，不管 `Cookie`；身份从 Bearer 换成 cookie 以后，这层保护要自己补上。游客的也写，缓存才不会把游客版给登录的人。
    - 对谁都一样的回答不动，带不带 cookie 都一样。
14. **Streamlit 删号「没收到确认」那句**（`app/privacy_view.py`）改成和新前端一样的说法（R5c，用户定的）：「这次没收到服务器的确认，不确定删除有没有完成。刷新后若仍是登录状态，可以再试；若已变成游客但需要确认，请联系维护者。」原来那句说「变成游客了，就是已经删掉了」，可登录自己过期也会变成游客。

### 修改文件

- 新建：`api/session_cookie.py`、`api/csrf.py`、`api/privacy_text.py`、`api/routes/public.py`，以及第二个提交的 `api/private_cache.py`。
- 搬家：`api/google_oauth.py`（原 `app/auth.py`）、`api/session_tokens.py`（原 `app/session_tokens.py`）；`app/auth.py`、`app/session_tokens.py` 改成转发的壳。
- 改：`api/dependencies.py`、`api/exceptions.py`、`api/routes/auth.py`、`api/models.py`、`api/main.py`、`app/privacy_view.py`、`app/answer_feedback_view.py`、`config/settings.py`、`.env.example`、`docker-compose.yml`（只加了 api 服务的联系邮箱）；第二个提交另改了 `api/logging.py`（访问日志去掉登录地址的查询串）和 `db/user_repository.py`（文档字符串里的模块路径；另外去掉了基底就有、没用到的 `datetime` 导入：这个文件进了 Ruff 检查的范围以后报 F401）。
- 文档：
  - `docs/api_contract.md`：路由表（第二个提交补上了原来就漏掉的七个接口）、鉴权方式、`/auth/callback` 的 `session` 字段、四个新接口，以及「Session cookie, CSRF and CORS」一节；
  - `docs/adr/0021-session-token-auth.md` 的补充；
  - `docs/oauth_secret_rotation.md` 和 `docs/cloudflare_tunnel.md` 里的模块路径，第二个提交加上 `docs/system_architecture.md` 两张图里的；
  - 本节。
- 测试：新建 `test_session_cookie.py`、`test_csrf_cors.py`、`test_public_routes.py`，第一个提交 79 项，第二个提交以后 133 项；`test_privacy_view.py` 的 compose 测试加上了联系邮箱。第二个提交另改了 `test_account_deletion.py`（钉住「没收到确认」那句）和 `test_request_admission.py`（中间件顺序那条不再受开发者的 `.env` 影响）。

数据库结构、检索、提示词和 Streamlit 版的登录都没改。Streamlit 版只改了删号「没收到确认」那一句（第 14 条）。

### 验证记录

- **新测试：** 三个新测试文件 79 项全过。同样的测试放在基底 `3a08ebd` 的副本上：`test_session_cookie.py` 和 `test_csrf_cors.py` 在收集时就失败，因为新模块还不存在；`test_public_routes.py` 的 30 项全部失败。
- **定向和静态检查：**
  - 冒烟 **360 passed**（登录、令牌、Co-op、删号、隐私页、反馈开关、错误出口、日志和限流的测试）；定向 **1081 passed**。
  - Ruff F／E9／B 在 20 个改过的 Python 文件上通过，没有 CR。隐形字符只有 `docs/api_contract.md` 开头的 BOM，基底里本来就有。
  - 九个快照 9/9 match；C 的离线 CLI 47／53 complete，route 53／0，隔离计数为 0。
  - 隐私页的文字搬家前后逐字节相同（`same_words.py`）：`privacy_sections` 比了 24 种设置组合（保留天数 0、1、90，反馈开关 true、false、null、1，有没有联系邮箱），勾选说明比了 5 种天数，另外是删号说明、备份说明和查询日志提示。
- **变异：98 个，全部杀掉**（mut4）。
  - 新写 60 个：R01–R58，以及 T61b、T91b（T 的 T61、T91 跟着代码搬家以后改锚）。
    - R36（没设 `WEB_ORIGINS` 也加 CORS）第一次被当成等价拿掉，是错的：一个谁都不放行的 CORS 层照样会加 `access-control-allow-credentials` 和暴露的头，预检也回 400。收紧那条测试以后加回来了。
    - R32 第一次写错了，把请求日志删掉了；现在是真的把日志挪到 CORS 外面。
    - 跨站防护改用 Starlette 读凭证、又抽出 `from_web_origin()` 以后，R23–R30 改了锚点；补了 R47–R49（空的 `Authorization` 也免查、按子串找 cookie、只看第一个 Cookie 头）和 R56–R58（cookie 登录不查来源、换完 code 才查、token 模式也查）。
  - 锚点落在 R2a 改过或搬走的代码里的旧变异体 38 个：`collect_old_mutants_r2a.py` 按 diff 收集，受影响 9 个，跟着代码搬家、改到新位置的 29 个（搬家用 `--no-renames` 加一张搬家表对上）；T 的 T61、T91 由 T61b、T91b 顶替。
  - 每个变异体日志的第一条错误都逐个看过：除了 R06，都是对口的测试杀的；没有只靠超时判定的，也没有因为时钟跳变失败的。
    - R04、R32、R33、R35 是测试按名字取那个属性或响应头时报 KeyError，取的正是变异去掉的那个，算对口。
    - R06（让 cookie 过期的函数什么都不做）两轮都是被 `/auth/me` 的 500 杀的：过期用的那条头 `expired_session_cookie_header()` 就是靠这个函数生成的，它一坏，每次 `/auth/me` 都报 KeyError。这算真杀（谁都登录不了），但不是对口的那条检查；对口的是 R15（登出不让 cookie 过期）和 R55（过期时留下一个空值 cookie），都被对口的测试杀了。
  - 第一轮 mut1（第一版代码）85/85。mut2 中途停掉，作废；mut3 的基线没过，也作废，原因见下一条。
- **测试机的时钟：** 10-22 晚这台机器的 Windows 时间服务没开，本机比 NTP 快 2.75 秒，WSL 的时钟每 20–30 秒被来回拨一次。往回拨以后，刚签的令牌会被 itsdangerous 当成「签发时间在未来」（`Signature age -3 < 0 seconds`）而拒绝。mut3 的基线就是这样失败的：同一个令牌 `/auth/me` 刚回 200，下一步删号回 401。同样的测试在 worktree 里重跑全过。这是这台测试机的时钟问题，和本节的代码无关；令牌的这条规则（签发时间在未来就拒绝）也不是 R2a 加的。
- **串行全量：** **5106 passed／7 warnings／485.35 秒**，退出码 0。比 main `3a08ebd` 的 5027 多出的 79 项就是新测试；27 个改动文件在全量前后一致。全量开始以后只改了本节：补上这些数字，以及「发布状态」里关于 main 的一句。

- **第 24 轮审查以后的修复**（第二个提交：A25 和 B25 的报告，加上 Streamlit 那一句）：
  - 改过的 5 个测试文件 **257 passed**。同样的测试放在第一个提交 `2d5ebdf` 上跑，24 项失败，原因都对：没带 cookie 的跨站登出（5 项）、防缓存头、缺 client secret 时的 `/config` 和 503（2 项）、访问日志里的 state（2 项）、`WEB_ORIGINS` 的九种写法、Streamlit 那句（5 项）。其余新加的测试在 `2d5ebdf` 上就通过：它们钉的是原来就对、只是没测到的行为（B25 的 L1–L4 和 N1，以及严格的 Content-Type，它本来就是 FastAPI 的默认值）。
  - 冒烟 **360 passed**，定向 **1135 passed**（比第一个提交多的 54 项，就是三个新测试文件里新加的）。Ruff F／E9／B 第一次在 `db/user_repository.py` 报了一处 F401：基底就有、没用到的 `datetime` 导入（这个文件只改了文档字符串，才进了检查的范围）；去掉以后 25 个改过的 Python 文件都通过。没有 CR，隐形字符只有 `docs/api_contract.md` 开头基底就有的 BOM。九个快照 9/9 match；C 的离线 CLI 47／53 complete，route 53／0，隔离计数为 0。
  - **变异 131/131 killed**（mut6），被杀的都是对口的测试，没有只靠超时判定的。
    - 新写 22 个：R59–R80。改锚 5 个：R16b、R39b–R41b、R45b（代码挪进 `login_configured()` 和新的来源写法以后，原来的 R16、R39–R41、R45 锚不上了）。R42（端口放宽到六位）不再跑：六位的端口都大于 65535，现在照样按数字拒绝，它和没改的代码等价。「按身份的回答保留路由自己写的 Cache-Control」也是等价的，没写：没有这样的路由自己写这个头。
    - 第一个提交的其余 54 个照样重跑：好几个测试文件改了，杀死它们的测试可能跟着变。
    - 锚点落在改过的代码里的旧变异体 50 个：受影响的 21 个（比第一个提交多了访问日志过滤器的 5 个和 Streamlit 删号回调的 7 个），跟着代码搬家的 29 个。去掉 `datetime` 导入以后重新收集，还是这 50 个。
    - R80（Streamlit 那句改回旧的）第一遍是被 `test_coop_moderation.py` 的 `KeyError: 'coop_id'` 杀的：WSL 的时钟又往回跳了（这段时间 journalctl 里有 17 次），刚签的令牌被拒，和 R80 无关。单独重跑，被对口的 `test_page_delete_failure_says_what_is_known` 杀掉。
  - 串行全量 **5160 passed／7 warnings／484.36 秒**，退出码 0。比第一个提交的 5106 多出的 54 项就是这次新加的测试；相对 `3a08ebd` 的 33 个改动文件在全量前后一致。全量开始以后只补了本节的数字。

### 审查

第 24 轮，两路只读审查，在 `2d5ebdf` 上做（10-22 夜到 10-23），都不派子 agent：A25 看安全和正确性，B25 看测试、变异和文档。

**A25 的报告：** 没有 CRITICAL、HIGH、MEDIUM，3 LOW、5 NIT。它在自己的副本里用合成密钥、内存库、不联网，做了三组探针，核过：
- 方法的各种写法、`Origin` 和标记头的各种形式、各种 Content-Type，都过不了跨站检查；中间件和身份解析读到的凭证一致，空的、重复的头和 cookie 也一样；
- cookie 登录在 code 交给 Google 之前就拒绝；让 cookie 过期的头带着 `__Host-` 要的属性；
- CORS 只让 `WEB_ORIGINS` 读到东西，层的顺序和文档一致；
- 搬家的模块除了文档字符串逐字节相同，`api/` 不再导入 `app`；隐私页的文字在 48 种设置组合下逐字节相同。

它的发现：
- **LOW-1：** 别的网站能把人登出：不带 cookie 的登出不过跨站检查，照样回 204 和让 cookie 过期的头。已修，见第 4 条。
- **LOW-2：** 第 2 条给的理由不对：锁定的 FastAPI 0.136.1 默认严格检查 Content-Type，不带 Content-Type 的 JSON 是 422，根本不读。改了第 2 条，加了第 12 条。
- **LOW-3：** 按身份返回的 GET 没有防缓存的头。已修，见第 13 条。
- **NIT：**
  - 隐私页文字里两句是 Streamlit 的版面用语，`CAPTURE_OFF_NOTICE` 留在 `app/`：记进「已知」，是 R2b 的事。
  - `WEB_ORIGINS` 放过浏览器不会发的写法，`.env.example` 说「空」就是没有 CORS：见第 11 条。
  - state 进了 uvicorn 的访问日志：见第 8 条。
  - `login_available` 和 503 没看 client secret：见第 8、10 条。
  - `api_contract.md` 的几处旧说法（回调「不需要头」、匿名接口清单少了四个、401 的文字还写着 Bearer）：改了文档；401 的文字为了兼容不改，文档写明前端别显示它。

**B25 的报告：** 没有 CRITICAL、HIGH、MEDIUM，6 LOW、6 NIT。它核过本节的每个数字和日志，mut4 的 98 个杀死都对口，它的副本上全量也是 5106；搬家的模块和所有导入都对；隐私页的 24 种设置组合走到了每个分支。它自己写了 24 个变异体：4 个被杀，2 个等价，18 个存活。缺口都在新约定的边上：
- **LOW-1：** 同时带 Bearer 和 cookie 的测试没确认 cookie 真在：把 cookie 登录改成不设 cookie，`test_session_cookie.py` 的 27 项里还有 21 项通过；「有 cookie 就过期」（应该是「用了 cookie 才过期」）能存活。补了 `logged_in()`（登录以后确认 jar 里真有 cookie），删号和 `/auth/me` 都加了「Bearer 旁边带着别的账号的 cookie」的情况。
- **LOW-2：** `state` 的边界没钉住，补了（见第 8 条）。
- **LOW-3：** login-url 的 503 返回体没钉住，改成整个返回体相等。
- **LOW-4：** 身份解析读 `Authorization` 的方式没钉住：「不是 `Bearer …` 的头就用 cookie」和「空的头算坏的 Bearer」两种变异都能存活。补了两条测试。
- **LOW-5：** 和 A25 的 LOW-2 相同。
- **LOW-6：** `docs/system_architecture.md` 还画着 API 依赖 `app/auth.py`，`db/user_repository.py` 的文档字符串也这样写。改了。
- **NIT：**
  - 没钉住的反例：拒绝时不带 `no-store`、两个标记头、HEAD 和 OPTIONS 也查、CORS 放行 `Origin: null`、方法和请求头放开成 `*`。都补了测试。`Vary: Origin` 是 Starlette 加的，记进「已知」。
  - 同一个检查函数（`from_web_origin`）两个调用方：有的变异体只被其中一个调用方的测试杀掉；回调要是不再调这个共用的函数、自己另写一套（B25 的 M16），没有测试会发现。只要都调它就没问题；现在登出也调它。
  - `/config` 和 `/privacy` 用 `is True`：设置本来就转成 bool，生产上和 `bool(...)` 一样，没改。
  - 旧变异体收集的盲区，记进「已知」。B25 核过，这些盲区没漏掉存活的变异体。
  - 措辞：`api_contract.md` 第 49 行、ADR-0021 和第 3 条说「有 `Authorization` 头时」，应该是非空的头；新接口哪些是匿名的、`/auth/me` 要凭证，没写；路由表漏了 R2a 以前的七个接口。都改了。
  - 两条测试读当前目录的 `.env`：开发者在 `.env` 里设了 `WEB_ORIGINS` 时会失败。改成不读。

修复是第二个提交。

**复核第 1 轮**（10-23，还是 A25 和 B25，在 `6b98209` 的新副本上，只读、不派子 agent）：两边都没有新的 CRITICAL、HIGH、MEDIUM、LOW。第 24 轮的问题都按本节说的修好了，记进「已知」的几条也属实。
- A25 用探针核过：登出只在来自 `WEB_ORIGINS`、带标记头时回 204，带不带 cookie 都一样；防缓存头只加在那四个按身份的接口上（依赖里抛的 401 也有），别的接口的头和 `2d5ebdf` 一样；`WEB_ORIGINS` 试了 31 种写法。它第 24 轮的探针在两个提交上跑，只有这几处不同。修复没有让别的网站多做到什么，也没有多漏什么。
- B25 在 `2d5ebdf` 上重跑改过的测试，失败的正是那 24 项，原因都对。它第 24 轮写的 19 个变异体有 15 个被新测试杀掉；剩下 4 个（M09、M10、M16，以及新写的 M16L：登出那边的同一种改法）在全量下存活，和上面不改的那几条一致。本节第二组验证的数字都和日志或它的重跑对得上。它复核时 WSL 的时钟还是每半分钟往回跳 2.5 秒左右：这只会多出假的失败，通过的结果都算数。
- NIT 共五处（401 的文字两边都报了），都是文字，第三个提交都改了：
  - `api_contract.md` 的 401 文字清单漏了 `POST /coop` 的两句（A25、B25）；
  - 「已知」里 `Vary: Origin` 那条拿 `/search` 举例，可它是 POST，没有明确的新鲜度和对应的 `Content-Location`，共享缓存本来就不存；改成 GET 的接口（A25）；
  - 「发布状态」里 main 的提交号过时了（B25）；
  - `.env.example` 新加的那句说明以 `# WEB_ORIGINS=` 开头，去掉注释就成了一个不合格的设置；改了开头（B25）；
  - 变异那段说 R42 和 R75 等价，应该是和没改的代码等价（B25）。
- 第三个提交只改 `docs/api_contract.md`、`.env.example` 的那行注释和本节。没有测试读这几个文件，所以没有重跑测试，也不再开第 2 轮复核。

### 已知、未处理

- **登出不吊销令牌：** 登出只让 cookie 过期，令牌本身到期以前一直有效，和 Bearer 一样没有服务器端吊销。cookie 是 HttpOnly 的，前端脚本偷不到；万一被偷（比如设备被别人拿到），登出也挡不住，只能等 7 天到期，或者换 `SESSION_SECRET`（所有人都要重新登录）。
- **state 只在前端核对：** `/auth/login-url` 不存 state。别的网站直接调回调已经被来源检查挡住，但它还可以把人引到站点根路径、带上它自己的 `?code=`，让我们自己的前端去提交；挡这一种全靠 R2b 的前端核对 state。
- 生产没有设 `WEB_ORIGINS`。R7 上线新前端时要设成生产的 compass 子域名，并且核对 compass 和 api 在同一个站点下，不然 SameSite=Lax 的 cookie 不会带上。
- `eval/route_eval.py`、`scripts/answer_render_check.py` 还从 `app/` 导入 UI 模块（`app.state_manager`、`app.api_client`、`app.chat_view`、`app.answer_evidence_view`），到切换（R7）时再处理。
- 跨站防护只看 `Origin`，不看 `Referer`：不带 `Origin` 的、带 cookie 的写请求一律拒绝。新前端用 fetch，现代浏览器都会带上它。
- 被跨站防护拒掉的请求不写 query_log，每周统计看不到；要看就数 API 日志里的 403。
- 隐私页的文字只有中文。
- **隐私页里两句是 Streamlit 的版面用语**（A25 N1）：「登录以后，可以在本页最下面删除…」说的是页面位置，「选课草案和课程对比只在这次会话里，刷新或登出就清空」说的是 Streamlit 的会话，`GET /privacy` 照样返回。新前端要让这两句也成立（删除放在页面最下面；草案和对比刷新或登出就清空），做不到就把这两句挪到各个前端。回答反馈关着时提问框旁边那句（`CAPTURE_OFF_NOTICE`）留在 `app/`，接口返回 null，新前端要自己写一份。这是 R2b、R3 的事。
- **`Vary: Origin`**（B25 N1）：Starlette 只给放行的来源加 `Vary: Origin`，给别的来源和不带 `Origin` 的回答都不加。对谁都一样的 GET 回答（比如 `/programs`、`/course/{course_id}`、`/privacy`、`/config`）要是被共享缓存存下来，可能把不带 CORS 头的那份给了前端。今天 api 子域名没有缓存规则；R7 上线时核对，不要加。
- **FastAPI 的版本：** pyproject 写的是 `fastapi>=0.110`，锁定的是 0.136.1。较早的 FastAPI 会把不带 Content-Type 的请求体照样按 JSON 读，那时第一道就没了，只剩来源检查。测试钉住了 422，换版本时会失败。
- **旧变异体的收集**（B25 N4）：只认 `mutate*.py` 这样的文件名（T 那一节已经记了）；只看 `.py` 文件，R2a 在 compose 里加的那一行让 T 的 T100 的锚点出现了两次，它跑不了，也没算成被顶替；作用域从 `def` 算起，只改装饰器的地方（路由的说明文字）不算。B25 核过，这些盲区没漏掉存活的变异体，它为 compose 那一行写的三个变异体都被杀了。

### 发布状态

分支 `feat/api-cookie-session`，基底是合并 T（#24）以后的 main `3a08ebd`。之后 main 又合并了 R1（#25）、Co-op 页（#26）、课程对比页（#27）和隐私页（#28），现在是 `30cfbae`；四次都只改 `web/`（R1 另改了 CI），和本节的文件不重叠。第一个提交 `2d5ebdf` 是 R2a 本身，第二个提交 `6b98209` 是第 24 轮审查（A25、B25）的修复和 Streamlit 那一句，第三个提交是复核第 1 轮的五处措辞，只改文档和 `.env.example` 的一行注释。没有使用真实模型、账号、NAS 或生产库，也没有连真实的 Google（测试用现有的替身）。上线要另外授权。

## 34 — 新前端接上真实 API：接口层、登录和聊天流（R2b，2026-10-23）

### 范围与原因

R2 的前端一半（方案 `R2B_PLAN.md`，10-23 用户定了第 6 节四条）。第 33 节（R2a）给了 cookie 登录、跨站防护、CORS 和三个公开接口；这一批让 React 前端第一次真的请求 API：接口类型从 OpenAPI 生成，请求和错误统一处理，cookie 登录和登出，`/chat` 的流式客户端，外加一个只给本机开发和验收用的 API 外壳。各页的内容还是假数据：隐私、Co-op、对比三页在 R5d 接，搜索和聊天页在 R3。

线上不变：新前端还没部署，生产也没设 `WEB_ORIGINS`。后端只多了两样（第 6、7 条），Streamlit 版不受影响：`/auth/login-url` 它不调用；回调的 token 模式不查 `redirect_uri`；401 多一个字段，它不读。

### 已实现

**第一步：接口层**

1. **导出 OpenAPI**（`scripts/export_openapi.py`）：`create_app(run_startup=False).openapi()` 写成 `web/openapi.json`，键排序、不转义中文、缩进 2、一个 LF 结尾；不起服务、不加载模型。`--check` 只比较不写，不一致就退出 1。设置（`WEB_ORIGINS`、反馈开关、限流、保留天数）不影响导出的内容。除了 `POST /chat` 的 200（NDJSON，第 11 条手写类型），每个接口的回答都有类型。
2. **生成类型**（`web/tools/openapi-types/`）：openapi-typescript 7.13.0 的 peer 只声明 TypeScript 5，主包用 6.0.3，直接装会 ERESOLVE；规矩不许 `--legacy-peer-deps`／`--force`，所以生成器单独一个包（自带 TypeScript 5.9.3 和 lockfile），用主包的 Prettier 排版。`npm run gen:api` 生成 `web/src/api/schema.ts`，`gen:api:check` 比较。原来手写的 `api/coop.ts`、`privacy.ts`、`course.ts` 的接口形状改成从生成的类型取（`CoopRecord` 从 `CoopOut` 收窄 industry 和 visibility_level，`CoopUploadRequest` 用 `Required<>`，表单总是发全部字段）。
3. **API 地址**（`web/src/api/apiBase.ts` 的 `chooseApiBase`、`vite.config.ts`）：构建时定，`VITE_API_BASE_URL`。正式构建（`npm run build`）默认 `https://api.neu-compass.me`，换成别的也只能是 https，本机的 http 让构建失败，免得给学生的页面去连他们自己的电脑；`npm run build:dev-api`（模式 `dev-api`）和开发服务器默认 `http://127.0.0.1:8000`，前者输出到 `dist-dev-api/`、用 `npm run preview:dev-api` 预览，所以 `dist/` 里只会有连正式 API 的构建（测试钉住这几个脚本）；别的构建模式（比如以后的 beta）必须写明地址；测试一律用本机的，不管环境里设了什么。地址只认 https 或本机的 http（localhost、127.0.0.1、[::1]），不带路径、查询、`#`、账号密码，坏值让构建失败。代码里读 `__API_BASE_URL__`，不从 `window.location` 推。`web/.env.local` 这类文件加进了 `.gitignore`。
   - 本机地址用 127.0.0.1，不用方案写的 localhost：开发服务器在 127.0.0.1:5173，主机名不同浏览器就当成两个站点，SameSite=Lax 的 cookie 不跟着 fetch 走。
4. **请求函数**（`web/src/api/client.ts`）：
   - 每个请求 `credentials: 'include'`、`cache: 'no-store'`、`redirect: 'manual'`；写请求加 `X-NEU-Compass: 1`，有请求体才加 JSON 的 Content-Type，读请求两样都不加，不触发预检。
   - `apiPath` 按 OpenAPI 的路径模板填参数、逐个编码：接口改名或删掉，重新生成 `schema.ts` 以后就编译不过。空值、`.`、`..` 直接报错：编码以后 URL 会把它们读成另一条路径。
   - 四档超时照 Streamlit（5／8／15／30 秒，读完回答也算在内）；什么都不自动重试；调用方取消时原样抛出它的原因。
   - 失败一律是 `ApiError {status, errorType, retryAfter, invalidFields, reason}`：`error_type` 和 `reason` 只认小写名字，`Retry-After` 只认 1–3600 的整数秒，422 只取被拒字段的名字。**不带 `detail` 原文**（R2a 的约定，原文是英文、可能说出内部细节）。2xx 不是 JSON、重定向都算 502 `invalid_response`；连不上 503 `transport_error`，超时 504 `transport_timeout`。
   - `apiErrorMessage` 照 Streamlit 的中文：429 带秒数、503 分忙和不可用、408／504「处理可能仍在进行」、502 无法识别、其余 5xx、其余一句通用的。4xx 由各页按状态和 `error_type` 说自己的话。Streamlit 版 4xx 会显示 `detail`，React 版不显示，是有意的不同。
5. **取数**（`web/src/api/queries.ts`，新依赖 `@tanstack/react-query` 5.104.5）：不重试，切回窗口、网络恢复都不重取；`networkMode: 'always'`：断网时请求照样发出、照样失败，不排队等网络回来再自己发出去（TanStack 默认会这样，写请求不能）；`shownData`：暂时的失败（408、429、5xx、断线）继续显示同一访客上次的内容，明确的答复不留。`useConfig`（`/config`，5 分钟内算新鲜）、`useMe`（`/auth/me`，401 就是游客，不自己过期）；身份照 Streamlit 的 `valid_identity` 检查，格式不对算失败，不会半登录。

**第二步：登录**

6. **回调的 401 带上原因**（`api/exceptions.oauth_rejection_response`，用户定的第 1 条）：回调和全局处理器回同一个返回体，原来的三个字段之外加 `reason`（`OAuthError` 的七种稳定原因之一）。`detail` 照旧是固定英文；`reason` 本来就能从 `detail` 看出来，没有多告诉浏览器什么。
7. **回调地址**（用户定的第 2 条，beta 上要能登录）：`GET /auth/login-url` 多一个可选的 `redirect_uri`（最多 2048 个字符），`authorize_url` 用它代替 `GOOGLE_OAUTH_REDIRECT_URI`；cookie 模式的回调也查请求体里的 `redirect_uri`。login-url 只认 `WEB_ORIGINS` 里的来源加 `/`（`auth.web_redirect_uris()`）；回调更严，只认这次请求的 `Origin`（上一步刚查过它在 `WEB_ORIGINS` 里）加 `/`，Google 送到哪个前端的 code 只有那个前端能兑换。别的回固定的 422 `redirect_uri must be the web front end's own address.`，不回显；回调在 code 交给 Google 之前就拒绝。没有登录配置时，login-url 的 503 先于这个检查。token 模式不查（Streamlit 自己发）。
8. **前端登录**（`web/src/api/login.ts`、`web/src/layout/useSession.ts`）：
   - 先看 `/config` 的 `login_available`，false 就禁用按钮、说「暂时不能登录」。
   - 点按钮：32 字节随机 state（base64url，43 个字符）和「回来以后去哪」放进 sessionStorage（本站唯一往 storage 里放的东西，用一次就删；存不进去就说「这个浏览器不让本页暂存登录信息」，也不发请求），`GET /auth/login-url?state=&redirect_uri=` 拿地址，整页跳过去。地址只认 Google 的登录页（`https://accounts.google.com`，不带账号密码）；页面连的是本机的 http API 时，也认那个 API 自己的页面（开发 API 的假 Google）。拿地址失败就删掉存的 state。
   - 回到站点根路径：先 `navigate('/', {replace})` 把 code 和 state 从地址栏和历史里去掉（两步都是 replace，后退回不到带 code 的地址），这时 `/config` 和 `/auth/me` 都还不问；再取出存的 state（取出即删，要是 43 位 base64url）核对：没存、不一致、code 是空的，都不发请求，说「登录没有完成，请重新登录」（R2a「已知」里只能靠前端挡的那种登录劫持）。对上了才用 cookie 模式提交回调，带上同一个 `redirect_uri`。Google 自己的错误（如 `access_denied`）也要 state 对上，并且是小写名字才说出来；state 对不上的 `error=` 链接一样说「请重新登录」，不显示链接里的字。
   - 回调成功：先换成新身份，再重读一次 `/auth/me`（方案 3.1），只有它能说明浏览器收下了 cookie。读到游客就说「登录状态没有保存下来（可能是浏览器不让本站使用 cookie），请再登录一次。」：多半是浏览器拦了 cookie（比如隐私设置，或者跨站的 beta），也可能是 API 不认它刚发的令牌（比如服务器的时钟往回跳了）。重读失败就保留回调给的身份，并把它放回缓存；不然失败的那次会显示成「暂时无法确认」，还会自己再发一次。回来的路上不问 `/auth/me`，旧 cookie 的那次 401 也就不会晚于新 cookie 到达、把它删掉。登出时仍先取消还在路上的 `/auth/me`，晚到的回答改不回已登录。登录、登出都清掉按身份取的查询（键以 `['viewer']` 开头），登出另清课程对比。
   - 失败分开说：外校邮箱「只能用 husky.neu.edu 或 northeastern.edu 邮箱登录」，邮箱没验证单说一句，暂时的失败用第 4 条的话，其余「登录没有完成，请再试一次」。登出失败（断网、503）说「没能退出登录，请再试一次」，不假装已经登出：cookie 是 HttpOnly 的，只有 API 能结束会话。
   - 回来的路径只认本站的路径：不以 `/` 开头的、解析出别的来源的，或者结果以 `//` 开头的（`/.//evil.test` 解析后就是 `//evil.test`），都换成 `/`。
9. **侧栏**（`Sidebar.tsx`、`TopBar.tsx`、`AppShell.tsx`）：账号框只负责显示：确认中、游客（可登录／去 Google 的路上／暂时不能登录／暂时无法确认）、已登录（名字，没有名字时显示邮箱，贡献数，登出）。手机菜单用同一个。「游客」标签只给游客。
   - **焦点**（浏览器验收时发现）：用键盘登出时，按钮先被禁用、再被登录按钮换掉，焦点掉到页面最前面。现在按下的按钮忙完以后，焦点如果落在页面或菜单本身，就放回账号框现在的按钮上，和显示结果在同一次渲染里（`useLayoutEffect`，结果上屏时焦点已经在按钮上）；用户自己移到别处的不动；只有被按的那个账号框（桌面侧栏或手机菜单）会动。
   - **后退**：从 Google 页按「后退」，浏览器可能原样恢复本页，按钮停在「正在前往 Google…」。现在听 `pageshow`（`persisted`）清掉这个状态。
10. **开发用的 API**（`tests/support/dev_api.py`，`python -m tests.support.dev_api`）：真的 `create_app()`，临时文件里的合成数据库（`db/init.sql` 加 `tests/conftest.py` 的三门课），测试套件的替身模型。Google 换成本机的假登录页 `/__dev/google`：三个合成账号，三种被拒，一个 state 不对、一个取消的链接；只认前端自己的地址，转义它回显的东西，不缓存；没见过的 code 照 Google 拒绝换 code 那样回。除了没有默认值的 Gemini key，每个设置都先恢复成代码里的默认值，`.env` 和环境变量里的限流、数据路径之类改不了它的行为；装上 API 自己的日志设置（生产在启动时装，这里不跑启动），uvicorn 的访问日志去掉登录地址的查询串、课程只记路径模板；假登录页那条也带着 state，由它自己的过滤器去掉查询串（生产里没有这一页，生产代码不管它）。每次启动换一个会话密钥，重启以后旧 cookie 就失效。不部署，部署的包（从 `pyproject.toml` 读 wheel 的包清单）不 import `tests`（测试钉住），API 里也没有测试模式。前端和它都在 127.0.0.1，两个前端的端口和 `vite.config.ts` 的开发服务器、预览一致（测试读那个文件去对），它自己也只监听 127.0.0.1。

**第三步：聊天流**

11. **`streamChat`**（`web/src/api/chatStream.ts`，异步生成器，R3 的搜索和聊天页用）：`client.ts` 以外唯一调 fetch 的文件，两边共用请求选项、请求头和错误转换（`FETCH_OPTIONS`、`requestHeaders`、`plainName`、`failureFrom`）。
    - 请求和别的写请求一样；流开始前的失败（422、404、409、429、503，连不上，超时）是同样的 `ApiError`，4xx、5xx 各按自己的状态，读它们的正文也最多等 30 秒；别的 2xx、重定向、没有正文的 200，都不是这个接口的流（502 `invalid_response`）。
    - 按行切 NDJSON：一行被切在两块里、一个汉字的字节被切开、最后一行没有换行、CRLF 和空行都对。第一件必须是 meta（`matched_via` 是字符串、`results` 是数组；其余由 R3 的页面检查），meta 只有一次；token 的 `text` 是字符串；error 要有小写的 `error_type` 和非空的 `detail`；done 的反馈凭证原样交给页面，由页面照 Streamlit 的做法和显示的回答核对。遇到 error 或 done 就结束。
    - error 的 `detail` 是 API 给学生看的固定中文（约定里写明给界面接在半截回答后面），照样显示；这和 HTTP 错误的 `detail` 不同。
    - 等回答开始、等下一块各最多 30 秒（照 Streamlit 的读超时）；读完一块就停表，页面处理事件时不计。断线或 30 秒没动静：在已经收到的内容后面补一个 error 事件「连接中断。仅保留部分回答，未完整结束；请稍后手动重试。」（Streamlit 的英文开头换成了中文）；没有 done 或 error 就结束、有一行不是这四种事件、或者一行（包括还没收完的一行）不算行尾的 `\r` 长过 100 万个字符（API 最长的 meta 也就几十 KB）：Streamlit 的「回答流未完整结束；仅保留部分内容，请稍后手动重试。」。不带换行的一块不再把整个缓冲重新切一遍，长行不会越收越慢。**和 Streamlit 不同**：它跳过读不懂的行，这里当作流坏了（照方案）。
    - 不自动重发：每问一次都算模型的每日次数、写 query_log。调用方取消时停止读取，抛出它的原因；页面不再读（`break`）或者流结束时，剩下的请求放掉。
12. **开发 API 的聊天**：`/chat` 按脚本回答（七块，每块之间停 50 毫秒），从不调用 Gemini；会调用它的 HyDE 补救也关掉，每日上限只在问题里点名时才有。问题里带 `dev:model-error`、`dev:no-answer`、`dev:daily-limit`、`dev:no-done`、`dev:cut`、`dev:stall`，分别是模型中途出错、没有回答、今天的次数用完、流没有 done 就正常结束、连接中途断开（中间件不再发送也不结束响应，uvicorn 断开连接）、停 35 秒（比前端等的 30 秒久）。

**其他**

13. **测试的约定**：渲染整个 App 的测试套 `web/src/test/withApi.tsx` 的 `WithApi`，预先放好 `/config` 和游客身份，测试里不发请求（四个页面测试文件改了）。`contracts.test.ts`：只有 `client.ts` 和 `chatStream.ts` 能用 fetch，提到就算、不只是调用（别名 `const send = globalThis.fetch`、`globalThis['fetch']`、`window.navigator.sendBeacon`、XMLHttpRequest、WebSocket、EventSource 都查）；TanStack 只许 `@tanstack/react-query`，不许 devtools 和别的 HTTP 客户端（axios、ky、got、superagent、ofetch、wretch、node-fetch、cross-fetch、undici、socket.io 等）；两个包的依赖都要精确版本；`index.html` 设了 Referrer-Policy `strict-origin-when-cross-origin`（R0 14.15，发给别的站点的只有本站来源；R7 在服务器上再设一次）。
    - 项目自己的 `npm run test:mutations` 的副本原来只拷 `src/` 和五个配置文件，这一批的测试要读 `index.html`、`openapi.json` 和生成器的 `package.json`，基线一跑就失败（B26 M4）；现在一起拷，基线的时限放宽到 120 秒。
14. **CI**（`.github/workflows/ci.yml`）：前端 job 装生成器、查 `schema.ts` 和 `openapi.json` 一致；Python job 跑 `scripts/export_openapi.py --check`。
15. `api/models.py` 里 `login_available` 的注释改成三样都要（client ID、client secret、`SESSION_SECRET`），R2a 第 24 轮以后漏改的。`tests/test_public_routes.py` 里 R2a 留下的一处 `zip()` 补上 `strict=True`（Ruff B905）。
16. **合进 main 的 R3a（#30）：**
    - R3a 的 `web/src/api/requisites.ts` 保留手写。面板要的是按 kind、status 分开的窄类型，生成的类型只有一个扁平的形状，换过去会丢掉这层收窄。文件顶上加了一句说明。
    - 新文件 `web/src/api/requisites.types.test.ts` 只在类型检查时起作用，对照生成的类型查三样：
      - 面板读的字段 API 都有；
      - API 可能给的标量值面板都收，成绩、种类、状态这些固定取值也算在内，null 不算；值是对象的字段各有自己的那条去查，只有方案节点的 `areas` 没有，单独对一次（复核第 2 轮补的）；
      - 课程详情里放先修列表和旧边的两个字段，类型对得上。
    - API 删了或改名了面板读的字段，或者给出面板不收的值，`npm run typecheck` 就失败。
    - R3a 的演示页测试包上 `WithApi`。README 里两节都留，R3a 一节在前。
17. **合进 main 的 R3b（#31）：**
    - R3b 的课程详情类型（`web/src/api/course.ts` 的 `CourseDetailBody`、`CatalogSnapshot`、`AnswerEvidence`、`EvidenceSnippet`）也留手写。R3b 原来在 R5b 手写的 `CourseDetail` 上 `extends`；这一批把 `CourseDetail` 换成了生成的类型，有默认值的字段都成了可选，自动合并以后 R3b 的页面和检查有 13 处编译不过。现在 `CourseDetailBody` 自己把字段写全，形状和 R3b 原来得到的一样，R3b 的代码一行没改。
    - 新文件 `web/src/api/course.types.test.ts` 照第 16 条的办法对照生成的类型：课程详情本身，加上成绩构成、方案关系、AI 政策、证据片段、来源说明、目录快照各一条（值是对象的字段要各自对照）。两份对照共用的类型挪到 `web/src/test/misfits.ts`。
    - R3b 的演示页测试包上 `WithApi`。README 里 R3b 一节放在 R2b 一节前面；`test:mutations` 那一条两边合在一起（152 个；副本照 R2b 多拷几个文件，基线等 120 秒）。

### 修改文件

- 后端：改 `api/exceptions.py`、`api/google_oauth.py`、`api/models.py`（注释）、`api/routes/auth.py`；新建 `scripts/export_openapi.py`、`tests/support/dev_api.py`。
- 前端：新建 `web/src/api/` 下的 `apiBase.ts`、`client.ts`、`queries.ts`、`login.ts`、`chatStream.ts`、`types.ts`、`env.d.ts`，生成的 `schema.ts` 和 `web/openapi.json`，`web/src/layout/useSession.ts`、`web/src/test/withApi.tsx`，生成器 `web/tools/openapi-types/`；改 `web/src/api/coop.ts`、`course.ts`、`privacy.ts`，`layout/AppShell.tsx`、`Sidebar.tsx`、`TopBar.tsx`，`main.tsx`，`web/index.html`（第二个提交），`vite.config.ts`、`package.json`、`package-lock.json`、`eslint.config.js`、`.prettierignore`，`web/scripts/mutations.mjs`（第二个提交）。
- CI：`.github/workflows/ci.yml`。根目录 `.gitignore`（第二个提交）。
- 文档：`docs/api_contract.md`（回调的 `reason` 和 `redirect_uri`、login-url 的 `redirect_uri`，`/chat` 的 done 凭证和流开始前的错误，后两样是原来就落后于代码的），`web/README.md`（R2b 一节，和几句已经不对的话），本节。
- 测试：新建 `tests/test_export_openapi.py`、`tests/test_dev_api.py`；改 `tests/test_api_auth_route.py`、`test_api_errors.py`、`test_public_routes.py`、`test_session_cookie.py`。前端新建 `apiBase.test.ts`、`client.test.ts`、`queries.test.tsx`、`schema.test.ts`、`login.test.ts`、`chatStream.test.ts`、`layout/session.test.tsx`；改 `layout/navigation.test.tsx`、`test/contracts.test.ts`、`test/setup.ts` 和四个页面测试文件。
- 合并 main 时：新建 `web/src/api/requisites.types.test.ts`；改 R3a 的 `web/src/api/requisites.ts`（只加注释）、`web/src/pages/RequisitesDemoPage.test.tsx`（包 `WithApi`），`web/README.md`（两边的改动都留）。
- 复核第 1 轮的修复（第四个提交）：
  - 前端改 `web/src/layout/useSession.ts`、`web/src/api/login.ts`、`chatStream.ts`，`web/package.json`、`scripts/check-bundle.mjs`、`eslint.config.js`、`.gitignore`、`.prettierignore`；
  - 前端测试改 `layout/session.test.tsx`、`api/login.test.ts`、`chatStream.test.ts`、`test/contracts.test.ts`；
  - 后端改 `tests/support/dev_api.py`、`tests/test_dev_api.py`；
  - 文档改 `web/README.md` 和本节。
- 复核第 2 轮以后（第五个提交）：前端测试改 `web/src/api/requisites.types.test.ts`，文档改本节。
- 合并 main（R3b）时：改 `web/src/api/course.ts`（R3b 的类型写全）、`web/src/api/requisites.types.test.ts`（共用的类型挪走）、`web/src/pages/CourseDetailDemoPage.test.tsx`（包 `WithApi`）、`web/README.md`；新建 `web/src/api/course.types.test.ts`、`web/src/test/misfits.ts`；文档改本节。

数据库结构、检索、提示词和 Streamlit 版都没改。

### 验证记录

- **浏览器验收**（内置浏览器，开发用的 API 加 `npm run dev`，都在 127.0.0.1）：
  - 登录：点按钮到假 Google 页，选账号回来已登录；刷新以后 `/auth/me` 还是 200，也就是 **Chromium 在 http://127.0.0.1 上收下了 `__Host-` 开头、带 Secure 的 cookie**（第一步时还没验证的一点）。登出 204，刷新以后 401。
  - 失败：state 不对（不发回调）、外校域名、没验证、Google 拒绝、取消，各一次，中文都对，地址栏都干净，存的 state 都删了。
  - 从 `/privacy?tab=export#export` 登录回到原地址；没有名字的账号显示邮箱；登出把课程对比从 4 门清到 0。
  - 390 宽的手机菜单登录、登出；键盘：焦点框看得见，登出以后焦点在登录按钮上（修第 9 条以前掉到页面最前面）。
  - 聊天流：在页面里直接 `import` 开发服务器提供的 `chatStream.ts`，用真的 fetch 问：每 50 毫秒到一块；六种脚本、空问题（422）、取消都对；`dev:stall` 在最后一块之后 30.0 秒给出「连接中断」；登录以后带着 cookie 也过跨站检查。正常结束的请求在 DevTools 里显示「已中止」：读到 done 就把剩下的放掉（Streamlit 的 httpx 也这样关），服务器那时已经发完。
  - 「后退」的修复在这里复现不了：开发服务器和按本机 API 构建的正式预览都试过，这个浏览器面板的后退都是重新加载（页面上做的记号没了），不会原样恢复页面。只有单测。
- **前端检查：** check（类型、零警告 lint、Vitest、构建）全过，**433 项**（25 个测试文件）；首屏 JavaScript gzip **158,231 字节**（预算 250,000；聊天流还没有页面用到）；格式、生成的类型都一致。
- **后端：** Ruff F／E9／B 在 12 个改过和新建的 Python 文件上通过（第一次报了 R2a 留下的那处 B905）；改动和新建的文件里没有 CR。
- **变异：** 都在副本里跑，被杀的都看了是对口的测试。
  - 第一步：前端 83 个杀 82 个，存活的 C14（`Retry-After` 不去空白）：fetch 的 Headers 本来就去掉首尾空白，只有直接调用才看得出，补了一例以后杀掉；Python 7／7。
  - 第二步：前端 98 个（新写 69 个，另 29 个是第一步里函数改过的，改锚重跑），全部杀掉。中间存活过三个：S04（「Google 跳回只处理一次」的标记去掉）——测试到了原页面就判过了，补了「停一会儿还在原页、没有失败提示」；L06、L07（回来的路径去掉 `//`、`/\` 的字符串检查）——第 8 条对解析结果的检查已经挡住这两种，这两条多余，删了。Python 24 个杀 23 个，存活的 X04（401 的 `detail` 改用 `str(exc)`）不是等价的：`id_token_invalid` 带诊断时会把异常类型名带出去，测试补了这种情况以后杀掉。
  - 第三步：前端 K01–K34 34／34；第一步里跟着代码挪了位置的 C01–C06、C22、R01、R02 加一个新的 C06b，10／10。K23（预先取消时不早退）第一遍是靠测试超时失败的，改了测试以后由断言直接杀掉。Python H01–H14（开发 API 的聊天脚本）连同补了测试的 X04，15／15。
  - 合计：前端 187 个（第一步 83、第二步新写 69、第三步新写 35；代码改动波及的旧变异体都改锚重跑了），Python 45 个；最后都被对口的测试杀掉。中途存活的 5 个（C14、S04、L06、L07、X04）按上面说的补了测试或删了多余的代码。
- **串行全量：** **5206 passed／7 warnings／515.02 秒**，退出码 0。比 R2a 第二个提交时的 5160 多 46 项，就是这次新加的测试。全量开始以后只加了本节。
- **第二个提交（第 25 轮审查的修复）：**
  - 前端：check 全过，**454 项**（25 个测试文件）；首屏 JavaScript gzip **158,411 字节**；格式、生成的类型都一致。正式构建配本机的 http API 会停下来，报「A production build needs an https API…」；`build:dev-api` 照常构建。
  - 后端：Ruff 在改过的 5 个 Python 文件上通过；改动的 30 个文件里没有 CR；改过的 3 个测试文件，加上跟着 `auth.py` 一起跑的 `test_api_auth_route.py`，共 163 项都过。
  - 开发 API 在 8000 上短跑一次：访问日志只记了 `/auth/login-url`（不带查询参数）和 `/course/{course_id}`，state 和课程 ID 都不在日志里；停下以后端口空出来。那次只请求了登录地址和课程；假登录页那一条当时还带着 state，复核第 1 轮才找到。
  - 变异（都在副本里；判法改成读 Vitest 的 JSON 报告，只撞上超时的不算杀）：前端新写 50 个（W 组 31 个，W25 这个编号空着；V 组 19 个，由 B26 存活的变异移植过来，它的 B03 随回环判断一起删掉了），10 个旧变异跟着代码改锚，连同函数改过的旧变异一共 184 个，**183 个由断言杀掉**，C26、C28、C32、Q10 也在内。剩下的 W03（去掉 `refetchOnReconnect: false`）是等价的：探针去掉这一行以后，`networkMode: 'always'` 下网络恢复时也不重取。Python 新写 P01–P12，连同代码改过、要重跑的 A01–A09、D01–D09 和 H01、H02、H14，33／33，都由对口的测试杀掉。项目自己的 `npm run test:mutations` 基线通过，110／110。
  - **串行全量：** **5213 passed／7 warnings／545.56 秒**，退出码 0；比第一个提交多 7 项，就是这次新加的 7 个测试。
- **合并 main（R3a）以后：**
  - 合并只有 `web/README.md` 冲突；R3a 的 19 项演示页测试没包 `WithApi`，报「No QueryClient set」，包上以后都过。
  - check 全过，**662 项**（32 个测试文件，多出来的是 R3a 的和这次的类型检查）；首屏 JavaScript gzip **173,177 字节**（R3a 的演示页连同 16 份假数据是静态 import 的，都算在首屏里；预算 250,000）；格式、生成的类型都一致。
  - 类型检查的检查也试了：在 R3a 的类型上做四处改动，分别是去掉成绩 `S`、文档的 `catalog_year` 改名、列表的 `unusable_records` 改成字符串、方案去掉 `bridge`。每一处都让 `tsc` 在对应的那条检查上失败。把 `minimum` 放宽成 `string | number` 作对照，照样通过。改完文件都原样还原。
- **第四个提交（复核第 1 轮的修复）：**
  - 前端：check 全过，**667 项**（32 个测试文件）；首屏 JavaScript gzip **173,198 字节**；格式、生成的类型都一致。`build:dev-api` 输出到 `dist-dev-api/`，体积检查读的也是这个目录，`dist-dev-api/` 被 git 忽略。
  - 后端：Ruff 在改过的 2 个 Python 文件上通过；改动的 16 个文件里没有 CR；`test_dev_api.py` 24 项都过。
  - 变异（都由对口的测试杀掉）：
    - 前端：去掉放回缓存那一行，新加的 3 条正好失败；`build:dev-api`、体积检查、`preview:dev-api` 三处改回 `dist/`，3/3；
    - 前端：行长上限的三处边界、`useLayoutEffect` 改回 `useEffect`、`notKept` 改措辞，5/5，连跑三遍都一样；
    - Python：D01–D09、P01–P14 23/23（新加的 P13、P14 是假登录页那条日志），P15（复位挪回 import 之后）也杀掉。
  - **串行全量：** **5214 passed／7 warnings／532.39 秒**，退出码 0；比第二个提交多 1 项，就是另开进程查复位的那条。
- **第二个提交在真浏览器里重验**（另开的会话做的，这个会话里的浏览器面板用不了；`3ebc04d` 的副本，开发 API 和合成数据，1440×900 和 390×844）：
  - 从 `/privacy?tab=export#export` 登录，回来还在原地址，查询串和 `#` 都在；地址栏和历史里都没有 code 和 state，`sessionStorage` 用完就空。
  - 请求顺序（浏览器的网络记录和开发 API 的访问日志对得上）：回来以后先回调，再 `/auth/me`，然后才 `/config`，回调之前这两个都不问。
  - 刷新还是登录状态；登出 204，刷新以后 401。
  - state 不对、取消、不带 state 的 `error=` 链接，三种都不发回调；state 对不上时链接里的字不上页面。外校、没验证、Google 拒绝三种被拒也对。
  - 手机菜单里登录、用键盘登出，焦点落在菜单里的登录按钮上。
  - `<meta name="referrer">` 是 `strict-origin-when-cross-origin`；`build:dev-api` 的正式预览里每个请求只发一次，顺序一样。
  - 之后的提交改过的几处（重读失败时放回身份、没保存住登录的那句话、`build:dev-api` 的输出目录）没有再在浏览器里看，由前端测试钉住。
- **第五个提交（复核第 2 轮的 NIT）：** 只多了一条类型检查。把生成的 `areas` 改成数字数组、把面板的 `areas` 收窄成两种前缀，`tsc` 都在这条上失败；把面板的放宽作对照，照样通过。check 全过，667 项（32 个测试文件），首屏 JavaScript gzip 173,198 字节；格式、生成的类型都一致。
- **合并 main（R3b）以后：**
  - 只有 `web/README.md` 冲突，`course.ts`、`mutations.mjs` 自动合并。自动合并的结果 `tsc` 报 13 处错（第 17 条），R3b 演示页的 18 项测试报「No QueryClient set」；改完都过。
  - check 全过，**909 项**（39 个测试文件）；首屏 JavaScript gzip **181,908 字节**（R3b 的演示页连同假数据也是静态 import 的；预算 250,000）；格式、生成的类型都一致。
  - 新对照的检查：在 R3b 的类型上做 8 处改动（快照 ID 改名、交付方式去掉 `async`、置信度改成字符串、成绩权重改成字符串、方案关系的字段改名、AI 政策的布尔改成字符串、来源说明的警告改成数字、抓取时间改成数字），再把生成的交付方式多加一个取值，`tsc` 都在新文件上失败；把证据原文放宽成 `string | number` 作对照，照样通过。第 16 条的 R3a 对照（四处改动加 `areas` 两处，各带对照）重跑，结果不变。
  - 项目自己的 `npm run test:mutations`：基线通过，**152／152** 都由对口的测试杀掉，R3b 的 M131–M152 也在内。

### 审查

第 25 轮，两路只读审查，在第一个提交 `6d054f5` 上做，都不派子 agent：A26 看安全和正确性，B26 看测试、变异和文档。中途按用户的意思暂停过一次，两路都把进度写进各自的 `PROGRESS.md`，续审从原处接着做。

- **A26：** 没有 CRITICAL、HIGH、MEDIUM；4 LOW、11 NIT，没有能直接利用的漏洞。核过、没问题的：前端的 state 检查和 cookie 模式要的 Origin 加标记挡住了登录劫持；`safeReturnPath` 35 种写法、两端 `redirect_uri` 各 26 种都跳不到别处；游客、已登录、坏 cookie 三种情况下的 cookie、CORS 和跨站检查；登出失败不假装；流里 error 的 `detail` 可以显示；开发 API 不会被部署，也碰不到真的 Gemini 和 Google。
- **B26：** 4 MEDIUM、9 LOW、6 NIT。本节的数字都核对上了（433 项、158,231 字节、5160→5206、变异 187 和 45）。用更严的判法重跑前端 187 个变异：183 个由断言杀掉，4 个（C26、C28、C32、Q10）只是撞上 Vitest 的 5 秒超时，所以原来那句「最后都被对口的测试杀掉」不准；Python 45 个都由对口的测试杀掉。它自己写的变异：前端 19 个存活 18 个、Python 6 个存活 5 个（各有一个对照组被杀）。

修复在第二个提交里，正文各条已经改成修完的样子：

1. **登录回来（A26 L1、N1）：** 回来的路上不问 `/config` 和 `/auth/me`；回调成功以后重读 `/auth/me`，浏览器没收下 cookie 就说出来（第 8 条）。`index.html` 设 Referrer-Policy（第 13 条）。
2. **断网（A26 L2）：** `networkMode: 'always'`，网络恢复也不重取（第 5 条）。
3. **构建用的 API（A26 L3，B26 L3、L4）：** `chooseApiBase`：正式构建只认 https，`build:dev-api` 连本机，别的模式要写明，测试不受环境影响；`.gitignore` 加 `.env.*`（第 3 条）。
4. **几处收紧（A26 N2、N3、N4、N6、N7、N11）：** `error=` 链接要 state 对上才说出 Google 的错误码；存的 state 要是 43 位 base64url；聊天流一行最多 100 万个字符，不带换行的一块不再重切整个缓冲；cookie 模式的回调只认请求自己的 `Origin` 加 `/`；`apiPath` 拒绝空值、`.`、`..`；登录地址只认 Google 的登录页，连本机 API 时才认它自己的页面。
5. **开发 API（A26 N5，B26 L8）：** 设置从代码里的默认值开始，装上 API 自己的日志设置（第 10 条）；短跑一次，访问日志里没有 state，也没有课程 ID。测试钉住它只监听 127.0.0.1、两个前端的端口和 `vite.config.ts` 一致、没见过的 code 怎么拒、`main()` 用的主机和端口。
6. **测试缺口（B26 M1、M2、L1、L6、L7、L8、L9、N1、N5、N6）：**
   - code 和 state 不留在历史里：用 BrowserRouter 测 `history.length` 不变（后退回不到带 code 的地址），同时记下每个请求发出时地址栏的样子；
   - 手机菜单里的账号框：显示和桌面一样；在菜单里登出以后，焦点落在菜单里的登录按钮上；
   - C26、C28、C32、Q10 的测试改成断言请求已经结束，由断言杀掉；变异判法改成读 Vitest 的 JSON 报告，只撞上超时的不算杀掉；
   - 聊天流：两句原话写死比对，错误正文最多等 30 秒，第一行是 error 当作坏流；
   - 登录：取消时 state 也用掉，存的回来路径再过一遍检查，state 来自 `crypto.getRandomValues`，回来时清掉上一个人的按身份数据，回来的路径保留 `#`；
   - Python：login-url 的 2048 上限（先于 503 查）；部署包清单改从 `pyproject.toml` 读（原来手写的漏了 `scrapers`）；重启以后旧 cookie 是 401；
   - 网络约定改成「提到就算」，补上 HTTP 客户端的清单；schema 的第一项也给 60 秒；几个测试名改成和断言一致。
7. **两条焦点测试不稳（B26 M3）：** 根子是焦点放回去在 passive effect 里，提示先上了屏；改成 `useLayoutEffect`，和结果同一次渲染（第 9 条），测试也就稳了。
8. **`test:mutations` 坏了（B26 M4）：** 副本补上测试要读的文件，基线时限 120 秒（第 13 条）。
9. **文档（A26 N9，B26 L5、N2、N3）：** README 的 CI 一句、安装和检查两节、「登录时也清课程对比」；`api_contract.md` 的 SAFE-02 提到 `reason`；本节 `dev:stall` 的「30.1 秒」改回工作记录里的 30.0 秒，「200 以外的回答都是 502」改准。

没改、记进「已知」的：A26 L4（没有 PKCE）、N8（登出不清问题和方案）、N10（回来的路径带查询串和 `#`），B26 N4（两处固定等 20 毫秒）。

**复核第 1 轮**（只看 `6d054f5..3ebc04d`，两路还是 A26、B26，续用原来的上下文；中途按用户的意思停过一晚）：

- **A26：** 0/0/0/0，NIT 5 条。原来 15 条里 11 条确认修好；N5 修了一半（就是下面第 4 条）；L4、N8、N10 的「已知」写得准。它用探针核过：回调没有 Origin 时先 403，不会变成 500；真实构建配本机 http 停下，`--mode staging` 不写地址也停下。
- **B26：** 0/0/0，LOW 2 条、NIT 4 条。上一轮的 19 条都修好了，M3、M4、L3 也自己确认过：M3 在负载下跑 60 次都没失败，`test:mutations` 110/110，设了 `VITE_API_BASE_URL` 也全过。它用自己的判法重跑了前端 86 个、Python 33 个变异，结果和本节一样；W03 等价是对的。

修复分两处：两处措辞在合并提交里，其余在第四个提交里。正文各条已经改成修完的样子。

1. **重读 `/auth/me` 失败（A26 N-A）：** 原来失败的那次留在缓存里，404 时侧栏显示「暂时无法确认」，开门以后 `/auth/me` 还会自己再发一次。现在把回调给的身份放回缓存（第 8 条）；测试换成 503、404、断网三种，各查只发了一次 `/auth/me`、缓存里是成功的那份。
2. **没保存住登录的提示（A26 N-B，B26 N4）：** 重读读到游客也可能是 API 不认刚发的令牌（比如时钟往回跳），原来那句只怪浏览器，改成「登录状态没有保存下来（可能是浏览器不让本站使用 cookie），请再登录一次。」。登录、登出的八句话加了一条写死原文的测试。
3. **连本机 API 的构建（A26 N-C）：** 原来和正式构建都写 `dist/`，手边的 `dist/` 可能是连本机的那份。现在输出到 `dist-dev-api/`，用 `preview:dev-api` 预览，`check-bundle.mjs` 收目录参数；contracts 测试钉住这几个脚本，三个忽略清单也加上了（第 3 条）。
4. **开发 API 的日志（A26 新的一条）：** 假登录页那一行带着 state，生产的过滤器不管这一页。开发 API 自己加一个过滤器，测试也查这一行（第 10 条）。
5. **开发 API 有一个设置没复位（B26 LOW 1）：** `api/routes/common.py` 在第一次 import 时就拷走了 `rerank_pool_size`，复位在那之后，所以环境里的 `RERANK_POOL_SIZE` 还管用。现在复位挪到 import 路由之前；新测试另开一个进程、设好这个变量再起，查三处拷贝都是默认值。
6. **焦点的修法没钉住（B26 LOW 2）：** 两条失败路径的焦点测试加一个断言：提示第一次出现在页面上的那一刻，焦点就已经回到按钮上（MutationObserver 记下那一刻）。改回 `useEffect` 现在每次都失败。
7. **行长上限两处量法不一样（B26 NIT 3，也是 A26 的 CRLF 边界）：** 收完的一行先去空白再量，没收完的不去，`\r\n` 正好切在两块之间时结果会变。现在两处都量「去掉行尾的 `\r`」以后的长度；加了测试：恰好上限的一行带 `\r\n`，切不切开都读得出来；没收完的一行恰好上限时等它收完，多一个字符就结束（第 11 条）。
8. **文档（B26 NIT 1、2）：** 第二个提交的新变异是 50 个，不是 51 个；跑的测试是改过的 3 个文件加 `test_api_auth_route.py`。这两处在合并提交里改了。

**复核第 2 轮**（最后一轮，看 `67f9fdd..56ce5e1`，B26 另看合并提交里给 R3a 加的东西；中途撞过一次额度上限，接着做完）：

- **A26：** 0/0/0/0/0，上一轮的 5 条都修对了。点名要它查的四处都没找到问题：重读失败时把身份放回缓存，中间不会有别的回答插进来（回来的路上 `useMe`、`useConfig` 都关着，忙的时候不收登出，同一个查询的请求会合并成一个）；行长的量法怎么切开都一样；开发 API 复位以前，没有别的模块在 import 时读设置（另开进程、设了三个变量去试）；假登录页的过滤器不碰别的行。
- **B26：** 0/0/0/0，NIT 1：先修类型的对照漏了方案节点的 `areas`（`Misfits` 不比值是对象的字段），API 把它的值改成数字，类型检查照样通过。上一轮的 4 条它都用变异和对照复现过，本节的数字和日志都对得上。这条只要补一条类型检查，第五个提交补了（第 16 条），没有再开一轮。

### 已知、未处理

- **R7 上线前：** Google OAuth 客户端要把新前端的地址（来源加 `/`）加进 Authorized redirect URI，API 的 `WEB_ORIGINS` 也要设成它（第 33 节已记），不然 Google 或 API 会拒绝。
- **`/chat` 的 409：** 选方案没选成、专业前缀对应多个项目、选的项目和问题里的前缀不一致，这三种 `detail` 都是给学生看的中文，Streamlit 原样显示。新前端不显示 `detail`，R3 要按情况自己说，或者后端给 409 加一个稳定的原因。
- **会话在页面开着时过期：** `useMe` 不自己过期，侧栏会一直显示已登录。R5d 的按身份请求收到 401 时要把身份改回游客。
- **「后退」以后的一种情况：** 登录成功以后连按两次后退回到 Google 的页面，Google 要是直接再跳回来，存的 state 已经用掉，会说「登录没有完成，请重新登录」，可人其实还登录着。没处理。
- 坏行的处理和 Streamlit 不同（见第 11 条）。生成的 `ChatRequest` 把有默认值的 `k`、`allow_feedback_capture` 也当作必填，调用方要明确给出（是否允许保存回答本来就该由页面明确给）。
- openapi-typescript 支持 TypeScript 6 以后，生成器可以并回主包。
- 隐私、Co-op、对比三页还用自己的演示身份，侧栏登录了它们也不知道；R5d 接上。
- **没有 PKCE（A26 L4，原有设计）：** code 不绑浏览器。state 对不上时 code 不会被兑换，但会留在浏览器的全局历史里，有效期内能用到这台电脑的人可以拿它走 token 模式换令牌。R7 前后考虑：`code_verifier` 和 state 一起放进 sessionStorage，兑换时由 API 交给 Google。
- **登出清得不全（A26 N8）：** 问题、项目和方案（PrototypeContext）和 MutationCache 登出时都不清；Streamlit 会清对话、项目和方案。R2b 里还是演示数据，R3／R4 要留一个统一的「重置会话」钩子。
- **回来的路径带查询串和 `#`（A26 N10）：** 现在只有演示参数；R3 以后要是把学生自己写的东西放进网址，就只存路径（R0 14.6）。
- 两条测试在固定等 20 毫秒以后做否定断言（B26 N4）：负载很大时可能漏掉变异体，不会误报。
- 变异 W03（去掉 `refetchOnReconnect: false`）是等价的：`networkMode: 'always'` 下 TanStack 默认就不在网络恢复时重取（本节验证记录里有探针）。这一行留着，以后要是有人把 `networkMode` 改回去，它还能兜底。
- **浏览器里重验的是第二个提交 `3ebc04d`**（见验证记录）；之后改的几处只有前端测试。
- **合并 R3b 的改动（第 17 条）在复核第 2 轮之后，没有再审：** 两轮复核的上限已经用完。它只动类型和测试，由上面的类型变异、全部前端测试和项目自己的变异核过。
- **账号的提示放在页面最底下（浏览器重验时发现，MINOR）：** 登录、登出的提示写在外壳 `<main>` 后面那个 `role="status"` 里（R1 原型的提示区）。长页面上第一屏看不见；手机菜单开着时，它在 Radix 给菜单外面加的 `aria-hidden` 里，所以在菜单里登出失败什么提示都看不到，像是按了没反应（焦点回到「退出登录」是对的）。R3 接线时外壳的这个提示区要改（原型的 PrototypeContext 会去掉），到时候把账号的话放进账号框里（桌面侧栏和手机菜单各显示自己的），回来时的结果放在页面顶上。
- **取消登录的说法：** 显示「登录没有完成（access_denied），请再试一次。」，照 Streamlit 把 Google 的错误码放进括号，字面上没有「取消」。要改成「你取消了登录」这类说法的话，Streamlit 和新前端一起改。
- 正式构建写明 `https://localhost:8443` 这样的地址也能过（A26 记下的，不算问题）：本机 http 拦住了，https 的本机地址只能是有意写的。

### 发布状态

分支 `feat/web-api-client`，基底是合并 R2a（#29）以后的 main `2aa2327`。第一个提交是 R2b 本身，第二个提交是第 25 轮审查的修复。R3a（#30）10-23 已经合并（main `7363572`），第三个提交把 main 合了进来（见第 16 条），第四个提交是复核第 1 轮的修复，第五个提交是复核第 2 轮（最后一轮）的那条 NIT 和本节。R3b（#31）10-24 已经合并（main `fe9203f`），第六个提交把 main 合了进来，给 R3b 的类型加了对照（第 17 条）。没有使用真实模型、账号、NAS 或生产库；登录和聊天都对着本机的开发 API 和合成数据。上线要另外授权。

## 35 — Co-op、课程对比、数据与隐私三页接上真实接口（R5d，2026-10-24）

### 范围与原因

用户 10-23 定了（R2b 方案第 6 节第 3 条）：已经做好的隐私和删号、Co-op、对比三页另开一小批 R5d 接真实接口，R2b 合并以后马上做。R2b（#32）和 R3c（#33）10-24 合并以后，从 main `4797a32` 开 `feat/web-pages-api`，方案 `R5D_PLAN.md`。三页本身是 R5a、R5b、R5c 照假数据写好的，这一批把它们接到 R2b 的接口层和登录身份上；三个演示外壳挪到新地址，内容不变。搜索、课程详情、培养方案还是假数据（R3、R4）。

线上不变：新前端还没部署。后端只改了开发用的 API（第 13 条），生产代码和 Streamlit 版都没动。

### 已实现

**外壳**

1. **页面拿到「现在是谁」**（新文件 `web/src/layout/account.ts`；`useSession.ts`、`AppShell.tsx`）：`AppShell` 用一个 context（`AccountContext`）包住 `<Outlet>`，把 `useSession` 给的 `account` 交给页面，页面用 `useAccount()` 读，拿不到就直接报错。方案写的是 `<Outlet context>`，效果一样。
   - `viewer`：`shownData(me)`，还在确认时是 undefined；从 Google 回来、地址里还带着 code 时也当作不知道，页面这时不发按身份的请求。
   - `unsure`：`/auth/me` 暂时失败、手里也没有上次的身份（侧栏那句「暂时无法确认登录状态」）。
   - `login()`：侧栏的同一个登录。
   - `signedOut()`：删号成功或删号 401 以后用。和登出一样丢掉按身份的缓存、清空对比、身份换成游客（R2b 登出里的这几步提成了 `forget()`，两处共用），但不调 `/auth/logout`：账号没了，API 已经让 cookie 过期。
   - `contributed(count)`：投稿的 201 带着服务端的贡献数（R0 第 8 节：以服务端为准，不从 201 推断加一）。数没变什么都不做；变了就当作换了访客，按身份的缓存整组丢掉，侧栏和 Co-op 的等级跟着变。
   - `viewerScope`：查询键里说明是谁在问的那一段：`guest`、`member:{user_id}:{贡献数}`、`unsure`，还不知道时是 null，查询就等着。`viewerOwner`：不带等级的「这一页是给谁的」，`guest` 或 `member:{user_id}`。
   - **写操作前再问一次是谁**（`queries.ts` 的 `signedInNow`，审查 A27 L4）：cookie 是所有标签页共用的，一个标签页只在登录、登出和整页刷新时问是谁，别的标签页可能早已登出，或者换了一个人登录。所以投稿和删号发出去之前先问一次 `/auth/me`（最多等 8 秒，不进缓存），结果分三种：还是这一页显示的那个会员（`same`）；明确是别人，或者没人登录（`other`）；8 秒内没有能读的回答（`unknown`）。投稿只在 `other` 时不发，表单照「登录已经失效」说，草稿留着；`unknown` 时照发，后面有审核，重复提交 API 也认得出来。删号只在 `same` 时发：`other` 当作 401（「这个登录已经失效」，登出）；`unknown` 也不发，当作「什么也没删」（复核第 1 轮 A27 N2：删号不可撤销，问不到时宁可让人再点一次）。`/auth/me` 的请求提成了 `whoIsAsking`，`meQuery` 也用它。
2. **刷新按钮**（`queries.ts` 的 `refreshReads`，`Sidebar.tsx`）：照 Streamlit 的 `🔄 刷新页面内容`，所有查询都过期，正在显示的马上重取。`/auth/me` 照 Streamlit 不重读（身份只在登录、登出、投稿和整页刷新时变），只有它失败过时才重读，不然「暂时无法确认」没有办法再试。按钮的字从「刷新课程数据」改成「刷新页面内容」；原来点了只显示「R1 使用固定假数据；未发送刷新请求。」。
3. **「显示的是上次的版本」**（`queries.ts` 的 `useShowingOld`，`AppShell.tsx`）：有正在显示的查询停在「这次失败了，失败是暂时的，手里还有上次的内容」时，`<main>` 最上面一个一直在的 `role="status"`（`aria-label="内容更新"`）里说「有些内容这次没能更新，显示的是上次加载的版本；可以点「刷新页面内容」再试。」。Streamlit 原文后半句是「稍后再操作页面时会再试」，新前端不会自己重试，所以改了。放在 `<main>` 里而不是侧栏，手机上也看得见；R3、R4 的页面接上以后一样适用。不在屏幕上的查询不算；外壳一直在用的 `/config` 算，所以 API 连不上时点刷新，这句在哪一页都会出现，也就告诉了学生这次刷新没成。缓存的事件可能在别的组件渲染中途来，所以照 TanStack 自己的 `useIsFetching`，经 `notifyManager.batchCalls` 再交给 React。
4. **侧栏和顶栏**：页脚那句「页面内容仍是假数据原型；登录已接真实接口」改成「登录、Co-op、课程对比、数据与隐私已接真实接口；搜索、课程详情和培养方案还是假数据原型」。顶栏的游客标记原来就不出现在 `/coop`、`/privacy`（页面自己说是游客），现在两个演示地址也一样；隐私演示页的标题也带锁。
5. **路由**（`App.tsx`、`routePresentation.ts`）：`/coop`、`/compare`、`/privacy` 换成 `CoopRoute`、`CompareRoute`、`PrivacyRoute`；演示外壳挪到 `/coop-demo`、`/compare-demo`、`/privacy-demo`（标题「Co-op 演示」「课程对比演示」「数据与隐私演示」），不进导航。**和方案不同**：方案写演示外壳改成懒加载，「像 `/requisites-demo` 那几个」，可是 `/requisites-demo`、`/course-detail-demo` 其实是直接加载的（只有 `/search-demo` 是懒加载），这次也照直接加载，演示的测试不用改成等页面加载出来；首屏因此没有变小（见验证记录）。

**Co-op**

6. **列表**（`api/coop.ts`）：`coopListQuery(scope)`，键 `['viewer', 身份, 'coop']`（R2b 的 `VIEWER_KEY`，登录、登出时整组丢掉；R0 第 14 节第 9 条：键里有用户和贡献数），`GET /coop` 用 `slow`（30 秒）。Streamlit 的 Co-op 页每次画都取，所以 `staleTime: 0`：每次进这一页都重取，中间先显示缓存里的。`parseCoopList` 要求是数组，每一行照 `CoopRecord` 查：字段和类型；`industry` 是六个代码之一或 null（生成的类型里要是多了代码，得先加进 `INDUSTRIES` 才编译得过）；`visibility_level` 是 0–2；`duration_months` 是 1–8 的整数或 null；`related_courses` 是字符串数组；可以不给的文字字段读成 null；只留这些键。有一行不对就整份当作读不懂（502 `invalid_response`，和 R2b 的 `parseIdentity` 一样，不显示半份）。
7. **投稿**（`uploadCoop`、`parseUploadResponse`）：`POST /coop`，`slow`，不自动重试（超时的投稿可能已经存下了，再发一次 API 会答「重复」）。201 照 `CoopUploadResponse` 查（状态是四种之一，等级是 0–2，贡献数是精确表示范围内的非负整数；A27 N6 以后，`/auth/me` 的贡献数和删号的七个计数也照这样查）。
8. **投稿失败的形状**（`SubmitOutcome`、`submitFailure`，`models/coop.ts`，`CoopForm.tsx`）：R5a 的失败原来带 API 的错误体（`body.detail`），R2b 定了页面不拿 `detail`，所以改成 R2b `ApiError` 的三样：`status`、`errorType`、`invalidFields`。不是 `ApiError` 的异常当作连不上（503 `transport_error`）。
   - 422 标出的字段来自 `invalidFields`（R2b 已经从 `detail` 里取出了字段名），`errorFields` 只认表单自己的字段。原来只能标出 `detail` 开头的那一个，现在认得的都标。
   - 「投稿暂时提交不了，请稍后再试。你填的内容还在。」原来看有没有错误体，现在看 `errorType`：没有回答（连不上、超时）、不是 API 的回答（代理的页面，`errorType` 是 null）、读不懂（`invalid_response`）和 503 说这句；别的失败照旧「提交没有成功，请稍后再试。」。
   - 演示外壳的失败结果改成用 R2b 的 `failureFrom` 从 R5a 的假数据读（和真页面读回答的办法一样），页面上的字一个没改。
9. **`CoopRoute`**（新文件 `web/src/pages/CoopRoute.tsx`）：还不知道是谁时只显示「正在加载」（`aria-label="Co-op 加载"`），不发请求；`/auth/me` 暂时失败时照 `unsure` 去问（API 只看 cookie），页面按游客画。**页面按游客画的时候（游客或 `unsure`），列表只留游客看得到的**（`coopListQuery` 按查询键里的身份，不是会员就把面试、技术题、薪资清掉，`asGuest`；A27 L3 和复核第 1 轮 L1）：cookie 是所有标签页共用的，可能是会员的，API 就会给出这些，不清掉的话页面一边说「你现在是游客」，一边显示薪资，游客的缓存里也会存着会员那一级的内容。列表：能显示的（`shownData`）就显示；失败了、也没在重取才是失败；其余是加载，重试的路上显示加载，不显示失败。投稿前先 `signedInNow`（第 1 条），`other` 就不发，表单说「登录已经失效，请重新登录后再提交。」、草稿留着；投稿成功以后先 `contributed(contribution_count)`，再把结果交给表单。
   - **两层 key**：`CoopPage` 里面原来按「游客／会员几级」给 key，等级一变草稿和结果都清掉；现在里面只分游客和会员，外面 `CoopRoute` 按登录的人（`viewerOwner`）给 key。换了一个人，页面从头开始（R5a 说明书要求的按真实会话的人隔开）；同一个人投稿以后等级变高，投稿结果那句还在。

**对比**

10. **对比列表**（`models/compareList.ts`）：改成 `createCompareList()` 工厂。页面那一份的导出名字不变（`addToCompare`、`removeFromCompare`、`clearCompare`、`getCompareList`、`useCompareList`），R3 的详情按钮照旧接它；`/compare-demo` 用自己的一份（`fixtures/compareDemo.ts` 的 `demoList`），演示不再改学生真正的对比列表，侧栏的数字也不跟着演示变（演示页上加了一句说明）。
11. **`CompareRoute`**（新文件）：列表里前 4 个 ID 各一个 `courseQuery`（`api/course.ts`：键 `['course', course_id]`，`GET /course/{course_id}`，`slow`，回答原样交给 R5b 自己的检查），`staleTime: 0`（Streamlit 每轮都取）。`compareColumn`：能显示的（`shownData`）是 `ready`；失败了、也没在重取是 `error`，`httpStatus` 是状态码，连不上和超时是 null（`client.ts` 新加的 `answerStatus`）；其余是 `loading`。「重新加载」只重取失败的列，R5b 认不出的回答（`resolveColumn` 判成失败的）也算。课程详情对谁都一样，键里不带身份。
    - 往列表里加课的按钮在课程详情上，R3 接（R5b 说明书第 8 节），所以在那之前真实的对比页一直是空的那句话。

**隐私**

12. **`PrivacyRoute`**（新文件；`api/privacy.ts`）：`privacyQuery`，`['privacy']`，`GET /privacy`，`read`（8 秒），和别的公开内容一样 5 分钟内不重取；回答原样交给 R5c 的 `privacyContent` 检查。删号 `deleteAccount()`：`POST /auth/delete-account`，请求体正好是 `{"confirm": "delete"}`，`write`（15 秒），不重试。200 照 `DeleteAccountResponse` 查（`deleted` 是 true，七个计数都是非负整数，只留这些键）；读不懂的 200 也是 API 回的，账号很可能已经没了，所以和没收到回答一样当作不知道（502）。失败给页面 `{ok: false, status}`，连不上、超时是 null（R5c 第 3 节）。删号前先 `signedInNow`（第 1 条），不是 `same` 就不发：`other` 当作 401，`unknown` 当作 409，R5c 把它说成「删除没有完成，什么也没删」。
    - **登出由路由来做**（A27 M1）：200 或 401 以后，账号（或者这个登录）就没了，不管页面还在不在。R5c 的页面在它或删除表单卸载以后不再处理回来的结果（R5c 说明书第 4 节），原来登出只挂在页面的 `onSignedOut` 上，删号路上离开这一页，回答到了也不登出，前端还按原来的人显示、按身份的缓存和对比都留着。现在 `PrivacyRoute` 自己在 200 或 401 以后调 `signedOut()`，放在下一轮事件里，页面还在时先由页面写出结果；页面的 `onSignedOut` 就不用再做什么。
    - 页面不按访客给 key：变成游客以后删除结果还留着（R5c 第 4 条）。游客看不到删除那一节；身份还在确认时先当游客画。

**开发用的 API**

13. **Co-op 的合成数据**（`tests/support/dev_api.py` 的 `COOP`、`PEER`、`seed_coop`）：浏览器验收要看得到三种等级和锁住的字段，原来的合成库里没有 Co-op 记录，假 Google 的账号也都没有贡献。现在有七条，最新的在前（时间固定、相隔一天，每次启动顺序一样）：三条策展种子，0、1、2 级各一；两组投稿，每组公司、职位、学期相同，各有两个不同的投稿人（k=2）。公司、职位和文字都是编的。
    - 假 Google 页多了 `dev-one`、`dev-two` 两个账号。它们的贡献不是写进去的：账号照登录那样建（`upsert_login`），投稿照 API 那样提交（`CoopSubmissionRepository.submit`），再照审核员那样逐条通过（`review`，审核说明写明是合成的、没有要脱敏的），每组第二条通过时整组公开、两个投稿人各记一次功。结果 `dev-one` 1 次、`dev-two` 2 次；第二组的另一个投稿人（`dev-sub-peer`）不在登录页上。
    - 删号在临时库上照真的走：删掉 `dev-two`，它公开的两条跟着删，它参与公开的两组都只剩一个投稿人，别人的那两条撤回 approved（第 32 节的 k=2 撤回），列表只剩三条种子；`dev-one` 的记功不收回。重启就都回来了（每次启动是新的临时库）。

**测试**

14. **测试工具**：`web/src/test/fakeApi.tsx`：`fakeApi(answer)` 按方法和路径回答、记下每个请求（`calls`、`count`；每个请求连查询串一起记，`asked` 把它写成「方法 路径?查询」，列请求顺序的测试都用它，多出查询串就对不上；请求体是 JSON 就解析，别的原样留着，B27 L6）；`json`、`apiError`（API 自己的错误体）、`held()`（回答由测试稍后给）、`livePage(path, client)`（整个 App，`/config` 和身份预先放好）。`web/src/test/timeouts.ts` 的 `expectTimeout`：一个请求在它那一档超时前 1 毫秒还在等，到点放弃（假计时器）。
15. **新测试**：`api/coop.test.ts`、`privacy.test.ts`、`course.test.ts`，`layout/account.test.ts`、`shell.test.tsx`（回退提示在 `<main>` 最前面、原文写死、外壳的 `/config` 也算，手机菜单的刷新，刷新只重取屏幕上的，B27 L2、L3），`pages/CoopRoute.test.tsx`、`CompareRoute.test.tsx`、`PrivacyRoute.test.tsx`；`queries.test.tsx`（刷新、回退提示）、`session.test.tsx`（`account` 的五条）、`client.test.ts`（`answerStatus`）、`compareList.test.tsx`（两份列表互不影响）各加了几条。`tests/test_dev_api.py` 加了 Co-op 的四条（一条分三种账号跑），共 6 项。
16. **改过的旧测试**（B27 L7 以后照实补全）：
    - 三个演示外壳的测试改地址，Co-op 演示的标题改成「Co-op 演示」。
    - `CompareDemoPage.test.tsx`：断言从 `getCompareList()` 换成演示自己的 `demoList`；「回到清空的演示不会复活示例课」原来是点侧栏回到 `/compare`，现在 `/compare` 是真实页，改成卸载再挂载演示页；**删掉了一条**「外部像登出那样清空，演示也跟着空」：演示有了自己的列表，登出只清学生的列表，这条不再成立，换成新的一条「演示用自己的列表，学生的列表和侧栏数字不动」。
    - `CoopPage.spec.test.tsx`：失败结果照新的形状给（`failureFrom` 从 R5a 的假数据读，另加代理页面、读不懂的 201 两种）；**去掉了「never shows raw detail」那几句断言**：detail 现在到不了页面（类型里没有它，`submitFailure` 的测试用 `toEqual` 钉住只有三样），换成 422 只标被拒的字段、两个字段都标、`__proto__` 和 `constructor` 不标、只有 422 才标。
    - `CoopDemoPage.test.tsx`：演示结果的契约从「有没有错误体」改成查 `errorType` 和 `invalidFields`。
    - `pages.test.tsx`：对比的几条改到 `/compare-demo`；「侧栏数字跟着列表」「换页后移出的还在」两条挪到 `CompareRoute.test.tsx` 用真列表测；`/coop`、`/privacy` 现在会发请求，用假的 fetch 回答，检查前等页面加载完；无障碍的检查把真实页和演示页都算上，外壳的检查（标题、导航当前项）另加三个演示地址；「加号只记一次演示动作」那条找提示的办法改了（页面上多了一个 `role="status"`，回退提示那个）。
    - `session.test.tsx` 那条「state 不对什么都不发」回到的页面从 `/coop` 改成 `/compare`：接线以后 `/coop` 会自己取列表。
    - `test_dev_api.py` 里假登录页那条按账号数算链接的位置，不再写死第 6、7 个。
17. **项目的变异脚本**（`web/scripts/mutations.mjs`）：M35（`CoopPage` 的 key 改了）、M54（422 标字段改用 `invalidFields`）、M55（原来测「不显示 detail」，现在 detail 根本到不了页面，改成测「不是 API 的回答当作没提交成」）、M79（测试改了名）重新对上锚点和测试名，总数还是 152。

### 修改文件

- 前端新建：`web/src/layout/account.ts`，`web/src/pages/CoopRoute.tsx`、`CompareRoute.tsx`、`PrivacyRoute.tsx`，`web/src/test/fakeApi.tsx`、`timeouts.ts`。
- 前端改：`web/src/App.tsx`；`api/client.ts`、`coop.ts`、`course.ts`、`privacy.ts`、`queries.ts`；`components/CoopForm.tsx`；`fixtures/compareDemo.ts`、`coopDemo.ts`；`layout/AppShell.tsx`、`AppShell.module.css`、`Sidebar.tsx`、`TopBar.tsx`、`routePresentation.ts`、`useSession.ts`；`models/compareList.ts`、`coop.ts`；`pages/CompareDemoPage.tsx`、`CoopPage.tsx`；`web/scripts/mutations.mjs`。
- 前端测试新建：`api/coop.test.ts`、`course.test.ts`、`privacy.test.ts`，`layout/account.test.ts`，`pages/CoopRoute.test.tsx`、`CompareRoute.test.tsx`、`PrivacyRoute.test.tsx`；改：`api/client.test.ts`、`queries.test.tsx`，`layout/session.test.tsx`，`models/compareList.test.tsx`，`pages/CompareDemoPage.test.tsx`、`CoopDemoPage.test.tsx`、`CoopPage.spec.test.tsx`、`PrivacyDemoPage.test.tsx`、`pages.test.tsx`。
- 后端（只有开发用的 API）：改 `tests/support/dev_api.py`、`tests/test_dev_api.py`。
- 文档：`web/README.md`（R5d 一节、路由表、几句已经不对的话、R5a 到 R5c 三节里的演示地址），本节。
- 第二个提交（第 26 轮的修复）：前端改 `web/src/api/queries.ts`、`coop.ts`、`privacy.ts`，`web/src/pages/CoopRoute.tsx`、`PrivacyRoute.tsx`；测试新建 `web/src/layout/shell.test.tsx`，改 `api/coop.test.ts`、`course.test.ts`、`privacy.test.ts`、`queries.test.tsx`，`pages/CoopRoute.test.tsx`、`CompareRoute.test.tsx`、`PrivacyRoute.test.tsx`、`pages.test.tsx`，`test/fakeApi.tsx`、`timeouts.ts`；文档改 `web/README.md` 和本节。
- 第三个提交（复核第 1 轮的修复）：前端改 `web/src/api/queries.ts`、`coop.ts`，`web/src/pages/CoopRoute.tsx`、`PrivacyRoute.tsx`；测试改 `api/coop.test.ts`、`queries.test.tsx`，`pages/CompareRoute.test.tsx`、`CoopRoute.test.tsx`、`PrivacyRoute.test.tsx`；文档改 `web/README.md` 和本节。
- 第四个提交（复核第 2 轮）：测试改 `web/src/pages/CoopRoute.test.tsx`（加一条），文档改本节。

数据库结构、API、检索、提示词和 Streamlit 版都没改。

### 验证记录

- **前端检查**：类型、零警告 lint、构建、格式、生成的类型都过；Vitest **53 个文件 1508 项**全过（开工前 46 个文件 1348 项）；首屏 JavaScript gzip **185,792 字节**（开工前 182,933；预算 250,000）。构建的「有块超过 500 kB」提示开工前就有。
- **后端**：`tests/test_dev_api.py` 30 项都过；Ruff F／E9／B 在改过的 2 个 Python 文件上通过；改动和新建的文件里没有 CR。**串行全量 5220 passed／7 warnings／563.12 秒**，退出码 0，比 R2b 最后一次的 5214 多 6 项，就是这次新加的 6 项。全量开始以后只改了 `web/README.md` 和本节。
- **变异**（都在副本里跑。前端读 Vitest 的 JSON 报告：R5d 的测试文件里有具名测试因断言失败才算杀掉，只撞上超时、整个文件起不来的不算；第一个提交时日志只记第一条失败的测试，B27 记下每个变异的全部失败重跑，被杀的都有对口的测试，之后脚本也记全部失败。Python 看 pytest 的 FAILED）：
  - 前端我自己的 100 个（外壳、三页的接线、Co-op 的检查和投稿、对比列表、演示外壳）：第一遍 91 个由断言杀掉，9 个存活，没有超时或出错。
    - 5 个是测试缺口，补了测试以后都由对口的测试杀掉。R02、M02、Y03（三页的「重取中算加载」去掉「没在重取」）：TanStack v5 对从没成功过的查询重取时，把状态退回 pending、清掉错误，原来那几条「重试路上显示加载」都是第一次就失败，看不出差别；只有先成功过、后来明确失败（404）、再重试时，状态才停在 error，三页各补了这一条。Y04（隐私页不用 `shownData`）：补了「先成功，刷新后 503 留着旧文字并提示，再刷新 404 就不留」（Co-op 和对比原来就有这条）。Q02（回退提示把不在屏幕上的查询也算进去）：原来那条测试卸下页面时，查询已经不是「暂时失败、手里有旧内容」了；改成停在这个状态时卸下页面，再看提示。
    - 4 个是等价的，见「已知」。
  - Python D01–D08（开发 API 的 Co-op 数据：不审核、种子不当种子、顺序反了、贡献数手写、第二组的投稿人换成 `dev-one`、种子都当 0 级、整个不建、第二组只审一半），8／8。
  - 项目自己的 `npm run test:mutations`：第三遍基线通过，**152／152** 都由对口的测试杀掉，工作源文件没变（`sourceUnchanged: true`）。前两遍不作数：第一遍中途我补了测试，记成 `sourceUnchanged: false`；第二遍基线没过，因为我补的一条测试有类型错误（展开写法造的会员 TypeScript 没认成 `Member`；之前只用 Vitest 跑过它，没跑 tsc），改了以后重跑。补完上面 5 条测试、写完开发 API 以后又跑了第四遍，结果一样：基线通过，152／152，源文件没变。
- **浏览器验收**（另一个会话，内置浏览器，第一个提交 `81f2c84` 的副本，开发 API 加开发服务器和 `build:dev-api` 的正式预览，1440×900 和 390×844）：**清单 11 项都过**：
  - Co-op：游客看到七条、顺序对，锁住的提示在该在的行上；`dev-one` 看得到面试和技术题、薪资还锁着；`dev-two` 全都看得到。投稿一次 `POST /coop`、带 `X-NEU-Compass`，贡献数没变、列表不重取；同样的内容再投一次，说「重复提交」。换人时草稿和展开的详情都不留。
  - 刷新按钮重取 `/coop`、`/privacy`，不重读 `/auth/me`；停掉开发 API 再进 Co-op 页，「显示的是上次的版本」出现在 `<main>` 最上面（手机宽度也在第一屏），换到别的页就没了，API 回来、点刷新以后也没了。
  - 对比：在控制台往列表里放三门课（其中一门不存在），三列各取一次，不存在的那列单独失败，「重新加载」只重取它；访问日志里课程只记路径模板。
  - 隐私：删掉 `dev-two`，请求体正好是 `{"confirm":"delete"}`，结果那句留着，本页变成游客、对比清空；之后游客的 Co-op 只剩三条种子，`dev-one` 的贡献还是 1。
  - 正式预览里每个请求只发一次；三个演示外壳照旧、不发 API 请求，`/compare-demo` 不改侧栏的数字；控制台没有报错和 React 警告。
  - **前端开在 5300，不是 5173**：这台机器现在把 TCP 5163–5262 整段留作 Windows 的动态保留端口，5173 谁都绑不上。验收时用一个启动脚本在运行时把 5300 加进开发 API 的前端清单，副本里一个文件都没改；cookie 只看主机不看端口，CORS 和 `redirect_uri` 对 5300 的处理和 5173 一样。这个保留区间也会让这台机器上的 `npm run dev` 起不来（`vite.config.ts` 写死 5173 加 `strictPort`），见「已知」。
  - 第二个提交以后改过的地方（写前确认、路由登出、按游客清字段等）没有再在浏览器里看，由前端测试钉住。
- **第二个提交（第 26 轮的修复）：**
  - 前端：类型、零警告 lint、构建、格式、生成的类型都过；Vitest **54 个文件 1544 项**全过（新加的是 `shell.test.tsx` 和各文件补的测试）；首屏 JavaScript gzip **185,954 字节**（第一个提交 185,792，多的是写前确认和按游客清字段）。格式检查第一次挂了几个改过的测试文件，Prettier 排好以后过，那几个文件只动了排版、重跑也都过。
  - 变异：A27 的修复让 7 个旧变异的锚点失效（C22、C28、P02、P03、R07、Y01、Y02），重写以后连同新加的 C29–C33、P12、W01–W06、R08–R10、Y06–Y10 和函数改过的旧变异，共 41 个：40 个由断言杀掉，Y09 等价（见「已知」）。B27 存活的 10 个（X 组）搬过来，10／10 由新测试杀掉。脚本现在共 130 个。
  - 项目自己的 `npm run test:mutations`（第五遍）：基线通过，**152／152**，源文件没变。
  - 后端没改，Python 的测试和变异不重跑。
- **第三个提交（复核第 1 轮的修复）：**
  - 前端：类型、零警告 lint、构建、格式、生成的类型都过；Vitest **54 个文件 1551 项**全过；首屏 JavaScript gzip **186,015 字节**（多的是三态的写前确认和查询层的按游客清字段）。
  - 变异：受影响的旧变异体改了锚点（W01–W03、Y06、Y08、C17、R07），R08 跟着代码挪走删掉，新加 W07、W08、C34–C36、R11、Y11、Y12 和 X16，连同函数改过的旧变异，跑了 46 个：45 个由断言杀掉（X16 第一遍存活，测试改写以后被杀，见「已知」），Y09 照旧等价。脚本现在共 138 个。
  - 项目自己的 `npm run test:mutations`（第六遍）：基线通过，**152／152**，源文件没变。
  - 后端没改，Python 的测试和变异不重跑。
- **第四个提交（复核第 2 轮补的测试）：** 类型、零警告 lint、构建、格式、生成的类型都过；Vitest **54 个文件 1552 项**全过，首屏不变。R11（`unknown` 也不发投稿）重跑，第一个挂的就是新测试。只加了一条测试，项目的 `test:mutations` 不重跑。

### 审查

第 26 轮，两路只读审查，在第一个提交 `81f2c84` 上做，都不派子 agent：A27 看安全和正确性，B27 看测试、变异和文档。两路都说环境不让它们写报告文件，报告原文由主会话存进评审目录。

- **A27：** 没有 CRITICAL、HIGH；1 MEDIUM、3 LOW、3 NIT。核过、没问题的：查询键里表示身份的那一段不会撞，还不知道是谁、从 Google 回来的路上都不发；登出、删号、贡献数变化都走 `becomes()`，还在路上的 `/coop` 被中止，登出以后才到的投稿 201 不改任何人；两层 key 换人时什么都不留；投稿防连点、不重试、只信检查过的服务端的数，422 只标表单自己的字段；对比的路径逐个编码、只重取失败的列；刷新不重读成功的 `/auth/me`，回退提示只算屏幕上的，没有自己不停重取的循环；三个检查函数对 `__proto__`、多余的键、类型不对、NaN 都稳；开发 API 不会被部署，记功走真代码。
- **B27：** 没有 CRITICAL、HIGH；1 MEDIUM、8 LOW、3 NIT。本节的数字它重跑都对得上。我那 100 个变异它记下全部失败重跑，96 个被杀的都有对口的测试，4 个等价成立。它自己写了 26 个变异，存活 14 个，其中 4 个是等价或防御代码（见「已知」），10 个是测试缺口。

修复在第二个提交里，正文各条已经改成修完的样子：

1. **删号的回答在离开页面以后才到（A27 M1）：** 登出改由路由来做（第 12 条）。
2. **别的标签页换了账号（A27 L4）：** 投稿、删号之前再问一次 `/auth/me`（第 1 条）。
3. **unsure 时卡片照 cookie 显示细节（A27 L3）：** 按游客清掉（第 9 条）。
4. **数的范围放得太宽（A27 N6）：** 上传回答的等级 0–2，贡献数和删号的计数都要在精确表示的范围里（第 7 条）。
5. **投稿 401 不动身份和草稿，没有测试管（B27 M1）：** 补了路由测试：`POST /coop` 回 401，那句话、草稿、侧栏的会员、缓存里的身份都还在，也不调 `/auth/logout`。
6. **几处设计没有测试钉住（B27 L2–L5）：** 回退提示原文写死、在 `<main>` 最前面、外壳的 `/config` 也算；手机菜单的刷新；刷新不重取已经离开的页面（`queries.test.tsx` 里原来那个离屏的查询没有 queryFn，断言测不出什么，换成真的）；身份还没确定时隐私页先当游客画、文字照常显示；三个演示地址的标题和导航当前项。
7. **测试工具（B27 L6）：** 第 14 条：记查询串、`asked`、请求体容错，`held()` 去掉没用到的 `fail`，`timeouts.ts` 补了注释。B27 存活的 10 个变异（X01、X06、X07、X08、X14、X14b、X48、X60、X62、X63）搬进我的变异脚本，都被对口的新测试杀掉。
8. **文档（B27 L7–L9、N10–N12）：** 第 16 条照实补全；变异的判法照脚本实际做的写，脚本也改成记下全部失败；验证记录写明浏览器验收另外做；两个测试名改成和断言一致；两条「原样发出」的测试对请求体改用 `toEqual`；README 两处加了限定；这里几句措辞。A27 的 L2、N5、N7 写进「已知」。

**复核第 1 轮**（只看 `81f2c84..5f040ef`，两路还是 A27、B27，续用原来的上下文；中途按用户的意思停过一次，又因为额度用完停过一次，接着做完）：

- **A27：** 0/0/0，LOW 1、NIT 2。原来 7 条里 M1、L3、L4 的写操作那一半、N6 修好了，L2、N5、N7 进「已知」也合适。它用探针核过：页面先写结果、后登出（页面的后续在微任务里，登出在后面的宏任务里），离开页面以后 200 和 401 都登出；确认还在路上时点退出，投稿不会发出去；清掉的三个字段和 API 的分级一致，`/auth/me` 恢复以后细节回来。
- **B27：** 0/0/0，LOW 1、NIT 3。上一轮 12 条都修好了，本节的数字它重跑都对得上。我那时的 130 个变异它在 `5f040ef` 上记下全部失败重跑：125 个被杀，每个都有对口的测试；存活的是原来的 4 个等价和 Y09。项目的 `test:mutations` 152／152。它的 Z03（先登出、再返回结果）被杀，说明「页面先写结果、再登出」的顺序有测试管，Y09 等价成立。它自己的 32 个变异存活 6 个：上一轮认定的 X03、X16、X25、X25b，和两个缺口 Z11、Z23。

修复在第三个提交里，正文各条已经改成修完的样子：

1. **页面当成游客、cookie 却是会员（A27 L1）：** 上一轮只在 unsure 时清字段，可还有两种情形：别的标签页登录了；删号前发现换了人，本页变成游客、cookie 却还是另一个人的。这时游客的页面会显示薪资，游客的缓存键里还会存着会员那一级的内容。现在清字段挪进了 `coopListQuery`：查询键里的身份不是会员就清，页面和缓存都只有游客看得到的（第 9 条）。
2. **删号前问不到 `/auth/me` 照发（A27 N2）：** 别的标签页换了账号、`/auth/me` 又恰好失败时，删号的 200 会删掉另一个账号，和正常成功一模一样。改成三态的 `signedInNow`，删号只在确认是同一个人时才发，问不到就说「什么也没删」；投稿照发（第 1、12 条）。
3. **读请求那一半（A27 N3）：** 写进「已知」第一条。
4. **同一个人、贡献数变了（B27 L1，它的 Z23）：** 写前确认只比 `user_id` 是对的（审核公开了以前的投稿，数会变大），可是没有测试管：要是有人把贡献数也拿来比，会员投第二篇就会被说成登录失效。补了 `signedInNow` 的一组：同一个人、数变大了，还是 `same`。
5. **游客该看到的还在（B27 N2，它的 Z11）：** 清字段挪进 `coopListQuery` 以后，`coop.test.ts` 按身份逐字段写出期望（行业、时长、相关课程都还在），清多了的变异（C36）由它杀掉。
6. **README 的首屏数字（B27 N3）、X16 的例外（B27 N4）：** 首屏数字按第三个提交改；X16 见「已知」，第一次补的测试用的是从没成功过的列，杀不掉，改成先成功、后来明确失败的列。

**复核第 2 轮**（最后一轮，只看 `5f040ef..63c183e`，还是 A27、B27）：

- **A27：** 0/0/0/0，NIT 1。上一轮的三条都处理好了，修复没有带出新问题。它用探针核过：三态的每一条路（只有页面显示会员时才去问；401 读成没人登录；超时、5xx、429、404、读不懂、断线都是 `unknown`；只比 user_id）；删号遇到 `unknown` 的五种情形都不发，说什么也没删，勾选还在，`/auth/me` 恢复以后再点就正常删掉；`other` 那条先写结果、再登出；按游客清字段在换人、删号前发现是别人、登出时还在路上的列表、unsure 恢复这几种情形下都对，游客能看到的字段都还在。那条 NIT（写前确认到真正发出之间还有一个往返的空档）写进「已知」。
- **B27：** 0/0/0/0，NIT 1。新测试钉住了三态的每一条路、`coopListQuery` 按身份清字段和 X16：受影响的 46 个加上它自己的 8 个，在 `63c183e` 上 53 个被杀，只有 Y09 存活，用全部相关文件再跑一次还是存活，等价成立；X16 的新测试单进程连跑 30 次都过。本节的数和日志、代码对得上。那条 NIT：投稿在 `unknown` 时照发，这条规则没有专门的测试，R11 只是被三条讲别的事、碰巧拿到 `/auth/me` 404 的测试杀掉。第四个提交补了一条：`/auth/me` 回 503，投稿照发，结果照常显示；R11 第一个挂的就是它。

第四个提交只有这条测试和本节，按复核最多两轮的规矩，不再开第三轮。

### 已知、未处理

- **会话在页面开着时过期**（第 34 节「已知」里留给 R5d 的那条）：读请求不会回 401：API 把坏掉或过期的 cookie 当作游客（R2a），`GET /coop` 就回游客的列表。所以 cookie 过期以后，Co-op 页还按会员画（等级、投稿表单），内容却是游客的（细节字段都是空的），侧栏也还显示已登录，直到整页刷新或重新登录。写操作前会再问一次 `/auth/me`（第 1 条）：投稿不发，表单说「登录已经失效，请重新登录后再提交。」并给登录按钮，草稿和身份都不动（照方案，和 Streamlit 一样；要是当场改成游客，按登录的人给 key 的页面会重来，草稿立刻就没了）；删号照旧登出。不过草稿也只是留在页面上、可以先复制下来：点登录是整页去 Google，回来草稿就没了，那句话没有提醒（A27 L2）。要不要在 R5a 的这句里加「先复制」，等用户定。别的标签页换了账号也一样：会员 A 的标签页、cookie 已经是 B 的，Co-op 列表照 B 的等级显示（挂在 A 的键下），只有写操作之前才会再问是谁（复核第 1 轮 A27 N3）。要做得更好，得让 API 在读请求的回答里说明这次是按谁回答的（比如一个响应头），R3 或 R7 再看。
- **写前确认只是把空档缩小了，没有关掉**（复核第 2 轮 A27 NIT）：`/auth/me` 说还是同一个人以后，投稿或删号还要再发一个请求；别的标签页要是恰好在这一来一回之间换了人，写操作照样算到新的人头上。前端堵不上，要 API 让写请求带上预期的 user_id 才行（删号的请求体又必须正好是 `{"confirm": "delete"}`），R3 或 R7 再看。
- **删号的结果在页面离开以后才到**：照样登出（第 12 条），但结果那句不再显示，这是 R5c 有意的；删号路上点「退出登录」也一样。
- **投稿超时，或者 201 读不懂**（A27 N5）：说「投稿暂时提交不了，请稍后再试。你填的内容还在。」，其实可能已经存下了；重交会得到「重复提交」，没有害处。改说法要动 R5a 的文案，留给用户定。
- **R1 的「加入对比」把课号写进控制台**（A27 N7，`SearchPage.tsx`、`CourseDetail.tsx` 的 `console.info`）：现在是假数据的课号，不是这一批加的；R3 把按钮接到 `addToCompare` 时一起删掉（R0 14.1）。
- **演示外壳没改成懒加载**（第 5 条）：首屏比开工前多 2,859 字节，是新的接线代码；三个演示外壳和它们的假数据本来就在首屏里。R3 以后首屏要是紧，演示外壳可以一起改成懒加载。
- **对比页在 R3 之前是空的**：加课的按钮在课程详情上（R5b 说明书第 8 节），R3 接。
- **等价的变异体**：
  - M04（`CompareRoute` 不截前 4 个）：对比列表本身最多存 4 个（满了 `add` 返回 `full`），这一行是多余的防线，留着是为了以后列表放宽时页面仍只取 4 门。
  - Q04（回退提示的订阅不经 `notifyManager.batchCalls`）：测试里看不出差别。它防的是缓存事件在别的组件渲染中途同步通知 React，引出「渲染时更新了另一个组件」的警告；TanStack 自己的 `useIsFetching` 也这样做。
  - D02（只给测试用的复位函数不清演示列表）：每条用演示的测试进页面时都会按场景重新填一遍，所以看不出来。
  - B01（两份对比列表共用一组监听）：一份变了也会通知另一份的订阅者，但那一份的快照没变，`useSyncExternalStore` 不会重画。
  - Y09（删号以后当场登出，不等下一轮事件）：`becomes()` 改缓存之前先 `await` 了一次（取消路上的 `/auth/me`），页面照样先写出结果，所以看不出差别。留着下一轮事件，是为了这个顺序不靠 `becomes()` 里面怎么写。
  - B27 认定的三个：X03（`contributed` 不等它做完）、X25／X25b（缺 `industry`、`duration_months` 的行当作读不懂：OpenAPI 里这两个都是必填，读成 null 是防御）；Python 的 PX2（开发 API 投稿的等级一律给 0：`review()` 会照脱敏后的字段重算）。它原来也算作近似等价的 X16（「重新加载」也重取还在加载的列）其实不等价：一门课先加载成功、后来明确失败、又在重新加载的路上时，TanStack 的 `refetch()` 会取消进行中的请求再发一次，第二次点「重新加载」就会给这一列多发一次（从没成功过的列只会接着用路上那次请求，看不出差别）。补了一条测试走这条路，现在由它杀掉（第一次写的测试用的是从没成功过的列，杀不掉，改过）。
- **三个「再试一次」的按钮按下以后，键盘焦点掉到 `<body>`**（浏览器验收时发现，MINOR）：对比页的「重新加载」、Co-op 列表和隐私说明的「重试」。重取期间按 R5d 的接线显示「加载」，按钮所在的那一块被换掉，再失败时出现的是一个新按钮，焦点不会回去。和 R3c 评价按钮那条是同一类问题；要改的话动的是 R5a–R5c 的页面（比如加载时把焦点放到那句「正在加载」上，或者加载完把焦点放回结果），等用户定。
- **这台机器上 5173 被 Windows 留作动态保留端口**（TCP 5163–5262）：`npm run dev` 起不来，浏览器验收临时开在 5300（见验证记录）。这是本机的系统设置，不是代码的问题，要用户自己调整保留区间。
- **和 R3d 合并**：R5d 和用户的 R3d 都改 `web/src/App.tsx` 和 `web/README.md`；不管哪一个后合并，冲突由写 R5d 的这一边来解。
- 第 34 节「已知」里账号的提示放在页面最底下的那条没动，R3 改外壳时一起改。

### 发布状态

分支 `feat/web-pages-api`，从 main `4797a32`（#33 合并以后）开。第一个提交 `81f2c84` 是 R5d 本身，第二个提交 `5f040ef` 是第 26 轮审查的修复，第三个提交 `63c183e` 是复核第 1 轮的修复，第四个提交是复核第 2 轮补的一条测试和本节的记录。没有使用真实模型、账号、NAS 或生产库；三页都对着本机的开发 API 和合成数据。上线要另外授权。

## 36 — 选课草案的核对搬进 API（R4b 的后端，2026-10-25）

### 范围与原因

10-25 用户同意 R4b 这样分：草案判断的接口由协调方做，培养方案页里的草案界面和离线演示由用户照说明书做（和 R4a 一样）。PLAN 第 2 节第 2 条：判断逻辑只留一份，放进 API，新前端不再写一遍。

Streamlit 版（第 30 节）在 UI 进程里存草案，每加一个课号就串行发 `/resolve/course` 和 `/course/{id}`，核对流程和 `evaluate_draft` 都在页面里跑。这一批加一个只计算、不存储的接口，把同样的核对和计算放到 API 里；Streamlit 版的行为不变。

### 已实现

1. **`POST /programs/{program_id}/plans/{plan_id}/draft`**（`api/plan_draft.py`，路由在 `api/routes/program.py`）。请求体 `{"plan_content_sha256", "course_ids", "input"}`：页面显示的方案版本、草案现在的课（最多 20 个、不重复）、这次要加的文字（最多 4000 字，可以没有）。都是严格类型，多出的字段是 422。
2. **方案要确切：** 新加的 `ProgramPlanRepository.resolve_by_id` 用路径里的两个 ID 找到存的那一行（查库时就按项目过滤，所以别的项目的方案不论那一行坏没坏都算 missing），拿它的范围和请求里的内容版本组成 `PlanSelection`，再交给 F 的 `resolve_selection` 做全部检查，所以过时与否由内容版本决定。不是 `selected` 就回 409，带 SAFE-02 的三个字段、固定的英文 detail 和 `reason`（`missing`、`stale`、`draft`、`unusable`、`unavailable`），和 R2a 登录 401 带 reason 一样；新前端照 `reason` 处理（R4b 说明书：前四种清掉方案选择，`unavailable` 可以重试）。program 不存在照旧 404。路径里的两个 ID 照 `PlanSelection` 的格式查，不合格是 422。
3. **草案以服务器为准：** `course_ids` 每次请求都从课程表重读，课号、课名、学分都按现在的记录。记录没了（`course_gone`）、读不出来（`invalid_record`：「草案里有 1 门课的课程记录无法读取，已从草案移除。」；整批读取失败时逐个再读，只拿掉读不了的那门；逐个读时每个 ID 只认自己名下的记录，记录里写的是别的请求 ID 时不顶替任何一门）、放不进草案（`invalid_record`：「草案里的 {课号} 课程身份或字段无效，已从草案移除。」，比如课名超过 500 字）、两个 ID 现在是同一个课号（`duplicate_code`，留第一个）的，从草案拿掉并各加一条提示。
4. **加课的规则和 Streamlit 一一对应**（`app.plan_draft_view._add`）：一次超过 20 个课号一个都不加、也不核对；格式不对的逐条报最多 10 条，其余报个数；全都已在草案里；加上会超过 20 门就不核对并说要减几门；查不到；对上多门（列出最多 10 个候选，其余报个数）；交叉列出的两个课号只算一次；同一引用还匹配别的课号；输入的课号对应另一个主课号；记录放不进草案。课号走 `resolve_course_ref` 和 `get_batch`，直接查库，没有「连接中断，后面几门没核对」这种情况。Streamlit 在合并时再查一次 20 门上限（它的会话状态可能被别处改），这里每个课号最多加一门、前面已经限住，合并不会超过 20，所以没有那一条。多了一条：匹配到的课的 ID 不合请求里 `course_ids` 的格式就不加（`invalid_record`），页面拿到的草案总能原样发回来（目录里的 ID 都是 `neu-{学科}-{课号}`，碰不到）。这时和 Streamlit 不同：Streamlit 会加上这门课，同一次输入里和它交叉列出的另一个课号在 Streamlit 里算作同一门、不加，在这里会加上。
5. **回答**：`courses`（加完以后的整份草案）、`added`（这次新加的课号）、`notices`（按处理顺序，每条有稳定的 `kind`、`level` 和一句话：按课号的是 Streamlit 页面同一情况的那句话，重读草案的三种是自己的；对上多门时带候选）、`result`（`evaluate_draft` 的结果：树、`unplaced`、`summary_counts`）。回答 `Cache-Control: no-store`。提示里引用的输入是纯文字。回答的每个字段总是带着，OpenAPI 里也都标成必有（`json_schema_serialization_defaults_required`），生成的类型和说明书手写的一致。
6. **读库出错：** 项目和课程读库出错回 503 `The course records cannot be read right now.`（`no-store`；日志 `draft.storage_failed` 只记错误的类型和位置）；方案那一步读库出错照 F 回 409 `unavailable`。路由接的是所有 sqlite3 错误，代码自己的错误（比如 `ProgrammingError`）也答成 503，见「已知」。
7. **`plan_revisions`：** `GET /programs/{id}` 和 `GET /programs/{id}/plans` 的回答顶层加 `{plan_id: plan_content_sha256}`（R4a 说明书第 2 节的建议），回答里列出的每份方案都有（草稿方案也有；带过滤条件时只有过滤后的）。新前端带回去，不用在 TypeScript 里重算 Python 的 JSON 摘要。放在顶层而不放进每份方案，因为 Streamlit 用 `ProgramPlan`（`extra="forbid"`）校验每份方案；Streamlit 读这两个回答用 `.get()`，多一个顶层键不影响它。
8. **隐私：** 不写数据库、不写 query_log、不交给聊天。路由只记个数（`draft.checked`：草案几门、这次加了几门、几条提示）；方案不确定时记 `draft.plan_selection`（结果和 plan_id，和 `/chat` 一样）。请求体里的课号、课程 ID 和输入的文字都不进日志，访问日志里只有 program 和 plan 的路径。草案路由的事件也走 I 批课程读的日志白名单（`api/logging.py`：只留代码定义的字段——计数、方案结果、plan_id、错误类型和位置；方案结果只收六种之一，plan_id 必须和路径里的一样），以后共用的查找代码里加的日志也带不出课号和课程 ID。游客也能用；带会话 cookie 的请求照 R2a 过跨站检查。
9. **`parse_course_codes` 搬到 `schemas/plan_draft.py`：** API 和 Streamlit 读输入用同一个函数；`app/plan_draft_view.py` 从那里导入，原来的名字照样能导入。
10. **新前端的类型：** 重新导出 `web/openapi.json`，`npm run gen:api` 重新生成 `web/src/api/schema.ts`（只多不改；草案回答的字段都是必有）。

### 修改文件

- 新建：`api/plan_draft.py`、`tests/test_api_plan_draft.py`。
- 改：`api/routes/program.py`（新路由、`plan_revisions`）、`api/exceptions.py`（`PlanSelectionConflict` 和它的 409）、`db/program_plan_repository.py`（`resolve_by_id`）、`schemas/plan_draft.py`（`parse_course_codes`，草案模型的 OpenAPI 必有字段）、`api/logging.py`（草案路由走课程读的日志白名单）、`app/plan_draft_view.py`（改成导入）、`web/openapi.json`、`web/src/api/schema.ts`。
- 文档：`docs/api_contract.md`（路由表、鉴权、新接口一节、SAFE-02 的 `reason`）和本节。
- 第二个提交（变异存活的补测）：只改 `tests/test_api_plan_draft.py`。
- 第三个提交 `89f6bce`（第 30 轮审查的修复）：改 `api/plan_draft.py`、`api/routes/program.py`、`api/logging.py`、`db/program_plan_repository.py`、`schemas/plan_draft.py`、`tests/test_api_plan_draft.py`、`web/openapi.json`、`web/src/api/schema.ts`；文档改 `docs/api_contract.md` 和本节。
- 第四个提交 `500a400`（复核第 1 轮的修复）：改 `api/plan_draft.py`、`api/logging.py`、`api/routes/program.py`、`api/exceptions.py`（只改说明）、`tests/test_api_plan_draft.py`、`web/openapi.json`、`web/src/api/schema.ts`；文档改 `docs/api_contract.md` 和本节。
- 第五个提交（复核第 2 轮补的测试）：测试改 `tests/test_api_plan_draft.py`，文档改本节。

数据库结构、检索、提示词和 Streamlit 版的行为都没改。

### 验证记录

- **第一个提交 `ff35231`：**
  - 新测试文件 43 项都过；邻近的测试（草案、培养方案、课号解析、OpenAPI、跨站、错误出口、日志）630 项都过。
  - 串行全量 **5263 passed／7 warnings／526.24 秒**，退出码 0；全量前后 11 个改动文件的哈希一样。
  - Ruff F／E9／B 在改过的 7 个 Python 文件上通过；改动的文件里没有 CR。
  - 前端：类型、零警告 lint、Vitest **64 个文件 2007 项**、构建、格式、`gen:api:check` 都过（前端只有生成的两份类型文件变了）。
- **变异第一轮**（`ff35231`，51 个，16 路并行，每个在自己的 `git archive` 副本里跑，只有具名测试 FAILED 或 ERROR 才算杀掉）：42 个杀，9 个存活，没有可疑的。8 个是测试缺口：D03（正好 20 个课号）、D05（正好 10 个格式错）、D07（没解析出课号时也说「已在草案里」）、D12（两条记录同一个课号时取第一条）、D15／D16／D17（交叉列出的 `twins` 和 `taken` 互相兜底：两门课的记录互相写了对方时，去掉哪一个都看不出来，只有单向写的交叉列出才分得出）、D22（别名对到草案里已有的课，`accepted` 里有重复）。D31 等价，见「已知」。
- **第二个提交 `4186ddb`**（这 8 个缺口的 12 项测试；和 Streamlit 的对照提成 `same_as_streamlit`，表里加了这 8 种输入）：新测试 55 项、邻近 642 项都过，Ruff 过。这 9 个重跑：8 个都由对口的新测试杀掉，D31 照旧存活。
- **第三个提交 `89f6bce`（第 30 轮审查的修复）：**
  - 新测试 69 项、邻近 656 项都过；Ruff 在改过的 8 个 Python 文件上通过；没有 CR，隐形字符只有 `docs/api_contract.md` 开头那个 main 上本来就有的 BOM。
  - 前端：类型、零警告 lint、Vitest 64 个文件 2007 项、构建、格式、`gen:api:check` 都过。
  - 串行全量 **5289 passed／7 warnings／534.06 秒**，退出码 0，比第一个提交多 26 项，就是第二、第三个提交新加的；全量前后 12 个改动文件的哈希一样。全量开始以后只改了本节。
  - 变异（把 worktree 里还没提交的文件叠在 `4186ddb` 的副本上跑）：修复让 5 个旧变异的锚点对不上（R01、R02、P01、P02、D29），重新对上；连同函数改过的 6 个（D23、D24、R03、R04、R05、P03）、新写的 15 个（N01–N15：逐个再读、读不了的那句、ID 守卫、503 和它的日志、草案路径的日志白名单、OpenAPI 的必有字段、「已从草案移除」）和 B30 存活的 14 个缺口，共 40 个，**40／40 杀**。P03 第一次记成 ERROR（「没计算」那条测试的探针用了 `pytest.fail`），改成抛 AssertionError 以后重跑是 FAILED。脚本现在共 80 个。
- **第四个提交 `500a400`（复核第 1 轮的修复）：**
  - 新测试 70 项、邻近 657 项都过；Ruff 在改过的 8 个 Python 文件上通过；没有 CR，隐形字符照旧只有那个 BOM。
  - 前端：类型、零警告 lint、Vitest 64 个文件 2007 项、构建、格式、`gen:api:check` 都过。
  - 串行全量 **5290 passed／7 warnings／526.41 秒**，退出码 0，比第三个提交多 1 项，就是新加的那条；全量前后 12 个改动文件的哈希一样。全量开始以后只改了本节。
  - 变异（照旧叠在副本上跑）：受影响的 N01、N02、N09–N12（N01、N09 重新对了锚点）和新写的 4 个（N16 逐个再读时把取回的整个结果并进去、N17 方案结果收任何标识符、N18 plan_id 不和路径比、N19 plan_id 一律去掉），共 10 个，**10／10 杀**。脚本现在共 84 个。
  - 假数据在 `500a400` 上重新生成：`out` 32 份、`expected` 31 份和 `89f6bce` 那份逐字节一样，只有 `source.sha256` 变了（提交号和三个改过的源文件）。
- **第五个提交（复核第 2 轮补的测试）：** 新测试 76 项、邻近 663 项都过，Ruff 过。B30 存活的 B40、B41、B48 搬进变异脚本，连同改写的那条测试原来管着的 N11、N12、N19，6 个都由对口的测试杀掉，脚本现在共 87 个。只改了测试文件和本节：全量、前端检查和假数据都不用重跑。

### 审查

第 30 轮，两路只读审查，范围 `5c1f1b9..4186ddb`，都不派子 agent：A30 看正确性、隐私、安全和与 Streamlit 是否一致，B30 看测试、变异、文档、说明书和假数据。两路都没有写报告文件，报告原文由主会话存进评审目录（B30 的脚本和日志在同一个目录）。

- **A30：** 没有 CRITICAL、HIGH；1 MEDIUM、3 LOW、5 NIT。核过、没问题的：两边的 `_add` 逐行一致（顺序、各个上限、文字和 level）；随机 1500 例在服务器重读后的草案上和 Streamlit 比，提示和最终草案没有一处不同，每例都不超过 20 门、课号和 ID 都不重复；去掉的「合并后超过 20」那一支确实到不了；方案确认不会串项目、绕不过内容版本，409 的文字和 `reason` 都来自固定的集合；请求体只会 422、不会 500，`evaluate_draft` 在 10 份策展方案上各跑 300 份随机草案从不抛异常；日志只有计数和方案结果，不写库；带 cookie 的 POST 照 R2a 过跨站检查；每次请求最多约 87 次走索引的查询；`plan_revisions` 不影响 Streamlit；生成的类型只加不删；D31 等价。
- **B30：** 没有 CRITICAL、HIGH；2 MEDIUM、9 LOW、8 NIT。核过、没问题的：用 `4186ddb` 重新生成的假数据逐字节一致；5 份方案和 R4a 的一样；55 项新测试在 `5c1f1b9` 上全部失败；`mut2` 的 8 个都由对口的测试杀掉；D31 换一种办法（经真实路由发 28 种原始请求体和 9 个边界请求）也等价；和 Streamlit 的逐行对照是真判据（改坏 Streamlit 一侧的两个变异都被抓到）；标准答案的规则和向量和说明书一致。它自己写了 34 个变异：13 个杀，21 个存活，其中 14 个是测试缺口，7 个等价（见「已知」）。

修复在第三个提交 `89f6bce` 里，正文各条已经改成修完的样子：

1. **草案里有一门课的记录读不出来，整个请求 500，之后每次都 500（A30 M1，B30 L7 的一半）：** `get_batch` 只要有一行校验不过，整批都抛，`_current` 原来没接住，页面每次都发回同一份草案，就一直失败。现在整批失败就逐个再读，只拿掉读不了的那门，加一条「草案里有 1 门课的课程记录无法读取，已从草案移除。」（第 3 条）。测试用两种坏记录：`generated_json` 不是一门课，和多一个字段（相当于旧镜像读到新写的行）。
2. **读库出错回 500，本节原来写的是 503（A30 L1，B30 L7、L9）：** 改成照文档：项目和课程读库出错回 503，方案那一步照旧 409 `unavailable`（第 6 条）。补了课程、别名、项目三处读库出错都回 503、不带输入的测试，和方案读库出错回 409 `unavailable` 的测试。
3. **草案路由不在课程读的日志白名单里（A30 L2）：** 加进去了（第 8 条），补了一条测试：草案路由上嵌套的日志只留白名单里的字段。
4. **别的项目的方案那一行坏了时回 `unusable`（A30 N1）：** `resolve_by_id` 查库时就按项目过滤，后面那个比较到不了，删掉（第 2 条）。
5. **「未加入」（A30 N2，B30 L3）：** 草案里本来就有的课放不进草案时，改成「草案里的 {课号} 课程身份或字段无效，已从草案移除。」（第 3 条）。Streamlit 不重读草案、没有这种情况，所以不受「一字不差」约束；加课时的那句照旧。
6. **服务器给出的草案发回来会 422（A30 N4 的第一种）：** 匹配到的课的 ID 不合 `course_ids` 的格式就不加（第 4 条）。第二种（同一次请求两次读库之间课号变了）进「已知」。
7. **重读草案的课名和学分没有测试钉住（B30 M1）：** 和 Streamlit 的对照、假数据的交叉核对都从 API 的草案出发，从设计上看不到这类错误。补了一条：已知学分的课断言整个 `courses`，两次请求之间改库里的课名和学分，第二次的回答跟着变。
8. **别的测试缺口（B30 L8、L9、N4、N5）：** `plan_revisions` 改成存两份方案和一份草稿方案，两个路由都断言整张表，再加一次带过滤条件的；「也匹配」的 10 个上限和去重；一个课号交叉列出到两门已接受的课；两门课的记录都没了出两行；方案被拒时日志带 plan_id；格式错的输入照原样最多 200 字。测试本身：恒为真的 `assert` 换成严格的整份比较；去掉没必要的替换日志器；「没计算」那条改用探针证明没调 `check_draft`。B30 存活的 14 个缺口都搬进变异脚本，都杀掉了（见验证记录）。
9. **说明书、生成的类型和文档（B30 M2、L1、L2、L4–L7、N1–N3、N6–N8，A30 N3）：**
   - 说明书（仓库外）：409 定了：`stale`、`missing`、`draft`、`unusable` 合成一句、不给重试，真实页面上接线会清掉方案选择、草案块跟着方案块消失，这句只是防万一；`unavailable` 可以重试。数字、章节引用、规则树层数的算法、第三行说明（学分按核对时的课程记录）、不用 `oneLine`、可以改 `.prettierignore`、输入框靠 `key` 清空、要能折行的清单都改了。
   - 生成脚本：422 的 `invalidFields` 照客户端算；`source.sha256` 补了 6 个依赖的源文件；标准答案的 `\d` 改成 `[0-9]`、说明里的章节改对。假数据和标准答案用第三个提交重新生成。
   - 回答模型和草案模型在 OpenAPI 里标成必有（第 5 条），生成的类型和说明书的手写类型一致。
   - 路由说明逐个说 409 的 `reason`，模块说明改了；`docs/api_contract.md` 的 SAFE-02 一节加上草案的 409 也带 `reason`。
   - A30 的 L3、N4 的第二种和 N5 进「已知」。

**复核第 1 轮**（只看 `4186ddb..89f6bce`，两路还是 A30、B30，续用原来的上下文；中途按用户的意思停过一次，存下进度以后接着做完）：

- **A30：** 0/0/0/0，NIT 4。上一轮 9 条都照本节处理了。它用探针核过：几门坏记录、全部坏、`generated_json` 是 NULL 都只拿掉读不了的那门，逐个读时遇到库错误回 503；404、409、422 都没变，三处读库出错和缺 `v_course_lookup` 视图都回 503，日志里没有课号；路径写成转义形式也一样走白名单；旧表缺 `program_id` 列时回 409 `unavailable`（以前是 500）；ID 守卫和请求模型的判断一致。上一轮的 21 个探针在新副本上全过，和 Streamlit 的随机对照 1500 例没有一处不同，相邻的 26 个测试文件 662 项全过。
- **B30：** 0/0/0/0，NIT 3。上一轮 19 条都照本节处理了。它在自己的目录用 `89f6bce` 重新生成假数据，逐字节一致，和改前副本的差别正好是说明书开头写的那些；新测试在 `4186ddb` 上正好 9 项失败，都是测这次修复的；它上一轮存活的 14 个缺口都只被对口的新测试杀掉，7 个等价照旧存活；`mut3` 里抽查的 20 个都是对口的测试杀的；本节的数字和日志都对得上。

修复在第四个提交 `500a400` 里，正文各条已经改成修完的样子：

1. **逐个再读时，记录挂到别的 ID 上（A30 NIT 1）：** 记录的 JSON 里写的是另一个请求 ID 时，原来的 `records.update` 让那个 ID 拿到哪条记录取决于请求里的顺序。现在逐个读时每个 ID 只认自己名下的记录（第 3 条），补了一条测试，两种顺序结果一样。不走逐个再读时按 SQL 返回的顺序，是 `get_batch` 原来就有的。
2. **日志白名单的两个方案键（A30 NIT 3）：** `plan_outcome` 只收六种结果，`plan_id` 必须和路径里的一样（第 8 条）；嵌套日志那条测试把课程 ID 那样的值放在这两个键下，都过不去。
3. **503 接得宽（A30 NIT 2）：** 接受，写进「已知」；路由里加了注释，契约写明任何 sqlite3 错误都算。
4. **文字和行为对不上（A30 NIT 4，B30 NIT 1–3）：** `PlanSelectionConflict` 的说明改成前四种清掉方案选择、`unavailable` 保留选择；契约里 503 的日志写成「类型和位置」；路由的 description 和模块说明写明按课号的是 Streamlit 的句子、重读草案的三种是自己的；说明书第 10 节第 3 条（仓库外）也改了。

**复核第 2 轮**（最后一轮，只看 `89f6bce..500a400`，还是 A30、B30）：

- **A30：** 0/0/0/0/0。上一轮的 4 条都处理好了，修复没有带出新问题。它用探针核过：逐个再读时两种顺序结果一样，那条记录自己的 ID 报「找不到了」；`plan_outcome` 只收六种，`plan_id` 是课程 ID、整数、列表、None、大写、带空格或没有这个键时都被去掉、也不报错；`draft.plan_selection` 那一行的结果和方案 ID 都还在，路径写成转义形式也在；能让路由参数和上下文里的路径不一致的字符，进处理函数之前就被拒了；别的路径不受影响。它的 57 个探针 56 个过（剩下那个是它测试替身自己的问题，和上一轮一样），和 Streamlit 的随机对照 1500 例没有一处不同，相邻的 26 个测试文件 663 项全过。
- **B30：** 0/0/0/0，NIT 2。上一轮的 3 条都改好了；新测试在 `89f6bce` 上正好 2 项失败；我的 10 个变异都由对口的测试杀掉；假数据在 `500a400` 上它自己重新生成，逐字节一样；第四个提交的数字和日志对得上。它自己加了 5 个变异，B42、B44 被杀，B40、B41（六种结果里去掉 `missing` 或 `unavailable`）和 B48（路由只接 `DatabaseError`）存活：方案被拒的日志测试只测了 `stale`，「任何 sqlite3 错误都回 503」也没有测试管。

第五个提交补了这两条测试：方案被拒的日志按五种原因各测一次，每种都要带着结果和路径里的方案 ID；课程读库抛 `ProgrammingError` 和 `InterfaceError` 都回 503（`InterfaceError` 不属于 `DatabaseError`，B48 由它杀掉）。第五个提交只有测试和本节，按复核最多两轮的规矩，不再开第三轮。

### 已知、未处理

- Streamlit 版的加课流程和这里各有一份，直到 Streamlit 版退役：两边的句子和顺序由 `test_the_api_says_what_the_streamlit_page_says_and_keeps_the_same_draft` 在同一个库上逐行对照。
- 加课时「记录放不进草案」那句沿用 Streamlit 的「…返回的课程身份或字段无效，未加入。」，在 API 里「返回的」不太贴切；为了两边一字不差，先不改。
- **单向交叉列出的两门课分两次加，会算成两门**（A30 L3）：「交叉列出只算一次」只在同一次输入里成立。只有 A 的记录写了 B 时，先加 B、再发一次请求加 A，草案里两门都在、没有提示，`result` 也按两门算。Streamlit 一样（每次提交核对一次），是原来就有的。要修得用草案里已有的课预填 `twins`，那样就和 Streamlit 不一致了，等 Streamlit 退役再做。
- **同一次请求的两次读库之间课号变了**（A30 N4 的第二种）：`_current` 和 `_add` 各读一次课程表，中间要是有人改了某门课的课号，同一个 course_id 可能以两个课号进草案，页面发回来就是 422（「超出了限制…请清空草案」）。要课程表恰好在一次请求中途被改才会发生（课程表由更新数据的脚本写，API 不写）；要堵的话，`_add` 跳过 course_id 已在草案里的候选。
- **方案每次请求解析两次、内容摘要算三次**（A30 N5）：`resolve_by_id` 的 `_verified` 一次，`resolve_selection` 又一次，`plan_revisions` 还重算 `_verified` 已经比过的摘要。量很小，不改。
- **读库出错的 503 接得宽**（复核第 1 轮 A30 NIT）：路由接的是 `sqlite3.Error`，代码自己的错误（`ProgrammingError`，或者方案那一步漏出来的 `InterfaceError`）也答成 503「暂时读不了」，页面会让人再试一次。这和 F 的方案那一步把所有 `DatabaseError` 都当作 `unavailable` 一样；日志里有错误的类型和位置，查得到。方案那一步的参数都是字符串，碰不到 `InterfaceError`。这个行为由 `test_any_sqlite_error_in_a_course_read_is_a_503_too` 钉住。
- **旧表缺 `document` 或 `content_hash` 列时回 500**（复核第 1 轮 A30 提到，不是新问题）：sqlite 的行对象缺键抛 `IndexError`，`resolve_by_id` 和原来的 `resolve_selection`、`list_for_program` 一样。现在的表结构（v1.5 起）这两列都在。
- **等价的变异体：**
  - D31（请求模型去掉 `strict=True`）：请求体是 JSON，严格和宽松只在 JSON 给不出的值（比如 tuple）上不同。`probe_strict.py` 每个字段用 180 种 JSON 形状的值比两个模型，Python 模式和 JSON 模式都没有差别；B30 又经真实路由发了 28 种原始请求体和 9 个边界请求，两边回答一样。`strict=True` 留着当保险。
  - B30 认定的 7 个：B08（去掉身份核对：API 里候选和匹配来自同一条记录，这段到不了）、B11（空输入也走加课流程：空串解析出来什么都没有）、B19／B20（`selected` 的结果一定带方案）、B27（路由只会传五种原因，守卫本身到不了）、B30／B31（`resolve_selection` 会再做一遍同样的检查）。

### 发布状态

分支 `feat/api-plan-draft`，从 main `5c1f1b9`（#35 合并以后）开。第一个提交 `ff35231` 是 R4b 的 API，第二个提交 `4186ddb` 是第一轮变异存活的 8 个缺口的测试，第三个提交 `89f6bce` 是第 30 轮审查的修复，第四个提交 `500a400` 是复核第 1 轮的修复，第五个提交是复核第 2 轮补的两条测试和本节的记录。没有使用真实模型、账号、NAS 或生产库，测试只用合成课程和仓库里的策展方案。上线要另外授权（和 React 前端一起）。

## 37 — 培养方案页里的选课草案：组件和离线演示（R4b 的前端，2026-10-26）

### 范围与原因

R4b 分两半：草案判断的接口（第 36 节，#36 已合并）和新前端里的草案界面、离线演示。界面这一半原本说好由用户照说明书 `R4B_DRAFT_SPEC.md`（评审目录，连同 `draft_fixtures/` 的假数据和标准答案）来做，10-26 改由协调方照同一份说明书做。和 R4a 一样只用假数据：组件是受控的，真实请求、草案放在内存里、刷新／登出／换账号清空、换方案重新核对、409 清掉方案选择、「课程页／年度先修」换页，都留给 R4 接线（说明书第 14 节）。

分支 `feat/web-plan-draft`，从 main `cbb91f7` 开（说明书写的是 `5c1f1b9`，那时接口还没合并；现在的 main 多了 #36，假数据依赖的 19 个源文件在两个提交上逐字节一样）。只改 `web/` 和本节。

线上不变：新前端还没部署。

### 已实现

1. **R4a 的课程表多一个参数**（第一个提交，单独提交）：`ProgramCurriculum` 的 `draft?: ReactNode`，选中了一份方案时原样放在方案块后面、「以下是旧课程表…」那行前面，也就是 R4a 说明书第 6 节第 9 步留给草案的位置；没选方案、选的方案不在列表里、课程表还在加载或读不出来、没传这个参数时什么都不画，R4a 的演示和 37 个标准答案不变。放在方案块后面而不是里面：方案块按 `plan_id` 重建（R4a 返工时加的 key），放进去的话换方案就会清掉输入框里还没加的字，Streamlit 的输入框不随方案清；接线要按方案重来，可以自己给 key。R3a–R4a 的文件只改了这一处。
2. **回答的类型**（`web/src/api/draft.ts`）：照说明书第 2 节手写。草案接口已经在 main 上，`draft.types.test.ts` 现在就用 `Misfits` 把它们（连同嵌套的课程、提示、候选、规则节点）和生成的 `DraftCheckOut` 等对照，说明书原本把这条留给 R4 接线。
3. **检查回答**（`web/src/models/planDraft.ts` 的 `parseDraftAnswer`）：照说明书第 4 节，参考实现是生成脚本里的 `answer_ok`（它在 19 份回答上和 API 自己的 pydantic 模型结论一样）。内容版本是 64 位小写十六进制；最多 20 门课，课程 ID 1–200 字、课号 `^[A-Z]{2,4} [0-9]{4}[A-Z]?$`（只认 ASCII 数字）、课名 1–500 字、`credits` 这个键必须在、值是 null 或 0–12 的整数（`true` 不算），课号不重复；`added` 不重复、都是草案里的课号；提示的 `kind` 是 14 种之一、`level` 两种、`text` 非空、候选最多 10 个、未展开数是非负整数；规则节点照第 4 节最后一条，根算第 0 层、最深第 20 层，`status` 这个键必须在；`unplaced` 最多 20 个；三个计数是非负整数。字数一律按码点（`Array.from`）。多出来的键不管。过了还要内容版本等于页面显示的那一版。
4. **几个小函数**（同一文件）：`draftTreeLines` 照 Streamlit 的 `_tree_lines` 去掉 emoji（状态、运算的字用 `Map` 查：`kind` 是任意字符串，用对象字面量的话 `constructor` 会查到 `Object.prototype` 上的函数；「按填写计入」去掉同时在 `possible` 里的；两种「另有…未展开」；每层两个空格）；`creditsText`（0 是「0 学分」，null 是「学分未知」）；`draftFailureMessage` 和 `canRetryDraft` 照第 8 节（409 的 `stale`、`missing`、`draft`、`unusable` 合成一句、不给重试，`unavailable` 一句、可以重试，404、422 各一句、不给重试，别的「无法核对草案。」加 R4a 的 `apiErrorMessage`；从不显示 API 的 `detail`）。
5. **组件**（`web/src/features/programs/PlanDraft.tsx`、`PlanDraft.module.css`）：方案不是 `source_checked` 就返回 null。从上到下照第 5 节：小标题（h3）、三行说明、「清空草案」、输入框（标题、`maxLength` 4000）、「加入草案」、核对中那一行、失败那一句和「重新核对」、回答（格式不对或版本对不上各一句警告；否则提示和候选、已填几门、每门课一行和两个按钮、统计、部分规则的说明、规则树、方案里没写到的课）。文字一个字不改，都是纯文本，课程行、提示和规则树保留换行和空格（`white-space: pre-wrap`），长词能折行；组件里没有 `<a>`。每个显示的东西带 `data-kind`。
   - **核对中：** 「加入草案」用 `aria-disabled`、点了不调 `onAdd`，不用 `disabled`（禁用的按钮会把焦点丢掉）；上一次的回答留在下面。
   - **焦点：** 照 10-25 定的统一焦点规则。「加入草案」「清空草案」按了焦点不动；「移除」先把焦点放到「已填 n/20 门」那一行，「重新核对」先放到小标题（都是 `tabIndex=-1`，`focus({ preventScroll: true })`），再调回调。
   - **读屏（说明书没写，协调方定的）：** 草案是以小标题命名的 region。核对中那一行放在「加入草案」旁边一个一直在的 `role="status"` 里；提示和「已填 n/20 门」放在一个一直在的 `aria-live="polite"` 区域里：按了「加入草案」焦点留在按钮上，读屏用户也能听到这次哪些课号没加进去、现在一共几门。失败和两种格式警告是 `role="alert"`（和 R4a 的警告一样）。两个一直在的区域空着时 `position: absolute`，不占网格的间距。
   - **样子（说明书没写，协调方定的）：** 没有转动的图标（和 R3d、R4a 一样只有一行字）；警告带 lucide 的 `TriangleAlert`、强调色边框，普通提示带 `Info`、普通边框（tokens 里没有黄色，没有加颜色）；每门课一张卡，两个按钮能折行；规则树用等宽字体。
6. **离线演示**（`web/src/pages/PlanDraftDemoPage.tsx`、`web/src/fixtures/draftDemo.ts`、`draftScenarios.ts`）：路由 `/programs-draft-demo`，不进导航，`React.lazy` 懒加载，放在 R3d 的 `OfflineDemoShell` 下面（不发 `/config`、`/auth/me`）。顶部「场景」（29 个）、「速度」（正常、慢、立即、一直加载），网址参数 `scenario`、`speed`，认不出的回到 `standard-mixed`、`normal`（`Object.hasOwn`，`constructor` 这样的名字不算），换了控件按 key 从头来。每个场景先按「第一次核对在路上」显示，300ms（慢乘 4，立即 0，一直加载不来）以后换成场景的参数。上面一行是 R4a 的 `scopeLabel(plan)`（h2）。回调只在一个 `role="status"` 区域写一句，回答不变。方案从假数据里按 R4a 的 `availablePlans` 检查以后取。标题「选课草案演示」（`routePresentation.ts`）。
7. **假数据和标准答案：** `draft_fixtures/out` 的 32 份原样复制到 `web/src/fixtures/draft/`，`expected` 的 31 份复制到 `expected/`，一个字节都没改（`cmp` 核过）；`draftFixtures.test.ts` 锁定 63 份的 SHA-256；`web/.prettierignore` 加 `src/fixtures/draft/`。expected 只在测试里读；演示的场景映射是从 29 个标准答案的 props 生成一次的源文件，测试核对两边一样。
8. **测试：**
   - `PlanDraft.test.tsx`：29 个场景逐项比对实际 DOM（`draftTestUtils.tsx` 的 `readDraftDom`：种类、文字、顺序、按钮的 action 和 course_id、「加入草案」的 `aria-disabled`、输入框的标题和字数上限、树的每一行）；回调（输入框的字原样、不去空白，空的也照样调；核对中点了、按回车都不调；清空清输入框、加入不清；移除、课程页、重新核对的参数）；焦点（先移焦点再调回调、`preventScroll`、新回答到了焦点还在那一行；加入时焦点留在按钮上；小标题和那一行不进 Tab 顺序）；纯文本（课名、提示、候选、规则名、原因、没写到的课里放 `<b>`、Markdown 链接、`javascript:`、`<img>`，原样显示，没有 `<a>`、`<b>`、`<img>`、`<script>`）；不是 `source_checked` 的方案什么都不画、不调回调；格式不对、版本对不上（另一个版本、页面上的版本不合格、没有版本）只有一句警告；多出来的键不影响；读屏的区域一直在；部分规则那行只看 `coverage`；学分 0 和 null；`vitest-axe` 六个场景没有违规。
   - `planDraft.test.ts`：18 份真实回答和改出来的两份都读得懂，没有 `result` 的那份不行；第 4 节每一条各一组（从真实回答改一处，边界两侧都测，码点和 UTF-16 长度不同的字也测）；18 个失败向量、7 个树向量；`creditsText`；`Object.prototype` 上的名字当 `kind`；`depth` 参数；同时在 `counted` 和 `possible` 里的课号。
   - `PlanDraftDemoPage.test.tsx`：参数（认不出的回默认）、四种速度的时间（差 1 毫秒都不对）、先核对中再出结果、核对中的场景一直核对中、换控件从头来（输入框的字和状态区的句子也清掉）、五句状态、回答不变、`axe`、整个 App 在这个地址不发请求也不往缓存里放东西。
   - `ProgramCurriculum.draft.test.tsx`：第 1 条的位置、不画的几种情况、换方案时同一个元素、输入框的字还在。
   - `draft.types.test.ts`：第 2 条。
9. **变异**（`web/scripts/draft-mutations.mjs`，照 R4a 的 `programs-mutations.mjs`）：在临时副本里先跑一遍类型和全量测试，再逐个改一处、只跑对口的测试，只有命中对口测试名的真实断言失败才算杀掉（类型变异算对口的类型测试编译失败），跑完核对工作区没变。说明书第 15 节第 2 条列的改坏都在里面（树里留着 emoji、运算的字写错、「按填写计入」算上 `possible`、两种「另有」不写、计数用了别的数、null 学分写成 0、`complete` 也写部分规则、版本不比、`credits` 是 `true` 或 13 也通过、候选超过 10 个也通过、stale 也给重试、unavailable 不给重试、失败时显示 API 给的东西、核对中照样调 `onAdd`、清空不清输入框、移除以后焦点不动、课程行做成 `<a>`、草稿方案也画出来）。

### 修改文件

- 第一个提交：改 `web/src/features/programs/ProgramCurriculum.tsx`；新建 `web/src/features/programs/ProgramCurriculum.draft.test.tsx`。
- 第二个提交：新建 `web/src/api/draft.ts`、`draft.types.test.ts`，`web/src/models/planDraft.ts`、`planDraft.test.ts`，`web/src/features/programs/PlanDraft.tsx`、`PlanDraft.module.css`、`PlanDraft.test.tsx`、`draftTestUtils.tsx`，`web/src/fixtures/draftDemo.ts`、`draftScenarios.ts`、`draftFixtures.test.ts`、`web/src/fixtures/draft/`（32 份）和 `draft/expected/`（31 份），`web/src/pages/PlanDraftDemoPage.tsx`、`PlanDraftDemoPage.test.tsx`，`web/scripts/draft-mutations.mjs`；改 `web/src/App.tsx`、`web/src/layout/routePresentation.ts`、`web/.prettierignore`；文档 `web/README.md`（R4b 一节）和本节。

数据库结构、API、Streamlit 版、Docker、nginx 都没改；`web/openapi.json`、`web/src/api/schema.ts` 没动。

### 验证记录

- **第一个提交 `979e4be`：** 新测试和 R4a 的两个测试文件 91 项都过，typecheck、Prettier、零警告 lint 都过。
- **第二个提交：**
  - typecheck、零警告 lint、Vitest **70 个文件 2332 项**、构建、`format:check`、`gen:api:check` 都过。首屏 JavaScript gzip **187,138 字节**（预算 250,000；演示页懒加载，不在首屏）。
  - 29 个场景、18 个失败向量、7 个树向量全对；63 份假数据和说明书目录里的逐字节一样。
  - 变异：`draft-mutations.mjs` 84 个，**84／84 杀**，跑完工作区没变。第一次跑有 21 个没判定，毛病都在脚本：20 个的过滤名把 describe 名和测试名用空格拼在一起，Vitest 是一层一层（「describe > 测试」）匹配的，一个测试都没选中；D21 写成了等价的（只改 `includes`，前面的 `hasOwn` 照样拦住），改成两行一起换（缺了 `status` 当成 null）。几条 `it.each` 的标题因此改得各自唯一。R4a 的 `programs-mutations.mjs` 也跑了一遍，29／29 杀（`ProgramCurriculum` 改了以后它的锚点都还对得上）。
  - 浏览器（内置浏览器，`build:dev-api` 以后 `preview:dev-api`，5173）：1440×900 和 390×844 各量了 13 个和 18 个场景，整页都没有横向滚动，也没有超出视口的元素；看了 `standard-mixed`、`standard-notices`、`standard-text-edge`（手机）、`standard-409-unavailable`、`standard-checking-again`、`standard-all-present`。键盘：场景、速度、清空、输入框、加入、重新核对依次能 Tab 到，焦点框看得见；按「重新核对」焦点到小标题，按「移除」焦点到「已填」那一行，页面不滚动。新开标签直接打开演示页：控制台没有消息，只有同源的请求。演示是离线外壳，没有开开发 API。服务器用完停了。

### 审查

第 31 轮，两路只读审查（A31：正确性、和说明书是否一致、无障碍、安全；B31：测试够不够、变异、文档），进行中。

### 已知、未处理

- **写成 `1.0`、`1e3` 的整数：** JSON 里的 `1.0` 在 JavaScript 里就是 `1`，所以前端把它当整数收（学分、几个计数都一样），Python 的 `answer_ok`（`type(v) is int`）不收。API 给的都是整数，碰不到；R4a 的检查也一样。
- **输入框的 `maxLength`** 按 UTF-16 算，API 的 4000 字按码点算：输入框里的字有表外字（比如 emoji）时，能填的比 API 收的少，不会多。

### 发布状态

分支 `feat/web-plan-draft`，从 main `cbb91f7` 开。第一个提交 `979e4be` 是 R4a 课程表的草案参数，第二个提交是组件、演示、测试、变异脚本和文档。没有使用真实模型、账号、NAS 或生产库，只用说明书目录里的合成假数据。上线要另外授权（和 React 前端一起）。
