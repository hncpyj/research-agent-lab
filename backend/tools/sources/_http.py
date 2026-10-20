"""Shared request helper: every call is paced and block-checked per source."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import config
from tools.rate_limit import SourceBlocked, get_limiter, is_rate_limit_status

_TIMEOUT = 30


class SourceUnavailable(Exception):
    """A source can't be used at all in this configuration (e.g. missing API key)."""


def user_agent() -> str:
    contact = f" (mailto:{config.CONTACT_EMAIL})" if config.CONTACT_EMAIL else ""
    return f"research-agent-lab/1.0{contact}"


def _request(source: str, url: str, headers: dict, body: dict | None) -> bytes:
    limiter = get_limiter()
    limiter.acquire(source)

    hdrs = {"User-Agent": user_agent()}
    hdrs.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if is_rate_limit_status(source, exc.code):
            until = limiter.block(source, f"HTTP {exc.code} from {url.split('?')[0]}")
            raise SourceBlocked(source, until, f"HTTP {exc.code}") from exc
        raise


def request_json(source: str, url: str, headers: dict | None = None, body: dict | None = None):
    """
    GET (or POST when `body` is given) and decode JSON.
    Raises SourceBlocked if the source is blocked, or becomes blocked because
    this response signalled rate limiting.
    """
    raw = _request(source, url, {"Accept": "application/json", **(headers or {})}, body)
    return json.loads(raw)


def request_text(source: str, url: str, headers: dict | None = None) -> str:
    """GET and decode as UTF-8 text (e.g. XML), with the same pacing and blocking."""
    return _request(source, url, headers or {}, None).decode("utf-8", errors="replace")
