import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { createSession } from '../../api/client';
import { useAction } from '../../hooks/useResource';

export default function NewSession() {
  const {projectId} = useParams();
  const navigate = useNavigate();
  const action = useAction();
  const [start, setStart] = useState(true);
  return <><h1>New research session</h1>
    <p>Uses your <Link to="/app/settings/api">model settings</Link>. Research pauses at approval gates.</p>
    <form className="panel stack" onSubmit={e => {
      e.preventDefault(); const form = new FormData(e.currentTarget);
      void action.run(async () => {
        const session = await createSession({topic: String(form.get('topic')), background: String(form.get('background')),
          goals: String(form.get('goals')), constraints: String(form.get('constraints')), project_id: projectId || '', autostart: start});
        navigate(`/app/sessions/${session.session_id}`);
      }, '');
    }}>
      {['topic', 'background', 'goals', 'constraints'].map(name => <label key={name}>{name}
        <textarea name={name} required={name === 'topic'} rows={name === 'topic' ? 2 : 3} /></label>)}
      <label className="check"><input type="checkbox" checked={start} onChange={e => setStart(e.target.checked)} />Start after creating (otherwise import work or run individual stages)</label>
      <button disabled={action.busy}>{action.busy ? 'Creating…' : 'Create session'}</button>
    </form><p role="alert">{action.error}</p></>;
}
