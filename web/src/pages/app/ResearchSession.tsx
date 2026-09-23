import { Link, useParams } from 'react-router-dom';
import { useState } from 'react';
import AppShell from '../../components/AppShell';

const STAGES = [
  { id: 'paper-collection', label: 'Paper Collection', status: 'Completed', completedAt: '14:02' },
  { id: 'lit-review', label: 'Literature Review', status: 'Completed', completedAt: '14:18' },
  { id: 'gap-analysis', label: 'Gap Analysis', status: 'Completed', completedAt: '14:31' },
  { id: 'questions', label: 'Research Questions', status: 'Completed', completedAt: '14:35' },
  { id: 'hypothesis', label: 'Hypothesis Generation', status: 'Running', completedAt: null },
  { id: 'experiment', label: 'Experiment Design', status: 'Not Started', completedAt: null },
  { id: 'codegen', label: 'Code Generation', status: 'Not Started', completedAt: null },
  { id: 'run', label: 'Experiment Run', status: 'Not Started', completedAt: null },
  { id: 'results', label: 'Results', status: 'Not Started', completedAt: null },
  { id: 'review', label: 'Review', status: 'Not Started', completedAt: null },
  { id: 'report', label: 'Report', status: 'Not Started', completedAt: null },
];

const LOG = [
  { time: '14:02:41', stage: 'Paper Collection', event: 'Searching papers', detail: 'Query: "chain-of-thought reasoning LLM benchmark"', status: 'info' },
  { time: '14:03:12', stage: 'Paper Collection', event: 'Paper accepted', detail: 'Wei et al. (2022) — Chain-of-Thought Prompting Elicits Reasoning in Large Language Models', status: 'success' },
  { time: '14:03:44', stage: 'Paper Collection', event: 'Paper accepted', detail: 'Kojima et al. (2022) — Large Language Models are Zero-Shot Reasoners', status: 'success' },
  { time: '14:09:01', stage: 'Paper Collection', event: 'Paper excluded', detail: 'Excluded: off-topic — "Neural Machine Translation by Jointly Learning to Align"', status: 'muted' },
  { time: '14:18:22', stage: 'Literature Review', event: 'Gap generated', detail: 'Consistency across reasoning-intensive benchmarks under distribution shift is underexplored.', status: 'accent' },
  { time: '14:31:05', stage: 'Gap Analysis', event: 'Hypothesis proposed', detail: 'Chain-of-thought consistency degrades more rapidly than answer accuracy under input perturbation.', status: 'accent' },
  { time: '14:35:00', stage: 'Hypothesis Generation', event: 'Hypothesis selected', detail: 'Selected for experiment design.', status: 'success' },
  { time: '14:47:00', stage: 'Hypothesis Generation', event: 'Agent paused', detail: 'Awaiting approval before proceeding to experiment design.', status: 'warning' },
];

function StageStatus({ status }: { status: string }) {
  const s: Record<string, { color: string; bg: string; dot?: boolean }> = {
    'Completed': { color: '#6ec87a', bg: 'rgba(110,200,122,0.1)' },
    'Running': { color: 'var(--primary)', bg: 'rgba(0,200,168,0.1)', dot: true },
    'Not Started': { color: 'var(--muted-foreground)', bg: 'transparent' },
    'Waiting for Approval': { color: 'var(--accent)', bg: 'rgba(240,160,48,0.1)' },
    'Failed': { color: '#ef4444', bg: 'rgba(239,68,68,0.1)' },
  };
  const c = s[status] ?? s['Not Started'];
  return (
    <span className="flex items-center gap-1.5 text-xs font-mono" style={{ color: c.color }}>
      {c.dot && <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: c.color }}/>}
      {status}
    </span>
  );
}

export default function ResearchSession() {
  const { projectId, sessionId } = useParams();
  const [activeTab, setActiveTab] = useState<'pipeline' | 'log'>('pipeline');

  return (
    <AppShell>
      <div className="p-8 max-w-5xl">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-xs mb-6" style={{ color: 'var(--muted-foreground)' }}>
          <Link to="/app/projects" style={{ color: 'var(--muted-foreground)' }}>Projects</Link>
          <span>→</span>
          <Link to={`/app/projects/${projectId}`} style={{ color: 'var(--muted-foreground)' }}>LLM Reasoning Benchmarks</Link>
          <span>→</span>
          <span style={{ color: 'var(--foreground)' }}>Session 3</span>
        </div>

        <div className="flex items-start justify-between mb-6">
          <div>
            <h1 className="font-display text-2xl font-light mb-1" style={{ color: 'var(--foreground)' }}>Research Session</h1>
            <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--muted-foreground)' }}>
              <span>Started 14:00 · 21 Sep 2026</span>
              <StageStatus status="Running"/>
              <span>Anthropic — Claude 3.5 Sonnet</span>
            </div>
          </div>
          <div className="flex gap-2">
            <button className="px-3 py-2 rounded text-sm border" style={{ borderColor: 'rgba(240,160,48,0.4)', color: 'var(--accent)', background: 'rgba(240,160,48,0.07)' }}>
              Approve
            </button>
            <button className="px-3 py-2 rounded text-sm border" style={{ borderColor: 'var(--border)', color: 'var(--muted-foreground)' }}>
              Pause
            </button>
          </div>
        </div>

        {/* Budget notice */}
        <div className="p-3 rounded border mb-6 text-xs font-mono flex items-center gap-2" style={{ background: 'rgba(240,160,48,0.07)', borderColor: 'rgba(240,160,48,0.3)', color: 'var(--accent)' }}>
          <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor"><path d="M6 1a5 5 0 100 10A5 5 0 006 1zm0 4.5a.5.5 0 01.5.5v2a.5.5 0 01-1 0V6a.5.5 0 01.5-.5zm0-2a.625.625 0 110 1.25A.625.625 0 016 3.5z"/></svg>
          Research budget approaching: £4.20 of £5.00 used.
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mb-6 border-b" style={{ borderColor: 'var(--border)' }}>
          {(['pipeline', 'log'] as const).map(t => (
            <button key={t} onClick={() => setActiveTab(t)} className="px-4 py-2 text-sm capitalize border-b-2 -mb-px transition-colors"
              style={{ borderColor: activeTab === t ? 'var(--primary)' : 'transparent', color: activeTab === t ? 'var(--foreground)' : 'var(--muted-foreground)' }}>
              {t === 'log' ? 'Live Log' : 'Pipeline'}
            </button>
          ))}
        </div>

        {activeTab === 'pipeline' && (
          <div className="flex flex-col gap-2">
            {STAGES.map((s, i) => (
              <div key={s.id} className="flex items-center gap-4 p-4 rounded-lg border" style={{ background: s.status === 'Running' ? 'rgba(0,200,168,0.04)' : 'var(--card)', borderColor: s.status === 'Running' ? 'rgba(0,200,168,0.2)' : 'var(--border)' }}>
                <div className="w-6 h-6 rounded-full border flex items-center justify-center text-xs font-mono flex-shrink-0"
                  style={{ borderColor: s.status === 'Completed' ? '#6ec87a' : s.status === 'Running' ? 'var(--primary)' : 'var(--border)', background: s.status === 'Completed' ? 'rgba(110,200,122,0.12)' : 'transparent', color: s.status === 'Completed' ? '#6ec87a' : 'var(--muted-foreground)' }}>
                  {s.status === 'Completed' ? '✓' : String(i + 1).padStart(2, '0')}
                </div>
                <div className="flex-1">
                  <div className="text-sm font-medium" style={{ color: s.status === 'Not Started' ? 'var(--muted-foreground)' : 'var(--foreground)' }}>{s.label}</div>
                  {s.completedAt && <div className="text-xs mt-0.5" style={{ color: 'var(--muted-foreground)' }}>Completed at {s.completedAt}</div>}
                </div>
                <StageStatus status={s.status}/>
                {s.status === 'Running' && (
                  <div className="flex gap-2">
                    <button className="text-xs px-2.5 py-1 rounded border" style={{ borderColor: 'var(--border)', color: 'var(--muted-foreground)' }}>Pause</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {activeTab === 'log' && (
          <div className="flex flex-col gap-1">
            {LOG.map((e, i) => (
              <div key={i} className="flex gap-4 p-3 rounded hover:bg-white/2 transition-colors">
                <span className="text-xs font-mono flex-shrink-0 pt-0.5" style={{ color: 'var(--muted-foreground)' }}>{e.time}</span>
                <div className="flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-mono px-1.5 py-0.5 rounded" style={{ background: 'var(--secondary)', color: 'var(--muted-foreground)' }}>{e.stage}</span>
                    <span className="text-sm" style={{ color: e.status === 'success' ? '#6ec87a' : e.status === 'accent' ? 'var(--primary)' : e.status === 'warning' ? 'var(--accent)' : 'var(--foreground)' }}>{e.event}</span>
                  </div>
                  <p className="text-xs mt-1" style={{ color: 'var(--muted-foreground)' }}>{e.detail}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
