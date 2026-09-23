"""
Literature Review Agent (Phase 2, Step 2)

For each paper:
1. Gather its own text: PDF sections (arXiv), open-access full-text sections
   (Europe PMC), or the abstract when nothing else is retrievable
2. Use the local model to extract method, findings, and the authors' own
   statements of limitations and future work — as verbatim quotes, which are
   checked against the text and discarded if not found
3. Save structured results to SQLite
4. Generate a comparison table

Why the quotes: gap analysis should start from what the papers themselves say
is unresolved. A 2026-09-13 run's gap report contradicted its own collection
("fuel stacking remains poorly understood" with six stacking papers in hand),
because in the Web UI this phase ran no model at all — it copied the first
three sentences of each abstract — so the gap step never saw a single stated
limitation or future-work sentence.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from tools.arxiv_fetcher import PaperRecord
from tools.pdf_parser import PDFParser

if TYPE_CHECKING:
    from models.local_model import LocalModel
    from memory.note_db import NoteDB

logger = logging.getLogger(__name__)
console = Console()

# Pattern to detect code repository mentions
_CODE_PATTERNS = re.compile(
    r"(github\.com|gitlab\.com|bitbucket\.org|code is available|our code|source code)",
    re.IGNORECASE,
)

_EXTRACTION_PROMPT = """\
Extract what this paper itself says. Use ONLY the text below.

Return ONLY a valid JSON object with these keys:
- method: 1-2 sentences on the study design or approach
- findings: 1-3 sentences on the main results as reported
- limitation_quotes: list of sentences copied EXACTLY from the text in which the authors state
  limitations or weaknesses of their own study; [] if there are none
- future_work_quotes: list of sentences copied EXACTLY from the text in which the authors say
  what future research should do or what remains unknown; [] if there are none
- dataset: data sources used (comma-separated), or "" if none are named
- metric: outcome measures (comma-separated), or "" if none are named
- contribution: the main contribution claimed, in one sentence
- replication_possible: true only if the data and procedures are described well enough to repeat

Quotes are checked word for word against the text; paraphrased or invented quotes are discarded.

Paper title: {title}

Paper text ({source}, may be truncated):
{text}

JSON:"""

_TEXT_CAP = 12_000  # characters; keeps prompt + output inside OLLAMA_NUM_CTX
# Characters of paper summaries the gap-analysis prompt can hold alongside the
# brief, instructions and a 2,048-token answer within an 8,192-token context.
SUMMARY_MAX_CHARS = 14_000


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\"“”'‘’]", "", text)).strip().lower()


def _verified_quotes(quotes, source_text: str) -> tuple[list[str], int]:
    """Keep quotes that really occur in the source text; return (kept, dropped_count)."""
    if not isinstance(quotes, list):
        return [], 0
    haystack = _norm(source_text)
    kept, dropped = [], 0
    for q in quotes:
        q = str(q).strip()
        if len(q) >= 20 and _norm(q).rstrip(".") in haystack:
            kept.append(q)
        elif q:
            dropped += 1
    return kept, dropped


class LiteratureReviewAgent:

    def __init__(
        self,
        local_model: "LocalModel",
        note_db: "NoteDB",
    ) -> None:
        self._local = local_model
        self._ndb = note_db
        self._parser = PDFParser()
        self._deg = None
        self._fulltext_blocked = False
        self._stats = {"full text": 0, "abstract only": 0, "heuristic": 0,
                       "extraction_failed": 0, "quotes_dropped": 0}

    # ------------------------------------------------------------------
    def run(
        self, papers: list[PaperRecord], session_id: str
    ) -> list[PaperRecord]:
        """
        Extract structured fields for each paper.
        Updates PaperRecord in-place and saves to SQLite.
        Returns the enriched list.
        """
        from agents.degradation import DegradationLog
        self._deg = DegradationLog(self._ndb, session_id, notify=console.print)

        console.print(
            f"\n[bold cyan][Literature Review][/] Analysing {len(papers)} papers…"
        )
        if not (self._local and self._local.is_loaded):
            self._deg.record(
                2, "literature_review", "critical",
                "No local model loaded: papers were not read. Fields are the first "
                "sentences of each abstract; no limitations or future work extracted.",
            )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("  Extracting…", total=len(papers))

            for paper in papers:
                self._process_paper(paper, session_id)
                progress.advance(task)

        self._report_coverage(len(papers))
        self._print_comparison_table(papers)
        return papers

    def _report_coverage(self, total: int) -> None:
        s = self._stats
        if s["abstract only"]:
            self._deg.record(
                2, "literature_review", "warn",
                f"{s['abstract only']} of {total} papers were read from the abstract only "
                f"(no retrievable full text); their limitations and future work are "
                f"largely unknown.",
            )
        if s["extraction_failed"]:
            self._deg.record(
                2, "literature_review", "warn",
                f"Extraction failed for {s['extraction_failed']} of {total} papers "
                f"(fell back to abstract sentences).",
            )
        if s["quotes_dropped"]:
            self._deg.record(
                2, "literature_review", "warn",
                f"{s['quotes_dropped']} limitation/future-work quotes were not found "
                f"word for word in the paper text and were discarded.",
            )

    # ------------------------------------------------------------------
    def _gather_text(self, paper: PaperRecord) -> tuple[str, str]:
        """Return (text, source label), preferring the paper's own full text."""
        if paper.pdf_path:
            parsed = self._parser.parse(paper.pdf_path)
            if parsed and parsed.raw_text:
                parts = [parsed.abstract or paper.abstract]
                if parsed.method_text:
                    parts.append("METHOD:\n" + parsed.method_text)
                if parsed.limitation_text:
                    parts.append("LIMITATIONS:\n" + parsed.limitation_text)
                if parsed.dataset_text:
                    parts.append("DATASET:\n" + parsed.dataset_text)
                return "\n\n".join(parts), "full text"

        if paper.fulltext_id and paper.source == "europepmc" and not self._fulltext_blocked:
            from tools.rate_limit import SourceBlocked
            from tools.sources.europepmc import fetch_fulltext_sections
            try:
                sections = fetch_fulltext_sections(paper.fulltext_id)
            except SourceBlocked as exc:
                self._fulltext_blocked = True
                if self._deg:
                    self._deg.record(2, "source:europepmc", "warn",
                                     f"Full-text downloads stopped: {exc}")
                sections = {}
            except Exception as exc:
                logger.warning("Full text unavailable for %s: %s", paper.fulltext_id, exc)
                sections = {}
            if sections:
                body = "\n\n".join(f"{title.upper()}:\n{text}" for title, text in sections.items())
                return f"ABSTRACT:\n{paper.abstract}\n\n{body}", "full text"

        return paper.abstract, "abstract only"

    def _process_paper(self, paper: PaperRecord, session_id: str) -> None:
        """Extract fields for a single paper and persist to SQLite."""
        text, source = self._gather_text(paper)
        paper.code_available = bool(_CODE_PATTERNS.search(text))

        extraction = self._extract_fields(paper.title, text, source)
        paper.text_source = extraction.pop("_source", source)
        self._stats[paper.text_source] = self._stats.get(paper.text_source, 0) + 1

        limitations, dropped_l = _verified_quotes(extraction.get("limitation_quotes"), text)
        future, dropped_f = _verified_quotes(extraction.get("future_work_quotes"), text)
        self._stats["quotes_dropped"] += dropped_l + dropped_f

        paper.method              = str(extraction.get("method", "") or "")
        paper.findings            = str(extraction.get("findings", "") or "")
        paper.limitation          = "\n".join(limitations) or str(extraction.get("limitation", "") or "")
        paper.future_work         = "\n".join(future)
        paper.dataset             = str(extraction.get("dataset", "") or "")
        paper.metric              = str(extraction.get("metric", "") or "")
        paper.contribution        = str(extraction.get("contribution", "") or "")
        paper.replication_possible = bool(extraction.get("replication_possible", False))

        self._ndb.save_paper(session_id, paper.to_dict())

    def _extract_fields(self, title: str, text: str, source: str = "abstract only") -> dict:
        """Run local model extraction; return dict (may be partial on failure)."""
        if not (self._local and self._local.is_loaded):
            return {**self._heuristic_extraction(text), "_source": "heuristic"}

        prompt = _EXTRACTION_PROMPT.format(title=title, source=source, text=text[:_TEXT_CAP])
        try:
            raw = self._local.generate(prompt, temperature=0.1, max_tokens=768)
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as exc:
            logger.warning("Local extraction failed for '%s': %s", title[:40], exc)

        self._stats["extraction_failed"] += 1
        return self._heuristic_extraction(text)

    @staticmethod
    def _heuristic_extraction(text: str) -> dict:
        """
        Minimal fallback: pick first 2 sentences for method,
        look for 'limit' keyword for limitation.
        """
        sentences = re.split(r'(?<=[.!?])\s+', text)
        method = " ".join(sentences[:3]) if sentences else ""
        limitation = ""
        for sent in sentences:
            if re.search(r'\blimit', sent, re.IGNORECASE):
                limitation = sent
                break
        return {
            "method":               method[:500],
            "limitation":          limitation[:300],
            "dataset":             "",
            "metric":              "",
            "contribution":        "",
            "replication_possible": False,
        }

    # ------------------------------------------------------------------
    def _print_comparison_table(self, papers: list[PaperRecord]) -> None:
        """Print a rich comparison table to the console."""
        table = Table(
            title="Paper Comparison Table",
            show_lines=True,
            expand=True,
        )
        table.add_column("#",           width=3, justify="right")
        table.add_column("Title",       min_width=20, no_wrap=False)
        table.add_column("Year",        width=5, justify="center")
        table.add_column("Dataset",     min_width=10)
        table.add_column("Metric",      min_width=10)
        table.add_column("Replicate?",  width=10, justify="center")
        table.add_column("Code?",       width=6, justify="center")

        for i, p in enumerate(papers, 1):
            table.add_row(
                str(i),
                p.title[:60] + ("…" if len(p.title) > 60 else ""),
                str(p.year),
                (p.dataset or "-")[:30],
                (p.metric  or "-")[:20],
                "[green]Yes[/]" if p.replication_possible else "[red]No[/]",
                "[green]Yes[/]" if p.code_available       else "[red]No[/]",
            )

        console.print(table)

    # ------------------------------------------------------------------
    def build_context_summary(self, papers: list[PaperRecord]) -> str:
        """
        Build a plain-text context block to feed into the Gap Analysis API call.
        """
        def clip(text: str, n: int) -> str:
            text = " ".join((text or "").split())
            return text if len(text) <= n else text[: n - 1] + "…"

        def quoted(block: str, n: int) -> str:
            quotes = [q for q in (block or "").split("\n") if q.strip()]
            return clip(" ".join(f'"{q.strip()}"' for q in quotes), n) if quotes else "none stated"

        # Share the budget evenly so every paper is represented, instead of the
        # gap prompt cutting off whichever papers come last.
        per_paper = max(360, SUMMARY_MAX_CHARS // max(len(papers), 1)) - 200
        lines = ["=== Literature Review Summary ===\n"]
        for i, p in enumerate(papers, 1):
            lines.append(
                f"[{i}] {clip(p.title, 140)} ({p.year}) — read from: {p.text_source or 'unknown'}\n"
                f"  Findings: {clip(p.findings, int(per_paper * 0.25)) or 'N/A'}\n"
                f"  Limitations stated by the authors: {quoted(p.limitation, int(per_paper * 0.3))}\n"
                f"  Future work stated by the authors: {quoted(p.future_work, int(per_paper * 0.3))}\n"
                f"  Method: {clip(p.method, int(per_paper * 0.15)) or 'N/A'}\n"
            )
        return "\n".join(lines)
