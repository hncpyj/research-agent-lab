import { Link } from 'react-router-dom';
import AppShell from '../../../components/AppShell';

export default function Billing() {
  return (
    <AppShell>
      <div className="p-8 max-w-2xl">
        <h1 className="font-display text-3xl font-light mb-8" style={{ color: 'var(--foreground)' }}>Billing</h1>

        {/* Current Plan */}
        <section className="p-6 rounded-lg border mb-6" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
          <h2 className="text-sm font-medium mb-4" style={{ color: 'var(--foreground)' }}>Current Plan</h2>
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="font-display text-2xl font-light" style={{ color: 'var(--foreground)' }}>Free Beta</div>
              <div className="text-sm" style={{ color: 'var(--muted-foreground)' }}>£0/month</div>
            </div>
            <Link to="/pricing" className="px-4 py-2 rounded text-sm font-medium border" style={{ borderColor: 'var(--border)', color: 'var(--muted-foreground)' }}>
              Founding Researcher — Coming Soon
            </Link>
          </div>
          <div className="p-3 rounded border" style={{ background: 'var(--secondary)', borderColor: 'var(--border)' }}>
            <div className="flex items-center justify-between text-sm">
              <span style={{ color: 'var(--muted-foreground)' }}>Hosted research runs</span>
              <span style={{ color: 'var(--foreground)' }}>4 / 10 used</span>
            </div>
            <div className="mt-2 h-1 rounded-full overflow-hidden" style={{ background: 'var(--muted)' }}>
              <div className="h-full rounded-full" style={{ width: '40%', background: 'var(--primary)' }}/>
            </div>
          </div>
        </section>

        {/* ResearchAgentLab Credits */}
        <section className="p-6 rounded-lg border mb-6" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
          <h2 className="text-sm font-medium mb-4" style={{ color: 'var(--foreground)' }}>ResearchAgentLab Credits</h2>
          <div className="grid grid-cols-3 gap-4 mb-4">
            {[
              { label: 'Included monthly', value: '£9.00' },
              { label: 'Used', value: '£4.38' },
              { label: 'Remaining', value: '£4.62' },
            ].map(m => (
              <div key={m.label} className="p-4 rounded border" style={{ background: 'var(--secondary)', borderColor: 'var(--border)' }}>
                <div className="font-display text-xl font-medium" style={{ color: 'var(--foreground)' }}>{m.value}</div>
                <div className="text-xs mt-0.5" style={{ color: 'var(--muted-foreground)' }}>{m.label}</div>
              </div>
            ))}
          </div>
          <p className="text-xs mb-4" style={{ color: 'var(--muted-foreground)' }}>No API key required. AI usage is covered by your ResearchAgentLab credit balance. Coming soon — today every run uses your own API key.</p>
          <div className="flex gap-2 flex-wrap">
            {['Add £5', 'Add £10', 'Add £25'].map(a => (
              <button key={a} className="px-4 py-2 rounded text-sm border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>{a}</button>
            ))}
          </div>
        </section>

        {/* Invoices */}
        <section className="p-6 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
          <h2 className="text-sm font-medium mb-4" style={{ color: 'var(--foreground)' }}>Invoices</h2>
          <p className="text-sm" style={{ color: 'var(--muted-foreground)' }}>No invoices yet.</p>
        </section>
      </div>
    </AppShell>
  );
}
