# 双盲标注指南 (NEU-Compass v1.1)

> **用于**: Day 6-13 团队双盲标注 20 门 Ground Truth 课程
> **基础版本**: schema v1.1
> **参考样本**: [scripts/seed_aai6600.py](../scripts/seed_aai6600.py) 是已经标注好的 AAI 6600 完整示例,**先读那一份再读本文档**

## 0. 为什么双盲

两个标注员独立填同一门课,Day 9 用 Cohen's Kappa 算一致性。
**Kappa ≥ 0.7** 直接进 Week 3;**0.5-0.7** 修订指南后重标 1 门;**< 0.5** schema 重新设计。

这个流程的真正产出**不是 20 个 JSON**, 而是**指南本身的演化**——
争议字段集中在哪几处, 哪些字段对人类来说本来就模糊, 这些发现直接喂回给 LLM extraction prompt。

## 1. 时间线

| 阶段 | 时间 | 任务 |
|---|---|---|
| 准备 | Day 5-6 | 每人下载自己负责的课程 syllabus PDF |
| 第一批 | Day 6-8 | 双人独立标 8 门 AAI 核心课 |
| Kappa 一致性会议 | Day 9 | 算 Kappa, 讨论争议字段, 修订本文档 |
| 第二批 | Day 10-13 | 双人独立标剩余 12 门 |
| 验收 | Day 14 | LLM 自动抽取与 Ground Truth 对比 |

## 2. 标注前的准备

```bash
cd /mnt/h/neu-compass
git pull && uv sync
uv run python scripts/seed_aai6600.py --db-path /tmp/check.db --output-dir /tmp/check
# 应该看到 109 测试全过、JSON 4657 字节、应用 AI / Tuesday 17:50 等显示正确
```

跑通之后,把 `data/ground_truth/` 当工作目录。每门课产出一份 `<course_code>.json`(如 `cs_5800.json`)。

## 3. 字段填写规则

### 3.1 标注总原则

| 原则 | 含义 |
|---|---|
| **L1 字段宁缺不错** | 硬过滤字段 (`term`, `credits`, `prereqs`...) **绝对不能猜**。 缺失填 `None` / `[]`,不要瞎补 |
| **L2 字段需附 evidence** | `skill_tags` / `career_relevance` / `controversial_signals` / `workload_hours_per_week` / `difficulty_score` 五个字段一旦非空,**必须**配 evidence_snippet |
| **空 ≠ 不存在** | `prereqs=[]` 表示"明确没有前修课"; `prereqs=None` 不允许 (schema 不允许 None list)。 区别在于 `instructor_contact=None` 表示"这次没填"vs `InstructorContact(name="X", email=None)` 表示"填了名字但没邮箱" |
| **Pydantic 自动校验** | 你写的 JSON 进 schema 不通过就是不对。`uv run python -c "from schemas.course import Course; import json; Course.model_validate_json(open('data/ground_truth/your_file.json').read())"` 自检 |

### 3.2 字段一栏说明 (按 schema 顺序)

#### 3.2.1 Identity (身份)

| 字段 | 来源 | 怎么填 |
|---|---|---|
| `course_id` | 内部生成 | **不要手填**。统一用 `neu-<dept-lower>-<number>` 格式,如 `neu-aai-6600` / `neu-cs-5800`。如果同一课程有多版本 (CS 5800 vs DS 5000 cross-listed),挑一个作为 primary,另一个走 alias |
| `primary_code` | NEU Catalog | 规范化大写 + 单空格,如 `"CS 5800"`。Schema 自动规范化大小写但**别依赖**, 手填正确格式 |
| `primary_name` | NEU Catalog | 课程官方全称, 不要缩写 |
| `schema_version` | 系统默认 | 不填,自动是当前版本 ("1.1") |

#### 3.2.2 L1 硬字段

| 字段 | 类型 | 来源 | 缺失填什么 |
|---|---|---|---|
| `professor` | List[str] | Catalog + Syllabus | `[]` (空列表) |
| `term` | str | Syllabus 标题 | `None`。格式: `"Spring 2026"` / `"Fall 2025"` / `"Summer 2026"` |
| `credits` | int | Catalog | `None`。范围 [0, 12] |
| `prereqs` | List[str] | Syllabus "Prerequisites" 段 | `[]`。每条前修课用规范代码: `["CS 5001", "MATH 1342"]` |
| `delivery_mode` | enum | Syllabus | `None`。 取值: `in_person` / `online` / `hybrid` / `async` |

> ⚠️ Cross-listed 课:professor 是同一个人在不同 dept 教,两个 primary_code 都列上 alias_text + alias_type=`cross_listed`,但 course 记录只建一份。详见 §4.3。

#### 3.2.3 L1.5 结构化字段 (v1.1 新增)

| 字段 | 模型 | 来源 | 注意 |
|---|---|---|---|
| `instructor_contact` | InstructorContact | Syllabus 顶部 instructor 段 | `name` 必填; `email` 是 NEU 教职邮箱可填 (公开); 学生邮箱**绝对不填** |
| `textbooks` | List[Textbook] | Syllabus "Required/Optional textbook" 段 | `is_required=True` 是必修; 区分明确,有的 syllabus 把 supplemental 也叫 optional |
| `meeting_schedule` | MeetingSchedule | Syllabus "Meeting days/times" | `start_time`/`end_time` 用 24h 格式字符串 `"17:50"` (Pydantic 自动转 `time(17, 50)`) |
| `ai_policy` | AIPolicy | Syllabus "AI Use" / "Permitted AI Tools" 段 | 只标结构化部分; 复杂规则进 `notes` |

**MeetingSchedule 例子** (M+W 14:00-15:30 hybrid):
```json
{
  "slots": [
    {"day_of_week": "monday", "start_time": "14:00", "end_time": "15:30", "location": "Snell 110"},
    {"day_of_week": "wednesday", "start_time": "14:00", "end_time": "15:30", "location": "Snell 110"}
  ],
  "timezone": "America/New_York",
  "start_date": "2026-01-12",
  "end_date": "2026-04-26"
}
```

#### 3.2.4 L2 软字段

> ⚠️ **Day 6-13 阶段不要填 `workload_hours_per_week` / `difficulty_score` / `controversial_signals`**。这三个字段必须靠 RMP/Reddit 数据,Syllabus 上猜不出来。强填会污染 Ground Truth。

| 字段 | 类型 | 来源 | 怎么填 |
|---|---|---|---|
| `workload_hours_per_week` | float | RMP only | **留 None** (Day 6-13 阶段) |
| `difficulty_score` | float (1-5) | RMP only | **留 None** |
| `grading_components` | List[GradingComponent] | Syllabus | 见 §3.3 |
| `topics_covered` | List[str] | Syllabus 主题列表/CLO | 短句, 5-15 项, 用学术术语 |
| `skill_tags` | List[str] | Syllabus CLO 推断 | 用小写连字符: `"decision-trees"`, `"python"`. 见 §3.4 |
| `career_relevance` | List[str] | Syllabus PLO 推断 | 岗位短语: `"AI Engineer (entry)"`. 见 §3.4 |
| `controversial_signals` | List[str] | RMP/Reddit only | **留 []** (Day 6-13 阶段) |

#### 3.2.5 Provenance

| 字段 | 怎么填 |
|---|---|
| `evidence_snippets` | 见 §3.5,关键 |
| `extraction_confidence` | 你对自己这次标注的整体信心。范围 [0, 1]。Day 6-13 syllabus-only 标注大致 0.7-0.92 |
| `source_review_ids` | 标注用到的所有 source 标识符列表。最简形式: `["syllabus_<code>_<term>"]` |

### 3.3 grading_components 的特殊处理

**v1.1 关键变化**: `weight` 现在是 Optional,**没权重就填 None,不要瞎猜**。

#### 三种典型 syllabus 写法 → 怎么标

```
A. 明确百分比:
   "Midterm 30%, Final 40%, Homework 30%"

   → grading_components = [
     {"name": "Midterm", "weight": 0.30},
     {"name": "Final", "weight": 0.40},
     {"name": "Homework", "weight": 0.30}
   ]

B. 只列项目, 没权重 (CPS 大量 syllabus 这样):
   "Discussion Board, Assignments, Project"

   → grading_components = [
     {"name": "Discussion Board (weekly primary + 2 secondary)", "weight": null},
     {"name": "Assignments", "weight": null},
     {"name": "Project", "weight": null}
   ]

C. 部分有权重, 部分没有:
   "Midterm 25%, weekly homeworks (各占一定比例)"

   → 全部填出来, 已知权重的填数,不知的填 null
   grading_components = [
     {"name": "Midterm", "weight": 0.25},
     {"name": "Weekly Homework", "weight": null}
   ]
```

⚠️ **不要把权重相加凑 1.0 来反推**: 如果只看到 "Midterm 25%, Final 30%" 就推断"剩下 45% 是 homework",这是猜测,不能进 Ground Truth。

### 3.4 skill_tags / career_relevance 命名规范

#### skill_tags

- 全小写, 连字符分隔: `"decision-trees"` 不是 `"Decision Trees"` 或 `"DecisionTrees"`
- 5-10 个粒度, 太碎或太粗都不好
- 建议词汇库 (会随项目演进):
  ```
  python, sql, r, scala, rust
  pytorch, tensorflow, scikit-learn
  search-algorithms, decision-trees, neural-networks
  bayesian-inference, knowledge-representation, nlp
  computer-vision, reinforcement-learning, time-series
  data-engineering, feature-engineering, model-evaluation
  cloud-aws, cloud-gcp, cloud-azure
  ```

#### career_relevance

- 完整岗位短语, 加资历限定: `"AI Engineer (entry)"`, `"ML Engineer (mid)"`, `"Data Scientist (senior)"`
- 不超过 5 个,只列**这门课直接喂给的岗位**,不是"AI 行业相关"这种空泛
- 示例:
  ```
  "AI Engineer (entry)"
  "ML Engineer (entry)"
  "Data Scientist (entry/mid)"
  "Quantitative Researcher (mid)"
  "AI Research Assistant"
  "Data Engineer (mid)"
  ```

### 3.5 evidence_snippets — 软字段的强制契约

Schema 规则: **任何非空 `skill_tags` / `career_relevance` / `controversial_signals` / `workload_hours_per_week` / `difficulty_score` 必须有至少一个 `evidence_snippet` 引用它**。

#### Evidence 长什么样

```json
{
  "field": "skill_tags",
  "value": ["search-algorithms"],
  "source_id": "syllabus_aai6600_spring2026",
  "quote": "coding both blind search (breadth-first, depth-first, iterative deepening) and heuristic search (A*, best-first) algorithms",
  "confidence": 0.95
}
```

**5 个字段全部必填**:

| 字段 | 怎么填 |
|---|---|
| `field` | 字符串,必须是 schema 里软字段的字段名(精确拼写) |
| `value` | 你这条 evidence 支持的具体值。可以是字符串、数字、列表 |
| `source_id` | 来源标识符。语法: `<source_type>_<id>_<context>`。例: `syllabus_aai6600_spring2026` / `rmp_review_98765` / `reddit_t1_xyz123` |
| `quote` | 来自源的**直接引用**,不能是你的总结。1-2000 字符。**多语种 OK** |
| `confidence` | [0, 1] 浮点。0.95+ = 字面量 / 0.7-0.95 = 推理可靠 / < 0.7 = 弱推断, 应当慎用 |

#### 反例 (常见错误)

```json
// ❌ field 拼错了
{"field": "skill_tag", "value": ["python"], ...}

// ❌ quote 是你自己写的总结, 不是源里的引用
{"field": "career_relevance", "quote": "this course teaches AI fundamentals which makes it good for AI jobs", ...}

// ❌ source_id 不可识别
{"field": "skill_tags", "source_id": "the syllabus", ...}

// ❌ confidence 凭感觉填 1.0
{"field": "career_relevance", "value": ["AI Engineer (entry)"], "confidence": 1.0, ...}
//    PLO 是 aspirational,不是 placement data, 应该 0.7 左右
```

## 4. 决策树

### 4.1 字段缺失 vs 字段不确定

```
Syllabus / Catalog 里这条信息是什么状态?

明确写了, 我能直接抄?
├── YES → 填值
└── NO
    ├── 明确写了"无"/"None"/类似?
    │   ├── YES (e.g. "Prerequisites: None") → 填空 [] 或 None
    │   └── NO 完全没提
    │       ├── 这是 L1 硬字段?
    │       │   ├── YES → 填 None / [] (绝不猜)
    │       │   └── NO (是 L2)
    │       │       ├── 现在是 Day 6-13 syllabus-only 阶段?
    │       │       │   ├── YES → 留 None
    │       │       │   └── NO (有 RMP 数据) → 推断 + 加 evidence
```

### 4.2 是否需要 evidence_snippet

```
我要填的字段是 SOFT_FIELDS_REQUIRING_EVIDENCE 之一?
(workload_hours / difficulty_score / skill_tags / career_relevance / controversial_signals)

YES?
├── 填的值非空?
│   ├── YES → 必须配 ≥ 1 个 evidence_snippet 引用此字段
│   └── NO (None 或 []) → 不需要 evidence
└── NO (其他 soft field 或 hard field) → 不强制 evidence
                                          (但加上对可解释性更好)
```

### 4.3 Cross-listed / 改名课的处理

NEU 选课系统三种导致数据割裂:
1. Cross-listed: `CS 5800 ≈ DS 5000`(同一节课两个号)
2. Version: `AAI 5000 → AAI 6600`(同一课程改革后换号)
3. Renaming: 课名改了号没改

**全部走 alias 表,不要建多份 course 记录**。

```
Step 1: 选一个 primary_code (一般选 catalog 当前最常用的那个)
Step 2: course 文件里只填 primary_code (例: "CS 5800")
Step 3: 在 data/aliases_manual.json 里加映射:
        "neu-cs-5800": [
          {"alias_text": "DS 5000", "alias_type": "cross_listed"},
          ...
        ]
```

## 5. 高频争议 + FAQ

### Q1. 教授 email 该不该写进 instructor_contact?

**写**, 如果是 NEU 教职邮箱 (`@northeastern.edu`)。
理由: 这些邮箱在 NEU 公开目录、syllabus 全班发放,属于 already-public。
**不写**学生邮箱、TA 邮箱、个人邮箱。

### Q2. AI policy 在 syllabus 里写了一大段, 怎么进 ai_policy?

只把**结构化的部分**进结构化字段, 复杂规则进 `notes`:

```json
{
  "permitted_tools": ["Microsoft Copilot", "Claude (claude.northeastern.edu)"],
  "banned_tools": [],
  "disclosure_required": true,
  "notes": "Penalties: 1st offense undisclosed = 50% reduction; 2nd = OSCCR..."
}
```

不要把 AI 政策再塞进 `controversial_signals`。两份。

### Q3. Course description 提到"Recommended background: linear algebra", 算 prereqs 吗?

**不算**。
`prereqs` 只填**强制前修课**(catalog 标 prerequisite 的)。Recommended/suggested 不算。
强制 prereq 通常 catalog 单独有"Prerequisites"段;recommended 在 description 行文里。

### Q4. 这门课 syllabus 没说 timezone 但显然是 EST, 要写吗?

不写。`MeetingSchedule.timezone` 默认 `"America/New_York"`,NEU Boston 校区都对。
如果是其他校区(SF/Toronto/London CPS),才需要显式覆盖。

### Q5. 标了 12 个 topics_covered,标注员 B 标了 5 个, Kappa 怎么算?

`topics_covered` 在 Day 9 Kappa 评估里走**集合相似度**(IoU),不是精确匹配。
但如果你们差距大到 IoU < 0.5,就是 schema 给了太多自由度,Day 9 会议讨论是否限定一个词汇库。

### Q6. extraction_confidence 该填多少?

按这张表:

| 数据完整度 | 置信度 |
|---|---|
| Syllabus + RMP + Reddit 都有 | 0.92-0.98 |
| Syllabus + RMP, 无 Reddit | 0.85-0.92 |
| 只有 Syllabus | **0.7-0.85** ← Day 6-13 阶段 |
| Syllabus 残缺 (扫描件 / 图片) | 0.5-0.7 |
| 无 Syllabus, 仅 catalog | < 0.5 |

### Q7. 我和搭档对某个字段争议, 怎么办?

1. **不要**当场协商对齐 —— 那破坏双盲性
2. 各自独立提交, Day 9 Kappa 分析自动标出争议字段
3. Day 9 会议上讨论争议背后的判断标准,**修订本指南**(让指南承担争议解决,不让某次标注承担)

## 6. 提交流程

### 6.1 文件位置

```
data/ground_truth/
├── aai_6600.json          # 已有, 参考
├── cs_5800.json           # ← 你的产出
├── cs_5800.annotator_<你的名字>.json    # 双盲阶段,加注解者后缀
└── ...
```

### 6.2 自检清单 (commit 前)

```bash
# 1. JSON 合法
python -c "import json; json.load(open('data/ground_truth/cs_5800.annotator_alice.json'))"

# 2. Pydantic schema 通过
python -c "
from schemas.course import Course
import json
data = json.load(open('data/ground_truth/cs_5800.annotator_alice.json'))
Course.model_validate(data)
print('OK')
"

# 3. 没把 .env / 个人数据带进去
git diff --cached | grep -i 'api_key\|@husky.neu.edu\|@northeastern.edu' && echo 'WARN'
```

### 6.3 PR 规范

- 一次 PR 只 1 门课, 标题: `data: AAI 6600 ground truth (annotator: alice)`
- PR body 注明: 用了几小时、花在哪些字段上、有没有觉得指南需要改的地方
- 双盲阶段:**不要**review 搭档的 PR(那破坏双盲性)。Kappa 分析后再合并
- Kappa 后, 双方协商版本 merge 进 `cs_5800.json`(不带后缀的最终版),annotator 各自的 JSON 保留作为审计记录

## 7. 快速参考表

| 我现在要... | 答案 |
|---|---|
| 标 syllabus-only 阶段, 该填 difficulty_score 吗? | 不,留 None |
| 教授邮箱要不要填? | NEU 教职邮箱填,其他不填 |
| grading 没权重怎么办? | weight=null, 别凑 |
| Cross-listed 怎么处理? | 选 primary, 另一个进 aliases |
| topics_covered 应当多细? | 短句, 5-15 项 |
| skill_tags 命名? | 小写连字符 `decision-trees` |
| confidence 凭感觉? | 不,看 Q6 表,字面引用 0.95+ / 推理 0.7-0.9 / 弱推断 < 0.7 |
| field 缺失 vs 不确定? | L1 缺失 → None/[];L2 缺失 → None |
| evidence quote 是总结? | 不,必须直接引用源 |
| 我和搭档不一样? | 各自独立提交, Day 9 解决 |

## 8. 反馈

发现指南没覆盖的边界情况, 在 Standup 提出。
本文档随 Day 9 Kappa 会议每周修订一版。
