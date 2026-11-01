"use client";

/**
 * Interactive container terminal over WebSocket (docker exec).
 * Uses xterm.js for a real terminal experience.
 */
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui";
import { API_URL } from "@/lib/api";
import { wsUrl } from "@/lib/api";

export function ContainerTerminal({ appId }: { appId: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: 'ui-monospace, "JetBrains Mono", Consolas, monospace',
      theme: {
        background: "#0a0e14",
        foreground: "#d8e0ea",
        cursor: "#4ade80",
        selectionBackground: "#334155",
      },
    });
    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    if (containerRef.current) {
      term.open(containerRef.current);
      try { fitAddon.fit(); } catch { /* zero-size container */ }
    }
    term.writeln("\x1b[36mLocalDeploy terminal\x1b[0m — connecting to container shell...");

    const ws = new WebSocket(wsUrl(`/api/applications/${appId}/terminal`));
    wsRef.current = ws;
    ws.onopen = () => {
      setConnected(true);
      term.writeln("\x1b[32mConnected.\x1b[0m");
    };
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.data) term.write(data.data);
      } catch { /* ignore */ }
    };
    ws.onclose = () => {
      setConnected(false);
      term.writeln("\r\n\x1b[33m[session closed]\x1b[0m");
    };
    ws.onerror = () => term.writeln("\r\n\x1b[31m[connection error — is the container running?]\x1b[0m");

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ data }));
    });
    const onResize = () => {
      try { fitAddon.fit(); } catch { return; }
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      }
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      ws.close();
      term.dispose();
    };
  }, [appId]);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Badge variant={connected ? "success" : "warning"}>
          {connected ? "attached" : "disconnected"}
        </Badge>
        <p className="text-xs text-muted-foreground">
          Shell di dalam container — jangan jalankan perintah destruktif pada PID 1.
        </p>
      </div>
      <div ref={containerRef} className="overflow-hidden rounded-lg border border-border" style={{ minHeight: 420 }} />
    </div>
  );
}
