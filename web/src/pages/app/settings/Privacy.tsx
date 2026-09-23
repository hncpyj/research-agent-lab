import { useState } from 'react';
import AppShell from '../../../components/AppShell';

function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button onClick={() => onChange(!on)} className="relative w-10 h-5 rounded-full transition-colors flex-shrink-0"
      style={{ background: on ? 'var(--primary)' : 'var(--secondary)', border: `1px solid ${on ? 'var(--primary)' : 'var(--border)'}` }}>
      <span className="absolute top-0.5 rounded-full w-4 h-4 transition-transform" style={{ background: 'white', left: on ? '20px' : '2px' }}/>
    </button>
  );
}

export default function Privacy() {
  const [settings, setSettings] = useState({
    analytics: true,
    telemetry: true,
    anonInteraction: false,
    privateContent: false,
    publicProfile: false,
  });

  const set = (k: keyof typeof settings) => (v: boolean) => setSettings(s => ({ ...s, [k]: v }));

  const items = [
    { key: 'analytics' as const, label: 'Product analytics', desc: 'Help us understand how ResearchAgentLab is used.' },
    { key: 'telemetry' as const, label: 'Anonymous operational telemetry', desc: 'Crash reports and performance data to improve reliability.' },
    { key: 'anonInteraction' as const, label: 'Share anonymised research interaction data', desc: 'Help improve autonomous research systems by contributing anonymised interaction data. Contributors may receive additional research credits.' },
    { key: 'privateContent' as const, label: 'Allow private research content to improve ResearchAgentLab', desc: 'Your private research remains private unless you explicitly choose to share it.' },
    { key: 'publicProfile' as const, label: 'Public research profile', desc: 'Allow others to see your public research profile.' },
  ];

  return (
    <AppShell>
      <div className="p-8 max-w-2xl">
        <h1 className="font-display text-3xl font-light mb-2" style={{ color: 'var(--foreground)' }}>Privacy</h1>
        <p className="text-sm mb-8" style={{ color: 'var(--muted-foreground)' }}>Your private research remains private unless you explicitly choose to share it.</p>

        <div className="flex flex-col gap-4">
          {items.map(item => (
            <div key={item.key} className="p-5 rounded-lg border flex items-start justify-between gap-6" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <div>
                <div className="text-sm font-medium mb-0.5" style={{ color: 'var(--foreground)' }}>{item.label}</div>
                <div className="text-xs" style={{ color: 'var(--muted-foreground)' }}>{item.desc}</div>
              </div>
              <Toggle on={settings[item.key]} onChange={set(item.key)}/>
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
