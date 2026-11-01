"use client";

import { useQuery } from "@tanstack/react-query";
import { Gauge } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Topbar } from "@/components/layout";
import {
  Button, Card, CardContent, CardHeader, CardTitle, EmptyState, Select,
  StatusBadge, TD, TBody, TH, THead, TR, Table,
} from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDuration, relTime } from "@/lib/format";
import { useLogStream } from "@/lib/use-log-stream";
import type { Deployment } from "@/lib/types";

export default function DeploymentsPage() {
  const [status, setStatus] = useState("");
  const { data: deployments, isLoading } = useQuery<Deployment[]>({
    queryKey: ["deployments", "all", status],
    queryFn: () => api(`/api/deployments?limit=100${status ? `&status=${status}` : ""}`),
    refetchInterval: 5_000,
  });

  return (
    <>
      <Topbar
        title="Deployments"
        description="Build history across every application"
        actions={
          <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-40">
            <option value="">All statuses</option>
            <option value="running">Running</option>
            <option value="success">Success</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
          </Select>
        }
      />
      <div className="grid gap-4 p-8 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardContent className="px-0">
            {isLoading ? (
              <p className="px-5 py-6 text-sm text-muted-foreground">Loading…</p>
            ) : !deployments?.length ? (
              <div className="p-5">
                <EmptyState
                  icon={Gauge}
                  title="No deployments"
                  description="Deploy an application to see its build history here."
                />
              </div>
            ) : (
              <Table>
                <THead>
                  <TH>Application</TH><TH>Status</TH><TH>Trigger</TH><TH>Commit</TH><TH>Duration</TH><TH>When</TH>
                </THead>
                <TBody>
                  {deployments.map((d) => (
                    <DeploymentRow key={d.id} deployment={d} onSelect={() => window.dispatchEvent(
                      new CustomEvent("select-deployment", { detail: d.id })
                    )} />
                  ))}
                </TBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <DeploymentDetail className="lg:col-span-2" />
      </div>
    </>
  );
}

function DeploymentRow({ deployment, onSelect }: { deployment: Deployment; onSelect: () => void }) {
  return (
    <TR className="cursor-pointer" onClick={onSelect}>
      <TD>
        <Link href={`/applications/${deployment.application_id}`} onClick={(e) => e.stopPropagation()} className="font-medium hover:underline">
          {deployment.application_name}
        </Link>
        {deployment.error_message && (
          <div className="max-w-xs truncate text-xs text-destructive">{deployment.error_message}</div>
        )}
      </TD>
      <TD><StatusBadge status={deployment.status} /></TD>
      <TD className="text-muted-foreground">{deployment.trigger}</TD>
      <TD><code className="text-xs">{deployment.git_commit_sha?.slice(0, 8) ?? "—"}</code></TD>
      <TD className="text-muted-foreground">{fmtDuration(deployment.build_duration_ms)}</TD>
      <TD className="text-muted-foreground">{relTime(deployment.created_at)}</TD>
    </TR>
  );
}

function DeploymentDetail({ className }: { className?: string }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    const handler = (e: Event) => setSelectedId((e as CustomEvent<string>).detail);
    window.addEventListener("select-deployment", handler);
    return () => window.removeEventListener("select-deployment", handler);
  }, []);

  const { data: deployment } = useQuery<Deployment>({
    queryKey: ["deployment", selectedId],
    queryFn: () => api(`/api/deployments/${selectedId}`),
    enabled: !!selectedId,
    refetchInterval: 3_000,
  });

  const { lines } = useLogStream(selectedId ? `/api/deployments/${selectedId}/stream` : null);

  return (
    <Card className={className}>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Deployment detail</CardTitle>
        {deployment && <StatusBadge status={deployment.status} />}
      </CardHeader>
      <CardContent>
        {!selectedId ? (
          <p className="py-10 text-center text-sm text-muted-foreground">Select a deployment to inspect it.</p>
        ) : (
          <div className="space-y-3">
            {deployment && (
              <div className="space-y-1 text-sm">
                <div><span className="text-muted-foreground">App: </span>{deployment.application_name}</div>
                <div><span className="text-muted-foreground">Image: </span><code className="text-xs">{deployment.image_tag ?? "—"}</code></div>
                <div><span className="text-muted-foreground">Branch: </span>{deployment.git_branch ?? "—"}</div>
                {deployment.git_message && <div className="text-muted-foreground">“{deployment.git_message}”</div>}
                {deployment.error_message && (
                  <div className="rounded-lg bg-destructive/10 p-2 text-xs text-destructive">{deployment.error_message}</div>
                )}
              </div>
            )}
            <div className="log-view max-h-[360px] overflow-y-auto rounded-lg bg-black/80 p-3 text-green-100">
              {lines.map((line, i) => (
                <div key={i} className={line.stream === "stderr" ? "text-red-300" : ""}>{line.message}</div>
              ))}
              {!lines.length && <div className="text-gray-500">Loading logs… (live stream attaches on selection)</div>}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
