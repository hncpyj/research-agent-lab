"""Hosted inference routing is explicit, session-scoped, and network-free here."""

from __future__ import annotations

import pytest

import config
from agents.self_bugfix_agent import SelfBugFixAgent
from memory.note_db import NoteDB
from models import providers
from models.api_model import (
    APIModel,
    BYOKProviderUnavailable,
    ModelAPIDisabled,
    SharedProviderUnavailable,
)
from tools.cost_tracker import CostTracker
from ui.runner import SessionRunner


class _Provider:
    free = False
    model = "test-model"

    def __init__(self, classification=providers.FATAL):
        self.classification = classification
        self.calls = 0

    def send(self, **_kwargs):
        self.calls += 1
        if self.classification != "ok":
            raise RuntimeError("provider diagnostic must stay private")
        return "answer", 2, 1

    def classify(self, _exc):
        return self.classification


@pytest.fixture
def hosted(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "HOSTED", True)
    monkeypatch.setattr(config, "SHARED_FREE_PROVIDER", "gemini")
    monkeypatch.setattr(config, "SHARED_FREE_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "shared-test-key")
    tracker = CostTracker(db_path=tmp_path / "usage.db")
    return tracker


def test_model_api_off_builds_and_calls_no_provider(hosted, monkeypatch):
    built = []
    monkeypatch.setattr(providers, "build", lambda *a, **k: built.append((a, k)))

    model = APIModel(enabled=False, user_id="member", cost_tracker=hosted)

    with pytest.raises(ModelAPIDisabled, match="disabled for this session"):
        model.generate("do not send this")
    assert built == []


def test_model_api_off_is_reported_as_safe_halt_without_ollama_advice(
    hosted, monkeypatch
):
    from memory import runs

    runner = SessionRunner("session", use_api=False)

    def stop_before_inference():
        raise ModelAPIDisabled(
            "Model API is disabled for this session. Gap Analysis cannot continue."
        )

    monkeypatch.setattr(runner, "_run", stop_before_inference)
    monkeypatch.setattr(runs, "finish", lambda *_a, **_k: None)
    runner._safe_run()
    events = []
    while not runner.queue_empty():
        events.append(runner.get_event())

    failure = next(event for event in events if event["type"] == "error")
    assert failure["data"]["kind"] == "model_api_off"
    assert "Ollama" not in failure["data"]["detail"]
    assert "LOCAL_MODEL_PATH" not in failure["data"]["detail"]


def test_hosted_without_byok_uses_shared_free_gemini(hosted, monkeypatch):
    from memory import api_keys

    used = {}
    fake = _Provider(classification="ok")
    monkeypatch.setattr(api_keys, "get", lambda *_a: "")
    monkeypatch.setattr(api_keys, "mark_used", lambda *_a: pytest.fail("no BYOK was used"))

    def build(name, key, model):
        used.update(name=name, key=key, model=model)
        fake.model = model
        return fake

    monkeypatch.setattr(providers, "build", build)
    model = APIModel(provider="anthropic", user_id="member", cost_tracker=hosted)

    assert model.routing_info() == {
        "mode": "shared_free",
        "provider": "gemini",
        "model": "gemini-3.5-flash-lite",
    }
    assert used == {
        "name": "gemini",
        "key": "shared-test-key",
        "model": "gemini-3.5-flash-lite",
    }
    assert model.generate("offline fake") == "answer"
    assert fake.calls == 1
    assert hosted.spend_today() == 0.0


def test_live_toggle_reconfigures_the_same_central_router(hosted, monkeypatch):
    from memory import api_keys

    fake = _Provider(classification="ok")
    monkeypatch.setattr(api_keys, "get", lambda *_a: "")
    monkeypatch.setattr(providers, "build", lambda *_a: fake)
    model = APIModel(enabled=False, provider="anthropic", user_id="member",
                     cost_tracker=hosted)
    runner = SessionRunner("session", use_api=False, model_provider="anthropic")
    runner._api_model = model

    runner.configure_model_api(True, "anthropic")
    assert model.routing_mode == "shared_free"
    assert model.generate("offline fake") == "answer"

    runner.configure_model_api(False, "anthropic")
    with pytest.raises(ModelAPIDisabled):
        model.generate("must not be sent")
    assert fake.calls == 1


@pytest.mark.parametrize("selected", ["anthropic", "openai", "gemini"])
def test_explicit_byok_wins_over_shared_provider(hosted, monkeypatch, selected):
    from memory import api_keys

    built = {}
    marked = []
    fake = _Provider(classification="ok")
    monkeypatch.setattr(api_keys, "get", lambda user, provider: f"{user}:{provider}:key")
    monkeypatch.setattr(api_keys, "mark_used", lambda user, provider: marked.append((user, provider)))

    def build(name, key, model):
        built.update(name=name, key=key, model=model)
        return fake

    monkeypatch.setattr(providers, "build", build)
    model = APIModel(provider=selected, user_id="member", cost_tracker=hosted)

    assert model.routing_mode == "byok"
    assert built["name"] == selected
    assert built["key"] == f"member:{selected}:key"
    assert marked == [("member", selected)]


def test_byok_failure_names_selected_provider_without_exposing_key(hosted, monkeypatch):
    from memory import api_keys

    secret = "never-print-this-secret"
    fake = _Provider(classification=providers.AUTH)
    monkeypatch.setattr(api_keys, "get", lambda *_a: secret)
    monkeypatch.setattr(api_keys, "mark_used", lambda *_a: None)
    monkeypatch.setattr(providers, "build", lambda *_a: fake)
    model = APIModel(provider="openai", user_id="member", cost_tracker=hosted)

    with pytest.raises(BYOKProviderUnavailable) as stopped:
        model.generate("offline fake")
    assert "openai" in str(stopped.value)
    assert secret not in str(stopped.value)
    assert secret not in str(model.routing_info())


@pytest.mark.parametrize("classification", [providers.QUOTA, providers.AUTH])
def test_shared_quota_or_auth_failure_has_no_paid_fallback_or_phase_retry(
    hosted, monkeypatch, classification
):
    from memory import api_keys

    fake = _Provider(classification=classification)
    builds = []
    monkeypatch.setattr(api_keys, "get", lambda *_a: "")
    monkeypatch.setattr(providers, "build", lambda *a: builds.append(a) or fake)
    model = APIModel(provider="anthropic", user_id="member", cost_tracker=hosted)
    phase_calls = []

    def phase():
        phase_calls.append(True)
        return model.generate("offline fake")

    with pytest.raises(SharedProviderUnavailable) as stopped:
        SelfBugFixAgent(model).wrap("Gap Analysis", phase)

    assert fake.calls == 1
    assert len(phase_calls) == 1
    assert len(builds) == 1
    assert "provider diagnostic" not in str(stopped.value)


def test_session_inference_choice_survives_database_reopen(tmp_path):
    path = tmp_path / "sessions.db"
    first = NoteDB(path)
    session_id = first.create_session(
        "topic", model_api_enabled=False, model_provider="openai"
    )

    reopened = NoteDB(path)
    stored = reopened.get_session(session_id)
    assert stored["model_api_enabled"] == 0
    assert stored["model_provider"] == "openai"

    reopened.update_session(
        session_id, model_api_enabled=True, model_provider="gemini"
    )
    updated = NoteDB(path).get_session(session_id)
    assert updated["model_api_enabled"] == 1
    assert updated["model_provider"] == "gemini"


def test_changing_inference_setting_preserves_completed_phase_status(tmp_path):
    path = tmp_path / "sessions.db"
    db = NoteDB(path)
    session_id = db.create_session(
        "topic", model_api_enabled=True, model_provider="gemini"
    )
    db.update_session(session_id, status="review_done")
    db.update_session(session_id, model_api_enabled=False)

    stored = NoteDB(path).get_session(session_id)
    assert stored["status"] == "review_done"
    assert stored["model_api_enabled"] == 0


def test_only_provider_adapter_module_constructs_provider_sdks():
    """A later phase must not regain a direct Anthropic/OpenAI escape hatch."""
    from pathlib import Path

    roots = [Path("agents"), Path("models"), Path("ui")]
    offenders = []
    for root in roots:
        for path in root.rglob("*.py"):
            if path.as_posix() == "models/providers.py":
                continue
            text = path.read_text(encoding="utf-8")
            if any(marker in text for marker in (
                "anthropic.Anthropic(", "openai.OpenAI(",
                ".messages.create(", ".chat.completions.create(",
            )):
                offenders.append(path.as_posix())
    assert offenders == []


def test_gap_analysis_safe_halt_guard_precedes_progress_log():
    """OFF must stop before the UI can claim that the API phase started."""
    from pathlib import Path

    source = Path("ui/runner.py").read_text(encoding="utf-8")
    guard = 'api_model.ensure_available("Gap Analysis")'
    progress = 'self.emit("phase_start", {"phase": 3, "name": "Gap Analysis"})'
    assert source.index(guard) < source.index(progress)


def test_browser_settings_requests_are_scoped_to_the_open_session():
    """Refresh/reconnect reads backend truth instead of a stale global toggle."""
    from pathlib import Path

    source = Path("ui/static/index.html").read_text(encoding="utf-8")
    assert "?session_id=' + encodeURIComponent(state.currentId)" in source
    assert "state.currentId ? {session_id: state.currentId}" in source
    assert "await loadApiSetting();" in source
