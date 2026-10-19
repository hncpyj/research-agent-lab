import { Link, useParams } from 'react-router-dom';
import { useState } from 'react';
import AppShell from '../../components/AppShell';

const tabs = ['Sessions', 'Papers', 'Hypotheses', 'Experiments', 'Reports'];

const sessions = [
  { id: 's1', number: 3, topic: 'Hypothesis generation for CoT consistency under perturbation', stage: 'Hypothesis Generation', status: 'Running', date: '21 Sep 2026' },
  { id: 's2', number: 2, topic: 'Literature review and gap analysis', stage: 'Literature Review', status: 'Completed', date: '20 Sep 2026' },
  { id: 's3', number: 1, topic: 'Initial paper collection', stage: 'Report', status: 'Completed', date: '18 Sep 2026' },
];

function Badge({ status }: { status: string }) {
  const c: Record<string, { bg: string; color: string }> = {
    Running: { bg: 'rgba(0,200,168,0.12)', color: 'var(--primary)' },
    Completed: { bg: 'rgba(110,200,122,0.1)', color: '#6ec87a' },
    Failed: { bg: 'rgba(239,68,68,0.1)', color: '#ef4444' },
  };
  const s = c[status] ?? { bg: 'var(--secondary)', color: 'var(--muted-foreground)' };
  return <span className="text-xs px-2 py-0.5 rounded font-mono" style={{ background: s.bg, color: s.color }}>{status}</span>;
}

export default function ProjectView() {
  const { projectId } = useParams();
  const [tab, setTab] = useState('Sessions');

  return (
    <AppShell>
      <div className="p-8 max-w-5xl">
        <div className="flex items-center gap-2 text-xs mb-6" style={{ color: 'var(--muted-foreground)' }}>
          <Link to="/app/projects" style={{ color: 'var(--muted-foreground)' }}>Projects</Link>
          <span>→</span>
          <span style={{ color: 'var(--foreground)' }}>LLM Reasoning Benchmarks</span>
        </div>

        <div className="flex items-start justify-between mb-6">
          <div>
            <h1 className="font-display text-3xl font-light mb-1" style={{ color: 'var(--foreground)' }}>LLM Reasoning Benchmarks</h1>
            <p className="text-sm" style={{ color: 'var(--muted-foreground)' }}>Investigating chain-of-thought consistency across reasoning-focused models.</p>
          </div>
          <Link to={`/app/projects/${projectId}/sessions/new`} className="px-4 py-2.5 rounded text-sm font-medium flex-shrink-0" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
            + New Session
          </Link>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-4 mb-8">
          {[
            { label: 'Sessions', value: '3' },
            { label: 'Papers', value: '47' },
            { label: 'Hypotheses', value: '5' },
            { label: 'Experiments', value: '2' },
          ].map(s => (
            <div key={s.label} className="p-4 rounded-lg border text-center" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <div className="font-display text-2xl font-light" style={{ color: 'var(--foreground)' }}>{s.value}</div>
              <div className="text-xs mt-0.5" style={{ color: 'var(--muted-foreground)' }}>{s.label}</div>
            </div>
          ))}
        </div>

        {/* Tabs */}
        <div className="flex gap-1 border-b mb-6" style={{ borderColor: 'var(--border)' }}>
          {tabs.map(t => (
            <button key={t} onClick={() => setTab(t)} className="px-4 py-2 text-sm border-b-2 -mb-px transition-colors"
              style={{ borderColor: tab === t ? 'var(--primary)' : 'transparent', color: tab === t ? 'var(--foreground)' : 'var(--muted-foreground)' }}>
              {t}
            </button>
          ))}
        </div>

        {tab === 'Sessions' && (
          <div className="flex flex-col gap-3">
            {sessions.map(s => (
              <Link key={s.id} to={`/app/projects/${projectId}/sessions/${s.id}`} className="p-5 rounded-lg border flex items-center justify-between group"
                style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-mono" style={{ color: 'var(--muted-foreground)' }}>Session {s.number}</span>
                    <Badge status={s.status}/>
                  </div>
                  <p className="text-sm font-medium group-hover:underline" style={{ color: 'var(--foreground)' }}>{s.topic}</p>
                  <p className="text-xs mt-1" style={{ color: 'var(--muted-foreground)' }}>{s.stage} · {s.date}</p>
                </div>
                <svg width="14" height="14" fill="currentColor" style={{ color: 'var(--muted-foreground)' }}><path d="M3 7h8M8 4l3 3-3 3"/></svg>
              </Link>
            ))}
          </div>
        )}

        {tab === 'Hypotheses' && (
          <div className="flex flex-col gap-3">
            {[
              { h: 'Chain-of-thought consistency degrades more rapidly than answer accuracy under input perturbation.', status: 'Testing', papers: 5 },
              { h: 'Few-shot prompting with step-by-step examples reduces reasoning variance across model sizes.', status: 'Generated', papers: 3 },
            ].map((h, i) => (
              <div key={i} className="p-5 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div className="flex justify-between gap-4 mb-2">
                  <p className="text-sm" style={{ color: 'var(--foreground)' }}>{h.h}</p>
                  <span className="text-xs px-2 py-0.5 rounded font-mono flex-shrink-0" style={{ background: h.status === 'Testing' ? 'rgba(0,200,168,0.1)' : 'var(--secondary)', color: h.status === 'Testing' ? 'var(--primary)' : 'var(--muted-foreground)' }}>{h.status}</span>
                </div>
                <p className="text-xs" style={{ color: 'var(--muted-foreground)' }}>{h.papers} supporting papers</p>
                <div className="flex gap-2 mt-3">
                  <button className="text-xs px-3 py-1.5 rounded border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>View Evidence</button>
                  <button className="text-xs px-3 py-1.5 rounded border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>Create Experiment</button>
                </div>
              </div>
            ))}
          </div>
        )}

        {(tab === 'Papers' || tab === 'Experiments' || tab === 'Reports') && (
          <p className="text-sm" style={{ color: 'var(--muted-foreground)' }}>
            {tab === 'Papers' ? '47 papers collected.' : tab === 'Experiments' ? '2 experiments.' : '1 report.'} Navigate to the full <Link to="/app/library" style={{ color: 'var(--primary)' }}>Library</Link> for detailed view.
          </p>
        )}
      </div>
    </AppShell>
  );
}
