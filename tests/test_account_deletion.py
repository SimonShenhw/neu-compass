"""Batch T, policy P4: a logged-in student deletes their account and their Co-op contributions.

Synthetic accounts, courses and Co-op rows in temporary databases only; no real login.
"""

import json
import sqlite3

import pytest

from db.account_deletion import AccountNotFound, delete_account

A, B = "synthetic-sub-a", "synthetic-sub-b"


def seed(conn):
    conn.execute("INSERT INTO courses (course_id, primary_code, primary_name, metadata, generated_json) "
                 "VALUES ('c-synthetic', 'CS 5999', 'Synthetic Course', '{}', '{}')")
    for user in (A, B):
        conn.execute("INSERT INTO users (user_id, email, domain, contribution_count) VALUES (?, ?, 'northeastern.edu', 1)",
                     (user, f"{user}@northeastern.edu"))
    for coop_id, user, status in [("s-a-pub", A, "published"), ("s-a-pending", A, "pending"), ("s-b-pub", B, "published")]:
        conn.execute("INSERT INTO coop_submissions (coop_id, contributor_user_id, submission_key, group_key, payload, "
                     "review_status) VALUES (?, ?, ?, 'synthetic-group', '{}', ?)", (coop_id, user, coop_id, status))
    for coop_id, user in [("s-a-pub", A), ("s-b-pub", B)]:
        conn.execute("INSERT INTO coop_experiences (coop_id, company, role, contributor_user_id) "
                     "VALUES (?, 'Synthetic Co', 'Synthetic Role', ?)", (coop_id, user))
        conn.execute("INSERT INTO coop_contribution_credits (user_id, group_key, coop_id) VALUES (?, 'synthetic-group', ?)",
                     (user, coop_id))
    conn.execute("INSERT INTO coop_experiences (coop_id, company, role, is_seed_data) VALUES ('seed-1', 'Seed Co', 'Seed', 1)")
    for user, coop_id in [(A, "seed-1"), (B, "s-a-pub"), (B, "seed-1")]:
        conn.execute("INSERT INTO user_unlocks (user_id, coop_id) VALUES (?, ?)", (user, coop_id))
    conn.execute("INSERT INTO user_courses (user_id, course_id, term) VALUES (?, 'c-synthetic', 'fall_2026')", (A,))
    conn.execute("INSERT INTO query_log (route, query) VALUES ('chat', 'synthetic question without an account')")
    conn.commit()


def table_counts(conn):
    tables = ["users", "user_unlocks", "user_courses", "coop_submissions", "coop_contribution_credits",
              "coop_experiences", "query_log"]
    return {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables}


def test_the_account_and_everything_it_contributed_go_and_nothing_else(empty_db):
    seed(empty_db)
    before = table_counts(empty_db)
    counts = delete_account(empty_db, A)
    assert counts == {"published_experiences": 1, "unlocks_of_those": 1, "own_unlocks": 1, "submissions": 2,
                      "credits": 1, "planned_courses": 1, "withdrawn_from_groups": 1}
    after = table_counts(empty_db)
    # B's item was the group's other half: withdrawn (k=2), not deleted. 中文：B 那份是同组的另一半：撤回，不删。
    assert after == {"users": before["users"] - 1, "user_unlocks": before["user_unlocks"] - 2,
                     "user_courses": before["user_courses"] - 1, "coop_submissions": before["coop_submissions"] - 2,
                     "coop_contribution_credits": before["coop_contribution_credits"] - 1,
                     "coop_experiences": before["coop_experiences"] - 2, "query_log": before["query_log"]}
    for table, column in [("users", "user_id"), ("user_unlocks", "user_id"), ("user_courses", "user_id"),
                          ("coop_submissions", "contributor_user_id"), ("coop_contribution_credits", "user_id"),
                          ("coop_experiences", "contributor_user_id")]:
        assert empty_db.execute(f"SELECT count(*) FROM {table} WHERE {column} = ?", (A,)).fetchone()[0] == 0
    assert [row[0] for row in empty_db.execute("SELECT coop_id FROM coop_experiences ORDER BY coop_id")] == ["seed-1"]
    assert empty_db.execute("SELECT review_status FROM coop_submissions WHERE coop_id = 's-b-pub'").fetchone()[0] == "approved"
    assert [row[0] for row in empty_db.execute("SELECT coop_id FROM user_unlocks WHERE user_id = ?", (B,))] == ["seed-1"]
    assert empty_db.execute("SELECT count(*) FROM coop_contribution_credits WHERE user_id = ?", (B,)).fetchone()[0] == 1
    assert empty_db.execute("SELECT contribution_count FROM users WHERE user_id = ?", (B,)).fetchone()[0] == 1


def test_no_unlock_is_left_pointing_at_a_withdrawn_or_deleted_experience(empty_db):
    seed(empty_db)
    empty_db.execute("INSERT INTO users (user_id, email, domain) VALUES "
                     "('synthetic-sub-c', 'synthetic-sub-c@northeastern.edu', 'northeastern.edu')")
    empty_db.execute("INSERT INTO user_unlocks (user_id, coop_id) VALUES ('synthetic-sub-c', 's-b-pub')")
    empty_db.commit()
    delete_account(empty_db, A)
    assert empty_db.execute("SELECT count(*) FROM user_unlocks WHERE coop_id NOT IN "
                            "(SELECT coop_id FROM coop_experiences)").fetchone()[0] == 0
    assert [tuple(row) for row in empty_db.execute("SELECT user_id, coop_id FROM user_unlocks")] == [(B, "seed-1")]


def test_an_unknown_account_changes_nothing(empty_db):
    seed(empty_db)
    before = table_counts(empty_db)
    with pytest.raises(AccountNotFound):
        delete_account(empty_db, "synthetic-sub-missing")
    assert table_counts(empty_db) == before and not empty_db.in_transaction


def test_a_failure_part_way_rolls_everything_back(empty_db):
    seed(empty_db)
    before = table_counts(empty_db)
    empty_db.execute("CREATE TEMP TRIGGER synthetic_block BEFORE DELETE ON users BEGIN SELECT RAISE(ABORT, 'blocked'); END")
    with pytest.raises(sqlite3.IntegrityError):
        delete_account(empty_db, A)
    assert table_counts(empty_db) == before and not empty_db.in_transaction


def test_it_refuses_without_foreign_keys_or_inside_a_transaction(empty_db):
    seed(empty_db)
    empty_db.execute("PRAGMA foreign_keys = OFF")
    with pytest.raises(RuntimeError, match="Foreign keys"):
        delete_account(empty_db, A)
    empty_db.execute("PRAGMA foreign_keys = ON")
    empty_db.execute("BEGIN")
    with pytest.raises(RuntimeError, match="transaction"):
        delete_account(empty_db, A)
    empty_db.rollback()
    with pytest.raises(ValueError):
        delete_account(empty_db, "")
    assert empty_db.execute("SELECT count(*) FROM users WHERE user_id = ?", (A,)).fetchone()[0] == 1


# === k=2 after a deletion (the user chose on 10-21: withdraw a group left with one contributor) ===


def submit(api_client, conn, user_id, payload):
    from app.session_tokens import issue_session_token

    conn.execute("INSERT INTO users(user_id, email, domain) VALUES(?, ?, 'husky.neu.edu')", (user_id, f"{user_id}@husky.neu.edu"))
    conn.commit()
    headers = {"Authorization": f"Bearer {issue_session_token(user_id, f'{user_id}@husky.neu.edu')}"}
    response = api_client.post("/coop", headers=headers, json=payload)
    assert response.status_code == 201
    return response.json()["coop_id"], headers


def approve(conn, coop_id):
    from db.coop_submission_repository import CoopSubmissionRepository
    from schemas.coop import CoopExperience

    repo = CoopSubmissionRepository(conn)
    repo.review(coop_id, approve=True, reviewer="synthetic curator", audit="synthetic audit",
                redacted=CoopExperience.model_validate_json(repo.get(coop_id)["payload"]))
    conn.commit()


PAYLOAD = {"company": "Synthetic Corp", "role": "Synthetic Analyst", "coop_term": "Summer 2026",
           "interview_summary": "Synthetic two rounds"}


def test_a_group_left_with_one_contributor_is_withdrawn_and_comes_back_with_a_new_one(api_client_unseeded, empty_db,
                                                                                         secret):
    first, first_headers = submit(api_client_unseeded, empty_db, "u-first", PAYLOAD)
    second, _ = submit(api_client_unseeded, empty_db, "u-second", PAYLOAD)
    approve(empty_db, first)
    approve(empty_db, second)
    assert len(api_client_unseeded.get("/coop").json()) == 2
    response = api_client_unseeded.post("/auth/delete-account", json={"confirm": "delete"}, headers=first_headers)
    assert response.status_code == 200 and response.json()["withdrawn_from_groups"] == 1
    assert api_client_unseeded.get("/coop").json() == []
    assert empty_db.execute("SELECT review_status FROM coop_submissions WHERE coop_id = ?", (second,)).fetchone()[0] == "approved"
    third, _ = submit(api_client_unseeded, empty_db, "u-third", PAYLOAD)
    approve(empty_db, third)
    assert sorted(row["coop_id"] for row in api_client_unseeded.get("/coop").json()) == sorted([second, third])
    counts = dict(empty_db.execute("SELECT user_id, contribution_count FROM users").fetchall())
    assert counts == {"u-second": 1, "u-third": 1}  # no second credit for the republished item


def test_a_group_that_still_has_two_contributors_stays_public(api_client_unseeded, empty_db, secret):
    ids = []
    for user in ("u-one", "u-two", "u-three"):
        coop_id, headers = submit(api_client_unseeded, empty_db, user, PAYLOAD)
        ids.append((coop_id, headers))
    for coop_id, _ in ids:
        approve(empty_db, coop_id)
    response = api_client_unseeded.post("/auth/delete-account", json={"confirm": "delete"}, headers=ids[0][1])
    assert response.json()["withdrawn_from_groups"] == 0
    assert sorted(row["coop_id"] for row in api_client_unseeded.get("/coop").json()) == sorted([ids[1][0], ids[2][0]])


# === The route ===


@pytest.fixture
def secret(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "session_secret", "synthetic-deletion-secret")


def token(user_id):
    from app.session_tokens import issue_session_token

    return issue_session_token(user_id, f"{user_id}@northeastern.edu")


def test_route_deletes_the_callers_account_and_then_the_token_is_refused(api_client, empty_db, secret):
    from structlog.testing import capture_logs

    seed(empty_db)
    headers = {"Authorization": f"Bearer {token(A)}"}
    assert api_client.get("/auth/me", headers=headers).status_code == 200
    with capture_logs() as logs:
        response = api_client.post("/auth/delete-account", json={"confirm": "delete"}, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"deleted": True, "published_experiences": 1, "unlocks_of_those": 1, "own_unlocks": 1,
                               "submissions": 2, "credits": 1, "planned_courses": 1, "withdrawn_from_groups": 1}
    assert api_client.get("/auth/me", headers=headers).status_code == 401
    assert api_client.post("/auth/delete-account", json={"confirm": "delete"}, headers=headers).status_code == 401
    events = [entry for entry in logs if entry["event"] == "account.deleted"]
    assert len(events) == 1 and A not in repr(events) and "northeastern" not in repr(events)
    assert {k: v for k, v in events[0].items() if k not in ("event", "log_level")} == {
        k: v for k, v in response.json().items() if k != "deleted"}
    assert empty_db.execute("SELECT count(*) FROM users WHERE user_id = ?", (B,)).fetchone()[0] == 1


@pytest.mark.parametrize("body", [{}, {"confirm": "yes"}, {"confirm": "delete", "user_id": B}, {"confirm": True}])
def test_route_needs_exactly_the_confirm_word(api_client, empty_db, secret, body):
    seed(empty_db)
    response = api_client.post("/auth/delete-account", json=body, headers={"Authorization": f"Bearer {token(A)}"})
    assert response.status_code == 422
    assert empty_db.execute("SELECT count(*) FROM users").fetchone()[0] == 2


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not-a-real-token"}])
def test_route_needs_a_valid_session(api_client, empty_db, secret, headers):
    seed(empty_db)
    response = api_client.post("/auth/delete-account", json={"confirm": "delete"}, headers=headers)
    assert response.status_code == 401
    assert empty_db.execute("SELECT count(*) FROM users").fetchone()[0] == 2


# === The page ===


def privacy_page(monkeypatch, status=200):
    """`status` is the delete call's HTTP status, or the name of an httpx exception the transport raises instead."""
    import httpx
    from streamlit.testing.v1 import AppTest

    import app.streamlit_auth_ui as auth
    from tests.page_layout_support import SCRIPT, install_backend, run

    real_sidebar = auth.render_auth_sidebar
    backend = install_backend(monkeypatch)
    monkeypatch.setattr(auth, "render_auth_sidebar", real_sidebar)
    original = type(backend).__call__
    deletions = []

    def transport(self, request):
        if request.url.path == "/auth/delete-account":
            deletions.append((request.method, request.headers.get("authorization"), request.content))
            if isinstance(status, str):
                raise getattr(httpx, status)("synthetic", request=request)
            body = {"deleted": True, "published_experiences": 0, "unlocks_of_those": 0, "own_unlocks": 0,
                    "submissions": 1, "credits": 0, "planned_courses": 0, "withdrawn_from_groups": 0} \
                if status == 200 else {"detail": "synthetic"}
            return httpx.Response(status, json=body)
        return original(self, request)

    monkeypatch.setattr(type(backend), "__call__", transport)
    app = AppTest.from_string(SCRIPT)
    app.session_state["nav_page"] = "🔒 数据与隐私 · Privacy"
    for key, value in {"session_token": "synthetic-token", "user_id": "synthetic-user",
                       "user_email": "synthetic@example.test", "oauth_state": "synthetic-oauth-state"}.items():
        app.session_state[key] = value
    return run(app), deletions, run


def test_page_delete_needs_the_tick_then_deletes_logs_out_and_says_so(monkeypatch):
    app, deletions, run = privacy_page(monkeypatch)
    button = app.button(key="delete-account")
    assert button.disabled and not deletions
    app.checkbox(key="delete-account-confirm").check()
    run(app)
    app.button(key="delete-account").click()
    run(app)
    assert [(method, auth, json.loads(body)) for method, auth, body in deletions] == [
        ("POST", "Bearer synthetic-token", {"confirm": "delete"})]
    assert app.session_state["user_id"] is None and app.session_state["session_token"] is None
    assert any("账号和 Co-op 投稿已经删除" in item.value for item in app.success)
    assert not [b for b in app.button if b.key == "delete-account"]
    assert ("clear", "nc_session", None, None) in app.session_state["_pending_cookie"]
    assert app.radio(key="nav_page").value.startswith("🔒")
    run(app)  # The message is shown once, not on every later run (B24). 中文：提示只显示一次。
    assert not any("账号和 Co-op 投稿已经删除" in item.value for item in app.success)


NOTHING_DELETED, NOT_KNOWN, EXPIRED = "删除没有完成，什么也没删", "不确定删除有没有完成", "这个登录已经失效"


@pytest.mark.parametrize(("status", "message"), [
    (500, NOTHING_DELETED), (429, NOTHING_DELETED),
    # No answer, or a gateway's (the client turns a timeout into 504 and a lost connection into 503): the server may
    # have committed, so the page must not say nothing was deleted (A24 L5). 中文：没收到回复时不能说什么也没删。
    (502, NOT_KNOWN), (503, NOT_KNOWN), (504, NOT_KNOWN), ("ReadTimeout", NOT_KNOWN), ("ConnectError", NOT_KNOWN),
    (401, EXPIRED)])
def test_page_delete_failure_says_what_is_known(monkeypatch, status, message):
    app, deletions, run = privacy_page(monkeypatch, status=status)
    app.checkbox(key="delete-account-confirm").check()
    run(app)
    app.button(key="delete-account").click()
    run(app)
    assert len(deletions) == 1
    assert (app.session_state["user_id"] is None) is (message == EXPIRED)
    # Only an expired login also drops the cookie; otherwise the student stays logged in to try again (B24).
    # 中文：只有登录失效时才清 cookie；别的情况保持登录，可以再试。
    pending = app.session_state["_pending_cookie"] if "_pending_cookie" in app.session_state else []
    assert (("clear", "nc_session", None, None) in pending) is (message == EXPIRED)
    errors = [item.value for item in app.error]
    assert any(message in value for value in errors) and "synthetic" not in "".join(errors)
    assert not any(other in value for value in errors for other in {NOTHING_DELETED, NOT_KNOWN, EXPIRED} - {message})


def test_guests_see_no_delete_controls(monkeypatch):
    from streamlit.testing.v1 import AppTest

    from tests.page_layout_support import SCRIPT, install_backend, run

    install_backend(monkeypatch)
    app = AppTest.from_string(SCRIPT)
    app.session_state["nav_page"] = "🔒 数据与隐私 · Privacy"
    run(app)
    assert not [b for b in app.button if b.key == "delete-account"] and not app.checkbox
