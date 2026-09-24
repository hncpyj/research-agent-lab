"""
The external model backends a run can use: Anthropic, OpenAI, Gemini.

APIModel owns the things that must behave the same whichever backend answers —
retries with the project's 20-30 s pacing, one cost-log row per call, the daily
spending cap, and falling back to the local model. What differs between
providers is only how a request is sent and how an error should be read, so
that is all a provider here does.

Gemini is reached through the OpenAI SDK: Google publishes an OpenAI-compatible
endpoint (https://ai.google.dev/gemini-api/docs/openai), so supporting it needs
no second SDK and no new dependency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import config

logger = logging.getLogger(__name__)

RETRY, NETWORK, FATAL, QUOTA, AUTH = "retry", "network", "fatal", "quota", "auth"


class ProviderUnavailable(RuntimeError):
    """The provider cannot be used at all (no key, SDK missing, unknown name)."""


@dataclass
class ProviderInfo:
    """What the settings page needs to offer a provider."""
    name: str
    label: str
    key_env: str
    default_model: str
    models: list[str] = field(default_factory=list)
    docs: str = ""
    needs_key: bool = True        # a server you run yourself usually needs none
    configurable_url: bool = False  # the settings page asks for its address

    def key(self) -> str:
        return getattr(config, self.key_env, "") or ""

    def ready(self) -> bool:
        """Whether a run could actually use this provider right now."""
        if self.configurable_url:
            from tools import app_settings
            return bool(app_settings.local_server_url())
        return bool(self.key())

    def as_dict(self) -> dict:
        from tools import app_settings
        return {"name": self.name, "label": self.label, "key_env": self.key_env,
                "key_set": bool(self.key()), "ready": self.ready(),
                "needs_key": self.needs_key, "configurable_url": self.configurable_url,
                "base_url": app_settings.local_server_url() if self.configurable_url else "",
                "default_model": self.default_model,
                "models": self.models, "docs": self.docs}


PROVIDERS: dict[str, ProviderInfo] = {
    "anthropic": ProviderInfo(
        name="anthropic", label="Anthropic (Claude)", key_env="ANTHROPIC_API_KEY",
        default_model=config.API_MODEL_DEFAULT,
        models=["claude-sonnet-4-5", "claude-opus-4-6"],
        docs="https://www.anthropic.com/pricing"),
    "openai": ProviderInfo(
        name="openai", label="OpenAI (GPT)", key_env="OPENAI_API_KEY",
        default_model=config.OPENAI_MODEL,
        models=["gpt-5", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-4o", "gpt-4o-mini", "o3-mini"],
        docs="https://developers.openai.com/api/docs/pricing"),
    "gemini": ProviderInfo(
        name="gemini", label="Google (Gemini)", key_env="GEMINI_API_KEY",
        default_model=config.GEMINI_MODEL,
        models=["gemini-3.5-flash-lite", "gemini-2.5-flash-lite",
                "gemini-2.5-flash", "gemini-2.5-pro"],
        docs="https://ai.google.dev/gemini-api/docs/pricing"),
    # Anything else that speaks the same protocol: LM Studio, vLLM,
    # llama.cpp's llama-server, text-generation-webui, a proxy. The address is
    # set on the settings page, so using one needs no .env edit.
    "local_server": ProviderInfo(
        name="local_server", label="Local server (OpenAI-compatible)", key_env="OPENAI_API_KEY",
        default_model="", models=[], needs_key=False, configurable_url=True,
        docs="https://platform.openai.com/docs/api-reference/chat"),
}


def describe() -> list[dict]:
    return [p.as_dict() for p in PROVIDERS.values()]


def resolve(name: str | None) -> ProviderInfo:
    info = PROVIDERS.get((name or "").strip().lower())
    if info is None:
        raise ProviderUnavailable(f"unknown provider {name!r}; known: {', '.join(PROVIDERS)}")
    return info


# --- the adapters -------------------------------------------------------------

def is_local_address(url: str) -> bool:
    """
    Whether this server is on this machine or this network — i.e. whether a
    call to it costs money. A model served from localhost has no price list;
    counting it as spend would make "today's spend" wrong and could stop a run
    on a daily cap that nothing was actually charged against.
    """
    import ipaddress
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").strip().lower()
    if not host:
        return False
    if host in ("localhost", "localhost.localdomain") or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False        # a public hostname: assume it bills
    return address.is_loopback or address.is_private or address.is_link_local


class _Provider:
    """One backend, already configured. Raises ProviderUnavailable if it cannot run."""

    free = False    # True when calls to it are not billed (a server you run)

    def __init__(self, info: ProviderInfo, api_key: str, model: str) -> None:
        self.info = info
        self.name = info.name
        self.model = model or info.default_model
        self.api_key = api_key

    def send(self, system: str, messages: list[dict], max_tokens: int,
             temperature: float) -> tuple[str, int, int]:
        """Return (text, input_tokens, output_tokens)."""
        raise NotImplementedError

    def classify(self, exc: Exception) -> str:
        """Classify transport, quota, authentication, or fatal request errors."""
        raise NotImplementedError


def anthropic_request_kwargs(model: str, system: str, messages: list[dict],
                             max_tokens: int, temperature: float) -> dict:
    """Build the exact keyword arguments passed to ``messages.create``.

    This function is deliberately transport-free: production and offline
    diagnostics share it, so inspecting a dry run cannot drift from the
    request the Anthropic adapter would submit. Authentication and Anthropic's
    HTTP headers remain SDK-managed and are never included here.
    """
    return {
        "model": model,
        "system": system,
        "messages": list(messages),
        "max_tokens": max_tokens,
        "temperature": temperature,
    }


class AnthropicProvider(_Provider):
    def __init__(self, info, api_key, model):
        super().__init__(info, api_key, model)
        try:
            import anthropic
        except ImportError as exc:                       # pragma: no cover - dependency present
            raise ProviderUnavailable("the anthropic package is not installed") from exc
        self._sdk = anthropic
        self._client = anthropic.Anthropic(api_key=api_key)

    def send(self, system, messages, max_tokens, temperature):
        response = self._client.messages.create(**anthropic_request_kwargs(
            model=self.model, system=system, messages=messages,
            max_tokens=max_tokens, temperature=temperature))
        return response.content[0].text, response.usage.input_tokens, response.usage.output_tokens

    def classify(self, exc):
        sdk = self._sdk
        if isinstance(exc, sdk.RateLimitError):
            return QUOTA
        if isinstance(exc, (sdk.APIConnectionError, sdk.APITimeoutError)):
            return NETWORK
        if isinstance(exc, sdk.APIStatusError):
            if exc.status_code >= 500:
                return RETRY
            if exc.status_code in (401, 403):
                return AUTH
            return FATAL
        return FATAL


class OpenAICompatibleProvider(_Provider):
    """
    OpenAI itself, Gemini's OpenAI-compatible endpoint, or any other server
    that speaks the same protocol (set OPENAI_BASE_URL).
    """

    def __init__(self, info, api_key, model, base_url: str = ""):
        super().__init__(info, api_key, model)
        try:
            import openai
        except ImportError as exc:
            raise ProviderUnavailable(
                "the openai package is not installed — run: python -m pip install openai") from exc
        self._sdk = openai
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url or None)
        self.base_url = base_url
        self.free = is_local_address(base_url)

    def send(self, system, messages, max_tokens, temperature):
        payload = ([{"role": "system", "content": system}] if system else []) + list(messages)
        response = self._client.chat.completions.create(
            model=self.model, messages=payload,
            max_completion_tokens=max_tokens, temperature=temperature,
        )
        usage = getattr(response, "usage", None)
        text = (response.choices[0].message.content or "") if response.choices else ""
        return (text,
                getattr(usage, "prompt_tokens", 0) or 0,
                getattr(usage, "completion_tokens", 0) or 0)

    def classify(self, exc):
        sdk = self._sdk
        if isinstance(exc, sdk.RateLimitError):
            return QUOTA
        if isinstance(exc, (sdk.APIConnectionError, sdk.APITimeoutError)):
            return NETWORK
        if isinstance(exc, sdk.APIStatusError):
            status = getattr(exc, "status_code", 0) or 0
            if status >= 500:
                return RETRY
            if status in (401, 403):
                return AUTH
            return FATAL
        return FATAL


def build(name: str | None = None, api_key: str | None = None,
          model: str | None = None) -> _Provider:
    """The provider a run should use. Raises ProviderUnavailable if it cannot run."""
    from tools import app_settings

    info = resolve(name or config.API_PROVIDER)
    key = api_key if api_key is not None else info.key()

    if info.configurable_url:
        base_url = app_settings.local_server_url()
        if not base_url:
            raise ProviderUnavailable(
                f"{info.label} has no address — set the server URL on the settings page")
        chosen = model or app_settings.api_model(info.name)
        if not chosen:
            raise ProviderUnavailable(
                f"{info.label} needs a model name — the one the server serves")
        # Most self-hosted servers ignore the key but the SDK requires one.
        return OpenAICompatibleProvider(info, key or "local", chosen, base_url)

    if not key:
        raise ProviderUnavailable(
            f"{info.label} has no API key — set {info.key_env} in .env")
    if info.name == "anthropic":
        return AnthropicProvider(info, key, model or info.default_model)
    base_url = config.GEMINI_BASE_URL if info.name == "gemini" else config.OPENAI_BASE_URL
    return OpenAICompatibleProvider(info, key, model or info.default_model, base_url)
