/** Switching to electric: subsidies in the driver's state for the vehicle they're looking at,
 * and what the vehicle loan looks like after them. Amounts are indicative. */

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Zap } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { Field, Input, Segmented } from "@/components/ui";
import { api } from "@/lib/api";
import { inr } from "@/lib/format";
import { t } from "@/lib/i18n";

interface Result {
  state: string;
  price: string;
  schemes: { key: string; name: string; amount: string; how: string; central: boolean }[];
  total: string;
  net_price: string;
  loan: { loan_amount: string; weeks: number; annual_rate: string; weekly_emi: string; eligible: boolean };
}

const DEFAULTS: Record<string, [number, number]> = { BIKE: [110000, 3], AUTO: [350000, 8], CAR: [1200000, 26] };

export default function DriverEv() {
  const [vehicle, setVehicle] = useState("AUTO");
  const [price, setPrice] = useState(DEFAULTS.AUTO[0]);
  const [kwh, setKwh] = useState(DEFAULTS.AUTO[1]);
  const q = useQuery({ queryKey: ["ev-subsidy", vehicle, price, kwh], queryFn: () => api.get<Result>(`driver/ev-subsidy/?vehicle=${vehicle}&price=${price}&battery_kwh=${kwh}`) });
  const r = q.data;
  return (
    <div className="mx-auto max-w-xl px-4 pb-24 pt-3">
      <div className="flex items-center gap-2">
        <Link to="/drive/loan" className="flex size-10 items-center justify-center rounded-full bg-surface-2" aria-label={t("Back")}><ArrowLeft className="size-5" /></Link>
        <h1 className="flex items-center gap-2 text-xl font-bold"><Zap className="size-5" /> {t("Switch to electric")}</h1>
      </div>
      <p className="mt-2 text-sm text-muted">{t("Subsidies in {state} for the vehicle you're looking at. Amounts are indicative: rules change, and we'll confirm them before you apply.", { state: r?.state ?? "" })}</p>
      <Segmented className="mt-3" value={vehicle} onChange={(v) => { setVehicle(v); setPrice(DEFAULTS[v][0]); setKwh(DEFAULTS[v][1]); }} options={[{ value: "BIKE", label: t("Bike") }, { value: "AUTO", label: t("Auto") }, { value: "CAR", label: t("Car") }]} />
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Field label={t("On-road price (₹)")}><Input type="number" value={price} onChange={(e) => setPrice(Number(e.target.value))} /></Field>
        <Field label={t("Battery (kWh)")}><Input type="number" step="0.1" value={kwh} onChange={(e) => setKwh(Number(e.target.value))} /></Field>
      </div>
      {r && (
        <div className="mt-4 space-y-2">
          {r.schemes.map((s) => (
            <div key={s.key} className="rounded-2xl border border-line p-3 text-sm">
              <div className="flex justify-between font-semibold"><span>{s.name}</span><span>{inr(s.amount, { whole: true })}</span></div>
              <div className="text-xs text-muted">{s.how}</div>
            </div>
          ))}
          <div className="rounded-2xl bg-surface-2 p-3 text-sm">
            <div className="flex justify-between"><span>{t("Subsidies")}</span><b>{inr(r.total, { whole: true })}</b></div>
            <div className="flex justify-between"><span>{t("Price after subsidies")}</span><b>{inr(r.net_price, { whole: true })}</b></div>
            <div className="mt-1 text-xs text-muted">
              {t("With a {yr}-year loan at {rate}%: about {emi} a week.", { yr: r.loan.weeks / 52, rate: r.loan.annual_rate, emi: inr(r.loan.weekly_emi, { whole: true }) })}
            </div>
          </div>
          <Link to="/drive/loan" className="block rounded-2xl bg-ink p-3 text-center text-sm font-semibold text-ink-fg">{t("Apply for a vehicle loan")}</Link>
        </div>
      )}
    </div>
  );
}
