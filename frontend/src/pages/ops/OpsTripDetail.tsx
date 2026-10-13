import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, XCircle } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";

import { BaseMap, CarMarker, FitBounds, MapPolyline, PinMarker, RouteLine } from "@/components/map";
import { Avatar, Badge, Button, Card, CardHeader, KeyValue, Modal, Spinner, StatusBadge, Stars, Table, Td, Textarea, Th } from "@/components/ui";
import { api, openFile } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dateTime, inr, km, minutes, time } from "@/lib/format";
import { isActive, useLiveTrip } from "@/lib/hooks";
import type { TripEvent, TripOffer } from "@/lib/types";

export default function OpsTripDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const { data: trip, driverPos } = useLiveTrip(id);
  const events = useQuery({ queryKey: ["trips", id, "events"], queryFn: () => api.get<TripEvent[]>(`trips/${id}/events/`), refetchInterval: trip && isActive(trip) ? 5000 : false });
  const offers = useQuery({ queryKey: ["trips", id, "offers"], queryFn: () => api.get<TripOffer[]>(`trips/${id}/offers/`) });
  const route = useQuery({ queryKey: ["trips", id, "route"], queryFn: () => api.get<[number, number][]>(`trips/${id}/route/`) });
  const [cancelOpen, setCancelOpen] = useState(false);
  const [reason, setReason] = useState("");
  const cancel = useMutation({
    mutationFn: () => api.post(`trips/${id}/cancel/`, { reason: reason || "Cancelled by operations" }),
    onSuccess: () => {
      toast.success("Trip cancelled");
      setCancelOpen(false);
      qc.invalidateQueries({ queryKey: ["trips"] });
    },
    onError: (err) => toast.error((err as Error).message),
  });

  if (!trip) return <Spinner className="mx-auto mt-20 size-7" />;
  const points: [number, number][] = [[trip.pickup_lat, trip.pickup_lng], [trip.dropoff_lat, trip.dropoff_lng]];
  if (driverPos) points.push([driverPos.lat, driverPos.lng]);

  return (
    <>
      <Link to="/ops/trips" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
        <ArrowLeft className="size-4" /> Trips
      </Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight">{trip.trip_number}</h1>
            <StatusBadge status={trip.status} label={trip.status_label} />
            {trip.flags.map((f) => (
              <Badge key={f} tone="danger">
                {f.replace(/_/g, " ").toLowerCase()}
              </Badge>
            ))}
          </div>
          <p className="mt-1 text-sm text-muted">
            {trip.ride_type_name} in {trip.city} · requested {dateTime(trip.requested_at)}
          </p>
        </div>
        <div className="flex gap-2">
          {trip.status === "COMPLETED" && (
            <Button variant="outline" icon={<Download className="size-4" />} onClick={() => openFile(`/api/v1/trips/${trip.id}/receipt/`)}>
              Receipt
            </Button>
          )}
          {isActive(trip) && can("trips.manage") && (
            <Button variant="danger" icon={<XCircle className="size-4" />} onClick={() => setCancelOpen(true)}>
              Cancel trip
            </Button>
          )}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
        <Card className="overflow-hidden">
          <div className="h-[360px]">
            <BaseMap center={[trip.pickup_lat, trip.pickup_lng]} zoom={13} zoomControl>
              <FitBounds points={points} padding={50} fitKey={`${trip.id}-${trip.status}-${driverPos ? 1 : 0}`} />
              <PinMarker lat={trip.pickup_lat} lng={trip.pickup_lng} kind="pickup" label="Pickup" />
              <PinMarker lat={trip.dropoff_lat} lng={trip.dropoff_lng} kind="dropoff" label="Drop" />
              <RouteLine from={[trip.pickup_lat, trip.pickup_lng]} to={[trip.dropoff_lat, trip.dropoff_lng]} encoded={trip.route_polyline} via={trip.stop && [trip.stop.lat, trip.stop.lng]} dashed={!!route.data?.length} />
              {trip.stop && <PinMarker lat={trip.stop.lat} lng={trip.stop.lng} kind="stop" />}
              {route.data && route.data.length > 1 && <MapPolyline positions={route.data} color="#10b981" weight={4} />}
              {driverPos && isActive(trip) && <CarMarker lat={driverPos.lat} lng={driverPos.lng} heading={driverPos.heading} rideType={trip.ride_type} />}
            </BaseMap>
          </div>
          <div className="grid grid-cols-2 gap-4 p-5 text-sm">
            <div>
              <div className="label">Pickup</div>
              <div className="font-medium">{trip.pickup_address}</div>
            </div>
            <div>
              <div className="label">Drop</div>
              <div className="font-medium">{trip.dropoff_address}</div>
            </div>
          </div>
        </Card>

        <div className="space-y-4">
          <Card className="p-5">
            <div className="grid grid-cols-2 gap-4">
              {[
                { label: "Rider", party: trip.rider },
                { label: "Driver", party: trip.driver },
              ].map(({ label, party }) => (
                <div key={label}>
                  <div className="label">{label}</div>
                  {party ? (
                    <div className="flex items-center gap-2">
                      <Avatar name={party.name} size={36} />
                      <div>
                        <div className="text-sm font-semibold">{party.name}</div>
                        <div className="text-xs text-muted">
                          <Stars value={party.rating} size={10} />
                        </div>
                      </div>
                    </div>
                  ) : (
                    <span className="text-sm text-muted">Not assigned</span>
                  )}
                </div>
              ))}
            </div>
            {trip.vehicle && <p className="mt-3 text-xs text-muted">Vehicle: {trip.vehicle}</p>}
          </Card>
          <Card>
            <CardHeader title="Fare" subtitle={trip.pricing_mode ? (trip.pricing_mode === "UPFRONT" ? "Upfront price honoured" : "Re-priced on actual route") : "Upfront estimate"} />
            <div className="px-5 py-2">
              {trip.fare.lines.map((l) => (
                <KeyValue key={l.code} label={l.label}>
                  {inr(l.amount)}
                </KeyValue>
              ))}
              <div className="border-t border-line">
                <KeyValue label={<span className="font-semibold text-fg">Total</span>}>{inr(trip.fare.total)}</KeyValue>
                <KeyValue label="Driver earning">{inr(trip.driver_earning)}</KeyValue>
                <KeyValue label="Payment">
                  {trip.payment_method} · <StatusBadge status={trip.payment_status} />
                </KeyValue>
                {Number(trip.tip_amount) > 0 && <KeyValue label="Tip">{inr(trip.tip_amount)}</KeyValue>}
                {trip.actual_distance_km && (
                  <KeyValue label="Actual vs estimate">
                    {km(trip.actual_distance_km)} / {km(trip.estimated_distance_km)} · {minutes(trip.actual_duration_min)}
                  </KeyValue>
                )}
              </div>
            </div>
          </Card>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Timeline" />
          <ol className="relative space-y-4 px-6 py-5">
            {(events.data ?? []).map((e) => (
              <li key={e.id} className="relative flex gap-3">
                <span className={`mt-1.5 size-2.5 shrink-0 rounded-full ${e.kind === "STATUS" ? "bg-brand" : e.kind.includes("EXPIRED") || e.kind.includes("DECLINED") ? "bg-amber-500" : "bg-sky-500"}`} />
                <div className="flex-1">
                  <div className="text-sm font-semibold">{e.kind === "STATUS" ? e.to_status.replace(/_/g, " ").toLowerCase() : e.kind.replace(/_/g, " ").toLowerCase()}</div>
                  {e.message && <div className="text-xs text-muted">{e.message}</div>}
                </div>
                <time className="text-xs text-muted">{time(e.created_at)}</time>
              </li>
            ))}
          </ol>
        </Card>
        <Card>
          <CardHeader title="Dispatch decisions" subtitle="Who was offered the trip, and why (lower score wins)" />
          <Table>
            <thead>
              <tr>
                <Th>Driver</Th>
                <Th className="text-right">Distance</Th>
                <Th className="text-right">ETA</Th>
                <Th className="text-right">Score</Th>
                <Th>Outcome</Th>
              </tr>
            </thead>
            <tbody>
              {(offers.data ?? []).map((o) => (
                <tr key={o.id}>
                  <Td>
                    {o.driver}
                    <div className="text-xs text-muted">{o.dispatch_mode.toLowerCase()}</div>
                  </Td>
                  <Td className="text-right">{km(o.distance_km)}</Td>
                  <Td className="text-right">{minutes(o.eta_minutes)}</Td>
                  <Td className="text-right font-mono">{o.rank_score.toFixed(2)}</Td>
                  <Td>
                    <StatusBadge status={o.status === "ACCEPTED" ? "COMPLETED" : o.status === "PENDING" ? "PENDING" : "CANCELLED"} label={o.status.toLowerCase()} />
                  </Td>
                </tr>
              ))}
              {offers.data?.length === 0 && (
                <tr>
                  <Td className="text-center text-muted">No offers yet</Td>
                </tr>
              )}
            </tbody>
          </Table>
        </Card>
      </div>

      <Modal
        open={cancelOpen}
        onClose={() => setCancelOpen(false)}
        title={`Cancel ${trip.trip_number}?`}
        footer={
          <Button variant="danger" onClick={() => cancel.mutate()} loading={cancel.isPending}>
            Cancel trip
          </Button>
        }
      >
        <p className="mb-3 text-sm text-muted">Operations cancellations never charge the rider. The driver is freed for new trips.</p>
        <Textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (shown to the rider)" />
      </Modal>
    </>
  );
}
