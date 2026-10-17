/** A short banner in the rider and driver apps while an incident affects them. */

import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { AlertTriangle } from "lucide-react";

import { api } from "@/lib/api";

interface Banner {
  number: string;
  severity: "MINOR" | "MAJOR" | "CRITICAL";
  message: string;
  status: string;
}

export function StatusBanner() {
  const q = useQuery({ queryKey: ["status", "banner"], queryFn: () => api.get<{ banner: Banner | null }>("status/banner/"), refetchInterval: 60_000 });
  const b = q.data?.banner;
  if (!b) return null;
  return (
    <a href="/status" className={clsx("flex items-center gap-2 px-4 py-2 text-sm", b.severity === "CRITICAL" ? "bg-danger text-white" : "bg-amber-500/20 text-amber-900 dark:text-amber-200")}>
      <AlertTriangle className="size-4 shrink-0" />
      <span className="flex-1">{b.message}</span>
      <span className="text-xs opacity-80">{b.status}</span>
    </a>
  );
}
