import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';

export function useResource<T>(path: string | null, interval = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const controller = useRef<AbortController | null>(null);
  const reload = useCallback(async () => {
    if (!path) { setLoading(false); return; }
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    try {
      const value = await api<T>(path, { signal: next.signal });
      if (!next.signal.aborted) { setData(value); setError(''); }
    } catch (e) {
      if (!next.signal.aborted) setError(e instanceof Error ? e.message : String(e));
    } finally { if (!next.signal.aborted) setLoading(false); }
  }, [path]);
  useEffect(() => {
    setData(null); setLoading(true); void reload();
    const timer = interval ? window.setInterval(reload, interval) : undefined;
    return () => { controller.current?.abort(); clearInterval(timer); };
  }, [reload, interval]);
  return { data, error, loading, reload };
}

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const locked = useRef(false);
  const run = async (fn: () => Promise<unknown>, success = 'Saved.') => {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError(''); setMessage('');
    try { await fn(); setMessage(success); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { locked.current = false; setBusy(false); }
  };
  return { busy, error, message, run };
}
