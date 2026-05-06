"""Prompt v1.1 for Course extraction.

Append-only revision over extract_v1 (v1.0). Fixes a Week 7 §3.2 finding:
the CS 5200 enrichment failed Pydantic validation because Gemini emitted
non-empty `skill_tags` without matching `evidence_snippets`. v1.0 had the
constraint in prose, but the LLM still drifted; v1.1 adds an upfront
CRITICAL block + Bad/Good few-shot examples + an explicit "leave empty
rather than invent" fallback rule.

The v1.0 file (extract_v1.py) is preserved unchanged so eval/compare_prompts.py
can A/B both. PLAN v2.3 §3.3 — must pass before scaling Gemini enrichment
to remaining 16 courses (PLAN §3.4).
"""

from __future__ import annotations

PROMPT_VERSION = "1.1"

PROMPT_TEMPLATE = """You are extracting structured information about a graduate-level course at Northeastern University.

You will be given source documents wrapped in <source> tags. Extract a single JSON object matching the Course schema.

# CRITICAL — soft fields require evidence_snippets

For EVERY non-empty value in any of these soft fields:
  - difficulty_score
  - workload_hours_per_week
  - skill_tags
  - career_relevance
  - controversial_signals

You MUST include AT LEAST ONE entry in `evidence_snippets` where:
  1. `field` matches the soft-field name verbatim (e.g. "skill_tags", not "skills")
  2. `quote` is a verbatim substring (≥ 10 chars) of one of the supplied <source> blocks
  3. `source_id` matches the `id` attribute of that source

If you cannot find supporting evidence in the sources, leave the soft field empty:
  null   for scalars (difficulty_score, workload_hours_per_week)
  []     for lists  (skill_tags, career_relevance, controversial_signals)

Do NOT invent. The Pydantic validator will reject any non-empty soft field without
matching evidence_snippet, and the entire extraction is discarded — wasting one
Gemini call.

## Examples

Bad — soft field set, evidence empty (REJECTED):
  {{"skill_tags": ["python", "ml"], "evidence_snippets": []}}

Bad — field name mismatch (REJECTED, validator looks for exact "skill_tags"):
  {{"skill_tags": ["python"], "evidence_snippets": [
    {{"field": "skills", "quote": "uses python heavily",
      "source_id": "rmp_review_42", "value": ["python"], "confidence": 0.85}}
  ]}}

Good — every non-empty soft field has at least one matching evidence entry:
  {{"skill_tags": ["python"], "evidence_snippets": [
    {{"field": "skill_tags",
      "value": ["python"],
      "source_id": "rmp_review_42",
      "quote": "Heavy use of Python for assignments",
      "confidence": 0.85}}
  ]}}

Good — no review evidence available, fields left empty (still valid):
  {{"skill_tags": [], "difficulty_score": null, "evidence_snippets": []}}

# Hard rules

1. **Hard fields** (course_code, primary_name, term, credits, prereqs, professor, delivery_mode, instructor_contact, textbooks, meeting_schedule, ai_policy):
   - Use ONLY official syllabus / catalog content.
   - If a hard field is not in any source, output null (never guess).

2. **Soft fields**: see CRITICAL section above. Synthesize from RMP / Reddit content,
   but always pair with evidence — if no quote supports it, leave the field empty.

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
