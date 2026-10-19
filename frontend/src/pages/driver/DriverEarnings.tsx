import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useState } from "react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { toast } from "sonner";

import { GoalsCard } from "@/components/DriverGoals";
import { DayPassCard } from "@/components/DayPass";
import { QuestsCard, StatementsCard } from "@/components/DriverBusiness";
import { RealEarningsCard } from "@/components/FairShare";
import { Button, KeyValue, Segmented, Skeleton, StatusBadge } from "@/components/ui";
import { api, newIdempotencyKey } from "@/lib/api";
import { date, inr, km } from "@/lib/format";
import { useDriverMe } from "@/lib/hooks";
import type { Earnings, Paginated, Payout } from "@/lib/types";
import { t } from "@/lib/i18n";

type Period = "today" | "week" | "month";

export default function DriverEarnings() {
  const [period, setPeriod] = useState<Period>("week");
  const qc = useQueryClient();
  const me = useDriverMe(false);
  const earnings = useQuery({ queryKey: ["driver", "earnings", period], queryFn: () => api.get<Earnings>(`driver/earnings/?period=${period}`) });
  const payouts = useQuery({ queryKey: ["payouts"], queryFn: () => api.get<Paginated<Payout>>("payouts/") });
  const payDues = useMutation({
    mutationFn: () => api.post<{ status: string; failure_reason: string }>("wallet/pay-dues/", { method: "UPI" }, { idempotencyKey: newIdempotencyKey() }),
    onSuccess: (p) => {
      if (p.status === "SUCCEEDED") toast.success(t("Dues cleared"));
      else toast.error(p.failure_reason);
      qc.invalidateQueries({ queryKey: ["driver"] });
    },
    onError: (err) => toast.error((err as Error).message),
  });
  const e = earnings.data;
  const balance = Number(me.data?.wallet_balance ?? 0);
  const chart = (e?.daily ?? []).map((d) => ({
    day: new Date(d.date).toLocaleDateString("en-IN", period === "month" ? { day: "numeric" } : { weekday: "short" }),
    earnings: Number(d.earnings),
    trips: d.trips,
  }));

  return (
    <div className="h-full overflow-y-auto px-5 pt-5 pb-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">{t("Earnings")}</h1>
        <Segmented
          value={period}
          onChange={setPeriod}
          options={[
            { value: "today", label: t("Today") },
            { value: "week", label: t("Week") },
            { value: "month", label: t("Month") },
          ]}
        />
      </div>
      <GoalsCard />
      <QuestsCard />
      <DayPassCard />
      <RealEarningsCard />

      <div className="mt-4 rounded-3xl bg-[#0b0f19] p-5 text-white">
        <div className="text-xs font-medium tracking-wide text-white/60 uppercase">{t("Total earnings")}</div>
        {e ? <div className="mt-1 text-4xl font-bold tracking-tight">{inr(e.earnings)}</div> : <Skeleton className="mt-2 h-10 w-36 bg-white/10" />}
        <div className="mt-1 text-sm text-white/60">
          {e?.trips ?? 0} trips · {km(e?.distance_km)}
        </div>
        {period !== "today" && chart.length > 0 && (
          <div className="mt-4 h-28">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chart}>
                <XAxis dataKey="day" tick={{ fill: "rgb(255 255 255 / 0.5)", fontSize: 10 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <Tooltip
                  cursor={{ fill: "rgb(255 255 255 / 0.06)" }}
                  contentStyle={{ background: "#111827", border: "none", borderRadius: 12, fontSize: 12 }}
                  formatter={(v) => [inr(Number(v)), "Earned"]}
                />
                <Bar dataKey="earnings" fill="#6366f1" radius={[6, 6, 2, 2]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      <div className="mt-4 divide-y divide-line rounded-2xl border border-line px-4">
        <KeyValue label={t("Trip earnings")}>{inr(e?.trip_earnings)}</KeyValue>
        <KeyValue label={t("Tips (100% yours)")}>{inr(e?.tips)}</KeyValue>
        <KeyValue label={t("Cancellation fees")}>{inr(e?.cancellation_fees)}</KeyValue>
        <KeyValue label={t("Fares collected")}>{inr(e?.fares)}</KeyValue>
        <KeyValue label={t("Platform commission")}>{inr(e?.commission)}</KeyValue>
        <KeyValue label={t("Cash collected")}>{inr(e?.cash_collected)}</KeyValue>
      </div>

      <div className="mt-4 flex items-center justify-between rounded-2xl bg-surface-2 p-4">
        <div>
          <div className="text-xs font-semibold text-muted uppercase">{t("Wallet balance")}</div>
          <div className={balance < 0 ? "text-xl font-bold text-danger" : "text-xl font-bold"}>{inr(balance)}</div>
          <div className="text-xs text-muted">{balance < 0 ? t("Commission due on cash trips") : t("Paid out every Monday")}</div>
        </div>
        {balance < 0 && (
          <Button size="sm" onClick={() => payDues.mutate()} loading={payDues.isPending}>
            {t("Pay dues")}
          </Button>
        )}
      </div>
      {balance < -500 && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-danger">
          <AlertTriangle className="size-3.5" /> {t("Dues over ₹500 stop you from going online.")}
        </p>
      )}

      <StatementsCard />

      <h2 className="mt-6 mb-2 text-sm font-semibold">{t("Payouts")}</h2>
      <div className="divide-y divide-line">
        {payouts.data?.results.length === 0 && <p className="py-6 text-center text-sm text-muted">{t("No payouts yet.")}</p>}
        {payouts.data?.results.map((p) => (
          <div key={p.id} className="flex items-center gap-3 py-3">
            <div className="flex-1">
              <div className="text-sm font-semibold">{inr(p.amount)}</div>
              <div className="text-xs text-muted">
                {date(p.period_start)} – {date(p.period_end)} · {p.payout_number}
              </div>
            </div>
            <StatusBadge status={p.status} />
          </div>
        ))}
      </div>
    </div>
  );
}
