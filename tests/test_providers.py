"""
Anthropic, OpenAI or Gemini — the choice must not change anything else.

2026-09-21: the only paid backend was Anthropic. Retries, cost logging, the
daily cap and the local fallback stay in APIModel; a provider only says how to
send a request and how to read an error.
"""
import pytest

import config
from models import providers
from models.api_model import APIModel
from tools import app_settings
from tools.cost_tracker import CostTracker


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config, "API_PROVIDER", "anthropic")
    return tmp_path


class _Recorder:
    """A provider that records what it was asked and answers without a network."""
    free = False        # same attribute every real provider carries

    def __init__(self, reply="answered", fail=None, free=False):
        self.free = free
        self.model = "test-model"
        self.calls = []
        self._reply = reply
        self._fail = fail
        self.name = "test"

    def send(self, system, messages, max_tokens, temperature):
        self.calls.append({"system": system, "messages": messages, "max_tokens": max_tokens})
        if self._fail:
            raise self._fail
        return self._reply, 1000, 500

    def classify(self, exc):
        return providers.FATAL


# --- what is on offer ----------------------------------------------------------

def test_three_providers_are_offered_with_their_key_state(env, monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-test")
    described = {p["name"]: p for p in providers.describe()}
    assert set(described) == {"anthropic", "openai", "gemini", "local_server"}
    assert described["openai"]["key_set"] is True
    assert described["anthropic"]["key_set"] is False
    assert described["gemini"]["key_env"] == "GEMINI_API_KEY"
    # Every hosted provider suggests models; a server you run yourself is asked
    # at the time, so it ships no list.
    assert all(p["models"] for name, p in described.items() if name != "local_server")
    assert described["local_server"]["needs_key"] is False


def test_an_unknown_provider_is_refused(env):
    with pytest.raises(providers.ProviderUnavailable, match="unknown provider"):
        providers.resolve("llama-corp")


def test_a_provider_without_a_key_cannot_be_built(env):
    with pytest.raises(providers.ProviderUnavailable, match="OPENAI_API_KEY"):
        providers.build("openai")


def test_gemini_is_reached_through_the_openai_endpoint(env, monkeypatch):
    """No second SDK: Google publishes an OpenAI-compatible endpoint."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "key-abc")
    built = {}

    class _FakeClient:
        def __init__(self, api_key=None, base_url=None):
            built["api_key"] = api_key
            built["base_url"] = base_url

    monkeypatch.setattr("openai.OpenAI", _FakeClient)
    provider = providers.build("gemini", model="gemini-2.5-flash")

    assert isinstance(provider, providers.OpenAICompatibleProvider)
    assert built["base_url"] == config.GEMINI_BASE_URL
    assert built["api_key"] == "key-abc"
    assert provider.model == "gemini-2.5-flash"


# --- the parts that must not change with the provider --------------------------

def test_every_provider_logs_one_row_and_a_real_price(env, tmp_path, monkeypatch):
    tracker = CostTracker(db_path=tmp_path / "usage.db")
    model = APIModel(api_key="x", cost_tracker=tracker, provider="openai")
    model._provider = _Recorder()
    model._model = "gpt-4o-mini"                     # $0.15 / $0.60 per 1M

    assert model.generate("hello", task_type="test") == "answered"
    assert tracker.call_count() == 1
    assert tracker.total_cost() == pytest.approx(1000 * 0.15 / 1e6 + 500 * 0.60 / 1e6)


def test_a_model_with_no_published_price_is_costed_high_not_silently_wrong(env, tmp_path):
    tracker = CostTracker(db_path=tmp_path / "usage.db")
    model = APIModel(api_key="x", cost_tracker=tracker, provider="openai")
    model._provider = _Recorder()
    model._model = "some-new-model-2030"

    model.generate("hello", task_type="test")
    expected = (1000 * config.UNKNOWN_TOKEN_COST["input"] + 500 * config.UNKNOWN_TOKEN_COST["output"]) / 1e6
    assert tracker.total_cost() == pytest.approx(expected)


def test_a_fatal_provider_error_falls_back_to_the_local_model(env, tmp_path):
    class _Local:
        is_loaded = True
        def generate(self, prompt, system="", max_tokens=0, **kw): return "local answer"

    tracker = CostTracker(db_path=tmp_path / "usage.db")
    model = APIModel(api_key="x", cost_tracker=tracker, provider="openai", local_model=_Local())
    model._provider = _Recorder(fail=RuntimeError("insufficient_quota"))

    assert model.generate("hello", task_type="test") == "local answer"
    assert tracker.call_count() == 1                  # the local call is logged too


def test_no_key_anywhere_means_the_run_stays_local(env, tmp_path):
    model = APIModel(cost_tracker=CostTracker(db_path=tmp_path / "usage.db"), provider="gemini")
    assert model._api_available is False
    assert model._provider is None


# --- choosing it from the settings page ----------------------------------------

def test_the_chosen_provider_and_model_survive_a_restart(env, monkeypatch):
    app_settings.save({"api_provider": "gemini"})
    app_settings.set_api_model("gemini", "gemini-2.5-pro")
    app_settings.set_api_model("openai", "gpt-4o")

    assert app_settings.api_provider() == "gemini"
    assert app_settings.api_model() == "gemini-2.5-pro"
    assert app_settings.api_model("openai") == "gpt-4o"          # kept per provider
    assert app_settings.api_model("anthropic") == providers.PROVIDERS["anthropic"].default_model


def test_an_unset_provider_falls_back_to_the_env_file(env, monkeypatch):
    monkeypatch.setattr(config, "API_PROVIDER", "openai")
    assert app_settings.api_provider() == "openai"
    assert app_settings.api_model() == config.OPENAI_MODEL


# --- swapping the local model --------------------------------------------------

def test_the_local_model_can_be_swapped_and_remembered(env):
    from models.ollama_model import OllamaEmbedModel, OllamaModel

    assert app_settings.local_model() == config.OLLAMA_MODEL           # .env default
    app_settings.save({"local_model": "qwen2.5:14b-instruct-q4_K_M",
                       "local_embed_model": "mxbai-embed-large",
                       "local_num_ctx": 4096})

    assert OllamaModel()._model == "qwen2.5:14b-instruct-q4_K_M"
    assert OllamaEmbedModel()._model == "mxbai-embed-large"
    assert app_settings.local_num_ctx() == 4096
    # An explicit argument still wins, so a caller can pin one model.
    assert OllamaModel(model="llama3.1:8b")._model == "llama3.1:8b"


def test_clearing_the_choice_falls_back_to_the_env_file(env, monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_MODEL", "llama3.1:8b")
    monkeypatch.setattr(config, "OLLAMA_NUM_CTX", 8192)
    app_settings.save({"local_model": None, "local_num_ctx": None})
    assert app_settings.local_model() == "llama3.1:8b"
    assert app_settings.local_num_ctx() == 8192


# --- a server you run yourself --------------------------------------------------

def test_an_address_on_this_machine_is_not_billed():
    assert providers.is_local_address("http://localhost:1234/v1") is True
    assert providers.is_local_address("http://127.0.0.1:8000/v1") is True
    assert providers.is_local_address("http://192.168.1.7:8000/v1") is True
    assert providers.is_local_address("http://studio.local:1234/v1") is True
    assert providers.is_local_address("https://api.openai.com/v1") is False
    assert providers.is_local_address("") is False


def test_the_local_server_provider_needs_an_address_not_a_key(env):
    info = providers.PROVIDERS["local_server"]
    assert info.needs_key is False and info.configurable_url is True
    assert info.ready() is False
    with pytest.raises(providers.ProviderUnavailable, match="no address"):
        providers.build("local_server")

    app_settings.save({"local_server_url": "http://localhost:1234/v1"})
    with pytest.raises(providers.ProviderUnavailable, match="needs a model name"):
        providers.build("local_server")

    app_settings.set_api_model("local_server", "qwen2.5-14b-instruct")
    assert info.ready() is True
    built = providers.build("local_server")
    assert built.model == "qwen2.5-14b-instruct"
    assert built.free is True                 # nothing to bill
    assert built.api_key == "local"           # the SDK needs something; the server ignores it


def test_calls_to_a_self_hosted_server_do_not_count_against_the_cap(env, tmp_path, monkeypatch):
    """A local server has no price list; pricing it would stop runs for money never spent."""
    monkeypatch.setattr(config, "API_DAILY_BUDGET_USD", 1.0)
    tracker = CostTracker(db_path=tmp_path / "usage.db")
    model = APIModel(api_key="x", cost_tracker=tracker, provider="openai")
    model._provider = _Recorder(free=True)
    model._model = "qwen2.5-14b-instruct"

    for _ in range(3):
        model.generate("hello", task_type="test")

    assert tracker.call_count() == 3          # still a complete record of what ran
    assert tracker.spend_today() == 0.0
    assert model.over_budget() is False
