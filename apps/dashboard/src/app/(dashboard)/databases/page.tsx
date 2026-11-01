"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database as DatabaseIcon, Info, Play, Plus, RotateCcw, Square, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Topbar } from "@/components/layout";
import {
  Button, Card, CardContent, CardHeader, CardTitle, ConfirmDialog, Dialog, EmptyState, Input,
  Label, Select, Skeleton, StatusBadge, TD, TBody, TH, THead, TR, Table,
} from "@/components/ui";
import { api } from "@/lib/api";
import { relTime } from "@/lib/format";
import type { BackupRecord, DatabaseInstance } from "@/lib/types";

const ENGINES = [
  { value: "postgresql", label: "PostgreSQL", version: "16-alpine" },
  { value: "mysql", label: "MySQL", version: "8.0" },
  { value: "mariadb", label: "MariaDB", version: "11" },
  { value: "redis", label: "Redis", version: "7-alpine" },
  { value: "mongodb", label: "MongoDB", version: "7" },
];

export default function DatabasesPage() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [connInfo, setConnInfo] = useState<Record<string, unknown> | null>(null);
  const [backupsFor, setBackupsFor] = useState<DatabaseInstance | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", engine: "postgresql", version: "16-alpine", username: "", database_name: "", password: "", published_port: "" });

  const { data: databases, isLoading } = useQuery<DatabaseInstance[]>({
    queryKey: ["databases"],
    queryFn: () => api("/api/databases"),
    refetchInterval: 8_000,
  });

  const { data: backups } = useQuery<BackupRecord[]>({
    queryKey: ["databases", backupsFor?.id, "backups"],
    queryFn: () => api(`/api/databases/${backupsFor!.id}/backups`),
    enabled: !!backupsFor,
    refetchInterval: 3_000,
  });

  const create = useMutation({
    mutationFn: () => api("/api/databases", {
      method: "POST",
      body: {
        name: form.name,
        engine: form.engine,
        version: form.version || undefined,
        username: form.username || undefined,
        database_name: form.database_name || undefined,
        password: form.password || undefined,
        published_port: form.published_port ? Number(form.published_port) : undefined,
      },
    }),
    onSuccess: () => {
      toast.success("Database provisioning started");
      setOpen(false);
      setForm({ name: "", engine: "postgresql", version: "16-alpine", username: "", database_name: "", password: "", published_port: "" });
      queryClient.invalidateQueries({ queryKey: ["databases"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const action = useMutation({
    mutationFn: ({ id, act }: { id: string; act: string }) =>
      api(`/api/databases/${id}/${act}`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["databases"] }),
    onError: (e) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/databases/${id}?remove_volume=true`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Database removed (volume deleted)");
      queryClient.invalidateQueries({ queryKey: ["databases"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const backup = useMutation({
    mutationFn: (id: string) => api(`/api/databases/${id}/backups`, { method: "POST" }),
    onSuccess: () => {
      toast.success("Backup started");
      queryClient.invalidateQueries({ queryKey: ["databases"] });
    },
    onError: (e) => toast.error(e.message),
  });

  return (
    <>
      <Topbar
        title="Databases"
        description="Provisioned datastores on the internal Docker network (never public by default)"
        actions={<Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> New database</Button>}
      />
      <div className="p-8">
        {isLoading ? (
          <Skeleton className="h-64" />
        ) : !databases?.length ? (
          <EmptyState
            icon={DatabaseIcon}
            title="No database instances"
            description="Provision PostgreSQL, MySQL, MariaDB, Redis or MongoDB with persistent volumes, health checks and backups."
            action={<Button onClick={() => setOpen(true)}>Provision a database</Button>}
          />
        ) : (
          <Card>
            <CardContent className="px-0">
              <Table>
                <THead>
                  <TH>Name</TH><TH>Engine</TH><TH>Status</TH><TH>Volume</TH><TH>Created</TH><TH className="w-64">Actions</TH>
                </THead>
                <TBody>
                  {databases.map((db) => (
                    <TR key={db.id}>
                      <TD className="font-medium">{db.name}</TD>
                      <TD>
                        <Badge variant="info">{db.engine}</Badge>
                        <div className="mt-1 text-xs text-muted-foreground">{db.image}</div>
                      </TD>
                      <TD>
                        <StatusBadge status={db.status} />
                        {db.last_error && <div className="max-w-40 truncate text-xs text-destructive">{db.last_error}</div>}
                      </TD>
                      <TD><code className="text-xs">{db.volume_name}</code></TD>
                      <TD className="text-muted-foreground">{relTime(db.created_at)}</TD>
                      <TD>
                        <div className="flex gap-1">
                          <Button variant="ghost" size="icon" title="Start" onClick={() => action.mutate({ id: db.id, act: "start" })}>
                            <Play className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" title="Stop" onClick={() => action.mutate({ id: db.id, act: "stop" })}>
                            <Square className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" title="Restart" onClick={() => action.mutate({ id: db.id, act: "restart" })}>
                            <RotateCcw className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" title="Connection info" onClick={async () => setConnInfo(await api(`/api/databases/${db.id}/connection`))}>
                            <Info className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" title="Backups" onClick={() => setBackupsFor(db)}>
                            <DatabaseIcon className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" title="Delete" onClick={() => setDeleteId(db.id)}>
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

      {/* create dialog */}
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Provision database"
        description="Runs as a managed container on the private network with its own volume."
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={() => create.mutate()} loading={create.isPending} disabled={!form.name.trim()}>
              Provision
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Name *</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value.toLowerCase() })} placeholder="app-db" />
            </div>
            <div className="space-y-1.5">
              <Label>Engine *</Label>
              <Select value={form.engine} onChange={(e) => {
                const engine = e.target.value;
                setForm({ ...form, engine, version: ENGINES.find((x) => x.value === engine)?.version ?? "latest" });
              }}>
                {ENGINES.map((e) => <option key={e.value} value={e.value}>{e.label}</option>)}
              </Select>
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Image tag</Label>
              <Input value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label>Username (optional)</Label>
              <Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Password (blank = generate)</Label>
              <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label>Publish on 127.0.0.1 port (optional)</Label>
              <Input type="number" value={form.published_port} onChange={(e) => setForm({ ...form, published_port: e.target.value })} placeholder="e.g. 15432" />
            </div>
          </div>
          <p className="rounded-lg bg-info/10 p-3 text-xs text-info">
            Ports are never exposed publicly. Applications reach the database over the internal Docker network.
          </p>
        </div>
      </Dialog>

      {/* connection info */}
      <Dialog
        open={!!connInfo}
        onClose={() => setConnInfo(null)}
        wide
        title="Connection information"
        footer={<Button variant="outline" onClick={() => setConnInfo(null)}>Close</Button>}
      >
        {connInfo && (
          <div className="space-y-2 text-sm">
            {Object.entries(connInfo).map(([key, value]) => (
              <div key={key} className="flex items-start justify-between gap-4 border-b border-border py-1.5 last:border-0">
                <span className="text-muted-foreground">{key}</span>
                <code className="max-w-md break-all text-right text-xs">{String(value)}</code>
              </div>
            ))}
          </div>
        )}
      </Dialog>

      {/* backups dialog */}
      <Dialog
        open={!!backupsFor}
        onClose={() => setBackupsFor(null)}
        wide
        title={`Backups — ${backupsFor?.name ?? ""}`}
        footer={
          <>
            <Button variant="outline" onClick={() => setBackupsFor(null)}>Close</Button>
            <Button onClick={() => backupsFor && backup.mutate(backupsFor.id)}>Create backup now</Button>
          </>
        }
      >
        <Table>
          <THead><TH>Status</TH><TH>File</TH><TH>Size</TH><TH>Created</TH></THead>
          <TBody>
            {(backups ?? []).map((b) => (
              <TR key={b.id}>
                <TD><StatusBadge status={b.status} /></TD>
                <TD><code className="text-xs">{b.file}</code></TD>
                <TD className="text-muted-foreground">{b.file_size_bytes ? `${(b.file_size_bytes / 1024).toFixed(1)} KB` : "—"}</TD>
                <TD className="text-muted-foreground">{relTime(b.created_at)}</TD>
              </TR>
            ))}
            {!backups?.length && (
              <TR><TD colSpan={4} className="py-6 text-center text-sm text-muted-foreground">No backups yet.</TD></TR>
            )}
          </TBody>
        </Table>
      </Dialog>

      <ConfirmDialog
        open={!!deleteId}
        onClose={() => setDeleteId(null)}
        onConfirm={() => deleteId && remove.mutate(deleteId)}
        title="Delete database?"
        message="The container AND its data volume will be permanently removed."
      />
    </>
  );
}

function Badge({ children, variant }: { children: React.ReactNode; variant?: "info" }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
      variant === "info" ? "bg-info/15 text-info" : "bg-muted text-foreground"
    }`}>
      {children}
    </span>
  );
}
