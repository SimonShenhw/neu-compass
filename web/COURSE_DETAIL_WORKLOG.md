# R3b 课程详情修改记录

## 范围和基线

- 2026-10-23，按 `R3B_COURSE_DETAIL_SPEC.md` 实施。
- 从 `origin/feat/web-requisites @ 87f96d8` 开 `feat/web-course-detail`，包含独立验收补的 4 个 R3a 测试。
- 干净安装后基线：527 个测试通过，类型、lint、构建通过；JS gzip 159,607 bytes。
- 只改 `web/`，不增加依赖；R3a 源码及其测试保持原样，原型课程详情也不改。
- 只做本地实现与提交，不取数、不推送、不发 PR、不合并、不部署。

## 修改索引

| 位置                                             | 修改与理由                                                                      |
| ------------------------------------------------ | ------------------------------------------------------------------------------- |
| `src/api/course.ts`                              | 补本页消费的课程详情、目录快照、证据类型，保留 R5b 的原类型                     |
| `src/models/courseDetail.ts`                     | unknown 入口、独立字段归一化；目录 absent／invalid／ok 三态，失败不拖累其他证据 |
| `src/models/courseDetailFormat.ts`               | Python 数字／时间适配、splitlines、提示及字段标签、来源稳定计数、摘要与支持值   |
| `src/models/compare.ts`                          | 只导出已有 scaledEven，复用精确二进制舍入，不改算法                             |
| `src/models/compareList.ts`                      | 导出共享 MAX_COMPARE_COURSES=4，store 与详情按钮用同一上限                      |
| `src/features/course-detail/`                    | 详情主体、概览／来源证据、纯文本与原生折叠辅助、tokens 样式；测试在同目录       |
| `src/pages/CourseDetailDemoPage.tsx`             | 两个参数选择器、固定导出数据、回调 status；不触碰真实 store                     |
| `src/fixtures/courseDetailDemo.ts`               | 只加载九份 API 导出，集中管理 case 与四种对比列表                               |
| `src/fixtures/course-detail/`                    | 9 份导出 + expected 下 9 份标准答案；内容不改                                   |
| `src/App.tsx`、`src/layout/routePresentation.ts` | 新增不进导航的演示路由与标题；旧课程路由不改                                    |
| `scripts/mutations.mjs`                          | 新增 M131–M152；原 M64 仅将四门上限锚点改成共享常量                             |
| `.prettierignore`、`README.md`                   | 冻结生成数据原字节，记录入口、选择、理由与边界                                  |

## 关键行为与实现决定

1. 身份三字段非空才展示；其他字段各管各的，列表有坏项整块拒绝。0 学分／0 工作量保留，空学期不画 chip。
2. 目录按规范化课号的科目精确匹配官方 HTTPS URL；坏快照同时隐藏描述与两个链接，并保留两句规定警告。Python 空值与校验失败分开。额外键忽略；可选目录字段沿用 Python 默认值，显式 null 的 prereq_codes 不通过。
3. snapshot_id 只需为字符串；摘要格式另判。坏摘要仍显示有效描述，但不产生错误的摘要或 title。
4. 精确复用 R5b 的 :g、UTC／无时区处理、IEEE-754 取偶数；百分比先乘 100 再取整。置信度测试包含浮点邻值，不能用 toFixed 冒充 Python。复核 Python 源码后补了合法负零的百分比／置信度符号保留（`-0%`／`-0.00`），增加两个独立函数用例及一个真实页面用例；支持值仍按规范用 JS String。
5. 全套 Python 换行符单行化，稀有记录分隔符不与前一 CR 意外合并；正文／引文保留空白，标签值与 AI 备注只去 CR。
6. 来源先稳定去重再计数，同数保留首次出现顺序；概览仅显示已知短提示，完整说明中未知代码／字段原样保留。
7. 主题与技能全部显示，不套用八项上限；未知方案关系按本页契约用 foundation，不沿用 R5b 的未知原样标签。未使用的 program_id 不额外限制。
8. 组件无网络、URL／storage 写入；演示外壳独立负责 URL，case／compare 任一个变化都重建详情。已有优先于满额，回调使用 course_id，不使用课号。
9. R3a 参数原样交入，以 course_id 为 key。没有改 R3a 的选择、规则、文本或链接校验。
10. 沿用 Sites 的本地预览与现有 tokens，不注册站点、不发布。Computer Use 用于真实浏览器检查，不能以 jsdom 绿色代替布局与键盘验收。

## 验证记录

### 来源和契约

- 18 份 JSON 的原始 SHA-256 独立锁定；共 9 份、12 个 scenario，展开后逐项核对实际 DOM（类型、文字、顺序、depth、href、title、disabled）。expected 不参与页面生成，也不打进生产包。
- `detail_fixtures/source.sha256` 列的 14 个生产者源文件，与 `2aa23279abd73009455bcd102c6b2a5a2edd64db` 的 git 对象逐项核对一致；没有在带 .env 的 main checkout 跑生成器或测试。
- 自增测试分别检查每个字段坏形状、目录每条限制、Unicode 20,000 码点、默认值、纯文本／链接白名单、回调、卸载重置与四类 axe 场景。相互独立的有效对照避免一个校验失败掩盖另一个分支。
- 九份原始导出全部没有年度规则文档或可导航旧边。R3a 回调／key 重置及演示的打开回调，使用测试内注入的有效关系走真实组件；固定 JSON 保持不变，浏览器不虚称点过不存在的按钮。

### 本地自动检查

- `npm.cmd ci`：成功，402 packages，audit 0 漏洞；已有 ESLint 9 官方支持例外与 deprecated 提示保留，不改变依赖。
- `npm.cmd run check`：最终补充后 strict 类型、零 lint 警告、30 文件／766 测试、构建通过。基线 527 → 766，增加 239 项。
- 首屏 JS gzip：168,252 bytes，低于 250,000 bytes；未改阈值，未以延迟加载绕过。Vite 仍有 gzip 前单 chunk 大于 500 kB 的提示，不等同于 gzip 超标。
- `npm.cmd run format:check`：最终补充后通过。
- 第一轮完整变异：150/150 KILLED，baseline passed、sourceUnchanged=true，退出 0；证据在 `artifacts/mutations-2026-10-23T19-10-20-636Z/`。之后补负零与类型收窄，不把这轮当作最终版本的变异结果。
- 最终轮完整变异：152/152 KILLED，baseline passed、sourceUnchanged=true，无未解决项；证据在 `artifacts/mutations-2026-10-23T19-17-04-845Z/`。保留原 M01–M130，新增 M131–M152 共 22 项；每项都有规定名称的真实断言失败（M03 为规定的类型编译断言），不是导入错误或超时。

### 真实浏览器（本地生产构建）

内置浏览器分别覆盖 1440×900 与 390×844。截图与 DOM 宽度证据在忽略的 `artifacts/course-detail-browser/`，截图未提交。最终构建 `index-CNFSYp9v.js` 重新覆盖下面 12 组状态，`final-observations.json` 记录这 12 张及 2 张手机来源／引文补图；早一轮截图另保留，不能混作最终 bundle 证据。

| 场景                                          | 桌面 | 手机 |
| --------------------------------------------- | ---- | ---- |
| cs-6140-everything／empty，全部折叠框展开     | 已查 | 已查 |
| cs-6140-everything／full-with，全部折叠框展开 | 已查 | 已查 |
| ds-5220-conflicts                             | 已查 | 已查 |
| cs-5800-identity-only                         | 已查 | 已查 |
| synth-cs-9999-test-record／0 学分             | 已查 | 已查 |
| derived-foreign-catalog-link                  | 已查 | 已查 |

- 全部记录的页面 scrollWidth 与 clientWidth 相等；没有用整页 overflow hidden 遮住问题。另拍正文、两段描述、方案／AI、去重 ID 与引文的视口；手机所有详情子节点无内部宽度溢出。
- 原生 AI、来源及来源 ID 折叠框用 Enter 展开；加入对比用 Enter／Space 得到准确 status，仍保持空列表／按钮可点。最终构建依次 Tab 经过加入按钮、概览目录链接、AI 标题、来源标题、来源目录链接和 ID 标题，均有钴蓝 2px 焦点边框；没有用 Enter 打开外站。
- 两个外部链接 href 精确为受检目录 URL，target=_blank、rel=noopener noreferrer；完整 ID title 核对正确。没有点击外部链接。
- 此次浏览器 warn／error 日志为空；DOM 声明的 JS／CSS 均同源。没有完整请求瀑布能力，所以不将源码无 HTTP 客户端及测试禁 fetch 等同于完成网络面板验收。
- 按 Sites 本地预览约定，验收后只停止本轮启动的两个 Vite preview 进程；最终确认 4173 没有监听，恢复浏览器原视口。没有关闭用户标签页或修改网络设置。

### 提交前范围检查

- 42 个暂存文件全部在 `web/`，CRLF 文件 0；19 个 TypeScript 文件经 AST 检查显式 any 为 0；常见私钥／凭证模式扫描命中文件 0（不将模式扫描称为完备安全审计）。
- 18 份生成 JSON 重新直接与评审原件做 SHA-256 比对，18/18 相同。
- R3a 的组件、模型、API 类型及测试、旧 `pages/CourseDetail.tsx`、package.json／lockfile 与基线 diff 为空；没有新增依赖。
- `git diff --cached --check` 通过。最终提交只留本地，交付提交号供独立验收。

## 具名变异（本轮新增）

| 变异      | 错误行为                                                                                         |
| --------- | ------------------------------------------------------------------------------------------------ |
| M131–M134 | 百分比 Math.round、置信度 toFixed、:g 换 String、日期不换 UTC 并误加时区                         |
| M135–M139 | 来源同数乱序／重复计数、未知代码丢失、目录科目不校验、描述越界                                   |
| M140–M145 | 满额优先于已有、0 学分丢失、空 chip 显示、未知关系错误标签、不完整 splitlines、AI 备注 CR 未去除 |
| M146–M150 | R3a 不按课程重挂载、坏 ID 错误 title、ID 未去重、数组支持值错误格式、compare 切换未重置          |
| M151–M152 | 合法负零的百分比／置信度符号丢失                                                                 |

完整结果、断言失败名称与 frozen hash 保存于上述两轮 `artifacts/mutations-<UTC timestamp>/`；仅具名断言失败算杀死，超时、导入错误不算。交付以最终 152 项记录为准。

## 明确未做

- 不接真实 API、resolver、加载／失败外壳、分享链接或全站会话；不做资格判断。
- 没有改后端、Streamlit、部署配置、R3a 或原型课程页；没有推送、PR、合并或部署。
- 完整网络面板、屏幕阅读器语音与真实账号／线上验收仍需后续负责方检查。
