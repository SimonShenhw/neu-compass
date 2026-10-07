# PII 脱敏指南 (NEU-Compass)

> **适用范围**: 任何即将进 `coop_experiences` 表 / Co-op 上传 / 未来扩展到学生 review 的数据
> **强制阶段**: 贡献者提交前自行去除直接 PII；写入公开 `coop_experiences` 前人工复审。2026-09-30 开发版本新增私有 `coop_submissions`，私有收集不等于公开，也不代表允许上传直接 PII。
> **关联**: PLAN §6.3 PII 脱敏标准 / §9 法律合规 / ADR(待补)

> **当前实现与运维入口**：[Co-op 私有收集与审核](coop-moderation.md)。该版本尚未部署；待审存储不提供额外静态加密。两账号门槛不能替代文本脱敏、存储访问控制或保留期限管理。

## 0. 为什么 NEU 这件事尤其敏感

Northeastern AAI/DS/CS graduate cohort **极小**。每年 AAI fall 入学约 100-150 人,
按 Quant / 大厂 / 生物 / 创业 4 个 industry 分桶,每桶**几十人**。
再按公司、岗位、入学届一切就**单数级别**——别人一看就知道是你。

你写 "我在 Boston 某 Quant 机构 2025 Summer 做 Quant Dev,面了 LSTM 时序模型",
**就这一句话**,只要你那届有一个人在 Quant 公司做了带时序模型的 Co-op,你就被定位了。

这是为什么需要公开前的群组门控：独有经历可以私有待审，但不能据此直接公开。

## 1. 什么算 PII

### 1.1 直接 PII (绝对不存)

| 类型 | 例 | 怎么处理 |
|---|---|---|
| 姓名 | "我是张三" | 删除整句, 不替换 |
| NEU 邮箱 | `zhang.s@husky.neu.edu` | 直接删 |
| 手机号 | `+1-617-...` | 直接删 |
| 学号 (NUID) | `001234567` | 直接删 |
| LinkedIn / GitHub URL | profile 链接 | 删, 即使是公开的 |
| 微信号 | `WeChat: zhang123` | 删 |
| 头像/照片 | 任何照片 | 不接受图片上传 |

### 1.2 准 PII (组合可识别, 必须脱敏)

| 类型 | 例 | 怎么处理 |
|---|---|---|
| 公司具体名 | "State Street" | **桶化**: "Boston 大型资管" 或行业类别 |
| 具体岗位级别 | "Quant Dev II, L4" | 仅保留 "Quant Dev" |
| 入学届 + 专业 + 国籍 | "2024 Fall AAI 中国男生" | 至少删一个字段, 一般删国籍/性别 |
| 精确薪资 | "$45/hr base + $5K signing" | 桶化为 `$40-50/hr` |
| 上司名 | "manager Sarah Chen 问我..." | "面试官" / "上司", 不带名 |
| 同事名 | "和 Alex 一起做..." | "和团队同事", 不带名 |
| Co-op 时间窗 | "2025 Spring (Jan 14-Apr 25)" | 仅保留学期 `Spring 2025` |

### 1.3 教职信息 (灰色, 个案判断)

| 类型 | 处理 |
|---|---|
| 教授名 (NEU 公开 directory) | **OK 保留** —— 已经公开 |
| 教授 NEU 邮箱 (`@northeastern.edu`) | **OK 保留** —— 已经在 syllabus 公开 |
| 教授对你私下说的话 | **删** —— 即使你能识别教授 |
| 课程评论(RMP/Reddit 外的) | 默认匿名化作者 |

**理由**: 教授姓名 + 课程是 **职务行为**, 已公开。私下言论 + 评分非公开。

## 2. k-anonymity 强制规则 (v1.3 新增)

### 2.1 三元组定义

每条 Co-op 记录的「唯一性指纹」是:
```
(company, role, coop_term)
```

例: ("State Street", "Quant Dev", "Summer 2025") 是一个三元组。

### 2.2 k=2 规则

**公开 UGC 的同一三元组须有至少两个不同登录用户的已审核经历。** 同一用户重复行、身份为空的行和策展种子不计数。种子走独立人工策展，不声称其满足此 UGC 门槛。

实操:用 `schemas.coop.is_uniquely_identifying`:

```python
from schemas.coop import is_uniquely_identifying
from db.coop_submission_repository import CoopSubmissionRepository

# Only approved/published records belong in this final reviewed corpus.
# Production review/publish/credit uses the atomic repository workflow.
reviewed_corpus = [...]  # reviewed CoopExperience objects, including the target
new_record = CoopExperience(...)

if is_uniquely_identifying(new_record, reviewed_corpus, k=2):
    # Keep approved-but-not-public; never echo private triples into routine logs.
    raise ValueError("Publication requires a second distinct reviewed contributor")
```

### 2.3 处理唯一三元组的两种路径

**路径 A — 等待 (推荐)**:
- 把记录加进 review queue, 状态待发布
- 每审核通过一条新 Co-op,重新检查不同贡献者门槛
- 直到第二个不同用户的同组记录也已审核,同组一起发布

**路径 B — 桶化 (打折)**:
- 把 company 改成 industry 桶: "State Street" -> "Boston 大型资管 (Quant)"
- 重新检查 k-anonymity (现在的三元组是 ("Boston 大型资管 (Quant)", "Quant Dev", "Summer 2025"))
- 桶化后仍必须满足两个不同用户的已审核同组记录；泛化本身不是通过条件

### 2.4 反例: 桶化也救不回的场景

如果 NEU 那届只有 1 人在 Quant 行业做 Co-op,**任何**桶化都还是定位到他。
此时:
- **不发布**, 永久存在 review queue
- 当前实现没有「凭同意绕过群组门槛」的分支；授权记录机制仍待单独设计

## 3. 字段级脱敏 patterns

### 3.1 推荐的预处理 regex

```python
import re

# NEU 邮箱
_NEU_EMAIL_RE = re.compile(
    r"\b[A-Za-z][A-Za-z0-9._%+-]*@(?:husky\.neu\.edu|northeastern\.edu)\b"
)

# 美国手机号 (各种格式)
_PHONE_US_RE = re.compile(
    r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
)

# Linkedin / Github URL
_PROFILE_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:linkedin\.com/in/|github\.com/)[A-Za-z0-9_-]+/?"
)

# 中文姓 + 名 (粗略, 易误删: 也会匹配学者名字)
_CHINESE_NAME_RE = re.compile(r"[赵钱孙李周吴郑王...][一-龥]{1,2}")  # 不推荐自动用

# 美元具体数字 (供桶化前清理)
_DOLLAR_RE = re.compile(r"\$[\d,]+(?:\.\d{2})?(?:/(?:hr|hour|year|month))?")

def auto_redact_pre(text: str) -> str:
    """First-pass automatic removal. **NOT a substitute for human review.**"""
    text = _NEU_EMAIL_RE.sub("[EMAIL]", text)
    text = _PHONE_US_RE.sub("[PHONE]", text)
    text = _PROFILE_URL_RE.sub("[URL]", text)
    return text
```

> ⚠️ **自动脱敏 NEVER 替代人工审**。中文姓名 / 隐式称呼 / 地点引用都不在 regex 范围。

### 3.2 必须人工干预的场景

- 隐含称呼 ("我组里的印度小哥说...")
- 地名 ("我是 Beijing 来的")
- 时间窗 ("我开始这个 Co-op 的第三个月" + 公开毕业时间 = 可推断起止)
- 项目名 ("做了一个叫 Compass-X 的内部工具") — 如果项目名本身公开过

## 4. 工作流: Seed Data 入库前的审核 checklist

每条 Co-op (无论 seed 还是 UGC) 提交进 `coop_experiences` 之前:

```
☐ 1. 直接 PII 全部删除 (姓名 / 邮箱 / 手机 / 学号 / profile URL / 头像)
☐ 2. 公司具体名考虑桶化 (除非 k-anonymity 已满足 k≥2)
☐ 3. 同事 / 上司 / 面试官名替换为通用称呼
☐ 4. 精确薪资 -> 桶值 (e.g. "$30-35/hr")
☐ 5. 时间窗仅保留学期粒度 (e.g. "Summer 2025", 不写 "Jun 1 - Aug 15")
☐ 6. UGC：已审核同组集合按不同贡献者检查通过；种子：独立策展确认残余识别风险
☐ 7. 在 redaction_audit 字段记录: 谁审 / 删了什么 / 桶化了什么
☐ 8. (UGC 路径) 上传者明确同意 PLAN §6.3 redaction policy
```

任何一个适用项未打勾，不写入公开经历表；私有收集也必须遵守直接 PII 去除要求。

### 4.1 redaction_audit 字段格式

```
"reviewed_by=<curator_id> | redacted=<删了什么> | bucketed=<桶化了什么> | residual_risk=<残余风险>"
```

例:
```
"reviewed_by=alice | redacted=2 names + 1 phone | bucketed=company->'Boston Quant 大资管' | residual_risk=low (k=3 in cohort)"
```

## 5. 已知失败模式 (持续更新, 警示)

### 5.1 反例 1: PLAN §6.3 给的演示

```
原文: "我是 NEU AAI 2024 fall 入学的中国男生,在 State Street 拿到 Quant Dev 的 Co-op,
       面试官姓张,是 NEU AAI 校友,问了我关于 GRU 模型的细节"

仅删名 ❌: "我是 NEU AAI 2024 fall 入学的中国男生..."
            (信息组合仍可定位个人)

合规改写 ✅:
  "Boston 某金融机构 Quant Dev Co-op 经验:
   - 简历筛选: 重点考察深度学习项目经验
   - 技术面 1: 时序模型 (GRU/LSTM) 的工程细节
   - 文化面: 校友连接很重要"
```

### 5.2 反例 2: 时间窗组合

```
"2025 Spring 起 8 周 Co-op,bridge 两 semester"
+ NEU AAI 已知 Spring 学期 Jan 13 开学
= 准确日期 Jan 13 + 8 周 = Mar 9 结束

→ 删 "8 周",保留 "Spring 2025"
```

### 5.3 反例 3: 项目细节的隐式 PII

```
"我在 Co-op 做了 Compass-X 的 RAG 改造"
+ 公司公开过 Compass-X 这个产品
+ 公司只有 1-2 个 RAG 工程师
= 团队内部所有人都知道这是谁

→ 改成 "做了一个 RAG 系统" / "改进了内部检索工具"
```

## 6. 紧急情况: 如果 PII 已经入库

### 6.1 立即 (5 分钟内)

先通过受控的维护/访问策略暂停 Co-op 公开读取，保留私有证据并交由可信运维处理。本批尚无单条已公开经历撤回接口；不得把重复审核命令当成撤回操作。

**不要设置 `visibility_level=99` 或把它设成 2 来隐藏问题行**：DDL 只允许 0/1/2，而且公开 API 的字段分层不是审核/撤回状态；提高分层不能保证隐藏已泄漏内容。原文的 level=99 紧急 SQL 已移除，不能作为运行指令。

### 6.2 当天 (24 小时内)

- 通知影响到的同学
- 如果在 GitHub / 公开 repo 也已 commit, 走 git filter-repo + force push (破坏性, 三人同意)
- 备份 (rclone / Google Drive) 也要清理对应日期的 snapshot
- 写 incident note 进 `docs/incidents/<date>.md`

### 6.3 当周 (7 天内)

- 复盘: 为什么 review checklist 没拦住
- 修订本指南 (§5 加新失败模式)
- 修订 review 流程 (e.g. 强制 reviewer 是非贡献者)

## 7. 升级路线 (v2)

当前是手工审核。规模上来后:

- 自动 PII 检测器集成 ([Microsoft Presidio](https://github.com/microsoft/presidio) / 自训 NER)
- 继续完善私有收集、人工审核与不同贡献者门控（不是拒绝首条合法提交）
- 用独立审核/撤回状态实现单条下架，不复用内容分层或 level=99
- 法律 / 合规审计 log
- 上传者授权状态记录 (ADR-0007 待写)

## 8. 06B 私有回答反馈的留存边界（2026-10-02）

本地新增 `chat_answers`／`answer_feedback`，与 Co-op 公开审核分开。完整回答与请求筛选值可能复述用户个人信息；原查询继续保存在 query_log。06C-1 起必须运营开关启用、当前请求明确允许且捕获成功；此时即使用户不投票也会保存完成回答。默认关闭，UI 有默认未勾选的保存告知；关闭、取消或清对话不删除原查询／已保存数据。新表没有自动脱敏或清理机制，不能因反馈只收 👍／👎 就称数据没有 PII。

- 原 token 只在 no-store 完成响应和当前 UI 私有状态，DB 存随机凭证 hash；不放 URL、公开访问日志、Git 或导出。清对话／登出清掉 UI 凭证，但不删除 DB／备份记录。
- 七天是**反馈凭证有效期**，不是查询／回答留存期。生产启用前须确认访问控制、前端告知、最小留存／清理及备份／导出脱敏；本批未实施 purge 或个人删除接口，不宣称法规／学校合规已验收。
- 保留评测来源标记，原 NULL 仅表示没有 X-Eval-Run。反馈不是正确性标签，样本导出仍需受控且人工审查，不直接发布用户原文或把下票当 ground truth。
- 外键定义从 query_log → 回答 → 评价的级联关系，删除／备份清理必须由可信运维在明确授权、备份和目标确认后处理；本批只在临时库测试关系，没有对真实数据执行删除。

06B-2 新增 [离线候选导出／审查入口](feedback-review-export.md)：默认只输出统计，显式 JSONL 仍默认元数据，原文需要成对隐私开关和私有新文件。投票凭证及其 hash、OAuth、session 与 raw user_id 不导出；元数据里的 ID／内容 hash／时间／课程线索仍是私有可关联数据，不能直接公开或称匿名化。仓库内限定已忽略的 data/raw/feedback_review，外部目录、Windows ACL、备份与临时文件仍须治理；七天不会清除导出文件。本批只验证合成临时库，没有实际 PII 审查／导出或清理真实数据。

本批测试的缺字段错误栈曾含 Settings 配置值；本地已隐藏敏感字段 repr 和校验字符串输入，并清理本次 RED 报告的错误细节。不能撤回工具输出历史，相关凭证处置／轮换仍须由持有人确认；显式 model_dump／errors() 不自动脱敏，不记录新值。

功能、迁移与测试边界见 [回答反馈说明](answer-feedback.md) 与 [联合发布验收准备](joint-release-acceptance.md)；生产数据库／留存策略修改、密钥操作仍需单独确认。

## 9. 查询日志导出（OPT-01，2026-10-07）

`scripts/export_query_log.py` 改成与 06B-2 相同的契约，见 [查询日志导出](query-log-export.md)：只读已有库、默认只统计；元数据文件不含查询原文和原始 user_id；原文需要成对开关和新文件；仓库内限定已忽略的 data/raw/query_log_review。旧版默认写的 `eval/query_log_export.jsonl` 已加入 Git 忽略，但忽略不替代访问控制、脱敏或留存。query_log 本身仍没有自动清理，保留期仍由运维负责。本批只在合成临时库上验证，没有导出或清理真实数据。
