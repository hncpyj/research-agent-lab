"""
FastAPI web application for the AI Research Agent.

Endpoints:
  GET  /                              → serve SPA
  GET  /api/sessions                  → list all sessions
  GET  /api/sessions/{id}             → session detail (papers, hypotheses)
  GET  /api/sessions/{id}/status      → is runner active?
  GET  /api/sessions/{id}/code        → generated experiment code
  POST /api/sessions                  → create + start new session
  POST /api/sessions/{id}/resume      → resume existing session
  POST /api/sessions/{id}/select-question → submit question choice
  WS   /ws/{id}                       → real-time event stream
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import secrets
import sys
import threading
from pathlib import Path
from typing import Any, Optional, Union

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from memory.note_db import NoteDB
from ui.runner import SessionRunner

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(title="AI Research Agent", version="1.0.0")

# Behind a domain, answer only to that domain: a request that arrives with
# somebody else's Host header is either a misconfigured proxy or someone
# probing, and neither deserves an answer. Empty (a laptop) means any host.
if config.ALLOWED_HOSTS:
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.ALLOWED_HOSTS)

# Static files
_static_dir = Path(__file__).parent / "static"
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# In-memory registry of active runners
_runners: dict[str, SessionRunner] = {}
# How often to look for runs left behind by a server that stopped.
_RECOVERY_SWEEP_S = 60

# ─── Local model singleton ─────────────────────────────────────────────────────
# Loaded lazily on first report generation when API key is unavailable.
# Protected by a lock so concurrent requests don't double-load.

_local_model_singleton = None
_local_model_lock = threading.Lock()


def _try_get_local_model():
    """
    Return a loaded LocalModel instance, or None if unavailable.
    Results are cached in _local_model_singleton so the model is
    loaded at most once per server process (first call may be slow).
    """
    global _local_model_singleton

    # Fast path — already loaded
    if _local_model_singleton is not None and _local_model_singleton.is_loaded:
        return _local_model_singleton

    lm_path = Path(config.LOCAL_MODEL_PATH)
    if not lm_path.exists():
        logger.info("Local model file not found at %s — skipping.", lm_path)
        return None

    with _local_model_lock:
        # Re-check under lock (another thread may have loaded in the meantime)
        if _local_model_singleton is not None and _local_model_singleton.is_loaded:
            return _local_model_singleton
        try:
            from models.local_model import LocalModel
            lm = LocalModel()
            logger.info("Loading local model from %s (this may take ~30s)…", lm_path)
            lm.load()
            _local_model_singleton = lm
            logger.info("Local model ready — will be used as API fallback.")
            return lm
        except Exception as exc:
            logger.warning("Could not load local model: %s", exc)
            return None


# ─── Request models ───────────────────────────────────────────────────────────

# ─── Global settings (in-memory; startup default comes from config.USE_API) ────
def _initial_use_api() -> bool:
    """The API toggle survives a restart: the settings page wins over .env."""
    from tools import app_settings
    return app_settings.use_api()


_settings: dict[str, bool] = {
    "use_api": _initial_use_api(),   # default for new sessions; each session persists its own value
}


class SettingsRequest(BaseModel):
    session_id: str = ""
    use_api: Optional[bool] = None
    daily_budget_usd: Optional[float] = None
    api_provider: Optional[str] = None
    api_model: Optional[str] = None
    local_server_url: Optional[str] = None


class LoginRequest(BaseModel):
    token: str


class AccountRequest(BaseModel):
    email: str
    password: str


class EmailRequest(BaseModel):
    email: str


class AccountTokenRequest(BaseModel):
    token: str


class PasswordResetRequest(BaseModel):
    token: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class NewTokenRequest(BaseModel):
    name: str = ""


class NewSessionRequest(BaseModel):
    topic: str
    background: Optional[str] = None   # what the user already knows / context
    goals: Optional[str] = None        # what they want to achieve
    constraints: Optional[str] = None  # e.g. "CPU only", "max 1 day training"
    autostart: bool = True             # False: create it, then run stages yourself
    project_id: str = ""               # file it under a project straight away


class UpdateDetailsRequest(BaseModel):
    topic: Optional[str] = None
    background: Optional[str] = None
    goals: Optional[str] = None
    constraints: Optional[str] = None


class SelectQuestionRequest(BaseModel):
    choice: Union[int, str]
    override: bool = False   # use a question that failed the data check anyway


class SelectHypothesesRequest(BaseModel):
    ids: list[str]


class PlanRequest(BaseModel):
    text: str
    approve: bool = False


class SourceDecisionRequest(BaseModel):
    proceed: bool


class ApiKeyRequest(BaseModel):
    key: str


class ProjectRequest(BaseModel):
    name: str = ""
    description: str | None = None
    archived: bool | None = None


class AssignProjectRequest(BaseModel):
    project_id: str = ""            # empty files the session under no project


# ─── Routes ───────────────────────────────────────────────────────────────────

def _session_inference_settings(session: dict | None) -> tuple[bool, str]:
    """Return the durable inference toggle/provider for one session."""
    from tools import app_settings

    if not session:
        return bool(_settings["use_api"]), app_settings.api_provider()
    raw_enabled = session.get("model_api_enabled")
    enabled = bool(_settings["use_api"]) if raw_enabled is None else bool(raw_enabled)
    provider = (session.get("model_provider") or app_settings.api_provider()).strip().lower()
    return enabled, provider


def _effective_inference_route(request: Request, enabled: bool, provider: str) -> dict:
    """Describe the actual route without returning or logging any credential."""
    from tools import app_settings

    if not enabled:
        return {"inference_mode": "off", "effective_provider": "", "effective_model": ""}
    if config.HOSTED:
        from memory import api_keys
        user = _current_user(request)
        if user is not None and api_keys.get(user.user_id, provider):
            return {
                "inference_mode": "byok",
                "effective_provider": provider,
                "effective_model": app_settings.api_model(provider),
            }
        return {
            "inference_mode": "shared_free",
            "effective_provider": config.SHARED_FREE_PROVIDER,
            "effective_model": config.SHARED_FREE_MODEL,
        }
    return {
        "inference_mode": "configured",
        "effective_provider": provider,
        "effective_model": app_settings.api_model(provider),
    }


@app.get("/api/settings")
async def get_settings(request: Request, session_id: str = ""):
    """Which backend a run uses, and what the API has cost today against the cap."""
    from models import providers
    from tools import app_settings
    from tools.cost_tracker import CostTracker

    spent = 0.0
    try:
        spent = CostTracker().spend_today()
    except Exception as exc:
        logger.warning("Could not read today's API spend: %s", exc)
    session = None
    if session_id:
        _authorise_session(session_id, request)
        session = NoteDB().get_session(session_id)
    enabled, provider = _session_inference_settings(session)
    route = _effective_inference_route(request, enabled, provider)
    return {"use_api": enabled, **route, "spend_today_usd": round(spent, 4),
            "daily_budget_usd": app_settings.daily_budget_usd(),
            "budget_from_env": app_settings.load()["daily_budget_usd"] is None,
            "api_provider": provider,
            "api_model": app_settings.api_model(provider),
            "local_server_url": app_settings.local_server_url(),
            "providers": providers.describe()}


@app.post("/api/settings")
async def update_settings(req: SettingsRequest, request: Request):
    """Change what can be changed while running; everything else needs .env."""
    from models import providers
    from tools import app_settings

    session_id = req.session_id.strip()
    session_updates: dict = {}
    if session_id:
        _authorise_session(session_id, request)
    stored: dict = {}
    if req.use_api is not None:
        if session_id:
            session_updates["model_api_enabled"] = bool(req.use_api)
        else:
            _settings["use_api"] = req.use_api
            stored["use_api"] = req.use_api
    if req.daily_budget_usd is not None:
        if req.daily_budget_usd < 0:
            raise HTTPException(status_code=400, detail="A daily cap cannot be negative.")
        stored["daily_budget_usd"] = float(req.daily_budget_usd)
    if req.api_provider is not None:
        try:
            providers.resolve(req.api_provider)
        except providers.ProviderUnavailable as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if session_id:
            session_updates["model_provider"] = req.api_provider.strip().lower()
        else:
            stored["api_provider"] = req.api_provider.strip().lower()
    if session_updates:
        NoteDB().update_session(session_id, **session_updates)
        runner = _runners.get(session_id)
        if runner and runner.is_alive():
            updated_session = NoteDB().get_session(session_id)
            enabled, provider = _session_inference_settings(updated_session)
            runner.configure_model_api(enabled, provider)
    if stored:
        app_settings.save(stored)
    if req.local_server_url is not None:
        address = req.local_server_url.strip().rstrip("/")
        if address and not address.startswith(("http://", "https://")):
            raise HTTPException(status_code=400,
                                detail="The server address must start with http:// or https://")
        app_settings.save({"local_server_url": address or None})
    if req.api_model is not None:
        # Kept per provider, so switching back and forth does not lose a choice.
        app_settings.set_api_model(req.api_provider or app_settings.api_provider(), req.api_model)
    return await get_settings(request, session_id=session_id)


@app.get("/api/local-server/models")
async def local_server_models(url: str = ""):
    """
    Ask an OpenAI-compatible server what it serves, so the model can be picked
    from a list. This deliberately allows a localhost address, unlike a URL
    found in a session brief (tools/url_safety.py refuses those): this one was
    typed on the settings page by whoever is signed in, and pointing at a
    server on this machine is the whole purpose.
    """
    import json as _json
    import urllib.error
    import urllib.request
    from urllib.parse import urlparse

    from tools import app_settings

    base = (url or app_settings.local_server_url()).strip().rstrip("/")
    if not base:
        raise HTTPException(status_code=400, detail="No server address given.")
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=400, detail="The address must start with http:// or https://")
    try:
        with urllib.request.urlopen(f"{base}/models", timeout=8) as resp:
            payload = _json.loads(resp.read())
    except Exception as exc:
        return {"base_url": base, "reachable": False, "models": [],
                "problem": f"{type(exc).__name__}: {exc}"}
    from models.providers import is_local_address
    models = [m.get("id", "") for m in payload.get("data", []) if m.get("id")]
    return {"base_url": base, "reachable": True, "models": sorted(models), "problem": "",
            "billed": not is_local_address(base)}


@app.get("/api/local-models")
async def local_models():
    """
    What Ollama has installed on this machine, so the local model can be
    picked from a list instead of guessed at and typed into .env.
    """
    import json as _json
    import urllib.request

    from tools import app_settings

    installed, reachable, problem = [], False, ""
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_HOST}/api/tags", timeout=5) as resp:
            models = _json.loads(resp.read()).get("models", [])
        reachable = True
        installed = sorted(
            ({"name": m.get("name", ""), "bytes": m.get("size", 0),
              "family": (m.get("details") or {}).get("family", ""),
              "parameters": (m.get("details") or {}).get("parameter_size", "")}
             for m in models if m.get("name")),
            key=lambda m: m["name"])
    except Exception as exc:
        problem = f"{type(exc).__name__}: {exc}"

    return {"host": config.OLLAMA_HOST, "reachable": reachable, "problem": problem,
            "installed": installed,
            "chosen": {"model": app_settings.local_model(),
                       "embed_model": app_settings.local_embed_model(),
                       "num_ctx": app_settings.local_num_ctx(),
                       "max_num_ctx": config.OLLAMA_MAX_NUM_CTX},
            "from_env": {"model": config.OLLAMA_MODEL, "embed_model": config.OLLAMA_EMBED_MODEL,
                         "num_ctx": config.OLLAMA_NUM_CTX}}


class LocalModelRequest(BaseModel):
    model: Optional[str] = None
    embed_model: Optional[str] = None
    num_ctx: Optional[int] = None


@app.post("/api/local-models")
async def choose_local_model(req: LocalModelRequest):
    """
    Pick the local model. It takes effect for runs started after this; a
    session already running keeps the model it loaded.
    """
    from tools import app_settings

    stored: dict = {}
    if req.model is not None:
        stored["local_model"] = req.model.strip() or None
    if req.embed_model is not None:
        stored["local_embed_model"] = req.embed_model.strip() or None
    if req.num_ctx is not None:
        if not (512 <= req.num_ctx <= 1_000_000):
            raise HTTPException(status_code=400, detail="A context window must be at least 512 tokens.")
        stored["local_num_ctx"] = int(req.num_ctx)
    if stored:
        app_settings.save(stored)
    running = [sid for sid, runner in _runners.items() if runner.is_alive()]
    return {**await local_models(), "running_sessions_keep_old_model": running}


@app.get("/api/usage")
async def usage(request: Request):
    """
    Three separate things the pricing page must not blur together: the hosted
    run allowance, what the user's own API key has cost, and managed credit
    (not offered yet — reported as absent rather than as zero).
    """
    from memory import plans, quota
    from tools import app_settings
    from tools.cost_tracker import CostTracker

    user = _require_user(request)
    left = quota.allowance(user)
    plan = plans.plan_for(user)
    spend_today = 0.0
    try:
        spend_today = CostTracker().spend_today()
    except Exception as exc:
        logger.warning("Could not read today's spend: %s", exc)
    return {
        "plan": plan.as_dict(),
        "hosted_runs": left.as_dict(),
        "own_api_key": {"spend_today_usd": round(spend_today, 4),
                        "daily_cap_usd": app_settings.daily_budget_usd(),
                        "provider": app_settings.api_provider(),
                        "billed_by": "your own provider account"},
        "managed_credit": {"available_gbp": 0.0, "offered": False,
                           "note": "ResearchAgentLab Credits are not available yet; "
                                   "runs use your own API key."},
        "recent_runs": quota.history(user, limit=20),
    }


def _authorise_project(project_id: str, request: Request):
    """A project belongs to whoever made it, like the sessions inside it."""
    from memory import projects

    project = projects.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    user = _require_user(request)
    if user is None:
        return project                              # local mode: one person
    if project["owner_id"] and project["owner_id"] != user.user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.get("/api/projects")
async def list_projects(request: Request, include_archived: bool = False):
    """Every project, each with what it amounts to so far."""
    from memory import projects

    owner = _owner_scope(request)
    return {"projects": [projects.summary(p["project_id"])
                         for p in projects.list_projects(owner, include_archived=include_archived)],
            "unfiled": len([s for s in NoteDB().list_sessions(owner_id=owner)
                            if not s.get("project_id")])}


@app.post("/api/projects")
async def create_project(req: ProjectRequest, request: Request):
    from memory import projects

    user = _require_user(request)
    try:
        project = projects.create(req.name, owner_id=user.user_id if user else "",
                                  description=req.description or "", user=user)
    except projects.ProjectLimit as exc:
        raise HTTPException(status_code=409, detail=str(exc),
                            headers={"X-Limit": "active_projects"}) from exc
    except projects.ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return projects.summary(project["project_id"])


@app.patch("/api/projects/{project_id}")
async def update_project(project_id: str, req: ProjectRequest, request: Request):
    from memory import projects

    _authorise_project(project_id, request)
    user = _require_user(request)
    try:
        if req.name or req.description is not None:
            projects.rename(project_id, req.name, req.description)
        if req.archived is not None:
            projects.archive(project_id, req.archived, user=user)
    except projects.ProjectLimit as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except projects.ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return projects.summary(project_id)


@app.get("/api/projects/{project_id}/papers")
async def project_papers(project_id: str, request: Request):
    """
    The project's reading list: each paper once, however many sessions read it,
    with the sessions that did.
    """
    from memory import paper_index, projects

    _authorise_project(project_id, request)
    ids = [s["session_id"] for s in projects.sessions_of(project_id)]
    return {"papers": paper_index.library(ids), "sessions": len(ids)}


@app.get("/api/projects/{project_id}/graph")
async def project_provenance(project_id: str, request: Request):
    """The project as a body of work: its sessions, and the reading they share."""
    from memory import projects, provenance

    _authorise_project(project_id, request)
    sessions = projects.sessions_of(project_id)
    return {"project": projects.summary(project_id),
            **provenance.project_graph(NoteDB(), sessions)}


@app.get("/api/sessions/{session_id}/provenance")
async def session_provenance(session_id: str):
    """What this session's result is built on, step by step."""
    from memory import provenance

    db = NoteDB()
    try:
        return provenance.graph(db, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/project")
async def file_session(session_id: str, req: AssignProjectRequest, request: Request):
    """Move a session into a project, or out of one."""
    from memory import projects

    if req.project_id:
        _authorise_project(req.project_id, request)
    try:
        projects.assign(session_id, req.project_id)
    except projects.ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"session_id": session_id, "project_id": req.project_id}


@app.get("/api/keys")
async def list_api_keys(request: Request):
    """
    Which providers this person has a key for. The keys themselves are never
    sent back -- only a hint like "sk-ant...4f2a", which is enough to tell two
    keys apart and useless to anyone who reads it.
    """
    from memory import api_keys

    user = _require_user(request)
    return api_keys.describe(user.user_id if user else api_keys.LOCAL_USER)


@app.put("/api/keys/{provider}")
async def save_api_key(provider: str, req: ApiKeyRequest, request: Request):
    """Store (or replace) this person's key for one provider."""
    from memory import api_keys

    user = _require_user(request)
    try:
        api_keys.store(user.user_id if user else api_keys.LOCAL_USER, provider, req.key)
    except api_keys.ApiKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:                        # an unknown provider name
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await list_api_keys(request)


@app.delete("/api/keys/{provider}")
async def delete_api_key(provider: str, request: Request):
    """Forget this person's key for one provider."""
    from memory import api_keys

    user = _require_user(request)
    api_keys.remove(user.user_id if user else api_keys.LOCAL_USER, provider)
    return await list_api_keys(request)


@app.get("/api/environment")
async def environment():
    """
    What this server is running with. Read-only: these come from .env, and a
    web request must not be able to rewrite the file that holds the API key.
    The Anthropic key itself is never sent — only whether one is set.
    """
    import sys as _sys

    return {
        "python": _sys.version.split()[0],
        "runner_python": config.RUNNER_PYTHON,
        "runner_allow_pip": config.RUNNER_ALLOW_PIP,
        "runner_max_fix_attempts": config.RUNNER_MAX_FIX_ATTEMPTS,
        "anthropic_key_set": bool(config.ANTHROPIC_API_KEY),
        "openai_key_set": bool(config.OPENAI_API_KEY),
        "gemini_key_set": bool(config.GEMINI_API_KEY),
        "api_provider": config.API_PROVIDER,
        "api_model": config.API_MODEL_DEFAULT,
        "ollama_host": config.OLLAMA_HOST,
        "ollama_model": config.OLLAMA_MODEL,
        "ollama_num_ctx": config.OLLAMA_NUM_CTX,
        "paper_sources": config.PAPER_SOURCES,
        "request_interval_s": [config.REQUEST_INTERVAL_MIN_S, config.REQUEST_INTERVAL_MAX_S],
        "dataset_max_mb": config.DATASET_MAX_MB,
        "dataset_allowed_hosts": config.DATASET_ALLOWED_HOSTS,
        "paths": {"database": str(config.SQLITE_PATH), "experiments": str(config.EXPERIMENTS_DIR),
                  "datasets": str(config.DATASETS_DIR), "data": str(config.DATA_DIR)},
    }


@app.get("/", include_in_schema=False)
@app.get("/login", include_in_schema=False)
@app.get("/signup", include_in_schema=False)
@app.get("/verify-email", include_in_schema=False)
@app.get("/forgot-password", include_in_schema=False)
@app.get("/reset-password", include_in_schema=False)
@app.get("/app", include_in_schema=False)
@app.get("/app/{path:path}", include_in_schema=False)
async def serve_spa():
    return FileResponse(_static_dir / "index.html")


# ─── Access ───────────────────────────────────────────────────────────────────
# There are no accounts here: whoever reaches this port can start runs that
# execute code on this machine, read every session and remove them. When any
# token exists the server asks for one; with none it is open, and run_ui.py
# then refuses to bind anything but localhost.

_TOKEN_COOKIE = "ra_token"
ACCOUNT_COOKIE = "ra_user"
# Failed sign-ins per address, so a token cannot be guessed at speed.
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_WINDOW_S = 300
_LOGIN_MAX_TRIES = 10
_SIGNUP_ATTEMPTS: dict[str, list[float]] = {}
_SIGNUP_WINDOW_S = 3600
_SIGNUP_MAX_TRIES = 5
_EMAIL_ATTEMPTS: dict[str, list[float]] = {}
_EMAIL_WINDOW_S = 3600
_EMAIL_MAX_TRIES = 5


def _client_address(request: Request) -> str:
    """The caller's address, honouring one proxy hop when the server is behind one."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _over_https(request: Request) -> bool:
    """Whether the browser reached this over HTTPS, including through a proxy."""
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return (proto or request.url.scheme) == "https"


def _set_account_cookie(response: Response, user, request: Request) -> None:
    """The signed 'who you are' cookie, secure once there is HTTPS in front."""
    from memory.accounts import SESSION_DAYS, issue_cookie

    response.set_cookie(ACCOUNT_COOKIE, issue_cookie(user), httponly=True, samesite="lax",
                        secure=_over_https(request), max_age=SESSION_DAYS * 86400, path="/")


def _set_token_cookie(response: Response, token: str, request: Request) -> None:
    """
    Carry the token in a cookie. Over HTTPS it is marked secure, so a browser
    will not send it back over plain HTTP — on a public domain that is the
    difference between a token that stays private and one that travels in the
    clear on the first http:// link someone clicks.
    """
    response.set_cookie(_TOKEN_COOKIE, token, httponly=True, samesite="strict",
                        secure=_over_https(request), path="/")
# Served without a token so the browser can show the sign-in screen and know
# whether one is needed at all.
# /health is open because whatever runs this has no token to offer; it
# answers with liveness only, never session data.
_OPEN_PATHS = {
    "/", "/login", "/signup", "/verify-email", "/forgot-password",
    "/reset-password", "/app", "/favicon.ico", "/health",
    "/api/access/state", "/api/login", "/api/auth/login", "/api/auth/logout",
    "/api/auth/me", "/api/auth/verify",
    "/api/auth/resend-verification", "/api/auth/password/forgot",
    "/api/auth/password/reset",
}

# Account authentication replaces the shared UI token for normal hosted use.
# These are the only API paths a signed-out browser needs in order to discover
# the account state, create an allowed account, or sign in.  The HTML shell and
# static assets stay public so they can render the sign-in screen.
_ACCOUNT_OPEN_PATHS = {
    "/", "/login", "/signup", "/verify-email", "/forgot-password",
    "/reset-password", "/app", "/favicon.ico", "/health",
    "/api/access/state", "/api/login", "/api/logout",
    "/api/auth/signup", "/api/auth/login", "/api/auth/logout", "/api/auth/me",
    "/api/auth/verify", "/api/auth/resend-verification",
    "/api/auth/password/forgot", "/api/auth/password/reset",
}


def _token_ok(given: str | None) -> bool:
    from ui.access import verify
    return verify(given)


def _request_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    # Query-string secrets are retained for local backwards compatibility only.
    # Hosted URLs pass through proxies, access logs and browser history, all of
    # which can retain the full URL. Hosted users exchange the token in the
    # POST /api/login body and receive an HttpOnly cookie instead.
    if not config.HOSTED:
        query_token = request.query_params.get("token")
        if query_token:
            return query_token
    return request.cookies.get(_TOKEN_COOKIE)


def _signed_in(request: Request) -> bool:
    from ui.access import locked
    if _current_user(request) is not None:
        return True
    return not locked() or _token_ok(_request_token(request))


def _current_user(request: Request):
    """The signed-in person, or None in the local single-user mode."""
    from memory.accounts import user_from_cookie
    try:
        return user_from_cookie(request.cookies.get(ACCOUNT_COOKIE))
    except Exception as exc:                       # a bad cookie is not a crash
        logger.warning("Could not read the account cookie: %s", exc)
        return None


def _require_user(request: Request):
    """The signed-in person when this server has accounts; None when it does not."""
    from memory.accounts import accounts_exist

    user = _current_user(request)
    if user is not None:
        if not user.email_verified:
            raise HTTPException(status_code=403, detail="Verify your email to continue.")
        return user
    if accounts_exist():
        raise HTTPException(status_code=401, detail="Sign in to use this.")
    return None


def _owner_scope(request: Request) -> str | None:
    """Which owner's sessions this request may see: None means "everything on this machine"."""
    user = _require_user(request)
    return user.user_id if user else None


def _authorise_session(session_id: str, request: Request):
    """
    Refuse a session that belongs to someone else. Without this, one account
    could read, run, export and delete another account's research by knowing
    its id — the single most important check on a hosted server.
    """
    db = NoteDB()
    owner = db.session_owner(session_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Session not found")
    user = _require_user(request)
    if user is None:
        return None                                 # local mode: one person, one machine
    if owner and owner != user.user_id:
        # Not 403: whether a session exists is itself somebody else's business.
        raise HTTPException(status_code=404, detail="Session not found")
    if not owner:                                   # a pre-accounts session, adopt on use
        db.update_session(session_id, owner_id=user.user_id)
    return user


@app.middleware("http")
async def _require_token(request: Request, call_next):
    from ui.access import locked
    from memory.accounts import accounts_exist

    path = request.url.path
    public_member_signup = path == "/api/auth/signup" and accounts_exist()
    if (path.startswith("/static/") or path.startswith("/app/") or
            path in _OPEN_PATHS or public_member_signup or not locked()):
        return await call_next(request)
    given = _request_token(request)
    if not _token_ok(given):
        return Response(content=json.dumps({"detail": "Sign in with an access token."}),
                        status_code=401, media_type="application/json")
    response = await call_next(request)
    if not config.HOSTED and request.query_params.get("token"):
        _set_token_cookie(response, given, request)
    return response


@app.middleware("http")
async def _require_account_session(request: Request, call_next):
    """Require a real account for every private HTTP API once accounts exist."""
    from memory.accounts import accounts_exist

    path = request.url.path
    public_page = (path.startswith("/static/") or path.startswith("/app/") or
                   path in _ACCOUNT_OPEN_PATHS)
    if public_page or not accounts_exist():
        return await call_next(request)
    user = _current_user(request)
    if user is None:
        return Response(content=json.dumps({"detail": "Sign in to use this."}),
                        status_code=401, media_type="application/json")
    if not user.email_verified:
        return Response(content=json.dumps({"detail": "Verify your email to continue."}),
                        status_code=403, media_type="application/json")
    return await call_next(request)


@app.get("/health", include_in_schema=False)
async def health():
    """A cheap liveness check for whatever runs this, with no session data in it."""
    from memory.note_db import NoteDB
    try:
        NoteDB().list_sessions()
        database = "ok"
    except Exception as exc:
        logger.warning("Health check could not read the database: %s", exc)
        database = "unreachable"
    return {"status": "ok" if database == "ok" else "degraded", "database": database}


_SESSION_PATH = re.compile(r"^/api/sessions/([^/]+)")


@app.middleware("http")
async def _session_ownership(request: Request, call_next):
    """
    Every route under /api/sessions/<id> is checked here rather than in each
    handler: there are two dozen of them and one forgotten check is a data
    leak. A session belonging to someone else answers 404, the same as one
    that does not exist.
    """
    match = _SESSION_PATH.match(request.url.path)
    if match:
        try:
            _authorise_session(match.group(1), request)
        except HTTPException as exc:
            return Response(content=json.dumps({"detail": exc.detail}),
                            status_code=exc.status_code, media_type="application/json")
        except ValueError:                       # not an id-shaped path segment
            return Response(content=json.dumps({"detail": "Session not found"}),
                            status_code=404, media_type="application/json")
    return await call_next(request)


@app.get("/api/access/state")
async def access_state(request: Request):
    """Whether a token is needed here, and whether this browser has one."""
    from ui.access import locked
    return {"locked": locked(), "signed_in": _signed_in(request)}


@app.post("/api/login")
async def login(req: LoginRequest, request: Request):
    """Exchange a token for a cookie, so the token is not in every URL."""
    import time as _time

    address = _client_address(request)
    recent = [t for t in _LOGIN_ATTEMPTS.get(address, []) if _time.time() - t < _LOGIN_WINDOW_S]
    if len(recent) >= _LOGIN_MAX_TRIES:
        _LOGIN_ATTEMPTS[address] = recent
        raise HTTPException(status_code=429,
                            detail="Too many sign-in attempts. Wait a few minutes and try again.")
    if not _token_ok(req.token.strip()):
        recent.append(_time.time())
        _LOGIN_ATTEMPTS[address] = recent
        raise HTTPException(status_code=401, detail="That token does not work.")
    _LOGIN_ATTEMPTS.pop(address, None)
    response = Response(content=json.dumps({"status": "ok"}), media_type="application/json")
    _set_token_cookie(response, req.token.strip(), request)
    return response


@app.post("/api/logout")
async def logout():
    response = Response(content=json.dumps({"status": "ok"}), media_type="application/json")
    response.delete_cookie(_TOKEN_COOKIE)
    return response


@app.post("/api/auth/signup")
async def signup(req: AccountRequest, request: Request):
    """Create an inactive account and send a one-time verification link."""
    import time as _time

    from memory import account_email
    from memory.accounts import (AccountError, accounts_exist, create_user,
                                 get_user_by_email, issue_account_token,
                                 validate_password)

    if accounts_exist() and not config.ALLOW_SIGNUP:
        raise HTTPException(status_code=403,
                            detail="This server is not accepting new accounts.")
    if not account_email.configured():
        raise HTTPException(status_code=503,
                            detail="Account email is not configured on this server.")
    address = _client_address(request)
    recent = [t for t in _SIGNUP_ATTEMPTS.get(address, [])
              if _time.time() - t < _SIGNUP_WINDOW_S]
    if len(recent) >= _SIGNUP_MAX_TRIES:
        _SIGNUP_ATTEMPTS[address] = recent
        raise HTTPException(status_code=429,
                            detail="Too many account attempts. Try again later.")
    recent.append(_time.time())
    _SIGNUP_ATTEMPTS[address] = recent
    try:
        validate_password(req.password, req.email)
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    user = get_user_by_email(req.email)
    if user is None:
        try:
            user = create_user(req.email, req.password)
        except AccountError as exc:
            # A concurrent request may have inserted the same address. Keep the
            # public response non-enumerating and look it up once more.
            user = get_user_by_email(req.email)
            if user is None:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not user.email_verified:
        token = issue_account_token(user.user_id, "verify_email")
        try:
            await asyncio.to_thread(account_email.send_verification, user.email, token)
        except account_email.EmailDeliveryError as exc:
            logger.error("Could not deliver verification email for user %s: %s",
                         user.user_id, exc)
            raise HTTPException(status_code=503,
                                detail="Verification email could not be delivered. Try again later.") from exc
    return Response(status_code=202, content=json.dumps({
        "status": "verification_required",
        "message": "If this address can be registered, a verification email has been sent.",
    }), media_type="application/json")


@app.post("/api/auth/login")
async def account_login(req: AccountRequest, request: Request):
    """Sign in. Rate limited the same way as the access-token door."""
    import time as _time

    from memory.accounts import verify_password

    address = _client_address(request)
    recent = [t for t in _LOGIN_ATTEMPTS.get(address, []) if _time.time() - t < _LOGIN_WINDOW_S]
    if len(recent) >= _LOGIN_MAX_TRIES:
        _LOGIN_ATTEMPTS[address] = recent
        raise HTTPException(status_code=429, detail="Too many attempts. Wait a few minutes.")
    user = verify_password(req.email, req.password)
    if user is None:
        recent.append(_time.time())
        _LOGIN_ATTEMPTS[address] = recent
        raise HTTPException(status_code=401, detail="Wrong email or password.")
    if not user.email_verified:
        raise HTTPException(status_code=403, detail="Verify your email before signing in.")
    _LOGIN_ATTEMPTS.pop(address, None)
    response = Response(content=json.dumps({"status": "ok", "user": user.as_dict()}),
                        media_type="application/json")
    _set_account_cookie(response, user, request)
    return response


def _limit_account_email(request: Request) -> None:
    import time as _time

    address = _client_address(request)
    recent = [t for t in _EMAIL_ATTEMPTS.get(address, [])
              if _time.time() - t < _EMAIL_WINDOW_S]
    if len(recent) >= _EMAIL_MAX_TRIES:
        _EMAIL_ATTEMPTS[address] = recent
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
    recent.append(_time.time())
    _EMAIL_ATTEMPTS[address] = recent


@app.post("/api/auth/resend-verification")
async def resend_verification(req: EmailRequest, request: Request):
    """Send a fresh link without revealing whether an account exists."""
    from memory import account_email
    from memory.accounts import get_user_by_email, issue_account_token

    _limit_account_email(request)
    if not account_email.configured():
        raise HTTPException(status_code=503,
                            detail="Account email is not configured on this server.")
    user = get_user_by_email(req.email)
    if user is not None and not user.email_verified:
        token = issue_account_token(user.user_id, "verify_email")
        try:
            await asyncio.to_thread(account_email.send_verification, user.email, token)
        except account_email.EmailDeliveryError as exc:
            logger.error("Could not resend verification email for user %s: %s",
                         user.user_id, exc)
    return {"status": "ok", "message": "If the account needs verification, an email has been sent."}


@app.post("/api/auth/verify")
async def verify_account_email(req: AccountTokenRequest, request: Request):
    from memory.accounts import verify_email_token

    user = verify_email_token(req.token)
    if user is None:
        raise HTTPException(status_code=400, detail="That verification link is invalid or expired.")
    response = Response(content=json.dumps({"status": "ok", "user": user.as_dict()}),
                        media_type="application/json")
    _set_account_cookie(response, user, request)
    return response


@app.post("/api/auth/password/forgot")
async def forgot_password(req: EmailRequest, request: Request):
    """Always return the same response so account existence is not disclosed."""
    from memory import account_email
    from memory.accounts import get_user_by_email, issue_account_token

    _limit_account_email(request)
    if not account_email.configured():
        raise HTTPException(status_code=503,
                            detail="Account email is not configured on this server.")
    user = get_user_by_email(req.email)
    if user is not None:
        token = issue_account_token(user.user_id, "reset_password")
        try:
            await asyncio.to_thread(account_email.send_password_reset, user.email, token)
        except account_email.EmailDeliveryError as exc:
            logger.error("Could not deliver password reset email for user %s: %s",
                         user.user_id, exc)
    return {"status": "ok", "message": "If an account exists, a reset email has been sent."}


@app.post("/api/auth/password/reset")
async def reset_password(req: PasswordResetRequest, request: Request):
    from memory.accounts import AccountError, reset_password_with_token

    try:
        user = reset_password_with_token(req.token, req.password)
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=400, detail="That reset link is invalid or expired.")
    response = Response(content=json.dumps({"status": "ok", "user": user.as_dict()}),
                        media_type="application/json")
    _set_account_cookie(response, user, request)
    return response


@app.post("/api/auth/password/change")
async def update_password(req: PasswordChangeRequest, request: Request):
    from memory.accounts import AccountError, change_password

    current = _require_user(request)
    try:
        user = change_password(current.user_id, req.current_password, req.new_password)
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    response = Response(content=json.dumps({"status": "ok", "user": user.as_dict()}),
                        media_type="application/json")
    _set_account_cookie(response, user, request)
    return response


@app.post("/api/auth/logout")
async def account_logout():
    response = Response(content=json.dumps({"status": "ok"}), media_type="application/json")
    response.delete_cookie(ACCOUNT_COOKIE, path="/")
    return response


@app.get("/api/auth/me")
async def account_me(request: Request):
    """Who is signed in, and whether this server uses accounts at all."""
    from memory import account_email
    from memory.accounts import MAX_PASSWORD, MIN_PASSWORD, accounts_exist

    user = _current_user(request)
    return {"accounts": accounts_exist(), "signup_open": bool(config.ALLOW_SIGNUP),
            "email_configured": account_email.configured(),
            "password_policy": {"min_length": MIN_PASSWORD, "max_length": MAX_PASSWORD,
                                "lowercase": True, "uppercase": True,
                                "number": True, "symbol": True},
            "user": user.as_dict() if user else None}


@app.get("/api/access/tokens")
async def list_access_tokens():
    """Every token that opens this server, masked."""
    from ui.access import list_tokens
    return {"tokens": list_tokens(), "locked": bool(list_tokens())}


@app.post("/api/access/tokens")
async def create_access_token(req: NewTokenRequest, request: Request):
    """
    Make a token. The full value is in this one response; afterwards the list
    shows it masked and it can be revealed one at a time by someone signed in.
    """
    from ui.access import create_token, locked

    was_open = not locked()
    created = create_token(req.name)
    response = dict(created)
    response["was_open"] = was_open
    if was_open:            # do not lock the person out of the page they just used
        return Response(content=json.dumps(response), media_type="application/json",
                        headers={"set-cookie": f"{_TOKEN_COOKIE}={created['token']}; HttpOnly; Path=/; SameSite=strict"})
    return response


@app.get("/api/access/tokens/{token_id}")
async def reveal_access_token(token_id: str):
    """The full value of one token, for someone already signed in."""
    from ui.access import reveal
    token = reveal(token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="No such token.")
    return {"id": token_id, "token": token}


@app.delete("/api/access/tokens/{token_id}")
async def revoke_access_token(token_id: str):
    from ui.access import revoke_token
    if not revoke_token(token_id):
        raise HTTPException(status_code=400,
                            detail="That token cannot be revoked here; the .env one is edited in the file.")
    return {"status": "ok", "id": token_id}


@app.get("/api/dashboard")
async def dashboard(request: Request):
    """
    One screen for "what is this thing doing": what is running, what is
    waiting for me, what it has spent, and whether the data is backed up.
    """
    from memory.backup import list_backups
    from tools import app_settings
    from tools.cost_tracker import CostTracker

    db = NoteDB()
    sessions = db.list_sessions(owner_id=_owner_scope(request))
    by_status: dict[str, int] = {}
    running, waiting, recent = [], [], []
    for s in sessions:
        by_status[s["status"]] = by_status.get(s["status"], 0) + 1
        runner = _runners.get(s["session_id"])
        alive = bool(runner and runner.is_alive())
        row = {"session_id": s["session_id"], "topic": s["topic"], "status": s["status"],
               "created_at": s.get("created_at"), "is_running": alive}
        if alive:
            row["waiting_step"] = runner.waiting_step
            running.append(row)
        for stage in ("source_check", "hypotheses", "plan"):
            art = db.get_artifact(s["session_id"], stage)
            if art and art["status"] == "awaiting_approval":
                waiting.append({**row, "stage": stage})
                break
        if len(recent) < 8:
            recent.append(row)

    spent = 0.0
    try:
        spent = CostTracker().spend_today()
    except Exception as exc:
        logger.warning("Could not read today's API spend: %s", exc)
    backups = list_backups()
    db_bytes = Path(config.SQLITE_PATH).stat().st_size if Path(config.SQLITE_PATH).exists() else 0

    critical = 0
    for s in sessions:
        critical += sum(1 for d in db.get_degradations(s["session_id"]) if d["severity"] == "critical")

    return {
        "sessions": {"total": len(sessions), "by_status": by_status,
                     "running": len(running), "waiting": len(waiting)},
        "running": running,
        "waiting_for_you": waiting,
        "recent": recent,
        "spend": {"today_usd": round(spent, 4), "daily_budget_usd": app_settings.daily_budget_usd(),
                  "use_api": _settings["use_api"]},
        "critical_degradations": critical,
        "storage": {"database_bytes": db_bytes, "backups": len(backups),
                    "latest_backup": backups[0] if backups else None},
    }


@app.get("/api/sessions")
async def list_sessions(request: Request):
    from memory import runs as run_registry

    db = NoteDB()
    sessions = db.list_sessions(owner_id=_owner_scope(request))
    # Annotate with running status, and with runs a stopped server left behind.
    stopped = {r["session_id"] for r in run_registry.list_all(run_registry.INTERRUPTED)}
    for s in sessions:
        runner = _runners.get(s["session_id"])
        s["is_running"] = bool(runner and runner.is_alive())
        s["interrupted"] = s["session_id"] in stopped
    return {"sessions": sessions}


def _load_json_field(session: dict, key: str) -> Any:
    """Parse a JSON-encoded column from the session dict, return None on failure."""
    import json as _json
    val = session.get(key)
    if not val:
        return None
    try:
        return _json.loads(val)
    except Exception:
        return None


def _gap_staleness(db: NoteDB, session_id: str) -> str:
    """Empty when the stored gap report still matches this session's brief and papers."""
    try:
        from agents.gap_analysis import gap_staleness
        return gap_staleness(db, session_id)
    except Exception as exc:
        logger.warning("Could not check gap report freshness: %s", exc)
        return ""


def _sanitize_json(obj: Any) -> Any:
    """Recursively replace NaN/Inf floats with None so FastAPI can serialize them."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_json(v) for v in obj]
    return obj


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    db = NoteDB()
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    papers = db.get_papers(session_id)
    hypotheses = db.get_hypotheses(session_id)
    code_files = db.get_session_experiment_code(session_id)
    runs = db.get_experiment_runs(session_id)

    # What this session cost — not the all-time total, which is on the dashboard.
    from tools.cost_tracker import CostTracker
    spend = CostTracker().session_cost(session_id)

    return _sanitize_json({
        "session": session,
        "gap_report": session.get("gap_report"),
        # A gap report written for a different brief or paper set still shows;
        # say so rather than letting it look current.
        "gap_report_stale": _gap_staleness(db, session_id),
        "papers": papers,
        "hypotheses": hypotheses,
        "code_files": [
            {
                "file_path": f["file_path"],
                "language": f["language"],
                "content": f["file_content"],
                "hypothesis_id": f["hypothesis_id"],
            }
            for f in code_files
        ],
        "runs": runs,
        "cost_usd": spend["cost_usd"],
        "spend": spend,
        "quality_review": _load_json_field(session, "quality_review"),
        "report": _load_json_field(session, "report"),
        "gap_validation": _load_json_field(session, "gap_validation"),
        "artifacts": {a["stage"]: {"version": a["version"], "status": a["status"], "approved": a["approved"],
                                   "content": a["content"]} for a in db.list_artifacts(session_id)},
        "waiting_step": _runners[session_id].waiting_step if session_id in _runners else None,
        "interrupted": _interrupted_marker(session_id),
    })


def _interrupted_marker(session_id: str) -> dict | None:
    """What the page shows when a run was cut short by the server stopping."""
    from memory import runs as run_registry

    row = run_registry.interrupted(session_id)
    if row is None:
        return None
    return {"stopped_at": row["heartbeat_at"] or row["started_at"],
            "stage": row["stage"], "note": row["note"]}


@app.get("/api/sessions/{session_id}/status")
async def session_status(session_id: str):
    runner = _runners.get(session_id)
    return {"running": bool(runner and runner.is_alive()),
            "interrupted": _interrupted_marker(session_id)}


@app.get("/api/sessions/{session_id}/training-metrics")
async def training_metrics(session_id: str):
    """
    Return this session's training metrics (experiments/<session_id>/runs/metrics.json).
    """
    import json as _json
    import config as _cfg

    for hyp_dir in [_cfg.session_experiment_dir(session_id)]:
        metrics_path = hyp_dir / "runs" / "metrics.json"
        if metrics_path.exists():
            try:
                with metrics_path.open("r", encoding="utf-8") as f:
                    data = _json.load(f)
                return {"metrics": _sanitize_json(data), "source": str(metrics_path)}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Failed to read metrics: {exc}")

    raise HTTPException(status_code=404, detail="No training metrics found.")


@app.get("/api/sessions/{session_id}/eval-results")
async def eval_results(session_id: str):
    """
    Return this session's eval_results.json (experiments/<session_id>/results/).
    """
    import json as _json
    import config as _cfg

    for hyp_dir in [_cfg.session_experiment_dir(session_id)]:
        results_path = hyp_dir / "results" / "eval_results.json"
        if results_path.exists():
            try:
                with results_path.open("r", encoding="utf-8") as f:
                    data = _json.load(f)
                return {"results": _sanitize_json(data), "source": str(results_path)}
            except Exception as exc:
                raise HTTPException(
                    status_code=500, detail=f"Failed to read eval results: {exc}"
                )

    raise HTTPException(status_code=404, detail="No eval results found.")


# ─── Report endpoints ─────────────────────────────────────────────────────────

def _report_dir(session_id: str) -> Path:
    return Path(config.BASE_DIR) / "data" / "reports" / session_id

def _load_report_json(session_id: str) -> dict | None:
    p = _report_dir(session_id) / "report.json"
    if not p.exists():
        return None
    import json as _json
    return _json.loads(p.read_text(encoding="utf-8"))


@app.post("/api/sessions/{session_id}/report", status_code=201)
async def generate_report(session_id: str, request: Request):
    """
    Generate the research report for a session (LLM call — may take ~30s).
    Saves report.json + rendered files under data/reports/{session_id}/.
    Returns the full report JSON plus a 'mode' field:
      "api"      — used the session's effective model API route
      "local"    — used local LLM (llama-cpp) as API fallback
      "template" — no LLM available; data-driven template only
    """
    from models.api_model import APIModel
    from agents.report_agent import ReportAgent
    from ui.report_renderer import save_all

    _authorise_session(session_id, request)
    db = NoteDB()
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    # A study report (stage S8) is built only from checked claims; the generic
    # writer below must not overwrite it.
    study_report = db.get_artifact(session_id, "report")
    if study_report is not None:
        report = {k: v for k, v in study_report["content"].items() if k != "results_hash"}
        return {"report": report, "mode": "study"}

    use_api, model_provider = _session_inference_settings(session)
    api_model = APIModel(session_id=session_id,
                         user_id=db.session_owner(session_id) or "",
                         provider=model_provider, enabled=use_api)

    # Hosted deployments never probe for a local binary or model file.
    local_model = None
    if not config.HOSTED:
        try:
            from models.ollama_model import OllamaModel
            local_model = OllamaModel()
            local_model.load()
        except Exception as exc:
            logger.info("Ollama not available for report generation (%s); trying GGUF.", exc)
            local_model = _try_get_local_model()
    if local_model is not None:
        api_model.set_local_model(local_model)

    # Run in a thread so the async event loop isn't blocked
    def _run():
        agent = ReportAgent(api_model=api_model, note_db=db)
        report = agent.generate(session_id)
        save_all(report, _report_dir(session_id))
        return report, agent.mode

    try:
        report, mode = await asyncio.get_event_loop().run_in_executor(None, _run)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}")

    return {"report": report, "mode": mode}


@app.get("/api/report-backend-status")
async def report_backend_status(request: Request, session_id: str = ""):
    """
    Return which report-generation backends are available.
    Used by the UI to show the expected mode before generating.
    """
    from models import providers

    session = None
    if session_id:
        _authorise_session(session_id, request)
        session = NoteDB().get_session(session_id)
    enabled, provider = _session_inference_settings(session)
    route = _effective_inference_route(request, enabled, provider)
    effective_provider = route["effective_provider"]
    api_ready = False
    if enabled and route["inference_mode"] == "byok":
        api_ready = True
    elif enabled and effective_provider:
        try:
            api_ready = bool(providers.resolve(effective_provider).key())
        except providers.ProviderUnavailable:
            api_ready = False
    lm_path = Path(config.LOCAL_MODEL_PATH)
    lm_loaded = bool(_local_model_singleton and _local_model_singleton.is_loaded)
    local_ready = not config.HOSTED and (lm_path.exists() or lm_loaded)
    return {
        "api_key_configured": api_ready,
        **route,
        "local_model_file_exists": bool(not config.HOSTED and lm_path.exists()),
        "local_model_loaded": lm_loaded,
        "local_model_path": str(lm_path),
        # Expected mode: api → local → template
        "expected_mode": (
            "api" if api_ready
            else "local" if local_ready
            else "template"
        ),
    }


@app.get("/api/sessions/{session_id}/report")
async def get_report(session_id: str):
    """Return the cached report JSON (404 if not generated yet)."""
    report = _load_report_json(session_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not generated yet.")
    return {"report": report}


@app.get("/api/sessions/{session_id}/report/markdown")
async def download_markdown(session_id: str):
    from ui.report_renderer import to_markdown
    report = _load_report_json(session_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not generated yet.")
    md = to_markdown(report)
    return Response(
        content=md.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="report.md"'},
    )


@app.get("/api/sessions/{session_id}/report/latex")
async def download_latex(session_id: str):
    from ui.report_renderer import to_latex
    report = _load_report_json(session_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not generated yet.")
    tex = to_latex(report)
    return Response(
        content=tex.encode("utf-8"),
        media_type="application/x-latex; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="report.tex"'},
    )


@app.get("/api/sessions/{session_id}/report/pdf")
async def download_pdf(session_id: str):
    from ui.report_renderer import to_pdf_bytes
    report = _load_report_json(session_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not generated yet.")
    pdf_bytes, mimetype, why_not_pdf = to_pdf_bytes(report)
    ext = "pdf" if "pdf" in mimetype else "html"
    headers = {"Content-Disposition": f'attachment; filename="report.{ext}"',
               "X-Report-Format": ext}
    if why_not_pdf:
        headers["X-Report-Fallback"] = why_not_pdf.encode("ascii", "replace").decode()  # header must be latin-1
    return Response(content=pdf_bytes, media_type=mimetype, headers=headers)


@app.post("/api/sessions", status_code=201)
async def create_session(req: NewSessionRequest, request: Request):
    from tools import app_settings

    topic = req.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic cannot be empty.")

    background   = (req.background   or "").strip()
    goals        = (req.goals        or "").strip()
    constraints  = (req.constraints  or "").strip()

    db = NoteDB()
    owner = _require_user(request)
    project_id = (getattr(req, "project_id", "") or "").strip()
    if project_id:
        _authorise_project(project_id, request)
    session_id = db.create_session(
        topic, background=background, goals=goals, constraints=constraints,
        owner_id=owner.user_id if owner else "", project_id=project_id,
        model_api_enabled=_settings["use_api"],
        model_provider=app_settings.api_provider(),
    )

    # Someone starting in the middle — their own papers, their own question —
    # does not want the whole pipeline to set off the moment they press create.
    if not req.autostart:
        return {"session_id": session_id, "topic": topic, "started": False}

    # A hosted run takes a place in the plan's allowance. Opening, reading or
    # exporting a session never does; only work that the server performs.
    run_id = _claim_run(owner, session_id, stage="full")
    runner = SessionRunner(
        session_id=session_id,
        topic=topic,
        background=background,
        goals=goals,
        constraints=constraints,
        use_api=_settings["use_api"],
        model_provider=app_settings.api_provider(),
    )
    runner.run_id = run_id
    _runners[session_id] = runner
    runner.start()

    return {"session_id": session_id, "topic": topic, "started": True}


@app.patch("/api/sessions/{session_id}/details")
async def update_session_details(session_id: str, req: UpdateDetailsRequest):
    """Update topic / background / goals / constraints for a session."""
    db = NoteDB()
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    updates: dict = {}
    if req.topic       is not None: updates["topic"]       = req.topic.strip()
    if req.background  is not None: updates["background"]  = req.background.strip()
    if req.goals       is not None: updates["goals"]       = req.goals.strip()
    if req.constraints is not None: updates["constraints"] = req.constraints.strip()

    if updates:
        db.update_session(session_id, **updates)

    # If runner is active, update its fields in-memory too
    runner = _runners.get(session_id)
    if runner and runner.is_alive():
        if "background"  in updates: runner.background  = updates["background"]
        if "goals"       in updates: runner.goals        = updates["goals"]
        if "constraints" in updates: runner.constraints  = updates["constraints"]
        if "topic"       in updates: runner.topic        = updates["topic"]

    return {"status": "ok", "updated": list(updates.keys())}


@app.post("/api/sessions/{session_id}/stop")
async def stop_session(session_id: str):
    runner = _runners.get(session_id)
    if not runner or not runner.is_alive():
        raise HTTPException(status_code=404, detail="No active runner for this session.")
    runner.stop()
    return {"status": "stopping"}


@app.post("/api/sessions/{session_id}/resume")
async def resume_session(session_id: str, request: Request):
    _authorise_session(session_id, request)
    db = NoteDB()
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    existing = _runners.get(session_id)
    if existing and existing.is_alive():
        return {"session_id": session_id, "status": "already_running"}

    # Restore detail fields from DB so the runner uses them
    use_api, model_provider = _session_inference_settings(session)
    runner = SessionRunner(
        session_id=session_id,
        background=session.get("background") or "",
        goals=session.get("goals") or "",
        constraints=session.get("constraints") or "",
        use_api=use_api,
        model_provider=model_provider,
    )
    _runners[session_id] = runner
    runner.start()
    return {"session_id": session_id, "status": "started"}


@app.post("/api/sessions/{session_id}/select-question")
async def select_question(session_id: str, req: SelectQuestionRequest):
    runner = _runners.get(session_id)
    if not runner:
        raise HTTPException(
            status_code=404,
            detail="No active runner for this session. Start or resume first.",
        )
    runner.select_question(req.choice, req.override)
    return {"status": "ok"}


def _claim_run(user, session_id: str, stage: str = "") -> str:
    """
    Take a place in the plan's allowance before starting work. Raises 409 with
    the reason — allowance or concurrency — so the page can say which.
    """
    from memory import quota

    try:
        return quota.reserve(user, session_id=session_id, stage=stage)
    except quota.QuotaExceeded as exc:
        raise HTTPException(status_code=409, detail=str(exc),
                            headers={"X-Quota-Reason": exc.reason}) from exc


def _release_run(run_id: str, outcome: str, reason: str = "") -> None:
    from memory import quota
    quota.settle(run_id, outcome, reason)


def _start_runner(session_id: str, db: NoteDB, only: str | None = None) -> bool:
    """
    Start the pipeline for a session that has no live runner. With `only`, it
    runs that one stage and stops. Returns True if it started.
    """
    existing = _runners.get(session_id)
    if existing and existing.is_alive():
        return False
    session = db.get_session(session_id)
    use_api, model_provider = _session_inference_settings(session)
    runner = SessionRunner(
        session_id=session_id,
        background=session.get("background") or "",
        goals=session.get("goals") or "",
        constraints=session.get("constraints") or "",
        use_api=use_api,
        model_provider=model_provider,
        only=only,
    )
    _runners[session_id] = runner
    runner.start()
    return True


# A paste box reachable from the internet needs a ceiling; 4 MB is a very
# large reference list and still far below anything that would exhaust memory.
MAX_IMPORT_BYTES = 4 * 1024 * 1024


class ImportRequest(BaseModel):
    text: str
    filename: str = ""


@app.get("/api/sessions/{session_id}/stages")
async def session_stages(session_id: str):
    """
    Every stage with: is it done, can it run now, and if not, what is missing
    and how to supply it by hand.
    """
    from agents.stages import readiness

    db = NoteDB()
    if not db.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    runner = _runners.get(session_id)
    return {"stages": readiness(db, session_id),
            "running": bool(runner and runner.is_alive()),
            "waiting_step": runner.waiting_step if runner else None}


@app.post("/api/sessions/{session_id}/run/{stage}")
async def run_one_stage(session_id: str, stage: str, request: Request):
    """
    Run a single stage and stop. Whatever it needs must already be in the
    session — produced by an earlier stage or imported — and if it is not,
    this says what is missing instead of starting and failing half-way.
    """
    from agents.stages import BY_KEY, blocking

    db = NoteDB()
    if not db.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    if stage not in BY_KEY:
        raise HTTPException(status_code=400,
                            detail=f"Unknown stage. Known stages: {', '.join(BY_KEY)}")
    missing = blocking(db, session_id, stage)
    if missing:
        raise HTTPException(status_code=409, detail="This stage cannot run yet: " + "; ".join(missing))
    runner = _runners.get(session_id)
    if runner and runner.is_alive():
        raise HTTPException(status_code=409, detail="This session is already running.")
    run_id = _claim_run(_require_user(request), session_id, stage=stage)
    started = _start_runner(session_id, db, only=stage)
    if started:
        _runners[session_id].run_id = run_id
    else:
        _release_run(run_id, "cancelled", "the runner did not start")
    return {"status": "ok", "stage": stage, "started": started}


@app.post("/api/sessions/{session_id}/import/{kind}")
async def import_into_session(session_id: str, kind: str, req: ImportRequest):
    """
    Put work someone already has into a session: a paper list (CSV, JSON or
    BibTeX), a research question, or a gap report. Imported work is marked as
    imported so the report can say which parts this pipeline did not do.
    """
    from memory import importing

    db = NoteDB()
    if not db.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    handlers = {
        "papers": lambda: importing.import_papers(db, session_id, req.text, req.filename),
        "question": lambda: importing.import_question(db, session_id, req.text),
        "gap_report": lambda: importing.import_gap_report(db, session_id, req.text),
    }
    if kind not in handlers:
        raise HTTPException(status_code=400,
                            detail=f"Unknown import. Known kinds: {', '.join(handlers)}")
    if len(req.text.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413,
                            detail=f"That is larger than {MAX_IMPORT_BYTES // (1024 * 1024)} MB. "
                                   "Split the file, or trim it to the papers you need.")
    try:
        result = handlers[kind]()
    except importing.ImportError_ as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    from agents.stages import readiness
    return {"status": "ok", "kind": kind, **result, "stages": readiness(db, session_id)}


@app.post("/api/sessions/{session_id}/select-hypotheses")
async def select_hypotheses(session_id: str, req: SelectHypothesesRequest):
    """
    Answer the hypothesis gate. Works whether or not the pipeline is running:
    after a server restart the stored decision is applied and the session is
    resumed, instead of the buttons doing nothing.
    """
    from ui.study_runner import apply_hypothesis_selection

    runner = _runners.get(session_id)
    if runner and runner.waiting_step == "hypothesis_selection":
        runner.provide_input("hypothesis_selection", req.ids)
        return {"status": "ok", "resumed": False}
    db = NoteDB()
    accepted, message = apply_hypothesis_selection(db, session_id, req.ids)
    if not accepted:
        raise HTTPException(status_code=409, detail=message)
    return {"status": "ok", "resumed": _start_runner(session_id, db), "message": message}


@app.post("/api/sessions/{session_id}/source-decision")
async def decide_source(session_id: str, req: SourceDecisionRequest):
    """Continue without a blocked source the brief relies on, or stop the study."""
    from ui.study_runner import apply_source_decision

    runner = _runners.get(session_id)
    if runner and runner.waiting_step == "source_confirmation":
        runner.provide_input("source_confirmation", {"proceed": req.proceed})
        return {"status": "ok", "proceeding": req.proceed, "resumed": False}
    db = NoteDB()
    proceeding, message = apply_source_decision(db, session_id, req.proceed)
    resumed = _start_runner(session_id, db) if proceeding else False
    return {"status": "ok", "proceeding": proceeding, "message": message, "resumed": resumed}


@app.post("/api/sessions/{session_id}/plan")
async def submit_plan(session_id: str, req: PlanRequest):
    """Check (approve=false) or approve (approve=true) the analysis plan text."""
    from ui.study_runner import apply_plan

    runner = _runners.get(session_id)
    if runner and runner.waiting_step == "plan_approval":
        runner.provide_input("plan_approval", {"text": req.text, "approve": req.approve})
        return {"status": "ok", "resumed": False}
    db = NoteDB()
    approved, problems = apply_plan(db, session_id, req.text, req.approve)
    resumed = _start_runner(session_id, db) if approved else False
    return {"status": "ok", "approved": approved, "problems": problems, "resumed": resumed}


@app.get("/api/sessions/{session_id}/export")
async def export_session_bundle(session_id: str):
    """Download everything stored for a session as one JSON file."""
    from memory.backup import export_session

    try:
        bundle = export_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return Response(
        content=json.dumps(_sanitize_json(bundle), indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="session-{session_id[:8]}.json"'},
    )


@app.delete("/api/sessions/{session_id}")
async def remove_session_endpoint(session_id: str):
    """
    Take a session out of the list. Its rows and folders are written to
    data/removed/<session id>/ first, and the database is backed up, so this
    can be undone by hand.
    """
    from memory.backup import remove_session

    runner = _runners.get(session_id)
    if runner and runner.is_alive():
        runner.stop()                             # cooperative: it stops at the next checkpoint
        for _ in range(20):
            if not runner.is_alive():
                break
            await asyncio.sleep(0.5)
        if runner.is_alive():
            raise HTTPException(
                status_code=409,
                detail="The session is still finishing a step. Stop it, wait for it to end, then remove it.",
            )
    try:
        result = remove_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    _runners.pop(session_id, None)
    return result


@app.get("/api/backups")
async def list_backups_endpoint():
    from memory.backup import list_backups
    return {"backups": list_backups(), "folder": str(Path(config.DB_DIR) / "backups")}


@app.post("/api/backups")
async def make_backup():
    from memory.backup import backup_db
    path = backup_db("manual")
    return {"status": "ok", "file": path.as_posix(), "bytes": path.stat().st_size}


@app.on_event("startup")
async def _recover_interrupted_runs() -> None:
    """
    Runs belonging to a server that is gone. Each one gets its allowance place
    back and its session told why it stopped, so nobody comes back to a session
    that looks finished at a stage it never finished.

    The sweep runs again on a timer: a server can also die while this one is
    up, and an allowance place must not stay held for hours.
    """
    import asyncio

    from memory import runs as run_registry

    async def sweep(first: bool) -> None:
        try:
            found = await asyncio.to_thread(run_registry.recover)
            if found:
                logger.warning("Marked %d run(s) as interrupted: %s", len(found),
                               ", ".join(r["session_id"][:8] for r in found))
            elif first:
                logger.info("No interrupted runs to recover.")
        except Exception as exc:                  # never stop the server for this
            logger.warning("Could not check for interrupted runs: %s", exc)

    await sweep(first=True)

    async def keep_sweeping() -> None:
        while True:
            await asyncio.sleep(_RECOVERY_SWEEP_S)
            await sweep(first=False)

    asyncio.create_task(keep_sweeping())


@app.on_event("startup")
async def _daily_backup() -> None:
    from memory.backup import backup_if_stale
    try:
        made = backup_if_stale()
        if made:
            logger.info("Database backed up to %s", made)
    except Exception as exc:                      # a backup must never stop the server
        logger.warning("Startup backup failed: %s", exc)


@app.post("/api/sessions/{session_id}/redo/{stage}")
async def redo_stage(session_id: str, stage: str):
    """
    Rebuild a stage and everything built from it. Until now this needed editing
    the database by hand.
    """
    from ui.study_runner import DOWNSTREAM, invalidate

    if stage not in DOWNSTREAM:
        raise HTTPException(status_code=400, detail=f"Unknown stage {stage!r}.")
    runner = _runners.get(session_id)
    if runner and runner.is_alive():
        raise HTTPException(status_code=409, detail="Stop the session before redoing a stage.")
    db = NoteDB()
    if db.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    cleared = invalidate(db, session_id, stage)
    return {"status": "ok", "cleared": cleared, "resumed": _start_runner(session_id, db)}


# ─── WebSocket ────────────────────────────────────────────────────────────────

def _websocket_may_watch(session_id: str, websocket: WebSocket) -> bool:
    """The live log of someone else's session is theirs, not yours."""
    from memory.accounts import accounts_exist, user_from_cookie

    if not accounts_exist():
        return True
    user = user_from_cookie(websocket.cookies.get(ACCOUNT_COOKIE))
    if user is None:
        return False
    owner = NoteDB().session_owner(session_id)
    return owner in ("", user.user_id) and owner is not None


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    query_token = websocket.query_params.get("token") if not config.HOSTED else None
    if config.UI_TOKEN and not _token_ok(query_token or websocket.cookies.get(_TOKEN_COOKIE)):
        await websocket.close(code=1008)      # HTTP middleware does not see websockets
        return
    if not _websocket_may_watch(session_id, websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()

    runner = _runners.get(session_id)
    if not runner:
        await websocket.send_json({
            "type": "error",
            "data": {"message": "No active runner for this session."},
        })
        await websocket.close()
        return

    try:
        while True:
            # Non-blocking poll of the thread queue
            event = runner.get_event(timeout=0.05)
            if event is not None:
                try:
                    await websocket.send_json(event)
                except Exception:
                    break
                if event["type"] == "done":
                    # Drain any remaining events
                    await asyncio.sleep(0.1)
                    while True:
                        ev = runner.get_event(timeout=0.01)
                        if ev is None:
                            break
                        try:
                            await websocket.send_json(ev)
                        except Exception:
                            break
                    break
            else:
                # No event yet — check if runner finished
                if not runner.is_alive() and runner.queue_empty():
                    break
                await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session %s", session_id)
    except Exception as exc:
        logger.warning("WebSocket error for %s: %s", session_id, exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
