import { useState } from 'react';
import { send } from '../../api/client';
import { useAction, useResource } from '../../hooks/useResource';
import DataView from '../../components/DataView';

export type Settings = {hosted: boolean; use_api: boolean; api_provider: string; api_model: string; inference_mode: string;
  effective_provider: string; effective_model: string; local_server_url: string; daily_budget_usd: number; budget_editable: boolean;
  providers: {name: string; label: string; default_model?: string}[]; route_history: unknown[]};
type Credential = {credential_id: string; provider: string; label: string; hint: string; enabled: boolean; is_default: boolean; verification_status: string};

export function ModelForm({sessionId}: {sessionId?: string}) {
  const path = `/api/settings${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''}`;
  const resource = useResource<Settings>(path);
  const action = useAction();
  const settings = resource.data;
  return <section className="panel"><h2>{sessionId ? 'Session model settings' : 'Model settings'}</h2>
    <p role="alert">{resource.error || action.error}</p>
    {settings && <form className="stack" key={`${settings.use_api}-${settings.api_provider}-${settings.api_model}`} onSubmit={e => {
      e.preventDefault(); const f = new FormData(e.currentTarget);
      void action.run(async () => {
        await send('/api/settings', {session_id: sessionId || '', use_api: f.has('enabled'),
          api_provider: f.get('provider'), api_model: f.get('model'),
          ...(settings.budget_editable && !sessionId ? {daily_budget_usd: Number(f.get('budget')), local_server_url: f.get('server')} : {})});
        await resource.reload();
      });
    }}>
      <label className="check"><input type="checkbox" name="enabled" defaultChecked={settings.use_api} />Enable model API</label>
      <p className="muted">{settings.use_api ? `Route: ${settings.inference_mode} · ${settings.effective_provider} ${settings.effective_model}` :
        settings.hosted ? 'Model API is off. Hosted model-dependent stages will pause.' : 'External model API is off. A loaded Ollama/GGUF model is required.'}</p>
      <label>Provider<select name="provider" defaultValue={settings.api_provider} onChange={e => {
        const input = e.currentTarget.form?.elements.namedItem('model') as HTMLInputElement | null;
        if (input) input.value = settings.providers.find(p => p.name === e.target.value)?.default_model || '';
      }}>
        {settings.providers.map(p => <option key={p.name} value={p.name}>{p.label || p.name}</option>)}</select></label>
      <label>Model<input name="model" defaultValue={settings.api_model} /></label>
      <p className="muted">When changing provider, enter its model ID or clear the field to use its default.</p>
      {settings.budget_editable && !sessionId && <><label>Daily budget (USD; 0 = unlimited)<input name="budget" type="number" min="0" step="0.01" defaultValue={settings.daily_budget_usd} /></label>
        <label>OpenAI-compatible local server<input name="server" defaultValue={settings.local_server_url} placeholder="http://localhost:1234/v1" /></label></>}
      <button disabled={action.busy}>Save model settings</button><p role="status">{action.message}</p>
    </form>}
    {settings && <details><summary>Recent model routes</summary><DataView value={settings.route_history} /></details>}
  </section>;
}

export default function ModelSettings() {
  const settings = useResource<Settings>('/api/settings');
  const credentials = useResource<{credentials: Credential[]}>('/api/account/credentials');
  const action = useAction();
  const [key, setKey] = useState('');
  const [provider, setProvider] = useState('openai');
  const [replacement, setReplacement] = useState('');
  return <><h1>Models & API keys</h1><ModelForm />
    <h2>Stored credentials</h2><p role="alert">{settings.error || credentials.error || action.error}</p><p role="status">{action.message}</p>
    <div className="stack">{credentials.data?.credentials.map(c => <section className="panel" key={c.credential_id}>
      <h3>{c.provider} · {c.label}</h3><p>{c.hint} · {c.verification_status}{c.is_default ? ' · Default' : ''}</p>
      <div className="actions">
        <button disabled={action.busy} onClick={() => action.run(async () => {await send(`/api/account/credentials/${c.credential_id}`, {enabled: !c.enabled}, 'PATCH'); await credentials.reload();})}>{c.enabled ? 'Disable' : 'Enable'}</button>
        <button disabled={action.busy || c.is_default} onClick={() => action.run(async () => {await send(`/api/account/credentials/${c.credential_id}`, {make_default: true}, 'PATCH'); await credentials.reload();})}>Make default</button>
        <button disabled={action.busy} onClick={() => action.run(async () => {
          const result = await send(`/api/account/credentials/${c.credential_id}/test`);
          await credentials.reload();
          if (result.status === 'untested') throw new Error(String(result.detail));
        }, 'Credential verified.')}>Test</button>
        <button disabled={action.busy} onClick={() => {if (window.confirm(`Delete ${c.label}?`)) void action.run(async () => {
          await send(`/api/account/credentials/${c.credential_id}`, {}, 'DELETE'); await credentials.reload();
        }, 'Credential deleted.');}}>Delete</button>
        <button onClick={() => {setReplacement(c.credential_id); setKey(''); setProvider(c.provider);}}>Replace secret</button>
      </div>
    </section>)}</div>
    <form className="panel stack" onSubmit={e => {
      e.preventDefault(); const form = new FormData(e.currentTarget);
      void action.run(async () => {
        if (replacement) await send(`/api/account/credentials/${replacement}/secret`, {key, base_url: form.get('base_url') || ''}, 'PUT');
        else await send('/api/account/credentials', {provider, label: form.get('label'), key, base_url: form.get('base_url') || ''});
        setKey(''); setReplacement(''); await credentials.reload();
      });
    }}>
      <h2>{replacement ? 'Replace secret' : 'Add credential'}</h2>
      {!replacement && <><label>Provider<select value={provider} onChange={e => setProvider(e.target.value)}>
        {settings.data?.providers.filter(p => !['auto_byok', 'local_server'].includes(p.name)).map(p => <option key={p.name} value={p.name}>{p.label || p.name}</option>)}</select></label>
        <label>Label<input name="label" required defaultValue="Default" /></label></>}
      <label>Secret key<input type="password" autoComplete="off" required value={key} onChange={e => setKey(e.target.value)} /></label>
      {provider === 'freellmapi' && <label>Gateway URL<input name="base_url" type="url" required /></label>}
      <div className="actions"><button disabled={action.busy}>Save credential</button>{replacement && <button type="button" onClick={() => {setReplacement(''); setKey('');}}>Cancel</button>}</div>
    </form>
  </>;
}

type LocalModels = {host: string; reachable: boolean; problem: string; installed: {name: string}[];
  chosen: {model: string; embed_model: string; num_ctx: number}};
export function LocalRunner() {
  const settings = useResource<Settings>('/api/settings');
  const local = useResource<LocalModels>(settings.data && !settings.data.hosted ? '/api/local-models' : null);
  const action = useAction();
  return <><h1>Local models</h1><p role="alert">{settings.error || local.error || action.error}</p>
    {settings.data?.hosted ? <p>Local models are unavailable in hosted mode.</p> : local.data && <>
      <p>{local.data.reachable ? 'Ollama reachable' : 'Ollama unavailable'} · {local.data.host}</p><p>{local.data.problem}</p>
      <button onClick={local.reload}>Refresh models</button>
      <form key={JSON.stringify(local.data.chosen)} className="panel stack" onSubmit={e => {
        e.preventDefault(); const form = new FormData(e.currentTarget);
        void action.run(async () => {
          await send('/api/local-models', {model: form.get('model'), embed_model: form.get('embed_model'), num_ctx: Number(form.get('num_ctx'))});
          await local.reload();
        }, 'Saved. New runs use this model; active runs keep their loaded model.');
      }}>
        <datalist id="installed-models">{local.data.installed.map(m => <option key={m.name} value={m.name} />)}</datalist>
        <label>Chat model<input name="model" list="installed-models" defaultValue={local.data.chosen.model} /></label>
        <label>Embedding model<input name="embed_model" list="installed-models" defaultValue={local.data.chosen.embed_model} /></label>
        <label>Context tokens<input name="num_ctx" type="number" min="512" max="1000000" defaultValue={local.data.chosen.num_ctx} /></label>
        <button disabled={action.busy}>Save local model</button><p role="status">{action.message}</p>
      </form><ModelForm />
    </>}
  </>;
}
