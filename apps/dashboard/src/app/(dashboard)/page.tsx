"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Cpu,
  HardDrive,
  MemoryStick,
  Rocket,
} from "lucide-react";
import Link from "next/link";

import { ResourceChart } from "@/components/charts";
import { Topbar } from "@/components/layout";
import { Badge, Card, CardContent, CardHeader, CardTitle, Skeleton, StatusBadge, TD, THead, TH, TR, Table, TBody } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtBps, fmtDuration, fmtMb, fmtUptime, relTime } from "@/lib/format";
import type { Overview, ServerMetricPoint } from "@/lib/types";

export default function OverviewPage() {
  const { data: overview, isLoading } = useQuery<Overview>({
    queryKey: ["overview"],
    queryFn: () => api("/api/overview"),
    refetchInterval: 10_000,
  });

  const { data: history } = useQuery<ServerMetricPoint[]>({
    queryKey: ["monitoring", "history", 6],
    queryFn: () => api("/api/monitoring/server/history?hours=6"),
    refetchInterval: 30_000,
  });

  if (isLoading || !overview) {
    return (
      <>
        <Topbar title="Overview" description="Platform health at a glance" />
        <div className="space-y-6 p-8">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28" />)}
          </div>
          <Skeleton className="h-72" />
        </div>
      </>
    );
  }

  const stats = [
    {
      label: "Applications", value: overview.applications.total,
      sub: `${overview.applications.running} running · ${overview.applications.stopped} stopped`,
      icon: Rocket, href: "/applications",
      alert: overview.applications.error > 0,
    },
    {
      label: "CPU", value: `${overview.server.cpu_percent.toFixed(0)}%`,
      sub: `${overview.server.cpu_count} cores · load ${overview.server.load_1?.toFixed(2) ?? "—"}`,
      icon: Cpu, href: "/monitoring",
    },
    {
      label: "Memory", value: `${overview.server.memory_percent.toFixed(0)}%`,
      sub: `${fmtMb(overview.server.memory_used_mb)} / ${fmtMb(overview.server.memory_total_mb)}`,
      icon: MemoryStick, href: "/monitoring",
    },
    {
      label: "Disk", value: `${overview.server.disk_percent.toFixed(0)}%`,
      sub: `${overview.server.disk_used_gb.toFixed(1)} / ${overview.server.disk_total_gb.toFixed(1)} GB`,
      icon: HardDrive, href: "/storage",
      alert: overview.server.disk_percent > 85,
    },
  ];

  const chartData = (history ?? []).map((point) => ({
    t: new Date(point.sampled_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }),
    cpu: point.cpu_percent,
    memory: point.memory_percent,
    network_in: point.net_rx_bps / 1024,
    network_out: point.net_tx_bps / 1024,
  }));

  return (
    <>
      <Topbar
        title="Overview"
        description={`Uptime ${fmtUptime(overview.server.uptime_seconds)} · ${overview.server.platform}`}
      />
      <div className="space-y-6 p-8">
        {/* Stat widgets */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {stats.map((stat) => (
            <Link key={stat.label} href={stat.href}>
              <Card className="transition-shadow hover:shadow-md">
                <CardContent className="flex items-start justify-between p-5">
                  <div>
                    <p className="text-sm text-muted-foreground">{stat.label}</p>
                    <p className="mt-1 text-2xl font-semibold tracking-tight">{stat.value}</p>
                    <p className="mt-1 text-xs text-muted-foreground">{stat.sub}</p>
                  </div>
                  <div className={`rounded-lg p-2 ${stat.alert ? "bg-destructive/15 text-destructive" : "bg-primary/10 text-primary"}`}>
                    <stat.icon className="h-5 w-5" />
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>

        {/* Failure banner */}
        {overview.deployments_failed_24h > 0 && (
          <div className="flex items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm">
            <AlertTriangle className="h-5 w-5 text-destructive" />
            <span>
              <strong>{overview.deployments_failed_24h}</strong> deployment(s) failed in the last 24 hours —{" "}
              <Link href="/deployments?status=failed" className="underline">review them</Link>
            </span>
          </div>
        )}

        {/* Charts */}
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle>CPU & Memory (6h)</CardTitle>
              <Badge variant="outline">live sample</Badge>
            </CardHeader>
            <CardContent>
              <ResourceChart
                data={chartData}
                percent
                series={[
                  { key: "cpu", label: "CPU %", color: "hsl(160 74% 42%)" },
                  { key: "memory", label: "Memory %", color: "hsl(217 91% 58%)" },
                ]}
              />
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle>Network traffic (6h)</CardTitle>
              <Badge variant="outline">KB/s</Badge>
            </CardHeader>
            <CardContent>
              <ResourceChart
                data={chartData}
                formatter={(v) => `${v.toFixed(0)} KB/s`}
                series={[
                  { key: "network_in", label: "In", color: "hsl(38 92% 50%)" },
                  { key: "network_out", label: "Out", color: "hsl(271 76% 53%)" },
                ]}
              />
            </CardContent>
          </Card>
        </div>

        {/* Recent deployments + activity */}
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle>Recent deployments</CardTitle>
              <Link href="/deployments" className="flex items-center gap-1 text-sm text-primary hover:underline">
                View all <ArrowUpRight className="h-3.5 w-3.5" />
              </Link>
            </CardHeader>
            <CardContent className="px-0">
              {overview.recent_deployments.length === 0 ? (
                <p className="px-5 py-6 text-sm text-muted-foreground">
                  No deployments yet. <Link href="/applications" className="text-primary underline">Create your first application</Link>.
                </p>
              ) : (
                <Table>
                  <THead>
                    <TH>Application</TH>
                    <TH>Status</TH>
                    <TH>Trigger</TH>
                    <TH>Duration</TH>
                    <TH>When</TH>
                  </THead>
                  <TBody>
                    {overview.recent_deployments.map((d) => (
                      <TR key={d.id}>
                        <TD>
                          <Link href={`/applications/${d.application_id}`} className="font-medium hover:underline">
                            {d.application_name}
                          </Link>
                          {d.git_message && (
                            <div className="max-w-xs truncate text-xs text-muted-foreground">{d.git_message}</div>
                          )}
                        </TD>
                        <TD><StatusBadge status={d.status} /></TD>
                        <TD className="text-muted-foreground">{d.trigger}</TD>
                        <TD className="text-muted-foreground">{fmtDuration(d.build_duration_ms)}</TD>
                        <TD className="text-muted-foreground">{relTime(d.created_at)}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle>Recent activity</CardTitle>
              <Activity className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent className="space-y-3">
              {overview.recent_activity.length === 0 && (
                <p className="text-sm text-muted-foreground">No activity recorded yet.</p>
              )}
              {overview.recent_activity.map((a, i) => (
                <div key={i} className="flex items-start gap-2.5 text-sm">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary/60" />
                  <div className="min-w-0">
                    <div className="truncate">
                      <span className="font-medium">{a.action}</span>
                      {a.username && <span className="text-muted-foreground"> · {a.username}</span>}
                    </div>
                    <div className="text-xs text-muted-foreground">{relTime(a.created_at)}</div>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
