import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { send, type SessionSummary } from '../../api/client';
import { useAction, useResource } from '../../hooks/useResource';
import DataView from '../../components/DataView';

type Project = {project_id: string; name: string; description: string; archived: boolean; sessions: number; papers: number; spend_usd: number};
export default function Projects() {
  const resource = useResource<{projects: Project[]}>('/api/projects?include_archived=true');
  const action = useAction();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  return <><h1>Projects</h1>
    <form className="panel stack" onSubmit={e => {e.preventDefault(); void action.run(async () => {
      await send('/api/projects', {name, description}); setName(''); setDescription(''); await resource.reload();
    });}}>
      <label>Name<input required value={name} onChange={e => setName(e.target.value)} /></label>
      <label>Description<textarea value={description} onChange={e => setDescription(e.target.value)} /></label>
      <button disabled={action.busy}>Create project</button>
    </form>
    <p role="alert">{resource.error || action.error}</p>
    {resource.loading && <p>Loading…</p>}
    <div className="stack">{resource.data?.projects.map(p => <div className="panel" key={p.project_id}>
      <Link to={`/app/projects/${p.project_id}`}><h2>{p.name}</h2></Link><p>{p.description}</p>
      <p>{p.sessions} sessions · {p.papers} papers · ${p.spend_usd} {p.archived && '· Archived'}</p>
      <button disabled={action.busy} onClick={() => action.run(async () => {
        await send(`/api/projects/${p.project_id}`, {archived: !p.archived}, 'PATCH'); await resource.reload();
      })}>{p.archived ? 'Restore' : 'Archive'}</button>
    </div>)}</div>
    {resource.data?.projects.length === 0 && <p>No projects yet.</p>}
  </>;
}

export function ProjectView() {
  const {projectId} = useParams();
  const path = `/api/projects/${encodeURIComponent(projectId!)}`;
  const resource = useResource<{project: Project}>(`${path}/graph`);
  const sessions = useResource<{sessions: (SessionSummary & {project_id?: string})[]}>('/api/sessions');
  const papers = useResource<{papers: unknown[]}>(`${path}/papers`);
  const action = useAction();
  return <><header><h1>{resource.data?.project.name || 'Project'}</h1><Link className="button" to={`/app/projects/${projectId}/sessions/new`}>New session</Link></header>
    <p role="alert">{resource.error || sessions.error || papers.error || action.error}</p>
    {resource.data && <form key={resource.data.project.name + resource.data.project.description} className="panel stack" onSubmit={e => {
      e.preventDefault(); const form = new FormData(e.currentTarget);
      void action.run(async () => {await send(path, {name: form.get('name'), description: form.get('description')}, 'PATCH'); await resource.reload();});
    }}><label>Name<input name="name" required defaultValue={resource.data.project.name} /></label>
      <label>Description<textarea name="description" defaultValue={resource.data.project.description} /></label><button disabled={action.busy}>Save</button></form>}
    <h2>Sessions</h2><div className="stack">{sessions.data?.sessions.filter(s => s.project_id === projectId).map(s =>
      <Link className="panel" key={s.session_id} to={`/app/sessions/${s.session_id}`}>{s.topic} · {s.status}</Link>)}</div>
    <h2>Papers</h2><DataView value={papers.data?.papers} />
  </>;
}
