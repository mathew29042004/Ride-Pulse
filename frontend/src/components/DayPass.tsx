/** Zero-commission day pass for drivers: pay a flat fee, keep 100% of every fare today. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgePercent } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { inr } from "@/lib/format";
import { t } from "@/lib/i18n";

interface DayPass {
  price: string | number;
  active_today: boolean;
  kept_today: string | number;
}

export function useDayPass() {
  return useQuery({ queryKey: ["driver", "day-pass"], queryFn: () => api.get<DayPass>("driver/day-pass/"), refetchInterval: 60_000 });
}

export function DayPassCard() {
  const qc = useQueryClient();
  const pass = useDayPass().data;
  const buy = useMutation({
    mutationFn: (method: "WALLET" | "UPI") => api.post<DayPass>("driver/day-pass/", { method, payer_reference: "driver@upi" }),
    onSuccess: (data) => {
      qc.setQueryData(["driver", "day-pass"], data);
      toast.success(t("Day pass active: 0% commission today"));
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t("Couldn't buy the day pass.")),
  });
  if (!pass) return null;
  return (
    <div className="mt-4 rounded-2xl border border-line p-4">
      <div className="flex items-center gap-2 font-semibold">
        <BadgePercent className="size-4 text-brand" /> {t("Zero-commission day pass")}
      </div>
      {pass.active_today ? (
        <p className="mt-1 text-sm">
          {t("Active today. You keep 100% of every fare.")} <b>{t("Kept so far: {amount}", { amount: inr(pass.kept_today) })}</b>
        </p>
      ) : (
        <>
          <p className="mt-1 text-sm text-muted">{t("Pay {price} once and keep the whole fare on every trip until midnight. Riders pay the same.", { price: inr(pass.price) })}</p>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Button size="sm" loading={buy.isPending && buy.variables === "WALLET"} onClick={() => buy.mutate("WALLET")}>
              {t("Pay from earnings")}
            </Button>
            <Button size="sm" variant="secondary" loading={buy.isPending && buy.variables === "UPI"} onClick={() => buy.mutate("UPI")}>
              {t("Pay by UPI")}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
