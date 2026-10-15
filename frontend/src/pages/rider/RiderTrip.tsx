import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { ArrowLeft, ChevronRight, Download, Heart, LifeBuoy, LocateFixed, Mail, RotateCcw, Share2, ShieldAlert, X, Zap } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";

import { BaseMap, CarMarker, FitBounds, type LatLng, PinMarker, RouteLine, routePath, snapToPath } from "@/components/map";
import { RideTypeArt } from "@/components/RideTypeArt";
import { CounterOffers, SureRideBadge } from "@/components/Bids";
import { CallButton } from "@/components/CallButton";
import { CarCheck, StartCode } from "@/components/PickupVerification";
import { FairShareCard } from "@/components/FairShare";
import { LockFareButton, TripEcoLine } from "@/components/GreenAndLock";
import { ParcelCard } from "@/components/ParcelForm";
import { LostItemCard } from "@/components/LostItem";
import { HomeSafeButton, NightSafeBar, RideCheckPrompt } from "@/components/SafetyPlus";
import { SplitFareCard } from "@/components/SplitFare";
import { PoolBadge } from "@/components/PoolBadge";
import { TripRecorder } from "@/components/TripRecorder";
import { TripChat } from "@/components/TripChat";
import { Avatar, Badge, Button, Modal, Sheet, Spinner, StarInput, Stars, Textarea } from "@/components/ui";
import { api, ApiError, newIdempotencyKey, openFile } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dateTime, inr, km, minutes, time } from "@/lib/format";
import { usePhoneGps } from "@/lib/gps";
import { clockIn, etaFromKm, etaMinutes, haversineKm, isActive, useLiveTrip, useNow } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { Estimate, Trip } from "@/lib/types";

const TAGS = ["Great driving", "Clean car", "Polite", "On time", "Safe", "Good music"];

function Searching({ trip }: { trip: Trip }) {
  const now = useNow();
  const seconds = Math.floor((now - new Date(trip.requested_at).getTime()) / 1000);
  return (
    <div className="py-2 text-center">
      <div className="relative mx-auto mb-4 flex size-20 items-center justify-center">
        <span className="absolute inset-0 animate-ping rounded-full bg-brand/30" />
        <span className="absolute inset-3 animate-ping rounded-full bg-brand/30 [animation-delay:400ms]" />
        <RideTypeArt code={trip.ride_type} className="relative h-10 w-16" />
      </div>
      <h2 className="text-lg font-bold">{t("Finding your {ride}", { ride: trip.ride_type_name })}</h2>
      <p className="mt-1 text-sm text-muted">
        {t("Matching you with a nearby driver")} · {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}
      </p>
      <div className="mx-auto mt-4 h-1 w-40 overflow-hidden rounded-full bg-surface-3">
        <div className="h-full w-1/3 animate-[indeterminate_1.3s_ease-in-out_infinite] rounded-full bg-brand" />
      </div>
      <BoostChips trip={trip} show={seconds >= 10 || Number(trip.boost_amount) > 0} />
    </div>
  );
}

/** "Taking a while? Add ₹10/20/30 to get a driver faster" (100% goes to the driver). */
function BoostChips({ trip, show }: { trip: Trip; show: boolean }) {
  const qc = useQueryClient();
  const boost = useMutation({
    mutationFn: (amount: number) => api.post<Trip>(`trips/${trip.id}/boost/`, { amount }),
    onSuccess: (updated, amount) => {
      qc.setQueryData(["trips", String(trip.id)], updated);
      toast.success(`+₹${amount} boost added. Asking more drivers now.`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't add the boost."),
  });
  const boosted = Number(trip.boost_amount);
  if (!show) return null;
  return (
    <div className="mt-5 rounded-2xl bg-amber-50 p-3 text-left dark:bg-amber-400/10">
      <div className="flex items-center gap-2 text-sm font-semibold text-amber-900 dark:text-amber-200">
        <Zap className="size-4" />
        {boosted > 0 ? `₹${boosted} boost added · new fare ${inr(trip.estimated_fare)}` : t("Taking a while? Boost your request")}
      </div>
      <p className="mt-0.5 text-xs text-amber-800/80 dark:text-amber-200/70">100% goes to your driver. More drivers see your ride, and those who passed get asked again.</p>
      <div className="mt-2.5 grid grid-cols-3 gap-2">
        {[10, 20, 30].map((amount) => (
          <button
            key={amount}
            onClick={() => boost.mutate(amount)}
            disabled={boost.isPending || boosted + amount > 100}
            className="rounded-xl border border-amber-300 bg-surface py-2 text-sm font-bold text-amber-900 transition hover:bg-amber-100 disabled:opacity-40 dark:border-amber-400/30 dark:text-amber-100 dark:hover:bg-amber-400/20"
          >
            +₹{amount}
          </button>
        ))}
      </div>
    </div>
  );
}

function DriverCard({ trip }: { trip: Trip }) {
  if (!trip.driver) return null;
  const [model, plate] = (trip.vehicle ?? "").split(" · ");
  return (
    <div className="flex items-center gap-3">
      <div className="relative">
        <Avatar name={trip.driver.name} size={52} />
        <span className="absolute -bottom-1 left-1/2 -translate-x-1/2 rounded-full bg-surface px-1.5 text-[10px] font-bold shadow">
          <Stars value={trip.driver.rating} size={10} />
        </span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="font-semibold">{trip.driver.name}</div>
        <div className="truncate text-xs text-muted">{model}</div>
        {plate && <div className="mt-1 inline-block rounded-md border border-line bg-surface-2 px-2 py-0.5 font-mono text-xs font-bold tracking-wider">{plate}</div>}
      </div>
      <RideTypeArt code={trip.ride_type} className="h-10 w-18 shrink-0" />
    </div>
  );
}

export default function RiderTrip() {
  const { id } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: trip, isLoading, driverPos } = useLiveTrip(id);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [recenter, setRecenter] = useState(0);
  // Share the rider's location during pickup and the ride, for the safety checks (the server
  // ignores it if this device clearly isn't near the trip, e.g. a laptop running the demo).
  const sharing = !!trip && ["DRIVER_ASSIGNED", "DRIVER_ARRIVED", "IN_PROGRESS"].includes(trip.status);
  usePhoneGps(
    sharing,
    (fix) => {
      api.post(`trips/${id}/rider-location/`, { lat: fix.lat, lng: fix.lng }).catch(() => undefined);
    },
    { keepAwake: false },
  );
  const [sosOpen, setSosOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [stars, setStars] = useState(5);
  const [tags, setTags] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  const now = useNow(5000);

  const refresh = () => qc.invalidateQueries({ queryKey: ["trips"] });
  const onError = (err: unknown) => toast.error(err instanceof ApiError ? err.message : "Something went wrong.");
  const cancel = useMutation({ mutationFn: () => api.post<Trip>(`trips/${id}/cancel/`, { reason: "Changed my plans" }), onSuccess: () => { setConfirmCancel(false); refresh(); }, onError });
  const rate = useMutation({ mutationFn: () => api.post<Trip>(`trips/${id}/rate/`, { stars, tags, comment }), onSuccess: () => { toast.success("Thanks for rating your driver!"); refresh(); }, onError });
  const tip = useMutation({
    mutationFn: (amount: number) => api.post<Trip>(`trips/${id}/tip/`, { amount, method: "UPI" }, { idempotencyKey: newIdempotencyKey() }),
    onSuccess: (_, amount) => { toast.success(`₹${amount} tip sent. 100% goes to your driver.`); refresh(); },
    onError,
  });
  // A live "follow my ride" link for family: the phone's share sheet, else the clipboard.
  const share = useMutation({
    mutationFn: () => api.post<{ path: string }>(`trips/${id}/share/`),
    onSuccess: async ({ path }) => {
      const url = `${location.origin}${path}`;
      const text = "Follow my Ride Pulse trip live";
      try {
        if (navigator.share) {
          await navigator.share({ title: "Ride Pulse", text, url });
          return;
        }
      } catch {
        return; // the share sheet was dismissed
      }
      await navigator.clipboard?.writeText(url);
      toast.success("Live trip link copied. Anyone with it can follow your ride until you arrive.");
    },
    onError,
  });
  const sos = useMutation({
    mutationFn: (ambulance: boolean) => api.post(`trips/${id}/sos/`, { note: "Rider pressed SOS in the app", ambulance, lat: driverPos?.lat ?? trip?.pickup_lat, lng: driverPos?.lng ?? trip?.pickup_lng }),
    onSuccess: (_d, ambulance) => { setSosOpen(false); toast.success(ambulance ? "Safety team alerted and an ambulance requested. Also call 108 if you can." : "Safety team alerted. Stay on the line; we're calling you now."); },
    onError,
  });

  const points = useMemo<[number, number][]>(() => {
    if (!trip) return [];
    const pts: [number, number][] = [[trip.pickup_lat, trip.pickup_lng], [trip.dropoff_lat, trip.dropoff_lng]];
    if (driverPos && (trip.status === "DRIVER_ASSIGNED" || trip.status === "DRIVER_ARRIVED")) {
      return [[trip.pickup_lat, trip.pickup_lng], [driverPos.lat, driverPos.lng]];
    }
    if (driverPos && trip.status === "IN_PROGRESS") pts.push([driverPos.lat, driverPos.lng]);
    return pts;
  }, [trip, driverPos?.lat, driverPos?.lng]); // eslint-disable-line react-hooks/exhaustive-deps

  // The route the rider sees, and where the car is along it: the car is drawn on the line, the
  // part already driven disappears, and the ETA counts the road that's left.
  const route = useMemo<LatLng[]>(
    () => (trip ? routePath([trip.pickup_lat, trip.pickup_lng], [trip.dropoff_lat, trip.dropoff_lng], trip.route_polyline, (trip.stops ?? []).map((s) => [s.lat, s.lng] as [number, number])) : []),
    [trip?.id, trip?.route_polyline], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const onRoute = useMemo(() => {
    if (!driverPos || trip?.status !== "IN_PROGRESS") return null;
    const snap = snapToPath(route, [driverPos.lat, driverPos.lng]);
    return snap && snap.offMetres < 300 ? snap : null;
  }, [route, driverPos?.lat, driverPos?.lng, trip?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  if (isLoading || !trip) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="size-7" />
      </div>
    );
  }

  const pickup = { lat: trip.pickup_lat, lng: trip.pickup_lng };
  const dropoff = { lat: trip.dropoff_lat, lng: trip.dropoff_lng };
  const toPickupEta = driverPos ? etaMinutes(driverPos, pickup) : Number(trip.pickup_eta_min ?? 0);
  const toPickupKm = driverPos ? haversineKm(driverPos, pickup) * 1.3 : null;
  const toDropKm = onRoute ? onRoute.remainingKm : driverPos ? haversineKm(driverPos, dropoff) * 1.3 : Number(trip.estimated_distance_km);
  const toDropEta = onRoute || driverPos ? etaFromKm(toDropKm) : Number(trip.estimated_duration_min);
  const stopsAt: LatLng[] = (trip.stops ?? []).map((s) => [s.lat, s.lng]);
  const carAt: LatLng | null = onRoute ? onRoute.at : driverPos ? [driverPos.lat, driverPos.lng] : null;
  const waited = trip.arrived_at ? Math.max(0, Math.floor((now - new Date(trip.arrived_at).getTime()) / 60000)) : 0;
  const active = isActive(trip);

  return (
    <div className="relative flex h-full flex-col">
      <div className="absolute inset-0">
        <BaseMap center={[trip.pickup_lat, trip.pickup_lng]} zoom={14}>
          <FitBounds points={points} padding={50} bottom={380} fitKey={`${trip.status}-${driverPos ? 1 : 0}-${recenter}`} />
          <PinMarker lat={trip.pickup_lat} lng={trip.pickup_lng} kind={trip.status === "REQUESTED" ? "searching" : "pickup"} />
          {stopsAt.map(([lat, lng], i) => (
            <PinMarker key={i} lat={lat} lng={lng} kind="stop" label={stopsAt.length > 1 ? String(i + 1) : undefined} />
          ))}
          <PinMarker lat={trip.dropoff_lat} lng={trip.dropoff_lng} kind="dropoff" />
          {trip.status === "IN_PROGRESS" || !active ? (
            <RouteLine from={[trip.pickup_lat, trip.pickup_lng]} to={[trip.dropoff_lat, trip.dropoff_lng]} encoded={trip.route_polyline} via={stopsAt} progress={active ? carAt : null} />
          ) : (
            <RouteLine from={[trip.pickup_lat, trip.pickup_lng]} to={[trip.dropoff_lat, trip.dropoff_lng]} encoded={trip.route_polyline} via={stopsAt} dashed />
          )}
          {driverPos && carAt && active && trip.status !== "REQUESTED" && (
            <>
              {trip.status === "DRIVER_ASSIGNED" && <RouteLine from={[driverPos.lat, driverPos.lng]} to={[trip.pickup_lat, trip.pickup_lng]} dashed color="#10b981" />}
              <CarMarker lat={carAt[0]} lng={carAt[1]} heading={driverPos.heading} rideType={trip.ride_type} />
            </>
          )}
        </BaseMap>
      </div>

      <div className="rp-overlay relative z-[600] flex items-center justify-between p-3">
        <button onClick={() => navigate(active ? "/ride" : "/ride/activity")} className="flex size-10 items-center justify-center rounded-full bg-surface shadow-[var(--shadow-float)]" aria-label="Back">
          <ArrowLeft className="size-5" />
        </button>
        {active && trip.status !== "REQUESTED" && (
          <button onClick={() => setSosOpen(true)} className="flex items-center gap-1.5 rounded-full bg-danger px-4 py-2 text-sm font-bold text-white shadow-lg">
            <ShieldAlert className="size-4" /> SOS
          </button>
        )}
      </div>

      <div className="flex-1" />

      <div className="rp-overlay relative z-[600] flex justify-end px-3 pb-2">
        <button onClick={() => setRecenter((n) => n + 1)} className="flex size-10 items-center justify-center rounded-full bg-surface shadow-[var(--shadow-float)]" aria-label="Re-centre map">
          <LocateFixed className="size-5" />
        </button>
      </div>

      <RideCheckPrompt trip={trip} role="rider" />
      <Sheet height="70%">
        {trip.status === "REQUESTED" && (
          <>
            <Searching trip={trip} />
            <CounterOffers trip={trip} />
            <SureRideBadge trip={trip} />
            <Button variant="secondary" block className="mt-3" onClick={() => cancel.mutate()} loading={cancel.isPending}>
              {t("Cancel request")}
            </Button>
          </>
        )}

        {(trip.status === "DRIVER_ASSIGNED" || trip.status === "DRIVER_ARRIVED" || trip.status === "IN_PROGRESS") && (
          <>
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-xl font-bold">
                  {trip.status === "DRIVER_ASSIGNED" && t("Arriving in {time}", { time: minutes(toPickupEta) })}
                  {trip.status === "DRIVER_ARRIVED" && t(trip.service === "PARCEL" ? "Driver is here to pick up your parcel" : "Your driver is here")}
                  {trip.status === "IN_PROGRESS" &&
                    (trip.service === "RENTAL"
                      ? t("Rental · {h} h / {km} km", { h: trip.package_hours ?? 0, km: trip.package_km ?? 0 })
                      : t(trip.service === "PARCEL" ? "Parcel arriving in {time}" : "{time} to drop", { time: minutes(toDropEta) }))}
                </h2>
                <p className="mt-0.5 text-sm text-muted">
                  {trip.status === "DRIVER_ASSIGNED" && (toPickupKm !== null ? t("{distance} away · meet at {place}", { distance: km(toPickupKm), place: trip.pickup_address }) : t("Meet at {place}", { place: trip.pickup_address }))}
                  {trip.status === "DRIVER_ARRIVED" && (waited < 3 ? t("Free waiting: {n} min left", { n: 3 - waited }) : t("Waiting {n} min · waiting charges apply", { n: waited }))}
                  {trip.status === "IN_PROGRESS" && t("{distance} left · drop by {clock}", { distance: km(toDropKm), clock: clockIn(toDropEta) })}
                </p>
              </div>
            </div>
            <DriverCard trip={trip} />
            <PoolBadge trip={trip} role="rider" />
            <ParcelCard trip={trip} />
            <TripRecorder trip={trip} />
            <SureRideBadge trip={trip} />
            <NightSafeBar trip={trip} role="rider" />
            {trip.otp && trip.status !== "IN_PROGRESS" && (
              <>
                <CarCheck trip={trip} />
                <StartCode trip={trip} />
              </>
            )}
            {trip.driver && <TripChat tripId={trip.id} me="RIDER" otherName={trip.driver.name} canSend={active} />}
            <div className="mt-3 grid grid-cols-3 gap-2">
              <CallButton tripId={trip.id} name={trip.driver?.name ?? "your driver"} />
              <button
                onClick={() => share.mutate()}
                disabled={share.isPending}
                className="flex flex-col items-center gap-1 rounded-2xl bg-surface-2 py-3 text-xs font-semibold"
              >
                <Share2 className="size-4" /> {t("Share trip")}
              </button>
              {trip.status !== "IN_PROGRESS" ? (
                <button onClick={() => setConfirmCancel(true)} className="flex flex-col items-center gap-1 rounded-2xl bg-surface-2 py-3 text-xs font-semibold">
                  <X className="size-4" /> {t("Cancel")}
                </button>
              ) : (
                <button onClick={() => setHelpOpen(true)} className="flex flex-col items-center gap-1 rounded-2xl bg-surface-2 py-3 text-xs font-semibold">
                  <LifeBuoy className="size-4" /> {t("Help")}
                </button>
              )}
            </div>
            <div className="mt-4 flex items-center justify-between rounded-2xl border border-line px-4 py-3 text-sm">
              <span className="text-muted">
                {trip.payment_method === "CASH" ? t("Pay cash") : t("Pay by {method}", { method: trip.payment_method.toLowerCase() })} · {t("upfront")}
              </span>
              <span className="font-bold">{inr(trip.estimated_fare)}</span>
            </div>
          </>
        )}

        {trip.status === "COMPLETED" && (
          <>
            <div className="text-center">
              <Badge tone="brand">{t("Trip completed · {time}", { time: time(trip.completed_at) })}</Badge>
              <div className="mt-2 text-4xl font-bold tracking-tight">{inr(trip.fare_total)}</div>
              <div className="mt-1 text-sm text-muted">
                {km(trip.actual_distance_km)} · {minutes(trip.actual_duration_min)} · {trip.payment_method.toLowerCase()} {trip.payment_status === "DUES" && "(payment pending)"}
              </div>
            </div>

            <HomeSafeButton trip={trip} />
            {trip.driver && <FavouriteDriver trip={trip} />}
            {!trip.has_rated ? (
              <div className="mt-5 rounded-2xl bg-surface-2 p-4">
                <p className="mb-3 text-center text-sm font-semibold">{t("How was your ride with {name}?", { name: trip.driver?.name.split(" ")[0] ?? "" })}</p>
                <StarInput value={stars} onChange={setStars} />
                <div className="mt-3 flex flex-wrap justify-center gap-1.5">
                  {TAGS.map((tag) => (
                    <button
                      key={tag}
                      onClick={() => setTags((t) => (t.includes(tag) ? t.filter((x) => x !== tag) : [...t, tag]))}
                      className={clsx("rounded-full border px-3 py-1 text-xs font-medium", tags.includes(tag) ? "border-fg bg-ink text-ink-fg" : "border-line")}
                    >
                      {tag}
                    </button>
                  ))}
                </div>
                <Textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder={t("Add a comment (optional)")} className="mt-3 !min-h-16" />
                <Button block className="mt-3" onClick={() => rate.mutate()} loading={rate.isPending}>
                  {t("Submit rating")}
                </Button>
              </div>
            ) : (
              <p className="mt-4 text-center text-sm text-muted">{t("Thanks for your rating ⭐")}</p>
            )}

            <div className="mt-4">
              <p className="mb-2 text-center text-xs font-semibold text-muted uppercase">Add a tip · goes 100% to your driver</p>
              <div className="grid grid-cols-3 gap-2">
                {[20, 50, 100].map((amount) => (
                  <Button key={amount} variant="outline" onClick={() => tip.mutate(amount)} loading={tip.isPending && tip.variables === amount}>
                    ₹{amount}
                  </Button>
                ))}
              </div>
              {Number(trip.tip_amount) > 0 && <p className="mt-2 text-center text-xs text-brand-strong">You tipped {inr(trip.tip_amount)}. Thank you!</p>}
            </div>

            <details className="mt-4 rounded-2xl border border-line px-4 py-3 text-sm">
              <summary className="cursor-pointer font-semibold">{t("Fare details")}</summary>
              <div className="mt-2 space-y-1 text-xs">
                {trip.fare.lines.map((line) => (
                  <div key={line.code} className="flex justify-between">
                    <span className="text-muted">{line.label}</span>
                    <span>{inr(line.amount)}</span>
                  </div>
                ))}
                <div className="flex justify-between border-t border-line pt-1 font-semibold">
                  <span>{t("Total")}</span>
                  <span>{inr(trip.fare.total)}</span>
                </div>
                <p className="pt-1 text-muted">{trip.pricing_mode === "UPFRONT" ? "Your upfront price was honoured." : "Re-priced because the route was much longer than estimated."}</p>
              </div>
            </details>

            <ParcelCard trip={trip} />
            <TripEcoLine trip={trip} />
            <FairShareCard trip={trip} />
            <InvoiceCard trip={trip} />
            <SplitFareCard trip={trip} />
            <TripRecorder trip={trip} />
            <LockFareButton trip={trip} />
            <LostItemCard trip={trip} />

            <div className="mt-3 grid grid-cols-3 gap-2">
              <Button variant="secondary" icon={<Download className="size-4" />} onClick={() => openFile(`/api/v1/trips/${trip.id}/receipt/`)}>
                PDF
              </Button>
              <Button variant="secondary" icon={<LifeBuoy className="size-4" />} onClick={() => setHelpOpen(true)}>
                {t("Help")}
              </Button>
              <Button variant="secondary" icon={<RotateCcw className="size-4" />} onClick={() => navigate(`/ride/book?to=${trip.dropoff_lat},${trip.dropoff_lng}&name=${encodeURIComponent(trip.dropoff_address)}`)}>
                {t("Again")}
              </Button>
            </div>
          </>
        )}

        {(trip.status === "CANCELLED" || trip.status === "NO_DRIVER_FOUND") && (
          <div className="py-2 text-center">
            <div className="mx-auto mb-3 flex size-14 items-center justify-center rounded-full bg-surface-3">
              <X className="size-6 text-muted" />
            </div>
            <h2 className="text-lg font-bold">{trip.status === "NO_DRIVER_FOUND" ? "No drivers available" : "Trip cancelled"}</h2>
            <p className="mt-1 text-sm text-muted">{trip.cancellation_reason}</p>
            {Number(trip.cancellation_fee) > 0 && <p className="mt-2 text-sm font-semibold text-danger">Cancellation fee {inr(trip.cancellation_fee)}</p>}
            <p className="mt-1 text-xs text-muted">{dateTime(trip.cancelled_at)}</p>
            {trip.status === "NO_DRIVER_FOUND" && <NoDriverAlternative trip={trip} />}
            <Button className="mt-4" block onClick={() => navigate(`/ride/book?to=${trip.dropoff_lat},${trip.dropoff_lng}&name=${encodeURIComponent(trip.dropoff_address)}`)}>
              {t("Try again")}
            </Button>
          </div>
        )}
      </Sheet>

      <Modal
        open={confirmCancel}
        onClose={() => setConfirmCancel(false)}
        title={t("Cancel this ride?")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmCancel(false)}>
              {t("Keep ride")}
            </Button>
            <Button variant="danger" onClick={() => cancel.mutate()} loading={cancel.isPending}>
              {t("Cancel ride")}
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted">
          Cancelling is free for 2 minutes after a driver accepts. After that, or once the driver has arrived, a cancellation fee is charged to your wallet.
        </p>
      </Modal>

      <Modal
        open={sosOpen}
        onClose={() => setSosOpen(false)}
        title="Emergency help"
        footer={
          <div className="grid gap-2">
            <Button variant="danger" block onClick={() => sos.mutate(false)} loading={sos.isPending}>
              Alert the safety team now
            </Button>
            <Button variant="secondary" block onClick={() => sos.mutate(true)} disabled={sos.isPending}>
              Medical emergency: send an ambulance
            </Button>
          </div>
        }
      >
        <p className="text-sm">We'll share your trip and live location with the Ride Pulse safety team, who will call you right away.</p>
        <p className="mt-3 text-sm text-muted">
          In a life-threatening emergency, call <a className="font-bold text-danger" href="tel:112">112</a> (ambulance: <a className="font-bold text-danger" href="tel:108">108</a>).
        </p>
      </Modal>

      <HelpModal open={helpOpen} onClose={() => setHelpOpen(false)} tripId={trip.id} />
    </div>
  );
}

export function HelpModal({ open, onClose, tripId, base = "/ride" }: { open: boolean; onClose: () => void; tripId?: number; base?: string }) {
  const navigate = useNavigate();
  const [category, setCategory] = useState("FARE_DISPUTE");
  const [description, setDescription] = useState("");
  const create = useMutation({
    mutationFn: () =>
      api.post<{ id: number }>("support/tickets/", {
        category,
        subject: { FARE_DISPUTE: "I was overcharged", LOST_ITEM: "I left something in the car", DRIVER_BEHAVIOUR: "Problem with my driver", PAYMENT: "Payment problem", OTHER: "Something else" }[category] ?? "Help with my trip",
        description,
        trip: tripId ?? null,
      }),
    onSuccess: (ticket) => {
      toast.success("Ticket created. Our support team will reply shortly.");
      onClose();
      navigate(`${base}/support/${ticket.id}`);
    },
    onError: (err) => toast.error((err as Error).message),
  });
  const options = [
    ["FARE_DISPUTE", "I was overcharged"],
    ["LOST_ITEM", "I lost an item"],
    ["DRIVER_BEHAVIOUR", "Problem with my driver"],
    ["PAYMENT", "Payment problem"],
    ["OTHER", "Something else"],
  ];
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Get help with this trip"
      footer={
        <Button onClick={() => create.mutate()} loading={create.isPending} disabled={description.trim().length < 5}>
          Send to support
        </Button>
      }
    >
      <div className="space-y-2">
        {options.map(([value, label]) => (
          <label key={value} className={clsx("flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 text-sm", category === value ? "border-fg bg-surface-2" : "border-line")}>
            <input type="radio" name="category" value={value} checked={category === value} onChange={() => setCategory(value)} className="accent-current" />
            {label}
          </label>
        ))}
      </div>
      <Textarea className="mt-3" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Tell us what happened" />
      <p className="mt-2 text-xs text-muted">
        Or see <Link to={`${base}/support`} className="font-semibold underline" onClick={onClose}>your tickets</Link>.
      </p>
    </Modal>
  );
}

/** "Invoice sent to priya@…": view it, or have it emailed again. */
function InvoiceCard({ trip }: { trip: Trip }) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const hasEmail = !!user?.email && !user.email.endsWith(".invalid");
  const resend = useMutation({
    mutationFn: () => api.post<{ sent_to: string }>(`trips/${trip.id}/email-invoice/`),
    onSuccess: ({ sent_to }) => {
      toast.success(`Invoice sent to ${sent_to}`);
      qc.invalidateQueries({ queryKey: ["trips"] });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't send the invoice."),
  });
  if (trip.payment_status !== "PAID") {
    return <p className="mt-4 rounded-2xl bg-surface-2 px-4 py-3 text-xs text-muted">Your invoice will be emailed once the payment goes through.</p>;
  }
  return (
    <div className="mt-4 flex items-center gap-3 rounded-2xl bg-surface-2 px-4 py-3">
      <Mail className="size-5 shrink-0 text-muted" />
      <div className="min-w-0 flex-1 text-sm">
        <div className="font-semibold">{trip.invoice_number ? `Invoice ${trip.invoice_number}` : "Invoice"}</div>
        <div className="truncate text-xs text-muted">
          {trip.invoice_emailed_at ? `Sent to ${hasEmail ? user!.email : "your email"}` : hasEmail ? "Tap Email to get a copy" : "Add an email in Account to receive it"}
        </div>
      </div>
      <button onClick={() => openFile(`/api/v1/trips/${trip.id}/invoice/`)} className="text-xs font-semibold text-brand-strong">
        View
      </button>
      <button onClick={() => resend.mutate()} disabled={resend.isPending} className="text-xs font-semibold text-brand-strong disabled:opacity-50">
        {resend.isPending ? "Sending…" : "Email"}
      </button>
    </div>
  );
}

/** Heart a driver you liked: they're offered your rides first when they're nearby. */
function FavouriteDriver({ trip }: { trip: Trip }) {
  const qc = useQueryClient();
  const toggle = useMutation({
    mutationFn: (favourite: boolean) => api.post(`trips/${trip.id}/favourite/`, { favourite }),
    onSuccess: (_, favourite) => {
      qc.invalidateQueries({ queryKey: ["trips"] });
      qc.invalidateQueries({ queryKey: ["rider", "me"] });
      if (favourite) toast.success(`${trip.driver!.name.split(" ")[0]} is a favourite. They'll be asked first when nearby.`);
    },
  });
  const on = trip.is_favourite_driver;
  return (
    <button
      onClick={() => toggle.mutate(!on)}
      disabled={toggle.isPending}
      className={clsx("mt-4 flex w-full items-center justify-center gap-2 rounded-2xl border py-2.5 text-sm font-semibold transition", on ? "border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-400/30 dark:bg-rose-400/10 dark:text-rose-200" : "border-line")}
      aria-pressed={on}
    >
      <Heart className={clsx("size-4", on && "fill-current")} /> {on ? `${trip.driver!.name.split(" ")[0]} is a favourite driver` : `Add ${trip.driver!.name.split(" ")[0]} to favourite drivers`}
    </button>
  );
}

/** After "no drivers available": the ride type that has cars near this pickup right now. */
function NoDriverAlternative({ trip }: { trip: Trip }) {
  const navigate = useNavigate();
  const estimate = useQuery({
    queryKey: ["estimate", "after-no-driver", trip.id],
    queryFn: () =>
      api.post<Estimate>("fares/estimate/", {
        pickup: { lat: trip.pickup_lat, lng: trip.pickup_lng },
        dropoff: { lat: trip.dropoff_lat, lng: trip.dropoff_lng },
      }),
    staleTime: 30_000,
  });
  const mine = estimate.data?.options.find((o) => o.ride_type.code === trip.ride_type);
  const alt = mine?.suggestion;
  if (!alt) return null;
  return (
    <button
      onClick={() => navigate(`/ride/book?to=${trip.dropoff_lat},${trip.dropoff_lng}&name=${encodeURIComponent(trip.dropoff_address)}&type=${alt.ride_type}`)}
      className="mt-4 flex w-full items-center gap-3 rounded-2xl bg-brand/10 px-4 py-3 text-left"
    >
      <RideTypeArt code={alt.ride_type} className="h-8 w-14 shrink-0" />
      <span className="flex-1">
        <span className="block font-semibold">{t("Switch to {ride}", { ride: alt.name })}</span>
        <span className="block text-xs text-muted">
          {alt.pickup_eta_min !== null && t("{n} min away", { n: alt.pickup_eta_min })} · {inr(alt.fare_total)}
        </span>
      </span>
      <ChevronRight className="size-4" />
    </button>
  );
}
