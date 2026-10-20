import { useEffect, useState } from 'react';
import { sessionSocketUrl } from '../api/client';

export type RunnerEvent = {type: string; data?: Record<string, unknown>};
export function useSessionSocket(sessionId: string | undefined, enabled: boolean) {
  const [events, setEvents] = useState<RunnerEvent[]>([]);
  const [connection, setConnection] = useState('idle');
  useEffect(() => {setEvents([]);}, [sessionId]);
  useEffect(() => {
    if (!sessionId || !enabled) {setConnection('idle'); return;}
    let closed = false, retry = 0, timer: ReturnType<typeof setTimeout>;
    let socket: WebSocket;
    const connect = () => {
      if (closed) return;
      setConnection('connecting');
      socket = new WebSocket(sessionSocketUrl(sessionId));
      socket.onopen = () => {if (!closed) {setConnection('connected'); retry = 0;}};
      socket.onmessage = event => {
        if (closed) return;
        try {
          const parsed = JSON.parse(event.data) as RunnerEvent;
          setEvents(current => [...current, parsed].slice(-1000));
          if (parsed.type === 'done' || (parsed.type === 'error' && String(parsed.data?.message).includes('No active runner'))) {
            closed = true; setConnection('finished'); socket.close();
          }
        } catch { setConnection('invalid event'); }
      };
      socket.onclose = event => {
        if (closed) return;
        if (event.code === 1008) {setConnection('authentication required'); return;}
        setConnection('reconnecting');
        timer = setTimeout(connect, Math.min(1000 * 2 ** retry++, 15000));
      };
      socket.onerror = () => socket.close();
    };
    connect();
    return () => {closed = true; clearTimeout(timer); socket?.close();};
  }, [sessionId, enabled]);
  return {events, connected: connection === 'connected', connection};
}
