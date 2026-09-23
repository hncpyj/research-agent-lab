"""
Background runner for the research pipeline.

Each SessionRunner runs in a background thread and emits events
to a threading.Queue that the FastAPI WebSocket handler consumes.

Interactive steps (gap analysis question selection) pause the thread
until the user submits a choice via the REST API.
"""

from __future__ import annotations

import io
import logging
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

# Add project root to path so agents/ can be imported
sys.path.insert(0, str(Path(__file__).parent.parent))

import config

logger = logging.getLogger(__name__)

# How often a working run touches its row in the registry. Frequent enough that
# a stopped server is noticed quickly, rare enough to cost nothing.
_HEARTBEAT_EVERY_S = 15.0


class _DummyVectorDB:
    """
    No-op VectorDB for the web UI.
    ChromaDB (used by the real VectorDB) is incompatible with Python 3.14,
    and the web UI reads papers/hypotheses from SQLite anyway — not from
    the vector store — so this is safe to skip entirely.
    """
    def connect(self): pass
    def add_paper(self, *a, **kw): pass
    def add_papers_batch(self, *a, **kw): pass
    def search(self, *a, **kw): return []
    def query(self, *a, **kw): return []
    def delete_session(self, *a, **kw): pass
    def close(self): pass


# ─────────────────────────────────────────────────────────────────────────────
# QueueConsole
# ─────────────────────────────────────────────────────────────────────────────

class QueueConsole:
    """
    Drop-in replacement for rich.Console.
    Renders markup/objects to plain text and emits log events to a queue.
    """

    def __init__(self, event_queue: queue.Queue) -> None:
        self._q = event_queue
        self._buf = io.StringIO()
        try:
            from rich.console import Console as RichConsole
            self._rc = RichConsole(
                file=self._buf,
                highlight=False,
                markup=True,
                no_color=True,
                width=100,
            )
        except ImportError:
            self._rc = None

    def _render(self, *args, **kwargs) -> str:
        if self._rc is None:
            return " ".join(str(a) for a in args)
        self._buf.seek(0)
        self._buf.truncate(0)
        kwargs.pop("end", None)  # suppress extra blank lines from Panel
        self._rc.print(*args, **kwargs)
        return self._buf.getvalue()

    def print(self, *args, **kwargs) -> None:
        text = self._render(*args, **kwargs).rstrip()
        if text:
            self._q.put({"type": "log", "data": {"message": text}})

    def rule(self, title: str = "", **kwargs) -> None:
        self._q.put({"type": "separator", "data": {"title": str(title)}})

    def log(self, *args, **kwargs) -> None:
        self.print(*args, **kwargs)

    # Support `with console:` context manager used by some rich helpers
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def __getattr__(self, name: str):
        """
        Delegate any attribute not defined on QueueConsole to the underlying
        Rich Console.  This covers internal Rich methods like get_time(),
        _detect_color_system(), size, options, etc. that Progress bars and
        Live displays call directly on the console object.
        """
        rc = object.__getattribute__(self, "_rc")
        if rc is not None:
            return getattr(rc, name)
        raise AttributeError(f"'QueueConsole' object has no attribute '{name}'")


# ─────────────────────────────────────────────────────────────────────────────
# SessionRunner
# ─────────────────────────────────────────────────────────────────────────────

class SessionRunner:
    """
    Runs the research pipeline phases in a background thread.
    Exposes a threading.Queue for event streaming and a threading.Event
    for interactive question selection.
    """

    def __init__(
        self,
        session_id: str,
        topic: Optional[str] = None,
        background: Optional[str] = None,
        goals: Optional[str] = None,
        constraints: Optional[str] = None,
        use_api: bool = True,
        only: Optional[str] = None,   # run this one stage (agents/stages.py) and stop
    ) -> None:
        self.session_id = session_id
        self.only = only
        # The place this run took in the plan's allowance, settled when it ends.
        self.run_id: str = ""
        self.topic = topic
        self.background = background or ""
        self.goals = goals or ""
        self.constraints = constraints or ""
        self.use_api = use_api
        self._q: queue.Queue = queue.Queue()
        self._question_event = threading.Event()
        self._question_choice: Optional[Any] = None
        self._question_override = False
        self._thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._current_proc: Optional[Any] = None  # subprocess.Popen set by runner agent
        # Gates after the research question (hypothesis selection, plan approval)
        self._input_event = threading.Event()
        self._input_payload: Any = None
        self.waiting_step: Optional[str] = None
        self._last_touch = 0.0

    # ── Public interface ──────────────────────────────────────────────────

    def start(self) -> None:
        if self.run_id:
            try:
                from memory import quota
                quota.start(self.run_id, self.session_id)
            except Exception as exc:
                logger.warning("Could not mark run %s as started: %s", self.run_id, exc)
        # Written where a restart cannot lose it: if this process dies, the
        # next one finds the row and turns it into an interrupted run.
        try:
            from memory import runs
            runs.begin(self.session_id, self.run_id, self.only or "full")
        except Exception as exc:
            logger.warning("Could not record that %s started: %s", self.session_id, exc)
        self._thread = threading.Thread(target=self._safe_run, daemon=True, name=f"runner-{self.session_id[:8]}")
        self._thread.start()

    def select_question(self, choice: Any, override: bool = False) -> None:
        """Called by the HTTP handler when user picks a research question."""
        self._question_choice = choice
        self._question_override = override
        self._question_event.set()

    def wait_for_input(self, step: str, message: str) -> Any:
        """Block the pipeline until the user answers `step` through provide_input(). Raises StudyStopped on stop."""
        from ui.study_runner import StudyStopped
        self._input_event.clear()
        self._input_payload = None
        self.waiting_step = step
        self.emit("waiting_for_input", {"step": step, "message": message})
        self._input_event.wait()
        self.waiting_step = None
        if self._stop_flag.is_set():
            raise StudyStopped()
        return self._input_payload

    def provide_input(self, step: str, payload: Any) -> bool:
        """Called by the HTTP handler. False if the pipeline is not waiting for this step."""
        if self.waiting_step != step:
            return False
        self._input_payload = payload
        self._input_event.set()
        return True

    def stop(self) -> None:
        """Request the runner to stop. Kills any running subprocess."""
        self._stop_flag.set()
        # Unblock question-wait so the thread can exit
        self._question_event.set()
        self._input_event.set()
        # Kill subprocess if one is running
        proc = self._current_proc
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass

    def emit(self, event_type: str, data: Any = None) -> None:
        self._q.put({"type": event_type, "data": data or {}})
        self._touch()

    def _touch(self) -> None:
        """Say the run is still alive, at most once every few seconds."""
        now = time.monotonic()
        if now - self._last_touch < _HEARTBEAT_EVERY_S:
            return
        self._last_touch = now
        try:
            from memory import runs
            runs.heartbeat(self.session_id)
        except Exception as exc:
            logger.debug("Heartbeat for %s failed: %s", self.session_id, exc)

    def get_event(self, timeout: float = 0.05) -> Optional[dict]:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def queue_empty(self) -> bool:
        return self._q.empty()

    # ── Thread entry point ────────────────────────────────────────────────

    def _safe_run(self) -> None:
        outcome, reason = "completed", ""
        try:
            self._run()
        except Exception as exc:
            logger.exception("Pipeline crashed: %s", exc)
            # What the person reading the page needs, with the traceback kept
            # underneath rather than put first.
            from ui.failures import describe
            self.emit("error", describe(exc).as_dict())
            # A crash in our own code is our fault, not the user's allowance.
            outcome, reason = "failed_system", f"{type(exc).__name__}: {exc}"
        finally:
            if self._stop_flag.is_set() and outcome == "completed":
                outcome, reason = "cancelled", "stopped by the user"
            self._settle_run(outcome, reason)
            # However this ended, it ended here: no later startup should find
            # it and report it as interrupted.
            try:
                from memory import runs
                runs.finish(self.session_id)
            except Exception as exc:
                logger.warning("Could not clear the run record for %s: %s", self.session_id, exc)
            self.emit("done", {})

    def _settle_run(self, outcome: str, reason: str = "") -> None:
        """Close this run's place in the allowance, exactly once."""
        if not self.run_id:
            return
        try:
            from memory import quota
            quota.settle(self.run_id, outcome, reason)
        except Exception as exc:                  # bookkeeping must not break a run
            logger.warning("Could not settle run %s: %s", self.run_id, exc)
        finally:
            self.run_id = ""

    # ── Monkey-patch module consoles ──────────────────────────────────────

    def _patch_consoles(self, qc: QueueConsole) -> None:
        module_names = [
            "agents.paper_collection",
            "agents.literature_review",
            "agents.gap_analysis",
            "agents.hypothesis",
            "agents.experiment_agent",
            "agents.experiment_runner",
            "agents.orchestrator",
        ]
        import importlib
        for name in module_names:
            try:
                mod = importlib.import_module(name)
                if hasattr(mod, "console"):
                    mod.console = qc
            except ImportError:
                pass

    # ── Main pipeline ─────────────────────────────────────────────────────

    def _build_enhanced_topic(self, base_topic: str) -> str:
        """Combine topic + optional detail fields into a richer prompt string."""
        parts = [base_topic]
        if self.background:
            parts.append(f"\nBackground / context: {self.background}")
        if self.goals:
            parts.append(f"\nResearch goals: {self.goals}")
        if self.constraints:
            parts.append(f"\nConstraints / requirements: {self.constraints}")
        return "".join(parts)

    def _run(self) -> None:
        qc = QueueConsole(self._q)
        self._patch_consoles(qc)

        self.emit("log", {"message": "Initialising research pipeline…"})

        from datetime import datetime as _datetime
        from memory.note_db import NoteDB
        from models.api_model import APIModel
        from tools.cost_tracker import CostTracker

        run_started_at = _datetime.utcnow().isoformat(timespec="seconds")
        note_db = NoteDB()
        cost_tracker = CostTracker()
        def _budget_stop(spent: float, cap: float) -> None:
            """A run that quietly switches backend mid-way must say so."""
            from agents.degradation import DegradationLog
            message = (f"API spend today reached ${spent:.2f} of the ${cap:.2f} daily cap "
                       "(API_DAILY_BUDGET_USD). Every call from here on is answered by the "
                       "local model, which is weaker.")
            DegradationLog(note_db, self.session_id,
                           notify=lambda m: self.emit("log", {"message": m})).record(
                0, "api_budget", "critical", message)
            self.emit("log", {"message": message})

        # Whose key this run spends: the person the session belongs to.
        owner_id = note_db.session_owner(self.session_id) or ""
        api_model = APIModel(cost_tracker=cost_tracker, on_budget_stop=_budget_stop,
                             session_id=self.session_id, user_id=owner_id)

        # Honour the global API toggle — if disabled, go straight to local.
        if not self.use_api:
            api_model._api_available = False
            self.emit("log", {"message": "Anthropic API disabled — using local model only."})

        # Try to load a local model for API fallback.
        # Priority: Ollama (server-based, auto-start) → llama-cpp GGUF → none
        _local_loaded = False
        try:
            from models.ollama_model import OllamaModel
            _lm = OllamaModel()
            _lm.load()
            api_model.set_local_model(_lm)
            self.emit("log", {
                "message": f"Ollama '{_lm._resolved_model}' ready — API fallback active."
            })
            _local_loaded = True
        except Exception as _ollama_exc:
            self.emit("log", {
                "message": f"Ollama not available ({_ollama_exc}). Trying local GGUF…"
            })

        if not _local_loaded:
            try:
                from models.local_model import LocalModel
                _lm = LocalModel()
                _lm.load()
                api_model.set_local_model(_lm)
                self.emit("log", {"message": "Local GGUF model loaded — API fallback ready."})
            except Exception as _gguf_exc:
                self.emit("log", {
                    "message": f"No local model available ({_gguf_exc}). API-only mode."
                })

        # Resolve topic + status
        session = note_db.get_session(self.session_id)
        if session is None:
            self.emit("error", {"message": f"Session {self.session_id} not found."})
            return
        if self.topic is None:
            self.topic = session["topic"]

        status = session["status"]

        # clean_topic  → arXiv search keywords (Phase 1-2); must stay short
        # rich_topic   → LLM prompts for gap analysis, hypotheses, etc. (Phase 3+)
        clean_topic = self.topic
        rich_topic  = self._build_enhanced_topic(self.topic)

        self.emit("session_info", {
            "topic": clean_topic,
            "status": status,
            "session_id": self.session_id,
        })

        from agents.self_bugfix_agent import SelfBugFixAgent
        bugfix = SelfBugFixAgent(api_model, self.emit)

        # Legacy phases and study stages share one order. A status missing here
        # used to count as "nothing done": on 2026-09-14 a session at
        # data_audited re-ran paper collection and gap analysis on resume.
        STATUS_ORDER = [
            "started",
            "papers_collected",
            "review_done",
            "question_selected",
            "data_audited",
            "hypotheses_generated",
            "hypotheses_selected",
            "plan_approved",
            "code_generated",
            "experiment_run",
            "report_written",
            "reviewed",
        ]
        if status not in STATUS_ORDER:
            self.emit("error", {"message": f"Unknown session status {status!r}; not resuming."})
            return

        def needed(req: str) -> bool:
            return STATUS_ORDER.index(status) < STATUS_ORDER.index(req)

        def check_stop() -> bool:
            if self._stop_flag.is_set():
                self.emit("log", {"message": "⏹ Pipeline stopped by user."})
                return True
            return False

        def finished_requested_stage() -> bool:
            """
            True when the one stage the caller asked for is done. Running a
            single stage is how someone who only wants the paper search, or
            who brought their own papers, uses this (agents/stages.py).
            """
            if not self.only:
                return False
            from agents.stages import BY_KEY
            stage = BY_KEY.get(self.only)
            if stage is None:
                return False
            current = (note_db.get_session(self.session_id) or {}).get("status", "started")
            if current not in STATUS_ORDER or stage.status_after not in STATUS_ORDER:
                return False
            if STATUS_ORDER.index(current) < STATUS_ORDER.index(stage.status_after):
                return False
            self.emit("stage_done", {"stage": self.only, "status": current})
            self.emit("log", {"message": f"Stage '{self.only}' finished; stopping here as asked."})
            self.emit("pipeline_complete", {"session_id": self.session_id, "stage": self.only})
            return True

        # ── Phase 1: Paper Collection ─────────────────────────────────────
        # Uses clean_topic so arXiv gets only a short search string, not the
        # full background/goals/constraints text which causes HTTP 500 errors.
        if check_stop() or finished_requested_stage(): return
        if needed("papers_collected"):
            self.emit("phase_start", {"phase": 1, "name": "Paper Collection"})
            papers = bugfix.wrap("Phase 1: Paper Collection",
                                 self._phase_paper_collection,
                                 clean_topic, note_db, api_model, qc)
            note_db.update_session(self.session_id, status="papers_collected")
            self.emit("phase_done", {"phase": 1, "name": "Paper Collection"})
        else:
            papers = self._load_papers(note_db)
            self.emit("phase_skip", {"phase": 1, "name": "Paper Collection"})

        papers_data = [
            {
                "title": p.title,
                "authors": ", ".join(p.authors) if p.authors else "",
                "year": p.year,
                "url": p.url,
                "abstract": (p.abstract[:300] + "…") if len(p.abstract) > 300 else p.abstract,
                "method": p.method or "",
                "limitation": p.limitation or "",
            }
            for p in papers
        ]
        self.emit("papers_collected", {"papers": papers_data})

        if not papers:
            self.emit("error", {"message": "No papers collected. Pipeline stopped."})
            return

        # ── Phase 2: Literature Review ────────────────────────────────────
        if check_stop() or finished_requested_stage(): return
        if needed("review_done"):
            self.emit("phase_start", {"phase": 2, "name": "Literature Review"})
            papers = bugfix.wrap("Phase 2: Literature Review",
                                 self._phase_literature_review,
                                 papers, note_db, qc, api_model)
            note_db.update_session(self.session_id, status="review_done")
            self.emit("phase_done", {"phase": 2, "name": "Literature Review"})
        else:
            self.emit("phase_skip", {"phase": 2, "name": "Literature Review"})

        from agents.literature_review import LiteratureReviewAgent
        lit_summary = LiteratureReviewAgent(
            local_model=None, note_db=note_db
        ).build_context_summary(papers)

        # ── Phase 3: Gap Analysis ─────────────────────────────────────────
        # From here on, rich_topic includes background/goals/constraints
        # to steer the LLM toward the user's specific intent.
        if check_stop() or finished_requested_stage(): return
        if needed("question_selected"):
            self.emit("phase_start", {"phase": 3, "name": "Gap Analysis"})
            rq = bugfix.wrap("Phase 3: Gap Analysis",
                             self._phase_gap_analysis,
                             rich_topic, lit_summary, papers, note_db, api_model)
            if self._stop_flag.is_set() or rq is None: return
            self.emit("phase_done", {"phase": 3, "name": "Gap Analysis"})
        else:
            self.emit("phase_skip", {"phase": 3, "name": "Gap Analysis"})
            s = note_db.get_session(self.session_id)
            from agents.gap_analysis import ResearchQuestion
            rq = ResearchQuestion(index=0, text=s.get("research_question", ""))
            self.emit("research_question", {"text": rq.text, "index": 0})
            # Re-emit stored gap report if available
            if s.get("gap_report"):
                self.emit("gap_report", {"content": s["gap_report"]})
            if s.get("gap_validation"):
                try:
                    import json as _json
                    self.emit("gap_validation", {"findings": _json.loads(s["gap_validation"])})
                except Exception:
                    pass
            # Re-emit stored quality review if available (Phase 7 already done)
            if s.get("quality_review"):
                try:
                    import json as _json
                    self.emit("quality_review", _json.loads(s["quality_review"]))
                except Exception:
                    pass
            # Re-emit stored report if available (Phase 8 already done)
            if s.get("report"):
                try:
                    import json as _json
                    self.emit("report", _json.loads(s["report"]))
                except Exception:
                    pass

        # ── Declared dataset: study stages S2-S9 (ui/study_runner.py) ─────
        # The legacy phases below (ML templates) are only for briefs without a
        # dataset. A declared dataset that cannot be read stops here; it never
        # falls back to them.
        if check_stop() or finished_requested_stage(): return
        from agents.data_audit import DataAuditError, declared_dataset
        try:
            declared = declared_dataset(note_db.get_session(self.session_id))
        except DataAuditError as exc:
            note_db.save_artifact(self.session_id, "data_audit", {"error": str(exc)}, "blocked")
            self.emit("study_blocked", {"stage": "Data audit", "message": str(exc)})
            self.emit("error", {"message": f"Data audit: {exc}"})
            return
        if declared is not None:
            from ui.study_runner import StudyPipeline, StudyStopped
            try:
                finished = StudyPipeline(self, note_db, api_model, declared).run()
            except StudyStopped:
                self.emit("log", {"message": "⏹ Pipeline stopped by user."})
                return
            if finished:
                self.emit("pipeline_complete", {"session_id": self.session_id})
            return

        # ── Phase 4: Hypothesis Generation ───────────────────────────────
        if check_stop() or finished_requested_stage(): return
        if needed("hypotheses_generated"):
            self.emit("phase_start", {"phase": 4, "name": "Hypothesis Generation"})
            bugfix.wrap("Phase 4: Hypothesis Generation",
                        self._phase_hypothesis,
                        rq, papers, note_db, api_model)
            note_db.update_session(self.session_id, status="hypotheses_generated")
            self.emit("phase_done", {"phase": 4, "name": "Hypothesis Generation"})
        else:
            self.emit("phase_skip", {"phase": 4, "name": "Hypothesis Generation"})

        hyps = note_db.get_hypotheses(self.session_id)
        self.emit("hypotheses", {
            "hypotheses": [
                {
                    "id": h["hypothesis_id"],
                    "content": h["content"],
                    "score": h.get("feasibility_score"),
                    "status": h.get("status", "candidate"),
                }
                for h in hyps
            ]
        })

        # ── Phase 5: Experiment Code Generation ──────────────────────────
        if check_stop() or finished_requested_stage(): return
        if needed("code_generated"):
            self.emit("phase_start", {"phase": 5, "name": "Experiment Code Generation"})
            bugfix.wrap("Phase 5: Experiment Code Generation",
                        self._phase_experiment_code,
                        note_db, api_model)
            note_db.update_session(self.session_id, status="code_generated")
            self.emit("phase_done", {"phase": 5, "name": "Experiment Code Generation"})
        else:
            self.emit("phase_skip", {"phase": 5, "name": "Experiment Code Generation"})

        # ── Phase 6: Experiment Execution ─────────────────────────────────
        if check_stop() or finished_requested_stage(): return
        if needed("experiment_run"):
            self.emit("phase_start", {"phase": 6, "name": "Experiment Execution"})
            self._phase_experiment_run(note_db, api_model)
            note_db.update_session(self.session_id, status="experiment_run")
            self.emit("phase_done", {"phase": 6, "name": "Experiment Execution"})
        else:
            self.emit("phase_skip", {"phase": 6, "name": "Experiment Execution"})

        # ── Phase 7: Quality Review ────────────────────────────────────
        # Automated peer-review simulation — always runs, never blocks pipeline.
        if check_stop() or finished_requested_stage(): return
        self.emit("phase_start", {"phase": 7, "name": "Quality Review"})
        quality_report = self._phase_quality_review(note_db, api_model)
        qr_dict = quality_report.as_dict()
        self.emit("quality_review", qr_dict)
        # Persist so it survives page refresh
        try:
            import json as _json
            note_db.update_session(self.session_id, quality_review=_json.dumps(qr_dict))
        except Exception as _e:
            logger.warning("Could not persist quality review: %s", _e)
        self.emit("phase_done", {"phase": 7, "name": "Quality Review"})

        # Cost summary
        try:
            summary = cost_tracker.session_summary()
            total = cost_tracker.total_cost()
            self.emit("cost_summary", {"summary": summary, "total_usd": total})
        except Exception:
            pass

        # Log-integrity healthcheck: a session that got at least as far as
        # question_selected made at least 2 generate() calls (gap analysis +
        # research question), each of which must now log exactly one
        # api_usage_log row (API or local-fallback, see APIModel). Zero
        # logged calls for this run despite that progress means the audit
        # trail is broken again — this is the exact silent-gap pattern a
        # 2026-09-12 audit found for several real sessions.
        try:
            final_status = note_db.get_session(self.session_id).get("status", "")
            reached_gap_analysis = STATUS_ORDER.index(final_status) >= STATUS_ORDER.index("question_selected") \
                if final_status in STATUS_ORDER else False
            calls_this_run = cost_tracker.call_count(since_timestamp=run_started_at)
            if reached_gap_analysis and calls_this_run == 0:
                msg = (
                    "Log integrity check failed: this run reached "
                    f"status='{final_status}' (requires gap analysis + research "
                    "question generation, at least 2 generate() calls) but "
                    "api_usage_log has 0 rows for this run. Cost/backend "
                    "tracking is broken for this session — investigate before "
                    "trusting cost totals."
                )
                logger.warning(msg)
                self.emit("log_integrity_warning", {"message": msg})
        except Exception as exc:
            logger.warning("Log-integrity healthcheck itself failed: %s", exc)

        self.emit("pipeline_complete", {"session_id": self.session_id})

    # ── Phase helpers ─────────────────────────────────────────────────────

    def _phase_paper_collection(self, topic, note_db, api_model, qc):
        from agents.paper_collection import PaperCollectionAgent
        from agents.degradation import DegradationLog

        class _DummyEmbed:
            is_loaded = True
            def embed(self, text): return [0.0] * 768
            def embed_batch(self, texts): return [[0.0] * 768 for _ in texts]

        vector_db = _DummyVectorDB()

        # Try a real embedding backend so Phase 1's relevance ranking has an
        # actual signal — the Web UI used to always pass a zero-vector dummy
        # here, which made ranking a silent no-op (see PaperCollectionAgent
        # ._rank_all). Falls back to the dummy, with a recorded degradation,
        # if Ollama or the embedding model isn't available.
        embed_model = _DummyEmbed()
        try:
            from models.ollama_model import OllamaEmbedModel
            real_embed = OllamaEmbedModel()
            real_embed.load()
            embed_model = real_embed
            self.emit("log", {"message": "Using Ollama embeddings for paper ranking."})
        except Exception as exc:
            DegradationLog(note_db, self.session_id, notify=lambda m: self.emit("log", {"message": m})).record(
                1, "embedding_backend", "critical",
                f"No real embedding backend available ({exc}). Paper relevance ranking "
                f"in the Web UI will be degraded or unranked."
            )

        agent = PaperCollectionAgent(
            local_model=None,
            embed_model=embed_model,
            vector_db=vector_db,
            note_db=note_db,
            top_k=config.ARXIV_TOP_K,
        )
        return agent.run(topic=topic, session_id=self.session_id)

    def _load_papers(self, note_db):
        from tools.arxiv_fetcher import PaperRecord
        rows = note_db.get_papers(self.session_id)
        papers = []
        for r in rows:
            pdf = Path(r["pdf_path"]) if r.get("pdf_path") else None
            p = PaperRecord(
                arxiv_id=r["arxiv_id"],
                title=r["title"] or "",
                authors=r["authors"].split(", ") if r.get("authors") else [],
                year=r["year"] or 0,
                url=r["url"] or "",
                abstract=r["abstract"] or "",
                pdf_path=pdf,
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
        return papers

    def _phase_literature_review(self, papers, note_db, qc, api_model):
        from agents.literature_review import LiteratureReviewAgent
        # Use the local model loaded at startup. This used to pass None, which
        # silently reduced "reading" each paper to copying its first abstract
        # sentences — the agent now records that as a critical degradation.
        local = getattr(api_model, "_local_model", None)
        agent = LiteratureReviewAgent(local_model=local, note_db=note_db)
        return agent.run(papers=papers, session_id=self.session_id)

    def _phase_gap_analysis(self, topic, lit_summary, papers, note_db, api_model):
        import json as _json
        from agents.gap_analysis import GapAnalysisAgent, ResearchQuestion

        agent = GapAnalysisAgent(api_model=api_model, note_db=note_db)

        self.emit("log", {"message": "Identifying research gaps (API)…"})
        gap_report = agent._analyse_gaps(topic, lit_summary, len(papers), self.session_id)

        self.emit("log", {"message": "Cross-checking claimed gaps against paper sources…"})
        gap_report, validation = agent.validate_gap_report(topic, gap_report, self.session_id)
        self.emit("gap_validation", {
            "findings": [vars(v) for v in validation],
        })

        # Persist gap report + validation so it survives session reload
        note_db.update_session(
            self.session_id,
            gap_report=gap_report,
            gap_validation=_json.dumps([vars(v) for v in validation]),
        )
        from agents.gap_analysis import record_gap_context
        record_gap_context(note_db, self.session_id)
        self.emit("gap_report", {"content": gap_report})

        self.emit("log", {"message": "Generating research question candidates…"})
        questions = agent.generate_checked_questions(topic, gap_report, validation, self.session_id)

        questions_data = [
            {
                "index": q.index,
                "text": q.text,
                "feasibility": q.feasibility_notes,
                "novelty": q.novelty_notes,
                "echoes_input": q.echoes_input,
                "compliance": q.compliance,
            }
            for q in questions
        ]
        self.emit("questions", {"questions": questions_data})
        self.emit("waiting_for_input", {
            "step": "question_selection",
            "message": "Please select a research question to proceed.",
        })

        # Block thread until the user picks. An unusable choice used to select
        # question 1 silently, and a question that failed the data check could
        # be chosen without any warning.
        while True:
            self._question_event.wait()
            self._question_event.clear()
            if self._stop_flag.is_set():
                return None
            choice, override = self._question_choice, self._question_override
            if isinstance(choice, int) and 1 <= choice <= len(questions):
                selected = questions[choice - 1]
                if selected.compliance == "fail" and not override:
                    self.emit("question_needs_override", {"index": choice, "notes": selected.compliance_notes})
                    self.emit("log", {"message": f"RQ {choice} failed the data check: {selected.compliance_notes} "
                                                 "Confirm to use it anyway."})
                    continue
                break
            if isinstance(choice, str) and choice.strip():
                selected = ResearchQuestion(index=0, text=choice.strip(), feasibility_notes="User-defined",
                                            novelty_notes="User-defined",
                                            compliance_notes="Written by the user; not checked against the data.")
                break
            self.emit("log", {"message": f"Selection {choice!r} is not a question number or text; choose again."})

        note_db.save_artifact(self.session_id, "question", {
            "text": selected.text, "index": selected.index, "compliance": selected.compliance,
            "compliance_notes": selected.compliance_notes, "feasibility": selected.feasibility_notes,
            "novelty": selected.novelty_notes, "data_check_overridden": selected.compliance == "fail",
        }, "passed")
        self.emit("research_question", {"text": selected.text, "index": selected.index})
        note_db.update_session(
            self.session_id,
            research_question=selected.text,
            status="question_selected",
        )
        return selected

    def _phase_hypothesis(self, rq, papers, note_db, api_model):
        from agents.hypothesis import HypothesisAgent

        class _DummyEmbed:
            is_loaded = True
            def embed(self, text): return [0.0] * 768
            def embed_batch(self, texts): return [[0.0] * 768 for _ in texts]

        vector_db = _DummyVectorDB()

        agent = HypothesisAgent(
            api_model=api_model,
            embed_model=_DummyEmbed(),
            vector_db=vector_db,
            note_db=note_db,
        )
        agent.run(research_question=rq, papers=papers, session_id=self.session_id)

    def _phase_experiment_code(self, note_db, api_model):
        """
        Phase 5 without interactive input().
        Auto-selects the best hypothesis and skips the regeneration prompt.
        """
        from agents.experiment_agent import ExperimentAgent

        hypotheses = note_db.get_hypotheses(self.session_id)
        if not hypotheses:
            raise RuntimeError("No hypotheses found. Run Phase 4 first.")

        # Auto-select: prefer one already marked code_generated, else highest score
        selected = None
        for h in hypotheses:
            if h.get("status") == "code_generated":
                selected = h
                break
        if selected is None:
            # Pick the one with the highest feasibility score
            selected = max(
                hypotheses,
                key=lambda h: h.get("feasibility_score") or 0.0,
            )

        # Compute 1-based index in the hypothesis list (for directory naming)
        h_index = next(
            (i + 1 for i, h in enumerate(hypotheses)
             if h["hypothesis_id"] == selected["hypothesis_id"]),
            1,
        )
        hypothesis_id = selected["hypothesis_id"]
        self.emit("log", {
            "message": f"Auto-selected hypothesis {h_index}: {selected['content'][:80]}…"
        })

        agent = ExperimentAgent(
            api_model=api_model,
            note_db=note_db,
            experiments_base_dir=config.EXPERIMENTS_DIR,
        )

        # If code already exists, just re-write files to disk and skip generation
        existing = note_db.get_experiment_code(hypothesis_id)
        if existing:
            self.emit("log", {
                "message": f"Reusing {len(existing)} previously generated file(s) from DB."
            })
            files = {r["file_path"]: r["file_content"] for r in existing}
            hypothesis_dir = config.session_experiment_dir(self.session_id)
            agent._write_files(hypothesis_dir, files)
            self._run_pre_execution_check(note_db, api_model)
            return

        # Generate fresh
        existing_paths: set[str] = set()
        generated = agent._generate_all_files(
            hypothesis=selected,
            skip_paths=existing_paths,
            session_id=self.session_id,
        )

        hypothesis_dir = config.session_experiment_dir(self.session_id)
        agent._write_files(hypothesis_dir, generated)
        agent._persist_to_db(self.session_id, hypothesis_id, generated)
        note_db.update_hypothesis_status(
            hypothesis_id, "code_generated", domain=agent._last_domain
        )

        self.emit("log", {
            "message": f"Generated {len(generated)} experiment files "
                       f"(domain: {agent._last_domain}) → {hypothesis_dir}"
        })
        self._run_pre_execution_check(note_db, api_model)

    def _run_pre_execution_check(self, note_db, api_model) -> None:
        """
        Fast domain-alignment check between Phase 5 (code generation) and
        Phase 6 (execution) — catches a wrong-domain codebase (e.g. RL
        environment code for a retrieval hypothesis) before burning compute
        running it. Never blocks the pipeline; just warns loudly via the
        WebSocket log stream.
        """
        try:
            from agents.quality_review import QualityReviewAgent
            agent = QualityReviewAgent(api_model=api_model, note_db=note_db)
            report = agent.pre_execution_check(self.session_id)
            if report.fails:
                for f in report.fails:
                    self.emit("log", {
                        "message": f"⚠ Pre-execution check FAILED: {f.title} — {f.detail}"
                    })
            else:
                self.emit("log", {"message": "Pre-execution domain-alignment check: OK."})
        except Exception as exc:
            logger.warning("Pre-execution check failed to run: %s", exc)

    def _phase_experiment_run(self, note_db, api_model):
        import subprocess as _sp_mod
        from agents.experiment_runner import ExperimentRunnerAgent

        agent = ExperimentRunnerAgent(
            api_model=api_model,
            note_db=note_db,
            experiments_base_dir=config.EXPERIMENTS_DIR,
        )

        # Temporarily patch subprocess.Popen so we can capture the process
        # reference for on-demand kill via stop().
        _orig_popen = _sp_mod.Popen
        _runner_ref = self

        class _TrackingPopen(_orig_popen):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                _runner_ref._current_proc = self

        _sp_mod.Popen = _TrackingPopen
        try:
            agent.run(session_id=self.session_id)
        finally:
            _sp_mod.Popen = _orig_popen
            self._current_proc = None

    def _phase_quality_review(self, note_db, api_model):
        """
        Phase 7 — automated peer-review simulation.
        Never raises: wraps all errors and returns a degraded report.
        """
        from agents.quality_review import QualityReviewAgent, QualityReport
        try:
            agent = QualityReviewAgent(api_model=api_model, note_db=note_db)
            return agent.review(self.session_id)
        except Exception as exc:
            logger.warning("Quality review failed: %s", exc)
            # Return a minimal degraded report so the pipeline can continue
            from agents.quality_review import QualityFinding
            return QualityReport(
                session_id=self.session_id,
                topic="",
                score=0,
                gate="warn",
                findings=[QualityFinding(
                    level="warn",
                    criterion="review_error",
                    title="Quality Review Unavailable",
                    detail=str(exc),
                    fix="Check agent logs for details.",
                )],
                llm_summary="Quality review could not complete due to an error.",
            )
