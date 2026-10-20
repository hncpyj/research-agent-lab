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

All application routes now stay in React. Authentication, projects, session
controls and approval gates, model credentials/settings, local models, reports,
usage and backups call FastAPI. Existing Python HTML is retained for compatibility
but is not used by React. Public account links also stay on the current origin.

`npm run build` includes TypeScript checking. `npm test` runs browser workflow
tests against mocked API responses (Chrome by default; set `PLAYWRIGHT_CHANNEL`
to another installed Playwright-supported channel). `TEST_PREVIEW=1 npm test`
checks the production build after `npm run build`.

Tests do not invoke real model APIs or send email. Backend regression tests
validate database ownership and approval logic separately. Real email delivery,
model availability and deployment ingress must be configured for the target host.

For full application deployment use the Nginx Dockerfile. The optional Vercel
configuration only serves static files; API/WebSocket routing requires an
additional gateway and is not configured by that file.
