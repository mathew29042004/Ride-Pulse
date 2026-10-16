/**
 * Platform health: the transactional outbox (events waiting, lag), webhook endpoints with
 * retries and dead letters, and the security log (locked accounts, rate limits, top IPs).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Activity, Lock, Plus, RotateCcw, ShieldAlert, Unlock, Webhook } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, Field, Input, Modal, PageHeader, Stat, Table, Td, Th } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { ago } from "@/lib/format";

interface Health {
  outbox: { unpublished: number; lag_seconds: number; events_last_hour: number; by_topic_last_hour: Record<string, number>; deliveries: Record<string, number>; endpoints: number; disabled_endpoints: number };
  topics: Record<string, string>;
  security: {
    last_24h: Record<string, number>;
    locked: { email: string; until: string }[];
    top_ips: { ip: string; n: number }[];
    top_paths: { path: string; n: number }[];
    recent: { kind: string; label: string; email: string; ip: string | null; path: string; detail: string; at: string }[];
  };
  echo_received: { id: string; topic: string; at: string }[];
  jobs: { name: string; every_seconds: number; last_finished_at: string | null; last_duration_ms: number; last_ok: boolean; last_error: string; last_result: Record<string, unknown>; runs: number; failures: number; state: "OK" | "LATE" | "FAILING" }[];
  speed: {
    routes: { route: string; method: string; requests: number; avg_ms: number; p95_ms: number | null }[];
    requests: number;
    server_errors: number;
    threshold_ms: number;
    last_24h: number;
    by_route: { method: string; route: string; n: number; worst_ms: number; last: string }[];
  };
}
interface Endpoint {
  id: number;
  name: string;
  url: string;
  topics: string[];
  is_active: boolean;
  consecutive_failures: number;
  disabled_reason: string;
  delivered: number;
  failing: number;
  dead: number;
}

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "Something went wrong.");

export default function OpsPlatform() {
  const qc = useQueryClient();
  const health = useQuery({ queryKey: ["platform", "health"], queryFn: () => api.get<Health>("platform/health/"), refetchInterval: 10_000 });
  const endpoints = useQuery({ queryKey: ["platform", "webhooks"], queryFn: () => api.get<Endpoint[]>("platform/webhooks/"), refetchInterval: 15_000 });
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", url: "", topics: [] as string[] });
  const [secret, setSecret] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["platform"] });
  const create = useMutation({
    mutationFn: () => api.post<Endpoint & { secret: string }>("platform/webhooks/", form),
    onSuccess: (e) => {
      setSecret(e.secret);
      setAdding(false);
      setForm({ name: "", url: "", topics: [] });
      refresh();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const replay = useMutation({
    mutationFn: (id: number) => api.post<{ replayed: number }>(`platform/webhooks/${id}/replay/`),
    onSuccess: (r) => {
      toast.success(`${r.replayed} deliveries queued again`);
      refresh();
    },
  });
  const unlock = useMutation({
    mutationFn: (email: string) => api.post("platform/unlock/", { email }),
    onSuccess: () => {
      toast.success("Account unlocked");
      refresh();
    },
  });
  const h = health.data;
  const o = h?.outbox;
  const s = h?.security;
  return (
    <>
      <PageHeader title="Platform health" subtitle="Events are saved in the same transaction as the change (the outbox), then delivered to webhooks at least once, signed, with retries and a dead-letter queue. The security log shows lockouts and rate limits as they happen." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Events in the last hour" value={o?.events_last_hour ?? "—"} icon={<Activity className="size-4" />} tone="brand" />
        <Stat label="Waiting to publish" value={o?.unpublished ?? "—"} sub={o ? `oldest ${o.lag_seconds}s ago` : ""} tone={o && o.lag_seconds > 60 ? "danger" : "neutral"} />
        <Stat label="Webhook deliveries" value={o ? o.deliveries.DELIVERED ?? 0 : "—"} sub={o ? `${o.deliveries.RETRYING ?? 0} retrying · ${o.deliveries.DEAD ?? 0} dead` : ""} icon={<Webhook className="size-4" />} tone="info" />
        <Stat label="Accounts locked now" value={s?.locked.length ?? "—"} sub={s ? `${s.last_24h.LOGIN_FAILED ?? 0} wrong passwords · ${s.last_24h.THROTTLED ?? 0} rate limited (24 h)` : ""} icon={<ShieldAlert className="size-4" />} tone={s?.locked.length ? "warning" : "neutral"} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_340px]">
        <Card className="overflow-x-auto">
          <div className="p-4 pb-0">
            <CardHeader
              title="Webhook endpoints"
              action={
                <Button size="sm" icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>
                  Endpoint
                </Button>
              }
            />
          </div>
          <Table>
            <thead>
              <tr>
                <Th>Endpoint</Th>
                <Th className="text-right">Delivered</Th>
                <Th className="text-right">Retrying</Th>
                <Th className="text-right">Dead</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {(endpoints.data ?? []).map((e) => (
                <tr key={e.id} className="border-t border-line">
                  <Td>
                    <div className="flex items-center gap-2 font-semibold">
                      {e.name} {!e.is_active && <Badge tone="danger">Off</Badge>}
                    </div>
                    <div className="truncate text-xs text-muted">{e.url}</div>
                    <div className="text-xs text-muted">{e.topics.length ? e.topics.join(", ") : "every topic"}</div>
                    {e.disabled_reason && <div className="text-xs text-danger">{e.disabled_reason}</div>}
                  </Td>
                  <Td className="text-right">{e.delivered}</Td>
                  <Td className={clsx("text-right", e.failing > 0 && "text-amber-600")}>{e.failing}</Td>
                  <Td className={clsx("text-right", e.dead > 0 && "font-semibold text-danger")}>{e.dead}</Td>
                  <Td>
                    {(e.dead > 0 || !e.is_active) && (
                      <Button size="sm" variant="outline" icon={<RotateCcw className="size-3.5" />} onClick={() => replay.mutate(e.id)}>
                        Replay
                      </Button>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
        <Card className="p-4">
          <CardHeader title="Events by topic (last hour)" />
          {o &&
            Object.entries(h!.topics).map(([topic, label]) => (
              <div key={topic} className="flex justify-between py-1 text-sm">
                <span>
                  <code className="text-xs">{topic}</code>
                  <span className="block text-xs text-muted">{label}</span>
                </span>
                <span className="font-semibold">{o.by_topic_last_hour[topic] ?? 0}</span>
              </div>
            ))}
          {(h?.echo_received.length ?? 0) > 0 && (
            <>
              <div className="mt-3 text-xs font-semibold text-muted uppercase">Demo receiver got</div>
              {h!.echo_received.map((e) => (
                <div key={e.id} className="text-xs">
                  <code>{e.topic}</code> · {ago(e.at)}
                </div>
              ))}
            </>
          )}
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_340px]">
        <Card className="overflow-x-auto">
          <div className="p-4 pb-0">
            <CardHeader title="Security log" />
          </div>
          <Table>
            <thead>
              <tr>
                <Th>Event</Th>
                <Th>Who</Th>
                <Th>Where</Th>
                <Th>When</Th>
              </tr>
            </thead>
            <tbody>
              {(s?.recent ?? []).map((e, i) => (
                <tr key={i} className="border-t border-line">
                  <Td>
                    <Badge tone={e.kind === "LOCKED" ? "danger" : e.kind === "THROTTLED" ? "warning" : e.kind === "UNLOCKED" ? "brand" : "neutral"}>{e.label}</Badge>
                    {e.detail && <div className="mt-0.5 text-xs text-muted">{e.detail}</div>}
                  </Td>
                  <Td className="text-xs">
                    {e.email || "—"}
                    <div className="text-muted">{e.ip}</div>
                  </Td>
                  <Td className="text-xs">{e.path}</Td>
                  <Td className="text-xs">{ago(e.at)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {s && s.recent.length === 0 && <p className="p-6 text-center text-sm text-muted">Quiet. No failed logins or rate limits yet.</p>}
        </Card>
        <Card className="p-4">
          <CardHeader title="Locked accounts" />
          {(s?.locked ?? []).length === 0 && <p className="text-sm text-muted">None.</p>}
          {(s?.locked ?? []).map((l) => (
            <div key={l.email} className="flex items-center gap-2 py-1.5 text-sm">
              <Lock className="size-4 text-danger" />
              <span className="min-w-0 flex-1 truncate">{l.email}</span>
              <Button size="sm" variant="outline" icon={<Unlock className="size-3.5" />} onClick={() => unlock.mutate(l.email)}>
                Unlock
              </Button>
            </div>
          ))}
          {(s?.top_ips.length ?? 0) > 0 && (
            <>
              <div className="mt-4 text-xs font-semibold text-muted uppercase">Noisiest IPs (24 h)</div>
              {s!.top_ips.map((ip) => (
                <div key={ip.ip} className="flex justify-between text-xs">
                  <code>{ip.ip}</code>
                  <span>{ip.n}</span>
                </div>
              ))}
            </>
          )}
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card className="overflow-x-auto">
          <div className="p-4 pb-0">
            <CardHeader title="Background jobs" subtitle="Every scheduled job records each run. Late: it missed three of its runs. Failing: its last run raised an error." />
          </div>
          <Table>
            <thead>
              <tr>
                <Th>Job</Th>
                <Th>Last run</Th>
                <Th className="text-right">Took</Th>
                <Th className="text-right">Runs</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {(h?.jobs ?? []).map((j) => (
                <tr key={j.name} className="border-t border-line">
                  <Td>
                    <div className="font-semibold">{j.name}</div>
                    <div className="text-xs text-muted">
                      every {j.every_seconds >= 86400 ? `${j.every_seconds / 86400} d` : j.every_seconds >= 3600 ? `${j.every_seconds / 3600} h` : j.every_seconds >= 60 ? `${j.every_seconds / 60} min` : `${j.every_seconds} s`}
                      {j.last_error ? ` · ${j.last_error}` : Object.keys(j.last_result).length ? ` · ${Object.entries(j.last_result).map(([k, v]) => `${k} ${v}`).join(", ")}` : ""}
                    </div>
                  </Td>
                  <Td className="whitespace-nowrap text-xs">{j.last_finished_at ? ago(j.last_finished_at) : "never"}</Td>
                  <Td className="text-right text-xs">{j.last_duration_ms} ms</Td>
                  <Td className="text-right text-xs">
                    {j.runs.toLocaleString("en-IN")}
                    {j.failures > 0 && <span className="text-danger"> · {j.failures} failed</span>}
                  </Td>
                  <Td>
                    <Badge tone={j.state === "OK" ? "brand" : j.state === "LATE" ? "warning" : "danger"}>{j.state === "OK" ? "OK" : j.state === "LATE" ? "Late" : "Failing"}</Badge>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {h?.jobs.length === 0 && <p className="p-4 text-sm text-muted">No job has run yet. Start the simulator or Celery beat.</p>}
        </Card>
        <Card className="overflow-x-auto">
          <div className="p-4 pb-0">
            <CardHeader
              title="Speed"
              subtitle={h ? `Slowest routes since this server started (${h.speed.requests.toLocaleString("en-IN")} requests, ${h.speed.server_errors} server errors). Requests over ${h.speed.threshold_ms} ms are logged; ${h.speed.last_24h} in the last 24 h.` : ""}
            />
          </div>
          <Table>
            <thead>
              <tr>
                <Th>Route</Th>
                <Th className="text-right">Requests</Th>
                <Th className="text-right">Average</Th>
                <Th className="text-right">p95</Th>
              </tr>
            </thead>
            <tbody>
              {(h?.speed.routes ?? []).map((r) => (
                <tr key={`${r.method} ${r.route}`} className="border-t border-line">
                  <Td className="text-xs">
                    <span className="font-mono text-muted">{r.method}</span> {r.route}
                  </Td>
                  <Td className="text-right text-xs">{r.requests}</Td>
                  <Td className="text-right text-xs">{r.avg_ms} ms</Td>
                  <Td className={clsx("text-right text-xs", (r.p95_ms ?? 0) >= (h?.speed.threshold_ms ?? 500) && "font-semibold text-danger")}>{r.p95_ms != null ? `≤ ${r.p95_ms} ms` : "> 10 s"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {(h?.speed.by_route ?? []).length > 0 && (
            <div className="border-t border-line p-4 text-xs">
              <div className="mb-1 font-semibold">Slow requests, last 24 h</div>
              {h!.speed.by_route.map((r) => (
                <div key={`${r.method} ${r.route}`} className="flex justify-between py-0.5">
                  <span>
                    <span className="font-mono text-muted">{r.method}</span> {r.route}
                  </span>
                  <span>
                    {r.n}× · worst {r.worst_ms} ms · {ago(r.last)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Modal open={adding} onClose={() => setAdding(false)} title="New webhook endpoint" footer={<Button block loading={create.isPending} disabled={!form.name || !form.url} onClick={() => create.mutate()}>Create</Button>}>
        <Field label="Name">
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Acme travel desk" />
        </Field>
        <Field label="URL (HTTPS)" className="mt-3">
          <Input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://partner.example.com/ride-pulse" />
        </Field>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {Object.keys(h?.topics ?? {}).map((topic) => (
            <button key={topic} onClick={() => setForm({ ...form, topics: form.topics.includes(topic) ? form.topics.filter((x) => x !== topic) : [...form.topics, topic] })} className={clsx("rounded-full border px-2.5 py-1 text-xs font-semibold", form.topics.includes(topic) ? "border-fg bg-ink text-ink-fg" : "border-line text-muted")}>
              {topic}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted">No topics selected = every topic. Each request carries X-RidePulse-Signature (HMAC-SHA256 of the body) and X-RidePulse-Event (for de-duplication).</p>
      </Modal>
      <Modal open={!!secret} onClose={() => setSecret(null)} title="Signing secret" footer={<Button block onClick={() => setSecret(null)}>I've saved it</Button>}>
        <p className="text-sm">Copy this now. It won't be shown again.</p>
        <code className="mt-2 block rounded-xl bg-surface-2 p-3 text-xs break-all">{secret}</code>
      </Modal>
    </>
  );
}
