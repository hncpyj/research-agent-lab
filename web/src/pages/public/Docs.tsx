import PublicFooter from '../../components/PublicFooter';
import PublicNav from '../../components/PublicNav';

const command = `git clone https://github.com/hncpyj/research-agent-lab.git
cd research-agent-lab
python -m venv .venv
.venv\\Scripts\\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python run_ui.py`;

export default function Docs() {
  return (
    <div className="public-light min-h-screen">
      <PublicNav />
      <main id="main-content" className="pt-28 pb-20 px-6">
        <div className="max-w-4xl mx-auto">
          <p className="text-xs font-mono uppercase tracking-widest mb-4" style={{ color: 'var(--primary)' }}>Run locally</p>
          <h1 className="font-display text-5xl font-light mb-5" style={{ color: 'var(--foreground)' }}>Install on infrastructure you control.</h1>
          <p className="text-lg leading-relaxed max-w-2xl mb-10" style={{ color: 'var(--muted-foreground)' }}>Python 3.12 is recommended. Ollama is optional and is the simplest local-model route. Paid provider use remains subject to each provider's own terms and billing.</p>

          <section className="mb-10" aria-labelledby="quick-start">
            <h2 id="quick-start" className="font-display text-2xl font-light mb-4" style={{ color: 'var(--foreground)' }}>Windows quick start</h2>
            <pre className="p-6 rounded-lg border overflow-x-auto text-xs leading-6" style={{ background: '#0f1117', color: '#d8deea', borderColor: 'var(--border)' }}><code>{command}</code></pre>
            <p className="text-xs mt-3" style={{ color: 'var(--muted-foreground)' }}>The UI binds to loopback by default. The application refuses a non-loopback bind without an explicit UI token.</p>
          </section>

          <div className="grid md:grid-cols-2 gap-5 mb-10">
            <article className="p-6 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <h2 className="font-display text-xl font-light mb-3" style={{ color: 'var(--foreground)' }}>Before using a provider</h2>
              <p className="text-sm leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>Read the provider-specific configuration in the repository. Keep secrets in local environment configuration, never in the public repository or research logs.</p>
            </article>
            <article className="p-6 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <h2 className="font-display text-xl font-light mb-3" style={{ color: 'var(--foreground)' }}>Before running a study</h2>
              <p className="text-sm leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>Review and freeze the scientific package. Smoke, pilot, and confirmatory outputs should remain explicitly separated.</p>
            </article>
          </div>

          <div className="flex flex-wrap gap-3">
            <a href="https://github.com/hncpyj/research-agent-lab#quick-start" target="_blank" rel="noopener noreferrer" className="px-5 py-2.5 rounded text-sm font-medium" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>Full README</a>
            <a href="https://github.com/hncpyj/research-agent-lab/issues" target="_blank" rel="noopener noreferrer" className="px-5 py-2.5 rounded text-sm font-medium border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)', background: 'var(--card)' }}>Report a problem</a>
          </div>
        </div>
      </main>
      <PublicFooter />
    </div>
  );
}
