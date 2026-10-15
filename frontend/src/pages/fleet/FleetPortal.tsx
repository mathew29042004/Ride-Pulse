/**
 * Fleet owner portal: your drivers (online now, trips, earnings and your share), your vehicles'
 * upkeep, and the weekly payouts of your share.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Car, IndianRupee, LogOut, UserMinus, Users, Wrench } from "lucide-react";
import { toast } from "sonner";

import { Logo } from "@/components/Logo";
import { Badge, Button, Card, CardHeader, Stat, Table, Td, Th } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { inr } from "@/lib/format";

interface Health {
  id: number;
  registration: string;
  name: string;
  driver: string | null;
  odometer_km: number;
  service: "OK" | "DUE_SOON" | "OVERDUE";
  service_due_in_km: number;
  documents: { document: string; expires_on: string; status: string }[];
  fuel_type: string;
  battery_percent: number | null;
  status: "OK" | "SOON" | "ACTION";
}
interface Board {
  company: string;
  city: string;
  share_percent: string;
  account_manager: string | null;
  drivers: { id: number; name: string; phone: string; availability: string; rating: string; today_trips: number; week_trips: number; week_earnings: string; week_share: string }[];
  online: number;
  today_trips: number;
  week_trips: number;
  week_share: string;
  balance: string;
  vehicles: Health[];
  payouts: { number: string; amount: string; status: string; period: string }[];
}

export default function FleetPortal() {
  const { user, logout } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["fleet", "dashboard"], queryFn: () => api.get<Board>("fleet/dashboard/"), refetchInterval: 30_000 });
  const onDone = (data: Board) => qc.setQueryData(["fleet", "dashboard"], data);
  const onError = (err: unknown) => toast.error(err instanceof ApiError ? err.message : "Something went wrong.");
  const release = useMutation({ mutationFn: (driver_id: number) => api.post<Board>("fleet/release/", { driver_id }), onSuccess: onDone, onError });
  const service = useMutation({
    mutationFn: (vehicle_id: number) => api.post<Board>("fleet/service/", { vehicle_id, workshop: "Fleet workshop" }),
    onSuccess: (data) => {
      onDone(data);
      toast.success("Service logged");
    },
    onError,
  });
  const b = q.data;
  return (
    <div className="min-h-dvh bg-bg">
      <header className="flex h-16 items-center gap-3 border-b border-line bg-surface px-4 lg:px-8">
        <Logo />
        <span className="ml-2 rounded-full bg-surface-3 px-2.5 py-1 text-xs font-semibold">Fleet partner</span>
        <div className="flex-1" />
        <span className="hidden text-sm text-muted sm:block">{user?.email}</span>
        <button onClick={() => logout()} className="rounded-lg p-2 hover:bg-surface-3" aria-label="Sign out">
          <LogOut className="size-4" />
        </button>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6 lg:px-8">
        <h1 className="text-2xl font-bold">{b?.company ?? "Your fleet"}</h1>
        <p className="text-sm text-muted">
          {b && `${b.city} · you keep ${Number(b.share_percent)}% of your drivers' trip earnings (tips and boosts stay with them)`}
          {b?.account_manager && ` · account manager: ${b.account_manager}`}
        </p>
        <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Drivers online" value={b ? `${b.online} / ${b.drivers.length}` : "—"} icon={<Users className="size-4" />} tone="brand" />
          <Stat label="Trips today" value={b?.today_trips ?? "—"} sub={b ? `${b.week_trips} this week` : ""} icon={<Car className="size-4" />} tone="info" />
          <Stat label="Your share this week" value={b ? inr(b.week_share, { whole: true }) : "—"} icon={<IndianRupee className="size-4" />} />
          <Stat label="Balance for next payout" value={b ? inr(b.balance, { whole: true }) : "—"} sub="Paid every Monday" />
        </div>

        <Card className="mt-4 overflow-x-auto">
          <div className="p-4 pb-0">
            <CardHeader title="Drivers" />
          </div>
          <Table>
            <thead>
              <tr>
                <Th>Driver</Th>
                <Th>Status</Th>
                <Th className="text-right">Today</Th>
                <Th className="text-right">This week</Th>
                <Th className="text-right">Earnings</Th>
                <Th className="text-right">Your share</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {(b?.drivers ?? []).map((d) => (
                <tr key={d.id} className="border-t border-line">
                  <Td>
                    <div className="font-semibold">{d.name}</div>
                    <div className="text-xs text-muted">
                      {d.phone} · ★ {Number(d.rating).toFixed(2)}
                    </div>
                  </Td>
                  <Td>
                    <Badge tone={d.availability === "OFFLINE" ? "neutral" : d.availability === "ON_TRIP" ? "info" : "brand"}>{d.availability === "ON_TRIP" ? "On trip" : d.availability === "ONLINE" ? "Online" : "Offline"}</Badge>
                  </Td>
                  <Td className="text-right">{d.today_trips}</Td>
                  <Td className="text-right">{d.week_trips}</Td>
                  <Td className="text-right">{inr(d.week_earnings, { whole: true })}</Td>
                  <Td className="text-right font-semibold">{inr(d.week_share, { whole: true })}</Td>
                  <Td>
                    <button
                      onClick={() => confirm(`Let ${d.name} go from your fleet?`) && release.mutate(d.id)}
                      className="rounded-lg p-1.5 text-muted hover:bg-surface-3 hover:text-danger"
                      aria-label={`Remove ${d.name}`}
                    >
                      <UserMinus className="size-4" />
                    </button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>

        <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_320px]">
          <Card className="p-4">
            <CardHeader title="Vehicles" subtitle="Service by distance; insurance, permit and fitness by date. Expired insurance stops a car going online." />
            <div className="space-y-2">
              {(b?.vehicles ?? []).map((v) => (
                <div key={v.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-line px-3 py-2.5 text-sm">
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold">
                      {v.registration} <span className="font-normal text-muted">· {v.name}</span>
                    </div>
                    <div className="text-xs text-muted">
                      {v.driver ?? "No driver"} · {v.odometer_km.toLocaleString("en-IN")} km ·{" "}
                      <span className={clsx(v.service !== "OK" && "font-semibold text-danger")}>{v.service === "OVERDUE" ? "service overdue" : `service in ${v.service_due_in_km} km`}</span>
                      {v.fuel_type === "EV" && v.battery_percent != null && ` · battery ${v.battery_percent}%`}
                      {v.documents
                        .filter((d) => d.status !== "OK")
                        .map((d) => ` · ${d.document.toLowerCase()} ${d.status === "EXPIRED" ? "expired" : "expires"} ${d.expires_on}`)
                        .join("")}
                    </div>
                  </div>
                  <Badge tone={v.status === "ACTION" ? "danger" : v.status === "SOON" ? "warning" : "brand"}>{v.status === "ACTION" ? "Needs action" : v.status === "SOON" ? "Due soon" : "OK"}</Badge>
                  {v.service !== "OK" && (
                    <Button size="sm" variant="outline" icon={<Wrench className="size-3.5" />} onClick={() => service.mutate(v.id)}>
                      Serviced
                    </Button>
                  )}
                </div>
              ))}
            </div>
          </Card>
          <Card className="p-4">
            <CardHeader title="Payouts" />
            {(b?.payouts ?? []).length === 0 && <p className="text-sm text-muted">Your first payout arrives on Monday.</p>}
            {(b?.payouts ?? []).map((p) => (
              <div key={p.number} className="flex justify-between border-t border-line py-2 text-sm first:border-0">
                <span>
                  {p.period}
                  <span className="block text-xs text-muted">{p.status}</span>
                </span>
                <span className="font-semibold">{inr(p.amount)}</span>
              </div>
            ))}
          </Card>
        </div>
      </main>
    </div>
  );
}
