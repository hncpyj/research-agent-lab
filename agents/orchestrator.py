"""
Orchestrator: top-level controller that coordinates all agents.

Execution order:
  1. Load models (local + embedding + API)
  2. Init / resume session in SQLite
  3. PaperCollectionAgent       → top-K papers
  4. LiteratureReviewAgent      → structured extraction + comparison table
  5. GapAnalysisAgent           → gap report + research question (user picks)
  6. HypothesisAgent            → hypotheses + experiment designs
  7. ExperimentAgent            → generate runnable experiment codebase
  8. ExperimentRunnerAgent      → install deps, run, auto-fix errors, save results
  9. Print cost summary
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.rule import Rule

import config
from models.local_model import LocalModel, EmbeddingModel
from models.api_model import APIModel
from memory.vector_db import VectorDB
from memory.note_db import NoteDB
from tools.cost_tracker import CostTracker
from agents.paper_collection import PaperCollectionAgent
from agents.literature_review import LiteratureReviewAgent
from agents.gap_analysis import GapAnalysisAgent
from agents.hypothesis import HypothesisAgent
from agents.experiment_agent import ExperimentAgent
from agents.experiment_runner import ExperimentRunnerAgent

logger = logging.getLogger(__name__)
console = Console()


class Orchestrator:

    def __init__(
        self,
        use_local_model: bool = True,
        max_papers: int = config.ARXIV_MAX_RESULTS,
    ) -> None:
        self._use_local = use_local_model
        self._max_papers = max_papers

        # Shared infrastructure (initialised lazily in _setup)
        self._local_model: Optional[LocalModel]    = None
        self._embed_model: Optional[EmbeddingModel] = None
        self._api_model:   Optional[APIModel]       = None
        self._vector_db:   Optional[VectorDB]       = None
        self._note_db:     Optional[NoteDB]         = None
        self._cost_tracker: Optional[CostTracker]   = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(
        self,
        topic: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """
        Main pipeline.
        If `session_id` is given the session is resumed from that point.
        If `topic` is given a new session is created.
        """
        self._setup()

        # ---- Session management ----
        if session_id:
            session = self._note_db.get_session(session_id)
            if session is None:
                console.print(f"[red]Session {session_id} not found.[/]")
                sys.exit(1)
            topic = session["topic"]
            status = session["status"]
            console.print(
                f"[cyan]Resuming session[/] {session_id}  "
                f"status=[yellow]{status}[/]  topic: {topic}"
            )
        else:
            assert topic, "Either topic or session_id must be provided."
            session_id = self._note_db.create_session(topic)
            status = "started"
            console.print(f"[cyan]New session:[/] {session_id}")

        # Every call this run makes is costed against this session.
        self._api_model.session_id = session_id

        console.print(Rule(f"Topic: {topic}", style="cyan"))

        # Status ordering — used to decide which phases to skip on resume
        _STATUS_ORDER = [
            "started",
            "papers_collected",
            "review_done",
            "question_selected",
            "hypotheses_generated",
            "code_generated",
            "experiment_run",
        ]

        def _phase_needed(required_status: str) -> bool:
            """Return True if this phase has not been completed yet."""
            try:
                return _STATUS_ORDER.index(status) < _STATUS_ORDER.index(required_status)
            except ValueError:
                return True  # unknown status → run the phase

        # ---- Phase 1: Paper collection ----
        if _phase_needed("papers_collected"):
            papers = self._run_paper_collection(topic, session_id)
            status = "papers_collected"
        else:
            papers = self._load_papers_from_db(session_id)

        if not papers:
            console.print("[red]No papers found. Exiting.[/]")
            return

        # ---- Phase 2: Literature review ----
        if _phase_needed("review_done"):
            papers = self._run_literature_review(papers, session_id)
            status = "review_done"
        else:
            console.print(
                f"[cyan]Skipping literature review[/] (already done — {len(papers)} papers loaded)"
            )

        # Build context string for gap analysis
        review_agent = LiteratureReviewAgent(
            local_model=self._local_model,
            note_db=self._note_db,
        )
        lit_summary = review_agent.build_context_summary(papers)

        # ---- Phase 3: Gap analysis + Research question ----
        if _phase_needed("question_selected"):
            research_question = self._run_gap_analysis(
                topic, lit_summary, papers, session_id
            )
            status = "question_selected"
        else:
            # Resume: use stored research question
            session = self._note_db.get_session(session_id)
            from agents.gap_analysis import ResearchQuestion
            research_question = ResearchQuestion(
                index=0, text=session.get("research_question", "")
            )
            console.print(
                f"[cyan]Skipping gap analysis[/] (already done)\n"
                f"  Research question: {research_question.text}"
            )

        # ---- Declared dataset: the study stages (S2-S9), same as the web UI ----
        # A brief that names its own dataset gets the gated pipeline here too;
        # the ML-template phases below are only for briefs without one. Running
        # `python main.py` used to skip the audit, the operationalization check
        # and the plan approval entirely.
        from ui.console_runner import run_study
        finished = run_study(session_id, self._note_db, self._api_model)
        if finished is not None:
            console.print(Rule("Session Complete" if finished else "Session Stopped",
                               style="green" if finished else "yellow"))
            self._cost_tracker.print_summary()
            return

        # ---- Phase 4: Hypothesis generation ----
        if _phase_needed("hypotheses_generated"):
            self._run_hypothesis_generation(
                research_question, papers, session_id
            )
            status = "hypotheses_generated"
        else:
            console.print(
                "[cyan]Skipping hypothesis generation[/] (already done)"
            )
            hyps = self._note_db.get_hypotheses(session_id)
            console.print(f"  Loaded {len(hyps)} hypotheses from DB.")

        # ---- Phase 5: Experiment code generation ----
        if _phase_needed("code_generated"):
            self._run_experiment_generation(session_id)
        else:
            console.print(
                "[cyan]Skipping experiment generation[/] (already done)"
            )

        # ---- Phase 6: Experiment execution ----
        if _phase_needed("experiment_run"):
            self._run_experiment_execution(session_id)
        else:
            console.print(
                "[cyan]Skipping experiment execution[/] (already done)"
            )

        # ---- Done ----
        console.print(Rule("Session Complete", style="green"))
        self._cost_tracker.print_summary()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup(self) -> None:
        console.print("\n[dim]Initialising infrastructure…[/]")

        # Databases
        self._note_db    = NoteDB()
        self._vector_db  = VectorDB()
        self._vector_db.connect()
        self._cost_tracker = CostTracker()

        # API model (always needed — local fallback injected below)
        # session_id is attached in run(), once the session exists
        from tools import app_settings

        provider = app_settings.api_provider()
        self._api_model = APIModel(
            cost_tracker=self._cost_tracker,
            enabled=app_settings.use_api(),
            provider=provider,
            model=app_settings.api_model(provider),
        )

        # Local models (optional) — try Ollama first, then llama-cpp GGUF
        if self._use_local:
            # 1. Try Ollama (auto-starts server if needed, no GGUF file required)
            try:
                from models.ollama_model import OllamaModel
                console.print("[dim]Connecting to Ollama…[/]")
                _ollama = OllamaModel()
                _ollama.load()
                self._local_model = _ollama
                console.print(
                    f"[dim]Ollama model '{_ollama._resolved_model}' ready.[/]"
                )
            except Exception as ollama_exc:
                console.print(
                    f"[yellow]Ollama not available ({ollama_exc}) — trying llama-cpp GGUF…[/]"
                )
                # 2. Fall back to llama-cpp-python
                try:
                    self._local_model = LocalModel()
                    self._embed_model = EmbeddingModel()
                    console.print("[dim]Loading local LLM…[/]")
                    self._local_model.load()
                    console.print("[dim]Loading embedding model…[/]")
                    self._embed_model.load()
                except Exception as gguf_exc:
                    console.print(
                        f"[yellow]llama-cpp also failed ({gguf_exc}) — API-only mode.[/]"
                    )
                    self._local_model = None
                    self._embed_model = None

        # Inject local model into API model so it can fall back when offline
        if self._local_model is not None:
            self._api_model.set_local_model(self._local_model)
            console.print(
                "[dim]Local model registered as API offline fallback.[/]"
            )

        console.print("[green]Infrastructure ready.[/]\n")

    # ------------------------------------------------------------------
    # Phase runners
    # ------------------------------------------------------------------

    def _run_paper_collection(self, topic: str, session_id: str):
        if self._embed_model is None:
            console.print(
                "[yellow]No embedding model: paper ranking by similarity disabled.[/]"
            )
            embed = _UnavailableEmbedModel()
        else:
            embed = self._embed_model

        agent = PaperCollectionAgent(
            local_model=self._local_model,
            embed_model=embed,
            vector_db=self._vector_db,
            note_db=self._note_db,
            top_k=min(self._max_papers, config.ARXIV_TOP_K),
            keyword_model=self._api_model if self._api_model.is_loaded else None,
            allow_lexical_ranking=True,
        )
        papers = agent.run(topic=topic, session_id=session_id)
        self._note_db.update_session(session_id, status="papers_collected")
        return papers

    def _run_literature_review(self, papers, session_id: str):
        self._api_model.ensure_available("Literature Review")
        agent = LiteratureReviewAgent(
            local_model=self._api_model,
            note_db=self._note_db,
        )
        enriched = agent.run(papers=papers, session_id=session_id)
        self._note_db.update_session(session_id, status="review_done")
        return enriched

    def _run_gap_analysis(self, topic, lit_summary, papers, session_id):
        self._api_model.ensure_available("Gap Analysis")
        agent = GapAnalysisAgent(
            api_model=self._api_model,
            note_db=self._note_db,
        )
        return agent.run(
            topic=topic,
            literature_summary=lit_summary,
            papers=papers,
            session_id=session_id,
        )

    def _run_hypothesis_generation(self, research_question, papers, session_id):
        self._api_model.ensure_available("Hypothesis Generation")
        embed = self._embed_model or _UnavailableEmbedModel()
        agent = HypothesisAgent(
            api_model=self._api_model,
            embed_model=embed,
            vector_db=self._vector_db,
            note_db=self._note_db,
        )
        result = agent.run(
            research_question=research_question,
            papers=papers,
            session_id=session_id,
        )
        self._note_db.update_session(session_id, status="hypotheses_generated")
        return result

    def _run_experiment_generation(self, session_id: str) -> None:
        """Phase 5: generate experiment code for a selected hypothesis."""
        agent = ExperimentAgent(
            api_model=self._api_model,
            note_db=self._note_db,
            experiments_base_dir=config.EXPERIMENTS_DIR,
        )
        agent.run(session_id=session_id)
        self._note_db.update_session(session_id, status="code_generated")
        self._run_pre_execution_check(session_id)

    def _run_pre_execution_check(self, session_id: str) -> None:
        """
        Fast domain-alignment check between Phase 5 (code generation) and
        Phase 6 (execution) — catches a wrong-domain codebase (e.g. RL
        environment code for a retrieval hypothesis) before burning compute
        running it. Never blocks the pipeline; just warns loudly.
        """
        try:
            from agents.quality_review import QualityReviewAgent
            agent = QualityReviewAgent(api_model=self._api_model, note_db=self._note_db)
            report = agent.pre_execution_check(session_id)
            for f in report.fails:
                console.print(
                    f"[bold red]⚠ Pre-execution check FAILED:[/] {f.title}\n"
                    f"  {f.detail}\n  [dim]Fix:[/] {f.fix}"
                )
            if not report.fails:
                console.print("[dim]Pre-execution domain-alignment check: OK.[/]")
        except Exception as exc:
            logger.warning("Pre-execution check failed to run: %s", exc)

    def _run_experiment_execution(self, session_id: str) -> None:
        """Phase 6: run generated experiment code and persist results."""
        agent = ExperimentRunnerAgent(
            api_model=self._api_model,
            note_db=self._note_db,
            experiments_base_dir=config.EXPERIMENTS_DIR,
        )
        agent.run(session_id=session_id)
        self._note_db.update_session(session_id, status="experiment_run")

    # ------------------------------------------------------------------

    def _load_papers_from_db(self, session_id: str):
        """Reconstruct PaperRecord objects from SQLite for session resume."""
        from tools.arxiv_fetcher import PaperRecord
        rows = self._note_db.get_papers(session_id)
        papers: list[PaperRecord] = []
        for r in rows:
            p = PaperRecord(
                arxiv_id=r["arxiv_id"],
                title=r["title"] or "",
                authors=r["authors"].split(", ") if r.get("authors") else [],
                year=r["year"] or 0,
                url=r["url"] or "",
                abstract=r["abstract"] or "",
                pdf_path=Path(r["pdf_path"]) if r.get("pdf_path") else None,
                doi=r.get("doi") or "",
                source=r.get("source") or "arxiv",
                fulltext_id=r.get("fulltext_id") or "",
                method=r.get("method", ""),
                limitation=r.get("limitation", ""),
                future_work=r.get("future_work") or "",
                findings=r.get("findings") or "",
                text_source=r.get("text_source") or "",
                dataset=r.get("dataset", ""),
                metric=r.get("metric", ""),
                contribution=r.get("contribution", ""),
                replication_possible=bool(r.get("replication_possible", 0)),
                code_available=bool(r.get("code_available", 0)),
            )
            papers.append(p)
        console.print(f"[cyan]Loaded {len(papers)} papers from previous session.[/]")
        return papers


# ---------------------------------------------------------------------------
# Fallback embedding model (zero vectors) when no local model is available
# ---------------------------------------------------------------------------
class _UnavailableEmbedModel:
    """Explicit absence; callers degrade to lexical/unranked behavior."""

    is_loaded = False

    def embed(self, _text: str):
        raise RuntimeError("no real embedding backend is configured")

    def embed_batch(self, _texts: list[str]):
        raise RuntimeError("no real embedding backend is configured")
