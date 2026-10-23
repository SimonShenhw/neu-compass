# R5c 数据与隐私页修改记录

日期：2026-10-22（America/New_York；日志目录名使用 UTC，可能显示 10-23）。

## 1. 起点和授权边界

- 本机单独的 web worktree（本机路径不写进仓库），分支 `feat/web-privacy`，起点 `101775e2a6e5340da5daa8c436fc19410877a4bd`。开工前工作树干净，保留原 `feat/web-compare`。
- 依据评审目录 `frontend_react/R5C_PRIVACY_SPEC.md`。用户明确同意修改不确定结果的误导性句子后开工；只改 `web/`，不动另一边后端／Streamlit／外部说明书，不改依赖／lockfile／CI，不 rebase、push、建 PR、合并或部署。
- 只用合成记录，无真实 HTTP、Cookie、身份或数据库操作；没有真正删除任何账号或数据。未在带 `.env` 的 main checkout 跑测试。

## 2. 修改索引

| 文件／范围                                          | 改动                                                                                                   |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `src/api/privacy.ts`                                | 手写 PrivacyBody、PrivacyState、DeleteOutcome、DeleteAccountResult 和 props 契约；R2b 后续替换生成类型 |
| `src/models/privacy.ts`                             | 先完整校验本页所用字段；其他键忽略；四种删除结果的固定中文及分类                                       |
| `src/pages/PrivacyPage.tsx` / `.module.css`         | 替换占位；接口文字、四段列表、最后的删除区；页面级结果、status、焦点和响应式样式                       |
| `src/components/AccountDeletion.tsx`                | 默认未勾选；禁用／确认提交、同步防重锁、pending、卸载保护；不拥有结果状态                              |
| `src/fixtures/privacy/`                             | 十份真实 API 形状的合成导出原样入库；不运行导出脚本、不改内容                                          |
| `src/fixtures/privacyFixtures.test.ts`              | 十份文件名／SHA-256 锁定                                                                               |
| `src/fixtures/privacyDemo.ts`                       | 参数白名单、四份政策／六份删除 fixture、额外模拟失败；不传递 detail 给页面                             |
| `src/pages/PrivacyDemoPage.tsx`                     | 三个 URL 选择器、400ms 删除／重试、内存身份切游客；显式换场景与签出分开                                |
| `src/App.tsx`                                       | `/privacy` 接本地演示外壳                                                                              |
| `src/layout/TopBar.tsx` / `.module.css`             | 原全站唯一 h1 旁加 Lucide Lock，不重复标题                                                             |
| `src/layout/AppShell.tsx`                           | 隐私演示隐藏与本地 member 矛盾的固定游客徽标；真实侧栏身份仍未接入                                     |
| `PrivacyPage.test.tsx` / `PrivacyDemoPage.test.tsx` | 完整契约、状态、隐私、取消、焦点、延迟与 axe 行为测试                                                  |
| `scripts/mutations.mjs`                             | 保留 84 项，新增 M85–M110 共 26 项；完整基线限时由 45 提至 60 秒，单项仍 45 秒                         |
| `.prettierignore` / `README.md`                     | 原始 JSON 不格式化，其他文件格式照常；记录运行入口、选择和接入边界                                     |

## 3. 一处经过确认的规范偏离

规范原句：`变成游客了，就是已经删掉了`。

问题：R2a 的依赖在 cookie 无效／过期时返回无身份；`/auth/me` 随 401 清 cookie；`/auth/delete-account` 在无身份时直接返回 401，不执行删除。因而游客状态本身不证明账号不存在。`delete-401-cookie-not-valid` 的 account_left 是 null，不能把它当成已删除的证据。

用户本轮同意后的完整提示：

> 这次没收到服务器的确认，不确定删除有没有完成。刷新后若仍是登录状态，可以再试；若已变成游客但需要确认，请联系维护者。

仅这句结果改动；成功、401 和确定失败的三句按规范保留。没有修改 fixture 里的政策文本，也不越界改另一分支。接入／上线前需由相应负责人同步旧前端及规范，避免两边说法不一致。

## 4. 设计和状态选择

- 本页 intro、heading、sentences、delete_what 都从 body 直接取，不重新拼保留期或政策文案；query_log_notice／capture_notice 不显示。body 有任何必需形状错误，整页失败且不显示删除入口；不把四段标题或段数硬编码进校验器，遵循规范的非空数组契约。
- 所有接口文字纯文本，不解析 HTML／Markdown，不自动链接邮箱／网址；接口 detail、行数均不显示；页面和演示壳不写 storage／console，测试中 fetch 仍禁止。
- 加载用文字，不造内容骨架；锁图标复用 Lucide、颜色字号复用 tokens，白底细线和钴蓝强调色保持一致。使用 Sites 的 local-only 开发／预览流程，没有创建托管资源。
- 结果放在 PrivacyPage，不放 AccountDeletion。member→guest 隐藏表单而不移除结果；再次登录新表单默认未勾选，旧结果作为最近一次操作保留，不因无关 rerender 抢焦点；新尝试先清旧结果。
- AccountDeletion 在等待时同时禁用按钮和 checkbox，另有同步锁防止同一轮 React 更新前重复提交。失败后允许再试；旧请求在表单／页面卸载后不回灌，也不登出新的演示场景。
- 外壳 URL 是初始化场景；当前身份单独一行展示。显式换参数才重建整个演示场景、清除旧结果。onSignedOut 只改内存，不改 URL，所以不会通过 key 把成功／401 结果卸载掉。

## 5. 验证过程

日志均在本 worktree `web/artifacts/`，不提交，可按 README 重跑。依赖版本和 lockfile 未改。

| 阶段               | 结果／证据                                                                                                                                                    |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 旧树基线           | 251 tests / 15 files，类型／lint／构建通过；`privacy-baseline-2026-10-22.log`                                                                                 |
| RED                | 修正测试文件自身的一个括号笔误后，旧占位页为 39 failed / 3 passed，真实行为断言失败；`privacy-red-2026-10-22.json`                                            |
| 页面 GREEN         | 42 passed；`privacy-green-1-2026-10-22.json`                                                                                                                  |
| 中途类型修正       | 测试 mock 的 ok 被推宽为 boolean，明确 Promise<DeleteOutcome>，不放宽 strict；`privacy-types-1-2026-10-22.log`                                                |
| 扩充分支与演示     | 69 项隐私相关测试通过；`privacy-green-2-2026-10-22.json`                                                                                                      |
| 最终干净安装       | `npm ci` 成功；`privacy-ci-2026-10-22.log`，保留既存 ESLint 9 deprecated 提示，不称无警告安装                                                                 |
| 最终格式／完整检查 | 格式通过，320 tests / 18 files，类型／零 lint 警告／构建通过；`privacy-format-2026-10-22.log`、`privacy-check-final-2026-10-22.log`                           |
| 变异检查           | 110 / 110 killed；副本基线通过，sourceUnchanged=true；`mutations-2026-10-23T00-25-45-283Z/summary.json`、逐项 JSON／log 和 `privacy-mutations-2026-10-22.log` |

首屏入口 JS gzip **144,798 / 250,000 bytes**，构建入口 `index-CTT3N-rp.js`；浏览器测的是同一份生产构建，没有靠延迟加载藏依赖。

69 项新增测试包括：四份说明逐句／逐标题顺序、游客／member、零／30／90 天和反馈／邮箱变化、未使用 notice 不泄漏；必需字段错误／空数组／非字符串整页失败；确认、等待、连点、重试清旧结果；两种成功、两种 401、403／422／429／500、null／502／503／504／抛错；签出后结果／焦点、再次登录、卸载／坏政策／切场景迟到请求；纯文本、storage／console 禁止；四种 axe 状态；演示参数／缺省／400ms 边界和取消。

### 新增具名变异

| ID        | 人为破坏                                                                               |
| --------- | -------------------------------------------------------------------------------------- |
| M85–M89   | 倒置段落／句子、放过空政策／非字符串句子、无效政策仍开放删除                           |
| M90–M95   | 未确认按钮可点、提交不检查确认、无同步锁、等待 checkbox 可改、不清旧结果、卸载后仍回灌 |
| M96–M99   | 401 不登出、502 误归确定失败、500 误归网关失败、恢复“游客证明删掉”的误导句             |
| M100–M102 | 结果随 guest 消失、不聚焦结果、游客也有删除表单                                        |
| M103–M106 | 删除延迟变 0、演示不切游客、政策按 HTML 显示、暴露英文错误原文                         |
| M107–M110 | 再登录默认已勾、重试延迟变 0、放过错误标题、onSignedOut 调两次                         |

变异只在隔离副本运行；只有命中预期测试名的失败算 killed，超时／导入失败不算。原 R1、Co-op、R5b 84 项不删。

## 6. 浏览器验收与限制

- 使用 Windows Node 24 的生产构建预览，临时 5173。1440×900／390×844 各检查八种：guest、member、success、expired、uncertain、refused、loading、error；另测手机 unrecognised。没有触发任何真实删除。
- 截图在 `artifacts/privacy-browser-2026-10-22/desktop-<状态>.jpg`、`mobile-<状态>.jpg`；布局／焦点测量在 `measurements.json`。底部表单另看 `desktop-member-bottom-correct.jpg`、`mobile-member-bottom.jpg`。
- 整页截图接口连续失败，原生视口截图可用但偏模糊；最终用可用的 clip 截图保留清晰视口图，裁掉右侧 15px 边缘／滚动条区域。上下内容用额外滚动截图检查，不声称交付完整整页长图。失败尝试的临时图片留在 artifacts，不当成验收证据。
- 两种尺寸 document.scrollWidth 均不超过 innerWidth；长段落正常换行。正文的四个 h2 后才有删除 h2；游客／失败没有表单。
- 键盘 Space 勾选、Tab 到按钮、Enter 模拟删除；按钮有 2px 钴蓝焦点。四类结果均聚焦 aria-label=删除结果 的 status；成功／401 表单消失但焦点仍在结果。不确定／确定失败保持 member 和表单；键盘 Enter 重试即时进入 loading，随后回到原错误。
- 浏览器捕获的 error／warn 为空。DOM 与构建入口为同源静态资源；完整网络面板请求瀑布不可读，不能声称该项已经完整验收。
- 临时视口最后恢复、结束本轮拥有的 preview，不关闭用户已有标签页。

## 7. 留给集成和独立验收

- R2b 负责真实 GET／POST、响应校验、CSRF 和 Cookie。请求体应为 {"confirm":"delete"}；本页只调无参数回调。特别要先校验 200 确实 deleted=true，不能把任意 200 HTML／错误 JSON 当成功。
- 真实登录／退出须清会话 store，并管理不同账号与迟到请求；不把 URL 演示 viewer 当权限，不随 viewer 给 PrivacyPage 换 key。
- R3 接 query_log_notice／capture_notice，不把它们重复塞进本页。生产设置、真正删号及 cookie 失效、屏幕阅读器语音、完整请求瀑布和部署均需另验。
- 这次只做本地提交；后续 push／PR／合并仍由用户另行授权，未改 main checkout。
