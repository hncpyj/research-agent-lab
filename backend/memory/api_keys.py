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
import uuid
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
    credential_id: str
    provider: str
    label: str
    hint: str                # e.g. "sk-ant…4f2a" -- recognisable, not usable
    created_at: str
    updated_at: str
    last_used_at: str
    enabled: bool = True
    verification_status: str = "untested"
    is_default: bool = False
    base_url: str = ""

    def as_dict(self) -> dict:
        return {"credential_id": self.credential_id, "provider": self.provider,
                "label": self.label, "hint": self.hint,
                "created_at": self.created_at, "updated_at": self.updated_at,
                "last_used_at": self.last_used_at, "enabled": self.enabled,
                "verification_status": self.verification_status,
                "is_default": self.is_default, "base_url": self.base_url}


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
    # Additive v2 storage: the legacy table stays intact so rollback remains
    # possible. Existing ciphertext is copied verbatim because its AEAD context
    # is already bound to user_id + provider. No secret is decrypted or logged
    # during migration.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_api_credentials (
            credential_id      TEXT PRIMARY KEY,
            user_id            TEXT NOT NULL,
            provider           TEXT NOT NULL,
            label              TEXT NOT NULL,
            secret             TEXT NOT NULL,
            hint               TEXT NOT NULL DEFAULT '',
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL,
            last_used_at       TEXT NOT NULL DEFAULT '',
            enabled            INTEGER NOT NULL DEFAULT 1,
            verification_status TEXT NOT NULL DEFAULT 'untested',
            is_default         INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_credentials_owner_provider "
                 "ON user_api_credentials(user_id, provider)")
    conn.execute("CREATE TABLE IF NOT EXISTS api_key_schema_migrations "
                 "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    migrated = conn.execute(
        "SELECT 1 FROM api_key_schema_migrations WHERE name = 'multiple_credentials_v1'"
    ).fetchone()
    if migrated is None:
        legacy_rows = conn.execute(
            "SELECT user_id, provider, secret, hint, created_at, updated_at, last_used_at "
            "FROM user_api_keys"
        ).fetchall()
        for row in legacy_rows:
            migrated_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL, f"researchagentlab:{row['user_id']}:{row['provider']}:legacy"))
            conn.execute(
                "INSERT OR IGNORE INTO user_api_credentials "
                "(credential_id, user_id, provider, label, secret, hint, created_at, updated_at, "
                "last_used_at, enabled, verification_status, is_default) "
                "VALUES (?, ?, ?, 'Default', ?, ?, ?, ?, ?, 1, 'untested', 1)",
                (migrated_id, row["user_id"], row["provider"], row["secret"], row["hint"],
                 row["created_at"], row["updated_at"], row["last_used_at"]),
            )
        conn.execute("INSERT INTO api_key_schema_migrations (name, applied_at) VALUES (?, ?)",
                     ("multiple_credentials_v1", _now()))
    conn.commit()
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
        return "••••" + key[-2:]
    return f"••••{key[-4:]}"


def _row_to_key(row: sqlite3.Row) -> StoredKey:
    base_url = ""
    if row["provider"] == "freellmapi":
        try:
            payload = json.loads(_decrypt(row["user_id"], row["provider"], row["secret"]))
            base_url = str(payload.get("base_url", ""))
        except Exception:
            base_url = ""
    return StoredKey(
        credential_id=row["credential_id"], provider=row["provider"], label=row["label"],
        hint=row["hint"], created_at=row["created_at"], updated_at=row["updated_at"],
        last_used_at=row["last_used_at"], enabled=bool(row["enabled"]),
        verification_status=row["verification_status"], is_default=bool(row["is_default"]),
        base_url=base_url,
    )


def _selected_row(conn: sqlite3.Connection, user_id: str, provider: str):
    return conn.execute(
        "SELECT * FROM user_api_credentials WHERE user_id = ? AND provider = ? AND enabled = 1 "
        "ORDER BY is_default DESC, created_at ASC, credential_id ASC LIMIT 1",
        (user_id, provider),
    ).fetchone()


def add_credential(user_id: str, provider: str, key: str, *, label: str = "Default",
                   base_url: str = "", db_path: Path | None = None) -> StoredKey:
    """Create one independently managed credential without exposing its secret."""
    from models import providers

    info = providers.resolve(provider)
    if info.managed_router:
        raise ApiKeyError("Automatic routing uses separately stored provider credentials.")
    clean_label = " ".join((label or "Default").split())[:80]
    if not clean_label:
        raise ApiKeyError("Give this credential a name.")
    key = (key or "").strip()
    if not key:
        raise ApiKeyError("Paste the key before saving it.")
    if len(key) < MIN_KEY_LENGTH:
        raise ApiKeyError("That does not look like an API key — it is too short.")
    if any(ch.isspace() for ch in key):
        raise ApiKeyError("An API key has no spaces in it; check what was pasted.")
    if provider == "freellmapi":
        address = normalize_gateway_url(base_url)
        plaintext = json.dumps({"base_url": address, "token": key}, separators=(",", ":"))
    else:
        plaintext = key
    now = _now()
    credential_id = str(uuid.uuid4())
    conn = _connect(db_path)
    try:
        has_default = conn.execute(
            "SELECT 1 FROM user_api_credentials WHERE user_id = ? AND provider = ? "
            "AND is_default = 1 LIMIT 1", (user_id, provider)).fetchone()
        conn.execute(
            "INSERT INTO user_api_credentials "
            "(credential_id, user_id, provider, label, secret, hint, created_at, updated_at, "
            "enabled, verification_status, is_default) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (credential_id, user_id, provider, clean_label,
             _encrypt(user_id, provider, plaintext), hint_for(key), now, now,
             "untested", 0 if has_default else 1),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM user_api_credentials WHERE credential_id = ?",
                           (credential_id,)).fetchone()
    finally:
        conn.close()
    logger.info("Stored credential %s for provider %s.", credential_id, provider)
    return _row_to_key(row)


def credential(user_id: str, credential_id: str,
               db_path: Path | None = None) -> StoredKey | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM user_api_credentials WHERE credential_id = ? AND user_id = ?",
            (credential_id, user_id)).fetchone()
        return _row_to_key(row) if row else None
    finally:
        conn.close()


def selected_credential(user_id: str, provider: str,
                        db_path: Path | None = None) -> StoredKey | None:
    conn = _connect(db_path)
    try:
        row = _selected_row(conn, user_id, provider)
        return _row_to_key(row) if row else None
    finally:
        conn.close()


def update_credential(user_id: str, credential_id: str, *, label: str | None = None,
                      enabled: bool | None = None, make_default: bool = False,
                      db_path: Path | None = None) -> StoredKey:
    """Update non-secret metadata, always scoped to the authenticated owner."""
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM user_api_credentials WHERE credential_id = ? AND user_id = ?",
            (credential_id, user_id)).fetchone()
        if row is None:
            raise ApiKeyError("Credential not found.")
        clean_label = row["label"]
        if label is not None:
            clean_label = " ".join(label.split())[:80]
            if not clean_label:
                raise ApiKeyError("Give this credential a name.")
        next_enabled = int(row["enabled"] if enabled is None else bool(enabled))
        if make_default and not next_enabled:
            raise ApiKeyError("Enable a credential before making it the default.")
        if make_default:
            conn.execute(
                "UPDATE user_api_credentials SET is_default = 0 "
                "WHERE user_id = ? AND provider = ?", (user_id, row["provider"]))
        conn.execute(
            "UPDATE user_api_credentials SET label = ?, enabled = ?, is_default = ?, "
            "updated_at = ? WHERE credential_id = ? AND user_id = ?",
            (clean_label, next_enabled, 1 if make_default else row["is_default"],
             _now(), credential_id, user_id),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM user_api_credentials WHERE credential_id = ?",
                               (credential_id,)).fetchone()
        return _row_to_key(updated)
    finally:
        conn.close()


def replace_credential(user_id: str, credential_id: str, key: str, *, base_url: str = "",
                       db_path: Path | None = None) -> StoredKey:
    """Replace a secret in place; the old secret is never returned."""
    key = (key or "").strip()
    if len(key) < MIN_KEY_LENGTH:
        raise ApiKeyError("That does not look like an API key — it is too short.")
    if any(ch.isspace() for ch in key):
        raise ApiKeyError("An API key has no spaces in it; check what was pasted.")
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM user_api_credentials WHERE credential_id = ? AND user_id = ?",
            (credential_id, user_id)).fetchone()
        if row is None:
            raise ApiKeyError("Credential not found.")
        provider = row["provider"]
        if provider == "freellmapi":
            address = normalize_gateway_url(base_url)
            plaintext = json.dumps({"base_url": address, "token": key}, separators=(",", ":"))
        else:
            plaintext = key
        conn.execute(
            "UPDATE user_api_credentials SET secret = ?, hint = ?, updated_at = ?, "
            "verification_status = 'untested' WHERE credential_id = ? AND user_id = ?",
            (_encrypt(user_id, provider, plaintext), hint_for(key), _now(),
             credential_id, user_id),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM user_api_credentials WHERE credential_id = ?",
                               (credential_id,)).fetchone()
        return _row_to_key(updated)
    finally:
        conn.close()


def remove_credential(user_id: str, credential_id: str,
                      db_path: Path | None = None) -> bool:
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT provider, is_default FROM user_api_credentials "
            "WHERE credential_id = ? AND user_id = ?", (credential_id, user_id)).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM user_api_credentials WHERE credential_id = ? AND user_id = ?",
                     (credential_id, user_id))
        if row["is_default"]:
            replacement = conn.execute(
                "SELECT credential_id FROM user_api_credentials WHERE user_id = ? "
                "AND provider = ? AND enabled = 1 ORDER BY created_at, credential_id LIMIT 1",
                (user_id, row["provider"])).fetchone()
            if replacement:
                conn.execute("UPDATE user_api_credentials SET is_default = 1 "
                             "WHERE credential_id = ?", (replacement["credential_id"],))
        conn.commit()
        return True
    finally:
        conn.close()


def set_verification_status(user_id: str, credential_id: str, status: str,
                            db_path: Path | None = None) -> None:
    if status not in {"untested", "verified", "failed"}:
        raise ApiKeyError("Unknown verification status.")
    conn = _connect(db_path)
    try:
        changed = conn.execute(
            "UPDATE user_api_credentials SET verification_status = ?, updated_at = ? "
            "WHERE credential_id = ? AND user_id = ?",
            (status, _now(), credential_id, user_id)).rowcount
        if not changed:
            raise ApiKeyError("Credential not found.")
        conn.commit()
    finally:
        conn.close()


# --- storing and using ------------------------------------------------------------

def store(user_id: str, provider: str, key: str, db_path: Path | None = None) -> StoredKey:
    """Compatibility upsert: replace the selected key, or create its first key."""
    conn = _connect(db_path)
    try:
        existing = _selected_row(conn, user_id, provider)
    finally:
        conn.close()
    if existing is None:
        if provider == "freellmapi":
            raise ApiKeyError("FreeLLMAPI needs both its gateway address and token.")
        return add_credential(user_id, provider, key, db_path=db_path)
    return replace_credential(user_id, existing["credential_id"], key, db_path=db_path)


def store_gateway(user_id: str, base_url: str, token: str,
                  db_path: Path | None = None) -> StoredKey:
    """Compatibility upsert for the selected FreeLLMAPI gateway."""
    conn = _connect(db_path)
    try:
        existing = _selected_row(conn, user_id, "freellmapi")
    finally:
        conn.close()
    if existing is None:
        return add_credential(user_id, "freellmapi", token, label="FreeLLMAPI",
                              base_url=base_url, db_path=db_path)
    return replace_credential(user_id, existing["credential_id"], token,
                              base_url=base_url, db_path=db_path)


def get_gateway(user_id: str, db_path: Path | None = None) -> GatewayCredential | None:
    """Return this user's gateway configuration, never another user's or a server default."""
    conn = _connect(db_path)
    try:
        row = _selected_row(conn, user_id, "freellmapi")
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


def gateway_for_credential(user_id: str, credential_id: str,
                           db_path: Path | None = None) -> GatewayCredential | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT secret FROM user_api_credentials WHERE credential_id = ? "
            "AND user_id = ? AND provider = 'freellmapi'",
            (credential_id, user_id)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    try:
        payload = json.loads(_decrypt(user_id, "freellmapi", row["secret"]))
        return GatewayCredential(normalize_gateway_url(payload["base_url"]), str(payload["token"]))
    except Exception as exc:
        logger.warning("Stored FreeLLMAPI credential %s could not be read (%s).",
                       credential_id, type(exc).__name__)
        return None


def remove(user_id: str, provider: str, db_path: Path | None = None) -> bool:
    """Compatibility operation: forget every credential for this provider."""
    conn = _connect(db_path)
    try:
        removed = conn.execute(
            "DELETE FROM user_api_credentials WHERE user_id = ? AND provider = ?",
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
            "SELECT * FROM user_api_credentials WHERE user_id = ? "
            "ORDER BY provider, is_default DESC, created_at, credential_id", (user_id,)).fetchall()
    finally:
        conn.close()
    return [_row_to_key(r) for r in rows]


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
        row = _selected_row(conn, user_id, provider)
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


def mark_used(user_id: str, provider: str, db_path: Path | None = None,
              credential_id: str = "") -> None:
    """So the page can say when a key was last actually used."""
    conn = _connect(db_path)
    try:
        if credential_id:
            conn.execute("UPDATE user_api_credentials SET last_used_at = ? "
                         "WHERE credential_id = ? AND user_id = ?",
                         (_now(), credential_id, user_id))
        else:
            row = _selected_row(conn, user_id, provider)
            if row:
                conn.execute("UPDATE user_api_credentials SET last_used_at = ? "
                             "WHERE credential_id = ?", (_now(), row["credential_id"]))
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

    all_keys = list_keys(user_id, db_path=db_path)
    stored: dict[str, dict] = {}
    for key in all_keys:
        if key.enabled and (key.is_default or key.provider not in stored):
            stored[key.provider] = key.as_dict()
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
    return {"providers": out, "credentials": [key.as_dict() for key in all_keys],
            "server_key_allowed": server_key_allowed}
