"""Tests for app.streamlit_app — pure helper functions + import smoke.

The render() body needs Streamlit's session machinery and isn't exercised
here. We cover the data-shaping helpers and confirm the module imports
cleanly without Streamlit running."""

from __future__ import annotations

from app.streamlit_app import _format_evidence, _summarize_results, stream_assistant


# === _format_evidence ===


def test_format_evidence_extracts_canonical_fields() -> None:
    results = [
        {
            "course_id": "c-cs-5800", "primary_code": "CS 5800",
            "primary_name": "Algorithms", "score": 0.65,
            "matched_via": "hybrid",
        },
        {
            "course_id": "c-aai-6600", "primary_code": "AAI 6600",
            "primary_name": "Applied AI", "score": 0.50,
            "matched_via": "hybrid",
        },
    ]
    out = _format_evidence(results)
    assert len(out) == 2
    assert out[0] == {
        "course_id": "c-cs-5800",
        "primary_code": "CS 5800",
        "primary_name": "Algorithms",
        "score": 0.65,
    }


def test_format_evidence_empty() -> None:
    assert _format_evidence([]) == []


# === _summarize_results ===


def test_summarize_results_alias_path_emphasizes_single_match() -> None:
    out = _summarize_results(
        [{
            "course_id": "c-cs-5800", "primary_code": "CS 5800",
            "primary_name": "Algorithms", "score": 1.0,
            "matched_via": "alias",
        }],
        matched_via="alias",
    )
    assert "CS 5800" in out
    assert "Algorithms" in out
    assert "alias" in out.lower()


def test_summarize_results_hybrid_lists_topk() -> None:
    out = _summarize_results(
        [
            {"course_id": "c-cs-5800", "primary_code": "CS 5800",
             "primary_name": "Algorithms", "score": 0.7, "matched_via": "hybrid"},
            {"course_id": "c-aai-6600", "primary_code": "AAI 6600",
             "primary_name": "Applied AI", "score": 0.5, "matched_via": "hybrid"},
        ],
        matched_via="hybrid",
    )
    assert "CS 5800" in out
    assert "AAI 6600" in out
    assert "0.700" in out
    assert "1." in out  # numbered list


def test_summarize_results_empty() -> None:
    assert "No matching" in _summarize_results([], matched_via="empty")


# === Import smoke ===


def test_module_imports_without_streamlit_running() -> None:
    """The render() guard must keep `import app.streamlit_app` from
    triggering Streamlit. Mirrors the pattern in test_eval_dashboard."""
    import app.streamlit_app  # noqa: F401


# === stream_assistant ===


class _FakeApi:
    def __init__(self, events: list[dict]) -> None:
        self._events = events

    def chat_stream(self, body):  # noqa: ANN001
        for e in self._events:
            yield e


def test_stream_assistant_yields_token_text_only() -> None:
    state: dict = {}
    api = _FakeApi([
        {"type": "meta", "matched_via": "alias", "results": [{"course_id": "c-cs-5800"}]},
        {"type": "token", "text": "Hello "},
        {"type": "token", "text": "world"},
        {"type": "done"},
    ])
    chunks = list(stream_assistant(api, {"query": "Algo"}, state))
    assert chunks == ["Hello ", "world"]


def test_stream_assistant_captures_meta_into_state() -> None:
    state: dict = {}
    meta_event = {
        "type": "meta",
        "matched_via": "hybrid",
        "results": [{"course_id": "c-1", "primary_code": "CS 5800", "primary_name": "Algorithms", "score": 0.5}],
    }
    api = _FakeApi([meta_event, {"type": "token", "text": "x"}, {"type": "done"}])
    list(stream_assistant(api, {"query": "x"}, state))
    assert state["last_chat_meta"] == meta_event


def test_stream_assistant_handles_error_event() -> None:
    state: dict = {}
    api = _FakeApi([
        {"type": "meta", "results": []},
        {"type": "token", "text": "partial..."},
        {"type": "error", "detail": "Gemini quota exceeded"},
        {"type": "done"},  # never reached after error
    ])
    chunks = list(stream_assistant(api, {"query": "x"}, state))
    assert "partial..." in chunks
    assert any("Gemini quota exceeded" in c for c in chunks)
    assert state["last_chat_error"] == "Gemini quota exceeded"


def test_stream_assistant_resets_state_per_call() -> None:
    """A new chat call should clear stale meta/error from prior turn."""
    state: dict = {"last_chat_meta": {"old": True}, "last_chat_error": "old"}
    api = _FakeApi([{"type": "done"}])  # no events
    list(stream_assistant(api, {"query": "x"}, state))
    assert state["last_chat_meta"] is None
    assert state["last_chat_error"] is None


def test_stream_assistant_skips_empty_token_text() -> None:
    state: dict = {}
    api = _FakeApi([
        {"type": "token", "text": ""},  # noisy empty
        {"type": "token", "text": "real"},
        {"type": "done"},
    ])
    chunks = list(stream_assistant(api, {"query": "x"}, state))
    assert chunks == ["real"]
