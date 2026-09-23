import { Link } from 'react-router-dom';
import AppShell from '../../components/AppShell';

const recentProjects = [
  { id: 'p1', name: 'LLM Reasoning Benchmarks', sessions: 3, updated: '2 hours ago' },
  { id: 'p2', name: 'Protein Folding Under Stress', sessions: 1, updated: 'Yesterday' },
  { id: 'p3', name: 'Adversarial Robustness in Vision Transformers', sessions: 2, updated: '3 days ago' },
];

const recentSessions = [
  { id: 's1', project: 'LLM Reasoning Benchmarks', stage: 'Hypothesis Generation', status: 'Running', started: '2 hours ago' },
  { id: 's2', project: 'LLM Reasoning Benchmarks', stage: 'Literature Review', status: 'Completed', started: 'Yesterday' },
  { id: 's3', project: 'Protein Folding Under Stress', stage: 'Report', status: 'Completed', started: '3 days ago' },
];

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
  return (
    <AppShell>
      <div className="p-8 max-w-5xl">
        <div className="flex items-start justify-between mb-8">
          <div>
            <h1 className="font-display text-3xl font-light mb-1" style={{ color: 'var(--foreground)' }}>Good afternoon, Alice.</h1>
            <p className="text-sm" style={{ color: 'var(--muted-foreground)' }}>21 September 2026</p>
          </div>
          <Link to="/app/projects" className="px-4 py-2.5 rounded text-sm font-medium flex items-center gap-2" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor"><path d="M7 1a.75.75 0 01.75.75V6.25h4.5a.75.75 0 010 1.5h-4.5v4.5a.75.75 0 01-1.5 0v-4.5H1.75a.75.75 0 010-1.5h4.5V1.75A.75.75 0 017 1z"/></svg>
            New Research Session
          </Link>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          {[
            { label: 'Hosted runs this month', value: '4 / 10', sub: '6 remaining' },
            { label: 'ResearchAgentLab Credits', value: '—', sub: 'coming soon' },
            { label: 'Active projects', value: '3 / 3', sub: 'Free Beta limit' },
            { label: 'Local Runner', value: 'Connected', sub: 'macbook-pro-alice', primary: true },
          ].map(s => (
            <div key={s.label} className="p-5 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <div className="text-lg font-display font-medium mb-0.5" style={{ color: s.primary ? 'var(--primary)' : 'var(--foreground)' }}>{s.value}</div>
              <div className="text-xs mb-0.5" style={{ color: 'var(--muted-foreground)' }}>{s.label}</div>
              <div className="text-xs" style={{ color: 'var(--muted-foreground)' }}>{s.sub}</div>
            </div>
          ))}
        </div>

        <div className="grid md:grid-cols-2 gap-6">
          {/* Recent Projects */}
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-medium" style={{ color: 'var(--foreground)' }}>Recent Projects</h2>
              <Link to="/app/projects" className="text-xs" style={{ color: 'var(--primary)' }}>View all →</Link>
            </div>
            <div className="flex flex-col gap-2">
              {recentProjects.map(p => (
                <Link key={p.id} to={`/app/projects/${p.id}`} className="p-4 rounded-lg border flex items-center justify-between transition-colors group"
                  style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                  <div>
                    <div className="text-sm font-medium group-hover:underline" style={{ color: 'var(--foreground)' }}>{p.name}</div>
                    <div className="text-xs mt-0.5" style={{ color: 'var(--muted-foreground)' }}>{p.sessions} session{p.sessions !== 1 ? 's' : ''} · {p.updated}</div>
                  </div>
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor" style={{ color: 'var(--muted-foreground)' }}><path d="M3 7h8M8 4l3 3-3 3"/></svg>
                </Link>
              ))}
            </div>
          </div>

          {/* Recent Sessions */}
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-medium" style={{ color: 'var(--foreground)' }}>Recent Sessions</h2>
            </div>
            <div className="flex flex-col gap-2">
              {recentSessions.map(s => (
                <Link key={s.id} to={`/app/projects/p1/sessions/${s.id}`} className="p-4 rounded-lg border flex items-start justify-between transition-colors group"
                  style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                  <div>
                    <div className="text-sm font-medium group-hover:underline" style={{ color: 'var(--foreground)' }}>{s.project}</div>
                    <div className="text-xs mt-0.5" style={{ color: 'var(--muted-foreground)' }}>{s.stage} · {s.started}</div>
                  </div>
                  <StatusBadge status={s.status}/>
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
