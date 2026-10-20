import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { download, send, type SessionDetail } from '../../api/client';
import { useResource, useAction } from '../../hooks/useResource';
import { useSessionSocket } from '../../hooks/useSessionSocket';
import DataView from '../../components/DataView';
import { ModelForm } from './ModelSettings';

type Stage = {key: string; label: string; done: boolean; ready: boolean; path: string; note: string; missing: {label: string; supply: string}[]};
type Question = {index: number; text: string; compliance?: string};
type Hypothesis = {id: string; testable: boolean; [key: string]: unknown};
export default function ResearchSession() {
  const {sessionId} = useParams();
  const navigate = useNavigate();
  const base = `/api/sessions/${encodeURIComponent(sessionId!)}`;
  const detail = useResource<SessionDetail>(base, 4000);
  const stages = useResource<{stages: Stage[]; running: boolean; waiting_step: string | null}>(`${base}/stages`, 4000);
  const projects = useResource<{projects: {project_id: string; name: string}[]}>('/api/projects');
  const [tab, setTab] = useState('Workflow');
  const [savedReport, setSavedReport] = useState<unknown>(null);
  useEffect(() => {setSavedReport(null); setTab('Workflow');}, [sessionId]);
  const action = useAction();
  const running = stages.data?.running || false;
  const socket = useSessionSocket(sessionId, running);
  const refresh = async () => {await Promise.all([detail.reload(), stages.reload()]);};
  const perform = (path: string, body: unknown = {}, method = 'POST') => action.run(async () => {
    const result = await send(`${base}/${path}`, body, method); await refresh();
    if (Array.isArray(result.problems) && result.problems.length) throw new Error(result.problems.join('\n'));
  }, 'Request accepted. Check the current status and log.');
  const d = detail.data;
  if (!d) return <><p>{detail.loading ? 'Loading session…' : detail.error}</p><button onClick={detail.reload}>Retry</button></>;
  const artifacts = d.artifacts || {};
  const waiting = stages.data?.waiting_step || d.waiting_step;
  const questions = (artifacts.question_candidates?.content.questions || []) as Question[];
  const hypotheses = (artifacts.hypotheses?.content.hypotheses || []) as Hypothesis[];
  const plan = artifacts.plan;
  return <>
    <header><div><Link to="/app">← Sessions</Link><h1>{d.session.topic}</h1><p>{d.session.status} · {waiting ? `Waiting: ${waiting}` : running ? 'Running' : 'Stopped'} · ${d.cost_usd}</p></div>
      <div className="actions"><button disabled={action.busy || !stages.data} onClick={() => perform(running ? 'stop' : 'resume')}>{running ? 'Stop' : 'Start / resume'}</button>
        <button disabled={action.busy} onClick={() => action.run(() => download(`${base}/export`, `session-${sessionId}.json`), 'Downloaded.')}>Export</button></div></header>
    {d.interrupted && <div role="status" className="panel"><h2>Run interrupted</h2><DataView value={d.interrupted} /></div>}
    <p role="alert">{detail.error || stages.error || action.error}</p><p role="status">{action.message}</p>
    <nav className="tabs">{['Workflow', 'Papers', 'Hypotheses', 'Code & results', 'Report', 'Log', 'Settings'].map(name =>
      <button key={name} aria-pressed={tab === name} onClick={() => setTab(name)}>{name}</button>)}</nav>
    {tab === 'Workflow' && <>
      {(waiting === 'question_selection' || (!d.session.research_question && questions.length > 0)) && <section className="panel stack"><h2>Select research question</h2>
        {questions.map(q => <div className="panel" key={q.index}><p>{q.text}</p><p>Data check: {q.compliance || 'unknown'}</p>
          <button disabled={action.busy || !running} onClick={() => {
            const override = q.compliance === 'fail';
            if (!override || window.confirm('This question failed the data check. Use it anyway?')) void perform('select-question', {choice: q.index, override});
          }}>Select question {q.index}</button></div>)}
        <form className="stack" onSubmit={e => {e.preventDefault(); const form = new FormData(e.currentTarget); void perform('select-question', {choice: String(form.get('question'))});}}>
          <label>Custom question<textarea name="question" required /></label><button disabled={action.busy || !running}>Use custom question</button>
        </form>{!running && <p>Resume the session to select a question.</p>}
      </section>}
      {(waiting === 'source_confirmation' || artifacts.source_check?.status === 'awaiting_approval') && <section className="panel">
        <h2>Source availability requires your decision</h2><DataView value={artifacts.source_check?.content} />
        <div className="actions"><button disabled={action.busy} onClick={() => perform('source-decision', {proceed: true})}>Continue without blocked source</button>
          <button disabled={action.busy} onClick={() => perform('source-decision', {proceed: false})}>Do not continue</button></div>
      </section>}
      {(waiting === 'hypothesis_selection' || artifacts.hypotheses?.status === 'awaiting_approval') && <form className="panel stack" key={`hyp-${artifacts.hypotheses?.version}`} onSubmit={e => {
        e.preventDefault(); const form = new FormData(e.currentTarget); const ids = form.getAll('hypothesis');
        if (!ids.length) return;
        void perform('select-hypotheses', {ids});
      }}><h2>Approve hypotheses</h2>{hypotheses.map(h => <div className="panel" key={h.id}>
        <label className="check"><input name="hypothesis" type="checkbox" value={h.id} disabled={!h.testable} />{h.id}{!h.testable && ' · Not testable'}</label><DataView value={h} />
      </div>)}<button disabled={action.busy}>Approve selected hypotheses</button></form>}
      {(waiting === 'plan_approval' || plan?.status === 'awaiting_approval') && <form className="panel stack" key={`plan-${plan?.version}`} onSubmit={e => {
        e.preventDefault(); const form = new FormData(e.currentTarget);
        const approve = (e.nativeEvent as SubmitEvent).submitter?.getAttribute('value') === 'approve';
        void perform('plan', {text: String(form.get('text')), approve});
      }}><h2>Review analysis plan</h2><DataView value={plan?.content.tests} />
        <label>Plan text<textarea rows={18} name="text" required defaultValue={String(plan?.content.text || '')} /></label>
        <div className="actions"><button value="check" disabled={action.busy}>Check changes</button><button value="approve" disabled={action.busy}>Approve plan</button></div>
      </form>}
      <h2>Stages</h2><div className="stack">{stages.data?.stages.map(s => <section className="panel" key={s.key}>
        <h3>{s.label}</h3><p>{s.done ? 'Completed' : s.ready ? 'Ready' : 'Prerequisites missing'} · {s.path}</p><p className="muted">{s.note}</p>
        {!s.ready && <DataView value={s.missing} />}
        <button disabled={running || action.busy || !s.ready} onClick={() => perform(`run/${s.key}`)}>Run stage</button>
      </section>)}</div>
      <details className="panel"><summary>Import existing work</summary><form className="stack" onSubmit={e => {
        e.preventDefault(); const f = new FormData(e.currentTarget); void perform(`import/${f.get('kind')}`, {text: f.get('text'), filename: f.get('filename')});
      }}><label>Kind<select name="kind"><option value="papers">Papers (CSV, JSON, BibTeX)</option><option value="question">Research question</option><option value="gap_report">Gap report</option></select></label>
        <label>Filename<input name="filename" /></label><label>Content<textarea rows={10} name="text" required /></label><button disabled={running || action.busy}>Import</button></form></details>
      <details className="panel"><summary>Rebuild a stage and downstream results</summary>
        <div className="actions">{['hypotheses', 'plan', 'analysis', 'report', 'review'].map(s => <button key={s} disabled={running || action.busy} onClick={() => {
          if (window.confirm(`Rebuild ${s}? Its downstream results will be invalidated.`)) void perform(`redo/${s}`);
        }}>{s}</button>)}</div></details>
      <details className="panel"><summary>Evidence and saved artifacts</summary><DataView value={artifacts} /></details>
    </>}
    {tab === 'Papers' && <><DataView value={d.papers} /><h2>Gap analysis</h2><DataView value={d.gap_report} /></>}
    {tab === 'Hypotheses' && <DataView value={hypotheses.length ? hypotheses : d.hypotheses} />}
    {tab === 'Code & results' && <><h2>Code</h2>{d.code_files.map(f => <details className="panel" key={f.file_path}><summary>{f.file_path}</summary><pre>{f.content}</pre></details>)}
      <h2>Experiment runs</h2><DataView value={d.runs} /><h2>Checked results</h2><DataView value={artifacts.results?.content} /><h2>Claims</h2><DataView value={artifacts.claims?.content} />
      <button disabled={action.busy} onClick={() => action.run(async () => {setSavedReport(await send(`${base}/report`)); setTab('Report');}, 'Report generated.')}>Generate report</button></>}
    {tab === 'Report' && <><div className="actions">
      <button disabled={action.busy || running} onClick={() => action.run(async () => {setSavedReport(await send(`${base}/report`)); await refresh();}, 'Report generated.')}>Generate / refresh report</button>
      {['markdown', 'latex', 'pdf'].map(format => <button key={format} disabled={action.busy} onClick={() => action.run(() => download(`${base}/report/${format}`, `report.${format}`), 'Downloaded.')}>{format}</button>)}
    </div><DataView value={savedReport || artifacts.report?.content || d.report} /></>}
    {tab === 'Log' && <><p>Connection: {socket.connection}. Live log is limited to the latest 1,000 received events; saved artifacts remain available after reconnect.</p>
      <div className="log" role="log">{socket.events.map((e, i) => <div key={i}><strong>{e.type}</strong><DataView value={e.data} /></div>)}</div></>}
    {tab === 'Settings' && <><ModelForm sessionId={sessionId} />
      <form className="panel stack" key={d.session.updated_at} onSubmit={e => {e.preventDefault(); const f = new FormData(e.currentTarget);
        void perform('details', Object.fromEntries(f), 'PATCH');
      }}><h2>Research brief</h2>{['topic', 'background', 'goals', 'constraints'].map(name => <label key={name}>{name}<textarea name={name} required={name === 'topic'} defaultValue={String(d.session[name] || '')} /></label>)}<button disabled={action.busy || running}>Save brief</button></form>
      <form className="panel stack" onSubmit={e => {e.preventDefault(); void perform('project', {project_id: new FormData(e.currentTarget).get('project')});}}>
        <label>Project<select name="project" defaultValue={String(d.session.project_id || '')}><option value="">Unfiled</option>{projects.data?.projects.map(p => <option key={p.project_id} value={p.project_id}>{p.name}</option>)}</select></label>
        <button disabled={action.busy}>Move session</button><p role="alert">{projects.error}</p>
      </form>
      <button disabled={action.busy || running} onClick={() => {if (window.confirm('Remove this session? The server stores a recovery copy.')) void action.run(async () => {
        await send(base, {}, 'DELETE'); navigate('/app');
      }, '');}}>Remove session</button>
    </>}
  </>;
}
