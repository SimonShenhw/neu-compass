# R1 修改记录

最新状态见文末最新的 R1 补验记录。前面的数字按各自提交保留为历史结果，不代表补验后的代码。

## 2026-10-21 · 开工

- 按 `frontend_react/R1_SPEC.md` 和 `mockup_v1/neu-compass-redesign.html` 实施；用户确认沿用设计稿、中文导航、对比默认只看不同的行；首版只做浅色，保留主题 tokens。
- 从已合并 L 的 `origin/main @ 6395ee586e3145323bd0bc94eb87c4b8ec0aa69d`，经 WSL 建立单独的 worktree，分支 `feat/web-skeleton`。
- 范围仅 `web/` 与 `.github/workflows/ci.yml` 的前端 job。不接接口、不做登录、不安装 HTTP 库或 Playwright、不改 Python、Docker 或 Streamlit。
- Windows Node 24.19.0 / npm 11.17.0；依赖精确锁定，提交 lockfile。测试、视觉验收、体积和边界结果在完成后追加，不提前写成通过。

## 交付范围

这批是可供独立验收的本地 React 假数据原型，不是线上迁移完成。Sites 技能采用 local-only 路径，不注册站点、不上传源码、不发布。记录按项目现有中文批次格式整理。

| 部分       | 实际改动                                                                                                                                      |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| 工具链     | React 19、Router 7、Vite、strict TypeScript、Vitest / RTL、ESLint flat config、Prettier、精确依赖与 lockfile                                  |
| 设计系统   | 白底细线、钴蓝强调、Plex Sans / Mono 本地字体、中文系统字体、CSS Modules、浅色 tokens、Lucide 图标                                            |
| 11 组组件  | Button、IconButton、CourseCode、Select、Toggle、Chips、EmptyState、DataNote、RequisiteTree、AskBar、Sidebar / MobileNav；均有行为或编译期测试 |
| 搜索与详情 | 一问一答、四门课、空首页四个问题、项目 / 方案、内联详情、可点击先修树、展开全文、明确未知项                                                   |
| 对比       | 预填四门假数据；默认隐藏相同行；可恢复相同行、移出、清空；路由间保留内存状态；表内横滑和首列 sticky                                           |
| 其他路由   | 培养方案、Co-op、隐私占位页；404 与未知课程空状态                                                                                             |
| 检查脚本   | manifest 首屏 JS gzip 门限；19 项隔离变异及具名失败证据                                                                                       |
| CI         | 仅新增独立 frontend job；原 Python job 内容保持不变                                                                                           |

唯一五门 fixture 是 CS 5800、CS 6140、CS 7800、DS 5220、CS 5100。没有真实用户数据。搜索 / 详情的「加入对比」只输出合成课号与本地提示，不实际添加；登录禁用；发送不请求模型、不写查询日志；分享不复制或上传。具体状态边界见 README。

## 实现和自验中修正的地方

1. Radix Select、Dialog 使用真实组件测试，不用简化替身掩盖键盘行为。只补 jsdom 缺失的 pointer capture、scroll、ResizeObserver；测试中禁止 fetch。
2. 先修叶子跳转精确课号；进入另一门课后重置全文展开状态。CS 7800 正文明确标成 fixture / 未建模，不补造官方要求。
3. 路由聚焦主内容使用 `preventScroll`，显式回页顶，避免焦点让顶栏离开视口。
4. 手机空首页省略重复游客行和项目选择器，保留可访问标题；修正搜索标题的 CSS 优先级，消除手机约 1px 的整页横溢。没有通过 `overflow-x: hidden` 隐藏问题。
5. 手机品牌、按钮、链接提供至少 44px 高的点击区；勾选框通过整行 label 提供目标区域。对比表的独立滚动区可聚焦，保留键盘操作。
6. 次级文字由设计稿 `#727e90` 调为 `#596678`，增加七组 token 的 4.5:1 数值检查。主题摘要和短输入占位文案按手机稿处理，理由写入 README。
7. 「允许保存这次」发送后重置为关闭，防止误沿用上一个问题的演示授权；增加行为测试和 M18。
8. 从对比页选择 Boston 假方案时同步 MSCS 项目，避免返回搜索后出现「项目不指定但方案已选」；增加跨路由测试和 M19。

## 干净安装与检查结果

2026-10-21，在 worktree 的 `web/` 里，使用 Windows Node 24.19.0 / npm 11.17.0：

| 命令 / 检查     | 结果                                                                                      |
| --------------- | ----------------------------------------------------------------------------------------- |
| `npm ci`        | exit 0；新增 402、审计 403 个包，0 vulnerabilities；存在 ESLint 9 deprecated 提示，见下节 |
| `npm run check` | exit 0；strict 类型检查、零警告 lint、行为测试、生产构建全部通过                          |
| Vitest          | 6 个文件，59 passed；包含 9 个页面 / 状态的 axe 检查                                      |
| 首屏 JS         | 124,574 gzip bytes / 250,000 bytes；计入入口和递归静态 import，不计 CSS / 字体            |
| 构建            | Vite 8.3.5；入口 `index-D4parCIL.js`，CSS `index-DLTtrk24.css`                            |

本地完整输出保存在被忽略的 `artifacts/clean-install-2026-10-21.log` 和 `artifacts/clean-check-2026-10-21.log`。格式和提交前范围检查在末节记录。没有在含 `.env` 的主 checkout 跑 Python 测试。

### 版本兼容例外

没有用强制安装或忽略 peer dependencies 绕过冲突：

- `typescript-eslint@8.72.0` 要求 TypeScript `<6.1.0`，因此锁定 `typescript@6.0.3`，未用 registry 当时的 7.0.2。
- `eslint-plugin-jsx-a11y@6.10.2` 声明只支持至 ESLint 9，因此锁定 `eslint@9.39.5`。ESLint 9 已停止官方支持，安装的 deprecated 提示是真实的待确认例外；lint 的零警告和 audit 的零漏洞不能替代维护支持。
- 独立验收需确认上述例外，后续插件支持时再独立升级，不擅自删掉规定的无障碍插件。

## 19 项具名变异

最终证据：`artifacts/mutations-2026-10-21T20-50-52-413Z/summary.json`，baseline passed，**19 / 19 KILLED，sourceUnchanged: true**。冻结范围覆盖 src、脚本、package / lockfile 和测试 / 类型配置；没有原地改坏源码。

| 变异 | 破坏的行为 / 契约         | 命中的断言要点                                  |
| ---- | ------------------------- | ----------------------------------------------- |
| M01  | Button variant            | primary / outline class                         |
| M02  | disabled 按钮             | 不触发 click                                    |
| M03  | IconButton label 改成可选 | 唯一 TS2578，命中缺 label 的 `@ts-expect-error` |
| M04  | CourseCode 原文被替换     | literal text                                    |
| M05  | 主题上限 8 改为 9         | 8 个 +1                                         |
| M06  | DataNote 默认展开         | initially collapsed                             |
| M07  | Toggle 状态不变           | keyboard and pointer                            |
| M08  | all / any 混淆            | nested all/any                                  |
| M09  | 叶子都跳同一门            | exact course                                    |
| M10  | Select 不更新选择         | opens, selects and closes                       |
| M11  | Enter / Shift+Enter 反转  | Enter sends trimmed                             |
| M12  | 允许保存默认打开          | leaves consent off                              |
| M13  | 移除 aria-current         | only current destination                        |
| M14  | 手机抽屉不响应开关        | expansion / Escape / focus                      |
| M15  | 相同行永远隐藏            | switch restores shared rows                     |
| M16  | 移出保留错列              | removal keeps other columns                     |
| M17  | 路由聚焦不防滚动          | focus does not scroll                           |
| M18  | 发送后不重置允许保存      | consent applies only to this question           |
| M19  | 对比方案不带所属项目      | fixture project consistent on return            |

每个目录保留 stdout / stderr、Vitest JSON 的真实失败名、SHA-256 和临时副本位置。Vitest 必须 exit 1 且命中预期断言；类型变异必须 exit 2 且只有预期文件的 TS2578。超时、导入失败、无对应断言不计为杀死。

早期失败也保留，未覆盖或伪装成绿色：

- `20-46-38-694Z`：Windows TEMP 的 8.3 路径令 Vite baseline 无法导入 setup；改为 canonical temp path 后重跑。
- `20-47-19-990Z`：16 项已杀死，M03 实际产生正确 TS2578，但脚本误以为 tsc 应 exit 1，记为 UNRESOLVED；修正为严格检查 exit 2 和唯一预期诊断。
- `20-48-33-722Z`：17 / 17；后来新增两项行为修正后重新冻结，最终跑到 19 / 19，没有拿旧结果覆盖新代码。

## 浏览器实测和截图

使用内置浏览器访问本机 Vite 生产预览。规定视口是桌面 1440×900、手机 390×844；长页面用 full-page 截图，因此图片高度可以超过视口。临时 viewport override 已重置，独占预览进程已停止。

最终图片和 DOM 尺寸记录保存在评审目录的 `frontend_react/r1-evidence-2026-10-21/`，不混入源码提交：

- `delivery-desktop-search.jpg`、`delivery-desktop-detail.jpg`、`delivery-desktop-compare.jpg`。
- `delivery-mobile-empty.jpg`、`delivery-mobile-answer.jpg`、`delivery-mobile-detail.jpg`、`delivery-mobile-compare.jpg`、`delivery-mobile-compare-scrolled.jpg`。
- `delivery-layout.json`：桌面三页 document scrollWidth = clientWidth = 1440；手机页面 scrollWidth = clientWidth = 390。

实际操作覆盖：

- 项目 / 方案用键盘打开、选择；搜索 → 详情保留状态；对比页选 Boston 后返回详情，MSCS 项目和方案一致。
- CS 6140 先修叶子点击进入 CS 7800；返回仍可使用。详情全文展开 / 收起由行为测试覆盖。
- 手机菜单打开、Escape 关闭并回焦点；点导航目的地后抽屉关闭。
- 对比默认隐藏学分 / 年份；关闭开关恢复；移出 CS 6140 后保留另三门并更新计数；清空变成可返回搜索的空状态。
- 最终手机对比横滑：scrollLeft 从 0 到 588，首列左边界一直是 17px，整页宽度仍 390px；表格内容宽 944px、独立容器宽 356px。
- 最终手机空首页 body 高 844px，输入框底部 763px，允许保存 label 底部 824px，没有被推出首屏。
- 浏览器中勾选允许保存、输入合成问题并发送，确认问题更新、仍明确固定示例回答、勾选恢复 false。

## 尚未声称通过的验收

| 说明书验收项    | 当前边界                                                                                                             |
| --------------- | -------------------------------------------------------------------------------------------------------------------- |
| 1 干净安装 / CI | 本地干净安装和 check 通过；尚未 push，GitHub frontend job 未执行                                                     |
| 2 组件测试      | 11 组均有测试，19 项具名变异通过；不等同于任意变异全覆盖                                                             |
| 3 无障碍        | 9 个 DOM axe 状态通过；jsdom 仅关闭 color-contrast，七组 token 另测。不是每页所有控件的完整人工键盘 / 屏幕阅读器验收 |
| 4 视觉          | 两种视口核心页实际截图；设计差异见 README，等待独立并排验收                                                          |
| 5 仅同源网络    | 字体本地、源码无 HTTP 客户端、DOM 静态资源同源；浏览器工具没有完整请求瀑布，网络面板全量验收仍待做                   |
| 6 体积          | 自定义 manifest 检查 124,574 gzip bytes，低于门限                                                                    |
| 7 代码          | strict / no-any / fixture / LF / token 合约测试通过；提交前还核范围，不把这些测试称作完整安全审计                    |
| 8 文档          | README 记录安装、运行、测试、状态边界、设计差异和依赖兼容例外                                                        |

R2 的接口、认证、聊天流，R3 的旧深链，以及真实数据 / 登录 / 部署都未开始。没有 push、PR、合并或线上变更。下一步是用本地提交做独立验收，不直接跨到 R2。

## 提交前收尾

- 补齐 README 和本记录后，再次 `npm run format:check`、`npm run check`，均 exit 0；仍是 59 passed、零 lint 警告、首屏 JS 124,574 gzip bytes。输出保存在 `artifacts/format-check-2026-10-21.log`、`artifacts/final-check-2026-10-21.log`。
- 当前源码与最终 19 项变异的冻结 SHA-256 逐项对照，差异 0；后续只整理说明文档，没有修改被验证的实现。
- 暂存 67 个文件，仅 `web/` 与 CI；越界文件 0、禁止提交目录 0、含 CR 文件 0；`git diff --cached --check` 通过。
- `node_modules/`、`dist/`、`artifacts/` 确认被忽略。主 checkout 工作树仍干净。本地预览已停止，不留下后台服务。
- 交付为 `feat/web-skeleton` 上的本地提交；提交号另交评审目录的 R1_HANDOFF，避免在本提交内自引用哈希。没有 push、PR、合并或部署。

## 2026-10-21 · R1 补验 1：控件移除后的键盘焦点

### 范围与复现

用户继续推进后，核对到本分支仍是 `dfe5f3d`，工作树干净；没有新的 R1 审查文件，计划仍把 R2 分给另一边。因此仅推进 R1 的自验 / 修复，不改接口、登录或后端。

先跑冻结基线 `npm run check`：59 passed。浏览器用 Enter 实测三个路径，操作后 `document.activeElement` 都变成 BODY：移出某个对比列、清空对比、空首页选择示例问题。原控件消失后没有焦点接续，不只是样式问题。

新增测试后、修改实现前，页面测试 30 项中 21 passed / 9 failed；九个失败全部是 `toHaveFocus()` 断言，覆盖首 / 中 / 尾列、最后一门、清空和四个示例。另一个「无关更新不抢焦点」保护测试保持绿色。证据在 `artifacts/r1-followup-red.json` 与 `.log`，没有改坏生产源码来伪造 RED。

### 修改位置

| 文件                                 | 修改                                                                                                                              |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| `src/pages/ComparePage.tsx`          | 操作前记录后继目标，DOM 更新后聚焦下一列移出按钮，末列则上一列；清空 / 末门转到空状态返回链接。只处理显式操作，不为普通渲染抢焦点 |
| `src/pages/SearchPage.tsx`           | 空首页示例按钮消失后，把焦点交给新回答；`tabIndex=-1` 不增加普通 Tab 停靠点；`preventScroll` 保留位置                             |
| `src/components/Button.tsx`          | props 类型使用带 DOM ref 的按钮类型，允许焦点管理拿到真实按钮；外观、默认 type 和 disabled 行为不变                               |
| `src/pages/pages.test.tsx`           | 新增 10 项焦点流程 / 保护测试                                                                                                     |
| `src/components/primitives.test.tsx` | 新增 Button / IconButton 两项 DOM ref 转交测试，仍保留 IconButton 必填 label 的编译断言                                           |
| `scripts/mutations.mjs`              | 新增 M20–M25，原 19 项全部重跑，不借用上次结果                                                                                    |
| `README.md`、本文件                  | 更新键盘策略、变异数量和本批证据                                                                                                  |

实现中首遍 strict 编译抓到了 Button 旧 props 没有 ref，以及 RTL 的角色查询不接受浏览器接口的 exact 选项，均按类型契约修正，没有放宽 strict 或引入 any。React 19 的 ref-as-prop 用法已对照 [React 官方说明](https://react.dev/reference/react/forwardRef)，并由真实 DOM ref 测试验证。

### 结果与证据

- 完整 `npm run check`：71 passed（6 个测试文件，仍含 9 个页面 / 状态 axe）；strict 类型检查、零警告 lint、生产构建通过。日志：`artifacts/r1-followup-green-check-2.log`。首遍未通过的编译日志保留为 `r1-followup-green-check.log`，不记成绿色。
- 首屏 JS 为 **124,773 gzip bytes / 250,000 bytes**，入口 `index-BaZzBYXt.js`。依赖和 lockfile 未改，未增加包。
- 最终变异 `artifacts/mutations-2026-10-22T01-43-42-265Z/summary.json`：baseline passed，**25 / 25 KILLED，sourceUnchanged: true**。目录使用 UTC 时间，执行日按用户时区仍是 10-21。
- M20 错选上一列，M21 丢失末门空状态焦点，M22 清空不发焦点请求，M23 新回答不接焦点，M24 Button 丢弃 ref，M25 筛选更新强抢焦点，均命中具名行为断言；没有把编译或导入失败算成杀死。
- 桌面 1440×900 实测移出 CS 6140 后焦点在 DS 5220 的移出按钮，清空后在返回搜索链接，可直接 Enter 返回。手机 390×844 实测示例问题后聚焦 ARTICLE「示例回答」，连续移出到最后一门后聚焦返回搜索链接。
- 手机长页存在原生滚动条时 DOM clientWidth 为 375px，短页为 390px；两种情况下 scrollWidth 均等于 clientWidth。手机邻列焦点边界为 314–358px，位于可视内容中，没有整页横溢。
- 本批浏览器证据在评审目录 `frontend_react/r1-followup-2026-10-21/`：`desktop-neighbor-focus.jpg`、`mobile-answer-focus.jpg`、`mobile-last-course-focus.jpg`、`focus-observations.json`。截图和日志不提交。

这批是原范围内的键盘缺陷修复，不是独立验收通过；完整网络面板、所有页面人工键盘 / 读屏检查、远端 CI 和 ESLint 9 兼容例外仍按前述边界处理。没有进入 R2，没有 push、PR、合并或部署。

收尾：补齐文档后再次 `npm run format:check`、`npm run check`，均 exit 0，仍为 71 passed / 124,773 gzip bytes，日志 `artifacts/r1-followup-final-check.log`。当前实现与本批 25 项变异冻结哈希差异 0；改动仅上述 8 个 web 文件，未改 CI 或 Python，主 checkout 干净。临时视口已重置，独占预览进程已停止。保留初次提交，在其后追加独立本地修复提交，提交号更新到评审目录 R1_HANDOFF。

## 2026-10-21 · R1 补验 2：路径匹配与页面状态一致

### 复现与 RED

基于 `d73e727`、干净工作树继续 R1 自验，没有新的审查文件或分工变更，未接手 R2。冻结基线 `npm run check` 为 71 passed，日志 `artifacts/r1-route-baseline-check.log`。

浏览器复现：`/compare/` 和 `/COMPARE` 已渲染对比表，但页面标题是「找不到页面」，导航无当前项；`/course/CS-6140/extra` 正文是 404，却保留「课程搜索」标题、搜索导航高亮和输入框。原因是页面使用 Router 匹配，外壳 / 导航却各用字符串相等或 startsWith 判断。

先增加页面回归用例再改实现：页面测试 **37 passed / 12 failed（共 49）**，失败均命中标题 / 页面状态断言；已有正确行为仍保留。证据 `artifacts/r1-route-red.json`、`r1-route-red.log`。

### 修改

- 新增 `src/layout/routePresentation.ts`：使用已安装 Router 的 `matchPath`，统一得到标题、当前导航目的地和是否显示搜索输入。`AppShell.tsx` 与 `Sidebar.tsx` 共用结果，移除各自不一致的字符串判断；没有改 App 的路由定义。
- 规则对照 [React Router 7.18.4 官方说明](https://reactrouter.com/7.18.4/api/utils/matchPath)。主路径按 Router 已有的大小写 / 尾斜杠规则匹配，课程路由匹配到末尾；不改 URL、不重定向、不新增课号参数归一化，也不做 R3 的旧深链兼容。
- 新增 19 项测试：10 个已匹配路径变体、5 个无效路径、1 个「路由存在但课程未知」保护用例，以及 3 个 axe 状态。未知课程仍是原有课程空状态，不误当成不存在的页面。
- 新增 M26 大小写规则、M27 匹配到末尾、M28 课程不能只匹配前缀、M29 导航不能退回原始路径相等判断；原 25 项一并重跑。

### 验证

- 完整检查 **90 passed**，6 个测试文件，包含 **12 个页面 / 状态 axe**；strict、零警告 lint 和构建通过。日志 `artifacts/r1-route-green-check.log`。
- 最终变异 `artifacts/mutations-2026-10-22T01-50-10-422Z/summary.json`：baseline passed，**29 / 29 KILLED，sourceUnchanged: true**；当前实现与冻结 SHA-256 差异 0，没有复用前两批数字。
- 首屏 JS **124,771 gzip bytes / 250,000 bytes**，入口 `index-C394UCVY.js`。没有新增依赖或改 lockfile。
- 1440×900 桌面复验 `/compare/`：对比表、标题和当前导航一致；无效课程子路径保持客户端 404，无搜索表单、无当前导航项。
- 390×844 手机复验 `/PRIVACY/`：隐私标题与可见抽屉导航一致，Escape 关闭回焦点；`/COURSE/CS-6140` 显示详情和搜索输入框。长页有原生滚动条时内容宽 375px，短页 390px，scrollWidth 都等于 clientWidth。
- 证据位于评审目录 `frontend_react/r1-routes-2026-10-21/`：`desktop-compare-slash.jpg`、`mobile-privacy-navigation.jpg`、`route-observations.json`。JSON 的原始 DOM 查询包含 CSS 隐藏的桌面导航，手机开抽屉时会记录两个相同标签；可见 / 可访问导航以截图和 AX 状态为准，并非两个可见当前项。

本批客户端 404 不等于服务器 HTTP 状态码检查。完整网络面板、全页人工键盘 / 读屏、远端 CI 和 ESLint 9 兼容例外仍待独立验收。临时视口已重置，独占预览进程已停止；未改后端、CI、部署或真实账号，不进入 R2。

## 2026-10-22 · 独立验收（协调方）

在 `f372988` 的独立副本上照 `R1_SPEC.md` 第 8 节逐条验收，没有在 worktree 里跑任何东西。

- **干净安装：** `npm ci` 装了 402 个包，0 个漏洞，唯一的警告是上面写明的 ESLint 9 停止支持。`npm run check`（90 passed，strict、零警告 lint、构建）和 `format:check` 都过，首屏 JS 124,771 gzip bytes。
- **协调方自己的 20 个变异**（和 `scripts/mutations.mjs` 无关）：19 个被对口的测试杀掉。存活 1 个：先修树的「满足其一」「都要」两个标签互换。原来的测试只查两个标签都在，没查各自标在哪种节点上；标签反了，学生会以为修一门就行。这个提交在 `controls.test.tsx` 补了按节点核对的断言，这个变异体随之被杀。
- **浏览器**（构建产物的 preview，1440×900 和 390×844）：搜索、课程详情、对比、手机四屏和设计稿对得上；只有同源请求；手机整页不横滚，对比表在自己的框里横滑，首列固定；键盘顺序合理，焦点框都看得见；手机菜单按 Escape 关闭后，焦点回到菜单按钮。
- **和设计稿不同、没写理由的一处：** 对比页的行序，「在你的方案里」放到了最后（设计稿在「学生评价」后面）。留给用户定。
- **版本例外**（TypeScript 6.0.3、ESLint 9）：同意，两处都受插件的 peer 范围限制；等 `eslint-plugin-jsx-a11y` 支持 ESLint 10 再升。
- **公开内容：** README 和本文件里有三处带盘符的本机路径，这个提交改成了不带盘符的写法；没有邮箱和密钥。
