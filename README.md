# ResearchAgentLab workspace

Two independent projects, each with its own build context and dependencies:

- `frontend/`: React, TypeScript, Vite; production Nginx serves the build and proxies API/WebSockets.
- `backend/`: FastAPI, research agents, model adapters, SQLite and tests.

Each directory can be copied into its own Git repository and deployed independently.
This workspace retains the existing Git history; no remote repositories are created.

## Development

```sh
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run_ui.py --no-browser
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open `http://localhost:8443/app`. Vite proxies `/api` and `/ws` to port 8000.
For a different backend, set `BACKEND_URL` in the Vite process environment.
The pre-existing workspace `.venv` was preserved; from `backend/` it can temporarily
be used as `../.venv/bin/python` until a backend-local environment is created.

## Deployment

Build and release the projects separately:

```sh
docker build -t research-agent-backend ./backend
docker build -t research-agent-frontend ./frontend
```

The frontend container's `BACKEND_URL` identifies the backend's internal address
(default `http://backend:8000`). The two containers must share a network where
that name resolves. Publish the frontend port; keep backend port 8000 internal.
Frontend deployments do not restart backend research jobs.

Configure TLS at the ingress and set frontend `PUBLIC_SCHEME=https` when the
public endpoint is HTTPS (default `http` is for local use). Configure backend
`ALLOWED_HOSTS` to the browser-facing hostname and `FORWARDED_ALLOW_IPS` to trusted
proxy addresses. Keep `/data` on a persistent backend volume. Set backend secrets
and account bootstrap settings following `backend/DEPLOYMENT.md`.

Local `.env`, `data/`, and `experiments/` moved into `backend/`; their contents
were preserved. Absolute paths in existing local settings or artifacts may need
updating if they refer to the old workspace location.

## Migration status

React provides authentication, projects, library, usage, account/model settings,
session controls, research approvals, artifacts and report downloads. Public
account links stay on the frontend. The backend's legacy HTML is retained for
compatibility, but no React route redirects to it.

Browser workflow tests live in `frontend/tests/`; backend regression tests live
in `backend/tests/`. No real model inference or email delivery is performed by
the browser test suite.
