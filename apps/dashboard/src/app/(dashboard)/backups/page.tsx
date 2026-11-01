"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Download, Plus, Save, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Topbar } from "@/components/layout";
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, ConfirmDialog, Dialog, EmptyState,
  Input, Label, Select, Skeleton, StatusBadge, TD, TBody, TH, THead, TR, Table,
} from "@/components/ui";
import { API_URL, api } from "@/lib/api";
import { fmtBytes, relTime } from "@/lib/format";
import type { BackupRecord, BackupSchedule, DatabaseInstance, Volume } from "@/lib/types";

export default function BackupsPage() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [volume, setVolume] = useState("");
  const [restoreId, setRestoreId] = useState<BackupRecord | null>(null);
  const [targetVolume, setTargetVolume] = useState("");
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [schedOpen, setSchedOpen] = useState(false);
  const [schedForm, setSchedForm] = useState({ target_type: "volume", target_id: "", interval_hours: "24", keep_last: "7" });

  const { data: backups, isLoading } = useQuery<BackupRecord[]>({
    queryKey: ["backups"],
    queryFn: () => api("/api/backups"),
    refetchInterval: 5_000,
  });

  const { data: volumes } = useQuery<{ volumes: Volume[] }>({
    queryKey: ["storage", "volumes"],
    queryFn: () => api("/api/storage/volumes"),
  });

  const { data: databases } = useQuery<DatabaseInstance[]>({
    queryKey: ["databases"],
    queryFn: () => api("/api/databases"),
  });

  const { data: schedules } = useQuery<BackupSchedule[]>({
    queryKey: ["backup-schedules"],
    queryFn: () => api("/api/backups/schedules/all"),
    refetchInterval: 30_000,
  });

  const createSchedule = useMutation({
    mutationFn: (body: Record<string, unknown>) => api("/api/backups/schedules", { method: "POST", body }),
    onSuccess: () => {
      toast.success("Backup schedule created — the scheduler runs every minute");
      queryClient.invalidateQueries({ queryKey: ["backup-schedules"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const toggleSchedule = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api(`/api/backups/schedules/${id}`, { method: "PUT", body: { enabled } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["backup-schedules"] }),
    onError: (e) => toast.error(e.message),
  });

  const deleteSchedule = useMutation({
    mutationFn: (id: string) => api(`/api/backups/schedules/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Schedule deleted");
      queryClient.invalidateQueries({ queryKey: ["backup-schedules"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const runScheduleNow = useMutation({
    mutationFn: (id: string) => api(`/api/backups/schedules/${id}/run`, { method: "POST" }),
    onSuccess: () => { toast.success("Backup will run within 60 seconds"); queryClient.invalidateQueries({ queryKey: ["backups"] }); },
    onError: (e) => toast.error(e.message),
  });

  const createVolumeBackup = useMutation({
    mutationFn: () => api("/api/backups/volumes", { method: "POST", body: { volume } }),
    onSuccess: () => {
      toast.success("Volume backup started");
      setCreateOpen(false);
      queryClient.invalidateQueries({ queryKey: ["backups"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const restore = useMutation({
    mutationFn: () => api("/api/backups/volumes/restore", {
      method: "POST",
      body: { backup_id: restoreId!.id, target_volume: targetVolume },
    }),
    onSuccess: () => {
      toast.success("Restore started");
      queryClient.invalidateQueries({ queryKey: ["backups"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/backups/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Backup deleted");
      queryClient.invalidateQueries({ queryKey: ["backups"] });
    },
    onError: (e) => toast.error(e.message),
  });

  return (
    <>
      <Topbar
        title="Backups"
        description="Database dumps and volume archives with restore"
        actions={<Button onClick={() => setCreateOpen(true)}><Save className="h-4 w-4" /> Backup a volume</Button>}
      />
      <div className="space-y-6 p-8">
        {/* ---------- schedules ---------- */}
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2"><CalendarClock className="h-4 w-4" /> Scheduled backups</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-end">
              <Button size="sm" onClick={() => setSchedOpen(true)}>
                <Plus className="h-4 w-4" /> Add schedule
              </Button>
            </div>
            {(schedules ?? []).map((schedule) => (
              <div key={schedule.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border p-3">
                <div>
                  <div className="flex items-center gap-2 text-sm font-medium">
                    {schedule.target_name}
                    <Badge variant="info">{schedule.target_type}</Badge>
                    <span className="text-muted-foreground">every {schedule.interval_hours}h · keep {schedule.keep_last}</span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    last run {schedule.last_run_at ? relTime(schedule.last_run_at) : "never"}
                    {schedule.last_status === "failed" && (
                      <span className="text-destructive"> — {schedule.last_error}</span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button size="sm" variant="outline" onClick={() => runScheduleNow.mutate(schedule.id)}>Run now</Button>
                  <Button size="sm" variant="ghost" onClick={() => toggleSchedule.mutate({ id: schedule.id, enabled: !schedule.enabled })}>
                    {schedule.enabled ? "Pause" : "Resume"}
                  </Button>
                  <Button size="icon" variant="ghost" onClick={() => deleteSchedule.mutate(schedule.id)} aria-label="Delete schedule">
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              </div>
            ))}
            {!schedules?.length && (
              <p className="text-sm text-muted-foreground">
                No schedules yet — click <strong>Add schedule</strong> to back up a database or volume automatically.
              </p>
            )}
          </CardContent>
        </Card>

        {/* ---------- records ---------- */}
        {isLoading ? (
          <Skeleton className="h-64" />
        ) : !backups?.length ? (
          <EmptyState
            icon={Save}
            title="No backups yet"
            description="Create backups from here or from each database's detail panel. Restore anything, anytime."
          />
        ) : (
          <Card>
            <CardContent className="px-0">
              <Table>
                <THead>
                  <TH>Type</TH><TH>Target</TH><TH>Status</TH><TH>Size</TH><TH>Created</TH><TH className="w-40">Actions</TH>
                </THead>
                <TBody>
                  {backups.map((record) => (
                    <TR key={record.id}>
                      <TD><code className="text-xs">{record.target_type}</code></TD>
                      <TD className="max-w-48 truncate font-medium" title={record.file}>{record.target_name}</TD>
                      <TD>
                        <StatusBadge status={record.status} />
                        {record.error_message && (
                          <div className="max-w-40 truncate text-xs text-destructive">{record.error_message}</div>
                        )}
                      </TD>
                      <TD className="text-muted-foreground">{fmtBytes(record.file_size_bytes)}</TD>
                      <TD className="text-muted-foreground">{relTime(record.created_at)}</TD>
                      <TD>
                        <div className="flex gap-1">
                          {record.status === "success" && (
                            <>
                              <a href={`${API_URL}/api/backups/${record.id}/download`} target="_blank" rel="noreferrer">
                                <Button variant="ghost" size="icon" title="Download"><Download className="h-4 w-4" /></Button>
                              </a>
                              {record.target_type === "volume" && (
                                <Button variant="ghost" size="sm" onClick={() => { setRestoreId(record); setTargetVolume(record.target_id); }}>
                                  Restore
                                </Button>
                              )}
                            </>
                          )}
                          <Button variant="ghost" size="icon" onClick={() => setDeleteId(record.id)} title="Delete">
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
        open={createOpen} onClose={() => setCreateOpen(false)} title="Backup a volume"
        description="Archives the entire volume content into a .tar.gz stored on the server."
        footer={
          <>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button onClick={() => createVolumeBackup.mutate()} loading={createVolumeBackup.isPending} disabled={!volume}>
              Create backup
            </Button>
          </>
        }
      >
        <div className="space-y-1.5">
          <Label>Volume</Label>
          <Select value={volume} onChange={(e) => setVolume(e.target.value)}>
            <option value="">Select volume…</option>
            {volumes?.volumes.map((v) => <option key={v.name} value={v.name}>{v.name}{v.in_use ? " (in use)" : ""}</option>)}
          </Select>
        </div>
      </Dialog>

      <Dialog
        open={!!restoreId} onClose={() => setRestoreId(null)} title="Restore volume"
        description={`Restoring ${restoreId?.target_name} — pick the destination volume. Existing data is overwritten.`}
        footer={
          <>
            <Button variant="outline" onClick={() => setRestoreId(null)}>Cancel</Button>
            <Button variant="destructive" onClick={() => restore.mutate()} loading={restore.isPending} disabled={!targetVolume}>
              Restore now
            </Button>
          </>
        }
      >
        <div className="space-y-1.5">
          <Label>Target volume</Label>
          <Input value={targetVolume} onChange={(e) => setTargetVolume(e.target.value)} />
        </div>
      </Dialog>

      <ConfirmDialog
        open={!!deleteId}
        onClose={() => setDeleteId(null)}
        onConfirm={() => deleteId && remove.mutate(deleteId)}
        title="Delete backup?"
        message="The backup file will be removed from disk permanently."
      />

      <Dialog
        open={schedOpen} onClose={() => setSchedOpen(false)} title="Add backup schedule"
        description="Runs automatically; keeps only the newest N backups."
        footer={
          <>
            <Button variant="outline" onClick={() => setSchedOpen(false)}>Cancel</Button>
            <Button
              onClick={() => {
                if (!schedForm.target_id) { toast.error("Select a target first"); return; }
                const targetName = schedForm.target_type === "volume"
                  ? (volumes?.volumes ?? []).find((v) => v.name === schedForm.target_id)?.name ?? schedForm.target_id
                  : (databases ?? []).find((d) => d.id === schedForm.target_id)?.name ?? schedForm.target_id;
                createSchedule.mutate({
                  target_type: schedForm.target_type,
                  target_id: schedForm.target_id,
                  target_name: targetName,
                  interval_hours: Number(schedForm.interval_hours) || 24,
                  keep_last: Number(schedForm.keep_last) || 7,
                });
                setSchedOpen(false);
              }}
              loading={createSchedule.isPending}
            >
              Create schedule
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Type</Label>
              <Select value={schedForm.target_type}
                      onChange={(e) => setSchedForm({ ...schedForm, target_type: e.target.value, target_id: "" })}>
                <option value="volume">Volume</option>
                <option value="database">Database</option>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Target</Label>
              <Select value={schedForm.target_id}
                      onChange={(e) => setSchedForm({ ...schedForm, target_id: e.target.value })}>
                <option value="">Select…</option>
                {schedForm.target_type === "volume" &&
                  (volumes?.volumes ?? []).map((v) => <option key={v.name} value={v.name}>{v.name}</option>)}
                {schedForm.target_type === "database" &&
                  (databases ?? []).map((d) => <option key={d.id} value={d.id}>{d.name} ({d.engine})</option>)}
              </Select>
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Every (hours)</Label>
              <Input type="number" min={1} value={schedForm.interval_hours}
                     onChange={(e) => setSchedForm({ ...schedForm, interval_hours: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label>Keep last</Label>
              <Input type="number" min={1} value={schedForm.keep_last}
                     onChange={(e) => setSchedForm({ ...schedForm, keep_last: e.target.value })} />
            </div>
          </div>
        </div>
      </Dialog>

    </>
  );
}
