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


class ProviderRouteViolation(RuntimeError):
    """A gateway served (or failed to identify) a route the caller did not authorize."""


class SimpleRouteExhausted(RuntimeError):
    """Every user-owned route in Simple Mode failed without exposing provider text."""

    def __init__(self, kind: str, trail: str) -> None:
        detail = f" ({trail})" if trail else ""
        super().__init__(f"all configured Simple Mode providers failed{detail}")
        self.kind = kind
        self.trail = trail


@dataclass(frozen=True)
class ProviderResult:
    """One response plus non-secret routing evidence returned by its provider."""
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    actual_provider: str = ""
    actual_model: str = ""
    fallback_attempts: int = 0
    fallback_trail: str = ""


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
    user_configurable_url: bool = False  # address belongs to the signed-in user
    managed_router: bool = False  # virtual provider composed from this user's keys

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
                "user_configurable_url": self.user_configurable_url,
                 "managed_router": self.managed_router,
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
    "groq": ProviderInfo(
        name="groq", label="Groq", key_env="GROQ_API_KEY",
        default_model=config.GROQ_MODEL,
        models=["openai/gpt-oss-20b", "openai/gpt-oss-120b"],
        docs="https://console.groq.com/docs/models"),
    "auto_byok": ProviderInfo(
        name="auto_byok", label="Automatic (your Gemini + Groq keys)", key_env="",
        default_model="simple:balanced",
        models=["simple:balanced", "simple:gemini-first", "simple:groq-first"],
        docs="docs/FREELLMAPI_INTEGRATION.md", needs_key=False,
        managed_router=True),
    "freellmapi": ProviderInfo(
        name="freellmapi", label="FreeLLMAPI (your gateway)", key_env="",
        default_model="auto:balanced",
        models=["auto:balanced", "auto:reliable", "auto:fast", "auto:smart", "fusion"],
        docs="https://github.com/tashfeenahmed/freellmapi/blob/v0.13.4/docs/en/api/01-rest-api.md",
        user_configurable_url=True),
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
        return ProviderResult(
            text=text,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            actual_provider=self.name,
            actual_model=str(getattr(response, "model", "") or self.model),
        )

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


def _is_virtual_freellmapi_model(model: str) -> bool:
    value = (model or "").strip().lower()
    return value == "fusion" or value == "auto" or value.startswith("auto:")


def _routed_identity(value: str) -> tuple[str, str]:
    """Split FreeLLMAPI's X-Routed-Via ``platform/model`` value."""
    route = (value or "").strip()
    if "/" not in route:
        return "", route
    return tuple(route.split("/", 1))


class FreeLLMAPIProvider(OpenAICompatibleProvider):
    """A user-owned FreeLLMAPI v0.13.4 gateway.

    The raw OpenAI response is required because routing provenance lives in
    HTTP headers rather than in the OpenAI response body. Exact model requests
    fail closed when that evidence is absent or names a different model.
    """

    tested_version = "v0.13.4"
    billing_known = False

    def send(self, system, messages, max_tokens, temperature):
        payload = ([{"role": "system", "content": system}] if system else []) + list(messages)
        raw = self._client.chat.completions.with_raw_response.create(
            model=self.model, messages=payload,
            max_completion_tokens=max_tokens, temperature=temperature,
        )
        response = raw.parse()
        headers = raw.headers
        routed_via = headers.get("x-routed-via", "")
        actual_provider, actual_model = _routed_identity(routed_via)

        if not _is_virtual_freellmapi_model(self.model):
            requested = self.model.strip().lower()
            route = routed_via.strip().lower()
            served = actual_model.strip().lower()
            if not routed_via:
                raise ProviderRouteViolation(
                    "FreeLLMAPI omitted X-Routed-Via for an exact-model request")
            if requested not in {route, served}:
                raise ProviderRouteViolation(
                    f"FreeLLMAPI served {routed_via!r} for exact model {self.model!r}")

        usage = getattr(response, "usage", None)
        text = (response.choices[0].message.content or "") if response.choices else ""
        try:
            attempts = int(headers.get("x-fallback-attempts", "0") or 0)
        except (TypeError, ValueError):
            attempts = 0
        return ProviderResult(
            text=text,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            actual_provider=actual_provider,
            actual_model=actual_model,
            fallback_attempts=max(attempts, 0),
            fallback_trail=headers.get("x-fallback-trail", "") or "",
        )


class SimpleBYOKProvider:
    """A bounded router over one user's own direct-provider credentials.

    This is not a shared FreeLLMAPI process. Each child adapter receives a key
    already scoped to the current RAL user, and every successful response
    reports the provider/model that actually answered.
    """

    name = "auto_byok"
    free = False
    billing_known = True

    def __init__(self, policy: str, routes: list[_Provider]) -> None:
        self.model = policy or "simple:balanced"
        self._routes = list(routes)
        self.api_key = ""
        self.secrets = tuple(route.api_key for route in routes if route.api_key)
        self._cursor = 0

    def _ordered_routes(self) -> list[_Provider]:
        routes = list(self._routes)
        if self.model == "simple:balanced":
            routes.sort(key=lambda route: route.name != "gemini")
            if routes:
                offset = self._cursor % len(routes)
                routes = routes[offset:] + routes[:offset]
                self._cursor = (self._cursor + 1) % len(routes)
        elif self.model == "simple:groq-first":
            routes.sort(key=lambda route: route.name != "groq")
        elif self.model == "simple:gemini-first":
            routes.sort(key=lambda route: route.name != "gemini")
        else:
            raise ProviderUnavailable(f"unknown Simple Mode policy {self.model!r}")
        return routes

    def send(self, system, messages, max_tokens, temperature):
        trail: list[str] = []
        last_kind = FATAL
        for route in self._ordered_routes():
            try:
                raw = route.send(system, messages, max_tokens, temperature)
            except ProviderRouteViolation:
                raise
            except Exception as exc:
                last_kind = route.classify(exc)
                trail.append(f"{route.name}/{route.model}={last_kind}")
                continue
            if isinstance(raw, ProviderResult):
                result = raw
            else:
                text, input_tokens, output_tokens = raw
                result = ProviderResult(text, input_tokens, output_tokens)
            return ProviderResult(
                text=result.text,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                actual_provider=result.actual_provider or route.name,
                actual_model=result.actual_model or route.model,
                fallback_attempts=len(trail) + result.fallback_attempts,
                fallback_trail=";".join(
                    item for item in [*trail, result.fallback_trail] if item),
            )
        raise SimpleRouteExhausted(last_kind, ";".join(trail))

    def classify(self, exc):
        if isinstance(exc, SimpleRouteExhausted):
            return exc.kind
        return FATAL


def build_simple_router(policy: str, credentials: dict[str, str]) -> SimpleBYOKProvider:
    """Build Simple Mode only from the explicitly supplied current-user keys."""
    routes: list[_Provider] = []
    permitted = [name for name in config.SIMPLE_BYOK_PROVIDERS
                 if name in {"gemini", "groq"}]
    for name in permitted:
        key = (credentials.get(name) or "").strip()
        if not key:
            continue
        info = resolve(name)
        routes.append(build(name, api_key=key, model=info.default_model))
    if not routes:
        raise ProviderUnavailable(
            "Simple Mode needs at least one user-owned Gemini or Groq API key")
    return SimpleBYOKProvider(policy, routes)


def build(name: str | None = None, api_key: str | None = None,
          model: str | None = None, base_url: str | None = None) -> _Provider:
    """The provider a run should use. Raises ProviderUnavailable if it cannot run."""
    from tools import app_settings

    info = resolve(name or config.API_PROVIDER)
    key = api_key if api_key is not None else info.key()

    if info.managed_router:
        raise ProviderUnavailable(
            f"{info.label} must be built from the signed-in user's isolated keys")

    if info.user_configurable_url:
        if not key:
            raise ProviderUnavailable(f"{info.label} has no gateway token")
        if not base_url:
            raise ProviderUnavailable(f"{info.label} has no gateway address")
        return FreeLLMAPIProvider(info, key, model or info.default_model, base_url)

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
    base_url = {
        "gemini": config.GEMINI_BASE_URL,
        "groq": config.GROQ_BASE_URL,
    }.get(info.name, config.OPENAI_BASE_URL)
    return OpenAICompatibleProvider(info, key, model or info.default_model, base_url)


def list_gateway_models(api_key: str, base_url: str) -> list[str]:
    """Read model ids through the same isolated FreeLLMAPI adapter boundary."""
    provider = build("freellmapi", api_key, "auto:balanced", base_url=base_url)
    listing = provider._client.with_options(timeout=8.0, max_retries=0).models.list()
    return sorted({str(item.id) for item in listing.data if getattr(item, "id", None)})
