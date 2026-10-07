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
    error_log_fields,
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


def _interrupted_stream() -> Any:
    yield _FakeResponse(text="partial ")
    raise RuntimeError("connection reset")


def _failing_before_text() -> Any:
    """The real SDK sends the request on the first iteration, so its errors come from next()."""
    raise RuntimeError("upstream status 429")
    yield  # pragma: no cover - makes this a generator


def _textless_then_failing() -> Any:
    yield _FakeResponse(text="")
    raise RuntimeError("connection reset")


def test_generate_text_stream_interruption_keeps_the_earlier_chunks() -> None:
    received: list[str] = []
    with pytest.raises(GeminiError, match="stream interrupted") as info:
        for chunk in generate_text_stream("p", client=_FakeClient(_interrupted_stream())):
            received.append(chunk)
    assert received == ["partial "]
    assert info.value.kind == "stream_interrupted"


# === error kinds and log-safe fields ===

def _structured(client: Any) -> Any:
    return generate_structured("p", schema=_Sample, client=client)


def _text(client: Any) -> Any:
    return generate_text("p", client=client)


def _stream(client: Any) -> Any:
    return list(generate_text_stream("p", client=client))


@pytest.mark.parametrize(("call", "response", "kind"), [
    (_structured, RuntimeError("x"), "call_failed"),
    (_structured, _FakeResponse(text="not json"), "invalid_response"),
    (_structured, _FakeResponse(text='{"wrong_field": 1}'), "invalid_response"),
    (_structured, _FakeResponse(text=""), "empty_response"),
    (_text, ConnectionError("x"), "call_failed"),
    (_text, _FakeResponse(text=""), "empty_response"),
    (_stream, RuntimeError("x"), "stream_init_failed"),
    (_stream, _failing_before_text(), "stream_init_failed"),  # Before any text, as with the real SDK.
    (_stream, _textless_then_failing(), "stream_init_failed"),
    (_stream, [_FakeResponse(text="")], "empty_stream"),
    (_stream, _interrupted_stream(), "stream_interrupted"),
])
def test_each_failure_names_its_kind(call: Any, response: Any, kind: str) -> None:
    with pytest.raises(GeminiError) as info:
        call(_FakeClient(response))
    assert info.value.kind == kind


UPSTREAM_TEXT = "POST https://upstream.example/v1/models?key=placeholder-credential-123 body=request-body-sample"


class _StatusError(RuntimeError):
    def __init__(self, message: str, code: Any) -> None:
        super().__init__(message)
        self.code = code


class _Response:
    status_code = 503


class _ResponseError(RuntimeError):
    response = _Response()


def _wrapped(cause: BaseException) -> GeminiError:
    error = GeminiError(f"Gemini API call failed: {type(cause).__name__}: {cause}", kind="call_failed")
    error.__cause__ = cause
    return error


def test_error_log_fields_keep_types_kind_and_status_never_the_message() -> None:
    fields = error_log_fields(_wrapped(_StatusError(UPSTREAM_TEXT, 429)))
    assert fields == {"exc_type": "GeminiError", "error_kind": "call_failed",
                      "cause_type": "_StatusError", "upstream_status": 429}


@pytest.mark.parametrize(("status", "logged"), [
    ("RESOURCE_EXHAUSTED", "RESOURCE_EXHAUSTED"),
    ("Bad Gateway", None),  # google.genai's fallback for a body that is not JSON: a reason phrase.
    ("A" * 41, None),
    (429, None),
])
def test_error_log_fields_keep_only_a_status_name(status: Any, logged: str | None) -> None:
    cause = _StatusError(UPSTREAM_TEXT, 429)
    cause.status = status  # type: ignore[attr-defined]
    assert error_log_fields(_wrapped(cause)).get("upstream_reason") == logged


class _BrokenProperty(RuntimeError):
    @property
    def code(self) -> int:
        raise RuntimeError("property failed")


class _NoInitError(GeminiError):
    def __init__(self, message: str) -> None:  # Skips GeminiError.__init__, so no .kind.
        Exception.__init__(self, message)


def test_error_log_fields_never_raise() -> None:
    """It runs inside except blocks: a second error there would cut the chat stream off."""
    assert error_log_fields(_wrapped(_BrokenProperty(UPSTREAM_TEXT))) == {
        "exc_type": "GeminiError", "error_kind": "call_failed", "cause_type": "_BrokenProperty"}
    assert error_log_fields(_NoInitError(UPSTREAM_TEXT)) == {"exc_type": "_NoInitError", "error_kind": "error"}
    # A kind that is not text (callers compare it against string sets) is reported as the default.
    assert error_log_fields(GeminiError(UPSTREAM_TEXT, kind=5))["error_kind"] == "error"  # type: ignore[arg-type]


def test_error_log_fields_read_the_status_of_an_httpx_style_response() -> None:
    assert error_log_fields(_wrapped(_ResponseError(UPSTREAM_TEXT)))["upstream_status"] == 503


@pytest.mark.parametrize("code", [True, "429", None, 4.29])
def test_error_log_fields_skip_a_status_that_is_not_an_integer(code: Any) -> None:
    fields = error_log_fields(_wrapped(_StatusError(UPSTREAM_TEXT, code)))
    assert "upstream_status" not in fields and fields["cause_type"] == "_StatusError"


def test_error_log_fields_look_past_a_boolean_code_and_skip_a_boolean_status() -> None:
    cause = _StatusError(UPSTREAM_TEXT, True)
    cause.response = _Response()  # type: ignore[attr-defined]  # status_code 503
    assert error_log_fields(_wrapped(cause))["upstream_status"] == 503
    other = _StatusError(UPSTREAM_TEXT, None)
    other.response = type("_BoolResponse", (), {"status_code": True})()  # type: ignore[attr-defined]
    assert "upstream_status" not in error_log_fields(_wrapped(other))


def test_error_log_fields_of_other_errors() -> None:
    assert error_log_fields(RuntimeError(UPSTREAM_TEXT)) == {"exc_type": "RuntimeError"}
    assert error_log_fields(GeminiError(UPSTREAM_TEXT)) == {"exc_type": "GeminiError", "error_kind": "error"}


# === lazy SDK import ===

def test_module_imports_without_api_key() -> None:
    """Importing llm.gemini_client should not require GEMINI_API_KEY in env.
    The fact that we got here in test_gemini_client.py imports proves it.
    """
    import llm.gemini_client  # noqa: F401
