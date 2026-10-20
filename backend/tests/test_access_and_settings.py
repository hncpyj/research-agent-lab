"""
Access tokens you can see and change, and settings that survive a restart.

2026-09-21: access was one string in .env — invisible, unchangeable without a
file edit and a restart, and there could only ever be one.
"""
import pytest

import config
from tools import app_settings
from ui import access


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "UI_TOKEN", "")
    return tmp_path


# --- tokens -------------------------------------------------------------------

def test_a_server_with_no_tokens_is_open(store):
    assert access.locked() is False
    assert access.list_tokens() == []
    assert access.verify("anything") is False


def test_a_new_token_is_shown_in_full_once_and_masked_afterwards(store):
    created = access.create_token("laptop")
    assert len(created["token"]) > 30
    assert created["masked"].count("•") == 8
    assert created["token"][:6] in created["masked"] and created["token"][-4:] in created["masked"]

    listed = access.list_tokens()
    assert [t["name"] for t in listed] == ["laptop"]
    assert listed[0]["masked"] == created["masked"]
    assert "token" not in listed[0]              # the full value is not in the listing
    assert access.locked() is True


def test_a_token_opens_the_server_and_records_when_it_was_used(store):
    created = access.create_token("phone")
    assert access.verify(created["token"]) is True
    assert access.verify(created["token"][:-1] + "x") is False
    assert access.list_tokens()[0]["last_used_at"] is not None


def test_the_full_value_can_be_read_back_by_someone_signed_in(store):
    created = access.create_token("laptop")
    assert access.reveal(created["id"]) == created["token"]
    assert access.reveal("no-such-id") is None


def test_a_revoked_token_stops_working_and_leaves_the_list(store):
    first = access.create_token("old laptop")
    second = access.create_token("new laptop")

    assert access.revoke_token(first["id"]) is True
    assert access.verify(first["token"]) is False
    assert access.verify(second["token"]) is True
    assert [t["name"] for t in access.list_tokens()] == ["new laptop"]
    assert access.revoke_token(first["id"]) is False      # already gone


def test_the_env_token_is_listed_but_cannot_be_revoked_from_the_page(store, monkeypatch):
    monkeypatch.setattr(config, "UI_TOKEN", "from-the-env-file")
    listed = access.list_tokens()
    assert listed[-1]["source"] == "env file" and listed[-1]["can_revoke"] is False
    assert listed[-1]["masked"].endswith("file") and "from-t" in listed[-1]["masked"]
    assert access.verify("from-the-env-file") is True
    assert access.revoke_token(access.ENV_TOKEN_ID) is False
    assert access.reveal(access.ENV_TOKEN_ID) == "from-the-env-file"


# --- settings -----------------------------------------------------------------

def test_settings_fall_back_to_the_env_file(store, monkeypatch):
    monkeypatch.setattr(config, "USE_API", True)
    monkeypatch.setattr(config, "API_DAILY_BUDGET_USD", 5.0)
    assert app_settings.use_api() is True
    assert app_settings.daily_budget_usd() == 5.0


def test_a_changed_setting_is_written_down_and_wins(store, monkeypatch):
    monkeypatch.setattr(config, "USE_API", True)
    monkeypatch.setattr(config, "API_DAILY_BUDGET_USD", 5.0)

    app_settings.save({"use_api": False, "daily_budget_usd": 2.5})

    assert app_settings.path().exists()
    assert app_settings.use_api() is False           # survives a restart, unlike the old toggle
    assert app_settings.daily_budget_usd() == 2.5
    assert app_settings.load()["use_api"] is False


def test_unknown_keys_are_not_stored(store):
    app_settings.save({"use_api": False, "anthropic_api_key": "sk-nope"})
    assert "anthropic_api_key" not in app_settings.path().read_text(encoding="utf-8")


def test_a_damaged_settings_file_falls_back_instead_of_crashing(store, monkeypatch):
    app_settings.path().write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(config, "USE_API", False)
    assert app_settings.use_api() is False


def test_the_settings_page_wins_over_the_env_file_for_the_cap(store, monkeypatch):
    """A cap set on the page is what the model checks, including an explicit 0."""
    from models.api_model import APIModel
    from tools.cost_tracker import CostTracker

    monkeypatch.setattr(config, "API_DAILY_BUDGET_USD", 5.0)
    tracker = CostTracker(db_path=store / "usage.db")
    tracker.log("claude-sonnet-4-5", 0, 1_000_000, "test")      # about $15, over any of these caps
    model = APIModel(api_key="", cost_tracker=tracker)

    assert model.over_budget() is True                          # 5.0 from .env
    app_settings.save({"daily_budget_usd": 0})
    model._budget_warned = False
    assert model.over_budget() is False                         # "no cap", set on the page
