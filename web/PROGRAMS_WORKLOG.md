# R4a 培养方案页修改记录

2026-10-24，用户要求继续推进，按 R4A_PROGRAMS_SPEC.md 从 R3d `f871de9` 开 `feat/web-programs`。R3d 尚无新增独立验收意见；说明书允许后续验收修正再并入。本轮只改 web/，不接接口、不推送、不部署。

- `ebaec74`：独立提交，只给 R3a 的 programTree 加 export，不改逻辑。
- 复用 R3d Load、项目列表／课程表检查与无请求演示壳；方案的内容版本直接使用参数，不重算 Python 哈希。
- 35 份导出、40 份标准答案原字节复制，生成器不运行。
- 已实现受控列表／课程表、政策身份来源校验、分享链接与独立演示。

## 文件与修改索引

路径相对 `web/`。

| 文件                                                                         | 修改内容                                                                                  |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `src/models/requisites.ts`                                                   | 仅 export programTree，独立提交 `ebaec74`                                                 |
| `src/api/programs.ts`、`programs.types.test.ts`                              | 新增完整方案、范围、关联、政策、片段及来源类型；七组编译期生成类型对照                    |
| `src/models/programGuard.ts`                                                 | 码点长度、真实日期、官方目录完整 URL、范围身份及哈希检查                                  |
| `src/models/programPlans.ts`                                                 | 单份方案校验；按原顺序说明坏记录；重复 ID 或范围的成员整组排除                            |
| `src/models/programPolicy.ts`                                                | 政策来源、学院路径、身份、版本、日期、片段和顺序校验；省略的 source_kind 归一为 paragraph |
| `src/models/programFormat.ts`                                                | Python 空白集合、scopeLabel、徽标、学期标题、UTC 捕获文字、分享编码；显式适配 ApiError    |
| `src/features/programs/ProgramList.tsx`                                      | 受控项目列表、空／加载／失败／格式错误及回调                                              |
| `src/features/programs/ProgramCurriculum.tsx`                                | 受控方案选择、规则树与来源、分享折叠框、旧课程表和课程回调                                |
| `src/features/programs/ProgramPolicies.tsx`、`ProgramParts.tsx`              | 政策逐步拒绝规则、片段展示、原生折叠框及官方链接                                          |
| `src/features/programs/Programs.module.css`                                  | 现有浅色 tokens、双列／单列、长 URL／哈希／规则折行                                       |
| `src/features/programs/useProgramDemoLoad.ts`                                | 仅演示用计时请求、StrictMode 清理及卸载取消                                               |
| `src/fixtures/programsDemo.ts`、`programsScenarios.ts`                       | 固定输入来源映射、参数默认及五类方案政策来源；运行时不导入 expected                       |
| `src/pages/ProgramsDemoPage.tsx`                                             | 37 场景、四速度、打开／返回／选择／刷新／重试的可继续操作演示                             |
| `src/features/programs/Programs.test.tsx`、`programTestUtils.tsx`            | 实际 DOM golden、真实 Radix 选项、回调、纯文本、axe 与逐层读取                            |
| `src/models/programPlans.test.tsx`、`programFormat.test.tsx`                 | 逐字段拒绝、身份及版本边界、42 个向量及小函数                                             |
| `src/pages/ProgramsDemoPage.test.tsx`                                        | 精确时序、取消、场景切换、交互及空 QueryClient 整页无请求                                 |
| `src/fixtures/programsFixtures.test.ts`、`programs/`                         | 75 份原文件名与 SHA-256 冻结，直接与仓库外原件复核                                        |
| `scripts/programs-mutations.mjs`                                             | 冻结源码、隔离快照、具名变异和指定断言；不改旧批次变异脚本                                |
| `src/App.tsx`、`layout/routePresentation.ts`、`.prettierignore`、`README.md` | 懒加载演示入口／标题、原始数据跳过格式化、使用与决定说明                                  |

## 行为决定

1. 列表和课程表各一个受控组件，只保存原生 details 的展开状态。选中 ID 不在有效列表时显示占位，不替外层清除或自动选最新；只有一个方案也不默认选。空选项使用非法 plan_id `__none__`，避免和合法 ID 冲突。
2. 复用 R3d 的两个项目检查器，不复制；规则树仍用 R3a 的检查与格式函数，课程单行仍用 R3b oneLine。没有更改 R3a/b/c 原有逻辑、测试或数据。
3. 有效方案先逐份检查，再统计所有 ID／范围出现次数；两种冲突各自能独立排除整组成员，幸存顺序不变。完整方案必须经过来源对照且树内没有 unmodeled。
4. 政策先查形状和官方链接，再查当前方案的 ID、五字段范围及外层内容版本，再查状态和审核日期。失败不复用旧缓存，规则树仍可读；本批不计算或验证原文哈希语义。
5. 分享保持 Python 参数顺序、quote_plus 编码和 JSON concentration；只有来源已对照且拥有有效版本的方案给精确链接。分享是可选中的普通文字，只有两类已检查的官方来源成为链接。
6. 备注、规则、摘录、摘要、原文保持文本节点和 pre-wrap，不解释 Markdown／HTML。范围说明压 Python 空白，选择框选项保留原浓度文字；徽标未知值回 foundation。
7. 演示页 `/programs-demo` 懒加载，复用 R3d 的无请求外壳；真实 `/programs` 占位、API 会话和缓存不改。输入来源映射是固定 props，不在生产演示导入标准答案输出。
8. 外层演示负责选择与请求计时；默认 300ms，slow 1200ms，instant 0ms，forever 不排定时器。来源或速度切换以 key 重建；政策切换只重建对应读结果。刷新清掉选择，失败重试仍给相同失败，不伪造成功。

## 已通过验证

- `npm run check`：**56 文件 / 1,729 测试**，类型、零 lint 警告、完整回归和生产构建通过。相对 R3d 新增 210 个测试；没有删减旧测试。
- **37 个实际 DOM 场景**逐项比较 kind、原始文本、折叠深度、按钮 action／ID、R1 Select 的真实全部选项及当前值、链接地址。
- **42 个 Python 向量**：分享 15、空白 14、完整失败文字 13；另测格式小函数、逐字段拒绝、可选归一、码点上界、日期、稀疏数组、受控选择、旧请求取消和回调。
- `api/programs.types.test.ts` 七组新增类型检查，包含独立的 PolicyEvidence.source；R3a 的 ProgramNode 对照保持原状。
- 五种 axe 场景：列表、完整政策全部展开、特殊文本、404、加载；仅禁用 jsdom 不支持的 color-contrast，既有 token 对比度测试仍运行。不宣称真实屏幕阅读器语音验收。
- 首屏 JS gzip **184,151 / 250,000 bytes**，较 R3d 增加 1,011 bytes；新演示块 ProgramsDemoPage，继续懒加载。既有 >500KB 构建警告阈值未改。
- `format:check` 与 `gen:api:check` 通过；没有新增依赖、修改 lock、生成 schema 或旧脚本。
- 75 份 JSON 和原件逐字节一致；修改只在 web/；无 CR、无 TS any；R3a 只多一个 export，R3b/c 以及 R3d 的两个项目检查器不改。

证据：`artifacts/programs-check-second.log`、`programs-format-first.log`、`programs-schema.log`、`programs-guard-refined.log`、`programs-audit-first.json`。

## 浏览器验证

- 最终生产构建入口 `assets/index-DDlSWcxe.js`；1440×900 和 390×844 两种尺寸，共 **18 张截图**及 `artifacts/programs-browser/observations.json`。
- 两种尺寸各覆盖 list、cs-nothing-selected、cs-standard-ready（全部证据展开）、cs-align-not-linked、cs-text-edge、cs-404、list-503、加载中；另补手机政策／哈希与课程行正文。
- 全部测点根 scrollWidth==clientWidth，无整页横向溢出；实看手机特殊文字、方案选项弹层、政策正文、哈希折行及课程卡片。控制台 warn/error 为零。
- 实际键盘 Enter 打开项目、选择方案、展开来源／分享／全部政策片段；Space 查看课程，Enter 刷新清除选择、返回列表、重试固定失败。查看按钮的可见焦点为钴蓝 2px；status 输出真实课程 ID。
- 未访问任何官方来源链接或真实 API；无 API 的证据是演示路由静态隔离和未预填 QueryClient 的整页测试。浏览器接口不提供完整网络瀑布，**完整网络面板仍待独立验收**。
- 仅停止本轮拥有的 preview PID 18020，关闭本轮验证标签并恢复 viewport；用户原有标签保持原状。

## 验证中发现并处理的事项

- 首次额外交互测试发现无参数回调会收到 React 事件对象，已改为显式零参调用；DS 测试里缺失的 `-ai` 后缀按固定数据纠正。
- 枚举严格要求字符串，拒绝形似合法枚举的单元素数组；未知徽标不用对象原型查表，`__proto__`、`constructor` 也正确回退。
- 控制分隔符正则与 Python 定义一致；仅在该正则上局部说明 ESLint 例外，不全局放宽规则。
- 首轮变异快照基线全过，但 ID 去重用例同时触发了范围去重，不能独立抓住删掉 ID 检查；已改成相同 ID、不同 campus。政策 link ID 的变异先前选错了测试目标，现改为既有的单字段校验测试。第 23 个替换锚点不唯一导致工具停止，已改成唯一锚点，并在任何变异前集中预检所有锚点；这些工具结果不冒充全部通过。

## 交付边界

### 最终具名变异结果

最终证据 `artifacts/programs-mutations-2026-10-24T23-47-32-150Z/summary.json`：**29 / 29 KILLED**，完整隔离基线 1,729 passed；sourceUnchanged=true。报告的全部冻结摘要再次与当前 src／scripts／配置比较，零差异。

| ID      | 故意改坏的行为                                                                                   |
| ------- | ------------------------------------------------------------------------------------------------ |
| P01–P04 | 完整方案放过 unmodeled、外国项目混入、ID／范围去重各自失效                                       |
| P05–P10 | 错用 JS 空白、丢 UTC 转换、只删一个根斜杠、null 错编码、URLSearchParams 编码、未知徽标错回退     |
| P11–P14 | 自动选首份、草稿给精确分享、范围浓度不压空白、选项带项目 ID                                      |
| P15–P18 | 不查政策内容版本、缺版本仍显示、范围不匹配仍显示、审核日期比较反向                               |
| P19–P24 | 政策关联另一个方案、顺序不查、学院 URL 前缀不查、只给前缀也放行、非 ready 携带政策、审核早于捕获 |
| P25–P27 | 正常延迟多 1ms、卸载不清计时器、换场景／速度不重建会话                                           |
| P28–P29 | 手写方案 source_title、嵌套来源 page_title 类型偏离生成 schema                                   |

前 27 项以指定行为断言失败计 kill；后两项要求 programs.types.test.ts 出现指定字段的 ExpectNever / TS2349 编译错误。超时、缺报告、导入错误和错误锚点不计 kill。本批没有重跑旧批次所有具名变异；旧功能由完整回归覆盖，不把旧变异数量并入本批。

最终 lint、格式检查通过，见 `artifacts/programs-lint-final.log`、`programs-format-final.log`；源码／原始数据／浏览器范围复核见 `programs-audit-final.json`。

本轮不含后端 plan_revisions、真实取数／缓存／路由接线、改版检测、草案 evaluate_draft、分享 URL 的读取核验、登录或上线验收。R3d 独立验收若有修正，可再并入本分支。仅本地提交，推送／PR／合并／部署仍按原分工。
