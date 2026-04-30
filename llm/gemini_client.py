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

from functools import lru_cache
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_TEMPERATURE = 0.2  # low for extraction; high for creative tasks
DEFAULT_MAX_OUTPUT_TOKENS = 8192


class GeminiError(Exception):
    """Wrapped error from Gemini API call or response parsing."""


class _ModelLike(Protocol):
    """Minimal interface we need from a Gemini GenerativeModel.

    Lets tests pass a fake without depending on the SDK or having a real key.
    """

    def generate_content(
        self, prompt: str, generation_config: Any | None = ...
    ) -> Any: ...


@lru_cache(maxsize=4)
def _build_default_model(name: str = DEFAULT_MODEL) -> _ModelLike:
    """Lazy: import SDK + configure on first use, cache by model name."""
    import google.generativeai as genai  # noqa: PLC0415

    from config import settings  # noqa: PLC0415

    genai.configure(api_key=settings.gemini_api_key)
    return genai.GenerativeModel(name)  # type: ignore[return-value]


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

    try:
        response = model.generate_content(
            prompt,
            generation_config={
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
                "response_mime_type": "application/json",
                "response_schema": schema,
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
]
