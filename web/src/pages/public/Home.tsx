import { Link } from 'react-router-dom';
import GitHubMetrics from '../../components/GitHubMetrics';
import PublicFooter from '../../components/PublicFooter';
import PublicNav from '../../components/PublicNav';

const boundaryStages = [
  ['01', 'Approved intent', 'Record the research question, hypothesis, variables, constraints, and analysis plan.'],
  ['02', 'Frozen protocol', 'Hash the reviewed specification before generated code can become authoritative.'],
  ['03', 'Constrained build', 'Bind implementation artifacts and candidate pools to the approved design.'],
  ['04', 'Conformance checks', 'Block changes in scientific meaning even when code remains syntactically valid.'],
  ['05', 'Result acceptance', 'Verify outputs against the frozen manifest before accepting a scientific claim.'],
];

const evidence = [
  { value: '42', label: 'Intent-fidelity cases', detail: 'All verdict categories reported; 15 escalated for human review.' },
  { value: '18/18', label: 'Apparatus mutations caught', detail: 'Pre-execution detection on the generator-blind holdout.' },
  { value: '15/18', label: 'Counterfactual escapes', detail: 'Passed the remaining stack when the integrity layer was removed.' },
  { value: '25/25', label: 'Layered regression detections', detail: 'Development regression closure, not independent external validation.' },
];

const controls = [
  ['Intent Fidelity', 'Compares approved intent with the proposed protocol and routes ambiguity to human review.'],
  ['Methodology Review', 'Separates scientific validity from fidelity to the already-approved question.'],
  ['Freeze and BuildManifest', 'Creates a verifiable authority boundary between review and implementation.'],
  ['Scientific Conformance', 'Checks that the implementation still matches the frozen experimental contract.'],
  ['Result Conformance', 'Requires accepted results to trace back to the same frozen artifacts.'],
  ['Local-first execution', 'Keeps the runnable research application on infrastructure controlled by the researcher.'],
];

export default function Home() {
  return (
    <div className="public-light min-h-screen">
      <PublicNav />
      <main id="main-content">
        <section className="pt-32 pb-20 px-6 relative overflow-hidden">
          <div className="absolute inset-0 pointer-events-none" style={{ background: 'radial-gradient(ellipse 70% 55% at 50% -5%, rgba(10,170,144,0.12), transparent 70%)' }} />
          <div className="max-w-4xl mx-auto text-center relative">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-mono mb-8 border" style={{ borderColor: 'rgba(10,170,144,0.3)', color: 'var(--primary)', background: 'rgba(10,170,144,0.07)' }}>
              Research preview · Source available
            </div>
            <h1 className="font-display text-5xl md:text-7xl font-light leading-[0.98] tracking-tight mb-7" style={{ color: 'var(--foreground)' }}>
              Keep the approved study<br /><em className="not-italic" style={{ color: 'var(--primary)' }}>in control.</em>
            </h1>
            <p className="text-lg md:text-xl leading-relaxed max-w-2xl mx-auto mb-9" style={{ color: 'var(--muted-foreground)' }}>
              ResearchAgentLab is a local-first autonomous research system for testing whether scientific intent survives the path from protocol to code to accepted results.
            </p>
            <div className="flex flex-wrap justify-center gap-3">
              <a href="https://github.com/hncpyj/research-agent-lab" target="_blank" rel="noopener noreferrer" className="px-6 py-3 rounded font-medium text-sm" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>View the source</a>
              <Link to="/docs" className="px-6 py-3 rounded font-medium text-sm border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)', background: 'var(--card)' }}>Run locally</Link>
            </div>
            <p className="text-xs mt-5" style={{ color: 'var(--muted-foreground)' }}>No public hosted accounts, uploads, or research execution are offered on this site.</p>
          </div>
        </section>

        <section className="px-6 pb-20">
          <div className="max-w-6xl mx-auto">
            <div className="mb-10 max-w-3xl">
              <p className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: 'var(--primary)' }}>Control boundaries</p>
              <h2 className="font-display text-4xl font-light mb-4" style={{ color: 'var(--foreground)' }}>Protocol before code.</h2>
              <p className="leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>The architecture treats human-approved intent as an authority boundary. Each later artifact must remain traceable to that frozen decision.</p>
            </div>
            <div className="grid md:grid-cols-5 border rounded-lg overflow-hidden" style={{ borderColor: 'var(--border)', background: 'var(--card)' }}>
              {boundaryStages.map(([number, title, description]) => (
                <article key={number} className="p-5 border-b md:border-b-0 md:border-r last:border-0" style={{ borderColor: 'var(--border)' }}>
                  <div className="text-xs font-mono mb-7" style={{ color: 'var(--primary)' }}>{number}</div>
                  <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--foreground)' }}>{title}</h3>
                  <p className="text-xs leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>{description}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="px-6 py-20 border-y" style={{ borderColor: 'var(--border)', background: 'var(--muted)' }}>
          <div className="max-w-6xl mx-auto">
            <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 mb-10">
              <div className="max-w-3xl">
                <p className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: 'var(--primary)' }}>Reported evidence</p>
                <h2 className="font-display text-4xl font-light mb-3" style={{ color: 'var(--foreground)' }}>Auditable results, with their limits visible.</h2>
                <p className="leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>These are internal development and holdout evaluations reported by the project. They are not a claim of universal reliability.</p>
              </div>
              <a href="https://github.com/hncpyj/research-agent-lab#evidence-and-reported-results" target="_blank" rel="noopener noreferrer" className="text-sm font-medium" style={{ color: 'var(--primary)' }}>Read the full evidence record →</a>
            </div>
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {evidence.map(item => (
                <article key={item.label} className="p-6 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                  <div className="font-display text-3xl mb-2" style={{ color: 'var(--primary)' }}>{item.value}</div>
                  <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--foreground)' }}>{item.label}</h3>
                  <p className="text-xs leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>{item.detail}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="px-6 py-20">
          <div className="max-w-6xl mx-auto grid lg:grid-cols-[0.8fr_1.2fr] gap-12 items-start">
            <div>
              <p className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: 'var(--primary)' }}>Independent gates</p>
              <h2 className="font-display text-4xl font-light mb-4" style={{ color: 'var(--foreground)' }}>A valid method can still answer the wrong question.</h2>
              <p className="leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>ResearchAgentLab keeps intent fidelity and methodological validity as separate blocking properties, then adds artifact integrity and result-level checks.</p>
            </div>
            <div className="grid sm:grid-cols-2 gap-4">
              {controls.map(([title, description]) => (
                <article key={title} className="p-5 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                  <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--foreground)' }}>{title}</h3>
                  <p className="text-xs leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>{description}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="px-6 pb-20">
          <div className="max-w-6xl mx-auto p-8 md:p-12 rounded-xl border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
            <div className="grid md:grid-cols-[1fr_auto] gap-8 items-center mb-10">
              <div>
                <p className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: 'var(--primary)' }}>Current availability</p>
                <h2 className="font-display text-3xl font-light mb-3" style={{ color: 'var(--foreground)' }}>Run it on infrastructure you control.</h2>
                <p className="text-sm leading-relaxed max-w-2xl" style={{ color: 'var(--muted-foreground)' }}>The research application is available for local, noncommercial use under the PolyForm Noncommercial 1.0.0 license. This public site is informational only.</p>
              </div>
              <Link to="/docs" className="px-5 py-2.5 rounded text-sm font-medium text-center" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>Installation guide</Link>
            </div>
            <GitHubMetrics />
          </div>
        </section>
      </main>
      <PublicFooter />
    </div>
  );
}
