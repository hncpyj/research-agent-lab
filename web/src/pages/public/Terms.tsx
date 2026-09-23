import PublicFooter from '../../components/PublicFooter';
import PublicNav from '../../components/PublicNav';

export default function Terms() {
  return (
    <div className="public-light min-h-screen">
      <PublicNav />
      <main id="main-content" className="pt-28 pb-20 px-6">
        <article className="max-w-3xl mx-auto">
          <p className="text-xs font-mono uppercase tracking-widest mb-4" style={{ color: 'var(--primary)' }}>Terms</p>
          <h1 className="font-display text-5xl font-light mb-3" style={{ color: 'var(--foreground)' }}>Website and software terms</h1>
          <p className="text-xs mb-10" style={{ color: 'var(--muted-foreground)' }}>Last updated 23 September 2026</p>
          <div className="space-y-8 text-sm leading-7" style={{ color: 'var(--muted-foreground)' }}>
            <section><h2 className="text-base font-medium mb-2" style={{ color: 'var(--foreground)' }}>Website purpose</h2><p>This is an informational research website. It does not offer a hosted research service, account, subscription, or paid plan.</p></section>
            <section><h2 className="text-base font-medium mb-2" style={{ color: 'var(--foreground)' }}>Software license</h2><p>The linked software is source-available under the PolyForm Noncommercial 1.0.0 license. Your use of the software must comply with the complete license text in the repository.</p></section>
            <section><h2 className="text-base font-medium mb-2" style={{ color: 'var(--foreground)' }}>Research responsibility</h2><p>The software is a research system, not a guarantee of scientific validity or safety. You remain responsible for study design, ethics, provider usage, data rights, review, and any conclusions you publish.</p></section>
            <section><h2 className="text-base font-medium mb-2" style={{ color: 'var(--foreground)' }}>No warranty</h2><p>The website and software are provided without warranties or promises of availability. Report technical or reproducibility issues through the public repository.</p></section>
          </div>
        </article>
      </main>
      <PublicFooter />
    </div>
  );
}
