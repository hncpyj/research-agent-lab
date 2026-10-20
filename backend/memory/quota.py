"""
How much of the allowance is used, and what happens when a run fails.

Two rules decide the shape of this:

- A run must be counted before it starts, not after. Counting at the end lets
  two requests that arrive together both pass a check that says "9 used of 10".
  So a run reserves its place first, and the reservation is settled later.

- A run that fails because of *our* fault must not cost the user a run. That
  distinction has to exist in the data, not in an apology, so every settlement
  records why.

An allowance period is a calendar month, stored explicitly rather than counted
from events at request time: the question "how many do I have left" must have
the same answer for the page, the API and the runner.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
from memory import plans

logger = logging.getLogger(__name__)

# How a run ended, and whether it should count against the allowance.
COMPLETED = "completed"
FAILED_USER = "failed_user"          # the brief, the data or the plan was wrong: counts
FAILED_SYSTEM = "failed_system"      # our fault: does not count
FAILED_PROVIDER = "failed_provider"  # the model provider's fault: does not count
CANCELLED = "cancelled"              # stopped before it did the work: does not count

_COUNTS_AGAINST_ALLOWANCE = {COMPLETED, FAILED_USER}


class QuotaExceeded(RuntimeError):
    """The plan does not allow another run right now."""

    def __init__(self, message: str, *, limit=None, used=None, reason: str = "allowance"):
        super().__init__(message)
        self.limit, self.used, self.reason = limit, used, reason


@dataclass(frozen=True)
class Allowance:
    period_start: str
    period_end: str
    plan: str
    limit: int | None            # None = unlimited
    used: int
    reserved: int
    running: int
    concurrent_limit: int | None

    @property
    def remaining(self) -> int | None:
        if self.limit is None:
            return None
        return max(0, self.limit - self.used - self.reserved)

    def as_dict(self) -> dict:
        return {"period_start": self.period_start, "period_end": self.period_end,
                "plan": self.plan, "limit": self.limit, "used": self.used,
                "reserved": self.reserved, "remaining": self.remaining,
                "running": self.running, "concurrent_limit": self.concurrent_limit}


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or config.SQLITE_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hosted_runs (
            run_id      TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            session_id  TEXT NOT NULL DEFAULT '',
            stage       TEXT NOT NULL DEFAULT '',
            period      TEXT NOT NULL,
            state       TEXT NOT NULL,          -- reserved | running | settled
            outcome     TEXT NOT NULL DEFAULT '',
            counted     INTEGER NOT NULL DEFAULT 0,
            reason      TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            settled_at  TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_user_period ON hosted_runs(user_id, period)")
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def period_of(when: datetime | None = None) -> tuple[str, str, str]:
    """The calendar month a moment falls in: (key, start, end)."""
    when = when or datetime.now(timezone.utc)
    start = when.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=32)).replace(day=1)
    return start.strftime("%Y-%m"), start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def allowance(user, db_path: Path | None = None) -> Allowance:
    """What is left this period, for the page and the API to agree on."""
    plan = plans.plan_for(user)
    key, start, end = period_of()
    limit = plan.entitlements["hosted_runs_per_period"]
    concurrent = plan.entitlements["concurrent_runs"]
    if user is None:
        return Allowance(start, end, plan.key, limit, 0, 0, 0, concurrent)

    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT "
            " SUM(CASE WHEN state = 'settled' AND counted = 1 THEN 1 ELSE 0 END) used, "
            " SUM(CASE WHEN state = 'reserved' THEN 1 ELSE 0 END) reserved, "
            " SUM(CASE WHEN state = 'running' THEN 1 ELSE 0 END) running "
            "FROM hosted_runs WHERE user_id = ? AND period = ?",
            (user.user_id, key)).fetchone()
    finally:
        conn.close()
    return Allowance(start, end, plan.key, limit, row["used"] or 0,
                     row["reserved"] or 0, row["running"] or 0, concurrent)


def reserve(user, session_id: str = "", stage: str = "", db_path: Path | None = None) -> str:
    """
    Claim a place before the work starts. Raises QuotaExceeded when the plan
    does not allow it. Returns a run id to settle later.

    The check and the insert happen inside one immediate transaction, so two
    requests arriving together cannot both see the last free slot.
    """
    plan = plans.plan_for(user)
    if user is None:                       # nobody's server but your own
        return ""

    key, _, _ = period_of()
    limit = plan.entitlements["hosted_runs_per_period"]
    concurrent_limit = plan.entitlements["concurrent_runs"]
    run_id = str(uuid.uuid4())

    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT "
            " SUM(CASE WHEN state = 'settled' AND counted = 1 THEN 1 ELSE 0 END) used, "
            " SUM(CASE WHEN state = 'reserved' THEN 1 ELSE 0 END) reserved, "
            " SUM(CASE WHEN state IN ('reserved','running') THEN 1 ELSE 0 END) active "
            "FROM hosted_runs WHERE user_id = ? AND period = ?",
            (user.user_id, key)).fetchone()
        used, reserved, active = row["used"] or 0, row["reserved"] or 0, row["active"] or 0

        if concurrent_limit is not None and active >= concurrent_limit:
            conn.execute("ROLLBACK")
            raise QuotaExceeded(
                f"{plan.label} allows {concurrent_limit} research run"
                f"{'' if concurrent_limit == 1 else 's'} at a time. Wait for the current one, "
                "or stop it.", limit=concurrent_limit, used=active, reason="concurrency")
        if limit is not None and used + reserved >= limit:
            conn.execute("ROLLBACK")
            raise QuotaExceeded(
                f"{plan.label} includes {limit} hosted research runs this month and "
                f"{used} have been used. The allowance resets at the start of next month.",
                limit=limit, used=used, reason="allowance")

        conn.execute(
            "INSERT INTO hosted_runs (run_id, user_id, session_id, stage, period, state, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'reserved', ?)",
            (run_id, user.user_id, session_id, stage, key, _now()))
        conn.execute("COMMIT")
    except QuotaExceeded:
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return run_id


def start(run_id: str, session_id: str = "", db_path: Path | None = None) -> None:
    """The reserved run has actually begun."""
    if not run_id:
        return
    conn = _connect(db_path)
    try:
        conn.execute("UPDATE hosted_runs SET state = 'running', session_id = COALESCE(NULLIF(?, ''), session_id) "
                     "WHERE run_id = ? AND state = 'reserved'", (session_id, run_id))
    finally:
        conn.close()


def settle(run_id: str, outcome: str, reason: str = "", db_path: Path | None = None) -> bool:
    """
    Close a run. Returns whether it counted against the allowance.

    Settling twice does nothing the second time: a stop and a crash can both
    try to close the same run, and neither should double-count it.
    """
    if not run_id:
        return False
    counted = 1 if outcome in _COUNTS_AGAINST_ALLOWANCE else 0
    conn = _connect(db_path)
    try:
        changed = conn.execute(
            "UPDATE hosted_runs SET state = 'settled', outcome = ?, counted = ?, reason = ?, "
            "settled_at = ? WHERE run_id = ? AND state != 'settled'",
            (outcome, counted, reason, _now(), run_id)).rowcount
    finally:
        conn.close()
    if not changed:
        logger.debug("Run %s was already settled; left as it was.", run_id)
    return bool(counted and changed)


def history(user, limit: int = 50, db_path: Path | None = None) -> list[dict]:
    """This person's recent runs, so a disputed allowance can be looked at."""
    if user is None:
        return []
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT run_id, session_id, stage, period, state, outcome, counted, reason, "
            "created_at, settled_at FROM hosted_runs WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT ?", (user.user_id, limit)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
