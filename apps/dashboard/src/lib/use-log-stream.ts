"use client";

import { useEffect, useRef, useState } from "react";

import { wsUrl } from "@/lib/api";

export type StreamMessage = Record<string, unknown> & { message?: string };

/**
 * Subscribes to a WebSocket log stream. Auto-reconnects with backoff while
 * `enabled` stays true. Cookie auth is applied by the browser automatically.
 */
export function useLogStream(
  path: string | null,
  { enabled = true, maxLines = 1000 }: { enabled?: boolean; maxLines?: number } = {},
) {
  const [lines, setLines] = useState<StreamMessage[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!path || !enabled) {
      setConnected(false);
      return;
    }
    let closed = false;
    let attempts = 0;

    const connect = () => {
      if (closed) return;
      const ws = new WebSocket(wsUrl(path));
      wsRef.current = ws;
      ws.onopen = () => {
        attempts = 0;
        setConnected(true);
      };
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as StreamMessage;
          setLines((prev) => {
            const next = [...prev, data];
            return next.length > maxLines ? next.slice(next.length - maxLines) : next;
          });
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) {
          attempts += 1;
          retryRef.current = setTimeout(connect, Math.min(1000 * attempts, 10000));
        }
      };
      ws.onerror = () => ws.close();
    };

    setLines([]);
    connect();
    return () => {
      closed = true;
      if (retryRef.current) clearTimeout(retryRef.current);
      wsRef.current?.close();
      setConnected(false);
    };
  }, [path, enabled, maxLines]);

  return { lines, connected, clear: () => setLines([]) };
}
