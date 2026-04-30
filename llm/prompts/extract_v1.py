"""Prompt v1.0 for Course extraction.

Input:  <source>-tagged documents (syllabus + reviews + posts)
Output: JSON validating against schemas.course.Course (v1.1)

Conventions enforced by prompt:
  - Hard fields ONLY from authoritative sources (catalog/syllabus); else null.
  - Soft fields require evidence_snippets with verbatim quotes + matching source_id.
  - extraction_confidence rubric tied to source completeness (0.7-0.85 syllabus only).
  - course_code format: 'AAI 6600' canonical.

When this prompt produces wrong output:
  1. Don't tweak this file — copy to extract_v2.py and tweak there.
  2. Run eval/compare_prompts.py to A/B both on the eval set.
  3. Update llm.gemini_client default to v2 only after Recall@5 + Faithfulness wins.
"""

from __future__ import annotations

PROMPT_VERSION = "1.0"

PROMPT_TEMPLATE = """You are extracting structured information about a graduate-level course at Northeastern University.

You will be given source documents wrapped in <source> tags. Extract a single JSON object matching the Course schema.

# Hard rules

1. **Hard fields** (course_code, primary_name, term, credits, prereqs, professor, delivery_mode, instructor_contact, textbooks, meeting_schedule, ai_policy):
   - Use ONLY official syllabus / catalog content.
   - If a hard field is not in any source, output null (never guess).

2. **Soft fields** (workload_hours_per_week, difficulty_score, skill_tags, career_relevance, controversial_signals):
   - Synthesize from RMP / Reddit content.
   - EVERY non-empty soft value MUST have ≥1 corresponding evidence_snippet.
   - evidence_snippet.quote MUST be a verbatim excerpt from a source (you can shorten via "..." but cannot paraphrase).
   - evidence_snippet.source_id MUST match an `id` attribute on one of the input <source> tags.

3. **Confidence calibration** (extraction_confidence):
   - 0.95+ : all fields syllabus-direct or strongly corroborated across ≥2 sources
   - 0.85-0.95 : syllabus + ≥1 review source, no contradictions
   - 0.70-0.85 : syllabus only, soft fields synthesized from limited reviews
   - <0.70 : syllabus incomplete, sources disagree, or speculation required

4. **Format**:
   - course_code: 'CC NNNN' or 'CC NNNNX' (e.g. 'CS 5800', 'AAI 6600', 'DS 5230A')
   - skill_tags: lowercase-hyphenated ('decision-trees', not 'Decision Trees')
   - topics_covered: 5-15 short academic phrases
   - career_relevance: max 5 entries, each a job-title phrase with seniority

5. **Schema strictness**:
   - Output JSON ONLY (no markdown fences, no commentary).
   - Set schema_version to "1.1".
   - Set workload_hours_per_week and difficulty_score to null if no review data.
   - Set controversial_signals to [] if no concerns surfaced (not a forced field).

# Sources

{sources}

# Output

Output the Course JSON now."""


def build_prompt(sources_xml: str) -> str:
    """Substitute the formatted source documents into the template.

    Caller is responsible for building `sources_xml` via llm.formatter.format_sources.
    """
    return PROMPT_TEMPLATE.format(sources=sources_xml)


__all__ = ["PROMPT_VERSION", "PROMPT_TEMPLATE", "build_prompt"]
