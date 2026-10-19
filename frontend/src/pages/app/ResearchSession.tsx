import { Link, useParams } from 'react-router-dom';
import { useEffect, useMemo, useState } from 'react';
import AppShell from '../../components/AppShell';
import { getSession, getSessionStatus, resumeSession, stopSession, type SessionDetail } from '../../api/client';
import { useSessionSocket, type RunnerEvent } from '../../hooks/useSessionSocket';

function StageStatus({ status }: { status: string }) {
  const running = status === 'Running';
  return <span className="flex items-center gap-1.5 text-xs font-mono" style={{ color: running ? 'var(--primary)' : 'var(--muted-foreground)' }}>
    {running && <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: 'var(--primary)' }} />}
    {status}
  </span>;
}

export default function ResearchSession() {
  const { sessionId } = useParams();
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [running, setRunning] = useState(false);
  const [activeTab, setActiveTab] = useState<'pipeline' | 'log'>('pipeline');
  const [error, setError] = useState('');
  const [actionBusy, setActionBusy] = useState(false);
  const { events, connected } = useSessionSocket(sessionId, running);

  const refresh = () => {
    if (!sessionId) return;
    Promise.all([getSession(sessionId), getSessionStatus(sessionId)])
      .then(([next, status]) => { setDetail(next); setRunning(status.running); })
      .catch((err: Error) => setError(err.message));
  };

  useEffect(() => { refresh(); }, [sessionId]);
  useEffect(() => {
    if (!running || !sessionId) return;
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, [running, sessionId]);

  const logEvents = useMemo(() => events.map((event: RunnerEvent, index) => ({
    id: index,
    type: event.type,
    message: String(event.data?.message || event.data?.name || event.type),
  })), [events]);

  const action = async (fn: () => Promise<unknown>) => {
    setActionBusy(true); setError('');
    try { await fn(); refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : 'Action failed.'); }
    finally { setActionBusy(false); }
  };

  if (!detail) return <AppShell><div className="p-8">{error || 'Loading session…'}</div></AppShell>;

  const session = detail.session;
  const currentStatus = running ? 'Running' : session.status === 'experiment_run' ? 'Completed' : session.status || 'Started';
  const stages = [
    ['papers_collected', 'Paper Collection'],
    ['review_done', 'Literature Review'],
    ['question_selected', 'Research Question'],
    ['hypotheses_generated', 'Hypothesis Generation'],
    ['code_generated', 'Experiment Code Generation'],
    ['experiment_run', 'Experiment Execution'],
  ] as const;
  const statusIndex = stages.findIndex(([key]) => key === session.status);

  return <AppShell>
    <div className="p-8 max-w-5xl">
      <div className="flex items-start justify-between mb-6">
        <div>
          <Link to="/app" className="text-xs" style={{ color: 'var(--muted-foreground)' }}>← Dashboard</Link>
          <h1 className="font-display text-2xl font-light mt-3 mb-1" style={{ color: 'var(--foreground)' }}>{session.topic}</h1>
          <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--muted-foreground)' }}>
            <StageStatus status={currentStatus} />
            <span>{connected ? 'Live connection' : 'Polling status'}</span>
            <span>{detail.papers.length} papers · {detail.hypotheses.length} hypotheses</span>
          </div>
        </div>
        <div className="flex gap-2">
          {running ? <button disabled={actionBusy} onClick={() => action(() => stopSession(session.session_id))} className="px-3 py-2 rounded text-sm border disabled:opacity-50" style={{ borderColor: 'rgba(239,68,68,0.4)', color: '#ef4444' }}>Stop</button>
            : <button disabled={actionBusy} onClick={() => action(() => resumeSession(session.session_id))} className="px-3 py-2 rounded text-sm disabled:opacity-50" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>Resume</button>}
        </div>
      </div>

      {error && <div className="p-3 rounded border mb-5 text-sm" style={{ background: 'rgba(239,68,68,0.08)', borderColor: 'rgba(239,68,68,0.3)', color: '#ef4444' }}>{error}</div>}
      <div className="flex gap-1 mb-6 border-b" style={{ borderColor: 'var(--border)' }}>
        {(['pipeline', 'log'] as const).map((tab) => <button key={tab} onClick={() => setActiveTab(tab)} className="px-4 py-2 text-sm capitalize border-b-2 -mb-px" style={{ borderColor: activeTab === tab ? 'var(--primary)' : 'transparent', color: activeTab === tab ? 'var(--foreground)' : 'var(--muted-foreground)' }}>{tab === 'log' ? `Live Log${events.length ? ` (${events.length})` : ''}` : 'Pipeline'}</button>)}
      </div>

      {activeTab === 'pipeline' && <div className="flex flex-col gap-2">
        {stages.map(([key, label], index) => {
          const completed = statusIndex >= index || session.status === key;
          const stageStatus = completed ? 'Completed' : running && index === statusIndex + 1 ? 'Running' : 'Not started';
          return <div key={key} className="flex items-center gap-4 p-4 rounded-lg border" style={{ background: stageStatus === 'Running' ? 'rgba(0,200,168,0.04)' : 'var(--card)', borderColor: stageStatus === 'Running' ? 'rgba(0,200,168,0.2)' : 'var(--border)' }}>
            <div className="w-6 h-6 rounded-full border flex items-center justify-center text-xs font-mono" style={{ borderColor: completed ? '#6ec87a' : 'var(--border)', color: completed ? '#6ec87a' : 'var(--muted-foreground)' }}>{completed ? '✓' : String(index + 1).padStart(2, '0')}</div>
            <div className="flex-1 text-sm" style={{ color: completed ? 'var(--foreground)' : 'var(--muted-foreground)' }}>{label}</div>
            <StageStatus status={stageStatus} />
          </div>;
        })}
      </div>}

      {activeTab === 'log' && <div className="flex flex-col gap-1">
        {logEvents.length === 0 && <div className="p-4 text-sm" style={{ color: 'var(--muted-foreground)' }}>No live events yet. Start or resume the session to see progress.</div>}
        {logEvents.map((event) => <div key={event.id} className="flex gap-4 p-3 rounded" style={{ background: 'var(--card)' }}><span className="text-xs font-mono" style={{ color: 'var(--muted-foreground)' }}>{event.type}</span><span className="text-sm" style={{ color: 'var(--foreground)' }}>{event.message}</span></div>)}
      </div>}
    </div>
  </AppShell>;
}
