const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  });

  const contentType = response.headers.get('content-type') || '';
  const body = contentType.includes('application/json')
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const message = typeof body === 'object' && body?.detail
      ? String(body.detail)
      : `Request failed (${response.status})`;
    throw new ApiError(message, response.status);
  }
  return body as T;
}

export type SessionSummary = {
  session_id: string;
  topic: string;
  status: string;
  created_at?: string;
  updated_at?: string;
  is_running?: boolean;
  interrupted?: boolean;
};

export type SessionDetail = {
  session: SessionSummary & Record<string, unknown>;
  papers: Array<Record<string, unknown>>;
  hypotheses: Array<Record<string, unknown>>;
  runs: Array<Record<string, unknown>>;
  report: Record<string, unknown> | null;
  waiting_step: string | null;
  interrupted: Record<string, unknown> | null;
  cost_usd: number;
};

export async function listSessions() {
  return api<{ sessions: SessionSummary[] }>('/api/sessions');
}

export type AuthUser = { user_id: string; email: string; role: string; plan: string };

export async function login(email: string, password: string) {
  return api<{ status: string; user: AuthUser }>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
}

export async function logout() {
  return api<{ status: string }>('/api/auth/logout', { method: 'POST' });
}

export async function currentUser() {
  return api<{ accounts: boolean; user: AuthUser | null }>('/api/auth/me');
}

export async function getSession(sessionId: string) {
  return api<SessionDetail>(`/api/sessions/${encodeURIComponent(sessionId)}`);
}

export async function getSessionStatus(sessionId: string) {
  return api<{ running: boolean; interrupted: Record<string, unknown> | null }>(
    `/api/sessions/${encodeURIComponent(sessionId)}/status`,
  );
}

export async function createSession(input: {
  topic: string;
  background?: string;
  goals?: string;
  constraints?: string;
  autostart?: boolean;
  project_id?: string;
}) {
  return api<{ session_id: string; topic: string; started: boolean }>('/api/sessions', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export async function stopSession(sessionId: string) {
  return api<{ status: string }>(`/api/sessions/${encodeURIComponent(sessionId)}/stop`, {
    method: 'POST',
  });
}

export async function resumeSession(sessionId: string) {
  return api<{ session_id: string; status: string }>(`/api/sessions/${encodeURIComponent(sessionId)}/resume`, {
    method: 'POST',
  });
}

export function sessionSocketUrl(sessionId: string) {
  const base = API_BASE || window.location.origin;
  const url = new URL(`/ws/${encodeURIComponent(sessionId)}`, base);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}
