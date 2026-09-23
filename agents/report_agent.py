"""
ReportAgent (Phase 7 — optional)

Gathers all session context from the DB + eval_results.json and calls the
Claude API once to produce a structured JSON research report.
The JSON is then rendered to Markdown / LaTeX / PDF by ui/report_renderer.py
without any additional LLM calls.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import config
from router import TaskType

if TYPE_CHECKING:
    from models.api_model import APIModel
    from memory.note_db import NoteDB

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are an expert AI/ML researcher and technical writer.
You are given the full context of an automated research pipeline run:
topic, research gap, hypothesis, experiment configuration, and results.

Write a complete, rigorous research report in JSON format.
Every claim MUST be grounded in the provided data — never invent numbers,
citations, or conclusions that are not supported by the context.

Metric interpretation hints (use these to write accurate commentary):
- recall_at_K: higher is better. <0.40 = weak, 0.40-0.65 = moderate, >0.65 = strong
- mean_reciprocal_rank (MRR): higher is better. Same scale as recall.
- domain_gap (cosine distance between domain centroids):
    HIGHER = domains are MORE separated = WORSE for domain-invariant learning.
    Values near 0 = good domain alignment. Values near 1 = poor alignment.
- credit_assignment_gap = return(long horizon) - return(short horizon):
    Larger = model benefits more from longer context, harder credit assignment problem.
- domain_invariance_gain: higher = contrastive loss contributed more to domain alignment.
- Train → Eval drop: if eval metrics are lower than train metrics,
    this indicates generalisation loss (potential overfitting or distribution shift).

Output a single JSON object with exactly these keys:
{
  "title": "...",
  "abstract": "...",          // 150-200 words
  "introduction": "...",      // motivation, problem statement, contributions (300-400 words)
  "related_work": "...",      // cite the provided papers; 200-300 words
  "methodology": "...",       // model architecture, training setup, evaluation protocol (300-400 words)
  "results": "...",           // quantitative analysis using the exact numbers provided (300-400 words)
  "discussion": "...",        // strengths, weaknesses (domain_gap!), future work (200-300 words)
  "conclusion": "...",        // 100-150 words
  "references": [             // only papers from the PROVIDED list; do not invent any
    {"key": "cite_key", "title": "...", "authors": "...", "venue": "...", "year": "..."}
  ]
}

Return ONLY the JSON object. No markdown fences, no explanation.
"""

_USER_TEMPLATE = """\
=== RESEARCH TOPIC ===
{topic}

=== BACKGROUND / CONTEXT ===
{background}

=== RESEARCH GOALS ===
{goals}

=== CONSTRAINTS ===
{constraints}

=== IDENTIFIED RESEARCH GAP ===
{gap_report}

=== HYPOTHESIS TESTED ===
{hypothesis}

=== EXPERIMENT CONFIGURATION ===
{experiment_config}

=== TRAINING METRICS (from train.py) ===
{training_metrics}

=== EVALUATION RESULTS (from evaluate.py — use these numbers verbatim) ===
{eval_results}

=== AVAILABLE PAPERS (use only these for references; do not invent others) ===
{papers}
"""


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

MAX_LIST_ITEMS = 10


def _compact_lists(value):
    """
    Long per-item lists (e.g. one record per country series) are replaced by
    their length and first items. 2026-09-13: a 180-record list made the
    report prompt ~12k tokens for an 8k local context; the model saw a
    truncated prompt and answered questions nobody asked, with invented numbers.
    """
    if isinstance(value, dict):
        return {k: _compact_lists(v) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > MAX_LIST_ITEMS:
            return {"total_items": len(value), "first_items": [_compact_lists(v) for v in value[:3]],
                    "note": "remaining items omitted here; see results/eval_results.json"}
        return [_compact_lists(v) for v in value]
    return value


class ReportAgent:
    """
    Generates a structured JSON research report from all available session data.
    Single LLM call — no hallucination of numbers or references.

    Fallback chain (in order):
      1. Anthropic API  (if ANTHROPIC_API_KEY configured)
      2. Local model    (if a loaded LocalModel is injected into api_model)
      3. Template-based report (no LLM — data-driven only)

    The mode used is recorded in self.mode after generate() returns.
    """

    #: Set after generate() — one of "api", "local", "template"
    mode: str = "unknown"

    def __init__(self, api_model: "APIModel", note_db: "NoteDB") -> None:
        self._api  = api_model
        self._ndb  = note_db

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def generate(self, session_id: str) -> dict:
        """
        Gather all context and call the LLM once.
        Returns the parsed JSON report dict.
        Saves the result to data/reports/{session_id}/report.json.
        """
        ctx = self._gather_context(session_id)
        prompt = _USER_TEMPLATE.format(**ctx)

        try:
            raw = self._api.generate_structured(
                prompt=prompt,
                system=_SYSTEM,
                task_type=TaskType.PAPER_WRITING,
                max_tokens=config.API_MAX_TOKENS,
            )
            report = self._parse_json(raw)
            if report.get("title") == "Report Generation Error":
                from agents.degradation import DegradationLog
                DegradationLog(self._ndb, session_id).record(
                    7, "report", "critical",
                    "The model's report could not be parsed as JSON; the saved report is its raw output.")
            # _api_available is True if Anthropic API was used, False if
            # it was skipped (no key) or failed (network) and local ran instead.
            self.mode = "api" if getattr(self._api, "_api_available", True) else "local"
        except Exception as exc:
            logger.warning(
                "LLM report generation failed (%s) — using template fallback.", exc
            )
            report = self._template_report(ctx)
            self.mode = "template"

        # Persist so app.py can serve without re-generating
        out_dir = Path(config.BASE_DIR) / "data" / "reports" / session_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("Report saved to %s", out_dir / "report.json")
        return report

    # ------------------------------------------------------------------
    # Template fallback (no LLM — structured from raw data)
    # ------------------------------------------------------------------

    @staticmethod
    def _template_report(ctx: dict) -> dict:
        """
        Report without any model call: the recorded inputs and results, no
        interpretation. Until 2026-09-14 this template described "a
        domain-invariant contrastive learning approach", a DualEncoder and
        Recall@K for every topic — text from an earlier project, presented as
        this session's work.
        """
        topic = ctx.get("topic", "Unknown topic")
        unavailable = "Not written: no language model was available to write this section."
        return {
            "title": f"Research Report: {topic}",
            "abstract": ("No language model was available, so this report lists the recorded brief, gap "
                         "analysis, hypothesis, configuration and results without interpretation."),
            "introduction": (f"Background: {(ctx.get('background') or '').strip() or 'Not specified.'}\n\n"
                             f"Research goals: {(ctx.get('goals') or '').strip() or 'Not specified.'}\n\n"
                             f"Constraints: {(ctx.get('constraints') or '').strip() or 'None.'}"),
            "related_work": (ctx.get("gap_report") or "").strip() or "Not available.",
            "methodology": (f"Hypothesis under test:\n{(ctx.get('hypothesis') or '').strip() or 'Not available.'}\n\n"
                            f"Experiment configuration:\n{ctx.get('experiment_config', 'Not available.')}"),
            "results": f"Recorded evaluation results:\n{ctx.get('eval_results', 'Not available.')}",
            "discussion": unavailable,
            "conclusion": unavailable,
            "references": [],
        }

    # ------------------------------------------------------------------
    # Context gathering
    # ------------------------------------------------------------------

    def _gather_context(self, session_id: str) -> dict:
        session    = self._ndb.get_session(session_id) or {}
        hypotheses = self._ndb.get_hypotheses(session_id)
        papers     = self._ndb.get_papers(session_id)

        # Pick the hypothesis that was actually run (code_generated or first)
        hypothesis_text = ""
        for h in hypotheses:
            if h.get("status") == "code_generated":
                hypothesis_text = h.get("content", "")
                break
        if not hypothesis_text and hypotheses:
            hypothesis_text = hypotheses[0].get("content", "")

        # Experiment config from disk
        experiment_config = self._load_experiment_config(session_id)

        # Eval results
        eval_results, training_metrics = self._load_eval_results(session_id)

        # Format papers (limit to 20 to stay within context)
        papers_text = self._format_papers(papers[:20])

        return {
            "topic":             session.get("topic") or "Unknown",
            "background":        session.get("background") or "Not provided.",
            "goals":             session.get("goals") or "Not provided.",
            "constraints":       session.get("constraints") or "Not provided.",
            "gap_report":        session.get("gap_report") or "Not provided.",
            "hypothesis":        hypothesis_text or "Not provided.",
            "experiment_config": experiment_config,
            "training_metrics":  training_metrics,
            "eval_results":      eval_results,
            "papers":            papers_text,
        }

    def _load_experiment_config(self, session_id: str) -> str:
        for hyp_dir in [config.session_experiment_dir(session_id)]:
            cfg_path = hyp_dir / "config.yaml"
            if cfg_path.exists():
                try:
                    return cfg_path.read_text(encoding="utf-8")
                except Exception:
                    pass
        return "config.yaml not found."

    def _load_eval_results(self, session_id: str) -> tuple[str, str]:
        """Returns (eval_results_str, training_metrics_str) for this session only."""
        for hyp_dir in [config.session_experiment_dir(session_id)]:
            results_path = hyp_dir / "results" / "eval_results.json"
            if results_path.exists():
                try:
                    data = json.loads(results_path.read_text(encoding="utf-8"))
                    train_m = data.pop("training_metrics", {})
                    # Remove noisy keys from eval display
                    for key in ("config", "checkpoint_dir", "seed"):
                        data.pop(key, None)
                    data = _compact_lists(data)
                    eval_str  = json.dumps(data, indent=2)
                    train_str = json.dumps(train_m, indent=2)
                    return eval_str, train_str
                except Exception:
                    pass
        return "eval_results.json not found.", ""

    @staticmethod
    def _format_papers(papers: list[dict]) -> str:
        if not papers:
            return "No papers available."
        lines = []
        for i, p in enumerate(papers, 1):
            title   = p.get("title", "Unknown title")
            authors = p.get("authors", "Unknown authors")
            year    = p.get("year") or p.get("published", "")[:4]
            arxiv   = p.get("arxiv_id", "")
            venue   = p.get("venue", "arXiv")
            lines.append(
                f"[{i}] {title}\n"
                f"    Authors: {authors}\n"
                f"    Venue/Year: {venue}, {year}"
                + (f"\n    arXiv: {arxiv}" if arxiv else "")
            )
        return "\n\n".join(lines)

    # ------------------------------------------------------------------
    # JSON parsing with fence stripping
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json(raw: str) -> dict:
        # Strip markdown code fences if present
        text = raw.strip()
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to extract the first {...} block
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
            # Last resort: return a minimal error report
            logger.error("Failed to parse report JSON. Raw output:\n%s", raw[:500])
            return {
                "title": "Report Generation Error",
                "abstract": "The LLM output could not be parsed as JSON.",
                "introduction": raw[:2000],
                "related_work": "", "methodology": "", "results": "",
                "discussion": "", "conclusion": "", "references": [],
            }
