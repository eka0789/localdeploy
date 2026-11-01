"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, KeyRound, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, ConfirmDialog, Dialog, Input, Label,
  Select, TD, TBody, TH, THead, TR, Table,
} from "@/components/ui";
import { api } from "@/lib/api";
import { relTime } from "@/lib/format";
import type { ApiToken, NotificationChannel } from "@/lib/types";

const EVENT_OPTIONS = ["deployment.success", "deployment.failed", "container.died"];

/* ------------------------------------------------------- notifications */

export function NotificationsTab() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<{
    name: string; type: string; url: string; bot_token: string; chat_id: string; events: string[];
  }>({
    name: "", type: "discord", url: "", bot_token: "", chat_id: "",
    events: ["deployment.success", "deployment.failed", "container.died"],
  });
  const [testingId, setTestingId] = useState<string | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);

  const { data: channels } = useQuery<NotificationChannel[]>({
    queryKey: ["notifications"],
    queryFn: () => api("/api/notifications"),
  });

  const save = useMutation({
    mutationFn: () => api("/api/notifications", { method: "POST", body: form }),
    onSuccess: () => {
      toast.success("Notification channel added");
      setOpen(false);
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const test = useMutation({
    mutationFn: (id: string) => api(`/api/notifications/${id}/test`, { method: "POST" }),
    onMutate: (id) => setTestingId(id),
    onSuccess: () => toast.success("Test sent — check your channel"),
    onSettled: () => setTestingId(null),
    onError: (e) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/notifications/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Channel deleted");
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const toggleEvent = (event: string) => {
    setForm((f) => ({
      ...f,
      events: f.events.includes(event) ? f.events.filter((x) => x !== event) : [...f.events, event],
    }));
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => setOpen(true)}><Bell className="h-4 w-4" /> Add channel</Button>
      </div>

      {!channels?.length ? (
        <p className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          No notification channels yet. Get pinged on Discord/Telegram/Slack when a deployment
          succeeds or fails, or when a container dies unexpectedly.
        </p>
      ) : (
        channels.map((channel) => (
          <div key={channel.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border p-4">
            <div>
              <div className="flex items-center gap-2 font-medium">
                {channel.name}
                <Badge variant="info">{channel.type}</Badge>
                {!channel.is_active && <Badge>inactive</Badge>}
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                {channel.events.map((e) => (
                  <code key={e} className="rounded bg-muted px-1.5 py-0.5 text-xs">{e}</code>
                ))}
              </div>
              {channel.last_error && <div className="mt-1 text-xs text-destructive">{channel.last_error}</div>}
            </div>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" loading={testingId === channel.id} onClick={() => test.mutate(channel.id)}>
                Send test
              </Button>
              <Button size="icon" variant="ghost" onClick={() => setDeleteId(channel.id)} aria-label="Delete channel">
                <Trash2 className="h-4 w-4 text-destructive" />
              </Button>
            </div>
          </div>
        ))
      )}

      <Dialog
        open={open} onClose={() => setOpen(false)} title="Add notification channel"
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!form.name.trim()}>
              Add channel
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Name</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Ops alerts" />
            </div>
            <div className="space-y-1.5">
              <Label>Type</Label>
              <Select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                <option value="discord">Discord webhook</option>
                <option value="slack">Slack webhook</option>
                <option value="telegram">Telegram bot</option>
                <option value="webhook">Generic webhook</option>
              </Select>
            </div>
          </div>
          {form.type === "telegram" ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>Bot token</Label>
                <Input type="password" value={form.bot_token} onChange={(e) => setForm({ ...form, bot_token: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>Chat ID</Label>
                <Input value={form.chat_id} onChange={(e) => setForm({ ...form, chat_id: e.target.value })} />
              </div>
            </div>
          ) : (
            <div className="space-y-1.5">
              <Label>Webhook URL</Label>
              <Input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })}
                     placeholder={form.type === "discord" ? "https://discord.com/api/webhooks/…" : "https://…"} />
            </div>
          )}
          <div>
            <Label>Notify on</Label>
            <div className="mt-2 flex flex-wrap gap-2">
              {EVENT_OPTIONS.map((event) => (
                <button
                  key={event} type="button" onClick={() => toggleEvent(event)}
                  className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                    form.events.includes(event)
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground"
                  }`}
                >
                  {event}
                </button>
              ))}
            </div>
          </div>
        </div>
      </Dialog>

      <ConfirmDialog
        open={!!deleteId} onClose={() => setDeleteId(null)}
        onConfirm={() => deleteId && remove.mutate(deleteId)}
        title="Delete channel?"
        message="You will stop receiving notifications from this channel."
      />
    </div>
  );
}

/* ------------------------------------------------------- API tokens */

export function TokensTab() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [created, setCreated] = useState<{ token: string; usage: string } | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);

  const { data: tokens } = useQuery<ApiToken[]>({
    queryKey: ["api-tokens"],
    queryFn: () => api("/api/auth/tokens"),
  });

  const create = useMutation({
    mutationFn: () => api<{ token: string; usage: string }>("/api/auth/tokens", { method: "POST", body: { name } }),
    onSuccess: (data) => {
      setCreated(data);
      setName("");
      queryClient.invalidateQueries({ queryKey: ["api-tokens"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const revoke = useMutation({
    mutationFn: (id: string) => api(`/api/auth/tokens/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Token revoked");
      queryClient.invalidateQueries({ queryKey: ["api-tokens"] });
    },
    onError: (e) => toast.error(e.message),
  });

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><KeyRound className="h-4 w-4" /> Personal access tokens</CardTitle>
          <p className="text-sm text-muted-foreground">
            Trigger deployments from CI/CD (GitHub Actions, scripts) with{" "}
            <code>Authorization: Bearer ldt_…</code>. The token is shown only once.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-end gap-3">
            <div className="flex-1 space-y-1.5">
              <Label>Token name</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="github-actions-deploy" />
            </div>
            <Button onClick={() => create.mutate()} loading={create.isPending} disabled={!name.trim()}>
              Generate token
            </Button>
          </div>

          {created && (
            <div className="rounded-lg border border-primary/40 bg-primary/5 p-4">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-primary">
                Copy it now — shown only once
              </p>
              <code className="block break-all text-xs">{created.token}</code>
              <p className="mt-3 text-xs text-muted-foreground">Example usage:</p>
              <code className="block break-all text-xs text-muted-foreground">{created.usage}</code>
            </div>
          )}

          <Table>
            <THead><TH>Name</TH><TH>Prefix</TH><TH>Last used</TH><TH>Created</TH><TH className="w-16" /></THead>
            <TBody>
              {(tokens ?? []).map((t) => (
                <TR key={t.id}>
                  <TD className="font-medium">{t.name}</TD>
                  <TD><code className="text-xs">{t.prefix}…</code></TD>
                  <TD className="text-muted-foreground">{t.last_used_at ? relTime(t.last_used_at) : "never"}</TD>
                  <TD className="text-muted-foreground">{relTime(t.created_at)}</TD>
                  <TD>
                    <Button size="icon" variant="ghost" onClick={() => setDeleteId(t.id)} aria-label="Revoke token">
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </TD>
                </TR>
              ))}
              {!tokens?.length && (
                <TR><TD colSpan={5} className="py-6 text-center text-sm text-muted-foreground">No tokens yet.</TD></TR>
              )}
            </TBody>
          </Table>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={!!deleteId} onClose={() => setDeleteId(null)}
        onConfirm={() => deleteId && revoke.mutate(deleteId)}
        title="Revoke token?"
        message="Any CI/CD pipeline using this token will immediately lose access."
        confirmLabel="Revoke"
      />
    </div>
  );
}
