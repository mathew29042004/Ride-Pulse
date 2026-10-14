import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import {
  ArrowLeft,
  Banknote,
  ChevronDown,
  ChevronUp,
  Clock,
  CreditCard,
  Crosshair,
  HandCoins,
  MapPin,
  Plus,
  Smartphone,
  Tag,
  Users,
  Wallet as WalletIcon,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { toast } from "sonner";

import { BaseMap, FitBounds, MapCenterWatch, PinMarker, Recenter, RouteLine, useMapProvider } from "@/components/map";
import { describePoint, PlaceSuggestions } from "@/components/PlaceSuggestions";
import { RideTypeArt } from "@/components/RideTypeArt";
import { earliestSlot, formatWhen, SchedulePicker } from "@/components/SchedulePicker";
import { Badge, Button, Input, Sheet } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { inr, km, minutes } from "@/lib/format";
import { useWallet } from "@/lib/hooks";
import { useLayout } from "@/lib/layout";
import type { Estimate, PaymentMethod, SavedPlace, Trip } from "@/lib/types";

import { useRiderLocation } from "./RiderHome";

interface Spot {
  lat: number;
  lng: number;
  name: string;
}

const PAYMENT: { value: PaymentMethod; label: string; icon: typeof Banknote }[] = [
  { value: "UPI", label: "UPI", icon: Smartphone },
  { value: "CASH", label: "Cash", icon: Banknote },
  { value: "CARD", label: "Card", icon: CreditCard },
  { value: "WALLET", label: "Wallet", icon: WalletIcon },
];

function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export default function RiderBook() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const [home] = useRiderLocation();
  const [pickup, setPickup] = useState<Spot>({ lat: home.lat, lng: home.lng, name: home.name });
  const [dropoff, setDropoff] = useState<Spot | null>(() => {
    const to = params.get("to");
    if (!to) return null;
    const [lat, lng] = to.split(",").map(Number);
    return { lat, lng, name: params.get("name") ?? "Destination" };
  });
  type Field = "pickup" | "stop" | "dropoff";
  const [editing, setEditing] = useState<Field>("dropoff");
  // One optional stop on the way.
  const [stop, setStop] = useState<Spot | null>(null);
  const [showStop, setShowStop] = useState(false);
  const fieldLabel = { pickup: "pickup", stop: "stop", dropoff: "drop" }[editing];
  const [query, setQuery] = useState("");
  const [pickOnMap, setPickOnMap] = useState(false);
  // "Move the map to set the pin": the pin stays in the middle and the map moves under it.
  const [pickStart, setPickStart] = useState<[number, number]>([0, 0]);
  const [candidate, setCandidate] = useState<Spot | null>(null);
  const [moving, setMoving] = useState(false);
  const [selected, setSelected] = useState<string>("MINI");
  const [payment, setPayment] = useState<PaymentMethod>("UPI");
  const [promoInput, setPromoInput] = useState("");
  const [tip, setTip] = useState(0); // promised at booking, paid with the fare, 100% to the driver
  const [promo, setPromo] = useState("");
  const [showFare, setShowFare] = useState(false);
  // Book now, or schedule for later (opened straight from Home's "Later" button).
  const [scheduleAt, setScheduleAt] = useState<Date | null>(() => (params.get("later") ? earliestSlot() : null));
  const [pickingTime, setPickingTime] = useState(() => !!params.get("later"));
  const wallet = useWallet();
  const { provider: mapProvider } = useMapProvider();
  const desktop = useLayout().mode === "desktop";
  const search = useDebounced(query);

  const saved = useQuery({ queryKey: ["places", "saved"], queryFn: () => api.get<SavedPlace[]>("rider/places/") });

  const estimate = useQuery({
    queryKey: ["estimate", pickup.lat, pickup.lng, dropoff?.lat, dropoff?.lng, stop?.lat, stop?.lng, promo],
    queryFn: () =>
      api.post<Estimate>("fares/estimate/", {
        pickup: { lat: pickup.lat, lng: pickup.lng },
        dropoff: { lat: dropoff!.lat, lng: dropoff!.lng },
        stop: stop && { lat: stop.lat, lng: stop.lng },
        promo_code: promo,
      }),
    enabled: !!dropoff,
    retry: false,
    refetchInterval: 30_000,
  });

  useEffect(() => {
    if (!estimate.data) return;
    if (promo && estimate.data.promo_error) toast.error(estimate.data.promo_error);
    if (!estimate.data.options.some((o) => o.ride_type.code === selected) && estimate.data.options[0]) {
      setSelected(estimate.data.options[0].ride_type.code);
    }
  }, [estimate.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const schedule = useMutation({
    mutationFn: () =>
      api.post("scheduled-rides/", {
        ride_type: selected,
        pickup: { lat: pickup.lat, lng: pickup.lng, address: pickup.name },
        dropoff: { lat: dropoff!.lat, lng: dropoff!.lng, address: dropoff!.name },
        stop: stop && { lat: stop.lat, lng: stop.lng, address: stop.name },
        payment_method: payment,
        promo_code: promo,
        scheduled_for: scheduleAt!.toISOString(),
      }),
    onSuccess: () => {
      toast.success(`Ride scheduled for ${formatWhen(scheduleAt!)}. We'll find your driver a few minutes before.`);
      qc.invalidateQueries({ queryKey: ["scheduled-rides"] });
      navigate("/ride/activity", { replace: true });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't schedule the ride."),
  });

  const book = useMutation({
    mutationFn: () =>
      api.post<Trip>("trips/", {
        ride_type: selected,
        pickup: { lat: pickup.lat, lng: pickup.lng, address: pickup.name },
        dropoff: { lat: dropoff!.lat, lng: dropoff!.lng, address: dropoff!.name },
        stop: stop && { lat: stop.lat, lng: stop.lng, address: stop.name },
        payment_method: payment,
        promo_code: promo,
        tip,
      }),
    onSuccess: (trip) => {
      qc.invalidateQueries({ queryKey: ["trips"] });
      navigate(`/ride/trips/${trip.id}`, { replace: true });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't book the ride."),
  });

  function startPicking() {
    const from = (editing === "dropoff" && dropoff) || (editing === "stop" && (stop ?? dropoff)) || pickup;
    setPickStart([from.lat, from.lng]);
    setCandidate(null);
    setPickOnMap(true);
  }

  // Name the spot under the pin once the map stops moving (ignoring answers that arrive late).
  const candidateKey = candidate ? `${candidate.lat.toFixed(5)},${candidate.lng.toFixed(5)}` : "";
  useEffect(() => {
    if (!candidate || candidate.name) return;
    let stale = false;
    const t = setTimeout(async () => {
      const name = await describePoint(candidate.lat, candidate.lng, mapProvider);
      if (!stale) setCandidate((c) => (c && c.lat === candidate.lat && c.lng === candidate.lng ? { ...c, name } : c));
    }, 250);
    return () => {
      stale = true;
      clearTimeout(t);
    };
  }, [candidateKey]); // eslint-disable-line react-hooks/exhaustive-deps

  function confirmPick() {
    if (!candidate?.name) return;
    fill(candidate);
    setPickOnMap(false);
    setQuery("");
  }

  function choose(place: { lat: number; lng: number; name: string }) {
    fill({ lat: place.lat, lng: place.lng, name: place.name });
    setQuery("");
  }

  /** Put a chosen spot into the field being edited, then move on to the drop. */
  function fill(spot: Spot) {
    if (editing === "pickup") setPickup(spot);
    else if (editing === "stop") setStop(spot);
    else setDropoff(spot);
    setEditing("dropoff");
  }

  function removeStop() {
    setStop(null);
    setShowStop(false);
    if (editing === "stop") setEditing("dropoff");
  }

  const option = estimate.data?.options.find((o) => o.ride_type.code === selected);
  const choosing = !!dropoff && !pickOnMap && editing === "dropoff" && !query;
  const points = useMemo(
    () =>
      [[pickup.lat, pickup.lng], ...(stop ? [[stop.lat, stop.lng]] : []), ...(dropoff ? [[dropoff.lat, dropoff.lng]] : [])] as [number, number][],
    [pickup, dropoff, stop],
  );

  // Pickup / stop / drop fields: floating over the map on a phone, at the top of the side panel
  // on desktop (like Uber's website).
  const locationInputs = (
      <div className={desktop ? "-mx-1 mb-4 rounded-2xl bg-surface-2 p-3" : "relative z-[600] m-3 rounded-2xl bg-surface p-3 shadow-[var(--shadow-float)]"}>
        <div className="flex items-start gap-2">
          <Link to="/ride" className="mt-1 rounded-full p-1.5 hover:bg-surface-3" aria-label="Back">
            <ArrowLeft className="size-5" />
          </Link>
          <div className="relative flex-1 space-y-2">
            <div className="absolute top-[22px] bottom-[22px] left-[13px] w-0.5 bg-line" />
            {(["pickup", ...(showStop ? ["stop"] : []), "dropoff"] as Field[]).map((field) => {
              const value = field === "pickup" ? pickup.name : field === "stop" ? (stop?.name ?? "") : (dropoff?.name ?? "");
              const isEditing = editing === field;
              const placeholder = field === "pickup" ? "Pickup location" : field === "stop" ? "Add a stop" : "Where to?";
              return (
                <div key={field} className="flex items-center gap-3">
                  <span
                    className={clsx(
                      "relative z-10 ml-2 size-3 shrink-0",
                      field === "pickup" ? "rounded-full bg-brand" : field === "stop" ? "ml-[9px] size-2.5 rounded-full bg-slate-500" : "bg-ink",
                    )}
                  />
                  {isEditing ? (
                    <Input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder={value || placeholder} className="!py-2" />
                  ) : (
                    <button
                      onClick={() => {
                        setEditing(field);
                        setQuery("");
                      }}
                      className="w-full truncate rounded-xl bg-surface-2 px-3.5 py-2 text-left text-sm"
                    >
                      {value || <span className="text-muted">{placeholder}</span>}
                    </button>
                  )}
                  {field === "stop" && (
                    <button onClick={removeStop} className="shrink-0 rounded-full p-1 text-muted hover:bg-surface-3" aria-label="Remove stop">
                      <X className="size-4" />
                    </button>
                  )}
                </div>
              );
            })}
            {dropoff && !showStop && (
              <button
                onClick={() => {
                  setShowStop(true);
                  setEditing("stop");
                  setQuery("");
                }}
                className="ml-8 flex items-center gap-1 text-xs font-semibold text-brand-strong"
              >
                <Plus className="size-3.5" /> Add a stop
              </button>
            )}
          </div>
        </div>
      </div>
  );

  return (
    <div className="relative flex h-full flex-col">
      <div className="absolute inset-0">
        <BaseMap center={[pickup.lat, pickup.lng]} zoom={14}>
          {!pickOnMap && <FitBounds points={points} padding={50} bottom={380} />}
          {!(pickOnMap && editing === "pickup") && <PinMarker lat={pickup.lat} lng={pickup.lng} kind="pickup" label={dropoff && !pickOnMap ? "Pickup" : undefined} />}
          {dropoff && !(pickOnMap && editing === "dropoff") && (
            <PinMarker lat={dropoff.lat} lng={dropoff.lng} kind="dropoff" label={option && !pickOnMap ? minutes(option.duration_minutes) : undefined} />
          )}
          {stop && !(pickOnMap && editing === "stop") && <PinMarker lat={stop.lat} lng={stop.lng} kind="stop" />}
          {dropoff && !pickOnMap && (
            <RouteLine from={[pickup.lat, pickup.lng]} to={[dropoff.lat, dropoff.lng]} encoded={option?.route_polyline} via={stop && [stop.lat, stop.lng]} />
          )}
          {pickOnMap && (
            <>
              <Recenter center={pickStart} zoom={16} />
              <MapCenterWatch
                onMoveStart={() => setMoving(true)}
                onMoveEnd={(lat, lng) => {
                  setMoving(false);
                  setCandidate({ lat, lng, name: "" });
                }}
              />
            </>
          )}
        </BaseMap>
      </div>

      {!desktop && locationInputs}

      <div className="flex-1" />

      {pickOnMap && (
        <>
          {/* The pin: its tip marks the map's centre. It lifts while the map moves. */}
          <div className="pointer-events-none absolute inset-0 z-[550] flex items-center justify-center">
            <div className="relative">
              <span className="absolute top-0 left-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-black/30 blur-[1px]" />
              <div className={clsx("absolute bottom-0 left-1/2 flex -translate-x-1/2 flex-col items-center transition-transform duration-200", moving && "-translate-y-3")}>
                <span className={clsx("flex size-9 items-center justify-center rounded-full border-4 border-white shadow-lg", editing === "pickup" ? "bg-brand" : editing === "stop" ? "bg-slate-500" : "bg-ink")}>
                  <span className="size-2.5 rounded-full bg-white" />
                </span>
                <span className="h-4 w-1 rounded-b bg-ink" />
              </div>
            </div>
          </div>
          <div className="rp-overlay relative z-[600] m-3 rounded-3xl bg-surface p-4 shadow-[var(--shadow-float)]">
            <div className="text-xs font-semibold tracking-wide text-muted uppercase">Set {fieldLabel}</div>
            <div className="mt-1 flex min-h-12 items-center gap-2">
              <MapPin className={clsx("size-5 shrink-0", editing === "pickup" ? "text-brand" : "text-fg")} />
              <div className="min-w-0 flex-1 font-semibold">
                {moving || !candidate?.name ? <span className="inline-block h-4 w-40 animate-pulse rounded bg-surface-3 align-middle" /> : <span className="line-clamp-2">{candidate.name}</span>}
              </div>
            </div>
            <p className="mb-3 text-xs text-muted">Move the map to put the pin exactly where you are.</p>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setPickOnMap(false)}>
                Cancel
              </Button>
              <Button className="flex-1" size="lg" disabled={moving || !candidate?.name} onClick={confirmPick}>
                Confirm {fieldLabel}
              </Button>
            </div>
          </div>
        </>
      )}

      {!choosing && !pickOnMap && (
        <Sheet height="60%">
          {desktop && locationInputs}
          <button onClick={startPicking} className="flex w-full items-center gap-3 py-2.5 text-left">
            <span className="flex size-9 items-center justify-center rounded-full bg-surface-3">
              <Crosshair className="size-4" />
            </span>
            <span className="font-semibold">Set {fieldLabel} on map</span>
          </button>
          {query.length < 2 &&
            (saved.data ?? []).map((p) => (
              <button key={p.id} onClick={() => choose(p)} className="flex w-full items-center gap-3 py-2.5 text-left">
                <span className="flex size-9 items-center justify-center rounded-full bg-surface-3">
                  <MapPin className="size-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold">{p.label === "OTHER" ? p.name : p.label === "HOME" ? "Home" : "Work"}</span>
                  <span className="block truncate text-xs text-muted">{p.address || p.name}</span>
                </span>
              </button>
            ))}
          <PlaceSuggestions query={search} near={{ lat: pickup.lat, lng: pickup.lng }} onPick={choose} />
        </Sheet>
      )}

      {choosing && (
        <Sheet
          height="66%"
          footer={
            estimate.data &&
            (scheduleAt ? (
              <Button size="lg" block loading={schedule.isPending} disabled={!option} onClick={() => schedule.mutate()}>
                Schedule {option?.ride_type.name} · {formatWhen(scheduleAt)}
              </Button>
            ) : (
              <Button size="lg" block loading={book.isPending} disabled={!option} onClick={() => book.mutate()}>
                Book {option?.ride_type.name} · {inr(option?.fare.total)}
                {tip > 0 && ` + ₹${tip} tip`}
              </Button>
            ))
          }
        >
          {desktop && locationInputs}
          {estimate.isLoading && (
            <div className="space-y-3 py-2">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-16 animate-pulse rounded-2xl bg-surface-3" />
              ))}
            </div>
          )}
          {estimate.error && <p className="py-6 text-center text-sm text-danger">{(estimate.error as Error).message}</p>}
          {estimate.data && (
            <>
              <div className="mb-2 flex items-center justify-between gap-2">
                <h2 className="font-semibold">Choose a ride</h2>
                <button
                  onClick={() => setPickingTime((v) => !v)}
                  className="ml-auto flex items-center gap-1 rounded-full bg-surface-3 px-3 py-1 text-xs font-semibold"
                  aria-expanded={pickingTime}
                >
                  <Clock className="size-3.5" /> {scheduleAt ? formatWhen(scheduleAt) : "Now"}
                  <ChevronDown className="size-3.5" />
                </button>
                {option && Number(option.fare.surge_multiplier) > 1 && (
                  <Badge tone="warning">
                    <Zap className="size-3" /> {option.fare.surge_multiplier}× high demand
                  </Badge>
                )}
              </div>
              {pickingTime && (
                <div className="mb-3 rounded-2xl bg-surface-2 p-3">
                  <SchedulePicker value={scheduleAt} onChange={setScheduleAt} />
                  {scheduleAt && <p className="mt-2 text-xs text-muted">Fares shown are for now; the fare is confirmed when your driver is found, a few minutes before pickup.</p>}
                </div>
              )}
              <div className="space-y-1.5">
                {estimate.data.options.map((o) => {
                  const active = o.ride_type.code === selected;
                  return (
                    <button
                      key={o.ride_type.code}
                      onClick={() => setSelected(o.ride_type.code)}
                      className={clsx(
                        "flex w-full items-center gap-3 rounded-2xl border-2 px-3 py-2.5 text-left transition",
                        active ? "border-fg bg-surface-2" : "border-transparent hover:bg-surface-2",
                      )}
                    >
                      <RideTypeArt code={o.ride_type.code} className="h-9 w-16 shrink-0" />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5 font-semibold">
                          {o.ride_type.name}
                          <span className="flex items-center gap-0.5 text-xs font-medium text-muted">
                            <Users className="size-3" />
                            {o.ride_type.seats}
                          </span>
                        </div>
                        <div className="text-xs text-muted">
                          {o.pickup_eta_min !== null ? `${o.pickup_eta_min} min away` : "No cars nearby"} · {km(o.distance_km)}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="font-bold">{inr(o.fare.total)}</div>
                        {Number(o.fare.discount) > 0 && <div className="text-xs text-muted line-through">{inr(Number(o.fare.total) + Number(o.fare.discount) * 1.05)}</div>}
                      </div>
                    </button>
                  );
                })}
              </div>

              {option && (
                <button onClick={() => setShowFare((s) => !s)} className="mt-2 flex w-full items-center justify-center gap-1 text-xs font-medium text-muted">
                  Fare breakdown {showFare ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
                </button>
              )}
              {option && showFare && (
                <div className="mt-2 space-y-1 rounded-2xl bg-surface-2 p-3 text-xs">
                  {option.fare.lines.map((line) => (
                    <div key={line.code} className="flex justify-between">
                      <span className="text-muted">{line.label}</span>
                      <span className={clsx("font-medium", line.kind === "DISCOUNT" && "text-brand-strong")}>{inr(line.amount)}</span>
                    </div>
                  ))}
                  <div className="flex justify-between border-t border-line pt-1 font-semibold">
                    <span>Total (upfront)</span>
                    <span>{inr(option.fare.total)}</span>
                  </div>
                </div>
              )}

              <div className="mt-3">
                <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-muted">
                  <HandCoins className="size-3.5" /> Tip your driver <span className="font-normal">(optional, 100% to them)</span>
                </div>
                <div className="grid grid-cols-4 gap-1.5">
                  {[0, 10, 20, 30].map((amount) => (
                    <button
                      key={amount}
                      onClick={() => setTip(amount)}
                      className={clsx(
                        "rounded-xl border py-1.5 text-xs font-semibold transition",
                        tip === amount ? "border-fg bg-surface-2" : "border-line text-muted",
                      )}
                    >
                      {amount ? `₹${amount}` : "No tip"}
                    </button>
                  ))}
                </div>
              </div>

              <div className="mt-3 grid grid-cols-4 gap-1.5">
                {PAYMENT.map(({ value, label, icon: Icon }) => (
                  <button
                    key={value}
                    onClick={() => setPayment(value)}
                    className={clsx(
                      "flex flex-col items-center gap-1 rounded-xl border py-2 text-xs font-semibold transition",
                      payment === value ? "border-fg bg-surface-2" : "border-line text-muted",
                    )}
                  >
                    <Icon className="size-4" />
                    {label}
                  </button>
                ))}
              </div>
              {payment === "WALLET" && wallet.data && <p className="mt-1.5 text-center text-xs text-muted">Wallet balance {inr(wallet.data.balance)}</p>}

              <div className="mt-3 flex gap-2">
                <div className="relative flex-1">
                  <Tag className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
                  <Input value={promoInput} onChange={(e) => setPromoInput(e.target.value.toUpperCase())} placeholder="Promo code" className="!py-2 pl-9" />
                </div>
                <Button variant="secondary" onClick={() => setPromo(promoInput.trim())} disabled={!promoInput.trim()}>
                  Apply
                </Button>
              </div>
            </>
          )}
        </Sheet>
      )}
    </div>
  );
}
