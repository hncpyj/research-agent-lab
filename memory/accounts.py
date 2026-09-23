"""
People, and which research belongs to whom.

Until now access was one shared token: whoever had it saw, edited and deleted
every session in the database. That is workable for one person on one machine
and impossible for anything hosted — and it is also the thing every other
hosted feature depends on. A plan, a quota, a bill or an API key means nothing
until "whose?" has an answer.

Two modes, on purpose:
- No accounts: the server behaves exactly as it did — one person, one machine,
  no sign-in. This is how it is used locally every day and that must not break.
- Accounts: the first account claims the sessions that already exist (they are
  the owner's own work), and from then on every session has an owner and is
  only visible to them.

Passwords are hashed with scrypt from the standard library; sessions are a
signed cookie, so there is no session table to keep and no extra dependency.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import config

logger = logging.getLogger(__name__)

SESSION_COOKIE = "ra_user"
SESSION_DAYS = 30
MIN_PASSWORD = 10           # long enough to matter, short enough to type
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountError(ValueError):
    """Something about the account request is wrong, in a way worth showing."""


@dataclass(frozen=True)
class User:
    user_id: str
    email: str
    role: str            # owner (the first account) | member
    plan: str            # free | researcher
    created_at: str

    def as_dict(self) -> dict:
        return {"user_id": self.user_id, "email": self.email, "role": self.role,
                "plan": self.plan, "created_at": self.created_at}


# --- storage -------------------------------------------------------------------

def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or config.SQLITE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id       TEXT PRIMARY KEY,
            email         TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'member',
            plan          TEXT NOT NULL DEFAULT 'free',
            created_at    TEXT NOT NULL,
            last_login_at TEXT
        )
        """
    )
    return conn


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _password_matches(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), dklen=32, **_SCRYPT)
    return hmac.compare_digest(candidate.hex(), digest_hex)


def _row_to_user(row: sqlite3.Row) -> User:
    return User(user_id=row["user_id"], email=row["email"], role=row["role"],
                plan=row["plan"], created_at=row["created_at"])


def accounts_exist(db_path: Path | None = None) -> bool:
    """Whether this server has accounts at all. False means the local single-user mode."""
    conn = _connect(db_path)
    try:
        return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None
    finally:
        conn.close()


def count_users(db_path: Path | None = None) -> int:
    conn = _connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


def create_user(email: str, password: str, db_path: Path | None = None) -> User:
    """
    Make an account. The first one is the owner and adopts the sessions that
    already exist on this machine — they were made before anyone signed in, by
    the person setting this up.
    """
    email = (email or "").strip().lower()
    if not _EMAIL.match(email):
        raise AccountError("That does not look like an email address.")
    if len(password or "") < MIN_PASSWORD:
        raise AccountError(f"Use a password of at least {MIN_PASSWORD} characters.")

    conn = _connect(db_path)
    try:
        first = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        user_id = str(uuid.uuid4())
        try:
            conn.execute(
                "INSERT INTO users (user_id, email, password_hash, role, plan, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, email, _hash_password(password), "owner" if first else "member",
                 "free", _now()),
            )
        except sqlite3.IntegrityError as exc:
            raise AccountError("There is already an account with that email.") from exc
        if first:
            try:
                adopted = conn.execute(
                    "UPDATE research_sessions SET owner_id = ? WHERE owner_id IS NULL OR owner_id = ''",
                    (user_id,)).rowcount
                if adopted:
                    logger.info("First account adopted %d existing sessions", adopted)
            except sqlite3.OperationalError:
                # A database with no research table yet has no earlier work to adopt.
                logger.debug("No research_sessions table yet; nothing to adopt.")
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return _row_to_user(row)
    finally:
        conn.close()


def verify_password(email: str, password: str, db_path: Path | None = None) -> User | None:
    """The user, if this password is theirs. Records when they signed in."""
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM users WHERE email = ?",
                           ((email or "").strip().lower(),)).fetchone()
        if row is None or not _password_matches(password or "", row["password_hash"]):
            return None
        conn.execute("UPDATE users SET last_login_at = ? WHERE user_id = ?", (_now(), row["user_id"]))
        conn.commit()
        return _row_to_user(row)
    finally:
        conn.close()


def get_user(user_id: str, db_path: Path | None = None) -> User | None:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return _row_to_user(row) if row else None
    finally:
        conn.close()


def list_users(db_path: Path | None = None) -> list[User]:
    conn = _connect(db_path)
    try:
        return [_row_to_user(r) for r in
                conn.execute("SELECT * FROM users ORDER BY created_at")]
    finally:
        conn.close()


def set_plan(user_id: str, plan: str, db_path: Path | None = None) -> None:
    conn = _connect(db_path)
    try:
        conn.execute("UPDATE users SET plan = ? WHERE user_id = ?", (plan, user_id))
        conn.commit()
    finally:
        conn.close()


# --- the signed cookie ------------------------------------------------------------

def _secret() -> bytes:
    """
    The key that signs sign-in cookies. Kept in the data folder rather than in
    code, made once, so restarting the server does not sign everyone out and
    two machines do not share a predictable key.
    """
    path = Path(config.DATA_DIR) / "session_secret"
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_bytes(32)
    path.write_bytes(secret)
    try:
        path.chmod(0o600)
    except OSError:                                   # Windows: no POSIX modes
        pass
    return secret


def issue_cookie(user: User, days: int = SESSION_DAYS) -> str:
    """A signed 'this is who you are, until then' string."""
    expires = int(time.time()) + days * 86400
    payload = f"{user.user_id}.{expires}"
    signature = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def user_from_cookie(value: str | None, db_path: Path | None = None) -> User | None:
    """Who this cookie belongs to, or None if it is missing, altered or expired."""
    if not value:
        return None
    try:
        user_id, expires, signature = value.rsplit(".", 2)
    except ValueError:
        return None
    expected = hmac.new(_secret(), f"{user_id}.{expires}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        if int(expires) < time.time():
            return None
    except ValueError:
        return None
    return get_user(user_id, db_path)
