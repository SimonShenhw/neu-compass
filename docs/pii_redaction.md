# PII 脱敏指南 (NEU-Compass)

> **适用范围**: 任何即将进 `coop_experiences` 表 / Co-op 上传 / 未来扩展到学生 review 的数据
> **强制阶段**: 写库前。一旦数据进了 SQLite 即视为已发布,事后撤是补救不是预防
> **关联**: PLAN §6.3 PII 脱敏标准 / §9 法律合规 / ADR(待补)

## 0. 为什么 NEU 这件事尤其敏感

Northeastern AAI/DS/CS graduate cohort **极小**。每年 AAI fall 入学约 100-150 人,
按 Quant / 大厂 / 生物 / 创业 4 个 industry 分桶,每桶**几十人**。
再按公司、岗位、入学届一切就**单数级别**——别人一看就知道是你。

你写 "我在 Boston 某 Quant 机构 2025 Summer 做 Quant Dev,面了 LSTM 时序模型",
**就这一句话**,只要你那届有一个人在 Quant 公司做了带时序模型的 Co-op,你就被定位了。

这是为什么 PLAN §6.3 / v1.3 加了 **k-anonymity** 强制规则:不允许唯一三元组进库。

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

**已发布的所有 Co-op 数据中,任意三元组必须出现 ≥ 2 次。**

实操:用 `schemas.coop.is_uniquely_identifying`:

```python
from schemas.coop import is_uniquely_identifying
from db.coop_repository import CoopRepository

repo = CoopRepository(conn)
existing = repo.list_all()
new_record = CoopExperience(...)

if is_uniquely_identifying(new_record, existing + [new_record], k=2):
    # 三元组目前在库内只出现 1 次 (即将插入的这条)
    raise ValueError(
        f"k-anonymity violation: ({new_record.company}, "
        f"{new_record.role}, {new_record.coop_term}) appears only once. "
        "Generalize company to industry bucket or wait for a 2nd contribution."
    )
```

### 2.3 处理唯一三元组的两种路径

**路径 A — 等待 (推荐)**:
- 把记录加进 review queue, 状态待发布
- 每收一条新 Co-op,重新跑 k-anonymity 检查
- 直到出现第二条同三元组,两条一起发布

**路径 B — 桶化 (打折)**:
- 把 company 改成 industry 桶: "State Street" -> "Boston 大型资管 (Quant)"
- 重新检查 k-anonymity (现在的三元组是 ("Boston 大型资管 (Quant)", "Quant Dev", "Summer 2025"))
- 桶化后通常通过

### 2.4 反例: 桶化也救不回的场景

如果 NEU 那届只有 1 人在 Quant 行业做 Co-op,**任何**桶化都还是定位到他。
此时:
- **不发布**, 永久存在 review queue
- 或得到该同学的明确知情同意 + 书面授权 (ADR-0007 待写)

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
☐ 6. is_uniquely_identifying() 跑过, 返回 False
☐ 7. 在 redaction_audit 字段记录: 谁审 / 删了什么 / 桶化了什么
☐ 8. (UGC 路径) 上传者明确同意 PLAN §6.3 redaction policy
```

任何一个未打勾, 不入库。

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

```bash
# 把那条 Co-op 隐藏掉, 不让任何用户能看到
sqlite3 ~/neu-compass-data/courses.db <<EOF
UPDATE coop_experiences
SET visibility_level = 99,  -- 大于任何用户的 contribution_count
    redaction_audit = 'EMERGENCY HIDE: PII LEAK ' || datetime('now')
WHERE coop_id = '<the_problem_coop_id>';
EOF
```

(visibility_level=99 利用 `users.contribution_count <= visibility_level` 这条比较,
没人贡献 99 条所以谁都看不见。比 DELETE 好,保留审计trail。)

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
- 自动 k-anonymity 检查在 API 层 reject 上传
- 区分 公开级别 0/1/2 之外的 "撤回区" (level=99)
- 法律 / 合规审计 log
- 上传者授权状态记录 (ADR-0007 待写)
