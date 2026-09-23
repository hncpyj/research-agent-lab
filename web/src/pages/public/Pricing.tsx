import { Link } from 'react-router-dom';
import PublicFooter from '../../components/PublicFooter';
import PublicNav from '../../components/PublicNav';

export default function Pricing() {
  return (
    <div className="public-light min-h-screen">
      <PublicNav />
      <main id="main-content" className="pt-28 pb-20 px-6">
        <div className="max-w-4xl mx-auto">
          <p className="text-xs font-mono uppercase tracking-widest mb-4" style={{ color: 'var(--primary)' }}>Availability</p>
          <h1 className="font-display text-5xl font-light mb-5" style={{ color: 'var(--foreground)' }}>No hosted plan is on sale.</h1>
          <p className="text-lg leading-relaxed max-w-2xl mb-10" style={{ color: 'var(--muted-foreground)' }}>ResearchAgentLab is currently a local-first research preview. This website does not provide accounts, accept API keys, upload papers, execute research jobs, or sell usage credits.</p>
          <div className="grid md:grid-cols-2 gap-5 mb-10">
            <article className="p-7 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <div className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: 'var(--primary)' }}>Available now</div>
              <h2 className="font-display text-2xl font-light mb-3" style={{ color: 'var(--foreground)' }}>Local execution</h2>
              <p className="text-sm leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>Inspect the source, install the Python application, and run it on infrastructure you control. Ollama is supported as the simplest local model path.</p>
            </article>
            <article className="p-7 rounded-lg border" style={{ background: 'var(--muted)', borderColor: 'var(--border)' }}>
              <div className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: 'var(--accent)' }}>Not available</div>
              <h2 className="font-display text-2xl font-light mb-3" style={{ color: 'var(--foreground)' }}>Public hosted beta</h2>
              <p className="text-sm leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>Hosted multi-user execution is intentionally not published while its security, isolation, quota, and persistence boundaries remain under engineering review.</p>
            </article>
          </div>
          <div className="flex flex-wrap gap-3">
            <Link to="/docs" className="px-5 py-2.5 rounded text-sm font-medium" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>Run locally</Link>
            <Link to="/source" className="px-5 py-2.5 rounded text-sm font-medium border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)', background: 'var(--card)' }}>License and source</Link>
          </div>
        </div>
      </main>
      <PublicFooter />
    </div>
  );
}
