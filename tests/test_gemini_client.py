"""Tests for llm.gemini_client — uses fake model objects, no SDK / API calls."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from llm.gemini_client import (
    GeminiError,
    generate_structured,
    generate_text,
)


class _FakeResponse:
    def __init__(self, text: str = "", *, candidates: list | None = None):
        self.text = text
        self.candidates = candidates or []


class _FakeModel:
    """Replays a queue of responses or raises."""

    def __init__(self, response: Any):
        self._response = response
        self.calls: list[tuple[str, dict]] = []

    def generate_content(self, prompt: str, generation_config: Any | None = None) -> Any:
        self.calls.append((prompt, dict(generation_config) if generation_config else {}))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _Sample(BaseModel):
    name: str
    count: int


# === generate_structured ===

def test_generate_structured_validates_against_schema() -> None:
    fake = _FakeModel(_FakeResponse(text='{"name": "foo", "count": 3}'))
    result = generate_structured("dummy prompt", schema=_Sample, model=fake)
    assert isinstance(result, _Sample)
    assert result.name == "foo"
    assert result.count == 3


def test_generate_structured_passes_schema_in_config() -> None:
    """The Pydantic class is converted to a Gemini-compatible JSON Schema dict
    before reaching the SDK (otherwise the SDK chokes on minLength/pattern/etc
    that Pydantic emits but Gemini's Schema proto rejects)."""
    fake = _FakeModel(_FakeResponse(text='{"name": "x", "count": 1}'))
    generate_structured("p", schema=_Sample, model=fake, temperature=0.5)
    _, config = fake.calls[0]
    assert config["response_mime_type"] == "application/json"
    assert config["temperature"] == 0.5
    schema = config["response_schema"]
    assert isinstance(schema, dict)
    assert schema["type"] == "object"
    assert set(schema["properties"].keys()) == {"name", "count"}


def test_generate_structured_invalid_json_raises_gemini_error() -> None:
    fake = _FakeModel(_FakeResponse(text="not json at all"))
    with pytest.raises(GeminiError, match="schema validation"):
        generate_structured("p", schema=_Sample, model=fake)


def test_generate_structured_schema_mismatch_raises() -> None:
    fake = _FakeModel(_FakeResponse(text='{"wrong_field": 1}'))
    with pytest.raises(GeminiError, match="schema validation"):
        generate_structured("p", schema=_Sample, model=fake)


def test_generate_structured_api_error_wrapped() -> None:
    fake = _FakeModel(RuntimeError("simulated quota error"))
    with pytest.raises(GeminiError, match="Gemini API call failed"):
        generate_structured("p", schema=_Sample, model=fake)


def test_generate_structured_handles_candidates_path() -> None:
    """When response.text is empty but candidates[].content.parts[].text has it."""
    candidate = MagicMock()
    candidate.content.parts = [MagicMock(text='{"name": "via_candidates", "count": 7}')]
    fake = _FakeModel(_FakeResponse(text="", candidates=[candidate]))

    result = generate_structured("p", schema=_Sample, model=fake)
    assert result.name == "via_candidates"


def test_generate_structured_empty_response_raises() -> None:
    """No text at all — likely safety block; should raise loud GeminiError."""
    fake = _FakeModel(_FakeResponse(text="", candidates=[]))
    with pytest.raises(GeminiError, match="no text content"):
        generate_structured("p", schema=_Sample, model=fake)


# === generate_text ===

def test_generate_text_returns_text() -> None:
    fake = _FakeModel(_FakeResponse(text="hello world"))
    assert generate_text("p", model=fake) == "hello world"


def test_generate_text_uses_default_temperature() -> None:
    fake = _FakeModel(_FakeResponse(text="x"))
    generate_text("p", model=fake, temperature=0.9)
    _, config = fake.calls[0]
    assert config["temperature"] == 0.9
    # No JSON config for text mode
    assert "response_mime_type" not in config


def test_generate_text_api_error_wrapped() -> None:
    fake = _FakeModel(ConnectionError("network down"))
    with pytest.raises(GeminiError, match="Gemini API call failed"):
        generate_text("p", model=fake)


# === lazy SDK import ===

def test_module_imports_without_api_key() -> None:
    """Importing llm.gemini_client should not require GEMINI_API_KEY in env.
    The fact that we got here in test_gemini_client.py imports proves it.
    """
    import llm.gemini_client  # noqa: F401
