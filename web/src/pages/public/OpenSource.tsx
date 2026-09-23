import GitHubMetrics from '../../components/GitHubMetrics';
import PublicFooter from '../../components/PublicFooter';
import PublicNav from '../../components/PublicNav';

export default function OpenSource() {
  return (
    <div className="public-light min-h-screen">
      <PublicNav />
      <main id="main-content" className="pt-28 pb-20 px-6">
        <div className="max-w-4xl mx-auto">
          <p className="text-xs font-mono uppercase tracking-widest mb-4" style={{ color: 'var(--primary)' }}>Source available</p>
          <h1 className="font-display text-5xl font-light mb-5" style={{ color: 'var(--foreground)' }}>Inspect the complete research system.</h1>
          <p className="text-lg max-w-2xl mb-8 leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>The public repository includes the implementation, evaluation artifacts, run records, and documentation needed to examine how the controls work.</p>
          <div className="flex flex-wrap gap-3 mb-12">
            <a href="https://github.com/hncpyj/research-agent-lab" target="_blank" rel="noopener noreferrer" className="px-5 py-2.5 rounded text-sm font-medium" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>View repository</a>
            <a href="https://github.com/hncpyj/research-agent-lab/issues" target="_blank" rel="noopener noreferrer" className="px-5 py-2.5 rounded text-sm font-medium border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)', background: 'var(--card)' }}>Report an issue</a>
          </div>
          <GitHubMetrics />
          <div className="mt-12 grid md:grid-cols-2 gap-5">
            <article className="p-7 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <h2 className="font-display text-2xl font-light mb-3" style={{ color: 'var(--foreground)' }}>License</h2>
              <p className="text-sm leading-relaxed mb-4" style={{ color: 'var(--muted-foreground)' }}>The repository uses the PolyForm Noncommercial 1.0.0 license. It permits noncommercial use subject to the license terms; it is source-available, not OSI-approved open source.</p>
              <a href="https://github.com/hncpyj/research-agent-lab/blob/main/LICENSE" target="_blank" rel="noopener noreferrer" className="text-sm font-medium" style={{ color: 'var(--primary)' }}>Read the license →</a>
            </article>
            <article className="p-7 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <h2 className="font-display text-2xl font-light mb-3" style={{ color: 'var(--foreground)' }}>Contributing</h2>
              <p className="text-sm leading-relaxed mb-4" style={{ color: 'var(--muted-foreground)' }}>Use the repository issue tracker to report reproducibility problems, documentation gaps, or implementation defects. Pull requests can be proposed against the public repository.</p>
              <a href="https://github.com/hncpyj/research-agent-lab/issues" target="_blank" rel="noopener noreferrer" className="text-sm font-medium" style={{ color: 'var(--primary)' }}>Open the issue tracker →</a>
            </article>
          </div>
        </div>
      </main>
      <PublicFooter />
    </div>
  );
}
