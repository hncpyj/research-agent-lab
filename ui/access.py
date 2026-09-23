"""
Who may use this server.

Until now access was one string in .env: to change it you edited a file and
restarted, and there was no way to see what was set, revoke it, or have more
than one. Tokens live in the database instead, so the settings page can list
them (masked), add one, and revoke one while the server runs.

The .env value still works and is listed as a read-only entry, so an existing
setup keeps working and a first token can always be bootstrapped from a file.

With no token at all the server is open, which is fine on localhost and is
what run_ui.py enforces: it refuses to bind a non-loopback address unless a
token exists.
"""

from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import config

TOKEN_BYTES = 32
ENV_TOKEN_ID = "env"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or config.SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ui_tokens (
            token_id     TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            token        TEXT NOT NULL UNIQUE,
            created_at   TEXT NOT NULL,
            last_used_at TEXT,
            revoked_at   TEXT
        )
        """
    )
    return conn


def mask(token: str) -> str:
    """Enough to recognise a token, not enough to use it."""
    if len(token) <= 10:
        return token[:2] + "•" * 6
    return f"{token[:6]}{'•' * 8}{token[-4:]}"


def list_tokens(db_path: Path | None = None) -> list[dict]:
    """Every token that can open this server, newest first; the .env one last."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM ui_tokens WHERE revoked_at IS NULL ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    tokens = [{"id": r["token_id"], "name": r["name"], "masked": mask(r["token"]),
               "created_at": r["created_at"], "last_used_at": r["last_used_at"],
               "source": "database", "can_revoke": True} for r in rows]
    if config.UI_TOKEN:
        tokens.append({"id": ENV_TOKEN_ID, "name": "UI_TOKEN in .env", "masked": mask(config.UI_TOKEN),
                       "created_at": None, "last_used_at": None,
                       "source": "env file", "can_revoke": False})
    return tokens


def create_token(name: str, db_path: Path | None = None) -> dict:
    """Make a token. The full value is returned once here and shown masked afterwards."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    token_id = secrets.token_hex(8)
    conn = _connect(db_path)
    try:
        conn.execute("INSERT INTO ui_tokens (token_id, name, token, created_at) VALUES (?, ?, ?, ?)",
                     (token_id, (name or "").strip() or "unnamed", token, _now()))
        conn.commit()
    finally:
        conn.close()
    return {"id": token_id, "name": (name or "").strip() or "unnamed", "token": token,
            "masked": mask(token), "created_at": _now(), "source": "database", "can_revoke": True}


def reveal(token_id: str, db_path: Path | None = None) -> str | None:
    """The full value of one token, for the person who is already signed in."""
    if token_id == ENV_TOKEN_ID:
        return config.UI_TOKEN or None
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT token FROM ui_tokens WHERE token_id = ? AND revoked_at IS NULL",
                           (token_id,)).fetchone()
    finally:
        conn.close()
    return row["token"] if row else None


def revoke_token(token_id: str, db_path: Path | None = None) -> bool:
    """Stop a token working. The .env one cannot be revoked from here — edit the file."""
    if token_id == ENV_TOKEN_ID:
        return False
    conn = _connect(db_path)
    try:
        changed = conn.execute("UPDATE ui_tokens SET revoked_at = ? WHERE token_id = ? AND revoked_at IS NULL",
                               (_now(), token_id)).rowcount
        conn.commit()
    finally:
        conn.close()
    return bool(changed)


def verify(token: str | None, db_path: Path | None = None) -> bool:
    """True if this token opens the server; records when it was last used."""
    if not token:
        return False
    if config.UI_TOKEN and secrets.compare_digest(token, config.UI_TOKEN):
        return True
    conn = _connect(db_path)
    try:
        for row in conn.execute("SELECT token_id, token FROM ui_tokens WHERE revoked_at IS NULL"):
            if secrets.compare_digest(token, row["token"]):
                conn.execute("UPDATE ui_tokens SET last_used_at = ? WHERE token_id = ?",
                             (_now(), row["token_id"]))
                conn.commit()
                return True
    finally:
        conn.close()
    return False


def locked(db_path: Path | None = None) -> bool:
    """Whether a token is needed at all. False means anyone who reaches the port is in."""
    return bool(config.UI_TOKEN) or bool(list_tokens(db_path))
