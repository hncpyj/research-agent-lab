"""
The paid-API model interface.

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
    Single interface for every paid API call, whichever provider is chosen.
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
    ) -> None:
        self._tracker = cost_tracker or CostTracker()
        self.session_id = session_id
        self._local_model = local_model  # fallback when API unavailable
        self._on_budget_stop = on_budget_stop
        self._budget_warned = False

        from tools import app_settings
        self._provider_name = provider or app_settings.api_provider()
        model = model or app_settings.api_model(self._provider_name)

        # A run belongs to somebody, and so does the key it spends. Given a
        # user, their own stored key is used; the server's `.env` key is only
        # theirs to use if this is their own machine or they own the server.
        if api_key is None and user_id is not None:
            from memory import api_keys
            api_key = api_keys.key_for(user_id, self._provider_name)

        # An empty api_key means "this run has no paid backend" — the old
        # behaviour when ANTHROPIC_API_KEY was unset — and must stay local.
        try:
            self._provider = providers.build(self._provider_name, api_key, model)
            self._model = self._provider.model
            self._api_available = True
        except providers.ProviderUnavailable as exc:
            logger.warning("%s — using the local model instead.", exc)
            self._provider = None
            self._model = model or self._provider_name
            self._api_available = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_local_model(self, local_model) -> None:
        """Inject or replace the local fallback model after construction."""
        self._local_model = local_model

    def over_budget(self) -> bool:
        """
        True once the day's API spend has reached API_DAILY_BUDGET_USD; every
        call then goes to the local model. Nothing stopped a retry loop from
        spending without limit before 2026-09-20, and a run that dies on
        exhausted credit mid-way leaves a half-finished study behind.
        """
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

        if not self._api_available or self.over_budget():
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
        except _NetworkError as exc:
            logger.warning("API unreachable: %s — switching to local fallback.", exc)
            self._api_available = False
            return self._local_fallback(prompt, system, task_name, max_tokens)
        except Exception as exc:
            # Anything _call_with_retry did not turn into _NetworkError and the
            # provider calls fatal: billing or credit errors, a model this key
            # may not use, a permission problem. The run continues locally
            # rather than dying half-way; a bug in our own code still raises.
            if self._provider is None or self._provider.classify(exc) != providers.FATAL:
                raise
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
                text, input_tokens, output_tokens = self._provider.send(
                    system=system,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                # Cost logging must never be able to fail a real API call —
                # a DB write hiccup here shouldn't corrupt or crash a
                # response we already successfully received.
                try:
                    cost = self._tracker.log(
                        model=self._model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        task_type=task_name,
                        # A server on this machine bills nothing; pricing it
                        # would put money that was never spent against the
                        # daily cap and stop a run for no reason.
                        is_local=self._provider.free,
                        session_id=self.session_id,
                    )
                    logger.info(
                        "API call OK: task=%s in=%d out=%d cost=$%.4f",
                        task_name, input_tokens, output_tokens, cost,
                    )
                except Exception as log_exc:
                    logger.warning(
                        "Cost logging failed for task=%s (call still succeeded): %s",
                        task_name, log_exc,
                    )

                return text

            except Exception as exc:
                # How to read an error is the one thing that differs between
                # providers; what to do about it does not.
                kind = self._provider.classify(exc)
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


class _NetworkError(Exception):
    """Raised when the chosen API is unreachable, unauthorised, or has no key."""
