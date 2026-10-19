/** Ops → Command centre (the commander only): every city at a glance, standing orders that pause
 * bookings, pause a vehicle type or switch surge off (here or everywhere), and one broadcast to
 * staff, drivers and riders. Orders and broadcasts are posted to #leadership and #operations. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CarTaxiFront, Crown, Megaphone, MessagesSquare, Radio, ShieldAlert, Siren, Users } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, PageHeader, Segmented, Select, Stat, Table, Td, Textarea, Th } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime } from "@/lib/format";

type Kind = "PAUSE_BOOKINGS" | "PAUSE_VEHICLE" | "SURGE_OFF";
interface Order {
  id: number;
  kind: Kind;
  kind_label: string;
  city: string;
  vehicle: string;
  reason: string;
  starts_at: string;
  ends_at: string;
  active: boolean;
  by: string | null;
  lifted_by: string | null;
}
interface CityRow {
  id: number;
  name: string;
  state: string;
  drivers_live: number;
  trips_today: number;
  completion_pct: number | null;
  searching: number;
  flags: string[];
  health: "green" | "amber" | "red";
}
interface Data {
  live: { drivers_online: number; drivers_on_trip: number; active_trips: number; searching: number; open_sos: number; open_tickets: number };
  open_incidents: { id: number; number: string; title: string; severity: string }[];
  orders: Order[];
  history: Order[];
  cities: CityRow[];
  vehicles: { code: string; label: string }[];
}

const DOT = { green: "bg-emerald-500", amber: "bg-amber-500", red: "bg-rose-500" } as const;

export default function OpsCommand() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["ops", "command"], queryFn: () => api.get<Data>("ops/command/"), refetchInterval: 15_000 });
  const refresh = () => qc.invalidateQueries({ queryKey: ["ops", "command"] });
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong.");

  const [kind, setKind] = useState<Kind>("PAUSE_BOOKINGS");
  const [city, setCity] = useState<number | null>(null);
  const [vehicle, setVehicle] = useState("BIKE");
  const [hours, setHours] = useState(2);
  const [reason, setReason] = useState("");
  const issue = useMutation({
    mutationFn: () => api.post("ops/command/", { kind, city, vehicle_code: vehicle, hours, reason }),
    onSuccess: () => {
      toast.success("Order issued. Leadership and operations have been told.");
      setReason("");
      refresh();
    },
    onError: fail,
  });
  const lift = useMutation({ mutationFn: (id: number) => api.post(`ops/command/${id}/lift/`), onSuccess: () => { toast.success("Order lifted."); refresh(); }, onError: fail });

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [audiences, setAudiences] = useState<string[]>(["STAFF"]);
  const send = useMutation({
    mutationFn: () => api.post("ops/command/broadcast/", { title, body, audiences }),
    onSuccess: () => {
      toast.success("Broadcast sent.");
      setTitle("");
      setBody("");
    },
    onError: fail,
  });

  const d = q.data;
  return (
    <>
      <PageHeader
        title={<span className="inline-flex items-center gap-2"><Crown className="size-6 text-amber-300" /> Command centre</span>}
        subtitle="Every city at a glance. Orders take effect at once and end by themselves."
        actions={
          <>
            <Link to="/ops/chat"><Button variant="outline" icon={<MessagesSquare className="size-4" />}>Team chat</Button></Link>
            <Link to="/ops/incidents"><Button variant="outline" icon={<Siren className="size-4" />}>Incidents</Button></Link>
          </>
        }
      />
      {d && (
        <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Drivers live" value={d.live.drivers_online + d.live.drivers_on_trip} sub={`${d.live.drivers_on_trip} on a trip`} icon={<CarTaxiFront className="size-4" />} tone="brand" />
          <Stat label="Trips now" value={d.live.active_trips} sub={`${d.live.searching} looking for a driver`} icon={<Radio className="size-4" />} tone="info" />
          <Stat label="Open SOS" value={d.live.open_sos} sub={`${d.live.open_tickets} support tickets open`} icon={<ShieldAlert className="size-4" />} tone={d.live.open_sos ? "danger" : "neutral"} />
          <Stat label="Orders in force" value={d.orders.length} sub={`${d.open_incidents.length} open incidents`} icon={<Crown className="size-4" />} tone={d.orders.length ? "warning" : "neutral"} />
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[380px_1fr]">
        <div className="space-y-4">
          <Card className="space-y-3 p-4">
            <h3 className="font-semibold">Issue an order</h3>
            <Segmented
              value={kind}
              onChange={setKind}
              options={[
                { value: "PAUSE_BOOKINGS", label: "Pause bookings" },
                { value: "PAUSE_VEHICLE", label: "Pause vehicle" },
                { value: "SURGE_OFF", label: "Surge off" },
              ]}
            />
            <Field label="Where">
              <Select value={city ?? ""} onChange={(e) => setCity(Number(e.target.value) || null)}>
                <option value="">All cities</option>
                {d?.cities.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </Select>
            </Field>
            {kind === "PAUSE_VEHICLE" && (
              <Field label="Vehicle type">
                <Select value={vehicle} onChange={(e) => setVehicle(e.target.value)}>
                  {d?.vehicles.map((v) => (
                    <option key={v.code} value={v.code}>{v.label}</option>
                  ))}
                </Select>
              </Field>
            )}
            <Field label="For how many hours">
              <Input type="number" min={1} max={72} value={hours} onChange={(e) => setHours(Number(e.target.value))} />
            </Field>
            <Field label="Reason" hint="Riders see it when they try to book; drivers get it as a notice.">
              <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={240} placeholder="e.g. Citywide bandh called for today" />
            </Field>
            <Button block variant={kind === "SURGE_OFF" ? "brand" : "danger"} loading={issue.isPending} disabled={reason.trim().length < 10} onClick={() => issue.mutate()}>
              {city ? "Issue order" : "Issue order for every city"}
            </Button>
          </Card>

          <Card className="space-y-3 p-4">
            <h3 className="flex items-center gap-2 font-semibold"><Megaphone className="size-4" /> Broadcast</h3>
            <div className="flex flex-wrap gap-1.5">
              {[["STAFF", "Staff"], ["DRIVERS", "Drivers"], ["RIDERS", "Riders"]].map(([v, label]) => {
                const on = audiences.includes(v);
                return (
                  <button key={v} type="button" aria-pressed={on} onClick={() => setAudiences(on ? audiences.filter((a) => a !== v) : [...audiences, v])} className={`rounded-full px-3 py-1 text-xs font-semibold transition ${on ? "bg-ink text-ink-fg" : "bg-surface-3 text-muted"}`}>
                    {label}
                  </button>
                );
              })}
            </div>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} placeholder="Title" aria-label="Title" />
            <Textarea value={body} onChange={(e) => setBody(e.target.value)} maxLength={2000} placeholder="Message" aria-label="Message" />
            <Button block loading={send.isPending} disabled={!title.trim() || !body.trim() || !audiences.length} onClick={() => send.mutate()}>
              Send to {audiences.length ? audiences.map((a) => a.toLowerCase()).join(", ") : "…"}
            </Button>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader title="Orders in force" subtitle="Lift one to end it now." />
            {d && !d.orders.length && <EmptyState icon={<Crown />} title="No orders in force">Everything is running normally.</EmptyState>}
            <div className="divide-y divide-line">
              {d?.orders.map((o) => (
                <div key={o.id} className="flex items-start justify-between gap-3 px-5 py-3 text-sm">
                  <div>
                    <div className="flex flex-wrap items-center gap-2 font-semibold">
                      {o.kind_label}{o.vehicle ? `: ${o.vehicle}` : ""} <Badge tone={o.kind === "SURGE_OFF" ? "brand" : "danger"}>{o.city}</Badge>
                    </div>
                    <div className="mt-0.5 text-muted">{o.reason}</div>
                    <div className="mt-0.5 text-xs text-muted">until {dateTime(o.ends_at)}{o.by ? ` · ${o.by}` : ""}</div>
                  </div>
                  <Button size="sm" variant="secondary" loading={lift.isPending} onClick={() => lift.mutate(o.id)}>Lift</Button>
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader title="Every city" subtitle="Today, refreshed every 15 seconds." />
            <Table>
              <thead>
                <tr><Th>City</Th><Th className="text-right">Drivers live</Th><Th className="text-right">Trips today</Th><Th className="text-right">Completed</Th><Th className="text-right">Waiting</Th><Th>Notes</Th></tr>
              </thead>
              <tbody>
                {d?.cities.map((c) => (
                  <tr key={c.id}>
                    <Td>
                      <div className="flex items-center gap-2 font-medium"><span className={`size-2 rounded-full ${DOT[c.health]}`} aria-hidden /> {c.name}</div>
                      <div className="text-xs text-muted">{c.state}</div>
                    </Td>
                    <Td className="text-right tabular-nums">{c.drivers_live}</Td>
                    <Td className="text-right tabular-nums">{c.trips_today}</Td>
                    <Td className="text-right tabular-nums">{c.completion_pct === null ? "—" : `${c.completion_pct}%`}</Td>
                    <Td className="text-right tabular-nums">{c.searching}</Td>
                    <Td>
                      <div className="flex flex-wrap gap-1">{c.flags.map((f) => <Badge key={f} tone="warning">{f}</Badge>)}</div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>

          {d && d.open_incidents.length > 0 && (
            <Card>
              <CardHeader title="Open incidents" action={<Link to="/ops/incidents" className="text-xs font-semibold text-brand">Manage →</Link>} />
              <div className="divide-y divide-line">
                {d.open_incidents.map((i) => (
                  <div key={i.id} className="flex items-center justify-between px-5 py-2.5 text-sm">
                    <span><span className="font-semibold">{i.number}</span> {i.title}</span>
                    <Badge tone={i.severity === "CRITICAL" ? "danger" : "warning"}>{i.severity.toLowerCase()}</Badge>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {d && d.history.length > 0 && (
            <Card>
              <CardHeader title="Order history" />
              <div className="divide-y divide-line">
                {d.history.map((o) => (
                  <div key={o.id} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm">
                    <span>{o.kind_label}{o.vehicle ? `: ${o.vehicle}` : ""} · {o.city} <span className="text-muted">({o.reason})</span></span>
                    <span className="shrink-0 text-xs text-muted">
                      <Users className="mr-1 inline size-3" />{o.by}{o.lifted_by ? `, lifted by ${o.lifted_by}` : ""} · {dateTime(o.starts_at)}
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
