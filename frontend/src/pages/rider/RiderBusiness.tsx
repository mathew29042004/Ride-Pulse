/** Corporate portal: spend, travel policy, employees, the monthly GST invoice and webhooks. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, Webhook } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { toast } from "sonner";

import { PlacePick, type Picked } from "@/components/PlacePick";
import { Button, Input } from "@/components/ui";
import { api, ApiError, openFile } from "@/lib/api";
import { inr } from "@/lib/format";
import { t } from "@/lib/i18n";

interface Board {
  id: number;
  company: string;
  gstin: string;
  balance: string;
  credit_limit: string;
  policy: { allowed_ride_types: string[]; allowed_from_hour: number | null; allowed_to_hour: number | null; max_fare_per_trip: string | null; cost_centers: string[] };
  this_month: { spend: string; rides: number };
  by_month: { month: string; spend: string; rides: number }[];
  by_employee: { rider_id: number; name: string; spend: string; rides: number }[];
  by_cost_center: { cost_center: string; spend: string; rides: number }[];
  by_ride_type: { ride_type: string; spend: string; rides: number }[];
  employees: { member_id: number; name: string; status: string; is_admin: boolean; monthly_limit: string | null; default_cost_center: string }[];
  recent: { trip_number: string; employee: string; when: string; route: string; ride_type: string; fare: string; purpose: string; cost_center: string }[];
  webhooks: { id: number; name: string; url: string; is_active: boolean }[];
}

const TYPES = ["AUTO", "MINI", "SEDAN", "SUV", "SHARE", "BIKE"];

export default function RiderBusiness() {
  const { id } = useParams();
  const qc = useQueryClient();
  const key = ["business", id];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<Board>(`rider/business/${id}/`), refetchInterval: 60_000 });
  const done = (data: Board) => qc.setQueryData(key, data);
  const onError = (err: unknown) => toast.error(err instanceof ApiError ? err.message : t("Something went wrong."));
  const policy = useMutation({ mutationFn: (body: object) => api.post<Board>(`rider/business/${id}/policy/`, body), onSuccess: (d) => { done(d); toast.success(t("Travel policy saved")); }, onError });
  const employee = useMutation({ mutationFn: (body: object) => api.post<Board>(`rider/business/${id}/employee/`, body), onSuccess: done, onError });
  const [hook, setHook] = useState({ name: "", url: "" });
  const [secret, setSecret] = useState<string | null>(null);
  const webhook = useMutation({
    mutationFn: () => api.post<{ secret: string }>(`rider/business/${id}/webhook/`, hook),
    onSuccess: (r) => {
      setSecret(r.secret);
      setHook({ name: "", url: "" });
      qc.invalidateQueries({ queryKey: key });
    },
    onError,
  });
  const b = q.data;
  const [centres, setCentres] = useState<string | null>(null);
  const [cap, setCap] = useState<string | null>(null);
  if (!b) return <div className="p-5 text-sm text-muted">{t("Loading…")}</div>;
  const month = new Date().toISOString().slice(0, 7);
  return (
    <div className="h-full overflow-y-auto px-5 pt-5 pb-8">
      <Link to="/ride/account" className="mb-3 inline-flex items-center gap-1 text-sm text-muted">
        <ArrowLeft className="size-4" /> {t("Account")}
      </Link>
      <h1 className="text-2xl font-bold">{b.company}</h1>
      <p className="text-sm text-muted">
        {b.gstin && `GSTIN ${b.gstin} · `}
        {t("Balance {balance} · credit up to {credit}", { balance: inr(b.balance), credit: inr(b.credit_limit, { whole: true }) })}
      </p>

      <div className="mt-4 grid grid-cols-2 gap-2">
        <div className="rounded-2xl bg-surface-2 p-3">
          <div className="text-xs text-muted">{t("Spend this month")}</div>
          <div className="text-xl font-bold">{inr(b.this_month.spend, { whole: true })}</div>
          <div className="text-xs text-muted">{t("{n} rides", { n: b.this_month.rides })}</div>
        </div>
        <button onClick={() => openFile(`/api/v1/rider/business/${id}/invoice/?month=${month}`)} className="flex flex-col items-start justify-between rounded-2xl bg-surface-2 p-3 text-left">
          <span className="text-xs text-muted">{t("GST invoice")}</span>
          <span className="flex items-center gap-1 text-sm font-semibold">
            <Download className="size-4" /> {t("This month (PDF)")}
          </span>
        </button>
      </div>

      {b.by_month.length > 0 && (
        <div className="mt-4 h-36 rounded-2xl border border-line p-2">
          <ResponsiveContainer>
            <BarChart data={b.by_month.map((m) => ({ ...m, spend: Number(m.spend) }))}>
              <XAxis dataKey="month" tick={{ fontSize: 10 }} />
              <Tooltip formatter={(v) => inr(Number(v), { whole: true })} />
              <Bar dataKey="spend" fill="var(--color-brand)" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <Section title={t("By employee")}>
        {b.by_employee.length === 0 && <p className="text-sm text-muted">{t("No rides on the company yet this month.")}</p>}
        {b.by_employee.map((e) => (
          <Row key={e.rider_id} left={e.name} right={`${inr(e.spend, { whole: true })} · ${e.rides}`} />
        ))}
      </Section>
      <Section title={t("By cost centre")}>
        {b.by_cost_center.length === 0 && <p className="text-sm text-muted">—</p>}
        {b.by_cost_center.map((c) => (
          <Row key={c.cost_center} left={c.cost_center} right={`${inr(c.spend, { whole: true })} · ${c.rides}`} />
        ))}
      </Section>

      <Section title={t("Travel policy")}>
        <div className="flex flex-wrap gap-1.5">
          {TYPES.map((code) => {
            const on = b.policy.allowed_ride_types.includes(code);
            return (
              <button
                key={code}
                onClick={() => policy.mutate({ allowed_ride_types: on ? b.policy.allowed_ride_types.filter((x) => x !== code) : [...b.policy.allowed_ride_types, code] })}
                className={on ? "rounded-full border border-fg bg-ink px-2.5 py-1 text-xs font-semibold text-ink-fg" : "rounded-full border border-line px-2.5 py-1 text-xs font-semibold text-muted"}
              >
                {code}
              </button>
            );
          })}
        </div>
        <p className="mt-1 text-xs text-muted">{b.policy.allowed_ride_types.length ? t("Only these ride types.") : t("Every ride type allowed.")}</p>
        <div className="mt-2 flex gap-2">
          <Input inputMode="numeric" value={cap ?? b.policy.max_fare_per_trip ?? ""} onChange={(e) => setCap(e.target.value.replace(/\D/g, ""))} placeholder={t("Max fare per trip (₹)")} className="!py-2" />
          <Button size="sm" variant="secondary" onClick={() => policy.mutate({ max_fare_per_trip: cap ? Number(cap) : null })}>
            {t("Save")}
          </Button>
        </div>
        <div className="mt-2 flex gap-2">
          <Input value={centres ?? b.policy.cost_centers.join(", ")} onChange={(e) => setCentres(e.target.value)} placeholder={t("Cost centres, comma separated")} className="!py-2" />
          <Button size="sm" variant="secondary" onClick={() => policy.mutate({ cost_centers: (centres ?? "").split(",").map((c) => c.trim()).filter(Boolean) })}>
            {t("Save")}
          </Button>
        </div>
        {b.policy.allowed_from_hour != null && <p className="mt-1 text-xs text-muted">{t("Rides covered {from}:00 – {to}:00", { from: b.policy.allowed_from_hour, to: b.policy.allowed_to_hour ?? 0 })}</p>}
      </Section>

      <Section title={t("Employees ({n})", { n: b.employees.length })}>
        {b.employees.map((e) => (
          <div key={e.member_id} className="flex items-center gap-2 py-1.5 text-sm">
            <span className="min-w-0 flex-1 truncate">
              {e.name} {e.is_admin && <span className="text-xs font-semibold text-brand-strong">· {t("travel admin")}</span>}
            </span>
            <select
              value={e.default_cost_center}
              onChange={(ev) => employee.mutate({ member_id: e.member_id, default_cost_center: ev.target.value })}
              className="rounded-lg border border-line bg-surface px-1.5 py-1 text-xs"
              aria-label={t("Cost centre for {name}", { name: e.name })}
            >
              <option value="">—</option>
              {b.policy.cost_centers.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </div>
        ))}
      </Section>

      <Section title={t("Recent rides")}>
        {b.recent.map((r) => (
          <div key={r.trip_number} className="border-t border-line py-2 text-xs first:border-0">
            <div className="flex justify-between font-semibold">
              <span>{r.employee}</span>
              <span>{inr(r.fare)}</span>
            </div>
            <div className="truncate text-muted">{r.route}</div>
            <div className="text-muted">
              {r.purpose}
              {r.cost_center && ` · ${r.cost_center}`} · {r.ride_type}
            </div>
          </div>
        ))}
      </Section>

      <CommuteSection id={b.id} />
      <Co2Section id={b.id} />
      <Section title={t("Webhooks")}>
        <p className="text-xs text-muted">{t("Get your employees' trips in your own systems (expense tools, HR). Signed, retried, at least once.")}</p>
        {b.webhooks.map((w) => (
          <div key={w.id} className="mt-1 flex items-center gap-2 text-xs">
            <Webhook className="size-3.5" /> <span className="truncate">{w.url}</span>
          </div>
        ))}
        <div className="mt-2 grid gap-2">
          <Input value={hook.name} onChange={(e) => setHook({ ...hook, name: e.target.value })} placeholder={t("Name")} className="!py-2" />
          <Input value={hook.url} onChange={(e) => setHook({ ...hook, url: e.target.value })} placeholder="https://…" className="!py-2" />
          <Button size="sm" variant="secondary" disabled={!hook.name || !hook.url} onClick={() => webhook.mutate()}>
            {t("Add webhook")}
          </Button>
        </div>
        {secret && <code className="mt-2 block rounded-xl bg-surface-2 p-2 text-[11px] break-all">{t("Signing secret (shown once):")} {secret}</code>}
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-5">
      <h2 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{title}</h2>
      {children}
    </div>
  );
}

function Row({ left, right }: { left: string; right: string }) {
  return (
    <div className="flex justify-between py-1 text-sm">
      <span className="truncate">{left}</span>
      <span className="shrink-0 font-semibold">{right}</span>
    </div>
  );
}

interface CommutePlanRow {
  id: number;
  name: string;
  office_name: string;
  ride_type_name: string;
  weekdays_label: string;
  arrive_by: string;
  leave_at: string;
  is_active: boolean;
  enrolled: number;
  this_month: { booked: number; completed: number; failed: number; cost: string | number };
  employees: { name: string; home_address: string; morning: boolean; evening: boolean; skipping: string[] }[];
}

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Office commute plans: set up a shift; employees join from their app; rides are booked nightly. */
function CommuteSection({ id }: { id: number }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["business", id, "commute"], queryFn: () => api.get<{ plans: CommutePlanRow[] }>(`rider/business/${id}/commute/`) });
  const refresh = () => qc.invalidateQueries({ queryKey: ["business", id, "commute"] });
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : t("Something went wrong."));
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("General shift");
  const [office, setOffice] = useState<Picked | null>(null);
  const [rideType, setRideType] = useState("MINI");
  const [days, setDays] = useState([0, 1, 2, 3, 4]);
  const [arrive, setArrive] = useState("09:30");
  const [leave, setLeave] = useState("18:30");
  const [pool, setPool] = useState(false);
  const create = useMutation({
    mutationFn: () =>
      api.post(`rider/business/${id}/commute/plan/`, { name, office_name: office!.name, office_lat: office!.lat, office_lng: office!.lng, ride_type: rideType, weekdays: days, arrive_by: arrive, leave_at: leave, pool }),
    onSuccess: () => { toast.success(t("Plan created. Employees can join it from their app.")); setOpen(false); refresh(); },
    onError: fail,
  });
  const stop = useMutation({ mutationFn: (plan: number) => api.post(`rider/business/${id}/commute/${plan}/stop/`), onSuccess: refresh, onError: fail });
  return (
    <Section title={t("Office commute")}>
      {q.data?.plans.map((p) => (
        <div key={p.id} className="mb-2 rounded-2xl border border-line p-3 text-sm">
          <div className="flex justify-between font-semibold">
            <span>{p.name} · {p.office_name}</span>
            {p.is_active ? <button className="text-xs text-danger" onClick={() => stop.mutate(p.id)}>{t("Stop")}</button> : <span className="text-xs text-muted">{t("Stopped")}</span>}
          </div>
          <div className="text-xs text-muted">{p.weekdays_label} · {p.arrive_by}–{p.leave_at} · {p.ride_type_name} · {t("{n} employees", { n: p.enrolled })}</div>
          <div className="mt-1 text-xs">
            {t("This month: {b} rides booked, {c} completed, {f} couldn't be booked · {cost}", { b: p.this_month.booked, c: p.this_month.completed, f: p.this_month.failed, cost: inr(p.this_month.cost) })}
          </div>
          {p.employees.map((e) => (
            <div key={e.name} className="mt-1 text-xs text-muted">
              {e.name}: {e.home_address || "—"} {e.skipping.length > 0 && `· ${t("skipping")} ${e.skipping.join(", ")}`}
            </div>
          ))}
        </div>
      ))}
      {open ? (
        <div className="space-y-2 rounded-2xl border border-line p-3 text-sm">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("Plan name")} />
          <PlacePick value={office} onChange={setOffice} placeholder={t("Search for the office")} />
          <div className="flex flex-wrap gap-1">
            {DAYS.map((d, i) => (
              <button key={d} onClick={() => setDays(days.includes(i) ? days.filter((x) => x !== i) : [...days, i])} className={`rounded-lg px-2 py-1 text-xs ${days.includes(i) ? "bg-ink text-ink-fg" : "bg-surface-2"}`}>{t(d)}</button>
            ))}
          </div>
          <div className="grid grid-cols-3 gap-2">
            <label className="text-xs">{t("Arrive by")}<Input type="time" value={arrive} onChange={(e) => setArrive(e.target.value)} /></label>
            <label className="text-xs">{t("Leave at")}<Input type="time" value={leave} onChange={(e) => setLeave(e.target.value)} /></label>
            <label className="text-xs">{t("Ride type")}
              <select className="mt-1 w-full rounded-xl border border-line bg-transparent p-2" value={rideType} onChange={(e) => setRideType(e.target.value)}>
                {["MINI", "SEDAN", "SUV", "AUTO"].map((r) => <option key={r}>{r}</option>)}
              </select>
            </label>
          </div>
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={pool} onChange={(e) => setPool(e.target.checked)} />
            {t("Colleagues who live close share a cab (cheaper)")}
          </label>
          <Button block disabled={!office || !days.length} loading={create.isPending} onClick={() => create.mutate()}>{t("Create plan")}</Button>
        </div>
      ) : (
        <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>{t("New commute plan")}</Button>
      )}
    </Section>
  );
}

interface Co2 {
  month: string;
  trips: number;
  km: number;
  co2_kg: number;
  saved_kg: number;
  electric_share_pct: number;
  grams_per_km: number;
  by_ride_type: { ride_type: string; trips: number; km: number; co2_kg: number }[];
  trend: { month: string; co2_kg: number }[];
  method: string;
}

/** Monthly CO₂ for the company's sustainability reporting, with a CSV for auditors. */
function Co2Section({ id }: { id: number }) {
  const q = useQuery({ queryKey: ["business", id, "co2"], queryFn: () => api.get<Co2>(`rider/business/${id}/co2/`) });
  const c = q.data;
  if (!c) return null;
  const max = Math.max(1, ...c.trend.map((m) => m.co2_kg));
  return (
    <Section title={t("CO₂ report")}>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <Row left={t("CO₂ emitted")} right={`${c.co2_kg} kg`} />
        <Row left={t("Saved vs own cars")} right={`${c.saved_kg} kg`} />
        <Row left={t("Electric share")} right={`${c.electric_share_pct}%`} />
        <Row left={t("Per km")} right={`${c.grams_per_km} g`} />
      </div>
      <div className="mt-3 flex h-16 items-end gap-1">
        {c.trend.map((m) => (
          <div key={m.month} className="flex flex-1 flex-col items-center gap-1" title={`${m.month}: ${m.co2_kg} kg`}>
            <div className="w-full rounded-t bg-brand/60" style={{ height: `${Math.max(4, (56 * m.co2_kg) / max)}px` }} />
            <span className="text-[9px] text-muted">{m.month.slice(5)}</span>
          </div>
        ))}
      </div>
      <p className="mt-2 text-xs text-muted">{t("Estimates by vehicle type; electric cars count the grid's share.")}</p>
      <Button className="mt-2" size="sm" variant="secondary" icon={<Download className="size-4" />} onClick={() => openFile(`rider/business/${id}/co2/?export=csv`)}>
        {t("Download CSV")}
      </Button>
    </Section>
  );
}
