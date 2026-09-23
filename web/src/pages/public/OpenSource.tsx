import PublicNav from '../../components/PublicNav';
import GitHubMetrics from '../../components/GitHubMetrics';

export default function OpenSource() {
  return (
    <div className="public-light min-h-screen">
      <PublicNav />
      <div className="pt-28 pb-20 px-6">
        <div className="max-w-4xl mx-auto">
          <div className="mb-14">
            <p className="text-xs font-mono uppercase tracking-widest mb-4" style={{ color: 'var(--primary)' }}>Open Source</p>
            <h1 className="font-display text-5xl font-light mb-4" style={{ color: 'var(--foreground)' }}>ResearchAgentLab is built in the open.</h1>
            <p className="text-lg max-w-2xl mb-8 leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>
              Run the research agent locally, inspect how it works, contribute improvements or build on top of it.
            </p>
            <div className="flex flex-wrap gap-3">
              {[
                { label: 'View repository', href: 'https://github.com/researchagentlab/researchagentlab', primary: true },
                { label: 'Star on GitHub', href: 'https://github.com/researchagentlab/researchagentlab' },
                { label: 'Install', href: '#install' },
                { label: 'Read documentation', href: '#' },
                { label: 'Report an issue', href: 'https://github.com/researchagentlab/researchagentlab/issues' },
                { label: 'Contribute', href: 'https://github.com/researchagentlab/researchagentlab/blob/main/CONTRIBUTING.md' },
              ].map(a => (
                <a key={a.label} href={a.href} target={a.href.startsWith('http') ? '_blank' : undefined} rel="noopener"
                  className="px-5 py-2.5 rounded text-sm font-medium border"
                  style={{ background: a.primary ? 'var(--primary)' : 'var(--card)', color: a.primary ? 'var(--primary-foreground)' : 'var(--foreground)', borderColor: a.primary ? 'transparent' : 'var(--border)' }}>
                  {a.label}
                </a>
              ))}
            </div>
          </div>

          <GitHubMetrics />

          <div id="install" className="mt-16 grid md:grid-cols-2 gap-6">
            <div className="p-8 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <h2 className="font-display text-xl font-light mb-4" style={{ color: 'var(--foreground)' }}>Installation</h2>
              <p className="text-sm mb-4" style={{ color: 'var(--muted-foreground)' }}>
                Installation commands are provided by the product configuration. See the GitHub repository for current install instructions.
              </p>
              <div className="p-4 rounded border font-mono text-xs mb-4" style={{ background: 'var(--muted)', borderColor: 'var(--border)', color: 'var(--muted-foreground)' }}>
                # See documentation for current install commands
              </div>
              <a href="https://github.com/researchagentlab/researchagentlab" target="_blank" rel="noopener"
                className="text-sm px-4 py-2 rounded border inline-block" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>
                Install locally
              </a>
            </div>

            <div className="p-8 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <h2 className="font-display text-xl font-light mb-4" style={{ color: 'var(--foreground)' }}>Contributing</h2>
              <p className="text-sm mb-4" style={{ color: 'var(--muted-foreground)' }}>
                ResearchAgentLab is open to contributions. Report issues, suggest features, or submit pull requests.
              </p>
              <ul className="flex flex-col gap-2 text-sm" style={{ color: 'var(--foreground)' }}>
                {['Report a bug', 'Request a feature', 'Submit a pull request', 'Improve documentation'].map(a => (
                  <li key={a} className="flex items-center gap-2">
                    <span style={{ color: 'var(--primary)' }}>→</span>{a}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Non-blocking nudge for Local Runner users */}
          <div className="mt-10 p-5 rounded-lg border flex items-center justify-between gap-4" style={{ background: 'var(--muted)', borderColor: 'var(--border)' }}>
            <p className="text-sm" style={{ color: 'var(--muted-foreground)' }}>Finding ResearchAgentLab useful? Star the project on GitHub.</p>
            <a href="https://github.com/researchagentlab/researchagentlab" target="_blank" rel="noopener"
              className="flex items-center gap-2 px-4 py-2 rounded text-sm font-medium flex-shrink-0 border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)', background: 'var(--card)' }}>
              <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
              Star on GitHub
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
