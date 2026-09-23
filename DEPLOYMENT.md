# Putting this online

Two things get deployed, to two different kinds of host, because they are two
different kinds of program.

| | What it is | Where it goes | Domain |
|---|---|---|---|
| `web/` | The public site: what this is, what it costs, where the source is. Static files after a build. | Any static host or CDN (Cloudflare Pages, Netlify, GitHub Pages) | `researchagentlab.com` |
| everything else | The application: FastAPI, the pipeline, the database. Long-lived, stateful, holds websockets open for hours. | A container host with a persistent volume (Railway, Fly, Render, a VPS) | `app.researchagentlab.com` |

## Why they are not merged

The obvious-looking move is to rebuild the working single-page UI
(`ui/static/index.html`) inside the React site so there is "one frontend". That
would throw away the only part of the product that actually runs research — the
gates, the live event stream, the stage controls, the two languages — and
replace it with screens that currently contain invented numbers. There is
nothing a user gains from it.

So the split is by purpose, not by technology:

- The React site stays a **public site**. Its `src/pages/app` and
  `src/pages/auth` screens are design references with made-up figures in them
  (`£4.62 credit`, `4 / 10 used`); `src/App.tsx` deliberately does not route to
  them. `/login`, `/signup` and `/app/*` redirect to the real application at
  `VITE_APP_URL`. A visitor must never be shown a dashboard of invented usage
  as though it were their own.
- The application keeps serving its own UI at `/`. Where the React site's
  design is better, it can be taken into the SPA a panel at a time — that is a
  styling job, not a rewrite.

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
   quietly starts an empty product.
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
   `UI_TOKEN` is the only thing in the way. `ALLOW_SIGNUP` is off by default,
   so sign up as the owner first and set `ALLOW_SIGNUP=1` only when the beta is
   actually open.
7. **The owner's `.env` API key is the owner's.** A member account with no key
   of its own runs on the local model rather than spending the operator's
   credit. Nothing needs configuring for that; it is worth knowing.

## Limits to be honest about

- **One instance only.** State is SQLite on one disk and runs are threads in
  the process. Two instances against one volume will corrupt each other's
  assumptions long before they share work. Scale by making the box bigger, and
  do not turn on the host's autoscaling.
- **A restart ends the runs in flight.** They are recovered on the next start:
  the allowance place is returned, the session is told why it stopped, and the
  page offers to resume (`memory/runs.py`). Deploys are therefore cheap but not
  invisible — a run in progress will need one click to continue.
- **No managed credit.** Every run uses the user's own API key. The pricing
  page says so, and ResearchAgentLab Credits are marked Coming Soon.
- **Local models are not available on a hosted box.** Ollama and GGUF models
  are for the copy someone runs themselves. A hosted run with no usable API key
  therefore has nothing to fall back to and degrades to the data-template path,
  which records itself as a degradation — worth knowing before reading a report
  that came out of it.

## The application

```bash
docker build -t researchagentlab .
docker run -p 8000:8000 -v researchagentlab-data:/data \
  -e HOSTED=1 \
  -e ALLOWED_HOSTS=app.researchagentlab.com \
  -e API_KEY_ENCRYPTION_KEY=... \
  -e UI_TOKEN=... \
  researchagentlab
```

`/health` answers for the host's health check and leaks nothing. The image
carries no data, no `.env` and no model files (`.dockerignore`).

On Railway or Render: point it at this repository, add a volume mounted at
`/data`, set the variables above, and let the platform provide `PORT`.

## The public site

```bash
cd web
pnpm install
VITE_APP_URL=https://app.researchagentlab.com pnpm build   # dist/
```

Deploy `dist/` as static files. The site is a single-page app, so the host
needs the usual rewrite of unknown paths to `index.html`.

`web/AGENTS.md` and `web/CLAUDE.md` came from the tool the site was designed in
and describe that environment, not this repository.

## DNS

| Name | Points at |
|---|---|
| `researchagentlab.com` | the static host |
| `www` | the static host |
| `app` | the container host |

Both need TLS; the application relies on it for the secure cookie flag.
