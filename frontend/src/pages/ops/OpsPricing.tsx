import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { RefreshCw, Zap } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button, Card, CardHeader, EmptyState, Field, Input, Modal, PageHeader, Select, Table, Td, Th } from "@/components/ui";
import { useOps } from "@/layouts/OpsLayout";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ago, dateTime, inr } from "@/lib/format";
import type { FareRule, Paginated, SurgeOverride, SurgeZone } from "@/lib/types";

import { LiveMap } from "./LiveMap";

export default function OpsPricing() {
  const { city, cityInfo, cities, setCity } = useOps();
  const { can } = useAuth();
  const qc = useQueryClient();
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [editing, setEditing] = useState<FareRule | null>(null);
  const [override, setOverride] = useState({ zone: "", multiplier: "1.5", hours: "2", reason: "" });
  const board = useQuery({ queryKey: ["surge", "board", city], queryFn: () => api.get<SurgeZone[]>(`surge/board/?city=${city}`), enabled: !!city, refetchInterval: 20_000 });
  const overrides = useQuery({ queryKey: ["surge", "overrides"], queryFn: () => api.get<SurgeOverride[]>("surge/overrides/") });
  const fares = useQuery({ queryKey: ["fare-rules", city], queryFn: () => api.get<Paginated<FareRule>>(`fare-rules/?city__slug=${city}&page_size=50`) });

  const recompute = useMutation({
    mutationFn: () => api.post<{ snapshots: number }>("surge/recompute/"),
    onSuccess: (r) => {
      toast.success(`Recomputed ${r.snapshots} zone multipliers from live demand and supply`);
      qc.invalidateQueries({ queryKey: ["surge"] });
    },
  });
  const createOverride = useMutation({
    mutationFn: () => {
      const start = new Date();
      const end = new Date(start.getTime() + Number(override.hours) * 3600_000);
      return api.post("surge/overrides/", { zone: Number(override.zone), multiplier: override.multiplier, starts_at: start.toISOString(), ends_at: end.toISOString(), reason: override.reason });
    },
    onSuccess: () => {
      toast.success("Surge override is live");
      setOverrideOpen(false);
      qc.invalidateQueries({ queryKey: ["surge"] });
    },
    onError: (err) => toast.error((err as Error).message),
  });
  const saveFare = useMutation({
    mutationFn: (rule: FareRule) => api.patch(`fare-rules/${rule.id}/`, rule),
    onSuccess: () => {
      toast.success("Fare card updated. New quotes use it immediately.");
      setEditing(null);
      qc.invalidateQueries({ queryKey: ["fare-rules"] });
    },
    onError: (err) => toast.error((err as Error).message),
  });

  if (!city) {
    return (
      <>
        <PageHeader title="Pricing & surge" />
        <Card>
          <EmptyState icon={<Zap />} title="Choose a city" action={<div className="flex gap-2">{cities.map((c) => <Button key={c.slug} variant="outline" onClick={() => setCity(c.slug)}>{c.name}</Button>)}</div>}>
            Surge is computed per zone, so pricing is managed one city at a time.
          </EmptyState>
        </Card>
      </>
    );
  }

  const zones = [...(board.data ?? [])].sort((a, b) => Number(b.multiplier) - Number(a.multiplier));
  return (
    <>
      <PageHeader
        title={`Pricing & surge · ${cityInfo?.name}`}
        subtitle="Multipliers update every 2 minutes from demand (requests) versus supply (free drivers) in each zone"
        actions={
          can("pricing.manage") && (
            <>
              <Button variant="outline" icon={<RefreshCw className="size-4" />} onClick={() => recompute.mutate()} loading={recompute.isPending}>
                Recompute now
              </Button>
              <Button icon={<Zap className="size-4" />} onClick={() => setOverrideOpen(true)}>
                Manual surge
              </Button>
            </>
          )
        }
      />
      <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
        <Card className="h-[420px] overflow-hidden">
          <LiveMap city={city} cityInfo={cityInfo} surge={board.data} />
        </Card>
        <Card className="max-h-[420px] overflow-y-auto">
          <CardHeader title="Zones" subtitle="Demand / free drivers in the last 10 minutes" />
          <div className="divide-y divide-line">
            {zones.map((z) => {
              const m = Number(z.multiplier);
              return (
                <div key={z.zone_id} className="flex items-center gap-3 px-5 py-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold">{z.zone}</div>
                    <div className="text-xs text-muted">
                      {z.demand} requests · {z.supply} free cars · {z.computed_at ? ago(z.computed_at) : "no data"}
                    </div>
                  </div>
                  <div className="w-24">
                    <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
                      <div className={clsx("h-full rounded-full", m > 1.5 ? "bg-danger" : m > 1 ? "bg-amber-500" : "bg-brand")} style={{ width: `${Math.min(100, ((m - 1) / 2) * 100 + 4)}%` }} />
                    </div>
                  </div>
                  <span className={clsx("w-12 text-right text-sm font-bold", m > 1 && "text-amber-600")}>{z.multiplier}×</span>
                </div>
              );
            })}
          </div>
        </Card>
      </div>

      {(overrides.data ?? []).length > 0 && (
        <Card className="mt-4">
          <CardHeader title="Active manual overrides" />
          <Table>
            <thead>
              <tr>
                <Th>Zone</Th>
                <Th>Multiplier</Th>
                <Th>Window</Th>
                <Th>Reason</Th>
              </tr>
            </thead>
            <tbody>
              {overrides.data!.map((o) => (
                <tr key={o.id}>
                  <Td>{cityInfo?.zones.find((z) => z.id === o.zone)?.name ?? `Zone ${o.zone}`}</Td>
                  <Td className="font-semibold">{o.multiplier}×</Td>
                  <Td>
                    {dateTime(o.starts_at)} → {dateTime(o.ends_at)}
                  </Td>
                  <Td>{o.reason}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      <Card className="mt-4">
        <CardHeader title="Fare cards" subtitle="Base fare + per km + per minute, with a minimum fare. GST of 5% is added on top." />
        <Table>
          <thead>
            <tr>
              <Th>Ride type</Th>
              <Th className="text-right">Base</Th>
              <Th className="text-right">Per km</Th>
              <Th className="text-right">Per min</Th>
              <Th className="text-right">Minimum</Th>
              <Th className="text-right">Booking fee</Th>
              <Th className="text-right">Cancel fee</Th>
              <Th className="text-right">Airport</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {fares.data?.results.map((f) => (
              <tr key={f.id}>
                <Td className="font-semibold">{f.ride_type}</Td>
                <Td className="text-right">{inr(f.base_fare)}</Td>
                <Td className="text-right">{inr(f.per_km)}</Td>
                <Td className="text-right">{inr(f.per_minute)}</Td>
                <Td className="text-right">{inr(f.minimum_fare)}</Td>
                <Td className="text-right">{inr(f.booking_fee)}</Td>
                <Td className="text-right">{inr(f.cancellation_fee)}</Td>
                <Td className="text-right">{inr(f.airport_fee)}</Td>
                <Td className="text-right">
                  {can("pricing.manage") && (
                    <Button size="sm" variant="ghost" onClick={() => setEditing(f)}>
                      Edit
                    </Button>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      <Modal
        open={overrideOpen}
        onClose={() => setOverrideOpen(false)}
        title="Manual surge"
        footer={
          <Button onClick={() => createOverride.mutate()} disabled={!override.zone || !override.reason.trim()} loading={createOverride.isPending}>
            Start surge
          </Button>
        }
      >
        <p className="mb-3 text-sm text-muted">For events the algorithm can't see coming: a concert letting out, heavy rain, a cricket match.</p>
        <Field label="Zone">
          <Select value={override.zone} onChange={(e) => setOverride((o) => ({ ...o, zone: e.target.value }))}>
            <option value="">Choose a zone</option>
            {cityInfo?.zones.map((z) => (
              <option key={z.id} value={z.id}>
                {z.name}
              </option>
            ))}
          </Select>
        </Field>
        <div className="mt-3 grid grid-cols-2 gap-3">
          <Field label="Multiplier">
            <Select value={override.multiplier} onChange={(e) => setOverride((o) => ({ ...o, multiplier: e.target.value }))}>
              {["1.2", "1.5", "1.8", "2.0", "2.5", "3.0"].map((m) => (
                <option key={m} value={m}>
                  {m}×
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Duration">
            <Select value={override.hours} onChange={(e) => setOverride((o) => ({ ...o, hours: e.target.value }))}>
              {["1", "2", "3", "6"].map((h) => (
                <option key={h} value={h}>
                  {h} hour{h === "1" ? "" : "s"}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Reason" className="mt-3">
          <Input value={override.reason} onChange={(e) => setOverride((o) => ({ ...o, reason: e.target.value }))} placeholder="IPL match at Chepauk" />
        </Field>
      </Modal>

      <Modal
        open={!!editing}
        onClose={() => setEditing(null)}
        title={`Edit ${editing?.ride_type} fare card`}
        footer={
          <Button onClick={() => editing && saveFare.mutate(editing)} loading={saveFare.isPending}>
            Save
          </Button>
        }
      >
        {editing && (
          <div className="grid grid-cols-2 gap-3">
            {(["base_fare", "per_km", "per_minute", "minimum_fare", "booking_fee", "cancellation_fee", "wait_per_minute", "airport_fee"] as const).map((key) => (
              <Field key={key} label={key.replace(/_/g, " ")}>
                <Input type="number" step="0.5" value={editing[key]} onChange={(e) => setEditing((r) => (r ? { ...r, [key]: e.target.value } : r))} />
              </Field>
            ))}
          </div>
        )}
      </Modal>
    </>
  );
}
