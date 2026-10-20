"""Simple Mode routes only across the current user's own provider keys."""

from __future__ import annotations

import pytest

import config
from memory import api_keys
from models import providers
from models.api_model import APIModel
from tools.cost_tracker import CostTracker


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "keys.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "HOSTED", True)
    monkeypatch.setattr(config, "SIMPLE_BYOK_PROVIDERS", ["gemini", "groq"])
    monkeypatch.delenv("API_KEY_ENCRYPTION_KEY", raising=False)
    return tmp_path


class _Route:
    free = False

    def __init__(self, name, model, result=None, kind=providers.QUOTA):
        self.name = name
        self.model = model
        self.api_key = f"{name}-secret-key-for-test"
        self._result = result
        self._kind = kind

    def send(self, *_args, **_kwargs):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    def classify(self, _exc):
        return self._kind


def test_simple_router_falls_back_and_records_actual_route():
    first = _Route("gemini", "gemini-test", RuntimeError("quota"))
    second = _Route("groq", "groq-test", ("answer", 8, 3))
    router = providers.SimpleBYOKProvider("simple:balanced", [second, first])

    result = router.send("system", [{"role": "user", "content": "hi"}], 20, 0.2)

    assert result == providers.ProviderResult(
        text="answer", input_tokens=8, output_tokens=3,
        actual_provider="groq", actual_model="groq-test",
        fallback_attempts=1, fallback_trail="gemini/gemini-test=quota",
    )
    second_result = router.send("system", [], 20, 0.2)
    assert second_result.actual_provider == "groq"
    assert second_result.fallback_attempts == 0


def test_simple_router_is_bounded_when_every_route_fails():
    router = providers.SimpleBYOKProvider("simple:balanced", [
        _Route("gemini", "gemini-test", RuntimeError("quota")),
        _Route("groq", "groq-test", RuntimeError("auth"), providers.AUTH),
    ])
    with pytest.raises(providers.SimpleRouteExhausted) as stopped:
        router.send("", [], 20, 0.2)
    assert stopped.value.kind == providers.AUTH
    assert "secret" not in str(stopped.value)


def test_api_model_builds_simple_mode_from_only_current_users_keys(
    isolated, monkeypatch
):
    api_keys.store("user-a", "gemini", "gemini-user-a-key-123456")
    api_keys.store("user-b", "groq", "groq-user-b-key-12345678")
    captured = {}

    fake = _Route("auto_byok", "simple:balanced", providers.ProviderResult(
        "ok", 2, 1, actual_provider="gemini", actual_model="gemini-test"))
    fake.secrets = ()
    fake.billing_known = True

    def build_router(policy, credentials):
        captured["policy"] = policy
        captured["credentials"] = credentials
        return fake

    monkeypatch.setattr(providers, "build_simple_router", build_router)
    model = APIModel(
        provider="auto_byok", user_id="user-a",
        cost_tracker=CostTracker(isolated / "usage.db"),
    )

    assert model.routing_mode == "simple_byok"
    assert captured == {
        "policy": "simple:balanced",
        "credentials": {"gemini": "gemini-user-a-key-123456", "groq": ""},
    }
    assert "groq-user-b" not in str(captured)
    assert model.generate("offline test") == "ok"
    used = {item.provider: item.last_used_at for item in api_keys.list_keys("user-a")}
    assert used["gemini"]


def test_virtual_router_cannot_be_given_a_fake_standalone_key(isolated):
    with pytest.raises(api_keys.ApiKeyError, match="separately stored"):
        api_keys.store("user-a", "auto_byok", "not-a-real-router-key-123456")


def test_simple_mode_without_user_keys_does_not_use_operator_shared_key(
    isolated, monkeypatch
):
    built = []
    monkeypatch.setattr(providers, "build", lambda *args, **kwargs: built.append(args))
    model = APIModel(
        provider="auto_byok", user_id="user-a",
        cost_tracker=CostTracker(isolated / "usage-empty.db"),
    )
    assert model.routing_info() == {
        "mode": "simple_byok", "provider": "auto_byok", "model": "simple:balanced"
    }
    assert built == []
