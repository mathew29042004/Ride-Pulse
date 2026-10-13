import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "./api";
import { useSocket } from "./ws";
import type { Driver, Paginated, Trip, Wallet } from "./types";

const ACTIVE = new Set(["REQUESTED", "DRIVER_ASSIGNED", "DRIVER_ARRIVED", "IN_PROGRESS"]);

export function isActive(trip: Trip | null | undefined): boolean {
  return !!trip && ACTIVE.has(trip.status);
}

export function useActiveTrip(enabled = true) {
  return useQuery({
    queryKey: ["trips", "active"],
    queryFn: () => api.get<Trip | undefined>("trips/active/").then((t) => t ?? null),
    refetchInterval: 4_000,
    enabled,
  });
}

/** A trip that stays fresh: WebSocket pushes when available, polling as a fallback. */
export function useLiveTrip(id: string | number | undefined) {
  const qc = useQueryClient();
  const [driverPos, setDriverPos] = useState<{ lat: number; lng: number; heading: number | null } | null>(null);
  const [polling, setPolling] = useState(true);
  const query = useQuery({
    queryKey: ["trips", String(id)],
    queryFn: () => api.get<Trip>(`trips/${id}/`),
    enabled: id !== undefined,
    // Poll while the trip is live. Socket events refresh instantly on top of this, but the
    // interval must not depend on socket state, or a flapping socket would keep resetting it.
    refetchInterval: polling ? 3_000 : false,
  });
  useEffect(() => {
    if (query.data) setPolling(isActive(query.data));
  }, [query.data?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const connected = useSocket(id && isActive(query.data) ? `/ws/trips/${id}/` : null, (msg) => {
    if (msg.event === "driver_location") {
      const d = msg.data as { lat: number; lng: number; heading: number | null };
      setDriverPos({ lat: d.lat, lng: d.lng, heading: d.heading });
    } else {
      qc.invalidateQueries({ queryKey: ["trips"] });
    }
  });
  useEffect(() => {
    if (query.data?.driver_location) setDriverPos(query.data.driver_location);
  }, [query.data?.driver_location?.lat, query.data?.driver_location?.lng]); // eslint-disable-line react-hooks/exhaustive-deps
  return { ...query, driverPos, connected };
}

export function useWallet() {
  return useQuery({ queryKey: ["wallet"], queryFn: () => api.get<Wallet>("wallet/") });
}

export function useDriverMe(refetchInterval: number | false = 8_000) {
  return useQuery({ queryKey: ["driver", "me"], queryFn: () => api.get<Driver>("driver/me/"), refetchInterval });
}

export function useTrips(params = "", enabled = true) {
  return useQuery({
    queryKey: ["trips", "list", params],
    queryFn: () => api.get<Paginated<Trip>>(`trips/?${params}`),
    enabled,
  });
}

/** Re-render every `ms` (for countdowns and "x min ago" labels). */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

export function haversineKm(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Rough city ETA used for live countdowns between server updates (1.3× road factor, 22 km/h). */
export function etaMinutes(from: { lat: number; lng: number }, to: { lat: number; lng: number }): number {
  return etaFromKm(haversineKm(from, to) * 1.3);
}

/** Minutes to cover `km` of road at an average city speed of 22 km/h. */
export function etaFromKm(km: number): number {
  return Math.max(1, Math.round((km / 22) * 60));
}

/** "4:32 pm": the clock time `minutesFromNow` from now. */
export function clockIn(minutesFromNow: number): string {
  return new Date(Date.now() + minutesFromNow * 60_000).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
}
