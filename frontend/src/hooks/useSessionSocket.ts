import { useEffect, useRef, useState } from 'react';
import { sessionSocketUrl } from '../api/client';

export type RunnerEvent = {
  type: string;
  data?: Record<string, unknown>;
};

export function useSessionSocket(sessionId: string | undefined, enabled: boolean) {
  const [events, setEvents] = useState<RunnerEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!sessionId || !enabled) return;
    const socket = new WebSocket(sessionSocketUrl(sessionId));
    socketRef.current = socket;

    socket.onopen = () => setConnected(true);
    socket.onmessage = (event) => {
      try {
        setEvents((current) => [...current, JSON.parse(event.data) as RunnerEvent]);
      } catch {
        setEvents((current) => [...current, { type: 'log', data: { message: event.data } }]);
      }
    };
    socket.onclose = () => setConnected(false);
    socket.onerror = () => setConnected(false);

    return () => {
      socket.close();
      socketRef.current = null;
    };
  }, [sessionId, enabled]);

  return { events, connected };
}
