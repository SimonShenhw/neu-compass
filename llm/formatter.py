"""Source-document XML packager for LLM prompts.

Wraps each source (syllabus / RMP review / Reddit post / catalog excerpt)
in `<source id=... type=...>` tags so the prompt can refer to them by id
and the LLM can produce evidence_snippet.source_id values that match.

Prompt-injection defense: closing `</source>` tags inside content are
escaped (replaced with `<\\/source>`). This is a basic mitigation —
adversarial inputs may still trip up the LLM, but the simple "user
content breaks out of tag" path is closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Match closing source tag inside content (case-insensitive, optional whitespace)
_CLOSE_TAG_RE = re.compile(r"<\s*/\s*source\s*>", re.IGNORECASE)


@dataclass
class SourceDocument:
    """One input document for the LLM extraction pipeline.

    `metadata` keys become XML attributes (escaped). Use sparingly — the LLM
    should mostly key off `id` and `type`.
    """

    source_id: str
    source_type: str  # 'syllabus' | 'rmp_review' | 'reddit_post' | 'catalog' | ...
    content: str
    metadata: dict[str, str] = field(default_factory=dict)


def format_sources(sources: list[SourceDocument]) -> str:
    """Wrap sources in `<source>` tags. Returns a single string ready to
    embed in a prompt template.

    Raises ValueError on duplicate source_ids (LLM evidence_snippet.source_id
    must unambiguously map back to one input).
    """
    if not sources:
        return ""

    seen_ids: set[str] = set()
    parts: list[str] = []
    for src in sources:
        if not src.source_id:
            raise ValueError("SourceDocument.source_id must be non-empty")
        if src.source_id in seen_ids:
            raise ValueError(f"Duplicate source_id: {src.source_id!r}")
        seen_ids.add(src.source_id)

        attrs = [
            f'id="{_attr_escape(src.source_id)}"',
            f'type="{_attr_escape(src.source_type)}"',
        ]
        for k in sorted(src.metadata):
            attrs.append(f'{k}="{_attr_escape(src.metadata[k])}"')

        safe_content = _CLOSE_TAG_RE.sub(r"<\\/source>", src.content)
        parts.append(f"<source {' '.join(attrs)}>\n{safe_content}\n</source>")

    return "\n\n".join(parts)


def _attr_escape(s: str) -> str:
    """Escape attribute value: replace " and < and >. Keep & since most
    LLMs handle bare ampersands fine and full HTML escaping bloats the prompt."""
    return s.replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


__all__ = ["SourceDocument", "format_sources"]
