/**
 * "Follow my ride": the public page a rider shares with family. No login; shows the car moving,
 * the driver's first name and plate, and the ETA. Nothing private (no phone numbers or fare).
 */

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Clock, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { useParams } from "react-router";

import { BaseMap, CarMarker, FitBounds, type LatLng, PinMarker, RouteLine, routePath, snapToPath } from "@/components/map";
import { FrameAside, PhoneFrame } from "@/components/PhoneFrame";
import { RideTypeArt } from "@/components/RideTypeArt";
import { Avatar, Sheet, Spinner, Stars } from "@/components/ui";
import { ApiError, request } from "@/lib/api";
import { km, time } from "@/lib/format";
import { clockIn, etaFromKm, haversineKm } from "@/lib/hooks";

interface SharedTrip {
  status: string;
  status_label: string;
  rider_first_name: string;
  ride_type: string;
  ride_type_code: string;
  pickup: { lat: number; lng: number; address: string };
  dropoff: { lat: number; lng: number; address: string };
  stop: { lat: number; lng: number; address: string } | null;
  route_polyline: string;
  driver: { first_name: string; rating: string } | null;
  vehicle: string | null;
  driver_location: { lat: number; lng: number; heading: number | null } | null;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
}

const LIVE = new Set(["REQUESTED", "DRIVER_ASSIGNED", "DRIVER_ARRIVED", "IN_PROGRESS"]);

export default function TrackTrip() {
  const { token } = useParams();
  const [recenter, setRecenter] = useState(0);
  const shared = useQuery({
    queryKey: ["track", token],
    // No auth header: this page is for people without an account.
    queryFn: () => request<SharedTrip>(`/api/v1/track/${token}/`, { headers: { Authorization: "" } }),
    refetchInterval: (q) => (q.state.data && LIVE.has(q.state.data.status) ? 3_000 : false),
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 3,
  });
  const trip = shared.data;

  const route = useMemo<LatLng[]>(
    () => (trip ? routePath([trip.pickup.lat, trip.pickup.lng], [trip.dropoff.lat, trip.dropoff.lng], trip.route_polyline, trip.stop && [trip.stop.lat, trip.stop.lng]) : []),
    [trip?.pickup.lat, trip?.dropoff.lat, trip?.route_polyline], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const car = trip?.driver_location;
  const onRoute = useMemo(() => {
    if (!car || trip?.status !== "IN_PROGRESS") return null;
    const snap = snapToPath(route, [car.lat, car.lng]);
    return snap && snap.offMetres < 300 ? snap : null;
  }, [route, car?.lat, car?.lng, trip?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <PhoneFrame
      aside={
        <FrameAside title="Follow a ride">
          <p>Riders can share a live link to their trip with family or friends. Anyone with the link can watch the car move, see the driver and the plate, and know when they've arrived, with no account needed.</p>
          <p>Phone numbers, the ride PIN and the fare stay private, and the link stops working an hour after the trip ends.</p>
        </FrameAside>
      }
    >
      <div className="relative flex min-h-0 flex-1 flex-col md:pt-11">
        {shared.isLoading && (
          <div className="flex flex-1 items-center justify-center">
            <Spinner className="size-7" />
          </div>
        )}
        {shared.isError && (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
            <Clock className="size-10 text-muted" />
            <h1 className="text-lg font-bold">This link has expired</h1>
            <p className="text-sm text-muted">Shared trip links stop working an hour after the ride ends.</p>
          </div>
        )}
        {trip && (
          <TrackView
            trip={trip}
            carAt={onRoute ? onRoute.at : car ? [car.lat, car.lng] : null}
            remainingKm={onRoute ? onRoute.remainingKm : car ? haversineKm(car, trip.dropoff) * 1.3 : null}
            recenter={recenter}
            onRecenter={() => setRecenter((n) => n + 1)}
          />
        )}
      </div>
    </PhoneFrame>
  );
}

function TrackView({
  trip,
  carAt,
  remainingKm,
  recenter,
  onRecenter,
}: {
  trip: SharedTrip;
  carAt: LatLng | null;
  remainingKm: number | null;
  recenter: number;
  onRecenter: () => void;
}) {
  const live = LIVE.has(trip.status);
  const name = trip.rider_first_name || "Your friend";
  const toPickupKm = carAt && trip.status === "DRIVER_ASSIGNED" ? haversineKm({ lat: carAt[0], lng: carAt[1] }, trip.pickup) * 1.3 : null;
  const points: LatLng[] = [[trip.pickup.lat, trip.pickup.lng], [trip.dropoff.lat, trip.dropoff.lng]];
  if (carAt) points.push(carAt);

  let headline = trip.status_label;
  let detail = "";
  if (trip.status === "REQUESTED") headline = `Finding ${name} a driver`;
  if (trip.status === "DRIVER_ASSIGNED") {
    headline = `Driver on the way to ${name}`;
    if (toPickupKm !== null) detail = `${km(toPickupKm)} away · about ${etaFromKm(toPickupKm)} min`;
  }
  if (trip.status === "DRIVER_ARRIVED") headline = `Driver is waiting for ${name}`;
  if (trip.status === "IN_PROGRESS") {
    headline = `${name} is on the way`;
    if (remainingKm !== null) detail = `${km(remainingKm)} to go · arriving around ${clockIn(etaFromKm(remainingKm))}`;
  }
  if (trip.status === "COMPLETED") {
    headline = `${name} has arrived`;
    detail = trip.completed_at ? `Dropped off at ${time(trip.completed_at)}` : "";
  }
  if (trip.status.startsWith("CANCELLED") || trip.status === "EXPIRED") headline = "This trip was cancelled";

  return (
    <>
      <div className="absolute inset-0">
        <BaseMap center={[trip.pickup.lat, trip.pickup.lng]} zoom={13}>
          <FitBounds points={points} padding={50} bottom={330} fitKey={`${trip.status}-${carAt ? 1 : 0}-${recenter}`} />
          <PinMarker lat={trip.pickup.lat} lng={trip.pickup.lng} kind="pickup" />
          {trip.stop && <PinMarker lat={trip.stop.lat} lng={trip.stop.lng} kind="stop" />}
          <PinMarker lat={trip.dropoff.lat} lng={trip.dropoff.lng} kind="dropoff" />
          <RouteLine
            from={[trip.pickup.lat, trip.pickup.lng]}
            to={[trip.dropoff.lat, trip.dropoff.lng]}
            encoded={trip.route_polyline}
            via={trip.stop && [trip.stop.lat, trip.stop.lng]}
            progress={trip.status === "IN_PROGRESS" ? carAt : null}
            dashed={trip.status !== "IN_PROGRESS"}
          />
          {carAt && live && <CarMarker lat={carAt[0]} lng={carAt[1]} heading={trip.driver_location?.heading} rideType={trip.ride_type_code} />}
        </BaseMap>
      </div>

      <div className="relative z-[600] flex items-center gap-2 p-3">
        <div className="flex flex-1 items-center gap-2 rounded-full bg-surface/95 px-4 py-2 text-sm font-semibold shadow-[var(--shadow-float)] backdrop-blur">
          {live ? (
            <span className="relative flex size-2.5">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex size-2.5 rounded-full bg-emerald-500" />
            </span>
          ) : (
            <CheckCircle2 className="size-4 text-brand" />
          )}
          {live ? "Live" : "Trip ended"} · {name}'s ride
        </div>
        <button onClick={onRecenter} className="rounded-full bg-surface px-3 py-2 text-xs font-semibold shadow-[var(--shadow-float)]">
          Re-centre
        </button>
      </div>

      <div className="flex-1" />

      <Sheet height="55%">
        <h1 className="text-xl font-bold">{headline}</h1>
        {detail && <p className="mt-0.5 text-sm text-muted">{detail}</p>}

        {trip.driver && (
          <div className="mt-4 flex items-center gap-3 rounded-2xl bg-surface-2 p-3">
            <Avatar name={trip.driver.first_name} size={44} />
            <div className="min-w-0 flex-1">
              <div className="font-semibold">{trip.driver.first_name}</div>
              <div className="flex items-center gap-1 text-xs text-muted">
                <Stars value={trip.driver.rating} size={10} />
              </div>
              {trip.vehicle && <div className="mt-0.5 truncate text-xs font-medium">{trip.vehicle}</div>}
            </div>
            <RideTypeArt code={trip.ride_type_code} className="h-8 w-14 shrink-0" />
          </div>
        )}

        <div className="mt-4 space-y-3 text-sm">
          <div className="flex gap-3">
            <span className="mt-1.5 size-2.5 shrink-0 rounded-full bg-brand" />
            <div className="min-w-0">
              <div className="text-xs text-muted">From</div>
              <div className="truncate font-medium">{trip.pickup.address}</div>
            </div>
          </div>
          {trip.stop && (
            <div className="flex gap-3">
              <span className="mt-1.5 size-2.5 shrink-0 rounded-full bg-slate-500" />
              <div className="min-w-0">
                <div className="text-xs text-muted">Stop</div>
                <div className="truncate font-medium">{trip.stop.address || "On the way"}</div>
              </div>
            </div>
          )}
          <div className="flex gap-3">
            <span className="mt-1.5 size-2.5 shrink-0 bg-ink" />
            <div className="min-w-0">
              <div className="text-xs text-muted">To</div>
              <div className="truncate font-medium">{trip.dropoff.address}</div>
            </div>
          </div>
        </div>

        <p className="mt-4 flex items-center gap-2 rounded-xl bg-surface-2 px-3 py-2 text-xs text-muted">
          <ShieldCheck className="size-4 shrink-0" />
          {name} shared this ride with you. Ride Pulse's safety team monitors every trip.
        </p>
      </Sheet>
    </>
  );
}
