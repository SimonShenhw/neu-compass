"""LLM extraction pipeline.

Top-level: gemini_client (model wrapper) + formatter (source-doc XML packager) +
alias_detector (LLM-inferred aliases -> pending queue).

Prompts live in llm/prompts/ as versioned modules (extract_v1, extract_v2, ...).
"""

from llm.formatter import SourceDocument, format_sources
from llm.gemini_client import DEFAULT_MODEL, GeminiError, generate_structured, generate_text

__all__ = [
    "DEFAULT_MODEL",
    "GeminiError",
    "SourceDocument",
    "format_sources",
    "generate_structured",
    "generate_text",
]
