/**
 * Models & experiments: feature flags (rollout and kill switch), A/B tests with their statistics,
 * model cards for the trained ETA and churn models, riders at risk with a win-back offer, and the
 * surge optimiser that turns its recommendation into a draft test.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, FlaskConical, Play, Send, Square, ToggleLeft, TrendingUp } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, Input, PageHeader, Stat, Table, Td, Th } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import { ago } from "@/lib/format";

interface Flag {
  key: string;
  description: string;
  enabled: boolean;
  rollout_percent: number;
  updated_at: string;
}
interface VariantRow {
  exposures: number;
  people: number;
  conversions: number;
  completed: number;
  conversion_rate: number | null;
  revenue: string;
  revenue_per_exposure: number;
}
interface Experiment {
  key: string;
  name: string;
  hypothesis: string;
  status: "DRAFT" | "RUNNING" | "STOPPED";
  treatment_percent: number;
  treatment_config: Record<string, unknown>;
  started_at: string | null;
  decision: string;
  results: {
    control: VariantRow;
    treatment: VariantRow;
    conversion_test: { diff: number | null; p_value: number | null; ci: [number, number] | null };
    sample_ratio: { mismatch: boolean };
    needed_per_variant: number;
    verdict: string;
  };
}
interface Card_ {
  trained_at: string | null;
  kind: string;
  target: string;
  metrics: Record<string, unknown>;
}
interface Models {
  cards: { eta: Card_ | null; churn: Card_ | null };
  at_risk: { rider_id: number; name: string; probability: number; days_since_last: number; trips_56d: number; failed_56d: number; can_message: boolean }[];
}
interface Policy {
  elasticity: string;
  cap: string;
  completed: number;
  revenue: number;
  unserved: number;
  surge_share: number;
}
interface SurgePolicy {
  snapshots: number;
  current?: Policy;
  recommended: Policy | null;
  uplift_completed?: number;
  uplift_revenue?: number;
  policies: Policy[];
  model?: { rider_response: string; driver_response: string };
}

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "Something went wrong.");
const pct = (v: number | null | undefined, digits = 1) => (v == null ? "—" : `${(v * 100).toFixed(digits)}%`);
const signed = (v: number | null | undefined) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);

export default function OpsModels() {
  const qc = useQueryClient();
  const { can } = useAuth();
  const manage = can("experiments.manage");
  const overview = useQuery({
    queryKey: ["experiments"],
    queryFn: () => api.get<{ flags: Flag[]; experiments: Experiment[] }>("ops/experiments/overview/"),
    enabled: manage,
    refetchInterval: 30_000,
  });
  const models = useQuery({ queryKey: ["intel", "models"], queryFn: () => api.get<Models>("intel/models/") });
  const surge = useQuery({ queryKey: ["intel", "surge-policy"], queryFn: () => api.get<SurgePolicy>("intel/surge-policy/"), enabled: can("pricing.view") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["experiments"] });

  const setFlag = useMutation({
    mutationFn: ({ key, ...body }: { key: string; enabled?: boolean; rollout_percent?: number }) => api.post(`ops/experiments/flags/${key}/`, body),
    onSuccess: refresh,
    onError: (err) => toast.error(errorText(err)),
  });
  const start = useMutation({
    mutationFn: (key: string) => api.post(`ops/experiments/${key}/start/`),
    onSuccess: () => {
      toast.success("Experiment started");
      refresh();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const stop = useMutation({
    mutationFn: ({ key, decision }: { key: string; decision: string }) => api.post(`ops/experiments/${key}/stop/`, { decision }),
    onSuccess: () => {
      toast.success("Experiment stopped");
      refresh();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const propose = useMutation({
    mutationFn: () => api.post<{ experiment: string | null }>("intel/surge-policy/"),
    onSuccess: (r) => {
      toast.success(r.experiment ? `Draft test "${r.experiment}" ready to start` : "Nothing to propose yet");
      refresh();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const [picked, setPicked] = useState<number[]>([]);
  const [offer, setOffer] = useState({ title: "We miss you", body: "20% off your next ride this week." });
  const winBack = useMutation({
    mutationFn: () => api.post<{ sent: number }>("intel/win_back/", { rider_ids: picked, ...offer }),
    onSuccess: (r) => {
      toast.success(`Offer sent to ${r.sent} riders (only those who opted in)`);
      setPicked([]);
    },
    onError: (err) => toast.error(errorText(err)),
  });

  const eta = models.data?.cards.eta;
  const churn = models.data?.cards.churn;
  const etaM = (eta?.metrics ?? {}) as Record<string, number & unknown>;
  const churnM = (churn?.metrics ?? {}) as Record<string, number & unknown>;
  const s = surge.data;
  const running = overview.data?.experiments.filter((e) => e.status === "RUNNING").length ?? 0;

  return (
    <>
      <PageHeader title="Models & experiments" subtitle="Trained in the data platform, served here in plain Python. Every change to riders goes through a flag or an A/B test, read with proper statistics before anyone decides." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="ETA model error" value={eta ? `${etaM.model_mae_min} min` : "Not trained"} sub={eta ? `app estimate alone: ${etaM.baseline_mae_min} min (${pct(etaM.improvement as number, 0)} better)` : "run the data pipeline"} icon={<Brain className="size-4" />} tone="brand" />
        <Stat label="Churn model AUC" value={churn ? String(churnM.auc ?? "—") : "Not trained"} sub={churn ? `recency alone: ${churnM.recency_only_auc ?? "—"}` : ""} icon={<TrendingUp className="size-4" />} tone="info" />
        <Stat label="Experiments running" value={manage ? running : "—"} icon={<FlaskConical className="size-4" />} tone="neutral" />
        <Stat label="Surge policy uplift" value={s?.recommended ? signed(s.uplift_completed) : "—"} sub={s?.recommended ? `trips, at ${s.recommended.cap}x cap · revenue ${signed(s.uplift_revenue)}` : "needs surge history"} tone="warning" />
      </div>

      {manage && (
        <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_360px]">
          <Card className="p-4">
            <CardHeader title="A/B tests" />
            <div className="space-y-4">
              {(overview.data?.experiments ?? []).map((e) => {
                const r = e.results;
                const ct = r.conversion_test;
                return (
                  <div key={e.key} className="rounded-lg border border-line p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold">{e.name}</span>
                      <Badge tone={e.status === "RUNNING" ? "brand" : e.status === "DRAFT" ? "neutral" : "dark"}>{e.status}</Badge>
                      <span className="text-xs text-muted">{e.key} · {JSON.stringify(e.treatment_config)}</span>
                      <span className="ml-auto flex gap-2">
                        {e.status === "DRAFT" && (
                          <Button size="sm" icon={<Play className="size-4" />} onClick={() => start.mutate(e.key)}>
                            Start
                          </Button>
                        )}
                        {e.status === "RUNNING" && (
                          <Button
                            size="sm"
                            variant="outline"
                            icon={<Square className="size-4" />}
                            onClick={() => {
                              const decision = window.prompt("Decision (what we do next and why)?", r.verdict);
                              if (decision) stop.mutate({ key: e.key, decision });
                            }}
                          >
                            Stop
                          </Button>
                        )}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-muted">{e.hypothesis}</p>
                    <Table>
                      <thead>
                        <tr>
                          <Th>Variant</Th>
                          <Th className="text-right">Exposures</Th>
                          <Th className="text-right">Booked</Th>
                          <Th className="text-right">Conversion</Th>
                          <Th className="text-right">₹ / exposure</Th>
                        </tr>
                      </thead>
                      <tbody>
                        {(["control", "treatment"] as const).map((v) => (
                          <tr key={v} className="border-t border-line">
                            <Td>{v === "control" ? "A · control" : `B · treatment (${e.treatment_percent}%)`}</Td>
                            <Td className="text-right">{r[v].exposures}</Td>
                            <Td className="text-right">{r[v].conversions}</Td>
                            <Td className="text-right">{pct(r[v].conversion_rate)}</Td>
                            <Td className="text-right">{r[v].revenue_per_exposure.toFixed(2)}</Td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                    <div className="mt-2 text-sm">
                      Difference {signed(ct.diff)}
                      {ct.ci && ` (95% CI ${signed(ct.ci[0])} to ${signed(ct.ci[1])})`}, p = {ct.p_value == null ? "—" : ct.p_value.toFixed(3)} · needs {r.needed_per_variant} per variant
                    </div>
                    <div className={r.sample_ratio.mismatch ? "text-sm font-semibold text-danger" : "text-sm font-semibold"}>{e.decision || r.verdict}</div>
                  </div>
                );
              })}
              {overview.data?.experiments.length === 0 && <p className="text-sm text-muted">No experiments yet. Propose one from the surge optimiser below.</p>}
            </div>
          </Card>

          <Card className="p-4">
            <CardHeader title="Feature flags" />
            <div className="space-y-3">
              {(overview.data?.flags ?? []).map((f) => (
                <div key={f.key} className="rounded-lg border border-line p-3">
                  <div className="flex items-center gap-2">
                    <ToggleLeft className="size-4 text-muted" />
                    <span className="font-semibold">{f.key}</span>
                    <Button size="sm" variant={f.enabled ? "outline" : "primary"} className="ml-auto" onClick={() => setFlag.mutate({ key: f.key, enabled: !f.enabled })}>
                      {f.enabled ? "Turn off" : "Turn on"}
                    </Button>
                  </div>
                  <p className="text-xs text-muted">{f.description}</p>
                  <label className="mt-2 flex items-center gap-2 text-xs">
                    Rollout
                    <input
                      type="range"
                      min={0}
                      max={100}
                      step={5}
                      defaultValue={f.rollout_percent}
                      disabled={!f.enabled}
                      onMouseUp={(ev) => setFlag.mutate({ key: f.key, rollout_percent: Number((ev.target as HTMLInputElement).value) })}
                      onKeyUp={(ev) => setFlag.mutate({ key: f.key, rollout_percent: Number((ev.target as HTMLInputElement).value) })}
                      className="flex-1"
                    />
                    <span className="w-10 text-right">{f.enabled ? `${f.rollout_percent}%` : "off"}</span>
                  </label>
                  <div className="text-xs text-muted">changed {ago(f.updated_at)}</div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {[
          { name: "ETA", card: eta, rows: eta && [["Predicts", eta.target], ["Test rides", etaM.test_rows], ["Error (MAE)", `${etaM.model_mae_min} min vs ${etaM.baseline_mae_min} min`], ["Error (MAPE)", `${pct(etaM.model_mape as number)} vs ${pct(etaM.baseline_mape as number)}`], ["Strongest signals", ((etaM.top_features as unknown as [string, number][]) ?? []).slice(0, 5).map(([n]) => n).join(", ")]] },
          { name: "Rider churn", card: churn, rows: churn && [["Predicts", churn.target], ["Test riders", `${churnM.test_rows} (snapshot ${churnM.test_cutoff})`], ["Churn rate", pct(churnM.churn_rate as number)], ["AUC", `${churnM.auc} (recency alone ${churnM.recency_only_auc})`]] },
        ].map(({ name, card, rows }) => (
          <Card key={name} className="p-4">
            <CardHeader title={`Model card · ${name}`} />
            {card && rows ? (
              <dl className="grid grid-cols-[140px_1fr] gap-y-1 text-sm">
                {rows.map(([k, v]) => (
                  <div key={String(k)} className="contents">
                    <dt className="text-muted">{String(k)}</dt>
                    <dd>{String(v ?? "—")}</dd>
                  </div>
                ))}
                <dt className="text-muted">Trained</dt>
                <dd>{card.trained_at ? ago(card.trained_at) : "—"} · {card.kind.replaceAll("_", " ")}</dd>
              </dl>
            ) : (
              <p className="text-sm text-muted">Not trained yet. Run the data pipeline (make data-run) to train and export it.</p>
            )}
          </Card>
        ))}
      </div>

      <Card className="mt-4 overflow-x-auto">
        <div className="p-4 pb-0">
          <CardHeader
            title="Riders at risk of churning"
            action={
              can("promos.manage") && (
                <Button size="sm" icon={<Send className="size-4" />} disabled={!picked.length || winBack.isPending} onClick={() => winBack.mutate()}>
                  Send offer ({picked.length})
                </Button>
              )
            }
          />
          {can("promos.manage") && (
            <div className="mb-3 grid gap-2 sm:grid-cols-[200px_1fr]">
              <Input value={offer.title} onChange={(e) => setOffer({ ...offer, title: e.target.value })} aria-label="Offer title" />
              <Input value={offer.body} onChange={(e) => setOffer({ ...offer, body: e.target.value })} aria-label="Offer message" />
            </div>
          )}
        </div>
        <Table>
          <thead>
            <tr>
              <Th />
              <Th>Rider</Th>
              <Th className="text-right">Churn chance</Th>
              <Th className="text-right">Days since last</Th>
              <Th className="text-right">Trips (56 d)</Th>
              <Th className="text-right">Failed</Th>
            </tr>
          </thead>
          <tbody>
            {(models.data?.at_risk ?? []).map((r) => (
              <tr key={r.rider_id} className="border-t border-line">
                <Td>
                  <input
                    type="checkbox"
                    aria-label={`Select ${r.name}`}
                    disabled={!r.can_message}
                    title={r.can_message ? "" : "Not opted in to offers"}
                    checked={picked.includes(r.rider_id)}
                    onChange={(e) => setPicked(e.target.checked ? [...picked, r.rider_id] : picked.filter((id) => id !== r.rider_id))}
                  />
                </Td>
                <Td>
                  {r.name} {!r.can_message && <Badge>no consent</Badge>}
                </Td>
                <Td className="text-right font-semibold">{pct(r.probability, 0)}</Td>
                <Td className="text-right">{r.days_since_last}</Td>
                <Td className="text-right">{r.trips_56d}</Td>
                <Td className="text-right">{r.failed_56d}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      {s && (
        <Card className="mt-4 overflow-x-auto">
          <div className="p-4 pb-0">
            <CardHeader
              title="Surge optimiser"
              action={
                manage && s.recommended && (
                  <Button size="sm" icon={<FlaskConical className="size-4" />} onClick={() => propose.mutate()}>
                    Propose A/B test
                  </Button>
                )
              }
            />
            <p className="mb-3 text-sm text-muted">
              Replays {s.snapshots} recorded zone snapshots under each policy. Riders: {s.model?.rider_response}. Drivers: {s.model?.driver_response}. A model of the market, not the market: test before switching.
            </p>
          </div>
          <Table>
            <thead>
              <tr>
                <Th>Elasticity</Th>
                <Th>Cap</Th>
                <Th className="text-right">Completed</Th>
                <Th className="text-right">Revenue (₹)</Th>
                <Th className="text-right">Unserved</Th>
                <Th className="text-right">Time in surge</Th>
              </tr>
            </thead>
            <tbody>
              {[...(s.current ? [{ ...s.current, label: "today" }] : []), ...s.policies.map((p, i) => ({ ...p, label: i === 0 ? "best" : "" }))].map((p, i) => (
                <tr key={i} className="border-t border-line">
                  <Td>
                    {p.elasticity} {p.label && <Badge tone={p.label === "best" ? "brand" : "neutral"}>{p.label}</Badge>}
                  </Td>
                  <Td>{p.cap}x</Td>
                  <Td className="text-right">{p.completed.toLocaleString("en-IN")}</Td>
                  <Td className="text-right">{p.revenue.toLocaleString("en-IN")}</Td>
                  <Td className="text-right">{p.unserved.toLocaleString("en-IN")}</Td>
                  <Td className="text-right">{pct(p.surge_share, 0)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
    </>
  );
}
