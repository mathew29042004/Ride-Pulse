/**
 * Ops intelligence: the morning briefing, automatic alerts (each one a task for its owner),
 * the next-hour demand forecast, and the fraud review queue.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { AlertTriangle, BellRing, CheckCircle2, Flame, ShieldAlert, ShieldCheck, Sunrise, TrendingUp } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { toast } from "sonner";

import { BaseMap, FitBounds, type LatLng, MapDot } from "@/components/map";
import { Badge, Button, Card, CardHeader, EmptyState, Input, PageHeader, Segmented, Select, Stat, Table, Td, Th } from "@/components/ui";
import { useOps } from "@/layouts/OpsLayout";
import { api, ApiError } from "@/lib/api";
import { ago, dateTime, inr } from "@/lib/format";
import type { Paginated } from "@/lib/types";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "Something went wrong.");

// --- Morning briefing ------------------------------------------------------------------------

interface TripNumbers {
  requests: number;
  completed: number;
  cancelled: number;
  no_driver: number;
  completion_rate: number | null;
  gmv: string;
  commission: string;
}
interface CityRow {
  city: string;
  requests: number;
  completed: number;
  completion_rate: number;
  gmv: string;
}
interface Briefing {
  day: string;
  headline: string;
  trips: TripNumbers;
  week_ago: TripNumbers;
  worst_cities: CityRow[];
  best_cities: CityRow[];
  safety: { sos: number; ambulance: number };
  support: { opened: number; resolved: number; resolved_in_sla: number; open_past_sla: number };
  drivers: { approved: number; total_approved: number };
  alerts: { raised: number; open: { title: string; severity: string }[] };
  fraud: { open_cases: number; new: number };
  team: { tasks_done: number; tasks_late: number; tasks_overdue: number };
}

function change(now: number, before: number) {
  if (!before) return "";
  const pct = Math.round((100 * (now - before)) / before);
  return `${pct >= 0 ? "+" : ""}${pct}% vs last week`;
}

export function OpsBriefing() {
  const [params, setParams] = useSearchParams();
  const day = params.get("day") ?? "";
  const q = useQuery({ queryKey: ["intel", "briefing", day], queryFn: () => api.get<{ briefing: Briefing | null; available: string[] }>(`intel/briefing/${day ? `?day=${day}` : ""}`) });
  const b = q.data?.briefing;
  return (
    <>
      <PageHeader
        title="Morning briefing"
        subtitle={b ? new Date(b.day).toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" }) : "Yesterday in numbers"}
        actions={
          (q.data?.available.length ?? 0) > 1 && (
            <Select value={day} onChange={(e) => setParams(e.target.value ? { day: e.target.value } : {})} className="!w-auto">
              <option value="">Yesterday</option>
              {q.data!.available.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </Select>
          )
        }
      />
      {!b ? (
        <EmptyState icon={<Sunrise className="size-6" />} title={q.isLoading ? "Loading…" : "No briefing for this day"} />
      ) : (
        <>
          <Card className="mb-4 flex items-start gap-3 p-4">
            <Sunrise className="mt-0.5 size-5 shrink-0 text-amber-500" />
            <p className="text-sm font-medium">{b.headline}</p>
          </Card>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Trips completed" value={b.trips.completed} sub={change(b.trips.completed, b.week_ago.completed)} tone="brand" icon={<CheckCircle2 className="size-4" />} />
            <Stat label="Completion rate" value={b.trips.completion_rate != null ? `${b.trips.completion_rate}%` : "—"} sub={`${b.trips.cancelled} cancelled · ${b.trips.no_driver} no driver`} tone="info" icon={<TrendingUp className="size-4" />} />
            <Stat label="Bookings" value={inr(b.trips.gmv, { whole: true })} sub={`Commission ${inr(b.trips.commission, { whole: true })}`} />
            <Stat label="Safety" value={`${b.safety.sos} SOS`} sub={b.safety.ambulance ? `${b.safety.ambulance} ambulance requests` : "No ambulance requests"} tone={b.safety.sos ? "danger" : "neutral"} icon={<ShieldAlert className="size-4" />} />
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Card className="p-4">
              <CardHeader title="Cities to watch" subtitle="Lowest completion rate (10+ requests)" />
              {b.worst_cities.map((c) => (
                <CityLine key={c.city} row={c} bad />
              ))}
              <div className="mt-3 text-xs font-semibold text-muted uppercase">Doing best</div>
              {b.best_cities.map((c) => (
                <CityLine key={c.city} row={c} />
              ))}
            </Card>
            <Card className="space-y-3 p-4">
              <CardHeader title="Support, drivers and the team" />
              <Line label="Tickets opened / resolved" value={`${b.support.opened} / ${b.support.resolved}`} />
              <Line label="Resolved within SLA" value={b.support.resolved ? `${Math.round((100 * b.support.resolved_in_sla) / b.support.resolved)}%` : "—"} />
              <Line label="Tickets open past SLA" value={b.support.open_past_sla} warn={b.support.open_past_sla > 0} />
              <Line label="Drivers approved" value={`${b.drivers.approved} (total ${b.drivers.total_approved})`} />
              <Line label="Team tasks done / late" value={`${b.team.tasks_done} / ${b.team.tasks_late}`} />
              <Line label="Tasks overdue" value={b.team.tasks_overdue} warn={b.team.tasks_overdue > 0} />
              <Line label="Alerts raised" value={b.alerts.raised} />
              <Line label="Open fraud cases" value={`${b.fraud.open_cases} (${b.fraud.new} new)`} warn={b.fraud.open_cases > 0} />
            </Card>
          </div>
          {b.alerts.open.length > 0 && (
            <Card className="mt-4 p-4">
              <CardHeader title="Still open this morning" action={<Link to="/ops/alerts" className="text-sm font-semibold text-brand-strong">All alerts</Link>} />
              {b.alerts.open.map((a) => (
                <div key={a.title} className="flex items-center gap-2 py-1 text-sm">
                  <AlertTriangle className={clsx("size-4", a.severity === "CRITICAL" ? "text-danger" : "text-amber-500")} /> {a.title}
                </div>
              ))}
            </Card>
          )}
        </>
      )}
    </>
  );
}

function CityLine({ row, bad }: { row: CityRow; bad?: boolean }) {
  return (
    <div className="flex items-center gap-3 py-1.5 text-sm">
      <span className="flex-1 font-medium">{row.city}</span>
      <span className="text-xs text-muted">
        {row.completed}/{row.requests} · {inr(row.gmv, { whole: true })}
      </span>
      <Badge tone={bad ? "warning" : "brand"}>{row.completion_rate}%</Badge>
    </div>
  );
}

function Line({ label, value, warn }: { label: string; value: React.ReactNode; warn?: boolean }) {
  return (
    <div className="flex justify-between text-sm">
      <span className="text-muted">{label}</span>
      <span className={clsx("font-semibold", warn && "text-danger")}>{value}</span>
    </div>
  );
}

// --- Alerts ----------------------------------------------------------------------------------

interface Alert {
  id: number;
  kind_label: string;
  city_name: string;
  severity: "WARNING" | "CRITICAL";
  title: string;
  detail: string;
  status: "OPEN" | "RESOLVED";
  owner_name: string | null;
  task: number | null;
  task_status: string | null;
  created_at: string;
  resolved_at: string | null;
}

export function OpsAlerts() {
  const [status, setStatus] = useState("OPEN");
  const q = useQuery({ queryKey: ["intel", "alerts", status], queryFn: () => api.get<Paginated<Alert>>(`intel/alerts/?status=${status}&page_size=100`), refetchInterval: 30_000 });
  const list = q.data?.results ?? [];
  return (
    <>
      <PageHeader title="Alerts" subtitle="Checked every 5 minutes against each city's normal level. Every alert becomes a task for the manager who owns the problem, and closes itself when the numbers recover." />
      <Segmented value={status} onChange={setStatus} options={[{ value: "OPEN", label: "Open" }, { value: "RESOLVED", label: "Resolved" }]} />
      <div className="mt-4 space-y-2">
        {list.map((a) => (
          <Card key={a.id} className="flex flex-wrap items-center gap-3 p-4">
            <BellRing className={clsx("size-5 shrink-0", a.severity === "CRITICAL" ? "text-danger" : "text-amber-500")} />
            <div className="min-w-0 flex-1">
              <div className="font-semibold">{a.title}</div>
              <div className="text-xs text-muted">
                {a.detail} · {a.status === "OPEN" ? `raised ${ago(a.created_at)}` : `resolved ${ago(a.resolved_at)}`}
              </div>
            </div>
            <Badge tone={a.severity === "CRITICAL" ? "danger" : "warning"}>{a.kind_label}</Badge>
            {a.task ? (
              <Link to={`/ops/work/tasks/${a.task}`} className="text-sm font-semibold text-brand-strong">
                Task · {a.owner_name} ({a.task_status?.replace("_", " ").toLowerCase()})
              </Link>
            ) : (
              <span className="text-xs text-muted">No owner found</span>
            )}
          </Card>
        ))}
        {!q.isLoading && list.length === 0 && <EmptyState icon={<CheckCircle2 className="size-6" />} title={status === "OPEN" ? "All clear" : "No resolved alerts yet"} />}
      </div>
    </>
  );
}

// --- Demand forecast -------------------------------------------------------------------------

interface ZoneForecast {
  zone_id: number;
  zone: string;
  city: string;
  lat: number;
  lng: number;
  expected_trips: number;
  drivers_nearby: number;
  shortage: number;
  status: "SHORT" | "TIGHT" | "OK";
}
interface Forecast {
  for_hour: string;
  total_expected: number;
  zones: ZoneForecast[];
  accuracy: { hours: number; trips: number; model: number | null; seasonal: number | null; naive: number | null };
}

const STATUS_COLOR = { SHORT: "#e11d48", TIGHT: "#f59e0b", OK: "#16a34a" };

export function OpsDemand() {
  const { cityInfo } = useOps();
  const q = useQuery({ queryKey: ["intel", "demand", cityInfo?.id], queryFn: () => api.get<Forecast>(`intel/demand/${cityInfo ? `?city=${cityInfo.id}` : ""}`), refetchInterval: 60_000 });
  const f = q.data;
  const zones = f?.zones ?? [];
  const points: LatLng[] = zones.map((z) => [z.lat, z.lng]);
  const acc = f?.accuracy;
  const pct = (v: number | null | undefined) => (v == null ? "—" : `${v}%`);
  return (
    <>
      <PageHeader
        title={`Demand forecast · ${cityInfo?.name ?? "All cities"}`}
        subtitle={f ? `Next hour from ${new Date(f.for_hour).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}: where riders will be, and where drivers are short. Free drivers near short zones get a nudge.` : ""}
      />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Trips expected next hour" value={f?.total_expected ?? "—"} icon={<TrendingUp className="size-4" />} tone="brand" />
        <Stat label="Zones short of drivers" value={zones.filter((z) => z.status === "SHORT").length} icon={<Flame className="size-4" />} tone="danger" />
        <Stat label="Forecast accuracy" value={pct(acc?.model)} sub={acc ? `Last 72 h, ${acc.hours} steady hours, ${acc.trips} trips` : ""} tone="info" />
        <Stat label="Compared with" value={`${pct(acc?.seasonal)} · ${pct(acc?.naive)}`} sub="History only · same as last hour" />
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_420px]">
        <Card className="h-[460px] overflow-hidden">
          {points.length > 0 && (
            <BaseMap center={points[0]} zoom={11} zoomControl className="h-full">
              {zones.map((z) => (
                <MapDot key={z.zone_id} center={[z.lat, z.lng]} radius={5 + 2 * Math.min(8, z.expected_trips)} color={STATUS_COLOR[z.status]} label={`${z.zone}: ${z.expected_trips} trips, ${z.drivers_nearby} drivers`} />
              ))}
              <FitBounds points={points} padding={20} maxZoom={13} fitKey={`${cityInfo?.id ?? "all"}-${points.length > 0}`} />
            </BaseMap>
          )}
        </Card>
        <Card className="max-h-[460px] overflow-y-auto">
          <Table>
            <thead>
              <tr>
                <Th>Zone</Th>
                <Th className="text-right">Next hour</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {zones.map((z) => (
                <tr key={z.zone_id} className="border-t border-line">
                  <Td>
                    <div className="font-semibold">{z.zone}</div>
                    <div className="text-xs text-muted">{z.city}</div>
                  </Td>
                  <Td className="text-right">
                    <div>{z.expected_trips} trips</div>
                    <div className="text-xs text-muted">{z.drivers_nearby} drivers nearby</div>
                  </Td>
                  <Td>
                    <Badge tone={z.status === "SHORT" ? "danger" : z.status === "TIGHT" ? "warning" : "brand"}>{z.status === "SHORT" ? "Short" : z.status === "TIGHT" ? "Tight" : "OK"}</Badge>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {!q.isLoading && zones.length === 0 && <p className="p-6 text-center text-sm text-muted">Not enough history for this hour yet.</p>}
        </Card>
      </div>
      <p className="mt-3 text-xs text-muted">
        How it works: the same hour on the same weekday over the past four weeks (recent weeks count more), blended with the last hour's real demand. Accuracy counts steady hours only; jumps of more than 3x (like the simulator being switched on) can't be forecast from history.
      </p>
    </>
  );
}

// --- Fraud review ----------------------------------------------------------------------------

interface FraudCase {
  id: number;
  number: string;
  kind: string;
  kind_label: string;
  driver: number | null;
  driver_name: string | null;
  rider: number | null;
  rider_name: string | null;
  city_name: string | null;
  score: number;
  summary: string;
  evidence: Record<string, number>;
  trip_ids: number[];
  status: "OPEN" | "CONFIRMED" | "DISMISSED";
  status_label: string;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  review_note: string;
  action_taken: string;
  created_at: string;
}

export function OpsFraud() {
  const qc = useQueryClient();
  const [status, setStatus] = useState("OPEN");
  const summary = useQuery({ queryKey: ["intel", "fraud", "summary"], queryFn: () => api.get<{ open: number; high_risk: number; confirmed_30d: number; by_kind: Record<string, number> }>("intel/fraud/summary/") });
  const cases = useQuery({ queryKey: ["intel", "fraud", status], queryFn: () => api.get<Paginated<FraudCase>>(`intel/fraud/?status=${status}&page_size=100`) });
  const [notes, setNotes] = useState<Record<number, string>>({});
  const review = useMutation({
    mutationFn: ({ id, ...body }: { id: number; confirm: boolean; action: string; note: string }) => api.post<FraudCase>(`intel/fraud/${id}/review/`, body),
    onSuccess: (c) => {
      toast.success(`${c.number}: ${c.status_label}`);
      qc.invalidateQueries({ queryKey: ["intel", "fraud"] });
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const s = summary.data;
  const list = cases.data?.results ?? [];
  return (
    <>
      <PageHeader title="Fraud review" subtitle="Patterns honest users rarely produce, checked every hour over the last two weeks. Confirm (and suspend or block in the same step) or dismiss." />
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Open cases" value={s?.open ?? "—"} icon={<ShieldAlert className="size-4" />} tone="warning" />
        <Stat label="High risk (score 75+)" value={s?.high_risk ?? "—"} tone="danger" />
        <Stat label="Confirmed (30 days)" value={s?.confirmed_30d ?? "—"} icon={<ShieldCheck className="size-4" />} />
      </div>
      <div className="mt-4">
        <Segmented value={status} onChange={setStatus} options={[{ value: "OPEN", label: "Needs review" }, { value: "CONFIRMED", label: "Confirmed" }, { value: "DISMISSED", label: "Dismissed" }]} />
      </div>
      <div className="mt-4 space-y-3">
        {list.map((c) => (
          <Card key={c.id} className="p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className={clsx("flex size-10 items-center justify-center rounded-xl text-sm font-bold", c.score >= 75 ? "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300" : "bg-amber-100 text-amber-800 dark:bg-amber-400/15 dark:text-amber-300")}>{c.score}</span>
              <div className="min-w-0 flex-1">
                <div className="font-semibold">
                  {c.kind_label} <span className="font-normal text-muted">· {c.number}</span>
                </div>
                <div className="text-sm">{c.summary}</div>
                <div className="text-xs text-muted">
                  {c.driver && (
                    <Link className="text-brand-strong" to={`/ops/drivers/${c.driver}`}>
                      Driver {c.driver_name}
                    </Link>
                  )}
                  {c.driver && c.rider && " · "}
                  {c.rider && <span>Rider {c.rider_name}</span>}
                  {c.city_name && ` · ${c.city_name}`} · found {ago(c.created_at)}
                </div>
                {c.trip_ids.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1.5 text-xs">
                    {c.trip_ids.slice(0, 8).map((id) => (
                      <Link key={id} to={`/ops/trips/${id}`} className="rounded-full bg-surface-3 px-2 py-0.5 hover:bg-line">
                        Trip {id}
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            </div>
            {c.status === "OPEN" ? (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Input className="min-w-60 flex-1 !py-2" placeholder="Note (what you checked)" value={notes[c.id] ?? ""} onChange={(e) => setNotes({ ...notes, [c.id]: e.target.value })} />
                <Button variant="outline" onClick={() => review.mutate({ id: c.id, confirm: false, action: "NONE", note: notes[c.id] ?? "" })}>
                  Not fraud
                </Button>
                <Button variant="secondary" onClick={() => review.mutate({ id: c.id, confirm: true, action: "NONE", note: notes[c.id] ?? "" })}>
                  Confirm
                </Button>
                {c.driver && (
                  <Button variant="danger" onClick={() => review.mutate({ id: c.id, confirm: true, action: "SUSPEND_DRIVER", note: notes[c.id] ?? "" })}>
                    Confirm & suspend driver
                  </Button>
                )}
                {c.rider && !c.driver && (
                  <Button variant="danger" onClick={() => review.mutate({ id: c.id, confirm: true, action: "BLOCK_RIDER", note: notes[c.id] ?? "" })}>
                    Confirm & block rider
                  </Button>
                )}
              </div>
            ) : (
              <p className="mt-2 text-xs text-muted">
                {c.status_label} by {c.reviewed_by_name} {c.reviewed_at && dateTime(c.reviewed_at)}
                {c.action_taken && c.action_taken !== "NONE" && ` · ${c.action_taken.replace("_", " ").toLowerCase()}`}
                {c.review_note && ` · “${c.review_note}”`}
              </p>
            )}
          </Card>
        ))}
        {!cases.isLoading && list.length === 0 && <EmptyState icon={<ShieldCheck className="size-6" />} title="Nothing here" />}
      </div>
    </>
  );
}
