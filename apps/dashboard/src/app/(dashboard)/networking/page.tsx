"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, Cloud, Globe, Play, Plus, Square, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Topbar } from "@/components/layout";
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, ConfirmDialog, Dialog, Input,
  Label, Skeleton, StatusBadge,
} from "@/components/ui";
import { api } from "@/lib/api";
import { relTime } from "@/lib/format";
import type { Tunnel } from "@/lib/types";

type NetworkingInfo = {
  mode: string;
  public_ip: string | null;
  local_ip: string | null;
  docker_available: boolean;
  modes: Record<string, {
    title: string;
    prerequisites: string[];
    ssl?: string;
    advantages?: string[];
    never_do?: string[];
  }>;
};

export default function NetworkingPage() {
  const queryClient = useQueryClient();
  const [tunnelOpen, setTunnelOpen] = useState(false);
  const [name, setName] = useState("");
  const [token, setToken] = useState("");
  const [deleteId, setDeleteId] = useState<string | null>(null);

  const { data: info, isLoading } = useQuery<NetworkingInfo>({
    queryKey: ["networking", "info"],
    queryFn: () => api("/api/networking/info"),
    refetchInterval: 20_000,
  });

  const { data: tunnels } = useQuery<Tunnel[]>({
    queryKey: ["tunnels"],
    queryFn: () => api("/api/networking/tunnels"),
    refetchInterval: 8_000,
  });

  const setMode = useMutation({
    mutationFn: (mode: string) => api("/api/networking/mode", { method: "PUT", body: { mode } }),
    onSuccess: () => {
      toast.success("Networking mode updated");
      queryClient.invalidateQueries({ queryKey: ["networking"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const createTunnel = useMutation({
    mutationFn: () => api("/api/networking/tunnels", { method: "POST", body: { name, token } }),
    onSuccess: () => {
      toast.success("Tunnel registered — press Start to connect");
      setTunnelOpen(false); setName(""); setToken("");
      queryClient.invalidateQueries({ queryKey: ["tunnels"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const action = useMutation({
    mutationFn: ({ id, act }: { id: string; act: string }) =>
      api(`/api/networking/tunnels/${id}/${act}`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tunnels"] }),
    onError: (e) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/networking/tunnels/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Tunnel removed");
      queryClient.invalidateQueries({ queryKey: ["tunnels"] });
    },
    onError: (e) => toast.error(e.message),
  });

  if (isLoading || !info) {
    return (
      <>
        <Topbar title="Networking" />
        <div className="space-y-4 p-8">{[0, 1].map((i) => <Skeleton key={i} className="h-48" />)}</div>
      </>
    );
  }

  return (
    <>
      <Topbar
        title="Networking"
        description={`Public access mode · ${info.mode === "cloudflare-tunnel" ? "Cloudflare Tunnel" : "Public IP"}`}
        actions={<Button onClick={() => setTunnelOpen(true)}><Plus className="h-4 w-4" /> Add tunnel</Button>}
      />
      <div className="space-y-6 p-8">
        {/* mode selection */}
        <div className="grid gap-4 lg:grid-cols-2">
          {(["public-ip", "cloudflare-tunnel"] as const).map((mode) => {
            const spec = info.modes[mode];
            const active = info.mode === mode;
            return (
              <Card key={mode} className={active ? "border-primary ring-1 ring-primary/40" : ""}>
                <CardHeader className="flex-row items-start justify-between">
                  <div className="flex items-center gap-2">
                    {mode === "public-ip" ? <Globe className="h-5 w-5 text-primary" /> : <Cloud className="h-5 w-5 text-primary" />}
                    <CardTitle>{spec.title}</CardTitle>
                  </div>
                  {active ? <Badge variant="success">active</Badge> : (
                    <Button size="sm" variant="outline" onClick={() => setMode.mutate(mode)}>Use this mode</Button>
                  )}
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Prerequisites</p>
                  <ul className="list-inside list-disc space-y-1 text-muted-foreground">
                    {spec.prerequisites.map((p, i) => <li key={i}>{p}</li>)}
                  </ul>
                  {spec.advantages && (
                    <>
                      <p className="pt-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Advantages</p>
                      <ul className="list-inside list-disc space-y-1 text-muted-foreground">
                        {spec.advantages.map((p, i) => <li key={i}>{p}</li>)}
                      </ul>
                    </>
                  )}
                  {spec.never_do && (
                    <p className="rounded-lg bg-destructive/10 p-2.5 text-xs text-destructive">
                      ⚠ {spec.never_do.join(" · ")}
                    </p>
                  )}
                  {spec.ssl && <p className="text-xs text-muted-foreground">SSL: {spec.ssl}</p>}
                </CardContent>
              </Card>
            );
          })}
        </div>

        {/* detected addresses */}
        <Card>
          <CardHeader><CardTitle>Detected addresses</CardTitle></CardHeader>
          <CardContent className="grid gap-4 text-sm sm:grid-cols-2">
            <div>
              <p className="text-muted-foreground">Public IP</p>
              <code className="text-lg font-semibold">{info.public_ip ?? "not detectable (offline?)"}</code>
            </div>
            <div>
              <p className="text-muted-foreground">Local IP</p>
              <code className="text-lg font-semibold">{info.local_ip ?? "—"}</code>
            </div>
          </CardContent>
        </Card>

        {/* tunnels */}
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>Cloudflare Tunnels</CardTitle>
            <ArrowLeftRight className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent className="space-y-3">
            {!tunnels?.length ? (
              <p className="py-4 text-sm text-muted-foreground">
                No tunnels configured. Create one in Cloudflare Zero Trust → Networks → Tunnels, copy the token, add it here.
              </p>
            ) : (
              tunnels.map((tunnel) => (
                <div key={tunnel.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border p-4">
                  <div>
                    <div className="flex items-center gap-2 font-medium">
                      {tunnel.name} <StatusBadge status={tunnel.status} />
                    </div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      {tunnel.last_error ?? "cloudflared"} · created {relTime(tunnel.created_at)}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    {tunnel.status !== "running" ? (
                      <Button size="sm" onClick={() => action.mutate({ id: tunnel.id, act: "start" })}>
                        <Play className="h-3.5 w-3.5" /> Start
                      </Button>
                    ) : (
                      <Button size="sm" variant="outline" onClick={() => action.mutate({ id: tunnel.id, act: "stop" })}>
                        <Square className="h-3.5 w-3.5" /> Stop
                      </Button>
                    )}
                    <Button size="icon" variant="ghost" onClick={() => setDeleteId(tunnel.id)} aria-label="Delete tunnel">
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog
        open={tunnelOpen} onClose={() => setTunnelOpen(false)} title="Add Cloudflare Tunnel"
        description="Create a tunnel in the Cloudflare Zero Trust dashboard and paste its token here."
        footer={
          <>
            <Button variant="outline" onClick={() => setTunnelOpen(false)}>Cancel</Button>
            <Button onClick={() => createTunnel.mutate()} loading={createTunnel.isPending} disabled={!name.trim() || token.length < 20}>
              Register tunnel
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="home-tunnel" />
          </div>
          <div className="space-y-1.5">
            <Label>Tunnel token</Label>
            <Input value={token} onChange={(e) => setToken(e.target.value)} placeholder="eyJhIjoi..." />
            <p className="text-xs text-muted-foreground">Stored encrypted. The token never leaves this server except to Cloudflare.</p>
          </div>
        </div>
      </Dialog>

      <ConfirmDialog
        open={!!deleteId}
        onClose={() => setDeleteId(null)}
        onConfirm={() => deleteId && remove.mutate(deleteId)}
        title="Delete tunnel?"
        message="The cloudflared container will be stopped and the tunnel record removed."
      />
    </>
  );
}
