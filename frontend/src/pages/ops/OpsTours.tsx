/**
 * Ops: tour packages. The catalogue by city with bookings, revenue and ratings (pause a tour or
 * set a seasonal price), and the next 7 days of tours with their assigned drivers.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { AlertTriangle, Landmark, Star } from "lucide-react";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, PageHeader, Stat, Table, Td, Th } from "@/components/ui";
import { useOps } from "@/layouts/OpsLayout";
import { api, ApiError } from "@/lib/api";
import { dateTime, inr } from "@/lib/format";

interface Row {
  slug: string;
  name: string;
  city_name: string;
  category_label: string;
  days: number;
  stops: unknown[];
  from_price: string;
  hours: number;
  rating: number | null;
  rating_count: number;
  price_adjust_percent: number;
  is_active: boolean;
  bookings: number;
  completed: number;
  upcoming: number;
  revenue: string;
}
interface Upcoming {
  id: number;
  reference: string;
  package: { name: string; city_name: string };
  depart_at: string;
  ride_type: string;
  group_size: number;
  price: string;
  status: string;
  status_label: string;
  driver: { name: string; rating: string; vehicle: string } | null;
  rider: { name: string } | null;
}
interface Overview {
  packages: Row[];
  upcoming: Upcoming[];
  unassigned_24h: number;
  completed_30d: number;
  revenue_30d: string;
  cancelled_30d: number;
}

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "Something went wrong.");

export default function OpsTours() {
  const { cityInfo } = useOps();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["ops", "tours", cityInfo?.id], queryFn: () => api.get<Overview>(`ops/tours/overview/${cityInfo ? `?city=${cityInfo.id}` : ""}`), refetchInterval: 30_000 });
  const refresh = () => qc.invalidateQueries({ queryKey: ["ops", "tours"] });
  const update = useMutation({
    mutationFn: ({ slug, ...body }: { slug: string; is_active?: boolean; price_adjust_percent?: number }) => api.post(`ops/tours/packages/${slug}/`, body),
    onSuccess: () => {
      toast.success("Tour updated");
      refresh();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const assign = useMutation({
    mutationFn: (id: number) => api.post<{ status: string }>(`ops/tours/bookings/${id}/assign/`),
    onSuccess: (r) => {
      toast[r.status === "ASSIGNED" ? "success" : "error"](r.status === "ASSIGNED" ? "Driver assigned" : "No suitable driver free that day yet");
      refresh();
    },
  });
  const d = q.data;
  const packages = (d?.packages ?? []).slice().sort((a, b) => b.bookings - a.bookings);
  return (
    <>
      <PageHeader title={`Tours · ${cityInfo?.name ?? "All cities"}`} subtitle="Day trips and short tours at a fixed price per car. A top-rated driver with a road-worthy car is assigned the day before; if they don't start 15 minutes before departure, the tour goes to normal dispatch at the same price." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Tour packages" value={d ? packages.filter((p) => p.is_active).length : "—"} sub={d ? `${packages.length - packages.filter((p) => p.is_active).length} paused` : ""} icon={<Landmark className="size-4" />} tone="brand" />
        <Stat label="Completed (30 d)" value={d?.completed_30d ?? "—"} sub={d ? `${inr(d.revenue_30d, { whole: true })} in fares` : ""} />
        <Stat label="Next 7 days" value={d?.upcoming.length ?? "—"} sub={d ? `${d.cancelled_30d} cancelled in 30 d` : ""} tone="info" />
        <Stat label="No driver yet (24 h)" value={d?.unassigned_24h ?? "—"} tone={d?.unassigned_24h ? "danger" : "neutral"} icon={<AlertTriangle className="size-4" />} />
      </div>

      <Card className="mt-4 overflow-x-auto">
        <div className="p-4 pb-0">
          <CardHeader title="Next 7 days" />
        </div>
        <Table>
          <thead>
            <tr>
              <Th>Departs</Th>
              <Th>Tour</Th>
              <Th>Traveller</Th>
              <Th>Car</Th>
              <Th>Driver</Th>
              <Th className="text-right">Price</Th>
            </tr>
          </thead>
          <tbody>
            {(d?.upcoming ?? []).map((b) => (
              <tr key={b.id} className="border-t border-line">
                <Td className="whitespace-nowrap">{dateTime(b.depart_at)}</Td>
                <Td>
                  <div className="font-semibold">{b.package.name}</div>
                  <div className="text-xs text-muted">
                    {b.reference} · {b.package.city_name}
                  </div>
                </Td>
                <Td>
                  {b.rider?.name ?? "—"}
                  <div className="text-xs text-muted">{b.group_size} people</div>
                </Td>
                <Td>{b.ride_type}</Td>
                <Td>
                  {b.driver ? (
                    <>
                      {b.driver.name} <span className="text-xs text-muted">{b.driver.rating}★</span>
                      <div className="text-xs text-muted">{b.driver.vehicle}</div>
                    </>
                  ) : (
                    <div className="flex items-center gap-2">
                      <Badge tone="warning">{b.status === "STARTED" ? "Dispatching" : "Unassigned"}</Badge>
                      {b.status === "BOOKED" && (
                        <Button size="sm" variant="outline" onClick={() => assign.mutate(b.id)}>
                          Find driver
                        </Button>
                      )}
                    </div>
                  )}
                </Td>
                <Td className="text-right">{inr(b.price, { whole: true })}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
        {d?.upcoming.length === 0 && <p className="p-4 text-sm text-muted">No tours in the next 7 days.</p>}
      </Card>

      <Card className="mt-4 overflow-x-auto">
        <div className="p-4 pb-0">
          <CardHeader title="Catalogue" subtitle="Most booked first. Seasonal price: −30% to +50% on the route and time charges." />
        </div>
        <Table>
          <thead>
            <tr>
              <Th>Tour</Th>
              <Th className="text-right">From</Th>
              <Th className="text-right">Booked</Th>
              <Th className="text-right">Upcoming</Th>
              <Th className="text-right">Revenue</Th>
              <Th>Rating</Th>
              <Th>Season</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {packages.map((p) => (
              <tr key={p.slug} className={clsx("border-t border-line", !p.is_active && "opacity-50")}>
                <Td>
                  <div className="font-semibold">{p.name}</div>
                  <div className="text-xs text-muted">
                    {p.city_name} · {p.category_label} · {p.stops.length} stops · {p.days > 1 ? `${p.days} days` : `${Math.round(p.hours)} h`}
                  </div>
                </Td>
                <Td className="text-right">{inr(p.from_price, { whole: true })}</Td>
                <Td className="text-right">{p.bookings}</Td>
                <Td className="text-right">{p.upcoming}</Td>
                <Td className="text-right">{inr(p.revenue, { whole: true })}</Td>
                <Td>
                  {p.rating ? (
                    <span className="flex items-center gap-1">
                      <Star className="size-3.5 fill-amber-400 text-amber-400" />
                      {p.rating.toFixed(1)} <span className="text-xs text-muted">({p.rating_count})</span>
                    </span>
                  ) : (
                    <span className="text-xs text-muted">New</span>
                  )}
                </Td>
                <Td>
                  <select
                    value={p.price_adjust_percent}
                    onChange={(e) => update.mutate({ slug: p.slug, price_adjust_percent: Number(e.target.value) })}
                    className="rounded-lg border border-line bg-surface px-2 py-1 text-xs"
                    aria-label={`Seasonal price for ${p.name}`}
                  >
                    {[-30, -20, -10, 0, 10, 20, 30, 50].map((v) => (
                      <option key={v} value={v}>
                        {v > 0 ? `+${v}%` : v === 0 ? "Normal" : `${v}%`}
                      </option>
                    ))}
                  </select>
                </Td>
                <Td>
                  <Button size="sm" variant="ghost" onClick={() => update.mutate({ slug: p.slug, is_active: !p.is_active })}>
                    {p.is_active ? "Pause" : "Resume"}
                  </Button>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </>
  );
}
