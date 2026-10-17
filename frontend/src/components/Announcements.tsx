/** Announcements on the rider and driver home: unread ones first, in the person's language. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Megaphone, X } from "lucide-react";

import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

interface Item {
  id: number;
  title: string;
  body: string;
  important: boolean;
  published_at: string;
  read: boolean;
}

export function AnnouncementCard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["announcements", "mine"], queryFn: () => api.get<Item[]>("announcements/mine/"), refetchInterval: 120_000 });
  const read = useMutation({
    mutationFn: (id: number) => api.post(`announcements/${id}/read/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["announcements", "mine"] }),
  });
  const next = (q.data ?? []).find((a) => !a.read);
  if (!next) return null;
  return (
    <div className={clsx("mb-3 flex gap-3 rounded-2xl p-3 text-sm", next.important ? "bg-amber-500/15 text-amber-950 dark:text-amber-100" : "bg-sky-500/10")}>
      <Megaphone className="mt-0.5 size-5 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="font-semibold">{next.title}</div>
        <div className="text-xs">{next.body}</div>
      </div>
      <button onClick={() => read.mutate(next.id)} className="self-start rounded-full p-1 hover:bg-black/5" aria-label={t("Dismiss")}>
        <X className="size-4" />
      </button>
    </div>
  );
}
