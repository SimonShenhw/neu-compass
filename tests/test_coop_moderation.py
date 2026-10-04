"""Co-op collection must not be confused with reviewed, anonymous publication."""

from __future__ import annotations

import pytest

from app.session_tokens import issue_session_token
from config import settings
from db.coop_repository import CoopRepository
from db.coop_submission_repository import CoopSubmissionRepository
from schemas.coop import CoopExperience


@pytest.fixture(autouse=True)
def session_secret(monkeypatch):
    monkeypatch.setattr(settings, "session_secret", "coop-moderation-test")


def seed_user(conn, user_id):
    conn.execute(
        "INSERT INTO users(user_id,email,domain) VALUES(?,?,?)",
        (user_id, f"{user_id}@husky.neu.edu", "husky.neu.edu"),
    )
    conn.commit()
    return {"Authorization": f"Bearer {issue_session_token(user_id, f'{user_id}@husky.neu.edu')}"}


def test_unique_upload_is_collected_privately(api_client_unseeded, empty_db):
    auth = seed_user(empty_db, "u-first")
    response = api_client_unseeded.post("/coop", headers=auth, json={
        "company": "Unique Corp", "role": "Data Engineer", "coop_term": "Spring 2026",
        "interview_summary": "Private until reviewed",
    })
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert response.json()["contribution_credited"] is False
    assert response.json()["contribution_count"] == 0
    assert api_client_unseeded.get("/coop", headers=auth).json() == []
    assert CoopRepository(empty_db).list_all() == []


def test_seed_row_cannot_make_an_upload_public(api_client_unseeded, empty_db):
    auth = seed_user(empty_db, "u-first")
    repo = CoopRepository(empty_db)
    repo.add(CoopExperience(coop_id="seed", company="Fidelity", role="Quant Dev", is_seed_data=True))
    empty_db.commit()
    response = api_client_unseeded.post("/coop", headers=auth, json={
        "company": "Fidelity", "role": "Quant Dev", "salary_range_usd": "$30-35/hr",
    })
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert [row["coop_id"] for row in api_client_unseeded.get("/coop").json()] == ["seed"]


def test_retries_and_content_edits_do_not_reward_twice(api_client_unseeded, empty_db):
    auth = seed_user(empty_db, "u-first")
    payload = {"company": "Fidelity", "role": "Quant Dev", "coop_term": "Summer 2025"}
    first = api_client_unseeded.post("/coop", headers=auth, json=payload)
    second = api_client_unseeded.post("/coop", headers=auth, json={
        **payload, "company": "  FIDELITY  ", "interview_summary": "Edited content",
    })
    assert first.status_code == second.status_code == 201
    assert first.json()["coop_id"] == second.json()["coop_id"]
    assert second.json()["duplicate"] is True
    assert second.json()["contribution_count"] == 0
    assert api_client_unseeded.get("/coop", headers=auth).json() == []


def test_legacy_unreviewed_ugc_is_not_public(api_client_unseeded, empty_db):
    repo = CoopRepository(empty_db)
    repo.add(CoopExperience(coop_id="legacy", company="Unique Corp", role="Private role"))
    empty_db.commit()
    assert api_client_unseeded.get("/coop").json() == []


def test_reviewed_publication_retries_and_field_redaction(api_client_unseeded, empty_db):
    auth1 = seed_user(empty_db, "u1")
    auth2 = seed_user(empty_db, "u2")
    payload = {"company": "Fidelity", "role": "Quant Dev", "coop_term": "Summer 2025",
               "interview_summary": "Two rounds", "salary_range_usd": "$30-35/hr"}
    ids = [api_client_unseeded.post("/coop", headers=auth, json=payload).json()["coop_id"] for auth in (auth1, auth2)]
    repo = CoopSubmissionRepository(empty_db)
    for cid in ids:
        sanitized = CoopExperience.model_validate_json(repo.get(cid)["payload"])
        repo.review(cid, approve=True, reviewer="curator", audit="PII and bucket reviewed", redacted=sanitized)
    empty_db.commit()
    guest = api_client_unseeded.get("/coop").json()
    member = api_client_unseeded.get("/coop", headers=auth1).json()
    assert len(guest) == len(member) == 2
    assert all(row["interview_summary"] is None and row["salary_range_usd"] is None for row in guest)
    assert all(row["interview_summary"] == "Two rounds" and row["salary_range_usd"] is None for row in member)
    assert all("contributor_user_id" not in row and "redaction_audit" not in row for row in member)
    retry = api_client_unseeded.post("/coop", headers=auth1, json=payload).json()
    assert retry["status"] == "published"
    assert retry["duplicate"] is True
    assert retry["contribution_credited"] is True
    assert retry["contribution_count"] == 1


@pytest.mark.parametrize("field", ["company", "role"])
def test_blank_identity_fields_are_not_collected(api_client_unseeded, empty_db, field):
    auth = seed_user(empty_db, "u1")
    payload = {"company": "Fidelity", "role": "Quant Dev", field: "   "}
    assert api_client_unseeded.post("/coop", headers=auth, json=payload).status_code == 422
    assert empty_db.execute("SELECT COUNT(*) FROM coop_submissions").fetchone()[0] == 0


def test_moderation_state_cannot_be_set_by_client(api_client_unseeded, empty_db):
    auth = seed_user(empty_db, "u1")
    response = api_client_unseeded.post("/coop", headers=auth, json={
        "company": "Fidelity", "role": "Quant Dev", "status": "published", "is_seed_data": True,
    })
    assert response.status_code == 422


def _drop_moderation_schema(conn):
    conn.execute("DROP TABLE coop_contribution_credits")
    conn.execute("DROP TABLE coop_submissions")
    conn.commit()


def test_missing_moderation_schema_upload_fails_closed(api_client_unseeded, empty_db):
    auth = seed_user(empty_db, "u1")
    _drop_moderation_schema(empty_db)
    response = api_client_unseeded.post(
        "/coop", headers=auth, json={"company": "Fidelity", "role": "Quant Dev"},
    )
    assert response.status_code == 503
    assert "migration" in response.json()["detail"]


def test_missing_moderation_schema_list_degrades_to_seeds(api_client_unseeded, empty_db):
    """Deploy-before-migrate used to 503 the whole public Co-op page. Reading
    must not depend on the private write queue: seeds stay browsable, legacy
    unreviewed UGC stays hidden, and the header carries the migration state."""
    repo = CoopRepository(empty_db)
    seed_user(empty_db, "u-legacy")
    repo.add(CoopExperience(coop_id="seed-1", company="State Street", role="Quant Dev", is_seed_data=True))
    repo.add(CoopExperience(coop_id="legacy-ugc", company="Acme", role="Analyst",
                            contributor_user_id="u-legacy", is_seed_data=False))
    _drop_moderation_schema(empty_db)
    response = api_client_unseeded.get("/coop")
    assert response.status_code == 200
    assert [row["coop_id"] for row in response.json()] == ["seed-1"]
    assert response.headers["x-coop-moderation"] == "missing"


def test_list_reports_available_moderation_schema(api_client_unseeded):
    response = api_client_unseeded.get("/coop")
    assert response.status_code == 200
    assert response.headers["x-coop-moderation"] == "available"


def test_private_queue_has_no_public_endpoint(api_client_unseeded):
    assert api_client_unseeded.get("/coop/pending").status_code == 404


def test_salary_text_is_bounded(api_client_unseeded, empty_db):
    auth = seed_user(empty_db, "u1")
    response = api_client_unseeded.post("/coop", headers=auth, json={
        "company": "Fidelity", "role": "Quant Dev", "salary_range_usd": "x" * 10_001,
    })
    assert response.status_code == 422
