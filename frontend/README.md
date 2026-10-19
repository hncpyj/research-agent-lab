# ResearchAgentLab frontend

Independent React/TypeScript project. No Python source or database is required here.

```sh
npm ci
npm run dev
npm run build
```

Development: port 8443, API/WebSocket proxy to `http://127.0.0.1:8000`.
Override the target with the process environment variable `BACKEND_URL`.

Production: build this directory's Dockerfile. Nginx serves React and proxies
`/api/` and `/ws/` to runtime `BACKEND_URL` (default `http://backend:8000`).
Frontend and backend containers deploy independently while browser requests stay
on one origin. Do not set `VITE_API_BASE_URL` for this same-origin setup.
Set `PUBLIC_SCHEME=https` behind a TLS ingress, and configure backend trusted
proxy addresses so authentication cookies receive the Secure flag.

React migration is incomplete; some routes still use `VITE_APP_URL` to open the
legacy application. Configure that address explicitly if using those routes.
