"""Security and provenance contract for the optional FreeLLMAPI gateway."""

from __future__ import annotations

import ipaddress
import sqlite3

import pytest

import config
from memory import api_keys
from models import providers
from models.api_model import APIModel, ProviderRouteMismatch
from tools.cost_tracker import CostTracker


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "keys.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "HOSTED", False)
    monkeypatch.delenv("API_KEY_ENCRYPTION_KEY", raising=False)
    return tmp_path


def test_gateway_url_policy_distinguishes_local_and_hosted(monkeypatch):
    assert api_keys.normalize_gateway_url("http://localhost:3001", hosted=False) == (
        "http://localhost:3001/v1")
    with pytest.raises(api_keys.ApiKeyError, match="HTTPS"):
        api_keys.normalize_gateway_url("http://gateway.example/v1", hosted=True)

    monkeypatch.setattr(config, "FREELLMAPI_ALLOWED_HOSTS", [])
    with pytest.raises(api_keys.ApiKeyError, match="disabled"):
        api_keys.normalize_gateway_url("https://gateway.example/v1", hosted=True)

    from tools import url_safety
    monkeypatch.setattr(config, "FREELLMAPI_ALLOWED_HOSTS", ["gateway.example"])
    monkeypatch.setattr(url_safety, "_addresses",
                        lambda _host: [ipaddress.ip_address("10.0.0.7")])
    with pytest.raises(api_keys.ApiKeyError, match="inside this network"):
        api_keys.normalize_gateway_url("https://gateway.example/v1", hosted=True)


def test_gateway_token_and_endpoint_are_encrypted_and_user_isolated(local_store):
    token = "freellmapi-test-token-not-secret"
    endpoint = "http://localhost:3001/v1"
    api_keys.store_gateway("u1", endpoint, token)

    raw = (local_store / "keys.db").read_bytes()
    assert token.encode() not in raw
    assert endpoint.encode() not in raw
    assert api_keys.get_gateway("u2") is None
    assert api_keys.get_gateway("u1") == api_keys.GatewayCredential(endpoint, token)

    api_keys.store_gateway("u1", "http://localhost:3002", "replacement-token-for-u1")
    assert api_keys.get_gateway("u1") == api_keys.GatewayCredential(
        "http://localhost:3002/v1", "replacement-token-for-u1")


def test_api_model_passes_only_the_current_users_gateway_to_adapter(
    local_store, monkeypatch
):
    api_keys.store_gateway("u1", "http://localhost:3001", "freellmapi-token-for-u1")
    api_keys.store_gateway("u2", "http://localhost:4001", "freellmapi-token-for-u2")
    captured = {}
    fake = type("Provider", (), {"model": "auto:balanced", "free": False})()

    def build(name, key, model, base_url=None):
        captured.update(name=name, key=key, model=model, base_url=base_url)
        return fake

    monkeypatch.setattr(providers, "build", build)
    model = APIModel(provider="freellmapi", user_id="u1",
                     cost_tracker=CostTracker(local_store / "usage.db"))
    assert model.routing_info()["provider"] == "freellmapi"
    assert captured == {
        "name": "freellmapi",
        "key": "freellmapi-token-for-u1",
        "model": "auto:balanced",
        "base_url": "http://localhost:3001/v1",
    }


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(key.lower(), default)


class _Raw:
    def __init__(self, route="google/gemini-2.5-flash", attempts="2"):
        self.headers = _Headers({
            "x-routed-via": route,
            "x-fallback-attempts": attempts,
            "x-fallback-trail": "groq/model=rate_limited",
        })

    def parse(self):
        message = type("Message", (), {"content": "answer"})()
        choice = type("Choice", (), {"message": message})()
        usage = type("Usage", (), {"prompt_tokens": 7, "completion_tokens": 3})()
        return type("Response", (), {"choices": [choice], "usage": usage})()


class _Completions:
    def __init__(self, raw):
        self.with_raw_response = self
        self._raw = raw

    def create(self, **_kwargs):
        return self._raw


def _gateway_provider(model, raw):
    provider = object.__new__(providers.FreeLLMAPIProvider)
    provider.model = model
    provider._client = type("Client", (), {
        "chat": type("Chat", (), {"completions": _Completions(raw)})()
    })()
    return provider


def test_auto_route_preserves_actual_route_and_fallback_evidence():
    result = _gateway_provider("auto:balanced", _Raw()).send(
        "system", [{"role": "user", "content": "hello"}], 100, 0.2)
    assert result == providers.ProviderResult(
        text="answer", input_tokens=7, output_tokens=3,
        actual_provider="google", actual_model="gemini-2.5-flash",
        fallback_attempts=2, fallback_trail="groq/model=rate_limited")


def test_exact_model_request_rejects_silent_substitution_and_missing_header():
    with pytest.raises(providers.ProviderRouteViolation, match="served"):
        _gateway_provider("gemini-2.5-pro", _Raw()).send("", [], 10, 0)
    with pytest.raises(providers.ProviderRouteViolation, match="omitted"):
        _gateway_provider("gemini-2.5-pro", _Raw(route="")).send("", [], 10, 0)


def test_route_violation_never_falls_back_to_another_model(tmp_path, monkeypatch):
    class _BadRoute:
        free = False
        billing_known = False
        model = "gemini-2.5-pro"

        def send(self, **_kwargs):
            raise providers.ProviderRouteViolation("wrong model")

        def classify(self, _exc):
            return providers.FATAL

    model = APIModel(api_key="a-valid-test-token", provider="openai",
                     cost_tracker=CostTracker(tmp_path / "usage.db"))
    model._provider = _BadRoute()
    model._provider_name = "freellmapi"
    model._model = "gemini-2.5-pro"
    fallback = type("Local", (), {"is_loaded": True,
                                   "generate": lambda *_a, **_k: "must not run"})()
    model.set_local_model(fallback)
    with pytest.raises(ProviderRouteMismatch):
        model.generate("frozen request")


def test_provider_failure_log_redacts_the_stored_gateway_token(
    local_store, monkeypatch
):
    secret = "freellmapi-token-that-must-not-be-logged"

    class _Failure:
        free = False
        billing_known = False
        model = "auto:balanced"
        api_key = secret

        def send(self, **_kwargs):
            raise RuntimeError(f"Authorization: Bearer {secret}")

        def classify(self, _exc):
            return providers.AUTH

    class _Local:
        is_loaded = True

        def generate(self, **_kwargs):
            return "safe local result"

    tracker = CostTracker(local_store / "events.db")
    model = APIModel(api_key="placeholder-key-for-construction", provider="openai",
                     cost_tracker=tracker, local_model=_Local())
    model._provider = _Failure()
    model._provider_name = "freellmapi"
    model._model = "auto:balanced"
    assert model.generate("prompt") == "safe local result"

    conn = sqlite3.connect(local_store / "events.db")
    message = conn.execute(
        "SELECT error_message FROM provider_route_events ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    conn.close()
    assert secret not in message
    assert "[redacted]" in message


def test_usage_row_records_selected_and_actual_route(tmp_path):
    tracker = CostTracker(tmp_path / "usage.db")
    tracker.log(
        model="gemini-2.5-flash", input_tokens=7, output_tokens=3,
        task_type="GAP_ANALYSIS", session_id="s1", provider="freellmapi",
        selected_model="auto:balanced", actual_provider="google",
        actual_model="gemini-2.5-flash", routing_policy="auto:balanced",
        fallback_attempts=2, fallback_trail="groq/model=rate_limited",
        retry_count=1, cost_known=False)
    conn = sqlite3.connect(tmp_path / "usage.db")
    row = conn.execute(
        "SELECT provider, selected_model, actual_provider, actual_model, "
        "fallback_attempts, retry_count, cost_known, cost_usd FROM api_usage_log"
    ).fetchone()
    conn.close()
    assert row == ("freellmapi", "auto:balanced", "google", "gemini-2.5-flash",
                   2, 1, 0, 0.0)
    assert tracker.session_routes("another-session") == []
    visible = tracker.session_routes("s1")
    assert len(visible) == 1
    assert visible[0]["actual_provider"] == "google"
    assert visible[0]["fallback_trail"] == "groq/model=rate_limited"
