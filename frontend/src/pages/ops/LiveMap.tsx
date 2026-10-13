import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { useNavigate } from "react-router";

import { BaseMap, CarMarker, FitBounds, type LatLng, MapCircle, MapDot, MapPolyline } from "@/components/map";
import { api } from "@/lib/api";
import type { City, LiveDriver, LiveTrip, SurgeZone } from "@/lib/types";
import { useSocket } from "@/lib/ws";

export interface LiveData {
  time: string;
  drivers: LiveDriver[];
  trips: LiveTrip[];
}

export function useLiveOps(city: string) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["ops", "live", city],
    queryFn: () => api.get<LiveData>(`ops/live/?city=${city}`),
    refetchInterval: 3_000,
  });
  const connected = useSocket("/ws/ops/", (msg) => {
    if (msg.event === "driver_location") {
      const d = msg.data as { driver_id: number; lat: number; lng: number; heading: number | null };
      qc.setQueryData<LiveData>(["ops", "live", city], (old) =>
        old ? { ...old, drivers: old.drivers.map((x) => (x.id === d.driver_id ? { ...x, lat: d.lat, lng: d.lng, heading: d.heading } : x)) } : old,
      );
    } else {
      qc.invalidateQueries({ queryKey: ["ops", "live"] });
    }
  });
  return { ...query, connected };
}

export function LiveMap({
  city,
  cityInfo,
  data,
  surge,
  heat,
  interactive = true,
}: {
  city: string;
  cityInfo?: City;
  data?: LiveData;
  surge?: SurgeZone[];
  heat?: { lat: number; lng: number; requests: number }[];
  interactive?: boolean;
}) {
  const navigate = useNavigate();
  const center: LatLng = cityInfo ? [cityInfo.center_lat, cityInfo.center_lng] : [13.05, 80.23];
  const fit = useMemo<LatLng[]>(() => {
    if (cityInfo) {
      const d = cityInfo.radius_km / 111 / 1.6;
      return [
        [cityInfo.center_lat - d, cityInfo.center_lng - d],
        [cityInfo.center_lat + d, cityInfo.center_lng + d],
      ];
    }
    return (data?.drivers ?? []).slice(0, 300).map((d) => [d.lat, d.lng] as LatLng);
  }, [city, cityInfo, !!data]); // eslint-disable-line react-hooks/exhaustive-deps
  const drivers = new Map((data?.drivers ?? []).map((d) => [d.id, d]));
  const maxHeat = Math.max(1, ...(heat ?? []).map((h) => h.requests));

  return (
    <BaseMap center={center} zoom={12} zoomControl={interactive}>
      <FitBounds points={fit} padding={20} maxZoom={14} />
      {(heat ?? []).map((h) => {
        const share = h.requests / maxHeat;
        return (
          <MapCircle
            key={`${h.lat}-${h.lng}`}
            center={[h.lat, h.lng]}
            radius={250 + 650 * share}
            color={share > 0.6 ? "#ef4444" : "#f59e0b"}
            weight={0}
            fillOpacity={0.12 + 0.4 * share}
            label={`${h.requests} requests`}
          />
        );
      })}
      {(surge ?? []).map((z) => {
        const m = Number(z.multiplier);
        return (
          <MapCircle
            key={z.zone_id}
            center={[z.lat, z.lng]}
            radius={2200}
            color={m > 1 ? "#f59e0b" : "#94a3b8"}
            fillOpacity={m > 1 ? 0.12 + (m - 1) * 0.15 : 0.03}
            label={`${z.zone}: ${z.multiplier}× · demand ${z.demand} / supply ${z.supply}`}
          />
        );
      })}
      {(data?.trips ?? []).map((t) => {
        const driver = t.driver_id ? drivers.get(t.driver_id) : undefined;
        return (
          <span key={t.id}>
            {driver && t.status !== "IN_PROGRESS" && <MapPolyline positions={[[driver.lat, driver.lng], t.pickup]} color="#10b981" weight={2} dashed />}
            {t.status === "IN_PROGRESS" && driver && <MapPolyline positions={[[driver.lat, driver.lng], t.dropoff]} color="#0ea5e9" weight={2} opacity={0.6} />}
            <MapDot
              center={t.pickup}
              radius={t.status === "REQUESTED" ? 7 : 5}
              color={t.status === "REQUESTED" ? "#ef4444" : "#10b981"}
              label={`${t.trip_number} · ${t.status.replace(/_/g, " ").toLowerCase()} · ${t.ride_type}`}
              onClick={interactive ? () => navigate(`/ops/trips/${t.id}`) : undefined}
            />
          </span>
        );
      })}
      {(data?.drivers ?? []).map((d) => (
        <CarMarker
          key={d.id}
          lat={d.lat}
          lng={d.lng}
          heading={d.heading}
          rideType={d.ride_type}
          dim={d.availability === "ONLINE"}
          label={`${d.name} · ${d.availability === "ON_TRIP" ? "on trip" : "available"}`}
          onClick={interactive ? () => navigate(`/ops/drivers/${d.id}`) : undefined}
        />
      ))}
    </BaseMap>
  );
}
