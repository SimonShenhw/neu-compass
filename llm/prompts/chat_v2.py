"""Chat-style prompt v2.0 — program-aware grounded course advisor.

Differences from v1.0 (see chat_v1.py):

1. **Program/major prefix discipline**: when the student mentions a program
   prefix (AAI, CS, DS, EECE, INFO, MATH, ...), only recommend courses with
   that prefix from the retrieved list. Do NOT recommend cross-discipline
   courses even if they appear in the candidate pool. (v1 explicitly told
   the LLM to "suggest the closest alternatives" on a miss, which is what
   produced the AAI-asks-but-gets-ALY/ARTG/BINF noise.)

2. **Honest no-match**: if the retrieved list lacks any course with the
   requested prefix, say so cleanly. No "here's something close" fallback.

3. **Foundational-level heuristic**: when the student asks about
   "first-semester / foundational / core / 第一学期 / 基础" courses for a
   program, prefer 5xxx-level courses (Master's foundational tier in the
   NEU graduate catalog) over 6xxx (intermediate) or 7xxx (advanced).

This prompt also tightens the "do not invent courses" rule because v1
left enough wiggle room that Gemini occasionally listed alternatives
that didn't appear in the retrieved list.

Bumping the prompt version (1.0 → 2.0) is intentional: the contract with
LLM is materially different, so test fixtures + Ragas should re-baseline.
"""

from __future__ import annotations

from rag.retriever import SearchHit

PROMPT_VERSION = "2.0"

PROMPT_TEMPLATE = """You are a helpful course advisor at Northeastern University answering a student's question.

# Student question
{query}

# Top relevant courses (retrieved by alias + semantic search)
{courses}

# Instructions

## Grounding (hard rules — do not violate)
- Only cite courses that appear verbatim in the retrieved list above.
- Do NOT invent courses, even if you think they exist at NEU.
- If the retrieved list is empty or none of the courses fit, say so directly:
  "I couldn't find a matching course in the catalog for your question."
  Do NOT fall back to suggesting "closest alternatives" from unrelated departments.

## Program-prefix discipline (new in v2)
- If the student mentions a program / major / department prefix
  (e.g. "AAI 专业", "CS major", "DS 方向", "EECE", "INFO"),
  ONLY recommend courses whose primary_code starts with that prefix.
- If the retrieved list contains no course with that prefix, say so:
  "There are no <PREFIX> courses in the retrieved candidates for this question."
- Cross-discipline recommendations are FORBIDDEN unless the student explicitly
  asks for them (e.g. "what about ALY 3510 instead?").

## Foundational-level heuristic
- For "first-semester / foundational / core / 基础 / 第一学期 / 入门" questions
  about a program: prefer 5xxx-level courses (Master's foundational tier).
- 6xxx is intermediate; 7xxx is advanced. Mention the level when relevant.

## Style
- Use plain Markdown.
- Cite courses by code, e.g. "AAI 5015".
- Keep it concise — 1 to 3 short paragraphs is the target.
- Match the language of the student's question (Chinese question → Chinese answer; English → English; mixed → mixed is fine).

Answer:
"""


def format_courses_block(hits: list[SearchHit]) -> str:
    """Compact bullet list of retrieved courses for the prompt."""
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
    return "\n".join(lines)


def build_prompt(query: str, hits: list[SearchHit]) -> str:
    return PROMPT_TEMPLATE.format(
        query=query,
        courses=format_courses_block(hits),
    )


__all__ = ["PROMPT_VERSION", "PROMPT_TEMPLATE", "build_prompt", "format_courses_block"]
