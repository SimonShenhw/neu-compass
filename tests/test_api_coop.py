"""Tests for api.routes.coop — POST upload (k-anonymity gated) + GET list (tiered).

The k-anonymity gate is the security boundary that PLAN §3.4 marks as a red
line. These tests pin down both the rejection path (would-be uniquely
identifying) and the acceptance path (combined-corpus ≥ k=2) — so a future
refactor can't silently drop the gate.
"""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from db.coop_repository import CoopRepository
from schemas.coop import CoopExperience


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
        headers={"X-User-Id": "u-test"},
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
        headers={"X-User-Id": "u-test"},
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
        headers={"X-User-Id": "u-test"},
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
        headers={"X-User-Id": "u-test"},
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
        headers={"X-User-Id": "u-test"},
    )
    assert r.status_code == 201
    assert r.json()["visibility_level"] == 1


# === GET /coop — visibility tier filtering ===


def test_get_coop_anonymous_sees_only_level_0(
    api_client_unseeded: TestClient, empty_db: sqlite3.Connection
) -> None:
    repo = CoopRepository(empty_db)
    repo.add(CoopExperience(
        coop_id="c0", company="Fidelity", role="Q", visibility_level=0,
        is_seed_data=True,
    ))
    repo.add(CoopExperience(
        coop_id="c1", company="Fidelity", role="Q", visibility_level=1,
        is_seed_data=True,
    ))
    repo.add(CoopExperience(
        coop_id="c2", company="Fidelity", role="Q", visibility_level=2,
        is_seed_data=True,
    ))
    empty_db.commit()

    r = api_client_unseeded.get("/coop")
    assert r.status_code == 200
    rows = r.json()
    assert {row["coop_id"] for row in rows} == {"c0"}


def test_get_coop_with_high_contributor_sees_all(
    api_client_unseeded: TestClient, empty_db: sqlite3.Connection
) -> None:
    _seed_user(empty_db, "u-high", contribution_count=2)
    repo = CoopRepository(empty_db)
    for cid, level in [("c0", 0), ("c1", 1), ("c2", 2)]:
        repo.add(CoopExperience(
            coop_id=cid, company="Fidelity", role="Q",
            visibility_level=level, is_seed_data=True,
        ))
    empty_db.commit()

    r = api_client_unseeded.get("/coop", headers={"X-User-Id": "u-high"})
    assert r.status_code == 200
    rows = r.json()
    assert {row["coop_id"] for row in rows} == {"c0", "c1", "c2"}


def test_get_coop_mid_contributor_sees_levels_0_and_1(
    api_client_unseeded: TestClient, empty_db: sqlite3.Connection
) -> None:
    _seed_user(empty_db, "u-mid", contribution_count=1)
    repo = CoopRepository(empty_db)
    for cid, level in [("c0", 0), ("c1", 1), ("c2", 2)]:
        repo.add(CoopExperience(
            coop_id=cid, company="Fidelity", role="Q",
            visibility_level=level, is_seed_data=True,
        ))
    empty_db.commit()

    r = api_client_unseeded.get("/coop", headers={"X-User-Id": "u-mid"})
    assert r.status_code == 200
    assert {row["coop_id"] for row in r.json()} == {"c0", "c1"}
