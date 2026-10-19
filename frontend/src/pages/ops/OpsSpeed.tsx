/** Ops → Speeding: drivers warned for speeding this week (repeat offenders first) and the slow
 * zones near schools, hospitals and markets. */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { Badge, Card, CardHeader, PageHeader, Stat } from "@/components/ui";
import { api } from "@/lib/api";

interface Data {
  days: number;
  alerts: number;
  in_slow_zones: number;
  drivers: number;
  zones: number;
  top_drivers: { driver_id: number; name: string; city: string; alerts: number }[];
  top_zones: { name: string; kind: string; alerts: number }[];
  zone_list: { id: number; name: string; kind: string; city: string; limit_kmh: number; radius_m: number }[];
}

export default function OpsSpeed() {
  const q = useQuery({ queryKey: ["speed"], queryFn: () => api.get<Data>("ops/speed/") });
  const d = q.data;
  return (
    <>
      <PageHeader title="Speeding" subtitle="Drivers are warned live when they go more than 10% over the limit: 60 km/h in town (autos 45, bikes 50), 25 km/h near schools on school days, 30 km/h near hospitals and markets." />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card className="p-3"><Stat label="Warnings (7 days)" value={d?.alerts ?? "—"} /></Card>
        <Card className="p-3"><Stat label="In slow zones" value={d?.in_slow_zones ?? "—"} /></Card>
        <Card className="p-3"><Stat label="Drivers warned" value={d?.drivers ?? "—"} /></Card>
        <Card className="p-3"><Stat label="Slow zones" value={d?.zones ?? "—"} /></Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <CardHeader title="Repeat offenders" />
          {d?.top_drivers.map((r) => (
            <div key={r.driver_id} className="flex justify-between border-b border-line py-1.5 text-sm last:border-0">
              <Link className="hover:underline" to={`/ops/drivers/${r.driver_id}`}>{r.name} <span className="text-xs text-muted">{r.city}</span></Link>
              <Badge tone={r.alerts >= 5 ? "danger" : "warning"}>{r.alerts}</Badge>
            </div>
          ))}
        </Card>
        <Card className="p-4">
          <CardHeader title="Where it happens most" />
          {d?.top_zones.map((z) => (
            <div key={z.name} className="flex justify-between py-1 text-sm"><span>{z.name} <span className="text-xs text-muted">{z.kind.toLowerCase()}</span></span><span>{z.alerts}</span></div>
          ))}
          <div className="mt-3 max-h-64 overflow-y-auto text-xs text-muted">
            {d?.zone_list.map((z) => <div key={z.id}>{z.city} · {z.name} · {z.limit_kmh} km/h within {z.radius_m} m</div>)}
          </div>
        </Card>
      </div>
    </>
  );
}
