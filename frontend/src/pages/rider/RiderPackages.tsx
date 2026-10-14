/**
 * Hourly rentals (a car and driver for 1–8 hours) and intercity trips (one-way or round trip to
 * another city), on one screen with a tab for each.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { ArrowLeft, Clock, MapPinned, Minus, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { toast } from "sonner";

import { BaseMap, FitBounds, PinMarker, Recenter } from "@/components/map";
import { RideTypeArt } from "@/components/RideTypeArt";
import { Button, Segmented, Sheet } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { inr, km } from "@/lib/format";
import { haversineKm } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { Fare, PaymentMethod, Trip } from "@/lib/types";

import { useRiderLocation } from "./RiderHome";

type Kind = "RENTAL" | "INTERCITY";

interface Quote {
  city: string;
  distance_km: string | null;
  packages: { hours: number; km: number }[];
  options: { ride_type: { code: string; name: string; seats: number; description: string }; pickup_eta_min: number | null; fare: Fare }[];
}

/** Popular getaways from South Indian cities; only those 40–600 km from the pickup are shown. */
const DESTINATIONS = [
  { name: "Puducherry", lat: 11.9416, lng: 79.8083 },
  { name: "Mamallapuram", lat: 12.6208, lng: 80.1945 },
  { name: "Vellore", lat: 12.9165, lng: 79.1325 },
  { name: "Tirupati", lat: 13.6288, lng: 79.4192 },
  { name: "Chennai", lat: 13.0827, lng: 80.2707 },
  { name: "Bengaluru", lat: 12.9716, lng: 77.5946 },
  { name: "Mysuru", lat: 12.2958, lng: 76.6394 },
  { name: "Coimbatore", lat: 11.0168, lng: 76.9558 },
  { name: "Ooty", lat: 11.4064, lng: 76.6932 },
  { name: "Madurai", lat: 9.9252, lng: 78.1198 },
  { name: "Kochi", lat: 9.9312, lng: 76.2673 },
  { name: "Tiruchirappalli", lat: 10.7905, lng: 78.7047 },
];

const PAYMENT: PaymentMethod[] = ["UPI", "CASH", "CARD", "WALLET"];

export default function RiderPackages() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [spot] = useRiderLocation();
  const [kind, setKind] = useState<Kind>(params.get("service") === "INTERCITY" ? "INTERCITY" : "RENTAL");
  const [hours, setHours] = useState(2);
  const [roundTrip, setRoundTrip] = useState(false);
  const [days, setDays] = useState(1);
  const [selected, setSelected] = useState("MINI");
  const [payment, setPayment] = useState<PaymentMethod>("UPI");
  const destinations = useMemo(
    () => DESTINATIONS.map((d) => ({ ...d, km: haversineKm(spot, d) })).filter((d) => d.km >= 40 && d.km <= 600).sort((a, b) => a.km - b.km),
    [spot],
  );
  const [destination, setDestination] = useState<(typeof DESTINATIONS)[number] | null>(null);
  const dest = kind === "INTERCITY" ? (destination ?? destinations[0] ?? null) : null;

  const quote = useQuery({
    queryKey: ["package-quote", kind, spot.lat, spot.lng, hours, dest?.name, roundTrip, days],
    queryFn: () =>
      api.post<Quote>("fares/packages/", {
        service: kind,
        pickup: { lat: spot.lat, lng: spot.lng },
        dropoff: dest && { lat: dest.lat, lng: dest.lng },
        package_hours: hours,
        round_trip: roundTrip,
        days,
      }),
    enabled: kind === "RENTAL" || !!dest,
    retry: false,
  });
  const option = quote.data?.options.find((o) => o.ride_type.code === selected) ?? quote.data?.options[0];

  const book = useMutation({
    mutationFn: () =>
      api.post<Trip>("trips/", {
        service: kind,
        ride_type: option!.ride_type.code,
        pickup: { lat: spot.lat, lng: spot.lng, address: spot.name },
        dropoff: dest && { lat: dest.lat, lng: dest.lng, address: dest.name },
        payment_method: payment,
        package_hours: hours,
        round_trip: roundTrip,
        days,
      }),
    onSuccess: (trip) => {
      qc.invalidateQueries({ queryKey: ["trips"] });
      navigate(`/ride/trips/${trip.id}`, { replace: true });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't book."),
  });

  return (
    <div className="relative flex h-full flex-col">
      <div className="absolute inset-0">
        <BaseMap center={[spot.lat, spot.lng]} zoom={kind === "INTERCITY" ? 7 : 13}>
          {dest ? <FitBounds points={[[spot.lat, spot.lng], [dest.lat, dest.lng]]} padding={60} bottom={420} fitKey={dest.name} /> : <Recenter center={[spot.lat, spot.lng]} />}
          <PinMarker lat={spot.lat} lng={spot.lng} kind="pickup" />
          {dest && <PinMarker lat={dest.lat} lng={dest.lng} kind="dropoff" label={dest.name} />}
        </BaseMap>
      </div>
      <div className="rp-overlay relative z-[600] flex items-center gap-2 p-3">
        <Link to="/ride" className="flex size-10 items-center justify-center rounded-full bg-surface shadow-[var(--shadow-float)]" aria-label="Back">
          <ArrowLeft className="size-5" />
        </Link>
        <div className="rounded-full bg-surface px-4 py-2 text-sm font-semibold shadow-[var(--shadow-float)]">{t("From {place}", { place: spot.name })}</div>
      </div>
      <div className="flex-1" />

      <Sheet
        height="72%"
        footer={
          option && (
            <Button size="lg" block loading={book.isPending} onClick={() => book.mutate()}>
              {t("Book {ride} · {fare}", { ride: option.ride_type.name, fare: inr(option.fare.total) })}
            </Button>
          )
        }
      >
        <Segmented
          value={kind}
          onChange={(v) => setKind(v as Kind)}
          options={[
            { value: "RENTAL", label: t("Rentals") },
            { value: "INTERCITY", label: t("Intercity") },
          ]}
        />

        {kind === "RENTAL" ? (
          <>
            <p className="mt-3 text-xs text-muted">{t("A car and driver for as long as you need. Make stops, run errands; it ends wherever you finish.")}</p>
            <div className="mt-2 grid grid-cols-4 gap-1.5">
              {(quote.data?.packages ?? [{ hours: 1, km: 10 }, { hours: 2, km: 20 }, { hours: 4, km: 40 }, { hours: 8, km: 80 }]).map((p) => (
                <button
                  key={p.hours}
                  onClick={() => setHours(p.hours)}
                  className={clsx("rounded-xl border py-2 text-center", hours === p.hours ? "border-fg bg-surface-2" : "border-line text-muted")}
                >
                  <div className="text-sm font-bold">{p.hours} h</div>
                  <div className="text-[11px]">{p.km} km</div>
                </button>
              ))}
            </div>
          </>
        ) : (
          <>
            <p className="mt-3 text-xs text-muted">{t("Outstation trips with a driver. Tolls, parking and state permits are paid on the way.")}</p>
            <div className="mt-2 flex gap-1.5 overflow-x-auto pb-1">
              {destinations.map((d) => (
                <button
                  key={d.name}
                  onClick={() => setDestination(d)}
                  className={clsx("flex shrink-0 items-center gap-1 rounded-full border px-3 py-1.5 text-xs font-semibold", dest?.name === d.name ? "border-fg bg-ink text-ink-fg" : "border-line")}
                >
                  <MapPinned className="size-3.5" /> {d.name}
                </button>
              ))}
            </div>
            {destinations.length === 0 && <p className="mt-2 text-sm text-muted">{t("No intercity destinations from here yet.")}</p>}
            <div className="mt-2 flex items-center gap-2">
              <Segmented
                value={roundTrip ? "ROUND" : "ONE"}
                onChange={(v) => setRoundTrip(v === "ROUND")}
                options={[
                  { value: "ONE", label: t("One way") },
                  { value: "ROUND", label: t("Round trip") },
                ]}
              />
              {roundTrip && (
                <div className="ml-auto flex items-center gap-2 text-sm">
                  <button onClick={() => setDays((d) => Math.max(1, d - 1))} className="rounded-full bg-surface-3 p-1.5" aria-label="One day less">
                    <Minus className="size-3.5" />
                  </button>
                  <span className="font-semibold">{t("{n} days", { n: days })}</span>
                  <button onClick={() => setDays((d) => Math.min(7, d + 1))} className="rounded-full bg-surface-3 p-1.5" aria-label="One day more">
                    <Plus className="size-3.5" />
                  </button>
                </div>
              )}
            </div>
            {quote.data?.distance_km && <div className="mt-2 text-xs text-muted">{t("About {distance} by road, one way", { distance: km(quote.data.distance_km) })}</div>}
          </>
        )}

        {quote.isError && <p className="mt-3 text-sm text-danger">{(quote.error as Error).message}</p>}
        <div className="mt-3 space-y-1.5">
          {quote.data?.options.map((o) => (
            <button
              key={o.ride_type.code}
              onClick={() => setSelected(o.ride_type.code)}
              className={clsx("flex w-full items-center gap-3 rounded-2xl border-2 px-3 py-2.5 text-left", option?.ride_type.code === o.ride_type.code ? "border-fg bg-surface-2" : "border-transparent hover:bg-surface-2")}
            >
              <RideTypeArt code={o.ride_type.code} className="h-9 w-16 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="font-semibold">{o.ride_type.name}</div>
                <div className="flex items-center gap-1 text-xs text-muted">
                  <Clock className="size-3" />
                  {o.pickup_eta_min !== null ? t("{n} min away", { n: o.pickup_eta_min }) : t("No cars nearby")}
                </div>
              </div>
              <div className="text-right font-bold">{inr(o.fare.total)}</div>
            </button>
          ))}
        </div>
        {option && (
          <div className="mt-3 space-y-1 rounded-2xl bg-surface-2 p-3 text-xs">
            {option.fare.lines.map((line) => (
              <div key={line.code} className="flex justify-between">
                <span className="text-muted">{line.label}</span>
                <span className="font-medium">{inr(line.amount)}</span>
              </div>
            ))}
            {kind === "RENTAL" && <p className="pt-1 text-muted">{t("Extra km and minutes beyond the package are added at the end.")}</p>}
          </div>
        )}
        <div className="mt-3 grid grid-cols-4 gap-1.5">
          {PAYMENT.map((m) => (
            <button key={m} onClick={() => setPayment(m)} className={clsx("rounded-xl border py-2 text-xs font-semibold", payment === m ? "border-fg bg-surface-2" : "border-line text-muted")}>
              {t(m === "UPI" ? "UPI" : m === "CASH" ? "Cash" : m === "CARD" ? "Card" : "Wallet")}
            </button>
          ))}
        </div>
      </Sheet>
    </div>
  );
}
