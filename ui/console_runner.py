"""
Running the study stages (S2-S9) from a terminal.

The redesigned pipeline lived only behind the web UI, because it talks to a
SessionRunner: it emits events and blocks on `wait_for_input` at the two
gates. `python main.py` therefore still ran the old ML-template phases, with
no data audit, no operationalization check and no plan approval — the same
run, started a different way, was held to different standards.

ConsoleRunner is that interface backed by stdout and input(), so the CLI runs
the same stages with the same gates.
"""

from __future__ import annotations

import threading
from typing import Any

from rich.console import Console

console = Console()

_QUIET = {"log", "phase_start", "phase_done", "phase_skip", "separator"}


class ConsoleRunner:
    """What StudyPipeline needs from a runner, answered at the terminal."""

    def __init__(self, session_id: str, quiet: bool = False) -> None:
        self.session_id = session_id
        self.waiting_step: str | None = None
        self.quiet = quiet
        self._stop_flag = threading.Event()

    # --- events ---------------------------------------------------------------
    def emit(self, event_type: str, data: Any = None) -> None:
        data = data or {}
        if event_type == "log":
            console.print(f"  [dim]{data.get('message', '')}[/]")
        elif event_type == "phase_start":
            console.print(f"\n[bold cyan]{data.get('name', '')}[/]")
        elif event_type in ("study_blocked", "error"):
            console.print(f"[red]{data.get('stage', '')}: {data.get('message', '')}[/]".strip(": "))
        elif event_type not in _QUIET and not self.quiet:
            console.print(f"  [dim]{event_type}[/]")

    # --- gates ----------------------------------------------------------------
    def wait_for_input(self, step: str, message: str) -> Any:
        from ui.study_runner import StudyStopped

        self.waiting_step = step
        console.print(f"\n[bold yellow]{message}[/]")
        try:
            answer = self._ask(step)
        except (KeyboardInterrupt, EOFError):
            self._stop_flag.set()
            raise StudyStopped()
        finally:
            self.waiting_step = None
        return answer

    def _ask(self, step: str) -> Any:
        if step == "hypothesis_selection":
            console.print("[dim]Hypothesis ids to study, comma separated (e.g. H1,H3):[/]")
            return [i.strip() for i in input("> ").split(",") if i.strip()]
        if step == "plan_approval":
            console.print("[dim]Path to an edited plan file, or blank to keep the plan as written. "
                          "Then 'y' to approve.[/]")
            path = input("plan file> ").strip()
            text = self._plan_text(path)
            approve = input("approve? [y/N] ").strip().lower().startswith("y")
            return {"text": text, "approve": approve}
        if step == "source_confirmation":
            answer = input("continue without it? [y/N] ").strip().lower()
            return {"proceed": answer.startswith("y")}
        return input("> ").strip()

    def _plan_text(self, path: str) -> str:
        from pathlib import Path

        from memory.note_db import NoteDB
        if path:
            return Path(path).read_text(encoding="utf-8")
        art = NoteDB().get_artifact(self.session_id, "plan")
        return art["content"].get("text", "") if art else ""

    def stop(self) -> None:
        self._stop_flag.set()

    def is_alive(self) -> bool:
        return False


def run_study(session_id: str, note_db, api_model) -> bool | None:
    """
    Run the study stages for a session whose brief declares a dataset.
    Returns True when the study finished, False when a stage stopped it, and
    None when this brief has no declared dataset (the caller keeps its own path).
    """
    from agents.data_audit import DataAuditError, declared_dataset
    from ui.study_runner import StudyPipeline, StudyStopped

    session = note_db.get_session(session_id)
    try:
        declared = declared_dataset(session)
    except DataAuditError as exc:
        note_db.save_artifact(session_id, "data_audit", {"error": str(exc)}, "blocked")
        console.print(f"[red]Data audit: {exc}[/]")
        return False
    if declared is None:
        return None

    runner = ConsoleRunner(session_id)
    try:
        return StudyPipeline(runner, note_db, api_model, declared).run()
    except StudyStopped:
        console.print("[yellow]Stopped.[/]")
        return False
