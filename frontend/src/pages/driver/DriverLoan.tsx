/** Vehicle loans from our partner NBFC: apply, see the weekly EMI, repayments and arrears, and
 * pay off early with no fee. The EMI comes out of weekly earnings; you always keep a minimum. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Car } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { Button, Field, Input, Segmented, Select } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime, inr } from "@/lib/format";
import { t } from "@/lib/i18n";

interface Loan {
  id: number;
  vehicle: string;
  purpose_label: string;
  details: string;
  principal: string;
  annual_rate: string;
  tenure_weeks: number;
  weekly_emi: string;
  outstanding: string;
  arrears: string;
  paid: string;
  status: string;
  status_label: string;
  note: string;
  repayments: { amount: string; interest: string; principal: string; due: string; early: boolean; at: string }[];
}
interface Data {
  eligible: boolean;
  reasons: string[];
  max_amount: string;
  weekly_earnings: string;
  annual_rate: string;
  tenures: number[];
  partner: string;
  keep_at_least: string;
  purposes: { value: string; label: string }[];
  loans: Loan[];
}

/** Same formula as the server (reducing balance, weekly). */
function emi(p: number, weeks: number, rate: number) {
  const r = rate / 100 / 52;
  const f = (1 + r) ** weeks;
  return (p * r * f) / (f - 1);
}

export default function DriverLoan() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["driver", "loan"], queryFn: () => api.get<Data>("driver/loan/") });
  const [vehicle, setVehicle] = useState("");
  const [purpose, setPurpose] = useState("");
  const [details, setDetails] = useState("");
  const [amount, setAmount] = useState(100000);
  const [weeks, setWeeks] = useState("104");
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : t("Something went wrong."));
  const refresh = () => qc.invalidateQueries({ queryKey: ["driver", "loan"] });
  const apply = useMutation({
    mutationFn: () => api.post("driver/loan/apply/", { vehicle, amount, weeks: Number(weeks), purpose, details }),
    onSuccess: () => {
      toast.success(t("Applied. We'll tell you when it's decided."));
      refresh();
    },
    onError: fail,
  });
  const payOff = useMutation({ mutationFn: () => api.post("driver/loan/pay-off/"), onSuccess: () => { toast.success(t("Loan paid off!")); refresh(); }, onError: fail });
  const d = q.data;
  const max = Number(d?.max_amount ?? 0);
  const current = d?.loans.find((l) => l.status === "ACTIVE" || l.status === "REQUESTED");
  return (
    <div className="mx-auto max-w-xl px-4 pb-24 pt-3">
      <div className="flex items-center gap-2">
        <Link to="/drive/account" className="flex size-10 items-center justify-center rounded-full bg-surface-2" aria-label={t("Back")}>
          <ArrowLeft className="size-5" />
        </Link>
        <h1 className="text-xl font-bold">{t("Vehicle loan")}</h1>
      </div>
      {d && (
        <p className="mt-2 text-sm text-muted">
          {t("From {partner} at {rate}% a year. The EMI comes out of your weekly earnings before payout; you always keep at least {keep}. No fee to pay off early.", { partner: d.partner, rate: d.annual_rate, keep: inr(d.keep_at_least, { whole: true }) })}
        </p>
      )}
      {current && (
        <div className="mt-4 rounded-3xl border border-line p-4 text-sm">
          <div className="flex items-center gap-2 font-semibold">
            <Car className="size-5" /> {current.vehicle} · {t(current.status_label)}
          </div>
          <div className="mt-1 text-xs text-muted">{t(current.purpose_label)}{current.details ? ` · ${current.details}` : ""}</div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-center">
            <div><div className="text-xs text-muted">{t("Weekly EMI")}</div><div className="font-bold">{inr(current.weekly_emi)}</div></div>
            <div><div className="text-xs text-muted">{t("Left to pay")}</div><div className="font-bold">{inr(current.outstanding, { whole: true })}</div></div>
            <div><div className="text-xs text-muted">{t("Paid")}</div><div className="font-bold">{inr(current.paid, { whole: true })}</div></div>
          </div>
          {Number(current.arrears) > 0 && (
            <p className="mt-2 rounded-xl bg-amber-500/15 p-2 text-xs">{t("{a} carried to next week because earnings were low. No penalty.", { a: inr(current.arrears) })}</p>
          )}
          {current.status === "ACTIVE" && (
            <Button className="mt-3" block variant="secondary" loading={payOff.isPending} onClick={() => payOff.mutate()}>
              {t("Pay off now ({amount})", { amount: inr(current.outstanding) })}
            </Button>
          )}
          {current.repayments.length > 0 && (
            <div className="mt-3 space-y-1 text-xs">
              {current.repayments.map((r, i) => (
                <div key={i} className="flex justify-between">
                  <span>{dateTime(r.at)}{r.early ? ` · ${t("early pay-off")}` : ""}</span>
                  <span>{inr(r.amount)} <span className="text-muted">({t("interest")} {inr(r.interest)})</span></span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {d?.loans
        .filter((l) => l.status === "REJECTED")
        .slice(0, 1)
        .map((l) => (
          <p key={l.id} className="mt-4 rounded-2xl bg-surface-2 p-3 text-sm">
            {t("Your application for {v} wasn't approved. Reason: {r}", { v: l.vehicle, r: l.note })}
          </p>
        ))}
      {d && !current && !d.eligible && (
        <div className="mt-4 rounded-3xl border border-line p-4 text-sm">
          <div className="font-semibold">{t("Not yet eligible")}</div>
          <ul className="mt-2 list-disc pl-5 text-muted">
            {d.reasons.map((r) => <li key={r}>{t(r)}</li>)}
          </ul>
        </div>
      )}
      {d && !current && d.eligible && (
        <div className="mt-4 space-y-3 rounded-3xl border border-line p-4">
          <Field label={t("What is the loan for?")}>
            <Select value={purpose} onChange={(e) => setPurpose(e.target.value)}>
              <option value="">{t("Choose…")}</option>
              {d.purposes.map((p) => (
                <option key={p.value} value={p.value}>{t(p.label)}</option>
              ))}
            </Select>
          </Field>
          <Field label={t("Tell us more (optional)")}>
            <Input value={details} onChange={(e) => setDetails(e.target.value)} maxLength={300} placeholder={t("e.g. my current car is 9 years old")} />
          </Field>
          <Field label={t("Which vehicle?")}>
            <Input value={vehicle} onChange={(e) => setVehicle(e.target.value)} placeholder="Tata Tiago EV 2026" />
          </Field>
          <Field label={t("Amount (up to {max})", { max: inr(max, { whole: true }) })}>
            <Input type="number" min={20000} max={max} step={1000} value={amount} onChange={(e) => setAmount(Number(e.target.value))} />
          </Field>
          <Segmented value={weeks} onChange={setWeeks} options={d.tenures.map((w) => ({ value: String(w), label: t("{n} yr", { n: w / 52 }) }))} />
          <p className="text-sm">
            {t("Weekly EMI about {emi}", { emi: inr(emi(amount, Number(weeks), Number(d.annual_rate)), { whole: true }) })}
          </p>
          <Button block disabled={!purpose || vehicle.length < 3 || amount < 20000 || amount > max} loading={apply.isPending} onClick={() => apply.mutate()}>
            {t("Apply")}
          </Button>
        </div>
      )}
    </div>
  );
}
