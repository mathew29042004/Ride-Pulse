/**
 * The driver's business: incentive quests, weekly statements (with TDS), the EV battery and
 * nearby chargers, vehicle care and the airport queue.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { BatteryCharging, Download, FileText, Plane, Plug, Target, Wrench } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { Button, Input } from "@/components/ui";
import { api, ApiError, openFile } from "@/lib/api";
import { inr } from "@/lib/format";
import { t } from "@/lib/i18n";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : t("Something went wrong."));

// --- Quests ----------------------------------------------------------------------------------

interface Quest {
  id: number;
  name: string;
  ends_at: string;
  tiers: [number, string][];
  trips: number;
  earned: string;
  next_tier: [number, string] | null;
  peak_hours_only: boolean;
  ride_types: string[];
  started: boolean;
  starts_at: string;
}

export function QuestsCard() {
  const q = useQuery({ queryKey: ["driver", "quests"], queryFn: () => api.get<Quest[]>("driver/biz/quests/"), refetchInterval: 60_000 });
  const list = q.data ?? [];
  if (!list.length) return null;
  return (
    <div className="mt-4 rounded-3xl border border-line p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <Target className="size-4 text-brand-strong" /> {t("Quests")}
      </div>
      <div className="space-y-3">
        {list.map((quest) => {
          const top = quest.tiers[quest.tiers.length - 1];
          const pct = Math.min(100, (100 * quest.trips) / top[0]);
          return (
            <div key={quest.id}>
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <span className="font-semibold">{quest.name}</span>
                <span className="shrink-0 text-xs text-muted">
                  {quest.started
                    ? t("ends {when}", { when: new Date(quest.ends_at).toLocaleString("en-IN", { weekday: "short", day: "numeric", hour: "numeric" }) })
                    : t("starts {when}", { when: new Date(quest.starts_at).toLocaleString("en-IN", { weekday: "short", day: "numeric", hour: "numeric" }) })}
                </span>
              </div>
              <div className="relative mt-1.5 h-2 rounded-full bg-surface-3">
                <div className="h-full rounded-full bg-brand" style={{ width: `${pct}%` }} />
                {quest.tiers.map(([trips]) => (
                  <span key={trips} className="absolute top-1/2 size-2.5 -translate-y-1/2 rounded-full border-2 border-surface bg-ink" style={{ left: `calc(${(100 * trips) / top[0]}% - 5px)` }} />
                ))}
              </div>
              <div className="mt-1 text-xs text-muted">
                {quest.trips} {t("trips")}
                {quest.next_tier
                  ? ` · ${t("{n} more for {amount}", { n: quest.next_tier[0] - quest.trips, amount: inr(quest.next_tier[1], { whole: true }) })}`
                  : ` · ${t("all rewards earned")}`}
                {Number(quest.earned) > 0 && ` · ${t("earned {amount}", { amount: inr(quest.earned, { whole: true }) })}`}
                {quest.peak_hours_only && ` · ${t("peak hours only")}`}
                {quest.ride_types.length > 0 && ` · ${quest.ride_types.join(", ")}`}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// --- Statements ------------------------------------------------------------------------------

interface Statement {
  number: string;
  week_start: string;
  week_end: string;
  trips: number;
  gross_fares: string;
  net_earnings: string;
  tds_amount: string;
  tds_rate: string;
  pan_on_file: boolean;
  fleet_share: string;
}

export function StatementsCard() {
  const q = useQuery({ queryKey: ["driver", "statements"], queryFn: () => api.get<{ pan_on_file: boolean; statements: Statement[] }>("driver/biz/statements/") });
  const rows = q.data?.statements ?? [];
  if (!q.data) return null;
  const fmt = (d: string) => new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  return (
    <div className="mt-4 rounded-3xl border border-line p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <FileText className="size-4" /> {t("Weekly statements")}
      </div>
      {!q.data.pan_on_file && (
        <Link to="/drive/documents" className="mb-3 block rounded-2xl bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-400/10 dark:text-amber-200">
          {t("No PAN on file: 5% of your fares is withheld as TDS. Upload your PAN card to pay 0.1% instead.")}
        </Link>
      )}
      {rows.length === 0 && <p className="text-sm text-muted">{t("Your first statement arrives the Monday after your first trip.")}</p>}
      {rows.slice(0, 6).map((s) => (
        <div key={s.number} className="flex items-center gap-3 border-t border-line py-2.5 text-sm first:border-0">
          <div className="min-w-0 flex-1">
            <div className="font-semibold">
              {fmt(s.week_start)} – {fmt(s.week_end)}
            </div>
            <div className="text-xs text-muted">
              {s.trips} {t("trips")} · {t("TDS {amount}", { amount: inr(s.tds_amount) })}
              {Number(s.fleet_share) > 0 && ` · ${t("fleet {amount}", { amount: inr(s.fleet_share, { whole: true }) })}`}
            </div>
          </div>
          <span className="font-semibold">{inr(s.net_earnings, { whole: true })}</span>
          <button onClick={() => openFile(`/api/v1/driver/biz/statements/${s.number}/pdf/`)} className="rounded-full bg-surface-3 p-2" aria-label={t("Download PDF")}>
            <Download className="size-4" />
          </button>
        </div>
      ))}
    </div>
  );
}

// --- EV battery ------------------------------------------------------------------------------

interface EvInfo {
  battery_percent: number | null;
  range_left_km: number | null;
  full_range_km: number;
  reserve_km: number;
  low: boolean;
  chargers: { id: number; name: string; distance_km: number; power_kw: number; price_per_kwh: string; lat: number; lng: number }[];
}

export function EvCard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["driver", "ev"], queryFn: () => api.get<EvInfo | null>("driver/biz/ev/"), refetchInterval: 60_000 });
  const [percent, setPercent] = useState<number | null>(null);
  const save = useMutation({
    mutationFn: (value: number) => api.post<EvInfo>("driver/biz/ev/", { percent: value }),
    onSuccess: (data) => {
      qc.setQueryData(["driver", "ev"], data);
      setPercent(null);
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const info = q.data;
  if (!info) return null;
  const shown = percent ?? info.battery_percent ?? 0;
  return (
    <div className={clsx("mb-3 rounded-2xl p-3", info.low ? "bg-amber-50 dark:bg-amber-400/10" : "bg-surface-2")}>
      <div className="flex items-center gap-2 text-sm">
        <BatteryCharging className={clsx("size-4", info.low ? "text-amber-600" : "text-brand-strong")} />
        <span className="font-semibold">{shown}%</span>
        <span className="flex-1 text-xs text-muted">{t("{km} km range · trips are matched to your range", { km: info.range_left_km ?? "—" })}</span>
      </div>
      <input
        type="range"
        min={0}
        max={100}
        value={shown}
        onChange={(e) => setPercent(Number(e.target.value))}
        onMouseUp={() => percent !== null && save.mutate(percent)}
        onTouchEnd={() => percent !== null && save.mutate(percent)}
        onKeyUp={() => percent !== null && save.mutate(percent)}
        className="mt-2 w-full accent-[var(--color-brand)]"
        aria-label={t("Battery level")}
      />
      {info.low &&
        info.chargers.map((c) => (
          <a key={c.id} href={`https://www.google.com/maps/dir/?api=1&destination=${c.lat},${c.lng}`} target="_blank" rel="noreferrer" className="mt-1.5 flex items-center gap-2 text-xs">
            <Plug className="size-3.5 text-muted" />
            <span className="flex-1 font-medium">{c.name}</span>
            <span className="text-muted">
              {c.distance_km} km · {c.power_kw} kW · ₹{c.price_per_kwh}/kWh
            </span>
          </a>
        ))}
    </div>
  );
}

// --- Airport queue ---------------------------------------------------------------------------

export function AirportQueueChip() {
  const q = useQuery({ queryKey: ["driver", "airport"], queryFn: () => api.get<{ airport: string; position: number; waiting: number; outside: boolean } | null>("driver/biz/airport/"), refetchInterval: 20_000 });
  const spot = q.data;
  if (!spot) return null;
  return (
    <div className="mb-3 flex items-center gap-2 rounded-2xl bg-sky-50 p-3 text-sm text-sky-900 dark:bg-sky-500/10 dark:text-sky-200">
      <Plane className="size-4" />
      <span className="flex-1">
        <b>{t("#{n} in line", { n: spot.position })}</b> {t("at {airport} ({waiting} waiting)", { airport: spot.airport, waiting: spot.waiting })}
      </span>
      {spot.outside && <span className="text-xs font-semibold">{t("Come back within 5 min to keep your spot")}</span>}
    </div>
  );
}

// --- Vehicle care ----------------------------------------------------------------------------

interface Health {
  registration: string;
  name: string;
  odometer_km: number;
  km_since_service: number;
  service_interval_km: number;
  service_due_in_km: number;
  service: "OK" | "DUE_SOON" | "OVERDUE";
  documents: { document: string; expires_on: string; days_left: number; status: "OK" | "EXPIRING" | "EXPIRED" }[];
  status: "OK" | "SOON" | "ACTION";
  history?: { odometer_km: number; serviced_on: string; workshop: string }[];
}

export function VehicleCare() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["driver", "vehicle-care"], queryFn: () => api.get<Health | null>("driver/biz/vehicle/") });
  const [odometer, setOdometer] = useState("");
  const [workshop, setWorkshop] = useState("");
  const log = useMutation({
    mutationFn: () => api.post<Health>("driver/biz/vehicle/", { odometer_km: odometer ? Number(odometer) : undefined, workshop }),
    onSuccess: (data) => {
      qc.setQueryData(["driver", "vehicle-care"], data);
      setOdometer("");
      setWorkshop("");
      toast.success(t("Service logged"));
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const h = q.data;
  if (!h) return null;
  const pct = Math.min(100, (100 * h.km_since_service) / h.service_interval_km);
  return (
    <div className="mt-4 rounded-3xl border border-line p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <Wrench className="size-4" /> {t("Vehicle care")} <span className="font-normal text-muted">· {h.registration}</span>
      </div>
      <div className="text-xs text-muted">
        {t("{km} km on the odometer", { km: h.odometer_km.toLocaleString("en-IN") })} ·{" "}
        <span className={clsx(h.service !== "OK" && "font-semibold text-danger")}>
          {h.service === "OVERDUE" ? t("service overdue") : t("next service in {km} km", { km: h.service_due_in_km.toLocaleString("en-IN") })}
        </span>
      </div>
      <div className="mt-1.5 h-1.5 rounded-full bg-surface-3">
        <div className={clsx("h-full rounded-full", h.service === "OK" ? "bg-brand" : "bg-danger")} style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-3 space-y-1">
        {h.documents.map((d) => (
          <div key={d.document} className="flex justify-between text-xs">
            <span>{t(d.document)}</span>
            <span className={clsx(d.status === "EXPIRED" ? "font-semibold text-danger" : d.status === "EXPIRING" ? "font-semibold text-amber-600" : "text-muted")}>
              {d.status === "EXPIRED" ? t("expired {date}", { date: d.expires_on }) : t("valid till {date}", { date: d.expires_on })}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-3 flex gap-2">
        <Input inputMode="numeric" value={odometer} onChange={(e) => setOdometer(e.target.value.replace(/\D/g, ""))} placeholder={t("Odometer (km)")} className="!py-2 text-sm" />
        <Input value={workshop} onChange={(e) => setWorkshop(e.target.value)} placeholder={t("Workshop")} className="!py-2 text-sm" />
        <Button size="sm" variant="secondary" loading={log.isPending} onClick={() => log.mutate()}>
          {t("Log service")}
        </Button>
      </div>
    </div>
  );
}
