"""Tests for api.routes.resolve — GET /resolve/course.

Seed (conftest.seed_minimal_corpus): c-aai-6600 / c-cs-5800 / c-ds-5220
plus one approved slang alias 'Algo' -> c-cs-5800.
"""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from db.query_log_repository import QueryLogRepository


def _matches(client: TestClient, ref: str) -> list[dict]:
    r = client.get("/resolve/course", params={"ref": ref})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ref"] == ref
    return body["matches"]


# === Canonical code, in every spelling a URL produces ===


def test_resolve_dashed_code(api_client: TestClient) -> None:
    """The headline case: ?course=CS-5800 out of a shared link."""
    assert _matches(api_client, "CS-5800") == [{
        "course_id": "c-cs-5800",
        "primary_code": "CS 5800",
        "primary_name": "Algorithms",
    }]


def test_resolve_separator_variants_agree(api_client: TestClient) -> None:
    """Underscore, plus (form-encoded space), real space, and the space-free
    spelling all have to land on the same course as the dashed form."""
    expected = _matches(api_client, "CS-5800")
    for ref in ["CS_5800", "CS+5800", "CS 5800", "cs5800", "cs-5800"]:
        assert _matches(api_client, ref) == expected, f"diverged for {ref!r}"


def test_resolve_raw_internal_id(api_client: TestClient) -> None:
    """An id copied out of an API response or a log stays a valid ref —
    the alias tier alone can't do this (ids aren't in v_course_lookup)."""
    assert _matches(api_client, "c-cs-5800")[0]["course_id"] == "c-cs-5800"


def test_resolve_approved_slang_alias(api_client: TestClient) -> None:
    assert _matches(api_client, "Algo")[0]["course_id"] == "c-cs-5800"


# === Non-matches are 200 + empty, never 404 ===


def test_resolve_unknown_ref_is_empty_not_404(api_client: TestClient) -> None:
    """A dead link must not look like an API failure — the UI renders
    ApiError as 'the backend is down', which would be a lie here."""
    r = api_client.get("/resolve/course", params={"ref": "CS-9999"})
    assert r.status_code == 200
    assert r.json()["matches"] == []


def test_resolve_long_but_legal_ref_is_empty_not_422(
    api_client: TestClient,
) -> None:
    """Between the resolver's 64-char cap and the route's 200-char cap the
    answer is 'no match' — that's a truncated link, not abuse."""
    r = api_client.get("/resolve/course", params={"ref": "CS-5800" + "x" * 80})
    assert r.status_code == 200
    assert r.json()["matches"] == []


# === Request validation ===


def test_resolve_missing_ref_is_422(api_client: TestClient) -> None:
    assert api_client.get("/resolve/course").status_code == 422


def test_resolve_empty_ref_is_422(api_client: TestClient) -> None:
    assert api_client.get(
        "/resolve/course", params={"ref": ""},
    ).status_code == 422


def test_resolve_absurd_ref_is_422(api_client: TestClient) -> None:
    r = api_client.get("/resolve/course", params={"ref": "x" * 500})
    assert r.status_code == 422


# === Telemetry boundary ===


def test_resolve_does_not_write_query_log(
    api_client: TestClient, empty_db: sqlite3.Connection,
) -> None:
    """The whole reason this route exists instead of reusing /search:
    deep-link resolution is machine traffic. One row here would contaminate
    the organic-query signal the distribution push is meant to collect.

    Paired with a real /search call so the assertion can't pass just
    because logging is broken in the fixture."""
    api_client.get("/resolve/course", params={"ref": "CS-5800"})
    api_client.get("/resolve/course", params={"ref": "Algo"})
    api_client.get("/resolve/course", params={"ref": "CS-9999"})
    assert QueryLogRepository(empty_db).count() == 0

    api_client.post("/search", json={"query": "CS 5800", "k": 3})
    assert QueryLogRepository(empty_db).count() == 1


# === Contract with the UI's next call ===


def test_every_match_is_fetchable_via_course_route(
    api_client: TestClient,
) -> None:
    """The UI's next move after resolving is GET /course/{course_id}. Any
    id this route returns must survive that hop — otherwise a deep link
    turns into a detail panel showing an API error."""
    for ref in ["CS-5800", "cs5800", "Algo", "c-aai-6600", "DS-5220"]:
        for m in _matches(api_client, ref):
            r = api_client.get(f"/course/{m['course_id']}")
            assert r.status_code == 200, f"{ref!r} -> {m['course_id']!r}"
            assert r.json()["primary_code"] == m["primary_code"]


def test_resolve_ignores_alias_pointing_at_deleted_course(
    api_client: TestClient, empty_db: sqlite3.Connection,
) -> None:
    """A dangling alias row (course deleted, alias left behind) resolves to
    nothing rather than to a hollow match. v_course_lookup's INNER JOIN is
    what enforces this; the test pins that the route inherits it."""
    from db.alias_repository import AliasRepository  # noqa: PLC0415
    from schemas.alias import (  # noqa: PLC0415
        Alias,
        AliasReviewStatus,
        AliasSource,
        AliasType,
    )

    empty_db.commit()  # PRAGMA foreign_keys is a no-op inside a transaction
    empty_db.execute("PRAGMA foreign_keys = OFF")
    AliasRepository(empty_db).add(Alias(
        alias_text="ghostcourse", alias_type=AliasType.SLANG,
        primary_course_id="c-ghost-9999",
        source=AliasSource.MANUAL,
        review_status=AliasReviewStatus.APPROVED,
    ))
    empty_db.commit()
    empty_db.execute("PRAGMA foreign_keys = ON")

    assert _matches(api_client, "ghostcourse") == []


def test_resolve_pending_alias_does_not_leak(
    api_client: TestClient, empty_db: sqlite3.Connection,
) -> None:
    """A shared link must not be a side door around alias review (ADR §3.2)."""
    from db.alias_repository import AliasRepository  # noqa: PLC0415
    from schemas.alias import (  # noqa: PLC0415
        Alias,
        AliasReviewStatus,
        AliasSource,
        AliasType,
    )

    AliasRepository(empty_db).add(Alias(
        alias_text="unreviewed-guess", alias_type=AliasType.SLANG,
        primary_course_id="c-cs-5800",
        source=AliasSource.LLM_INFERRED,
        review_status=AliasReviewStatus.PENDING,
    ))
    empty_db.commit()

    assert _matches(api_client, "unreviewed-guess") == []
