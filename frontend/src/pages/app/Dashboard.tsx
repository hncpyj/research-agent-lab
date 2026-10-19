import { Link } from 'react-router-dom';
import AppShell from '../../components/AppShell';
import { useEffect, useState } from 'react';
import { listSessions, type SessionSummary } from '../../api/client';

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, { bg: string; color: string }> = {
    Running: { bg: 'rgba(0,200,168,0.12)', color: 'var(--primary)' },
    Completed: { bg: 'rgba(100,200,100,0.1)', color: '#6ec87a' },
    Failed: { bg: 'rgba(239,68,68,0.1)', color: '#ef4444' },
    Queued: { bg: 'rgba(240,160,48,0.1)', color: 'var(--accent)' },
  };
  const c = colors[status] ?? { bg: 'var(--secondary)', color: 'var(--muted-foreground)' };
  return (
    <span className="text-xs px-2 py-0.5 rounded font-mono" style={{ background: c.bg, color: c.color }}>{status}</span>
  );
}

export default function Dashboard() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    listSessions()
      .then((data) => setSessions(data.sessions))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const recentSessions = sessions.slice(0, 6);
  const running = sessions.filter((session) => session.is_running).length;

  return (
    <AppShell>
      <div className="p-8 max-w-5xl">
        <div className="flex items-start justify-between mb-8">
          <div>
            <h1 className="font-display text-3xl font-light mb-1" style={{ color: 'var(--foreground)' }}>Research dashboard</h1>
            <p className="text-sm" style={{ color: 'var(--muted-foreground)' }}>Your research sessions and current runs.</p>
          </div>
          <Link to="/app/sessions/new" className="px-4 py-2.5 rounded text-sm font-medium flex items-center gap-2" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor"><path d="M7 1a.75.75 0 01.75.75V6.25h4.5a.75.75 0 010 1.5h-4.5v4.5a.75.75 0 01-1.5 0v-4.5H1.75a.75.75 0 010-1.5h4.5V1.75A.75.75 0 017 1z"/></svg>
            New Research Session
          </Link>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          {[
            { label: 'Total sessions', value: String(sessions.length), sub: 'stored sessions' },
            { label: 'Running now', value: String(running), sub: 'active pipelines', primary: running > 0 },
            { label: 'Waiting for input', value: String(sessions.filter((s) => s.status === 'waiting').length), sub: 'needs your decision' },
            { label: 'Backend', value: 'Connected', sub: 'FastAPI', primary: true },
          ].map(s => (
            <div key={s.label} className="p-5 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <div className="text-lg font-display font-medium mb-0.5" style={{ color: s.primary ? 'var(--primary)' : 'var(--foreground)' }}>{s.value}</div>
              <div className="text-xs mb-0.5" style={{ color: 'var(--muted-foreground)' }}>{s.label}</div>
              <div className="text-xs" style={{ color: 'var(--muted-foreground)' }}>{s.sub}</div>
            </div>
          ))}
        </div>

        <div className="grid md:grid-cols-2 gap-6">
          {/* Recent Sessions */}
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-medium" style={{ color: 'var(--foreground)' }}>Recent sessions</h2>
              <Link to="/app/sessions/new" className="text-xs" style={{ color: 'var(--primary)' }}>New session →</Link>
            </div>
            {loading && <div className="text-sm" style={{ color: 'var(--muted-foreground)' }}>Loading sessions…</div>}
            {error && <div className="text-sm" style={{ color: '#ef4444' }}>{error}</div>}
            {!loading && !error && recentSessions.length === 0 && <div className="text-sm" style={{ color: 'var(--muted-foreground)' }}>No sessions yet. Start your first research session.</div>}
            <div className="flex flex-col gap-2">
              {recentSessions.slice(0, 3).map((session) => (
                <Link key={session.session_id} to={`/app/sessions/${session.session_id}`} className="p-4 rounded-lg border flex items-center justify-between transition-colors group"
                  style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                  <div>
                    <div className="text-sm font-medium group-hover:underline" style={{ color: 'var(--foreground)' }}>{session.topic}</div>
                    <div className="text-xs mt-0.5" style={{ color: 'var(--muted-foreground)' }}>{session.status} · {session.updated_at || session.created_at || '—'}</div>
                  </div>
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor" style={{ color: 'var(--muted-foreground)' }}><path d="M3 7h8M8 4l3 3-3 3"/></svg>
                </Link>
              ))}
            </div>
          </div>

          {/* Pipeline summary */}
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-medium" style={{ color: 'var(--foreground)' }}>How it works</h2>
            </div>
            <div className="p-5 rounded-lg border text-sm" style={{ background: 'var(--card)', borderColor: 'var(--border)', color: 'var(--muted-foreground)' }}>
              <p>Research sessions run through paper collection, literature review, gap analysis, hypothesis generation, experiment execution, and reporting.</p>
              <p className="mt-3">The React interface controls the workflow; FastAPI runs the research agents and stores the results.</p>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
