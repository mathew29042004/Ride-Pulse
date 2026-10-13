import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, ChevronRight, Clock } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { RideTypeArt } from "@/components/RideTypeArt";
import { formatWhen } from "@/components/SchedulePicker";
import { Button, EmptyState, Skeleton, StatusBadge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime, inr } from "@/lib/format";
import { useTrips } from "@/lib/hooks";
import type { Paginated, ScheduledRide } from "@/lib/types";

/** Rides booked for later, with cancel. (Rider only.) */
function Upcoming() {
  const qc = useQueryClient();
  const upcoming = useQuery({
    queryKey: ["scheduled-rides", "upcoming"],
    queryFn: () => api.get<Paginated<ScheduledRide>>("scheduled-rides/?status=SCHEDULED&ordering=scheduled_for"),
    refetchInterval: 30_000,
  });
  const cancel = useMutation({
    mutationFn: (id: number) => api.post(`scheduled-rides/${id}/cancel/`),
    onSuccess: () => {
      toast.success("Scheduled ride cancelled");
      qc.invalidateQueries({ queryKey: ["scheduled-rides"] });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't cancel."),
  });
  const rides = upcoming.data?.results ?? [];
  if (!rides.length) return null;
  return (
    <div className="mb-3 px-2">
      <h2 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">Upcoming</h2>
      {rides.map((ride) => (
        <div key={ride.id} className="mb-2 flex items-center gap-3 rounded-2xl border border-line p-3">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-brand-soft text-brand-strong">
            <CalendarClock className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="font-semibold">{formatWhen(new Date(ride.scheduled_for))}</div>
            <div className="truncate text-xs text-muted">
              {ride.ride_type_name} to {ride.dropoff.address || "your destination"} · about {inr(ride.quoted_fare)}
            </div>
          </div>
          <Button size="sm" variant="outline" loading={cancel.isPending && cancel.variables === ride.id} onClick={() => cancel.mutate(ride.id)}>
            Cancel
          </Button>
        </div>
      ))}
    </div>
  );
}

export default function TripHistory({ base = "/ride", title = "Activity" }: { base?: string; title?: string }) {
  const [page, setPage] = useState(1);
  const trips = useTrips(`page=${page}&ordering=-requested_at`);
  const results = trips.data?.results ?? [];

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="px-5 pt-5 pb-3">
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        <p className="text-sm text-muted">{trips.data ? `${trips.data.count} trips` : " "}</p>
      </div>
      <div className="flex-1 px-3">
        {base === "/ride" && <Upcoming />}
        {trips.isLoading &&
          [0, 1, 2, 3].map((i) => <Skeleton key={i} className="mx-2 mb-3 h-20" />)}
        {!trips.isLoading && results.length === 0 && (
          <EmptyState icon={<Clock />} title="No trips yet">
            Your past rides will show up here.
          </EmptyState>
        )}
        {results.map((trip) => (
          <Link
            key={trip.id}
            to={base === "/ride" ? `/ride/trips/${trip.id}` : "#"}
            className="flex items-center gap-3 rounded-2xl px-2 py-3 transition hover:bg-surface-2"
          >
            <div className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-surface-2">
              <RideTypeArt code={trip.ride_type} className="h-7 w-12" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate font-semibold">{trip.dropoff_address || "Drop"}</div>
              <div className="truncate text-xs text-muted">{dateTime(trip.requested_at)}</div>
              <div className="mt-1">
                <StatusBadge status={trip.status} label={trip.status_label} />
              </div>
            </div>
            <div className="text-right">
              <div className="font-semibold">{inr(trip.fare_total ?? (trip.status === "COMPLETED" ? null : trip.estimated_fare))}</div>
              <ChevronRight className="ml-auto size-4 text-muted" />
            </div>
          </Link>
        ))}
      </div>
      {trips.data && (trips.data.next || trips.data.previous) && (
        <div className="flex justify-center gap-2 p-4">
          <Button size="sm" variant="outline" disabled={!trips.data.previous} onClick={() => setPage((p) => p - 1)}>
            Newer
          </Button>
          <Button size="sm" variant="outline" disabled={!trips.data.next} onClick={() => setPage((p) => p + 1)}>
            Older
          </Button>
        </div>
      )}
    </div>
  );
}
