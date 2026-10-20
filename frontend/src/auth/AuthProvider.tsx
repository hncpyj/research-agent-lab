import { createContext, useContext, useEffect, type ReactNode } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useResource } from '../hooks/useResource';
import type { AuthState } from '../api/client';

type State = { auth: AuthState | null; access: {locked: boolean; signed_in: boolean} | null; loading: boolean; error: string; reload: () => Promise<void> };
const Context = createContext<State | null>(null);
export function AuthProvider({ children }: { children: ReactNode }) {
  const auth = useResource<AuthState>('/api/auth/me');
  const access = useResource<State['access']>('/api/access/state');
  useEffect(() => {
    const refresh = () => {void auth.reload(); void access.reload();};
    window.addEventListener('auth-expired', refresh);
    return () => window.removeEventListener('auth-expired', refresh);
  }, [auth.reload, access.reload]);
  return <Context.Provider value={{auth: auth.data, access: access.data, loading: auth.loading || access.loading,
    error: auth.error || access.error, reload: async () => { await Promise.all([auth.reload(), access.reload()]); }}}>
    {children}
  </Context.Provider>;
}
export const useAuth = () => {
  const value = useContext(Context);
  if (!value) throw new Error('AuthProvider required');
  return value;
};
export function ProtectedRoute() {
  const state = useAuth();
  const location = useLocation();
  if (state.loading) return <main className="workspace">Connecting…</main>;
  if (state.error) return <main className="workspace"><p role="alert">{state.error}</p><button onClick={state.reload}>Retry connection</button></main>;
  if ((state.auth?.accounts && !state.auth.user) || (state.access?.locked && !state.access.signed_in)) {
    return <Navigate to="/login" state={{from: location.pathname}} replace />;
  }
  return <Outlet />;
}
