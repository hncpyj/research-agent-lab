"""
Per-source request pacing and block tracking for every external paper /
metadata API this project calls.

Rules (set by the project owner after arXiv blocked this machine on
2026-09-13):
- Every request to an external source waits a randomized 20-30 s after the
  previous request to that same source — far slower than any published
  limit, so pacing is never the reason a source blocks us.
- The moment a source signals rate limiting (429, or 503 from arXiv, which
  uses 503 for throttling), it is marked blocked for 7 days and not
  contacted again until then — no retries, no probing.
- State lives in SQLite, so pacing and blocks hold across threads, the
  Web UI and CLI running side by side, and process restarts.

Published limits, checked 2026-09-13 (all well above our pacing):
- arXiv API: max 1 request / 3 s, single connection; programmatic PDF
  downloads should use export.arxiv.org
  https://info.arxiv.org/help/api/tou.html
  https://info.arxiv.org/help/bulk_data.html
- Semantic Scholar: unauthenticated calls share one global pool (throttled
  under load); an API key gives 1 request / s
  https://www.semanticscholar.org/product/api/tutorial
- OpenAlex: API key required since Feb 2026; free key includes 1,000
  searches / day
  https://blog.openalex.org/openalex-api-new-features-and-usage-based-pricing/
- Europe PMC: 10 requests / s per IP
  https://europepmc.org/RestfulWebService
- Crossref: limits revised 1 Dec 2025 (exact values not retrievable at time
  of writing); honours `mailto` for the polite pool
  https://www.crossref.org/blog/announcing-changes-to-rest-api-rate-limits/
- OpenReview: account login required even for public notes; no published
  read limit
  https://docs.openreview.net/reference/api-v2
"""

from __future__ import annotations

import random
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

import config


class SourceBlocked(Exception):
    """Raised instead of contacting a source that is inside its block window."""

    def __init__(self, source: str, blocked_until: float, reason: str) -> None:
        self.source = source
        self.blocked_until = blocked_until
        self.reason = reason
        until = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(blocked_until))
        super().__init__(f"{source} is blocked until {until} ({reason})")


class RateLimiter:
    def __init__(
        self,
        db_path: Path | None = None,
        min_interval: float | None = None,
        max_interval: float | None = None,
        block_days: float | None = None,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # Resolved now, not at import time — see the note in memory/note_db.py.
        self._db_path = db_path if db_path is not None else config.SQLITE_PATH
        # The pacing figures are read here too, for the same reason: a default
        # argument would freeze whatever config held when this module was first
        # imported, and no later change could reach it.
        self._min = min_interval if min_interval is not None else config.REQUEST_INTERVAL_MIN_S
        self._max = max_interval if max_interval is not None else config.REQUEST_INTERVAL_MAX_S
        days = block_days if block_days is not None else config.SOURCE_BLOCK_DAYS
        self._block_seconds = days * 86400
        self._now = now
        self._sleep = sleep
        self._lock = threading.Lock()
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_access (
                    source           TEXT PRIMARY KEY,
                    next_allowed_at  REAL NOT NULL DEFAULT 0,
                    blocked_until    REAL NOT NULL DEFAULT 0,
                    block_reason     TEXT NOT NULL DEFAULT ''
                )
                """
            )
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=60, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def acquire(self, source: str) -> None:
        """
        Reserve the next request slot for `source` and sleep until it.
        Raises SourceBlocked if the source is inside its block window.
        The reservation is written atomically before sleeping, so concurrent
        callers (threads or processes) queue up instead of firing together.
        """
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT next_allowed_at, blocked_until, block_reason "
                    "FROM source_access WHERE source = ?",
                    (source,),
                ).fetchone()
                next_allowed, blocked_until, reason = row if row else (0.0, 0.0, "")
                now = self._now()
                if blocked_until > now:
                    conn.execute("ROLLBACK")
                    raise SourceBlocked(source, blocked_until, reason)
                slot = max(now, next_allowed)
                following = slot + random.uniform(self._min, self._max)
                conn.execute(
                    """
                    INSERT INTO source_access (source, next_allowed_at)
                    VALUES (?, ?)
                    ON CONFLICT(source) DO UPDATE SET next_allowed_at = excluded.next_allowed_at
                    """,
                    (source, following),
                )
                conn.execute("COMMIT")
            finally:
                conn.close()
        wait = slot - now
        if wait > 0:
            self._sleep(wait)

    def block(self, source: str, reason: str) -> float:
        """Mark `source` as not to be contacted for SOURCE_BLOCK_DAYS."""
        until = self._now() + self._block_seconds
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO source_access (source, blocked_until, block_reason)
                    VALUES (?, ?, ?)
                    ON CONFLICT(source) DO UPDATE SET
                        blocked_until = excluded.blocked_until,
                        block_reason  = excluded.block_reason
                    """,
                    (source, until, reason),
                )
            finally:
                conn.close()
        return until

    def blocked_until(self, source: str) -> float:
        """Epoch seconds the block ends, or 0 if not blocked."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT blocked_until FROM source_access WHERE source = ?", (source,)
            ).fetchone()
        finally:
            conn.close()
        until = row[0] if row else 0.0
        return until if until > self._now() else 0.0


_default: RateLimiter | None = None
_default_lock = threading.Lock()


def get_limiter() -> RateLimiter:
    global _default
    with _default_lock:
        if _default is None:
            _default = RateLimiter()
        return _default


def is_rate_limit_status(source: str, status: int) -> bool:
    """
    429 always means throttling. arXiv also throttles with 503, as does Azure
    Blob Storage (503 ServerBusy), which hosts direct dataset downloads
    (source names "host:<domain>").
    """
    return status == 429 or (status == 503 and (source == "arxiv" or source.startswith("host:")))
