"use client";

import { useQuery } from "@tanstack/react-query";
import { HardDrive } from "lucide-react";

import { Topbar } from "@/components/layout";
import { Card, CardContent, CardHeader, CardTitle, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtBytes } from "@/lib/format";

type Summary = {
  disk_used_gb: number;
  disk_total_gb: number;
  disk_percent: number;
  docker: {
    images_size_bytes: number;
    containers_size_bytes: number;
    volumes_size_bytes: number;
    build_cache_size_bytes: number;
  } | null;
};

function Bar({ label, value, total, color }: { label: string; value: number; total: number; color: string }) {
  const percent = total > 0 ? Math.min(100, (value / total) * 100) : 0;
  return (
    <div>
      <div className="mb-1 flex justify-between text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium">{fmtBytes(value)} ({percent.toFixed(1)}%)</span>
      </div>
      <div className="h-2.5 w-full overflow-hidden rounded-full bg-muted">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

export default function StoragePage() {
  const { data, isLoading } = useQuery<Summary>({
    queryKey: ["storage", "summary"],
    queryFn: () => api("/api/storage/summary"),
    refetchInterval: 15_000,
  });

  if (isLoading || !data) {
    return (
      <>
        <Topbar title="Storage" description="Disk and Docker storage usage" />
        <div className="space-y-4 p-8">{[0, 1].map((i) => <Skeleton key={i} className="h-40" />)}</div>
      </>
    );
  }

  const docker = data.docker;

  return (
    <>
      <Topbar title="Storage" description="Disk and Docker storage usage" />
      <div className="grid gap-4 p-8 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Host disk</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <Bar
              label="Used"
              value={data.disk_used_gb * 1024 ** 3}
              total={data.disk_total_gb * 1024 ** 3}
              color={data.disk_percent > 85 ? "bg-destructive" : "bg-primary"}
            />
            <p className="text-sm text-muted-foreground">
              {data.disk_used_gb.toFixed(1)} GB of {data.disk_total_gb.toFixed(1)} GB used ({data.disk_percent.toFixed(1)}%)
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Docker storage</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {!docker ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <HardDrive className="h-4 w-4" /> Docker Engine offline — usage unavailable.
              </p>
            ) : (
              <>
                <Bar label="Images" value={docker.images_size_bytes} total={docker.images_size_bytes + docker.containers_size_bytes + docker.volumes_size_bytes + docker.build_cache_size_bytes} color="bg-info" />
                <Bar label="Volumes" value={docker.volumes_size_bytes} total={docker.images_size_bytes + docker.containers_size_bytes + docker.volumes_size_bytes + docker.build_cache_size_bytes} color="bg-primary" />
                <Bar label="Containers (writable layer)" value={docker.containers_size_bytes} total={docker.images_size_bytes + docker.containers_size_bytes + docker.volumes_size_bytes + docker.build_cache_size_bytes} color="bg-warning" />
                <Bar label="Build cache" value={docker.build_cache_size_bytes} total={docker.images_size_bytes + docker.containers_size_bytes + docker.volumes_size_bytes + docker.build_cache_size_bytes} color="bg-muted-foreground" />
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
