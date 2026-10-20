# Putting this online

This project deploys FastAPI and the research engine independently of the React
frontend. Its Docker build needs only the contents of this backend directory.

| | What it is | Where it goes | Domain |
|---|---|---|---|
| Backend | FastAPI, research pipeline, SQLite and WebSockets | Container host with persistent storage | Internal API address |
| Frontend (separate project) | React and Nginx | Separate container | Public application domain |

## Connection

Frontend Nginx proxies `/api/` and `/ws/` to this backend. Browser requests use
one origin, but builds and deployments are independent. Backend images contain
no React source or build. The legacy HTML UI remains available on the backend
while React feature migration is completed.

A static host cannot run the application: a research run is a background thread
that lives for hours, writes to SQLite on disk and streams events over a
websocket. Cloudflare Pages, Vercel and the like are not that kind of host.

## Before letting anyone in

These are not preferences; each one is a way for this to go wrong in public.

1. **`ALLOW_CODE_EXECUTION=0`** (the default once `HOSTED=1`). The last phases
   run code a model wrote. On your machine that is the product; on a shared
   server it is remote code execution offered to strangers. The run stops with
   an explanation before anything executes. Turn it on only when the runner has
   its own isolated machine — that work has not been done yet, so hosted runs
   finish at the code and the user runs it themselves.
2. **`DATA_DIR` is a mounted volume.** The database, the backups and the key
   that decrypts stored API keys all live there. Without a volume, every deploy
   quietly starts an empty product. Railway mounts volumes as root, so the
   image entrypoint fixes the mount-point ownership and immediately drops to
   the unprivileged `researcher` user before starting Python.
3. **`API_KEY_ENCRYPTION_KEY` is set in the environment** on any host whose
   disk can be replaced. Lose it and every user has to enter their provider key
   again. Generate one with
   `python -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`.
4. **`ALLOWED_HOSTS` names the domain.** Requests arriving with someone else's
   `Host` header get a 400 instead of an answer.
5. **`FORWARDED_ALLOW_IPS` is as narrow as the host allows.** The client
   address and "was this HTTPS?" are read from proxy headers; the secure flag
   on the sign-in cookie depends on getting that right.
6. **An account exists, and you decide who else may make one.** The first
   account made becomes the owner and adopts the sessions already on the
   machine. Until someone signs up, the server is in local mode and a
   `UI_TOKEN` is the only thing in the way. After the owner exists, remove the
   bootstrap token: normal users authenticate with their own account, never a
   shared token.
7. **Transactional email is configured before signup opens.** Set
   `PUBLIC_APP_URL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`,
   `SMTP_PASSWORD`, `SMTP_FROM`, and `SMTP_STARTTLS`. On Railway Free, Trial,
   or Hobby, set `RESEND_API_KEY` and `SMTP_FROM` instead because outbound SMTP
   is unavailable. New accounts cannot sign
   in until a one-use 24-hour verification link is consumed. Password-reset
   links expire after 30 minutes and invalidate every older login cookie.
   `ALLOW_SIGNUP` stays off if mail is unavailable.
8. **Hosted inference has explicit precedence.** Model API OFF makes no remote
   model call. With it ON, a member's selected BYOK key wins; without BYOK the
   server uses `SHARED_FREE_PROVIDER` / `SHARED_FREE_MODEL`. For the default
   Gemini route, `GEMINI_API_KEY` is required even on Google's free tier. This
   server-side key is never returned to the browser or stored as user BYOK.

## Limits to be honest about

- **One instance only.** State is SQLite on one disk and runs are threads in
  the process. Two instances against one volume will corrupt each other's
  assumptions long before they share work. Scale by making the box bigger, and
  do not turn on the host's autoscaling.
- **A restart ends the runs in flight.** They are recovered on the next start:
  the allowance place is returned, the session is told why it stopped, and the
  page offers to resume (`memory/runs.py`). Deploys are therefore cheap but not
  invisible — a run in progress will need one click to continue.
- **The shared free route has provider quotas, not an SLA.** It never falls
  through to a paid provider. If its quota or authentication fails, the run
  preserves its state and asks the user to retry later or configure BYOK.
- **FreeLLMAPI is not a shared hosted credential pool.** Its upstream security
  model is single-user. RAL accepts it only as a per-user, user-owned gateway;
  hosted URLs must be public HTTPS and explicitly listed in
  `FREELLMAPI_ALLOWED_HOSTS`, and credentials remain encrypted per user.
  See `docs/FREELLMAPI_INTEGRATION.md` before enabling it.
- **Simple Mode is not a shared gateway.** It routes in-process across only the
  signed-in user's encrypted Gemini/Groq keys. No separate FreeLLMAPI service
  is required, and no operator key or other user's key enters its fallback
  chain. Use an exact direct route for frozen or confirmatory work.
- **Local models are not available on a hosted box.** Ollama and GGUF models
  are for the copy someone runs themselves. With Model API OFF, a hosted run
  pauses before the next model-dependent phase. With it ON, a run uses BYOK or
  the configured shared free route; it never silently chooses Anthropic.

## The application

```bash
docker build -t researchagentlab .
docker run -p 8000:8000 -v researchagentlab-data:/data \
  -e HOSTED=1 \
  -e ALLOWED_HOSTS=app.researchagentlab.com \
  -e API_KEY_ENCRYPTION_KEY=... \
  -e GEMINI_API_KEY=... \
  -e SHARED_FREE_PROVIDER=gemini \
  -e SHARED_FREE_MODEL=gemini-3.5-flash-lite \
  -e PUBLIC_APP_URL=https://app.researchagentlab.com \
  -e SMTP_HOST=smtp.example.com \
  -e SMTP_PORT=587 \
  -e SMTP_USERNAME=... \
  -e SMTP_PASSWORD=... \
  -e 'SMTP_FROM=ResearchAgentLab <accounts@researchagentlab.com>' \
  -e SMTP_STARTTLS=1 \
  researchagentlab
```

Keep `UI_TOKEN` only for the first owner bootstrap, then remove it. Set
`ALLOW_SIGNUP=1` only after a real verification email has been received and
the reset flow has been exercised end to end.

`/health` answers for the host's health check and leaks nothing. The image
carries no data, no `.env` and no model files (`.dockerignore`).

On Railway or Render: point it at this repository, add a volume mounted at
`/data`, set the variables above, and let the platform provide `PORT`.

For Railway CLI authentication, use the names Railway recognizes:

- `RAILWAY_API_TOKEN` for an account/workspace token that may create and manage
  projects;
- `RAILWAY_TOKEN` for a token scoped to an existing project.

`RAILWAY_API_KEY` is not a Railway CLI authentication variable. Do not copy a
token into the repository or pass it on a command line.

## Frontend connection

The separate frontend project's Vite server proxies to `127.0.0.1:8000` during
development. Production Nginx uses runtime `BACKEND_URL` to reach this server.
Set frontend `PUBLIC_SCHEME=https` behind HTTPS ingress; configure this backend's
`FORWARDED_ALLOW_IPS` for that trusted proxy. Do not expose the backend port publicly
when using an internal frontend proxy.

## DNS

Point the application domain at the frontend ingress. Keep the backend address
internal. TLS is required for secure authentication cookies and WebSockets.
