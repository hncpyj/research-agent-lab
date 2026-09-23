import AppShell from '../../../components/AppShell';

export default function Account() {
  return (
    <AppShell>
      <div className="p-8 max-w-2xl">
        <h1 className="font-display text-3xl font-light mb-8" style={{ color: 'var(--foreground)' }}>Account</h1>
        <div className="p-6 rounded-lg border mb-6" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
          <div className="flex items-center gap-4 mb-6">
            <div className="w-14 h-14 rounded-full flex items-center justify-center text-xl font-bold" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>A</div>
            <div>
              <div className="font-medium" style={{ color: 'var(--foreground)' }}>alice@uni.ac.uk</div>
              <div className="text-sm" style={{ color: 'var(--muted-foreground)' }}>Free Beta</div>
            </div>
          </div>
          <div className="flex flex-col gap-4">
            {[{ label: 'Email', value: 'alice@uni.ac.uk' }, { label: 'Display name', value: 'Alice' }].map(f => (
              <div key={f.label}>
                <label className="block text-xs mb-1.5" style={{ color: 'var(--muted-foreground)' }}>{f.label}</label>
                <input defaultValue={f.value} className="w-full px-3 py-2.5 rounded border text-sm outline-none" style={{ background: 'var(--secondary)', borderColor: 'var(--border)', color: 'var(--foreground)' }}/>
              </div>
            ))}
            <button className="self-start px-4 py-2 rounded text-sm font-medium" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>Save changes</button>
          </div>
        </div>
        <div className="p-6 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'rgba(239,68,68,0.2)' }}>
          <h2 className="text-sm font-medium mb-2" style={{ color: '#ef4444' }}>Danger zone</h2>
          <p className="text-xs mb-4" style={{ color: 'var(--muted-foreground)' }}>Permanently delete your account and all associated data.</p>
          <button className="px-4 py-2 rounded text-xs border" style={{ borderColor: 'rgba(239,68,68,0.3)', color: '#ef4444' }}>Delete account</button>
        </div>
      </div>
    </AppShell>
  );
}
