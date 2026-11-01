"use client";

import { useQuery } from "@tanstack/react-query";

import { ResourceChart } from "@/components/charts";
import { Topbar } from "@/components/layout";
import { Card, CardContent, CardHeader, CardTitle, Skeleton, StatusBadge, TD, TBody, TH, THead, TR, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtBps, fmtMb, fmtUptime } from "@/lib/format";
import type { AppMetric, ServerMetricPoint, ServerSnapshot } from "@/lib/types";

export default function MonitoringPage() {
  const { data: server } = useQuery<ServerSnapshot>({
    queryKey: ["monitoring", "server"],
    queryFn: () => api("/api/monitoring/server"),
    refetchInterval: 5_000,
  });

  const { data: history } = useQuery<ServerMetricPoint[]>({
    queryKey: ["monitoring", "history", 24],
    queryFn: () => api("/api/monitoring/server/history?hours=24"),
    refetchInterval: 30_000,
  });

  const { data: apps } = useQuery<{ applications: AppMetric[] }>({
    queryKey: ["monitoring", "applications"],
    queryFn: () => api("/api/monitoring/applications"),
    refetchInterval: 10_000,
  });

  const chartData = (history ?? []).map((point) => ({
    t: new Date(point.sampled_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }),
    cpu: point.cpu_percent,
    memory: point.memory_percent,
    disk: point.disk_percent,
  }));

  return (
    <>
      <Topbar
        title="Monitoring"
        description={server ? `Uptime ${fmtUptime(server.uptime_seconds)} · ${server.platform}` : "Real server metrics — never simulated"}
      />
      <div className="space-y-6 p-8">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <MetricCard label="CPU" value={`${server?.cpu_percent.toFixed(1) ?? "—"}%`} detail={`${server?.cpu_count ?? "?"} cores · load ${server?.load_1?.toFixed(2) ?? "—"}`} />
          <MetricCard label="Memory" value={`${server?.memory_percent.toFixed(1) ?? "—"}%`} detail={`${fmtMb(server?.memory_used_mb)} / ${fmtMb(server?.memory_total_mb)}`} />
          <MetricCard label="Swap" value={`${server?.swap_percent.toFixed(0) ?? "—"}%`} detail="virtual memory" />
          <MetricCard label="Network" value={`↓ ${fmtBps(server?.net_rx_bps)}`} detail={`↑ ${fmtBps(server?.net_tx_bps)}`} />
        </div>

        <Card>
          <CardHeader><CardTitle>Resource history (24h)</CardTitle></CardHeader>
          <CardContent>
            {!history?.length ? (
              <Skeleton className="h-64" />
            ) : (
              <ResourceChart
                data={chartData}
                percent
                height={300}
                series={[
                  { key: "cpu", label: "CPU %", color: "hsl(160 74% 42%)" },
                  { key: "memory", label: "Memory %", color: "hsl(217 91% 58%)" },
                  { key: "disk", label: "Disk %", color: "hsl(38 92% 50%)" },
                ]}
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Application resources</CardTitle></CardHeader>
          <CardContent className="px-0">
            {!apps?.applications.length ? (
              <p className="px-5 py-6 text-sm text-muted-foreground">No managed applications running.</p>
            ) : (
              <Table>
                <THead>
                  <TH>Application</TH><TH>Status</TH><TH>CPU</TH><TH>Memory</TH><TH>Network I/O</TH>
                </THead>
                <TBody>
                  {apps.applications.map((app) => (
                    <TR key={app.application_id}>
                      <TD className="font-medium">{app.name}</TD>
                      <TD><StatusBadge status={app.status} /></TD>
                      <TD>{app.cpu_percent.toFixed(2)}%</TD>
                      <TD>
                        {fmtMb(app.memory_usage_mb)}
                        {app.memory_limit_mb > 0 && (
                          <span className="text-muted-foreground"> / {fmtMb(app.memory_limit_mb)}</span>
                        )}
                      </TD>
                      <TD className="text-muted-foreground">
                        ↓ {fmtBps(app.net_rx_bytes)} · ↑ {fmtBps(app.net_tx_bytes)}
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function MetricCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <Card>
      <CardContent className="p-5">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="mt-1 text-2xl font-semibold tracking-tight">{value}</p>
        <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
      </CardContent>
    </Card>
  );
}
