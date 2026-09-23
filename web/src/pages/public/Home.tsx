import { Link } from 'react-router-dom';
import PublicNav from '../../components/PublicNav';
import GitHubMetrics from '../../components/GitHubMetrics';

const stages = [
  { n: '01', label: 'Paper Collection' },
  { n: '02', label: 'Literature Review' },
  { n: '03', label: 'Gap Analysis' },
  { n: '04', label: 'Research Questions' },
  { n: '05', label: 'Hypothesis Generation' },
  { n: '06', label: 'Experiment Design' },
  { n: '07', label: 'Code Generation' },
  { n: '08', label: 'Experiment Run' },
  { n: '09', label: 'Results' },
  { n: '10', label: 'Review' },
  { n: '11', label: 'Report' },
];

const provenanceChain = ['Paper', 'Claim', 'Gap', 'Research Question', 'Hypothesis', 'Experiment', 'Result', 'Conclusion'];

const memoryItems = [
  'Papers', 'Claims', 'Gaps', 'Research questions', 'Hypotheses', 'Experiments', 'Results', 'Reports', 'Research history',
];

const autonomyModes = [
  {
    label: 'Suggest Only',
    desc: 'The agent proposes research actions but does not continue automatically.',
    icon: '💬',
  },
  {
    label: 'Approval Required',
    desc: 'The agent pauses before important research actions.',
    icon: '✋',
  },
  {
    label: 'Autonomous Within Limits',
    desc: 'The agent continues automatically within the limits you configure.',
    icon: '⚙️',
  },
];

const hostedCaps = [
  'No installation required',
  'Persistent projects',
  'Paper library',
  'Research history',
  'Cross-session memory',
  'Use your own API key',
  'ResearchAgentLab Credits — no API key required (coming soon)',
  'Research provenance graph',
  'Report generation',
];

const ossCaps = [
  'Free local usage',
  'Use local AI models',
  'Use your own API key',
  'Execute experiments on your CPU or GPU',
  'Access local datasets',
  'Unlimited local research runs',
  'Inspect and contribute to the source code',
];

const freePlan = [
  '10 hosted research runs per month',
  'Use your own API key',
  'Unlimited local research',
  '1 concurrent hosted research run',
  'Up to 3 active projects',
];

const researcherPlan = [
  'Unlimited hosted research with your own API key, subject to fair-use limits',
  'Monthly ResearchAgentLab Credits included',
  '2 concurrent hosted research runs',
  'Unlimited projects',
  'Persistent cross-session research memory',
  'Full research history',
  'Research provenance graph',
  'Advanced exports',
  'Local Runner',
  'Early access to new features',
];

function Check({ primary = true }: { primary?: boolean }) {
  return (
    <svg className="flex-shrink-0 mt-0.5" width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle cx="7" cy="7" r="7" fill={primary ? 'var(--primary)' : '#6b7280'} opacity="0.15"/>
      <path d="M4 7l2 2 4-4" stroke={primary ? 'var(--primary)' : '#6b7280'} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: 'var(--primary)' }}>{children}</p>
  );
}

function Divider() {
  return <div className="border-t" style={{ borderColor: 'var(--border)' }} />;
}

export default function Home() {
  return (
    <div className="public-light min-h-screen">
      <PublicNav />

      {/* ── 1. HERO ───────────────────────────────── */}
      <section className="pt-32 pb-20 px-6 relative overflow-hidden">
        <div className="absolute inset-0 pointer-events-none" style={{
          background: 'radial-gradient(ellipse 70% 50% at 50% -5%, rgba(10,170,144,0.1) 0%, transparent 70%)'
        }} />
        <div className="max-w-4xl mx-auto text-center relative">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-mono mb-8 border" style={{ borderColor: 'rgba(10,170,144,0.3)', color: 'var(--primary)', background: 'rgba(10,170,144,0.07)' }}>
            <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: 'var(--primary)' }} />
            Early Access — Open Source
          </div>
          <h1 className="font-display text-5xl md:text-7xl font-light leading-none tracking-tight mb-6" style={{ color: 'var(--foreground)' }}>
            From a research question<br />
            <em className="font-light not-italic" style={{ color: 'var(--primary)' }}>to evidence, hypotheses,<br />experiments and a report.</em>
          </h1>
          <p className="text-lg max-w-2xl mx-auto mb-10 leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>
            ResearchAgentLab is an autonomous research workspace that searches literature, identifies gaps, develops hypotheses, designs experiments, and keeps every step connected to the evidence behind it.
          </p>
          <div className="flex flex-wrap gap-3 justify-center">
            <Link to="/signup" className="px-6 py-3 rounded font-medium text-sm" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
              Start researching free
            </Link>
            <a href="https://github.com/researchagentlab/researchagentlab" target="_blank" rel="noopener"
              className="flex items-center gap-2 px-6 py-3 rounded font-medium text-sm border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)', background: 'var(--card)' }}>
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
              View on GitHub
            </a>
          </div>
        </div>
      </section>

      {/* ── 2. OPEN-SOURCE ADOPTION METRICS ──────── */}
      <section className="px-6 pb-16">
        <div className="max-w-4xl mx-auto">
          <GitHubMetrics />
        </div>
      </section>

      <Divider />

      {/* ── 3. RESEARCH WORKFLOW ──────────────────── */}
      <section className="py-20 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14">
            <SectionLabel>Autonomous Research Workflow</SectionLabel>
            <h2 className="font-display text-4xl font-light mb-4" style={{ color: 'var(--foreground)' }}>From question to report — autonomously.</h2>
            <p className="max-w-xl mx-auto" style={{ color: 'var(--muted-foreground)' }}>
              The research agent works through a structured lifecycle. Run generated experiments on your own hardware through the Local Runner.
            </p>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {stages.map((s, i) => (
              <div key={s.n} className="p-4 rounded-lg border" style={{
                background: s.n === '08' ? 'rgba(10,170,144,0.05)' : 'var(--card)',
                borderColor: s.n === '08' ? 'rgba(10,170,144,0.25)' : 'var(--border)'
              }}>
                <div className="text-xs font-mono mb-1" style={{ color: 'var(--primary)' }}>{s.n}</div>
                <div className="text-sm font-medium" style={{ color: 'var(--foreground)' }}>{s.label}</div>
                {s.n === '08' && (
                  <div className="text-xs mt-1.5 leading-snug" style={{ color: 'var(--muted-foreground)' }}>
                    Run on your own hardware via Local Runner
                  </div>
                )}
              </div>
            ))}
          </div>

          <p className="text-xs text-center mt-6" style={{ color: 'var(--muted-foreground)' }}>
            Experiment execution currently happens through the Local Runner. Managed cloud execution is coming later.
          </p>
        </div>
      </section>

      <Divider />

      {/* ── 4. RESEARCH PROVENANCE ───────────────── */}
      <section className="py-20 px-6">
        <div className="max-w-5xl mx-auto grid md:grid-cols-2 gap-16 items-center">
          <div>
            <SectionLabel>Research Provenance</SectionLabel>
            <h2 className="font-display text-4xl font-light mb-4" style={{ color: 'var(--foreground)' }}>See how your research was produced.</h2>
            <p className="mb-4 leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>
              Every source, claim, gap, hypothesis, experiment and result remains connected, so you can trace a conclusion back to the evidence that produced it.
            </p>
            <p className="text-sm font-medium" style={{ color: 'var(--foreground)' }}>Trace every conclusion back to its evidence.</p>
            <p className="text-sm mt-2" style={{ color: 'var(--muted-foreground)' }}>
              ResearchAgentLab does not only generate a final answer — it preserves the research process that created it.
            </p>
          </div>
          <div>
            <div className="flex flex-col gap-2">
              {provenanceChain.map((item, i) => (
                <div key={item} className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full border flex items-center justify-center text-xs font-mono flex-shrink-0"
                    style={{ borderColor: i === provenanceChain.length - 1 ? 'var(--primary)' : 'var(--border)', background: i === provenanceChain.length - 1 ? 'rgba(10,170,144,0.1)' : 'var(--card)', color: i === provenanceChain.length - 1 ? 'var(--primary)' : 'var(--muted-foreground)' }}>
                    {i + 1}
                  </div>
                  <div className="flex-1 px-4 py-2 rounded border text-sm font-medium"
                    style={{ background: i === provenanceChain.length - 1 ? 'rgba(10,170,144,0.05)' : 'var(--card)', borderColor: i === provenanceChain.length - 1 ? 'rgba(10,170,144,0.25)' : 'var(--border)', color: 'var(--foreground)' }}>
                    {item}
                  </div>
                  {i < provenanceChain.length - 1 && (
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" style={{ color: 'var(--border)', position: 'absolute', left: '1.25rem', top: '100%' }}>
                    </svg>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <Divider />

      {/* ── 5. PERSISTENT RESEARCH MEMORY ────────── */}
      <section className="py-20 px-6" style={{ background: 'var(--muted)' }}>
        <div className="max-w-5xl mx-auto">
          <div className="grid md:grid-cols-2 gap-16 items-center">
            <div>
              <SectionLabel>Persistent Research Memory</SectionLabel>
              <h2 className="font-display text-4xl font-light mb-4" style={{ color: 'var(--foreground)' }}>Your research does not reset with every chat.</h2>
              <p className="mb-4 leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>
                Papers discovered last week, rejected hypotheses, previous experiments and results remain part of the project context for future research sessions.
              </p>
              <p className="text-sm font-medium mb-2" style={{ color: 'var(--foreground)' }}>Continue where you left off instead of starting from zero.</p>
              <p className="text-sm" style={{ color: 'var(--muted-foreground)' }}>
                A Project is a persistent research workspace that may contain multiple autonomous research sessions. Everything a session produces is available to the next one.
              </p>
            </div>
            <div className="p-6 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <p className="text-sm font-medium mb-4" style={{ color: 'var(--foreground)' }}>A project retains across all sessions:</p>
              <div className="grid grid-cols-2 gap-2">
                {memoryItems.map(item => (
                  <div key={item} className="flex items-center gap-2 text-sm" style={{ color: 'var(--foreground)' }}>
                    <Check />{item}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <Divider />

      {/* ── 6. HUMAN CONTROL / AUTONOMY ──────────── */}
      <section className="py-20 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14">
            <SectionLabel>Human Control</SectionLabel>
            <h2 className="font-display text-4xl font-light mb-4" style={{ color: 'var(--foreground)' }}>You stay in control.</h2>
            <p className="max-w-xl mx-auto" style={{ color: 'var(--muted-foreground)' }}>
              Choose whether the agent suggests actions, waits for approval, or works autonomously within limits you define. Autonomy is configurable, not all-or-nothing.
            </p>
          </div>

          <div className="grid md:grid-cols-3 gap-5 mb-10">
            {autonomyModes.map(m => (
              <div key={m.label} className="p-6 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div className="text-2xl mb-3">{m.icon}</div>
                <h3 className="text-base font-medium mb-2" style={{ color: 'var(--foreground)' }}>{m.label}</h3>
                <p className="text-sm" style={{ color: 'var(--muted-foreground)' }}>{m.desc}</p>
              </div>
            ))}
          </div>

          <div className="p-6 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
            <p className="text-sm font-medium mb-3" style={{ color: 'var(--foreground)' }}>Configurable limits for autonomous mode:</p>
            <div className="flex flex-wrap gap-2">
              {['Maximum papers', 'Maximum AI budget', 'Maximum experiment attempts', 'External downloads', 'Code execution approval'].map(l => (
                <span key={l} className="text-xs px-3 py-1.5 rounded-full border font-mono" style={{ borderColor: 'var(--border)', color: 'var(--muted-foreground)', background: 'var(--muted)' }}>{l}</span>
              ))}
            </div>
          </div>
        </div>
      </section>

      <Divider />

      {/* ── 7. HOSTED VS OPEN SOURCE ─────────────── */}
      <section className="py-20 px-6" style={{ background: 'var(--muted)' }}>
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14">
            <SectionLabel>Two Ways to Use</SectionLabel>
            <h2 className="font-display text-4xl font-light" style={{ color: 'var(--foreground)' }}>Hosted or self-hosted — your choice.</h2>
          </div>
          <div className="grid md:grid-cols-2 gap-6">
            {/* Hosted */}
            <div className="p-8 rounded-lg border flex flex-col" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <div className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: 'var(--primary)' }}>Hosted</div>
              <h3 className="font-display text-2xl font-light mb-2" style={{ color: 'var(--foreground)' }}>Use ResearchAgentLab on the web</h3>
              <p className="text-sm mb-2" style={{ color: 'var(--muted-foreground)' }}>The web app keeps your research organised and available across sessions.</p>
              <p className="text-sm mb-6" style={{ color: 'var(--muted-foreground)' }}>Projects, literature, hypotheses, experiments and reports remain connected in one persistent research workspace.</p>
              <ul className="flex flex-col gap-2.5 mb-8 flex-1">
                {hostedCaps.map(f => (
                  <li key={f} className="flex items-start gap-2.5 text-sm" style={{ color: 'var(--foreground)' }}>
                    <Check />{f}
                  </li>
                ))}
              </ul>
              <Link to="/signup" className="inline-block text-center px-5 py-2.5 rounded text-sm font-medium" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
                Start on the web
              </Link>
            </div>

            {/* OSS */}
            <div className="p-8 rounded-lg border flex flex-col" style={{ background: 'var(--card)', borderColor: 'rgba(10,170,144,0.2)' }}>
              <div className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: 'var(--accent)' }}>Open Source</div>
              <h3 className="font-display text-2xl font-light mb-2" style={{ color: 'var(--foreground)' }}>Run ResearchAgentLab yourself</h3>
              <p className="text-sm mb-6" style={{ color: 'var(--muted-foreground)' }}>The open-source version is free to run on your own hardware.</p>
              <ul className="flex flex-col gap-2.5 mb-8 flex-1">
                {ossCaps.map(f => (
                  <li key={f} className="flex items-start gap-2.5 text-sm" style={{ color: 'var(--foreground)' }}>
                    <Check primary={false} />{f}
                  </li>
                ))}
              </ul>
              <div className="flex gap-3 flex-wrap">
                <a href="https://github.com/researchagentlab/researchagentlab" target="_blank" rel="noopener"
                  className="inline-flex items-center gap-2 px-5 py-2.5 rounded text-sm font-medium border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
                  View GitHub repository
                </a>
                <Link to="/open-source" className="inline-block px-5 py-2.5 rounded text-sm font-medium" style={{ background: 'var(--secondary)', color: 'var(--foreground)' }}>
                  Install Local Runner
                </Link>
              </div>
            </div>
          </div>
        </div>
      </section>

      <Divider />

      {/* ── 8. LOCAL RUNNER ──────────────────────── */}
      <section className="py-20 px-6">
        <div className="max-w-5xl mx-auto grid md:grid-cols-2 gap-16 items-center">
          <div>
            <SectionLabel>Local Runner</SectionLabel>
            <h2 className="font-display text-4xl font-light mb-4" style={{ color: 'var(--foreground)' }}>Run experiments on your own hardware.</h2>
            <p className="mb-4 leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>
              ResearchAgentLab handles the research workflow on the web while Local Runner executes experiments on your machine.
            </p>
            <p className="text-sm mb-6" style={{ color: 'var(--muted-foreground)' }}>Your local compute is not billed as cloud compute.</p>
            <div className="flex gap-3">
              <Link to="/open-source" className="px-5 py-2.5 rounded text-sm font-medium" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
                Install Local Runner
              </Link>
              <a href="https://github.com/researchagentlab/researchagentlab" target="_blank" rel="noopener"
                className="px-5 py-2.5 rounded text-sm font-medium border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>
                View on GitHub
              </a>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {[
              { icon: '🖥', label: 'Generated experiment execution' },
              { icon: '⚡', label: 'Local CPU or GPU' },
              { icon: '🤖', label: 'Local AI models' },
              { icon: '📁', label: 'Local datasets' },
              { icon: '🔑', label: 'Your own API key' },
              { icon: '🔒', label: 'No cloud compute billing' },
            ].map(item => (
              <div key={item.label} className="p-4 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
                <div className="text-xl mb-2">{item.icon}</div>
                <div className="text-sm" style={{ color: 'var(--foreground)' }}>{item.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <Divider />

      {/* ── 9. PRIVACY ───────────────────────────── */}
      <section className="py-20 px-6" style={{ background: 'var(--muted)' }}>
        <div className="max-w-4xl mx-auto text-center">
          <SectionLabel>Research Ownership</SectionLabel>
          <h2 className="font-display text-4xl font-light mb-4" style={{ color: 'var(--foreground)' }}>Your research stays yours.</h2>
          <p className="text-lg max-w-2xl mx-auto mb-4 leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>
            Private research content is not used for model improvement unless you explicitly choose to share it.
          </p>
          <p className="max-w-xl mx-auto mb-8" style={{ color: 'var(--muted-foreground)' }}>
            Local execution can keep experiment code, local models and datasets on your own machine.
          </p>
          <Link to="/privacy" className="text-sm font-medium" style={{ color: 'var(--primary)' }}>
            Learn about research data and privacy →
          </Link>
        </div>
      </section>

      <Divider />

      {/* ── 10. PRICING PREVIEW ──────────────────── */}
      <section className="py-20 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14">
            <SectionLabel>Pricing</SectionLabel>
            <h2 className="font-display text-4xl font-light" style={{ color: 'var(--foreground)' }}>Start free. Upgrade when your research grows.</h2>
          </div>
          <div className="grid md:grid-cols-2 gap-6 max-w-3xl mx-auto">
            {/* Free */}
            <div className="p-8 rounded-lg border flex flex-col" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <div className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: 'var(--muted-foreground)' }}>Free</div>
              <div className="font-display text-3xl font-light mb-1" style={{ color: 'var(--foreground)' }}>£0</div>
              <div className="text-sm mb-6" style={{ color: 'var(--muted-foreground)' }}>/ month</div>
              <ul className="flex flex-col gap-2.5 mb-8 flex-1">
                {freePlan.map(f => (
                  <li key={f} className="flex items-start gap-2.5 text-sm" style={{ color: 'var(--foreground)' }}>
                    <Check />{f}
                  </li>
                ))}
              </ul>
              <Link to="/signup" className="w-full text-center py-2.5 rounded text-sm font-medium border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>
                Start free
              </Link>
              <p className="text-xs text-center mt-2" style={{ color: 'var(--muted-foreground)' }}>No payment card required.</p>
            </div>

            {/* Researcher */}
            <div className="p-8 rounded-lg border flex flex-col relative overflow-hidden" style={{ background: 'var(--card)', borderColor: 'rgba(10,170,144,0.35)' }}>
              <div className="absolute top-0 right-0 px-3 py-1 text-xs font-mono rounded-bl" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>Coming Soon</div>
              <div className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: 'var(--primary)' }}>Founding Researcher</div>
              <div className="font-display text-3xl font-light mb-1" style={{ color: 'var(--foreground)' }}>£9</div>
              <div className="text-sm mb-6" style={{ color: 'var(--muted-foreground)' }}>/ month</div>
              <ul className="flex flex-col gap-2.5 mb-4 flex-1">
                {researcherPlan.slice(0, 6).map(f => (
                  <li key={f} className="flex items-start gap-2.5 text-sm" style={{ color: 'var(--foreground)' }}>
                    <Check />{f}
                  </li>
                ))}
              </ul>
              <p className="text-xs mb-6" style={{ color: 'var(--muted-foreground)' }}>Included ResearchAgentLab Credits reset each billing period and do not roll over.</p>
              <Link to="/pricing" className="w-full text-center py-2.5 rounded text-sm font-medium" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
                View pricing
              </Link>
            </div>
          </div>
        </div>
      </section>

      <Divider />

      {/* ── 11. GITHUB CTA ───────────────────────── */}
      <section className="py-20 px-6" style={{ background: 'var(--muted)' }}>
        <div className="max-w-4xl mx-auto text-center">
          <SectionLabel>Open Source</SectionLabel>
          <h2 className="font-display text-4xl font-light mb-4" style={{ color: 'var(--foreground)' }}>ResearchAgentLab is built in the open.</h2>
          <p className="text-lg max-w-xl mx-auto mb-8" style={{ color: 'var(--muted-foreground)' }}>
            Run the research agent locally, inspect how it works, contribute improvements or build on top of it.
          </p>
          <div className="flex flex-wrap justify-center gap-3 mb-6">
            {[
              { label: 'Star on GitHub', href: 'https://github.com/researchagentlab/researchagentlab', primary: true },
              { label: 'View source', href: 'https://github.com/researchagentlab/researchagentlab' },
              { label: 'Report an issue', href: 'https://github.com/researchagentlab/researchagentlab/issues' },
              { label: 'Contribute', href: 'https://github.com/researchagentlab/researchagentlab/blob/main/CONTRIBUTING.md' },
            ].map(a => (
              <a key={a.label} href={a.href} target="_blank" rel="noopener"
                className="flex items-center gap-2 px-5 py-2.5 rounded text-sm font-medium border"
                style={{ background: a.primary ? 'var(--foreground)' : 'var(--card)', color: a.primary ? 'var(--background)' : 'var(--foreground)', borderColor: a.primary ? 'transparent' : 'var(--border)' }}>
                {a.primary && <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>}
                {a.label}
              </a>
            ))}
          </div>
          <GitHubMetrics />
        </div>
      </section>

      {/* ── 12. FOOTER ───────────────────────────── */}
      <footer className="border-t py-10 px-6" style={{ borderColor: 'var(--border)', background: 'var(--card)' }}>
        <div className="max-w-5xl mx-auto flex flex-wrap gap-6 justify-between items-center">
          <div className="flex items-center gap-2 font-display text-sm" style={{ color: 'var(--muted-foreground)' }}>
            <span className="w-5 h-5 rounded flex items-center justify-center text-xs font-bold font-mono" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>R</span>
            ResearchAgentLab
          </div>
          <div className="flex flex-wrap gap-6 text-xs" style={{ color: 'var(--muted-foreground)' }}>
            <Link to="/features">Features</Link>
            <Link to="/pricing">Pricing</Link>
            <Link to="/open-source">Open Source</Link>
            <Link to="/docs">Docs</Link>
            <Link to="/privacy">Privacy</Link>
            <Link to="/terms">Terms</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
