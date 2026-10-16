/** Fair Share Meter (where the fare goes, drivers' real hourly earnings) and Driver Wellbeing. */

import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Coffee, PieChart, Timer } from "lucide-react";
import { useState } from "react";

import { api } from "@/lib/api";
import { inr } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { Trip } from "@/lib/types";

interface TripSplit {
  paid: string;
  driver_percent: number;
  tip: string;
  parts: { key: "driver" | "platform" | "fees" | "discount" | "gst"; label: string; amount: string }[];
}

interface DriverSummary {
  days: number;
  trips: number;
  fares_collected: string;
  gross_earnings: string;
  commission_paid: string;
  commission_percent: number;
  running_km: string;
  running_costs: string;
  running_cost_per_km: string;
  net_earnings: string;
  online_hours: string;
  net_per_hour: string;
  gross_per_hour: string;
}

export interface Wellbeing {
  driving_minutes: number;
  limit_minutes: number;
  minutes_left: number;
  break_minutes: number;
  on_break_until: string | null;
  rest_bonus: string;
  rest_bonus_after_minutes: number;
  rest_bonus_paid_today: boolean;
  daily_minutes: number;
  daily_limit_minutes: number;
  days_driven_this_week: number;
  week_days_limit: number;
  rest_stops: { name: string; kind: string; km: number }[];
}

const COLOURS: Record<string, string> = {
  driver: "bg-brand",
  platform: "bg-slate-500",
  fees: "bg-slate-400",
  gst: "bg-amber-400",
};

/** "Where your ₹180 went": a stacked bar and the list, after a completed trip. */
export function FairShareCard({ trip }: { trip: Trip }) {
  const [open, setOpen] = useState(false);
  const split = useQuery({
    queryKey: ["trips", String(trip.id), "fair-share"],
    queryFn: () => api.get<TripSplit>(`trips/${trip.id}/fair-share/`),
    enabled: trip.status === "COMPLETED",
  });
  const data = split.data;
  if (!data) return null;
  const positive = data.parts.filter((p) => Number(p.amount) > 0);
  const total = positive.reduce((sum, p) => sum + Number(p.amount), 0) || 1;

  return (
    <div className="mt-3 rounded-2xl bg-surface-2 px-4 py-3 text-sm">
      <button onClick={() => setOpen((v) => !v)} className="flex w-full items-center gap-2 text-left font-semibold" aria-expanded={open}>
        <PieChart className="size-4" />
        <span className="flex-1">{t("Where your {amount} went", { amount: inr(data.paid) })}</span>
        <span className="text-xs font-semibold text-brand-strong">{t("{n}% to your driver", { n: data.driver_percent })}</span>
      </button>
      <div className="mt-2 flex h-2.5 overflow-hidden rounded-full">
        {positive.map((p) => (
          <div key={p.key} className={COLOURS[p.key] ?? "bg-slate-300"} style={{ width: `${(Number(p.amount) / total) * 100}%` }} />
        ))}
      </div>
      {open && (
        <div className="mt-2 space-y-1">
          {data.parts.map((p) => (
            <div key={p.key} className="flex items-center justify-between text-xs">
              <span className="flex items-center gap-2 text-muted">
                <span className={clsx("size-2 rounded-full", COLOURS[p.key] ?? "bg-transparent ring-1 ring-brand")} />
                {t(p.label)}
              </span>
              <span className={clsx("font-semibold", Number(p.amount) < 0 && "text-brand-strong")}>{inr(p.amount)}</span>
            </div>
          ))}
          <p className="pt-1 text-[11px] text-muted">{t("Boosts and tips go 100% to the driver.")}</p>
        </div>
      )}
    </div>
  );
}

/** Driver Earnings page: what they really made per hour after running costs. */
export function RealEarningsCard() {
  const summary = useQuery({ queryKey: ["driver", "fair-share"], queryFn: () => api.get<DriverSummary>("driver/fair-share/?days=7"), refetchInterval: 60_000 });
  const s = summary.data;
  if (!s) return null;
  const rows: [string, string, string?][] = [
    ["Fares collected", inr(s.fares_collected)],
    ["Ride Pulse commission", `−${inr(s.commission_paid)}`, `${s.commission_percent}%`],
    ["Your earnings (incl. boosts & tips)", inr(s.gross_earnings)],
    ["Running costs (est.)", `−${inr(s.running_costs)}`, `${s.running_km} km × ₹${Number(s.running_cost_per_km)}`],
    ["Take-home after costs", inr(s.net_earnings)],
  ];
  return (
    <div className="mt-4 rounded-2xl border border-line p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold">
          <PieChart className="size-4 text-brand" /> {t("Real earnings · last 7 days")}
        </div>
        <div className="text-sm text-muted">{t("{n} h online", { n: s.online_hours })}</div>
      </div>
      <div className="mt-3 flex items-end gap-2">
        <div className="text-3xl font-bold tracking-tight">{inr(s.net_per_hour)}</div>
        <div className="pb-1 text-sm text-muted">{t("per hour after costs")}</div>
      </div>
      <div className="text-xs text-muted">{t("{amount}/hour before costs", { amount: inr(s.gross_per_hour) })}</div>
      <div className="mt-3 space-y-1.5 border-t border-line pt-3 text-sm">
        {rows.map(([label, value, note]) => (
          <div key={label} className="flex justify-between gap-3">
            <span className="text-muted">
              {t(label)}
              {note && <span className="ml-1 text-xs">({note})</span>}
            </span>
            <span className="font-semibold">{value}</span>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-muted">{t("Running costs are an estimate (fuel and upkeep per km, including the drive to each pickup).")}</p>
    </div>
  );
}

export function useWellbeing() {
  return useQuery({ queryKey: ["driver", "wellbeing"], queryFn: () => api.get<Wellbeing>("driver/wellbeing/"), refetchInterval: 60_000 });
}

const hm = (minutes: number) => `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;

/** Under the online toggle: "4h 10m driving · break in 1h 50m". */
export function WellbeingChip() {
  const w = useWellbeing().data;
  if (!w || (!w.driving_minutes && !w.on_break_until)) return null;
  const close = w.minutes_left <= 30;
  return (
    <div className={clsx("mt-0.5 flex items-center gap-1 text-[11px] font-semibold", close ? "text-amber-600" : "text-muted")}>
      <Timer className="size-3" />
      {t("{time} driving", { time: hm(w.driving_minutes) })} · {w.minutes_left ? t("break in {time}", { time: hm(w.minutes_left) }) : t("break due")}
      <span className={clsx(w.daily_minutes >= w.daily_limit_minutes - 60 && "text-amber-600")}>· {t("{a} of {b} today", { a: hm(w.daily_minutes), b: `${w.daily_limit_minutes / 60}h` })}</span>
      {w.days_driven_this_week >= w.week_days_limit && <span className="text-amber-600">· {t("take a day off soon")}</span>}
    </div>
  );
}

/** While a forced break runs: a countdown instead of the go-online button. */
export function BreakCard() {
  const w = useWellbeing().data;
  const now = useNow(1000);
  if (!w?.on_break_until) return null;
  const left = Math.max(0, Math.ceil((new Date(w.on_break_until).getTime() - now) / 1000));
  if (!left) return null;
  const long = left > 3600;
  return (
    <div className="mb-3 flex items-center gap-3 rounded-2xl bg-sky-50 p-3 text-sm text-sky-950 dark:bg-sky-400/10 dark:text-sky-100">
      <Coffee className="size-6 shrink-0" />
      <div className="flex-1">
        <div className="font-semibold">{long ? t("Rest until tomorrow") : t("Rest break")}</div>
        <div className="text-xs">
          {long
            ? t("That's 12 hours on the road today. Get some sleep: back online at {time}.", { time: new Date(w.on_break_until).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) })
            : t("You've been driving a long time. Stretch, drink some water. Back online in {time}.", { time: `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` })}
        </div>
        {!w.rest_bonus_paid_today && !long && <div className="mt-0.5 text-xs font-semibold">{t("₹{n} rest bonus when you come back", { n: Number(w.rest_bonus) })}</div>}
        {w.rest_stops.length > 0 && (
          <div className="mt-1.5 text-xs">
            <span className="font-semibold">{t("Places to rest nearby")}: </span>
            {w.rest_stops.map((p) => `${p.name} (${p.kind.toLowerCase()}, ${p.km} km)`).join(" · ")}
          </div>
        )}
      </div>
    </div>
  );
}
