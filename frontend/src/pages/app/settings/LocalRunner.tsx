import AppShell from '../../../components/AppShell';

const machine = {
  name: 'macbook-pro-alice',
  os: 'macOS 15.2',
  cpu: 'Apple M3 Pro',
  gpu: 'Apple M3 Pro GPU (18-core)',
  version: '0.4.1',
  lastConnected: 'Just now',
  status: 'Connected',
};

export default function LocalRunner() {
  return (
    <AppShell>
      <div className="p-8 max-w-2xl">
        <h1 className="font-display text-3xl font-light mb-2" style={{ color: 'var(--foreground)' }}>Local Runner</h1>
        <p className="text-sm mb-8" style={{ color: 'var(--muted-foreground)' }}>Run experiments and local AI models on your own hardware.</p>

        {/* Connected machine */}
        <div className="p-6 rounded-lg border mb-6" style={{ background: 'var(--card)', borderColor: 'rgba(0,200,168,0.2)' }}>
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full animate-pulse" style={{ background: 'var(--primary)' }}/>
              <span className="text-sm font-medium" style={{ color: 'var(--foreground)' }}>{machine.name}</span>
            </div>
            <span className="text-xs px-2 py-0.5 rounded font-mono" style={{ background: 'rgba(0,200,168,0.1)', color: 'var(--primary)' }}>{machine.status}</span>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: 'OS', value: machine.os },
              { label: 'CPU', value: machine.cpu },
              { label: 'GPU', value: machine.gpu },
              { label: 'Runner version', value: machine.version },
              { label: 'Last connected', value: machine.lastConnected },
            ].map(m => (
              <div key={m.label} className="p-3 rounded border" style={{ background: 'var(--secondary)', borderColor: 'var(--border)' }}>
                <div className="text-xs" style={{ color: 'var(--muted-foreground)' }}>{m.label}</div>
                <div className="text-sm font-mono mt-0.5" style={{ color: 'var(--foreground)' }}>{m.value}</div>
              </div>
            ))}
          </div>
          <div className="flex gap-2 mt-4">
            <button className="px-4 py-2 rounded text-xs border" style={{ borderColor: 'rgba(239,68,68,0.3)', color: '#ef4444' }}>Disconnect</button>
          </div>
        </div>

        {/* Actions */}
        <div className="p-6 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
          <h2 className="text-sm font-medium mb-4" style={{ color: 'var(--foreground)' }}>Connect Another Runner</h2>
          <div className="flex gap-3 flex-wrap">
            <a href="https://github.com/researchagentlab/researchagentlab" target="_blank" rel="noopener"
              className="px-4 py-2 rounded text-xs border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>
              View source on GitHub
            </a>
            <button className="px-4 py-2 rounded text-xs font-medium" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
              Install Local Runner
            </button>
            <a href="#" className="px-4 py-2 rounded text-xs border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>
              Open Documentation
            </a>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
