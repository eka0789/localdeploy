"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cloud, Copy, Globe, Info, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { Topbar } from "@/components/layout";
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Dialog, EmptyState, Input, Label, Select,
  Skeleton, StatusBadge, Switch, TD, TBody, TH, THead, TR, Table,
} from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate, relTime } from "@/lib/format";
import type { Application, CloudflareStatus, Domain } from "@/lib/types";

type DnsInstructions = {
  hostname: string;
  application: string | null;
  records: Array<{ type: string; name: string; value: string; note: string }>;
  cloudflare_hint: string;
};

export default function DomainsPage() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [hostname, setHostname] = useState("");
  const [appId, setAppId] = useState("");
  const [ssl, setSsl] = useState(true);
  const [instructions, setInstructions] = useState<DnsInstructions | null>(null);
  const [tunnelFor, setTunnelFor] = useState<Domain | null>(null);
  const [selectedTunnel, setSelectedTunnel] = useState("");

  const { data: domains, isLoading } = useQuery<Domain[]>({
    queryKey: ["domains"],
    queryFn: () => api("/api/domains"),
    refetchInterval: 15_000,
  });

  const { data: apps } = useQuery<Application[]>({
    queryKey: ["applications"],
    queryFn: () => api("/api/applications"),
  });

  const { data: cf } = useQuery<CloudflareStatus>({
    queryKey: ["cloudflare"],
    queryFn: () => api("/api/networking/cloudflare"),
  });

  const add = useMutation({
    mutationFn: () => api("/api/domains", {
      method: "POST",
      body: { application_id: appId, hostname, ssl_enabled: ssl },
    }),
    onSuccess: (_data) => {
      toast.success("Domain added");
      setOpen(false);
      setHostname("");
      queryClient.invalidateQueries({ queryKey: ["domains"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/domains/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Domain removed");
      queryClient.invalidateQueries({ queryKey: ["domains"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const verify = useMutation({
    mutationFn: (id: string) => api<{ resolved: boolean; message: string }>(`/api/domains/${id}/verify`, { method: "POST" }),
    onSuccess: (data) => {
      data.resolved ? toast.success(data.message) : toast.warning(data.message);
      queryClient.invalidateQueries({ queryKey: ["domains"] });
    },
  });

  const showInstructions = async (id: string) => {
    setInstructions(await api(`/api/domains/${id}/dns-instructions`));
  };

  const provision = useMutation({
    mutationFn: ({ id, tunnelId }: { id: string; tunnelId: string }) =>
      api<{ message: string }>(`/api/domains/${id}/provision-tunnel`, {
        method: "POST",
        body: { tunnel_id: tunnelId },
      }),
    onSuccess: (data) => {
      toast.success(data.message);
      setTunnelFor(null);
      queryClient.invalidateQueries({ queryKey: ["domains"] });
    },
    onError: (e) => toast.error(e.message),
  });

  return (
    <>
      <Topbar
        title="Domains"
        description="Custom domains and subdomains routed through Traefik"
        actions={<Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Add domain</Button>}
      />
      <div className="p-8">
        {isLoading ? (
          <Skeleton className="h-64" />
        ) : !domains?.length ? (
          <EmptyState
            icon={Globe}
            title="No domains configured"
            description="Assign a domain to an application, point its DNS at this server, and Traefik routes traffic with automatic SSL."
            action={<Button onClick={() => setOpen(true)}>Add your first domain</Button>}
          />
        ) : (
          <Card>
            <CardContent className="px-0">
              <Table>
                <THead>
                  <TH>Hostname</TH><TH>Application</TH><TH>SSL</TH><TH>Cert expires</TH><TH>Added</TH><TH className="w-28" />
                </THead>
                <TBody>
                  {domains.map((domain) => (
                    <TR key={domain.id}>
                      <TD>
                        <div className="font-medium">{domain.hostname}</div>
                        {domain.is_primary && <Badge className="mt-1">primary</Badge>}
                      </TD>
                      <TD>
                        <Link href={`/applications/${domain.application_id}`} className="text-primary hover:underline">
                          {domain.application_name}
                        </Link>
                      </TD>
                      <TD><StatusBadge status={domain.ssl_enabled ? domain.ssl_status : "disabled"} /></TD>
                      <TD className="text-muted-foreground">{fmtDate(domain.ssl_expires_at)}</TD>
                      <TD className="text-muted-foreground">{relTime(domain.created_at)}</TD>
                      <TD>
                        <div className="flex gap-1">
                          <Button variant="ghost" size="sm" onClick={() => verify.mutate(domain.id)}>Verify</Button>
                          {cf?.connected && (
                            <Button variant="ghost" size="sm" onClick={() => { setTunnelFor(domain); setSelectedTunnel(cf.tunnels?.[0]?.id ?? ""); }}>
                              <Cloud className="h-4 w-4" /> Tunnel
                            </Button>
                          )}
                          <Button variant="ghost" size="icon" onClick={() => showInstructions(domain.id)} aria-label="DNS instructions">
                            <Info className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" onClick={() => remove.mutate(domain.id)} aria-label="Delete domain">
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </div>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </CardContent>
          </Card>
        )}
      </div>

      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Add domain"
        description="Route a hostname to an application via Traefik."
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={() => add.mutate()} loading={add.isPending} disabled={!hostname.trim() || !appId}>
              Add domain
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>Hostname</Label>
            <Input value={hostname} onChange={(e) => setHostname(e.target.value)} placeholder="app.example.com" />
          </div>
          <div className="space-y-1.5">
            <Label>Application</Label>
            <Select value={appId} onChange={(e) => setAppId(e.target.value)}>
              <option value="">Select application…</option>
              {apps?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </Select>
          </div>
          <div className="flex items-center gap-2">
            <Switch checked={ssl} onChange={setSsl} />
            <Label>Enable HTTPS with Let&apos;s Encrypt</Label>
          </div>
        </div>
      </Dialog>

      <Dialog
        open={!!tunnelFor} onClose={() => setTunnelFor(null)}
        title={`Connect ${tunnelFor?.hostname ?? ""} via Cloudflare Tunnel`}
        description="Creates the tunnel ingress rule and the proxied DNS CNAME automatically. SSL is issued by Cloudflare."
        footer={
          <>
            <Button variant="outline" onClick={() => setTunnelFor(null)}>Cancel</Button>
            <Button
              onClick={() => tunnelFor && provision.mutate({ id: tunnelFor.id, tunnelId: selectedTunnel })}
              loading={provision.isPending}
              disabled={!selectedTunnel}
            >
              Provision now
            </Button>
          </>
        }
      >
        <div className="space-y-1.5">
          <Label>Cloudflare tunnel</Label>
          <Select value={selectedTunnel} onChange={(e) => setSelectedTunnel(e.target.value)}>
            <option value="">Select tunnel…</option>
            {cf?.tunnels?.map((t) => (
              <option key={t.id} value={t.id}>{t.name} — {t.status} ({t.connections} connections)</option>
            ))}
          </Select>
          {!cf?.tunnels?.length && (
            <p className="text-xs text-warning">
              No remote tunnels found. Create one in Zero Trust → Networks → Tunnels, or start a local
              token tunnel on the Networking page (it appears here once registered on Cloudflare).
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            Target service will be http://ld-{tunnelFor?.application_slug}:{tunnelFor?.target_port ?? ""}
          </p>
        </div>
      </Dialog>

      <Dialog
        open={!!instructions}
        onClose={() => setInstructions(null)}
        wide
        title={`DNS setup — ${instructions?.hostname ?? ""}`}
        description="Create these records at your DNS provider."
        footer={<Button variant="outline" onClick={() => setInstructions(null)}>Close</Button>}
      >
        {instructions && (
          <div className="space-y-4">
            <Table>
              <THead><TH>Type</TH><TH>Name</TH><TH>Value</TH><TH>Note</TH></THead>
              <TBody>
                {instructions.records.map((r, i) => (
                  <TR key={i}>
                    <TD><Badge variant="info">{r.type}</Badge></TD>
                    <TD><code>{r.name}</code></TD>
                    <TD>
                      <div className="flex items-center gap-2">
                        <code>{r.value}</code>
                        <button onClick={() => { navigator.clipboard.writeText(r.value); toast.success("Copied"); }} aria-label="Copy">
                          <Copy className="h-3.5 w-3.5 text-muted-foreground" />
                        </button>
                      </div>
                    </TD>
                    <TD className="text-xs text-muted-foreground">{r.note}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            <p className="rounded-lg bg-info/10 p-3 text-xs text-info">{instructions.cloudflare_hint}</p>
          </div>
        )}
      </Dialog>
    </>
  );
}
