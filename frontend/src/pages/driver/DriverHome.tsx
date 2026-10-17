import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { AlertTriangle, Banknote, BellRing, Bot, LocateFixed, MapPin, Navigation, Package, Power, Satellite, ScanLine, ShieldAlert, Zap } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { BaseMap, CarMarker, FitBounds, MapCircle, MapClick, PinMarker, RouteLine, advanceAlong, routePath, snapToPath } from "@/components/map";
import { CallButton } from "@/components/CallButton";
import { GoalChip, GoingHomeButton } from "@/components/DriverGoals";
import { AirportQueueChip, EvCard } from "@/components/DriverBusiness";
import { DriverTours } from "@/components/DriverTours";
import { InductionDueCard } from "@/pages/driver/DriverAcademy";
import { AnnouncementCard } from "@/components/Announcements";
import { NpsCard } from "@/components/NpsCard";
import { HotZones } from "@/components/HotZones";
import { BreakCard, WellbeingChip } from "@/components/FairShare";
import { DriverLostItems } from "@/components/LostItem";
import { PoolBadge } from "@/components/PoolBadge";
import { TripRecorder } from "@/components/TripRecorder";
import { NightSafeBar, RideCheckPrompt } from "@/components/SafetyPlus";
import { NotificationBell } from "@/components/NotificationBell";
import { usePush } from "@/components/PushToggle";
import { QrScanner } from "@/components/QrScanner";
import { TripChat } from "@/components/TripChat";
import { Avatar, Badge, Button, Input, Modal, Sheet, StarInput, Stars } from "@/components/ui";
import { buzz, chime } from "@/lib/alert";
import { api, ApiError } from "@/lib/api";
import { sendLocation } from "@/lib/offline";
import { inr, km, minutes } from "@/lib/format";
import { usePhoneGps } from "@/lib/gps";
import { ACCESSIBILITY, PREFERENCES } from "@/lib/preferences";
import { clockIn, etaFromKm, haversineKm, useActiveTrip, useDriverMe, useNow } from "@/lib/hooks";
import type { City, Earnings, Offer, Trip } from "@/lib/types";
import { t } from "@/lib/i18n";
import { useSocket } from "@/lib/ws";

type Pos = { lat: number; lng: number; heading: number | null };

function stepTowards(from: Pos, to: { lat: number; lng: number }, stepKm: number): Pos & { arrived: boolean } {
  const d = haversineKm(from, to);
  const heading = (Math.atan2(to.lng - from.lng, to.lat - from.lat) * 180) / Math.PI;
  if (d <= stepKm) return { ...to, heading: (heading + 360) % 360, arrived: true };
  const f = stepKm / d;
  return { lat: from.lat + (to.lat - from.lat) * f, lng: from.lng + (to.lng - from.lng) * f, heading: (heading + 360) % 360, arrived: false };
}

function OfferCard({ offer, onAccept, onDecline, onCounter, busy }: { offer: Offer; onAccept: () => void; onDecline: () => void; onCounter: (extra: string) => void; busy: boolean }) {
  const now = useNow(250);
  const total = 20_000;
  const left = Math.max(0, new Date(offer.expires_at).getTime() - now);
  const fraction = Math.min(1, left / total);
  const r = 26;
  const c = 2 * Math.PI * r;
  const urgent = left < 6_000;
  // Chime and buzz once per offer, like a real driver app.
  useEffect(() => {
    chime();
    buzz();
  }, [offer.offer_id]);
  return (
    <div className={clsx("rp-offer absolute inset-x-3 bottom-3 z-[800] animate-[slide-up_0.35s_ease-out] rounded-3xl bg-surface p-5 shadow-[0_24px_60px_-12px_rgb(0_0_0/0.45)] ring-2 transition", urgent ? "ring-amber-400/70" : "ring-transparent")}>
      <div className="flex items-start justify-between">
        <div>
          <Badge tone="brand">{offer.service === "PARCEL" ? t("New parcel delivery") : `New ${offer.ride_type} request`}</Badge>
          {offer.day_pass && <div className="mt-1 text-xs font-semibold text-brand-strong">{t("Day pass: you keep 100%")}</div>}
          {offer.package && (
            <div className="mt-1 text-xs font-semibold text-indigo-700 dark:text-indigo-300">
              {offer.package.kind === "RENTAL"
                ? t("Rental · {h} h / {km} km", { h: offer.package.hours, km: offer.package.km })
                : t("Intercity to {place} · {km} km · {how}", {
                    place: offer.package.destination,
                    km: Math.round(Number(offer.package.km)),
                    how: offer.package.round_trip ? t("round trip, {n} days", { n: offer.package.days }) : t("one way"),
                  })}
            </div>
          )}
          {offer.parcel && (
            <div className="mt-1 flex items-center gap-1 text-xs font-semibold">
              <Package className="size-3.5" /> {t(offer.parcel.category)} · {t("up to {n} kg", { n: Number(offer.parcel.weight_kg) })}
            </div>
          )}
          <div className="mt-2 text-3xl font-bold tracking-tight">{inr(offer.estimated_earning)}</div>
          {offer.fare_offer !== null && (
            <div className="mt-1 text-xs font-semibold text-indigo-700 dark:text-indigo-300">
              {t("Rider offers {offer} · usual fare {usual}", { offer: inr(offer.fare_offer), usual: inr(offer.usual_fare) })}
            </div>
          )}
          {offer.preferences.length > 0 && <PreferenceChips values={offer.preferences} />}
          {(Number(offer.boost) > 0 || Number(offer.tip) > 0) && (
            <div className="mt-1 flex flex-wrap gap-1.5">
              {Number(offer.boost) > 0 && <Badge tone="warning">+₹{Number(offer.boost)} boost</Badge>}
              {Number(offer.tip) > 0 && <Badge tone="brand">+₹{Number(offer.tip)} tip</Badge>}
            </div>
          )}
          <div className="text-xs text-muted">
            est. earning{Number(offer.tip) > 0 ? " before tip" : ""} · {offer.payment_method.toLowerCase()}
            {Number(offer.surge) > 1 && (
              <span className="ml-1 font-semibold text-amber-600">
                <Zap className="inline size-3" /> {offer.surge}×
              </span>
            )}
          </div>
        </div>
        <svg width="64" height="64" className="-rotate-90">
          <circle cx="32" cy="32" r={r} fill="none" stroke="var(--color-surface-3)" strokeWidth="6" />
          <circle
            cx="32"
            cy="32"
            r={r}
            fill="none"
            stroke={left < 3_000 ? "var(--color-danger)" : urgent ? "#f59e0b" : "var(--color-brand)"}
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={c}
            strokeDashoffset={c * (1 - fraction)}
            className="transition-[stroke-dashoffset,stroke] duration-300 ease-linear"
          />
          <text x="32" y="38" textAnchor="middle" className="rotate-90 fill-fg text-base font-bold" style={{ transformOrigin: "32px 32px" }}>
            {Math.ceil(left / 1000)}
          </text>
        </svg>
      </div>
      <div className="mt-4 space-y-3 text-sm">
        <div className="flex gap-3">
          <span className="mt-1.5 size-2.5 shrink-0 rounded-full bg-brand" />
          <div>
            <div className="font-semibold">{offer.pickup.address || "Pickup"}</div>
            <div className="text-xs text-muted">
              {km(offer.pickup_distance_km)} away · {minutes(offer.pickup_eta_min)}
            </div>
          </div>
        </div>
        <div className="flex gap-3">
          <span className="mt-1.5 size-2.5 shrink-0 bg-ink" />
          <div>
            <div className="font-semibold">{offer.dropoff.address || "Drop"}</div>
            <div className="text-xs text-muted">{km(offer.trip_distance_km)} trip</div>
          </div>
        </div>
      </div>
      {offer.counter_steps.length > 0 && (
        <div className="mt-4">
          <div className="mb-1 text-xs font-semibold text-muted">{t("Or counter-offer")}</div>
          <div className="grid grid-cols-3 gap-2">
            {offer.counter_steps.map((step) => (
              <Button key={step} variant="outline" size="sm" disabled={busy} onClick={() => onCounter(step)}>
                +₹{Number(step)}
              </Button>
            ))}
          </div>
        </div>
      )}
      <div className="mt-5 grid grid-cols-[1fr_2fr] gap-2">
        <Button variant="secondary" size="lg" onClick={onDecline} disabled={busy}>
          {t("Decline")}
        </Button>
        <Button variant="brand" size="lg" onClick={onAccept} loading={busy}>
          {t("Accept")}
        </Button>
      </div>
    </div>
  );
}

/** The rider's requests ("Quiet ride", "AC on", …) as small chips. */
function PreferenceChips({ values }: { values: string[] }) {
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {ACCESSIBILITY.filter((p) => values.includes(p.value)).map(({ value, driverLabel, icon: Icon }) => (
        <span key={value} className="flex items-center gap-1 rounded-full bg-sky-100 px-2 py-0.5 text-[11px] font-semibold text-sky-800 dark:bg-sky-500/15 dark:text-sky-300">
          <Icon className="size-3" /> {driverLabel}
        </span>
      ))}
      {PREFERENCES.filter((p) => values.includes(p.value)).map(({ value, driverLabel, icon: Icon }) => (
        <span key={value} className="flex items-center gap-1 rounded-full bg-surface-3 px-2 py-0.5 text-[11px] font-semibold">
          <Icon className="size-3" /> {driverLabel}
        </span>
      ))}
    </div>
  );
}

function PinEntry({ onSubmit, onScan, busy }: { onSubmit: (pin: string) => void; onScan: (code: string) => void; busy: boolean }) {
  const [pin, setPin] = useState("");
  const [scanning, setScanning] = useState(false);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (pin.length === 4) onSubmit(pin);
      }}
    >
      <Button
        type="button"
        block
        size="lg"
        variant="brand"
        className="mb-3"
        icon={<ScanLine className="size-5" />}
        onClick={() => setScanning(true)}
        loading={busy && scanning}
      >
        {t("Scan rider's QR code")}
      </Button>
      {scanning && (
        <QrScanner
          onClose={() => setScanning(false)}
          onScan={(code) => {
            setScanning(false);
            onScan(code);
          }}
        />
      )}
      <label className="label">{t("Or enter the 4-digit PIN they read out")}</label>
      <div className="flex gap-2">
        <Input
          inputMode="numeric"
          maxLength={4}
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 4))}
          placeholder="• • • •"
          className="text-center font-mono text-2xl font-bold tracking-[0.6em]"
        />
        <Button type="submit" size="lg" variant="brand" disabled={pin.length !== 4} loading={busy}>
          {t("Start")}
        </Button>
      </div>
    </form>
  );
}

export default function DriverHome() {
  const qc = useQueryClient();
  const me = useDriverMe(6_000);
  const driver = me.data;
  const online = driver?.availability === "ONLINE" || driver?.availability === "ON_TRIP";
  const active = useActiveTrip(!!driver);
  const trip = active.data;
  const cities = useQuery({ queryKey: ["cities"], queryFn: () => api.get<City[]>("cities/") });
  const city = cities.data?.find((c) => c.slug === driver?.city);
  const [pos, setPos] = useState<Pos | null>(null);
  const [offer, setOffer] = useState<Offer | null>(null);
  const [autopilot, setAutopilot] = useState(false);
  const push = usePush();
  // Real GPS from the phone (remembered per device); otherwise the demo: tap the map / autopilot.
  const [phoneGps, setPhoneGps] = useState(() => {
    try {
      return localStorage.getItem("rp.driver.gps") === "1";
    } catch {
      return false;
    }
  });
  const [completed, setCompleted] = useState<Trip | null>(null);
  const [recenter, setRecenter] = useState(0);
  const [riderStars, setRiderStars] = useState(5);
  const lastSent = useRef(0);

  const today = useQuery({
    queryKey: ["driver", "earnings", "today"],
    queryFn: () => api.get<Earnings>("driver/earnings/?period=today"),
    refetchInterval: 30_000,
    enabled: !!driver,
  });
  const surge = useQuery({
    queryKey: ["driver", "surge"],
    queryFn: () => api.get<{ zone: string; lat: number; lng: number; radius_km: number; multiplier: string }[]>("driver/surge/"),
    refetchInterval: 60_000,
    enabled: !!driver,
  });
  const offerPoll = useQuery({
    queryKey: ["driver", "offer"],
    queryFn: () => api.get<Offer | undefined>("driver/offer/").then((o) => o ?? null),
    refetchInterval: 2_500,
    enabled: online && !trip,
  });

  useEffect(() => {
    if (offerPoll.data !== undefined) setOffer(offerPoll.data);
  }, [offerPoll.data]);

  useSocket(driver ? "/ws/driver/" : null, (msg) => {
    if (msg.event === "offer") setOffer(msg.data as Offer);
    if (msg.event === "offer_closed") setOffer(null);
    if (msg.event === "trip_cancelled") {
      toast.warning("The rider cancelled the trip.");
      qc.invalidateQueries({ queryKey: ["trips"] });
    }
  });

  // Initial position: last known GPS, else the city centre.
  useEffect(() => {
    if (pos || !driver) return;
    if (driver.current_lat !== null && driver.current_lng !== null) setPos({ lat: driver.current_lat, lng: driver.current_lng, heading: null });
    else if (city) setPos({ lat: city.center_lat, lng: city.center_lng, heading: null });
  }, [driver, city, pos]);

  const pushLocation = useCallback(async (next: Pos) => {
    setPos(next);
    lastSent.current = Date.now();
    // Offline: the fix is kept with its time and replayed when the signal comes back.
    await sendLocation({ lat: next.lat, lng: next.lng, heading: next.heading });
  }, []);

  const gpsState = usePhoneGps(phoneGps && online, (fix) => {
    pushLocation({ lat: fix.lat, lng: fix.lng, heading: fix.heading ?? posRef.current?.heading ?? null });
  });
  useEffect(() => {
    if (gpsState === "denied") toast.error("Location permission is blocked. Allow it in the browser to use phone GPS.");
    if (gpsState === "unavailable") toast.error("This device can't share its location right now.");
  }, [gpsState]);
  const toggleGps = () => {
    const next = !phoneGps;
    setPhoneGps(next);
    if (next) setAutopilot(false);
    try {
      localStorage.setItem("rp.driver.gps", next ? "1" : "0");
    } catch {
      /* not persisted */
    }
  };

  // Demo autopilot: drive to the pickup, then along the trip's route to the drop, sending GPS as we go.
  const route = useMemo(
    () => (trip ? routePath([trip.pickup_lat, trip.pickup_lng], [trip.dropoff_lat, trip.dropoff_lng], trip.route_polyline, (trip.stops ?? []).map((s) => [s.lat, s.lng] as [number, number])) : []),
    [trip?.id, trip?.route_polyline], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const target = useMemo(() => {
    if (!trip) return null;
    if (trip.status === "DRIVER_ASSIGNED") return { lat: trip.pickup_lat, lng: trip.pickup_lng };
    if (trip.status === "IN_PROGRESS") return { lat: trip.dropoff_lat, lng: trip.dropoff_lng };
    return null;
  }, [trip]);
  const following = trip?.status === "IN_PROGRESS";
  const posRef = useRef(pos);
  posRef.current = pos;
  useEffect(() => {
    if (!autopilot || !target) return;
    const t = setInterval(() => {
      const current = posRef.current;
      if (!current) return;
      if (following) {
        const next = advanceAlong(route, [current.lat, current.lng], 0.18);
        pushLocation({ lat: next.at[0], lng: next.at[1], heading: next.heading });
      } else {
        pushLocation(stepTowards(current, target, 0.18));
      }
    }, 1200);
    return () => clearInterval(t);
  }, [autopilot, target, following, route, pushLocation]);

  const onError = (err: unknown) => toast.error(err instanceof ApiError ? err.message : "Something went wrong.");
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["driver"] });
    qc.invalidateQueries({ queryKey: ["trips"] });
  };
  const toggle = useMutation({
    mutationFn: () => (online ? api.post("driver/offline/") : api.post("driver/online/", { lat: pos?.lat, lng: pos?.lng })),
    onSuccess: () => {
      toast.success(online ? "You're offline" : "You're online. Finding trips near you…");
      refresh();
    },
    onError,
  });
  const accept = useMutation({
    mutationFn: (o: Offer) => api.post<Trip>(`driver/offers/${o.offer_id}/accept/`),
    onSuccess: (accepted) => {
      setOffer(null);
      // Show the trip straight away rather than waiting for the next poll.
      qc.setQueryData(["trips", "active"], accepted);
      toast.success("Trip accepted. Head to the pickup.");
      refresh();
    },
    onError: (err) => {
      setOffer(null);
      onError(err);
    },
  });
  // Declining can't meaningfully fail for the driver, so the card goes away immediately.
  const decline = useMutation({ mutationFn: (o: Offer) => api.post(`driver/offers/${o.offer_id}/decline/`), onMutate: () => setOffer(null), onError });
  const counter = useMutation({
    mutationFn: ({ o, extra }: { o: Offer; extra: string }) => api.post(`driver/offers/${o.offer_id}/counter/`, { extra }),
    onMutate: () => setOffer(null),
    onSuccess: () => toast.success(t("Counter-offer sent. We'll tell you if the rider accepts.")),
    onError,
  });
  const arrive = useMutation({ mutationFn: () => api.post(`trips/${trip!.id}/arrive/`), onSuccess: refresh, onError });
  const start = useMutation({
    mutationFn: (proof: { otp: string } | { qr: string }) => api.post(`trips/${trip!.id}/start/`, proof),
    onSuccess: () => {
      toast.success("Trip started. Drive safe!");
      refresh();
    },
    onError,
  });
  const [deliveryCode, setDeliveryCode] = useState("");
  const complete = useMutation({
    mutationFn: () =>
      api.post<Trip>(`trips/${trip!.id}/complete/`, {
        delivery_code: deliveryCode,
        telemetry: { harsh_brakes: Math.round(Math.random() * 2), harsh_accelerations: Math.round(Math.random()), speeding_seconds: Math.round(Math.random() * 40) },
      }),
    onSuccess: (done) => {
      setCompleted(done);
      setDeliveryCode("");
      setAutopilot(false);
      refresh();
    },
    onError,
  });
  const cancel = useMutation({ mutationFn: () => api.post(`trips/${trip!.id}/cancel/`, { reason: "Driver cancelled" }), onSuccess: () => { toast("Trip released to another driver"); refresh(); }, onError });
  const rateRider = useMutation({
    mutationFn: () => api.post(`trips/${completed!.id}/rate/`, { stars: riderStars }),
    onSuccess: () => setCompleted(null),
    onError: () => setCompleted(null),
  });

  const points = useMemo<[number, number][]>(() => {
    const pts: [number, number][] = [];
    if (pos) pts.push([pos.lat, pos.lng]);
    if (trip) pts.push(trip.status === "IN_PROGRESS" ? [trip.dropoff_lat, trip.dropoff_lng] : [trip.pickup_lat, trip.pickup_lng]);
    if (offer) pts.push([offer.pickup.lat, offer.pickup.lng]);
    return pts;
  }, [pos?.lat, pos?.lng, trip?.status, trip?.id, offer?.offer_id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!driver || !pos) {
    return <div className="flex h-full items-center justify-center text-muted">Loading…</div>;
  }

  const blocked = driver.compliance_problems.length > 0;
  const distanceToPickup = trip ? haversineKm(pos, { lat: trip.pickup_lat, lng: trip.pickup_lng }) : 0;
  const onRoute = following ? snapToPath(route, [pos.lat, pos.lng]) : null;
  const distanceToDrop = trip ? (onRoute && onRoute.offMetres < 300 ? onRoute.remainingKm : haversineKm(pos, { lat: trip.dropoff_lat, lng: trip.dropoff_lng }) * 1.3) : 0;

  return (
    <div className="relative flex h-full flex-col">
      <div className="absolute inset-0">
        <BaseMap center={[pos.lat, pos.lng]} zoom={14}>
          <FitBounds points={points} padding={60} bottom={380} fitKey={`${trip?.id}-${trip?.status}-${offer?.offer_id}-${recenter}`} />
          {(surge.data ?? []).map((z) => (
            <MapCircle key={z.zone} center={[z.lat, z.lng]} radius={z.radius_km * 1000} color="#f59e0b" label={`${z.multiplier}×`} permanentLabel />
          ))}
          <CarMarker lat={pos.lat} lng={pos.lng} heading={pos.heading} rideType={driver.vehicle?.ride_type} />
          {trip && <PinMarker lat={trip.pickup_lat} lng={trip.pickup_lng} kind="pickup" />}
          {(trip?.stops ?? []).map((s, i, all) => (
            <PinMarker key={i} lat={s.lat} lng={s.lng} kind="stop" label={all.length > 1 ? `Stop ${i + 1}` : "Stop"} />
          ))}
          {trip && <PinMarker lat={trip.dropoff_lat} lng={trip.dropoff_lng} kind="dropoff" />}
          {trip && trip.status === "DRIVER_ASSIGNED" && <RouteLine from={[pos.lat, pos.lng]} to={[trip.pickup_lat, trip.pickup_lng]} dashed color="#10b981" />}
          {trip && trip.status !== "DRIVER_ASSIGNED" && (
            <RouteLine
              from={[trip.pickup_lat, trip.pickup_lng]}
              to={[trip.dropoff_lat, trip.dropoff_lng]}
              encoded={trip.route_polyline}
              via={(trip.stops ?? []).map((s) => [s.lat, s.lng] as [number, number])}
              progress={following ? [pos.lat, pos.lng] : null}
            />
          )}
          {offer && <PinMarker lat={offer.pickup.lat} lng={offer.pickup.lng} kind="pickup" label="Pickup" />}
          {!autopilot && !phoneGps && <MapClick onClick={(lat, lng) => pushLocation({ lat, lng, heading: pos.heading })} />}
        </BaseMap>
      </div>

      <div className="rp-overlay relative z-[600] flex items-center gap-2 p-3">
        <div className="rp-compact flex flex-1 items-center gap-2 rounded-full bg-surface/95 px-2 py-1.5 shadow-[var(--shadow-float)] backdrop-blur">
          <Avatar name={driver.name} size={32} />
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-sm font-semibold">{inr(today.data?.earnings ?? 0)} today</div>
            <div className="text-[11px] text-muted">
              <Stars value={driver.rating} size={10} /> · {today.data?.trips ?? 0} trips
            </div>
            <GoalChip />
            <WellbeingChip />
          </div>
        </div>
        <div className="rp-phone-only rounded-full bg-surface/95 shadow-[var(--shadow-float)] backdrop-blur">
          <NotificationBell />
        </div>
      </div>

      {online && !trip && !offer && push.status === "off" && (
        <button
          onClick={push.toggle}
          className="rp-overlay relative z-[600] mx-3 mt-1 flex items-center gap-2 rounded-2xl bg-surface px-4 py-2.5 text-left text-xs shadow-[var(--shadow-float)]"
        >
          <BellRing className="size-4 shrink-0 text-brand" />
          <span className="flex-1">
            <b>Turn on notifications</b> to get trip offers when the app is in the background.
          </span>
        </button>
      )}
      {!trip && online && !offer && !phoneGps && (
        <div className="rp-overlay relative z-[600] mx-auto mt-1 rounded-full bg-ink/90 px-4 py-1.5 text-xs font-semibold text-ink-fg">{t("Tap the map to move your car")}</div>
      )}

      <div className="flex-1" />

      {trip && <RideCheckPrompt trip={trip} role="driver" />}
      {!trip && !offer && <DriverLostItems />}
      <div className="rp-overlay relative z-[600] flex items-center justify-end gap-2 px-3 pb-2">
        {online && !trip && <GoingHomeButton driver={driver} />}
        {online && (
          <button
            onClick={toggleGps}
            className={clsx("flex items-center gap-1.5 rounded-full px-3 py-2 text-xs font-bold shadow-lg", phoneGps ? "bg-info text-white" : "bg-surface")}
            aria-pressed={phoneGps}
          >
            <Satellite className="size-4" /> {phoneGps ? (gpsState === "tracking" ? "Phone GPS live" : "Finding GPS…") : "Use phone GPS"}
          </button>
        )}
        {trip && !phoneGps && (
          <button
            onClick={() => setAutopilot((a) => !a)}
            className={clsx("flex items-center gap-1.5 rounded-full px-3 py-2 text-xs font-bold shadow-lg", autopilot ? "bg-brand text-white" : "bg-surface")}
          >
            <Bot className="size-4" /> Demo autopilot {autopilot ? "on" : "off"}
          </button>
        )}
        <button onClick={() => setRecenter((n) => n + 1)} className="flex size-10 items-center justify-center rounded-full bg-surface shadow-[var(--shadow-float)]" aria-label="Re-centre map">
          <LocateFixed className="size-5" />
        </button>
      </div>

      {offer && !trip ? (
        <OfferCard offer={offer} busy={accept.isPending || decline.isPending || counter.isPending} onAccept={() => accept.mutate(offer)} onDecline={() => decline.mutate(offer)} onCounter={(extra) => counter.mutate({ o: offer, extra })} />
      ) : (
        <Sheet>
          {!trip && <InductionDueCard />}
          {!trip && <AnnouncementCard />}
          {!trip && !online && <NpsCard />}
          <DriverTours pos={pos} tripId={trip?.id} />
          {!trip && (
            <>
              <BreakCard />
              {online && <AirportQueueChip />}
              <EvCard />
              {online && <HotZones />}
              {blocked && (
                <div className="mb-3 flex gap-2 rounded-2xl bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-400/10 dark:text-amber-200">
                  <AlertTriangle className="size-4 shrink-0" />
                  <div>
                    <div className="font-semibold">{t("You can't go online yet")}</div>
                    <ul className="mt-1 list-disc pl-4">
                      {driver.compliance_problems.map((p) => (
                        <li key={p}>{p}</li>
                      ))}
                    </ul>
                    <Link to="/drive/documents" className="mt-1 inline-block font-semibold underline">
                      {t("Fix in Documents")}
                    </Link>
                  </div>
                </div>
              )}
              <div className="flex items-center gap-3">
                <div className="flex-1">
                  <div className="text-lg font-bold">{t(online ? "You're online" : "You're offline")}</div>
                  <div className="text-sm text-muted">{t(online ? "Finding trips near you" : "Go online to start earning")}</div>
                </div>
                <button
                  onClick={() => toggle.mutate()}
                  disabled={toggle.isPending || (!online && blocked)}
                  className={clsx(
                    "flex size-16 items-center justify-center rounded-full text-white shadow-lg transition active:scale-95 disabled:opacity-50",
                    online ? "bg-danger" : "bg-brand",
                  )}
                  aria-label={online ? "Go offline" : "Go online"}
                >
                  <Power className="size-7" />
                </button>
              </div>
              {online && (
                <div className="mt-4 flex items-center gap-2 text-xs text-muted">
                  <span className="relative flex size-2.5">
                    <span className="absolute inline-flex size-full animate-ping rounded-full bg-brand opacity-75" />
                    <span className="relative inline-flex size-2.5 rounded-full bg-brand" />
                  </span>
                  Acceptance {Number(driver.acceptance_rate).toFixed(0)}% · Safety score {driver.safety_score ?? "—"}
                </div>
              )}
            </>
          )}

          {trip && (
            <>
              <div className="flex items-center gap-3">
                <Avatar name={trip.rider.name} size={46} />
                <div className="min-w-0 flex-1">
                  <div className="font-semibold">{trip.rider.name}</div>
                  <div className="text-xs text-muted">
                    <Stars value={trip.rider.rating} size={10} /> · {trip.ride_type_name} · {trip.payment_method === "CASH" ? "collect cash" : trip.payment_method.toLowerCase()}
                  </div>
                  {trip.preferences.length > 0 && <PreferenceChips values={trip.preferences} />}
                </div>
                <TripChat tripId={trip.id} me="DRIVER" otherName={trip.rider.name} canSend compact />
                {!trip.preferences.includes("HEARING") && <CallButton tripId={trip.id} name={trip.rider.name} compact />}
              </div>

              <div className="mt-4 flex gap-3 rounded-2xl bg-surface-2 p-3 text-sm">
                <MapPin className={clsx("mt-0.5 size-4 shrink-0", trip.status === "IN_PROGRESS" ? "text-fg" : "text-brand")} />
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-semibold text-muted uppercase">{t(trip.status === "IN_PROGRESS" ? "Drop" : "Pickup")}</div>
                  <div className="truncate font-semibold">{trip.status === "IN_PROGRESS" ? trip.dropoff_address : trip.pickup_address}</div>
                  {trip.stop && <div className="truncate text-xs text-muted">Stop on the way: {trip.stop.address || "marked on the map"}</div>}
                  {trip.status === "DRIVER_ASSIGNED" && <div className="text-xs text-muted">{km(distanceToPickup)} away</div>}
                  {trip.status === "IN_PROGRESS" && (
                    <div className="text-xs text-muted">
                      {km(distanceToDrop)} · {minutes(etaFromKm(distanceToDrop))} · drop by {clockIn(etaFromKm(distanceToDrop))}
                    </div>
                  )}
                </div>
                <a
                  target="_blank"
                  rel="noreferrer"
                  href={`https://www.google.com/maps/dir/?api=1&destination=${trip.status === "IN_PROGRESS" ? `${trip.dropoff_lat},${trip.dropoff_lng}` : `${trip.pickup_lat},${trip.pickup_lng}`}`}
                  className="flex size-9 items-center justify-center rounded-full bg-info text-white"
                  aria-label="Navigate"
                >
                  <Navigation className="size-4" />
                </a>
              </div>

              <NightSafeBar trip={trip} role="driver" />
              <PoolBadge trip={trip} role="driver" />
              <TripRecorder trip={trip} />
              <div className="mt-4 space-y-2">
                {trip.status === "DRIVER_ASSIGNED" && (
                  <>
                    <Button block size="lg" variant="brand" onClick={() => arrive.mutate()} loading={arrive.isPending}>
                      {t("I've arrived")}
                    </Button>
                    {distanceToPickup > 0.5 && <p className="text-center text-xs text-muted">Get within 500 m of the pickup (tap the map or use autopilot).</p>}
                    <Button block variant="ghost" onClick={() => cancel.mutate()} loading={cancel.isPending}>
                      {t("Cancel trip")}
                    </Button>
                  </>
                )}
                {trip.status === "DRIVER_ARRIVED" && (
                  <>
                    <PinEntry onSubmit={(pin) => start.mutate({ otp: pin })} onScan={(code) => start.mutate({ qr: code })} busy={start.isPending} />
                    <Button block variant="ghost" onClick={() => cancel.mutate()} loading={cancel.isPending}>
                      {t("Rider didn't show up")}
                    </Button>
                  </>
                )}
                {trip.status === "IN_PROGRESS" && (
                  <>
                    {trip.payment_method === "CASH" && (
                      <div className="flex items-center gap-2 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-400/10 dark:text-amber-200">
                        <Banknote className="size-4" /> Collect about {inr(trip.estimated_fare)} in cash at drop-off
                      </div>
                    )}
                    {trip.service === "PARCEL" && trip.parcel && (
                      <div className="rounded-2xl bg-surface-2 p-3 text-sm">
                        <div className="flex items-center gap-2 font-semibold">
                          <Package className="size-4" /> {t("Deliver to {name}", { name: trip.parcel.recipient_name })}
                          {trip.parcel.recipient_phone && (
                            <a href={`tel:${trip.parcel.recipient_phone}`} className="ml-auto text-xs font-semibold text-info">
                              {trip.parcel.recipient_phone}
                            </a>
                          )}
                        </div>
                        {trip.parcel.instructions && <div className="mt-0.5 text-xs text-muted">“{trip.parcel.instructions}”</div>}
                        <label className="label mt-2">{t("Delivery code from the recipient")}</label>
                        <Input
                          inputMode="numeric"
                          maxLength={4}
                          value={deliveryCode}
                          onChange={(e) => setDeliveryCode(e.target.value.replace(/\D/g, "").slice(0, 4))}
                          placeholder="• • • •"
                          className="text-center font-mono text-xl font-bold tracking-[0.5em]"
                        />
                      </div>
                    )}
                    <Button
                      block
                      size="lg"
                      variant="primary"
                      onClick={() => complete.mutate()}
                      loading={complete.isPending}
                      disabled={trip.service === "PARCEL" && deliveryCode.length !== 4}
                    >
                      {t(trip.service === "PARCEL" ? "Mark delivered" : "Complete trip")}
                    </Button>
                  </>
                )}
              </div>
              {trip.flags.includes("SOS") && (
                <p className="mt-2 flex items-center gap-1 text-xs font-semibold text-danger">
                  <ShieldAlert className="size-3.5" /> The safety team is monitoring this trip
                </p>
              )}
            </>
          )}
        </Sheet>
      )}

      <Modal
        open={!!completed}
        onClose={() => setCompleted(null)}
        title={t("Trip complete")}
        footer={
          <Button block onClick={() => rateRider.mutate()} loading={rateRider.isPending}>
            {t("Rate rider & continue")}
          </Button>
        }
      >
        {completed && (
          <div className="text-center">
            <div className="text-xs font-semibold text-muted uppercase">{t("You earned")}</div>
            <div className="text-4xl font-bold tracking-tight text-brand-strong">{inr(completed.driver_earning)}</div>
            <div className="mt-1 text-sm text-muted">
              Fare {inr(completed.fare_total)} · {km(completed.actual_distance_km)} · {minutes(completed.actual_duration_min)}
            </div>
            {completed.payment_method === "CASH" && <p className="mt-3 rounded-xl bg-surface-2 p-2 text-sm">Collect {inr(completed.fare_total)} in cash from the rider.</p>}
            <p className="mt-5 mb-2 text-sm font-semibold">Rate {completed.rider.name.split(" ")[0]}</p>
            <StarInput value={riderStars} onChange={setRiderStars} />
          </div>
        )}
      </Modal>
    </div>
  );
}
