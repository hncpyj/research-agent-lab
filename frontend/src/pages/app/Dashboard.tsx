import { Link } from 'react-router-dom';
import { useResource } from '../../hooks/useResource';
import type { SessionSummary } from '../../api/client';

export default function Dashboard() {
  const resource = useResource<{sessions: {total: number; running: number; waiting: number}; spend: {today_usd: number}; waiting_for_you: SessionSummary[]}>('/api/dashboard', 5000);
  const sessions = useResource<{sessions: SessionSummary[]}>('/api/sessions', 5000);
  return <>
    <header><h1>Research dashboard</h1><Link className="button" to="/app/sessions/new">New research</Link></header>
    <p role="alert">{resource.error || sessions.error}</p>
    {resource.loading && <p>Loading…</p>}
    {resource.data && <div className="cards">{Object.entries({
      Sessions: resource.data.sessions.total, Running: resource.data.sessions.running,
      'Waiting for approval': resource.data.sessions.waiting, 'Today (USD)': resource.data.spend.today_usd,
    }).map(([label, value]) => <div className="panel" key={label}><small>{label}</small><h2>{value}</h2></div>)}</div>}
    <h2>Sessions</h2><div className="stack">{sessions.data?.sessions.map(s =>
      <Link className="panel" key={s.session_id} to={`/app/sessions/${s.session_id}`}><strong>{s.topic}</strong>
        <p>{s.is_running ? 'Running · ' : ''}{s.status}{s.interrupted ? ' · Interrupted' : ''}</p></Link>)}
      {sessions.data?.sessions.length === 0 && <p>No sessions yet.</p>}</div>
  </>;
}
