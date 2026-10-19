/**
 * Tour packages: day trips and short tours to famous places from the rider's city, at a fixed
 * price per car, with a driver assigned the day before. "My tours" follows each one stop by stop.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { ArrowLeft, CalendarDays, Check, Clock, Landmark, MapPin, Mountain, Palmtree, Route, Star, Trees, Building2, Sparkles, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";

import { BaseMap, FitBounds, MapPolyline, PinMarker } from "@/components/map";
import { Button, Modal, Segmented } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime, inr } from "@/lib/format";
import { haversineKm } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { City, PaymentMethod } from "@/lib/types";

import { useRiderLocation } from "./RiderHome";

interface Stop {
  order: number;
  name: string;
  lat: number;
  lng: number;
  minutes: number;
  note: string;
}
interface Tour {
  slug: string;
  name: string;
  tagline: string;
  category: string;
  category_label: string;
  city: string;
  city_name: string;
  days: number;
  start_time: string;
  rating: number | null;
  rating_count: number;
  stops: Stop[];
  from_price: string;
  hours: number;
  km: string;
  quotes?: { ride_type: string; name: string; seats: number; price: string }[];
}
interface Booking {
  id: number;
  reference: string;
  package: { slug: string; name: string; city_name: string; days: number; stops: Stop[] };
  ride_type: string;
  depart_at: string;
  pickup_address: string;
  group_size: number;
  price: string;
  status: "BOOKED" | "ASSIGNED" | "STARTED" | "COMPLETED" | "CANCELLED";
  status_label: string;
  driver: { name: string; rating: string; phone: string; vehicle: string } | null;
  trip: number | null;
  progress: Record<string, { arrived?: string; left?: string }>;
  cancellation_fee: string;
  rating: number | null;
}

const CATEGORIES = [
  ["", "All", Sparkles],
  ["HERITAGE", "Heritage", Landmark],
  ["PILGRIMAGE", "Pilgrimage", Building2],
  ["NATURE", "Nature", Trees],
  ["HILLS", "Hills", Mountain],
  ["BEACH", "Beaches", Palmtree],
  ["CITY", "City", MapPin],
] as const;
const ICON: Record<string, typeof Landmark> = Object.fromEntries(CATEGORIES.filter(([k]) => k).map(([k, , icon]) => [k, icon]));
const TINT: Record<string, string> = {
  HERITAGE: "from-amber-500/25 to-orange-600/10",
  PILGRIMAGE: "from-rose-500/20 to-amber-500/10",
  NATURE: "from-emerald-500/25 to-teal-600/10",
  HILLS: "from-sky-500/25 to-emerald-500/10",
  BEACH: "from-cyan-400/25 to-sky-500/10",
  CITY: "from-violet-500/20 to-sky-500/10",
};
const PAYMENT: PaymentMethod[] = ["UPI", "CASH", "CARD", "WALLET"];
const errorText = (err: unknown) => (err instanceof ApiError ? err.message : t("Something went wrong."));

function tomorrowAt(start: string) {
  const d = new Date(Date.now() + 86_400_000);
  const [h, m] = start.split(":").map(Number);
  d.setHours(h, m, 0, 0);
  return { date: d.toISOString().slice(0, 10), time: start.slice(0, 5) };
}

export default function RiderTours() {
  const [spot] = useRiderLocation();
  const [tab, setTab] = useState<"explore" | "mine">("explore");
  const [category, setCategory] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const cities = useQuery({ queryKey: ["cities"], queryFn: () => api.get<City[]>("cities/") });
  const nearest = useMemo(() => {
    const list = cities.data ?? [];
    return list.length ? list.reduce((a, b) => (haversineKm(spot, { lat: a.center_lat, lng: a.center_lng }) <= haversineKm(spot, { lat: b.center_lat, lng: b.center_lng }) ? a : b)) : null;
  }, [cities.data, spot]);
  const [citySlug, setCitySlug] = useState<string | null>(null);
  const city = citySlug ?? nearest?.slug ?? "";
  const tours = useQuery({
    queryKey: ["tours", city, category],
    queryFn: () => api.get<Tour[]>(`tours/?city=${city}${category ? `&category=${category}` : ""}`),
    enabled: !!city,
  });
  const mine = useQuery({ queryKey: ["tours", "mine"], queryFn: () => api.get<Booking[]>("tours/bookings/"), refetchInterval: tab === "mine" ? 15_000 : false });
  const upcoming = (mine.data ?? []).filter((b) => ["BOOKED", "ASSIGNED", "STARTED"].includes(b.status)).length;

  return (
    <div className="mx-auto max-w-xl px-4 pb-24 pt-3">
      <div className="flex items-center gap-2">
        <Link to="/ride" className="flex size-10 items-center justify-center rounded-full bg-surface-2" aria-label={t("Back")}>
          <ArrowLeft className="size-5" />
        </Link>
        <div>
          <h1 className="text-lg font-bold">{t("Tours")}</h1>
          <p className="text-xs text-muted">{t("Famous places, a fixed price, your own driver for the day")}</p>
        </div>
      </div>

      <div className="mt-3">
        <Segmented
          value={tab}
          onChange={(v) => setTab(v as "explore" | "mine")}
          options={[
            { value: "explore", label: t("Explore") },
            { value: "mine", label: upcoming ? `${t("My tours")} (${upcoming})` : t("My tours") },
          ]}
        />
      </div>

      {tab === "explore" && (
        <>
          <div className="mt-3 flex items-center gap-2">
            <MapPin className="size-4 text-brand" />
            <select value={city} onChange={(e) => setCitySlug(e.target.value)} className="flex-1 rounded-xl border border-line bg-surface px-3 py-2 text-sm font-semibold" aria-label={t("Starting city")}>
              {(cities.data ?? [])
                .slice()
                .sort((a, b) => a.name.localeCompare(b.name))
                .map((c) => (
                  <option key={c.slug} value={c.slug}>
                    {t("From {city}", { city: c.name })}
                  </option>
                ))}
            </select>
          </div>
          <div className="-mx-4 mt-3 flex gap-2 overflow-x-auto px-4 pb-1">
            {CATEGORIES.map(([key, label, Icon]) => (
              <button key={key || "all"} onClick={() => setCategory(key)} className={clsx("flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold", category === key ? "border-ink bg-ink text-ink-fg" : "border-line")}>
                <Icon className="size-3.5" /> {t(label)}
              </button>
            ))}
          </div>
          <div className="mt-3 space-y-3">
            {(tours.data ?? []).map((tour) => {
              const Icon = ICON[tour.category] ?? Sparkles;
              return (
                <button key={tour.slug} onClick={() => setOpen(tour.slug)} className="block w-full overflow-hidden rounded-3xl border border-line text-left transition hover:shadow-[var(--shadow-float)]">
                  <div className={clsx("flex items-start gap-3 bg-gradient-to-br p-4", TINT[tour.category])}>
                    <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-surface/80">
                      <Icon className="size-5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="font-bold">{tour.name}</div>
                      <div className="text-xs text-muted">{tour.tagline}</div>
                    </div>
                    {tour.rating && (
                      <span className="flex items-center gap-0.5 rounded-full bg-surface/80 px-2 py-0.5 text-xs font-semibold">
                        <Star className="size-3 fill-amber-400 text-amber-400" /> {tour.rating.toFixed(1)}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 px-4 py-2.5 text-xs text-muted">
                    <span className="flex items-center gap-1">
                      <Route className="size-3.5" /> {t("{n} places", { n: tour.stops.length })}
                    </span>
                    <span className="flex items-center gap-1">
                      <Clock className="size-3.5" /> {tour.days > 1 ? t("{n} days", { n: tour.days }) : t("{h} h", { h: Math.round(tour.hours) })}
                    </span>
                    <span className="ml-auto text-sm font-bold text-fg">
                      {t("from {price}", { price: inr(tour.from_price, { whole: true }) })}
                    </span>
                  </div>
                </button>
              );
            })}
            {tours.data?.length === 0 && <p className="py-8 text-center text-sm text-muted">{t("No tours in this category yet.")}</p>}
          </div>
        </>
      )}

      {tab === "mine" && <MyTours bookings={mine.data ?? []} />}

      {open && <TourSheet slug={open} onClose={() => setOpen(null)} onBooked={() => { setOpen(null); setTab("mine"); }} />}
    </div>
  );
}

function TourSheet({ slug, onClose, onBooked }: { slug: string; onClose: () => void; onBooked: () => void }) {
  const qc = useQueryClient();
  const [spot] = useRiderLocation();
  const tour = useQuery({ queryKey: ["tours", "detail", slug], queryFn: () => api.get<Tour>(`tours/${slug}/`) });
  const tr = tour.data;
  const [car, setCar] = useState("");
  const [when, setWhen] = useState<{ date: string; time: string } | null>(null);
  const [group, setGroup] = useState(2);
  const [payment, setPayment] = useState<PaymentMethod>("UPI");
  const choice = tr?.quotes?.find((q) => q.ride_type === (car || tr.quotes?.[0]?.ride_type));
  const slot = when ?? (tr ? tomorrowAt(tr.start_time) : null);
  const book = useMutation({
    mutationFn: () =>
      api.post(`tours/${slug}/book/`, {
        ride_type: choice?.ride_type,
        depart_at: new Date(`${slot!.date}T${slot!.time}`).toISOString(),
        pickup_lat: spot.lat,
        pickup_lng: spot.lng,
        pickup_address: spot.name,
        group_size: group,
        payment_method: payment,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tours", "mine"] });
      toast.success(t("Tour booked. We'll confirm your driver the day before."));
      onBooked();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const points = tr ? ([[spot.lat, spot.lng], ...tr.stops.map((s) => [s.lat, s.lng])] as [number, number][]) : [];
  return (
    <Modal open onClose={onClose} title={tr?.name ?? t("Tour")}>
      {!tr ? (
        <div className="py-10 text-center text-sm text-muted">{t("Loading…")}</div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-muted">{tr.tagline}</p>
          <div className="h-48 overflow-hidden rounded-2xl">
            <BaseMap center={points[0]} zoom={9}>
              <FitBounds points={points} padding={24} fitKey={tr.slug} inset />
              <PinMarker lat={spot.lat} lng={spot.lng} kind="pickup" />
              {tr.stops.map((s) => (
                <PinMarker key={s.order} lat={s.lat} lng={s.lng} kind="stop" label={`${s.order}. ${s.name}`} />
              ))}
              <MapPolyline positions={[...points, points[0]]} color="#6366f1" weight={3} dashed />
            </BaseMap>
          </div>

          <ol className="relative space-y-3 border-l-2 border-dashed border-line pl-5">
            {tr.stops.map((s) => (
              <li key={s.order} className="relative">
                <span className="absolute -left-[27px] top-0 flex size-5 items-center justify-center rounded-full bg-brand text-[10px] font-bold text-on-brand">{s.order}</span>
                <div className="text-sm font-semibold">{s.name}</div>
                <div className="text-xs text-muted">
                  {t("About {m} min here", { m: s.minutes })}
                  {s.note && ` · ${s.note}`}
                </div>
              </li>
            ))}
          </ol>
          <div className="rounded-2xl bg-surface-2 p-3 text-xs text-muted">
            {t("Round trip of about {km} km, {h} hours in all. Includes the car, fuel, your driver, highway tolls, parking at every stop and GST. Entry tickets, boats and meals are paid on the spot.", { km: Math.round(Number(tr.km)), h: Math.round(tr.hours) })}
          </div>

          <div>
            <div className="mb-1.5 text-xs font-semibold">{t("Car")}</div>
            <div className="grid grid-cols-3 gap-2">
              {(tr.quotes ?? []).map((q) => (
                <button key={q.ride_type} onClick={() => setCar(q.ride_type)} disabled={q.seats < group} className={clsx("rounded-2xl border p-2.5 text-left disabled:opacity-40", choice?.ride_type === q.ride_type ? "border-ink ring-2 ring-ink/10" : "border-line")}>
                  <div className="text-sm font-semibold">{q.name}</div>
                  <div className="text-[11px] text-muted">{t("{n} seats", { n: q.seats })}</div>
                  <div className="mt-1 font-bold">{inr(q.price, { whole: true })}</div>
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-[1fr_100px_120px] gap-2">
            <label className="text-xs font-semibold">
              {t("Date")}
              <input type="date" value={slot!.date} min={new Date(Date.now() + 4 * 3_600_000).toISOString().slice(0, 10)} onChange={(e) => setWhen({ ...slot!, date: e.target.value })} className="mt-1 w-full rounded-xl border border-line bg-surface px-2 py-2 text-sm font-normal" />
            </label>
            <label className="text-xs font-semibold">
              {t("Pickup")}
              <input type="time" value={slot!.time} onChange={(e) => setWhen({ ...slot!, time: e.target.value })} className="mt-1 w-full rounded-xl border border-line bg-surface px-2 py-2 text-sm font-normal" />
            </label>
            <label className="text-xs font-semibold">
              {t("People")}
              <div className="mt-1 flex items-center justify-between rounded-xl border border-line px-2 py-1.5">
                <button onClick={() => setGroup(Math.max(1, group - 1))} className="px-1 text-lg" aria-label={t("Fewer")}>
                  −
                </button>
                <span className="flex items-center gap-1 text-sm">
                  <Users className="size-3.5" /> {group}
                </span>
                <button onClick={() => setGroup(Math.min(7, group + 1))} className="px-1 text-lg" aria-label={t("More")}>
                  +
                </button>
              </div>
            </label>
          </div>
          <div className="flex gap-2">
            {PAYMENT.map((p) => (
              <button key={p} onClick={() => setPayment(p)} className={clsx("flex-1 rounded-full border px-2 py-1.5 text-xs font-semibold", payment === p ? "border-ink bg-ink text-ink-fg" : "border-line")}>
                {p}
              </button>
            ))}
          </div>
          <p className="text-xs text-muted">
            <MapPin className="mr-1 inline size-3.5" />
            {t("Pickup near {place}", { place: spot.name })} · {t("Free cancellation until 24 hours before.")}
          </p>
          <Button block size="lg" loading={book.isPending} disabled={!choice} onClick={() => book.mutate()}>
            {choice ? t("Book for {price}", { price: inr(choice.price) }) : t("Choose a car")}
          </Button>
        </div>
      )}
    </Modal>
  );
}

function MyTours({ bookings }: { bookings: Booking[] }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const refresh = () => qc.invalidateQueries({ queryKey: ["tours", "mine"] });
  const cancel = useMutation({
    mutationFn: (id: number) => api.post<Booking>(`tours/bookings/${id}/cancel/`),
    onSuccess: (b) => {
      refresh();
      toast.success(Number(b.cancellation_fee) ? t("Cancelled. A late-cancellation fee of {fee} applies.", { fee: inr(b.cancellation_fee) }) : t("Cancelled at no charge."));
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const rate = useMutation({
    mutationFn: ({ id, stars }: { id: number; stars: number }) => api.post(`tours/bookings/${id}/rate/`, { stars }),
    onSuccess: () => {
      refresh();
      toast.success(t("Thanks for rating your tour"));
    },
    onError: (err) => toast.error(errorText(err)),
  });
  if (!bookings.length) return <p className="py-10 text-center text-sm text-muted">{t("No tours yet. Explore what's near you.")}</p>;
  return (
    <div className="mt-3 space-y-3">
      {bookings.map((b) => {
        const live = b.status === "STARTED";
        return (
          <div key={b.id} className={clsx("rounded-3xl border p-4", live ? "border-brand" : "border-line")}>
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <div className="font-bold">{b.package.name}</div>
                <div className="text-xs text-muted">
                  <CalendarDays className="mr-1 inline size-3.5" />
                  {dateTime(b.depart_at)} · {b.ride_type} · {b.group_size} {t("people")} · {inr(b.price)}
                </div>
              </div>
              <span className={clsx("rounded-full px-2 py-0.5 text-[11px] font-semibold", b.status === "CANCELLED" ? "bg-surface-3 text-muted" : b.status === "COMPLETED" ? "bg-brand/15 text-brand" : "bg-amber-500/15 text-amber-700 dark:text-amber-400")}>{t(b.status_label)}</span>
            </div>
            {b.driver && b.status !== "CANCELLED" && (
              <div className="mt-2 text-xs">
                <span className="font-semibold">{b.driver.name}</span> · {b.driver.rating}★ · {b.driver.vehicle}
              </div>
            )}
            {(live || b.status === "COMPLETED") && (
              <ol className="mt-3 space-y-1">
                {b.package.stops.map((s) => {
                  const p = b.progress[String(s.order)] ?? {};
                  return (
                    <li key={s.order} className="flex items-center gap-2 text-xs">
                      <span className={clsx("flex size-4 items-center justify-center rounded-full", p.left ? "bg-brand text-on-brand" : p.arrived ? "bg-amber-500 text-white" : "bg-surface-3")}>{p.left && <Check className="size-3" />}</span>
                      <span className={clsx(p.arrived && !p.left && "font-semibold")}>{s.name}</span>
                      {p.arrived && !p.left && <span className="text-amber-600">{t("here now")}</span>}
                    </li>
                  );
                })}
              </ol>
            )}
            <div className="mt-3 flex gap-2">
              {live && b.trip && (
                <Button size="sm" onClick={() => navigate(`/ride/trips/${b.trip}`)}>
                  {t("Open live trip")}
                </Button>
              )}
              {(b.status === "BOOKED" || b.status === "ASSIGNED") && (
                <Button size="sm" variant="outline" loading={cancel.isPending} onClick={() => window.confirm(t("Cancel this tour? It's free until 24 hours before departure.")) && cancel.mutate(b.id)}>
                  {t("Cancel")}
                </Button>
              )}
              {b.status === "COMPLETED" && b.rating == null && (
                <div className="flex items-center gap-1">
                  <span className="text-xs text-muted">{t("Rate")}</span>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <button key={n} onClick={() => rate.mutate({ id: b.id, stars: n })} aria-label={`${n}`}>
                      <Star className="size-5 text-amber-400" />
                    </button>
                  ))}
                </div>
              )}
              {b.rating != null && (
                <span className="flex items-center gap-0.5 text-xs">
                  {Array.from({ length: b.rating }).map((_, i) => (
                    <Star key={i} className="size-3.5 fill-amber-400 text-amber-400" />
                  ))}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
