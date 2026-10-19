import { useNavigate } from 'react-router-dom';
import { useState } from 'react';

type Provider = 'anthropic' | 'openai' | 'gemini';

const providers: { id: Provider; name: string; placeholder: string }[] = [
  { id: 'anthropic', name: 'Anthropic', placeholder: 'sk-ant-api03-...' },
  { id: 'openai', name: 'OpenAI', placeholder: 'sk-proj-...' },
  { id: 'gemini', name: 'Google Gemini', placeholder: 'AIzaSy...' },
];

export default function Onboarding() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<'byok' | 'managed' | null>(null);
  const [provider, setProvider] = useState<Provider>('anthropic');
  const [key, setKey] = useState('');

  const skip = () => navigate('/app');
  const finish = () => navigate('/app');

  return (
    <div className="public-light min-h-screen flex items-center justify-center px-6">
      <div className="w-full max-w-lg">
        <div className="mb-8 text-center">
          <span className="w-8 h-8 rounded flex items-center justify-center text-sm font-bold font-mono mx-auto mb-4" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>R</span>
          <h1 className="font-display text-3xl font-light mb-2" style={{ color: 'var(--foreground)' }}>How would you like to use AI?</h1>
          <p className="text-sm" style={{ color: 'var(--muted-foreground)' }}>You can change this at any time in Settings.</p>
        </div>

        <div className="grid grid-cols-2 gap-4 mb-6">
          {[
            { id: 'byok' as const, label: 'Use my API key', desc: 'Connect OpenAI, Anthropic or Gemini. You pay the provider directly.', badge: '' },
            { id: 'managed' as const, label: 'Use ResearchAgentLab Credits', desc: 'No API key needed.', badge: 'Coming Soon' },
          ].map(opt => (
            <button key={opt.id} onClick={() => setMode(opt.id)}
              className="p-5 rounded-lg border text-left transition-all"
              style={{ background: mode === opt.id ? 'var(--secondary)' : 'var(--card)', borderColor: mode === opt.id ? 'var(--primary)' : 'var(--border)' }}>
              <div className="flex items-center gap-2 mb-2">
                <div className="w-4 h-4 rounded-full border-2 flex items-center justify-center" style={{ borderColor: mode === opt.id ? 'var(--primary)' : 'var(--muted-foreground)' }}>
                  {mode === opt.id && <div className="w-2 h-2 rounded-full" style={{ background: 'var(--primary)' }}/>}
                </div>
                <span className="text-sm font-medium" style={{ color: 'var(--foreground)' }}>{opt.label}</span>
                {opt.badge && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded font-mono" style={{ background: 'var(--secondary)', color: 'var(--muted-foreground)' }}>{opt.badge}</span>
                )}
              </div>
              <p className="text-xs" style={{ color: 'var(--muted-foreground)' }}>{opt.desc}</p>
            </button>
          ))}
        </div>

        {mode === 'byok' && (
          <div className="p-6 rounded-lg border mb-6" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
            <div className="flex gap-2 mb-4">
              {providers.map(p => (
                <button key={p.id} onClick={() => setProvider(p.id)} className="px-3 py-1.5 rounded text-xs font-medium border transition-colors"
                  style={{ background: provider === p.id ? 'var(--primary)' : 'transparent', color: provider === p.id ? 'var(--primary-foreground)' : 'var(--muted-foreground)', borderColor: provider === p.id ? 'transparent' : 'var(--border)' }}>
                  {p.name}
                </button>
              ))}
            </div>
            <input type="password" value={key} onChange={e => setKey(e.target.value)}
              placeholder={providers.find(p => p.id === provider)?.placeholder}
              className="w-full px-3 py-2.5 rounded border text-sm font-mono outline-none"
              style={{ background: 'var(--secondary)', borderColor: 'var(--border)', color: 'var(--foreground)' }}/>
            <p className="text-xs mt-2" style={{ color: 'var(--muted-foreground)' }}>Connect your OpenAI, Anthropic, or Gemini API key. AI usage is billed directly by your provider.</p>
          </div>
        )}

        {mode === 'managed' && (
          <div className="p-6 rounded-lg border mb-6" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
            <p className="text-sm" style={{ color: 'var(--muted-foreground)' }}>ResearchAgentLab Credits are coming soon: no API key required, AI usage covered by your ResearchAgentLab credit balance. Until then, use your own API key.</p>
          </div>
        )}

        {/* Local model */}
        <div className="p-5 rounded-lg border mb-6 opacity-60" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
          <div className="flex items-center justify-between mb-1">
            <span className="text-sm font-medium" style={{ color: 'var(--foreground)' }}>Local Model</span>
            <span className="text-xs px-2 py-0.5 rounded font-mono" style={{ background: 'var(--secondary)', color: 'var(--muted-foreground)' }}>Not available on hosted</span>
          </div>
          <p className="text-xs mb-3" style={{ color: 'var(--muted-foreground)' }}>Local models run through the open-source Local Runner.</p>
          <div className="flex gap-3">
            <a href="https://github.com/researchagentlab/researchagentlab" target="_blank" rel="noopener" className="text-xs px-3 py-1.5 rounded border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>View GitHub</a>
            <button className="text-xs px-3 py-1.5 rounded border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>Install Local Runner</button>
          </div>
        </div>

        <div className="flex gap-3">
          <button onClick={finish} className="flex-1 py-2.5 rounded font-medium text-sm" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
            {mode ? 'Continue' : 'Continue'}
          </button>
          <button onClick={skip} className="px-5 py-2.5 rounded text-sm border" style={{ borderColor: 'var(--border)', color: 'var(--muted-foreground)' }}>
            Skip
          </button>
        </div>
        {!mode && <p className="text-xs text-center mt-3" style={{ color: 'var(--muted-foreground)' }}>You can add an API key later in Settings.</p>}
      </div>
    </div>
  );
}
