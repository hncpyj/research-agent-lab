import PublicFooter from '../../components/PublicFooter';
import PublicNav from '../../components/PublicNav';

const layers = [
  ['StudyProtocol', 'A structured record of the approved question, hypothesis, variables, constraints, metrics, and analysis plan.'],
  ['Intent Fidelity', 'A blocking comparison between approved scientific intent and the proposed executable specification.'],
  ['Methodology Review', 'A distinct judgment about whether the proposed method can validly test the approved claim.'],
  ['Freeze and hash', 'Immutable identifiers for reviewed artifacts, including protocol, prompts, candidate pools, and analysis code.'],
  ['BuildManifest', 'Binds implementation inputs to the frozen scientific package used for a run.'],
  ['Scientific Conformance', 'Detects semantic mutations at pre-freeze, post-freeze, implementation, and result boundaries.'],
  ['Software QA', 'Checks operational correctness without substituting software tests for scientific review.'],
  ['Result Conformance', 'Rejects outputs that cannot be tied back to the frozen execution package.'],
];

export default function Features() {
  return (
    <div className="public-light min-h-screen">
      <PublicNav />
      <main id="main-content" className="pt-28 pb-20 px-6">
        <div className="max-w-6xl mx-auto">
          <div className="max-w-3xl mb-14">
            <p className="text-xs font-mono uppercase tracking-widest mb-4" style={{ color: 'var(--primary)' }}>Architecture</p>
            <h1 className="font-display text-5xl font-light mb-5" style={{ color: 'var(--foreground)' }}>Controls that remain separate on purpose.</h1>
            <p className="text-lg leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>The system is designed to locate where an approved scientific objective changes—not merely whether the final code runs.</p>
          </div>
          <div className="grid md:grid-cols-2 gap-5 mb-16">
            {layers.map(([title, description], index) => (
              <article key={title} className="p-6 rounded-lg border flex gap-5" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div className="font-mono text-xs mt-1" style={{ color: 'var(--primary)' }}>{String(index + 1).padStart(2, '0')}</div>
                <div>
                  <h2 className="font-display text-xl font-light mb-2" style={{ color: 'var(--foreground)' }}>{title}</h2>
                  <p className="text-sm leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>{description}</p>
                </div>
              </article>
            ))}
          </div>
          <div className="p-8 rounded-lg border" style={{ background: 'var(--muted)', borderColor: 'var(--border)' }}>
            <h2 className="font-display text-2xl font-light mb-3" style={{ color: 'var(--foreground)' }}>What the current evidence does not prove</h2>
            <p className="text-sm leading-relaxed max-w-3xl" style={{ color: 'var(--muted-foreground)' }}>The evaluations do not establish universal safety, correctness across every scientific domain, or secure public multi-user hosting. They test specific control hypotheses and failure modes in the documented apparatus.</p>
          </div>
        </div>
      </main>
      <PublicFooter />
    </div>
  );
}
