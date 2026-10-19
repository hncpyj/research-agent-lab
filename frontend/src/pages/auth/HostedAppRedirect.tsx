import { useEffect } from 'react';
import { hostedAppUrl } from '../../config';

export default function HostedAppRedirect({ path }: { path: '/login' | '/signup' | '/verify-email' | '/forgot-password' | '/reset-password' | '/app' }) {
  const destination = `${hostedAppUrl(path)}${window.location.search}${window.location.hash}`;

  useEffect(() => {
    window.location.replace(destination);
  }, [destination]);

  return (
    <main className="public-light min-h-screen flex items-center justify-center px-6">
      <div className="text-center">
        <div className="w-8 h-8 rounded flex items-center justify-center text-sm font-bold font-mono mx-auto mb-4" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>R</div>
        <h1 className="font-display text-2xl font-light mb-3" style={{ color: 'var(--foreground)' }}>Opening ResearchAgentLab…</h1>
        <p className="text-sm mb-5" style={{ color: 'var(--muted-foreground)' }}>Account credentials are entered only on the application server.</p>
        <a href={destination} className="inline-flex px-5 py-2.5 rounded text-sm font-medium" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>Continue</a>
      </div>
    </main>
  );
}
