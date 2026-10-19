import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Bell, CheckCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import type { Notification, Paginated } from "@/lib/types";
import { t } from "@/lib/i18n";

const DOT: Record<Notification["level"], string> = {
  INFO: "bg-sky-500",
  SUCCESS: "bg-emerald-500",
  WARNING: "bg-amber-500",
  DANGER: "bg-rose-500",
};

export function NotificationBell({ className, align = "right" }: { className?: string; align?: "left" | "right" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const unread = useQuery({
    queryKey: ["notifications", "unread"],
    queryFn: () => api.get<{ unread: number }>("notifications/unread-count/"),
    refetchInterval: 15_000,
  });
  const list = useQuery({
    queryKey: ["notifications", "list"],
    queryFn: () => api.get<Paginated<Notification>>("notifications/?page_size=12"),
    enabled: open,
  });
  const markAll = useMutation({
    mutationFn: () => api.post("notifications/mark-all-read/"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  async function openNotification(n: Notification) {
    if (!n.is_read) {
      await api.patch(`notifications/${n.id}/`, { is_read: true });
      qc.invalidateQueries({ queryKey: ["notifications"] });
    }
    setOpen(false);
    if (n.link) navigate(n.link.replace(/\/$/, ""));
  }

  const count = unread.data?.unread ?? 0;
  return (
    <div ref={ref} className={clsx("relative", className)}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative flex size-10 items-center justify-center rounded-full text-fg transition hover:bg-surface-3"
        aria-label={`Notifications${count ? ` (${count} unread)` : ""}`}
      >
        <Bell className="size-5" />
        {count > 0 && (
          <span className="absolute top-1.5 right-1.5 flex min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-bold text-white">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>
      {open && (
        <div
          className={clsx(
            "absolute top-12 z-[1200] w-80 overflow-hidden rounded-2xl border border-line bg-surface shadow-[var(--shadow-float)]",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <span className="text-sm font-semibold">{t("Notifications")}</span>
            <button onClick={() => markAll.mutate()} className="flex items-center gap-1 text-xs font-medium text-muted hover:text-fg">
              <CheckCheck className="size-3.5" /> {t("Mark all read")}
            </button>
          </div>
          <div className="max-h-96 overflow-y-auto">
            {(list.data?.results ?? []).length === 0 && <p className="px-4 py-8 text-center text-sm text-muted">{t("You're all caught up.")}</p>}
            {list.data?.results.map((n) => (
              <button key={n.id} onClick={() => openNotification(n)} className={clsx("flex w-full gap-3 border-b border-line px-4 py-3 text-left transition last:border-0 hover:bg-surface-2", !n.is_read && "bg-brand-soft/40")}>
                <span className={clsx("mt-1.5 size-2 shrink-0 rounded-full", DOT[n.level])} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">{n.title}</span>
                  {n.body && <span className="mt-0.5 line-clamp-2 block text-xs text-muted">{n.body}</span>}
                  <span className="mt-1 block text-[11px] text-muted">{ago(n.created_at)}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
