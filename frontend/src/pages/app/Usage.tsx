import AppShell from '../../components/AppShell';

const metrics = [
  { label: 'Hosted research runs', value: '4', max: '10', sub: '6 remaining this period' },
  { label: 'Runs using your API key', value: '2', max: null, sub: 'This period' },
  { label: 'Runs using ResearchAgentLab Credits', value: '0', max: null, sub: 'Coming soon' },
  { label: 'ResearchAgentLab Credits used', value: '£0.00', max: null, sub: 'Coming soon' },
  { label: 'Active projects', value: '3', max: '3', sub: 'Free Beta limit reached' },
  { label: 'Paper records', value: '131', max: null, sub: 'Across all projects' },
  { label: 'Local Runner executions', value: '5', max: null, sub: 'All time' },
];

const history = [
  { period: 'Sep 2026', runs: 4, spend: '£2.76' },
  { period: 'Aug 2026', runs: 7, spend: '£4.12' },
  { period: 'Jul 2026', runs: 3, spend: '£1.88' },
];

export default function Usage() {
  return (
    <AppShell>
      <div className="p-8 max-w-4xl">
        <div className="mb-8">
          <h1 className="font-display text-3xl font-light mb-1" style={{ color: 'var(--foreground)' }}>Usage</h1>
          <p className="text-sm" style={{ color: 'var(--muted-foreground)' }}>Current period: 1 Sep – 30 Sep 2026</p>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-10">
          {metrics.map(m => (
            <div key={m.label} className="p-5 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <div className="text-xl font-display font-medium mb-0.5" style={{ color: 'var(--foreground)' }}>
                {m.value}{m.max ? <span className="text-base font-normal" style={{ color: 'var(--muted-foreground)' }}> / {m.max}</span> : ''}
              </div>
              <div className="text-xs font-medium mb-0.5" style={{ color: 'var(--foreground)' }}>{m.label}</div>
              <div className="text-xs" style={{ color: 'var(--muted-foreground)' }}>{m.sub}</div>
              {m.max && (
                <div className="mt-3 h-1 rounded-full overflow-hidden" style={{ background: 'var(--secondary)' }}>
                  <div className="h-full rounded-full" style={{ width: `${(parseInt(m.value) / parseInt(m.max)) * 100}%`, background: parseInt(m.value) >= parseInt(m.max) ? 'var(--accent)' : 'var(--primary)' }}/>
                </div>
              )}
            </div>
          ))}
        </div>

        <div>
          <h2 className="text-sm font-medium mb-4" style={{ color: 'var(--foreground)' }}>Monthly History</h2>
          <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b" style={{ borderColor: 'var(--border)', background: 'var(--card)' }}>
                  <th className="text-left px-5 py-3 text-xs font-medium" style={{ color: 'var(--muted-foreground)' }}>Period</th>
                  <th className="text-left px-5 py-3 text-xs font-medium" style={{ color: 'var(--muted-foreground)' }}>Hosted Runs</th>
                  <th className="text-left px-5 py-3 text-xs font-medium" style={{ color: 'var(--muted-foreground)' }}>ResearchAgentLab Credits</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h, i) => (
                  <tr key={h.period} className={i < history.length - 1 ? 'border-b' : ''} style={{ borderColor: 'var(--border)', background: i === 0 ? 'rgba(0,200,168,0.03)' : 'var(--card)' }}>
                    <td className="px-5 py-3 font-mono text-xs" style={{ color: 'var(--foreground)' }}>{h.period}</td>
                    <td className="px-5 py-3 text-xs" style={{ color: 'var(--foreground)' }}>{h.runs}</td>
                    <td className="px-5 py-3 text-xs" style={{ color: 'var(--foreground)' }}>{h.spend}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
