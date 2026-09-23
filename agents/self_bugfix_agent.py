"""
Self-BugFix Agent

Wraps pipeline phases with automatic retry + LLM-assisted error recovery.

Recovery strategies (in order):
1. Transient errors (network, rate-limit) → plain retry with backoff
2. JSON parse errors                       → ask LLM to reformat bad output
3. KeyError / AttributeError               → retry with explicit format hint
4. Persistent unknown errors               → log, emit warning, continue pipeline
"""

from __future__ import annotations

import json
import logging
import random
import time
import traceback
from typing import Any, Callable

import config

logger = logging.getLogger(__name__)

_TRANSIENT_KEYWORDS = ("connection", "timeout", "network", "rate limit", "503", "502", "500")

_JSON_REPAIR_SYSTEM = (
    "You are a JSON repair assistant. "
    "Return ONLY valid JSON — no markdown, no code fences, no explanation."
)

_MAX_RETRIES = 2          # up to 2 extra attempts (3 total)


def _accepts(fn: Callable, name: str) -> bool:
    import inspect
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


class SelfBugFixAgent:
    """
    Drop-in retry wrapper for pipeline phase functions.

    Usage:
        bugfix = SelfBugFixAgent(api_model, emit_fn)
        result = bugfix.wrap("Phase 3: Gap Analysis", gap_fn, arg1, arg2)
    """

    def __init__(self, api_model: Any, emit: Callable | None = None) -> None:
        self._api  = api_model
        self._emit = emit or (lambda t, d: None)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def wrap(
        self,
        phase_name: str,
        fn: Callable,
        *args: Any,
        max_retries: int = _MAX_RETRIES,
        **kwargs: Any,
    ) -> Any:
        """
        Execute fn(*args, **kwargs).  On failure, attempt up to max_retries
        auto-fix-and-retry cycles.  Returns the function's return value or
        raises the last exception if all attempts fail.
        """
        last_exc: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                return fn(*args, **kwargs)

            except Exception as exc:
                last_exc = exc
                tb = traceback.format_exc()

                if attempt >= max_retries:
                    break

                # 20-30 s: a retried phase re-sends its external requests
                wait = random.uniform(config.REQUEST_INTERVAL_MIN_S, config.REQUEST_INTERVAL_MAX_S)
                strategy = self._classify(exc)

                self._log(phase_name, attempt + 1, max_retries, exc, strategy)

                # Extra keyword arguments go only to functions that accept them:
                # none of the pipeline phases do, so injecting them made every
                # retry fail with a new TypeError instead of retrying.
                if strategy == "json_repair" and _accepts(fn, "_repaired_json"):
                    raw = getattr(exc, "text", None) or getattr(exc, "raw", None) or ""
                    if raw:
                        repaired = self._repair_json(raw, exc)
                        if repaired:
                            kwargs["_repaired_json"] = repaired

                elif strategy == "hint_retry" and _accepts(fn, "_bugfix_hint"):
                    hint = self._generate_hint(phase_name, exc, tb)
                    if hint:
                        kwargs["_bugfix_hint"] = hint

                elif strategy == "transient":
                    pass  # just wait and retry

                else:
                    # Unknown error — one more attempt then give up
                    pass

                time.sleep(wait)

        # All retries exhausted
        assert last_exc is not None
        logger.error(
            "[BugFix] %s failed after %d attempts: %s",
            phase_name, max_retries + 1, last_exc,
        )
        self._emit("bugfix_failed", {
            "phase": phase_name,
            "error": str(last_exc),
            "attempts": max_retries + 1,
        })
        raise last_exc

    def repair_json(self, bad_output: str, error: Exception | str) -> str:
        """Public helper: ask the LLM to fix a malformed JSON string."""
        return self._repair_json(bad_output, error) or bad_output

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _classify(self, exc: Exception) -> str:
        msg = str(exc).lower()
        if isinstance(exc, (json.JSONDecodeError, ValueError)) and "json" in msg:
            return "json_repair"
        if any(k in msg for k in _TRANSIENT_KEYWORDS):
            return "transient"
        if isinstance(exc, (KeyError, AttributeError, TypeError)):
            return "hint_retry"
        return "unknown"

    def _repair_json(self, bad_output: str, error: Any) -> str | None:
        """Ask the LLM to reformat bad_output as valid JSON."""
        prompt = (
            f"The following text was supposed to be JSON but failed to parse.\n"
            f"Error: {error}\n\n"
            f"Broken output:\n{bad_output[:4000]}\n\n"
            f"Return ONLY the corrected JSON. No markdown, no explanation."
        )
        try:
            fixed = self._api.generate(
                prompt,
                system=_JSON_REPAIR_SYSTEM,
                temperature=0.1,
            )
            # Validate that the repair actually produces parseable JSON
            json.loads(fixed)
            return fixed
        except Exception as e:
            logger.warning("[BugFix] JSON repair failed: %s", e)
            return None

    def _generate_hint(self, phase_name: str, exc: Exception, tb: str) -> str | None:
        """Ask the LLM to suggest what went wrong and how to correct it."""
        prompt = (
            f"A pipeline phase '{phase_name}' failed with this error:\n\n"
            f"{tb[-2000:]}\n\n"
            f"In one sentence, what is the most likely root cause and how should "
            f"the output format be corrected on the next attempt?"
        )
        try:
            return self._api.generate(prompt, temperature=0.2)
        except Exception:
            return None

    def _log(
        self,
        phase_name: str,
        attempt: int,
        max_retries: int,
        exc: Exception,
        strategy: str,
    ) -> None:
        msg = (
            f"[BugFix] {phase_name} — attempt {attempt}/{max_retries} "
            f"failed ({type(exc).__name__}: {exc}). "
            f"Strategy: {strategy}. Retrying…"
        )
        logger.warning(msg)
        self._emit("bugfix_retry", {
            "phase": phase_name,
            "attempt": attempt,
            "max_retries": max_retries,
            "error": str(exc),
            "strategy": strategy,
        })
