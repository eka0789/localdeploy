"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Container, Play, Plus, RotateCcw, Square, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Topbar } from "@/components/layout";
import {
  Button, Card, CardContent, CardHeader, CardTitle, Dialog, EmptyState, Input, Label, Select,
  Skeleton, StatusBadge, TD, TBody, TH, THead, TR, Table,
} from "@/components/ui";
import { api } from "@/lib/api";
import { fmtBytes, relTime } from "@/lib/format";
import type { DockerContainer, DockerImage, DockerNetwork, DockerStatus, Volume } from "@/lib/types";

type Tab = "containers" | "images" | "networks" | "volumes";

export default function DockerPage() {
  const [tab, setTab] = useState<Tab>("containers");
  const queryClient = useQueryClient();

  const { data: status } = useQuery<DockerStatus>({
    queryKey: ["docker", "status"],
    queryFn: () => api("/api/docker/status"),
    refetchInterval: 10_000,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["docker"] });
  };

  const tabs: Tab[] = ["containers", "images", "networks", "volumes"];

  return (
    <>
      <Topbar title="Docker" description="Direct management of the local Docker Engine" />
      <div className="space-y-6 p-8">
        {status && !status.available && (
          <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4">
            <p className="text-sm font-medium text-destructive">Docker Engine is not reachable</p>
            <p className="mt-1 text-xs text-muted-foreground">{status.hint ?? status.error}</p>
          </div>
        )}
        {status?.available && (
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard label="Engine" value={status.version ?? "?"} sub={status.os} />
            <StatCard label="Containers" value={`${status.containers_running ?? 0} running`} sub={`${status.containers ?? 0} total · ${status.containers_stopped ?? 0} stopped`} />
            <StatCard label="Images" value={String(status.images ?? 0)} sub={`API ${status.api_version ?? ""}`} />
            <StatCard label="Resources" value={`${status.cpus ?? "?"} CPUs`} sub={`${status.total_memory_mb ?? 0} MB RAM`} />
          </div>
        )}

        <div className="flex gap-1 border-b border-border">
          {tabs.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`border-b-2 px-4 py-2.5 text-sm capitalize transition-colors ${
                tab === t ? "border-primary font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {tab === "containers" && <ContainersTab onChanged={invalidate} />}
        {tab === "images" && <ImagesTab onChanged={invalidate} />}
        {tab === "networks" && <NetworksTab onChanged={invalidate} />}
        {tab === "volumes" && <VolumesTab onChanged={invalidate} />}
      </div>
    </>
  );
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card>
      <CardContent className="p-5">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="mt-1 text-xl font-semibold">{value}</p>
        {sub && <p className="mt-1 truncate text-xs text-muted-foreground">{sub}</p>}
      </CardContent>
    </Card>
  );
}

function ContainersTab({ onChanged }: { onChanged: () => void }) {
  const action = useMutation({
    mutationFn: ({ id, act }: { id: string; act: string }) =>
      api(`/api/docker/containers/${id}/${act}`, { method: "POST" }),
    onSuccess: () => { toast.success("Done"); onChanged(); },
    onError: (e) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/docker/containers/${id}`, { method: "DELETE" }),
    onSuccess: () => { toast.success("Container removed"); onChanged(); },
    onError: (e) => toast.error(e.message),
  });

  const { data, isLoading } = useQuery<{ containers: DockerContainer[] }>({
    queryKey: ["docker", "containers"],
    queryFn: () => api("/api/docker/containers"),
    refetchInterval: 8_000,
  });

  if (isLoading) return <Skeleton className="h-64" />;
  if (!data?.containers.length) {
    return <EmptyState icon={Container} title="No containers" description="Nothing is running on this engine yet." />;
  }

  return (
    <Card>
      <CardContent className="px-0">
        <Table>
          <THead>
            <TH>Name</TH><TH>Image</TH><TH>Status</TH><TH>Managed</TH><TH>Created</TH><TH className="w-40">Actions</TH>
          </THead>
          <TBody>
            {data.containers.map((c) => (
              <TR key={c.id}>
                <TD>
                  <div className="font-medium">{c.name}</div>
                  <code className="text-xs text-muted-foreground">{c.id}</code>
                </TD>
                <TD><code className="text-xs">{c.image}</code></TD>
                <TD><StatusBadge status={c.status} /></TD>
                <TD>{c.managed && <StatusBadge status="success" />}</TD>
                <TD className="text-muted-foreground">{c.created ? relTime(c.created) : "—"}</TD>
                <TD>
                  <div className="flex gap-1">
                    <Button variant="ghost" size="icon" title="Start" onClick={() => action.mutate({ id: c.id, act: "start" })}><Play className="h-4 w-4" /></Button>
                    <Button variant="ghost" size="icon" title="Stop" onClick={() => action.mutate({ id: c.id, act: "stop" })}><Square className="h-4 w-4" /></Button>
                    <Button variant="ghost" size="icon" title="Restart" onClick={() => action.mutate({ id: c.id, act: "restart" })}><RotateCcw className="h-4 w-4" /></Button>
                    <Button variant="ghost" size="icon" title="Remove" onClick={() => remove.mutate(c.id)}><Trash2 className="h-4 w-4 text-destructive" /></Button>
                  </div>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function ImagesTab({ onChanged }: { onChanged: () => void }) {
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/docker/images/${id}`, { method: "DELETE" }),
    onSuccess: () => { toast.success("Image removed"); onChanged(); },
    onError: (e) => toast.error(e.message),
  });

  const { data, isLoading } = useQuery<{ images: DockerImage[] }>({
    queryKey: ["docker", "images"],
    queryFn: () => api("/api/docker/images"),
    refetchInterval: 30_000,
  });

  if (isLoading) return <Skeleton className="h-64" />;

  return (
    <Card>
      <CardContent className="px-0">
        <Table>
          <THead><TH>Tags</TH><TH>Size</TH><TH>Created</TH><TH className="w-16" /></THead>
          <TBody>
            {(data?.images ?? []).map((img) => (
              <TR key={img.id}>
                <TD>
                  {img.tags.map((t) => <code key={t} className="mr-2 text-xs">{t}</code>)}
                </TD>
                <TD className="text-muted-foreground">{fmtBytes(img.size_mb * 1024 * 1024)}</TD>
                <TD className="text-muted-foreground">{img.created ? relTime(img.created) : "—"}</TD>
                <TD>
                  <Button variant="ghost" size="icon" onClick={() => remove.mutate(img.id)} aria-label="Remove image">
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function NetworksTab({ onChanged }: { onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const remove = useMutation({
    mutationFn: (name: string) => api(`/api/docker/networks/${name}`, { method: "DELETE" }),
    onSuccess: () => { toast.success("Network removed"); onChanged(); },
    onError: (e) => toast.error(e.message),
  });
  const create = useMutation({
    mutationFn: () => api("/api/docker/networks", { method: "POST", body: { name } }),
    onSuccess: () => { toast.success("Network created"); setOpen(false); setName(""); onChanged(); },
    onError: (e) => toast.error(e.message),
  });

  const { data, isLoading } = useQuery<{ networks: DockerNetwork[] }>({
    queryKey: ["docker", "networks"],
    queryFn: () => api("/api/docker/networks"),
    refetchInterval: 30_000,
  });

  if (isLoading) return <Skeleton className="h-64" />;

  return (
    <>
      <div className="mb-4 flex justify-end">
        <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> New network</Button>
      </div>
      <Card>
        <CardContent className="px-0">
          <Table>
            <THead><TH>Name</TH><TH>Driver</TH><TH>Internal</TH><TH>Containers</TH><TH className="w-16" /></THead>
            <TBody>
              {(data?.networks ?? []).map((net) => (
                <TR key={net.id}>
                  <TD className="font-medium">{net.name}</TD>
                  <TD>{net.driver}</TD>
                  <TD>{net.internal ? "yes" : "no"}</TD>
                  <TD className="text-muted-foreground">{net.containers.join(", ") || "—"}</TD>
                  <TD>
                    <Button variant="ghost" size="icon" onClick={() => remove.mutate(net.name)} aria-label="Remove network">
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog
        open={open} onClose={() => setOpen(false)} title="Create network"
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={() => create.mutate()} disabled={!name.trim()}>Create</Button>
          </>
        }
      >
        <div className="space-y-1.5">
          <Label>Network name</Label>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="my-network" />
        </div>
      </Dialog>
    </>
  );
}

function VolumesTab({ onChanged }: { onChanged: () => void }) {
  const [name, setName] = useState("");
  const [open, setOpen] = useState(false);
  const remove = useMutation({
    mutationFn: (name: string) => api(`/api/storage/volumes/${name}`, { method: "DELETE" }),
    onSuccess: () => { toast.success("Volume removed"); onChanged(); },
    onError: (e) => toast.error(e.message),
  });
  const create = useMutation({
    mutationFn: () => api("/api/storage/volumes", { method: "POST", body: { name } }),
    onSuccess: () => { toast.success("Volume created"); setOpen(false); setName(""); onChanged(); },
    onError: (e) => toast.error(e.message),
  });

  const { data, isLoading } = useQuery<{ volumes: Volume[] }>({
    queryKey: ["storage", "volumes"],
    queryFn: () => api("/api/storage/volumes"),
    refetchInterval: 30_000,
  });

  if (isLoading) return <Skeleton className="h-64" />;

  return (
    <>
      <div className="mb-4 flex justify-end">
        <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> New volume</Button>
      </div>
      <Card>
        <CardContent className="px-0">
          <Table>
            <THead><TH>Name</TH><TH>Driver</TH><TH>In use</TH><TH>Managed</TH><TH className="w-16" /></THead>
            <TBody>
              {(data?.volumes ?? []).map((v) => (
                <TR key={v.name}>
                  <TD><code className="text-xs">{v.name}</code></TD>
                  <TD>{v.driver}</TD>
                  <TD>{v.in_use ? <StatusBadge status="running" /> : <StatusBadge status="idle" />}</TD>
                  <TD>{v.managed && <StatusBadge status="success" />}</TD>
                  <TD>
                    <Button variant="ghost" size="icon" disabled={v.in_use} onClick={() => remove.mutate(v.name)} aria-label="Remove volume">
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog
        open={open} onClose={() => setOpen(false)} title="Create volume"
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={() => create.mutate()} disabled={!name.trim()}>Create</Button>
          </>
        }
      >
        <div className="space-y-1.5">
          <Label>Volume name</Label>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="my-data" />
        </div>
      </Dialog>
    </>
  );
}
