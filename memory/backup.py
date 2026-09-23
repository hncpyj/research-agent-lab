"""
Backups, session export and session removal.

Every session this project has ever run lives in one SQLite file, and until
2026-09-20 there was no backup, no export and no way to remove a session — a
corrupt file would have taken the lot, and failed runs piled up in the list
with no way to clear them.

A removed session is not destroyed: its rows are written to a bundle under
data/removed/ and its folders are moved there, so it can be restored by hand.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config

TABLES = ("research_sessions", "papers", "hypotheses", "experiment_code", "experiment_runs",
          "degradations", "research_artifacts")
KEEP_BACKUPS = 10


def backups_dir() -> Path:
    path = Path(config.DB_DIR) / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def removed_dir() -> Path:
    path = Path(config.DATA_DIR) / "removed"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_backups() -> list[dict]:
    return sorted(({"name": p.name, "bytes": p.stat().st_size,
                    "made_at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")}
                   for p in backups_dir().glob("research-*.db")),
                  key=lambda b: b["made_at"], reverse=True)


def backup_db(reason: str = "manual", db_path: Path | None = None, keep: int = KEEP_BACKUPS) -> Path:
    """Copy the database with SQLite's own backup API (safe while it is in use)."""
    source = Path(db_path or config.SQLITE_PATH)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = backups_dir() / f"research-{stamp}-{reason}.db"
    src, dst = sqlite3.connect(source), sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()          # Windows keeps the file locked until it is closed
        src.close()
    for old in list_backups()[keep:]:
        (backups_dir() / old["name"]).unlink(missing_ok=True)
    return target


def backup_if_stale(max_age_hours: int = 24, reason: str = "daily") -> Path | None:
    """One backup a day, made when the server starts."""
    latest = list_backups()
    if latest:
        made = datetime.fromisoformat(latest[0]["made_at"])
        if datetime.now(timezone.utc) - made < timedelta(hours=max_age_hours):
            return None
    return backup_db(reason)


def export_session(session_id: str, db_path: Path | None = None) -> dict:
    """Everything stored for one session, as a JSON-ready bundle."""
    conn = sqlite3.connect(db_path or config.SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    bundle: dict = {"format": "research-agent-session/1", "session_id": session_id,
                    "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tables": {}}
    try:
        for table in TABLES:
            column = "session_id"
            rows = conn.execute(f"SELECT * FROM {table} WHERE {column} = ?", (session_id,)).fetchall()
            bundle["tables"][table] = [dict(r) for r in rows]
    finally:
        conn.close()
    if not bundle["tables"]["research_sessions"]:
        raise KeyError(session_id)

    folder = config.session_experiment_dir(session_id)
    notebook = folder / "notebook.jsonl"
    bundle["notebook"] = notebook.read_text(encoding="utf-8").splitlines() if notebook.exists() else []
    bundle["experiment_files"] = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()) \
        if folder.exists() else []
    report = Path(config.BASE_DIR) / "data" / "reports" / session_id / "report.json"
    bundle["report"] = json.loads(report.read_text(encoding="utf-8")) if report.exists() else None
    return bundle


def remove_session(session_id: str, db_path: Path | None = None) -> dict:
    """
    Take a session out of the list: back up the database, write the session's
    bundle and move its folders under data/removed/, then delete its rows.
    """
    bundle = export_session(session_id, db_path)
    backup = backup_db("before-remove", db_path)
    target = removed_dir() / session_id
    target.mkdir(parents=True, exist_ok=True)
    (target / "session.json").write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")

    moved = []
    for folder in (config.session_experiment_dir(session_id),
                   Path(config.BASE_DIR) / "data" / "reports" / session_id):
        if folder.exists():
            destination = target / folder.parent.name
            if destination.exists():
                shutil.rmtree(destination)
            shutil.move(str(folder), str(destination))
            moved.append(destination.as_posix())

    conn = sqlite3.connect(db_path or config.SQLITE_PATH)
    removed = {}
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        for table in reversed(TABLES):
            removed[table] = conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,)).rowcount
        conn.commit()
    finally:
        conn.close()
    return {"session_id": session_id, "rows_removed": removed, "moved": moved,
            "bundle": (target / "session.json").as_posix(), "backup": backup.as_posix()}
