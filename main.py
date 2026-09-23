"""
Entry point for the AI Research Agent system.

Usage:
    python main.py
    python main.py --topic "transformer attention efficiency"
    python main.py --session <session_id>   # resume an existing session

A brief that names its own dataset runs the study stages (data audit,
hypotheses, analysis plan, run, results, report, review) with the same gates
as the web UI, asking here at the terminal; briefs without one run the
ML-template phases.
"""

import argparse
import sys
import logging

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

import config
from agents.orchestrator import Orchestrator

console = Console()

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Research Agent — from vague topic to research hypotheses"
    )
    parser.add_argument(
        "--topic",
        type=str,
        default=None,
        help="Research topic (skips interactive prompt)",
    )
    parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="Resume an existing session by session_id",
    )
    parser.add_argument(
        "--max-papers",
        type=int,
        default=config.ARXIV_MAX_RESULTS,
        help=f"Max papers to collect (default: {config.ARXIV_MAX_RESULTS})",
    )
    parser.add_argument(
        "--skip-local",
        action="store_true",
        help="Skip loading local model (use API for all tasks — costs more)",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="List all saved sessions and their status, then exit",
    )
    parser.add_argument(
        "--experiment",
        action="store_true",
        help="Run only Phase 5 (experiment code generation) for an existing session",
    )
    parser.add_argument(
        "--run-experiment",
        action="store_true",
        dest="run_experiment",
        help=(
            "Run only Phase 6 (experiment execution + auto-fix) for an existing session. "
            "Requires --session <session_id>."
        ),
    )
    return parser.parse_args()


def print_banner() -> None:
    title = Text("AI Research Agent", style="bold cyan")
    subtitle = Text(
        "Literature Review → Gap Analysis → Hypothesis Generation",
        style="dim",
    )
    console.print(Panel.fit(title + "\n" + subtitle, border_style="cyan"))


def main() -> None:
    args = parse_args()
    print_banner()

    # --list-sessions: show saved sessions and exit (no API key needed)
    if args.list_sessions:
        from memory.note_db import NoteDB
        from rich.table import Table
        db = NoteDB()
        sessions = db.list_sessions()
        if not sessions:
            console.print("[yellow]No sessions found.[/]")
        else:
            table = Table(title="Saved Sessions", show_lines=True)
            table.add_column("Session ID", style="cyan", no_wrap=True)
            table.add_column("Topic", min_width=30)
            table.add_column("Status", style="yellow")
            table.add_column("Created", width=19)
            for s in sessions:
                table.add_row(
                    s["session_id"],
                    s["topic"],
                    s["status"],
                    s["created_at"],
                )
            console.print(table)
            console.print(
                "\n[dim]Resume a session with:[/] "
                "python main.py --session <session_id>"
            )
        sys.exit(0)

    # --experiment: run only Phase 5 for an existing session
    if args.experiment:
        if not args.session:
            console.print(
                "[red]--experiment requires --session <session_id>[/]\n"
                "[dim]Example: python main.py --session <id> --experiment[/]"
            )
            sys.exit(1)
        if not config.ANTHROPIC_API_KEY:
            console.print("[bold red]Error:[/] ANTHROPIC_API_KEY is not set.")
            sys.exit(1)
        from memory.note_db import NoteDB
        from models.api_model import APIModel
        from tools.cost_tracker import CostTracker
        from agents.experiment_agent import ExperimentAgent
        tracker = CostTracker()
        api = APIModel(cost_tracker=tracker)
        db = NoteDB()
        agent = ExperimentAgent(
            api_model=api,
            note_db=db,
            experiments_base_dir=config.EXPERIMENTS_DIR,
        )
        try:
            agent.run(session_id=args.session)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted. Progress saved.[/]")
        tracker.print_summary()
        sys.exit(0)

    # --run-experiment: run Phase 6 (execution) for an existing session
    if args.run_experiment:
        if not args.session:
            console.print(
                "[red]--run-experiment requires --session <session_id>[/]\n"
                "[dim]Example: python main.py --session <id> --run-experiment[/]"
            )
            sys.exit(1)
        if not config.ANTHROPIC_API_KEY:
            console.print("[bold red]Error:[/] ANTHROPIC_API_KEY is not set.")
            sys.exit(1)
        from memory.note_db import NoteDB
        from models.api_model import APIModel
        from tools.cost_tracker import CostTracker
        from agents.experiment_runner import ExperimentRunnerAgent
        tracker = CostTracker()
        api = APIModel(cost_tracker=tracker)
        db = NoteDB()
        agent = ExperimentRunnerAgent(
            api_model=api,
            note_db=db,
            experiments_base_dir=config.EXPERIMENTS_DIR,
        )
        try:
            agent.run(session_id=args.session)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted. Progress saved to DB.[/]")
        except RuntimeError as exc:
            console.print(f"\n[red]Experiment run failed:[/] {exc}")
        tracker.print_summary()
        sys.exit(0)

    # Validate API key early
    if not config.ANTHROPIC_API_KEY:
        console.print(
            "[bold red]Error:[/] ANTHROPIC_API_KEY environment variable is not set.\n"
            "Export it before running:\n"
            "  [dim]export ANTHROPIC_API_KEY=sk-ant-...[/]  (macOS / Linux)\n"
            "  [dim]set ANTHROPIC_API_KEY=sk-ant-...[/]      (Windows CMD)\n"
            "  [dim]$env:ANTHROPIC_API_KEY='sk-ant-...'[/]   (PowerShell)",
        )
        sys.exit(1)

    # Get topic
    if args.session:
        topic = None  # orchestrator will load from DB
        console.print(f"[cyan]Resuming session:[/] {args.session}")
    elif args.topic:
        topic = args.topic
    else:
        console.print("\n[bold]What is your research topic?[/]")
        console.print("[dim]Be as vague or specific as you like.[/]\n")
        try:
            topic = input("Topic: ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Cancelled.[/]")
            sys.exit(0)
        if not topic:
            console.print("[red]No topic entered. Exiting.[/]")
            sys.exit(1)

    orchestrator = Orchestrator(
        use_local_model=not args.skip_local,
        max_papers=args.max_papers,
    )

    try:
        orchestrator.run(
            topic=topic,
            session_id=args.session,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user. Progress saved.[/]")
        sys.exit(0)


if __name__ == "__main__":
    main()
