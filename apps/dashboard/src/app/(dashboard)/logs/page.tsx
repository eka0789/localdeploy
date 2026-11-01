"use client";

import { useQuery } from "@tanstack/react-query";
import { Terminal } from "lucide-react";
import { useEffect, useRef } from "react";

import { Topbar } from "@/components/layout";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { api } from "@/lib/api";
import { useLogStream } from "@/lib/use-log-stream";

export default function LogsPage() {
  const { data } = useQuery<{ logs: Array<{ message: string; level?: string }> }>({
    queryKey: ["logs", "system"],
    queryFn: () => api("/api/logs/system?limit=100"),
  });

  const { lines, connected } = useLogStream("/api/logs/system/stream");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [lines.length]);

  const historical = data?.logs ?? [];

  return (
    <>
      <Topbar
        title="System logs"
        description="Platform events: deployments, container actions, tunnels, security"
        actions={<Badge variant={connected ? "success" : "warning"}>{connected ? "live" : "connecting…"}</Badge>}
      />
      <div className="p-8">
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>Event stream</CardTitle>
            <Terminal className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="log-view max-h-[600px] min-h-[400px] overflow-y-auto rounded-lg bg-black/80 p-4 text-green-100">
              {historical.map((log, i) => (
                <div key={`h-${i}`} className="text-gray-300">{log.message}</div>
              ))}
              {lines.map((line, i) => (
                <div key={`l-${i}`} className={line.level === "success" ? "text-green-300" : line.level === "info" ? "text-sky-300" : "text-gray-200"}>
                  {line.message}
                </div>
              ))}
              {!historical.length && !lines.length && (
                <div className="text-gray-500">No events yet — they appear here as the platform works.</div>
              )}
              <div ref={bottomRef} />
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
