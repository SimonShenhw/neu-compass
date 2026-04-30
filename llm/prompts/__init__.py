"""Versioned prompt templates.

Each prompt is a self-contained module with:
  - PROMPT_VERSION (semver-ish string)
  - PROMPT_TEMPLATE (string with {placeholders})
  - build_prompt(...) function

When tweaking, copy current to next version (extract_v1 -> extract_v2),
keep both around, A/B compare via eval/compare_prompts.py.
"""
