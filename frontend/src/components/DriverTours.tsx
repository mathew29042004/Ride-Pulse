/** The driver's tours: upcoming ones assigned ahead (start or decline), and during a tour the
 * itinerary with "Reached" / "Leaving" for each stop, which the traveller sees live. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { CalendarDays, Check, Landmark } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime, inr } from "@/lib/format";
import { t } from "@/lib/i18n";

interface Assigned {
  id: number;
  reference: string;
  package: { name: string; stops: { order: number; name: string; minutes: number; note: string }[] };
  depart_at: string;
  pickup_address: string;
  group_size: number;
  ride_type: string;
  status: "ASSIGNED" | "STARTED";
  earning: string | null;
  trip: number | null;
  rider: { name: string } | null;
  progress: Record<string, { arrived?: string; left?: string }>;
}

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : t("Something went wrong."));

export function DriverTours({ pos, tripId }: { pos: { lat: number; lng: number }; tripId?: number }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["driver", "tours"], queryFn: () => api.get<Assigned[]>("tours/assigned/"), refetchInterval: 30_000 });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["driver", "tours"] });
    qc.invalidateQueries({ queryKey: ["driver", "me"] });
    qc.invalidateQueries({ queryKey: ["trips", "active"] });
  };
  const start = useMutation({
    mutationFn: (id: number) => api.post(`tours/bookings/${id}/start/`, { lat: pos.lat, lng: pos.lng }),
    onSuccess: () => {
      refresh();
      toast.success(t("Tour started. Head to the pickup."));
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const decline = useMutation({
    mutationFn: (id: number) => api.post(`tours/bookings/${id}/decline/`),
    onSuccess: () => {
      refresh();
      toast(t("Declined. We'll find another driver."));
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const stop = useMutation({
    mutationFn: ({ id, order, event }: { id: number; order: number; event: "arrived" | "left" }) => api.post(`tours/bookings/${id}/stop/`, { order, event }),
    onSuccess: refresh,
    onError: (err) => toast.error(errorText(err)),
  });
  const rows = q.data ?? [];
  const live = rows.find((b) => b.status === "STARTED" && b.trip === tripId);
  if (live) {
    const next = live.package.stops.find((s) => !live.progress[String(s.order)]?.left);
    return (
      <div className="mb-3 rounded-2xl border border-brand/40 bg-brand/5 p-3">
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
          <Landmark className="size-4 text-brand" /> {live.package.name}
        </div>
        <ol className="space-y-1.5">
          {live.package.stops.map((s) => {
            const p = live.progress[String(s.order)] ?? {};
            const current = next?.order === s.order;
            return (
              <li key={s.order} className="flex items-center gap-2 text-xs">
                <span className={clsx("flex size-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold", p.left ? "bg-brand text-white" : current ? "bg-ink text-ink-fg" : "bg-surface-3")}>{p.left ? <Check className="size-3" /> : s.order}</span>
                <span className={clsx("flex-1", current && "font-semibold")}>
                  {s.name} <span className="text-muted">· {t("{m} min", { m: s.minutes })}</span>
                </span>
                {current && !p.arrived && (
                  <Button size="sm" onClick={() => stop.mutate({ id: live.id, order: s.order, event: "arrived" })}>
                    {t("Reached")}
                  </Button>
                )}
                {current && p.arrived && (
                  <Button size="sm" variant="outline" onClick={() => stop.mutate({ id: live.id, order: s.order, event: "left" })}>
                    {t("Leaving")}
                  </Button>
                )}
              </li>
            );
          })}
        </ol>
        {!next && <p className="mt-2 text-xs text-muted">{t("All places visited. Drive back to the pickup and end the trip.")}</p>}
      </div>
    );
  }
  if (tripId) return null;
  const upcoming = rows.filter((b) => b.status === "ASSIGNED");
  if (!upcoming.length) return null;
  return (
    <div className="mb-3 rounded-2xl border border-line p-3">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <Landmark className="size-4 text-brand" /> {t("Your tours")}
      </div>
      <div className="space-y-2">
        {upcoming.map((b) => {
          const soon = new Date(b.depart_at).getTime() - Date.now() < 2 * 3_600_000;
          return (
            <div key={b.id} className="rounded-xl bg-surface-2 p-2.5 text-xs">
              <div className="flex justify-between gap-2">
                <span className="font-semibold">{b.package.name}</span>
                {b.earning && <span className="font-semibold text-brand">{t("you earn {amount}", { amount: inr(b.earning, { whole: true }) })}</span>}
              </div>
              <div className="text-muted">
                <CalendarDays className="mr-1 inline size-3" />
                {dateTime(b.depart_at)} · {b.pickup_address || t("pickup in the app")} · {b.group_size} {t("people")} · {t("{n} stops", { n: b.package.stops.length })}
              </div>
              <div className="mt-2 flex gap-2">
                <Button size="sm" disabled={!soon} loading={start.isPending} onClick={() => start.mutate(b.id)} title={soon ? "" : t("You can start within 2 hours of departure")}>
                  {t("Start tour")}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => window.confirm(t("Decline this tour? It goes to another driver.")) && decline.mutate(b.id)}>
                  {t("Decline")}
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
