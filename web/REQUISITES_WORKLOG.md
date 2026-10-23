# R3a 先修要求面板修改记录

## 范围与基线

- 2026-10-23，按 `R3A_REQUISITES_SPEC.md` 实施；`feat/web-requisites` 从隐私修复提交 `c6eef7d` 创建。
- 只改 `web/`，没有新依赖；不取数、不碰后端、Streamlit、原型课程详情或原 RequisiteTree。
- 本地提交供独立验收；不执行 push、PR、合并、rebase、部署或真实账号操作。

## 修改索引

| 位置                                             | 修改与边界                                                 |
| ------------------------------------------------ | ---------------------------------------------------------- |
| `src/api/requisites.ts`                          | 面板消费的最小手写接口，R2b 后续可替换为生成类型           |
| `src/models/requisites.ts`                       | unknown 全量形状校验、来源链接、树限制、旧边校验与标注条件 |
| `src/models/requisiteRules.ts`                   | 两个 Python 对齐的纯函数；局部去重和课程后缀供树共用       |
| `src/features/requisites/`                       | 面板、语义嵌套树、原文／证据折叠、同年方案与旧边导航       |
| `src/fixtures/requisites/`                       | 16 份 API 导出及 16 份 Python 标准答案，原字节复制         |
| `src/pages/RequisitesDemoPage.tsx`               | 不在导航中的演示路由，按 case 重置，导航仅提示             |
| `src/App.tsx`、`src/layout/routePresentation.ts` | 注册路由与正确标题，不修改课程详情原型                     |
| `scripts/mutations.mjs`                          | 原 110 项保留，新加 M111–M130，在隔离副本执行              |

## 关键约束和实现决定

- 多年份默认空；单年份只在首次挂载默认显示。清空后不会补选；调用者按课程 ID 设 key，演示再按 case 重置。
- 换年份清空方案；数据移除后清空的选择，即使记录恢复也不自动复活。
- 校验只按前端契约做形状／链接检查，不重解析原文、不核对摘要对应的实际 HTML、不证明个人资格。
- 旧边独立保留；有结构化记录、冲突或非法数据时只供跳转，不加必修性标注。缺表本身不禁止旧标注。
- 原文、原因码、描述、方案文本均为 React 纯文本。只有通过检查的官方来源链接打开新标签页。
- 学分字符串不转数字；UTC 时间只替换末尾 Z；方案保留缩进且允许折行。

## 验证记录

- 初次完整 check：24 个测试文件、523 个测试全过；strict 类型、零警告 lint、生产构建通过。
- 16 份标准答案的 34 个场景逐项比较种类、文字、顺序、选择项与折叠层级。
- 32 个 JSON 的 SHA-256 与导出文件一致；expected 不进入产品 bundle。
- 逐字段破坏测试、节点数／深度边界、局部去重、选择重置／移除、纯文本、回调、演示和四种 axe 状态均覆盖。
- 最终样式构建首屏 JS gzip：159,607 / 250,000 bytes。Vite 提示未压缩单 chunk 超过 500 KB；未调高警告阈值或靠懒加载规避统计。
- npm ci：402 个包安装，audit 0 漏洞；沿用已有 ESLint 9 兼容性例外及其 deprecated 提示，不改依赖。
- 干净安装后 check：24 文件、523 测试，类型、lint、构建及 format:check 通过。手机 CSS 修正和跨年份同 ID 测试补强后，最终完整 check 与格式检查再次通过。变异副本完整基线也通过 523 个测试与类型检查。

### 浏览器验收

按 Computer Use 的浏览器流程在内置浏览器操作生产构建；不是终端脚本或 mock 浏览器。两种视口各覆盖以下 8 种状态：

| 状态                     | 1440 × 900 | 390 × 844 |
| ------------------------ | ---------- | --------- |
| CS 6140 两年份未选       | 通过       | 通过      |
| CS 6140 选 2026–2027     | 通过       | 通过      |
| CS 6140 再选普通 MS 方案 | 通过       | 通过      |
| CS 5008 重复叶子         | 通过       | 通过      |
| DS 5220 两段均未解析     | 通过       | 通过      |
| CS 7800 只有旧边         | 通过       | 通过      |
| 先修存储损坏             | 通过       | 通过      |
| 非法规则树               | 通过       | 通过      |

- 全部已测状态的 document.scrollWidth 等于 clientWidth；不靠隐藏 overflow 掩盖溢出。
- 另展开全部证据与方案片段检查长原文、64 位摘要和缩进规则行折行；手机补拍重复叶子和未解析详情。
- 手机首轮发现「查看」被长课名挤成竖排、summary 的原生标记被原型公共样式抹掉。只在本组件 CSS 固定按钮不收缩／不换行，并保留 summary 的 list-item 标记；复验通过。课号按钮手机高度沿用 control-sm 的 44px。
- 真实键盘：Enter／方向键选择年份和方案，Tab 到规则课号，Enter 触发准确课号；全部 7 个 details 用 Enter 展开；旧边「查看」用空格激活。规则按钮、summary 和查看按钮均有 2px 钴蓝 focus-visible 描边。
- DOM 资源声明仅同源 JS／CSS；源码无 HTTP 客户端，测试禁止 fetch；浏览器 warn/error 日志为空。这不等于完整网络瀑布验收，也未打开两个外部来源链接。
- 截图在本地忽略目录 `artifacts/requisites-browser/`；保存的是滚动位置对应的视口截图，长页以补充视口覆盖，不称作一张完整长截图。不提交图片／本地机器绝对路径。

### 新增具名变异

原 M01–M110 保留。第一轮 128/130 命中：M122 暴露测试遗漏，补上两个年份复用同一 plan_id 的场景；M129 原注入是等价变更（本项目无 m 标记的 JavaScript 正则本来就拒绝末尾换行），不算测试漏检，改成真正绕过方案来源链接限制。没有靠把存活变异标为通过来提高计数；修正后重新执行整批，不仅重跑两项。

最终整批：**130/130 KILLED**，M122、M129 均命中预定名称的真实断言失败；未修改基线通过，sourceUnchanged=true，无未解决项。证据在本地忽略目录 `artifacts/mutations-2026-10-23T11-28-07-832Z/summary.json` 及逐项日志。旧的失败轮保留用于追溯，不当作最终通过结果。

| 编号 | 人为破坏的行为                                    | 实现位置                                         |
| ---- | ------------------------------------------------- | ------------------------------------------------ |
| M111 | single-year default                               | `src/features/requisites/CourseRequisites.tsx`   |
| M112 | multiple years never default newest               | `src/features/requisites/CourseRequisites.tsx`   |
| M113 | explicit empty year persists                      | `src/features/requisites/CourseRequisites.tsx`   |
| M114 | course identity includes name                     | `src/features/requisites/CourseRequisites.tsx`   |
| M115 | conflicting years fail closed                     | `src/features/requisites/CourseRequisites.tsx`   |
| M116 | unusable annual record warning                    | `src/features/requisites/CourseRequisites.tsx`   |
| M117 | stored records block legacy labels                | `src/models/requisites.ts`                       |
| M118 | missing schema alone does not block legacy labels | `src/models/requisites.ts`                       |
| M119 | exact department source link                      | `src/models/requisites.ts`                       |
| M120 | identical sibling leaf dedup                      | `src/models/requisiteRules.ts`                   |
| M121 | terminal Z display parity                         | `src/features/requisites/SourceEvidence.tsx`     |
| M122 | year changes reset plan                           | `src/features/requisites/CourseRequisites.tsx`   |
| M123 | unresolved legacy course has no View              | `src/features/requisites/CourseRequisites.tsx`   |
| M124 | structured records keep legacy navigation only    | `src/features/requisites/CourseRequisites.tsx`   |
| M125 | rule leaf callback uses exact course              | `src/features/requisites/RequisiteRulesTree.tsx` |
| M126 | program area minimum retained                     | `src/models/requisiteRules.ts`                   |
| M127 | course total node bound                           | `src/models/requisites.ts`                       |
| M128 | program depth bound                               | `src/models/requisites.ts`                       |
| M129 | official program source link allowlist            | `src/models/requisites.ts`                       |
| M130 | case change remounts demo                         | `src/pages/RequisitesDemoPage.tsx`               |

## 验收边界

本轮不是 R3 取数集成或线上验收。真实 API 状态、按课号解析、登录、完整网络请求瀑布、屏幕阅读器语音及部署均未验证。

验收后已恢复浏览器默认视口，并停止本轮启动的 4173 本地预览。重新查看请在 `web/` 运行 `npm run preview`，打开 `/requisites-demo`。工作保留在本地分支供独立验收，不执行外部 GitHub 操作。
