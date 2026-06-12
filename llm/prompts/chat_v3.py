"""Chat-style prompt v3.0 — conversational, content-grounded course advisor.

Differences from v2.0 (see chat_v2.py):

1. **Conversation history block**: the client now sends prior turns;
   the model resolves references ("这门课", "it") against history — but
   FACTS still come only from the retrieved list. v2's stateless prompt
   is why follow-ups derailed.

2. **Course CONTENT in the candidates block**: v2 fed only code/name/
   term/credits, so "what does this course cover?" had no raw material —
   the model padded with plausible-sounding filler. v3 includes
   topics_covered / skill_tags / workload / difficulty when present.

3. **No code-number inference**: live answers said "6xxx 级别通常属于
   中级水平" — invented from the course NUMBER, not the catalog. v3
   forbids deriving difficulty/level/content from the code; missing data
   is stated as missing. (The v2 foundational-level heuristic survives
   ONLY for choosing among retrieved candidates in first-semester
   questions — never as a fact about a course.)

4. **Did-you-mean behavior**: when candidates only weakly match, name
   the 2-3 most plausible by code and ask which one — never a bare
   "couldn't find it" while ten candidates sit in the evidence panel.

Bumping 2.0 → 3.0: contract change (history param), so fixtures + any
Ragas baselines re-anchor here. chat_v2 stays importable for rollback.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from rag.retriever import SearchHit

PROMPT_VERSION = "3.0"

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
    model reads as a fresh conversation."""
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
    raw material for "what does it cover"-type questions that v2 lacked."""
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
