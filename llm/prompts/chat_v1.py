"""Chat-style prompt v1.0 — grounded course advisor.

Different from extract_v1 (structured Course extraction). Chat answers a
student's free-form question, citing courses retrieved by the alias +
hybrid pipeline. Hard rule: do NOT invent courses that aren't in the
retrieved list.

When this prompt produces wrong output:
  1. Don't tweak this file — copy to chat_v2.py and tweak there.
  2. Run an A/B with the eval harness (or judge via Gemini-as-judge).
  3. Bump the API's chat builder to v2 only after qualitative wins.
"""

from __future__ import annotations

from rag.retriever import SearchHit

PROMPT_VERSION = "1.0"

PROMPT_TEMPLATE = """You are a helpful course advisor at Northeastern University answering a student's question.

# Student question
{query}

# Top relevant courses (retrieved by alias + semantic search)
{courses}

# Instructions
- Answer the student's question grounded in the listed courses.
- Cite specific courses by code (e.g. "CS 5800") when relevant.
- If none of the listed courses match, say so clearly and suggest the closest alternatives.
- Use plain Markdown. Be concise — 1 to 3 short paragraphs is the target.
- Do NOT make up courses that aren't in the list.

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
