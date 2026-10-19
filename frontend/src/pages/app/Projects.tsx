import { Link, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import AppShell from '../../components/AppShell';

const projects = [
  { id: 'p1', name: 'LLM Reasoning Benchmarks', desc: 'Investigating chain-of-thought consistency across reasoning-focused models.', sessions: 3, papers: 47, status: 'Active', updated: '2 hours ago' },
  { id: 'p2', name: 'Protein Folding Under Stress', desc: 'Examining how temperature and pH perturbations affect tertiary structure stability.', sessions: 1, papers: 23, status: 'Active', updated: 'Yesterday' },
  { id: 'p3', name: 'Adversarial Robustness in Vision Transformers', desc: 'Comparative study of adversarial training strategies for ViT architectures.', sessions: 2, papers: 61, status: 'Active', updated: '3 days ago' },
];

export default function Projects() {
  const navigate = useNavigate();
  const [showNew, setShowNew] = useState(false);
  const [topic, setTopic] = useState('');

  return (
    <AppShell>
      <div className="p-8 max-w-4xl">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="font-display text-3xl font-light mb-1" style={{ color: 'var(--foreground)' }}>Projects</h1>
            <p className="text-sm" style={{ color: 'var(--muted-foreground)' }}>3 of 3 active — Free plan limit reached.</p>
          </div>
          <button onClick={() => setShowNew(true)} className="px-4 py-2.5 rounded text-sm font-medium flex items-center gap-2" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
            + New Project
          </button>
        </div>

        {/* Limit banner */}
        <div className="p-4 rounded-lg border mb-6 flex items-center justify-between gap-4" style={{ background: 'rgba(240,160,48,0.07)', borderColor: 'rgba(240,160,48,0.3)' }}>
          <div>
            <p className="text-sm font-medium" style={{ color: 'var(--accent)' }}>You've reached the Free plan project limit.</p>
            <p className="text-xs mt-0.5" style={{ color: 'var(--muted-foreground)' }}>Archive a project or upgrade to create more.</p>
          </div>
          <div className="flex gap-2 flex-shrink-0">
            <Link to="/app/settings/billing" className="text-xs px-3 py-1.5 rounded font-medium" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>Upgrade to Researcher</Link>
            <button className="text-xs px-3 py-1.5 rounded border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>Archive a project</button>
          </div>
        </div>

        <div className="flex flex-col gap-3">
          {projects.map(p => (
            <div key={p.id} className="p-6 rounded-lg border group" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <Link to={`/app/projects/${p.id}`} className="text-base font-medium group-hover:underline" style={{ color: 'var(--foreground)' }}>{p.name}</Link>
                  <p className="text-sm mt-1" style={{ color: 'var(--muted-foreground)' }}>{p.desc}</p>
                  <div className="flex gap-4 mt-3 text-xs" style={{ color: 'var(--muted-foreground)' }}>
                    <span>{p.sessions} sessions</span>
                    <span>{p.papers} papers</span>
                    <span>Updated {p.updated}</span>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Link to={`/app/projects/${p.id}/sessions/new`} className="text-xs px-3 py-1.5 rounded font-medium" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
                    New Session
                  </Link>
                  <button className="text-xs px-3 py-1.5 rounded border" style={{ borderColor: 'var(--border)', color: 'var(--muted-foreground)' }}>···</button>
                </div>
              </div>
            </div>
          ))}
        </div>

        {showNew && (
          <div className="fixed inset-0 flex items-center justify-center z-50 px-6" style={{ background: 'rgba(0,0,0,0.7)' }}>
            <div className="w-full max-w-md p-8 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <h2 className="font-display text-xl font-light mb-4" style={{ color: 'var(--foreground)' }}>New Research Project</h2>
              <p className="text-sm mb-4 p-3 rounded border" style={{ background: 'rgba(240,160,48,0.07)', borderColor: 'rgba(240,160,48,0.3)', color: 'var(--accent)' }}>
                You've reached the Free plan project limit. Archive a project or upgrade to continue.
              </p>
              <div className="flex gap-3">
                <Link to="/app/settings/billing" className="flex-1 py-2.5 rounded text-sm font-medium text-center" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
                  Upgrade to Researcher
                </Link>
                <button onClick={() => setShowNew(false)} className="px-5 py-2.5 rounded text-sm border" style={{ borderColor: 'var(--border)', color: 'var(--muted-foreground)' }}>
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
