"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { toast } from "sonner";

import { DashboardShell } from "@/components/layout";
import { Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { data, isLoading, isError } = useQuery<User>({
    queryKey: ["me"],
    queryFn: () => api("/api/auth/me"),
    retry: false,
  });

  useEffect(() => {
    if (isError) router.replace("/login");
  }, [isError, router]);

  useEffect(() => {
    if (data?.must_change_password) {
      toast.warning("You are using the bootstrap password. Change it in Settings → Profile.", {
        duration: 8000,
      });
    }
  }, [data?.must_change_password]);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center gap-3 text-muted-foreground">
        <Skeleton className="h-10 w-10 rounded-full" />
        <div className="space-y-2">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-3 w-24" />
        </div>
      </div>
    );
  }

  return <DashboardShell>{children}</DashboardShell>;
}
