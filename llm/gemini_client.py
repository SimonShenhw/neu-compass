"""Gemini 2.5 Flash client wrapper (google.genai SDK).

Migrated from `google.generativeai` (deprecated) per PLAN v2.3 §3.5.

Schema-stripping is still required:
The new SDK has its own bug — when you pass a Pydantic class as
`response_schema`, the SDK serializes it to a protobuf payload that
includes `additional_properties` (snake_case), and Gemini's API rejects
that field with INVALID_ARGUMENT. We sidestep this by going through a
dict path: `pydantic_to_gemini_schema(model)` returns a stripped dict
that the SDK ships verbatim (no re-serialization), so we control the
exact wire format. The strip list is the same as for the old SDK
(both surfaces reject OpenAPI-3-incompatible JSON-Schema-2020 keywords),
which is why the helper survives the migration.

Design choice: generate_structured() accepts an explicit `client` parameter
so tests can pass a fake without monkey-patching globals. The default factory
_build_default_client() reads settings.gemini_api_key.

Cost discipline (PLAN §8 budget): caller is responsible for managing prompt
length + retries. This wrapper does NOT auto-retry on quota errors — Gemini
quota retries cost real money. Caller logs + decides.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_TEMPERATURE = 0.2  # low for extraction; high for creative tasks
DEFAULT_MAX_OUTPUT_TOKENS = 16384  # Week 7 §3.2: 8192 truncated CS 5800 mid-JSON


class GeminiError(Exception):
    """Wrapped error from Gemini API call or response parsing."""


class _ModelsLike(Protocol):
    """Subset of google.genai client.models we need."""

    def generate_content(
        self,
        *,
        model: str,
        contents: Any,
        config: Any | None = ...,
    ) -> Any: ...

    def generate_content_stream(
        self,
        *,
        model: str,
        contents: Any,
        config: Any | None = ...,
    ) -> Any: ...


class _ClientLike(Protocol):
    models: _ModelsLike


# Hard ceiling on any single Gemini HTTP round-trip (milliseconds — the SDK's
# HttpOptions unit). Without it a hung call holds the request slot forever;
# /chat streams stay well under this, and extraction calls that exceed it are
# better surfaced as GeminiError than waited on.
DEFAULT_HTTP_TIMEOUT_MS = 120_000


@lru_cache(maxsize=4)
def _build_client_with_timeout(timeout_ms: int) -> _ClientLike:
    """Lazy: import SDK + build Client on first use; one cached client per
    distinct timeout (the SDK sets timeout at client construction, not per
    call). maxsize=4 — in practice two values exist: the 120s default and
    the short rescue budget."""
    from google import genai  # noqa: PLC0415
    from google.genai import types  # noqa: PLC0415

    from config import settings  # noqa: PLC0415

    return genai.Client(  # type: ignore[return-value]
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(timeout=timeout_ms),
    )


def _build_default_client() -> _ClientLike:
    return _build_client_with_timeout(DEFAULT_HTTP_TIMEOUT_MS)


# Schema keywords Gemini's Schema proto doesn't accept. Pydantic v2's
# model_json_schema() emits these for Field(min_length=...) / Field(pattern=...)
# / nested-model $refs / etc — passing them through trips
# `Unknown name "<key>": Cannot find field` from the API (or its protobuf layer).
# Both google.generativeai (old) and google.genai (new) reject the same set
# at the wire level, so the strip list survives the SDK migration.
_GEMINI_UNSUPPORTED_SCHEMA_KEYS = frozenset({
    "minLength", "maxLength", "pattern",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "additionalProperties", "propertyNames", "patternProperties",
    "uniqueItems", "contains", "minContains", "maxContains",
    "$schema", "$id", "title",  # title harmless but cleaner to drop at top level
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
        # Collapse `anyOf` BEFORE generic recursion. Both old and new Gemini
        # Schema surfaces reject `anyOf` outright.
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

    Why not pass the Pydantic class directly: both old and new SDKs
    re-serialize Pydantic schemas in ways the API rejects (old SDK chokes
    on `minLength`/`pattern`/etc inside its Schema proto; new SDK emits
    `additional_properties` (snake_case) at the protobuf layer that the
    API rejects with INVALID_ARGUMENT). Going through a stripped dict
    bypasses both bugs.

    The returned dict still validates the LLM's reply via
    `schema.model_validate_json` downstream, so the constraints we strip
    here from the prompt schema are still enforced when we PARSE the response.
    """
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})
    inlined = _resolve_refs(raw, defs)
    return _strip_unsupported(inlined)


def _build_config(
    *,
    temperature: float,
    max_output_tokens: int,
    response_schema: dict[str, Any] | None = None,
    thinking_budget: int | None = None,
) -> Any:
    """Construct GenerateContentConfig with our defaults.

    When response_schema is set, also forces JSON mime so Gemini emits
    structured output validating the schema. Schema must be the
    pre-stripped dict (cf. pydantic_to_gemini_schema), not a Pydantic class.

    thinking_budget: gemini-2.5-flash "thinks" by default, which multiplies
    latency+cost. Mechanical tasks (batch extraction/expansion) set 0;
    None keeps the model default (good for judgment calls like the
    ADR-0019 rescue verdict).
    """
    from google.genai import types  # noqa: PLC0415

    kwargs: dict[str, Any] = {
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
    }
    if response_schema is not None:
        kwargs["response_mime_type"] = "application/json"
        kwargs["response_schema"] = response_schema
    if thinking_budget is not None:
        kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_budget=thinking_budget
        )
    return types.GenerateContentConfig(**kwargs)


def generate_structured(
    prompt: str,
    *,
    schema: type[T],
    client: _ClientLike | None = None,
    model_name: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    thinking_budget: int | None = None,
) -> T:
    """Call Gemini, parse JSON response, validate against `schema`.

    Caller may inject `client` for testing. Otherwise uses cached default
    (lazy SDK import + config from settings.gemini_api_key).

    Raises GeminiError on:
      - API call failure (network / quota / auth)
      - Response not valid JSON
      - JSON not matching `schema`
    """
    if client is None:
        client = _build_default_client()

    response_schema = pydantic_to_gemini_schema(schema)
    config = _build_config(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        response_schema=response_schema,
        thinking_budget=thinking_budget,
    )

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config,
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
    client: _ClientLike | None = None,
    model_name: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    timeout_ms: int | None = None,
) -> str:
    """Plain text response (no JSON schema). Use for prompts that don't need
    structured output — e.g., quick summary or paraphrase tasks.

    timeout_ms: per-call HTTP budget override. Latency-sensitive callers
    (the HyDE rescue sits INSIDE a /search request) must not inherit the
    120s default — a hung Gemini call would pin a threadpool worker and
    the user for two minutes."""
    if client is None:
        client = (
            _build_client_with_timeout(timeout_ms)
            if timeout_ms is not None
            else _build_default_client()
        )

    config = _build_config(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config,
        )
    except Exception as e:
        raise GeminiError(f"Gemini API call failed: {type(e).__name__}: {e}") from e

    return _extract_text(response)


def generate_text_stream(
    prompt: str,
    *,
    client: _ClientLike | None = None,
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
    if client is None:
        client = _build_default_client()

    config = _build_config(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )

    try:
        stream = client.models.generate_content_stream(
            model=model_name,
            contents=prompt,
            config=config,
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
    """Pull the text out of a Gemini response. response.text is a property
    that auto-concatenates parts; falls back to candidates path if empty."""
    text = getattr(response, "text", None)
    if text:
        return str(text)

    # Fallback: dig through candidates path (defensive — covers safety-blocked
    # responses where .text returns None but parts may still have content).
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
