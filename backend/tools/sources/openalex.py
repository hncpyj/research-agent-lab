"""OpenAlex works search — broad journal coverage (policy, health, economics)."""

from __future__ import annotations

import urllib.parse

import config
from tools.arxiv_fetcher import PaperRecord
from tools.sources._http import SourceUnavailable, request_json

SOURCE = "openalex"
_BASE = "https://api.openalex.org/works"
_SELECT = "id,doi,display_name,publication_year,authorships,abstract_inverted_index,primary_location"


def search(query: str, limit: int) -> list[PaperRecord]:
    if not config.OPENALEX_API_KEY:
        raise SourceUnavailable("OPENALEX_API_KEY is not set (required since Feb 2026)")
    params = urllib.parse.urlencode({
        "search": query,
        "per_page": limit,
        "select": _SELECT,
        "api_key": config.OPENALEX_API_KEY,
    })
    data = request_json(SOURCE, f"{_BASE}?{params}")
    return [r for r in (_to_record(w) for w in data.get("results", [])) if r]


def _abstract(inverted: dict | None) -> str:
    if not inverted:
        return ""
    positions = [(pos, word) for word, poss in inverted.items() for pos in poss]
    return " ".join(word for _, word in sorted(positions))


def _to_record(w: dict) -> PaperRecord | None:
    title = (w.get("display_name") or "").strip()
    if not title:
        return None
    work_id = (w.get("id") or "").rsplit("/", 1)[-1]
    doi = (w.get("doi") or "").replace("https://doi.org/", "")
    landing = ((w.get("primary_location") or {}).get("landing_page_url")) or w.get("doi") or w.get("id", "")
    return PaperRecord(
        arxiv_id=f"openalex:{work_id}",
        title=title,
        authors=[
            (a.get("author") or {}).get("display_name", "")
            for a in (w.get("authorships") or [])
            if (a.get("author") or {}).get("display_name")
        ],
        year=w.get("publication_year") or 0,
        url=landing,
        abstract=_abstract(w.get("abstract_inverted_index")),
        doi=doi,
        source=SOURCE,
    )
