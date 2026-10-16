/**
 * Ops: fleet owners, incentive quests, vehicle upkeep, airport queues and the EV network, and the
 * quarterly TDS report.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { BatteryCharging, Building2, Download, Plane, Plus, Target, Wrench } from "lucide-react";
import { Fragment, useState } from "react";
import { toast } from "sonner";

import { StateBadge, STATE_LABEL, type Health as VehicleHealth } from "@/components/DriverBusiness";
import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, Modal, PageHeader, Segmented, Select, Stat, Table, Td, Th, Toggle } from "@/components/ui";
import { useOps } from "@/layouts/OpsLayout";
import { api, ApiError, openFile } from "@/lib/api";
import { inr } from "@/lib/format";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "Something went wrong.");
const localInput = (hours: number) => {
  const d = new Date(Date.now() + hours * 3_600_000);
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
};

// --- Fleet owners ----------------------------------------------------------------------------

interface Owner {
  id: number;
  company_name: string;
  name: string;
  email: string;
  city: number;
  city_name: string;
  gstin: string;
  share_percent: string;
  drivers: number;
  vehicles_count: number;
  manager_name: string | null;
  is_active: boolean;
}

export function OpsFleetOwners() {
  const qc = useQueryClient();
  const { cityInfo, cities } = useOps();
  const q = useQuery({ queryKey: ["ops", "fleet", "owners", cityInfo?.id], queryFn: () => api.get<Owner[]>(`ops/fleet/owners/${cityInfo ? `?city=${cityInfo.id}` : ""}`) });
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState<Owner | null>(null);
  const [driverId, setDriverId] = useState("");
  const blank = { company_name: "", first_name: "", last_name: "", email: "", phone: "", city: "", gstin: "", share_percent: "20" };
  const [f, setF] = useState(blank);
  const create = useMutation({
    mutationFn: () => api.post<Owner>("ops/fleet/owners/", { ...f, city: Number(f.city || cityInfo?.id) }),
    onSuccess: (o) => {
      toast.success(`${o.company_name} signed up`);
      qc.invalidateQueries({ queryKey: ["ops", "fleet", "owners"] });
      setOpen(false);
      setF(blank);
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const attach = useMutation({
    mutationFn: () => api.post(`ops/fleet/owners/${adding!.id}/drivers/`, { driver_id: Number(driverId) }),
    onSuccess: () => {
      toast.success("Driver added to the fleet");
      qc.invalidateQueries({ queryKey: ["ops", "fleet", "owners"] });
      setAdding(null);
      setDriverId("");
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const rows = q.data ?? [];
  return (
    <>
      <PageHeader
        title="Fleet owners"
        subtitle="Partners who own cars and employ drivers. They keep a share of their drivers' trip earnings, paid through the ledger on every trip and settled weekly."
        actions={
          <Button icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>
            Sign up an owner
          </Button>
        }
      />
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Fleet owners" value={rows.length} icon={<Building2 className="size-4" />} tone="brand" />
        <Stat label="Drivers in fleets" value={rows.reduce((n, o) => n + o.drivers, 0)} tone="info" />
        <Stat label="Fleet-owned vehicles" value={rows.reduce((n, o) => n + o.vehicles_count, 0)} />
      </div>
      <Card className="mt-4 overflow-x-auto">
        <Table>
          <thead>
            <tr>
              <Th>Company</Th>
              <Th>City</Th>
              <Th className="text-right">Share</Th>
              <Th className="text-right">Drivers</Th>
              <Th className="text-right">Vehicles</Th>
              <Th>Account manager</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {rows.map((o) => (
              <tr key={o.id} className="border-t border-line">
                <Td>
                  <div className="font-semibold">{o.company_name}</div>
                  <div className="text-xs text-muted">
                    {o.name} · {o.email}
                    {o.gstin && ` · GSTIN ${o.gstin}`}
                  </div>
                </Td>
                <Td>{o.city_name}</Td>
                <Td className="text-right">{Number(o.share_percent)}%</Td>
                <Td className="text-right">{o.drivers}</Td>
                <Td className="text-right">{o.vehicles_count}</Td>
                <Td>{o.manager_name ?? "—"}</Td>
                <Td>
                  <Button size="sm" variant="outline" onClick={() => setAdding(o)}>
                    Add driver
                  </Button>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      <Modal open={open} onClose={() => setOpen(false)} title="Sign up a fleet owner" footer={<Button block loading={create.isPending} onClick={() => create.mutate()}>Create account</Button>}>
        <Field label="Company name">
          <Input value={f.company_name} onChange={(e) => setF({ ...f, company_name: e.target.value })} placeholder="Sri Murugan Travels" />
        </Field>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Field label="First name">
            <Input value={f.first_name} onChange={(e) => setF({ ...f, first_name: e.target.value })} />
          </Field>
          <Field label="Last name">
            <Input value={f.last_name} onChange={(e) => setF({ ...f, last_name: e.target.value })} />
          </Field>
          <Field label="Email">
            <Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
          </Field>
          <Field label="Mobile">
            <Input inputMode="tel" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />
          </Field>
          <Field label="City">
            <Select value={f.city || String(cityInfo?.id ?? "")} onChange={(e) => setF({ ...f, city: e.target.value })}>
              <option value="">Choose…</option>
              {cities.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Owner's share (%)">
            <Input type="number" min={0} max={50} value={f.share_percent} onChange={(e) => setF({ ...f, share_percent: e.target.value })} />
          </Field>
        </div>
        <Field label="GSTIN (optional)" className="mt-3">
          <Input value={f.gstin} maxLength={15} onChange={(e) => setF({ ...f, gstin: e.target.value.toUpperCase() })} />
        </Field>
        <p className="mt-3 text-xs text-muted">They sign in with phone OTP (or a password reset) and see only their own fleet.</p>
      </Modal>

      <Modal open={!!adding} onClose={() => setAdding(null)} title={`Add a driver to ${adding?.company_name ?? ""}`} footer={<Button block disabled={!driverId} loading={attach.isPending} onClick={() => attach.mutate()}>Add driver</Button>}>
        <Field label="Driver ID" hint="From the Drivers page. The driver must work in the same city and not already be in a fleet.">
          <Input inputMode="numeric" value={driverId} onChange={(e) => setDriverId(e.target.value.replace(/\D/g, ""))} />
        </Field>
      </Modal>
    </>
  );
}

// --- Quests ----------------------------------------------------------------------------------

interface QuestRow {
  id: number;
  number: string;
  name: string;
  city_name: string | null;
  state: string;
  ride_type_codes: string[];
  starts_at: string;
  ends_at: string;
  tiers: [number, string][];
  peak_hours_only: boolean;
  min_rating: string | null;
  budget: string;
  spent: string;
  status: "DRAFT" | "LIVE" | "ENDED" | "CANCELLED";
  stats: { drivers: number; trips: number; finished: number; budget_used_percent: number };
}

const STATES = ["Tamil Nadu", "Kerala", "Karnataka", "Andhra Pradesh"];
const TYPES = ["BIKE", "AUTO", "MINI", "SEDAN", "SUV", "PARCEL", "SHARE"];

export function OpsQuests() {
  const qc = useQueryClient();
  const { cities } = useOps();
  const [status, setStatus] = useState("LIVE");
  const q = useQuery({ queryKey: ["ops", "quests", status], queryFn: () => api.get<QuestRow[]>(`ops/fleet/quests/?status=${status}`), refetchInterval: 30_000 });
  const [open, setOpen] = useState(false);
  const blank = { name: "", scope: "state", state: "Tamil Nadu", city: "", types: [] as string[], starts: localInput(0), ends: localInput(72), tiers: "10:150, 20:400", budget: "50000", peak: false, minRating: "" };
  const [f, setF] = useState(blank);
  const create = useMutation({
    mutationFn: () =>
      api.post<QuestRow>("ops/fleet/quests/", {
        name: f.name,
        state: f.scope === "state" ? f.state : "",
        city: f.scope === "city" ? Number(f.city) : null,
        ride_types: f.types,
        starts_at: new Date(f.starts).toISOString(),
        ends_at: new Date(f.ends).toISOString(),
        tiers: f.tiers.split(",").map((pair) => pair.split(":").map((x) => x.trim())),
        budget: f.budget,
        peak_hours_only: f.peak,
        min_rating: f.minRating || null,
      }),
    onSuccess: (quest) => {
      toast.success(`${quest.name} is live; drivers have been told`);
      qc.invalidateQueries({ queryKey: ["ops", "quests"] });
      setOpen(false);
      setF(blank);
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const act = useMutation({
    mutationFn: ({ id, verb }: { id: number; verb: "launch" | "cancel" }) => api.post(`ops/fleet/quests/${id}/${verb}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ops", "quests"] }),
    onError: (err) => toast.error(errorText(err)),
  });
  const rows = q.data ?? [];
  return (
    <>
      <PageHeader
        title="Quests"
        subtitle="Driver incentives without code: trips in a window earn tiered rewards, paid into wallets the moment a tier is reached, within a hard budget."
        actions={
          <Button icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>
            New quest
          </Button>
        }
      />
      <Segmented value={status} onChange={setStatus} options={[{ value: "LIVE", label: "Live" }, { value: "DRAFT", label: "Drafts" }, { value: "ENDED", label: "Ended" }, { value: "CANCELLED", label: "Cancelled" }]} />
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        {rows.map((quest) => (
          <Card key={quest.id} className="p-4">
            <div className="flex items-start gap-2">
              <Target className="mt-0.5 size-5 text-brand-strong" />
              <div className="min-w-0 flex-1">
                <div className="font-semibold">{quest.name}</div>
                <div className="text-xs text-muted">
                  {quest.city_name ?? quest.state} · {new Date(quest.starts_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric" })} – {new Date(quest.ends_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric" })}
                  {quest.ride_type_codes.length > 0 && ` · ${quest.ride_type_codes.join(", ")}`}
                  {quest.peak_hours_only && " · peak hours"}
                  {quest.min_rating && ` · rating ${quest.min_rating}+`}
                </div>
              </div>
              <Badge tone={quest.status === "LIVE" ? "brand" : "neutral"}>{quest.status}</Badge>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
              {quest.tiers.map(([trips, reward]) => (
                <span key={trips} className="rounded-full bg-surface-3 px-2 py-0.5">
                  {trips} trips → {inr(reward, { whole: true })}
                </span>
              ))}
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
              <div>
                <div className="text-lg font-bold">{quest.stats.drivers}</div>drivers taking part
              </div>
              <div>
                <div className="text-lg font-bold">{quest.stats.finished}</div>finished
              </div>
              <div>
                <div className="text-lg font-bold">{quest.stats.budget_used_percent}%</div>
                {inr(quest.spent, { whole: true })} of {inr(quest.budget, { whole: true })}
              </div>
            </div>
            <div className="mt-2 h-1.5 rounded-full bg-surface-3">
              <div className={clsx("h-full rounded-full", quest.stats.budget_used_percent > 85 ? "bg-danger" : "bg-brand")} style={{ width: `${Math.min(100, quest.stats.budget_used_percent)}%` }} />
            </div>
            {(quest.status === "LIVE" || quest.status === "DRAFT") && (
              <div className="mt-3 flex justify-end gap-2">
                {quest.status === "DRAFT" && (
                  <Button size="sm" onClick={() => act.mutate({ id: quest.id, verb: "launch" })}>
                    Launch
                  </Button>
                )}
                <Button size="sm" variant="ghost" className="text-danger" onClick={() => act.mutate({ id: quest.id, verb: "cancel" })}>
                  Cancel
                </Button>
              </div>
            )}
          </Card>
        ))}
      </div>
      {!q.isLoading && rows.length === 0 && <EmptyState icon={<Target className="size-6" />} title="No quests here" />}

      <Modal open={open} onClose={() => setOpen(false)} title="New quest" footer={<Button block loading={create.isPending} disabled={f.name.trim().length < 3} onClick={() => create.mutate()}>Launch quest</Button>}>
        <Field label="Name">
          <Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Weekend warrior" />
        </Field>
        <div className="mt-3">
          <Segmented value={f.scope} onChange={(scope) => setF({ ...f, scope })} options={[{ value: "state", label: "Whole state" }, { value: "city", label: "One city" }]} />
        </div>
        {f.scope === "state" ? (
          <Select className="mt-2" value={f.state} onChange={(e) => setF({ ...f, state: e.target.value })}>
            {STATES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </Select>
        ) : (
          <Select className="mt-2" value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })}>
            <option value="">Choose a city…</option>
            {cities.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        )}
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Field label="Starts">
            <Input type="datetime-local" value={f.starts} onChange={(e) => setF({ ...f, starts: e.target.value })} />
          </Field>
          <Field label="Ends">
            <Input type="datetime-local" value={f.ends} onChange={(e) => setF({ ...f, ends: e.target.value })} />
          </Field>
        </div>
        <Field label="Reward tiers (trips:₹ total, comma separated)" className="mt-3">
          <Input value={f.tiers} onChange={(e) => setF({ ...f, tiers: e.target.value })} />
        </Field>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {TYPES.map((code) => (
            <button key={code} onClick={() => setF({ ...f, types: f.types.includes(code) ? f.types.filter((x) => x !== code) : [...f.types, code] })} className={clsx("rounded-full border px-2.5 py-1 text-xs font-semibold", f.types.includes(code) ? "border-fg bg-ink text-ink-fg" : "border-line text-muted")}>
              {code}
            </button>
          ))}
          <span className="self-center text-xs text-muted">(none = every ride type)</span>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Field label="Budget (₹)">
            <Input type="number" value={f.budget} onChange={(e) => setF({ ...f, budget: e.target.value })} />
          </Field>
          <Field label="Minimum rating">
            <Input type="number" step="0.1" min={0} max={5} value={f.minRating} onChange={(e) => setF({ ...f, minRating: e.target.value })} placeholder="Any" />
          </Field>
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm">
          <Toggle checked={f.peak} onChange={(peak) => setF({ ...f, peak })} label="Peak hours only" /> Peak hours only (7–10 am, 5–9 pm)
        </label>
      </Modal>
    </>
  );
}

// --- Vehicle upkeep --------------------------------------------------------------------------

interface Upkeep {
  vehicles: number;
  action: number;
  soon: number;
  service_overdue: number;
  insurance_expired: number;
  by_state: Record<"OK" | "DUE" | "OVERDUE" | "IN_WORKSHOP" | "OFF_ROAD", number>;
  open_issues: number;
  checked_today: number;
  spend_30d: string;
  attention: (VehicleHealth & { ride_type: string })[];
}
type Detail = VehicleHealth & { inspections: { inspected_on: string; passed: boolean; items: Record<string, boolean> }[] };

export function OpsUpkeep() {
  const { cityInfo } = useOps();
  const qc = useQueryClient();
  const [filter, setFilter] = useState<string>("");
  const [open, setOpen] = useState<number | null>(null);
  const q = useQuery({ queryKey: ["ops", "upkeep", cityInfo?.id], queryFn: () => api.get<Upkeep>(`ops/fleet/upkeep/${cityInfo ? `?city=${cityInfo.id}` : ""}`), refetchInterval: 30_000 });
  const detail = useQuery({ queryKey: ["ops", "upkeep", "vehicle", open], queryFn: () => api.get<Detail>(`ops/fleet/upkeep/${open}/`), enabled: open != null });
  const condition = useMutation({
    mutationFn: ({ id, ...body }: { id: number; condition: string; note: string }) => api.post(`ops/fleet/upkeep/${id}/condition/`, body),
    onSuccess: () => {
      toast.success("Vehicle updated");
      qc.invalidateQueries({ queryKey: ["ops", "upkeep"] });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Something went wrong."),
  });
  const d = q.data;
  const rows = (d?.attention ?? []).filter((v) => !filter || v.state === filter);
  const states = ["OFF_ROAD", "IN_WORKSHOP", "OVERDUE", "DUE"] as const;
  return (
    <>
      <PageHeader title={`Vehicle health · ${cityInfo?.name ?? "All cities"}`} subtitle="Every car is on the road, needs attention, overdue, in the workshop, or off the road (unsafe). Drivers do a daily safety check; a failed brake, tyre, light or belt, a breakdown or an accident takes the car off the road until the repair is logged." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Active vehicles" value={d?.vehicles ?? "—"} icon={<Wrench className="size-4" />} sub={d ? `${d.by_state.OK} on the road, all clear` : ""} />
        <Stat label="Off the road" value={d?.by_state.OFF_ROAD ?? "—"} tone="danger" sub={d ? `${d.by_state.IN_WORKSHOP} in the workshop` : ""} />
        <Stat label="Overdue" value={d?.by_state.OVERDUE ?? "—"} tone="warning" sub={d ? `${d.service_overdue} service · ${d.insurance_expired} insurance` : ""} />
        <Stat label="Open faults" value={d?.open_issues ?? "—"} sub={d ? `${d.by_state.DUE} cars need attention soon` : ""} />
        <Stat label="Daily checks today" value={d ? `${Math.round((100 * d.checked_today) / Math.max(1, d.vehicles))}%` : "—"} sub={d ? `upkeep spend 30 d ${inr(d.spend_30d)}` : ""} tone="info" />
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button size="sm" variant={filter === "" ? "primary" : "outline"} onClick={() => setFilter("")}>
          All needing attention
        </Button>
        {states.map((s) => (
          <Button key={s} size="sm" variant={filter === s ? "primary" : "outline"} onClick={() => setFilter(s)}>
            {STATE_LABEL[s]} {d ? `(${d.by_state[s]})` : ""}
          </Button>
        ))}
      </div>
      <Card className="mt-3 overflow-x-auto">
        <Table>
          <thead>
            <tr>
              <Th>Vehicle</Th>
              <Th>Driver</Th>
              <Th>State</Th>
              <Th>Why</Th>
              <Th className="text-right">Odometer</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {rows.map((v) => (
              <Fragment key={v.id}>
                <tr className="cursor-pointer border-t border-line hover:bg-surface-2" onClick={() => setOpen(open === v.id ? null : v.id)}>
                  <Td>
                    <div className="font-semibold">{v.registration}</div>
                    <div className="text-xs text-muted">
                      {v.name} · {v.ride_type}
                    </div>
                  </Td>
                  <Td>{v.driver ?? "—"}</Td>
                  <Td>
                    <StateBadge state={v.state} />
                  </Td>
                  <Td className="max-w-md text-xs">
                    {[
                      v.condition_note,
                      ...v.open_issues.map((i) => `${i.kind_label}${i.description ? `: ${i.description}` : ""} (${i.source.toLowerCase()})`),
                      v.service === "OVERDUE" ? `service overdue by ${-v.service_due_in_km} km` : v.service === "DUE_SOON" ? `service in ${v.service_due_in_km} km` : "",
                      ...v.documents.filter((doc) => doc.status !== "OK").map((doc) => `${doc.document} ${doc.status === "EXPIRED" ? "expired" : "expires"} ${doc.expires_on}`),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </Td>
                  <Td className="text-right">{v.odometer_km.toLocaleString("en-IN")} km</Td>
                  <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                    {v.state === "IN_WORKSHOP" ? (
                      <Button size="sm" variant="outline" onClick={() => condition.mutate({ id: v.id, condition: "ACTIVE", note: "Back from the workshop" })}>
                        Back on road
                      </Button>
                    ) : v.state !== "OFF_ROAD" ? (
                      <Button size="sm" variant="ghost" onClick={() => condition.mutate({ id: v.id, condition: "IN_WORKSHOP", note: "Called in by operations" })}>
                        To workshop
                      </Button>
                    ) : null}
                  </td>
                </tr>
                {open === v.id && (
                  <tr className="bg-surface-2">
                    <td colSpan={6} className="px-4 py-3 text-xs">
                      {!detail.data ? (
                        "Loading…"
                      ) : (
                        <div className="grid gap-4 md:grid-cols-[1fr_260px]">
                          <div>
                            <div className="mb-1 font-semibold">
                              Service history · {detail.data.costs?.visits ?? 0} visits, {inr(detail.data.costs?.spend ?? "0")} this year
                              {detail.data.costs?.cost_per_km && ` · ${inr(detail.data.costs.cost_per_km)}/km`}
                            </div>
                            {(detail.data.history ?? []).map((h) => (
                              <div key={h.id} className="border-t border-line py-1">
                                <span className="font-semibold">{h.kind_label}</span> · {h.serviced_on} · {h.odometer_km.toLocaleString("en-IN")} km · {h.workshop || "—"} · {inr(h.total_cost)}
                                {h.invoice_number && ` · ${h.invoice_number}`}
                                {h.parts.length > 0 && <span className="text-muted"> · {h.parts.map((p) => `${p.name} ${inr(p.cost)}`).join(", ")}</span>}
                                {h.fixed.length > 0 && <span className="text-brand"> · fixed {h.fixed.join(", ").toLowerCase()}</span>}
                              </div>
                            ))}
                            {(detail.data.history ?? []).length === 0 && <div className="text-muted">No service on record.</div>}
                          </div>
                          <div>
                            <div className="mb-1 font-semibold">Daily checks (last 2 weeks)</div>
                            <div className="flex flex-wrap gap-1">
                              {detail.data.inspections.map((c, i) => (
                                <span key={i} title={Object.entries(c.items).filter(([, ok]) => !ok).map(([k]) => k).join(", ") || "all OK"} className={clsx("rounded px-1.5 py-0.5", c.passed ? "bg-brand/15 text-brand" : "bg-danger/15 text-danger")}>
                                  {c.inspected_on.slice(5)}
                                </span>
                              ))}
                              {detail.data.inspections.length === 0 && <span className="text-muted">None</span>}
                            </div>
                          </div>
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </Table>
        {rows.length === 0 && <p className="p-4 text-sm text-muted">Nothing here.</p>}
      </Card>
    </>
  );
}

// --- Airports and EVs ------------------------------------------------------------------------

export function OpsAirportsEv() {
  const airports = useQuery({ queryKey: ["ops", "airports"], queryFn: () => api.get<{ zone_id: number; airport: string; city: string; waiting: number; served_24h: number; pickups_24h: number; avg_wait_minutes: number | null }[]>("ops/fleet/airports/"), refetchInterval: 20_000 });
  const ev = useQuery({ queryKey: ["ops", "ev"], queryFn: () => api.get<{ ev_vehicles: number; share_percent: number; low_battery: number; chargers: number; chargers_by_city: Record<string, number> }>("ops/fleet/electric/") });
  const e = ev.data;
  return (
    <>
      <PageHeader title="Airports & EVs" subtitle="Airport pickups go to drivers waiting in the airport's virtual queue, first come first served. Electric cars only get trips their battery can finish." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Electric vehicles" value={e?.ev_vehicles ?? "—"} sub={e ? `${e.share_percent}% of the fleet` : ""} icon={<BatteryCharging className="size-4" />} tone="brand" />
        <Stat label="Low battery now" value={e?.low_battery ?? "—"} tone={e?.low_battery ? "warning" : "neutral"} />
        <Stat label="Charging stations" value={e?.chargers ?? "—"} sub={e ? `${Object.keys(e.chargers_by_city).length} cities` : ""} />
        <Stat label="Drivers in airport queues" value={(airports.data ?? []).reduce((n, a) => n + a.waiting, 0)} icon={<Plane className="size-4" />} tone="info" />
      </div>
      <Card className="mt-4 overflow-x-auto">
        <div className="p-4 pb-0">
          <CardHeader title="Airport queues" />
        </div>
        <Table>
          <thead>
            <tr>
              <Th>Airport</Th>
              <Th className="text-right">Waiting now</Th>
              <Th className="text-right">Pickups (24 h)</Th>
              <Th className="text-right">Served from queue</Th>
              <Th className="text-right">Avg wait</Th>
            </tr>
          </thead>
          <tbody>
            {(airports.data ?? []).map((a) => (
              <tr key={a.zone_id} className="border-t border-line">
                <Td>
                  <div className="font-semibold">{a.airport}</div>
                  <div className="text-xs text-muted">{a.city}</div>
                </Td>
                <Td className="text-right">{a.waiting}</Td>
                <Td className="text-right">{a.pickups_24h}</Td>
                <Td className="text-right">{a.served_24h}</Td>
                <Td className="text-right">{a.avg_wait_minutes != null ? `${a.avg_wait_minutes} min` : "—"}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </>
  );
}

// --- TDS -------------------------------------------------------------------------------------

export function OpsTds() {
  const now = new Date();
  const fy = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
  const [year, setYear] = useState(String(fy));
  const [quarter, setQuarter] = useState(String({ 3: 1, 4: 1, 5: 1, 6: 2, 7: 2, 8: 2, 9: 3, 10: 3, 11: 3 }[now.getMonth()] ?? 4));
  const q = useQuery({
    queryKey: ["ops", "tds", year, quarter],
    queryFn: () => api.get<{ financial_year: string; from: string; to: string; statements: number; drivers: number; gross_fares: string; tds_withheld: string; without_pan: number; rows: { driver_id: number; name: string; pan_on_file: boolean; gross_fares: string; tds: string }[] }>(`ops/fleet/tds/?year=${year}&quarter=${quarter}`),
  });
  const r = q.data;
  return (
    <>
      <PageHeader
        title="TDS (section 194-O)"
        subtitle="Income tax withheld from drivers' gross fares in their weekly statements: 0.1% with a PAN on file, 5% without. This backs the quarterly TDS return (Form 26Q)."
        actions={
          <div className="flex gap-2">
            <Select value={year} onChange={(e) => setYear(e.target.value)} className="!w-auto">
              {[fy, fy - 1].map((y) => (
                <option key={y} value={y}>
                  FY {y}-{String(y + 1).slice(2)}
                </option>
              ))}
            </Select>
            <Select value={quarter} onChange={(e) => setQuarter(e.target.value)} className="!w-auto">
              {["1", "2", "3", "4"].map((qq) => (
                <option key={qq} value={qq}>
                  Q{qq}
                </option>
              ))}
            </Select>
            <Button variant="outline" icon={<Download className="size-4" />} onClick={() => openFile(`/api/v1/ops/fleet/tds/?year=${year}&quarter=${quarter}&export=csv`)}>
              CSV
            </Button>
          </div>
        }
      />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Gross fares" value={r ? inr(r.gross_fares, { whole: true }) : "—"} sub={r ? `${r.from} – ${r.to}` : ""} />
        <Stat label="TDS withheld" value={r ? inr(r.tds_withheld) : "—"} tone="brand" />
        <Stat label="Drivers" value={r?.drivers ?? "—"} sub={r ? `${r.statements} weekly statements` : ""} />
        <Stat label="Without PAN (5%)" value={r?.without_pan ?? "—"} tone={r?.without_pan ? "warning" : "neutral"} />
      </div>
      <Card className="mt-4 overflow-x-auto">
        <Table>
          <thead>
            <tr>
              <Th>Driver</Th>
              <Th>PAN</Th>
              <Th className="text-right">Gross fares</Th>
              <Th className="text-right">TDS</Th>
            </tr>
          </thead>
          <tbody>
            {(r?.rows ?? []).map((row) => (
              <tr key={row.driver_id} className="border-t border-line">
                <Td>{row.name}</Td>
                <Td>{row.pan_on_file ? <Badge tone="brand">On file</Badge> : <Badge tone="warning">Missing</Badge>}</Td>
                <Td className="text-right">{inr(row.gross_fares)}</Td>
                <Td className="text-right font-semibold">{inr(row.tds)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </>
  );
}
