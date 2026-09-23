import { Link } from 'react-router-dom';
import PublicNav from '../../components/PublicNav';

const free = [
  '10 hosted research runs per month',
  'Use your own API key',
  'Unlimited local research',
  '1 concurrent hosted research run',
  'Up to 3 active projects',
  'Paper collection, literature review, gap analysis',
  'Hypothesis generation, experiment planning, code generation',
  'Research reports',
  'Local Runner',
];

const researcher = [
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

function Check({ accent = false }: { accent?: boolean }) {
  return (
    <svg className="flex-shrink-0 mt-0.5" width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle cx="7" cy="7" r="7" fill={accent ? 'var(--primary)' : '#6b7280'} opacity="0.15" />
      <path d="M4 7l2 2 4-4" stroke={accent ? 'var(--primary)' : '#6b7280'} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function Pricing() {
  return (
    <div className="public-light min-h-screen">
      <PublicNav />
      <div className="pt-28 pb-20 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14">
            <h1 className="font-display text-5xl font-light mb-4" style={{ color: 'var(--foreground)' }}>Simple, honest pricing.</h1>
            <p style={{ color: 'var(--muted-foreground)' }}>Start free. The open-source Local Runner is always free.</p>
          </div>

          {/* Three concepts explained */}
          <div className="grid md:grid-cols-3 gap-4 mb-12 p-6 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
            {[
              { label: 'Hosted research allowance', desc: 'The number of autonomous research runs you can start on the web each month.' },
              { label: 'Your API Key', desc: 'Connect your OpenAI, Anthropic, or Gemini API key. AI usage is billed directly by your provider.' },
              { label: 'ResearchAgentLab Credits', desc: 'No API key required. AI usage is covered by your ResearchAgentLab credit balance. Coming soon.' },
            ].map(c => (
              <div key={c.label}>
                <div className="text-xs font-mono font-medium mb-1" style={{ color: 'var(--primary)' }}>{c.label}</div>
                <p className="text-xs" style={{ color: 'var(--muted-foreground)' }}>{c.desc}</p>
              </div>
            ))}
          </div>

          <div className="grid md:grid-cols-2 gap-6 mb-12">
            {/* Free */}
            <div className="p-8 rounded-lg border flex flex-col" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <div className="text-xs font-mono uppercase tracking-widest mb-4" style={{ color: 'var(--muted-foreground)' }}>Free Beta</div>
              <div className="font-display text-4xl font-light mb-1" style={{ color: 'var(--foreground)' }}>£0</div>
              <div className="text-sm mb-2" style={{ color: 'var(--muted-foreground)' }}>/ month</div>
              <p className="text-sm mb-8" style={{ color: 'var(--muted-foreground)' }}>For exploring ResearchAgentLab and occasional hosted research.</p>
              <ul className="flex flex-col gap-2.5 mb-8 flex-1">
                {free.map(f => (
                  <li key={f} className="flex items-start gap-2.5 text-sm" style={{ color: 'var(--foreground)' }}>
                    <Check />{f}
                  </li>
                ))}
              </ul>
              <Link to="/signup" className="w-full text-center py-3 rounded font-medium text-sm border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>
                Start free
              </Link>
              <p className="text-xs text-center mt-3" style={{ color: 'var(--muted-foreground)' }}>No payment card required.</p>
              <p className="text-xs text-center mt-1" style={{ color: 'var(--muted-foreground)' }}>Need more hosted research runs? Run locally for free — there is no limit there.</p>
            </div>

            {/* Founding Researcher */}
            <div className="p-8 rounded-lg border flex flex-col relative overflow-hidden" style={{ background: 'var(--card)', borderColor: 'rgba(10,170,144,0.35)' }}>
              <div className="absolute top-0 right-0 px-3 py-1 rounded-bl text-xs font-mono" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>Coming Soon</div>
              <div className="text-xs font-mono uppercase tracking-widest mb-4" style={{ color: 'var(--primary)' }}>Founding Researcher</div>
              <div className="font-display text-4xl font-light mb-1" style={{ color: 'var(--foreground)' }}>£9</div>
              <div className="text-sm mb-2" style={{ color: 'var(--muted-foreground)' }}>/ month</div>
              <p className="text-sm mb-8" style={{ color: 'var(--muted-foreground)' }}>For researchers using ResearchAgentLab regularly.</p>
              <ul className="flex flex-col gap-2.5 mb-4 flex-1">
                {researcher.map(f => (
                  <li key={f} className="flex items-start gap-2.5 text-sm" style={{ color: 'var(--foreground)' }}>
                    <Check accent />{f}
                  </li>
                ))}
              </ul>
              <p className="text-xs mb-2" style={{ color: 'var(--muted-foreground)' }}>Included ResearchAgentLab Credits reset each billing period and do not roll over.</p>
              <p className="text-xs mb-8" style={{ color: 'var(--muted-foreground)' }}>Using your own API key does not consume ResearchAgentLab Credits.</p>
              <div className="w-full text-center py-3 rounded font-medium text-sm border" style={{ borderColor: 'var(--border)', color: 'var(--muted-foreground)' }}>
                Coming Soon
              </div>
            </div>
          </div>

          {/* Self-host callout */}
          <div className="p-8 rounded-lg border text-center" style={{ background: 'var(--muted)', borderColor: 'var(--border)' }}>
            <p className="font-display text-xl font-light mb-2" style={{ color: 'var(--foreground)' }}>Prefer to self-host?</p>
            <p className="text-sm mb-2" style={{ color: 'var(--muted-foreground)' }}>Run ResearchAgentLab locally for free using your own API key, local models and hardware.</p>
            <p className="text-xs mb-6" style={{ color: 'var(--muted-foreground)' }}>Hosted plan limits do not apply to local/self-hosted use.</p>
            <div className="flex gap-3 justify-center flex-wrap">
              <a href="https://github.com/researchagentlab/researchagentlab" target="_blank" rel="noopener"
                className="px-5 py-2.5 rounded text-sm font-medium border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)', background: 'var(--card)' }}>
                View on GitHub
              </a>
              <Link to="/open-source" className="px-5 py-2.5 rounded text-sm font-medium" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
                Installation guide
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
