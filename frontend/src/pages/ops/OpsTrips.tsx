import { useQuery } from "@tanstack/react-query";
import { Download, Flag, Search } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { Badge, Button, Card, Input, PageHeader, Pagination, Select, StatusBadge, Table, Td, Th } from "@/components/ui";
import { useOps } from "@/layouts/OpsLayout";
import { api, openFile } from "@/lib/api";
import { dateTime, inr, km } from "@/lib/format";
import type { Paginated, Trip } from "@/lib/types";

const STATUSES = ["", "REQUESTED", "DRIVER_ASSIGNED", "DRIVER_ARRIVED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "NO_DRIVER_FOUND"];

export default function OpsTrips() {
  const { city } = useOps();
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [rideType, setRideType] = useState("");
  const [flagged, setFlagged] = useState(false);
  const [search, setSearch] = useState("");
  const qs = new URLSearchParams({ page: String(page), ordering: "-requested_at", city, status, ride_type: rideType, search, ...(flagged ? { flagged: "true" } : {}) });
  const trips = useQuery({ queryKey: ["trips", "ops", qs.toString()], queryFn: () => api.get<Paginated<Trip>>(`trips/?${qs}`), refetchInterval: 15_000 });

  return (
    <>
      <PageHeader
        title="Trips"
        subtitle="Every booking across the platform"
        actions={
          <Button variant="outline" icon={<Download className="size-4" />} onClick={() => openFile(`/api/v1/analytics/trips.csv?city=${city}&days=30`)}>
            Export CSV (30 days)
          </Button>
        }
      />
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <div className="relative min-w-56 flex-1">
            <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
            <Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Trip number, address or email" className="pl-9" />
          </div>
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className="!w-48">
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s ? s.replace(/_/g, " ").toLowerCase() : "All statuses"}
              </option>
            ))}
          </Select>
          <Select value={rideType} onChange={(e) => { setRideType(e.target.value); setPage(1); }} className="!w-36">
            <option value="">All types</option>
            {["BIKE", "AUTO", "MINI", "SEDAN", "SUV"].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </Select>
          <Button variant={flagged ? "primary" : "outline"} icon={<Flag className="size-4" />} onClick={() => { setFlagged((f) => !f); setPage(1); }}>
            Flagged
          </Button>
        </div>
        <Table>
          <thead>
            <tr>
              <Th>Trip</Th>
              <Th>Route</Th>
              <Th>Rider · Driver</Th>
              <Th>Status</Th>
              <Th className="text-right">Fare</Th>
            </tr>
          </thead>
          <tbody>
            {trips.data?.results.map((t) => (
              <tr key={t.id} onClick={() => navigate(`/ops/trips/${t.id}`)} className="cursor-pointer hover:bg-surface-2">
                <Td>
                  <Link to={`/ops/trips/${t.id}`} className="font-semibold hover:underline">
                    {t.trip_number}
                  </Link>
                  <div className="text-xs text-muted">
                    {dateTime(t.requested_at)} · {t.ride_type_name}
                  </div>
                </Td>
                <Td>
                  <div className="max-w-64 truncate">{t.pickup_address}</div>
                  <div className="max-w-64 truncate text-xs text-muted">→ {t.dropoff_address}</div>
                </Td>
                <Td>
                  <div>{t.rider.name}</div>
                  <div className="text-xs text-muted">{t.driver?.name ?? "—"}</div>
                </Td>
                <Td>
                  <StatusBadge status={t.status} label={t.status_label} />
                  {t.flags.map((f) => (
                    <Badge key={f} tone="danger" className="ml-1">
                      {f.replace(/_/g, " ").toLowerCase()}
                    </Badge>
                  ))}
                </Td>
                <Td className="text-right">
                  <div className="font-semibold">{inr(t.fare_total ?? t.estimated_fare)}</div>
                  <div className="text-xs text-muted">
                    {km(t.actual_distance_km ?? t.estimated_distance_km)}
                    {Number(t.surge_multiplier) > 1 && ` · ${t.surge_multiplier}×`}
                  </div>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
        {trips.data && <Pagination page={page} count={trips.data.count} onChange={setPage} />}
      </Card>
    </>
  );
}
