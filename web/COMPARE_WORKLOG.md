# R5b 课程对比页修改记录

日期：2026-10-22。依据：评审目录 `frontend_react/R5B_COMPARE_SPEC.md` 及本轮用户确认的截图。

## 1. 起点、范围与当前交付

- worktree：`H:\neu-compass-web`，WSL `/mnt/h/neu-compass-web`。
- 从 `6b633b9e814565b9c990bb578fab5384b733bf19` 新建 `feat/web-compare`；保留 `feat/web-coop`，不在 main checkout 运行测试。
- 仅修改 `web/`。不改 Python、后端、Streamlit、Docker、nginx、CI、依赖版本或 lockfile；不接真实接口、登录、缓存、查询日志或模型。
- 交付为本地代码与提交；没有 push、PR、合并或部署。R3 详情页的「加入对比」由另一边接入本批 store；R4 的方案筛选不在此轮。
- 原 Co-op 记录保留在 `COOP_WORKLOG.md`，本文件只记 R5b；R1 历史仍在 `WORKLOG.md`。

## 2. 修改索引

| 文件／边界                                       | 改动及原因                                                                                                        |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| `src/api/course.ts`                              | 手写规定的 CourseDetail / CompareColumn / ComparePageProps 类型；未识别响应保持 `unknown`，不强行 cast 为完整响应 |
| `src/models/compare.ts`                          | 独立纯格式化与校验；七行、列头、来源提示、年度条款、学分范围及数字／日期兼容                                      |
| `src/components/CourseFacts.tsx` / `.module.css` | 可复用列头与事实格；纯文本和经校验的目录链接；单格错误局部退化                                                    |
| `src/models/compareList.ts`                      | course ID 内存列表；added / already / full、顺序、四门上限、移出、清空、多个订阅者；不写 storage／console         |
| `src/pages/ComparePage.tsx` / `.module.css`      | 改为 props-only；前四列、七行、独立 loading／error／ready、查看／移出／清空／重载回调；保留焦点恢复与 sticky 首列 |
| `src/fixtures/compareDemo.ts`                    | 合成数据与八种演示场景；同场景路由往返不复活移出的 ID，外部 clear 后也不自动重填                                  |
| `src/pages/CompareDemoPage.tsx`                  | URL／演示选择器独立外壳；失败列重载 400ms 后恢复原合成错误；切场景／卸载取消计时                                  |
| `src/fixtures/compare/`                          | 七份导出 + 六份标准答案按原字节入库，禁止重新生成或改内容；SHA-256 测试锁定                                       |
| `src/App.tsx` / `src/layout/AppShell.tsx`        | 对比路由接演示外壳；侧栏和顶栏计数统一读取 store                                                                  |
| `src/layout/PrototypeContext.tsx`                | 移除旧 comparison 状态，保留搜索问题和项目／方案状态，不双写列表                                                  |
| 测试、`src/test/setup.ts`                        | 标准答案、分支／安全、store／演示、焦点／路由回归；每项测试后隔离合成会话；fetch 仍禁止                           |
| `scripts/mutations.mjs`                          | 适配四项过时 R1 对比检查，另加 22 项具名 R5b 变异；总计 84 项                                                     |
| `.prettierignore` / `README.md`                  | 仅跳过原始 JSON 的自动格式化；补演示入口、设计取舍、真实集成边界和运行方式                                        |

## 3. 明确的行为选择

1. 七行始终显示；移除「只看不同的行」和「按方案看」。不从旧 seed 推断注册或毕业资格。
2. 加载直接写「正在加载」，不制造骨架内容；缺列也当独立 loading，可移出。只有存在失败列时显示「重新加载」。
3. 长描述不截断，全文换行显示。避免隐藏来源／提示或增加多层展开交互，代价是表格较长。
4. 目录 URL 必须精确等于对应课号前缀的官方 HTTPS 路径；额外键、其他网站、查询串、前缀不符和错误字段类型都拒绝。失败不保留描述／链接／抓取时间；认识的警告仍按 Python 来源逻辑处理。
5. 有时区的时间转 UTC，无时区的时间不补时区；日期本身也校验，避免 JS 自动把二月三十日滚到三月。
6. 百分比是 `.5` 取偶数，不用 `Math.round`；工作量数字对齐 Python 六位有效数字 `:g`，包括指数格式和精确二进制中点。
7. 年度规则核对 ID、课号、课名；同年度重复不任取一份。所有年度均比较先修和共修；解析树做深比较，未解析原文全长比较，不只看首尾或前 600 字。
8. 课程文字不解析 HTML／Markdown，不自动链接正文 URL；未知方案类型原样显示，不误标成基础课。
9. store 优先判断 already，再判断 full；满四门时重加原 ID 仍返回 already。R2 真实登录／退出必须主动调用 clear；演示刷新重填不能充当身份隔离验收。

## 4. 测试过程与证据

原始日志位于本 worktree 的 `web/artifacts/`，属本地验收产物，不提交；可按 README 命令重跑。

| 阶段               | 结果                                                      | 本地证据                                                                         |
| ------------------ | --------------------------------------------------------- | -------------------------------------------------------------------------------- |
| 旧实现基线         | 163 passed，10 files；原类型／lint／构建通过              | `compare-baseline-2026-10-22.log`                                                |
| 新行为 RED         | 20 failed / 4 passed；真实行为断言失败，不是导入错误      | `compare-red-2026-10-22.json` / `.log`                                           |
| 标准答案 GREEN     | 24 passed；六份列头／七格／顺序／链接全部对齐             | `compare-green-1-2026-10-22.json`                                                |
| 中途类型检查       | 未使用 import 和 RTL 不支持的选项已修正，不放宽 strict    | `compare-types-1-2026-10-22.log`                                                 |
| 完整回归第一遍     | 251 passed，15 files；类型／lint／构建通过                | `compare-check-1-2026-10-22.log`                                                 |
| 具名变异           | 84 / 84 killed；基线通过，源码前后 SHA-256 一致           | `mutations-2026-10-22T22-08-51-690Z/summary.json` 及各项 JSON／log               |
| 干净安装后复验     | `npm ci` 成功；251 passed，15 files；类型／lint／构建通过 | `compare-ci-2026-10-22.log` / `compare-check-final-2026-10-22.log`               |
| 最终格式及完整复验 | 格式通过；251 passed，15 files；类型／lint／构建通过      | `compare-format-final-2-2026-10-22.log` / `compare-check-final-2-2026-10-22.log` |

第一次最终格式检查指出 `compare.ts` 的排版差异，已用 Prettier 修正，没有忽略该文件；日志 `compare-format-final-2026-10-22.log` 保留。修正后完整复验及 84 项变异再次全过，最终 SHA-256 对应提交的源码；变异副本基线也再次通过全部测试和类型检查。

**最终变异证据：** `mutations-2026-10-22T22-15-44-376Z/summary.json` 及各项 JSON／log，84 / 84 killed，`sourceUnchanged: true`。交付文档补齐后的全项目格式检查记录为 `compare-format-delivery-2026-10-22.log`。

最终入口 JS gzip 为 **139,952 / 250,000 bytes**，与浏览器验收构建同为 `index-eZq2OaPi.js`，未靠动态拆分隐藏首屏依赖。`npm ci` 报告 0 vulnerabilities，但仍有既存 ESLint 9 不再受支持的 deprecated 提示；这是 README 已声明的兼容性例外，不称为无警告安装。

测试覆盖说明：

- 六份标准答案逐项检查 header、七行 main／note 的顺序、topics／program_context 结构、目录链接、先修摘要。13 份文件均校验原 SHA-256，未改 fixture 内容来迁就实现。
- 先修覆盖 null、形状错、schema 不可用、坏记录、三项身份不符、全无本课、同年重复、单年度、中间年度不同、未解析后半段不同、仅共修不同；另测树对象键序不影响含义。
- 学分范围只取最新本课记录，排除外国课程／同年重复／fixed。数字包括 12、12.5、0、0.125／0.375／0.135 权重、六位有效数字中点和科学计数。
- 404／null／429／503／418、三种无法识别 body、缺列 loading、坏一格、坏列头、四列上限、回调精确 ID／零参数、纯文本、未知类型／缺失代码、三种 axe 状态。
- store 多订阅者、no-op 快照、不可变顺序；离开返回、外部 clear、400ms 延迟及切场景取消；侧栏计数、旧搜索／课程／Co-op 及路由焦点仍回归。
- jsdom 的 axe 不提供真实布局／屏幕阅读器语音结论；token 对比度与浏览器布局另验，不把本地绿色解释为上线。

### 新增的 22 个具名变异

| ID      | 人为破坏                                         | 结果                         |
| ------- | ------------------------------------------------ | ---------------------------- |
| M63–M64 | 满四门重加误判 full、允许第五门                  | 对应 store 断言杀死          |
| M65–M66 | `.5` 不取偶、六位有效数字变五位                  | 数字断言杀死                 |
| M67–M69 | 放过非官方 URL／额外键、忽略时区偏移             | 校验／时间断言杀死           |
| M70–M73 | 只比最后一年、截断未解析原文、漏共修、漏课名身份 | 年度分支断言杀死             |
| M74–M75 | 取最旧学分范围、坏格伪装成没数据                 | 范围／局部错误断言杀死       |
| M76–M77 | 失败列回调错 ID、无法识别响应伪装没记录          | 失败状态断言杀死             |
| M78–M79 | 去掉 400ms 延迟、返回页面复活已清空列表          | 演示状态断言杀死             |
| M80–M82 | 未知方案误标基础、课名解析 HTML、展示第五列      | 原样文字／安全／上限断言杀死 |
| M83–M84 | 清空不调回调、提示不去重                         | 回调／提示顺序断言杀死       |

原 M01–M62 仍执行。M15 改查七行，M16 改查新 store 移除，M19 保留项目／方案一致性，M25 改查无关列更新不抢焦点；不再维护已按说明书移除的行筛选控件断言。

## 5. 浏览器验收

实际使用生产构建及本机预览，不是 jsdom 截图。遵循 Sites 的本地预览流程，未调用托管／发布；浏览器只操作合成数据。

- 1440×900 和 390×844 各拍七种：four、one、empty、failed、unrecognised、bad-cell、requisites-unavailable，共 14 张完整页面截图；另有 loading、键盘横滚、空状态焦点及最终预览。
- 路径：`artifacts/compare-browser-2026-10-22/desktop-<case>.png`、`mobile-<case>.png`；尺寸／行列／焦点测量在同目录 `measurements.json`。
- 两组整页 `scrollWidth` 都不超过视口；手机四列区域 clientWidth 341、scrollWidth 944。方向键使区域 scrollLeft 从 0 到 80，首列 x 保持 17；不是隐藏 body 溢出掩盖宽度问题。
- 键盘 Tab：演示选择器 → 清空 → 表格区域 → 查看 CS 5800 → 移出 CS 5800。区域焦点有 2px 钴蓝 outline。
- Enter 移出 CS 6140 后焦点到 DS 5220；失败 404 列移除后焦点到 CS 6140；清空／移出最后一门后到「回到课程搜索」。侧栏／顶栏数量同步更新。
- 重载即时只有两门失败课程的 14 格变成加载，两门正常标题仍在；随后恢复同一组模拟失败，不假装请求成功。精确 400ms 边界由假时钟行为测试及 M78 额外验证。
- 浏览器捕获的 error／warn 日志为空。DOM 的入口 JS／CSS 为同源 `/assets/`；没有打开外部目录链接。
- 4173 启动返回 EACCES；只读检查证实 Windows 排除端口范围 4117–4216 覆盖它。临时用 5173，不改系统设置。验收后恢复临时视口、停止本轮拥有的 preview 进程，不清除用户标签页。

## 6. 未完成边界与交接

- 真实网络面板的完整请求瀑布、真实身份刷新／退出、接口端到端、缓存、线上部署、屏幕阅读器语音均未验收。现有浏览器接口不提供完整请求瀑布；静态资源与源码检查不能替代它。
- R3 可以复用 `CourseHeaderFacts` / `CourseFactCell` 及 `addToCompare(id)`，自行实现详情按钮和解析真实课程 ID。不要把课号当成 ID，不要把 demo 默认四门带进正式壳。
- R2 应替换手写接口类型、演示外壳及数据来源；保留页面 props 边界，在真实会话身份改变时 clear。真实响应仍需服务端权限和缓存隔离，前端展示不承担鉴权。
- R4 准备好方案和草案数据后，再讨论按方案或差异筛选；不能直接恢复 R1 的静态比较器冒充方案逻辑。
- 本批可在用户／评审副本独立验收后再决定 push、PR、合并。没有扩大这些操作的授权。
