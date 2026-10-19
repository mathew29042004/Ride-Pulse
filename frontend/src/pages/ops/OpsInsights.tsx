/**
 * Data insights: the data platform's latest results (Parquet lake → DuckDB/dbt warehouse →
 * report), published by the nightly pipeline. Separate from Analytics, which reads live data.
 */

import { useQuery } from "@tanstack/react-query";
import { Database, IndianRupee, Leaf, MapPinned, Package, Route } from "lucide-react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Card, CardHeader, EmptyState, PageHeader, Stat, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime, inr, inrCompact } from "@/lib/format";

type Row = Record<string, string | number | null>;

interface Insights {
  available: boolean;
  message?: string;
  generated_at?: string;
  headline?: {
    requests: number;
    completed: number;
    gross_bookings: string;
    commission: string;
    driver_earnings: string;
    cities: number;
    first_day: string;
    last_day: string;
    parcels: number;
    co2_saved_tonnes: string;
  };
  daily?: Row[];
  cities?: Row[];
  states?: Row[];
  hours?: Row[];
  no_driver_hotspots?: Row[];
  driver_earnings?: Row[];
  support?: Row[];
  team?: Row[];
}

const axis = { fill: "var(--color-muted)", fontSize: 11 };
const tooltipStyle = { background: "var(--color-surface)", border: "1px solid var(--color-line)", borderRadius: 12, fontSize: 12, color: "var(--color-fg)" };
const pct = (v: unknown) => `${(Number(v) * 100).toFixed(1)}%`;
const num = (v: unknown) => Number(v ?? 0).toLocaleString("en-IN");

export default function OpsInsights() {
  const insights = useQuery({ queryKey: ["analytics", "warehouse"], queryFn: () => api.get<Insights>("analytics/warehouse/") });
  const data = insights.data;

  if (data && !data.available) {
    return (
      <>
        <PageHeader title="Data insights" subtitle="Results from the data platform (lake → warehouse → reports)." />
        <Card>
          <EmptyState icon={<Database />} title="No pipeline run yet">
            {data.message}
          </EmptyState>
        </Card>
      </>
    );
  }
  const h = data?.headline;
  const states = Object.values(
    (data?.states ?? []).reduce<Record<string, Row>>((acc, row) => {
      const key = String(row.state);
      acc[key] = acc[key] ?? { state: key };
      acc[key][String(row.service)] = Number(row.requests);
      return acc;
    }, {}),
  );

  return (
    <>
      <PageHeader
        title="Data insights"
        subtitle={
          h
            ? `From the data platform: ${h.first_day} to ${h.last_day} (IST) · refreshed ${dateTime(data?.generated_at)} · simulated data`
            : "Loading…"
        }
      />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Trip requests" value={h ? num(h.requests) : "—"} sub={h ? `${pct(h.completed / Math.max(h.requests, 1))} completed` : ""} icon={<Route className="size-4" />} tone="brand" />
        <Stat label="Gross bookings" value={h ? inrCompact(h.gross_bookings) : "—"} sub={h ? `${inrCompact(h.commission)} commission` : ""} icon={<IndianRupee className="size-4" />} tone="info" />
        <Stat label="Paid to drivers" value={h ? inrCompact(h.driver_earnings) : "—"} sub="incl. tips" icon={<IndianRupee className="size-4" />} />
        <Stat label="Cities" value={h?.cities ?? "—"} sub={h ? `${num(h.parcels)} parcels` : ""} icon={<MapPinned className="size-4" />} />
        <Stat label="CO₂ saved" value={h ? `${h.co2_saved_tonnes} t` : "—"} sub="vs driving your own car" icon={<Leaf className="size-4" />} tone="brand" />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Daily requests and completions" />
          <div className="h-64 px-2 pb-3">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data?.daily ?? []}>
                <CartesianGrid stroke="var(--color-line)" vertical={false} />
                <XAxis dataKey="date" tick={axis} tickFormatter={(d) => new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} minTickGap={24} />
                <YAxis tick={axis} width={40} />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend />
                <Area type="monotone" dataKey="requests" name="Requests" stroke="#0ea5e9" fill="#0ea5e9" fillOpacity={0.15} />
                <Area type="monotone" dataKey="completed" name="Completed" stroke="#6366f1" fill="#6366f1" fillOpacity={0.25} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card>
          <CardHeader title="Requests by hour of day (IST)" subtitle="Bars: requests · the no-driver rate is in the tooltip" />
          <div className="h-64 px-2 pb-3">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data?.hours ?? []}>
                <CartesianGrid stroke="var(--color-line)" vertical={false} />
                <XAxis dataKey="hour" tick={axis} tickFormatter={(v) => `${v}h`} />
                <YAxis tick={axis} width={40} />
                <Tooltip contentStyle={tooltipStyle} formatter={(v, name) => (name === "No driver" ? pct(v) : num(v))} labelFormatter={(v) => `${v}:00`} />
                <Bar dataKey="requests" name="Requests" fill="#6366f1" radius={[4, 4, 0, 0]} />
                <Bar dataKey="no_driver_rate" name="No driver" fill="transparent" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card>
          <CardHeader title="Service mix by state" subtitle="Requests per service" />
          <div className="h-64 px-2 pb-3">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={states} layout="vertical">
                <CartesianGrid stroke="var(--color-line)" horizontal={false} />
                <XAxis type="number" tick={axis} />
                <YAxis type="category" dataKey="state" tick={axis} width={100} />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend />
                <Bar dataKey="RIDE" name="Rides" stackId="s" fill="#6366f1" />
                <Bar dataKey="PARCEL" name="Parcels" stackId="s" fill="#f59e0b" />
                <Bar dataKey="RENTAL" name="Rentals" stackId="s" fill="#6366f1" />
                <Bar dataKey="INTERCITY" name="Intercity" stackId="s" fill="#0ea5e9" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card>
          <CardHeader title="Driver earnings per online hour" subtitle="Median across driver-weeks, by vehicle and fuel" />
          <Table>
            <thead>
              <tr>
                <Th>Vehicle</Th>
                <Th>Fuel</Th>
                <Th className="text-right">Drivers</Th>
                <Th className="text-right">₹ / hour</Th>
                <Th className="text-right">Trips / week</Th>
              </tr>
            </thead>
            <tbody>
              {(data?.driver_earnings ?? []).map((r) => (
                <tr key={`${r.vehicle_class}-${r.fuel}`} className="border-t border-line">
                  <Td>{r.vehicle_class}</Td>
                  <Td>{r.fuel}</Td>
                  <Td className="text-right">{r.drivers}</Td>
                  <Td className="text-right font-semibold">{inr(r.median_per_hour ?? 0)}</Td>
                  <Td className="text-right">{r.median_trips_per_week}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card className="overflow-hidden">
          <CardHeader title="Cities" subtitle="Ranked by gross bookings" />
          <div className="max-h-96 overflow-y-auto">
            <Table>
              <thead>
                <tr>
                  <Th>City</Th>
                  <Th className="text-right">Requests</Th>
                  <Th className="text-right">Completion</Th>
                  <Th className="text-right">Avg pickup</Th>
                  <Th className="text-right">Gross bookings</Th>
                </tr>
              </thead>
              <tbody>
                {(data?.cities ?? []).map((r) => (
                  <tr key={String(r.city)} className="border-t border-line">
                    <Td>
                      <div className="font-semibold">{r.city}</div>
                      <div className="text-xs text-muted">{r.state}</div>
                    </Td>
                    <Td className="text-right">{num(r.requests)}</Td>
                    <Td className="text-right">{pct(r.completion_rate)}</Td>
                    <Td className="text-right">{r.avg_pickup_minutes ?? "—"} min</Td>
                    <Td className="text-right font-semibold">{inrCompact(r.gross_bookings ?? 0)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        </Card>
        <div className="space-y-4">
          <Card>
            <CardHeader title="Where riders found no driver" subtitle="Highest no-driver rates (30+ requests)" />
            <Table>
              <tbody>
                {(data?.no_driver_hotspots ?? []).slice(0, 6).map((r) => (
                  <tr key={`${r.city}-${r.ride_type}`} className="border-t border-line">
                    <Td>
                      {r.city} · {r.ride_type}
                    </Td>
                    <Td className="text-right text-danger">{pct(r.rate)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
          <Card>
            <CardHeader title="Team coverage" subtitle="Driver partners per fleet executive" />
            <Table>
              <tbody>
                {(data?.team ?? []).map((r) => (
                  <tr key={String(r.state)} className="border-t border-line">
                    <Td>{r.state}</Td>
                    <Td className="text-right">{num(r.drivers)} drivers</Td>
                    <Td className="text-right">{(Number(r.drivers) / Math.max(Number(r.fleet_executives), 1)).toFixed(1)} each</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
          <Card>
            <CardHeader title="Support" subtitle="Tickets resolved within SLA" />
            <Table>
              <tbody>
                {(data?.support ?? []).map((r) => (
                  <tr key={String(r.category)} className="border-t border-line">
                    <Td>
                      <Package className="mr-1 inline size-3.5 text-muted" />
                      {String(r.category).replaceAll("_", " ").toLowerCase()}
                    </Td>
                    <Td className="text-right">{num(r.tickets)}</Td>
                    <Td className="text-right">{Number(r.resolved) ? pct(Number(r.within_sla) / Number(r.resolved)) : "—"}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        </div>
      </div>
    </>
  );
}
