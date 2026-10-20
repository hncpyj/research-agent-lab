import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { send } from '../../api/client';
import { useAuth } from '../../auth/AuthProvider';
import { useAction } from '../../hooks/useResource';

export default function AccountFlow() {
  const { pathname, search, state } = useLocation();
  const { auth, access, reload } = useAuth();
  const navigate = useNavigate();
  const action = useAction();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [accessToken, setAccessToken] = useState('');
  const [completed, setCompleted] = useState(false);
  const mode = pathname.slice(1);
  const title: Record<string, string> = {login: 'Sign in', signup: 'Create account', 'verify-email': 'Verify email',
    'forgot-password': 'Reset password', 'reset-password': 'Choose a new password'};
  const hasPassword = ['login', 'signup', 'reset-password'].includes(mode);
  const newPassword = ['signup', 'reset-password'].includes(mode);
  const token = new URLSearchParams(search).get('token') || '';
  const submit = () => action.run(async () => {
    if (newPassword && password !== confirm) throw new Error('Passwords do not match.');
    let endpoint = '/api/auth/login', body: unknown = {email, password};
    if (mode === 'signup') endpoint = '/api/auth/signup';
    if (mode === 'forgot-password') { endpoint = '/api/auth/password/forgot'; body = {email}; }
    if (mode === 'reset-password') { endpoint = '/api/auth/password/reset'; body = {token, password}; }
    if (mode === 'verify-email') { endpoint = '/api/auth/verify'; body = {token}; }
    await send(endpoint, body);
    setPassword(''); setConfirm('');
    if (mode === 'signup' || mode === 'forgot-password') { setCompleted(true); return; }
    await reload();
    const destination = typeof state?.from === 'string' && state.from.startsWith('/app') ? state.from : '/app';
    navigate(destination, {replace: true});
  }, 'Check your email for the next step.');
  return <main className="workspace auth-page">
    <Link to="/">ResearchAgentLab</Link><h1>{title[mode] || 'Account'}</h1>
    {access?.locked && !access.signed_in && <form className="panel stack" onSubmit={e => {e.preventDefault(); void action.run(async () => {
      await send('/api/login', {token: accessToken}); setAccessToken(''); await reload();
    }, 'Server access granted.');}}>
      <label>Server access token<input type="password" required value={accessToken} onChange={e => setAccessToken(e.target.value)} /></label>
      <button disabled={action.busy}>Unlock server</button>
    </form>}
    {completed ? <p role="status">Check your email. Delivery depends on the account and server configuration.</p> :
      <form className="panel stack" onSubmit={e => {e.preventDefault(); void submit();}}>
        {['login', 'signup', 'forgot-password'].includes(mode) && <label>Email<input type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)} /></label>}
        {hasPassword && <label>Password<input type="password" required autoComplete={newPassword ? 'new-password' : 'current-password'}
          minLength={newPassword ? auth?.password_policy.min_length || 8 : undefined} maxLength={128}
          value={password} onChange={e => setPassword(e.target.value)} /></label>}
        {newPassword && <><p className="muted">Use {auth?.password_policy.min_length || 8}–128 characters. Avoid common passwords and your email name.</p>
          <label>Confirm password<input type="password" required autoComplete="new-password" value={confirm} onChange={e => setConfirm(e.target.value)} /></label></>}
        {['verify-email', 'reset-password'].includes(mode) && !token && <p role="alert">Open the link from your email.</p>}
        <button disabled={action.busy || (['verify-email', 'reset-password'].includes(mode) && !token)}>{action.busy ? 'Working…' : title[mode]}</button>
      </form>}
    <p role="alert">{action.error}</p><p role="status">{action.message}</p>
    <nav className="actions"><Link to="/login">Sign in</Link><Link to="/signup">Create account</Link><Link to="/forgot-password">Forgot password</Link><Link to="/app">Research</Link></nav>
    {email && <button disabled={action.busy} onClick={() => action.run(() => send('/api/auth/resend-verification', {email}), 'Verification email requested.')}>Resend verification</button>}
  </main>;
}
