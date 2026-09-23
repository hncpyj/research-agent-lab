import { useState } from 'react';
import AppShell from '../../../components/AppShell';

type ProviderState = 'Connected' | 'Not Connected' | 'Invalid';

const initialProviders: { id: string; name: string; status: ProviderState; maskedKey?: string }[] = [
  { id: 'anthropic', name: 'Anthropic', status: 'Connected', maskedKey: 'demo-key-••••4932' },
  { id: 'openai', name: 'OpenAI', status: 'Not Connected' },
  { id: 'gemini', name: 'Google Gemini', status: 'Not Connected' },
];

const STATUS_STYLE: Record<ProviderState, { color: string; bg: string }> = {
  Connected: { color: '#6ec87a', bg: 'rgba(110,200,122,0.1)' },
  'Not Connected': { color: 'var(--muted-foreground)', bg: 'var(--secondary)' },
  Invalid: { color: '#ef4444', bg: 'rgba(239,68,68,0.1)' },
};

export default function ApiProviders() {
  const [providers, setProviders] = useState(initialProviders);
  const [adding, setAdding] = useState<string | null>(null);
  const [keyInput, setKeyInput] = useState('');

  const save = (id: string) => {
    if (!keyInput.trim()) return;
    setProviders(prev => prev.map(p => p.id === id ? { ...p, status: 'Connected', maskedKey: keyInput.slice(0, 8) + '••••••••' + keyInput.slice(-4) } : p));
    setAdding(null);
    setKeyInput('');
  };

  const remove = (id: string) => {
    setProviders(prev => prev.map(p => p.id === id ? { ...p, status: 'Not Connected', maskedKey: undefined } : p));
  };

  return (
    <AppShell>
      <div className="p-8 max-w-2xl">
        <h1 className="font-display text-3xl font-light mb-2" style={{ color: 'var(--foreground)' }}>API Providers</h1>
        <p className="text-sm mb-8" style={{ color: 'var(--muted-foreground)' }}>Your API usage is billed directly by the provider when you use your own key.</p>

        <div className="flex flex-col gap-4">
          {providers.map(p => {
            const s = STATUS_STYLE[p.status];
            return (
              <div key={p.id} className="p-6 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div className="flex items-center justify-between mb-3">
                  <span className="font-medium text-sm" style={{ color: 'var(--foreground)' }}>{p.name}</span>
                  <span className="text-xs px-2 py-0.5 rounded font-mono" style={{ background: s.bg, color: s.color }}>{p.status}</span>
                </div>
                {p.maskedKey && (
                  <div className="font-mono text-xs mb-4 p-2 rounded border" style={{ background: 'var(--secondary)', borderColor: 'var(--border)', color: 'var(--muted-foreground)' }}>
                    {p.maskedKey}
                  </div>
                )}
                {adding === p.id ? (
                  <div>
                    <input value={keyInput} onChange={e => setKeyInput(e.target.value)} placeholder="Paste your API key..."
                      type="password" className="w-full px-3 py-2 rounded border text-sm font-mono outline-none mb-3"
                      style={{ background: 'var(--secondary)', borderColor: 'var(--border)', color: 'var(--foreground)' }}/>
                    <div className="flex gap-2">
                      <button onClick={() => save(p.id)} className="px-4 py-1.5 rounded text-xs font-medium" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>Save</button>
                      <button onClick={() => { setAdding(null); setKeyInput(''); }} className="px-4 py-1.5 rounded text-xs border" style={{ borderColor: 'var(--border)', color: 'var(--muted-foreground)' }}>Cancel</button>
                    </div>
                  </div>
                ) : (
                  <div className="flex gap-2">
                    {p.status === 'Connected' ? (
                      <>
                        <button className="px-3 py-1.5 rounded text-xs border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>Test Connection</button>
                        <button onClick={() => setAdding(p.id)} className="px-3 py-1.5 rounded text-xs border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>Replace Key</button>
                        <button onClick={() => remove(p.id)} className="px-3 py-1.5 rounded text-xs border" style={{ borderColor: 'rgba(239,68,68,0.3)', color: '#ef4444' }}>Remove Key</button>
                      </>
                    ) : (
                      <button onClick={() => setAdding(p.id)} className="px-3 py-1.5 rounded text-xs font-medium" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>Add Key</button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </AppShell>
  );
}
