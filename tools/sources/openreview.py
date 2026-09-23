"""
OpenReview note search — ML conference submissions (ICLR, NeurIPS, ...).
Requires an OpenReview account even for public notes.
"""

from __future__ import annotations

import threading
import urllib.parse
from datetime import datetime, timezone

import config
from tools.arxiv_fetcher import PaperRecord
from tools.sources._http import SourceUnavailable, request_json

SOURCE = "openreview"
_BASE = "https://api2.openreview.net"

_token: str | None = None
_token_lock = threading.Lock()


def _get_token() -> str:
    global _token
    if not (config.OPENREVIEW_USERNAME and config.OPENREVIEW_PASSWORD):
        raise SourceUnavailable("OPENREVIEW_USERNAME / OPENREVIEW_PASSWORD are not set")
    with _token_lock:
        if _token is None:
            data = request_json(SOURCE, f"{_BASE}/login", body={
                "id": config.OPENREVIEW_USERNAME,
                "password": config.OPENREVIEW_PASSWORD,
            })
            _token = data["token"]
        return _token


def search(query: str, limit: int) -> list[PaperRecord]:
    token = _get_token()
    params = urllib.parse.urlencode({
        "term": query,
        "type": "terms",
        "content": "all",
        "group": "all",
        "source": "all",
        "limit": limit,
    })
    data = request_json(SOURCE, f"{_BASE}/notes/search?{params}",
                        headers={"Authorization": f"Bearer {token}"})
    return [r for r in (_to_record(n) for n in data.get("notes", [])) if r]


def _value(content: dict, key: str):
    v = content.get(key)
    return v.get("value") if isinstance(v, dict) else v


def _to_record(n: dict) -> PaperRecord | None:
    content = n.get("content") or {}
    title = (_value(content, "title") or "").strip()
    if not title:
        return None
    cdate = n.get("pdate") or n.get("cdate") or 0
    return PaperRecord(
        arxiv_id=f"openreview:{n.get('id', '')}",
        title=title,
        authors=list(_value(content, "authors") or []),
        year=datetime.fromtimestamp(cdate / 1000, tz=timezone.utc).year if cdate else 0,
        url=f"https://openreview.net/forum?id={n.get('forum') or n.get('id', '')}",
        abstract=(_value(content, "abstract") or "").strip(),
        source=SOURCE,
    )
