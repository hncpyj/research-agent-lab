"""
Degradation log — makes "best-effort, never blocks the pipeline" paths
honest instead of silent.

Three separate incidents on 2026-09-12 had the exact same shape: a
best-effort component (Semantic Scholar canon-seeding, embedding-based
paper ranking, the Anthropic API itself) failed or was unavailable, the
code caught the exception and fell back to something much weaker, and
nothing downstream — the gap report, the UI, the LLM writing "no study
exists" — ever learned a degraded path had been taken. `logger.warning()`
goes to a log file nobody is reading; it doesn't reach the next phase's
prompt or the person looking at the report. "Never blocks the pipeline"
had, in practice, become "never tells anyone."

DegradationLog persists these to the `degradations` table instead, so a
later phase can fold "here is what actually went wrong upstream" directly
into its own prompt (see GapAnalysisAgent's COLLECTION HEALTH block) rather
than reasoning from a paper set it doesn't know is compromised.
"""

from __future__ import annotations

from typing import Callable, Optional

_ICONS = {"info": "i", "warn": "⚠", "critical": "\U0001f6d1"}


class _PhaseGuard:
    """
    Context manager returned by DegradationLog.phase(). A step inside it must
    call ok() to count as successful; leaving the block any other way — an
    early return, an exception, a forgotten ok() — is recorded as critical.

    Four silent failures (ranking no-op, 0 canon papers, 0 cost-log rows, a
    data check that returned early without its label) each depended on
    someone remembering to report on that particular code path. With the
    guard, reporting is the default and success is what has to be stated, so
    a new code path cannot fail silently by construction.
    """

    def __init__(self, log: "DegradationLog", phase: int, component: str) -> None:
        self._log = log
        self._phase = phase
        self._component = component
        self._succeeded = False
        self._failure: Optional[str] = None

    def ok(self) -> None:
        self._succeeded = True

    def fail(self, reason: str) -> None:
        self._failure = reason

    def __enter__(self) -> "_PhaseGuard":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self._log.record(self._phase, self._component, "critical",
                             f"{self._component} failed: {type(exc).__name__}: {exc}")
        elif self._failure is not None:
            self._log.record(self._phase, self._component, "critical",
                             f"{self._component} failed: {self._failure}")
        elif not self._succeeded:
            self._log.record(self._phase, self._component, "critical",
                             f"{self._component} ended without confirming success")
        return False  # never swallow exceptions


class DegradationLog:
    """Records silent-failure events for one session so no best-effort
    fallback path can hide what it did.

    `notify`, when given, is normally a module's own (possibly
    QueueConsole-patched) `console.print` — this reuses whichever
    transport that module already has to the CLI terminal or the Web UI's
    live log, instead of wiring a second notification path.
    """

    def __init__(
        self,
        note_db,
        session_id: str,
        notify: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._ndb = note_db
        self._session_id = session_id
        self._notify = notify

    def record(self, phase: int, component: str, severity: str, message: str) -> None:
        """severity: 'info' | 'warn' | 'critical'."""
        try:
            self._ndb.save_degradation(self._session_id, phase, component, severity, message)
        except Exception:
            pass  # the degradation log itself must never break the pipeline
        if self._notify:
            # Plain text, no rich markup — `notify` may be a CLI/QueueConsole
            # console.print (which understands rich tags) or a raw WebSocket
            # log emitter (which does not), so this stays renderer-agnostic.
            icon = _ICONS.get(severity, "⚠")
            self._notify(f"{icon} {component}: {message}")

    def phase(self, phase: int, component: str) -> _PhaseGuard:
        """Guard a step: `with log.phase(3, "data_check") as gate: ...; gate.ok()`."""
        return _PhaseGuard(self, phase, component)

    def _get(self, phase: Optional[int]) -> list[dict]:
        try:
            items = self._ndb.get_degradations(self._session_id, phase=phase)
            return list(items) if items else []
        except Exception:
            return []

    def for_phase(self, phase: int) -> list[dict]:
        return self._get(phase)

    def summary_for_prompt(self, phase: Optional[int] = None) -> str:
        """Rendered for inclusion in a later phase's LLM prompt."""
        items = self._get(phase)
        if not items:
            return "No degradations recorded."
        return "\n".join(
            f"- [{d['severity']}] {d['component']}: {d['message']}" for d in items
        )

    def has_critical(self, phase: Optional[int] = None) -> bool:
        return any(d["severity"] == "critical" for d in self._get(phase))
