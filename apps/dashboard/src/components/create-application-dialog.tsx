"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Button, Dialog, Input, Label, Select, Switch } from "@/components/ui";
import { api } from "@/lib/api";
import type { Application, Project } from "@/lib/types";

const SOURCE_HELP: Record<string, string> = {
  git: "Clone a Git repository, detect the runtime and build automatically.",
  dockerfile: "Use the Dockerfile that lives inside your repository.",
  compose: "Deploy a full docker-compose.yml definition.",
  image: "Run a prebuilt Docker image from a registry.",
  upload: "Upload a .zip/.tar.gz source archive and build it.",
};

export function CreateApplicationDialog({ open, onClose, defaultProject }: {
  open: boolean;
  onClose: () => void;
  defaultProject?: string;
}) {
  const queryClient = useQueryClient();
  const { data: projects } = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: () => api("/api/projects"),
    enabled: open,
  });

  const [form, setForm] = useState({
    name: "", project_id: defaultProject ?? "", description: "",
    source_type: "git" as Application["source_type"],
    git_url: "", git_branch: "main", git_username: "", git_password: "",
    docker_image: "", container_port: 80, auto_deploy: true,
  });

  const set = (key: keyof typeof form, value: string | boolean | number) =>
    setForm((f) => ({ ...f, [key]: value }));

  const create = useMutation({
    mutationFn: () => api("/api/applications", {
      method: "POST",
      body: {
        name: form.name,
        project_id: form.project_id || null,
        description: form.description || null,
        source_type: form.source_type,
        git_url: form.git_url || null,
        git_branch: form.git_branch || null,
        git_username: form.git_username || null,
        git_password: form.git_password || null,
        docker_image: form.docker_image || null,
        container_port: Number(form.container_port) || 80,
        auto_deploy: form.auto_deploy,
      },
    }),
    onSuccess: () => {
      toast.success("Application created");
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      onClose();
    },
    onError: (e) => toast.error(e.message),
  });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      wide
      title="New application"
      description="Pick a source, LocalDeploy detects the runtime and builds it."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => create.mutate()} loading={create.isPending} disabled={!form.name.trim()}>
            Create application
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label>Name *</Label>
            <Input value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="my-web-app" />
          </div>
          <div className="space-y-1.5">
            <Label>Project</Label>
            <Select value={form.project_id} onChange={(e) => set("project_id", e.target.value)}>
              <option value="">No project</option>
              {projects?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </Select>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label>Deployment source</Label>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {(["git", "dockerfile", "compose", "image", "upload"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => set("source_type", t)}
                className={`rounded-lg border px-3 py-2 text-sm capitalize transition-colors ${
                  form.source_type === t
                    ? "border-primary bg-primary/10 font-medium text-primary"
                    : "border-border text-muted-foreground hover:bg-muted"
                }`}
              >
                {t === "git" ? "Git repo" : t === "dockerfile" ? "Dockerfile" : t === "compose" ? "Compose" : t === "image" ? "Image" : "Upload"}
              </button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">{SOURCE_HELP[form.source_type]}</p>
        </div>

        {form.source_type !== "image" && (
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-1.5 sm:col-span-2">
              <Label>Git repository URL *</Label>
              <Input value={form.git_url} onChange={(e) => set("git_url", e.target.value)}
                     placeholder="https://github.com/user/repo.git" />
            </div>
            <div className="space-y-1.5">
              <Label>Branch</Label>
              <Input value={form.git_branch} onChange={(e) => set("git_branch", e.target.value)} placeholder="main" />
            </div>
          </div>
        )}

        {(form.source_type === "git" || form.source_type === "dockerfile" || form.source_type === "compose") && (
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Git username (for private repos)</Label>
              <Input value={form.git_username} onChange={(e) => set("git_username", e.target.value)} placeholder="token or username" />
            </div>
            <div className="space-y-1.5">
              <Label>Git password / token (encrypted)</Label>
              <Input type="password" value={form.git_password} onChange={(e) => set("git_password", e.target.value)} />
            </div>
          </div>
        )}

        {form.source_type === "image" && (
          <div className="space-y-1.5">
            <Label>Docker image *</Label>
            <Input value={form.docker_image} onChange={(e) => set("docker_image", e.target.value)} placeholder="nginx:latest" />
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label>Container port</Label>
            <Input type="number" value={form.container_port} onChange={(e) => set("container_port", e.target.value)} />
          </div>
          <div className="flex items-end gap-2 pb-1">
            <Switch checked={form.auto_deploy} onChange={(v) => set("auto_deploy", v)} />
            <Label>Auto-deploy on Git webhook push</Label>
          </div>
        </div>
      </div>
    </Dialog>
  );
}
