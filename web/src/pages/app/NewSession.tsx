import { useNavigate, useParams } from 'react-router-dom';
import { useState } from 'react';
import AppShell from '../../components/AppShell';

export default function NewSession() {
  const navigate = useNavigate();
  const { projectId } = useParams();
  const [topic, setTopic] = useState('');
  const [bg, setBg] = useState('');
  const [goals, setGoals] = useState('');
  const [constraints, setConstraints] = useState('');
  const [billing, setBilling] = useState<'byok' | 'managed'>('byok');
  const [provider, setProvider] = useState('anthropic');
  const [autonomy, setAutonomy] = useState<'suggest' | 'approval' | 'autonomous'>('approval');

  const start = (e: React.FormEvent) => {
    e.preventDefault();
    navigate(`/app/projects/${projectId}/sessions/s1`);
  };

  return (
    <AppShell>
      <div className="p-8 max-w-2xl">
        <h1 className="font-display text-3xl font-light mb-8" style={{ color: 'var(--foreground)' }}>New Research Session</h1>

        <form onSubmit={start} className="flex flex-col gap-6">
          <div>
            <label className="block text-xs mb-1.5 font-medium" style={{ color: 'var(--foreground)' }}>Research Topic <span style={{ color: 'var(--primary)' }}>*</span></label>
            <input value={topic} onChange={e => setTopic(e.target.value)} required placeholder="e.g. Chain-of-thought consistency under input perturbation"
              className="w-full px-3 py-2.5 rounded border text-sm outline-none"
              style={{ background: 'var(--card)', borderColor: 'var(--border)', color: 'var(--foreground)' }}/>
          </div>

          <div>
            <label className="block text-xs mb-1.5" style={{ color: 'var(--muted-foreground)' }}>Background & Context <span style={{ color: 'var(--muted-foreground)' }}>(optional)</span></label>
            <textarea value={bg} onChange={e => setBg(e.target.value)} rows={3} placeholder="Provide any background context for this research session..."
              className="w-full px-3 py-2.5 rounded border text-sm outline-none resize-none"
              style={{ background: 'var(--card)', borderColor: 'var(--border)', color: 'var(--foreground)' }}/>
          </div>

          <div>
            <label className="block text-xs mb-1.5" style={{ color: 'var(--muted-foreground)' }}>Research Goals <span style={{ color: 'var(--muted-foreground)' }}>(optional)</span></label>
            <textarea value={goals} onChange={e => setGoals(e.target.value)} rows={2}
              className="w-full px-3 py-2.5 rounded border text-sm outline-none resize-none"
              style={{ background: 'var(--card)', borderColor: 'var(--border)', color: 'var(--foreground)' }}/>
          </div>

          <div>
            <label className="block text-xs mb-1.5" style={{ color: 'var(--muted-foreground)' }}>Constraints & Requirements <span style={{ color: 'var(--muted-foreground)' }}>(optional)</span></label>
            <textarea value={constraints} onChange={e => setConstraints(e.target.value)} rows={2}
              className="w-full px-3 py-2.5 rounded border text-sm outline-none resize-none"
              style={{ background: 'var(--card)', borderColor: 'var(--border)', color: 'var(--foreground)' }}/>
          </div>

          {/* AI Billing */}
          <div>
            <label className="block text-xs mb-3 font-medium" style={{ color: 'var(--foreground)' }}>How would you like to use AI?</label>
            <div className="grid grid-cols-2 gap-3 mb-4">
              {[
                { id: 'byok' as const, label: 'Use my API key', desc: 'Connect OpenAI, Anthropic or Gemini. You pay the provider directly.' },
                { id: 'managed' as const, label: 'Use ResearchAgentLab Credits', desc: 'No API key needed. Coming Soon' },
              ].map(o => (
                <button key={o.id} type="button" onClick={() => setBilling(o.id)}
                  className="p-4 rounded-lg border text-left"
                  style={{ background: billing === o.id ? 'var(--secondary)' : 'var(--card)', borderColor: billing === o.id ? 'var(--primary)' : 'var(--border)' }}>
                  <div className="text-sm font-medium mb-0.5" style={{ color: 'var(--foreground)' }}>{o.label}</div>
                  <div className="text-xs" style={{ color: 'var(--muted-foreground)' }}>{o.desc}</div>
                </button>
              ))}
            </div>
            {billing === 'byok' && (
              <div>
                <div className="flex gap-2 mb-2">
                  {['anthropic', 'openai', 'gemini'].map(p => (
                    <button key={p} type="button" onClick={() => setProvider(p)} className="px-3 py-1.5 rounded text-xs border capitalize"
                      style={{ background: provider === p ? 'var(--primary)' : 'transparent', color: provider === p ? 'var(--primary-foreground)' : 'var(--muted-foreground)', borderColor: provider === p ? 'transparent' : 'var(--border)' }}>
                      {p === 'gemini' ? 'Google Gemini' : p === 'openai' ? 'OpenAI' : 'Anthropic'}
                    </button>
                  ))}
                </div>
                <div className="text-xs px-3 py-2 rounded border font-mono" style={{ background: 'rgba(0,200,168,0.05)', borderColor: 'rgba(0,200,168,0.2)', color: 'var(--primary)' }}>
                  {provider === 'anthropic' ? 'Anthropic — Connected' : `${provider} — Not connected`}
                </div>
              </div>
            )}
            {billing === 'managed' && (
              <div className="p-3 rounded border text-xs" style={{ background: 'rgba(240,160,48,0.07)', borderColor: 'rgba(240,160,48,0.3)', color: 'var(--accent)' }}>
                ResearchAgentLab Credits are coming soon. No API key required, with AI usage covered by your ResearchAgentLab credit balance.
              </div>
            )}
          </div>

          {/* Autonomy */}
          <div>
            <label className="block text-xs mb-3 font-medium" style={{ color: 'var(--foreground)' }}>Autonomy Level</label>
            <div className="flex flex-col gap-2">
              {[
                { id: 'suggest' as const, label: 'Suggest Only', desc: 'The agent proposes research actions but does not continue automatically.' },
                { id: 'approval' as const, label: 'Approval Required', desc: 'The agent pauses before important research actions.' },
                { id: 'autonomous' as const, label: 'Autonomous Within Limits', desc: 'The agent continues automatically within the limits you configure.' },
              ].map(o => (
                <button key={o.id} type="button" onClick={() => setAutonomy(o.id)}
                  className="p-4 rounded-lg border text-left flex items-start gap-3"
                  style={{ background: autonomy === o.id ? 'var(--secondary)' : 'var(--card)', borderColor: autonomy === o.id ? 'var(--primary)' : 'var(--border)' }}>
                  <div className="w-4 h-4 rounded-full border-2 mt-0.5 flex-shrink-0 flex items-center justify-center" style={{ borderColor: autonomy === o.id ? 'var(--primary)' : 'var(--muted-foreground)' }}>
                    {autonomy === o.id && <div className="w-2 h-2 rounded-full" style={{ background: 'var(--primary)' }}/>}
                  </div>
                  <div>
                    <div className="text-sm font-medium mb-0.5" style={{ color: 'var(--foreground)' }}>{o.label}</div>
                    <div className="text-xs" style={{ color: 'var(--muted-foreground)' }}>{o.desc}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-3 pt-2">
            <div className="text-xs font-mono px-3 py-1.5 rounded" style={{ background: 'var(--secondary)', color: 'var(--muted-foreground)' }}>
              7 of 10 hosted research runs remaining
            </div>
          </div>

          <button type="submit" className="w-full py-3 rounded font-medium text-sm" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
            Start Research
          </button>
        </form>
      </div>
    </AppShell>
  );
}
