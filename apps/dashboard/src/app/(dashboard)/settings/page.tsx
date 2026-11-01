"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ScrollText, ShieldCheck, Trash2, UserPlus, Users } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Topbar } from "@/components/layout";
import { NotificationsTab, TokensTab } from "@/components/settings-ops";
import { ServersTab } from "@/components/servers-ops";
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, ConfirmDialog, Dialog, Input, Label,
  Select, Skeleton, Switch, TD, TBody, TH, THead, TR, Table,
} from "@/components/ui";
import { api } from "@/lib/api";
import { relTime } from "@/lib/format";
import type { AuditLogEntry, Role, User } from "@/lib/types";

type Tab = "profile" | "users" | "security" | "notifications" | "tokens" | "servers";

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("profile");

  const tabs: Array<{ id: Tab; label: string }> = [
    { id: "profile", label: "Profile" },
    { id: "users", label: "Users & roles" },
    { id: "notifications", label: "Notifications" },
    { id: "tokens", label: "API tokens" },
    { id: "servers", label: "Servers" },
    { id: "security", label: "Audit & security" },
  ];

  return (
    <>
      <Topbar title="Settings" description="Profile, team access and platform security" />
      <div className="p-8">
        <div className="mb-6 flex gap-1 border-b border-border">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`border-b-2 px-4 py-2.5 text-sm transition-colors ${
                tab === t.id ? "border-primary font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        {tab === "profile" && <ProfileTab />}
        {tab === "users" && <UsersTab />}
        {tab === "notifications" && <NotificationsTab />}
        {tab === "tokens" && <TokensTab />}
        {tab === "servers" && <ServersTab />}
        {tab === "security" && <SecurityTab />}
      </div>
    </>
  );
}

function ProfileTab() {
  const queryClient = useQueryClient();
  const { data: me } = useQuery<User>({ queryKey: ["me"], queryFn: () => api("/api/auth/me") });
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");

  const changePassword = useMutation({
    mutationFn: () => api("/api/auth/change-password", {
      method: "POST",
      body: { current_password: current, new_password: next },
    }),
    onSuccess: () => {
      toast.success("Password changed — other sessions revoked");
      setCurrent(""); setNext("");
      queryClient.invalidateQueries({ queryKey: ["me"] });
    },
    onError: (e) => toast.error(e.message),
  });

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>Account</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div className="flex justify-between border-b border-border py-2"><span className="text-muted-foreground">Username</span><span>{me?.username}</span></div>
          <div className="flex justify-between border-b border-border py-2"><span className="text-muted-foreground">Email</span><span>{me?.email}</span></div>
          <div className="flex justify-between border-b border-border py-2"><span className="text-muted-foreground">Role</span><Badge variant="info">{me?.role_name}</Badge></div>
          <div className="flex justify-between py-2"><span className="text-muted-foreground">Last login</span><span>{relTime(me?.last_login_at)}</span></div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Change password</CardTitle>
          <p className="text-sm text-muted-foreground">Passwords are hashed with Argon2id. Changing it revokes all other sessions.</p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label>Current password</Label>
            <Input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label>New password (min 8 chars)</Label>
            <Input type="password" value={next} onChange={(e) => setNext(e.target.value)} />
          </div>
          <Button onClick={() => changePassword.mutate()} loading={changePassword.isPending} disabled={!current || next.length < 8}>
            Update password
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

function UsersTab() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [form, setForm] = useState({ username: "", email: "", password: "", role_id: "" });

  const { data: users, isLoading } = useQuery<User[]>({
    queryKey: ["users"],
    queryFn: () => api("/api/users"),
  });

  const { data: roles } = useQuery<Role[]>({
    queryKey: ["roles"],
    queryFn: () => api("/api/users/roles"),
  });

  const create = useMutation({
    mutationFn: () => api("/api/users", { method: "POST", body: form }),
    onSuccess: () => {
      toast.success("User created");
      setOpen(false);
      setForm({ username: "", email: "", password: "", role_id: "" });
      queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const toggleActive = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      api(`/api/users/${id}`, { method: "PUT", body: { is_active } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
    onError: (e) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/users/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("User deleted");
      queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => toast.error(e.message),
  });

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2"><Users className="h-4 w-4" /> Users</CardTitle>
        <Button onClick={() => setOpen(true)}><UserPlus className="h-4 w-4" /> Add user</Button>
      </CardHeader>
      <CardContent className="px-0">
        {isLoading ? (
          <Skeleton className="mx-5 h-40" />
        ) : (
          <Table>
            <THead>
              <TH>Username</TH><TH>Email</TH><TH>Role</TH><TH>Active</TH><TH>Last login</TH><TH className="w-16" />
            </THead>
            <TBody>
              {(users ?? []).map((user) => (
                <TR key={user.id}>
                  <TD className="font-medium">{user.username}</TD>
                  <TD className="text-muted-foreground">{user.email}</TD>
                  <TD><Badge variant="info">{user.role_name}</Badge></TD>
                  <TD>
                    <Switch
                      checked={user.is_active}
                      onChange={(v) => toggleActive.mutate({ id: user.id, is_active: v })}
                    />
                  </TD>
                  <TD className="text-muted-foreground">{relTime(user.last_login_at)}</TD>
                  <TD>
                    <Button variant="ghost" size="icon" onClick={() => setDeleteId(user.id)} aria-label="Delete user">
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </CardContent>

      <Dialog
        open={open} onClose={() => setOpen(false)} title="Add user"
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={() => create.mutate()} loading={create.isPending} disabled={!form.username || !form.email || form.password.length < 8}>
              Create user
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>Username</Label>
            <Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label>Email</Label>
            <Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label>Password (min 8 chars)</Label>
            <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label>Role</Label>
            <Select value={form.role_id} onChange={(e) => setForm({ ...form, role_id: e.target.value })}>
              <option value="">No role</option>
              {roles?.map((r) => <option key={r.id} value={r.id}>{r.name} — {r.description}</option>)}
            </Select>
          </div>
        </div>
      </Dialog>

      <ConfirmDialog
        open={!!deleteId}
        onClose={() => setDeleteId(null)}
        onConfirm={() => deleteId && remove.mutate(deleteId)}
        title="Delete user?"
        message="The user will be soft-deleted and can no longer log in."
      />
    </Card>
  );
}

function SecurityTab() {
  const { data, isLoading } = useQuery<{ total: number; logs: AuditLogEntry[] }>({
    queryKey: ["audit", "logs"],
    queryFn: () => api("/api/audit-logs?limit=100"),
    refetchInterval: 15_000,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><ScrollText className="h-4 w-4" /> Audit log</CardTitle>
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <ShieldCheck className="h-4 w-4 text-success" />
          Every security-relevant action is recorded: logins, deployments, domain and database changes.
        </p>
      </CardHeader>
      <CardContent className="px-0">
        {isLoading ? (
          <Skeleton className="mx-5 h-64" />
        ) : (
          <Table>
            <THead>
              <TH>When</TH><TH>User</TH><TH>Action</TH><TH>Resource</TH><TH>IP</TH>
            </THead>
            <TBody>
              {(data?.logs ?? []).map((log) => (
                <TR key={log.id}>
                  <TD className="whitespace-nowrap text-muted-foreground">{relTime(log.created_at)}</TD>
                  <TD>{log.username ?? "system"}</TD>
                  <TD><code className="text-xs">{log.action}</code></TD>
                  <TD className="text-muted-foreground">{log.resource_type ?? "—"}</TD>
                  <TD className="text-muted-foreground">{log.ip_address ?? "—"}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
