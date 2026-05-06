"""Tests for llm.gemini_client — uses fake client objects, no SDK / API calls.

Migrated to google.genai SDK shape per PLAN v2.3 §3.5: the SDK now exposes
client.models.generate_content / generate_content_stream (instead of
GenerativeModel.generate_content), so the fake mirrors that surface.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from llm.gemini_client import (
    GeminiError,
    generate_structured,
    generate_text,
    generate_text_stream,
)


class _FakeResponse:
    def __init__(self, text: str = "", *, candidates: list | None = None):
        self.text = text
        self.candidates = candidates or []


class _FakeModels:
    """Replays a single response, raises on Exception, or yields stream chunks.

    `response` may be:
      - a _FakeResponse (one-shot generate_content)
      - an Exception (raised on call)
      - an iterable (used as stream chunks for generate_content_stream)
    """

    def __init__(self, response: Any):
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def generate_content(
        self,
        *,
        model: str,
        contents: Any,
        config: Any | None = None,
    ) -> Any:
        self.calls.append({"model": model, "contents": contents, "config": config})
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    def generate_content_stream(
        self,
        *,
        model: str,
        contents: Any,
        config: Any | None = None,
    ) -> Any:
        self.calls.append({"model": model, "contents": contents, "config": config})
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _FakeClient:
    def __init__(self, response: Any):
        self.models = _FakeModels(response)


class _Sample(BaseModel):
    name: str
    count: int


# === generate_structured ===

def test_generate_structured_validates_against_schema() -> None:
    fake = _FakeClient(_FakeResponse(text='{"name": "foo", "count": 3}'))
    result = generate_structured("dummy prompt", schema=_Sample, client=fake)
    assert isinstance(result, _Sample)
    assert result.name == "foo"
    assert result.count == 3


def test_generate_structured_passes_stripped_schema_dict() -> None:
    """Schema goes through pydantic_to_gemini_schema → dict.
    Going through a Pydantic class directly trips a SDK-internal bug where it
    emits `additional_properties` (snake_case) at the protobuf layer and
    Gemini's API rejects it with INVALID_ARGUMENT. The dict path bypasses
    that re-serialization (cf. live smoke during Week 8 §3.5 migration)."""
    fake = _FakeClient(_FakeResponse(text='{"name": "x", "count": 1}'))
    generate_structured("p", schema=_Sample, client=fake, temperature=0.5)
    call = fake.models.calls[0]
    assert call["model"] == "gemini-2.5-flash"
    assert call["contents"] == "p"
    config = call["config"]
    assert config.response_mime_type == "application/json"
    assert config.temperature == 0.5
    # response_schema is a stripped dict, not the Pydantic class
    schema = config.response_schema
    assert isinstance(schema, dict)
    assert schema["type"] == "object"
    assert set(schema["properties"].keys()) == {"name", "count"}


def test_generate_structured_invalid_json_raises_gemini_error() -> None:
    fake = _FakeClient(_FakeResponse(text="not json at all"))
    with pytest.raises(GeminiError, match="schema validation"):
        generate_structured("p", schema=_Sample, client=fake)


def test_generate_structured_schema_mismatch_raises() -> None:
    fake = _FakeClient(_FakeResponse(text='{"wrong_field": 1}'))
    with pytest.raises(GeminiError, match="schema validation"):
        generate_structured("p", schema=_Sample, client=fake)


def test_generate_structured_api_error_wrapped() -> None:
    fake = _FakeClient(RuntimeError("simulated quota error"))
    with pytest.raises(GeminiError, match="Gemini API call failed"):
        generate_structured("p", schema=_Sample, client=fake)


def test_generate_structured_handles_candidates_path() -> None:
    """When response.text is empty but candidates[].content.parts[].text has it."""
    candidate = MagicMock()
    candidate.content.parts = [MagicMock(text='{"name": "via_candidates", "count": 7}')]
    fake = _FakeClient(_FakeResponse(text="", candidates=[candidate]))

    result = generate_structured("p", schema=_Sample, client=fake)
    assert result.name == "via_candidates"


def test_generate_structured_empty_response_raises() -> None:
    """No text at all — likely safety block; should raise loud GeminiError."""
    fake = _FakeClient(_FakeResponse(text="", candidates=[]))
    with pytest.raises(GeminiError, match="no text content"):
        generate_structured("p", schema=_Sample, client=fake)


# === generate_text ===

def test_generate_text_returns_text() -> None:
    fake = _FakeClient(_FakeResponse(text="hello world"))
    assert generate_text("p", client=fake) == "hello world"


def test_generate_text_uses_default_temperature() -> None:
    fake = _FakeClient(_FakeResponse(text="x"))
    generate_text("p", client=fake, temperature=0.9)
    call = fake.models.calls[0]
    config = call["config"]
    assert config.temperature == 0.9
    # No JSON schema config in text mode
    assert config.response_mime_type is None
    assert config.response_schema is None


def test_generate_text_api_error_wrapped() -> None:
    fake = _FakeClient(ConnectionError("network down"))
    with pytest.raises(GeminiError, match="Gemini API call failed"):
        generate_text("p", client=fake)


# === generate_text_stream ===

def test_generate_text_stream_yields_chunks() -> None:
    """SDK yields chunks each with .text; wrapper passes them through."""
    chunks = [_FakeResponse(text="hello "), _FakeResponse(text="world")]
    fake = _FakeClient(chunks)
    out = list(generate_text_stream("p", client=fake))
    assert out == ["hello ", "world"]


def test_generate_text_stream_empty_raises() -> None:
    """If no chunk has text (safety block) we raise rather than silently
    returning an empty string."""
    fake = _FakeClient([_FakeResponse(text="")])
    with pytest.raises(GeminiError, match="no text chunks"):
        list(generate_text_stream("p", client=fake))


def test_generate_text_stream_init_error_wrapped() -> None:
    fake = _FakeClient(RuntimeError("api unavailable"))
    with pytest.raises(GeminiError, match="stream init failed"):
        list(generate_text_stream("p", client=fake))


# === lazy SDK import ===

def test_module_imports_without_api_key() -> None:
    """Importing llm.gemini_client should not require GEMINI_API_KEY in env.
    The fact that we got here in test_gemini_client.py imports proves it.
    """
    import llm.gemini_client  # noqa: F401
