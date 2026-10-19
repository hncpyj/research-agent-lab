import { Link } from 'react-router-dom';
import PublicFooter from '../../components/PublicFooter';
import PublicNav from '../../components/PublicNav';
import { hostedAppUrl } from '../../config';

export default function Pricing() {
  return (
    <div className="public-light min-h-screen">
      <PublicNav />
      <main id="main-content" className="pt-28 pb-20 px-6">
        <div className="max-w-4xl mx-auto">
          <p className="text-xs font-mono uppercase tracking-widest mb-4" style={{ color: 'var(--primary)' }}>Availability</p>
          <h1 className="font-display text-5xl font-light mb-5" style={{ color: 'var(--foreground)' }}>Hosted beta accounts are open.</h1>
          <p className="text-lg leading-relaxed max-w-2xl mb-10" style={{ color: 'var(--muted-foreground)' }}>The beta currently provides account-isolated research workspaces. It does not yet sell usage credits, and provider-backed or generated-code execution remains disabled while those boundaries are hardened.</p>
          <div className="grid md:grid-cols-2 gap-5 mb-10">
            <article className="p-7 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <div className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: 'var(--primary)' }}>Available now</div>
              <h2 className="font-display text-2xl font-light mb-3" style={{ color: 'var(--foreground)' }}>Local execution</h2>
              <p className="text-sm leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>Inspect the source, install the Python application, and run it on infrastructure you control. Ollama is supported as the simplest local model path.</p>
            </article>
            <article className="p-7 rounded-lg border" style={{ background: 'var(--muted)', borderColor: 'var(--border)' }}>
              <div className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: 'var(--primary)' }}>Beta</div>
              <h2 className="font-display text-2xl font-light mb-3" style={{ color: 'var(--foreground)' }}>Hosted workspace</h2>
              <p className="text-sm leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>Create an account and keep sessions separated by owner. Hosted model calls and generated-code execution are not enabled yet.</p>
            </article>
          </div>
          <div className="flex flex-wrap gap-3">
            <a href={hostedAppUrl('/signup')} className="px-5 py-2.5 rounded text-sm font-medium" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>Create beta account</a>
            <Link to="/docs" className="px-5 py-2.5 rounded text-sm font-medium border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)', background: 'var(--card)' }}>Run locally</Link>
          </div>
        </div>
      </main>
      <PublicFooter />
    </div>
  );
}
