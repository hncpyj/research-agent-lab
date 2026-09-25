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
from memory import account_email, accounts
from memory.note_db import NoteDB

_REAL_SEND_PASSWORD_RESET = account_email.send_password_reset


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "EXPERIMENTS_DIR", tmp_path / "experiments")
    monkeypatch.setattr(config, "UI_TOKEN", "")
    monkeypatch.setattr(config, "ALLOW_SIGNUP", True)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(config, "SMTP_FROM", "accounts@example.test")
    monkeypatch.setattr(config, "PUBLIC_APP_URL", "https://app.example.test")
    monkeypatch.setattr(config, "RESEND_API_KEY", "")

    outbox = []
    monkeypatch.setattr(account_email, "send_verification",
                        lambda email, token: outbox.append({"kind": "verify", "email": email, "token": token}))
    monkeypatch.setattr(account_email, "send_password_reset",
                        lambda email, token: outbox.append({"kind": "reset", "email": email, "token": token}))

    import ui.app as ui_app
    ui_app._runners.clear()
    ui_app._LOGIN_ATTEMPTS.clear()
    ui_app._SIGNUP_ATTEMPTS.clear()
    ui_app._EMAIL_ATTEMPTS.clear()

    class _NoRunner:                       # no test may start a real pipeline
        def __init__(self, **kwargs): self.waiting_step = None
        def start(self): pass
        def is_alive(self): return False
        def stop(self): pass

    monkeypatch.setattr(ui_app, "SessionRunner", _NoRunner)
    monkeypatch.setattr(ui_app, "_start_runner", lambda sid, db, only=None: True)
    test_client = TestClient(ui_app.app)
    test_client.auth_outbox = outbox
    return test_client


GOOD_PASSWORD = "Good!Password123"


def _signup(client, email, password=GOOD_PASSWORD):
    response = client.post("/api/auth/signup", json={"email": email, "password": password})
    if response.status_code == 202:
        token = client.auth_outbox[-1]["token"]
        return client.post("/api/auth/verify", json={"token": token})
    return response


def _new_session(client, topic):
    return client.post("/api/sessions", json={"topic": topic, "autostart": False}).json()["session_id"]


# --- the local mode must not change ----------------------------------------------

def test_with_no_accounts_the_server_works_as_before(client):
    state = client.get("/api/auth/me").json()
    assert state["accounts"] is False and state["signup_open"] is True
    assert state["email_configured"] is True and state["user"] is None
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


def test_hosted_first_signup_requires_the_access_token(client, monkeypatch):
    monkeypatch.setattr(config, "HOSTED", True)
    monkeypatch.setattr(config, "UI_TOKEN", "owner-bootstrap-token")

    refused = _signup(client, "attacker@example.com")
    assert refused.status_code == 401
    assert accounts.count_users() == 0
    assert client.get("/login").status_code == 200
    assert client.get("/signup").status_code == 200

    assert client.post("/api/login", json={"token": "owner-bootstrap-token"}).status_code == 200
    accepted = _signup(client, "owner@example.com")
    assert accepted.status_code == 200
    assert accepted.json()["user"]["role"] == "owner"


def test_spa_contains_owner_bootstrap_and_account_login_flow(client):
    html = client.get("/").text
    assert 'id="account-screen"' in html
    assert 'id="account-email"' in html
    assert 'id="account-password"' in html
    assert "'/api/auth/signup'" in html
    assert "'/api/auth/login'" in html
    assert "'/api/auth/verify'" in html
    assert "'/api/auth/password/forgot'" in html
    assert "'/api/auth/password/reset'" in html
    assert client.get("/login").status_code == 200
    assert client.get("/signup").status_code == 200
    assert client.get("/verify-email").status_code == 200
    assert client.get("/forgot-password").status_code == 200
    assert client.get("/reset-password").status_code == 200
    assert client.get("/app").status_code == 200
    assert client.get("/app/projects/example").status_code == 200


def test_a_weak_password_or_bad_email_is_refused(client):
    assert _signup(client, "not-an-email").status_code == 400
    assert _signup(client, "a@example.com", "short").status_code == 400
    assert _signup(client, "a@example.com", "x" * 129).status_code == 400
    assert _signup(client, "a@example.com", "onlylowercase123!").status_code == 400
    assert accounts.count_users() == 0


def test_signup_attempts_are_rate_limited(client):
    for index in range(5):
        response = client.post("/api/auth/signup",
                               json={"email": f"bad-{index}", "password": GOOD_PASSWORD})
        assert response.status_code == 400
    limited = client.post("/api/auth/signup",
                          json={"email": "sixth@example.com", "password": GOOD_PASSWORD})
    assert limited.status_code == 429
    assert accounts.count_users() == 0


def test_the_same_email_cannot_sign_up_twice(client):
    assert _signup(client, "one@example.com").status_code == 200
    again = client.post("/api/auth/signup",
                        json={"email": "one@example.com", "password": GOOD_PASSWORD})
    assert again.status_code == 202
    assert "already" not in again.text.lower()


def test_signing_in_and_out(client):
    _signup(client, "me@example.com")
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").json()["user"] is None
    assert client.get("/api/sessions").status_code == 401       # accounts exist now

    assert client.post("/api/auth/login",
                       json={"email": "me@example.com", "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login",
                       json={"email": "me@example.com", "password": GOOD_PASSWORD}).status_code == 200
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
    client.post("/api/auth/login", json={"email": "alice@example.com", "password": GOOD_PASSWORD})
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
    assert client.get("/api/settings").status_code == 401
    assert client.get("/api/environment").status_code == 401
    assert client.get("/api/access/tokens").status_code == 401
    assert client.get("/health").status_code == 200          # still fine to ask if it is alive
    assert client.get("/api/auth/me").status_code == 200


def test_public_signup_and_login_paths_remain_open_after_accounts_exist(client):
    _signup(client, "owner@example.com")
    client.post("/api/auth/logout")

    assert client.get("/login").status_code == 200
    assert client.get("/signup").status_code == 200
    assert client.get("/app").status_code == 200
    assert client.get("/app/projects/example").status_code == 200
    assert client.get("/api/settings").status_code == 401
    assert _signup(client, "member@example.com").status_code == 200


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
    assert GOOD_PASSWORD not in body and "password_hash" not in body

    import sqlite3
    conn = sqlite3.connect(config.SQLITE_PATH)
    stored = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    conn.close()
    assert stored.startswith("scrypt$") and GOOD_PASSWORD not in stored
    assert accounts.verify_password("alice@example.com", GOOD_PASSWORD) is not None
    assert accounts.verify_password("alice@example.com", "nearly-right") is None


def test_signup_requires_email_verification_before_login_or_private_access(client):
    response = client.post("/api/auth/signup",
                           json={"email": "new@example.com", "password": GOOD_PASSWORD})
    assert response.status_code == 202
    assert "ra_user" not in response.cookies
    assert client.post("/api/auth/login",
                       json={"email": "new@example.com", "password": GOOD_PASSWORD}).status_code == 403
    assert client.get("/api/sessions").status_code == 401

    token = client.auth_outbox[-1]["token"]
    verified = client.post("/api/auth/verify", json={"token": token})
    assert verified.status_code == 200
    assert verified.json()["user"]["email_verified"] is True
    assert client.post("/api/auth/verify", json={"token": token}).status_code == 400
    assert client.get("/api/sessions").status_code == 200


def test_account_tokens_are_hashed_and_expire(client):
    import sqlite3

    response = client.post("/api/auth/signup",
                           json={"email": "new@example.com", "password": GOOD_PASSWORD})
    assert response.status_code == 202
    raw = client.auth_outbox[-1]["token"]
    conn = sqlite3.connect(config.SQLITE_PATH)
    stored = conn.execute("SELECT token_hash FROM account_tokens").fetchone()[0]
    assert raw not in stored and len(stored) == 64
    conn.execute("UPDATE account_tokens SET expires_at = 0")
    conn.commit()
    conn.close()
    assert client.post("/api/auth/verify", json={"token": raw}).status_code == 400


def test_password_reset_is_non_enumerating_one_time_and_invalidates_sessions(client):
    _signup(client, "owner@example.com")
    old_cookie = client.cookies.get("ra_user")
    client.post("/api/auth/logout")

    unknown = client.post("/api/auth/password/forgot", json={"email": "nobody@example.com"})
    known = client.post("/api/auth/password/forgot", json={"email": "owner@example.com"})
    assert unknown.status_code == known.status_code == 200
    assert unknown.json()["message"] == known.json()["message"]

    token = [item for item in client.auth_outbox if item["kind"] == "reset"][-1]["token"]
    new_password = "Even!BetterPassword456"
    reset = client.post("/api/auth/password/reset",
                        json={"token": token, "password": new_password})
    assert reset.status_code == 200
    assert client.post("/api/auth/password/reset",
                       json={"token": token, "password": "Another!Password789"}).status_code == 400
    assert client.post("/api/auth/login",
                       json={"email": "owner@example.com", "password": GOOD_PASSWORD}).status_code == 401
    assert client.post("/api/auth/login",
                       json={"email": "owner@example.com", "password": new_password}).status_code == 200

    client.cookies.clear()
    client.cookies.set("ra_user", old_cookie)
    assert client.get("/api/sessions").status_code == 401


def test_password_change_requires_current_password_and_rotates_session(client):
    _signup(client, "owner@example.com")
    old_cookie = client.cookies.get("ra_user")
    refused = client.post("/api/auth/password/change", json={
        "current_password": "wrong", "new_password": "Even!BetterPassword456",
    })
    assert refused.status_code == 400
    changed = client.post("/api/auth/password/change", json={
        "current_password": GOOD_PASSWORD, "new_password": "Even!BetterPassword456",
    })
    assert changed.status_code == 200
    assert client.cookies.get("ra_user") != old_cookie


def test_signup_stays_unavailable_when_email_delivery_is_not_configured(client, monkeypatch):
    monkeypatch.setattr(account_email, "configured", lambda: False)
    response = client.post("/api/auth/signup",
                           json={"email": "new@example.com", "password": GOOD_PASSWORD})
    assert response.status_code == 503
    assert accounts.count_users() == 0


def test_authenticated_smtp_is_not_ready_without_its_password(client, monkeypatch):
    monkeypatch.setattr(config, "SMTP_USERNAME", "resend")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "")
    assert account_email.configured() is False
    monkeypatch.setattr(config, "SMTP_PASSWORD", "re_test_only")
    assert account_email.configured() is True


def test_resend_https_transport_is_ready_without_smtp(client, monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "")
    monkeypatch.setattr(config, "SMTP_USERNAME", "")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "")
    monkeypatch.setattr(config, "RESEND_API_KEY", "re_test_only")
    assert account_email.configured() is True


def test_resend_https_transport_posts_expected_shape(client, monkeypatch):
    import json

    monkeypatch.setattr(config, "RESEND_API_KEY", "re_test_only")
    requests = []

    class _Response:
        status = 200

        def __enter__(self): return self
        def __exit__(self, *args): return None

    def _urlopen(request, timeout):
        requests.append((request, timeout))
        return _Response()

    # The client fixture stubs account delivery so endpoint tests cannot send
    # mail. This test is specifically about the real transport implementation.
    monkeypatch.setattr(account_email, "send_password_reset", _REAL_SEND_PASSWORD_RESET)
    monkeypatch.setattr(account_email.urllib.request, "urlopen", _urlopen)
    account_email.send_password_reset("owner@example.com", "token-value")

    request, timeout = requests[0]
    payload = json.loads(request.data)
    assert request.full_url == "https://api.resend.com/emails"
    assert request.get_header("Authorization") == "Bearer re_test_only"
    assert payload["to"] == ["owner@example.com"]
    assert "#token=token-value" in payload["text"]
    assert timeout == 20


def test_legacy_bootstrap_account_is_grandfathered_without_verifying_new_accounts(tmp_path, monkeypatch):
    import sqlite3

    db_path = tmp_path / "legacy.db"
    monkeypatch.setattr(config, "SQLITE_PATH", db_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE users (user_id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, "
                 "password_hash TEXT NOT NULL, role TEXT NOT NULL, plan TEXT NOT NULL, "
                 "created_at TEXT NOT NULL, last_login_at TEXT)")
    conn.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, NULL)",
                 ("legacy", "owner@example.com", accounts._hash_password(GOOD_PASSWORD),
                  "owner", "free", "2026-09-01T00:00:00+00:00"))
    conn.commit()
    conn.close()

    legacy = accounts.get_user("legacy")
    assert legacy is not None and legacy.email_verified is True
    new_user = accounts.create_user("new@example.com", GOOD_PASSWORD)
    assert new_user.email_verified is False
