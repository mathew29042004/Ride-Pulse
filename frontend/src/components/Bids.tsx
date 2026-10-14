/** Bid your fare (counter-offers while searching) and the Sure Ride promise on the trip screen. */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, HandCoins, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { Avatar, Button, Stars } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { inr, time } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { Trip } from "@/lib/types";

/** "Karthik ★4.8 can come for ₹173 · 4 min [Accept]" for each counter-offer. */
export function CounterOffers({ trip }: { trip: Trip }) {
  const qc = useQueryClient();
  const take = useMutation({
    mutationFn: (offerId: number) => api.post<Trip>(`trips/${trip.id}/take-counter/`, { offer_id: offerId }),
    onSuccess: (updated) => {
      qc.setQueryData(["trips", String(trip.id)], updated);
      qc.invalidateQueries({ queryKey: ["trips"] });
      toast.success(t("Driver booked at their price"));
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't accept the counter-offer."),
  });
  if (trip.fare_offer === null) return null;

  return (
    <div className="mt-4 text-left">
      <div className="flex items-center gap-2 text-sm">
        <HandCoins className="size-4" />
        <span className="flex-1">{t("Your offer: {fare}", { fare: inr(trip.fare_offer) })}</span>
      </div>
      {trip.counter_offers.length === 0 ? (
        <p className="mt-1 text-xs text-muted">{t("Drivers can accept your price or send a counter-offer. They'll show up here.")}</p>
      ) : (
        <div className="mt-2 space-y-2">
          {trip.counter_offers.map((c) => (
            <div key={c.id} className="flex items-center gap-3 rounded-2xl border border-line p-3">
              <Avatar name={c.driver_name} size={36} />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold">{c.driver_name}</div>
                <div className="flex items-center gap-1 text-xs text-muted">
                  <Stars value={c.driver_rating} size={10} /> · {t("{n} min away", { n: Math.max(1, Math.round(c.eta_minutes)) })}
                </div>
              </div>
              <Button size="sm" variant="brand" loading={take.isPending && take.variables === c.id} onClick={() => take.mutate(c.id)}>
                {inr(c.counter_amount)}
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** "Sure Ride: driver by 6:42 pm or ₹30 back", and the refund once paid. */
export function SureRideBadge({ trip }: { trip: Trip }) {
  if (!trip.sure_ride_deadline) return null;
  if (trip.sure_ride_refunded_at) {
    return (
      <p className="mt-3 flex items-center gap-2 rounded-2xl bg-brand/10 px-3 py-2 text-xs font-semibold text-brand-strong">
        <BadgeCheck className="size-4" /> {t("Sure Ride: the driver was late, so ₹30 is back in your wallet.")}
      </p>
    );
  }
  if (trip.status !== "REQUESTED" && trip.status !== "DRIVER_ASSIGNED") return null;
  return (
    <p className="mt-3 flex items-center gap-2 rounded-2xl bg-surface-2 px-3 py-2 text-xs">
      <ShieldCheck className="size-4 text-brand" />
      {t("Sure Ride: driver at your pickup by {time}, or ₹30 back.", { time: time(trip.sure_ride_deadline) })}
    </p>
  );
}
