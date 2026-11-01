"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Copy, Eye, EyeOff, Globe, KeyRound, Pause, Play, Plus, RotateCcw,
  Rocket, Settings2, Terminal, Trash2,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Topbar } from "@/components/layout";
import { AppDatabaseLinks } from "@/components/external-db";
import { ContainerTerminal } from "@/components/container-terminal";
import { ResourceChart } from "@/components/charts";
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, ConfirmDialog, Dialog, EmptyState,
  Input, Label, Select, Skeleton, StatusBadge, Switch, TD, TBody, TH, THead, TR, Table, Textarea,
} from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate, fmtDuration, relTime } from "@/lib/format";
import { useLogStream } from "@/lib/use-log-stream";
import type { Application, ApplicationDetail, Deployment, Domain, EnvVar } from "@/lib/types";

type Tab = "overview" | "deployments" | "domains" | "databases" | "terminal" | "env" | "logs" | "settings";

export default function ApplicationDetailPage() {
  const params = useParams<{ id: string }>();
  const appId = params.id;
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("overview");

  const { data: app, isLoading } = useQuery<ApplicationDetail>({
    queryKey: ["application", appId],
    queryFn: () => api(`/api/applications/${appId}`),
    refetchInterval: 10_000,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["application", appId] });
    queryClient.invalidateQueries({ queryKey: ["applications"] });
  };

  const action = useMutation({
    mutationFn: (act: "start" | "stop" | "restart" | "deploy") =>
      api(`/api/applications/${appId}/${act}`, { method: "POST" }),
    onSuccess: (_data, act) => {
      toast.success(act === "deploy" ? "Deployment queued" : `Container ${act}ed`);
      invalidate();
      if (act === "deploy") setTab("deployments");
    },
    onError: (e) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: () => api(`/api/applications/${appId}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Application deleted");
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      window.location.href = "/applications";
    },
    onError: (e) => toast.error(e.message),
  });

  if (isLoading || !app) {
    return (
      <>
        <Topbar title="Application" />
        <div className="space-y-4 p-8">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-24" />)}</div>
      </>
    );
  }

  const tabs: Array<{ id: Tab; label: string; icon: React.ComponentType<{ className?: string }> }> = [
    { id: "overview", label: "Overview", icon: Rocket },
    { id: "deployments", label: "Deployments", icon: RotateCcw },
    { id: "domains", label: "Domains", icon: Globe },
    { id: "databases", label: "Databases", icon: KeyRound },
    { id: "env", label: "Environment", icon: KeyRound },
    { id: "terminal", label: "Terminal", icon: Terminal },
    { id: "logs", label: "Logs", icon: Terminal },
    { id: "settings", label: "Settings", icon: Settings2 },
  ];

  const busy = action.isPending;

  return (
    <>
      <Topbar
        title={app.name}
        description={`${app.slug} · ${app.source_type}${app.project_type ? ` · ${app.project_type}` : ""}`}
        actions={
          <div className="flex items-center gap-2">
            <StatusBadge status={app.status} />
            <Button variant="outline" size="sm" onClick={() => action.mutate("start")} disabled={busy}>
              <Play className="h-3.5 w-3.5" /> Start
            </Button>
            <Button variant="outline" size="sm" onClick={() => action.mutate("stop")} disabled={busy}>
              <Pause className="h-3.5 w-3.5" /> Stop
            </Button>
            <Button variant="outline" size="sm" onClick={() => action.mutate("restart")} disabled={busy}>
              <RotateCcw className="h-3.5 w-3.5" /> Restart
            </Button>
            <Button size="sm" onClick={() => action.mutate("deploy")} loading={busy}>
              <Rocket className="h-3.5 w-3.5" /> Deploy
            </Button>
          </div>
        }
      />

      <div className="p-8">
        <div className="mb-6 flex gap-1 border-b border-border">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 border-b-2 px-4 py-2.5 text-sm transition-colors ${
                tab === t.id
                  ? "border-primary font-medium text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <t.icon className="h-4 w-4" /> {t.label}
            </button>
          ))}
        </div>

        {tab === "overview" && <OverviewTab app={app} appId={appId} onChanged={invalidate} />}
        {tab === "deployments" && <DeploymentsTab appId={appId} />}
        {tab === "domains" && <DomainsTab app={app} onChanged={invalidate} />}
        {tab === "databases" && <AppDatabaseLinks appId={appId} />}
        {tab === "env" && <EnvTab appId={appId} />}
        {tab === "terminal" && <ContainerTerminal appId={appId} />}
        {tab === "logs" && <LogsTab app={app} />}
        {tab === "settings" && <SettingsTab app={app} onChanged={invalidate} onDelete={() => remove.mutate()} />}
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ tabs */

function OverviewTab({ app, appId, onChanged }: { app: ApplicationDetail; appId: string; onChanged: () => void }) {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      return api(`/api/applications/${appId}/upload`, { method: "POST", formData });
    },
    onSuccess: () => {
      toast.success("Source archive uploaded — press Deploy to build it");
      setUploading(false);
      queryClient.invalidateQueries({ queryKey: ["application", appId] });
      onChanged();
    },
    onError: (e) => { toast.error(e.message); setUploading(false); },
  });

  return (
    <div className="space-y-4">
      {app.source_type === "upload" && (
        <Card className="border-primary/40">
          <CardHeader>
            <CardTitle>Source archive</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-3 text-sm text-muted-foreground">
              Upload a .zip / .tar.gz of your project. It replaces the previous archive and is built on the next Deploy.
            </p>
            <input
              ref={fileRef} type="file" accept=".zip,.tar.gz,.tgz,.tar" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) { setUploading(true); upload.mutate(f); } }}
            />
            <Button onClick={() => fileRef.current?.click()} loading={uploading}>
              <Plus className="h-4 w-4" /> Upload source (.zip / .tar.gz)
            </Button>
          </CardContent>
        </Card>
      )}
      <AppMetricsChart appId={appId} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Source</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            <Row label="Source type"><Badge variant="info">{app.source_type}</Badge></Row>
            {app.git_url && <Row label="Repository"><code className="break-all text-xs">{app.git_url}</code></Row>}
            {app.git_branch && <Row label="Branch">{app.git_branch}</Row>}
            {app.project_type && <Row label="Detected runtime"><Badge>{app.project_type}</Badge></Row>}
            {app.docker_image && <Row label="Image"><code className="text-xs">{app.docker_image}</code></Row>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Runtime</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            <Row label="Status"><StatusBadge status={app.status} /></Row>
            <Row label="Container">{app.container_name ?? "—"}</Row>
            <Row label="Container port">{app.container_port}</Row>
            <Row label="Health check path">{app.health_check_path ?? "/"}</Row>
            <Row label="Last deployed">{relTime(app.last_deployed_at)}</Row>
            <Row label="Domains">{app.domains.length ? app.domains.join(", ") : "none"}</Row>
            {(app.cpu_limit || app.memory_limit_mb) && (
              <Row label="Limits">{app.cpu_limit ? `${app.cpu_limit} vCPU` : "—"} · {app.memory_limit_mb ? `${app.memory_limit_mb} MB` : "—"}</Row>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function AppMetricsChart({ appId }: { appId: string }) {
  interface AppMetricPoint {
    sampled_at: string;
    cpu_percent: number;
    memory_usage_mb: number;
  }
  const { data: history } = useQuery<AppMetricPoint[]>({
    queryKey: ["app-metrics-history", appId],
    queryFn: () => api(`/api/monitoring/applications/${appId}/history?hours=6`),
    refetchInterval: 15_000,
  });
  const chartData = (history ?? []).map((point) => ({
    t: new Date(point.sampled_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }),
    cpu: point.cpu_percent,
    memory: point.memory_usage_mb,
  }));
  return (
    <Card>
      <CardHeader><CardTitle>Resource usage (6h)</CardTitle></CardHeader>
      <CardContent>
        {!history?.length ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No samples yet — metrics appear after the container has been running for a while.
          </p>
        ) : (
          <ResourceChart
            data={chartData}
            height={220}
            series={[
              { key: "cpu", label: "CPU %", color: "hsl(160 74% 42%)" },
              { key: "memory", label: "Memory MB", color: "hsl(217 91% 58%)" },
            ]}
          />
        )}
      </CardContent>
    </Card>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{children}</span>
    </div>
  );
}

function DeploymentsTab({ appId }: { appId: string }) {
  const { data: deployments } = useQuery<Deployment[]>({
    queryKey: ["deployments", appId],
    queryFn: () => api(`/api/deployments?application_id=${appId}`),
    refetchInterval: 5_000,
  });
  const [openId, setOpenId] = useState<string | null>(null);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>History</CardTitle></CardHeader>
        <CardContent className="px-0">
          {!deployments?.length ? (
            <p className="px-5 py-6 text-sm text-muted-foreground">No deployments yet — hit Deploy.</p>
          ) : (
            <Table>
              <THead>
                <TH>Status</TH><TH>Trigger</TH><TH>Commit</TH><TH>Duration</TH><TH>When</TH>
              </THead>
              <TBody>
                {deployments.map((d) => (
                  <TR key={d.id} className="cursor-pointer" onClick={() => setOpenId(d.id)}>
                    <TD><StatusBadge status={d.status} /></TD>
                    <TD className="text-muted-foreground">{d.trigger}</TD>
                    <TD><code className="text-xs">{d.git_commit_sha?.slice(0, 8) ?? "—"}</code></TD>
                    <TD className="text-muted-foreground">{fmtDuration(d.build_duration_ms)}</TD>
                    <TD className="text-muted-foreground">{relTime(d.created_at)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <DeploymentLogPanel deploymentId={openId ?? deployments?.[0]?.id ?? null} />
    </div>
  );
}

function DeploymentLogPanel({ deploymentId }: { deploymentId: string | null }) {
  const queryClient = useQueryClient();
  const { data: deployment } = useQuery<Deployment | null>({
    queryKey: ["deployment", deploymentId],
    queryFn: () => api(`/api/deployments/${deploymentId}`),
    enabled: !!deploymentId,
    refetchInterval: 3_000,
  });

  const active = !!deploymentId && (deployment?.status === "queued" || deployment?.status === "running");
  const { lines, connected } = useLogStream(
    deploymentId ? `/api/deployments/${deploymentId}/stream` : null,
    { enabled: true },
  );
  const [dbLogs, setDbLogs] = useState<Array<{ sequence: number; message: string; stream: string }>>([]);

  useEffect(() => {
    if (!deploymentId) { setDbLogs([]); return; }
    api<{ logs: typeof dbLogs; status: string }>(`/api/deployments/${deploymentId}/logs`)
      .then((data) => setDbLogs(data.logs))
      .catch(() => undefined);
  }, [deploymentId]);

  const cancel = useMutation({
    mutationFn: () => api(`/api/deployments/${deploymentId}/cancel`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["deployment", deploymentId] }),
    onError: (e) => toast.error(e.message),
  });

  const retry = useMutation({
    mutationFn: () => api(`/api/deployments/${deploymentId}/retry`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["deployments"] });
      toast.success("Retry queued");
    },
    onError: (e) => toast.error(e.message),
  });

  const rollback = useMutation({
    mutationFn: () => api(`/api/deployments/${deploymentId}/rollback`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["deployments"] });
      toast.success("Rollback queued");
    },
    onError: (e) => toast.error(e.message),
  });

  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [lines.length, dbLogs.length]);

  return (
    <Card className="flex flex-col">
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Build log {deployment && <StatusBadge status={deployment.status} className="ml-2" />}</CardTitle>
        <div className="flex gap-2">
          {active && (
            <Button size="sm" variant="destructive" onClick={() => cancel.mutate()}>Cancel</Button>
          )}
          {deployment?.status === "failed" && (
            <Button size="sm" variant="outline" onClick={() => retry.mutate()}>Retry</Button>
          )}
          {deployment?.status === "success" && (
            <Button size="sm" variant="outline" onClick={() => rollback.mutate()}>Rollback to this</Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex-1">
        {!deploymentId ? (
          <p className="py-10 text-center text-sm text-muted-foreground">Select a deployment to view its log.</p>
        ) : (
          <div className="log-view max-h-[420px] min-h-[300px] overflow-y-auto rounded-lg bg-black/80 p-4 text-green-100">
            {dbLogs.map((log) => (
              <div key={log.sequence} className={log.stream === "stderr" ? "text-red-300" : ""}>
                <span className="text-gray-500">{String(log.sequence).padStart(3, "0")}</span> {log.message}
              </div>
            ))}
            {lines.map((line, i) => (
              <div key={`live-${i}`} className={line.stream === "stderr" ? "text-red-300" : ""}>
                <span className="text-gray-500">••</span> {line.message}
              </div>
            ))}
            {!active && !dbLogs.length && !lines.length && (
              <div className="text-gray-500">No log output recorded.</div>
            )}
            {active && !connected && (
              <div className="text-yellow-300">connecting to live stream…</div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DomainsTab({ app, onChanged }: { app: Application; onChanged: () => void }) {
  const queryClient = useQueryClient();
  const [hostname, setHostname] = useState("");
  const [ssl, setSsl] = useState(true);

  const { data: domains } = useQuery<Domain[]>({
    queryKey: ["domains", app.id],
    queryFn: () => api(`/api/domains?application_id=${app.id}`),
  });

  const add = useMutation({
    mutationFn: () => api("/api/domains", {
      method: "POST",
      body: { application_id: app.id, hostname, ssl_enabled: ssl },
    }),
    onSuccess: () => {
      toast.success("Domain added — apply labels live via container recreate");
      setHostname("");
      queryClient.invalidateQueries({ queryKey: ["domains"] });
      queryClient.invalidateQueries({ queryKey: ["domains", app.id] });
      onChanged();
    },
    onError: (e) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/domains/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["domains"] });
      queryClient.invalidateQueries({ queryKey: ["domains", app.id] });
      onChanged();
    },
    onError: (e) => toast.error(e.message),
  });

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle>Add domain</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap items-end gap-4">
          <div className="min-w-[240px] flex-1 space-y-1.5">
            <Label>Hostname</Label>
            <Input value={hostname} onChange={(e) => setHostname(e.target.value)} placeholder="app.example.com" />
          </div>
          <div className="flex items-center gap-2 pb-1.5">
            <Switch checked={ssl} onChange={setSsl} />
            <Label>HTTPS (Let&apos;s Encrypt)</Label>
          </div>
          <Button onClick={() => add.mutate()} loading={add.isPending} disabled={!hostname.trim()}>
            <Plus className="h-4 w-4" /> Add
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Assigned domains</CardTitle></CardHeader>
        <CardContent className="px-0">
          {!domains?.length ? (
            <p className="px-5 py-6 text-sm text-muted-foreground">
              No domains attached. Add one, point DNS at this server, and Traefik routes it here.
            </p>
          ) : (
            <Table>
              <THead>
                <TH>Hostname</TH><TH>SSL</TH><TH>Expires</TH><TH className="w-16" />
              </THead>
              <TBody>
                {domains.map((d) => (
                  <TR key={d.id}>
                    <TD className="font-medium">{d.hostname}</TD>
                    <TD><StatusBadge status={d.ssl_enabled ? d.ssl_status : "disabled"} /></TD>
                    <TD className="text-muted-foreground">{fmtDate(d.ssl_expires_at)}</TD>
                    <TD>
                      <Button variant="ghost" size="icon" onClick={() => remove.mutate(d.id)} aria-label="Remove domain">
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function EnvTab({ appId }: { appId: string }) {
  const queryClient = useQueryClient();
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [revealed, setRevealed] = useState<Record<string, string>>({});

  const { data: vars } = useQuery<EnvVar[]>({
    queryKey: ["env", appId],
    queryFn: () => api(`/api/applications/${appId}/env-vars`),
  });

  const add = useMutation({
    mutationFn: () => api(`/api/applications/${appId}/env-vars`, { method: "POST", body: { key, value } }),
    onSuccess: () => {
      toast.success("Environment variable added");
      setKey(""); setValue("");
      queryClient.invalidateQueries({ queryKey: ["env", appId] });
    },
    onError: (e) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/applications/${appId}/env-vars/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["env", appId] }),
    onError: (e) => toast.error(e.message),
  });

  const reveal = async (id: string) => {
    if (revealed[id]) {
      const copy = { ...revealed };
      delete copy[id];
      setRevealed(copy);
      return;
    }
    const data = await api<{ value: string }>(`/api/applications/${appId}/env-vars/${id}/reveal`);
    setRevealed((r) => ({ ...r, [id]: data.value }));
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Environment variables</CardTitle>
        <p className="text-sm text-muted-foreground">Encrypted at rest (Fernet). Injected into the container on every deploy.</p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[180px] flex-1 space-y-1.5">
            <Label>Key</Label>
            <Input value={key} onChange={(e) => setKey(e.target.value.toUpperCase())} placeholder="DATABASE_URL" />
          </div>
          <div className="min-w-[180px] flex-1 space-y-1.5">
            <Label>Value</Label>
            <Input value={value} onChange={(e) => setValue(e.target.value)} placeholder="postgres://…" />
          </div>
          <Button onClick={() => add.mutate()} loading={add.isPending} disabled={!key.trim()}>
            <Plus className="h-4 w-4" /> Add
          </Button>
        </div>

        {vars?.length ? (
          <Table>
            <THead>
              <TH>Key</TH><TH>Value</TH><TH className="w-24" />
            </THead>
            <TBody>
              {vars.map((v) => (
                <TR key={v.id}>
                  <TD><code className="text-xs font-semibold">{v.key}</code></TD>
                  <TD>
                    <div className="flex items-center gap-2">
                      <code className="max-w-xs truncate text-xs text-muted-foreground">
                        {revealed[v.id] ?? (v.is_secret ? "••••••••" : "set")}
                      </code>
                      <button onClick={() => reveal(v.id)} className="text-muted-foreground hover:text-foreground" aria-label="Reveal">
                        {revealed[v.id] ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                      </button>
                    </div>
                  </TD>
                  <TD>
                    <Button variant="ghost" size="icon" onClick={() => remove.mutate(v.id)} aria-label="Delete">
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        ) : (
          <p className="py-4 text-sm text-muted-foreground">No environment variables yet.</p>
        )}
      </CardContent>
    </Card>
  );
}

function LogsTab({ app }: { app: Application }) {
  const container = app.container_name ?? `ld-${app.slug}`;
  const { lines, connected } = useLogStream(`/api/applications/${app.id}/logs/stream`);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView(); }, [lines.length]);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Live container logs — {container}</CardTitle>
        <Badge variant={connected ? "success" : "warning"}>{connected ? "streaming" : "offline"}</Badge>
      </CardHeader>
      <CardContent>
        <div className="log-view max-h-[520px] min-h-[300px] overflow-y-auto rounded-lg bg-black/80 p-4 text-green-100">
          {!lines.length && (
            <div className="text-gray-500">
              {connected ? "Waiting for output…" : "No stream — is the container running and Docker reachable?"}
            </div>
          )}
          {lines.map((line, i) => (
            <div key={i}>{line.message}</div>
          ))}
          <div ref={bottomRef} />
        </div>
      </CardContent>
    </Card>
  );
}

function SettingsTab({ app, onChanged, onDelete }: { app: ApplicationDetail; onChanged: () => void; onDelete: () => void }) {
  const queryClient = useQueryClient();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [form, setForm] = useState({
    container_port: String(app.container_port),
    health_check_path: app.health_check_path ?? "/",
    build_command: app.build_command ?? "",
    start_command: app.start_command ?? "",
    install_command: app.install_command ?? "",
    cpu_limit: app.cpu_limit ? String(app.cpu_limit) : "",
    memory_limit_mb: app.memory_limit_mb ? String(app.memory_limit_mb) : "",
    auto_deploy: app.auto_deploy,
  });

  const save = useMutation({
    mutationFn: () => api(`/api/applications/${app.id}`, {
      method: "PUT",
      body: {
        container_port: Number(form.container_port) || undefined,
        health_check_path: form.health_check_path || undefined,
        build_command: form.build_command || null,
        start_command: form.start_command || null,
        install_command: form.install_command || null,
        cpu_limit: form.cpu_limit ? Number(form.cpu_limit) : null,
        memory_limit_mb: form.memory_limit_mb ? Number(form.memory_limit_mb) : null,
        auto_deploy: form.auto_deploy,
      },
    }),
    onSuccess: () => {
      toast.success("Settings saved — redeploy to apply");
      queryClient.invalidateQueries({ queryKey: ["application", app.id] });
      onChanged();
    },
    onError: (e) => toast.error(e.message),
  });

  const webhook = useQuery<{ url: string; secret: string | null; provider: string; branch: string | null }>({
    queryKey: ["webhook", app.id],
    queryFn: () => api(`/api/applications/${app.id}/webhook`),
  });

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>Build & run</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Container port</Label>
              <Input value={form.container_port} onChange={(e) => setForm({ ...form, container_port: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label>Health check path</Label>
              <Input value={form.health_check_path} onChange={(e) => setForm({ ...form, health_check_path: e.target.value })} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Install command override</Label>
            <Input value={form.install_command} onChange={(e) => setForm({ ...form, install_command: e.target.value })} placeholder="(auto from buildpack)" />
          </div>
          <div className="space-y-1.5">
            <Label>Build command override</Label>
            <Input value={form.build_command} onChange={(e) => setForm({ ...form, build_command: e.target.value })} placeholder="(auto from buildpack)" />
          </div>
          <div className="space-y-1.5">
            <Label>Start command override</Label>
            <Input value={form.start_command} onChange={(e) => setForm({ ...form, start_command: e.target.value })} placeholder="(auto from buildpack)" />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>CPU limit (vCPU)</Label>
              <Input value={form.cpu_limit} onChange={(e) => setForm({ ...form, cpu_limit: e.target.value })} placeholder="e.g. 1.5" />
            </div>
            <div className="space-y-1.5">
              <Label>Memory limit (MB)</Label>
              <Input value={form.memory_limit_mb} onChange={(e) => setForm({ ...form, memory_limit_mb: e.target.value })} placeholder="e.g. 512" />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Switch checked={form.auto_deploy} onChange={(v) => setForm({ ...form, auto_deploy: v })} />
            <Label>Auto-deploy on webhook push</Label>
          </div>
          <Button onClick={() => save.mutate()} loading={save.isPending}>Save settings</Button>
        </CardContent>
      </Card>

      <div className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Git webhook</CardTitle>
            <p className="text-sm text-muted-foreground">Point your GitHub/GitLab push webhook at this URL.</p>
          </CardHeader>
          <CardContent className="space-y-3">
            {webhook.data && (
              <>
                <div className="flex items-center gap-2">
                  <Input readOnly value={webhook.data.url} className="font-mono text-xs" />
                  <Button
                    variant="outline" size="icon"
                    onClick={() => { navigator.clipboard.writeText(webhook.data!.url); toast.success("Webhook URL copied"); }}
                    aria-label="Copy webhook URL"
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Provider: {webhook.data.provider} · watches branch <strong>{webhook.data.branch ?? "default"}</strong>
                </p>
              </>
            )}
          </CardContent>
        </Card>

        <Card className="border-destructive/40">
          <CardHeader><CardTitle className="text-destructive">Danger zone</CardTitle></CardHeader>
          <CardContent>
            <p className="mb-3 text-sm text-muted-foreground">
              Deleting the application stops and removes its container(s). Data volumes are kept.
            </p>
            <Button variant="destructive" onClick={() => setConfirmDelete(true)}>
              <Trash2 className="h-4 w-4" /> Delete application
            </Button>
          </CardContent>
        </Card>
      </div>

      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={onDelete}
        title={`Delete ${app.name}?`}
        message="This stops the container and removes the application record. This cannot be undone."
      />
    </div>
  );
}
