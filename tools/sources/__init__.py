"""
Multi-source paper search.

Spreads queries across several independent sources so no single one carries
the whole load, and so a blocked or unconfigured source degrades coverage
instead of stopping collection. Google Scholar is deliberately absent: it has
no official API and its terms prohibit automated queries.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

import config
from tools.arxiv_fetcher import ArxivFetcher, PaperRecord
from tools.rate_limit import SourceBlocked
from tools.sources import crossref, europepmc, openalex, openreview
from tools.sources._http import SourceUnavailable

logger = logging.getLogger(__name__)


def _arxiv_search(query: str, limit: int) -> list[PaperRecord]:
    return ArxivFetcher().search(query, max_results=limit)


SEARCHERS: dict[str, Callable[[str, int], list[PaperRecord]]] = {
    "arxiv": _arxiv_search,
    "openalex": openalex.search,
    "europepmc": europepmc.search,
    "crossref": crossref.search,
    "openreview": openreview.search,
}


def search_all(
    query: str,
    limit: int = config.SOURCE_MAX_RESULTS,
    sources: list[str] | None = None,
) -> tuple[list[PaperRecord], dict[str, str]]:
    """
    Query every configured source once. Returns (deduplicated papers,
    {source: reason} for each source that returned nothing usable because
    it was blocked, unconfigured, or failed).
    """
    papers: list[PaperRecord] = []
    problems: dict[str, str] = {}
    for name in sources or config.PAPER_SOURCES:
        searcher = SEARCHERS.get(name)
        if searcher is None:
            problems[name] = "unknown source name in PAPER_SOURCES"
            continue
        try:
            papers.extend(searcher(query, limit))
        except (SourceBlocked, SourceUnavailable) as exc:
            problems[name] = str(exc)
        except Exception as exc:
            logger.warning("Paper search failed on %s for %r: %s", name, query, exc)
            problems[name] = f"request failed: {exc}"
    return deduplicate(papers), problems


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())


def deduplicate(papers: list[PaperRecord]) -> list[PaperRecord]:
    """Drop repeats of the same work found via different sources (DOI, then title)."""
    seen_ids, seen_dois, seen_titles = set(), set(), set()
    out: list[PaperRecord] = []
    for p in papers:
        doi = p.doi.lower()
        title = _norm_title(p.title)
        if p.arxiv_id in seen_ids or (doi and doi in seen_dois) or (title and title in seen_titles):
            continue
        seen_ids.add(p.arxiv_id)
        if doi:
            seen_dois.add(doi)
        if title:
            seen_titles.add(title)
        out.append(p)
    return out
