# R3d 落地内容修改记录

2026-10-24，按 R3D_LANDING_SPEC.md 从 main `4797a32` 开 `feat/web-search-landing`。本轮仅 `web/`；R4a 等 R3d 验收完成再开始；没有推送、PR、合并或部署。

- 新基线：Windows Node 24，web 与 tools/openapi-types 两处 npm ci；404 / 33 packages，audit 0。工具安装遇到三条 tarball 重试后成功；保留既有 ESLint 9 deprecated 兼容例外。
- main 基线 46 文件 / 1,348 测试，类型、lint、构建通过；首屏 JS gzip 182,933 bytes。
- 31 份导出与 30 份标准答案原字节复制；61 份 SHA-256 与原件一致，不运行生成器、不读 .env、不调 API / Gemini。
- 共享项目类型、Load、校验器先实现，保留 R4a 复用边界；R3a–R3c 只 import，不改实现和测试。
- 新增演示专用 OfflineDemoShell，复用侧栏／顶栏／原布局 CSS，不挂载 useSession，不依赖测试预填缓存，也不通过全局禁用 fetch 改变正式页面行为。
- 使用 Sites 本地预览流程及现有 tokens；Computer Use 验证真实浏览器。只做本地开发，不注册托管或发布。

## 文件索引与职责

路径相对 `web/`。

| 文件                                                                         | 职责                                                                  |
| ---------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `src/api/load.ts`                                                            | 三态 Load、ApiFailure 的 Pick 类型、普通失败对象到 R2b 的临时失败适配 |
| `src/api/programs.ts`、`programs.types.test.ts`                              | 四层项目消费类型，逐层对照生成类型，供 R4a 复用                       |
| `src/models/programs.ts`                                                     | 列表去重、码点长度、完整课程表形状与可选值默认；plans 留给 R4a 校验   |
| `src/models/coopPreview.ts`                                                  | 复用 CoopRecord 的消费字段，只校验并返回前两条                        |
| `src/models/landing.ts`                                                      | 精选顺序、四个示例、挑课、锁提示、可见区块／pending／单一重试的纯派生 |
| `src/features/search-landing/SearchLanding.tsx`、同目录 CSS                  | 无状态纯展示，文本节点、可折行卡片和响应式布局                        |
| `src/features/search-landing/LandingConversation.tsx`                        | 接 R3c 钩子与组件、创建第一轮即隐藏落地内容、焦点接续                 |
| `src/features/search-landing/useLandingDemo.ts`                              | 仅演示使用的独立来源调度、延迟、StrictMode 与清理                     |
| `src/features/demo/OfflineDemoShell.tsx`                                     | 演示专用布局，复用现有侧栏／顶栏／CSS，固定游客，不挂 useSession      |
| `src/fixtures/landingDemo.ts`                                                | 生产演示用场景来源映射、读 fixture 转 Load、四份合成聊天数据          |
| `src/pages/SearchLandingDemoPage.tsx`                                        | 两个 URL 控件、重播、合成回调状态；key 控制整个会话重置               |
| `src/features/search-landing/SearchLanding.test.tsx`、`landingTestUtils.ts`  | 27 个实际 DOM golden、加载独立性、回调、纯文本与 axe                  |
| `src/models/landing.test.ts`                                                 | 三组 Python 向量及逐条校验、默认值、重复 ID、Unicode、稀疏数组等边界  |
| `src/pages/SearchLandingDemoPage.test.tsx`                                   | 精确时序、取消、切换、重试、四示例、被拒、返回、空缓存整页无请求      |
| `src/fixtures/landingFixtures.test.ts`                                       | 冻结 61 份原文件名与 SHA-256                                          |
| `scripts/landing-mutations.mjs`                                              | 29 个具名变异，在隔离快照运行，核对工作源码未变                       |
| `src/App.tsx`、`layout/routePresentation.ts`、`.prettierignore`、`README.md` | 演示路由、标题、固定数据排除格式化及使用说明                          |

## 行为与设计决定

1. **共享校验先完整实现。** 项目列表和课程表按 R3d 第 4 节全部字段检查，不只检查本页实际显示的字段。可选 notes／semester 等省略时归一成 null，额外键忽略；列表的 program_id 按码点数 1–64，重复 ID 整组无效。
2. **展示只读。** 五种来源的结果由外层传入，组件没有自己的加载／选择状态。项目列表失败或无效时不再看依赖它的课程表；Co-op 仍独立显示。精选顺序固定 AAI / CS / DS，只考虑列表里存在的项目。
3. **入门推荐整排等待。** 任一相关课程表 pending 时先不画整排。按顺序遍历所有 semester===1 的分组，找第一门严格等于 core / foundation 的课；不默认第一组或把选修、毕业项目算进去。课程卡片用课程表自己的 prefix。
4. **失败不是空列表。** 408、429、5xx 才提示一次「部分内容暂时没加载出来。」和重试。普通 failure 对象先构造成 ApiError，再复用 R2b 的 isTransientError；Pick 类型不冒充运行时实例。加载与失败提示可以同时出现。
5. **Co-op 仅前两条。** 第三条坏数据不影响预览，也不会显示。等级 1 的面试两字段均空才提示锁；等级 2 的薪资为空才提示锁；空字符串按 Python 的真假处理，等级 0 不锁，不额外展示敏感详情。
6. **页面文字保持参考。** 项目 prefix 用现有 oneLine；卡片与 Co-op 值只去 CR，LF 换行，使用 pre-line；正文不解释 HTML／Markdown，区块内没有 a。沿用 CourseCode 和浅色 tokens，手机一列、长值折行。
7. **完整演示与产品状态分开。** 新演示壳不调用 useSession，因此冷启动不通过真实外壳请求 config 或 auth/me；真实 AppShell 及现有登录代码不变，也不依赖预填 QueryClient 来阻止请求。member-0/1/2 只是合成返回体选择，不是鉴权。
8. **交互确实走 R3c。** 四个示例发 query、不发 label；用 R3c demoSource 正常速度播放 chat-sample，allowSave=false、反馈关。一轮创建立刻换成对话，waiting／被拒／出错都不再显示落地内容。对话区 tabIndex=-1，以 preventScroll 接续焦点，状态更新不会重复抢焦点；返回后聚焦演示容器并从头加载。
9. **异步边界。** 每次控件改变、重试或返回都以 key 重建整个会话，清理来源计时器并由 R3c abort 旧聊天。正常时间为 300 / 450 / 600ms，慢速乘四；forever 不安排计时器。重复失败原样重播，不假装成功；查看、去 Co-op、追问只写 status。
10. **只在演示入口引入假数据。** 新外壳与页面懒加载；生产场景映射与 expected 分离。测试逐一验证手写来源映射和原 27 个场景一致，expected 不生成页面。没有新增请求端点、storage、日志或依赖。

## 验证结果

- 完整检查：**51 文件 / 1,519 测试**，包含 27 个实际 DOM 场景、11 个挑课、11 个锁提示、16 个临时失败向量，以及字段、默认值、时序、焦点、取消和重播测试。对 App 的正常大小写／尾斜杠演示冷启动，使用未预填的 QueryClient，查询缓存始终为空，fetch 未调用。
- 两项 OpenAPI 生成器测试实际运行，没有靠不安装生成器跳过；另有 `programs.types.test.ts` 的四层编译期约束。
- axe：guest、programs-503、coop-text-edge 和 loading 均通过。只关闭 jsdom 无法执行的 color-contrast，沿用已有 token 对比度测试；不宣称屏幕阅读器语音验收。
- 生产构建首屏 JS gzip **183,140 / 250,000 bytes**，比新 main 基线多 **207 bytes**。懒加载块为 SearchLandingDemoPage / OfflineDemoShell；未调高主块大于 500 kB 的既有警告阈值。
- 61 份 JSON 原字节冻结；最终交付再次直接与仓库外原件比摘要。R3a–R3c 的实现、模型、测试及数据没有修改；package / lock、R2b client／生成 schema／真实会话壳没有修改。
- 类型、零 lint 警告、格式、schema 一致性和源码范围的最终命令及报告见 `artifacts/landing-check-final.log`、`landing-format-final.log`、`landing-schema-final.log` 与 `landing-final-audit.json`。

### 具名变异与验证工具修正

本轮新增 **29 / 29 KILLED**，27 项以指定行为断言失败为准，另两项要求生成类型对照文件出现指定字段的 `ExpectNever` / TS2349 编译失败。超时、导入失败、少报告不计 kill；不改正确实现来追求 kill。最终证据为 `artifacts/landing-mutations-2026-10-24T18-50-00-922Z/summary.json`，完整 1,519 测试基线通过，sourceUnchanged=true。

| ID      | 故意改坏的行为                                                          |
| ------- | ----------------------------------------------------------------------- |
| L01–L03 | 接受其他学期、把选修算入挑课、只查第一个第 1 学期分组                   |
| L04–L06 | 精选顺序改动、不要求在列表里、卡片错误使用列表 prefix                   |
| L07–L09 | 空字符串不算缺失、等级 0 也锁、检查／显示第三条 Co-op                   |
| L10–L12 | 普通失败未适配、明确 4xx 也提示、临时失败漏掉其他状态                   |
| L13–L16 | 不等整排、缺课程表不算 loading、无效依赖拖住页面、提示重复              |
| L17–L19 | 发送 label、已有空回答轮仍显示落地、丢弃对话焦点                        |
| L20–L22 | 延迟多 1ms、卸载不清计时器、换参数不重建会话                            |
| L23–L27 | 重复项目 ID 放行、课程表身份不查、学期上界改 9、空课 ID 放行、CR 未去除 |
| L28–L29 | 顶层 plan_count、嵌套 primary_name 的消费类型偏离生成 API 类型          |

准备工具时的失败保留：第一次快照缺少 index.html 和生成器 package.json；第二次补生成器后缺 Prettier 配置，导致生成文件引号格式不同；均为隔离副本准备失败，**没有当成产品缺陷或变异 kill**。补齐这些配置与两套 node_modules 的只读依赖链接后，完整快照基线通过。

首次完整变异的两项类型漂移确实已被编译器抓住，但工具最初匹配错了诊断编号（TS2344）；按实际 ExpectNever 的 TS2349 修正后 29 项全部命中。最后一次测试格式化后再冻结源文件重跑，以最终快照报告为交付证据。

本轮未重跑旧 R1–R3c 的所有具名变异，旧行为由完整 1,519 测试回归；不把旧批次的变异数量算成本轮结果。

## 浏览器与交付边界

- 使用 Computer Use 的内置浏览器、最终生产构建、Vite preview `127.0.0.1:4173`。入口 `assets/index-DoJ5jDlQ.js`，懒加载页面 `assets/SearchLandingDemoPage-EpUa2Glc.js`；最终构建证据在 `artifacts/landing-browser-final/`。
- **19 张最终截图**覆盖 1440×900、390×844 下的 guest、member-2、programs-503、coop-text-edge、cs-curriculum-text-edge、nothing-at-all、一直加载、点击示例进入对话；另有等待态／完成态及手机正文补拍。记录按名称保留最后一次观察，冷启动的 Suspense 过渡截图不冒充完成态。
- 所有测点根 scrollWidth==clientWidth，无整页横向滚动。Co-op 特殊文字与课程表特殊文字均作为文字显示，长课名和网址折行；warn / error 控制台记录为空。
- 实际键盘验证项目按钮、两张课程查看、去 Co-op、示例、返回、重试；可见焦点为钴蓝 2px。四个示例均可进入对应合成回答，英文 query 正确；点击后焦点在对话区，返回后焦点在落地演示容器。
- 浏览器接口不提供完整网络瀑布或 resource timing；因此无 API 请求的证据是路由隔离的静态调用链及空 QueryClient 的真实整页测试，**完整网络面板仍由独立验收确认**。未操作真实登录、生产数据、模型、发布或 NAS。
- 本轮临时浏览器标签页与 viewport 已清理；只停止本轮拥有的 preview 进程。用户自己打开的标签页不处理。
- R4a 等独立验收后的 R3d 末端开始，共享三个文件和校验器；R3/R4 真实取数、缓存、路由、允许保存状态及后端 plan_revisions 契约仍按原分工处理，不在此批夹带。
