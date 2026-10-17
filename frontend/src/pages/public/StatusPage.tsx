/** The public status page: every part of Ride Pulse, open incidents and the last 14 days. */

import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { CheckCircle2 } from "lucide-react";

import { Logo } from "@/components/Logo";
import { request } from "@/lib/api";

interface Incident {
  number: string;
  title: string;
  status_label: string;
  message: string;
  started_at: string;
  resolved_at: string | null;
  updates: { status: string; message: string; at: string }[];
}
interface Status {
  overall: string;
  components: { key: string; label: string; state: string }[];
  open: Incident[];
  recent: Incident[];
}

const LABEL: Record<string, string> = { OPERATIONAL: "Operational", DEGRADED: "Degraded", PARTIAL: "Partial outage", OUTAGE: "Outage" };
const DOT: Record<string, string> = { OPERATIONAL: "bg-brand", DEGRADED: "bg-amber-400", PARTIAL: "bg-orange-500", OUTAGE: "bg-danger" };
const when = (iso: string) => new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

export default function StatusPage() {
  const q = useQuery({ queryKey: ["status", "public"], queryFn: () => request<Status>("/api/v1/status/", { headers: { Authorization: "" } }), refetchInterval: 30_000 });
  const s = q.data;
  return (
    <div className="mx-auto min-h-dvh max-w-2xl bg-surface px-4 py-8">
      <Logo />
      <h1 className="mt-6 text-2xl font-bold">Ride Pulse status</h1>
      {s && (
        <>
          <div className={clsx("mt-4 flex items-center gap-2 rounded-2xl p-4 font-semibold", s.overall === "OPERATIONAL" ? "bg-brand/15 text-brand" : "bg-amber-500/15 text-amber-800 dark:text-amber-300")}>
            {s.overall === "OPERATIONAL" ? <CheckCircle2 className="size-5" /> : <span className={clsx("size-3 rounded-full", DOT[s.overall])} />}
            {s.overall === "OPERATIONAL" ? "All systems operational" : "Some services are affected"}
          </div>
          {s.open.map((i) => (
            <div key={i.number} className="mt-4 rounded-2xl border border-amber-500/50 p-4">
              <div className="font-semibold">{i.title}</div>
              <div className="text-sm">{i.message}</div>
              {[...i.updates].reverse().map((u, k) => (
                <div key={k} className="mt-2 border-t border-line pt-2 text-xs">
                  <b>{u.status}</b> · {when(u.at)}: {u.message}
                </div>
              ))}
            </div>
          ))}
          <div className="mt-4 divide-y divide-line rounded-2xl border border-line">
            {s.components.map((c) => (
              <div key={c.key} className="flex items-center justify-between px-4 py-3 text-sm">
                {c.label}
                <span className="flex items-center gap-2 text-xs">
                  <span className={clsx("size-2.5 rounded-full", DOT[c.state])} /> {LABEL[c.state]}
                </span>
              </div>
            ))}
          </div>
          <h2 className="mt-6 font-semibold">Past 14 days</h2>
          {s.recent.length === 0 && <p className="mt-1 text-sm text-muted">No incidents.</p>}
          {s.recent.map((i) => (
            <div key={i.number} className="mt-2 text-sm">
              <b>{i.title}</b>
              <span className="block text-xs text-muted">
                {when(i.started_at)} – {i.resolved_at && when(i.resolved_at)} · resolved
              </span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
