/** Ops → Command centre (the commander, or an acting commander): live alerts from the watchtower
 * (pushed over the ops socket), every city at a glance, standing orders that pause bookings, pause
 * a vehicle type or switch surge off (here or everywhere; every city needs confirming), people
 * search with one-click actions, one broadcast to staff, drivers and riders, and handing command
 * to a deputy for a few hours. Orders and broadcasts are posted to #leadership and #operations. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Inbox, X as XIcon, BellRing, CarTaxiFront, Crown, Megaphone, MessagesSquare, Radio, Search, ShieldAlert, Siren, UserCog, Users } from "lucide-react";
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
  target_pct: number | null;
  on_track: boolean | null;
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
  scheduled: Order[];
  leaders: Record<"city" | "agent" | "driver", { name: string; detail: string } | null>;
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
  const [startAt, setStartAt] = useState("");
  const issue = useMutation({
    mutationFn: () =>
      api.post("ops/command/", { kind, city, vehicle_code: vehicle, hours, reason, confirm: confirmText === "PAUSE", starts_at: startAt ? new Date(startAt).toISOString() : null }),
    onSuccess: () => {
      toast.success("Order issued. Leadership and operations have been told.");
      setReason("");
      setConfirmText("");
      setStartAt("");
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

      <ChiefInbox />

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
            <Field label="Start (optional)" hint="Leave empty to start now, or schedule it up to 30 days ahead.">
              <Input type="datetime-local" value={startAt} onChange={(e) => setStartAt(e.target.value)} />
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
                <tr><Th>City</Th><Th className="text-right">Drivers live</Th><Th className="text-right">Trips today</Th><Th className="text-right">Completed</Th><Th className="text-right">Target</Th><Th className="text-right">Waiting</Th><Th>Notes</Th></tr>
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
                    <Td className="text-right tabular-nums">
                      {c.completion_pct === null ? "—" : `${c.completion_pct}%`}
                      {c.on_track !== null && <span className={`ml-1 text-[10px] font-bold ${c.on_track ? "text-emerald-600" : "text-rose-600"}`}>{c.on_track ? "▲ on track" : "▼ behind"}</span>}
                    </Td>
                    <Td className="text-right">
                      <TargetInput city={c.id} value={c.target_pct} onSaved={refresh} />
                    </Td>
                    <Td className="text-right tabular-nums">{c.searching}</Td>
                    <Td>
                      <div className="flex flex-wrap gap-1">{c.flags.map((f) => <Badge key={f} tone="warning">{f}</Badge>)}</div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>

          {d && d.scheduled.length > 0 && (
            <Card>
              <CardHeader title="Scheduled orders" subtitle="They start by themselves." />
              <div className="divide-y divide-line">
                {d.scheduled.map((o) => (
                  <div key={o.id} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm">
                    <span>{o.kind_label}{o.vehicle ? `: ${o.vehicle}` : ""} · {o.city} <span className="text-muted">from {dateTime(o.starts_at)}</span></span>
                    <Button size="sm" variant="secondary" loading={lift.isPending} onClick={() => lift.mutate(o.id)}>Cancel</Button>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {d && <Leaders leaders={d.leaders} />}

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
    onSuccess: (_, v) => {
      const undo: Record<string, string> = { suspend: "reinstate", block: "unblock", reinstate: "suspend", unblock: "block" };
      const back = undo[v.action];
      const why = reason;
      toast.success("Done. It's in the audit trail.", back ? {
        duration: 10 * 60_000,
        action: {
          label: "Undo",
          onClick: () => api.post("ops/command/act/", { ...v, action: back, reason: `Undo: ${why}` }).then(() => { toast.success("Undone."); search.refetch(); onDone(); }),
        },
      } : undefined);
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

interface Update {
  id: number;
  kind: "UPDATE" | "BRIEFING" | "ESCALATION";
  kind_label: string;
  title: string;
  body: string;
  sent_by: string;
  source: string;
  sent_at: string;
  read: boolean;
  reply: string;
}
interface Decision {
  id: number;
  title: string;
  detail: string;
  order: string;
  asked_by: string;
  asked_at: string;
  status: "PENDING" | "APPROVED" | "DECLINED";
  status_label: string;
  decided_by: string | null;
  note: string;
}

/** The chief's inbox: decisions waiting (approve issues any proposed order at once) and updates
 * from the chief of staff, with a one-line reply. Live via ChiefBell's socket. */
function ChiefInbox() {
  const qc = useQueryClient();
  const [source, setSource] = useState("");
  const q = useQuery({
    queryKey: ["ops", "chief", source],
    queryFn: () => api.get<{ updates: Update[]; unread: number; decisions: Decision[]; pending: number; sources: string[] }>(`ops/chief/?source=${encodeURIComponent(source)}`),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["ops", "chief"] });
    qc.invalidateQueries({ queryKey: ["ops", "command"] });
  };
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong.");
  const [notes, setNotes] = useState<Record<number, string>>({});
  const decide = useMutation({
    mutationFn: (v: { id: number; approve: boolean }) => api.post(`ops/chief/decisions/${v.id}/decide/`, { approve: v.approve, note: notes[v.id] ?? "" }),
    onSuccess: (_, v) => {
      toast.success(v.approve ? "Approved. They've been told." : "Declined. They've been told.");
      refresh();
    },
    onError: fail,
  });
  const reply = useMutation({
    mutationFn: (id: number) => api.post(`ops/chief/updates/${id}/reply/`, { text: notes[-id] ?? "" }),
    onSuccess: () => {
      toast.success("Reply sent.");
      refresh();
    },
    onError: fail,
  });
  const read = useMutation({ mutationFn: () => api.post("ops/chief/read/"), onSuccess: refresh });
  const [question, setQuestion] = useState("");
  const ask = useMutation({
    mutationFn: () => api.post<Update>("ops/chief/question/", { question }),
    onSuccess: () => {
      setQuestion("");
      refresh();
    },
    onError: fail,
  });
  const d = q.data;
  if (!d) return null;
  const pending = d.decisions.filter((x) => x.status === "PENDING");
  return (
    <div className="mb-6 grid gap-4 lg:grid-cols-2">
      <Card className={pending.length ? "border-amber-500/40" : ""}>
        <CardHeader title={<span className="flex items-center gap-2"><Crown className="size-4 text-amber-500" /> Decisions for you {pending.length > 0 && <Badge tone="warning">{pending.length} waiting</Badge>}</span>} subtitle="Approving a proposed order puts it in force at once." />
        {!d.decisions.length && <EmptyState title="Nothing to decide">Your chief of staff will bring decisions here.</EmptyState>}
        <div className="max-h-96 divide-y divide-line overflow-y-auto">
          {d.decisions.slice(0, 8).map((x) => (
            <div key={x.id} className="px-5 py-3 text-sm">
              <div className="flex items-start justify-between gap-2">
                <div className="font-semibold">{x.title}</div>
                {x.status !== "PENDING" && <Badge tone={x.status === "APPROVED" ? "brand" : "neutral"}>{x.status_label}</Badge>}
              </div>
              {x.detail && <p className="mt-0.5 text-muted">{x.detail}</p>}
              {x.order && <p className="mt-1 text-xs font-medium">Proposed order: {x.order}</p>}
              <p className="mt-0.5 text-xs text-muted">{x.asked_by} · {dateTime(x.asked_at)}{x.note ? ` · “${x.note}”` : ""}</p>
              {x.status === "PENDING" && (
                <div className="mt-2 flex flex-wrap gap-2">
                  <Input className="!w-auto flex-1 !py-1.5" placeholder="Note (optional)" value={notes[x.id] ?? ""} onChange={(e) => setNotes({ ...notes, [x.id]: e.target.value })} aria-label="Note" />
                  <Button size="sm" variant="brand" icon={<Check className="size-3.5" />} loading={decide.isPending} onClick={() => decide.mutate({ id: x.id, approve: true })}>Approve</Button>
                  <Button size="sm" variant="secondary" icon={<XIcon className="size-3.5" />} loading={decide.isPending} onClick={() => decide.mutate({ id: x.id, approve: false })}>Decline</Button>
                </div>
              )}
            </div>
          ))}
        </div>
      </Card>
      <Card>
        <CardHeader
          title={<span className="flex items-center gap-2"><Inbox className="size-4" /> Updates for you {d.unread > 0 && <Badge tone="info">{d.unread} new</Badge>}</span>}
          subtitle="Briefings, updates and escalations from your chief of staff."
          action={d.unread > 0 ? <Button size="sm" variant="ghost" onClick={() => read.mutate()}>Mark all read</Button> : undefined}
        />
        <form className="flex gap-2 border-b border-line px-5 py-3" onSubmit={(e) => { e.preventDefault(); if (question.trim()) ask.mutate(); }}>
          <Input className="!py-1.5" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask your chief of staff, e.g. how's Kochi today?" aria-label="Ask your chief of staff" />
          <Button size="sm" type="submit" loading={ask.isPending} disabled={!question.trim()}>Ask</Button>
        </form>
        {d.sources.length > 1 && (
          <div className="scrollbar-none flex gap-1.5 overflow-x-auto border-b border-line px-5 py-2">
            {["", ...d.sources].map((s) => (
              <button key={s || "all"} onClick={() => setSource(s)} className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold ${source === s ? "bg-ink text-ink-fg" : "bg-surface-3 text-muted"}`}>
                {s || "Everyone"}
              </button>
            ))}
          </div>
        )}
        {!d.updates.length && <EmptyState title="No updates yet" />}
        <div className="max-h-96 divide-y divide-line overflow-y-auto">
          {d.updates.slice(0, 10).map((u) => (
            <div key={u.id} className={`px-5 py-3 text-sm ${u.kind === "ESCALATION" ? "bg-rose-500/5" : ""}`}>
              <div className="flex flex-wrap items-center gap-2 font-semibold">
                <Badge tone={u.kind === "ESCALATION" ? "danger" : u.kind === "BRIEFING" ? "info" : "neutral"}>{u.kind_label}</Badge>
                {u.title}
                {!u.read && <span className="size-2 rounded-full bg-sky-500" aria-label="New" />}
              </div>
              {u.body && <p className="mt-1 whitespace-pre-line text-muted">{u.body}</p>}
              <p className="mt-0.5 text-xs text-muted"><span className="font-semibold">{u.source}</span> · {u.sent_by} · {dateTime(u.sent_at)}</p>
              {u.reply ? (
                <p className="mt-1 text-xs"><span className="font-semibold">You replied:</span> {u.reply}</p>
              ) : (
                <div className="mt-2 flex gap-2">
                  <Input className="!py-1.5" placeholder="Reply in one line" value={notes[-u.id] ?? ""} onChange={(e) => setNotes({ ...notes, [-u.id]: e.target.value })} aria-label="Reply" />
                  <Button size="sm" variant="secondary" disabled={!(notes[-u.id] ?? "").trim()} loading={reply.isPending} onClick={() => reply.mutate(u.id)}>Reply</Button>
                </div>
              )}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function Leaders({ leaders }: { leaders: Data["leaders"] }) {
  const thank = useMutation({
    mutationFn: (kind: string) => api.post("ops/chief/thank/", { kind }),
    onSuccess: () => toast.success("Thanked. It's posted in #general."),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Something went wrong."),
  });
  const rows: [keyof Data["leaders"], string][] = [["city", "Best city"], ["agent", "Best support agent"], ["driver", "Best driver"]];
  return (
    <Card>
      <CardHeader title="This week's stars" subtitle="Say thanks: they're told, and it goes up in #general." />
      <div className="grid gap-3 p-4 sm:grid-cols-3">
        {rows.map(([k, label]) => {
          const w = leaders[k];
          return (
            <div key={k} className="rounded-2xl bg-surface-2 p-3 text-sm">
              <div className="text-xs font-medium text-muted">🏆 {label}</div>
              <div className="mt-1 font-semibold">{w?.name ?? "Not enough data yet"}</div>
              {w && <div className="text-xs text-muted">{w.detail}</div>}
              {w && <Button size="sm" variant="secondary" className="mt-2" loading={thank.isPending} onClick={() => thank.mutate(k)}>Say thanks</Button>}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function TargetInput({ city, value, onSaved }: { city: number; value: number | null; onSaved: () => void }) {
  const [v, setV] = useState(value?.toString() ?? "");
  const save = useMutation({
    mutationFn: () => api.post("ops/command/target/", { city, completion_pct: Number(v) }),
    onSuccess: () => {
      toast.success("Target set for this month.");
      onSaved();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Something went wrong."),
  });
  return (
    <form className="inline-flex items-center gap-1" onSubmit={(e) => { e.preventDefault(); if (v && Number(v) !== value) save.mutate(); }}>
      <input
        value={v}
        onChange={(e) => setV(e.target.value.replace(/\D/g, "").slice(0, 3))}
        onBlur={() => v && Number(v) !== value && save.mutate()}
        placeholder="—"
        className="w-12 rounded-lg bg-surface-2 px-1.5 py-0.5 text-right text-xs tabular-nums ring-1 ring-line outline-none focus:ring-brand"
        aria-label="Completion target %"
        inputMode="numeric"
      />
      <span className="text-xs text-muted">%</span>
    </form>
  );
}
