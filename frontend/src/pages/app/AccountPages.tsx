import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAction, useResource } from '../../hooks/useResource';
import { send } from '../../api/client';
import { useAuth } from '../../auth/AuthProvider';
import DataView from '../../components/DataView';

export function Usage() {
  const [days, setDays] = useState(30);
  const [offset, setOffset] = useState(0);
  const resource = useResource<Record<string, unknown>>(`/api/account/usage?days=${days}&limit=50&offset=${offset}`);
  return <><h1>Usage</h1><label>Period<select value={days} onChange={e => {setDays(Number(e.target.value)); setOffset(0);}}>
    {[1, 7, 30, 90].map(n => <option key={n} value={n}>{n} days</option>)}</select></label>
    <p role="alert">{resource.error}</p>{resource.loading ? <p>Loading…</p> : <DataView value={resource.data} />}
    <div className="actions"><button disabled={!offset} onClick={() => setOffset(n => Math.max(0, n - 50))}>Previous</button>
      <span>Offset {offset}</span><button onClick={() => setOffset(n => n + 50)}>Next</button></div></>;
}
export function Billing() {
  const resource = useResource('/api/account/billing');
  return <><h1>Billing</h1><p role="alert">{resource.error}</p><DataView value={resource.data} /></>;
}
export function Account() {
  const resource = useResource('/api/account/overview');
  const {auth, reload} = useAuth();
  const action = useAction();
  const [password, setPassword] = useState('');
  const [current, setCurrent] = useState('');
  const [confirm, setConfirm] = useState('');
  return <><h1>Account</h1><p role="alert">{resource.error || action.error}</p><DataView value={resource.data} />
    {auth?.user ? <form className="panel stack" onSubmit={e => {e.preventDefault(); void action.run(async () => {
      if (password !== confirm) throw new Error('Passwords do not match.');
      await send('/api/auth/password/change', {current_password: current, new_password: password});
      setPassword(''); setCurrent(''); setConfirm(''); await reload();
    }, 'Password changed.');}}>
      <label>Current password<input type="password" autoComplete="current-password" required value={current} onChange={e => setCurrent(e.target.value)} /></label>
      <label>New password<input type="password" autoComplete="new-password" required minLength={auth.password_policy.min_length} maxLength={128} value={password} onChange={e => setPassword(e.target.value)} /></label>
      <label>Confirm password<input type="password" autoComplete="new-password" required value={confirm} onChange={e => setConfirm(e.target.value)} /></label>
      <button disabled={action.busy}>Change password</button><p role="status">{action.message}</p>
    </form> : <Link to="/signup">Create an account</Link>}
  </>;
}
export function Privacy() {
  const settings = useResource<{hosted: boolean}>('/api/settings');
  const backups = useResource(settings.data && !settings.data.hosted ? '/api/backups' : null);
  const action = useAction();
  return <><h1>Data & backups</h1><p>Export or remove individual sessions from their detail page. Removed sessions are backed up by the server.</p>
    <p role="alert">{settings.error || backups.error || action.error}</p>
    {settings.data?.hosted ? <p>Hosted backups are managed by the operator.</p> : settings.data && <>
      <button disabled={action.busy} onClick={() => action.run(async () => {await send('/api/backups'); await backups.reload();}, 'Backup created.')}>Create backup</button>
      <p role="status">{action.message}</p><DataView value={backups.data} /></>}
  </>;
}
