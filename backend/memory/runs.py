"""
Which runs are actually running, written down where a restart cannot lose it.

A run lives in a background thread inside the web server. Nothing outside that
process knew about it, so when the server stopped -- a deploy, a crash, a
closed laptop -- three things went wrong at once and none of them were visible:

- the session simply stopped mid-phase, and the page still offered to watch a
  run that no longer existed;
- the place the run had taken in the plan's allowance was never settled, so a
  free account stayed at "1 research run at a time" forever;
- nobody was told. The user came back to a session that looked finished at a
  stage it had not finished.

So a run writes a row here when it starts, touches it while it works, and
removes it when it ends. Whatever is left over belongs to a process that is
gone, and startup turns each leftover into what it really is: an interrupted
run, settled as our fault, with the session told why it stopped.

Interrupted runs are not restarted on their own. A research run spends money
and stops at gates for a person to answer; starting one again because a server
rebooted is not a decision this module may take. The row stays as a marker the
page can show, with one button to carry on.
"""

from __future__ import annotations

import logging
import os
import socket
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import config

logger = logging.getLogger(__name__)

RUNNING = "running"
INTERRUPTED = "interrupted"

# How long a run may go without touching its row before we stop believing it.
# Long enough for a slow phase that emits nothing (a model call, a training
# script), short enough that a restart is noticed within a minute or two.
STALE_AFTER_S = 180

# New for every process. A row carrying a different one was written by a
# server that is not this one.
BOOT_ID = str(uuid.uuid4())
HOST = socket.gethostname()

INTERRUPTED_NOTE = ("The server stopped while this run was working, so the run ended "
                    "part-way through. Nothing that was already saved is lost; "
                    "resume the session to carry on from the last finished step.")


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or config.SQLITE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS active_runs (
            session_id   TEXT PRIMARY KEY,
            run_id       TEXT NOT NULL DEFAULT '',
            stage        TEXT NOT NULL DEFAULT '',
            state        TEXT NOT NULL,
            host         TEXT NOT NULL DEFAULT '',
            pid          INTEGER NOT NULL DEFAULT 0,
            boot_id      TEXT NOT NULL DEFAULT '',
            started_at   TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL DEFAULT '',
            note         TEXT NOT NULL DEFAULT ''
        )
        """
    )
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _age_seconds(stamp: str) -> float:
    if not stamp:
        return float("inf")
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        return float("inf")
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).total_seconds()


def process_alive(pid: int, host: str = "") -> bool:
    """
    Whether that process still exists on this machine.

    A pid from another machine cannot be checked, so it is believed and the
    heartbeat decides instead. A pid can also be reused after a reboot, which
    is why the boot id is checked first by everything that calls this.
    """
    if not pid or (host and host != HOST):
        return True
    if os.name == "nt":
        import ctypes

        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:                        # someone else's process: it exists
        return True
    return True


# --- a run saying where it is ---------------------------------------------------

def begin(session_id: str, run_id: str = "", stage: str = "",
          db_path: Path | None = None) -> None:
    """This process has started working on this session."""
    now = _now()
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO active_runs (session_id, run_id, stage, state, host, pid, boot_id, "
            "started_at, heartbeat_at, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '') "
            "ON CONFLICT(session_id) DO UPDATE SET run_id = excluded.run_id, "
            "stage = excluded.stage, state = excluded.state, host = excluded.host, "
            "pid = excluded.pid, boot_id = excluded.boot_id, started_at = excluded.started_at, "
            "heartbeat_at = excluded.heartbeat_at, note = ''",
            (session_id, run_id, stage, RUNNING, HOST, os.getpid(), BOOT_ID, now, now))
        conn.commit()
    finally:
        conn.close()


def heartbeat(session_id: str, db_path: Path | None = None) -> None:
    """Still here. Called as the run emits events, not on a timer of its own."""
    conn = _connect(db_path)
    try:
        conn.execute("UPDATE active_runs SET heartbeat_at = ? WHERE session_id = ? AND boot_id = ?",
                     (_now(), session_id, BOOT_ID))
        conn.commit()
    finally:
        conn.close()


def finish(session_id: str, db_path: Path | None = None) -> None:
    """The run ended in an orderly way -- done, stopped or failed on its own."""
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM active_runs WHERE session_id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()


def clear(session_id: str, db_path: Path | None = None) -> None:
    """Forget an interrupted marker: the user has seen it and moved on."""
    finish(session_id, db_path=db_path)


# --- what is left over ------------------------------------------------------------

def get(session_id: str, db_path: Path | None = None) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM active_runs WHERE session_id = ?",
                           (session_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def interrupted(session_id: str, db_path: Path | None = None) -> dict | None:
    """The marker the page shows: this session stopped part-way, here is when."""
    row = get(session_id, db_path=db_path)
    return row if row and row["state"] == INTERRUPTED else None


def list_all(state: str = "", db_path: Path | None = None) -> list[dict]:
    conn = _connect(db_path)
    try:
        if state:
            rows = conn.execute("SELECT * FROM active_runs WHERE state = ? ORDER BY started_at",
                                (state,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM active_runs ORDER BY started_at").fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _abandoned(row: dict) -> bool:
    """Whether the process that wrote this row is gone."""
    if row["state"] != RUNNING:
        return False
    if row["boot_id"] == BOOT_ID:
        return False                               # ours, and we would know
    if not process_alive(row["pid"], row["host"]):
        return True
    return _age_seconds(row["heartbeat_at"]) > STALE_AFTER_S


def recover(db_path: Path | None = None) -> list[dict]:
    """
    Turn every leftover row into an interrupted run: settle its place in the
    allowance as our fault, tell the session why it stopped, and leave a marker
    the page can show.

    Safe to call repeatedly, and while another server is running: a row is only
    touched once its own process is gone.
    """
    recovered = []
    for row in list_all(RUNNING, db_path=db_path):
        if not _abandoned(row):
            continue
        _settle(row, db_path=db_path)
        _tell_the_session(row, db_path=db_path)
        conn = _connect(db_path)
        try:
            conn.execute("UPDATE active_runs SET state = ?, note = ? WHERE session_id = ?",
                         (INTERRUPTED, INTERRUPTED_NOTE, row["session_id"]))
            conn.commit()
        finally:
            conn.close()
        recovered.append(row)
        logger.warning("Session %s was left running by a server that is gone; "
                       "marked as interrupted.", row["session_id"])
    return recovered


def _settle(row: dict, db_path: Path | None = None) -> None:
    """Give back the place this run held, without charging it to the user."""
    if not row["run_id"]:
        return
    try:
        from memory import quota
        quota.settle(row["run_id"], quota.FAILED_SYSTEM,
                     "the server stopped before this run finished", db_path=db_path)
    except Exception as exc:                       # bookkeeping must not stop startup
        logger.warning("Could not settle interrupted run %s: %s", row["run_id"], exc)


def _tell_the_session(row: dict, db_path: Path | None = None) -> None:
    """Write it where the user will see it, next to every other thing that went wrong."""
    try:
        from agents.degradation import DegradationLog
        from memory.note_db import NoteDB

        db = NoteDB(db_path) if db_path else NoteDB()
        if db.get_session(row["session_id"]) is None:
            return
        DegradationLog(db, row["session_id"]).record(0, "run_interrupted", "critical",
                                                     INTERRUPTED_NOTE)
    except Exception as exc:
        logger.warning("Could not record the interruption of %s: %s", row["session_id"], exc)
