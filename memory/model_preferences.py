"""Per-account defaults for new model-backed research sessions.

Session rows remain authoritative once a run has been created.  These values
only decide what a signed-in user's next session starts with; they must not be
stored in the process-wide ``ui_settings.json`` on a multi-user host.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import config


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or config.SQLITE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_model_preferences (
            user_id      TEXT PRIMARY KEY,
            use_api      INTEGER,
            api_provider TEXT,
            api_models   TEXT NOT NULL DEFAULT '{}',
            updated_at   TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _defaults() -> dict:
    from tools import app_settings

    return {
        "use_api": app_settings.use_api(),
        "api_provider": app_settings.api_provider(),
        "api_models": {},
    }


def load(user_id: str, db_path: Path | None = None) -> dict:
    defaults = _defaults()
    if not user_id:
        return defaults
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT use_api, api_provider, api_models FROM user_model_preferences "
            "WHERE user_id = ?", (user_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return defaults
    try:
        models = json.loads(row["api_models"] or "{}")
    except (TypeError, ValueError):
        models = {}
    return {
        "use_api": defaults["use_api"] if row["use_api"] is None else bool(row["use_api"]),
        "api_provider": (row["api_provider"] or defaults["api_provider"]).strip().lower(),
        "api_models": models if isinstance(models, dict) else {},
    }


def save(
    user_id: str,
    *,
    use_api: bool | None = None,
    api_provider: str | None = None,
    model_provider: str | None = None,
    api_model: str | None = None,
    db_path: Path | None = None,
) -> dict:
    if not user_id:
        raise ValueError("A user id is required for account model preferences.")
    current = load(user_id, db_path)
    if use_api is not None:
        current["use_api"] = bool(use_api)
    if api_provider is not None:
        current["api_provider"] = api_provider.strip().lower()
    if api_model is not None:
        name = (model_provider or current["api_provider"]).strip().lower()
        current["api_models"][name] = api_model.strip()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO user_model_preferences
                (user_id, use_api, api_provider, api_models, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                use_api = excluded.use_api,
                api_provider = excluded.api_provider,
                api_models = excluded.api_models,
                updated_at = excluded.updated_at
            """,
            (user_id, int(current["use_api"]), current["api_provider"],
             json.dumps(current["api_models"], sort_keys=True), now),
        )
        conn.commit()
    finally:
        conn.close()
    return current


def api_model(user_id: str, provider: str, db_path: Path | None = None) -> str:
    from models.providers import PROVIDERS
    from tools import app_settings

    name = provider.strip().lower()
    chosen = load(user_id, db_path)["api_models"].get(name)
    if chosen:
        return str(chosen)
    info = PROVIDERS.get(name)
    return info.default_model if info else app_settings.api_model(name)
