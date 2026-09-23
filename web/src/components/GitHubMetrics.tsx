import { useEffect, useState } from 'react';

type Metric = { label: string; value: number | null; link?: string };

export default function GitHubMetrics() {
  const [metrics, setMetrics] = useState<Metric[]>([
    { label: 'GitHub Stars', value: null, link: 'https://github.com/researchagentlab/researchagentlab' },
    { label: 'Forks', value: null },
    { label: 'Contributors', value: null },
    { label: 'Downloads', value: null },
  ]);
  const [status, setStatus] = useState<'loading' | 'available' | 'unavailable'>('loading');

  useEffect(() => {
    fetch('https://api.github.com/repos/researchagentlab/researchagentlab')
      .then(r => r.json())
      .then(data => {
        if (data.stargazers_count !== undefined) {
          setMetrics(prev => prev.map(m => {
            if (m.label === 'GitHub Stars') return { ...m, value: data.stargazers_count };
            if (m.label === 'Forks') return { ...m, value: data.forks_count };
            return m;
          }));
          setStatus('available');
        } else {
          setStatus('unavailable');
        }
      })
      .catch(() => setStatus('unavailable'));
  }, []);

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {metrics.map(m => (
        <div key={m.label} className="p-5 rounded-lg border text-center" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
          {status === 'loading' ? (
            <div className="h-7 w-16 mx-auto mb-1 rounded animate-pulse" style={{ background: 'var(--secondary)' }}/>
          ) : m.value !== null ? (
            m.link ? (
              <a href={m.link} target="_blank" rel="noopener" className="block text-2xl font-display font-medium hover:underline" style={{ color: 'var(--primary)' }}>
                {m.value.toLocaleString()}
              </a>
            ) : (
              <div className="text-2xl font-display font-medium" style={{ color: 'var(--foreground)' }}>{m.value.toLocaleString()}</div>
            )
          ) : (
            <div className="text-sm font-mono" style={{ color: 'var(--muted-foreground)' }}>—</div>
          )}
          <div className="text-xs mt-1" style={{ color: 'var(--muted-foreground)' }}>{m.label}</div>
        </div>
      ))}
    </div>
  );
}
