"""
Projects: the folder a body of work lives in.

Sessions were a flat list. One question asked twice, a replay with one input
changed, last month's study on the same data -- all of it sat in the same
undifferentiated list, and the only way to tell related work apart was to read
the topic lines. Worse, nothing could be said about a body of work as a whole:
how many papers it has read, which of them it keeps coming back to, what has
actually been concluded.

A project holds sessions. It is deliberately thin -- a name, an owner, and the
sessions that point at it -- because the research itself already lives in the
session rows. Archiving a project never removes research: the plans count
*active* projects, so archiving is how someone stays inside a limit without
throwing work away.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import config

logger = logging.getLogger(__name__)

NO_PROJECT = ""              # a session that has not been filed anywhere


class ProjectError(ValueError):
    """The project cannot be made or changed as asked."""


class ProjectLimit(ProjectError):
    """The plan does not allow another active project."""

    def __init__(self, message: str, limit: int, active: int):
        super().__init__(message)
        self.limit, self.active = limit, active


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or config.SQLITE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            project_id  TEXT PRIMARY KEY,
            owner_id    TEXT NOT NULL DEFAULT '',
            name        TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            archived_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id)")
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["archived"] = bool(out.get("archived_at"))
    return out


# --- making and changing ---------------------------------------------------------

def create(name: str, owner_id: str = "", description: str = "", user=None,
           db_path: Path | None = None) -> dict:
    """
    A new project for this person. `user` is checked against their plan's
    limit on active projects; pass None for the local single-user mode, where
    no plan applies.
    """
    name = (name or "").strip()
    if not name:
        raise ProjectError("A project needs a name.")
    if len(name) > 120:
        raise ProjectError("That name is too long; 120 characters at most.")

    _check_limit(owner_id, user, db_path=db_path)

    project_id = str(uuid.uuid4())
    now = _now()
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO projects (project_id, owner_id, name, description, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, owner_id, name, description.strip(), now, now))
        conn.commit()
    finally:
        conn.close()
    return get(project_id, db_path=db_path)


def _check_limit(owner_id: str, user, db_path: Path | None = None) -> None:
    from memory import plans

    limit = plans.allows(user, "active_projects")
    if limit is None:
        return
    active = len(list_projects(owner_id, db_path=db_path))
    if active >= limit:
        raise ProjectLimit(
            f"{plans.plan_for(user).label} keeps {limit} projects open at a time and "
            f"{active} are open. Archive one to start another — archiving keeps all "
            "of its research.", limit, active)


def get(project_id: str, db_path: Path | None = None) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,)).fetchone()
    finally:
        conn.close()
    return _row(row) if row else None


def list_projects(owner_id: str | None = None, include_archived: bool = False,
                  db_path: Path | None = None) -> list[dict]:
    """
    A person's projects, newest first. owner_id None means "everything on this
    machine", the same rule the session list follows.
    """
    where, params = [], []
    if owner_id is not None:
        where.append("owner_id = ?")
        params.append(owner_id)
    if not include_archived:
        where.append("archived_at = ''")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT * FROM projects{clause} ORDER BY created_at DESC", params).fetchall()
    finally:
        conn.close()
    return [_row(r) for r in rows]


def rename(project_id: str, name: str = "", description: str | None = None,
           db_path: Path | None = None) -> dict:
    project = get(project_id, db_path=db_path)
    if project is None:
        raise ProjectError("No such project.")
    name = (name or "").strip() or project["name"]
    if len(name) > 120:
        raise ProjectError("That name is too long; 120 characters at most.")
    conn = _connect(db_path)
    try:
        conn.execute("UPDATE projects SET name = ?, description = ?, updated_at = ? "
                     "WHERE project_id = ?",
                     (name, project["description"] if description is None else description.strip(),
                      _now(), project_id))
        conn.commit()
    finally:
        conn.close()
    return get(project_id, db_path=db_path)


def archive(project_id: str, archived: bool = True, user=None,
            db_path: Path | None = None) -> dict:
    """
    Put a project away, or bring it back. Sessions keep pointing at it either
    way: this hides a project and frees a place in the plan's limit, it does
    not delete anything.
    """
    project = get(project_id, db_path=db_path)
    if project is None:
        raise ProjectError("No such project.")
    if not archived and project["archived"]:
        _check_limit(project["owner_id"], user, db_path=db_path)
    conn = _connect(db_path)
    try:
        conn.execute("UPDATE projects SET archived_at = ?, updated_at = ? WHERE project_id = ?",
                     (_now() if archived else "", _now(), project_id))
        conn.commit()
    finally:
        conn.close()
    return get(project_id, db_path=db_path)


# --- what is in one --------------------------------------------------------------

def assign(session_id: str, project_id: str, db_path: Path | None = None) -> None:
    """File a session under a project, or under none when project_id is empty."""
    if project_id and get(project_id, db_path=db_path) is None:
        raise ProjectError("No such project.")
    _sessions_table_ready(db_path)
    conn = _connect(db_path)
    try:
        changed = conn.execute(
            "UPDATE research_sessions SET project_id = ? WHERE session_id = ?",
            (project_id, session_id)).rowcount
        conn.commit()
    finally:
        conn.close()
    if not changed:
        raise ProjectError("No such session.")


def _sessions_table_ready(db_path: Path | None = None) -> None:
    """
    The session tables are NoteDB's; a project may be made in a database it has
    not opened yet, and asking for its sessions must not fail because of that.
    """
    from memory.note_db import NoteDB

    NoteDB(db_path) if db_path else NoteDB()


def sessions_of(project_id: str, db_path: Path | None = None) -> list[dict]:
    _sessions_table_ready(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM research_sessions WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def summary(project_id: str, db_path: Path | None = None) -> dict:
    """
    What this project amounts to: how many sessions, how far they got, how
    much has been spent on it, and how many distinct papers it has read.
    """
    from memory import paper_index

    project = get(project_id, db_path=db_path)
    if project is None:
        raise ProjectError("No such project.")
    sessions = sessions_of(project_id, db_path=db_path)
    ids = [s["session_id"] for s in sessions]

    finished = [s for s in sessions if s["status"] in ("experiment_run", "reviewed", "report_written")]
    conn = _connect(db_path)
    try:
        spend = 0.0
        if ids:
            marks = ",".join("?" * len(ids))
            try:
                row = conn.execute(
                    f"SELECT SUM(cost_usd) total FROM api_usage_log WHERE session_id IN ({marks})",
                    ids).fetchone()
                spend = row["total"] or 0.0
            except sqlite3.OperationalError:       # a database from before per-session costs
                spend = 0.0
    finally:
        conn.close()

    return {**project,
            "sessions": len(sessions),
            "finished": len(finished),
            "papers": paper_index.count_for(ids, db_path=db_path),
            "spend_usd": round(spend, 4),
            "last_active": max((s["updated_at"] for s in sessions), default=project["updated_at"])}
