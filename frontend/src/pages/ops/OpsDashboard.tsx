import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  BadgeIndianRupee,
  CarTaxiFront,
  CheckCircle2,
  Clock,
  Expand,
  Hourglass,
  Percent,
  Radio,
  ShieldAlert,
  TrendingUp,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { Badge, Card, CardHeader, PageHeader, Segmented, Stat, Table, Td, Th } from "@/components/ui";
import { useOps } from "@/layouts/OpsLayout";
import { api } from "@/lib/api";
import { ago, inr, inrCompact, num } from "@/lib/format";
import type { Breakdown, Incident, Overview, Paginated, SeriesPoint, Ticket } from "@/lib/types";

import { HourlyChart, RideTypeDonut, TripsChart } from "./charts";
import { LiveMap, useLiveOps } from "./LiveMap";

export default function OpsDashboard() {
  const { city, cityInfo } = useOps();
  const [days, setDays] = useState<"1" | "7" | "30">("1");
  const qs = `city=${city}&days=${days}`;
  const overview = useQuery({ queryKey: ["analytics", "overview", qs], queryFn: () => api.get<Overview>(`analytics/overview/?${qs}`), refetchInterval: 10_000 });
  const series = useQuery({ queryKey: ["analytics", "series", qs], queryFn: () => api.get<{ unit: string; series: SeriesPoint[] }>(`analytics/timeseries/?${qs}`), refetchInterval: 60_000 });
  const breakdown = useQuery({ queryKey: ["analytics", "breakdown", qs], queryFn: () => api.get<Breakdown>(`analytics/breakdown/?${qs}`), refetchInterval: 60_000 });
  const live = useLiveOps(city);
  const sos = useQuery({ queryKey: ["incidents", "open"], queryFn: () => api.get<Paginated<Incident>>("safety/incidents/?status=OPEN"), refetchInterval: 10_000, retry: false });
  const tickets = useQuery({ queryKey: ["tickets", "escalated"], queryFn: () => api.get<Paginated<Ticket>>("support/tickets/?status=OPEN&ordering=sla_due_at&page_size=5"), retry: false });

  const k = overview.data?.kpis;
  const l = overview.data?.live;
  const period = days === "1" ? "last 24 hours" : `last ${days} days`;

  return (
    <>
      <PageHeader
        title={`Operations · ${cityInfo?.name ?? "All cities"}`}
        subtitle={`Marketplace health for the ${period}`}
        actions={
          <Segmented
            value={days}
            onChange={setDays}
            options={[
              { value: "1", label: "24 h" },
              { value: "7", label: "7 days" },
              { value: "30", label: "30 days" },
            ]}
          />
        }
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        <Stat label="Trips requested" value={num(k?.requested)} icon={<Activity className="size-4" />} tone="info" sub={`${num(k?.completed)} completed`} />
        <Stat label="Completion rate" value={k?.completion_rate != null ? `${k.completion_rate}%` : "—"} icon={<CheckCircle2 className="size-4" />} tone="brand" sub={`${num(k?.no_driver_found)} unfulfilled`} />
        <Stat label="Gross bookings" value={inrCompact(k?.gmv)} icon={<BadgeIndianRupee className="size-4" />} tone="brand" sub={`Net revenue ${inrCompact(k?.net_revenue)}`} />
        <Stat label="Avg wait for driver" value={k?.avg_wait_min != null ? `${k.avg_wait_min} min` : "—"} icon={<Hourglass className="size-4" />} tone="warning" sub={`Pickup ${k?.avg_pickup_min ?? "—"} min`} />
        <Stat label="Drivers live" value={num((l?.drivers_online ?? 0) + (l?.drivers_on_trip ?? 0))} icon={<CarTaxiFront className="size-4" />} sub={`${l?.drivers_on_trip ?? 0} on trip · ${l?.utilisation ?? 0}% busy`} />
        <Stat label="Avg surge" value={k?.avg_surge ? `${k.avg_surge}×` : "1.0×"} icon={<TrendingUp className="size-4" />} tone="warning" sub={`Avg fare ${inr(k?.avg_fare)}`} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <Card className="overflow-hidden">
          <CardHeader
            title={
              <span className="flex items-center gap-2">
                Live map
                <Badge tone={live.connected ? "brand" : "neutral"}>
                  <Radio className="size-3" /> {live.connected ? "real-time" : "polling"}
                </Badge>
              </span>
            }
            subtitle={`${live.data?.drivers.length ?? 0} drivers · ${live.data?.trips.length ?? 0} active trips`}
            action={
              <Link to="/ops/live" className="flex items-center gap-1 text-xs font-semibold text-muted hover:text-fg">
                <Expand className="size-3.5" /> Full screen
              </Link>
            }
          />
          <div className="h-[380px]">
            <LiveMap city={city} cityInfo={cityInfo} data={live.data} interactive />
          </div>
        </Card>

        <div className="grid gap-4">
          <Card>
            <CardHeader title="Requests vs completed" subtitle={series.data?.unit === "hour" ? "Per hour" : "Per day"} />
            <div className="h-56 p-3">{series.data && <TripsChart series={series.data.series} unit={series.data.unit} />}</div>
          </Card>
          <Card>
            <CardHeader title="Needs attention" />
            <div className="divide-y divide-line">
              {(sos.data?.results ?? []).map((incident) => (
                <Link key={incident.id} to={`/ops/safety/${incident.id}`} className="flex items-center gap-3 px-5 py-3 hover:bg-surface-2">
                  <ShieldAlert className="size-5 text-danger" />
                  <div className="flex-1">
                    <div className="text-sm font-semibold">SOS on {incident.trip_number}</div>
                    <div className="text-xs text-muted">
                      {incident.raised_by} · {ago(incident.created_at)}
                    </div>
                  </div>
                  <Badge tone="danger">Open</Badge>
                </Link>
              ))}
              {(tickets.data?.results ?? []).map((t) => (
                <Link key={t.id} to={`/ops/support/${t.id}`} className="flex items-center gap-3 px-5 py-3 hover:bg-surface-2">
                  <Clock className="size-5 text-amber-500" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold">{t.subject}</div>
                    <div className="text-xs text-muted">
                      {t.ticket_number} · SLA {ago(t.sla_due_at).replace(" ago", " overdue")}
                    </div>
                  </div>
                  <Badge tone={t.priority === "URGENT" ? "danger" : t.priority === "HIGH" ? "warning" : "info"}>{t.priority.toLowerCase()}</Badge>
                </Link>
              ))}
              {!sos.data?.results.length && !tickets.data?.results.length && <p className="px-5 py-6 text-center text-sm text-muted">Nothing urgent. 🎉</p>}
            </div>
          </Card>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader title="Ride type mix" subtitle="Completed trips" />
          <div className="h-60 p-3">{breakdown.data && <RideTypeDonut data={breakdown.data.ride_types} />}</div>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader title="Demand by hour of day" subtitle="Peaks drive surge pricing" />
          <div className="h-60 p-3">{breakdown.data && <HourlyChart data={breakdown.data.hourly} />}</div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Zones" subtitle="Where demand comes from" action={<Link to="/ops/analytics" className="text-xs font-semibold text-muted hover:text-fg">More →</Link>} />
          <Table>
            <thead>
              <tr>
                <Th>Zone</Th>
                <Th className="text-right">Requests</Th>
                <Th className="text-right">Fulfilled</Th>
                <Th className="text-right">Avg surge</Th>
                <Th className="text-right">Avg wait</Th>
              </tr>
            </thead>
            <tbody>
              {(breakdown.data?.zones ?? []).slice(0, 8).map((z) => (
                <tr key={`${z.city}-${z.zone}`}>
                  <Td>
                    <div className="font-medium">{z.zone}</div>
                    <div className="text-xs text-muted">{z.city}</div>
                  </Td>
                  <Td className="text-right">{num(z.requests)}</Td>
                  <Td className="text-right">{z.fulfilment ?? "—"}%</Td>
                  <Td className="text-right">{z.avg_surge}×</Td>
                  <Td className="text-right">{z.avg_wait_min ?? "—"} min</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
        <Card>
          <CardHeader title="Top drivers" subtitle={`By earnings, ${period}`} />
          <Table>
            <thead>
              <tr>
                <Th>Driver</Th>
                <Th className="text-right">Trips</Th>
                <Th className="text-right">Earned</Th>
                <Th className="text-right">Rating</Th>
                <Th className="text-right">
                  <Percent className="inline size-3" /> Safety
                </Th>
              </tr>
            </thead>
            <tbody>
              {(breakdown.data?.leaderboard ?? []).slice(0, 8).map((d) => (
                <tr key={d.driver_id}>
                  <Td>
                    <Link to={`/ops/drivers/${d.driver_id}`} className="font-medium hover:underline">
                      {d.name}
                    </Link>
                  </Td>
                  <Td className="text-right">{d.trips}</Td>
                  <Td className="text-right">{inr(d.earnings, { whole: true })}</Td>
                  <Td className="text-right">{Number(d.rating).toFixed(2)}</Td>
                  <Td className="text-right">{d.safety_score ?? "—"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      </div>
    </>
  );
}
