# NEU-Compass · React 本地原型

这是新前端的本地原型：长得对、点得动，大部分页面已经接上真实接口。R2b 起登录、登出和「现在是谁」是真的（见下面「接口层与登录 R2b」），R5d 起 Co-op、课程对比、数据与隐私三页也是（见「Co-op、对比、隐私接真实接口 R5d」），R3e 起搜索和课程详情也是（见「搜索页和课程页接真实接口 R3e」），R4c 起培养方案也是（见「培养方案页接真实接口 R4c」）。不是已经迁移完成的产品，也不替代线上 Streamlit。

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
npm.cmd run preview:dev-api
```

预览地址为 `http://127.0.0.1:4173/`。`build:dev-api` 构建的页面连本机的开发 API，放在 `dist-dev-api/`。`npm.cmd run build` 是给学生用的正式构建，连正式 API（只认 https），放在 `dist/`，用 `npm.cmd run preview` 预览；在本机预览时，登录和各页的请求都不会成功。两种构建分两个文件夹放，`dist/` 里就只会有连正式 API 的构建，不会把连本机的那份当成正式的交出去。两个服务都只绑定本机，没有代理。本机用的 API 怎么起见下面「接口层与登录 R2b」。`node_modules/`、`dist/`、`dist-dev-api/` 和本地 `artifacts/` 不提交。

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
- `test:mutations` 在系统临时目录创建隔离副本，先验证未修改副本的完整测试和类型，再执行 152 个具名变异。每项只运行对应名称的行为测试，避免重复执行整份表单用例；原 R1、Co-op、R5b 检查保留，R5c 另加 26 项，R3a 另加 M111–M130，R3b 另加 M131–M152（M64 仅将同一四门上限的变异锚点改到共享常量）；R3e 把指着已删原型的 M19、M23 和「允许保存」挪走以后的 M12、M18 改到新的搜索状态和搜索页上，M18 改成测「问完不复位」。副本里除了 `src/` 和配置，还有测试要读的 `index.html`、`openapi.json` 和生成器的 `package.json`（R2b）。完整基线测试最多等 120 秒，单个变异仍为 45 秒。不修改当前源码、不安装额外依赖。只把命中预期测试名称的真实断言失败算作杀死；超时、导入失败不算。类型变异要求命中缺失 label 的编译断言。
- 变异日志、失败测试名、源码 SHA-256 与结果位于 `artifacts/mutations-<UTC timestamp>/`。副本在进程退出时删掉（跑完，或者中途出错，比如基线没过、锚点对不上）：先删每份副本的 `node_modules` 联接，再删副本，不会碰到联接指着的东西（R4c；原来每跑一次就在系统临时目录留一个 `neu-compass-r1-*`）。按 Ctrl+C、从外面结束进程或者机器重启时走不到这一步，副本会留下，删之前先删里面的联接。
- `.github/workflows/ci.yml` 的前端 job：Node 24 → `npm ci` → 装生成器 → `gen:api:check` → 格式 → `check`；Python job 另查 `web/openapi.json` 是最新的（R2b）。远端是否绿色，必须在后续授权 push 后由 GitHub 验证，不能从本地检查推断。

## 路由与演示

| 路径                  | 内容                                                                                    |
| --------------------- | --------------------------------------------------------------------------------------- |
| `/`                   | R3e：没提问时是落地内容（项目、入门推荐、最近的 Co-op、示例问题），提问以后是真实的对话 |
| `/course/CS-6140`     | R3e：解析课号，取详情和先修；桌面左边对话、右边详情，再窄一栏，手机上只显示课程         |
| `/?course=CS-5800`    | R3e：旧链接，换成 `/course/CS-5800`，不多一条历史                                       |
| `/compare`            | R5d：对比列表里的课各取一次真实接口；R3e 起课程页的「加入对比」往里加课                 |
| `/coop`               | R5d：按「现在是谁」取真实的 Co-op 列表，登录的人能投稿                                  |
| `/programs`           | R4c：真实的培养方案列表                                                                 |
| `/programs/cs-ms`     | R4c：一个项目的课程表；选方案、看政策证据，选择换页保留                                 |
| `/?program=cs`        | R4c：旧链接，按 ID 或前缀找到项目，换成它的页面                                         |
| `/?plan_v=1&…`        | R4c：旧的方案链接，打开那个项目，方案和版本都对得上才选上                               |
| `/privacy`            | R5d：真实接口给的隐私说明，登录的人能删号                                               |
| `/compare-demo`       | R5b 合成 API 课程对比，默认四列；七项信息、独立失败状态、移出与清空                     |
| `/coop-demo`          | R5a 合成 Co-op 列表、等级展示、投稿表单与结果演示                                       |
| `/privacy-demo`       | R5c 接口形状的合成隐私说明、确认删除与四类结果演示                                      |
| `/course-detail-demo` | R3b 合成课程详情、四种对比状态及原样接入的 R3a 先修面板                                 |
| 其他                  | 404 与返回首页链接                                                                      |

课程页的路径用横线，例如 `CS-6140`；项目页的路径就是项目 ID，例如 `cs-ms`。独立演示的数据见各节，均不含真实用户数据。

标题、导航当前项和搜索输入框共同使用 Router 的路径匹配规则：已匹配页面的尾斜杠 / 主路径大小写变体仍显示一致的页面状态；无效子路径显示客户端 404，不混入搜索控件。这些地址都原样保留、不重定向，课号也不另外归一化；换地址的只有旧链接：`?course=`、`?program=` 和方案链接（见路由表）。客户端 404 展示不等于服务器 HTTP 状态码验收。

## 状态边界

- 对话、项目和方案的选择放在路由之上（R3e 的 `SearchContext`），页间跳转不会丢；换项目会清掉方案。对比页不提供方案选择。没有持久化到 localStorage、Cookie 或后端，整页刷新就没了。
- 课程页的「加入对比」R3e 起真的加进对比列表。
- 对比列表是 course ID 的内存 store，侧栏和顶栏读同一份；R5d 起它就是学生真正的对比列表，登出和删号时清空。演示外壳 `/compare-demo` 用自己的一份：首次进入或切换场景才填入示例；同一场景离开再返回，不会复活已移出／清空的课程。
- 侧栏和手机菜单的登录、登出从 R2b 起是真的（见「接口层与登录 R2b」）；R5d 起 Co-op、对比、隐私三页用的也是这个身份，Co-op 页上的登录就是侧栏的登录，R3e 起搜索页的对话也按这个人保留。三个演示外壳还用自己的演示身份。
- 提问是真的 `/chat`（R3e 一节）；对着开发 API 时回答是脚本给的，不调用模型。
- 课程页的分享框给这门课的网址，只读，不复制、上传或发布任何内容。侧栏的「刷新页面内容」R5d 起真的重取（见 R5d 一节）。

## Co-op R5a（2026-10-22）

按评审目录 `frontend_react/R5_COOP_SPEC.md` 实现，替代最初仅浏览的草稿；**不接真实 API、登录、取数或缓存**。R1 提交保留在 `feat/web-skeleton`，本批在 `feat/web-coop`。R2 后续连接回调，不需要重写页面的表单 / 展示逻辑。

`src/api/coop.ts` 暂手写说明书的接口类型。`CoopPage` 只接 `viewer`、`list`、`onRetryList`、`onSubmit`、`onLogin`；不读取 URL 或修改贡献数。`CoopDemoPage` 单独承担本地演示参数、通知和 400ms 延迟。登录按钮只显示“未发起真实登录”的本地提示，不伪造登录。

| `/coop-demo` 参数 | 可选值 / 默认                                                                                                                             |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `viewer`          | `guest`（默认）、`member0`、`member1`、`member2`，直接选择对应 API 导出列表                                                               |
| `list`            | `ready`（默认）、`loading`、`error`、`empty`                                                                                              |
| `submit`          | `pending`（默认）、`duplicate-pending`、`duplicate-approved`、`duplicate-published`、`duplicate-rejected`、`401`、`422`、`503`、`network` |

例如 `/coop-demo?viewer=member0&submit=duplicate-approved`，或 `/coop-demo?viewer=guest&list=error`（R5d 以前是 `/coop`）。页面顶部也有三个演示选择器。未知访客回退游客，未知状态回退正常列表 / pending；旧草稿的 `demo=coop-*` 不再使用。演示重试只恢复正常合成列表。

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

`/compare-demo?case=<值>`（R5d 以前是 `/compare`）可直接切换，页面顶部也有原生「演示场景」选择器；缺省及未知值回退 `four`。

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

`/privacy-demo`（R5d 以前是 `/privacy`）默认游客、90 天说明、成功结果场景。参数也可用页面顶部三个选择器切换：

| 参数      | 值                                                                                                                  |
| --------- | ------------------------------------------------------------------------------------------------------------------- |
| `viewer`  | `guest`（默认）、`member`                                                                                           |
| `privacy` | `90-days`（默认）、`no-cleanup-off`、`30-days`、`no-cleanup-contact`、`loading`、`error`、`network`、`unrecognised` |
| `delete`  | `ok`（默认）、`ok-nothing`、`401-stale`、`401-gone`、`403`、`422`、`503`、`network`                                 |

例如 `/privacy-demo?viewer=member&privacy=30-days&delete=503`。未知值分别回退 `guest` / `90-days` / `ok`；`network` 删除场景模拟抛错。删除和重试均等 400ms，重试回到原来的合成响应，不假装联网成功。

- **文本唯一来源：** intro、每段标题／句子、delete_what 全部来自原始 body；不在组件重写保留天数、邮箱或政策文字。10 份 JSON 原字节复制，独立 SHA-256 测试锁定，单独跳过 Prettier。query_log_notice / capture_notice 只声明类型，本页不显示，留给 R3。后端提供的 👍／👎 作为原句的一部分保留，不拿 emoji 代替 UI 图标；标题用 Lucide Lock。
- **整页校验：** 只校验本页实际使用的字段，其他键忽略；sections 必须非空，每个标题、每句都是字符串。有一处不对就只显示固定失败提示和重试，不展示半份隐私说明，也不开放删除。加载选择文字「正在加载」，避免虚构政策内容。
- **删除与结果：** `PrivacyPage` 只收 props／回调；`AccountDeletion` 管确认、同步锁、pending 和卸载保护，结果状态在页面上层。成功／401 只调用一次 onSignedOut；null／502／503／504／抛错为不确定；403／422／429／500 等保留“什么也没删”。原文 detail 和行数不展示。
- **结果保留选择：** 外部 viewer 从登录变游客时，表单消失但结果与焦点保留；再登录时新的表单默认未勾选，旧结果保留为最近一次操作结果，不重新抢焦点。下一次删除开始才清掉旧结果。卸载、隐藏表单或说明变无效后才回来的旧请求结果不回灌。
- **文案偏离已获用户批准：** 不确定结果改为「这次没收到服务器的确认，不确定删除有没有完成。刷新后若仍是登录状态，可以再试；若已变成游客但需要确认，请联系维护者。」原稿“变成游客了，就是已经删掉了”不成立，cookie 失效也会成为游客。其余三句结果沿用原稿。本轮不改另一分支的后端／Streamlit 或外部说明书。
- **演示身份不等于登录：** 删除成功或 401 只改变本地演示身份，不改 URL；选择器显示 URL 中的初始化场景，当前状态另有一行明确显示。显式切换任意参数会开始新的演示场景并清除旧结果；模拟删号导致的身份变化不会重建页面。全站身份、Cookie 和其他页面 store 的清空留给 R2b。
- **安全／布局：** 所有接口文字都是 React 纯文本，邮箱／网址不自动成链接；不写 storage，不输出 console。删除区始终在四段之后，确认 label 的触控区不小于 44px；结果是可聚焦 status，正文长句换行，两种验收宽度均无整页横向溢出。

这一节说的是 R5c 的演示页（R5d 起在 `/privacy-demo`），它仍是合成演示，**没有执行任何真实删号、登录／退出、请求或数据库操作**；`/privacy` 接真实接口见「Co-op、对比、隐私接真实接口 R5d」。真实 R2b 接入必须负责响应校验（特别是 200 的 deleted）、请求体 `{"confirm":"delete"}`、Cookie／Origin／X-NEU-Compass 及会话边界；不能照搬 URL 演示身份作为鉴权，也不能随 viewer 重建 PrivacyPage 丢掉结果。真实请求瀑布、实际删号、屏幕阅读器语音及上线仍需单独验收。

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

## R3b 课程详情组件与演示（2026-10-23）

从 `origin/feat/web-requisites @ 87f96d8` 开 `feat/web-course-detail`，只改 `web/`，无新增依赖。按 `frontend_react/R3B_COURSE_DETAIL_SPEC.md` 实施；保留原型 `/course/:code`，R3a 组件、模型及测试不改。沿用 Sites 本地开发／预览流程，不注册托管、不发布。

`/course-detail-demo?case=cs-6140-everything&compare=empty` 不加入导航。顶部「演示数据」列出九份导出；`case` 缺省或未知回退 `cs-6140-everything`。`compare` 为 `empty`（空）、`has`（已有／两门）、`full`（满且没有这门）、`full-with`（满且已有），缺省／未知回退 `empty`。切换任意参数都会重建详情，清空折叠状态及结果；两个回调只写 status，不跳转、不改变对比列表。

- **组件与数据边界：** `features/course-detail/CourseDetail.tsx` 只收 unknown 课程、只读对比列表及两个回调；展示辅助组件同目录。`models/courseDetail.ts` 独立校验各字段；只有身份错误才整页拒绝。列表有一个坏项就整块不显示，不偷偷保留半份。R3a 原始参数透传、以 course ID 为 key；不在这页重写先修规则或判断能否注册。
- **格式化复用：** `models/courseDetailFormat.ts` 复用 R5b 的 `generalNumber`／`when`／精确二进制 `scaledEven`，避免另写一套数字和日期算法；只额外导出已有函数，不改其行为。百分比先做浮点乘法再取偶数，置信度精确取两位；合法负零保留 Python 的 `-0%`／`-0.00`，不改变「支持值」明确要求的 JS String 规则。单行文字照 Python 全套 `splitlines()`，标签值和 AI 备注只去 CR，其余原文保留空白。
- **目录与证据选择：** 目录采用 Python 的可选字段默认值（省略 description／credits／retrieved_at 为 null，省略 prereq_codes 为 []，显式 null 的 prereq_codes 仍无效）。忽略额外键；坏快照不显示描述和链接，仍保留其他来源说明和引文。ID 不合摘要格式并不意味着整份快照无效，只标「格式异常」且没有完整 ID 悬停提示。未用于展示的 program_id 不额外限制，缺省统一为空串。
- **展示选择：** 主题／技能不复用 R1 八项截断的 Chips，全部显示、保持顺序与重复项；未知方案关系按说明书落到 foundation。对比四门上限复用 `models/compareList.ts` 的 `MAX_COMPARE_COURSES`，已有优先于满额。使用原生 details，默认收起；只读纯文本，不解析 HTML、Markdown 或正文网址。只有校验通过的两个官方目录链接可跳出，新标签页带 `noopener noreferrer`。
- **数据冻结：** 九份 API 导出及九份 Python 标准答案原字节放在 `fixtures/course-detail/` 与其 `expected/`，SHA-256 测试锁定全部 18 份；该目录单独跳过 Prettier。expected 仅用于测试、不进入 bundle；12 个 scenario 从实际 DOM 核对种类、文字、顺序、折叠层级、链接、title 和按钮状态，不拿标准答案生成页面。
- **真实交互的覆盖边界：** 九份导出都没有年度规则文档或可导航旧边。因此浏览器不能从这些固定数据点出「打开课程」；测试中另注入有效关系，经真实 R3a 面板验证课号回调、课程切换与选择重置，不改原始 JSON、不加演示专用假按钮。

完整修改索引、浏览器证据、具名变异及未完成边界见 [COURSE_DETAIL_WORKLOG.md](COURSE_DETAIL_WORKLOG.md)。这不是 R3 真实取数／resolver／分享链接集成；不宣称已部署、线上验收或完成真实网络瀑布检查。

## 接口层与登录 R2b（2026-10-23）

从 main 开 `feat/web-api-client`，依据评审目录 `frontend_react/R2B_PLAN.md`。这一批让前端第一次真的请求 API：接口层、登录和登出、聊天流的客户端；各页的内容还是假数据，隐私、Co-op、对比三页在 R5d 接上，搜索和聊天页在 R3。

**本机怎么跑：** 起两个服务，都在 `127.0.0.1`。

1. 开发用的 API：在仓库根目录（WSL）用项目的 Python 环境运行 `uv run python -m tests.support.dev_api`，监听 `127.0.0.1:8000`；没有 `.env` 时先设一个占位的 `GEMINI_API_KEY`（设置要求有这一项）。它是真的 `create_app()`，但用临时文件里的合成数据库、测试套件的替身模型，Google 换成本机的假登录页 `/__dev/google`（五个合成账号，R5d 加的两个有贡献，见 R5d 一节；三种被拒、state 不对和取消各一个链接）。除了 Gemini 的 key，每个设置都从代码里的默认值开始，`.env` 和环境变量里的限流、数据路径之类不起作用；访问日志和生产一样去掉登录地址的查询串、课程只记路径模板。每次启动换一个会话密钥，重启就都登出了。不部署，生产代码不 import 它，API 里也没有测试模式。
2. 本页：`npm.cmd run dev`，打开 `http://127.0.0.1:5173/`（不要用 `localhost`；5173 被占时换端口，见 R3e 一节）。预览构建用 `npm.cmd run build:dev-api` 再 `npm.cmd run preview:dev-api`。

页面和 API 的主机名必须一样：浏览器按主机名算「站点」，`localhost` 和 `127.0.0.1` 是两个站点，SameSite=Lax 的会话 cookie 就不跟着请求走，登录了也像没登录。Chromium 在 `http://127.0.0.1` 上收 `__Host-` 开头、带 Secure 的 cookie（10-23 在浏览器里验过）。

- **API 地址在构建时定**（`src/api/apiBase.ts`）：`npm run build` 是正式构建，默认 `https://api.neu-compass.me`，`VITE_API_BASE_URL` 可以换成别的 https 地址，本机的 http 一律让构建失败，免得给学生的页面去连他们自己的电脑；`npm run build:dev-api` 和开发服务器默认 `http://127.0.0.1:8000`，前者输出到 `dist-dev-api/`，不和正式构建的 `dist/` 混；别的构建模式（比如 beta）必须写明 `VITE_API_BASE_URL`。测试一律用本机的，不管环境里设了什么。地址只认 https 或本机的 http，不带路径、查询、`#` 或账号密码，坏值让构建失败。`web/.env.local` 这类文件已在 `.gitignore` 里。
- **接口类型是生成的：** 后端的 `scripts/export_openapi.py` 导出 `web/openapi.json`，`npm run gen:api` 从它生成 `src/api/schema.ts`，`npm run gen:api:check` 和 CI 查两者一致；后端那边 CI 也查 `openapi.json` 是最新的。生成器 openapi-typescript 7.13.0 只声明支持 TypeScript 5，本包用 6，所以它单独放在 `tools/openapi-types/`（自带 TypeScript 5 和 lockfile），没有用 `--legacy-peer-deps`。R3a 的先修类型（`src/api/requisites.ts`）比生成的窄，按 kind、status 分开，所以还是手写；`src/api/requisites.types.test.ts` 在类型检查时把它们和生成的类型对照：面板读的字段 API 得有，API 可能给的值面板得收。R3b 的课程详情类型（`src/api/course.ts` 的 `CourseDetailBody` 等）也留手写：生成的类型把有默认值的字段都标成可选（API 其实都会给），页面要的是每个字段都在；`src/api/course.types.test.ts` 照同样的办法对照，两份共用 `src/test/misfits.ts`。
- **请求只有一个出口：** `src/api/client.ts`。每个请求都带 cookie、不用 HTTP 缓存、不跟重定向；写请求带 `X-NEU-Compass: 1`，有请求体才带 JSON 的 Content-Type。四档超时照 Streamlit（5／8／15／30 秒，读完回答也算在内），什么都不自动重试。失败变成 `ApiError`（状态码、`error_type`、`Retry-After`、422 被拒的字段名、登录被拒的 `reason`），不带后端的英文原文；页面上的中文照 Streamlit。
- **取数：** TanStack Query，不重试；切回窗口、网络恢复都不重取。断网时请求照样发出、照样失败，不会排队等网络回来再自己发（写请求尤其不能这样）。暂时的失败（超时、429、5xx）继续显示上次的内容，明确的答复（401、404、422…）不留。`/config` 5 分钟内算新鲜；`/auth/me` 的 401 就是游客。
- **登录：** 点按钮时生成 32 字节的随机 state，和回来的页面一起放进 sessionStorage（本站只在这里存东西，用一次就删），整页去 Google（只认 Google 的登录页；页面连本机开发 API 时也认它的假登录页）。回到站点根路径时先把 code 和 state 从地址栏和历史里去掉，这时还不问 `/config`、`/auth/me`；再核对 state，对了才用 cookie 模式提交回调，然后重读一次 `/auth/me`：读到游客就说「登录状态没有保存下来…」，读失败就保留回调给的身份，最后回到原来的页面。state 对不上的返回链接（包括带 `error=` 的）什么都不发、也不显示链接里的字。外校邮箱和没验证的邮箱分开说，别的失败一句话。登录、登出时清掉按身份取的数据，登出时再清课程对比。
- **Referrer：** `index.html` 设 `strict-origin-when-cross-origin`，发给别的站点的只有本站的来源（R0 14.15；R7 在服务器上再设一次）。
- **焦点：** 账号框里按下的按钮忙完以后（登出换成登录按钮、失败恢复原按钮），焦点回到账号框现在的按钮上（桌面侧栏和手机菜单里都一样，和结果同一次渲染完成），用户自己移开了就不动。从 Google 页按「后退」、浏览器原样恢复本页时，登录按钮恢复可用。
- **聊天流：** `src/api/chatStream.ts` 的 `streamChat(request, { signal })` 边收边读 `/chat` 的 NDJSON，给 R3 的搜索和聊天页用；它是 `client.ts` 以外唯一调 fetch 的文件。先 `meta`，再若干 `token`，最后 `done`（可能带反馈凭证，由页面照 Streamlit 的做法核对）；或者中途一个 `error`，它的 `detail` 是 API 给学生看的固定中文，照样显示。等回答开始、等下一块各最多 30 秒；断线、超时、没有 `done` 就结束、有一行不是这四种事件、或者一行（不算行尾）长过 100 万个字符（API 最长的一行也就几十 KB），都在已经收到的内容后面补一句 Streamlit 的话（「连接中断。…」或「回答流未完整结束；…」）。流开始前的失败和别的请求一样是 `ApiError`。不自动重发（每问一次都算模型次数、写查询日志）；能取消。
- **开发 API 的聊天：** `/chat` 按脚本回答，不调用模型，HyDE 补救也关着。问题里带 `dev:model-error`（模型中途出错）、`dev:no-answer`（没有回答）、`dev:daily-limit`（今天的次数用完）、`dev:no-done`（流没有 `done` 就结束）、`dev:cut`（连接中途断开）、`dev:stall`（停 35 秒，比前端等的久），就换成对应的情况。
- **测试：** 渲染整个 App 的测试套 `src/test/withApi.tsx` 的 `WithApi`，它预先放好 `/config`、游客身份和顶栏的 `/ready`（R3e），外壳不再发请求（`fetch` 在测试里仍被禁止，要用就 stub；R5d 的接线测试用 `src/test/fakeApi.tsx` 回答页面自己的请求）。
- **上线前（R7）：** Google OAuth 客户端要把新前端的地址（来源加 `/`）加进 Authorized redirect URI，API 的 `WEB_ORIGINS` 也要设成它，不然 Google 或 API 会拒绝。

## R3c 搜索回答区与演示（2026-10-24）

从 R3b `f2cf032` 开 `feat/web-search-answer`，只改 `web/`，无新增依赖。`courseDetail.ts` 的 `catalog` / `evidence` 仅增加 export，独立提交 `4a9d008`；原型搜索页及 R3a / R3b 其他实现保持原样。完整索引、验证证据与返工记录见 [SEARCH_ANSWER_WORKLOG.md](SEARCH_ANSWER_WORKLOG.md)。

`/search-demo` 是不加入导航的 `React.lazy` 演示页。例：`/search-demo?case=feedback-receipt&feedback=on&speed=instant`。打开即播放，方便直接验收网址；「开始」从头重播。任何控件变更都卸载旧会话、abort 旧来源并清空反馈与展开状态，再按新选择播放。

| 参数       | 值及缺省                                                                                                                |
| ---------- | ----------------------------------------------------------------------------------------------------------------------- |
| `case`     | 32 个单轮 case（不含 `feedback-responses`）及 `conversation-followup` / `conversation-four-turns`；缺省 `alias-cs-6140` |
| `feedback` | `off`（缺省）/ `on`                                                                                                     |
| `reason`   | `on`（缺省）/ `off`，控制 409 是否采用导出的 proposed_reason                                                            |
| `vote`     | `saved`（缺省）/ `404` / `503` / `mismatch`                                                                             |
| `speed`    | `normal`（缺省）/ `slow` / `instant`                                                                                    |

未知值逐项回退缺省。正常速度 meta 前 400ms、每块及结束前 150ms；慢速乘四，立即为零。多轮依次播放；「查看」和追问只写演示 status，不导航、不提问、不修改对比列表。评价回调只返回固定合成结果，**没有真实接口请求或数据保存**。

- **分层：** `api/chat.ts` 手写消费类型；`models/` 放纯状态转换、历史窗口、受限正文解析、失败文案及 unknown 数据校验；`features/search-answer/` 放 `useConversation` 和展示组件。钩子只消费调用方的异步事件来源，负责同步忙碌锁、终态停止、异常、卸载取消和迟到事件隔离，不承担请求组装。会话、展开及评价均只在内存中。
- **加载与状态：** 等待时显示「正在查找相关的课…」，收到 meta 后无正文显示「正在生成回答…」；相关课程随 meta 出现，最多三门默认展开。进行中的回答带 `aria-busy`，整个对话用一个隐藏 status 宣告开始／终态，不逐字播报。每轮保留自己的课程与错误，追问只放在最后一轮。
- **正文与安全：** 不引入 Markdown 库，按 Python 参考实现受限子集，所有内容由 React 文本节点呈现；标题用有样式的段落，代码与长网址可折行。只有严格通过校验的官方 HTTPS 目录／方案来源链接可点击，带 `_blank` 和 `noopener noreferrer`。学生问题、课程与方案文字不解析 HTML 或 Markdown。
- **数据及数值：** 复用已有目录／证据校验器和精确取偶算法。分数 `.3f` 保留负零，条宽先浮点乘 100 再除 top，取偶并限制在 8–100；不拿 `toFixed` / `Math.round` 代替。meta 有一门课坏掉时整组拒绝；先修年份或方案位置不合法时只隐藏对应部分。方案标签的重复 ID 按 Python 字典取最后一条，保留原列表顺序与重复项。
- **评价：** 三字段凭证严格无额外键，完成且允许保存、正文非空时，异步核对原始 UTF-8 正文的 SHA-256 再显示。按字段而非对象身份识别凭证变化，避免原地修改对象沿用旧校验。只发四字段；仅精确匹配的成功响应更新已记录评价，失败保留旧记录；pending 禁止重复操作，卸载后丢弃回复。
- **固定数据：** 33 份导出和 36 份标准答案原字节放在 `fixtures/search/` 与 `expected/`。69 份 SHA-256 全部锁定、跳过 Prettier；expected 只供测试，不导入生产。50 个 scenario 核对实际 DOM、折叠默认值、层级、文案、按钮、链接、时序与下一次请求；86 个正文向量另测解析结构和真实元素。

在 Windows Node 24 下从 `web/` 执行：

```powershell
npm.cmd ci
npm.cmd run check
npm.cmd run format:check
node scripts/search-mutations.mjs
npm.cmd run test:mutations
npm.cmd run preview -- --port 4173 --strictPort
```

前一个变异脚本是 R3c 的 36 个具名变异，后一个保留现有 152 个回归变异；均在临时快照运行并核对工作源文件未变。完整网络瀑布、屏幕阅读器语音、真实 `/chat` / `/feedback`、方案选择、停止、分享及生产集成另行验收。本轮只有本地提交，不推送、不建 PR、不部署。

## Co-op、对比、隐私接真实接口 R5d（2026-10-24）

从 main `4797a32` 开 `feat/web-pages-api`，依据评审目录 `frontend_react/R5D_PLAN.md`。`/coop`、`/compare`、`/privacy` 换成接真实接口的外壳（`src/pages/CoopRoute.tsx`、`CompareRoute.tsx`、`PrivacyRoute.tsx`），页面本身还是 R5a、R5b、R5c 的；三个演示外壳挪到 `/coop-demo`、`/compare-demo`、`/privacy-demo`，内容不变。本机对着开发 API 跑，见「接口层与登录 R2b」。

- **外壳给页面的东西**（`src/layout/account.ts`）：页面用 `useAccount()` 读 `viewer`（还在确认时是 undefined）和 `unsure`（`/auth/me` 暂时失败），调 `login()`（侧栏的同一个登录）、`signedOut()`（删号成功或 401 以后：和登出一样丢掉按身份的缓存、清空对比，但不调 `/auth/logout`）、`contributed(count)`（投稿的 201 带着服务端的贡献数，数变了就当作换了访客，旧的按身份缓存一起丢）。
- **写操作前再问一次是谁**（`src/api/queries.ts` 的 `signedInNow`）：cookie 是所有标签页共用的，别的标签页可能已经登出或换了人。投稿和删号发出去之前先问 `/auth/me`（最多 8 秒）。明确是别人或没人登录，两样都不发，照「这个登录已经失效」处理；问不到时投稿照发，删号不发（不可撤销），说「什么也没删」。
- **刷新按钮**：侧栏的按钮改叫「刷新页面内容」，所有读过的内容都过期，正在显示的马上重取；`/auth/me` 只在失败过时重读（身份只在登录、登出、投稿和整页刷新时变）。
- **「显示的是上次的版本」**：正在显示的内容因为暂时的失败（408、429、5xx、连不上、读不懂）留着上次的版本时，`<main>` 最上面说一句「有些内容这次没能更新，显示的是上次加载的版本；可以点「刷新页面内容」再试。」（Streamlit 的 `FALLBACK_NOTICE`，后半句改了：新前端不会自己再试）。不在屏幕上的内容不算。
- **Co-op**：键 `['viewer', 身份, 'coop']`，身份是 `guest`、`member:{user_id}:{贡献数}` 或 `unsure`，还不知道是谁时不发；按游客显示的时候（游客或 `unsure`），API 照 cookie 给出的面试、技术题、薪资也按游客清掉，缓存里也不留。每次进这一页都重取，中间先显示上次的；`GET /coop` 等 30 秒。列表有一行不对就整份当作读不懂。投稿 `POST /coop`（30 秒，不自动重试）成功以后，用服务端给的贡献数更新侧栏和等级，列表跟着重取，投稿结果那句还在（页面按登录的人给 key，不按等级）。失败只给页面 R2b `ApiError` 的状态码、`error_type` 和被拒的字段名，API 的原文到不了页面；连不上、超时、代理页面、读不懂和 503 都说「投稿暂时提交不了，请稍后再试。你填的内容还在。」。
- **对比**：列表里的课（最多 4 门）各取一次 `GET /course/{course_id}`（30 秒），每次进这一页都重取；一门课失败只坏那一列，「重新加载」只重取失败和读不懂的列。`src/models/compareList.ts` 改成 `createCompareList()`：页面用原来那一份（导出的名字不变），演示外壳用自己的一份，演示不再改学生真正的对比列表。加课的按钮在课程详情上，R3e 接上了（在那之前真实的对比页是空的）。
- **隐私**：`GET /privacy`（8 秒），5 分钟内不重取。删号 `POST /auth/delete-account`，请求体正好是 `{"confirm": "delete"}`（15 秒）；200 要读得懂才算删了，读不懂当作不知道删没删。删完或 401，本页变成游客，删除结果留着（页面不按访客给 key）；登出由路由来做，删号路上离开了这一页，回答到了也照样登出（结果那句就看不到了）。
- **开发 API 的 Co-op**：合成库里有七条 Co-op 记录，三条策展种子（0、1、2 级各一），两组照真的审核流程公开的投稿（每组两个投稿人）。假 Google 页多了 `dev-one`（1 次贡献）和 `dev-two`（2 次贡献），贡献是审核公开时真记的功。删号在临时库上照真的走：删掉 `dev-two`，它参与公开的两组都只剩一个投稿人，一起撤下，列表只剩三条种子，`dev-one` 的贡献不收回。重启就都回来了。
- **测试**：`src/test/fakeApi.tsx` 按方法和路径回答、记下每个请求，连查询串一起（测试里 `fetch` 照旧要 stub）；`src/test/timeouts.ts` 查一个请求正好在它那一档超时上放弃。项目的 `test:mutations` 还是 152 个，M35、M54、M55、M79 跟着代码改了锚点和测试名。
- 演示外壳没有改成懒加载（方案里写了要改），和 `/requisites-demo`、`/course-detail-demo` 一样直接加载；首屏 JavaScript gzip 186,015 字节（预算 250,000）。

修改经过、验证和已知的问题在 `docs/development-change-log.md` 第 35 节。

## R3d 搜索落地内容与演示（2026-10-24）

从已合并 R3c / R2b 的 `4797a32` 开 `feat/web-search-landing`，仅 `web/`，无新增依赖。R3a–R3c 的模型、组件、测试及数据只 import，不改。独立修改记录与验收边界见 [LANDING_WORKLOG.md](LANDING_WORKLOG.md)。

入口 `/search-landing-demo?scenario=guest&speed=instant` 不加入导航，页面与演示外壳均 `React.lazy`。`scenario` 为顶部「数据」里的 27 个场景，缺省／未知回退 `guest`；`speed` 为 `normal`（缺省）、`slow`、`instant`、`forever`，未知回退正常。正常项目列表 300ms、有效精选课程表在它之后再 300ms、Co-op 450ms；慢速乘四，立即零延迟，一直加载不安排计时器。

- **共享边界：** `api/load.ts` 是三态 Load 与基于 R2b 的 ApiFailure；`api/programs.ts` 和 `models/programs.ts` 放完整项目消费类型及列表／课程表校验，给 R4a 原样复用。`programs.types.test.ts` 将四层消费类型逐一对照生成 schema，不能只测顶层而遗漏数组元素。
- **展示与派生：** `SearchLanding` 无状态，只接数据和回调；`landingView` 一次派生区块、pending、单一重试提示。项目和 Co-op 独立；入门推荐等所有「精选且在列表里」的课程表有结果再画。只挑第 1 学期的第一门 core / foundation；Co-op 仅校验并显示前两条，不读取第三条。
- **失败处理：** 普通 fixture failure 先构造 ApiError 再复用 `isTransientError`，没有用强制断言冒充实例。只对 408、429、5xx 显示一次重试；明确失败、空数据、坏形状不显示重试，其他已就绪区块照常显示。
- **演示会话：** 来源调度在 `useLandingDemo`，不进入产品组件；换任一控件／重试／返回都用 key 重建会话并取消旧计时器。重试重播同一份合成失败，不假装联网成功。项目、课程、Co-op 按钮只写 status；四个示例发送 query 而非 label，以 R3c 的真实钩子／展示组件播放四份 chat-sample，正常速度、允许保存 false、反馈关。第一轮一创建即隐藏落地内容并接续焦点，被拒／出错也不会重新显示落地内容。
- **演示壳隔离：** 新增 `features/demo/OfflineDemoShell` 复用原侧栏、顶栏及布局 CSS，固定游客与不可登录状态，完全不挂载 useSession。这样生产构建的本演示路由不会因外壳读取 `/config` / `/auth/me` 而访问公网；不依赖测试 WithApi 的预填缓存，也不改真实 AppShell 或全局 fetch。member 场景仅模拟 Co-op 返回体，不改变真实账号或共享缓存。
- **纯文本与排版：** 沿用浅色 tokens 和 CourseCode，项目标签用现有 oneLine；卡片／Co-op 值仅去 CR，LF 保留为换行，其余文本不解析 HTML 或 Markdown。本区没有链接。桌面最多四列项目、三列课程、两列示例，手机一列；长课号、课名与公司可折行。列数照说明书第 8 节的上限固定为 4／3／2（Streamlit 按项目数分列），不满一排时右边留空。加载时只有一行「正在加载推荐内容…」，发现区带 `aria-busy`，没有转动的图标或骨架，先到的块先画。
- **固定数据：** 31 份导出、30 份 expected 原字节冻结，独立 SHA-256 测试；expected 只供测试，生产场景来源映射单独手写并与 27 个参考场景核对，不从标准答案生成页面。27 个 DOM 场景及 11 / 11 / 16 个向量之外另测坏形状、时序、焦点、取消和冷启动无请求。

使用已有 Node 24 环境：`npm.cmd run check`、`npm.cmd run format:check`、`node scripts/landing-mutations.mjs`。本轮新增变异工具在临时副本验证行为与生成类型漂移，副本包含 R2b 生成器、独立依赖链接和 Prettier 配置；超时、导入失败或无具名断言不能冒充 kill。预览为 `npm.cmd run preview -- --port 4173 --strictPort`。

R1 原型首页、真实请求／缓存、允许保存勾选、路由跳转、R4a 培养方案页均留给后续约定批次。浏览器控制没有完整网络瀑布接口，不能把无请求组件／空 QueryClient 测试替代为完整网络面板验收；详细证据与限制见独立记录。本轮仅本地提交，无 push、PR 或部署。

## 设计选择及差异

- 用户确认：沿用第一版白底细线与钴蓝强调色；导航以中文为主；R1 只做浅色，不做主题切换。原 R1 的「默认只看不同的行」已被 R5b 的「本轮不做行筛选」取代。
- `tokens.css` 只声明变量；产品 token 去掉设计稿的 `a-` 前缀。CSS Modules 使用 tokens，无内联布局样式；动态值只有对比列数及 R3c 分数条百分比，分别控制表格最小宽度和条宽。
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

## R4a 培养方案与政策证据演示（2026-10-24）

入口 `/programs-demo?scenario=cs-standard-ready&speed=instant`；默认 `scenario=list&speed=normal`。37 个场景，速度为 normal（300ms）、slow（1200ms）、instant（0ms 定时器）、forever。未知参数回默认；场景／速度变化重建演示会话。演示页懒加载并复用 R3d 的 OfflineDemoShell，不挂真实 useSession，所有数据来自原字节冻结的 75 份合成 JSON。`/programs` 正式页面由 R4c 接上（见那一节）；R4c 把只分享项目的地址改成了 `/programs/<ID>`，标准答案里的 31 处跟着改了，冻结的哈希也换了。

`features/programs/ProgramList` 和 `ProgramCurriculum` 只消费 Load 和回调，项目、方案选择及内容版本由外层控制；只让原生 details 保存展开状态。用 R1 Select 明确选择，单个方案也不默认选中；内部空选项使用不可能成为合法 plan_id 的 `__none__`，避免与真实 ID 冲突。演示的选择和请求计时放在外层：每次读取带一个只往上加的请求号，钩子只显示为当前名字、速度和请求号读到的结果，别的时候给加载中，所以选方案和刷新都在原地重新读取、不重建课程表，焦点留在选择框和按钮上（所选方案那一块按方案重建，它自己的折叠框重新关着，「分享这个培养方案」不变）；每选一次方案都重新读政策证据，选回之前选过的也一样。打开项目、回到列表、重试会换掉按下的按钮，焦点移到新显示的那一块（列表和课程表的 section 带 `tabIndex=-1`）。刷新清掉选择，重试重放同一份失败；换场景或速度仍用 key 从头来。

沿用 R3d 项目检查、R3a programTree / programRuleLines 与 R3b oneLine。`models/programGuard` 放日期、官方目录 URL 和范围比较；`programPlans` 做逐份检查与整组去重；`programPolicy` 查来源路径、身份、版本和顺序，忽略未来额外字段。政策 UI 先检查响应再核对所选方案，失败时保留方案规则。版本直接使用 planRevisions，不在 TS 重算 Python JSON 哈希。

`programFormat` 集中 Python 空白集合、范围文字和分享编码。空白集合含 Python 的控制分隔符，所以只对该正则局部关闭 no-control-regex；不使用 JS 的 `\s`。失败对象显式转成 ApiError 复用 R2b 文案。分享文字支持选中复制，只有已检查的官方目录／政策来源成为链接；所有数据文本保持原样，不解析 HTML 或 Markdown。

使用既有浅色 tokens，列表桌面两列／手机一列；规则、摘要、长网址和课程文本折行；手机上折叠框照 R3a、R3b 设回 `display: list-item`，保留 ▶/▼。加载时只有一行 `role="status"` 的文字（「正在加载培养方案…」「正在加载课程表…」「正在加载政策证据…」），没有转动的图标或骨架；政策还在加载时，所选方案的规则照常显示。组件中的标题、按钮、说明、链接、折叠框带 data-kind，测试读取实际 DOM 与 37 份标准答案比较，不用标准答案生成组件。修改索引与验证记录见 `PROGRAMS_WORKLOG.md`。本批不含草案判断、真实缓存／路由接线或后端 plan_revisions 改动。

## R4b 选课草案组件与演示（2026-10-26）

从 main `cbb91f7`（草案接口 #36 已合并）开 `feat/web-plan-draft`，只改 `web/`，没有新依赖。照评审目录的 `frontend_react/R4B_DRAFT_SPEC.md` 做；修改经过、验证和已知的问题在 `docs/development-change-log.md` 第 37 节。

入口 `/programs-draft-demo?scenario=standard-mixed&speed=instant`，不进导航；默认 `scenario=standard-mixed&speed=normal`。顶部「场景」列出 29 个场景，「速度」是正常（300ms）、慢（1200ms）、立即（0ms 定时器）、一直加载；认不出的参数回默认，换了控件就从头来。每个场景先按「第一次核对在路上」显示（核对中、没有回答、没有失败），到点换成场景自己的参数；本身就是核对中的场景一直是核对中。演示页懒加载，用 R3d 的 `OfflineDemoShell`（不发 `/config`、`/auth/me`，不发任何请求）；五个回调只在一个 `role="status"` 区域写一句（「演示：加入「…」」「演示：移除 …」「演示：清空草案」「演示：重新核对」「演示：这里会打开 …」），回答不变。上面一行是 R4a 的 `scopeLabel(plan)`。

- **分工：** `features/programs/PlanDraft.tsx` 是受控组件：草案（课程 ID）、最近一次回答、核对中、失败都由外面（R4 接线）给，组件只画、只调回调；自己的状态只有输入框里的字（「加入草案」以后保留，「清空草案」以后清空；直接换到另一份已核对的方案时还在，换到不能用草案的方案时组件什么都不画，字也跟着清掉，和 Streamlit 一样）。不写网址和浏览器存储，不发请求。`models/planDraft.ts` 放回答的检查和几个小函数（`parseDraftAnswer`、`draftTreeLines`、`creditsText`、`draftFailureMessage`、`canRetryDraft`），`api/draft.ts` 是手写的回答类型。草案接口已经在 main 上，所以 `api/draft.types.test.ts` 现在就把手写类型和生成的类型对照（说明书原本留给 R4 接线）。
- **R4a 只多一个参数：** `ProgramCurriculum` 的 `draft?: ReactNode`，选中了一份方案时原样放在方案块后面、「以下是旧课程表…」前面（R4a 说明书第 6 节第 9 步）；没选方案或没传就什么都不画，R4a 的演示和 37 个标准答案不变。放在方案块**后面**而不是里面：方案块按 `plan_id` 重建，放进去的话换方案会清掉输入框里还没加的字（Streamlit 在两份已核对方案之间切换时不清输入框，只有那次运行不画输入框时字才没了）；接线想按方案重来，可以自己给 key。
- **判断都在 API：** 页面不解析课号、不算规则，提示的句子也由 API 给。回答先照说明书第 4 节检查（参考是生成脚本里的 `answer_ok`；字数按码点；多出来的键不管），过了还要内容版本等于 `planRevisions[plan_id]`；不过就只有一行警告，一点都不显示。规则树照 Streamlit 的 `_tree_lines`，去掉 emoji；状态和运算的字用 `Map` 查，`constructor` 这样的种类查不到 `Object.prototype` 上的东西。失败照说明书第 8 节说中文、不显示 API 的 `detail`；409 的 `stale`、`missing`、`draft`、`unusable` 和 404、422 不给「重新核对」。
- **样子：** 和 R3d、R4a 一样，核对中只有一行字（放在「加入草案」旁边，没有转动的图标）；这时「加入草案」和「重新核对」变灰、点了没反应（不会重复发同一次核对），用 `aria-disabled` 而不是 `disabled`（禁用的按钮会把焦点丢掉）；上一次的失败照说明书留到核对成功为止。提示两种样子：警告带 `TriangleAlert` 图标和强调色边框，普通提示带 `Info` 图标和普通边框（tokens 里没有黄色，没有加新颜色）。每门课一张卡：一行课号、课名、学分，下面「课程页／年度先修」和「移除」两个按钮；规则树用等宽字体、保留缩进。所有文字都是纯文本，课程行、提示、规则树保留换行和空格；长课名、长规则名、20 门课的「方案里没有写到」都能折行，390 宽的手机上整页不横向滚动。组件里没有 `<a>`：「课程页／年度先修」是站内按钮（草案留在内存里）。
- **焦点（统一焦点规则）：** 按下的按钮还在就不动（「加入草案」「清空草案」）；会消失的先把焦点放到固定的地方再调回调：「移除」放到「已填 n/20 门」那一行，「重新核对」放到小标题，都是 `tabIndex=-1`、`preventScroll`，不进 Tab 顺序。新回答或新结果拿掉草案里有焦点的那一块时，焦点先交给小标题（同样不滚动），比如：移除以后的回答显示不了，拿掉了「已填」那一行；一门课的两个按钮被拿掉；「重新核对」消失（核对成功了，或者新的失败不能再试）。焦点在别处或哪里都没有时不动，连一瞬都不借。「课程页／年度先修」换页的焦点由外壳管。
- **读屏：** 草案是以小标题命名的 region，小标题是 h3（在方案块的 h2 下面；演示页上面那行范围用 h2，顶栏是 h1，不跳级）。核对中那一行在一个一直在的 `role="status"` 里；提示和「已填 n/20 门」在一个一直在的 `aria-live="polite"` 区域里，按了「加入草案」焦点留在按钮上，也能听到这次哪些课号没加进去、现在一共几门。失败和两种格式警告是 `role="alert"`。读屏只在内容变了时才读，所以每个新回答都把提示和「已填 n/20 门」的字重新画一遍，每个新的失败、每个显示不了的新回答也把那句重新画一遍：结果和上次一字不差（重试又是同样的失败、加了同样的课号）也会再读一遍。新的失败只重画失败那一句，上一份回答的提示和「已填」不重画，免得听起来像又加了一次课。「已填」那一行本身和「重新核对」按钮不重建，焦点在上面不会掉。这两个一直在的区域空着时 `position: absolute`，不占布局的间距。
- **固定数据：** 32 份接口回答（真实 API 在合成库上导出 25 份，改出来 7 份）和 31 份标准答案原字节放在 `fixtures/draft/` 与 `expected/`，`fixtures/draftFixtures.test.ts` 锁定 63 份的 SHA-256，目录跳过 Prettier。expected 只供测试；演示的场景映射 `fixtures/draftScenarios.ts` 单独写，测试核对它和 29 个标准答案的 props 一样。29 个场景逐项比对实际 DOM（种类、文字、顺序、按钮的 action 和 course_id、`aria-disabled`、输入框的标题和字数上限、树的每一行；提示的级别从定样子的外层框读），另查读到的东西都看得见、不在 `aria-hidden` 里，读到的以外没有别的字（`placeholder`、`title`、`alt` 也没有）；另有 18 个失败向量、7 个树向量。jsdom 不套样式表，换行、折行、警告样子和变灰的那几条声明由测试直接读 CSS 文件核对，另一条测试核对这些规则对应的类都挂在该挂的元素上。
- **变异：** `node scripts/draft-mutations.mjs`，具名变异在临时副本里跑。Vitest 失败、而且失败的测试里有对应的那条，才算杀掉，不分是断言没过、找不到元素还是抛了异常；类型变异算对应的类型测试在那个字段上编译失败。说明书第 15 节列的那些改坏都在里面；第 31 轮审查以后又加了一批：每处修复反过来改一次，再加上审查自己的变异里没杀掉的那些。一个变异可以在同一个文件里按顺序改几处。进程退出时（跑完，或者中途出错，比如基线没过、锚点对不上）先删副本里的两个 `node_modules` 链接，再删副本。按 Ctrl+C、从外面结束进程或者机器重启时走不到这一步，副本会留在 `%TEMP%` 的 `neu-draft-*` 里；手动删时也先删那两个链接。

在 Windows Node 24 下从 `web/` 执行 `npm.cmd run check`、`npm.cmd run format:check`、`node scripts/draft-mutations.mjs`。本机看演示：`npm.cmd run build:dev-api` 再 `npm.cmd run preview:dev-api`（或 `npm.cmd run dev`），打开上面的入口。真实的请求、草案放在内存里、刷新／登出／换账号清空、换方案重新核对、409 清掉方案选择、「课程页／年度先修」换页都在 R4 接线时做（说明书第 14 节）。给接线的四点：

- 核对中按「移除」「清空草案」照样调回调（说明书没拦）。接线以最后一次请求为准，丢掉晚到的旧回答。
- 换方案时把 `answer`、`failure` 都置 null，或者按方案分别存。不然在新方案的结果回来以前，旧回答对不上新方案的内容版本，会闪一下版本警告；上一份方案的失败和「重新核对」也会挂在新方案下面。
- 组件按对象认「新结果」：同一个结果在下一个结果来以前一直传同一个对象；每次核对得到结果都给一个新对象，哪怕和上次一字不差，读屏才会再读一遍。也不要每次渲染都新建一个（比如 `answer={{ ...data }}`），不然读屏会把同样的结果一遍遍重读。
- 409 的四种清掉方案选择时，整块草案跟着拿掉，焦点可能正在里面（比如刚按的「加入草案」）。组件整个卸载时不动焦点，所以由接线先把焦点交给方案选择框或课程表那一块（R4a 的 section 带 `tabIndex=-1`），用 `preventScroll`。R4a 那句「这个项目的版本化方案有更新…」是普通的一行字，那一次要让读屏读到，比如放进 `role="status"`。

## 搜索页和课程页接真实接口 R3e（2026-10-26）

从 main `cbb91f7` 开 `feat/web-search-api`，依据评审目录 `frontend_react/R3E_PLAN.md`。`/` 和 `/course/:code` 换成接真实接口的页面（`src/pages/SearchRoute.tsx`、`CourseRoute.tsx`），用的是 R3a–R3d 的组件；R1 原型的搜索页、课程详情、假课程和 `PrototypeContext` 都删了。培养方案页由 R4c 接上。本机对着开发 API 跑，见「接口层与登录 R2b」。

- **对话在外壳里**（`src/layout/SearchContext.tsx`）：问题、回答、相关课程和评价放在路由上面，去课程页再回来还在；整页刷新就没了（和 Streamlit 一样）；登出、删号、换了账号时清空。同一时间只问一个。
- **提问**：照 Streamlit 的请求：问题最多 500 字、`k: 10`、最近 6 轮的历史、最近一条有结果的回答里的课、选了的项目和方案。Streamlit 侧栏「高级筛选」里的学分这里还没有（侧栏的筛选还是 R1 的入口），所以问题不带筛选。问题只带页面上看得见的：项目列表读不到（请求失败，或者回来了读不懂）、选择框不在的时候，不带项目和方案（选择留着，列表回来了照旧），页面说一句「暂时无法加载项目列表」；例外是手机上的课程页，版面把选择框连同对话一起藏起来，从那里提问照样带着首页选的项目和方案，回答回首页看。「允许保存」只在 `/config` 开着回答反馈、`/privacy` 给了说明时出现，默认不勾；勾了以后这个标签页里之后的回答都保存，直到取消勾选或登出，不每次复位（`/privacy` 的说明写的是「本次会话之后正常完成的回答」）；勾选框不在了（反馈关了，或者说明读不到），勾选也跟着清掉。评价 `POST /feedback` 只发凭证和评分。查询日志的提示和「允许保存」的说明都来自 `GET /privacy`。
- **项目和方案**：`GET /programs`、`GET /programs/{id}`，5 分钟内不重取。方案照 Streamlit 只列核对过来源的（草稿不列），列表里有一份读不成就一份都不列，ID 或范围在整份列表里（别的项目的也算）重复的不列；每份带 #36 的 `plan_revisions` 里的内容版本，提问时原样带上，前端不算摘要。换项目清掉方案；方案列表改版了清掉选择、说一次；`/chat` 回方案类的 409（`reason` 是 `plan_` 开头的那五种）清掉选择、重取这个项目；项目从列表里没了也清掉。
- **课程页**：地址里的那一段原样送去 `GET /resolve/course?ref=`（8 秒）解析，API 不管用什么分隔符；页面上说起它时把横线换成空格。从回答、落地推荐、对比页点进来的带着课程 ID，不再解析。对上多门时开第一门，另外列出最多 3 门；找不到、暂时打不开各一句，暂时的有「重试」，不自动重试。详情和先修是 R3b、R3a 的组件；「加入对比」真的加进对比列表。分享框给 `{站点}/course/CS-6140`。1200 宽以上左边对话、右边详情；768–1199 宽一栏，对话在上、详情在下；手机上课程页只显示课程（照 R1），对话回首页看，提问栏照旧在。
- **旧链接**：`/?course=CS-5800` 换成 `/course/CS-5800`（替换，不多一条历史）；同一个参数写了两次，照 Streamlit 取最后一个；只有 `.`、`..` 的放不进路径，和空的一样留在搜索页。从 Google 回来的地址由登录处理：登录去掉 code 时连整个查询串一起去掉，所以那一次不会打开课；登录前所在的地址带着 `?course=` 的话，回到那里以后照常换。`?program=` 和方案链接见 R4c 一节。
- **分享链接的站点在构建时定**（`src/api/apiBase.ts` 的 `choosePublicBase`，`VITE_PUBLIC_BASE_URL`）：正式构建和 beta 默认 `https://compass.neu-compass.me`，只认 https；`build:dev-api` 是本机的预览地址 `http://127.0.0.1:4173`，开发服务器是它自己的地址。不读页面的 `window.location`，beta 上分享出去的也是正式站点。
- **顶栏的课程数**（`src/api/ready.ts`）：`GET /ready` 的 `courses_indexed`，5 秒，5 分钟内不重取；失败了 30 秒后自己再取一次（只有这一个读请求会自己重试，Streamlit 是下一次操作页面时再取）。失败、预热中（数是 0）、读不懂时显示「NEU 研究生课程目录」。原型写死的「6,469 门课 · 目录 2026–2027」去掉了，目录年份没有接口给。窄屏上照 R1 不显示。
- **账号的提示**：在账号框里按出来的结果（登录没能开始、已经退出、没能退出）显示在账号框里，桌面侧栏和手机菜单各显示自己的；从 Google 回来的结果显示在页面最上面。原来都在页面最下面那一行：长页面上第一屏看不见，手机菜单开着时读屏也读不到。
- **开发端口**：5173 被占时（Windows 会把一段端口留作动态保留），PowerShell 里先 `$env:VITE_DEV_PORT = '5300'` 再 `npm.cmd run dev`，开发 API 跟着加 `--web-port 5300`，它的 CORS 和登录跳回的地址才认这个端口。另一个窗口占着 8000 时，开发 API 用 `--port` 换一个，页面这边设 `VITE_API_BASE_URL`。
- **开发 API 的合成目录**（`tests/support/dev_catalog.py`）：四个项目、每学期的课表、带版本的方案（cs-ms 有三份核对过的、一份草稿）、按两年存的先修文档、一门什么字段都有的 CS 6140 和几门只有一部分字段的课；「ML」是 CS 6140 和 DS 5220 共用的简称，`/course/ML` 能看到对上多门的样子。
- **测试**：`src/pages/searchRouteTestUtils.tsx` 是一个合成的假 API（落地数据、带方案版本的 cs-ms、一条固定回答、几门课），`SearchRoute.test.tsx`、`CourseRoute.test.tsx` 逐条核对请求。`WithApi` 也预先放好 `/ready`。

修改经过、验证和已知的问题在 `docs/development-change-log.md` 第 38 节（第 37 节是同时在做的 R4b 页面）。

## 培养方案页接真实接口 R4c（2026-10-27）

从 main `9dd490e`（#38 合并以后）开 `feat/web-programs-api`，依据评审目录 `frontend_react/R4C_PLAN.md`。`/programs` 换成接真实接口的页面（`src/pages/ProgramsRoute.tsx`），用 R4a 的 `ProgramList`、`ProgramCurriculum`；原来的占位页删了。10-27 用户定了：每个项目一个网址，搜索页和培养方案页的选择分开，方案链接没通过时打开这个项目、不选方案。

- **两个地址**：`/programs` 是列表，`/programs/<项目 ID>` 是一个项目的课程表。列表和课程表与落地页、搜索页的选择框共用缓存（`['programs']`、`['programs', id]`，5 分钟）。地址里的 ID 不合 API 的格式（`^[a-z0-9][a-z0-9-]{0,63}$`）就不问，直接说找不到；知道「现在是谁」以前也不问（和搜索页一样）。
- **选择放在外壳里**（`src/layout/ProgramsContext.tsx`）：每个项目记一个方案选择，连同选的时候方案列表的签名；去别的页面再回来还在，刷新页面就没了。签名变了（方案改版），选择在渲染时就清掉，页面说一次 R4a 那句「这个项目的版本化方案有更新…」，另有一个读屏读得到的 `role="status"` 说同一句；所选的方案不再提供了，静静清掉。登出、删号、换了账号时清空，`/auth/me` 第一次回答不算换人。和搜索页的选择分开（Streamlit 也是两套）。
- **「刷新方案及政策证据」**：删掉这个项目的缓存（`resetQueries`，重取失败也不退回旧的课程表），清掉选择，马上重取；课程表暂时读不到时，它就是重试。
- **政策证据**：`GET …/plans/{plan_id}/policies`，键里带方案 ID 和内容版本，不缓存（`staleTime`、`gcTime` 都是 0）。每次读取（选回之前选过的方案、侧栏的「刷新页面内容」）都只显示「正在加载政策证据…」，从不先显示上一次的回答。
- **分享框**：项目给 `/programs/<ID>`；选了核对过的方案时照旧给 Streamlit 的 8 个参数的方案链接，它是唯一带着方案内容版本的链接，两个前端都认。
- **旧链接**（从 `/` 进来，`SearchRoute` 先处理）：
  - 带了 `program` 以外任何一个方案参数，就当方案链接：参数缺、重复、格式不对，或者带了 `course`，开列表、说一句；参数对，就打开那个项目，在项目页上不读缓存、重新取一次再核对（照 Streamlit 的 `resolve_plan_link`）。方案和版本都对得上、核对过来源，才选上它；不然不选方案，说为什么。暂时取不到时说一句，按「刷新方案及政策证据」再核对。
  - 然后才是 `?course=`（R3e）；`?course=` 和 `?program=` 都有时开课程页。
  - `/?program=<ref>`：去列表，等列表回来照 Streamlit 的 `match_program_ref` 找（先按 ID、再按前缀，都不分大小写，前缀对上多个算没找到）：找到了换成那个项目的页面，没找到留在列表、说一句。列表读不到时，按「重新加载」以后接着找。
  - 都用替换，不多一条历史；提示的句子放在这一条历史记录的 state 里，由列表页或项目页显示。
- **「查看」**：课程行去 `/course/<课号>`，带着课程 ID（R3e 的做法）。
- **隐私说明**：`GET /privacy` 网页版那句改成课程页和培养方案页都有自己的网址、都会留在浏览器历史里；Streamlit 不变。
- **侧栏页脚**：「培养方案还是假数据原型」那句去掉了。

修改经过、验证和已知的问题在 `docs/development-change-log.md` 第 39 节。
