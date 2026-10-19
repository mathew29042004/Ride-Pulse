/** Ops → Command centre (the commander, or an acting commander): live alerts from the watchtower
 * (pushed over the ops socket), every city at a glance, standing orders that pause bookings, pause
 * a vehicle type or switch surge off (here or everywhere; every city needs confirming), people
 * search with one-click actions, one broadcast to staff, drivers and riders, and handing command
 * to a deputy for a few hours. Orders and broadcasts are posted to #leadership and #operations. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, CarTaxiFront, Crown, Megaphone, MessagesSquare, Radio, Search, ShieldAlert, Siren, UserCog, Users } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, PageHeader, Segmented, Select, Stat, Table, Td, Textarea, Th } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dateTime } from "@/lib/format";
import { useSocket } from "@/lib/ws";

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
  alerts: Alert[];
  delegations: { id: number; to: string; to_role: string; reason: string; ends_at: string; active: boolean }[];
  candidates: { id: number; name: string; role: string }[];
}
interface Alert {
  id: number;
  level: "WARNING" | "CRITICAL";
  title: string;
  detail: string;
  city: string | null;
  link: string;
  raised_at: string;
  acknowledged_by: string | null;
}
interface Person {
  kind: "driver" | "rider" | "trip";
  id: number;
  name: string;
  detail: string;
  link: string;
  status?: string;
  suspended?: boolean;
  online?: boolean;
  blocked?: boolean;
}

const DOT = { green: "bg-emerald-500", amber: "bg-amber-500", red: "bg-rose-500" } as const;

export default function OpsCommand() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["ops", "command"], queryFn: () => api.get<Data>("ops/command/"), refetchInterval: 15_000 });
  const refresh = () => qc.invalidateQueries({ queryKey: ["ops", "command"] });
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong.");
  const live = useSocket("/ws/ops/", (msg) => {
    if (msg.event === "command_alert") {
      const a = msg.data as Alert;
      if (!a.acknowledged_by) (a.level === "CRITICAL" ? toast.error : toast.warning)(a.title, { description: a.detail });
      refresh();
    } else if (msg.event === "command_order" || msg.event === "command_action" || msg.event === "sos") {
      refresh();
    }
  });
  const ack = useMutation({ mutationFn: (id: number) => api.post(`ops/command/alerts/${id}/acknowledge/`), onSuccess: refresh, onError: fail });
  const [confirmText, setConfirmText] = useState("");

  const [kind, setKind] = useState<Kind>("PAUSE_BOOKINGS");
  const [city, setCity] = useState<number | null>(null);
  const [vehicle, setVehicle] = useState("BIKE");
  const [hours, setHours] = useState(2);
  const [reason, setReason] = useState("");
  const issue = useMutation({
    mutationFn: () => api.post("ops/command/", { kind, city, vehicle_code: vehicle, hours, reason, confirm: confirmText === "PAUSE" }),
    onSuccess: () => {
      toast.success("Order issued. Leadership and operations have been told.");
      setReason("");
      setConfirmText("");
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
        subtitle={
          <span className="inline-flex items-center gap-2">
            <span className={`size-2 rounded-full ${live ? "animate-pulse bg-emerald-400" : "bg-white/30"}`} aria-hidden />
            {live ? "Live" : "Reconnecting…"} · Orders take effect at once and end by themselves.
          </span>
        }
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

      {d && d.alerts.length > 0 && (
        <Card className="mb-6 overflow-hidden border-rose-500/30">
          <CardHeader title={<span className="flex items-center gap-2"><BellRing className="size-4 text-danger" /> Live alerts</span>} subtitle="Raised by the watchtower every minute. Acknowledge to let the team know you're on it." />
          <div className="divide-y divide-line">
            {d.alerts.map((a) => (
              <div key={a.id} className={`flex items-start justify-between gap-3 px-5 py-3 text-sm ${a.level === "CRITICAL" ? "bg-rose-500/5" : ""}`}>
                <div>
                  <div className="flex flex-wrap items-center gap-2 font-semibold">
                    <Badge tone={a.level === "CRITICAL" ? "danger" : "warning"}>{a.level === "CRITICAL" ? "Critical" : "Warning"}</Badge> {a.title}
                  </div>
                  <div className="mt-0.5 text-muted">{a.detail}</div>
                  <div className="mt-0.5 text-xs text-muted">{dateTime(a.raised_at)}</div>
                </div>
                <div className="flex shrink-0 gap-2">
                  {a.link && <Link to={a.link}><Button size="sm" variant="outline">Open</Button></Link>}
                  <Button size="sm" loading={ack.isPending} onClick={() => ack.mutate(a.id)}>Acknowledge</Button>
                </div>
              </div>
            ))}
          </div>
        </Card>
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
            {kind === "PAUSE_BOOKINGS" && !city && (
              <Field label="Type PAUSE to confirm" hint="This stops bookings on the whole platform.">
                <Input value={confirmText} onChange={(e) => setConfirmText(e.target.value.toUpperCase())} placeholder="PAUSE" />
              </Field>
            )}
            <Button block variant={kind === "SURGE_OFF" ? "brand" : "danger"} loading={issue.isPending} disabled={reason.trim().length < 10 || (kind === "PAUSE_BOOKINGS" && !city && confirmText !== "PAUSE")} onClick={() => issue.mutate()}>
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

          <PeoplePanel onDone={refresh} />
          {d && <DelegationPanel data={d} onDone={refresh} />}
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

const ACTIONS: Record<Person["kind"], { action: string; label: string; show: (p: Person) => boolean; danger?: boolean; noReason?: boolean }[]> = {
  driver: [
    { action: "offline", label: "Take offline", show: (p) => !!p.online, noReason: true },
    { action: "suspend", label: "Suspend", show: (p) => !p.suspended, danger: true },
    { action: "reinstate", label: "Reinstate", show: (p) => !!p.suspended },
  ],
  rider: [
    { action: "block", label: "Block", show: (p) => !p.blocked, danger: true },
    { action: "unblock", label: "Unblock", show: (p) => !!p.blocked },
  ],
  trip: [{ action: "cancel", label: "Cancel trip", show: (p) => !["COMPLETED", "CANCELLED"].includes(p.status ?? ""), danger: true }],
};

function PeoplePanel({ onDone }: { onDone: () => void }) {
  const [q, setQ] = useState("");
  const [reason, setReason] = useState("");
  const search = useQuery({
    queryKey: ["ops", "command", "people", q],
    queryFn: () => api.get<{ results: Person[] }>(`ops/command/people/?q=${encodeURIComponent(q)}`),
    enabled: q.trim().length >= 3,
  });
  const act = useMutation({
    mutationFn: (v: { kind: string; id: number; action: string }) => api.post("ops/command/act/", { ...v, reason }),
    onSuccess: () => {
      toast.success("Done. It's in the audit trail.");
      setReason("");
      search.refetch();
      onDone();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Something went wrong."),
  });
  return (
    <Card className="space-y-3 p-4">
      <h3 className="flex items-center gap-2 font-semibold"><Search className="size-4" /> Act on anyone</h3>
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Phone, email, name or trip number" aria-label="Search people" />
      <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (needed for suspend, block, cancel)" aria-label="Reason" maxLength={240} />
      <div className="space-y-2">
        {search.data?.results.map((p) => (
          <div key={`${p.kind}-${p.id}`} className="rounded-xl border border-line p-2.5 text-sm">
            <div className="flex items-center justify-between gap-2">
              <Link to={p.link} className="font-semibold hover:underline">{p.name}</Link>
              {(p.suspended || p.blocked) && <Badge tone="danger">{p.suspended ? "Suspended" : "Blocked"}</Badge>}
            </div>
            <div className="text-xs text-muted">{p.detail}</div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {ACTIONS[p.kind].filter((a) => a.show(p)).map((a) => (
                <Button
                  key={a.action}
                  size="sm"
                  variant={a.danger ? "danger" : "secondary"}
                  disabled={!a.noReason && reason.trim().length < 5}
                  loading={act.isPending}
                  onClick={() => act.mutate({ kind: p.kind, id: p.id, action: a.action })}
                >
                  {a.label}
                </Button>
              ))}
            </div>
          </div>
        ))}
        {search.data && !search.data.results.length && <p className="text-xs text-muted">Nobody found.</p>}
      </div>
    </Card>
  );
}

function DelegationPanel({ data, onDone }: { data: Data; onDone: () => void }) {
  const { user } = useAuth();
  const [to, setTo] = useState<number | null>(null);
  const [hours, setHours] = useState(8);
  const [reason, setReason] = useState("");
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong.");
  const give = useMutation({
    mutationFn: () => api.post("ops/command/delegate/", { to, hours, reason }),
    onSuccess: () => {
      toast.success("Command handed over. They've been told.");
      setReason("");
      onDone();
    },
    onError: fail,
  });
  const revoke = useMutation({ mutationFn: (id: number) => api.post(`ops/command/delegations/${id}/revoke/`), onSuccess: onDone, onError: fail });
  const isCommander = user?.role === "COMMANDER";
  return (
    <Card className="space-y-3 p-4">
      <h3 className="flex items-center gap-2 font-semibold"><UserCog className="size-4" /> Acting commander</h3>
      {data.delegations.map((g) => (
        <div key={g.id} className="flex items-center justify-between gap-2 rounded-xl bg-amber-500/10 p-2.5 text-sm">
          <div>
            <div className="font-semibold">{g.to} <span className="font-normal text-muted">({g.to_role})</span></div>
            <div className="text-xs text-muted">{g.reason} · until {dateTime(g.ends_at)}</div>
          </div>
          {isCommander && <Button size="sm" variant="secondary" loading={revoke.isPending} onClick={() => revoke.mutate(g.id)}>Take back</Button>}
        </div>
      ))}
      {isCommander ? (
        <>
          <Select value={to ?? ""} onChange={(e) => setTo(Number(e.target.value) || null)} aria-label="Hand command to">
            <option value="">Hand command to…</option>
            {data.candidates.map((c) => (
              <option key={c.id} value={c.id}>{c.name} · {c.role}</option>
            ))}
          </Select>
          <div className="grid grid-cols-[90px_1fr] gap-2">
            <Input type="number" min={1} max={72} value={hours} onChange={(e) => setHours(Number(e.target.value))} aria-label="Hours" />
            <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why (e.g. travelling)" aria-label="Reason" />
          </div>
          <Button block variant="outline" disabled={!to || reason.trim().length < 5} loading={give.isPending} onClick={() => give.mutate()}>
            Hand over for {hours} h
          </Button>
        </>
      ) : (
        <p className="text-xs text-muted">You're acting commander. Only the commander can hand command on or take it back.</p>
      )}
    </Card>
  );
}
