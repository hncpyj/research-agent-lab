"""
arXiv paper fetcher.

Responsibilities:
- Search arXiv by keyword query (respecting rate limits)
- Download PDFs to data/papers/
- Return structured PaperRecord objects
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import config
from tools.rate_limit import SourceBlocked, get_limiter, is_rate_limit_status

logger = logging.getLogger(__name__)


def _import_arxiv():
    try:
        import arxiv
        return arxiv
    except ImportError as exc:
        raise ImportError(
            "arxiv is not installed. Run: pip install arxiv"
        ) from exc


@dataclass
class PaperRecord:
    # Unique key within a session. A real arXiv id for arXiv papers; a
    # source-prefixed id (e.g. "openalex:W123", "epmc:MED:456") otherwise.
    arxiv_id: str
    title: str
    authors: list[str]
    year: int
    url: str
    abstract: str
    pdf_path: Path | None = None
    doi: str = ""
    source: str = "arxiv"
    fulltext_id: str = ""   # e.g. a Europe PMC open-access PMCID, if full text is retrievable
    # Fields filled by literature review agent
    method: str = ""
    limitation: str = ""    # verbatim sentences from the paper, one per line
    future_work: str = ""   # verbatim sentences from the paper, one per line
    findings: str = ""
    text_source: str = ""   # "full text" | "abstract only" | "heuristic"
    dataset: str = ""
    metric: str = ""
    contribution: str = ""
    replication_possible: bool = False
    code_available: bool = False

    def to_dict(self) -> dict:
        return {
            "arxiv_id":             self.arxiv_id,
            "title":                self.title,
            "authors":              ", ".join(self.authors),
            "year":                 self.year,
            "url":                  self.url,
            "abstract":             self.abstract,
            "pdf_path":             str(self.pdf_path) if self.pdf_path else "",
            "doi":                  self.doi,
            "source":               self.source,
            "fulltext_id":          self.fulltext_id,
            "method":               self.method,
            "limitation":           self.limitation,
            "future_work":          self.future_work,
            "findings":             self.findings,
            "text_source":          self.text_source,
            "dataset":              self.dataset,
            "metric":               self.metric,
            "contribution":         self.contribution,
            "replication_possible": self.replication_possible,
            "code_available":       self.code_available,
        }

    @property
    def embed_document(self) -> str:
        """Text fed to the embedding model."""
        return f"{self.title}\n\n{self.abstract}"


class ArxivFetcher:
    """
    Fetches papers from arXiv.

    Usage:
        fetcher = ArxivFetcher()
        papers  = fetcher.search("efficient transformer attention", max_results=50)
    """

    def __init__(
        self,
        papers_dir: Path | None = None,
        max_results: int = config.ARXIV_MAX_RESULTS,
    ) -> None:
        # Read now, not at import time: a default argument would keep pointing
        # at the real papers folder however the caller changed config.
        self._papers_dir = papers_dir if papers_dir is not None else config.PAPERS_DIR
        self._max_results = max_results

    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        max_results: int | None = None,
        sort_by: str = "relevance",
    ) -> list[PaperRecord]:
        """
        Search arXiv and return PaperRecord objects (metadata only — PDFs are
        downloaded separately, and only for papers that survive ranking).

        One search is exactly one API request (max_results is capped at one
        page), paced through tools.rate_limit. Raises SourceBlocked if arXiv
        is inside its block window or throttles this request.
        """
        arxiv = _import_arxiv()
        limit = min(max_results or self._max_results, 100)

        sort_criterion = (
            arxiv.SortCriterion.Relevance
            if sort_by == "relevance"
            else arxiv.SortCriterion.SubmittedDate
        )

        logger.info("Searching arXiv: query=%r  max_results=%d", query, limit)

        limiter = get_limiter()
        limiter.acquire("arxiv")
        # num_retries=0: never let the library re-send after a failure —
        # a throttled source gets blocked, not retried.
        client = arxiv.Client(page_size=limit, delay_seconds=0, num_retries=0)
        search = arxiv.Search(query=query, max_results=limit, sort_by=sort_criterion)

        records: list[PaperRecord] = []
        seen_ids: set[str] = set()
        try:
            for result in client.results(search):
                arxiv_id = result.get_short_id()
                if arxiv_id in seen_ids:
                    continue
                seen_ids.add(arxiv_id)
                records.append(PaperRecord(
                    arxiv_id=arxiv_id,
                    title=result.title,
                    authors=[a.name for a in result.authors],
                    year=result.published.year,
                    url=result.entry_id,
                    abstract=result.summary.replace("\n", " "),
                    doi=result.doi or "",
                    source="arxiv",
                ))
        except arxiv.HTTPError as exc:
            if is_rate_limit_status("arxiv", exc.status):
                until = limiter.block("arxiv", f"HTTP {exc.status} on search")
                raise SourceBlocked("arxiv", until, f"HTTP {exc.status}") from exc
            raise

        logger.info("Fetched %d papers from arXiv.", len(records))
        return records

    # ------------------------------------------------------------------
    def download_pdf(self, record: PaperRecord) -> Path | None:
        """
        Download one arXiv PDF from export.arxiv.org (arXiv's host for
        programmatic access), paced through tools.rate_limit. Returns the
        path, or None on failure. Raises SourceBlocked on throttling.
        """
        pdf_path = self._papers_dir / f"{record.arxiv_id.replace('/', '_')}.pdf"
        if pdf_path.exists():
            return pdf_path

        limiter = get_limiter()
        limiter.acquire("arxiv")
        url = f"https://export.arxiv.org/pdf/{record.arxiv_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "research-agent-lab/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                pdf_path.parent.mkdir(parents=True, exist_ok=True)
                pdf_path.write_bytes(resp.read())
            return pdf_path
        except urllib.error.HTTPError as exc:
            if is_rate_limit_status("arxiv", exc.code):
                until = limiter.block("arxiv", f"HTTP {exc.code} on PDF download")
                raise SourceBlocked("arxiv", until, f"HTTP {exc.code}") from exc
            logger.warning("PDF download failed for %s: %s", record.arxiv_id, exc)
            return None
        except Exception as exc:
            logger.warning("PDF download failed for %s: %s", record.arxiv_id, exc)
            return None

    # ------------------------------------------------------------------
    def deduplicate(self, papers: list[PaperRecord]) -> list[PaperRecord]:
        """Remove exact-ID duplicates from a list of PaperRecords."""
        seen: set[str] = set()
        result: list[PaperRecord] = []
        for p in papers:
            if p.arxiv_id not in seen:
                seen.add(p.arxiv_id)
                result.append(p)
        return result
