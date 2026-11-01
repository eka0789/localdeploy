"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Rocket, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Topbar } from "@/components/layout";
import {
  Button, Card, CardContent, EmptyState, Input, Skeleton,
  StatusBadge, Switch,
} from "@/components/ui";
import { CreateApplicationDialog } from "@/components/create-application-dialog";
import { api } from "@/lib/api";
import { relTime } from "@/lib/format";
import type { Application, Project } from "@/lib/types";

export default function ApplicationsPage() {
  const [createOpen, setCreateOpen] = useState(false);
  const [search, setSearch] = useState("");

  const { data: apps, isLoading } = useQuery<Application[]>({
    queryKey: ["applications"],
    queryFn: () => api("/api/applications"),
    refetchInterval: 8_000,
  });

  const filtered = useMemo(
    () => (apps ?? []).filter((a) =>
      a.name.toLowerCase().includes(search.toLowerCase()) ||
      a.slug.includes(search.toLowerCase()) ||
      a.domains.some((d) => d.includes(search.toLowerCase()))),
    [apps, search],
  );

  return (
    <>
      <Topbar
        title="Applications"
        description="Every website and app hosted on this machine"
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" /> New application
          </Button>
        }
      />
      <div className="space-y-4 p-8">
        <div className="relative max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-9"
            placeholder="Search applications…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {isLoading ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((i) => <Skeleton key={i} className="h-40" />)}
          </div>
        ) : !filtered.length ? (
          <EmptyState
            icon={Rocket}
            title={search ? "No matching applications" : "No applications yet"}
            description={
              search
                ? "Try a different search term."
                : "Deploy from Git, Dockerfile, Compose, a prebuilt image, or an uploaded archive."
            }
            action={!search && <Button onClick={() => setCreateOpen(true)}>Create your first application</Button>}
          />
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {filtered.map((app) => (
              <Link key={app.id} href={`/applications/${app.id}`}>
                <Card className="h-full transition-shadow hover:shadow-md">
                  <CardContent className="p-5">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate font-semibold">{app.name}</div>
                        <div className="text-xs text-muted-foreground">{app.slug}</div>
                      </div>
                      <StatusBadge status={app.status} />
                    </div>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      <span className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                        {app.source_type}
                      </span>
                      {app.project_type && (
                        <span className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                          {app.project_type}
                        </span>
                      )}
                      {app.domains.slice(0, 1).map((d) => (
                        <span key={d} className="rounded-md bg-info/10 px-2 py-0.5 text-xs text-info">{d}</span>
                      ))}
                    </div>
                    <div className="mt-3 text-xs text-muted-foreground">
                      Port {app.container_port} · last deploy {relTime(app.last_deployed_at)}
                    </div>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </div>

      <CreateApplicationDialog open={createOpen} onClose={() => setCreateOpen(false)} />
    </>
  );
}
