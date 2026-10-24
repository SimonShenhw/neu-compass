# R3c 搜索回答区修改记录

实施：2026-10-23 至 2026-10-24，America/New_York。本批按仓库外 `frontend_react/R3C_SEARCH_ANSWER_SPEC.md` 的 18 节实施，供独立副本验收；所有验证均为本地合成数据验证。

## 1. 起点、提交与范围

- 工作树：`H:\neu-compass-web`，WSL `/mnt/h/neu-compass-web`；Windows Node 24 / npm，Git 操作使用 WSL。没有在包含 `.env` 的 main checkout 中运行测试。
- 从 R3b `f2cf032af85c1885cf42caa7290eb6d16848a0dd` 新建 `feat/web-search-answer`，开始时工作树干净。
- 基线 `npm ci`（402 packages，audit 0）、766 测试、strict 类型、lint、构建通过；首屏 JS gzip 168,252 bytes。
- **独立提交 `4a9d008`**：只给 `src/models/courseDetail.ts` 的已有 `catalog` / `evidence` 函数加两个 export，逻辑不改，类型检查通过。后续 R3c 实现另作本地提交，查看本分支 `git log -2 --oneline`。
- 仅 `web/`，无新增依赖，package / lock 不变。原型 `SearchPage`、R3a / R3b 的组件、模型、数据与测试未改，只有上述两个 export。
- Sites 仅用于本地开发／预览流程；沿用现有浅色 tokens。Computer Use 用于本地浏览器实测；不注册托管、不发布。本批无 push、PR、合并、rebase 或部署。

## 2. 修改索引

以下路径相对 `web/`；文件名可直接用于定位 diff。

| 文件／目录                                                                 | 修改及目的                                                                             |
| -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `src/api/chat.ts`                                                          | 手写事件、失败、凭证、异步来源与回调类型，保留未来 R2b / R3 替换边界                   |
| `src/models/chatTurn.ts`、`chatFailure.ts`                                 | 纯状态转换、终态及精确失败文案；不透传服务器 detail                                    |
| `src/models/conversation.ts`                                               | 下一问历史和上下文课程 ID，最后六条再过滤空消息，按 Unicode 码点截 4000 字             |
| `src/models/searchGuard.ts`、`chatMeta.ts`、`planContext.ts`               | unknown 形状、年度不变式、方案身份／日期／来源校验；分数及条宽格式化                   |
| `src/models/answerText.ts`、`answerFeedback.ts`                            | Python 受限正文解析移植；严格凭证与响应校验、原始正文 UTF-8 SHA-256                    |
| `src/features/search-answer/useConversation.ts`                            | 等待／回答／完成／中断／拒绝，忙碌同步锁、卸载 abort、迟到事件隔离                     |
| `src/features/search-answer/AnswerText.tsx`、`SearchParts.tsx`             | 文本节点渲染、可折行正文、课程证据、原生折叠框及方案位置                               |
| `src/features/search-answer/AnswerFeedback.tsx`、`SearchConversation.tsx`  | 评价异步门控和提交、每轮展示次序、追问条件、可访问状态                                 |
| `src/features/search-answer/SearchConversation.module.css`                 | 现有 tokens、手机布局、长文本／代码换行，不隐藏整页 overflow 掩盖溢出                  |
| `src/fixtures/searchDemo.ts`、`src/pages/SearchDemoPage.tsx`               | 固定假来源与速度、34 个演示对话、五项参数、重播和会话重置                              |
| `src/fixtures/search/`、`expected/`                                        | 69 份原字节 JSON；expected 只供测试                                                    |
| `src/models/searchCore.test.tsx`、`searchValidation.test.ts`               | 正文向量／数值／状态／历史与逐条坏形状测试                                             |
| `src/features/search-answer/*.test.tsx`、`searchTestUtils.tsx`             | 50 scenario 的实际 DOM 对照、钩子生命周期、评价、纯文本、axe；辅助函数隔离复制测试数据 |
| `src/pages/SearchDemoPage.test.tsx`、`src/fixtures/searchFixtures.test.ts` | 参数／速度／StrictMode／重置／回调／懒加载与 69 份哈希冻结                             |
| `scripts/search-mutations.mjs`                                             | 36 个具名变异，在临时快照中逐个改坏；不修改既有变异工具                                |
| `src/App.tsx`、`src/layout/routePresentation.ts`                           | 新增懒加载路由 `/search-demo` 和标题，不加入导航                                       |
| `src/test/setup.ts`、`.prettierignore`、`README.md`                        | 测试环境缺失时补 webcrypto、排除固定 JSON 格式化、记录入口和取舍                       |

## 3. 数据来源与冻结

- 33 份 `search_fixtures/out/` 导出、36 份 `expected/` 原字节复制，合计 **69 份**。复制时及最终收尾分别与原件直接比较 SHA-256，全部一致；独立测试同时冻结文件名和摘要。
- 生成器描述的 API / Streamlit 来源另核对过 **26 个源码 SHA-256**，对应 Git `73635722df551da03624ba878c5cc2d6c1a20c0d`。本轮没有运行生成器、读取 `.env`、开 API 端口或调用 Gemini。
- 单轮导出 32 份，加两段固定多轮对话，共 34 个对话／50 个 scenario；另有 86 个正文向量及数值向量。生产模块只载入单轮导出，不载入 expected 或评价响应标准答案。
- expected 不是页面数据源：golden 测试读取展开后的实际 DOM，核对种类、文字、层级、链接、默认展开、course_id、条宽和按钮禁用状态，再单独比较 timeline / next_request。

## 4. 已落实的行为与取舍

1. **来源与 UI 分开。** 钩子只消费 `AsyncIterable<ChatEvent>`，不组装请求。提问立即进入 waiting，同一 tick 内第二次 ask 被同步锁阻止；首终态即停止读。首事件前失败与中途异常分开处理，无 done 的结束也标记未完成。卸载时 abort；即使来源不配合，也不再读后续事件或更新状态。
2. **历史忠于协议。** 流中错误独立展示；下一问历史才按参考写入警告。只取已结束轮次，最后六条消息先截窗口再去空项，按码点截取，最多十个上下文课程 ID，保留顺序与重复项。被拒轮没有 assistant 错误文案进入历史。
3. **受限正文不调用 HTML / 通用 Markdown。** 精确移植 Python 块／行内解析器，标题用有样式的 p；HTML、图片语法、非法 URL、未闭合链接都保留文字。只允许校验过的官方 HTTPS 链接；React 文本渲染，外链 `_blank` + `noopener noreferrer`。极长单行与大量星号另有测试。
4. **课程随 meta 出现。** 每轮单独展示，最多三门默认展开，多门默认收起；用户的开关不随 token 更新复位。只摘要十类警告和前五类缺失字段，其他缺失用「等 N 项」。meta 中一门结果坏掉就拒绝整组，并且不提供方案、追问或上下文 ID。
5. **年份与方案可独立失败。** 年度证据只查契约规定的记录与计数不变式，不擅自解析规则树或推断注册资格；坏掉只隐藏年份说明。方案逐条验证范围、ID、摘要、时间次序、存档年份、课程键和 placements；不合法整块隐藏。方案条件、path 和 areas 全部纯文本。重复课程 ID 的方案课号沿用 Python 字典的最后一条，而非第一次出现的值。
6. **数值保持运算次序。** 分数复用精确二进制取偶格式化，保留负零。条宽先做 `100 * score / top` 的浮点运算再取偶并限制 8–100；不能重排成 `score / top * 100`。独立测试 `score=0.020500000000000004, top=0.1` 正确为 20，错误重排会为 21。
7. **评价绑定原始回答。** 只有 done、开关开、允许保存、正文非空且三字段凭证合法时，异步比较原始 UTF-8 SHA-256。无额外凭证键；校验缓存逐字段关联，父层原地修改同一对象也立即失效。只发送四字段；成功响应必须恰好两字段且 ID / rating 一致才更新记录。404、其他失败及不匹配分开，失败保留原评价；pending 双按钮禁用，卸载后不接迟到结果。
8. **演示选择。** 打开网址即自动播放，便于直接验收；开始重播。换任一控件用 key 重建会话，旧流取消、反馈和展开清空。StrictMode 下只启动一轮。查看／追问只写 status；固定假评价无真实保存。
9. **加载与无障碍。** waiting 是「正在查找相关的课…」，answering 无字是「正在生成回答…」。回答进行中 aria-busy；一个隐藏 status 宣告开始和结束，不逐字播报。保留原生 summary 键盘行为及可见焦点。没有新增停止、分享或加入对比按钮。

## 5. 验证结果

| 检查                          | 结果                                                                                         |
| ----------------------------- | -------------------------------------------------------------------------------------------- |
| `npm.cmd ci`                  | 基线干净安装成功，audit 0；保留既有 ESLint 9 deprecated 兼容例外                             |
| `npm.cmd run check`           | strict 类型、零 lint 警告、**37 文件 / 1,174 测试**、构建全部通过                            |
| 50 个 golden scenario         | 实际 DOM、点击结果、层级及默认展开全部对齐；timeline / next_request 另核对                   |
| 86 个正文向量、format-vectors | 解析结构、真实 DOM、分数文字、条宽全部对齐                                                   |
| 边界与生命周期                | 各类坏形状、哈希／多余键、409 reason、异常／断线／无终态、忙碌锁、卸载、迟到事件均覆盖       |
| axe                           | 指定四类完成场景与 answering 场景通过；不据此宣称实际语音或布局已验收                        |
| 首屏 JS gzip                  | **169,318 / 250,000 bytes**；基线 168,252，增加 1,066；演示 chunk 懒加载                     |
| R3c 具名变异                  | **36 / 36 KILLED**，基线通过，工作源文件 SHA-256 未变                                        |
| 原有 152 个变异               | **152 / 152 KILLED**，干净基线、sourceUnchanged=true；未改既有变异目标                       |
| 数据／范围静态复核            | 全部 102 个新改文件在 web/；69 / 69 原件摘要一致；无 CR、TypeScript any 关键字或凭证格式命中 |
| 浏览器                        | 两种规定尺寸，30 张最终构建截图，所有根 scrollWidth == clientWidth，warn / error 日志为空    |

`format:check` 第一次在新增 README 后发现排版问题，已用 Prettier 修正文档；最终 `format:check` 和 `git diff --check` 均通过。构建保留原有主 chunk 大于 500 kB 的非阻断提示；首屏 gzip 门禁通过，不通过调高警告阈值隐藏提示。

### 具名变异及测试补强

最初 32 个变异中 S04「先除后乘」存活（31 / 32），说明数值向量没有覆盖这一处真实舍入边界。先用 Python 独立确认 20 / 21，再补上具体数值断言，复跑 32 / 32 抓住。随后又补两个先失败、修正后通过的边界：同一个凭证对象原地改字段、重复课程 ID 方案标签取最后一条。新增原地修改测试一度污染共享 fixture，已将辅助函数改为逐次 structuredClone，不改原始 JSON；该轮 34 个全部抓住。

收尾又补出两个红→绿测试：含逗号的合并键名配合继承字段，不能冒充精确的三字段凭证或两字段评价响应。现在同时检查自有键数与完整键名；新增 S35 / S36 专门验证删掉键数约束会被抓住。新增约束后，旧 S17 只移除键名检查仍会被键数挡住，已将「容许额外字段」这个错误明确为同时移除两道检查，没有为得到 kill 放松正确实现。原有 152 项在这两行校验补强前已跑完；补强后再次通过全部 1,174 测试及新的 R3c 变异基线。

| ID      | 故意改坏的行为                                                                        |
| ------- | ------------------------------------------------------------------------------------- |
| S01–S05 | toFixed 替代、负号／负零丢失、条宽运算重排、取消 8 下限                               |
| S06–S07 | 缺失项摘要超过五个、放宽十类警告限制                                                  |
| S08–S12 | 重复年份、不可用状态仍有记录、未选择计数、selected 缺席计数、omitted 与三条展示的关系 |
| S13–S15 | 方案课程键身份不对应、checked 时间早于 capture、存档年份不核对                        |
| S16–S20 | 跳过凭证哈希、容许多余键、响应 rating 错误、非成功也改评价、请求多第五字段            |
| S21–S25 | 忙碌锁失效、卸载不 abort、非法状态转换、历史窗口八条、按 UTF-16 截字                  |
| S26–S28 | 409 忽略 reason、追问出现在旧轮、rejected / empty 也显示追问                          |
| S29–S32 | 标题改 h3、HTTP 目录可点击、粗体内侧空白放宽、卸载后继续读迟到事件                    |
| S33–S34 | 沿用已变更凭证的缓存校验、重复 ID 改取首条课号                                        |
| S35–S36 | 含逗号的自有键名伪装凭证／响应字段集合                                                |

变异只在临时目录运行；各条需要指定断言失败才算抓住，超时、缺报告或编译／导入错误不能冒充 kill。摘要包含改动前后片段、变异哈希和失败测试名，不只有总计。

本机证据（artifacts 为 Git ignored，可通过上面命令重建）：

- 最初缺口：`artifacts/search-mutations-2026-10-24T00-55-24-293Z/summary.json`。
- 补强 32 个：`artifacts/search-mutations-2026-10-24T00-57-22-301Z/summary.json`。
- 34 个版本：`artifacts/search-mutations-2026-10-24T01-00-23-343Z/summary.json`，含 1,172 测试的干净基线与 sourceUnchanged=true。
- 最终数据和静态检查：`artifacts/search-final-audit.json`。
- 来源复核：`artifacts/search-source-provenance.json`，26 / 26 与 Git blob 字节相符。
- 原有回归：`artifacts/mutations-2026-10-24T11-22-33-702Z/summary.json`，152 / 152，sourceUnchanged=true。
- 键集合红／绿证据：`artifacts/search-keyset-red.json`（两个断言失败）和 `search-keyset-green.json`（两个通过）。
- 最终全量：`artifacts/search-final-check.log`，1,174 测试、类型、lint、构建通过。
- 最终 36 个变异：`artifacts/search-mutations-2026-10-24T11-35-11-966Z/summary.json`，36 / 36，1,174 测试的基线通过，sourceUnchanged=true。
- 格式检查：`artifacts/search-final-format.log`。

## 6. 浏览器验收记录

2026-10-24 使用最终生产构建、Vite preview `127.0.0.1:4173`、内置浏览器实测。入口 `assets/index-DMHiANvF.js`，懒加载 `assets/SearchDemoPage-CqBzki0o.js`；不是旧构建的截图。最终证据在 `artifacts/search-browser-final/`，汇总 `observations.json` 包含实际 URL、尺寸、根宽度、状态、轮次数、按钮和键盘焦点。

| 场景                    | 1440×900                                       | 390×844                           |
| ----------------------- | ---------------------------------------------- | --------------------------------- |
| alias-cs-6140           | 中途／完成；半截链接为文字，终态才显示完整链接 | 中途／完成，长正文与证据折行      |
| hybrid-neural-network   | 默认收起、Enter 展开六门、底部补拍             | 默认及展开卡片，分数与课程名可读  |
| plan-ds-align           | 展开方案、条件与来源、课程区补拍               | 长 path／条件／日期／来源与课程区 |
| feedback-receipt（开）  | Space 投有帮助、Enter 改没帮助；状态和禁用正确 | 同样两次改票，保留最近评价说明    |
| model-error             | 部分正文和独立错误警告                         | 半截 URL 原文折行、警告可见       |
| refused-409-plan-stale  | reason 文案正确，无假回答                      | reason 文案完整换行               |
| answer-markdown-edge    | 非官方链接、HTML、图片为文字，代码块可读       | 网址、代码折行，无横向溢出        |
| conversation-four-turns | 四轮、被拒／中断留在原轮、末尾补拍             | 长问题及四轮，最后一轮追问可用    |

- 共 30 张最终截图；所有测点根 `scrollWidth == clientWidth`，两尺寸均没有整页横滚。滚动条出现时 clientWidth 会比 viewport 少 15px，比较的是两个根宽度，没有误把滚动条算成溢出。
- Tab 按演示对话→回答反馈→reason→评价结果→速度→开始走，焦点描边为钴蓝 2px。开始 Enter、相关课程 summary Enter 开关、方案 summary Enter、查看 Enter、追问 Space、两个评价按钮均实测。
- 查看回调显示「演示：这里会打开 c-cs-6140」；追问显示对应原句，不跳转或发问。正文边界的实际标签只有允许的 p / strong / a / pre / code；四条链接均为 HTTPS 官方目录、_blank、正确 rel，没有 img / script / 模型 h*。
- warn / error 控制台日志为空。完成后重置临时 viewport、关闭本轮临时浏览器标签页；本轮 preview 进程已核对归属后停止，4173 端口关闭。

## 7. 接下来与未验收边界

- 下一步交给 R3 集成：替换消费类型／来源，接 R2b streamChat、config / feedback、请求历史和课程详情右栏。此批只有可独立验收的组件与本地外壳，不改变 R1 原型搜索页。
- 方案／项目选择属于 R4；提问框、保存勾选、发现区、停止、分享、加入对比均按说明书留在后续。不要根据合成方案或检索分数推断选课、注册、毕业资格。
- 自动化测试禁用 fetch；演示源码没有请求客户端。浏览器可核对静态资源和实际 DOM，但当前控制接口没有完整请求瀑布，所以**没有宣称完成完整网络面板验收**。
- axe 和真实键盘检查不等于屏幕阅读器语音验收。无真实登录、API / 模型、生产数据保存、上线或 NAS 部署验收；后续需独立完成。
- 既有 ESLint 9 deprecated 与工具兼容例外沿用 README，未在本轮升级依赖或扩大修改范围。
