import { useQuery } from "@tanstack/react-query";
import { Briefcase, ChevronRight, Clock, House, LocateFixed, MapPin, Package, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";

import { BaseMap, CarMarker, PinMarker, Recenter } from "@/components/map";
import { NotificationBell } from "@/components/NotificationBell";
import { Sheet, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { greeting } from "@/lib/format";
import { useActiveTrip, useTrips } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { SavedPlace } from "@/lib/types";

const DEFAULT_SPOT = { lat: 13.0418, lng: 80.2341, name: "T. Nagar, Chennai" };

export function useRiderLocation() {
  const [spot, setSpot] = useState(() => {
    try {
      const saved = sessionStorage.getItem("rp.rider.spot");
      if (saved) return JSON.parse(saved) as typeof DEFAULT_SPOT;
    } catch {
      /* ignore */
    }
    return DEFAULT_SPOT;
  });
  const save = (value: typeof DEFAULT_SPOT) => {
    setSpot(value);
    sessionStorage.setItem("rp.rider.spot", JSON.stringify(value));
  };
  return [spot, save] as const;
}

export default function RiderHome() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [spot, setSpot] = useRiderLocation();
  const active = useActiveTrip();
  const places = useQuery({ queryKey: ["places", "saved"], queryFn: () => api.get<SavedPlace[]>("rider/places/") });
  const recent = useTrips("status=COMPLETED&page_size=6");
  const nearby = useQuery({
    queryKey: ["nearby", spot.lat.toFixed(3), spot.lng.toFixed(3)],
    queryFn: () => api.get<{ drivers: { key: string; lat: number; lng: number; heading: number | null; ride_type: string | null }[] }>(`fares/nearby-drivers/?lat=${spot.lat}&lng=${spot.lng}`),
    refetchInterval: 6_000,
  });

  useEffect(() => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      async ({ coords }) => {
        // Only use real GPS when it's inside a city we serve; otherwise keep the demo location.
        const [place] = await api.get<{ name: string; city: string }[]>(`places/?lat=${coords.latitude}&lng=${coords.longitude}`);
        if (place?.city) setSpot({ lat: coords.latitude, lng: coords.longitude, name: place.name });
      },
      () => undefined,
      { timeout: 4000 },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const recentPlaces = useMemo(() => {
    const seen = new Set<string>();
    return (recent.data?.results ?? [])
      .filter((t) => {
        const key = t.dropoff_address;
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .slice(0, 2);
  }, [recent.data]);

  const goTo = (lat: number, lng: number, name: string) =>
    navigate(`/ride/book?to=${lat},${lng}&name=${encodeURIComponent(name)}`);

  const home = places.data?.find((p) => p.label === "HOME");
  const work = places.data?.find((p) => p.label === "WORK");

  return (
    <div className="relative flex h-full flex-col">
      <div className="absolute inset-0">
        <BaseMap center={[spot.lat, spot.lng]} zoom={15}>
          <Recenter center={[spot.lat, spot.lng]} />
          <PinMarker lat={spot.lat} lng={spot.lng} kind="me" />
          {(nearby.data?.drivers ?? []).map((d) => (
            <CarMarker key={d.key} lat={d.lat} lng={d.lng} heading={d.heading} rideType={d.ride_type} />
          ))}
        </BaseMap>
      </div>

      <div className="rp-overlay relative z-[500] flex items-center justify-between p-4">
        <div className="rounded-full bg-surface/95 px-4 py-2 text-sm font-semibold shadow-[var(--shadow-float)] backdrop-blur">
          {t(greeting())}, {user?.first_name || t("there")} 👋
        </div>
        <div className="rp-phone-only rounded-full bg-surface/95 shadow-[var(--shadow-float)] backdrop-blur">
          <NotificationBell />
        </div>
      </div>

      <div className="flex-1" />

      <div className="rp-overlay relative z-[500] px-4 pb-3">
        <button
          onClick={() => setSpot(DEFAULT_SPOT)}
          className="ml-auto flex size-11 items-center justify-center rounded-full bg-surface shadow-[var(--shadow-float)]"
          aria-label="Recenter"
        >
          <LocateFixed className="size-5" />
        </button>
      </div>

      <Sheet>
        {active.data && (
          <Link to={`/ride/trips/${active.data.id}`} className="mb-4 flex items-center gap-3 rounded-2xl bg-ink p-4 text-ink-fg">
            <span className="relative flex size-3">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex size-3 rounded-full bg-emerald-400" />
            </span>
            <div className="flex-1">
              <div className="text-sm font-semibold">{t(active.data.status_label)}</div>
              <div className="text-xs opacity-70">
                {active.data.ride_type_name} to {active.data.dropoff_address}
              </div>
            </div>
            <ChevronRight className="size-5 opacity-70" />
          </Link>
        )}

        <button
          onClick={() => navigate("/ride/book")}
          className="flex w-full items-center gap-3 rounded-2xl bg-surface-3 px-4 py-4 text-left transition hover:bg-line"
        >
          <Search className="size-5" />
          <span className="flex-1 text-lg font-semibold">{t("Where to?")}</span>
          <span
            role="button"
            tabIndex={0}
            onClick={(e) => {
              e.stopPropagation();
              navigate("/ride/book?later=1");
            }}
            className="flex items-center gap-1 rounded-full bg-surface px-3 py-1.5 text-xs font-semibold hover:bg-line"
            aria-label="Schedule a ride for later"
          >
            <Clock className="size-3.5" /> {t("Later")}
          </span>
        </button>

        <button
          onClick={() => navigate("/ride/book?service=PARCEL")}
          className="mt-2 flex w-full items-center gap-3 rounded-2xl border border-line px-4 py-2.5 text-left transition hover:bg-surface-2"
        >
          <Package className="size-5 text-brand" />
          <span className="flex-1">
            <span className="block text-sm font-semibold">{t("Send a parcel")}</span>
            <span className="block text-xs text-muted">{t("Documents, keys, food: delivered by bike")}</span>
          </span>
          <ChevronRight className="size-4 text-muted" />
        </button>

        <div className="mt-2 text-xs text-muted">
          <MapPin className="mr-1 inline size-3.5" />
          {t("Pickup near {place}", { place: spot.name })}
        </div>

        <div className="mt-4 divide-y divide-line">
          {[
            { place: home, icon: House, label: "Home" },
            { place: work, icon: Briefcase, label: "Work" },
          ].map(({ place, icon: Icon, label }) =>
            place ? (
              <button key={label} onClick={() => goTo(place.lat, place.lng, place.name)} className="flex w-full items-center gap-3 py-3 text-left">
                <span className="flex size-10 items-center justify-center rounded-full bg-surface-3">
                  <Icon className="size-[18px]" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold">{t(label)}</span>
                  <span className="block truncate text-sm text-muted">{place.name}</span>
                </span>
              </button>
            ) : null,
          )}
          {recentPlaces.map((trip) => (
            <button key={trip.id} onClick={() => goTo(trip.dropoff_lat, trip.dropoff_lng, trip.dropoff_address)} className="flex w-full items-center gap-3 py-3 text-left">
              <span className="flex size-10 items-center justify-center rounded-full bg-surface-3">
                <Clock className="size-[18px]" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-semibold">{trip.dropoff_address}</span>
                <span className="block truncate text-sm text-muted">{t("From {place}", { place: trip.pickup_address })}</span>
              </span>
              <StatusBadge status={trip.ride_type} label={trip.ride_type_name} />
            </button>
          ))}
        </div>
      </Sheet>
    </div>
  );
}
