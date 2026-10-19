import GitHubMetrics from '../../components/GitHubMetrics';
import PublicFooter from '../../components/PublicFooter';
import PublicNav from '../../components/PublicNav';
import { hostedAppUrl } from '../../config';

const repositoryUrl = 'https://github.com/hncpyj/research-agent-lab';

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
        <section className="pt-32 pb-16 px-6 relative overflow-hidden">
          <div className="absolute inset-0 pointer-events-none" style={{ background: 'radial-gradient(ellipse 70% 55% at 50% -5%, rgba(10,170,144,0.12), transparent 70%)' }} />
          <div className="max-w-4xl mx-auto text-center relative">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-mono mb-8 border" style={{ borderColor: 'rgba(10,170,144,0.3)', color: 'var(--primary)', background: 'rgba(10,170,144,0.07)' }}>
              Open source · Hosted beta
            </div>
            <h1 className="font-display text-5xl md:text-7xl font-light leading-[0.98] tracking-tight mb-7" style={{ color: 'var(--foreground)' }}>
              Keep the approved study<br /><em className="not-italic" style={{ color: 'var(--primary)' }}>in control.</em>
            </h1>
            <p className="text-lg md:text-xl leading-relaxed max-w-2xl mx-auto mb-9" style={{ color: 'var(--muted-foreground)' }}>
              ResearchAgentLab is a local-first autonomous research system for testing whether scientific intent survives the path from protocol to code to accepted results.
            </p>
            <div className="flex flex-wrap justify-center gap-3">
              <a href={repositoryUrl} target="_blank" rel="noopener noreferrer" className="px-7 py-3.5 rounded font-semibold text-sm inline-flex items-center gap-2 shadow-sm" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
                <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 .7A11.5 11.5 0 0 0 8.36 23c.58.1.79-.25.79-.56v-2.02c-3.22.7-3.9-1.37-3.9-1.37-.53-1.34-1.29-1.7-1.29-1.7-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.2 1.77 1.2 1.04 1.77 2.71 1.26 3.37.96.1-.75.4-1.26.73-1.55-2.57-.29-5.27-1.29-5.27-5.72 0-1.26.45-2.3 1.19-3.1-.12-.3-.52-1.48.11-3.07 0 0 .97-.31 3.16 1.18a10.9 10.9 0 0 1 5.76 0c2.2-1.49 3.16-1.18 3.16-1.18.63 1.59.23 2.77.11 3.06.74.82 1.19 1.85 1.19 3.11 0 4.45-2.71 5.43-5.29 5.72.42.36.79 1.06.79 2.14v3.18c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .7Z" /></svg>
                View source on GitHub
              </a>
              <a href={hostedAppUrl('/signup')} className="px-6 py-3.5 rounded font-medium text-sm border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)', background: 'var(--card)' }}>Try the hosted beta</a>
            </div>
            <p className="text-xs mt-5" style={{ color: 'var(--muted-foreground)' }}>Read the implementation, evidence record, and local setup first. The hosted beta is optional.</p>
          </div>
          <div className="max-w-5xl mx-auto mt-14 relative">
            <GitHubMetrics />
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
            <div className="grid md:grid-cols-[1fr_auto] gap-8 items-center">
              <div>
                <p className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: 'var(--primary)' }}>Current availability</p>
                <h2 className="font-display text-3xl font-light mb-3" style={{ color: 'var(--foreground)' }}>Try the hosted beta or run it locally.</h2>
                <p className="text-sm leading-relaxed max-w-2xl" style={{ color: 'var(--muted-foreground)' }}>Beta accounts provide an isolated workspace while high-risk execution remains disabled. The source is also available for local, noncommercial use under the PolyForm Noncommercial 1.0.0 license.</p>
              </div>
              <div className="flex flex-col sm:flex-row gap-3">
                <a href={repositoryUrl} target="_blank" rel="noopener noreferrer" className="px-5 py-2.5 rounded text-sm font-semibold text-center" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>Open GitHub repository</a>
                <a href={hostedAppUrl('/signup')} className="px-5 py-2.5 rounded text-sm font-medium text-center border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>Create beta account</a>
              </div>
            </div>
          </div>
        </section>
      </main>
      <PublicFooter />
    </div>
  );
}
