"""
Hypothesis Generation Agent (Phase 3)

Step 1 [API]: Brainstorm 3-5 hypothesis candidates + experiment designs
Step 2 [LOCAL]: Similarity search — warn if hypothesis overlaps prior work
Step 3 [API]: Refine candidates → finalise experiment designs
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from router import TaskType

if TYPE_CHECKING:
    from models.local_model import EmbeddingModel
    from models.api_model import APIModel
    from memory.vector_db import VectorDB
    from memory.note_db import NoteDB
    from agents.gap_analysis import ResearchQuestion
    from tools.arxiv_fetcher import PaperRecord

logger = logging.getLogger(__name__)
console = Console()


@dataclass
class Hypothesis:
    index: int
    content: str
    experiment_design: dict = field(default_factory=dict)
    feasibility_score: float = 0.0
    similar_papers: list[dict] = field(default_factory=list)
    priority: str = "medium"  # low / medium / high


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
_BRAINSTORM_SYSTEM = (
    "You are a creative AI research scientist. Generate bold but verifiable hypotheses "
    "with detailed experiment designs. Always include ablation study plans."
)

_BRAINSTORM_PROMPT = """\
Research question: {research_question}

Literature context (top papers and their limitations):
{literature_context}

Brainstorm 3 to 5 distinct hypotheses that could answer this research question.
For each hypothesis, provide:

HYPOTHESIS N:
- Statement: A clear, falsifiable claim (1-2 sentences)
- Rationale: Why this is worth testing (2-3 sentences)
- Approach: Proposed method or architecture change
- Baseline: What to compare against
- Metrics: What to measure
- Ablations: 2-3 ablation variants to run
- Robustness: How to test if the result generalises
- Hardware feasibility: Is this runnable on a single RTX 3060 Ti (8 GB VRAM)?
- Estimated GPU hours: rough estimate

Use "HYPOTHESIS 1:", "HYPOTHESIS 2:", etc. as section markers."""

_REFINE_SYSTEM = (
    "You are an experienced research mentor. Filter and refine hypothesis candidates, "
    "removing those that are not novel or not feasible. Produce final experiment designs."
)

_REFINE_PROMPT = """\
Research question: {research_question}

Hypothesis candidates with similarity warnings:
{candidates_with_warnings}

Refine these hypotheses:
1. Remove any hypothesis that is essentially a repeat of existing work
2. For the remaining ones, produce a final, polished experiment design in JSON

Output a JSON array where each element has:
{{
  "index": <int>,
  "content": "<hypothesis statement>",
  "experiment_design": {{
    "approach": "...",
    "baseline": "...",
    "metrics": ["..."],
    "ablations": ["..."],
    "robustness_tests": ["..."],
    "estimated_gpu_hours": "..."
  }},
  "feasibility_score": <float 0.0-1.0>,
  "priority": "<low|medium|high>",
  "priority_reason": "..."
}}

Output ONLY the JSON array."""


class HypothesisAgent:

    def __init__(
        self,
        api_model: "APIModel",
        embed_model: "EmbeddingModel",
        vector_db: "VectorDB",
        note_db: "NoteDB",
    ) -> None:
        self._api   = api_model
        self._embed = embed_model
        self._vdb   = vector_db
        self._ndb   = note_db

    # ------------------------------------------------------------------
    def run(
        self,
        research_question: "ResearchQuestion",
        papers: list["PaperRecord"],
        session_id: str,
    ) -> list[Hypothesis]:
        """
        Full hypothesis generation pipeline.
        Returns the finalised list of Hypothesis objects.
        """
        console.print(
            f"\n[bold cyan][Hypothesis Generation][/] "
            f"Research question: {research_question.text}"
        )

        lit_context = self._build_lit_context(papers)

        # Step 1: brainstorm
        console.print("  Step 1: Brainstorming hypotheses (API)…")
        raw_hypotheses = self._brainstorm(research_question.text, lit_context)
        console.print(f"  Generated {len(raw_hypotheses)} candidate(s).")

        # Step 2: similarity search
        console.print("  Step 2: Checking similarity to prior work (local)…")
        raw_hypotheses = self._add_similarity_warnings(raw_hypotheses)

        # Step 3: refine
        console.print("  Step 3: Refining and designing experiments (API)…")
        hypotheses = self._refine(research_question.text, raw_hypotheses)

        # Persist
        for h in hypotheses:
            h_id = self._ndb.save_hypothesis(
                session_id=session_id,
                content=h.content,
                experiment_design=h.experiment_design,
                feasibility_score=h.feasibility_score,
            )
            logger.debug("Saved hypothesis %s", h_id)

        self._ndb.update_session(session_id, status="hypotheses_generated")

        # Print output
        self._print_hypotheses(hypotheses)
        return hypotheses

    # ------------------------------------------------------------------
    # Step 1
    # ------------------------------------------------------------------

    def _brainstorm(self, rq: str, lit_context: str) -> list[Hypothesis]:
        prompt = _BRAINSTORM_PROMPT.format(
            research_question=rq,
            literature_context=lit_context[:8000],
        )
        raw = self._api.generate(
            prompt=prompt,
            system=_BRAINSTORM_SYSTEM,
            task_type=TaskType.HYPOTHESIS_GEN,
            temperature=0.85,
        )
        return self._parse_brainstorm(raw)

    @staticmethod
    def _parse_brainstorm(raw: str) -> list[Hypothesis]:
        """Extract hypothesis blocks from free-text output."""
        blocks = re.split(r'\bHYPOTHESIS\s*\d+\s*:', raw, flags=re.IGNORECASE)
        hypotheses: list[Hypothesis] = []
        for i, block in enumerate(blocks[1:], 1):
            lines = block.strip().split("\n")
            # First line or "Statement:" line is the content
            content = ""
            for line in lines:
                m = re.match(r'-\s*[Ss]tatement[:\s]+(.*)', line)
                if m:
                    content = m.group(1).strip()
                    break
            if not content:
                content = lines[0].strip()

            hypotheses.append(Hypothesis(index=i, content=content))
        return hypotheses

    # ------------------------------------------------------------------
    # Step 2
    # ------------------------------------------------------------------

    def _add_similarity_warnings(
        self, hypotheses: list[Hypothesis]
    ) -> list[Hypothesis]:
        """Embed each hypothesis and find near-duplicate papers."""
        for h in hypotheses:
            try:
                emb = self._embed.embed(h.content)
                similar = self._vdb.query(query_embedding=emb, n_results=3)
                h.similar_papers = similar
                if similar and similar[0]["distance"] < 0.15:
                    logger.warning(
                        "Hypothesis %d may overlap with: %s",
                        h.index,
                        similar[0]["metadata"].get("title", "?"),
                    )
            except Exception as exc:
                logger.debug("Similarity check skipped for H%d: %s", h.index, exc)
        return hypotheses

    # ------------------------------------------------------------------
    # Step 3
    # ------------------------------------------------------------------

    def _refine(self, rq: str, hypotheses: list[Hypothesis]) -> list[Hypothesis]:
        candidates_text = self._format_candidates_for_refine(hypotheses)
        prompt = _REFINE_PROMPT.format(
            research_question=rq,
            candidates_with_warnings=candidates_text,
        )
        raw = self._api.generate(
            prompt=prompt,
            system=_REFINE_SYSTEM,
            task_type=TaskType.EXPERIMENT_DESIGN,
            max_tokens=4096,
            temperature=0.3,
        )
        return self._parse_refined(raw, hypotheses)

    @staticmethod
    def _format_candidates_for_refine(hypotheses: list[Hypothesis]) -> str:
        lines = []
        for h in hypotheses:
            warning = ""
            if h.similar_papers and h.similar_papers[0]["distance"] < 0.15:
                similar_title = h.similar_papers[0]["metadata"].get("title", "?")
                warning = f"  ⚠ WARNING: Similar to '{similar_title[:60]}'"
            lines.append(
                f"Hypothesis {h.index}: {h.content}\n{warning}"
            )
        return "\n\n".join(lines)

    @staticmethod
    def _parse_refined(raw: str, originals: list[Hypothesis]) -> list[Hypothesis]:
        """Parse JSON array from the refinement response."""
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if not match:
            logger.warning("Could not parse refined hypotheses JSON; using originals.")
            return originals

        try:
            data = json.loads(match.group())
        except json.JSONDecodeError as exc:
            logger.warning("JSON parse error in refinement: %s", exc)
            return originals

        result: list[Hypothesis] = []
        for item in data:
            h = Hypothesis(
                index=item.get("index", 0),
                content=item.get("content", ""),
                experiment_design=item.get("experiment_design", {}),
                feasibility_score=float(item.get("feasibility_score", 0.5)),
                priority=item.get("priority", "medium"),
            )
            result.append(h)

        return result or originals

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_lit_context(papers: list["PaperRecord"]) -> str:
        lines = []
        for p in papers[:10]:  # top-10 for context brevity
            lines.append(
                f"• {p.title} ({p.year})\n"
                f"  Limitation: {p.limitation or 'N/A'}\n"
                f"  Method: {(p.method or 'N/A')[:120]}\n"
            )
        return "\n".join(lines)

    def _print_hypotheses(self, hypotheses: list[Hypothesis]) -> None:
        console.print("\n[bold green]=== Hypothesis Candidates ===[/]\n")

        priority_color = {"high": "green", "medium": "yellow", "low": "red"}

        for h in hypotheses:
            color = priority_color.get(h.priority, "white")
            design = h.experiment_design
            design_str = (
                f"Baseline: {design.get('baseline', 'N/A')}\n"
                f"Metrics: {', '.join(design.get('metrics', []))}\n"
                f"Ablations: {', '.join(design.get('ablations', []))}\n"
                f"Est. GPU hours: {design.get('estimated_gpu_hours', 'N/A')}"
            ) if design else "No experiment design available."

            console.print(Panel(
                f"[bold]{h.content}[/]\n\n"
                f"[dim]Experiment Design:[/]\n{design_str}\n\n"
                f"Feasibility: {h.feasibility_score:.1f} | "
                f"Priority: [{color}]{h.priority.upper()}[/]",
                title=f"Hypothesis {h.index}",
                border_style=color,
            ))
