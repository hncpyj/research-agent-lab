"""
Each person's own provider key (memory/api_keys.py).

Before this, a key came from `.env` alone: one key for the whole server. On a
hosted server that means every account spends the operator's credit, and the
key sits in plain text in a file that gets backed up and exported.

What these pin: the key is unreadable at rest, it never leaves the server, one
account's key is no use to another, and an account without a key of its own
does not quietly fall back to the operator's.
"""
import pytest
from fastapi.testclient import TestClient

import config
from memory import accounts, api_keys

REAL_KEY = "test-anthropic-key-not-a-secret"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.delenv("API_KEY_ENCRYPTION_KEY", raising=False)
    return tmp_path


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "UI_TOKEN", "")
    monkeypatch.setattr(config, "ALLOW_SIGNUP", True)
    monkeypatch.delenv("API_KEY_ENCRYPTION_KEY", raising=False)

    import ui.app as ui_app
    ui_app._LOGIN_ATTEMPTS.clear()
    return TestClient(ui_app.app)


# --- at rest ---------------------------------------------------------------------

def test_the_key_is_not_in_the_database_in_readable_form(store):
    api_keys.store("u1", "anthropic", REAL_KEY)
    raw = (store / "t.db").read_bytes()
    assert REAL_KEY.encode() not in raw
    assert b"0123456789abcdefghijklmnop" not in raw          # nor any usable part of it


def test_what_was_stored_is_what_comes_back(store):
    api_keys.store("u1", "anthropic", REAL_KEY)
    assert api_keys.get("u1", "anthropic") == REAL_KEY


def test_a_key_is_no_use_to_another_account(store):
    """A row copied to another user must not decrypt: the two are bound together."""
    import sqlite3

    api_keys.store("u1", "anthropic", REAL_KEY)
    conn = sqlite3.connect(store / "t.db")
    secret = conn.execute("SELECT secret FROM user_api_keys WHERE user_id = 'u1'").fetchone()[0]
    conn.execute("INSERT INTO user_api_keys (user_id, provider, secret, hint, created_at, updated_at) "
                 "VALUES ('u2', 'anthropic', ?, 'x', 'now', 'now')", (secret,))
    conn.commit()
    conn.close()

    assert api_keys.get("u2", "anthropic") == ""             # reported as absent, not raised
    assert api_keys.get("u1", "anthropic") == REAL_KEY


def test_the_same_key_stored_for_another_provider_does_not_open_this_one(store):
    import sqlite3

    api_keys.store("u1", "openai", REAL_KEY)
    conn = sqlite3.connect(store / "t.db")
    secret = conn.execute("SELECT secret FROM user_api_keys WHERE provider = 'openai'").fetchone()[0]
    conn.execute("UPDATE user_api_keys SET provider = 'anthropic' WHERE user_id = 'u1'", ())
    conn.commit(); conn.close()
    assert api_keys.get("u1", "anthropic") == ""
    assert secret                                            # the row is there, it just will not open


def test_a_damaged_row_is_treated_as_absent_not_as_a_crash(store):
    import sqlite3

    api_keys.store("u1", "anthropic", REAL_KEY)
    conn = sqlite3.connect(store / "t.db")
    conn.execute("UPDATE user_api_keys SET secret = 'not-really-encrypted'")
    conn.commit(); conn.close()
    assert api_keys.get("u1", "anthropic") == ""


# --- what the page may see ---------------------------------------------------------

def test_the_listing_shows_a_hint_and_never_the_key(store):
    api_keys.store("u1", "anthropic", REAL_KEY)
    listed = api_keys.list_keys("u1")
    assert [k.provider for k in listed] == ["anthropic"]
    assert listed[0].hint == "sk-ant…mnop"
    assert REAL_KEY not in str([k.as_dict() for k in listed])


def test_replacing_a_key_keeps_when_it_was_first_added(store):
    first = api_keys.store("u1", "anthropic", REAL_KEY)
    second = api_keys.store("u1", "anthropic", REAL_KEY + "-second")
    assert second.created_at == first.created_at
    assert api_keys.get("u1", "anthropic").endswith("-second")
    assert len(api_keys.list_keys("u1")) == 1          # replaced, not added alongside


def test_a_removed_key_is_gone(store):
    api_keys.store("u1", "anthropic", REAL_KEY)
    assert api_keys.remove("u1", "anthropic") is True
    assert api_keys.get("u1", "anthropic") == ""
    assert api_keys.remove("u1", "anthropic") is False


def test_using_a_key_records_when(store):
    api_keys.store("u1", "anthropic", REAL_KEY)
    assert api_keys.list_keys("u1")[0].last_used_at == ""
    api_keys.key_for("u1", "anthropic")
    assert api_keys.list_keys("u1")[0].last_used_at


@pytest.mark.parametrize("bad, says", [
    ("", "Paste the key"),
    ("   ", "Paste the key"),
    ("sk-short", "too short"),
    ("sk-ant-api03 0123456789abcdef", "no spaces"),
])
def test_what_is_obviously_not_a_key_is_refused_with_a_reason(store, bad, says):
    with pytest.raises(api_keys.ApiKeyError, match=says):
        api_keys.store("u1", "anthropic", bad)


def test_an_unknown_provider_cannot_be_given_a_key(store):
    from models.providers import ProviderUnavailable

    with pytest.raises(ProviderUnavailable):
        api_keys.store("u1", "not-a-provider", REAL_KEY)


# --- whose key a run spends ----------------------------------------------------------

def test_on_your_own_machine_the_env_key_is_yours(store, monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-from-the-env-file")
    assert api_keys.key_for(api_keys.LOCAL_USER, "anthropic") == "sk-ant-from-the-env-file"


def test_a_member_without_a_key_does_not_spend_the_servers(store, monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-the-operators-key")
    owner = accounts.create_user("owner@example.com", "a-good-password")
    member = accounts.create_user("member@example.com", "a-good-password")

    assert api_keys.key_for(owner.user_id, "anthropic") == "sk-ant-the-operators-key"
    assert api_keys.key_for(member.user_id, "anthropic") == ""     # local model instead

    api_keys.store(member.user_id, "anthropic", REAL_KEY)
    assert api_keys.key_for(member.user_id, "anthropic") == REAL_KEY


def test_a_run_uses_the_key_of_whoever_it_belongs_to(store, monkeypatch):
    """The whole point: the call is made with this person's key, not the server's."""
    from models import api_model as api_model_module
    from models import providers

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-the-operators-key")
    accounts.create_user("owner@example.com", "a-good-password")
    member = accounts.create_user("member@example.com", "a-good-password")
    api_keys.store(member.user_id, "anthropic", REAL_KEY)

    used = {}

    def fake_build(name=None, api_key=None, model=None):
        used["provider"], used["key"] = name, api_key
        raise providers.ProviderUnavailable("not actually building one")

    monkeypatch.setattr(providers, "build", fake_build)
    api_model_module.APIModel(user_id=member.user_id, provider="anthropic")
    assert used["key"] == REAL_KEY


# --- over HTTP -------------------------------------------------------------------

def test_the_api_never_hands_back_a_key(client):
    saved = client.put("/api/keys/anthropic", json={"key": REAL_KEY})
    assert saved.status_code == 200
    assert REAL_KEY not in saved.text

    listed = client.get("/api/keys")
    assert REAL_KEY not in listed.text
    anthropic = [p for p in listed.json()["providers"] if p["provider"] == "anthropic"][0]
    assert anthropic["stored"]["hint"] == "sk-ant…mnop"
    assert anthropic["usable"] is True


def test_a_key_can_be_replaced_and_deleted_from_the_page(client):
    client.put("/api/keys/anthropic", json={"key": REAL_KEY})
    client.put("/api/keys/anthropic", json={"key": REAL_KEY + "-new"})
    assert api_keys.get(api_keys.LOCAL_USER, "anthropic").endswith("-new")

    after = client.delete("/api/keys/anthropic").json()
    assert [p for p in after["providers"] if p["provider"] == "anthropic"][0]["stored"] is None


def test_a_bad_key_is_refused_with_the_reason_shown(client):
    refused = client.put("/api/keys/anthropic", json={"key": "sk-short"})
    assert refused.status_code == 400 and "too short" in refused.json()["detail"]


def test_one_account_cannot_see_or_touch_another_accounts_keys(client):
    client.post("/api/auth/signup", json={"email": "owner@example.com", "password": "a-good-password"})
    client.put("/api/keys/anthropic", json={"key": REAL_KEY})
    client.post("/api/auth/logout")

    client.post("/api/auth/signup", json={"email": "member@example.com", "password": "a-good-password"})
    mine = client.get("/api/keys").json()
    assert all(p["stored"] is None for p in mine["providers"])
    assert mine["server_key_allowed"] is False           # the operator's key is not theirs

    client.delete("/api/keys/anthropic")                 # cannot remove someone else's
    owner = accounts.verify_password("owner@example.com", "a-good-password")
    assert api_keys.get(owner.user_id, "anthropic") == REAL_KEY


def test_signed_out_nobody_can_read_the_keys(client):
    client.post("/api/auth/signup", json={"email": "owner@example.com", "password": "a-good-password"})
    client.post("/api/auth/logout")
    assert client.get("/api/keys").status_code == 401
