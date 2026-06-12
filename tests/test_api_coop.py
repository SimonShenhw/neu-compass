"""Tests for api.routes.coop — POST upload (k-anonymity gated) + GET list (tiered).

The k-anonymity gate is the security boundary that PLAN §3.4 marks as a red
line. These tests pin down both the rejection path (would-be uniquely
identifying) and the acceptance path (combined-corpus ≥ k=2) — so a future
refactor can't silently drop the gate.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.session_tokens import issue_session_token
from config import settings
from db.coop_repository import CoopRepository
from schemas.coop import CoopExperience


@pytest.fixture(autouse=True)
def _session_secret(monkeypatch):
    """ADR-0021: coop routes authenticate via signed Bearer tokens; tests
    mint real ones against a test secret (settings is a module singleton —
    monkeypatch the attribute, never re-instantiate)."""
    monkeypatch.setattr(settings, "session_secret", "test-secret-coop")


def _auth(user_id: str) -> dict[str, str]:
    token = issue_session_token(user_id, f"{user_id}@husky.neu.edu")
    assert token is not None
    return {"Authorization": f"Bearer {token}"}


# === helpers ===


def _seed_user(conn: sqlite3.Connection, user_id: str, contribution_count: int) -> None:
    """Insert a user row directly — no UserRepository in this codebase yet."""
    conn.execute(
        "INSERT INTO users (user_id, email, domain, contribution_count) "
        "VALUES (?, ?, ?, ?)",
        (
            user_id,
            f"{user_id}@husky.neu.edu",
            "husky.neu.edu",
            contribution_count,
        ),
    )
    conn.commit()


# === POST /coop — auth ===


def test_post_coop_without_user_id_returns_401(api_client: TestClient) -> None:
    r = api_client.post(
        "/coop",
        json={"company": "Fidelity", "role": "Quant Dev", "coop_term": "Summer 2025"},
    )
    assert r.status_code == 401


# === POST /coop — k-anonymity ===


def test_post_coop_first_unique_triple_rejected(
    api_client: TestClient, empty_db: sqlite3.Connection
) -> None:
    """No prior matching row → combined corpus has 1 → uniquely identifying → 422."""
    _seed_user(empty_db, "u-test", contribution_count=0)
    r = api_client.post(
        "/coop",
        json={
            "company": "Acme Quant Boutique",
            "role": "Director of Quant Research",
            "coop_term": "Spring 2026",
        },
        headers=_auth("u-test"),
    )
    assert r.status_code == 422
    detail = r.json()["detail"].lower()
    assert "uniquely identifying" in detail


def test_post_coop_second_match_accepted(
    api_client: TestClient, empty_db: sqlite3.Connection
) -> None:
    """One prior matching row exists → new submission makes combined=2 ≥ k=2 → 201."""
    _seed_user(empty_db, "u-test", contribution_count=0)
    repo = CoopRepository(empty_db)
    repo.add(
        CoopExperience(
            coop_id="seed-1",
            company="Fidelity",
            role="Quant Dev",
            coop_term="Summer 2025",
            is_seed_data=True,
        )
    )
    empty_db.commit()

    r = api_client.post(
        "/coop",
        json={
            "company": "Fidelity",
            "role": "Quant Dev",
            "coop_term": "Summer 2025",
        },
        headers=_auth("u-test"),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["accepted"] is True
    assert body["coop_id"].startswith("coop-")
    # No interview / salary content → preview tier
    assert body["visibility_level"] == 0


# === POST /coop — give-to-get contribution credit (PLAN §6.4) ===


def test_post_coop_accepted_increments_contribution_count(
    api_client: TestClient, empty_db: sqlite3.Connection
) -> None:
    """Accepted upload must credit the contributor — without this the
    give-to-get gate can never unlock higher visibility tiers."""
    _seed_user(empty_db, "u-test", contribution_count=0)
    repo = CoopRepository(empty_db)
    repo.add(
        CoopExperience(
            coop_id="seed-1",
            company="Fidelity",
            role="Quant Dev",
            coop_term="Summer 2025",
            is_seed_data=True,
        )
    )
    empty_db.commit()

    r = api_client.post(
        "/coop",
        json={"company": "Fidelity", "role": "Quant Dev", "coop_term": "Summer 2025"},
        headers=_auth("u-test"),
    )
    assert r.status_code == 201
    row = empty_db.execute(
        "SELECT contribution_count FROM users WHERE user_id = ?", ("u-test",)
    ).fetchone()
    assert row["contribution_count"] == 1


# === POST /coop — visibility tier derivation ===


def test_post_coop_salary_sets_premium_tier(
    api_client: TestClient, empty_db: sqlite3.Connection
) -> None:
    """salary_range_usd present → visibility_level = 2 (server-derived,
    not client-chosen)."""
    _seed_user(empty_db, "u-test", contribution_count=0)
    repo = CoopRepository(empty_db)
    repo.add(
        CoopExperience(
            coop_id="seed-1", company="Fidelity", role="Quant Dev",
            coop_term="Summer 2025", is_seed_data=True,
        )
    )
    empty_db.commit()

    r = api_client.post(
        "/coop",
        json={
            "company": "Fidelity",
            "role": "Quant Dev",
            "coop_term": "Summer 2025",
            "salary_range_usd": "$30-35/hr",
        },
        headers=_auth("u-test"),
    )
    assert r.status_code == 201
    assert r.json()["visibility_level"] == 2


def test_post_coop_interview_only_sets_detail_tier(
    api_client: TestClient, empty_db: sqlite3.Connection
) -> None:
    _seed_user(empty_db, "u-test", contribution_count=0)
    repo = CoopRepository(empty_db)
    repo.add(
        CoopExperience(
            coop_id="seed-1", company="Fidelity", role="Quant Dev",
            coop_term="Summer 2025", is_seed_data=True,
        )
    )
    empty_db.commit()

    r = api_client.post(
        "/coop",
        json={
            "company": "Fidelity",
            "role": "Quant Dev",
            "coop_term": "Summer 2025",
            "interview_summary": "Two rounds. Behavioral + system design.",
        },
        headers=_auth("u-test"),
    )
    assert r.status_code == 201
    assert r.json()["visibility_level"] == 1


# === GET /coop — give-to-get FIELD-level redaction ===
#
# Contract change (2026-06 review sweep): every row is listed for every
# caller; tier-gated FIELDS are redacted server-side instead of hiding
# whole rows. Row-level filtering starved the marketplace — all seed rows
# carry salary (level 2), so anonymous/fresh users saw an EMPTY list and
# the give-to-get loop could never bootstrap.


def _seed_tiered_rows(conn: sqlite3.Connection) -> None:
    """c0=preview, c1=detail (interview), c2=premium (salary+interview)."""
    repo = CoopRepository(conn)
    repo.add(CoopExperience(
        coop_id="c0", company="Fidelity", role="Q", visibility_level=0,
        is_seed_data=True,
    ))
    repo.add(CoopExperience(
        coop_id="c1", company="Fidelity", role="Q", visibility_level=1,
        interview_summary="3 rounds, leetcode medium",
        is_seed_data=True,
    ))
    repo.add(CoopExperience(
        coop_id="c2", company="Fidelity", role="Q", visibility_level=2,
        interview_summary="2 rounds", salary_range_usd="$40-45/hr",
        is_seed_data=True,
    ))
    conn.commit()


def test_get_coop_anonymous_sees_all_rows_fields_redacted(
    api_client_unseeded: TestClient, empty_db: sqlite3.Connection
) -> None:
    _seed_tiered_rows(empty_db)

    r = api_client_unseeded.get("/coop")
    assert r.status_code == 200
    rows = {row["coop_id"]: row for row in r.json()}
    # Every row visible — that's the bootstrap fix
    assert set(rows) == {"c0", "c1", "c2"}
    # ...but tier-gated fields are stripped server-side
    assert rows["c1"]["interview_summary"] is None
    assert rows["c2"]["interview_summary"] is None
    assert rows["c2"]["salary_range_usd"] is None
    # visibility_level still reports the row's intrinsic tier (drives the
    # UI's "contribute to unlock" hints)
    assert rows["c2"]["visibility_level"] == 2
    # level-0 fields always present
    assert rows["c2"]["company"] == "Fidelity"


def test_get_coop_high_contributor_sees_all_fields(
    api_client_unseeded: TestClient, empty_db: sqlite3.Connection
) -> None:
    _seed_user(empty_db, "u-high", contribution_count=2)
    _seed_tiered_rows(empty_db)

    r = api_client_unseeded.get("/coop", headers=_auth("u-high"))
    assert r.status_code == 200
    rows = {row["coop_id"]: row for row in r.json()}
    assert set(rows) == {"c0", "c1", "c2"}
    assert rows["c1"]["interview_summary"] == "3 rounds, leetcode medium"
    assert rows["c2"]["salary_range_usd"] == "$40-45/hr"


def test_get_coop_mid_contributor_gets_detail_not_salary(
    api_client_unseeded: TestClient, empty_db: sqlite3.Connection
) -> None:
    _seed_user(empty_db, "u-mid", contribution_count=1)
    _seed_tiered_rows(empty_db)

    r = api_client_unseeded.get("/coop", headers=_auth("u-mid"))
    assert r.status_code == 200
    rows = {row["coop_id"]: row for row in r.json()}
    assert set(rows) == {"c0", "c1", "c2"}
    # tier 1 unlocks interview fields...
    assert rows["c1"]["interview_summary"] == "3 rounds, leetcode medium"
    assert rows["c2"]["interview_summary"] == "2 rounds"
    # ...but NOT salary
    assert rows["c2"]["salary_range_usd"] is None


def test_post_coop_valid_token_deleted_user_401(
    api_client_unseeded: TestClient, empty_db: sqlite3.Connection
) -> None:
    """A signed token can outlive its user row — must 401 like /auth/me,
    not 500 on the contributor FK."""
    r = api_client_unseeded.post(
        "/coop",
        json={"company": "X Corp", "role": "Dev"},
        headers=_auth("u-ghost-deleted"),
    )
    assert r.status_code == 401
    assert "unknown user" in r.json()["detail"].lower()
