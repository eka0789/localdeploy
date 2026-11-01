"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Database, Link2, Plug, Plus, Trash2, Unlink, XCircle, Zap } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, ConfirmDialog, Dialog, EmptyState,
  Input, Label, Select, StatusBadge, TD, TBody, TH, THead, TR, Table, Textarea,
} from "@/components/ui";
import { api } from "@/lib/api";
import { relTime } from "@/lib/format";
import type { AppDatabaseLink, DatabaseConnection, DbProvider } from "@/lib/types";

/* ================================================================
   External connections library (Databases page → "External" tab)
   ================================================================ */

interface FormState {
  name: string;
  provider: string;
  url: string;
  username: string;
  password: string;
  database_name: string;
  extra: Record<string, string>;
  notes: string;
}

const EMPTY_FORM: FormState = {
  name: "", provider: "supabase", url: "", username: "", password: "",
  database_name: "", extra: {}, notes: "",
};

export function ExternalDatabases() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);

  const { data: connections } = useQuery<DatabaseConnection[]>({
    queryKey: ["db-connections"],
    queryFn: () => api("/api/db-connections"),
    refetchInterval: 15_000,
  });

  const { data: providers } = useQuery<DbProvider[]>({
    queryKey: ["db-providers"],
    queryFn: () => api("/api/db-connections/providers"),
  });

  const provider = providers?.find((p) => p.key === form.provider);

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: form.name,
        provider: form.provider,
        url: form.url || null,
        username: form.username || null,
        password: form.password || null,
        database_name: form.database_name || null,
        extra_secrets: form.extra,
        notes: form.notes || null,
      };
      return editingId
        ? api(`/api/db-connections/${editingId}`, { method: "PUT", body })
        : api("/api/db-connections", { method: "POST", body });
    },
    onSuccess: () => {
      toast.success(editingId ? "Connection updated" : "Connection saved (credentials encrypted)");
      setOpen(false);
      setForm(EMPTY_FORM);
      setEditingId(null);
      queryClient.invalidateQueries({ queryKey: ["db-connections"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const test = useMutation({
    mutationFn: (id: string) => api<{ status: string; error: string | null }>(`/api/db-connections/${id}/test`, { method: "POST" }),
    onMutate: (id) => setTestingId(id),
    onSuccess: (data) => {
      if (data.status === "connected") toast.success("Connected — real query executed OK");
      else if (data.status === "reachable") toast.warning(`Reachable but not fully verified: ${data.error}`);
      else toast.error(`Failed: ${data.error}`);
      queryClient.invalidateQueries({ queryKey: ["db-connections"] });
    },
    onSettled: () => setTestingId(null),
    onError: (e) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/db-connections/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Connection deleted");
      queryClient.invalidateQueries({ queryKey: ["db-connections"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const startEdit = (connection: DatabaseConnection) => {
    setEditingId(connection.id);
    setForm({
      name: connection.name,
      provider: connection.provider,
      url: "", username: connection.username ?? "",
      password: "", database_name: connection.database_name ?? "",
      extra: {}, notes: connection.notes ?? "",
    });
    setOpen(true);
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => { setEditingId(null); setForm(EMPTY_FORM); setOpen(true); }}>
          <Plus className="h-4 w-4" /> Add connection
        </Button>
      </div>

      {!connections?.length ? (
        <EmptyState
          icon={Plug}
          title="No external database connections"
          description="Connect Supabase, Neon, Turso, MongoDB Atlas, Upstash, PlanetScale — or any connection string. Link them to applications and DATABASE_URL etc. are injected automatically on every deploy."
          action={<Button onClick={() => setOpen(true)}>Add your first connection</Button>}
        />
      ) : (
        <Card>
          <CardContent className="px-0">
            <Table>
              <THead>
                <TH>Name</TH><TH>Provider</TH><TH>Endpoint</TH><TH>Health</TH><TH className="w-52">Actions</TH>
              </THead>
              <TBody>
                {connections.map((connection) => (
                  <TR key={connection.id}>
                    <TD>
                      <div className="font-medium">{connection.name}</div>
                      <div className="text-xs text-muted-foreground">{connection.username ?? ""}{connection.database_name ? ` · ${connection.database_name}` : ""}</div>
                    </TD>
                    <TD><Badge variant="info">{connection.provider}</Badge></TD>
                    <TD><code className="text-xs">{connection.host ?? "—"}{connection.port ? `:${connection.port}` : ""}</code></TD>
                    <TD>
                      {connection.last_test_status === "connected" && (
                        <span className="flex items-center gap-1 text-xs text-success"><CheckCircle2 className="h-3.5 w-3.5" /> connected</span>
                      )}
                      {connection.last_test_status === "reachable" && (
                        <span className="flex items-center gap-1 text-xs text-warning"><Zap className="h-3.5 w-3.5" /> reachable</span>
                      )}
                      {connection.last_test_status === "failed" && (
                        <span className="flex items-center gap-1 text-xs text-destructive"><XCircle className="h-3.5 w-3.5" /> failed</span>
                      )}
                      {!connection.last_test_status && <span className="text-xs text-muted-foreground">untested</span>}
                      {connection.last_tested_at && (
                        <div className="text-xs text-muted-foreground">{relTime(connection.last_tested_at)}</div>
                      )}
                    </TD>
                    <TD>
                      <div className="flex gap-1">
                        <Button size="sm" variant="outline" loading={testingId === connection.id}
                                onClick={() => test.mutate(connection.id)}>
                          Test
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => startEdit(connection)}>Edit</Button>
                        <Button size="icon" variant="ghost" onClick={() => setDeleteId(connection.id)} aria-label="Delete">
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

      <Dialog
        open={open} onClose={() => { setOpen(false); setEditingId(null); }} wide
        title={editingId ? "Edit connection" : "Add external database"}
        description="Credentials are encrypted at rest and injected into linked applications at deploy time."
        footer={
          <>
            <Button variant="outline" onClick={() => { setOpen(false); setEditingId(null); }}>Cancel</Button>
            <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!form.name.trim()}>
              {editingId ? "Save changes" : "Save connection"}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Name *</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="production-db" />
            </div>
            <div className="space-y-1.5">
              <Label>Provider</Label>
              <Select value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value, extra: {} })}>
                {providers?.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
              </Select>
            </div>
          </div>

          {provider && (
            <p className="rounded-lg bg-info/10 p-3 text-xs text-info">
              {provider.docs}<br />
              <code className="text-[11px] opacity-80">{provider.url_scheme}</code>
            </p>
          )}

          <div className="space-y-1.5">
            <Label>Connection URL</Label>
            <Input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })}
                   placeholder={provider?.url_scheme ?? "postgresql://…"} />
          </div>

          {provider?.fields.map((fieldName) => (
            <div key={fieldName} className="space-y-1.5">
              <Label className="capitalize">{fieldName.replace(/_/g, " ")}</Label>
              <Input
                type={fieldName.includes("token") || fieldName.includes("key") ? "password" : "text"}
                value={form.extra[fieldName] ?? ""}
                onChange={(e) => setForm({ ...form, extra: { ...form.extra, [fieldName]: e.target.value } })}
              />
            </div>
          ))}

          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label>Username (if not in URL)</Label>
              <Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label>Password (if not in URL)</Label>
              <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label>Database name</Label>
              <Input value={form.database_name} onChange={(e) => setForm({ ...form, database_name: e.target.value })} />
            </div>
          </div>

          {provider && Object.keys(provider.default_env).length > 0 && (
            <p className="text-xs text-muted-foreground">
              Default env vars injected when linked:{" "}
              {Object.keys(provider.default_env).map((k) => (
                <code key={k} className="mr-1 rounded bg-muted px-1.5 py-0.5">{k}</code>
              ))}
            </p>
          )}

          <div className="space-y-1.5">
            <Label>Notes (optional)</Label>
            <Textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </div>
        </div>
      </Dialog>

      <ConfirmDialog
        open={!!deleteId} onClose={() => setDeleteId(null)}
        onConfirm={() => deleteId && remove.mutate(deleteId)}
        title="Delete connection?"
        message="Applications linked to it will stop receiving its environment variables on the next deploy."
      />
    </div>
  );
}

/* ================================================================
   Per-application links (Application detail → "Databases" tab)
   ================================================================ */

export function AppDatabaseLinks({ appId }: { appId: string }) {
  const queryClient = useQueryClient();
  const [linkOpen, setLinkOpen] = useState(false);
  const [selectedId, setSelectedId] = useState("");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [newKey, setNewKey] = useState("");
  const [newRef, setNewRef] = useState("url");
  const [unlinkConnection, setUnlinkConnection] = useState<DatabaseConnection | null>(null);

  const { data: links } = useQuery<AppDatabaseLink[]>({
    queryKey: ["db-links", appId],
    queryFn: () => api(`/api/db-connections/links/${appId}`),
  });

  const { data: connections } = useQuery<DatabaseConnection[]>({
    queryKey: ["db-connections"],
    queryFn: () => api("/api/db-connections"),
  });

  const { data: providers } = useQuery<DbProvider[]>({
    queryKey: ["db-providers"],
    queryFn: () => api("/api/db-connections/providers"),
  });

  const selected = connections?.find((c) => c.id === selectedId);
  const selectedPreset = providers?.find((p) => p.key === selected?.provider);

  const link = useMutation({
    mutationFn: () => api("/api/db-connections/links", {
      method: "POST",
      body: { application_id: appId, connection_id: selectedId, env_mapping: mapping },
    }),
    onSuccess: () => {
      toast.success("Database linked — env vars will be injected on next deploy");
      setLinkOpen(false);
      setSelectedId("");
      queryClient.invalidateQueries({ queryKey: ["db-links", appId] });
    },
    onError: (e) => toast.error(e.message),
  });

  const unlink = useMutation({
    mutationFn: (connectionId: string) =>
      api(`/api/db-connections/links/${appId}/${connectionId}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Link removed");
      queryClient.invalidateQueries({ queryKey: ["db-links", appId] });
    },
    onError: (e) => toast.error(e.message),
  });

  const openLinkDialog = () => {
    const first = connections?.[0];
    setSelectedId(first?.id ?? "");
    setMapping(first ? (providers?.find((p) => p.key === first.provider)?.default_env ?? {}) : {});
    setLinkOpen(true);
  };

  const onSelectedChange = (id: string) => {
    setSelectedId(id);
    const connection = connections?.find((c) => c.id === id);
    setMapping(connection ? (providers?.find((p) => p.key === connection.provider)?.default_env ?? {}) : {});
  };

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2">
          <Database className="h-4 w-4" /> Linked databases
        </CardTitle>
        <Button size="sm" onClick={openLinkDialog} disabled={!connections?.length}>
          <Link2 className="h-4 w-4" /> Link database
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {!links?.length ? (
          <p className="text-sm text-muted-foreground">
            No database linked. Link Supabase/Neon/Turso/etc. and its credentials are injected as
            environment variables on every deploy — no manual copying of secrets.
            {!connections?.length && " Add one under Databases → External first."}
          </p>
        ) : (
          links.map((item) => (
            <div key={item.link_id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border p-4">
              <div>
                <div className="flex items-center gap-2 font-medium">
                  {item.connection.name}
                  <Badge variant="info">{item.connection.provider}</Badge>
                  {item.connection.last_test_status === "connected" && <StatusBadge status="success" />}
                </div>
                <div className="mt-1 flex flex-wrap gap-1">
                  {item.env_keys.map((key) => (
                    <code key={key} className="rounded bg-muted px-1.5 py-0.5 text-xs">{key}</code>
                  ))}
                </div>
              </div>
              <Button size="sm" variant="ghost" onClick={() => setUnlinkConnection(item.connection)}>
                <Unlink className="h-4 w-4 text-destructive" /> Unlink
              </Button>
            </div>
          ))
        )}
      </CardContent>

      <Dialog
        open={linkOpen} onClose={() => setLinkOpen(false)}
        title="Link database to application"
        description="Choose which environment variables receive the credentials."
        footer={
          <>
            <Button variant="outline" onClick={() => setLinkOpen(false)}>Cancel</Button>
            <Button onClick={() => link.mutate()} loading={link.isPending} disabled={!selectedId || Object.keys(mapping).length === 0}>
              Link database
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>Connection</Label>
            <Select value={selectedId} onChange={(e) => onSelectedChange(e.target.value)}>
              <option value="">Select connection…</option>
              {connections?.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.provider})</option>)}
            </Select>
          </div>

          {selectedPreset && (
            <p className="text-xs text-muted-foreground">Preset for {selectedPreset.label}:</p>
          )}

          <div className="space-y-2">
            {Object.entries(mapping).map(([envKey, ref]) => (
              <div key={envKey} className="flex items-center gap-2">
                <code className="min-w-40 rounded bg-muted px-2 py-1 text-xs">{envKey}</code>
                <span className="text-muted-foreground">←</span>
                <code className="text-xs text-muted-foreground">{ref}</code>
                <button
                  className="ml-auto text-muted-foreground hover:text-destructive"
                  onClick={() => setMapping((m) => { const copy = { ...m }; delete copy[envKey]; return copy; })}
                  aria-label={`Remove ${envKey}`}
                >
                  <XCircle className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>

          <div className="flex items-end gap-2 border-t border-border pt-3">
            <div className="flex-1 space-y-1.5">
              <Label>Env var name</Label>
              <Input value={newKey} onChange={(e) => setNewKey(e.target.value.toUpperCase())} placeholder="DATABASE_URL" />
            </div>
            <div className="flex-1 space-y-1.5">
              <Label>Value from</Label>
              <Select value={newRef} onChange={(e) => setNewRef(e.target.value)}>
                <option value="url">Connection URL</option>
                <option value="username">Username</option>
                <option value="password">Password</option>
                <option value="database">Database name</option>
                <option value="host">Host</option>
                <option value="port">Port</option>
                {Object.keys(selected?.extra_fields ?? {}).map((f) => (
                  <option key={f} value={`extra:${f}`}>{f}</option>
                ))}
              </Select>
            </div>
            <Button variant="outline" disabled={!newKey.trim()}
                    onClick={() => { setMapping((m) => ({ ...m, [newKey]: newRef })); setNewKey(""); }}>
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </Dialog>

      <ConfirmDialog
        open={!!unlinkConnection} onClose={() => setUnlinkConnection(null)}
        onConfirm={() => unlinkConnection && unlink.mutate(unlinkConnection.id)}
        title={`Unlink ${unlinkConnection?.name}?`}
        message="The application will no longer receive these environment variables on the next deploy."
        confirmLabel="Unlink"
      />
    </Card>
  );
}
