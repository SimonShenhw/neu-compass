# 第五批本地验收与缺口清单（05E）

检查日期：2026-10-02。对象是 `bb2f6e3` 之上的当前本地实现和固定输入，不是该 commit 本身、生产 NAS 或学生个人 Plan of Study。

结论：第五批的有限证据浏览／存储／只读 API 功能阶段可收束，进入第六批本地分享／反馈开发；完整培养要求、个人资格、可靠学期安排和生产发布仍未验收。修改历史继续只记在 [开发修改记录](development-change-log.md)，本页是验收快照，不另起一份变更日志。

后续说明（2026-10-02）：06A 本地精确方案分享已经实现，契约见 [版本化方案分享](program-plan-sharing.md)，最终测试结果见主修改日志；下一入口为 06B 反馈关联。下文的 1813 项测试与家族分享状态保留为 **05E 时点快照**，不将该旧结果挪作 06A 验证，也不改变第五批的证据／个人资格缺口。

## 已实际复核的边界

| 层 | 固定输入与核对 | 本轮结果 | 不证明什么 |
|---|---|---|---|
| 培养方案 05A／05B | 5 个项目页面存档，普通 scope 5 份＋Align／Bridge 2 份；课程组合、分组选修、候选／排除、可选分支 | 两次真实表格审计 CLI 均 exit 0，7 份全部保持 partial | 不是完整 POS、获批路径、成绩或排课结果 |
| 课程先修／描述／学分 05C | 3 个院系页；前批 17 门固定课程＋全部 35 个范围标题，冻结为 52 门 | 52 个年度文档契约与精确 literal 复核；35 范围为 CS 13／DS 10／INFO 12；真实 CLI exit 2 | 仍有 1 个 unparsed，不是全部先修解析通过；campus 保持 null |
| 学校／学院政策 05D | 18 个章节、77 选定块、7 精确关联；来源字节／元数据／位置／标题／hash、方案 revision 与 home college | 整批 CLI exit 0；7 份当前方案 reader 均 ready | ready 仅表示输入／关联一致；不代表完整政策、摘要获官方认证或个人达标 |
| 接口／组件／兼容 | 精确身份与版本、默认留空、失败无旧成功证据、纯文本、旧库不自动建表、隔离同步／回滚等现有测试 | 全套 1813 passed、5 既有弃用警告、0 errors／failures／skips；新增 05D-4 33 项全部执行 | 不含真实账号 OAuth、完整浏览器布局、真实 Gemini 或生产运行库验收 |

本轮复核已有全部来源和公开输入，共 62 文件，审计前后 hash 未变；没有网络请求或数据库连接。随后只新增显式课程选择清单和验收文档，不改来源、方案、解析器或运行库。当前完整输入为项目 5 页、院系 3 页、政策 18 页，合计 26 份 HTML 与 26 份 sidecar；它们不随 Git／Docker build 发布。

课程选择冻结在 `data/course_requisite_sources/acceptance_2026_2027_course_codes.json`，不是运行库已导入课程名单，也不表示只支持这些课程。明确列表避免未来归档变化后悄悄用另一批样本重演验收。

冻结清单后再次实际调用课程 CLI，仍为 exit 2／52 条／1 个 unparsed；63 输入文件（原 62＋选择清单）hash 前后未变。

### 不可抹平的未知

- CS 4992 prerequisite 含旧式外部代码 `CIS 310M`，原因 `unsupported_syntax`；完整原文保留、rule=null。52 条课程找到与文档有效不意味着这段可解释；审计 exit 2 是正确的部分报告状态，不是发布失败或全部语法成功。没有将旧代码改写成类似 CS 编号。
- 不同学校／学院重修章节表述不一致，已在三个相关片段中记录；适用范围与优先级须向学术部门确认，不自动取更宽／更严规则。
- 转入窗口、课程有效期、共享期限分开；延期 petition／部门建议不等于最终批准。证书共享按项目类型／指定证书／方向／课程批准，不据额度或前缀算个人资格。
- 院系页未声明课程校区；目录范围学分不是实际 section 学分；description 关键词是候选原文，不是批准条件已解析。

### 方案上下文与政策层没有被混成一套规则

用当前纯函数对同年度七份规则做显式课程匹配：CS 5004 仅匹配 CS Align；DS 5110 匹配普通 CS、CS Align 和三个 DS 方向；DS 7995 仅匹配 DS-CS／DS-Engineering。DS 4996、INFO 6105／7405／7225 没有有限明确匹配，保持未知；没有从开放前缀／数字区间推断。此核对不是数据库导入或学生所属项目确认。

政策读取另外按显式 plan ID／完整 scope／当前内容 hash／home college 关联：Khoury 三份各 12 页／43 片段，CAMD 一份 9／31，Engineering 三份各 13／53。跨方案复用不计作新增来源或多个学院规则求和。

## 重演入口

在 WSL 的 `/mnt/h/neu-compass` 执行，只读固定归档，不加任何 `--commit`：

```bash
.venv/bin/python scripts/audit_program_rule_sources.py \
  --plan-file data/program_plan_seed/boston_2026_2027_extended_rules.json \
  --source-dir data/raw/program_catalog
.venv/bin/python scripts/audit_program_rule_sources.py \
  --plan-file data/program_plan_seed/boston_2026_2027_pathway_rules.json \
  --source-dir data/raw/program_catalog
.venv/bin/python scripts/audit_program_policy_sources.py \
  --bundle-file data/program_policy_seed/boston_2026_2027_evidence.json \
  --plan-file data/program_plan_seed/boston_2026_2027_extended_rules.json \
  --plan-file data/program_plan_seed/boston_2026_2027_pathway_rules.json \
  --policy-source-dir data/raw/program_policy_catalog \
  --program-source-dir data/raw/program_catalog
```

课程清单只转换成现有 CLI 的显式参数；当前预期退出码为 **2**，要读完整报告中的 unparsed，不吞掉退出码：

```bash
.venv/bin/python - <<'PY'
import json
import subprocess
import sys
from pathlib import Path

codes = json.loads(Path('data/course_requisite_sources/acceptance_2026_2027_course_codes.json').read_text())
args = [sys.executable, 'scripts/audit_course_requisites.py',
        '--manifest-file', 'data/course_requisite_sources/catalog_2026_2027_manifest.json',
        '--source-dir', 'data/raw/course_requisites']
for code in codes:
    args.extend(['--course-code', code])
raise SystemExit(subprocess.call(args))
PY
```

完整测试报告为 Git 忽略的 `data/raw/program-policy-validity-tests-05d4.xml`，复核 tests=1813／errors=0／failures=0／skipped=0。只有 Git checkout 没有私有原输入时，离线审计失败或运行 reader unavailable 是预期行为，不应换抓最新网页来冒充旧输入恢复。

## 后续顺序与验收门槛

| 顺序 | 事项 | 明确验收标准／边界 |
|---|---|---|
| 06A 本地优先 | 完整方案分享范围，兼容旧 course／program 家族链接 | 当前分享只定位家族；新增链接须精确表达已选方案，不猜个人年度／路径；缺失、冲突、旧 revision 明确提示，不选同前缀第一份 |
| 06B | 👍／👎 反馈与真实回答／查询关联 | 区分真实用户与合成测试，不制造 organic 样本；未经批准不改生产 query_log 或发送分发消息 |
| 发布前 P0 | 私有输入恢复、真实数据库副本演练、API／UI 联合发布与回滚 | 先明确副本／备份和目标路径，核完整来源；只在确认副本里演练原子迁移／导入、重复幂等、未知保留，再确认生产发布。不在 GET 自动迁移或重新抓取 |
| 人工核验 P0 | Google 登录／刷新全链路；个人官方 POS 与 catalog term | 需真实账号及用户确认，不由测试或春／秋入学猜测替代；本轮没有登录或读取个人成绩 |
| 规划前 P1 | DS Align 年度来源、剩余学院／项目例外、同一方案跨组计入、批准和 section availability | 分 scope 补官方证据；没有完整事实前不把浏览层接成个人资格／可靠学期安排保证 |
| 后续 P1 | CS 4992 旧式外部代码语法 | 先确认代码来源和语义，增加完整支持与负例，不能为了得到 exit 0 丢掉未知分支 |

第五批阶段收束不表示上述缺口已解决，也不改变原分发优先级。真实分布评测／门控重校准仍需实际用户使用；本轮未检查 organic 数量，不引用旧快照作为当前计数。未提交、推送、部署、改运行 `.env`／compose 或生产数据。
