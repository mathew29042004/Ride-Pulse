/** Ops → Compliance: India's Motor Vehicle Aggregator Guidelines, state by state, with the
 * drivers and vehicles to fix. Check the limits against each state's notified rules. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Scale } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

interface Overview {
  state: string;
  drivers: number;
  ok: number;
  total: number;
  actions: string[];
}
interface Check {
  key: string;
  rule: string;
  status: "OK" | "WARN" | "ACTION";
  detail: string;
}
interface DriverRow {
  id: number;
  name: string;
  city: string;
  police_verified_on: string | null;
  induction_trained_on: string | null;
}
interface Report {
  state: string;
  drivers: number;
  checks: Check[];
  unverified: DriverRow[];
  untrained: DriverRow[];
  old_vehicles: { id: number; registration: string; name: string; year: number; driver: string }[];
}

const TONE = { OK: "brand", WARN: "warning", ACTION: "danger" } as const;
const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "Something went wrong.");

export default function OpsCompliance() {
  const qc = useQueryClient();
  const { can } = useAuth();
  const overview = useQuery({ queryKey: ["compliance"], queryFn: () => api.get<Overview[]>("ops/compliance/") });
  const [picked, setPicked] = useState<string | null>(null);
  const state = picked ?? overview.data?.[0]?.state ?? null;
  const report = useQuery({ queryKey: ["compliance", state], queryFn: () => api.get<Report>(`ops/compliance/states/${encodeURIComponent(state!)}/`), enabled: !!state });
  const refresh = () => qc.invalidateQueries({ queryKey: ["compliance"] });
  const police = useMutation({
    mutationFn: ({ id, reference }: { id: number; reference: string }) => api.post(`ops/compliance/drivers/${id}/police/`, { reference }),
    onSuccess: () => {
      toast.success("Police verification recorded");
      refresh();
    },
    onError: (e) => toast.error(errorText(e)),
  });
  const trained = useMutation({
    mutationFn: (id: number) => api.post(`ops/compliance/drivers/${id}/induction/`),
    onSuccess: () => {
      toast.success("Training recorded");
      refresh();
    },
    onError: (e) => toast.error(errorText(e)),
  });
  const r = report.data;
  const verify = can("drivers.verify");
  return (
    <>
      <PageHeader title="Compliance" subtitle="India's Motor Vehicle Aggregator Guidelines (2025), state by state. Surge and cancellation-fee caps are enforced when fares are charged; drivers without police verification or induction training can't go online. Check these limits against each state's notified rules." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {(overview.data ?? []).map((o) => (
          <button key={o.state} onClick={() => setPicked(o.state)} className={clsx("rounded-2xl border p-4 text-left", o.state === state ? "border-ink" : "border-line")}>
            <div className="flex items-center gap-2 font-semibold">
              <Scale className="size-4 text-muted" /> {o.state}
            </div>
            <div className={clsx("mt-1 text-2xl font-bold", o.ok === o.total ? "text-brand" : "text-amber-600")}>
              {o.ok}/{o.total}
            </div>
            <div className="text-xs text-muted">checks passing · {o.drivers} drivers</div>
          </button>
        ))}
      </div>
      {r && (
        <>
          <Card className="mt-4 p-4">
            <CardHeader title={`${r.state}: the rules`} />
            <div className="divide-y divide-line">
              {r.checks.map((c) => (
                <div key={c.key} className="flex items-start gap-3 py-2">
                  <Badge tone={TONE[c.status]}>{c.status === "OK" ? "OK" : c.status === "WARN" ? "Check" : "Action"}</Badge>
                  <div>
                    <div className="text-sm font-semibold">{c.rule}</div>
                    <div className="text-xs text-muted">{c.detail}</div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <Card className="p-4">
              <CardHeader title={`Police verification pending (${r.unverified.length})`} />
              {r.unverified.map((d) => (
                <div key={d.id} className="flex items-center justify-between border-t border-line py-1.5 text-sm first:border-0">
                  <span>
                    {d.name}
                    <span className="block text-xs text-muted">{d.city}</span>
                  </span>
                  {verify && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        const reference = window.prompt(`Police verification certificate number for ${d.name}`);
                        if (reference) police.mutate({ id: d.id, reference });
                      }}
                    >
                      Record
                    </Button>
                  )}
                </div>
              ))}
              {r.unverified.length === 0 && <p className="text-sm text-muted">All verified.</p>}
            </Card>
            <Card className="p-4">
              <CardHeader title={`Training or refresher due (${r.untrained.length})`} />
              {r.untrained.map((d) => (
                <div key={d.id} className="flex items-center justify-between border-t border-line py-1.5 text-sm first:border-0">
                  <span>
                    {d.name}
                    <span className="block text-xs text-muted">{d.induction_trained_on ? `last trained ${d.induction_trained_on}` : "never trained"}</span>
                  </span>
                  {verify && (
                    <Button size="sm" variant="outline" onClick={() => trained.mutate(d.id)}>
                      Trained
                    </Button>
                  )}
                </div>
              ))}
              {r.untrained.length === 0 && <p className="text-sm text-muted">Everyone is up to date.</p>}
            </Card>
            <Card className="p-4">
              <CardHeader title={`Vehicles over age (${r.old_vehicles.length})`} />
              {r.old_vehicles.map((v) => (
                <div key={v.id} className="border-t border-line py-1.5 text-sm first:border-0">
                  {v.registration} · {v.name} · {v.year}
                  <span className="block text-xs text-muted">{v.driver}: needs a newer vehicle</span>
                </div>
              ))}
              {r.old_vehicles.length === 0 && <p className="text-sm text-muted">All within the age limit.</p>}
            </Card>
          </div>
        </>
      )}
    </>
  );
}
