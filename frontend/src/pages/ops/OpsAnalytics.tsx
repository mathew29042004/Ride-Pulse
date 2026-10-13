import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";

import { Button, Card, CardHeader, PageHeader, Segmented, Stat, Table, Td, Th } from "@/components/ui";
import { useOps } from "@/layouts/OpsLayout";
import { api, openFile } from "@/lib/api";
import { inr, inrCompact, num } from "@/lib/format";
import type { Breakdown, Overview, SeriesPoint } from "@/lib/types";

import { GmvChart, HourlyChart, RideTypeDonut, TripsChart } from "./charts";
import { LiveMap } from "./LiveMap";

export default function OpsAnalytics() {
  const { city, cityInfo } = useOps();
  const [days, setDays] = useState<"7" | "30" | "90">("30");
  const qs = `city=${city}&days=${days}`;
  const overview = useQuery({ queryKey: ["analytics", "overview", qs], queryFn: () => api.get<Overview>(`analytics/overview/?${qs}`) });
  const series = useQuery({ queryKey: ["analytics", "series", qs], queryFn: () => api.get<{ unit: string; series: SeriesPoint[] }>(`analytics/timeseries/?${qs}`) });
  const breakdown = useQuery({ queryKey: ["analytics", "breakdown", qs], queryFn: () => api.get<Breakdown>(`analytics/breakdown/?${qs}`) });
  const k = overview.data?.kpis;

  return (
    <>
      <PageHeader
        title={`Analytics · ${cityInfo?.name ?? "All cities"}`}
        subtitle="Aggregated in PostgreSQL: generate_series() time buckets, FILTER clauses and geohash cells"
        actions={
          <>
            <Segmented
              value={days}
              onChange={setDays}
              options={[
                { value: "7", label: "7 days" },
                { value: "30", label: "30 days" },
                { value: "90", label: "90 days" },
              ]}
            />
            <Button variant="outline" icon={<Download className="size-4" />} onClick={() => openFile(`/api/v1/analytics/trips.csv?${qs}`)}>
              CSV
            </Button>
          </>
        }
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Gross bookings" value={inrCompact(k?.gmv)} tone="brand" />
        <Stat label="Net revenue" value={inrCompact(k?.net_revenue)} sub={`Commission ${inrCompact(k?.commission)}`} />
        <Stat label="Driver earnings" value={inrCompact(k?.driver_earnings)} sub={`Tips ${inrCompact(k?.tips)}`} />
        <Stat label="Completed trips" value={num(k?.completed)} sub={`${k?.completion_rate ?? "—"}% of ${num(k?.requested)}`} tone="info" />
        <Stat label="Rider cancellations" value={num(k?.cancelled_by_rider)} sub={`${num(k?.no_driver_found)} no driver found`} tone="warning" />
        <Stat label="Driver-hours online" value={num(overview.data?.driver_hours_online)} sub={`Avg fare ${inr(k?.avg_fare)}`} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Trips" subtitle="Requested vs completed" />
          <div className="h-64 p-3">{series.data && <TripsChart series={series.data.series} unit={series.data.unit} />}</div>
        </Card>
        <Card>
          <CardHeader title="Gross bookings" subtitle="Completed fares incl. GST" />
          <div className="h-64 p-3">{series.data && <GmvChart series={series.data.series} unit={series.data.unit} />}</div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.3fr_1fr]">
        <Card className="overflow-hidden">
          <CardHeader title="Demand heatmap" subtitle="Ride requests per ~1 km geohash cell" />
          <div className="h-96">
            <LiveMap city={city} cityInfo={cityInfo} heat={breakdown.data?.heatmap} />
          </div>
        </Card>
        <div className="grid gap-4">
          <Card>
            <CardHeader title="Ride types" />
            <div className="h-44 p-2">{breakdown.data && <RideTypeDonut data={breakdown.data.ride_types} />}</div>
          </Card>
          <Card>
            <CardHeader title="Demand by hour" />
            <div className="h-44 p-2">{breakdown.data && <HourlyChart data={breakdown.data.hourly} />}</div>
          </Card>
        </div>
      </div>

      <Card className="mt-4">
        <CardHeader title="Zone performance" subtitle="Fulfilment = completed ÷ requested. Low fulfilment with high surge means too few drivers." />
        <Table>
          <thead>
            <tr>
              <Th>Zone</Th>
              <Th>City</Th>
              <Th className="text-right">Requests</Th>
              <Th className="text-right">Completed</Th>
              <Th className="text-right">Fulfilment</Th>
              <Th className="text-right">Avg surge</Th>
              <Th className="text-right">Avg wait</Th>
              <Th className="text-right">GMV</Th>
            </tr>
          </thead>
          <tbody>
            {breakdown.data?.zones.map((z) => (
              <tr key={`${z.city}-${z.zone}`}>
                <Td className="font-medium">{z.zone}</Td>
                <Td>{z.city}</Td>
                <Td className="text-right">{num(z.requests)}</Td>
                <Td className="text-right">{num(z.completed)}</Td>
                <Td className="text-right">{z.fulfilment ?? "—"}%</Td>
                <Td className="text-right">{z.avg_surge}×</Td>
                <Td className="text-right">{z.avg_wait_min ?? "—"} min</Td>
                <Td className="text-right">{inr(z.gmv, { whole: true })}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </>
  );
}
