import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Banknote,
  BellRing,
  ChevronDown,
  ChevronUp,
  Clock,
  CreditCard,
  Crosshair,
  HandCoins,
  MapPin,
  Plus,
  ShieldCheck,
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
import { EMPTY_PARCEL, ParcelForm, parcelReady, type ParcelDetails } from "@/components/ParcelForm";
import { BillTo } from "@/components/Profiles";
import { describePoint, PlaceSuggestions } from "@/components/PlaceSuggestions";
import { RideTypeArt } from "@/components/RideTypeArt";
import { earliestSlot, formatWhen, SchedulePicker } from "@/components/SchedulePicker";
import { Badge, Button, Input, Sheet, Toggle } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { inr, km, minutes } from "@/lib/format";
import { useWallet } from "@/lib/hooks";
import { useLayout } from "@/lib/layout";
import { isCar, PREFERENCES } from "@/lib/preferences";
import { t } from "@/lib/i18n";
import type { Estimate, EstimateOption, PaymentMethod, Rider, SavedPlace, Trip } from "@/lib/types";

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
  // "stop0".."stop2": up to three stops on the way, in order.
  type Field = "pickup" | "dropoff" | `stop${number}`;
  const [editing, setEditing] = useState<Field>("dropoff");
  const [stopSlots, setStopSlots] = useState<(Spot | null)[]>([]);
  const stops = stopSlots.filter((s): s is Spot => !!s);
  const stopIndex = (field: Field) => (field.startsWith("stop") ? Number(field.slice(4)) : -1);
  const editingStop = stopIndex(editing);
  const fieldLabel = editingStop >= 0 ? t("stop") : t({ pickup: "pickup", dropoff: "drop" }[editing as "pickup" | "dropoff"]);
  const stopsBody = (withAddress: boolean) =>
    stops.length ? stops.map((s) => ({ lat: s.lat, lng: s.lng, ...(withAddress ? { address: s.name } : {}) })) : undefined;
  const [query, setQuery] = useState("");
  const [pickOnMap, setPickOnMap] = useState(false);
  // "Move the map to set the pin": the pin stays in the middle and the map moves under it.
  const [pickStart, setPickStart] = useState<[number, number]>([0, 0]);
  const [candidate, setCandidate] = useState<Spot | null>(null);
  const [moving, setMoving] = useState(false);
  const [selected, setSelected] = useState<string>(() => params.get("type") ?? "MINI");
  const service = params.get("service") === "PARCEL" ? "PARCEL" : "RIDE";
  const [parcel, setParcel] = useState<ParcelDetails>(EMPTY_PARCEL);
  const [boost, setBoost] = useState(0); // "search anyway" boost when nobody's nearby
  const [bidding, setBidding] = useState(false); // Bid your fare
  const [bid, setBid] = useState(0);
  const [sureRide, setSureRide] = useState(false);
  const [billTo, setBillTo] = useState<number | null>(null); // family / business profile
  const [purpose, setPurpose] = useState("");
  const [costCenter, setCostCenter] = useState("");
  const [payment, setPayment] = useState<PaymentMethod>("UPI");
  const [promoInput, setPromoInput] = useState("");
  const [tip, setTip] = useState(0); // promised at booking, paid with the fare, 100% to the driver
  // Ride preferences: pre-selected from the rider's saved defaults, changeable per ride.
  const me = useQuery({ queryKey: ["rider", "me"], queryFn: () => api.get<Rider>("rider/me/") });
  const [prefs, setPrefs] = useState<string[] | null>(null);
  const chosenPrefs = prefs ?? me.data?.default_preferences ?? [];
  const togglePref = (value: string) => setPrefs(chosenPrefs.includes(value) ? chosenPrefs.filter((p) => p !== value) : [...chosenPrefs, value]);
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
    queryKey: ["estimate", service, pickup.lat, pickup.lng, dropoff?.lat, dropoff?.lng, stops.map((s) => `${s.lat},${s.lng}`).join("|"), promo],
    queryFn: () =>
      api.post<Estimate>("fares/estimate/", {
        pickup: { lat: pickup.lat, lng: pickup.lng },
        dropoff: { lat: dropoff!.lat, lng: dropoff!.lng },
        stops: stopsBody(false),
        promo_code: promo,
        service,
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

  // "Tell me when prices drop": watch this route while surge pricing is on.
  const [watching, setWatching] = useState<string | null>(null);
  const watchPrice = useMutation({
    mutationFn: () =>
      api.post("price-alerts/", {
        ride_type: selected,
        pickup: { lat: pickup.lat, lng: pickup.lng, address: pickup.name },
        dropoff: { lat: dropoff!.lat, lng: dropoff!.lng, address: dropoff!.name },
      }),
    onSuccess: () => {
      setWatching(selected);
      toast.success(t("We'll notify you when prices drop on this route."));
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t("Couldn't set the alert.")),
  });

  const schedule = useMutation({
    mutationFn: () =>
      api.post("scheduled-rides/", {
        ride_type: selected,
        pickup: { lat: pickup.lat, lng: pickup.lng, address: pickup.name },
        dropoff: { lat: dropoff!.lat, lng: dropoff!.lng, address: dropoff!.name },
        stops: stopsBody(true),
        payment_method: payment,
        promo_code: promo,
        scheduled_for: scheduleAt!.toISOString(),
      }),
    onSuccess: () => {
      toast.success(t("Ride scheduled for {when}. We'll find your driver a few minutes before.", { when: formatWhen(scheduleAt!) }));
      qc.invalidateQueries({ queryKey: ["scheduled-rides"] });
      navigate("/ride/activity", { replace: true });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t("Couldn't schedule the ride.")),
  });

  const book = useMutation({
    mutationFn: () =>
      api.post<Trip>("trips/", {
        ride_type: selected,
        pickup: { lat: pickup.lat, lng: pickup.lng, address: pickup.name },
        dropoff: { lat: dropoff!.lat, lng: dropoff!.lng, address: dropoff!.name },
        stops: stopsBody(true),
        payment_method: payment,
        promo_code: promo,
        tip,
        parcel: service === "PARCEL" ? parcel : null,
        payment_profile: billTo,
        trip_purpose: purpose,
        cost_center: costCenter || undefined,
        boost: option?.availability === "NONE" && !bidding ? boost : 0,
        fare_offer: bidding && !scheduleAt ? bid : null,
        sure_ride: sureRide && !bidding && !!option?.sure_ride && !scheduleAt,
        preferences: service === "PARCEL" ? [] : chosenPrefs.filter((p) => isCar(selected) || !PREFERENCES.find((x) => x.value === p)?.carsOnly),
      }),
    onSuccess: (trip) => {
      qc.invalidateQueries({ queryKey: ["trips"] });
      navigate(`/ride/trips/${trip.id}`, { replace: true });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t("Couldn't book the ride.")),
  });

  function startPicking() {
    const from = (editing === "dropoff" && dropoff) || (editingStop >= 0 && (stopSlots[editingStop] ?? dropoff)) || pickup;
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
    else if (editingStop >= 0) setStopSlots((slots) => slots.map((s, i) => (i === editingStop ? spot : s)));
    else setDropoff(spot);
    setEditing("dropoff");
  }

  function removeStop(index: number) {
    setStopSlots((slots) => slots.filter((_, i) => i !== index));
    if (editingStop >= 0) setEditing("dropoff");
  }

  function addStop() {
    setStopSlots((slots) => [...slots, null]);
    setEditing(`stop${stopSlots.length}`);
    setQuery("");
  }

  const option = estimate.data?.options.find((o) => o.ride_type.code === selected);
  const bookingTotal = !option
    ? 0
    : bidding && !scheduleAt
      ? bid
      : Number(option.fare.total) + (option.availability === "NONE" ? boost : 0) + (sureRide && option.sure_ride && !scheduleAt ? Number(option.sure_ride.fee) : 0);
  const choosing = !!dropoff && !pickOnMap && editing === "dropoff" && !query;
  const points = useMemo(
    () =>
      [[pickup.lat, pickup.lng], ...stops.map((s) => [s.lat, s.lng]), ...(dropoff ? [[dropoff.lat, dropoff.lng]] : [])] as [number, number][],
    [pickup, dropoff, stops],
  );

  // Pickup / stop / drop fields: floating over the map on a phone, at the top of the side panel
  // on desktop (like Uber's website).
  const locationInputs = (
      <div className={desktop ? "-mx-1 mb-4 rounded-2xl bg-surface-2 p-3" : "relative z-[600] m-3 rounded-2xl bg-surface p-3 shadow-[var(--shadow-float)]"}>
        <div className="flex items-start gap-2">
          <Link to="/ride" className="mt-1 rounded-full p-1.5 hover:bg-surface-3" aria-label={t("Back")}>
            <ArrowLeft className="size-5" />
          </Link>
          <div className="relative flex-1 space-y-2">
            <div className="absolute top-[22px] bottom-[22px] left-[13px] w-0.5 bg-line" />
            {(["pickup", ...stopSlots.map((_, i) => `stop${i}`), "dropoff"] as Field[]).map((field) => {
              const slot = stopIndex(field);
              const value = field === "pickup" ? pickup.name : slot >= 0 ? (stopSlots[slot]?.name ?? "") : (dropoff?.name ?? "");
              const isEditing = editing === field;
              const placeholder = slot >= 0 ? t("Stop {n}", { n: slot + 1 }) : (field === "pickup" ? t("Pickup location") : t("Where to?"));
              return (
                <div key={field} className="flex items-center gap-3">
                  <span
                    className={clsx(
                      "relative z-10 ml-2 size-3 shrink-0",
                      field === "pickup" ? "rounded-full bg-brand" : slot >= 0 ? "ml-[9px] size-2.5 rounded-full bg-slate-500" : "bg-ink",
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
                  {slot >= 0 && (
                    <button onClick={() => removeStop(slot)} className="shrink-0 rounded-full p-1 text-muted hover:bg-surface-3" aria-label={t("Remove stop {n}", { n: slot + 1 })}>
                      <X className="size-4" />
                    </button>
                  )}
                </div>
              );
            })}
            {dropoff && stopSlots.length < 3 && stopSlots.every(Boolean) && service === "RIDE" && (
              <button onClick={addStop} className="ml-8 flex items-center gap-1 text-xs font-semibold text-brand-strong">
                <Plus className="size-3.5" /> {stopSlots.length ? t("Add another stop") : t("Add a stop")}
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
          {!(pickOnMap && editing === "pickup") && <PinMarker lat={pickup.lat} lng={pickup.lng} kind="pickup" label={dropoff && !pickOnMap ? t("Pickup") : undefined} />}
          {dropoff && !(pickOnMap && editing === "dropoff") && (
            <PinMarker lat={dropoff.lat} lng={dropoff.lng} kind="dropoff" label={option && !pickOnMap ? minutes(option.duration_minutes) : undefined} />
          )}
          {stopSlots.map((s, i) => s && !(pickOnMap && editingStop === i) && <PinMarker key={i} lat={s.lat} lng={s.lng} kind="stop" label={stopSlots.length > 1 ? String(i + 1) : undefined} />)}
          {dropoff && !pickOnMap && (
            <RouteLine from={[pickup.lat, pickup.lng]} to={[dropoff.lat, dropoff.lng]} encoded={option?.route_polyline} via={stops.map((s) => [s.lat, s.lng] as [number, number])} />
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
                <span className={clsx("flex size-9 items-center justify-center rounded-full border-4 border-white shadow-lg", editing === "pickup" ? "bg-brand" : editingStop >= 0 ? "bg-slate-500" : "bg-ink")}>
                  <span className="size-2.5 rounded-full bg-white" />
                </span>
                <span className="h-4 w-1 rounded-b bg-ink" />
              </div>
            </div>
          </div>
          <div className="rp-overlay relative z-[600] m-3 rounded-3xl bg-surface p-4 shadow-[var(--shadow-float)]">
            <div className="text-xs font-semibold tracking-wide text-muted uppercase">{t("Set {field}", { field: fieldLabel })}</div>
            <div className="mt-1 flex min-h-12 items-center gap-2">
              <MapPin className={clsx("size-5 shrink-0", editing === "pickup" ? "text-brand" : "text-fg")} />
              <div className="min-w-0 flex-1 font-semibold">
                {moving || !candidate?.name ? <span className="inline-block h-4 w-40 animate-pulse rounded bg-surface-3 align-middle" /> : <span className="line-clamp-2">{candidate.name}</span>}
              </div>
            </div>
            <p className="mb-3 text-xs text-muted">{t("Move the map to put the pin exactly where you are.")}</p>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setPickOnMap(false)}>
                {t("Cancel")}
              </Button>
              <Button className="flex-1" size="lg" disabled={moving || !candidate?.name} onClick={confirmPick}>
                {t("Confirm {field}", { field: fieldLabel })}
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
            <span className="font-semibold">{t("Set {field} on map", { field: fieldLabel })}</span>
          </button>
          {query.length < 2 &&
            (saved.data ?? []).map((p) => (
              <button key={p.id} onClick={() => choose(p)} className="flex w-full items-center gap-3 py-2.5 text-left">
                <span className="flex size-9 items-center justify-center rounded-full bg-surface-3">
                  <MapPin className="size-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold">{p.label === "OTHER" ? p.name : (p.label === "HOME" ? t("Home") : t("Work"))}</span>
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
            !!estimate.data?.options.length &&
            (scheduleAt ? (
              <Button size="lg" block loading={schedule.isPending} disabled={!option} onClick={() => schedule.mutate()}>
                {t("Schedule {ride} · {when}", { ride: option?.ride_type.name ?? "", when: formatWhen(scheduleAt) })}
              </Button>
            ) : (
              <Button size="lg" block loading={book.isPending} disabled={!option || option.availability === "CLOSED" || (service === "PARCEL" && !parcelReady(parcel))} onClick={() => book.mutate()}>
                {t("Book {ride} · {fare}", { ride: option?.ride_type.name ?? "", fare: inr(bookingTotal) })}
                {tip > 0 && t(" + ₹{tip} tip", { tip })}
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
          {estimate.data && estimate.data.options.length === 0 && (
            <p className="py-6 text-center text-sm text-muted">{t("No rides are available here right now. Please try again in a little while.")}</p>
          )}
          {estimate.data && estimate.data.options.length > 0 && (
            <>
              <div className="mb-2 flex items-center justify-between gap-2">
                <h2 className="font-semibold">{(service === "PARCEL" ? t("Send a parcel") : t("Choose a ride"))}</h2>
                <button
                  onClick={() => setPickingTime((v) => !v)}
                  className="ml-auto flex items-center gap-1 rounded-full bg-surface-3 px-3 py-1 text-xs font-semibold"
                  aria-expanded={pickingTime}
                >
                  <Clock className="size-3.5" /> {scheduleAt ? formatWhen(scheduleAt) : t("Now")}
                  <ChevronDown className="size-3.5" />
                </button>
                {option?.fare.lines.some((l) => l.code === "RIDE_PASS") && <Badge tone="brand">{t("Ride Pass")}</Badge>}
                {option?.fare_lock && <Badge tone="brand">{t("Fare locked")}</Badge>}
                {option && Number(option.fare.surge_multiplier) > 1 && (
                  <Badge tone="warning">
                    <Zap className="size-3" /> {t("{n}× high demand", { n: option.fare.surge_multiplier })}
                  </Badge>
                )}
              </div>
              {option && Number(option.fare.surge_multiplier) > 1 && !scheduleAt && (
                <button
                  onClick={() => watchPrice.mutate()}
                  disabled={watchPrice.isPending || watching === selected}
                  className="mb-2 flex w-full items-center gap-2 rounded-xl bg-amber-50 px-3 py-2 text-left text-xs font-semibold text-amber-900 disabled:opacity-80 dark:bg-amber-400/10 dark:text-amber-200"
                >
                  <BellRing className="size-4 shrink-0" />
                  {(watching === selected ? t("We'll tell you when prices drop (for the next 2 hours)") : t("Prices are high right now. Tell me when they drop"))}
                </button>
              )}
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
                          {o.ride_type.seats > 0 && (
                            <span className="flex items-center gap-0.5 text-xs font-medium text-muted">
                              <Users className="size-3" />
                              {o.ride_type.seats}
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-muted">
                          {o.availability === "CLOSED" ? t("Not running now") : o.pickup_eta_min !== null ? t("{n} min away", { n: o.pickup_eta_min }) : t("No cars nearby")} · {km(o.distance_km)}
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

              {option && option.availability !== "AVAILABLE" && !scheduleAt && (
                <Unavailable option={option} boost={boost} onBoost={setBoost} onSwitch={(code) => setSelected(code)} />
              )}
              {option && (
                <button onClick={() => setShowFare((s) => !s)} className="mt-2 flex w-full items-center justify-center gap-1 text-xs font-medium text-muted">
                  {t("Fare breakdown")} {showFare ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
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
                    <span>{t("Total (upfront)")}</span>
                    <span>{inr(option.fare.total)}</span>
                  </div>
                </div>
              )}

              {option && option.availability !== "CLOSED" && !scheduleAt && (
                <PriceOptions option={option} bidding={bidding} bid={bid} sureRide={sureRide} onBidding={(on) => { setBidding(on); setBid(Math.round(Number(option.fare.total))); }} onBid={setBid} onSureRide={setSureRide} />
              )}

              {service === "PARCEL" && <ParcelForm value={parcel} onChange={setParcel} />}

              <div className={clsx("mt-3", service === "PARCEL" && "hidden")}>
                <div className="mb-1.5 text-xs font-semibold text-muted">{t("Ride preferences")}</div>
                <div className="flex flex-wrap gap-1.5">
                  {PREFERENCES.filter((p) => isCar(selected) || !p.carsOnly).map(({ value, label, icon: Icon }) => {
                    const on = chosenPrefs.includes(value);
                    return (
                      <button
                        key={value}
                        onClick={() => togglePref(value)}
                        aria-pressed={on}
                        className={clsx("flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition", on ? "border-fg bg-ink text-ink-fg" : "border-line text-muted")}
                      >
                        <Icon className="size-3.5" /> {t(label)}
                      </button>
                    );
                  })}
                </div>
                {chosenPrefs.includes("WOMAN_DRIVER") && <p className="mt-1.5 text-xs text-muted">{t("Women drivers nearby are asked first. If none is free, we'll find you the next best driver.")}</p>}
              </div>

              <div className="mt-3">
                <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-muted">
                  <HandCoins className="size-3.5" /> {t("Tip your driver")} <span className="font-normal">{t("(optional, 100% to them)")}</span>
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
                      {amount ? `₹${amount}` : t("No tip")}
                    </button>
                  ))}
                </div>
              </div>

              <BillTo value={billTo} purpose={purpose} onChange={setBillTo} onPurpose={setPurpose} costCenter={costCenter} onCostCenter={setCostCenter} />
              <div className={clsx("mt-3 grid grid-cols-4 gap-1.5", billTo !== null && "hidden")}>
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
                    {t(label)}
                  </button>
                ))}
              </div>
              {payment === "WALLET" && wallet.data && <p className="mt-1.5 text-center text-xs text-muted">{t("Wallet balance {amount}", { amount: inr(wallet.data.balance) })}</p>}

              <div className="mt-3 flex gap-2">
                <div className="relative flex-1">
                  <Tag className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
                  <Input value={promoInput} onChange={(e) => setPromoInput(e.target.value.toUpperCase())} placeholder={t("Promo code")} className="!py-2 pl-9" />
                </div>
                <Button variant="secondary" onClick={() => setPromo(promoInput.trim())} disabled={!promoInput.trim()}>
                  {t("Apply")}
                </Button>
              </div>
            </>
          )}
        </Sheet>
      )}
    </div>
  );
}

/** "No Bikes near you right now": switch to the suggested ride type, or search anyway with a boost. */
function Unavailable({ option, boost, onBoost, onSwitch }: { option: EstimateOption; boost: number; onBoost: (n: number) => void; onSwitch: (code: string) => void }) {
  const alt = option.suggestion;
  return (
    <div className="mt-2 rounded-2xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-950 dark:border-amber-400/30 dark:bg-amber-400/10 dark:text-amber-100">
      <div className="flex items-center gap-2 font-semibold">
        <AlertTriangle className="size-4 shrink-0" /> {t(option.unavailable_reason)}
      </div>
      {alt && (
        <button onClick={() => onSwitch(alt.ride_type)} className="mt-2 flex w-full items-center justify-between rounded-xl bg-surface px-3 py-2 text-left text-sm font-semibold text-fg">
          <span>
            {t("Switch to {ride}", { ride: alt.name })}
            <span className="block text-xs font-normal text-muted">
              {alt.pickup_eta_min !== null && t("{n} min away", { n: alt.pickup_eta_min })} · {inr(alt.fare_total)}
            </span>
          </span>
          <ArrowRight className="size-4" />
        </button>
      )}
      {option.availability === "NONE" && (
        <div className="mt-2">
          <div className="mb-1 font-semibold">{t("Or search anyway with a boost (100% to the driver)")}</div>
          <div className="grid grid-cols-4 gap-1.5">
            {[0, 10, 20, 30].map((amount) => (
              <button
                key={amount}
                onClick={() => onBoost(amount)}
                className={clsx("rounded-lg border py-1 font-semibold", boost === amount ? "border-fg bg-surface text-fg" : "border-amber-300 dark:border-amber-400/30")}
              >
                {amount ? `+₹${amount}` : t("No boost")}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** Bid your fare (pick your own price within a range) or Sure Ride (pickup promise). */
function PriceOptions({
  option,
  bidding,
  bid,
  sureRide,
  onBidding,
  onBid,
  onSureRide,
}: {
  option: EstimateOption;
  bidding: boolean;
  bid: number;
  sureRide: boolean;
  onBidding: (on: boolean) => void;
  onBid: (amount: number) => void;
  onSureRide: (on: boolean) => void;
}) {
  const low = Math.ceil(Number(option.offer_range.min));
  const high = Math.floor(Number(option.offer_range.max));
  const usual = Number(option.fare.total);
  const step = (delta: number) => onBid(Math.min(high, Math.max(low, bid + delta)));
  return (
    <div className="mt-3 space-y-2">
      <div className="rounded-2xl border border-line p-3">
        <div className="flex items-center gap-2">
          <HandCoins className="size-4" />
          <span className="flex-1 text-sm font-semibold">{t("Offer your fare")}</span>
          <Toggle checked={bidding} onChange={onBidding} label={t("Offer your fare")} />
        </div>
        {bidding && (
          <div className="mt-2">
            <div className="flex items-center justify-between gap-2">
              <button onClick={() => step(-5)} className="size-9 rounded-full bg-surface-3 text-lg font-bold" aria-label="−₹5">
                −
              </button>
              <div className="text-center">
                <div className="text-2xl font-bold">₹{bid}</div>
                <div className="text-[11px] text-muted">{t("Usual fare {fare}", { fare: inr(usual) })}</div>
              </div>
              <button onClick={() => step(5)} className="size-9 rounded-full bg-surface-3 text-lg font-bold" aria-label="+₹5">
                +
              </button>
            </div>
            <input type="range" min={low} max={high} step={1} value={bid} onChange={(e) => onBid(Number(e.target.value))} className="mt-2 w-full accent-[var(--color-brand)]" aria-label={t("Your offer")} />
            <p className="text-[11px] text-muted">{(bid < usual ? t("Drivers may accept or counter. Lower offers can take longer.") : t("A higher offer gets you a driver faster. The extra is all theirs."))}</p>
          </div>
        )}
      </div>
      {option.sure_ride && !bidding && (
        <div className="flex items-center gap-2 rounded-2xl border border-line p-3">
          <ShieldCheck className="size-4 text-brand" />
          <span className="flex-1 text-sm">
            <span className="block font-semibold">{t("Sure Ride · +{fee}", { fee: inr(option.sure_ride.fee) })}</span>
            <span className="block text-[11px] text-muted">{t("Driver at your pickup within {n} min, or {refund} back in your wallet", { n: option.sure_ride.minutes, refund: inr(option.sure_ride.refund) })}</span>
          </span>
          <Toggle checked={sureRide} onChange={onSureRide} label={t("Sure Ride")} />
        </div>
      )}
    </div>
  );
}
