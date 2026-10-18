"""
Each person's own provider key, kept encrypted.

Until now a key could only come from `.env`, which works for one person on one
machine and not at all for a hosted server: everyone would share the operator's
key and the operator would pay for everyone's research. So a key belongs to a
user, and three things follow from that.

It is encrypted at rest. The database file gets copied into backups, exports
and, one day, a managed host's disks; a provider key sitting in plain text
there is a key that leaks the first time a backup does. The ciphertext is bound
to the user and provider it was stored for, so a row moved to another user
decrypts to nothing rather than to a usable key.

It is never sent back. The page shows a masked hint -- enough to recognise
which key is which, not enough to use -- and there is no endpoint that returns
the key itself. Nothing here is logged.

And the server's own `.env` key stays the server owner's. A member account with
no key of its own runs on the local model rather than quietly spending the
operator's credit.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import config

logger = logging.getLogger(__name__)

# The user id used when nobody is signed in: one person, their own machine,
# their own `.env`. Keeping it as a real row means the settings page behaves
# the same locally and hosted.
LOCAL_USER = ""

MIN_KEY_LENGTH = 16          # every provider's keys are far longer than this


class ApiKeyError(ValueError):
    """The key as given cannot be stored."""


@dataclass(frozen=True)
class StoredKey:
    provider: str
    hint: str                # e.g. "sk-ant…4f2a" -- recognisable, not usable
    created_at: str
    updated_at: str
    last_used_at: str

    def as_dict(self) -> dict:
        return {"provider": self.provider, "hint": self.hint,
                "created_at": self.created_at, "updated_at": self.updated_at,
                "last_used_at": self.last_used_at}


@dataclass(frozen=True)
class GatewayCredential:
    """Decrypted only at the moment its owning user's gateway is configured."""
    base_url: str
    token: str


def normalize_gateway_url(value: str, *, hosted: bool | None = None) -> str:
    """Validate and canonicalise a user-owned OpenAI-compatible gateway URL.

    Hosted RAL may only reach public HTTPS endpoints. Local RAL deliberately
    permits localhost/private addresses because FreeLLMAPI is local-first.
    """
    raw = (value or "").strip()
    parsed = urlparse(raw)
    is_hosted = config.HOSTED if hosted is None else bool(hosted)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ApiKeyError("The gateway address must be an http(s) URL.")
    if parsed.username or parsed.password:
        raise ApiKeyError("Do not put gateway credentials in the URL.")
    if parsed.query or parsed.fragment:
        raise ApiKeyError("The gateway address cannot contain a query or fragment.")
    path = parsed.path.rstrip("/")
    if path not in ("", "/v1"):
        raise ApiKeyError("The gateway address must be its origin, optionally followed by /v1.")
    if is_hosted:
        if parsed.scheme != "https":
            raise ApiKeyError("Hosted accounts may only use an HTTPS gateway address.")
        allowed = config.FREELLMAPI_ALLOWED_HOSTS
        if not allowed:
            raise ApiKeyError(
                "Hosted FreeLLMAPI is disabled until the operator sets "
                "FREELLMAPI_ALLOWED_HOSTS.")
        from tools.url_safety import UnsafeURL, check_url
        try:
            check_url(urlunparse((parsed.scheme, parsed.netloc, "/v1", "", "", "")),
                      allow_hosts=allowed)
        except UnsafeURL as exc:
            raise ApiKeyError(f"Unsafe gateway address: {exc}") from exc
    return urlunparse((parsed.scheme, parsed.netloc, "/v1", "", "", ""))


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or config.SQLITE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_api_keys (
            user_id      TEXT NOT NULL,
            provider     TEXT NOT NULL,
            secret       TEXT NOT NULL,      -- encrypted, never the key itself
            hint         TEXT NOT NULL DEFAULT '',
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL,
            last_used_at TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (user_id, provider)
        )
        """
    )
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- the encryption ---------------------------------------------------------------

def _master_key() -> bytes:
    """
    The key that encrypts the stored keys.

    Read from the environment first: a hosted server's disk may be replaced
    between deployments, and a key file that disappears takes every stored
    provider key with it. Falling back to a file in the data folder keeps the
    local case working with nothing to configure.
    """
    from_env = os.environ.get("API_KEY_ENCRYPTION_KEY", "").strip()
    if from_env:
        try:
            raw = base64.urlsafe_b64decode(from_env + "=" * (-len(from_env) % 4))
        except Exception as exc:
            raise ApiKeyError(
                "API_KEY_ENCRYPTION_KEY is not valid base64; generate one with "
                "python -c \"import base64,secrets;print(base64.urlsafe_b64encode("
                "secrets.token_bytes(32)).decode())\"") from exc
        if len(raw) != 32:
            raise ApiKeyError("API_KEY_ENCRYPTION_KEY must decode to 32 bytes.")
        return raw

    path = Path(config.DATA_DIR) / "api_key_secret"
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    path.write_bytes(key)
    try:
        path.chmod(0o600)
    except OSError:                                # Windows: no POSIX modes
        pass
    return key


def _aead():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:                     # pragma: no cover - install problem
        raise ApiKeyError(
            "Storing an API key needs the 'cryptography' package: "
            "python -m pip install cryptography") from exc
    return AESGCM(_master_key())


def _context(user_id: str, provider: str) -> bytes:
    """Who and what this ciphertext was made for; changing either breaks it."""
    return f"{user_id}|{provider}".encode()


def _encrypt(user_id: str, provider: str, key: str) -> str:
    nonce = secrets.token_bytes(12)
    sealed = _aead().encrypt(nonce, key.encode(), _context(user_id, provider))
    return base64.urlsafe_b64encode(nonce + sealed).decode()


def _decrypt(user_id: str, provider: str, stored: str) -> str:
    raw = base64.urlsafe_b64decode(stored.encode())
    plain = _aead().decrypt(raw[:12], raw[12:], _context(user_id, provider))
    return plain.decode()


def hint_for(key: str) -> str:
    """What the page shows: the shape of the key, and its last four characters."""
    key = key.strip()
    if len(key) <= 8:
        return "…" + key[-2:]
    return f"{key[:6]}…{key[-4:]}"


# --- storing and using ------------------------------------------------------------

def store(user_id: str, provider: str, key: str, db_path: Path | None = None) -> StoredKey:
    """Keep this person's key for this provider, replacing any earlier one."""
    from models import providers

    info = providers.resolve(provider)             # an unknown provider is a mistake
    if info.managed_router:
        raise ApiKeyError("Automatic routing uses your separately stored provider keys.")
    if provider == "freellmapi":
        raise ApiKeyError("FreeLLMAPI needs both its gateway address and token.")
    key = (key or "").strip()
    if not key:
        raise ApiKeyError("Paste the key before saving it.")
    if len(key) < MIN_KEY_LENGTH:
        raise ApiKeyError("That does not look like an API key — it is too short.")
    if any(ch.isspace() for ch in key):
        raise ApiKeyError("An API key has no spaces in it; check what was pasted.")

    now = _now()
    conn = _connect(db_path)
    try:
        existing = conn.execute(
            "SELECT created_at FROM user_api_keys WHERE user_id = ? AND provider = ?",
            (user_id, provider)).fetchone()
        created = existing["created_at"] if existing else now
        conn.execute(
            "INSERT INTO user_api_keys (user_id, provider, secret, hint, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, provider) DO UPDATE SET secret = excluded.secret, "
            "hint = excluded.hint, updated_at = excluded.updated_at",
            (user_id, provider, _encrypt(user_id, provider, key), hint_for(key), created, now))
        conn.commit()
    finally:
        conn.close()
    logger.info("Stored an API key for provider %s.", provider)   # never the key
    return StoredKey(provider, hint_for(key), created, now, "")


def store_gateway(user_id: str, base_url: str, token: str,
                  db_path: Path | None = None) -> StoredKey:
    """Store one user's FreeLLMAPI endpoint and bearer token as one AEAD record."""
    token = (token or "").strip()
    if len(token) < MIN_KEY_LENGTH:
        raise ApiKeyError("That does not look like a gateway token — it is too short.")
    if any(ch.isspace() for ch in token):
        raise ApiKeyError("A gateway token has no spaces in it; check what was pasted.")
    address = normalize_gateway_url(base_url)
    provider = "freellmapi"
    payload = json.dumps({"base_url": address, "token": token}, separators=(",", ":"))
    now = _now()
    conn = _connect(db_path)
    try:
        existing = conn.execute(
            "SELECT created_at FROM user_api_keys WHERE user_id = ? AND provider = ?",
            (user_id, provider)).fetchone()
        created = existing["created_at"] if existing else now
        conn.execute(
            "INSERT INTO user_api_keys (user_id, provider, secret, hint, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, provider) DO UPDATE SET secret = excluded.secret, "
            "hint = excluded.hint, updated_at = excluded.updated_at",
            (user_id, provider, _encrypt(user_id, provider, payload),
             hint_for(token), created, now))
        conn.commit()
    finally:
        conn.close()
    logger.info("Stored a per-user FreeLLMAPI gateway credential.")
    return StoredKey(provider, hint_for(token), created, now, "")


def get_gateway(user_id: str, db_path: Path | None = None) -> GatewayCredential | None:
    """Return this user's gateway configuration, never another user's or a server default."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT secret FROM user_api_keys WHERE user_id = ? AND provider = 'freellmapi'",
            (user_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    try:
        payload = json.loads(_decrypt(user_id, "freellmapi", row["secret"]))
        return GatewayCredential(
            base_url=normalize_gateway_url(payload["base_url"]),
            token=str(payload["token"]),
        )
    except Exception as exc:
        logger.warning("The stored FreeLLMAPI gateway could not be read (%s); treating it as absent.",
                       type(exc).__name__)
        return None


def remove(user_id: str, provider: str, db_path: Path | None = None) -> bool:
    """Forget this person's key. Returns whether there was one."""
    conn = _connect(db_path)
    try:
        removed = conn.execute(
            "DELETE FROM user_api_keys WHERE user_id = ? AND provider = ?",
            (user_id, provider)).rowcount
        conn.commit()
    finally:
        conn.close()
    return bool(removed)


def list_keys(user_id: str, db_path: Path | None = None) -> list[StoredKey]:
    """What this person has stored, as the page may show it."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT provider, hint, created_at, updated_at, last_used_at "
            "FROM user_api_keys WHERE user_id = ? ORDER BY provider", (user_id,)).fetchall()
    finally:
        conn.close()
    return [StoredKey(r["provider"], r["hint"], r["created_at"],
                      r["updated_at"], r["last_used_at"]) for r in rows]


def get(user_id: str, provider: str, db_path: Path | None = None) -> str:
    """
    The key itself, for making a call. Returns "" when there is none.

    A row that will not decrypt is a damaged or moved row, not a reason to
    stop the run: it is reported and treated as absent.
    """
    if provider == "freellmapi":
        gateway = get_gateway(user_id, db_path=db_path)
        return gateway.token if gateway else ""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT secret FROM user_api_keys WHERE user_id = ? AND provider = ?",
            (user_id, provider)).fetchone()
    finally:
        conn.close()
    if row is None:
        return ""
    try:
        return _decrypt(user_id, provider, row["secret"])
    except Exception as exc:
        logger.warning("The stored %s key could not be read (%s); treating it as absent. "
                       "Save the key again.", provider, type(exc).__name__)
        return ""


def mark_used(user_id: str, provider: str, db_path: Path | None = None) -> None:
    """So the page can say when a key was last actually used."""
    conn = _connect(db_path)
    try:
        conn.execute("UPDATE user_api_keys SET last_used_at = ? WHERE user_id = ? AND provider = ?",
                     (_now(), user_id, provider))
        conn.commit()
    finally:
        conn.close()


def may_use_server_key(user_id: str, db_path: Path | None = None) -> bool:
    """
    Whether this person may fall back to the key in the server's `.env`.

    Nobody signed in means this is somebody's own machine, so the `.env` key is
    theirs. With accounts, the server and its key belong to the owner — the
    first account made. A member without a key of their own runs locally rather
    than spending the owner's credit without being told.
    """
    if not user_id:
        return True
    from memory.accounts import get_user

    user = get_user(user_id, db_path=db_path)
    return bool(user and user.role == "owner")


def key_for(user_id: str, provider: str, db_path: Path | None = None) -> str:
    """
    The key a run started by this person should use, or "" for none.

    Asking for it counts as using it: this is called where a run is about to
    make calls, and "last used" is more useful to read than "last saved".
    """
    own = get(user_id, provider, db_path=db_path)
    if own:
        mark_used(user_id, provider, db_path=db_path)
        return own
    if not may_use_server_key(user_id, db_path=db_path):
        return ""
    from models import providers

    try:
        return providers.resolve(provider).key()
    except providers.ProviderUnavailable:
        return ""


def describe(user_id: str, db_path: Path | None = None) -> dict:
    """
    Everything the settings page needs: which providers have a stored key, and
    whether the server's own key would be used if none is stored.
    """
    from models import providers

    stored = {k.provider: k.as_dict() for k in list_keys(user_id, db_path=db_path)}
    server_key_allowed = may_use_server_key(user_id, db_path=db_path)
    out = []
    for info in providers.PROVIDERS.values():
        if not info.needs_key:
            continue
        env_key = info.key()
        entry = {
            "provider": info.name,
            "label": info.label,
            "docs": info.docs,
            "user_configurable_url": info.user_configurable_url,
            "stored": stored.get(info.name),
            "server_key_available": bool(env_key) and server_key_allowed,
            "usable": bool(stored.get(info.name)) or (bool(env_key) and server_key_allowed),
        }
        if info.name == "freellmapi" and stored.get(info.name):
            gateway = get_gateway(user_id, db_path=db_path)
            entry["base_url"] = gateway.base_url if gateway else ""
            entry["server_key_available"] = False
            entry["usable"] = gateway is not None
        out.append(entry)
    return {"providers": out, "server_key_allowed": server_key_allowed}
