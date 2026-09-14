"""Tests for app.deep_links — share-URL building + `?course=`/`?program=` consumption.

The pure helpers (course_share_ref / share_url / match_program_ref) are
tested directly. apply_deep_link needs a Streamlit-shaped object; _FakeSt
provides the four surfaces it actually touches (session_state,
query_params, warning, info).
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.deep_links import (
    APPLIED_FLAG,
    apply_deep_link,
    course_share_ref,
    match_program_ref,
    share_url,
)

# Sentinel page labels: apply_deep_link routes by INDEX (0=search,
# 1=programs), so the real emoji strings are irrelevant here — and pinning
# indices instead of labels keeps this test from breaking on a rename.
PAGES = ["PAGE_SEARCH", "PAGE_PROGRAMS", "PAGE_COOP"]

PROGRAMS = [
    {"program_id": "cs-ms", "prefix": "CS", "full_name": "MS in CS"},
    {"program_id": "aai-ms", "prefix": "AAI", "full_name": "MPS in Applied AI"},
]


# ===========================================================================
# Pure helpers
# ===========================================================================


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("CS 5800", "CS-5800"),
        ("  CS 5800  ", "CS-5800"),
        ("CS  5800", "CS-5800"),
        ("CS5800", "CS5800"),
        ("INFO 6205", "INFO-6205"),
    ],
)
def test_course_share_ref(code: str, expected: str) -> None:
    assert course_share_ref(code) == expected


def test_share_url_course() -> None:
    assert share_url("https://compass.neu-compass.me", course="CS-5800") == (
        "https://compass.neu-compass.me/?course=CS-5800"
    )


def test_share_url_tolerates_trailing_slash() -> None:
    """PUBLIC_BASE_URL is hand-edited in .env — both spellings must work."""
    assert share_url("https://x.dev/", course="CS-5800") == share_url(
        "https://x.dev", course="CS-5800",
    )


def test_share_url_program() -> None:
    assert share_url("https://x.dev", program="cs-ms") == (
        "https://x.dev/?program=cs-ms"
    )


def test_share_url_both_params() -> None:
    assert share_url("https://x.dev", course="CS-5800", program="cs-ms") == (
        "https://x.dev/?course=CS-5800&program=cs-ms"
    )


def test_share_url_no_params_is_bare_origin() -> None:
    assert share_url("https://x.dev") == "https://x.dev/"


def test_share_url_never_emits_protocol_relative_url() -> None:
    """A double slash in a hand-edited PUBLIC_BASE_URL must not collapse the
    link into '//?course=...', which browsers read as protocol-relative and
    resolve against a different host."""
    url = share_url("https://x.dev//", course="CS-5800")
    assert url == "https://x.dev/?course=CS-5800"
    assert "//?" not in url


def test_share_url_percent_encodes_cjk_alias() -> None:
    """A CJK slang alias is a legal ref; it must survive the round trip."""
    from urllib.parse import parse_qs, urlparse  # noqa: PLC0415

    url = share_url("https://x.dev", course="应用-AI")
    assert " " not in url
    assert parse_qs(urlparse(url).query)["course"] == ["应用-AI"]


# === match_program_ref ===


def test_match_program_by_id() -> None:
    assert match_program_ref("cs-ms", PROGRAMS) == "cs-ms"


def test_match_program_by_id_case_insensitive() -> None:
    assert match_program_ref("CS-MS", PROGRAMS) == "cs-ms"


def test_match_program_by_prefix() -> None:
    assert match_program_ref("aai", PROGRAMS) == "aai-ms"


def test_match_program_id_beats_prefix() -> None:
    """A program whose id collides with another's prefix must not steal it."""
    programs = [
        {"program_id": "cs", "prefix": "XX"},
        {"program_id": "cs-ms", "prefix": "CS"},
    ]
    assert match_program_ref("cs", programs) == "cs"


def test_match_program_ambiguous_prefix_returns_none() -> None:
    """Two programs sharing a prefix: refuse rather than pick a winner."""
    programs = [
        {"program_id": "cs-ms", "prefix": "CS"},
        {"program_id": "cs-align", "prefix": "CS"},
    ]
    assert match_program_ref("CS", programs) is None


@pytest.mark.parametrize("ref", ["", "  ", "nope", "cs-phd"])
def test_match_program_unknown_returns_none(ref: str) -> None:
    assert match_program_ref(ref, PROGRAMS) is None


# ===========================================================================
# apply_deep_link
# ===========================================================================


class _FakeSt:
    """The four Streamlit surfaces apply_deep_link touches."""

    def __init__(self, **params: str) -> None:
        self.session_state: dict = {}
        self.query_params: dict = dict(params)
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def info(self, msg: str) -> None:
        self.infos.append(msg)


def _fake_resolve(monkeypatch, matches: list[dict] | Exception) -> None:
    """Stub ApiClient so _apply_course_ref never needs a live backend."""
    import app.api_client as api_client_mod  # noqa: PLC0415

    class _FakeApi:
        def __init__(self, *a, **kw) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            pass

        def resolve_course(self, ref: str) -> dict:
            if isinstance(matches, Exception):
                raise matches
            return {"ref": ref, "matches": matches}

    monkeypatch.setattr(api_client_mod, "ApiClient", _FakeApi)


# === No-ops ===


def test_no_params_is_noop() -> None:
    st = _FakeSt()
    apply_deep_link(st, pages=PAGES)
    assert st.session_state == {}


def test_blank_param_is_noop() -> None:
    """?course= with no value shouldn't warn at the user — nothing was asked."""
    st = _FakeSt(course="   ")
    apply_deep_link(st, pages=PAGES)
    assert st.session_state == {}
    assert st.warnings == []


# === Course refs ===


def test_course_ref_opens_detail_panel(monkeypatch) -> None:
    _fake_resolve(monkeypatch, [{
        "course_id": "c-cs-5800", "primary_code": "CS 5800",
        "primary_name": "Algorithms",
    }])
    st = _FakeSt(course="CS-5800")
    apply_deep_link(st, pages=PAGES)

    assert st.session_state["selected_course_id"] == "c-cs-5800"
    assert st.session_state["nav_page"] == "PAGE_SEARCH"
    assert st.warnings == []


def test_course_ref_applies_only_once_per_session(monkeypatch) -> None:
    """Streamlit reruns on every interaction and the param STAYS in the URL
    (it's the shareable part). Without the one-shot flag, every click would
    yank the user back to the linked course."""
    _fake_resolve(monkeypatch, [{
        "course_id": "c-cs-5800", "primary_code": "CS 5800",
        "primary_name": "Algorithms",
    }])
    st = _FakeSt(course="CS-5800")
    apply_deep_link(st, pages=PAGES)

    # User navigates away; the URL still says ?course=CS-5800.
    st.session_state["selected_course_id"] = "c-ds-5220"
    st.session_state["nav_page"] = "PAGE_COOP"
    apply_deep_link(st, pages=PAGES)

    assert st.session_state["selected_course_id"] == "c-ds-5220"
    assert st.session_state["nav_page"] == "PAGE_COOP"


def test_unresolvable_course_ref_warns_and_settles(monkeypatch) -> None:
    _fake_resolve(monkeypatch, [])
    st = _FakeSt(course="CS-9999")
    apply_deep_link(st, pages=PAGES)

    assert "selected_course_id" not in st.session_state
    assert len(st.warnings) == 1
    assert "CS-9999" in st.warnings[0]
    # Settled: a dead link is a final answer, don't re-ask every rerun.
    assert st.session_state[APPLIED_FLAG] is True


def test_bad_ref_cannot_inject_markdown_into_the_warning(monkeypatch) -> None:
    """The ref is echoed inside a markdown code span in our own warning box.
    A backtick would close that span, letting a forged URL render a clickable
    link the user would reasonably trust — phishing through our chrome.
    Streamlit blocks raw HTML; the delimiter is the actual hole."""
    _fake_resolve(monkeypatch, [])
    st = _FakeSt(course="x`[点这里](https://evil.example)`")
    apply_deep_link(st, pages=PAGES)

    warned = st.warnings[0]
    assert "evil.example" in warned  # still shown, so the user sees the truth
    assert "`[点这里]" not in warned  # but never as escapable markdown
    assert warned.count("`") == 2  # exactly our own code-span delimiters


def test_ref_label_is_length_capped(monkeypatch) -> None:
    """A 200-char ref (the route's ceiling) must not blow up the warning box."""
    _fake_resolve(monkeypatch, [])
    st = _FakeSt(course="z" * 200)
    apply_deep_link(st, pages=PAGES)
    assert "z" * 65 not in st.warnings[0]


def test_ambiguous_course_ref_opens_first_and_says_so(monkeypatch) -> None:
    _fake_resolve(monkeypatch, [
        {"course_id": "c-cs-5800", "primary_code": "CS 5800",
         "primary_name": "Algorithms"},
        {"course_id": "c-ds-5220", "primary_code": "DS 5220",
         "primary_name": "Supervised ML"},
    ])
    st = _FakeSt(course="ml")
    apply_deep_link(st, pages=PAGES)

    assert st.session_state["selected_course_id"] == "c-cs-5800"
    assert len(st.infos) == 1
    assert "DS 5220" in st.infos[0]


def test_transient_api_failure_does_not_burn_the_one_shot(monkeypatch) -> None:
    """A warming API must not permanently eat the deep link — the ref has to
    survive to the next rerun (same rule as program_view's uncached failures)."""
    from app.api_client import ApiError  # noqa: PLC0415

    _fake_resolve(monkeypatch, ApiError(503, "API unreachable: ConnectError"))
    st = _FakeSt(course="CS-5800")
    apply_deep_link(st, pages=PAGES)

    assert st.session_state.get(APPLIED_FLAG) is None
    assert len(st.warnings) == 1

    # API comes back on the next rerun.
    _fake_resolve(monkeypatch, [{
        "course_id": "c-cs-5800", "primary_code": "CS 5800",
        "primary_name": "Algorithms",
    }])
    apply_deep_link(st, pages=PAGES)
    assert st.session_state["selected_course_id"] == "c-cs-5800"


# === Program refs ===


def test_program_ref_opens_curriculum() -> None:
    st = _FakeSt(program="cs-ms")
    st.session_state["_programs_cache"] = PROGRAMS  # skips the API hop
    apply_deep_link(st, pages=PAGES)

    assert st.session_state["selected_program_id"] == "cs-ms"
    assert st.session_state["nav_page"] == "PAGE_PROGRAMS"


def test_unknown_program_ref_warns_and_stays_on_list() -> None:
    st = _FakeSt(program="cs-phd")
    st.session_state["_programs_cache"] = PROGRAMS
    apply_deep_link(st, pages=PAGES)

    assert "selected_program_id" not in st.session_state
    assert len(st.warnings) == 1


def test_both_params_course_wins_the_landing_page(monkeypatch) -> None:
    """Legal combination: the program is teed up for later, the more
    specific course decides where the user actually lands."""
    _fake_resolve(monkeypatch, [{
        "course_id": "c-cs-5800", "primary_code": "CS 5800",
        "primary_name": "Algorithms",
    }])
    st = _FakeSt(course="CS-5800", program="cs-ms")
    st.session_state["_programs_cache"] = PROGRAMS
    apply_deep_link(st, pages=PAGES)

    assert st.session_state["selected_program_id"] == "cs-ms"
    assert st.session_state["selected_course_id"] == "c-cs-5800"
    assert st.session_state["nav_page"] == "PAGE_SEARCH"


# ===========================================================================
# Produce -> consume round trip (the actual product loop)
# ===========================================================================


def test_share_ref_of_every_seeded_course_resolves_back(
    api_client: TestClient, empty_db: sqlite3.Connection,
) -> None:
    """The link the UI hands a student must be one the app can open again.
    Builds the share ref from each course's real primary_code and pushes it
    through the live /resolve/course route."""
    from db.repository import CourseRepository  # noqa: PLC0415

    courses = CourseRepository(empty_db).list_by_status("indexed")
    assert courses, "seed produced no indexed courses"

    for course in courses:
        ref = course_share_ref(course.primary_code)
        url = share_url("https://compass.neu-compass.me", course=ref)
        assert f"?course={ref}" in url

        r = api_client.get("/resolve/course", params={"ref": ref})
        assert r.status_code == 200, r.text
        ids = [m["course_id"] for m in r.json()["matches"]]
        assert course.course_id in ids, f"{ref!r} lost {course.course_id!r}"
