import { useState } from 'react';
import { useResource } from '../../hooks/useResource';
import DataView from '../../components/DataView';
import type { SessionDetail, SessionSummary } from '../../api/client';

export default function Library() {
  const sessions = useResource<{sessions: SessionSummary[]}>('/api/sessions');
  const [selected, setSelected] = useState('');
  const id = selected || sessions.data?.sessions[0]?.session_id;
  const detail = useResource<SessionDetail>(id ? `/api/sessions/${encodeURIComponent(id)}` : null);
  return <><h1>Paper library</h1><label>Research session<select value={id || ''} onChange={e => setSelected(e.target.value)}>
    <option value="">Choose session</option>{sessions.data?.sessions.map(s => <option key={s.session_id} value={s.session_id}>{s.topic}</option>)}
  </select></label><p role="alert">{sessions.error || detail.error}</p>
    {detail.loading && id ? <p>Loading…</p> : <DataView value={detail.data?.papers || []} />}</>;
}
