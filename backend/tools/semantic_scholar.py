"""
Semantic Scholar canon-seeding fetcher.

Why this exists: the arXiv keyword search in PaperCollectionAgent sorts by
relevance/recency, which systematically misses foundational, highly-cited
papers that predate the keyword phrasing currently in fashion (e.g. Vaswani
2017 "Attention Is All You Need", Hochreiter 1997 LSTM). An audit found the
agent's own paper collections had ZERO overlap with the 28-paper bibliography
of an actual expert-written paper in an adjacent subfield — the canon was
simply never fetched. This module supplements keyword search with a
citation-count-sorted query so the most influential prior work is always
considered, independent of how recent or keyword-matched it is.

Uses the Semantic Scholar Graph API. Without SEMANTIC_SCHOLAR_API_KEY,
requests share one global anonymous pool and are often throttled; requests
are paced and blocked per tools/rate_limit.py either way.
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

import config
from tools.arxiv_fetcher import PaperRecord
from tools.rate_limit import SourceBlocked
from tools.sources._http import request_json

logger = logging.getLogger(__name__)

SOURCE = "semantic_scholar"
_API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_FIELDS = "title,abstract,year,authors,externalIds,citationCount"


class SemanticScholarFetcher:
    """
    Fetches the most-cited papers for a query. Best-effort only: every
    public method catches its own exceptions and returns [] on failure so a
    down or rate-limited API never blocks the paper-collection phase.
    """

    def search_top_cited(
        self, query: str, limit: int = 5, min_citation_count: int = 20
    ) -> list[PaperRecord]:
        """
        Return up to `limit` papers matching `query`, sorted by citation
        count descending, filtered to citation_count >= min_citation_count
        (excludes very recent/uncited papers — those are already well
        covered by the arXiv relevance search this supplements).
        """
        try:
            raw = self._raw_search(query, limit=max(limit * 3, 20))
        except SourceBlocked:
            raise  # callers record why canon seeding didn't run
        except Exception as exc:
            logger.warning("Semantic Scholar canon search failed for %r: %s", query, exc)
            return []

        candidates = [p for p in raw if (p.get("citationCount") or 0) >= min_citation_count]
        candidates.sort(key=lambda p: p.get("citationCount") or 0, reverse=True)

        records: list[PaperRecord] = []
        for p in candidates[:limit]:
            record = self._to_paper_record(p)
            if record is not None:
                records.append(record)

        logger.info(
            "Semantic Scholar canon search: query=%r found %d, kept %d (citation_count>=%d)",
            query, len(raw), len(records), min_citation_count,
        )
        return records

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _raw_search(self, query: str, limit: int) -> list[dict]:
        params = urllib.parse.urlencode({
            "query": query,
            "fields": _FIELDS,
            "limit": limit,
            "sort": "citationCount:desc",
        })
        headers = {}
        if config.SEMANTIC_SCHOLAR_API_KEY:
            headers["x-api-key"] = config.SEMANTIC_SCHOLAR_API_KEY
        # One paced request, no retries — a throttled source is blocked for
        # SOURCE_BLOCK_DAYS rather than retried (see tools/rate_limit.py).
        data = request_json(SOURCE, f"{_API_URL}?{params}", headers=headers)
        return data.get("data", []) or []

    @staticmethod
    def _to_paper_record(p: dict[str, Any]) -> PaperRecord | None:
        title = (p.get("title") or "").strip()
        if not title:
            return None

        external_ids = p.get("externalIds") or {}
        arxiv_id = external_ids.get("ArXiv")
        # Papers without an arXiv id can't be PDF-downloaded by ArxivFetcher,
        # but the literature review agent already supports abstract-only
        # fallback, so we still keep them — keyed by a synthetic id.
        key = arxiv_id or f"s2:{p.get('paperId', title[:40])}"

        authors = [a.get("name", "") for a in (p.get("authors") or []) if a.get("name")]

        return PaperRecord(
            arxiv_id=key,
            title=title,
            authors=authors,
            year=p.get("year") or 0,
            url=f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else p.get("url", "") or "",
            abstract=(p.get("abstract") or "").replace("\n", " "),
            pdf_path=None,
            doi=external_ids.get("DOI") or "",
            source="arxiv" if arxiv_id else SOURCE,
        )
