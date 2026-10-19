import PublicFooter from '../../components/PublicFooter';
import PublicNav from '../../components/PublicNav';

export default function Privacy() {
  return (
    <div className="public-light min-h-screen">
      <PublicNav />
      <main id="main-content" className="pt-28 pb-20 px-6">
        <article className="max-w-3xl mx-auto">
          <p className="text-xs font-mono uppercase tracking-widest mb-4" style={{ color: 'var(--primary)' }}>Privacy</p>
          <h1 className="font-display text-5xl font-light mb-3" style={{ color: 'var(--foreground)' }}>Privacy notice for this website</h1>
          <p className="text-xs mb-10" style={{ color: 'var(--muted-foreground)' }}>Last updated 23 September 2026</p>
          <div className="space-y-8 text-sm leading-7" style={{ color: 'var(--muted-foreground)' }}>
            <section><h2 className="text-base font-medium mb-2" style={{ color: 'var(--foreground)' }}>A static informational site</h2><p>This website does not offer user accounts, paper uploads, API-key storage, or hosted research execution. Do not send confidential research material through this site; there is no upload facility.</p></section>
            <section><h2 className="text-base font-medium mb-2" style={{ color: 'var(--foreground)' }}>Public repository metrics</h2><p>The Source page requests public star, fork, and issue counts directly from the GitHub public API. Your browser contacts GitHub for that request, so GitHub's privacy practices apply.</p></section>
            <section><h2 className="text-base font-medium mb-2" style={{ color: 'var(--foreground)' }}>Hosting records</h2><p>Vercel hosts the static site and may process ordinary delivery and security logs such as IP address, browser information, requested path, and timestamp under its own service policies.</p></section>
            <section><h2 className="text-base font-medium mb-2" style={{ color: 'var(--foreground)' }}>The local application</h2><p>When you install the separate research application, its local files remain under your control. If you configure an external model or data provider, data sent to that provider is governed by the provider's terms and your configuration.</p></section>
          </div>
        </article>
      </main>
      <PublicFooter />
    </div>
  );
}
