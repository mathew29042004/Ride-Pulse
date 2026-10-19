/** Ride Pass: buy or see the monthly pass (10% off every ride, no booking fee). */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Crown } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { date } from "@/lib/format";
import { t } from "@/lib/i18n";

type PassInfo = {
  plan: { price: string; days: string; percent: string; max_discount: string };
  active: boolean;
  ends_at: string | null;
  savings: string;
};

export function RidePassCard() {
  const qc = useQueryClient();
  const info = useQuery({ queryKey: ["ride-pass"], queryFn: () => api.get<PassInfo>("rider/ride-pass/") });
  const [method, setMethod] = useState<"UPI" | "WALLET">("UPI");
  const buy = useMutation({
    mutationFn: () => api.post<PassInfo>("rider/ride-pass/", { method, payer_reference: "rider@upi" }),
    onSuccess: (data) => {
      qc.setQueryData(["ride-pass"], data);
      qc.invalidateQueries({ queryKey: ["wallet"] });
      toast.success(t("Ride Pass active until {date}", { date: date(data.ends_at) }));
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t("Couldn't buy the pass.")),
  });
  const pass = info.data;
  if (!pass) return null;
  const { price, days, percent, max_discount } = pass.plan;
  return (
    <div className="mt-3 overflow-hidden rounded-2xl bg-gradient-to-br from-amber-300 via-amber-200 to-yellow-100 p-4 text-amber-950">
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-amber-950 text-amber-200">
          <Crown className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="font-bold">{t("Ride Pass")}</div>
          <div className="text-xs">
            {t("{percent}% off every ride (up to ₹{max}) and no booking fee", { percent: Number(percent), max: Number(max_discount) })}
          </div>
        </div>
      </div>
      {pass.active ? (
        <div className="mt-3 flex items-center justify-between rounded-xl bg-white/60 px-3 py-2 text-sm">
          <span>
            {t("Active until")} <b>{date(pass.ends_at)}</b>
          </span>
          <span className="text-xs">{t("Saved ₹{n}", { n: Number(pass.savings).toFixed(0) })}</span>
        </div>
      ) : (
        <div className="mt-3 flex items-center gap-2">
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value as "UPI" | "WALLET")}
            className="rounded-xl border border-amber-950/20 bg-white/70 px-2 py-2 text-sm"
            aria-label={t("Pay with")}
          >
            <option value="UPI">UPI</option>
            <option value="WALLET">{t("Wallet")}</option>
          </select>
          <Button className="flex-1" onClick={() => buy.mutate()} loading={buy.isPending}>
            {t("Get it for ₹{price} / {days} days", { price: Number(price), days })}
          </Button>
        </div>
      )}
      {pass.active && (
        <button onClick={() => buy.mutate()} disabled={buy.isPending} className="mt-2 text-xs font-semibold underline">
          Extend another {days} days for ₹{Number(price)}
        </button>
      )}
    </div>
  );
}
