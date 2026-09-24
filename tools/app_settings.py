"""
Settings a person can change while the server runs.

config.py reads .env once at import, so anything set there needs a file edit
and a restart — and .env also holds the Anthropic key, which no web request
should be able to rewrite. These few settings live in their own JSON file
instead; config values are the defaults when the file says nothing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import config

logger = logging.getLogger(__name__)

DEFAULTS: dict = {
    "use_api": None,            # None -> config.USE_API
    "daily_budget_usd": None,   # None -> config.API_DAILY_BUDGET_USD
    "api_provider": None,       # None -> config.API_PROVIDER (gemini by default)
    "api_models": None,         # None -> each provider's default; {provider: model id}
    "local_model": None,        # None -> config.OLLAMA_MODEL
    "local_embed_model": None,  # None -> config.OLLAMA_EMBED_MODEL
    "local_num_ctx": None,      # None -> config.OLLAMA_NUM_CTX
    "local_server_url": None,   # OpenAI-compatible server (LM Studio, vLLM, llama-server…)
}


def path() -> Path:
    return Path(config.DATA_DIR) / "ui_settings.json"


def load() -> dict:
    try:
        stored = json.loads(path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        stored = {}
    except (OSError, ValueError) as exc:
        logger.warning("Could not read %s (%s); using defaults.", path(), exc)
        stored = {}
    return {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}


def save(values: dict) -> dict:
    current = load()
    current.update({k: v for k, v in values.items() if k in DEFAULTS})
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def use_api() -> bool:
    value = load()["use_api"]
    return config.USE_API if value is None else bool(value)


def daily_budget_usd() -> float:
    value = load()["daily_budget_usd"]
    return config.API_DAILY_BUDGET_USD if value is None else float(value)


def api_provider() -> str:
    """Preferred BYOK backend for a new run; hosted no-key uses shared Gemini."""
    value = load()["api_provider"]
    return (value or config.API_PROVIDER or "gemini").strip().lower()


def api_model(provider: str | None = None) -> str:
    """The model id chosen for that provider, or the provider's default."""
    from models.providers import PROVIDERS

    name = (provider or api_provider()).strip().lower()
    chosen = (load()["api_models"] or {}).get(name)
    if chosen:
        return str(chosen)
    info = PROVIDERS.get(name)
    return info.default_model if info else config.API_MODEL_DEFAULT


def set_api_model(provider: str, model: str) -> dict:
    """Remember one provider's model without forgetting the others."""
    models = dict(load()["api_models"] or {})
    models[provider.strip().lower()] = model.strip()
    return save({"api_models": models})


def local_model() -> str:
    """The Ollama tag a run should use for text (the settings page can change it)."""
    return str(load()["local_model"] or config.OLLAMA_MODEL)


def local_embed_model() -> str:
    """The Ollama tag used for paper-ranking embeddings."""
    return str(load()["local_embed_model"] or config.OLLAMA_EMBED_MODEL)


def local_num_ctx() -> int:
    """
    Context window sent with every local call. It belongs next to the model
    choice: a bigger model on the same GPU usually needs a smaller window, and
    picking one without the other is how a prompt ends up silently cut.
    """
    value = load()["local_num_ctx"]
    return config.OLLAMA_NUM_CTX if value in (None, "") else int(value)


def local_server_url() -> str:
    """Where an OpenAI-compatible server is listening, if one is being used."""
    return str(load()["local_server_url"] or config.OPENAI_BASE_URL or "")
