import { useEffect, useState } from 'react';

type RepositoryMetrics = {
  stargazers_count: number;
  forks_count: number;
  open_issues_count: number;
};

const repositoryUrl = 'https://github.com/hncpyj/research-agent-lab';

export default function GitHubMetrics() {
  const [metrics, setMetrics] = useState<RepositoryMetrics | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch('https://api.github.com/repos/hncpyj/research-agent-lab', { signal: controller.signal })
      .then(response => {
        if (!response.ok) throw new Error(`GitHub returned ${response.status}`);
        return response.json() as Promise<RepositoryMetrics>;
      })
      .then(setMetrics)
      .catch(error => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setUnavailable(true);
      });
    return () => controller.abort();
  }, []);

  const items = [
    { label: 'GitHub stars', value: metrics?.stargazers_count },
    { label: 'Forks', value: metrics?.forks_count },
    { label: 'Open issues', value: metrics?.open_issues_count },
  ];

  return (
    <div className="grid sm:grid-cols-3 gap-4" aria-label="Public GitHub repository metrics">
      {items.map(item => (
        <a key={item.label} href={repositoryUrl} target="_blank" rel="noopener noreferrer" className="p-5 rounded-lg border text-center hover:-translate-y-0.5 transition-transform" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
          {metrics ? (
            <div className="text-2xl font-display font-medium" style={{ color: 'var(--foreground)' }}>{item.value?.toLocaleString()}</div>
          ) : unavailable ? (
            <div className="text-sm font-mono" style={{ color: 'var(--muted-foreground)' }}>Unavailable</div>
          ) : (
            <div className="h-7 w-16 mx-auto rounded animate-pulse" style={{ background: 'var(--secondary)' }} />
          )}
          <div className="text-xs mt-1" style={{ color: 'var(--muted-foreground)' }}>{item.label}</div>
        </a>
      ))}
    </div>
  );
}
