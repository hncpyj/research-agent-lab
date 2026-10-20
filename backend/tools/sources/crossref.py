"""Crossref works search — publisher-deposited metadata; abstracts often missing."""

from __future__ import annotations

import re
import urllib.parse

import config
from tools.arxiv_fetcher import PaperRecord
from tools.sources._http import request_json

SOURCE = "crossref"
_BASE = "https://api.crossref.org/works"


def search(query: str, limit: int) -> list[PaperRecord]:
    params = {
        "query.bibliographic": query,
        "rows": limit,
        "select": "DOI,title,author,issued,abstract,URL",
    }
    if config.CONTACT_EMAIL:
        params["mailto"] = config.CONTACT_EMAIL  # polite pool
    data = request_json(SOURCE, f"{_BASE}?{urllib.parse.urlencode(params)}")
    items = (data.get("message") or {}).get("items", [])
    return [r for r in (_to_record(i) for i in items) if r]


def _to_record(i: dict) -> PaperRecord | None:
    title = " ".join(i.get("title") or []).strip()
    doi = i.get("DOI") or ""
    if not title or not doi:
        return None
    date_parts = ((i.get("issued") or {}).get("date-parts") or [[None]])[0]
    return PaperRecord(
        arxiv_id=f"doi:{doi}",
        title=title,
        authors=[
            " ".join(p for p in (a.get("given"), a.get("family")) if p)
            for a in (i.get("author") or [])
            if a.get("family")
        ],
        year=date_parts[0] or 0,
        url=i.get("URL") or f"https://doi.org/{doi}",
        abstract=re.sub(r"<[^>]+>", " ", i.get("abstract") or "").strip(),
        doi=doi,
        source=SOURCE,
    )
