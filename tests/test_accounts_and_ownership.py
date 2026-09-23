"""
Accounts, and research that belongs to one person.

Until 2026-09-21 a single shared token opened everything: whoever had it could
read, run, export and delete every session on the server. Nothing else a
hosted product needs — a plan, a quota, a bill, someone's API key — means
anything until "whose is this?" has an answer.

Local single-user use must keep working with no accounts at all.
"""
import pytest
from fastapi.testclient import TestClient

import config
from memory import accounts
from memory.note_db import NoteDB


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "EXPERIMENTS_DIR", tmp_path / "experiments")
    monkeypatch.setattr(config, "UI_TOKEN", "")
    monkeypatch.setattr(config, "ALLOW_SIGNUP", True)

    import ui.app as ui_app
    ui_app._runners.clear()
    ui_app._LOGIN_ATTEMPTS.clear()

    class _NoRunner:                       # no test may start a real pipeline
        def __init__(self, **kwargs): self.waiting_step = None
        def start(self): pass
        def is_alive(self): return False
        def stop(self): pass

    monkeypatch.setattr(ui_app, "SessionRunner", _NoRunner)
    monkeypatch.setattr(ui_app, "_start_runner", lambda sid, db, only=None: True)
    return TestClient(ui_app.app)


def _signup(client, email, password="a-good-password"):
    return client.post("/api/auth/signup", json={"email": email, "password": password})


def _new_session(client, topic):
    return client.post("/api/sessions", json={"topic": topic, "autostart": False}).json()["session_id"]


# --- the local mode must not change ----------------------------------------------

def test_with_no_accounts_the_server_works_as_before(client):
    assert client.get("/api/auth/me").json() == {"accounts": False, "signup_open": True, "user": None}
    sid = _new_session(client, "local work")
    assert client.get("/api/sessions").json()["sessions"][0]["session_id"] == sid
    assert client.get(f"/api/sessions/{sid}").status_code == 200


# --- accounts ----------------------------------------------------------------------

def test_the_first_account_owns_the_research_that_was_already_here(client):
    legacy = _new_session(client, "work from before accounts")
    assert NoteDB().session_owner(legacy) == ""

    r = _signup(client, "first@example.com")
    assert r.status_code == 200
    user = r.json()["user"]
    assert user["role"] == "owner" and user["plan"] == "free"
    assert NoteDB().session_owner(legacy) == user["user_id"]
    assert client.get("/api/auth/me").json()["user"]["email"] == "first@example.com"


def test_a_weak_password_or_bad_email_is_refused(client):
    assert _signup(client, "not-an-email").status_code == 400
    assert _signup(client, "a@example.com", "short").status_code == 400
    assert accounts.count_users() == 0


def test_the_same_email_cannot_sign_up_twice(client):
    assert _signup(client, "one@example.com").status_code == 200
    again = _signup(client, "one@example.com")
    assert again.status_code == 400 and "already" in again.json()["detail"]


def test_signing_in_and_out(client):
    _signup(client, "me@example.com")
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").json()["user"] is None
    assert client.get("/api/sessions").status_code == 401       # accounts exist now

    assert client.post("/api/auth/login",
                       json={"email": "me@example.com", "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login",
                       json={"email": "me@example.com", "password": "a-good-password"}).status_code == 200
    assert client.get("/api/sessions").status_code == 200


def test_a_private_server_stops_taking_new_accounts(client, monkeypatch):
    _signup(client, "owner@example.com")
    monkeypatch.setattr(config, "ALLOW_SIGNUP", False)
    refused = _signup(client, "stranger@example.com")
    assert refused.status_code == 403
    assert accounts.count_users() == 1


# --- the part that must not be wrong -------------------------------------------------

def test_one_account_cannot_reach_another_accounts_research(client):
    _signup(client, "alice@example.com")
    alice_session = _new_session(client, "alice's study")
    client.post("/api/auth/logout")

    _signup(client, "bob@example.com")
    bob_session = _new_session(client, "bob's study")

    # Bob sees only his own, and Alice's is "not found" rather than "forbidden":
    # whether it exists at all is her business.
    listed = [s["session_id"] for s in client.get("/api/sessions").json()["sessions"]]
    assert listed == [bob_session]
    assert client.get(f"/api/sessions/{alice_session}").status_code == 404
    assert client.get(f"/api/sessions/{alice_session}/export").status_code == 404
    assert client.post(f"/api/sessions/{alice_session}/stop").status_code == 404
    assert client.delete(f"/api/sessions/{alice_session}").status_code == 404
    assert client.get(f"/api/sessions/{alice_session}/stages").status_code == 404
    assert client.post(f"/api/sessions/{alice_session}/run/papers").status_code == 404
    assert client.post(f"/api/sessions/{alice_session}/import/papers",
                       json={"text": "title\nx\n"}).status_code == 404

    # and Alice still has hers
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "alice@example.com", "password": "a-good-password"})
    assert client.get(f"/api/sessions/{alice_session}").status_code == 200
    assert NoteDB().session_owner(bob_session) != NoteDB().session_owner(alice_session)


def test_the_dashboard_counts_only_your_own_sessions(client):
    _signup(client, "alice@example.com")
    _new_session(client, "alice one")
    _new_session(client, "alice two")
    client.post("/api/auth/logout")
    _signup(client, "bob@example.com")
    _new_session(client, "bob one")

    assert client.get("/api/dashboard").json()["sessions"]["total"] == 1


def test_signed_out_requests_cannot_read_anything(client):
    _signup(client, "alice@example.com")
    sid = _new_session(client, "alice's study")
    client.post("/api/auth/logout")

    assert client.get("/api/sessions").status_code == 401
    assert client.get(f"/api/sessions/{sid}").status_code == 401
    assert client.get("/api/dashboard").status_code == 401
    assert client.get("/health").status_code == 200          # still fine to ask if it is alive


def test_a_tampered_cookie_is_not_a_way_in(client):
    _signup(client, "alice@example.com")
    sid = _new_session(client, "alice's study")
    user_id = client.get("/api/auth/me").json()["user"]["user_id"]
    client.post("/api/auth/logout")

    # the payload without a valid signature, and a signature that does not match
    client.cookies.set("ra_user", f"{user_id}.9999999999.deadbeef")
    assert client.get(f"/api/sessions/{sid}").status_code == 401
    client.cookies.clear()


def test_password_hashes_are_not_reversible_and_not_returned(client):
    _signup(client, "alice@example.com")
    body = client.get("/api/auth/me").text
    assert "a-good-password" not in body and "password" not in body

    import sqlite3
    conn = sqlite3.connect(config.SQLITE_PATH)
    stored = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    conn.close()
    assert stored.startswith("scrypt$") and "a-good-password" not in stored
    assert accounts.verify_password("alice@example.com", "a-good-password") is not None
    assert accounts.verify_password("alice@example.com", "nearly-right") is None
