"""
The external-model API interface.

One class for whichever backend a run uses — Anthropic, OpenAI or Gemini (see
models/providers.py) — with the behaviour that must not depend on which one
answered:
- Automatic cost logging via CostTracker, one row per call
- A daily spending cap
- Token counting before/after each call
- Retry logic for transient errors, paced like every other external request
- Falling back to the local model instead of failing a run
"""

from __future__ import annotations

import logging
import random
import time
from pathlib import Path

import config
from models import providers
from tools.cost_tracker import CostTracker
from router import TaskType

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


def _retry_wait() -> float:
    """Randomized 20-30 s between retries (project-wide pacing rule)."""
    return random.uniform(config.REQUEST_INTERVAL_MIN_S, config.REQUEST_INTERVAL_MAX_S)


class APIModel:
    """
    Single interface for every external model call, whichever provider is chosen.
    Falls back to a local model when the API is unreachable or exhausted.
    One instance is shared across all agents.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        cost_tracker: CostTracker | None = None,
        local_model=None,  # LocalModel | None — injected by Orchestrator
        on_budget_stop=None,  # Callable[[float, float], None] — told once when the cap engages
        provider: str | None = None,   # anthropic | openai | gemini; None = the chosen one
        session_id: str = "",          # so each call's cost lands on the right session
        user_id: str | None = None,    # whose stored key to use; None = the server's own
        enabled: bool = True,          # authoritative external-model permission for this run
        base_url: str | None = None,   # explicit OpenAI-compatible gateway endpoint
    ) -> None:
        self._tracker = cost_tracker or CostTracker()
        self.session_id = session_id
        self._local_model = local_model  # fallback when API unavailable
        self._on_budget_stop = on_budget_stop
        self._budget_warned = False
        self._user_id = user_id
        self._explicit_api_key = api_key
        self._explicit_base_url = base_url
        self._enabled = False
        self._routing_mode = "off"
        self._provider_error = ""
        self._selected_provider = ""
        self._selected_model = ""
        self._provider_name = ""
        self._model = ""
        self._provider = None
        self._api_available = False
        self._last_route: dict = {}

        self.configure(enabled=enabled, provider=provider, model=model,
                       api_key=api_key, user_id=user_id)

    def configure(
        self,
        *,
        enabled: bool,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        user_id: str | None = None,
        base_url: str | None = None,
    ) -> None:
        """Apply the authoritative route without ever exposing a credential."""
        if user_id is not None:
            self._user_id = user_id
        if api_key is not None:
            self._explicit_api_key = api_key
        if base_url is not None:
            self._explicit_base_url = base_url
        self._enabled = bool(enabled)
        self._routing_mode = "off" if not self._enabled else "configured"
        self._provider_error = ""

        from tools import app_settings
        selected_provider = (
            provider or self._selected_provider or app_settings.api_provider()
        ).strip().lower()
        selected_model = model or app_settings.api_model(selected_provider)
        self._selected_provider = selected_provider
        self._selected_model = selected_model
        self._provider_name = selected_provider
        self._model = selected_model or selected_provider
        self._provider = None
        self._api_available = False

        if not self._enabled:
            return

        # Simple Mode is an in-process, per-user router. It reads only this
        # account's encrypted direct-provider keys and never constructs a
        # shared credential pool. Advanced FreeLLMAPI remains a separate path.
        if selected_provider == "auto_byok":
            from memory import api_keys

            owner_id = self._user_id if self._user_id is not None else api_keys.LOCAL_USER
            credentials = {
                name: api_keys.get(owner_id, name)
                for name in config.SIMPLE_BYOK_PROVIDERS
                if name in {"gemini", "groq"}
            }
            self._routing_mode = "simple_byok"
            try:
                self._provider = providers.build_simple_router(self._model, credentials)
                self._api_available = True
                return
            except providers.ProviderUnavailable as exc:
                self._provider_error = str(exc)
                logger.warning("%s — Simple Mode is unavailable.", exc)
                return

        # Hosted routing has one explicit precedence: selected BYOK first,
        # otherwise the shared free provider. The server's paid/default key is
        # never an implicit fallback for a hosted account.
        chosen_key = self._explicit_api_key
        chosen_base_url = self._explicit_base_url
        if chosen_key is None and config.HOSTED:
            from memory import api_keys
            gateway = (api_keys.get_gateway(self._user_id)
                       if self._user_id and selected_provider == "freellmapi" else None)
            own_key = (gateway.token if gateway else
                       api_keys.get(self._user_id, selected_provider) if self._user_id else "")
            if own_key:
                api_keys.mark_used(self._user_id, selected_provider)
                chosen_key = own_key
                chosen_base_url = gateway.base_url if gateway else chosen_base_url
                self._routing_mode = "byok"
            else:
                self._provider_name = config.SHARED_FREE_PROVIDER
                self._model = config.SHARED_FREE_MODEL
                self._routing_mode = "shared_free"
                try:
                    chosen_key = providers.resolve(self._provider_name).key()
                except providers.ProviderUnavailable as exc:
                    self._provider_error = str(exc)
                    return
        elif chosen_key is None and self._user_id is not None:
            from memory import api_keys
            if selected_provider == "freellmapi":
                gateway = api_keys.get_gateway(self._user_id)
                if gateway:
                    chosen_key, chosen_base_url = gateway.token, gateway.base_url
                    api_keys.mark_used(self._user_id, selected_provider)
            else:
                chosen_key = api_keys.key_for(self._user_id, selected_provider)

        try:
            if chosen_base_url:
                self._provider = providers.build(
                    self._provider_name, chosen_key, self._model, base_url=chosen_base_url)
            else:
                self._provider = providers.build(
                    self._provider_name, chosen_key, self._model)
            self._model = self._provider.model
            self._api_available = True
        except providers.ProviderUnavailable as exc:
            self._provider_error = str(exc)
            if self._routing_mode == "shared_free":
                logger.warning("Shared free model is not configured: %s", exc)
            else:
                logger.warning("%s — using the local model instead.", exc)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_local_model(self, local_model) -> None:
        """Inject or replace the local fallback model after construction."""
        self._local_model = local_model

    @property
    def routing_mode(self) -> str:
        return self._routing_mode

    @property
    def is_loaded(self) -> bool:
        """Compatibility capability flag for agents that accept any text model."""
        if self._api_available:
            return True
        return bool(self._local_model is not None and
                    getattr(self._local_model, "is_loaded", False))

    def routing_info(self) -> dict:
        """Non-secret effective route, safe for UI and logs."""
        return {
            "mode": self._routing_mode,
            "provider": self._provider_name if self._enabled else "",
            "model": self._model if self._enabled else "",
        }

    def last_route_info(self) -> dict:
        """Routing evidence from the latest successful call, without credentials."""
        return dict(self._last_route)

    def ensure_available(self, task_name: str = "this phase") -> None:
        """Fail before a model-dependent phase without making a provider call."""
        if not self._enabled:
            if self._local_model is not None and getattr(self._local_model, "is_loaded", False):
                return
            raise ModelAPIDisabled(
                f"Model API is disabled for this session. Hosted mode has no local "
                f"inference backend, so {task_name} cannot continue. Enable Model API "
                "to use the free hosted model or configure your own provider. "
                "Your completed work has been preserved."
            )
        if self._api_available:
            return
        if self._local_model is not None and getattr(self._local_model, "is_loaded", False):
            return
        if self._routing_mode == "shared_free":
            raise SharedProviderUnavailable(
                "The free hosted model is not configured or is temporarily unavailable. "
                "Your completed research is preserved. Retry later or configure your own "
                "API provider."
            )
        raise BYOKProviderUnavailable(
            f"The selected {self._provider_name} provider is unavailable. Your completed "
            "research is preserved. Check that provider's key and retry."
        )

    def over_budget(self) -> bool:
        """
        True once the day's API spend has reached API_DAILY_BUDGET_USD; every
        call then goes to the local model. Nothing stopped a retry loop from
        spending without limit before 2026-09-20, and a run that dies on
        exhausted credit mid-way leaves a half-finished study behind.
        """
        if self._routing_mode == "shared_free":
            return False
        from tools import app_settings
        cap = app_settings.daily_budget_usd()      # settings page overrides .env
        if cap <= 0:
            return False
        spent = self._tracker.spend_today()
        if spent < cap:
            self._budget_warned = False
            return False
        if not self._budget_warned:
            logger.warning("API spend today is $%.2f, at the $%.2f daily cap — "
                           "using the local model for the rest of the day.", spent, cap)
            self._budget_warned = True
            if self._on_budget_stop:
                self._on_budget_stop(spent, cap)
        return True

    def generate(
        self,
        prompt: str,
        system: str = "You are an expert AI research assistant.",
        task_type: TaskType | str = "unknown",
        max_tokens: int = config.API_MAX_TOKENS,
        temperature: float = 0.7,
    ) -> str:
        """
        Send a single user message and return the assistant reply as a string.
        Falls back to the local model if the API is unavailable.
        """
        task_name = task_type.name if isinstance(task_type, TaskType) else str(task_type)

        if not self._enabled:
            self.ensure_available(task_name)
            return self._local_fallback(prompt, system, task_name, max_tokens)

        if not self._api_available:
            self.ensure_available(task_name)
            return self._local_fallback(prompt, system, task_name, max_tokens)

        if self.over_budget():
            return self._local_fallback(prompt, system, task_name, max_tokens)

        messages = [{"role": "user", "content": prompt}]
        try:
            return self._call_with_retry(
                messages=messages,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                task_name=task_name,
            )
        except (_ProviderQuotaError, _ProviderAuthError, _NetworkError) as exc:
            if self._routing_mode == "shared_free":
                raise SharedProviderUnavailable(
                    "The free hosted model is temporarily unavailable or has reached its "
                    "provider quota. Your completed research is preserved. Retry later or "
                    "configure your own API provider."
                ) from exc
            if config.HOSTED and self._routing_mode in ("byok", "simple_byok"):
                raise BYOKProviderUnavailable(
                    f"The selected {self._provider_name} BYOK provider could not complete "
                    "the request. Your completed research is preserved; check its key, "
                    "quota, and model access before retrying."
                ) from exc
            logger.warning("API unreachable: %s — switching to local fallback.", exc)
            self._api_available = False
            return self._local_fallback(prompt, system, task_name, max_tokens)
        except providers.ProviderRouteViolation as exc:
            raise ProviderRouteMismatch(
                "The gateway did not prove that the authorized exact model served the request. "
                "The response was rejected and no local/model substitution was accepted."
            ) from exc
        except Exception as exc:
            # Anything _call_with_retry did not turn into _NetworkError and the
            # provider calls fatal: billing or credit errors, a model this key
            # may not use, a permission problem. The run continues locally
            # rather than dying half-way; a bug in our own code still raises.
            if self._provider is None or self._provider.classify(exc) != providers.FATAL:
                raise
            if self._routing_mode == "shared_free":
                raise SharedProviderUnavailable(
                    "The free hosted model rejected the request. Your completed research "
                    "is preserved. Retry later or configure your own API provider."
                ) from exc
            if config.HOSTED and self._routing_mode in ("byok", "simple_byok"):
                raise BYOKProviderUnavailable(
                    f"The selected {self._provider_name} BYOK provider rejected the request. "
                    "Your completed research is preserved; check its model access and retry."
                ) from exc
            status = getattr(exc, "status_code", "?")
            logger.warning("%s API error (HTTP %s: %s) — switching to local fallback.",
                           self._provider_name, status, exc)
            self._api_available = False
            return self._local_fallback(prompt, system, task_name, max_tokens)

    def generate_structured(
        self,
        prompt: str,
        system: str = "You are an expert AI research assistant.",
        task_type: TaskType | str = "unknown",
        max_tokens: int = config.API_MAX_TOKENS,
    ) -> str:
        """Low-temperature call intended to produce JSON or structured output."""
        return self.generate(
            prompt=prompt,
            system=system,
            task_type=task_type,
            max_tokens=max_tokens,
            temperature=0.2,
        )

    # ------------------------------------------------------------------
    # Local fallback
    # ------------------------------------------------------------------

    def _local_fallback(
        self, prompt: str, system: str, task_name: str, max_tokens: int | None = None
    ) -> str:
        """
        Use the local model when the API is unavailable.

        The requested output length is passed through, capped so prompt plus
        answer fit the local context window. It used to be dropped, so every
        local call — including whole generated scripts — was cut at
        LOCAL_MAX_TOKENS (2048), mid-file for longer code.
        """
        if self._local_model is None or not getattr(self._local_model, "is_loaded", False):
            raise RuntimeError(
                f"The {self._provider_name} API is unavailable and no local model is loaded.\n"
                f"  Failed task : {task_name}\n"
                f"  Fix option 1: check that provider's key and credit, then restart.\n"
                f"  Fix option 2: start Ollama, or set LOCAL_MODEL_PATH to an existing GGUF\n"
                f"                file, then restart without --skip-local."
            )
        backend_name = self._describe_local_backend()
        logger.info("Local fallback: task=%s backend=%s", task_name, backend_name)
        from rich.console import Console as _Console
        _Console().print(
            f"[yellow][Offline fallback][/] Using local model ({backend_name}) "
            f"for task: {task_name}"
        )

        from models.ollama_model import ContextOverflowError, OllamaModel

        prompt_estimate = (len(prompt) + len(system)) // 3  # conservative chars-per-token
        wanted = max_tokens or config.LOCAL_MAX_TOKENS
        kwargs = {}
        from tools import app_settings
        num_ctx = app_settings.local_num_ctx()      # the settings page can change it
        if isinstance(self._local_model, OllamaModel) and prompt_estimate + min(wanted, 2048) + 256 > num_ctx:
            num_ctx = min(config.OLLAMA_MAX_NUM_CTX,
                          -(-(prompt_estimate + min(wanted, 4096) + 256) // 4096) * 4096)
            kwargs["num_ctx"] = num_ctx
        budget = num_ctx - prompt_estimate - 256
        if budget < 512:
            raise ContextOverflowError(
                f"{task_name}: prompt (~{prompt_estimate} tokens) does not fit the local "
                f"{num_ctx}-token context with room to answer."
            )
        out_tokens = min(wanted, budget)
        result = self._local_model.generate(prompt=prompt, system=system, max_tokens=out_tokens, **kwargs)

        # Log this call too (cost=0) so api_usage_log stays a complete record
        # of every generate() call regardless of which backend served it —
        # without this, a session that silently falls back to local mid-run
        # leaves NO trace anywhere of that having happened (the exact gap an
        # audit found: zero cost-log rows for several real sessions that
        # definitely made generate() calls to finish the phases they did).
        try:
            self._tracker.log(
                model=f"local:{backend_name}",
                input_tokens=self.count_tokens(prompt),
                output_tokens=self.count_tokens(result),
                task_type=task_name,
                is_local=True,
                session_id=self.session_id,
            )
        except Exception as log_exc:
            logger.warning(
                "Local-fallback logging failed for task=%s (call still succeeded): %s",
                task_name, log_exc,
            )

        return result

    def _describe_local_backend(self) -> str:
        """Best-effort human-readable name for whichever local model is loaded."""
        lm = self._local_model
        resolved = getattr(lm, "_resolved_model", None)  # OllamaModel
        if resolved:
            return str(resolved)
        model_path = getattr(lm, "_model_path", None)  # LocalModel (GGUF)
        if model_path:
            return Path(model_path).name
        return type(lm).__name__

    def count_tokens(self, text: str) -> int:
        """Rough token estimate: 1 token ≈ 4 chars (no API call needed)."""
        return len(text) // 4

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_with_retry(
        self,
        messages: list[dict],
        system: str,
        max_tokens: int,
        temperature: float,
        task_name: str,
    ) -> str:
        if self._provider is None:
            raise _NetworkError(f"no usable {self._provider_name} backend (API key not set)")

        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                raw_result = self._provider.send(
                    system=system,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                if isinstance(raw_result, providers.ProviderResult):
                    result = raw_result
                else:
                    text, input_tokens, output_tokens = raw_result
                    result = providers.ProviderResult(text, input_tokens, output_tokens)
                self._last_route = {
                    "selected_provider": self._provider_name,
                    "selected_model": self._model,
                    "actual_provider": result.actual_provider,
                    "actual_model": result.actual_model,
                    "fallback_attempts": result.fallback_attempts,
                }
                if (self._routing_mode == "simple_byok" and self._user_id is not None
                        and result.actual_provider):
                    from memory import api_keys
                    api_keys.mark_used(self._user_id, result.actual_provider)
                # Cost logging must never be able to fail a real API call —
                # a DB write hiccup here shouldn't corrupt or crash a
                # response we already successfully received.
                try:
                    cost = self._tracker.log(
                        model=result.actual_model or self._model,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                        task_type=task_name,
                        # A server on this machine bills nothing; pricing it
                        # would put money that was never spent against the
                        # daily cap and stop a run for no reason.
                        is_local=self._provider.free or self._routing_mode == "shared_free",
                        session_id=self.session_id,
                        provider=self._provider_name,
                        selected_model=self._model,
                        actual_provider=result.actual_provider,
                        actual_model=result.actual_model,
                        routing_policy=(self._model if self._provider_name in
                                        {"freellmapi", "auto_byok"} else "direct"),
                        fallback_attempts=result.fallback_attempts,
                        fallback_trail=result.fallback_trail,
                        retry_count=attempt,
                        cost_known=getattr(self._provider, "billing_known", True),
                    )
                    logger.info(
                        "API call OK: task=%s in=%d out=%d cost=$%.4f",
                        task_name, result.input_tokens, result.output_tokens, cost,
                    )
                except Exception as log_exc:
                    logger.warning(
                        "Cost logging failed for task=%s (call still succeeded): %s",
                        task_name, log_exc,
                    )

                return result.text

            except Exception as exc:
                # How to read an error is the one thing that differs between
                # providers; what to do about it does not.
                kind = self._provider.classify(exc)
                try:
                    safe_message = self._redact_provider_error(exc)
                    self._tracker.log_provider_event(
                        session_id=self.session_id, task_type=task_name,
                        event_type="retry" if kind == providers.RETRY else "failure",
                        provider=self._provider_name, selected_model=self._model,
                        retry_count=attempt, error_type=type(exc).__name__,
                        error_message=safe_message,
                    )
                except Exception as log_exc:
                    logger.warning("Provider event logging failed for task=%s: %s",
                                   task_name, log_exc)
                if kind == providers.QUOTA:
                    raise _ProviderQuotaError(self._provider_name) from exc
                if kind == providers.AUTH:
                    raise _ProviderAuthError(self._provider_name) from exc
                if kind == providers.RETRY:
                    wait = _retry_wait()
                    logger.warning("%s: retrying attempt %d/%d in %.0fs (%s)",
                                   self._provider_name, attempt + 1, _MAX_RETRIES, wait, exc)
                    time.sleep(wait)
                    last_exc = exc
                    continue
                if kind == providers.NETWORK:
                    raise _NetworkError(str(exc)) from exc
                if "connection" in str(exc).lower() or "network" in str(exc).lower():
                    raise _NetworkError(str(exc)) from exc
                raise

        raise _NetworkError(
            f"API call failed after {_MAX_RETRIES} attempts (rate-limit or server errors)"
        ) from last_exc

    def _redact_provider_error(self, exc: Exception) -> str:
        """Remove every credential this model instance could have sent."""
        message = str(exc)
        secrets = {
            self._explicit_api_key or "",
            getattr(self._provider, "api_key", "") if self._provider is not None else "",
        }
        secrets.update(getattr(self._provider, "secrets", ()) if self._provider is not None else ())
        for secret in secrets:
            if secret:
                message = message.replace(secret, "[redacted]")
        return message


class _NetworkError(Exception):
    """Raised when the chosen API is unreachable, unauthorised, or has no key."""


class _ProviderQuotaError(Exception):
    """Internal quota signal; provider response text is deliberately not exposed."""


class _ProviderAuthError(Exception):
    """Internal authentication signal; never includes credentials."""


class InferenceUnavailable(RuntimeError):
    """Expected, resumable stop before a required inference capability."""


class ModelAPIDisabled(InferenceUnavailable):
    """The user deliberately disabled external model inference."""


class SharedProviderUnavailable(InferenceUnavailable):
    """The shared free hosted route is missing, exhausted, or unavailable."""


class BYOKProviderUnavailable(InferenceUnavailable):
    """The explicitly selected user-owned provider could not answer."""


class ProviderRouteMismatch(InferenceUnavailable):
    """An exact-model gateway request was substituted or could not be verified."""
