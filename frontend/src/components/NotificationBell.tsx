import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Bell, CheckCheck, Settings2 } from "lucide-react";
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

export function NotificationBell({ className, align = "right", settings = false }: { className?: string; align?: "left" | "right"; settings?: boolean }) {
  const [open, setOpen] = useState(false);
  const [prefsOpen, setPrefsOpen] = useState(false);
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
            <span className="flex items-center gap-2">
              <button onClick={() => markAll.mutate()} className="flex items-center gap-1 text-xs font-medium text-muted hover:text-fg">
                <CheckCheck className="size-3.5" /> {t("Mark all read")}
              </button>
              {settings && (
                <button onClick={() => setPrefsOpen(!prefsOpen)} className="rounded-full p-1 text-muted hover:bg-surface-3 hover:text-fg" aria-label="Notification settings" aria-expanded={prefsOpen}>
                  <Settings2 className="size-3.5" />
                </button>
              )}
            </span>
          </div>
          {settings && prefsOpen && <Preferences />}
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

interface Prefs {
  quiet_from: number | null;
  quiet_until: number | null;
  digest: boolean;
}

/** Staff: quiet hours (no pop-ups except urgent ones) and a once-a-morning digest. */
function Preferences() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["notifications", "prefs"], queryFn: () => api.get<Prefs>("notifications/preferences/") });
  const save = useMutation({
    mutationFn: (p: Partial<Prefs>) => api.post<Prefs>("notifications/preferences/", { ...q.data, ...p }),
    onSuccess: (p) => qc.setQueryData(["notifications", "prefs"], p),
  });
  const p = q.data;
  if (!p) return null;
  const hours = Array.from({ length: 24 }, (_, h) => h);
  const label = (h: number) => `${h % 12 || 12} ${h < 12 ? "am" : "pm"}`;
  return (
    <div className="space-y-2 border-b border-line bg-surface-2 px-4 py-3 text-xs">
      <div className="font-semibold">Quiet hours (urgent alerts still come through)</div>
      <div className="flex items-center gap-2">
        <select className="input !w-auto !py-1 !text-xs" value={p.quiet_from ?? ""} onChange={(e) => save.mutate({ quiet_from: e.target.value === "" ? null : Number(e.target.value) })} aria-label="Quiet from">
          <option value="">Off</option>
          {hours.map((h) => <option key={h} value={h}>{label(h)}</option>)}
        </select>
        to
        <select className="input !w-auto !py-1 !text-xs" value={p.quiet_until ?? ""} onChange={(e) => save.mutate({ quiet_until: e.target.value === "" ? null : Number(e.target.value) })} aria-label="Quiet until">
          <option value="">Off</option>
          {hours.map((h) => <option key={h} value={h}>{label(h)}</option>)}
        </select>
      </div>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={p.digest} onChange={(e) => save.mutate({ digest: e.target.checked })} />
        Daily digest: hold routine updates and sum them up at 8 am
      </label>
    </div>
  );
}
