import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';
import { logout } from '../api/client';
import { useAction } from '../hooks/useResource';

export default function AppShell() {
  const { auth, reload } = useAuth();
  const navigate = useNavigate();
  const action = useAction();
  const links = [['/app', 'Dashboard'], ['/app/projects', 'Projects'], ['/app/library', 'Library'],
    ['/app/usage', 'Usage'], ['/app/settings/account', 'Account'], ['/app/settings/api', 'Models & API keys'],
    ['/app/settings/local-runner', 'Local models'], ['/app/settings/billing', 'Billing'], ['/app/settings/privacy', 'Data & backups']];
  return <div className="app-layout">
    <aside><NavLink to="/">ResearchAgentLab</NavLink><nav>{links.map(([to, label]) =>
      <NavLink key={to} to={to} end={to === '/app'}>{label}</NavLink>)}</nav>
      <p>{auth?.user?.email || 'Local workspace'}</p><small>{auth?.user?.plan || 'Local'}</small>
      <button disabled={action.busy} onClick={() => action.run(async () => {await logout(); await reload(); navigate('/login');}, '')}>Sign out</button>
      <p role="alert">{action.error}</p>
    </aside>
    <main className="workspace"><Outlet /></main>
  </div>;
}
