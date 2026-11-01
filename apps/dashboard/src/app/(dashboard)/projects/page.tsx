"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderKanban, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { Topbar } from "@/components/layout";
import {
  Button, Card, CardContent, ConfirmDialog, Dialog, EmptyState, Input, Label,
  Skeleton, TD, TBody, TH, THead, TR, Table, Textarea,
} from "@/components/ui";
import { api } from "@/lib/api";
import { relTime } from "@/lib/format";
import type { Project } from "@/lib/types";

export default function ProjectsPage() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [deleteId, setDeleteId] = useState<string | null>(null);

  const { data: projects, isLoading } = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: () => api("/api/projects"),
  });

  const create = useMutation({
    mutationFn: () => api("/api/projects", { method: "POST", body: { name, description: description || null } }),
    onSuccess: () => {
      toast.success("Project created");
      setCreateOpen(false);
      setName("");
      setDescription("");
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/projects/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Project deleted");
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: (e) => toast.error(e.message),
  });

  return (
    <>
      <Topbar
        title="Projects"
        description="Group related applications together"
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" /> New project
          </Button>
        }
      />
      <div className="p-8">
        {isLoading ? (
          <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-16" />)}</div>
        ) : !projects?.length ? (
          <EmptyState
            icon={FolderKanban}
            title="No projects yet"
            description="Projects organize your applications. Create one, then add applications to it."
            action={<Button onClick={() => setCreateOpen(true)}>Create project</Button>}
          />
        ) : (
          <Card>
            <CardContent className="px-0">
              <Table>
                <THead>
                  <TH>Name</TH>
                  <TH>Applications</TH>
                  <TH>Created</TH>
                  <TH className="w-16" />
                </THead>
                <TBody>
                  {projects.map((project) => (
                    <TR key={project.id}>
                      <TD>
                        <div className="font-medium">{project.name}</div>
                        {project.description && (
                          <div className="text-xs text-muted-foreground">{project.description}</div>
                        )}
                      </TD>
                      <TD>
                        <Link href={`/applications?project=${project.id}`} className="text-primary hover:underline">
                          {project.application_count} application(s)
                        </Link>
                      </TD>
                      <TD className="text-muted-foreground">{relTime(project.created_at)}</TD>
                      <TD>
                        <Button
                          variant="ghost" size="icon"
                          onClick={() => setDeleteId(project.id)}
                          aria-label={`Delete ${project.name}`}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
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
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="New project"
        description="A project groups related applications."
        footer={
          <>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button onClick={() => create.mutate()} loading={create.isPending} disabled={!name.trim()}>
              Create
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="project-name">Name</Label>
            <Input id="project-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="My SaaS" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="project-desc">Description (optional)</Label>
            <Textarea id="project-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
        </div>
      </Dialog>

      <ConfirmDialog
        open={!!deleteId}
        onClose={() => setDeleteId(null)}
        onConfirm={() => deleteId && remove.mutate(deleteId)}
        title="Delete project?"
        message="Only empty projects can be deleted. Move or delete its applications first."
      />
    </>
  );
}
