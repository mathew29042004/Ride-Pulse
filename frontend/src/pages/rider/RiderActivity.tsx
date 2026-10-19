import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, ChevronRight, Clock } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { RideTypeArt } from "@/components/RideTypeArt";
import { formatWhen } from "@/components/SchedulePicker";
import { SplitRequests } from "@/components/SplitFare";
import { Button, EmptyState, Skeleton, StatusBadge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime, inr } from "@/lib/format";
import { useTrips } from "@/lib/hooks";
import type { Paginated, ScheduledRide } from "@/lib/types";
import { t } from "@/lib/i18n";

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
      toast.success(t("Scheduled ride cancelled"));
      qc.invalidateQueries({ queryKey: ["scheduled-rides"] });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t("Couldn't cancel.")),
  });
  const rides = upcoming.data?.results ?? [];
  if (!rides.length) return null;
  return (
    <div className="mb-3 px-2">
      <h2 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{t("Upcoming")}</h2>
      {rides.map((ride) => (
        <div key={ride.id} className="mb-2 flex items-center gap-3 rounded-2xl border border-line p-3">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-brand-soft text-brand-strong">
            <CalendarClock className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="font-semibold">{formatWhen(new Date(ride.scheduled_for))}</div>
            <div className="truncate text-xs text-muted">
              {t("{ride} to {place} · about {fare}", { ride: ride.ride_type_name, place: ride.dropoff.address || t("your destination"), fare: inr(ride.quoted_fare) })}
            </div>
            {ride.metro_trip && (
              <button className="mt-1 rounded-full bg-brand px-3 py-1 text-xs font-semibold text-on-brand" onClick={() =>
                  api.post(`scheduled-rides/${ride.id}/at-station/`).then(
                    () => {
                      toast.success(t("Finding your driver"));
                      void qc.invalidateQueries({ queryKey: ["scheduled-rides"] });
                    },
                    (e) => toast.error(e instanceof ApiError ? e.message : t("Something went wrong.")),
                  )
                }>
                {t("I'm at the station: send my ride")}
              </button>
            )}
            {ride.flight_number && (
              <div className="text-xs text-brand">{t("Following flight {flight}", { flight: ride.flight_number })}{ride.flight_status ? ` · ${t(ride.flight_status)}` : ""}</div>
            )}
          </div>
          <Button size="sm" variant="outline" loading={cancel.isPending && cancel.variables === ride.id} onClick={() => cancel.mutate(ride.id)}>
            {t("Cancel")}
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
        {base === "/ride" && <SplitRequests />}
        {base === "/ride" && <Upcoming />}
        {trips.isLoading &&
          [0, 1, 2, 3].map((i) => <Skeleton key={i} className="mx-2 mb-3 h-20" />)}
        {!trips.isLoading && results.length === 0 && (
          <EmptyState icon={<Clock />} title={t("No trips yet")}>
            {t("Your past rides will show up here.")}
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
            {t("Newer")}
          </Button>
          <Button size="sm" variant="outline" disabled={!trips.data.next} onClick={() => setPage((p) => p + 1)}>
            {t("Older")}
          </Button>
        </div>
      )}
    </div>
  );
}
