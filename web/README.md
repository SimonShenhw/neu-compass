# NEU-Compass · React 本地原型

这是新前端的本地原型：长得对、点得动，页面内容还是假数据。R2b 起登录、登出和「现在是谁」接上了真实接口（见下面「接口层与登录 R2b」），各页的内容以后分批接。不是已经迁移完成的产品，也不替代线上 Streamlit。

## 安装与运行

在 Windows PowerShell 中使用 Node 24，进入这个 worktree 的 `web/`：

```powershell
cd <你的 worktree>\web
npm.cmd ci
npm.cmd ci --prefix tools/openapi-types
npm.cmd run dev
```

第二行装接口类型的生成器（R2b，见下文）；不装也能开发和测试，只是 `gen:api` 跑不了，两项 schema 测试会显示为跳过。开发地址为 `http://127.0.0.1:5173/`。看生产构建：

```powershell
npm.cmd run build:dev-api
npm.cmd run preview
```

预览地址为 `http://127.0.0.1:4173/`。`build:dev-api` 构建的页面连本机的开发 API；`npm.cmd run build` 是给学生用的正式构建，连正式 API（只认 https），在本机预览时登录和各页的请求都不会成功。两个服务都只绑定本机，没有代理。本机用的 API 怎么起见下面「接口层与登录 R2b」。`node_modules/`、`dist/` 和本地 `artifacts/` 不提交。

## 检查

```powershell
npm.cmd run check
npm.cmd run format:check
npm.cmd run gen:api:check
npm.cmd run test:mutations
```

- `check` 依次做 strict 类型检查、零 lint 警告、Vitest 行为测试和构建。
- `gen:api:check` 查 `src/api/schema.ts` 和 `openapi.json` 生成的一致（要先装生成器）。
- `build` 额外读取 Vite manifest，累加首屏入口及其静态 import 的 JavaScript gzip 字节，超过 **250,000 bytes** 就失败。字体和 CSS 不混进 JS 指标，也没有靠延迟加载隐藏首屏依赖。
- `test:mutations` 在系统临时目录创建隔离副本，先验证未修改副本的完整测试和类型，再执行 130 个具名变异。每项只运行对应名称的行为测试，避免重复执行整份表单用例；原 R1、Co-op、R5b 检查保留，R5c 另加 26 项，R3a 另加 M111–M130。副本里除了 `src/` 和配置，还有测试要读的 `index.html`、`openapi.json` 和生成器的 `package.json`（R2b）。完整基线测试最多等 120 秒，单个变异仍为 45 秒。不修改当前源码、不安装额外依赖。只把命中预期测试名称的真实断言失败算作杀死；超时、导入失败不算。类型变异要求命中缺失 label 的编译断言。
- 变异日志、失败测试名、源码 SHA-256 与结果位于 `artifacts/mutations-<UTC timestamp>/`，副本保留以便复核，不自动递归清理。
- `.github/workflows/ci.yml` 的前端 job：Node 24 → `npm ci` → 装生成器 → `gen:api:check` → 格式 → `check`；Python job 另查 `web/openapi.json` 是最新的（R2b）。远端是否绿色，必须在后续授权 push 后由 GitHub 验证，不能从本地检查推断。

## 路由与演示

| 路径                 | 内容                                                                |
| -------------------- | ------------------------------------------------------------------- |
| `/`                  | 固定示例问答、回答用到的四门课、项目／方案选择、输入框              |
| `/?demo=empty`       | 四个示例问题的空首页；发送后显示固定示例回答                        |
| `/course/CS-6140`    | 桌面保留左侧对话，右侧课程详情；手机一栏到底                        |
| `/course/CS-5800` 等 | 只支持五门 fixture 课程；未知课号显示明确空状态                     |
| `/compare`           | R5b 合成 API 课程对比，默认四列；七项信息、独立失败状态、移出与清空 |
| `/coop`              | R5a 合成 Co-op 列表、等级展示、投稿表单与结果演示                   |
| `/programs`          | “这一页正在搬到新版”                                                |
| `/privacy`           | R5c 接口形状的合成隐私说明、确认删除与四类结果演示                  |
| 其他                 | 404 与返回首页链接                                                  |

课程路径使用横线，例如 `CS-6140`；旧 `?course=` / `?program=` 兼容留给 R3。假数据只有 CS 5800、CS 6140、CS 7800、DS 5220、CS 5100，不含真实用户数据。

标题、导航当前项和搜索输入框共同使用 Router 的路径匹配规则：已匹配页面的尾斜杠 / 主路径大小写变体仍显示一致的页面状态；无效子路径显示客户端 404，不混入搜索控件。保留原始 URL 和课号参数，不做重定向或新增课号归一化；客户端 404 展示不等于服务器 HTTP 状态码验收。

## 状态边界

- 项目／方案与演示问题放在路由之上的 React context，页间跳转不会丢；换项目会清掉方案。对比页不再提供方案选择。没有持久化到 localStorage、Cookie 或后端。
- 搜索清单和详情里的“加入对比”按 R1 规范只 `console.info` 合成课号，并显示本地提示，**不实际添加课程**。
- 对比列表改为独立的 course ID 内存 store，侧栏和顶栏读取同一份列表。演示首次进入或切换场景才填入示例；同一场景离开再返回，不会复活已移出／清空的课程。刷新会恢复示例，不能把它当成正式登录／退出策略；R2 仍须在真实身份边界主动调用 `clearCompare()`。
- 侧栏和手机菜单的登录、登出从 R2b 起是真的（见「接口层与登录 R2b」）。Co-op、对比、隐私三页还用自己的演示身份，Co-op 本页的登录按钮仍只显示演示通知，等 R5d 接上真实接口。
- 输入、发送、Enter、Shift+Enter、中文输入法和允许保存勾选可以操作，但只更新本地问题，回答始终标作固定示例；不会调用模型、写查询日志或真的保存回答。「允许保存」默认关闭，每次发送后重置，只代表这次问题的演示选择。未来查询日志提示文案保留；侧栏注明当前是假数据原型。
- 分享按钮仅展开当前本地路由，不复制、上传或发布任何内容。刷新课程数据也只显示演示提示。

## Co-op R5a（2026-10-22）

按评审目录 `frontend_react/R5_COOP_SPEC.md` 实现，替代最初仅浏览的草稿；**不接真实 API、登录、取数或缓存**。R1 提交保留在 `feat/web-skeleton`，本批在 `feat/web-coop`。R2 后续连接回调，不需要重写页面的表单 / 展示逻辑。

`src/api/coop.ts` 暂手写说明书的接口类型。`CoopPage` 只接 `viewer`、`list`、`onRetryList`、`onSubmit`、`onLogin`；不读取 URL 或修改贡献数。`CoopDemoPage` 单独承担本地演示参数、通知和 400ms 延迟。登录按钮只显示“未发起真实登录”的本地提示，不伪造登录。

| `/coop` 参数 | 可选值 / 默认                                                                                                                             |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `viewer`     | `guest`（默认）、`member0`、`member1`、`member2`，直接选择对应 API 导出列表                                                               |
| `list`       | `ready`（默认）、`loading`、`error`、`empty`                                                                                              |
| `submit`     | `pending`（默认）、`duplicate-pending`、`duplicate-approved`、`duplicate-published`、`duplicate-rejected`、`401`、`422`、`503`、`network` |

例如 `/coop?viewer=member0&submit=duplicate-approved`，或 `/coop?viewer=guest&list=error`。页面顶部也有三个演示选择器。未知访客回退游客，未知状态回退正常列表 / pending；旧草稿的 `demo=coop-*` 不再使用。演示重试只恢复正常合成列表。

- **数据来源：** 18 份 JSON 原样来自评审目录 `coop_fixtures/out/`，放在 `src/fixtures/coop/`。测试锁定全部 SHA-256。该生成目录单独跳过 Prettier，以保留来源字节；其余源码照常格式检查。不运行生成脚本、不改 JSON、不包含真实用户数据。
- **相关课程显示并链接：** 复用 `CourseCode`，空格换横线并编码为本地 `/course/<code>`。当前仍只支持 R1 五门示例；这不是 R3 的真实 resolver。
- **加载采用文字状态：** 一行“正在加载”并标记 `aria-busy`，不虚构骨架条目；失败只有固定中文和重试，空列表使用 `EmptyState`。缺少行业 / 时长不显示，学期为空不留下分隔符。
- **字段含义：** 只显示响应中非空的详情，原生 `details` 默认收起；文字不解析 HTML / Markdown，不自动生成正文网址链接，换行保留。2 级行只保证薪资，不保证面试细节；行业未知值原样显示。
- **投稿：** 原生字段 / 现有 Button；公司、职位 trim 后必填，时长可空或 1–8 整数。提交时同时检查数字框原生 `validity.badInput`，避免 `1e` 这类不完整输入虽然 DOM value 为空，却被当成留空提交。三段文字 trim 后各最多 10,000 个 Unicode 字符（不误用 UTF-16 长度）。课程按三种逗号拆分、trim、去空、稳定去重；请求只构造规定字段。
- **结果与隐私：** 提交中禁用字段和按钮，并用同步锁防连点；成功（含重复 / 拒绝原记录）清空，失败保留。结果接续焦点，字段错误用 `aria-describedby` 关联；401 提供登录回调，422 只白名单识别字段名，英文原文绝不展示。不写浏览器存储或控制台。
- **贡献数 / 切换：** 仅展示外部 `viewer`，不从 201 或结果计数加一。演示切换会清除草稿、筛选和展开；已离开页面的异步结果不回灌。R2 必须另外按真实会话 owner key 隔离页面，不能用贡献数区分两个账号。
- **文案 / 布局选择：** 正文与结果沿用说明书固定中文；额外增加“请检查标出的字段后再提交。”作为本地校验的结果摘要，便于聚焦朗读。1199px 以下改为单栏，手机表单字段单列，保证长标签可换行。Co-op 顶栏隐藏重复游客徽标；侧栏仍是 R1 原型，不代表演示会员已完成全站登录。

演示所有等级包会进入本地 bundle，**只能含合成记录**；不能把演示参数当鉴权。R2 接入后替换外壳和生成类型，服务端负责删字段、身份与缓存；真实账号、接口端到端、屏幕阅读器语音和上线仍需另验。修改经过见 [COOP_WORKLOG.md](COOP_WORKLOG.md)，R1 历史仍在 [WORKLOG.md](WORKLOG.md)。

## 课程对比 R5b（2026-10-22）

按评审目录 `frontend_react/R5B_COMPARE_SPEC.md`，从 `6b633b9` 开出 `feat/web-compare`，只改 `web/`，不接真实 API。沿用 Sites 的本地预览流程，保留原有 tokens、组件与路由；没有生成托管站点或发布。独立修改与验收记录见 [COMPARE_WORKLOG.md](COMPARE_WORKLOG.md)。

`/compare?case=<值>` 可直接切换，页面顶部也有原生「演示场景」选择器；缺省及未知值回退 `four`。

| case                     | 内容                                                                    |
| ------------------------ | ----------------------------------------------------------------------- |
| `four`                   | CS 5800、CS 6140、DS 5220、CS 5100 四门，覆盖跨年规则、缺失、学分冲突等 |
| `one`                    | CS 7800 单列，明确是合成测试课程                                        |
| `empty`                  | 空列表及返回搜索入口                                                    |
| `failed`                 | 两门正常、404、模拟连不上；失败列仍可移出，无「查看」                   |
| `unrecognised`           | `null`、数组、缺身份字段的对象，三列独立失败                            |
| `bad-cell`               | 只让 CS 5800 的考核构成字段类型错误，其他格／列照常                     |
| `loading`                | 两列文字加载状态                                                        |
| `requisites-unavailable` | 结构化先修暂不可用，但其他课程信息照常                                  |

- `src/api/course.ts` 手写说明书规定的类型。`ComparePage` 只接 `ids`、`columns`、`onRemove`、`onClear`、`onReload`，不读 URL、store 或接口；只展示前四个 ID。`CompareDemoPage` 独立承担参数和演示数据；重试只把失败列改为加载 400ms，再回到同一个合成失败，不假装已请求成功。
- `src/models/compareList.ts` 导出 `addToCompare`、`removeFromCompare`、`clearCompare`、`useCompareList`，另有只读 `getCompareList`。以 course ID 而非课号存储，保留加入顺序；满四门时重加原 ID 仍返回 `already`。不写 storage、不记录控制台；R3 的详情按钮可直接接入，当前 R1 的按钮仍只演示提示，不在此批改动。
- 七行始终展示；「只看不同的行」与「按方案看」已按 R5b 约定移除，等 R4 的方案与草案数据，不从旧 seed 推断资格。方案位置只保留未核验说明和已返回的关系。
- 格式化与 UI 分离：`src/models/compare.ts` 处理目录校验、年度条款比较、缺失及提示文案；`CourseHeaderFacts` / `CourseFactCell` 是可供 R3 复用的展示组件。某格字段错误只替换该格，列头错误不拖累正文；无法识别整个 body 才是列失败。
- **加载选择：** 用「正在加载」文字而不是虚构内容骨架，保持真实列数与可移出操作；失败列不透传服务器原文。**长描述选择：** 全文换行显示，不截断，避免多层展开按钮和隐藏来源说明；代价是表格较长。七行仍在一个可聚焦的独立横滚区域，固定首列；整页不横向滚动。
- 目录只接受规定形状和精确匹配课号前缀的官方 HTTPS 地址，拒绝额外键、查询串及来源不符；时间有偏移则转 UTC，无时区不擅自补 UTC。年度要求同时核对 ID／课号／课名，比较所有年度的先修和共修树，未解析文字全长比较；不拿首尾两年或截断文字替代。
- 百分比沿用 Python `.0f` 的恰好 `.5` 取偶数；工作量等沿用六位有效数字的 `:g`，而非 JS 默认字符串或 `Math.round`。0 和缺失分开，不把未知难度、要求或方案关系当成 0／没有。
- **来源与安全：** 七份 `compare_fixtures/out/` 及六份 `expected/` 原字节复制到 `src/fixtures/compare/`，SHA-256 全部锁定；目录单独跳过 Prettier。课名、描述、主题、考核名和方案名全部是纯文本，不解析 HTML／Markdown／正文网址。外部链接只来自通过校验的目录 URL；「查看」仍是本地课程路由。
- 2026-10-22 本机 Windows 将 4173 列入保留端口，验收临时用 `npm.cmd run preview -- --port 5173 --strictPort`，未改网络设置。常规端口未被保留时，默认 preview 命令仍用 4173。

这批不是 R2 的真实身份、请求与缓存集成，也不实现 R3 的加入按钮或 R4 的方案筛选。独立验收还要检查真实网络面板；本机浏览器没有完整请求瀑布接口，不能据此宣称完成线上验收。

## 数据与隐私 R5c（2026-10-22）

从对比页 `101775e` 开 `feat/web-privacy`，依据 `frontend_react/R5C_PRIVACY_SPEC.md`，仅改 `web/`，无新增依赖。沿用 Sites 的本地开发／预览流程与现有 tokens，不注册托管、不发布。独立记录见 [PRIVACY_WORKLOG.md](PRIVACY_WORKLOG.md)。

`/privacy` 默认游客、90 天说明、成功结果场景。参数也可用页面顶部三个选择器切换：

| 参数      | 值                                                                                                                  |
| --------- | ------------------------------------------------------------------------------------------------------------------- |
| `viewer`  | `guest`（默认）、`member`                                                                                           |
| `privacy` | `90-days`（默认）、`no-cleanup-off`、`30-days`、`no-cleanup-contact`、`loading`、`error`、`network`、`unrecognised` |
| `delete`  | `ok`（默认）、`ok-nothing`、`401-stale`、`401-gone`、`403`、`422`、`503`、`network`                                 |

例如 `/privacy?viewer=member&privacy=30-days&delete=503`。未知值分别回退 `guest` / `90-days` / `ok`；`network` 删除场景模拟抛错。删除和重试均等 400ms，重试回到原来的合成响应，不假装联网成功。

- **文本唯一来源：** intro、每段标题／句子、delete_what 全部来自原始 body；不在组件重写保留天数、邮箱或政策文字。10 份 JSON 原字节复制，独立 SHA-256 测试锁定，单独跳过 Prettier。query_log_notice / capture_notice 只声明类型，本页不显示，留给 R3。后端提供的 👍／👎 作为原句的一部分保留，不拿 emoji 代替 UI 图标；标题用 Lucide Lock。
- **整页校验：** 只校验本页实际使用的字段，其他键忽略；sections 必须非空，每个标题、每句都是字符串。有一处不对就只显示固定失败提示和重试，不展示半份隐私说明，也不开放删除。加载选择文字「正在加载」，避免虚构政策内容。
- **删除与结果：** `PrivacyPage` 只收 props／回调；`AccountDeletion` 管确认、同步锁、pending 和卸载保护，结果状态在页面上层。成功／401 只调用一次 onSignedOut；null／502／503／504／抛错为不确定；403／422／429／500 等保留“什么也没删”。原文 detail 和行数不展示。
- **结果保留选择：** 外部 viewer 从登录变游客时，表单消失但结果与焦点保留；再登录时新的表单默认未勾选，旧结果保留为最近一次操作结果，不重新抢焦点。下一次删除开始才清掉旧结果。卸载、隐藏表单或说明变无效后才回来的旧请求结果不回灌。
- **文案偏离已获用户批准：** 不确定结果改为「这次没收到服务器的确认，不确定删除有没有完成。刷新后若仍是登录状态，可以再试；若已变成游客但需要确认，请联系维护者。」原稿“变成游客了，就是已经删掉了”不成立，cookie 失效也会成为游客。其余三句结果沿用原稿。本轮不改另一分支的后端／Streamlit 或外部说明书。
- **演示身份不等于登录：** 删除成功或 401 只改变本地演示身份，不改 URL；选择器显示 URL 中的初始化场景，当前状态另有一行明确显示。显式切换任意参数会开始新的演示场景并清除旧结果；模拟删号导致的身份变化不会重建页面。全站身份、Cookie 和其他页面 store 的清空留给 R2b。
- **安全／布局：** 所有接口文字都是 React 纯文本，邮箱／网址不自动成链接；不写 storage，不输出 console。删除区始终在四段之后，确认 label 的触控区不小于 44px；结果是可聚焦 status，正文长句换行，两种验收宽度均无整页横向溢出。

当前仍是合成演示，**没有执行任何真实删号、登录／退出、请求或数据库操作**。真实 R2b 接入必须负责响应校验（特别是 200 的 deleted）、请求体 `{"confirm":"delete"}`、Cookie／Origin／X-NEU-Compass 及会话边界；不能照搬 URL 演示身份作为鉴权，也不能随 viewer 重建 PrivacyPage 丢掉结果。真实请求瀑布、实际删号、屏幕阅读器语音及上线仍需单独验收。

## R3a 先修要求组件与演示

`/requisites-demo?case=cs-6140-two-years`（不加入导航）只用合成 API 导出。演示数据选择器提供 16 个 case；缺省或未知 case 回到 `cs-6140-two-years`，换 case 清空年份、方案和导航提示。点击规则课号或旧边「查看」只在 status 区显示「演示：这里会打开 …」，不跳转、不取数。

- 目录：`features/requisites/CourseRequisites.tsx` 为公开组件；树、证据、方案上下文分文件以保持职责明确。参数完全由调用方提供；加载、失败和重试 UI 属于未来 R3 取数外壳，本组件不模拟这些状态。
- 调用方用 `key={course.course_id}` 区分课程。多年份默认空，单年份仅首次挂载默认显示；主动清空、数据移除后的选择均不会自动恢复。换年份重新挂载方案区，返回原年份也要重选。没有把选择写入 URL 或 storage。
- `api/requisites.ts` 为手写消费类型；`models/requisites.ts` 接收 unknown，只按说明书检查形状和链接，忽略额外字段；不复刻 Python 的原文重解析与候选池语义证明。未使用的方案节点字段不额外收紧，以免越过前端契约。
- `models/requisiteRules.ts` 导出 `ruleLines`、`programRuleLines`，逐字对齐 Python。课程树只在同组内合并完全相同的叶子；原文不改。方案用可折行、保留缩进的纯文本，不做个人资格或学期规划。
- `fixtures/requisites/` 的 16 份导出与 `expected/` 的 16 份标准答案逐字节冻结，独立 SHA-256 测试防改动；expected 只供测试，不打包进生产。34 个场景逐项比对 DOM，不从标准答案生成页面。
- 旧边保留用于未选年份、未解析和非树内课程的导航。R3a 明确覆盖了 R1「删掉下面那排按钮」的决定；原型课程页及旧 `RequisiteTree` 本轮不改。数据无效／存储冲突时旧边不能冒充必修性判断。
- 所有接口文字均按纯文本显示；两个来源链接须精确通过官方 URL 限制，且新标签页带 `noopener noreferrer`。学分字符串原样，时间只替换末尾 Z；树最深 10 层、方案最深 8 层，各最多 120 节点。
- 复用 R1 Select、CourseCode、Button 和浅色 tokens；details 默认折叠。测试中 jsdom 不实现原生 summary 的 Enter 默认行为，因此键盘展开另外由真实浏览器验收，不用 jsdom 的绿色结果代替。

过程、验证与边界另见 [REQUISITES_WORKLOG.md](REQUISITES_WORKLOG.md)。真实 R3 接入、线上数据和完整网络瀑布仍需另验。

## 接口层与登录 R2b（2026-10-23）

从 main 开 `feat/web-api-client`，依据评审目录 `frontend_react/R2B_PLAN.md`。这一批让前端第一次真的请求 API：接口层、登录和登出、聊天流的客户端；各页的内容还是假数据，隐私、Co-op、对比三页在 R5d 接上，搜索和聊天页在 R3。

**本机怎么跑：** 起两个服务，都在 `127.0.0.1`。

1. 开发用的 API：在仓库根目录（WSL）用项目的 Python 环境运行 `uv run python -m tests.support.dev_api`，监听 `127.0.0.1:8000`；没有 `.env` 时先设一个占位的 `GEMINI_API_KEY`（设置要求有这一项）。它是真的 `create_app()`，但用临时文件里的合成数据库、测试套件的替身模型，Google 换成本机的假登录页 `/__dev/google`（三个合成账号，三种被拒、state 不对和取消各一个链接）。除了 Gemini 的 key，每个设置都从代码里的默认值开始，`.env` 和环境变量里的限流、数据路径之类不起作用；访问日志和生产一样去掉登录地址的查询串、课程只记路径模板。每次启动换一个会话密钥，重启就都登出了。不部署，生产代码不 import 它，API 里也没有测试模式。
2. 本页：`npm.cmd run dev`，打开 `http://127.0.0.1:5173/`（不要用 `localhost`）。预览构建用 `npm.cmd run build:dev-api` 再 `npm.cmd run preview`。

页面和 API 的主机名必须一样：浏览器按主机名算「站点」，`localhost` 和 `127.0.0.1` 是两个站点，SameSite=Lax 的会话 cookie 就不跟着请求走，登录了也像没登录。Chromium 在 `http://127.0.0.1` 上收 `__Host-` 开头、带 Secure 的 cookie（10-23 在浏览器里验过）。

- **API 地址在构建时定**（`src/api/apiBase.ts`）：`npm run build` 是正式构建，默认 `https://api.neu-compass.me`，`VITE_API_BASE_URL` 可以换成别的 https 地址，本机的 http 一律让构建失败，免得给学生的页面去连他们自己的电脑；`npm run build:dev-api` 和开发服务器默认 `http://127.0.0.1:8000`；别的构建模式（比如 beta）必须写明 `VITE_API_BASE_URL`。测试一律用本机的，不管环境里设了什么。地址只认 https 或本机的 http，不带路径、查询、`#` 或账号密码，坏值让构建失败。`web/.env.local` 这类文件已在 `.gitignore` 里。
- **接口类型是生成的：** 后端的 `scripts/export_openapi.py` 导出 `web/openapi.json`，`npm run gen:api` 从它生成 `src/api/schema.ts`，`npm run gen:api:check` 和 CI 查两者一致；后端那边 CI 也查 `openapi.json` 是最新的。生成器 openapi-typescript 7.13.0 只声明支持 TypeScript 5，本包用 6，所以它单独放在 `tools/openapi-types/`（自带 TypeScript 5 和 lockfile），没有用 `--legacy-peer-deps`。R3a 的先修类型（`src/api/requisites.ts`）比生成的窄，按 kind、status 分开，所以还是手写；`src/api/requisites.types.test.ts` 在类型检查时把它们和生成的类型对照：面板读的字段 API 得有，API 可能给的值面板得收。
- **请求只有一个出口：** `src/api/client.ts`。每个请求都带 cookie、不用 HTTP 缓存、不跟重定向；写请求带 `X-NEU-Compass: 1`，有请求体才带 JSON 的 Content-Type。四档超时照 Streamlit（5／8／15／30 秒，读完回答也算在内），什么都不自动重试。失败变成 `ApiError`（状态码、`error_type`、`Retry-After`、422 被拒的字段名、登录被拒的 `reason`），不带后端的英文原文；页面上的中文照 Streamlit。
- **取数：** TanStack Query，不重试；切回窗口、网络恢复都不重取。断网时请求照样发出、照样失败，不会排队等网络回来再自己发（写请求尤其不能这样）。暂时的失败（超时、429、5xx）继续显示上次的内容，明确的答复（401、404、422…）不留。`/config` 5 分钟内算新鲜；`/auth/me` 的 401 就是游客。
- **登录：** 点按钮时生成 32 字节的随机 state，和回来的页面一起放进 sessionStorage（本站只在这里存东西，用一次就删），整页去 Google（只认 Google 的登录页；页面连本机开发 API 时也认它的假登录页）。回到站点根路径时先把 code 和 state 从地址栏和历史里去掉，这时还不问 `/config`、`/auth/me`；再核对 state，对了才用 cookie 模式提交回调，然后重读一次 `/auth/me`：浏览器没收下 cookie 就说「这个浏览器没有保存登录状态…」，最后回到原来的页面。state 对不上的返回链接（包括带 `error=` 的）什么都不发、也不显示链接里的字。外校邮箱和没验证的邮箱分开说，别的失败一句话。登录、登出时清掉按身份取的数据，登出时再清课程对比。
- **Referrer：** `index.html` 设 `strict-origin-when-cross-origin`，发给别的站点的只有本站的来源（R0 14.15；R7 在服务器上再设一次）。
- **焦点：** 账号框里按下的按钮忙完以后（登出换成登录按钮、失败恢复原按钮），焦点回到账号框现在的按钮上（桌面侧栏和手机菜单里都一样，和结果同一次渲染完成），用户自己移开了就不动。从 Google 页按「后退」、浏览器原样恢复本页时，登录按钮恢复可用。
- **聊天流：** `src/api/chatStream.ts` 的 `streamChat(request, { signal })` 边收边读 `/chat` 的 NDJSON，给 R3 的搜索和聊天页用；它是 `client.ts` 以外唯一调 fetch 的文件。先 `meta`，再若干 `token`，最后 `done`（可能带反馈凭证，由页面照 Streamlit 的做法核对）；或者中途一个 `error`，它的 `detail` 是 API 给学生看的固定中文，照样显示。等回答开始、等下一块各最多 30 秒；断线、超时、没有 `done` 就结束、有一行不是这四种事件、或者一行长过 100 万个字符（API 最长的一行也就几十 KB），都在已经收到的内容后面补一句 Streamlit 的话（「连接中断。…」或「回答流未完整结束；…」）。流开始前的失败和别的请求一样是 `ApiError`。不自动重发（每问一次都算模型次数、写查询日志）；能取消。
- **开发 API 的聊天：** `/chat` 按脚本回答，不调用模型，HyDE 补救也关着。问题里带 `dev:model-error`（模型中途出错）、`dev:no-answer`（没有回答）、`dev:daily-limit`（今天的次数用完）、`dev:no-done`（流没有 `done` 就结束）、`dev:cut`（连接中途断开）、`dev:stall`（停 35 秒，比前端等的久），就换成对应的情况。
- **测试：** 渲染整个 App 的测试套 `src/test/withApi.tsx` 的 `WithApi`，它预先放好 `/config` 和游客身份，测试里不发请求（`fetch` 在测试里仍被禁止，要用就 stub）。
- **上线前（R7）：** Google OAuth 客户端要把新前端的地址（来源加 `/`）加进 Authorized redirect URI，API 的 `WEB_ORIGINS` 也要设成它，不然 Google 或 API 会拒绝。

## 设计选择及差异

- 用户确认：沿用第一版白底细线与钴蓝强调色；导航以中文为主；R1 只做浅色，不做主题切换。原 R1 的「默认只看不同的行」已被 R5b 的「本轮不做行筛选」取代。
- `tokens.css` 只声明变量；产品 token 去掉设计稿的 `a-` 前缀。CSS Modules 使用 tokens，无内联布局样式；唯一内联值是对比列数，用于动态表格最小宽度。
- 原稿次级文字色 `#727e90` 对小字偏淡，调整为 `--ink3: #596678`，另加 4.5:1 token 对比度测试。其他主色沿用设计稿。
- 字体由 Fontsource 随包打包，IBM Plex Sans / Mono 仅带所需 Latin 字重，中文用指定系统字体，不使用 Google Fonts。图标只用 Lucide。
- 原 R1 原型先修树的叶子可以直接点击，所以原型曾删掉树下重复的“去看看”按钮；R3a 按新说明书恢复旧边导航，理由见上节。课号和未知要求不会自行推断为可注册。
- 手机空首页按手机稿省略重复游客行和项目选择器，避免把输入框挤出首屏；回答页仍提供项目选择。手机搜索标题对视觉隐藏但保留可访问标题；比较等页面标题正常显示。
- 输入框沿用手机稿的短占位文案「问任何课程问题…」；隐私说明保留完整句子。对比页主题复用 Chips，最多八个再显示「+N」；不改变原组件行为。
- 手机触控至少 44px；勾选框由整行 44px 高的 label 提供点击区域。对比表是独立可聚焦、可横向滚动的区域，首列 sticky，不通过隐藏整页 overflow 掩盖问题。
- 路由变更聚焦主内容时使用 `preventScroll`，并回到页顶，避免焦点把顶栏拉出视口。
- 控件被移除后显式接续键盘焦点：移出对比课程时优先下一列、否则上一列；清空或移出最后一门后聚焦返回搜索链接；从空首页选择示例问题后聚焦新回答。对比列的无关更新不会抢走焦点，新回答不额外加入 Tab 顺序。
- CS 7800 只作为先修叶子跳转的示意详情；原稿未给完整正文，已明确标出 fixture / 未建模，不冒充完整官方条款。

## 版本兼容例外

依赖均用 `npm install --save-exact`，直接依赖不带 `^`，完整依赖树由 lockfile 锁定。没有 `--force`、`--legacy-peer-deps` 或关闭 lint 来绕过冲突。

2026-10-21 核对 npm registry 后，React 19.3.1、React Router 7.18.4、Vite 8.3.5、Vitest 5.0.5 等使用当前稳定版；有两项必须明确偏离“全用最新稳定版”：

- `typescript-eslint@8.72.0` 的 peer 支持范围是 TypeScript `<6.1.0`，所以使用范围内最新的 `typescript@6.0.3`，而不是 7.0.2。
- `eslint-plugin-jsx-a11y@6.10.2` 的 peer 最高声明 ESLint 9，所以使用 `eslint@9.39.5` 与匹配的 `@eslint/js`，而不是 10.13.0。**ESLint 9 已停止官方支持，`npm ci` 会有 deprecated 提示**；这不是零 lint 警告的同义词，也不能用 audit 无漏洞来代替官方支持。独立验收需确认此兼容性例外，待插件支持后升级。

Node 类型固定在 24 系列，与规定运行时一致。实际命令版本与验证结果见 [WORKLOG.md](WORKLOG.md)。

## 无障碍与验收边界

每页有 `vitest-axe` 测试；jsdom 没有真实布局和 canvas，测试只关闭不能可靠运行的 `color-contrast`，不关闭其他 axe 规则。对比度另按 token 数值检查；真实键盘顺序、焦点、移动布局和表格滚动仍须浏览器验收，不能从 jsdom 结果推断。

Radix Select / Dialog 保留原生键盘和焦点管理；测试不替换这些组件。只有 jsdom 缺失的 pointer capture、scroll、ResizeObserver 做最小兼容，fetch 在测试中被禁止。

已知限制：当前浏览器控制接口没有完整请求瀑布读取能力，不把可读到的请求列表等同于完整网络面板验收。R2b 起页面只经 `src/api/client.ts` 请求 API（`contracts.test.ts` 钉住别处不许调 fetch），最终验收仍需确认此外只有同源静态资源。

R1 的修改经过、命令结果、浏览器覆盖和未完成边界在 [WORKLOG.md](WORKLOG.md)，Co-op 独立记在 [COOP_WORKLOG.md](COOP_WORKLOG.md)，R5b 记在 [COMPARE_WORKLOG.md](COMPARE_WORKLOG.md)，R5c 记在 [PRIVACY_WORKLOG.md](PRIVACY_WORKLOG.md)。本轮不执行 push、PR、合并或部署。
