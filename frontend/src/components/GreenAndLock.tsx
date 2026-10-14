/** Eco score (CO2 saved, eco points) and Fare Lock (fix a commute's price for a week). */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Leaf, Lock } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button, Modal } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { inr, time } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { Trip } from "@/lib/types";

interface EcoSummary {
  points: number;
  co2_saved_kg_total: number;
  co2_saved_kg_month: number;
  trees_equivalent: number;
  redeem_points: number;
  redeem_rupees: string;
  can_redeem: boolean;
}

interface FareLockRow {
  id: number;
  reference: string;
  ride_type: string;
  pickup_address: string;
  dropoff_address: string;
  time: string;
  weekdays: number[];
  locked_total: string;
  ends_at: string;
  active: boolean;
  uses: number;
  saved: string;
}

const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** After a ride: "You saved 1.2 kg of CO₂ vs driving yourself". */
export function TripEcoLine({ trip }: { trip: Trip }) {
  if (trip.status !== "COMPLETED" || !trip.co2_saved_g) return null;
  return (
    <p className="mt-3 flex items-center gap-2 rounded-2xl bg-emerald-50 px-3 py-2 text-xs text-emerald-900 dark:bg-emerald-400/10 dark:text-emerald-200">
      <Leaf className="size-4 shrink-0" />
      {t("You saved {kg} kg of CO₂ vs driving your own car · +{n} eco points", { kg: (trip.co2_saved_g / 1000).toFixed(1), n: Math.floor(trip.co2_saved_g / 100) })}
    </p>
  );
}

/** Account: CO2 saved, points, and "redeem for wallet money". */
export function EcoCard() {
  const qc = useQueryClient();
  const eco = useQuery({ queryKey: ["rider", "eco"], queryFn: () => api.get<EcoSummary>("rider/eco/") });
  const redeem = useMutation({
    mutationFn: () => api.post<EcoSummary>("rider/eco/"),
    onSuccess: (data) => {
      qc.setQueryData(["rider", "eco"], data);
      qc.invalidateQueries({ queryKey: ["wallet"] });
      toast.success(t("Eco points added to your wallet 🌱"));
    },
    onError: (err) => toast.error(errorText(err, "Couldn't redeem.")),
  });
  const e = eco.data;
  if (!e) return null;
  return (
    <div className="mt-4 rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 p-4 text-white">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <Leaf className="size-4" /> {t("Your eco score")}
      </div>
      <div className="mt-2 flex items-end gap-4">
        <div>
          <div className="text-3xl font-bold">{e.co2_saved_kg_total} kg</div>
          <div className="text-xs opacity-80">{t("CO₂ saved · {kg} kg this month", { kg: e.co2_saved_kg_month })}</div>
        </div>
        <div className="ml-auto text-right">
          <div className="text-2xl font-bold">{e.points}</div>
          <div className="text-xs opacity-80">{t("eco points")}</div>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2 text-xs">
        <span className="flex-1 opacity-90">{t("{p} points = {amount} in your wallet. Bikes, autos and EVs earn the most.", { p: e.redeem_points, amount: inr(e.redeem_rupees) })}</span>
        <Button size="sm" variant="secondary" disabled={!e.can_redeem} loading={redeem.isPending} onClick={() => redeem.mutate()}>
          {t("Redeem")}
        </Button>
      </div>
    </div>
  );
}

/** On a completed ride: lock this price for the weekday commute. */
export function LockFareButton({ trip }: { trip: Trip }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [days, setDays] = useState([0, 1, 2, 3, 4]);
  const lock = useMutation({
    mutationFn: () => api.post<FareLockRow>(`trips/${trip.id}/lock-fare/`, { method: "UPI", weekdays: days }),
    onSuccess: (row) => {
      setOpen(false);
      qc.invalidateQueries({ queryKey: ["rider", "fare-locks"] });
      toast.success(t("Fare locked at {amount} for a week", { amount: inr(row.locked_total) }));
    },
    onError: (err) => toast.error(errorText(err, "Couldn't lock the fare.")),
  });
  if (trip.status !== "COMPLETED" || trip.service !== "RIDE") return null;
  return (
    <>
      <button onClick={() => setOpen(true)} className="mt-3 flex w-full items-center gap-2 rounded-2xl bg-surface-2 px-4 py-3 text-left text-sm font-semibold">
        <Lock className="size-4" />
        <span className="flex-1">{t("Lock this fare for your commute")}</span>
        <span className="text-xs font-normal text-muted">₹49 / {t("week")}</span>
      </button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={t("Lock this fare")}
        footer={
          <Button block loading={lock.isPending} disabled={!days.length} onClick={() => lock.mutate()}>
            {t("Pay ₹49 by UPI and lock")}
          </Button>
        }
      >
        <p className="text-sm text-muted">
          {t("For 7 days, {from} → {to} in a {ride} costs no more than today's normal fare when you book within an hour of {time}. Surge never applies.", {
            from: trip.pickup_address,
            to: trip.dropoff_address,
            ride: trip.ride_type_name,
            time: time(trip.requested_at),
          })}
        </p>
        <div className="mt-3 flex gap-1.5">
          {DAYS.map((d, i) => (
            <button
              key={d}
              onClick={() => setDays((cur) => (cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i].sort()))}
              className={`flex-1 rounded-lg border py-1.5 text-xs font-semibold ${days.includes(i) ? "border-fg bg-ink text-ink-fg" : "border-line text-muted"}`}
            >
              {t(d)}
            </button>
          ))}
        </div>
      </Modal>
    </>
  );
}

/** Account: the rider's Fare Locks. */
export function FareLocks() {
  const locks = useQuery({ queryKey: ["rider", "fare-locks"], queryFn: () => api.get<FareLockRow[]>("rider/fare-locks/") });
  const active = (locks.data ?? []).filter((l) => l.active);
  if (!active.length) return null;
  return (
    <div className="mt-4 rounded-2xl border border-line p-4">
      <div className="flex items-center gap-2 font-semibold">
        <Lock className="size-4 text-brand" /> {t("Fare Locks")}
      </div>
      {active.map((l) => (
        <div key={l.id} className="mt-2 text-sm">
          <div className="font-medium">
            {l.pickup_address} → {l.dropoff_address}
          </div>
          <div className="text-xs text-muted">
            {l.ride_type} · {inr(l.locked_total)} · {l.time} · {l.weekdays.map((d) => t(DAYS[d])).join(", ")} · {t("{n} rides, saved {amount}", { n: l.uses, amount: inr(l.saved) })}
          </div>
        </div>
      ))}
    </div>
  );
}
