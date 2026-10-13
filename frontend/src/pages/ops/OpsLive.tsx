import { useMutation, useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Flame, Gauge, Play, Radio } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { RIDE_TYPE_COLORS } from "@/components/map";
import { Badge, Button, StatusBadge } from "@/components/ui";
import { useOps } from "@/layouts/OpsLayout";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { useAuth } from "@/lib/auth";
import type { Breakdown, SurgeZone } from "@/lib/types";

import { LiveMap, useLiveOps } from "./LiveMap";

export default function OpsLive() {
  const { city, cityInfo, cities, setCity } = useOps();
  const { can } = useAuth();
  const [showSurge, setShowSurge] = useState(true);
  const [showHeat, setShowHeat] = useState(false);
  const live = useLiveOps(city);
  const surge = useQuery({
    queryKey: ["surge", "board", city],
    queryFn: () => api.get<SurgeZone[]>(`surge/board/?city=${city}`),
    enabled: !!city && showSurge && can("pricing.view"),
    refetchInterval: 30_000,
  });
  const heat = useQuery({
    queryKey: ["analytics", "breakdown", `city=${city}&days=7`],
    queryFn: () => api.get<Breakdown>(`analytics/breakdown/?city=${city}&days=7`),
    enabled: showHeat && can("reports.view"),
  });
  const sweep = useMutation({
    mutationFn: () => api.post<{ offers_sent: number; offers_expired: number; requests_expired: number }>("ops/dispatch/sweep/"),
    onSuccess: (r) => toast.success(`Dispatch sweep: ${r.offers_sent} offers sent, ${r.offers_expired} expired, ${r.requests_expired} requests timed out`),
    onError: (err) => toast.error((err as Error).message),
  });

  const trips = live.data?.trips ?? [];
  const drivers = live.data?.drivers ?? [];
  const counts = {
    searching: trips.filter((t) => t.status === "REQUESTED").length,
    enroute: trips.filter((t) => t.status === "DRIVER_ASSIGNED" || t.status === "DRIVER_ARRIVED").length,
    onTrip: trips.filter((t) => t.status === "IN_PROGRESS").length,
    free: drivers.filter((d) => d.availability === "ONLINE").length,
  };

  return (
    <div className="relative h-full">
      <LiveMap city={city} cityInfo={cityInfo} data={live.data} surge={showSurge ? surge.data : undefined} heat={showHeat ? heat.data?.heatmap : undefined} />

      <div className="absolute top-4 left-4 z-[700] w-80 max-w-[calc(100%-2rem)] space-y-3">
        <div className="card p-4">
          <div className="flex items-center justify-between">
            <h1 className="font-bold">Live operations</h1>
            <Badge tone={live.connected ? "brand" : "neutral"}>
              <Radio className="size-3" /> {live.connected ? "real-time" : "polling 3s"}
            </Badge>
          </div>
          {!city && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {cities.map((c) => (
                <Button key={c.slug} size="sm" variant="outline" onClick={() => setCity(c.slug)}>
                  {c.name}
                </Button>
              ))}
            </div>
          )}
          <div className="mt-3 grid grid-cols-4 gap-2 text-center">
            {[
              ["Searching", counts.searching, "text-danger"],
              ["En route", counts.enroute, "text-amber-500"],
              ["On trip", counts.onTrip, "text-sky-500"],
              ["Free cars", counts.free, "text-brand"],
            ].map(([label, value, tone]) => (
              <div key={label as string} className="rounded-xl bg-surface-2 py-2">
                <div className={clsx("text-lg font-bold", tone as string)}>{value}</div>
                <div className="text-[10px] text-muted">{label}</div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <Button size="sm" variant={showSurge ? "primary" : "outline"} icon={<Gauge className="size-3.5" />} onClick={() => setShowSurge((s) => !s)} disabled={!city}>
              Surge zones
            </Button>
            <Button size="sm" variant={showHeat ? "primary" : "outline"} icon={<Flame className="size-3.5" />} onClick={() => setShowHeat((s) => !s)}>
              Demand heatmap
            </Button>
            {can("dispatch.run") && (
              <Button size="sm" variant="outline" icon={<Play className="size-3.5" />} onClick={() => sweep.mutate()} loading={sweep.isPending}>
                Run dispatch
              </Button>
            )}
          </div>
          <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted">
            {Object.entries(RIDE_TYPE_COLORS).map(([code, color]) => (
              <span key={code} className="flex items-center gap-1">
                <span className="size-2.5 rounded-sm" style={{ background: color }} /> {code.toLowerCase()}
              </span>
            ))}
          </div>
        </div>

        <div className="card max-h-[45vh] overflow-y-auto">
          <div className="sticky top-0 border-b border-line bg-surface px-4 py-2.5 text-xs font-semibold text-muted uppercase">Active trips</div>
          {trips.length === 0 && <p className="px-4 py-6 text-center text-sm text-muted">No active trips. Start the simulator to see live traffic.</p>}
          {trips.slice(0, 60).map((t) => (
            <Link key={t.id} to={`/ops/trips/${t.id}`} className="flex items-center justify-between border-b border-line px-4 py-2.5 text-sm last:border-0 hover:bg-surface-2">
              <div>
                <div className="font-medium">{t.trip_number}</div>
                <div className="text-xs text-muted">
                  {t.ride_type} · {ago(t.requested_at)}
                </div>
              </div>
              <StatusBadge status={t.status} />
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
