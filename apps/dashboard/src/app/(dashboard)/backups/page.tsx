"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Save, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Topbar } from "@/components/layout";
import {
  Button, Card, CardContent, CardHeader, CardTitle, ConfirmDialog, Dialog, EmptyState,
  Input, Label, Select, Skeleton, StatusBadge, TD, TBody, TH, THead, TR, Table,
} from "@/components/ui";
import { API_URL, api } from "@/lib/api";
import { fmtBytes, relTime } from "@/lib/format";
import type { BackupRecord, Volume } from "@/lib/types";

export default function BackupsPage() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [volume, setVolume] = useState("");
  const [restoreId, setRestoreId] = useState<BackupRecord | null>(null);
  const [targetVolume, setTargetVolume] = useState("");
  const [deleteId, setDeleteId] = useState<string | null>(null);

  const { data: backups, isLoading } = useQuery<BackupRecord[]>({
    queryKey: ["backups"],
    queryFn: () => api("/api/backups"),
    refetchInterval: 5_000,
  });

  const { data: volumes } = useQuery<{ volumes: Volume[] }>({
    queryKey: ["storage", "volumes"],
    queryFn: () => api("/api/storage/volumes"),
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
      <div className="p-8">
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
    </>
  );
}
