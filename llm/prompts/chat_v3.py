"""Chat-style prompt v3.0 — conversational, content-grounded course advisor.

Differences from v2.0 (see chat_v2.py):

与 v2.0 的区别(参见 chat_v2.py):

1. **Conversation history block**: the client now sends prior turns;
   the model resolves references ("这门课", "it") against history — but
   FACTS still come only from the retrieved list. v2's stateless prompt
   is why follow-ups derailed.

1. **对话历史区块**:客户端现在会发送之前的对话轮次;模型据此解析
   指代("这门课"、"it")—— 但事实性内容依然只能来自检索列表。v2 的
   无状态 prompt 正是追问会脱轨的原因。

2. **Course CONTENT in the candidates block**: v2 fed only code/name/
   term/credits, so "what does this course cover?" had no raw material —
   the model padded with plausible-sounding filler. v3 includes
   topics_covered / skill_tags / workload / difficulty when present.

2. **候选课程区块里的课程内容**:v2 只喂了 code/name/term/credits,
   所以 "what does this course cover?" 这类问题没有原始素材可用 ——
   模型只能用听起来靠谱的填充内容硬凑。v3 在有数据时会包含
   topics_covered / skill_tags / workload / difficulty。

3. **No code-number inference**: live answers said "6xxx 级别通常属于
   中级水平" — invented from the course NUMBER, not the catalog. v3
   forbids deriving difficulty/level/content from the code; missing data
   is stated as missing. (The v2 foundational-level heuristic survives
   ONLY for choosing among retrieved candidates in first-semester
   questions — never as a fact about a course.)

3. **不做代码数字推断**:线上曾出现 "6xxx 级别通常属于中级水平" 这种
   回答 —— 是从课程编号臆造出来的,不是来自目录。v3 禁止从课程代码
   推导难度/等级/内容;缺失的数据就如实说缺失。(v2 的"基础级别"
   启发式仅在首学期问题里用于从检索候选中做选择时保留 —— 绝不作为
   某门课的事实来陈述。)

4. **Did-you-mean behavior**: when candidates only weakly match, name
   the 2-3 most plausible by code and ask which one — never a bare
   "couldn't find it" while ten candidates sit in the evidence panel.

4. **"你是不是想问"的行为**:当候选只是弱匹配时,按代码点名 2-3 个
   最可能的选项并反问 —— 绝不能在证据面板里明明摆着十个候选时,还
   干巴巴回答"没找到"。

Bumping 2.0 → 3.0: contract change (history param), so fixtures + any
Ragas baselines re-anchor here. chat_v2 stays importable for rollback.

把版本从 2.0 提到 3.0:这是一次契约变更(history 参数),所以 fixtures
和任何 Ragas 基线都要以此为新锚点重新对齐。chat_v2 仍然可以被 import,
用于回滚。
"""

from __future__ import annotations

from typing import Mapping, Sequence

from rag.retriever import SearchHit

PROMPT_VERSION = "3.0"

# The v3.0 prompt template (differences from v2.0 detailed in the module
# docstring above). Test-asserted verbatim by fixtures/Ragas baselines —
# do not reflow or reword; any change is a version bump (chat_v4.py).
# 中文:v3.0 的 prompt 模板(与 v2.0 的区别见上方模块 docstring)。
# fixtures/Ragas 基线会逐字断言这段文本 —— 不要重新排版或改写措辞;
# 任何改动都应该是一次版本升级(建一个新的 chat_v4.py)。
PROMPT_TEMPLATE = """You are a helpful course advisor at Northeastern University in an ongoing conversation with a student.

# Conversation so far
{history}

# Student's new message
{query}

# Top relevant courses (retrieved by alias + semantic search)
{courses}

# Instructions

## Grounding (hard rules — do not violate)
- Only cite courses that appear verbatim in the retrieved list above.
- Do NOT invent courses, even if you think they exist at NEU.
- Facts about a course (content, workload, difficulty, prerequisites) may
  come ONLY from the retrieved list. NEVER infer difficulty, level, or
  content from the course NUMBER (e.g. do not say "6xxx courses are
  usually intermediate") — that is invented, not catalog data.
- If the student asks about an aspect the retrieved data doesn't cover
  (e.g. workload is absent), say plainly that the catalog entry doesn't
  include it — do not fill the gap with guesses.

## Conversation continuity
- Use the conversation history to resolve references: "这门课" / "it" /
  "that one" refer to the course(s) discussed in the previous turns.
- When the retrieved list contains exactly the course(s) under
  discussion, answer the follow-up directly — do not re-introduce the
  course from scratch.

## When the match is uncertain (did-you-mean)
- If no retrieved course clearly answers the question but some are
  plausible, name the 2-3 most plausible by code and ask the student
  which one they mean. Never answer a bare "I couldn't find it" when
  plausible candidates exist in the list.
- If the retrieved list is empty or nothing is even plausible, say so
  directly and ask one clarifying question.

## Program-prefix discipline
- If the student names a program / major prefix (e.g. "AAI 专业",
  "CS major"), ONLY recommend courses whose primary_code starts with
  that prefix; if none are in the list, say so. Cross-discipline
  recommendations are FORBIDDEN unless explicitly requested.
- For "first-semester / foundational / 基础 / 入门" questions, prefer the
  5xxx-tier candidates among the retrieved courses.

## Style
- Plain Markdown. Cite courses by code, e.g. "AAI 5015".
- Concise — 1 to 3 short paragraphs.
- Match the language of the student's message (Chinese → Chinese,
  English → English, mixed is fine).

Answer:
"""


def format_history_block(history: Sequence[Mapping[str, str]] | None) -> str:
    """Render prior turns as a compact transcript. Each item carries
    'role' ('user'/'assistant') and 'content'. Empty/None → a marker the
    model reads as a fresh conversation.

    中文:把之前的对话轮次渲染成一份紧凑的文字记录。每一项都带有 'role'
    ('user'/'assistant') 和 'content'。空/None → 一个标记,模型会把它
    读作"这是一次全新的对话"。
    """
    if not history:
        return "(this is the first message)"
    lines: list[str] = []
    for turn in history:
        speaker = "Student" if turn.get("role") == "user" else "Advisor"
        content = str(turn.get("content", "")).strip()
        if content:
            lines.append(f"{speaker}: {content}")
    return "\n".join(lines) if lines else "(this is the first message)"


def format_courses_block(hits: list[SearchHit]) -> str:
    """Bullet list of retrieved courses INCLUDING content fields — the
    raw material for "what does it cover"-type questions that v2 lacked.

    中文:检索到的课程列表(项目符号形式),包含内容字段 —— 这正是
    v2 缺少的、能回答 "what does it cover" 这类问题的原始素材。
    """
    if not hits:
        return "(no matches found in catalog)"
    lines: list[str] = []
    for hit in hits:
        c = hit.course
        bits = [f"{c.primary_code} — {c.primary_name}"]
        if c.term:
            bits.append(c.term)
        if c.credits is not None:
            bits.append(f"{c.credits} credits")
        if c.delivery_mode:
            bits.append(c.delivery_mode.value.replace("_", " "))
        lines.append("- " + " · ".join(bits))
        if c.topics_covered:
            # Cap list lengths so one course with 30 topics doesn't blow the
            # prompt's token budget; a handful is enough context for the LLM.
            # 中文:限制列表长度,避免某门课的 30 个主题把 prompt 的 token
            # 预算撑爆;给 LLM 几个足够形成上下文就够了。
            lines.append(f"  topics: {'; '.join(c.topics_covered[:8])}")
        if c.skill_tags:
            lines.append(f"  skills: {'; '.join(c.skill_tags[:6])}")
        extras: list[str] = []
        if c.workload_hours_per_week is not None:
            extras.append(f"workload ~{c.workload_hours_per_week:g} h/week")
        if c.difficulty_score is not None:
            extras.append(f"difficulty {c.difficulty_score:g}/5")
        if c.prereqs:
            extras.append(f"prereqs: {', '.join(c.prereqs[:4])}")
        if extras:
            lines.append(f"  {' · '.join(extras)}")
    return "\n".join(lines)


def build_prompt(
    query: str,
    hits: list[SearchHit],
    history: Sequence[Mapping[str, str]] | None = None,
) -> str:
    return PROMPT_TEMPLATE.format(
        query=query,
        courses=format_courses_block(hits),
        history=format_history_block(history),
    )


__all__ = [
    "PROMPT_VERSION",
    "PROMPT_TEMPLATE",
    "build_prompt",
    "format_courses_block",
    "format_history_block",
]
