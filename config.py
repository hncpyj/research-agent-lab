"""
Global configuration for the AI Research Agent system.
Edit this file to set model paths, API keys, and tuning parameters.
"""

from pathlib import Path
import os
import re
import sys

# Work around protobuf version conflicts in the base Conda environment.
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

# Load the .env file automatically.
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.resolve()
# Where anything worth keeping is written. On a hosted machine the code folder
# is usually wiped on every deploy, so point these at a mounted volume:
#   DATA_DIR=/data  EXPERIMENTS_DIR=/data/experiments
DATA_DIR = Path(os.environ.get("DATA_DIR") or (BASE_DIR / "data"))
PAPERS_DIR = DATA_DIR / "papers"
DB_DIR = DATA_DIR / "db"
DATASETS_DIR = DATA_DIR / "datasets"   # datasets declared in a session brief (tools/dataset_schema.py)
DATASET_MAX_MB: int = int(os.environ.get("DATASET_MAX_MB", "200"))
# Hosts a session brief may download a dataset from. Empty means any public
# host; addresses inside this network are refused either way
# (tools/url_safety.py). Example: DATASET_ALLOWED_HOSTS=who.int,worldbank.org
DATASET_ALLOWED_HOSTS: list[str] = [h.strip().lower() for h in
                                    os.environ.get("DATASET_ALLOWED_HOSTS", "").split(",") if h.strip()]

EXPERIMENTS_DIR = Path(os.environ.get("EXPERIMENTS_DIR") or (BASE_DIR / "experiments"))


_SESSION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def safe_session_id(session_id: str) -> str:
    """
    Session ids reach file paths from HTTP path parameters, so an id like
    '..%2f..%2fdata' would point at any folder on the machine. Ids are made
    with uuid4; anything that is not id-shaped is refused here rather than
    at each of the dozen call sites.
    """
    if not _SESSION_ID_RE.match(session_id or ""):
        raise ValueError(f"not a session id: {session_id!r}")
    return session_id


def session_experiment_dir(session_id: str) -> Path:
    """Every file a session's experiment writes or reads lives here, never in a shared folder."""
    return EXPERIMENTS_DIR / safe_session_id(session_id)

# Ensure directories exist at import time
for _d in (PAPERS_DIR, DB_DIR, DATASETS_DIR, EXPERIMENTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

CHROMA_PATH = DB_DIR / "chroma"
SQLITE_PATH = DB_DIR / "research.db"

# ---------------------------------------------------------------------------
# Local model (llama-cpp-python)
# ---------------------------------------------------------------------------
# Download Qwen2.5-14B-Instruct-Q4_K_M.gguf and set LOCAL_MODEL_PATH.
# Default location: ~/models/  (works on Windows, macOS, Linux)
#   Windows : C:\Users\<you>\models\qwen2.5-14b-instruct-q4_k_m-00001-of-00003.gguf
#   macOS   : /Users/<you>/models/qwen2.5-14b-instruct-q4_k_m-00001-of-00003.gguf
#   Linux   : /home/<you>/models/qwen2.5-14b-instruct-q4_k_m-00001-of-00003.gguf
_DEFAULT_MODELS_DIR = Path.home() / "models"
LOCAL_MODEL_PATH: str = os.environ.get(
    "LOCAL_MODEL_PATH",
    str(_DEFAULT_MODELS_DIR / "qwen2.5-14b-instruct-q4_k_m-00001-of-00003.gguf"),
)

# GPU layers to offload to VRAM.
# RTX 3060 Ti (8 GB): 35 layers  |  Apple Silicon (unified): try 1 (Metal)
# Set N_GPU_LAYERS=0 to run fully on CPU.
N_GPU_LAYERS: int = int(os.environ.get("N_GPU_LAYERS", "35"))

# Context window size (tokens)
N_CTX: int = int(os.environ.get("N_CTX", "8192"))

# Max tokens to generate in a single local-model call
LOCAL_MAX_TOKENS: int = 2048

# ---------------------------------------------------------------------------
# Embedding model (nomic-embed-text via llama-cpp-python)
# ---------------------------------------------------------------------------
# Download nomic-embed-text-v1.5.Q4_K_M.gguf and set EMBED_MODEL_PATH.
EMBED_MODEL_PATH: str = os.environ.get(
    "EMBED_MODEL_PATH",
    str(_DEFAULT_MODELS_DIR / "nomic-embed-text-v1.5.Q4_K_M.gguf"),
)
EMBED_N_GPU_LAYERS: int = int(os.environ.get("EMBED_N_GPU_LAYERS", "33"))

# ChromaDB collection name
CHROMA_COLLECTION: str = "papers"

# ---------------------------------------------------------------------------
# Ollama (local model backend — alternative to llama-cpp-python)
# ---------------------------------------------------------------------------
# Set OLLAMA_HOST to override the default server address.
# Set OLLAMA_MODEL to the tag shown by `ollama list` (prefix match also works).
OLLAMA_HOST: str  = os.environ.get("OLLAMA_HOST",  "http://localhost:11434")
OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
# Context window sent with every request. Ollama's default here was 2048
# tokens, and longer prompts were silently cut from the front (measured
# 2026-09-13: a ~15k-token prompt processed as 2,050 tokens). 8192 keeps
# llama3.1:8b fully on an 8 GB GPU; 16384 spilled 13% to CPU.
OLLAMA_NUM_CTX: int = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))
# Upper bound for a single call whose prompt does not fit OLLAMA_NUM_CTX
# (e.g. the final report); only those calls pay the CPU spill.
OLLAMA_MAX_NUM_CTX: int = int(os.environ.get("OLLAMA_MAX_NUM_CTX", "16384"))
# Used by the Web UI for paper-relevance ranking (Phase 1) — install with
# `ollama pull nomic-embed-text`. If unavailable, ranking degrades to
# unranked order with a recorded (not silent) degradation.
OLLAMA_EMBED_MODEL: str = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# ---------------------------------------------------------------------------
# Web UI access
# ---------------------------------------------------------------------------
# The UI has no accounts: anyone who can reach the port can start runs, read
# every session and remove them. Set UI_TOKEN to require it on every request
# (Authorization: Bearer or a ra_token cookie). Local mode also accepts
# ?token= once per browser for backwards compatibility; hosted mode does not,
# because URLs are commonly retained in proxy logs and browser history.
# run_ui.py refuses to bind to a non-loopback address without one.
UI_TOKEN: str = os.environ.get("UI_TOKEN", "")

# Whether anyone may create an account once the first one exists. A private
# server leaves this off: the owner signs up once, and nobody else can.
ALLOW_SIGNUP: bool = os.environ.get("ALLOW_SIGNUP", "0") not in ("0", "false", "False")

# Hosted account email. Signup should remain closed until a sender is
# configured. PUBLIC_APP_URL receives verification and password-reset links.
PUBLIC_APP_URL: str = os.environ.get("PUBLIC_APP_URL", "http://127.0.0.1:8000").rstrip("/")
SMTP_HOST: str = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT: int = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME: str = os.environ.get("SMTP_USERNAME", "").strip()
SMTP_PASSWORD: str = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM: str = os.environ.get("SMTP_FROM", "").strip()
SMTP_STARTTLS: bool = os.environ.get("SMTP_STARTTLS", "1") not in ("0", "false", "False")
RESEND_API_KEY: str = os.environ.get("RESEND_API_KEY", "").strip()

# ---------------------------------------------------------------------------
# Model inference APIs (Anthropic, OpenAI or Gemini) — see models/providers.py
# ---------------------------------------------------------------------------
# Startup default for the Web UI's API toggle. Set USE_API=0 to keep every
# phase on the local model even across server restarts — the toggle itself
# is in-memory, and used to fall back to "on" whenever the server restarted.
USE_API: bool = os.environ.get("USE_API", "1") not in ("0", "false", "False")

# Preferred BYOK backend for new sessions: anthropic | openai | gemini.
# Hosted users without a key for their selected provider use SHARED_FREE_PROVIDER.
API_PROVIDER: str = os.environ.get("API_PROVIDER", "gemini").strip().lower()

ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))

# Model IDs — switch to claude-opus-4-6 for highest quality
API_MODEL_DEFAULT: str = os.environ.get("API_MODEL", "claude-sonnet-4-5")
OPENAI_MODEL: str = os.environ.get("OPENAI_MODEL", "gpt-5")
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Hosted users without a BYOK key use this server-owned free-tier provider.
# The key stays server-side and is never returned by an HTTP or WebSocket API.
# Gemini's free tier still requires a Google AI Studio API key.
SHARED_FREE_PROVIDER: str = os.environ.get("SHARED_FREE_PROVIDER", "gemini").strip().lower()
SHARED_FREE_MODEL: str = os.environ.get(
    "SHARED_FREE_MODEL", "gemini-3.5-flash-lite"
).strip()

# Both OpenAI and Gemini are called through the OpenAI SDK: Google publishes an
# OpenAI-compatible endpoint (https://ai.google.dev/gemini-api/docs/openai), so
# a second SDK is not needed. Override OPENAI_BASE_URL to use any other
# OpenAI-compatible server (a proxy, a local vLLM, OpenRouter…).
OPENAI_BASE_URL: str = os.environ.get("OPENAI_BASE_URL", "")
GEMINI_BASE_URL: str = os.environ.get(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")

# Max tokens to request from the API per call
# 8192 prevents generated Python files from being truncated mid-function
API_MAX_TOKENS: int = 8192

# Most this may spend on billed model APIs in one day (UTC-naive local
# midnight), measured from the api_usage_log table so it survives a restart.
# Past the cap every call goes to the local model instead. 0 = no cap.
API_DAILY_BUDGET_USD: float = float(os.environ.get("API_DAILY_BUDGET_USD", "0"))

# ---------------------------------------------------------------------------
# External paper sources — see tools/rate_limit.py and tools/sources/
# ---------------------------------------------------------------------------
# Every request to the same source is spaced by a random 20-30 s, and a source
# that signals rate limiting is not contacted again for SOURCE_BLOCK_DAYS.
REQUEST_INTERVAL_MIN_S: float = float(os.environ.get("REQUEST_INTERVAL_MIN_S", "20"))
REQUEST_INTERVAL_MAX_S: float = float(os.environ.get("REQUEST_INTERVAL_MAX_S", "30"))
SOURCE_BLOCK_DAYS: float = float(os.environ.get("SOURCE_BLOCK_DAYS", "7"))

# Sources searched in Phase 1 and gap validation, in order.
PAPER_SOURCES: list[str] = [
    s.strip() for s in os.environ.get(
        "PAPER_SOURCES", "arxiv,openalex,europepmc,crossref,openreview"
    ).split(",") if s.strip()
]
SOURCE_MAX_RESULTS: int = int(os.environ.get("SOURCE_MAX_RESULTS", "25"))  # per source, per query

# OpenAlex requires a free API key since Feb 2026: https://openalex.org/settings/api
OPENALEX_API_KEY: str = os.environ.get("OPENALEX_API_KEY", "")
# Sent as `mailto` to Crossref (polite pool) and in User-Agent headers.
CONTACT_EMAIL: str = os.environ.get("CONTACT_EMAIL", "")
# OpenReview requires an account even to read public notes.
OPENREVIEW_USERNAME: str = os.environ.get("OPENREVIEW_USERNAME", "")
OPENREVIEW_PASSWORD: str = os.environ.get("OPENREVIEW_PASSWORD", "")

ARXIV_MAX_RESULTS: int = 100      # hard cap per search query
ARXIV_TOP_K: int = 20             # papers forwarded to review pipeline

# A paper must score within this margin of the best-scoring paper (cosine
# similarity to the topic) to be forwarded to review. Relative rather than
# absolute because embedding models compress scores differently: with
# nomic-embed-text, every paper in a 2026-09-12 test set scored >= 0.405, so an
# absolute 0.35 floor removed nothing, while relevant papers (0.681-0.758) and
# the best off-topic one (0.601) were cleanly separated relative to the top.
RELEVANCE_MARGIN: float = float(os.environ.get("RELEVANCE_MARGIN", "0.10"))

# ---------------------------------------------------------------------------
# Canon seeding (Semantic Scholar) — see tools/semantic_scholar.py
# ---------------------------------------------------------------------------
# Keyword-only arXiv search misses highly-cited foundational papers that
# predate current phrasing trends. This supplements it with a citation-count
# sorted search so canonical prior work is always considered.
CANON_SEED_ENABLED: bool = os.environ.get("CANON_SEED_ENABLED", "1") not in ("0", "false", "False")
CANON_SEED_COUNT: int = int(os.environ.get("CANON_SEED_COUNT", "5"))
CANON_MIN_CITATIONS: int = int(os.environ.get("CANON_MIN_CITATIONS", "20"))
# Without a key, requests share one global pool with every other anonymous
# user and get throttled under load; a free key gives a dedicated 1 request/s:
# https://www.semanticscholar.org/product/api#api-key
SEMANTIC_SCHOLAR_API_KEY: str = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")

# ---------------------------------------------------------------------------
# Cost tracking (USD per 1M tokens, as of 2025)
# ---------------------------------------------------------------------------
# Update these if Anthropic changes pricing.
# USD per 1M tokens. Taken from each provider's own pricing page on
# 2026-09-21; prices change, so a model that is not listed is costed at
# UNKNOWN_TOKEN_COST and the row is marked, rather than silently priced wrong.
TOKEN_COSTS: dict[str, dict[str, float]] = {
    # Anthropic — https://www.anthropic.com/pricing
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-opus-4-6":   {"input": 15.00, "output": 75.00},
    # OpenAI — https://developers.openai.com/api/docs/pricing
    "gpt-6-astra":   {"input": 10.00, "output": 50.00},
    "gpt-5.6-sol":   {"input": 4.00,  "output": 20.00},
    "gpt-5.6-terra": {"input": 2.00,  "output": 12.00},
    "gpt-5.6-luna":  {"input": 0.20,  "output": 1.20},
    "gpt-5.5":       {"input": 5.00,  "output": 30.00},
    "gpt-5":         {"input": 1.25,  "output": 10.00},
    "gpt-4o":        {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":   {"input": 0.15,  "output": 0.60},
    "o1":            {"input": 15.00, "output": 60.00},
    "o3-mini":       {"input": 1.10,  "output": 4.40},
    # Gemini — https://ai.google.dev/gemini-api/docs/pricing
    "gemini-3.8-flash": {"input": 0.75, "output": 3.75},
    "gemini-3.7-flash": {"input": 0.75, "output": 3.75},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-pro":   {"input": 1.25, "output": 10.00},   # prompts up to 200k tokens
}

# What an unlisted model is assumed to cost. Deliberately high: a spending cap
# that guesses low is worse than one that stops early, and the log says which
# rows were priced this way.
UNKNOWN_TOKEN_COST: dict[str, float] = {"input": 5.00, "output": 25.00}

# ---------------------------------------------------------------------------
# Experiment runner (Phase 6)
# ---------------------------------------------------------------------------
# Per-phase subprocess timeouts in seconds. 0 = no timeout (unlimited).
RUNNER_INSTALL_TIMEOUT: int  = int(os.environ.get("RUNNER_INSTALL_TIMEOUT", "300"))
RUNNER_PRETRAIN_TIMEOUT: int = int(os.environ.get("RUNNER_PRETRAIN_TIMEOUT", "0"))   # 0 = unlimited
RUNNER_TRAIN_TIMEOUT: int    = int(os.environ.get("RUNNER_TRAIN_TIMEOUT", "0"))      # 0 = unlimited
RUNNER_EVALUATE_TIMEOUT: int = int(os.environ.get("RUNNER_EVALUATE_TIMEOUT", "1800"))
RUNNER_ANALYSIS_TIMEOUT: int = int(os.environ.get("RUNNER_ANALYSIS_TIMEOUT", "3600"))

# Max auto-fix attempts per script (pretrain.py / train.py)
RUNNER_MAX_FIX_ATTEMPTS: int = int(os.environ.get("RUNNER_MAX_FIX_ATTEMPTS", "3"))

# Whether the runner may pip install a generated requirements.txt. Set
# RUNNER_ALLOW_PIP=0 on any machine where model-written code should not be
# able to fetch and run packages; requirement lines that are URLs, paths or
# pip options are refused either way (agents/experiment_runner.py).
RUNNER_ALLOW_PIP: bool = os.environ.get("RUNNER_ALLOW_PIP", "1") not in ("0", "false", "False")

# Whether this copy is serving other people over the internet. It changes
# nothing about how research is done; it decides what the server is allowed to
# do on their behalf.
HOSTED: bool = os.environ.get("HOSTED", "0") in ("1", "true", "True", "yes")

# Whether the server may execute code that a model wrote. On your own machine
# that is the point of the tool. On a shared server it is remote code execution
# offered to strangers, so it is off by default when HOSTED=1 and has to be
# turned on deliberately, once the runner is isolated from everything else.
ALLOW_CODE_EXECUTION: bool = os.environ.get(
    "ALLOW_CODE_EXECUTION", "0" if HOSTED else "1") in ("1", "true", "True", "yes")

# Hostnames this server answers to, comma separated. Empty means any, which is
# right on a laptop and wrong behind a domain.
ALLOWED_HOSTS: list[str] = [h.strip() for h in
                            os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]

# Python interpreter to use when running experiment subprocesses.
# Defaults to the same interpreter running main.py (i.e. the conda env).
RUNNER_PYTHON: str = os.environ.get("RUNNER_PYTHON", sys.executable)

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
