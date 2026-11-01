"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, MonitorSmartphone, Plus, RefreshCw, Server as ServerIcon, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, ConfirmDialog, Dialog, Input, Label,
} from "@/components/ui";
import { api } from "@/lib/api";
import { relTime } from "@/lib/format";
import type { RemoteServer } from "@/lib/types";

export function ServersTab() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<{ token: string; install_hint: string; name: string } | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [regenId, setRegenId] = useState<string | null>(null);

  const { data: servers } = useQuery<RemoteServer[]>({
    queryKey: ["servers"],
    queryFn: () => api("/api/servers"),
    refetchInterval: 10_000,
  });

  const create = useMutation({
    mutationFn: () => api<{ token: string; install_hint: string; name: string }>("/api/servers", {
      method: "POST", body: { name },
    }),
    onSuccess: (data) => {
      setCreated(data);
      setName("");
      setOpen(false);
      queryClient.invalidateQueries({ queryKey: ["servers"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const regenerate = useMutation({
    mutationFn: (id: string) => api<{ token: string }>(`/api/servers/${id}/regenerate-token`, { method: "POST" }),
    onSuccess: (data) => {
      setCreated({ token: data.token, install_hint: "Restart the agent with this new token.", name: "" });
      setRegenId(null);
      queryClient.invalidateQueries({ queryKey: ["servers"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/servers/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Server removed");
      queryClient.invalidateQueries({ queryKey: ["servers"] });
    },
    onError: (e) => toast.error(e.message),
  });

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Add server</Button>
      </div>

      {!servers?.length ? (
        <p className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          No remote servers yet. Add one to deploy applications onto other Docker hosts — the agent
          connects out to this dashboard, so no inbound ports are needed on the remote machine.
        </p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {servers.map((server) => (
            <Card key={server.id}>
              <CardHeader className="flex-row items-center justify-between">
                <CardTitle className="flex items-center gap-2">
                  <ServerIcon className="h-4 w-4 text-primary" /> {server.name}
                  <Badge variant={server.status === "online" ? "success" : server.status === "pending" ? "outline" : "warning"}>
                    {server.status}
                  </Badge>
                </CardTitle>
                <div className="flex gap-1">
                  <Button size="icon" variant="ghost" title="Regenerate token"
                          onClick={() => setRegenId(server.id)}>
                    <RefreshCw className="h-4 w-4" />
                  </Button>
                  <Button size="icon" variant="ghost" title="Remove server"
                          onClick={() => setDeleteId(server.id)}>
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-1.5 text-sm text-muted-foreground">
                <div className="flex justify-between"><span>Agent</span><span>{server.agent_version ?? "—"}</span></div>
                <div className="flex justify-between"><span>Last seen</span><span>{server.last_seen_at ? relTime(server.last_seen_at) : "never"}</span></div>
                <div className="flex justify-between"><span>CPU</span><span>{server.cpu_percent.toFixed(0)}%</span></div>
                <div className="flex justify-between">
                  <span>Memory</span>
                  <span>{server.memory_used_mb.toFixed(0)} / {server.memory_total_mb.toFixed(0)} MB</span>
                </div>
                <div className="flex justify-between">
                  <span>Containers</span>
                  <span>{server.running_count} running / {server.container_count}</span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog
        open={open} onClose={() => setOpen(false)} title="Add remote server"
        description="Creates a server entry and a one-time agent token."
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={() => create.mutate()} loading={create.isPending} disabled={!name.trim()}>
              Create
            </Button>
          </>
        }
      >
        <div className="space-y-1.5">
          <Label>Server name</Label>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="vps-hetzner" />
        </div>
      </Dialog>

      <Dialog
        open={!!created} onClose={() => setCreated(null)} wide
        title={created ? `Token for ${created.name || "server"}` : ""}
        description="Copy it now — shown only once. Run the agent on the remote host with it."
        footer={<Button onClick={() => setCreated(null)}>Done</Button>}
      >
        {created && (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <code className="flex-1 break-all rounded bg-muted p-2 text-xs">{created.token}</code>
              <Button size="icon" variant="outline"
                      onClick={() => { navigator.clipboard.writeText(created.token); toast.success("Token copied"); }}>
                <Copy className="h-4 w-4" />
              </Button>
            </div>
            <div className="rounded-lg bg-muted p-3 text-xs">
              <p className="mb-1 font-semibold">On the remote host:</p>
              <code className="block break-all">
                pip install docker requests psutil<br />
                export LOCALDEPLOY_API_URL=&quot;&lt;your-dashboard-api-url&gt;&quot;<br />
                export LOCALDEPLOY_SERVER_TOKEN={created.token}<br />
                python agent.py
              </code>
            </div>
            <p className="text-xs text-muted-foreground">{created.install_hint}</p>
          </div>
        )}
      </Dialog>

      <ConfirmDialog
        open={!!deleteId} onClose={() => setDeleteId(null)}
        onConfirm={() => deleteId && remove.mutate(deleteId)}
        title="Remove server?"
        message="Reassign its applications first; removal also deletes queued commands."
      />
      <ConfirmDialog
        open={!!regenId} onClose={() => setRegenId(null)}
        onConfirm={() => regenId && regenerate.mutate(regenId)}
        title="Regenerate token?"
        message="The old token stops working immediately — update the agent's environment."
        confirmLabel="Regenerate"
        destructive={false}
      />
    </div>
  );
}

export function ServerBadgeInline({ serverId }: { serverId: string | null }) {
  const { data: servers } = useQuery<RemoteServer[]>({
    queryKey: ["servers"],
    queryFn: () => api("/api/servers"),
    enabled: !!serverId,
  });
  if (!serverId) return null;
  const server = servers?.find((s) => s.id === serverId);
  if (!server) return null;
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-info/10 px-2 py-0.5 text-xs text-info">
      <MonitorSmartphone className="h-3 w-3" /> {server.name}
    </span>
  );
}
