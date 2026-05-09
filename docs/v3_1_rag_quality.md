# v3.1 RAG Quality — 3-layer chat-path overhaul

> **Range**: PLAN v3.0+ follow-up (post Week 9 perf). 修了 chat 路径在 abstract NL query 上的几类 systemic miss(典型: 用户问 "我是 AAI 专业,第一学期推荐什么?",chat_v1 路径返回 ALY/ARTG/BINF 跨学科 noise)。
> **Updated**: 2026-05-09
> **Status**: shipped(739 tests / 14s WSL2)

---

## 1. TL;DR

| 失败 case (chat_v1) | 根因 | 修法 (chat_v2.x) |
|---|---|---|
| "AAI 专业第一学期" → ALY/ARTG/BINF 替代品 | retriever 没有 program 概念,LLM prompt 又指示"找最近替代" | **Layer 1**:chat_v2 prompt 加 prefix discipline + 5xxx-foundational 规则;chat 路径加 reranker reject |
| "我是 AAI 专业,关于 X 有哪些课?" → 混跨学科 | prefix 信号没传给 retriever | **Layer 2**:LLM-free regex extractor 抽 prefix → SQLite WHERE `primary_code LIKE 'AAI %'` |
| "AAI 专业第一学期" 检索质量靠运气 | hybrid 不知道 "first semester" 该返回 5xxx 还是 6xxx | **Layer 3**:`programs` + `program_required_courses` 表(AAI MS PoC seeded with 23 课 + 4-4-7-8 学期分布) |
| "那 AAI 6640 这门课能说说吗?" → 没找到 AAI 6640 | `\b` Unicode-aware,中文邻字让 'AAI' 没 boundary | re.ASCII flag(同 patch 里) |
| "强化学习" cross-lingual reranker reject | 0.044 < 0.05 阈值 | 当 Layer 2 prefix filter 已 narrow,`reject_threshold=0.0`(prefix 已做高精度过滤) |

实测端到端(public):

| Query | matched_via | retrieval_ms | 验证 |
|---|---|---|---|
| "那基于我是aai专业,能给我推荐第一个学期的选课嘛?" | **program** | **3.8 ms** | Layer 3 graph,返回 AAI 5015/5025/5035/6600 |
| "那AAI 6640这门课能给我说说吗?" | alias | 1.1 ms | Layer 1 regex+alias |
| "我是AAI专业,关于强化学习有哪些课?" | hybrid | 24.6 ms | Layer 2 prefix filter,reject scoping 解封 |
| "ancient roman emperors and empires" | rejected | 27 ms | adversarial 仍正确 reject |

---

## 2. 架构改动

```
user query
   │
   ▼
┌─────────────────────────────────────────────┐
│ Tier 1: alias (regex + v_course_lookup)     │ ← chat path
│   Layer 1.regex: re.ASCII fix for CJK NL    │
└─────────────────────────────────────────────┘
   │ miss
   ▼
┌─────────────────────────────────────────────┐
│ Tier 2: program ontology (Layer 3)          │
│   IF query has program prefix               │
│   AND query has "first-semester" intent     │
│   AND program is seeded in `programs` table │
│   THEN return semester=1 courses            │
└─────────────────────────────────────────────┘
   │ miss
   ▼
┌─────────────────────────────────────────────┐
│ Tier 3: hybrid + reranker                   │
│   Layer 2.regex extract prefix → SQL WHERE  │
│     primary_code LIKE 'AAI %'               │
│   IF prefix applied: reject_threshold = 0.0 │
│   ELSE: reject_threshold = 0.05 (ADR-0016)  │
└─────────────────────────────────────────────┘
   │
   ▼
chat_v2 prompt (program-prefix discipline)
   │
   ▼
Gemini stream
```

### Layer 1: prompt 工程([llm/prompts/chat_v2.py](../llm/prompts/chat_v2.py))

新增 3 条硬规则:

1. **Program-prefix discipline**:user 提到 "AAI 专业 / CS major / DS 方向" → 只能推荐 prefix 命中的课。Cross-discipline 推荐**禁用**。
2. **Honest no-match**:retrieved list 里没 prefix 命中 → 直接说"No <PREFIX> courses",不再 fallback "closest alternatives"(v1 行为)。
3. **Foundational-level heuristic**:"first-semester / 第一学期 / foundational / 基础" → 优先 5xxx-level(NEU 研究生 foundational tier)。

同时 chat 路径开了 reranker reject(以前只有 `/search` 有,见 [api/routes/chat.py](../api/routes/chat.py))。

### Layer 2: 结构化 pre-filter([llm/query_filter_extractor.py](../llm/query_filter_extractor.py))

模仿 [Cole Hoffer "Structured Pre-Filtering"](https://www.colehoffer.ai/articles/advanced-rag-structured-pre-filtering) + [Haystack `QueryMetadataExtractor`](https://haystack.deepset.ai/blog/extracting-metadata-filter):

- **Adaptive gate**:正则先扫(`AAI / CS / DS / EECE / INFO / ALY / BINF / MATH / MGSC / STAT / IE / CSYE`),命中即用,不调 LLM。
- **LLM hook**:正则 miss 但有 program-keyword(`专业 / major / program / 主修 / track / concentration`)时,可以 inject `llm_fn` 做 "AI 专业" → AAI 之类的映射。当前 production 传 `llm_fn=None`(纯 regex),等真 query log 累积后看是否值得加 LLM 一跳。
- **Sanitized query**:抽掉的 prefix 词从 query 里剥掉,embedder 看的是纯语义意图(防止 "AAI" token 主导 vector 表示)。
- **Hard filter**:`{primary_code_prefix: 'AAI'}` 喂给 [rag/retriever.py](../rag/retriever.py) `_sqlite_filter`,新增 `WHERE primary_code LIKE 'AAI %'`。

### Layer 3: program 本体论([db/init.sql](../db/init.sql) v1.2 + 新表)

模仿教育领域 Knowledge Graph 论文的 ontology(参考 [emergentmind 综述](https://www.emergentmind.com/topics/knowledge-graph-based-curriculum-construction)):

```sql
CREATE TABLE programs (
    program_id   TEXT PRIMARY KEY,                 -- 'aai-ms'
    full_name    TEXT NOT NULL,                    -- 'MPS Applied AI'
    prefix       TEXT NOT NULL COLLATE NOCASE,     -- 'AAI'
    department   TEXT,
    college      TEXT
);

CREATE TABLE program_required_courses (
    program_id           TEXT, course_id TEXT,
    requirement_type     TEXT CHECK (... 'core'|'foundation'|'elective_pool'|'capstone'),
    semester_recommended INTEGER CHECK (1..8),
    PRIMARY KEY (program_id, course_id),
    FOREIGN KEY ...
);

CREATE TABLE course_prerequisites (
    course_id TEXT, prereq_course_id TEXT,
    requirement TEXT DEFAULT 'required'
                CHECK ('required'|'recommended'|'concurrent'),
    PRIMARY KEY (course_id, prereq_course_id),
    CHECK (course_id <> prereq_course_id)
);
```

⚠️ **不上 Neo4j / Neptune**:6469 nodes + < 30k edges 的 scale 下,SQLite 多 join 的延迟跟 Neo4j 差距可以忽略,且 ADR-0013 "SQLite as source of truth" 不破坏。GoodData / deepsense.ai 倡导专门 graph DB 的 GraphRAG 在我们这个 scale 是 over-engineering。

**AAI MS PoC 数据** ([data/program_seed/aai_ms.json](../data/program_seed/aai_ms.json)):

```
programs:                1 row  (aai-ms)
program_required_courses 23 rows (semester 1: 4 / 2: 4 / 3: 7 / 4: 8)
course_prerequisites     10 rows
```

数据是从 AAI 课程编号约定**最佳猜测**(5xxx foundational / 6600 gateway / 6610-6690 specialized core / 6710+ advanced / 6980 capstone),**user 应该对照 NEU 官方 Plan of Study 验证后再推广到其他 program**。

---

## 3. 修复的非 RAG bug

`/loop` 同 sprint 顺手清掉:

| Bug | 文件 | 修法 |
|---|---|---|
| `query_normalizer` `\b` 在 CJK NL 失效("那aai 6640" 不命中) | [rag/query_normalizer.py](../rag/query_normalizer.py:21) | `re.ASCII` flag |
| Streamlit Clear-all button 抛 `StreamlitAPIException` | [app/streamlit_app.py:171](../app/streamlit_app.py:171) | `on_click=callback`,callback 在 widget instantiate 之前 mutate |
| `DuplicateWidgetID` 当同 course 出现在多 message evidence | [app/streamlit_app.py:265](../app/streamlit_app.py:265) | key 加 `msg_idx` enumerate |
| Co-op industry dropdown 显示字面 "None" | [app/coop_view.py:113](../app/coop_view.py:113) | `format_func=lambda x: "(unspecified)" if x is None else ...` |
| broken markdown link in `PLAN_v2_3_1.md` | [docs/PLAN_v2_3_1.md:4](PLAN_v2_3_1.md) | `(PLAN_v2_3.md)` → `(PLAN_v2.3.md)` |

---

## 4. v3.2+ followups(不阻塞)

- **Cross-lingual 弱**:"强化学习" 在 prefix-filtered AAI 子集里没把 AAI 6740 "Applied Reinforcement Learning" 推到 top — bge-m3 + bge-reranker-v2-m3 在中→英 gap 上不强。两条修法:
  1. 加 alias `("强化学习", neu-aai-6740, slang)` — 2 行 SQL,直接 alias 命中
  2. 写中文 ML 术语扩展 dict(强化学习 → reinforcement learning,自然语言处理 → natural language processing,...)在 retrieval 之前加到 query
- **Layer 2 LLM hook 接通**:当真 query log 显示有人写 "AI 专业" 之类的 free-form,启用 `llm_fn=Gemini-structured-output` 兜底。+200-500ms 但 cover 长尾。
- **Layer 3 数据 scope**:当前只有 AAI MS。下一批补 CS Align / CS MS / DS MS / EECE,需要爬各自 plan-of-study webpage 或人工 review。
- **Reranker reject 在 prefix scope 的更精细策略**:目前是 binary(prefix 命中 → reject 关闭)。未来可以 per-prefix 校准(AAI 子集 sigmoid 阈值 0.02,通用 0.05)。

---

## 5. 修订

- 2026-05-09: 初版,3-layer + bugfix shipped 实测后。
