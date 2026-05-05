"""Gemini 2.5 Flash client wrapper.

Wraps google.generativeai for structured JSON output validated by Pydantic.
The SDK import is lazy (inside _build_default_model) so test imports of
this module don't require GEMINI_API_KEY in the environment.

Design choice: generate_structured() accepts an explicit `model` parameter,
so tests can pass a fake without monkey-patching globals. The default
factory _build_default_model() is what gets used in production.

Cost discipline (PLAN §8 budget): caller is responsible for managing
prompt length + retries. This wrapper does NOT auto-retry on quota errors —
Gemini quota retries cost real money. Caller logs + decides.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_TEMPERATURE = 0.2  # low for extraction; high for creative tasks
DEFAULT_MAX_OUTPUT_TOKENS = 16384  # Week 7 §3.2 finding: 8192 truncated CS 5800
                                    # mid-JSON when controversial_signals + topics
                                    # filled. Doubled to 16384; still well under
                                    # Flash's 65536 ceiling.


class GeminiError(Exception):
    """Wrapped error from Gemini API call or response parsing."""


class _ModelLike(Protocol):
    """Minimal interface we need from a Gemini GenerativeModel.

    Lets tests pass a fake without depending on the SDK or having a real key.
    """

    def generate_content(
        self,
        prompt: str,
        generation_config: Any | None = ...,
        stream: bool = ...,
    ) -> Any: ...


@lru_cache(maxsize=4)
def _build_default_model(name: str = DEFAULT_MODEL) -> _ModelLike:
    """Lazy: import SDK + configure on first use, cache by model name."""
    import google.generativeai as genai  # noqa: PLC0415

    from config import settings  # noqa: PLC0415

    genai.configure(api_key=settings.gemini_api_key)
    return genai.GenerativeModel(name)  # type: ignore[return-value]


# Pydantic-generated JSON Schema keywords that the Gemini Schema proto doesn't
# understand. Passing any of them through trips
# `ValueError: Unknown field for Schema: <k>` inside _normalize_schema.
# Pydantic v2 emits these from Field(min_length=...) / Field(pattern=...) etc.
_GEMINI_UNSUPPORTED_SCHEMA_KEYS = frozenset({
    "minLength", "maxLength", "pattern",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "additionalProperties", "propertyNames", "patternProperties",
    "uniqueItems", "contains", "minContains", "maxContains",
    "$schema", "$id", "title",  # title is harmless but cleaner to drop
    "const", "default",  # Gemini Schema doesn't model these
})


def _resolve_refs(node: Any, defs: dict[str, Any]) -> Any:
    """Inline Pydantic's $ref pointers using its $defs table.

    Pydantic v2 emits `{"$ref": "#/$defs/Name"}` for nested-model references.
    Gemini's Schema proto has no $ref concept; it requires fully-inlined trees.
    Cycles aren't expected for the schemas we send (Course / Alias / Coop are
    DAGs); we don't guard against them here.
    """
    if isinstance(node, dict):
        if "$ref" in node and len(node) == 1:
            ref_name = node["$ref"].split("/")[-1]
            return _resolve_refs(defs.get(ref_name, {}), defs)
        return {k: _resolve_refs(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_resolve_refs(x, defs) for x in node]
    return node


def _strip_unsupported(node: Any, *, in_properties_map: bool = False) -> Any:
    """Drop schema keywords Gemini doesn't accept; collapse Pydantic-style
    union encodings into Gemini's `nullable` form.

    Three Pydantic patterns we normalize:
      - `Optional[T]` → `{anyOf: [{type:T}, {type:"null"}]}` → `{type:T, nullable:True}`
      - JSON-Schema-2020 nullable → `{type:["foo","null"]}` → `{type:"foo", nullable:True}`
      - Multiple non-null variants in `anyOf` → first one (lossy; our schemas
        don't actually use sum types beyond Optional, so this branch is
        defensive rather than load-bearing).

    Context-aware: when `in_properties_map=True`, dict keys are property
    NAMES (e.g. a Textbook model has a property literally called `title`),
    not schema keywords — so the keyword blacklist is suppressed at that
    level. Without this, stripping `title` as metadata also nuked the
    `title` data field, leaving `required: ["title"]` dangling and Gemini
    complaining `property is not defined`.

    After the per-node strip, we also prune `required` entries that no
    longer have a corresponding `properties` key (defense in depth).
    """
    if isinstance(node, dict):
        # Collapse `anyOf` BEFORE generic recursion. The Gemini SDK proto we're
        # bound to doesn't model `anyOf` and rejects it loudly.
        if "anyOf" in node and not in_properties_map:
            variants = node["anyOf"]
            non_null = [
                v for v in variants
                if not (isinstance(v, dict) and v.get("type") == "null")
            ]
            has_null = len(non_null) < len(variants)
            if non_null:
                base = _strip_unsupported(non_null[0])
                if not isinstance(base, dict):
                    base = {"type": "string"}
                if has_null:
                    base["nullable"] = True
                if "description" in node and "description" not in base:
                    base["description"] = node["description"]
                return base
            return {"type": "string", "nullable": True}

        cleaned: dict[str, Any] = {}
        for k, v in node.items():
            # Inside a properties map, k is a property name — don't blacklist.
            if not in_properties_map and k in _GEMINI_UNSUPPORTED_SCHEMA_KEYS:
                continue
            if not in_properties_map and k == "type" and isinstance(v, list):
                non_null_types = [t for t in v if t != "null"]
                cleaned["type"] = non_null_types[0] if non_null_types else "string"
                if "null" in v:
                    cleaned["nullable"] = True
                continue
            cleaned[k] = _strip_unsupported(
                v, in_properties_map=(k == "properties" and not in_properties_map),
            )

        # Prune dangling `required` entries (defense: should be moot now that
        # properties keys aren't blacklisted, but a Pydantic schema with
        # exclude_*-style trickery could still produce this gap).
        if "required" in cleaned and "properties" in cleaned:
            valid = set(cleaned["properties"].keys())
            cleaned["required"] = [r for r in cleaned["required"] if r in valid]
            if not cleaned["required"]:
                del cleaned["required"]

        return cleaned
    if isinstance(node, list):
        return [_strip_unsupported(x) for x in node]
    return node


def pydantic_to_gemini_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Convert a Pydantic model class into a dict the Gemini SDK accepts as
    `response_schema`.

    Why we don't pass the Pydantic class directly: the SDK's
    `_normalize_schema` calls `protos.Schema(**dict)` recursively and barfs on
    Pydantic-only keywords (minLength, pattern, additionalProperties, …).
    The reverse fix — telling Pydantic not to emit those — would weaken
    server-side validation, which we want strict.

    The returned dict still validates the LLM's reply via
    `schema.model_validate_json` downstream, so the constraints we strip from
    the prompt are still enforced when we PARSE the response.
    """
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})
    inlined = _resolve_refs(raw, defs)
    return _strip_unsupported(inlined)


def generate_structured(
    prompt: str,
    *,
    schema: type[T],
    model: _ModelLike | None = None,
    model_name: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> T:
    """Call Gemini, parse JSON response, validate against `schema`.

    Caller may inject `model` for testing. Otherwise uses cached default
    (lazy SDK import + config from settings.gemini_api_key).

    Raises GeminiError on:
      - API call failure (network / quota / auth)
      - Response not valid JSON
      - JSON not matching `schema`
    """
    if model is None:
        model = _build_default_model(model_name)

    response_schema = pydantic_to_gemini_schema(schema)

    try:
        response = model.generate_content(
            prompt,
            generation_config={
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
                "response_mime_type": "application/json",
                "response_schema": response_schema,
            },
        )
    except Exception as e:
        raise GeminiError(f"Gemini API call failed: {type(e).__name__}: {e}") from e

    response_text = _extract_text(response)
    try:
        return schema.model_validate_json(response_text)
    except Exception as e:
        raise GeminiError(
            f"Response failed schema validation against {schema.__name__}: "
            f"{type(e).__name__}: {e}\nResponse text: {response_text[:500]}"
        ) from e


def generate_text(
    prompt: str,
    *,
    model: _ModelLike | None = None,
    model_name: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> str:
    """Plain text response (no JSON schema). Use for prompts that don't need
    structured output — e.g., quick summary or paraphrase tasks."""
    if model is None:
        model = _build_default_model(model_name)

    try:
        response = model.generate_content(
            prompt,
            generation_config={
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
            },
        )
    except Exception as e:
        raise GeminiError(f"Gemini API call failed: {type(e).__name__}: {e}") from e

    return _extract_text(response)


def generate_text_stream(
    prompt: str,
    *,
    model: _ModelLike | None = None,
    model_name: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> Iterator[str]:
    """Yield text chunks as Gemini produces them.

    Used by /chat for token-by-token UI streaming (Streamlit st.write_stream).
    Caller must consume the iterator promptly — Gemini disconnects idle
    streams after a few seconds.

    GeminiError surfaces if the SDK raises during stream init OR if the
    response never produces text (safety block, empty completion). Per-chunk
    errors mid-stream propagate as GeminiError too — the partial output up
    to that point is what the caller already received.
    """
    if model is None:
        model = _build_default_model(model_name)

    try:
        stream = model.generate_content(
            prompt,
            generation_config={
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
            },
            stream=True,
        )
    except Exception as e:
        raise GeminiError(
            f"Gemini stream init failed: {type(e).__name__}: {e}"
        ) from e

    saw_any_text = False
    try:
        for chunk in stream:
            text = getattr(chunk, "text", None)
            if text:
                saw_any_text = True
                yield str(text)
    except Exception as e:
        raise GeminiError(
            f"Gemini stream interrupted: {type(e).__name__}: {e}"
        ) from e

    if not saw_any_text:
        raise GeminiError(
            "Gemini stream produced no text chunks (safety block or empty completion)"
        )


def _extract_text(response: Any) -> str:
    """Pull the text out of a Gemini response. Handles both .text and the
    longer .candidates path; raises GeminiError if neither yields content."""
    text = getattr(response, "text", None)
    if text:
        return str(text)

    # Fall back to candidates path (newer SDK responses)
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        parts = getattr(getattr(candidate, "content", None), "parts", None) or []
        for part in parts:
            part_text = getattr(part, "text", None)
            if part_text:
                return str(part_text)

    raise GeminiError(
        "Gemini response had no text content. "
        f"Possible safety block or empty completion. Response: {response!r}"
    )


__all__ = [
    "DEFAULT_MAX_OUTPUT_TOKENS",
    "DEFAULT_MODEL",
    "DEFAULT_TEMPERATURE",
    "GeminiError",
    "generate_structured",
    "generate_text",
    "generate_text_stream",
    "pydantic_to_gemini_schema",
]
