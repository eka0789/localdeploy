"use client";

import {
  ArrowLeftRight,
  Boxes,
  Container,
  Database,
  FolderKanban,
  Gauge,
  Globe,
  HardDrive,
  LayoutDashboard,
  LogOut,
  Moon,
  Rocket,
  Save,
  Settings as SettingsIcon,
  Sun,
  Terminal,
  User as UserIcon,
  Users,
} from "lucide-react";
import { useTheme } from "next-themes";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui";

import type { User } from "@/lib/types";

const NAV = [
  { section: "Platform", items: [
    { href: "/", label: "Overview", icon: LayoutDashboard },
    { href: "/projects", label: "Projects", icon: FolderKanban },
    { href: "/applications", label: "Applications", icon: Rocket },
    { href: "/deployments", label: "Deployments", icon: Gauge },
  ]},
  { section: "Resources", items: [
    { href: "/domains", label: "Domains", icon: Globe },
    { href: "/databases", label: "Databases", icon: Database },
    { href: "/docker", label: "Docker", icon: Container },
    { href: "/storage", label: "Storage", icon: HardDrive },
  ]},
  { section: "Operations", items: [
    { href: "/monitoring", label: "Monitoring", icon: Gauge },
    { href: "/logs", label: "Logs", icon: Terminal },
    { href: "/backups", label: "Backups", icon: Save },
    { href: "/networking", label: "Networking", icon: ArrowLeftRight },
  ]},
  { section: "Admin", items: [
    { href: "/settings", label: "Settings", icon: SettingsIcon },
  ]},
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { theme, setTheme } = useTheme();

  const { data: user } = useQuery<User>({
    queryKey: ["me"],
    queryFn: () => api("/api/auth/me"),
    retry: false,
  });

  const logout = async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch { /* ignore */ }
    queryClient.clear();
    router.push("/login");
  };

  return (
    <aside className="flex h-screen w-60 shrink-0 flex-col border-r border-border bg-sidebar text-sidebar-foreground">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Boxes className="h-5 w-5" />
        </div>
        <div>
          <div className="text-sm font-bold tracking-tight text-foreground">LocalDeploy</div>
          <div className="text-[10px] uppercase tracking-widest text-muted-foreground">Self-hosted PaaS</div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 pb-4">
        {NAV.map((group) => (
          <div key={group.section} className="mb-4">
            <div className="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70">
              {group.section}
            </div>
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = pathname === item.href ||
                  (item.href !== "/" && pathname.startsWith(item.href));
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={cn(
                        "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors",
                        active
                          ? "bg-primary/15 font-medium text-foreground"
                          : "hover:bg-white/5 hover:text-foreground",
                      )}
                    >
                      <item.icon className={cn("h-4 w-4", active ? "text-primary" : "text-muted-foreground")} />
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-border p-3">
        <div className="flex items-center gap-2 rounded-lg px-2 py-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-muted">
            <UserIcon className="h-4 w-4 text-muted-foreground" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-foreground">{user?.username ?? "…"}</div>
            <div className="text-xs text-muted-foreground">{user?.role_name ?? ""}</div>
          </div>
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-white/5"
            aria-label="Toggle theme"
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          <button
            onClick={logout}
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-white/5"
            aria-label="Log out"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}

export function Topbar({ title, description, actions }: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  const { data: docker } = useQuery<{ available: boolean }>({
    queryKey: ["docker", "status"],
    queryFn: () => api("/api/docker/status"),
    refetchInterval: 15_000,
  });

  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-background/80 px-8 py-5 backdrop-blur">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>}
      </div>
      <div className="flex items-center gap-2">
        <Badge variant={docker?.available ? "success" : "destructive"}>
          Docker {docker?.available ? "connected" : "offline"}
        </Badge>
        {actions}
      </div>
    </header>
  );
}

export function DashboardShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}
