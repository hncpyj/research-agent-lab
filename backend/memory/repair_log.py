"""
What each repair attempt did, kept so the loop can be judged later.

Three API calls were spent rewriting the wrong file and nothing recorded which
file, which strategy, or whether the error even changed. Without that, "does
the repair loop work?" can only be answered by reading logs by hand, one run at
a time, and a better policy cannot be trained, tuned, or even argued for.

So every attempt leaves a row: what the failure was before the patch, what was
tried, what the failure was after, and which of four things happened.

    fixed        the phase went on to succeed
    progressed   a different failure: the cause it aimed at is gone
    same_error   the identical failure: that patch reached nothing
    regressed    the failure moved into a file that was working before

`same_error` is the one to count. It is the shape the 2026-09-21 run had three
times in a row, and a repair loop that produces it is spending money to stand
still.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import config

logger = logging.getLogger(__name__)

FIXED, PROGRESSED, SAME_ERROR, REGRESSED = "fixed", "progressed", "same_error", "regressed"
# A patch that was written but never applied, because applying it would have
# changed the experiment (tools/patch_guard.py).
REFUSED = "refused"


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or config.SQLITE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS repair_attempts (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id          TEXT NOT NULL,
            phase               TEXT NOT NULL DEFAULT '',
            attempt             INTEGER NOT NULL DEFAULT 0,
            strategy            TEXT NOT NULL DEFAULT '',
            target_file         TEXT NOT NULL DEFAULT '',
            culprit_file        TEXT NOT NULL DEFAULT '',
            fingerprint_before  TEXT NOT NULL DEFAULT '',
            fingerprint_after   TEXT NOT NULL DEFAULT '',
            outcome             TEXT NOT NULL DEFAULT '',
            -- What the attempt cost and what made it, so a later reading of
            -- this table can tell a model change from a prompt change.
            model_id            TEXT NOT NULL DEFAULT '',
            prompt_version      TEXT NOT NULL DEFAULT '',
            tokens_used         INTEGER NOT NULL DEFAULT 0,
            cost_usd            REAL NOT NULL DEFAULT 0,
            refusal_reason      TEXT NOT NULL DEFAULT '',
            created_at          TEXT NOT NULL,
            settled_at          TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_repair_session ON repair_attempts(session_id)")
    for column, kind in (("model_id", "TEXT NOT NULL DEFAULT ''"),
                         ("prompt_version", "TEXT NOT NULL DEFAULT ''"),
                         ("tokens_used", "INTEGER NOT NULL DEFAULT 0"),
                         ("cost_usd", "REAL NOT NULL DEFAULT 0"),
                         ("refusal_reason", "TEXT NOT NULL DEFAULT ''")):
        try:
            conn.execute(f"ALTER TABLE repair_attempts ADD COLUMN {column} {kind}")
        except sqlite3.OperationalError:
            pass                                   # already there
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record(session_id: str, phase: str, attempt: int, strategy: str, target_file: str,
           fingerprint_before: str, culprit_file: str = "", model_id: str = "",
           prompt_version: str = "", db_path: Path | None = None) -> int:
    """A repair is about to be made. Returns the row to settle afterwards."""
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            "INSERT INTO repair_attempts (session_id, phase, attempt, strategy, target_file, "
            "culprit_file, fingerprint_before, model_id, prompt_version, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, phase, attempt, strategy, target_file, culprit_file,
             fingerprint_before, model_id, prompt_version, _now()))
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def settle(row_id: int, outcome: str, fingerprint_after: str = "",
           refusal_reason: str = "", tokens_used: int = 0, cost_usd: float = 0.0,
           db_path: Path | None = None) -> None:
    """What the attempt turned out to have achieved, and what it cost."""
    if not row_id:
        return
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE repair_attempts SET outcome = ?, fingerprint_after = ?, "
            "refusal_reason = ?, tokens_used = ?, cost_usd = ?, settled_at = ? "
            "WHERE id = ? AND outcome = ''",
            (outcome, fingerprint_after, refusal_reason, tokens_used, cost_usd,
             _now(), row_id))
        conn.commit()
    finally:
        conn.close()


def judge(before: str, after: str, succeeded: bool) -> str:
    """Which of the four things happened, from the failures either side."""
    if succeeded:
        return FIXED
    if after and before and after == before:
        return SAME_ERROR
    return PROGRESSED


def history(session_id: str, db_path: Path | None = None) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM repair_attempts WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def summary(db_path: Path | None = None) -> dict:
    """
    How the repair loop is doing overall: by outcome, and by strategy.

    The number worth watching is `same_error`: attempts that changed nothing.
    """
    conn = _connect(db_path)
    try:
        by_outcome = {r["outcome"] or "unsettled": r["n"] for r in conn.execute(
            "SELECT outcome, COUNT(*) n FROM repair_attempts GROUP BY outcome")}
        by_strategy = {}
        for row in conn.execute(
                "SELECT strategy, outcome, COUNT(*) n FROM repair_attempts "
                "GROUP BY strategy, outcome"):
            by_strategy.setdefault(row["strategy"], {})[row["outcome"] or "unsettled"] = row["n"]
        total = sum(by_outcome.values())
    finally:
        conn.close()
    return {"attempts": total, "by_outcome": by_outcome, "by_strategy": by_strategy,
            "wasted": by_outcome.get(SAME_ERROR, 0)}
