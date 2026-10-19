/**
 * Guardian mode: what a trusted contact sees from the SMS link while the rider's alert is open.
 * The location updates live; once the rider is safe (or the alert ends) it is no longer shown.
 */

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Phone, Radio, Siren } from "lucide-react";
import { useParams } from "react-router";

import { BaseMap, PinMarker, Recenter } from "@/components/map";
import { Spinner } from "@/components/ui";
import { ApiError, request } from "@/lib/api";
import { ago, dateTime } from "@/lib/format";

interface Share {
  name: string;
  active: boolean;
  triggers: string[];
  started_at: string;
  ended_at: string | null;
  ended_by: string;
  location: { lat: number; lng: number; source: string; at: string | null } | null;
  trip: { number: string; status: string; vehicle: string | null; registration: string | null; driver: string | null; pickup: string; dropoff: string } | null;
  phone: string | null;
}

export default function SafeShare() {
  const { token } = useParams();
  const q = useQuery({
    queryKey: ["safe", token],
    queryFn: () => request<Share>(`/api/v1/safe/${token}/`, { headers: { Authorization: "" } }),
    refetchInterval: (query) => (query.state.data?.active === false ? false : 10_000),
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 3,
  });
  const s = q.data;
  if (q.isError) return <div className="flex h-dvh items-center justify-center p-6 text-center text-sm text-muted">This link doesn't exist.</div>;
  if (!s)
    return (
      <div className="flex h-dvh items-center justify-center">
        <Spinner />
      </div>
    );
  const loc = s.location;
  return (
    <div className="mx-auto flex h-dvh max-w-lg flex-col bg-surface">
      <div className={s.active ? "bg-danger px-4 py-3 text-white" : "bg-brand px-4 py-3 text-on-brand"}>
        <div className="flex items-center gap-2 text-sm font-bold">
          {s.active ? <Radio className="size-4 animate-pulse" /> : <CheckCircle2 className="size-4" />}
          {s.active ? `${s.name} may need help` : s.ended_by === "RIDER" ? `${s.name} is safe` : `${s.name}'s alert has ended`}
        </div>
        <div className="text-xs opacity-90">
          {s.active ? `${s.triggers.join(" · ")} · since ${dateTime(s.started_at)}` : `Ended ${dateTime(s.ended_at)}`}
        </div>
      </div>
      {loc ? (
        <div className="relative min-h-[300px] flex-1">
          <BaseMap center={[loc.lat, loc.lng]} zoom={15}>
            <Recenter center={[loc.lat, loc.lng]} />
            <PinMarker lat={loc.lat} lng={loc.lng} kind="me" label={s.name} />
          </BaseMap>
          <div className="absolute bottom-3 left-3 right-3 z-[500] rounded-2xl bg-surface px-3 py-2 text-xs shadow-[var(--shadow-float)]">
            Last seen {ago(loc.at)} · {loc.source === "PHONE" ? "from their phone" : "from the car"} ·{" "}
            <a className="font-semibold text-brand" href={`https://maps.google.com/?q=${loc.lat},${loc.lng}`} target="_blank" rel="noreferrer">
              Open in Maps
            </a>
          </div>
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center p-6 text-center text-sm text-muted">{s.active ? "Waiting for a location…" : "Location sharing has stopped."}</div>
      )}
      <div className="space-y-3 p-4">
        {s.trip && (
          <div className="rounded-2xl border border-line p-3 text-sm">
            <div className="font-semibold">{s.trip.vehicle ?? "Ride"} {s.trip.registration && <span className="ml-1 rounded bg-surface-2 px-1.5 font-mono text-xs">{s.trip.registration}</span>}</div>
            <div className="text-xs text-muted">
              {s.trip.driver && `Driver ${s.trip.driver} · `}
              {s.trip.pickup} → {s.trip.dropoff} · {s.trip.status}
            </div>
          </div>
        )}
        {s.active && (
          <div className="grid grid-cols-2 gap-2">
            {s.phone && (
              <a href={`tel:${s.phone}`} className="flex items-center justify-center gap-2 rounded-2xl bg-ink px-3 py-3 text-sm font-semibold text-ink-fg">
                <Phone className="size-4" /> Call {s.name.split(" ")[0]}
              </a>
            )}
            <a href="tel:112" className="flex items-center justify-center gap-2 rounded-2xl bg-danger px-3 py-3 text-sm font-semibold text-white">
              <Siren className="size-4" /> Call 112
            </a>
          </div>
        )}
        <p className="text-center text-[11px] text-muted">Ride Pulse safety · our safety team has been told and is following up.</p>
      </div>
    </div>
  );
}
